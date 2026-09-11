import threading
import time
from types import SimpleNamespace

import pytest

from app.api.history import normalize_history_details
from app.models.session import InputSummary
from app.services import mapper_service
from app.storage import session_store


class _FakeMappingResult:
    def __init__(self, source_term: str):
        self.target_code = f"LOINC:{source_term}"
        self.target_term = source_term
        self.ontology = "LOINC"
        self.confidence = 0.9
        self.logic_type = "llm"
        self.alternatives = []
        self.notes = None


@pytest.fixture(autouse=True)
def clear_batch_jobs():
    mapper_service._batch_jobs.clear()
    yield
    mapper_service._batch_jobs.clear()


def _patch_batch_environment(monkeypatch, mapper_cls):
    threads: list[threading.Thread] = []
    real_thread = threading.Thread

    class _TrackingThread:
        def __init__(self, *, target, daemon):
            self._thread = real_thread(target=target, daemon=daemon)

        def start(self):
            threads.append(self._thread)
            self._thread.start()

    monkeypatch.setattr(mapper_service, "_validate_config", lambda: None)
    monkeypatch.setattr(
        mapper_service,
        "load_config",
        lambda: SimpleNamespace(provider="ollama", model="fake-model", retrieval_mode="public"),
    )
    monkeypatch.setattr(
        mapper_service,
        "_build_mapper_kwargs",
        lambda _config, *, ontologies=None: ({}, None),
    )
    monkeypatch.setattr("llm_ontology_mapper.OntologyMapper", mapper_cls)
    monkeypatch.setattr(mapper_service.threading, "Thread", _TrackingThread)
    return threads


def _start_job(records: list[dict[str, str]]) -> str:
    return mapper_service.start_batch_job(
        records=records,
        column_map={"field_name": "field_name"},
        clinical_area=None,
        target_ontologies=None,
        auto_accept_threshold=0.85,
    )


def _join_threads(threads: list[threading.Thread]) -> None:
    for thread in threads:
        thread.join(timeout=2)
        assert not thread.is_alive()


def _wait_until(predicate) -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached before timeout")


def _use_temp_session_store(monkeypatch, tmp_path):
    session_dir = tmp_path / "session_logs"
    monkeypatch.setattr(session_store, "_SESSION_DIR", session_dir)
    monkeypatch.setattr(session_store, "_INDEX_FILE", session_dir / "index.json")


def test_interrupted_partial_batch_is_persisted_to_history(monkeypatch, tmp_path):
    _use_temp_session_store(monkeypatch, tmp_path)
    session_id = session_store.create_session(
        "batch_map",
        InputSummary(filename="dictionary.csv", row_count=3),
    )
    second_in_flight = threading.Event()
    release_second = threading.Event()

    class _Mapper:
        def map_term(self, **kwargs):
            source_term = kwargs["source_term"]
            if source_term == "second":
                second_in_flight.set()
                assert release_second.wait(timeout=2)
            return _FakeMappingResult(source_term)

    threads = _patch_batch_environment(monkeypatch, _Mapper)

    job_id = mapper_service.start_batch_job(
        records=[
            {"field_name": "first"},
            {"field_name": "second"},
            {"field_name": "third"},
        ],
        column_map={"field_name": "field_name"},
        clinical_area=None,
        target_ontologies=None,
        auto_accept_threshold=0.85,
        session_id=session_id,
    )
    assert second_in_flight.wait(timeout=2)

    assert mapper_service.cancel_batch_job(job_id) is True
    release_second.set()
    _join_threads(threads)

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "interrupted"
    assert job["completed"] == 1
    assert [row.field_name for row in job["results"]] == ["first"]

    record = session_store.get_session(session_id)
    assert record.status == "interrupted"
    assert record.result_snapshot is not None
    assert record.result_snapshot["status"] == "interrupted"
    assert record.result_snapshot["total"] == 3
    assert record.result_snapshot["completed"] == 1
    assert len(record.result_snapshot["results"]) == 1
    assert record.result_snapshot["results"][0]["field_name"] == "first"

    detail = normalize_history_details(record)
    assert detail.status == "interrupted"
    assert detail.result.status == "interrupted"
    assert detail.result.completed == 1
    assert detail.result.total == 3
    assert [row.field_name for row in detail.result.rows] == ["first"]


def test_done_batch_is_persisted_to_history_without_frontend_polling(monkeypatch, tmp_path):
    _use_temp_session_store(monkeypatch, tmp_path)
    session_id = session_store.create_session(
        "batch_map",
        InputSummary(filename="dictionary.csv", row_count=2),
    )

    class _Mapper:
        def map_term(self, **kwargs):
            return _FakeMappingResult(kwargs["source_term"])

    threads = _patch_batch_environment(monkeypatch, _Mapper)

    job_id = mapper_service.start_batch_job(
        records=[
            {"field_name": "first"},
            {"field_name": "second"},
        ],
        column_map={"field_name": "field_name"},
        clinical_area=None,
        target_ontologies=None,
        auto_accept_threshold=0.85,
        session_id=session_id,
    )
    _join_threads(threads)

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "done"
    assert job["completed"] == 2

    record = session_store.get_session(session_id)
    assert record.status == "complete"
    assert record.result_snapshot is not None
    assert record.result_snapshot["job_id"] == job_id
    assert record.result_snapshot["status"] == "done"
    assert record.result_snapshot["total"] == 2
    assert record.result_snapshot["completed"] == 2
    assert len(record.result_snapshot["results"]) == 2
    assert [row["field_name"] for row in record.result_snapshot["results"]] == [
        "first",
        "second",
    ]

    detail = normalize_history_details(record)
    assert detail.status == "complete"
    assert detail.result.status == "done"
    assert detail.result.completed == 2
    assert detail.result.total == 2
    assert [row.field_name for row in detail.result.rows] == ["first", "second"]


def test_failed_batch_is_persisted_to_history_without_frontend_polling(monkeypatch, tmp_path):
    _use_temp_session_store(monkeypatch, tmp_path)
    session_id = session_store.create_session(
        "batch_map",
        InputSummary(filename="dictionary.csv", row_count=1),
    )

    def fail_build_mapper_kwargs(_config, *, ontologies=None):
        raise ValueError("mapper setup failed")

    threads = _patch_batch_environment(monkeypatch, object)
    monkeypatch.setattr(mapper_service, "_build_mapper_kwargs", fail_build_mapper_kwargs)

    job_id = mapper_service.start_batch_job(
        records=[{"field_name": "first"}],
        column_map={"field_name": "field_name"},
        clinical_area=None,
        target_ontologies=None,
        auto_accept_threshold=0.85,
        session_id=session_id,
    )
    _join_threads(threads)

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "failed"
    assert job["error"] == "mapper setup failed"
    assert job["completed"] == 0
    assert job["results"] == []

    record = session_store.get_session(session_id)
    assert record.status == "error"
    assert record.result_snapshot is not None
    assert record.result_snapshot["job_id"] == job_id
    assert record.result_snapshot["status"] == "failed"
    assert record.result_snapshot["error"] == "mapper setup failed"
    assert record.result_snapshot["total"] == 1
    assert record.result_snapshot["completed"] == 0
    assert record.result_snapshot["results"] == []

    detail = normalize_history_details(record)
    assert detail.status == "error"
    assert detail.failure is not None
    assert detail.failure.message == "mapper setup failed"


def test_missing_history_association_does_not_break_interrupted_batch(monkeypatch):
    second_in_flight = threading.Event()
    release_second = threading.Event()

    class _Mapper:
        def map_term(self, **kwargs):
            source_term = kwargs["source_term"]
            if source_term == "second":
                second_in_flight.set()
                assert release_second.wait(timeout=2)
            return _FakeMappingResult(source_term)

    threads = _patch_batch_environment(monkeypatch, _Mapper)

    job_id = _start_job([
        {"field_name": "first"},
        {"field_name": "second"},
    ])
    assert second_in_flight.wait(timeout=2)

    assert mapper_service.cancel_batch_job(job_id) is True
    release_second.set()
    _join_threads(threads)

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "interrupted"
    assert job["completed"] == 1
    assert [row.field_name for row in job["results"]] == ["first"]


def test_invalid_history_association_is_logged_and_non_fatal(monkeypatch, tmp_path, caplog):
    _use_temp_session_store(monkeypatch, tmp_path)
    second_in_flight = threading.Event()
    release_second = threading.Event()

    class _Mapper:
        def map_term(self, **kwargs):
            source_term = kwargs["source_term"]
            if source_term == "second":
                second_in_flight.set()
                assert release_second.wait(timeout=2)
            return _FakeMappingResult(source_term)

    threads = _patch_batch_environment(monkeypatch, _Mapper)
    caplog.set_level("WARNING", logger=mapper_service.__name__)

    job_id = mapper_service.start_batch_job(
        records=[
            {"field_name": "first"},
            {"field_name": "second"},
        ],
        column_map={"field_name": "field_name"},
        clinical_area=None,
        target_ontologies=None,
        auto_accept_threshold=0.85,
        session_id="missing-session",
    )
    assert second_in_flight.wait(timeout=2)

    assert mapper_service.cancel_batch_job(job_id) is True
    release_second.set()
    _join_threads(threads)

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "interrupted"
    assert job["completed"] == 1
    assert "session missing-session was not found" in caplog.text


def test_cancel_before_first_row_prevents_mapping(monkeypatch):
    mapper_init_entered = threading.Event()
    release_mapper_init = threading.Event()
    mapped_terms: list[str] = []

    class _Mapper:
        def __init__(self, **_kwargs):
            mapper_init_entered.set()
            assert release_mapper_init.wait(timeout=2)

        def map_term(self, **kwargs):
            mapped_terms.append(kwargs["source_term"])
            return _FakeMappingResult(kwargs["source_term"])

    threads = _patch_batch_environment(monkeypatch, _Mapper)

    job_id = _start_job([{"field_name": "first"}])
    assert mapper_init_entered.wait(timeout=2)

    assert mapper_service.cancel_batch_job(job_id) is True
    release_mapper_init.set()
    _join_threads(threads)

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "interrupted"
    assert job["completed"] == 0
    assert job["results"] == []
    assert mapped_terms == []


def test_cancel_between_rows_preserves_completed_results_and_skips_next_map(monkeypatch):
    before_second_map = threading.Event()
    release_second_checkpoint = threading.Event()
    mapped_terms: list[str] = []

    class _Mapper:
        def map_term(self, **kwargs):
            mapped_terms.append(kwargs["source_term"])
            return _FakeMappingResult(kwargs["source_term"])

    original_json_safe_row = mapper_service._json_safe_original_row

    def guarded_json_safe_row(rec):
        if rec.get("field_name") == "second":
            before_second_map.set()
            assert release_second_checkpoint.wait(timeout=2)
        return original_json_safe_row(rec)

    monkeypatch.setattr(mapper_service, "_json_safe_original_row", guarded_json_safe_row)
    threads = _patch_batch_environment(monkeypatch, _Mapper)

    job_id = _start_job([
        {"field_name": "first"},
        {"field_name": "second"},
        {"field_name": "third"},
    ])
    assert before_second_map.wait(timeout=2)
    assert mapper_service.get_batch_job(job_id)["completed"] == 1

    assert mapper_service.cancel_batch_job(job_id) is True
    release_second_checkpoint.set()
    _join_threads(threads)

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "interrupted"
    assert job["completed"] == 1
    assert [row.field_name for row in job["results"]] == ["first"]
    assert mapped_terms == ["first"]


def test_cancel_while_row_in_flight_discards_that_row_and_stops(monkeypatch):
    second_in_flight = threading.Event()
    release_second = threading.Event()
    mapped_terms: list[str] = []

    class _Mapper:
        def map_term(self, **kwargs):
            source_term = kwargs["source_term"]
            mapped_terms.append(source_term)
            if source_term == "second":
                second_in_flight.set()
                assert release_second.wait(timeout=2)
            return _FakeMappingResult(source_term)

    threads = _patch_batch_environment(monkeypatch, _Mapper)

    job_id = _start_job([
        {"field_name": "first"},
        {"field_name": "second"},
        {"field_name": "third"},
    ])
    assert second_in_flight.wait(timeout=2)
    assert mapper_service.get_batch_job(job_id)["completed"] == 1

    assert mapper_service.cancel_batch_job(job_id) is True
    release_second.set()
    _join_threads(threads)

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "interrupted"
    assert job["completed"] == 1
    assert [row.field_name for row in job["results"]] == ["first"]
    assert mapped_terms == ["first", "second"]


def test_duplicate_cancellation_preserves_state(monkeypatch):
    second_in_flight = threading.Event()
    release_second = threading.Event()

    class _Mapper:
        def map_term(self, **kwargs):
            if kwargs["source_term"] == "second":
                second_in_flight.set()
                assert release_second.wait(timeout=2)
            return _FakeMappingResult(kwargs["source_term"])

    threads = _patch_batch_environment(monkeypatch, _Mapper)

    job_id = _start_job([{"field_name": "first"}, {"field_name": "second"}])
    assert second_in_flight.wait(timeout=2)

    assert mapper_service.cancel_batch_job(job_id) is True
    first_cancel_snapshot = mapper_service.get_batch_job(job_id)
    assert mapper_service.cancel_batch_job(job_id) is True
    second_cancel_snapshot = mapper_service.get_batch_job(job_id)
    release_second.set()
    _join_threads(threads)

    final_job = mapper_service.get_batch_job(job_id)
    assert first_cancel_snapshot["status"] == "interrupted"
    assert second_cancel_snapshot["status"] == "interrupted"
    assert len(first_cancel_snapshot["results"]) == 1
    assert len(second_cancel_snapshot["results"]) == 1
    assert final_job["completed"] == 1
    assert [row.field_name for row in final_job["results"]] == ["first"]


def test_cancel_after_done_does_not_mutate_completed_job(monkeypatch):
    class _Mapper:
        def map_term(self, **kwargs):
            return _FakeMappingResult(kwargs["source_term"])

    threads = _patch_batch_environment(monkeypatch, _Mapper)

    job_id = _start_job([{"field_name": "only"}])
    _join_threads(threads)
    completed_snapshot = mapper_service.get_batch_job(job_id)

    assert completed_snapshot["status"] == "done"
    assert mapper_service.cancel_batch_job(job_id) is True

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "done"
    assert job["completed"] == completed_snapshot["completed"]
    assert job["results"] == completed_snapshot["results"]


def test_cancel_requested_before_final_done_transition_wins():
    row = _FakeMappingResult("only")
    job = {
        "status": "running",
        "total": 1,
        "completed": 1,
        "results": [row],
        "cancel_requested": True,
    }

    mapper_service._mark_batch_done_locked(job)

    assert job["status"] == "interrupted"
    assert job["completed"] == 1
    assert job["results"] == [row]


def test_late_mapper_result_cannot_overwrite_interrupted(monkeypatch):
    row_in_flight = threading.Event()
    release_row = threading.Event()

    class _Mapper:
        def map_term(self, **kwargs):
            row_in_flight.set()
            assert release_row.wait(timeout=2)
            return _FakeMappingResult(kwargs["source_term"])

    threads = _patch_batch_environment(monkeypatch, _Mapper)

    job_id = _start_job([{"field_name": "only"}])
    assert row_in_flight.wait(timeout=2)

    assert mapper_service.cancel_batch_job(job_id) is True
    interrupted_snapshot = mapper_service.get_batch_job(job_id)
    release_row.set()
    _join_threads(threads)

    job = mapper_service.get_batch_job(job_id)
    assert interrupted_snapshot["status"] == "interrupted"
    assert job["status"] == "interrupted"
    assert job["completed"] == 0
    assert job["results"] == []


def test_cancelling_one_job_does_not_affect_another(monkeypatch):
    a_second_in_flight = threading.Event()
    release_a_second = threading.Event()

    class _Mapper:
        def map_term(self, **kwargs):
            source_term = kwargs["source_term"]
            if source_term == "a-second":
                a_second_in_flight.set()
                assert release_a_second.wait(timeout=2)
            return _FakeMappingResult(source_term)

    threads = _patch_batch_environment(monkeypatch, _Mapper)

    job_a = _start_job([
        {"field_name": "a-first"},
        {"field_name": "a-second"},
        {"field_name": "a-third"},
    ])
    assert a_second_in_flight.wait(timeout=2)

    job_b = _start_job([{"field_name": "b-only"}])
    _wait_until(lambda: mapper_service.get_batch_job(job_b)["status"] == "done")

    assert mapper_service.cancel_batch_job(job_a) is True
    release_a_second.set()
    _join_threads(threads)

    batch_a = mapper_service.get_batch_job(job_a)
    batch_b = mapper_service.get_batch_job(job_b)
    assert batch_a["status"] == "interrupted"
    assert [row.field_name for row in batch_a["results"]] == ["a-first"]
    assert batch_b["status"] == "done"
    assert batch_b["completed"] == 1
    assert [row.field_name for row in batch_b["results"]] == ["b-only"]
    assert batch_b["cancel_requested"] is False


def test_initialisation_failure_still_marks_uncancelled_batch_failed(monkeypatch):
    def fail_build_mapper_kwargs(_config, *, ontologies=None):
        raise ValueError("mapper setup failed")

    threads = _patch_batch_environment(monkeypatch, object)
    monkeypatch.setattr(mapper_service, "_build_mapper_kwargs", fail_build_mapper_kwargs)

    job_id = _start_job([{"field_name": "first"}])
    _join_threads(threads)

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "failed"
    assert job["error"] == "mapper setup failed"
    assert job["results"] == []


def test_cancelled_initialisation_failure_remains_interrupted(monkeypatch):
    build_entered = threading.Event()
    release_build = threading.Event()

    def fail_after_release(_config, *, ontologies=None):
        build_entered.set()
        assert release_build.wait(timeout=2)
        raise ValueError("mapper setup failed")

    threads = _patch_batch_environment(monkeypatch, object)
    monkeypatch.setattr(mapper_service, "_build_mapper_kwargs", fail_after_release)

    job_id = _start_job([{"field_name": "first"}])
    assert build_entered.wait(timeout=2)
    assert mapper_service.cancel_batch_job(job_id) is True
    release_build.set()
    _join_threads(threads)

    job = mapper_service.get_batch_job(job_id)
    assert job["status"] == "interrupted"
    assert "error" not in job
    assert job["completed"] == 0
    assert job["results"] == []

import pytest

from app.models.session import InputSummary
from app.storage import session_store


@pytest.fixture
def temp_session_store(monkeypatch, tmp_path):
    session_dir = tmp_path / "session_logs"
    monkeypatch.setattr(session_store, "_SESSION_DIR", session_dir)
    monkeypatch.setattr(session_store, "_INDEX_FILE", session_dir / "index.json")
    return session_store


def _create_batch_session(store=session_store) -> str:
    return store.create_session(
        "batch_map",
        InputSummary(filename="dictionary.csv", row_count=2),
    )


def _snapshot(status: str, completed: int, field_name: str):
    return {
        "job_id": "job-1",
        "total": 2,
        "completed": completed,
        "status": status,
        "results": [
            {
                "row_index": 0,
                "field_name": field_name,
                "suggested_code": "LOINC:8480-6",
                "suggested_term": "Systolic blood pressure",
                "ontology": "LOINC",
                "confidence": 0.9,
                "logic_type": "llm",
                "decision": "accepted",
                "alternatives": [],
            }
        ],
    }


def test_interrupted_session_survives_later_stale_complete_attempt(temp_session_store):
    session_id = _create_batch_session(temp_session_store)
    interrupted = _snapshot("interrupted", 1, "partial")
    stale_complete = _snapshot("done", 2, "stale-complete")

    temp_session_store.complete_session(session_id, "interrupted", interrupted)
    temp_session_store.complete_session(session_id, "complete", stale_complete)

    record = temp_session_store.get_session(session_id)
    assert record.status == "interrupted"
    assert record.result_snapshot == interrupted


def test_complete_session_cannot_later_become_interrupted(temp_session_store):
    session_id = _create_batch_session(temp_session_store)
    complete = _snapshot("done", 2, "complete")
    stale_interrupted = _snapshot("interrupted", 1, "stale-interrupted")

    temp_session_store.complete_session(session_id, "complete", complete)
    temp_session_store.complete_session(session_id, "interrupted", stale_interrupted)

    record = temp_session_store.get_session(session_id)
    assert record.status == "complete"
    assert record.result_snapshot == complete


def test_error_session_cannot_be_overwritten_by_complete_or_interrupted(temp_session_store):
    session_id = _create_batch_session(temp_session_store)
    error_snapshot = {"error": "provider failed"}

    temp_session_store.complete_session(session_id, "error", error_snapshot)
    temp_session_store.complete_session(session_id, "complete", _snapshot("done", 2, "complete"))
    temp_session_store.complete_session(
        session_id,
        "interrupted",
        _snapshot("interrupted", 1, "partial"),
    )

    record = temp_session_store.get_session(session_id)
    assert record.status == "error"
    assert record.result_snapshot == error_snapshot


def test_duplicate_interrupted_finalization_can_enrich_snapshot(temp_session_store):
    session_id = _create_batch_session(temp_session_store)
    provisional = {
        "status": "interrupted",
        "completed": 1,
        "total": 2,
    }
    enriched = _snapshot("interrupted", 1, "authoritative")

    temp_session_store.complete_session(session_id, "interrupted", provisional)
    temp_session_store.complete_session(session_id, "interrupted", enriched)
    temp_session_store.complete_session(session_id, "interrupted", enriched)

    record = temp_session_store.get_session(session_id)
    assert record.status == "interrupted"
    assert record.result_snapshot == enriched


def _snapshot_with_urls(status: str, completed: int, field_name: str):
    snapshot = _snapshot(status, completed, field_name)
    snapshot["results"][0]["suggested_url"] = "https://loinc.org/8480-6"
    snapshot["results"][0]["alternatives"] = [
        {
            "code": "LOINC:76534-7",
            "term": "Diastolic blood pressure",
            "ontology": "LOINC",
            "confidence": 0.5,
            "url": "https://loinc.org/76534-7",
        }
    ]
    return snapshot


def test_complete_session_strips_derived_batch_urls_before_persisting(temp_session_store):
    session_id = _create_batch_session(temp_session_store)
    snapshot = _snapshot_with_urls("done", 2, "sbp")

    temp_session_store.complete_session(session_id, "complete", snapshot)

    record = temp_session_store.get_session(session_id)
    row = record.result_snapshot["results"][0]
    assert "suggested_url" not in row
    assert "url" not in row["alternatives"][0]
    # Everything else is preserved untouched.
    assert row["suggested_code"] == "LOINC:8480-6"
    assert row["alternatives"][0]["code"] == "LOINC:76534-7"


def test_complete_session_preserves_batch_processing_time_seconds(temp_session_store):
    session_id = _create_batch_session(temp_session_store)
    snapshot = _snapshot_with_urls("done", 2, "sbp")
    snapshot["results"][0]["processing_time_seconds"] = 4.82

    temp_session_store.complete_session(session_id, "complete", snapshot)

    record = temp_session_store.get_session(session_id)
    row = record.result_snapshot["results"][0]
    # Processing time is historical execution data, not derived data like the
    # ontology URLs stripped above — the URL-stripping helper must not touch it.
    assert row["processing_time_seconds"] == 4.82


def test_complete_session_preserves_term_search_metadata_latency(temp_session_store):
    session_id = temp_session_store.create_session(
        "term_search",
        InputSummary(term="sbp"),
    )
    snapshot = {
        "source_term": "sbp",
        "target_code": "LOINC:8480-6",
        "target_term": "Systolic blood pressure",
        "ontology": "LOINC",
        "confidence": 0.9,
        "logic_type": "rag",
        "target_url": "https://loinc.org/8480-6",
        "metadata": {
            "model": "llama3.2",
            "provider": "ollama",
            "latency_ms": 4820.0,
        },
        "alternatives": [],
    }

    temp_session_store.complete_session(session_id, "complete", snapshot)

    record = temp_session_store.get_session(session_id)
    assert record.result_snapshot["metadata"]["latency_ms"] == 4820.0


def test_complete_session_strips_derived_term_search_url(temp_session_store):
    session_id = temp_session_store.create_session(
        "term_search",
        InputSummary(term="sbp"),
    )
    snapshot = {
        "source_term": "sbp",
        "target_code": "LOINC:8480-6",
        "target_term": "Systolic blood pressure",
        "ontology": "LOINC",
        "confidence": 0.9,
        "logic_type": "rag",
        "target_url": "https://loinc.org/8480-6",
        "alternatives": [
            {
                "code": "LOINC:76534-7",
                "term": "Diastolic blood pressure",
                "ontology": "LOINC",
                "confidence": 0.5,
                "url": "https://loinc.org/76534-7",
            }
        ],
    }

    temp_session_store.complete_session(session_id, "complete", snapshot)

    record = temp_session_store.get_session(session_id)
    assert "target_url" not in record.result_snapshot
    assert "url" not in record.result_snapshot["alternatives"][0]
    # The underlying code/term data is untouched.
    assert record.result_snapshot["target_code"] == "LOINC:8480-6"

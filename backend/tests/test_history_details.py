from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api import history as history_api
from app.api.history import normalize_history_details
from app.main import app
from app.models.session import EventRecord, InputSummary, SessionRecord
from app.services import mapper_service

client = TestClient(app)


def _record(session_type: str, input_summary: InputSummary, result_snapshot=None):
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    return SessionRecord(
        session_id=f"{session_type}-1",
        type=session_type,
        created_at=now,
        updated_at=now,
        status="complete",
        input_summary=input_summary,
        result_snapshot=result_snapshot,
    )


def test_term_search_detail_normalizes_best_match_and_alternatives():
    detail = normalize_history_details(
        _record(
            "term_search",
            InputSummary(term="sbp", target_ontologies=["LOINC"]),
            {
                "source_term": "sbp",
                "source_label": "Systolic blood pressure",
                "source_type": "numeric",
                "target_code": "8480-6",
                "target_term": "Systolic blood pressure",
                "ontology": "LOINC",
                "confidence": 0.91,
                "logic_type": "rag",
                "notes": "Strong lexical and clinical match.",
                "retrieval_mode": "local",
                "configured_provider": "ollama",
                "configured_model": "llama3.2",
                "alternatives": [
                    {
                        "code": "8462-4",
                        "term": "Diastolic blood pressure",
                        "ontology": "LOINC",
                        "confidence": 0.55,
                        "explanation": "Related vital sign.",
                    }
                ],
            },
        )
    )

    assert detail.type == "term_search"
    assert detail.result.best_match is not None
    assert detail.result.best_match.target_code == "8480-6"
    assert detail.result.alternatives[0].code == "8462-4"
    assert detail.configuration is not None
    assert detail.configuration.provider == "ollama"
    assert detail.configuration.model == "llama3.2"


def test_batch_detail_includes_rows_and_persisted_decisions():
    detail = normalize_history_details(
        _record(
            "batch_map",
            InputSummary(
                filename="dictionary.csv",
                row_count=2,
                target_ontologies=["HPO"],
                auto_accept_threshold=0.85,
            ),
            {
                "job_id": "job-1",
                "total": 2,
                "completed": 2,
                "status": "done",
                "results": [
                    {
                        "row_index": 0,
                        "field_name": "sbp",
                        "label": "Systolic BP",
                        "suggested_code": "LOINC:8480-6",
                        "suggested_term": "Systolic blood pressure",
                        "ontology": "LOINC",
                        "confidence": 0.92,
                        "logic_type": "rag",
                        "decision": "accepted",
                        "alternatives": [],
                    },
                    {
                        "row_index": 1,
                        "field_name": "unknown",
                        "suggested_code": "UNMAPPED",
                        "suggested_term": "Unmapped",
                        "ontology": "",
                        "confidence": 0,
                        "logic_type": "none",
                        "decision": "rejected",
                        "alternatives": [],
                    },
                ],
            },
        )
    )

    assert detail.type == "batch_map"
    assert [row.decision for row in detail.result.rows] == ["accepted", "rejected"]
    assert detail.result.summary.accepted_count == 1
    assert detail.result.summary.rejected_count == 1
    assert detail.result.summary.unmapped_count == 1


def test_interrupted_batch_detail_includes_partial_rows():
    record = _record(
        "batch_map",
        InputSummary(filename="dictionary.csv", row_count=3),
        {
            "job_id": "job-1",
            "total": 3,
            "completed": 1,
            "status": "interrupted",
            "results": [
                {
                    "row_index": 0,
                    "field_name": "sbp",
                    "label": "Systolic BP",
                    "suggested_code": "LOINC:8480-6",
                    "suggested_term": "Systolic blood pressure",
                    "ontology": "LOINC",
                    "confidence": 0.92,
                    "logic_type": "rag",
                    "decision": "accepted",
                    "alternatives": [],
                }
            ],
        },
    )
    record.status = "interrupted"
    detail = normalize_history_details(record)

    assert detail.status == "interrupted"
    assert detail.result.status == "interrupted"
    assert detail.result.total == 3
    assert detail.result.completed == 1
    assert [row.field_name for row in detail.result.rows] == ["sbp"]
    assert detail.result.summary.completed_count == 1


def test_get_interrupted_history_detail_does_not_resume_batch(monkeypatch):
    record = _record(
        "batch_map",
        InputSummary(filename="dictionary.csv", row_count=1),
        {
            "job_id": "job-1",
            "total": 1,
            "completed": 1,
            "status": "interrupted",
            "results": [
                {
                    "row_index": 0,
                    "field_name": "sbp",
                    "suggested_code": "LOINC:8480-6",
                    "suggested_term": "Systolic blood pressure",
                    "ontology": "LOINC",
                    "confidence": 0.92,
                    "logic_type": "rag",
                    "decision": "accepted",
                    "alternatives": [],
                }
            ],
        },
    )
    record.status = "interrupted"
    monkeypatch.setattr(history_api, "get_session", lambda _session_id: record)

    def fail_if_started(*_args, **_kwargs):
        raise AssertionError("History detail must not start batch jobs")

    monkeypatch.setattr(mapper_service, "start_batch_job", fail_if_started)

    response = client.get("/api/history/batch_map-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "interrupted"
    assert payload["result"]["rows"][0]["field_name"] == "sbp"


def test_validation_detail_includes_individual_results_and_counts():
    detail = normalize_history_details(
        _record(
            "validation",
            InputSummary(codes=["HP:0000822", "HP:9999999"]),
            {
                "results": [
                    {
                        "code": "HP:0000822",
                        "status": "valid",
                        "term": "Hypertension",
                        "ontology": "HPO",
                    },
                    {
                        "code": "HP:9999999",
                        "status": "not-found",
                    },
                ]
            },
        )
    )

    assert detail.type == "validation"
    assert [row.code for row in detail.result.results] == ["HP:0000822", "HP:9999999"]
    assert detail.result.summary.valid_count == 1
    assert detail.result.summary.not_found_count == 1


def test_legacy_unreconstructable_detail_has_message_not_raw_payload():
    record = _record("term_search", InputSummary(term="legacy"), {"unexpected": True})
    detail = normalize_history_details(record)

    assert detail.type == "term_search"
    assert detail.result.best_match is None
    assert detail.legacy_message == "Detailed results were not stored for this earlier session."


def test_failed_detail_uses_human_readable_error_message():
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    record = SessionRecord(
        session_id="term-search-error",
        type="term_search",
        created_at=now,
        updated_at=now,
        status="error",
        input_summary=InputSummary(term="sbp"),
        events=[
            EventRecord(
                timestamp=now,
                actor="system",
                event_type="session_error",
                payload={"message": "Provider timed out\nTraceback details"},
            )
        ],
    )

    detail = normalize_history_details(record)

    assert detail.failure is not None
    assert detail.failure.message == "Provider timed out"


def test_batch_history_csv_uses_enriched_export_serializer(monkeypatch):
    record = _record(
        "batch_map",
        InputSummary(filename="dictionary.csv", row_count=1),
        {
            "job_id": "job-1",
            "total": 1,
            "completed": 1,
            "status": "done",
            "results": [
                {
                    "row_index": 0,
                    "field_name": "sbp",
                    "label": "Systolic BP",
                    "source_description": "Measured seated.",
                    "original_row": {
                        "source_variable": "sbp",
                        "source_description": "Measured seated.",
                        "custom": "alpha",
                    },
                    "original_columns": [
                        "source_variable",
                        "source_description",
                        "custom",
                    ],
                    "requested_target_ontology": "LOINC",
                    "suggested_code": "LOINC:8480-6",
                    "suggested_term": "Systolic blood pressure",
                    "ontology": "LOINC",
                    "confidence": 0.92,
                    "logic_type": "rag",
                    "decision": "accepted",
                    "notes": "Strong match.",
                    "alternatives": [],
                }
            ],
        },
    )
    monkeypatch.setattr(history_api, "get_session", lambda _session_id: record)

    response = client.get("/api/history/batch_map-1/batch-csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.splitlines()[0].startswith(
        "source_variable,source_description,custom,target_ontology,mapped_code"
    )
    assert "sbp,Measured seated.,alpha,LOINC,LOINC:8480-6" in response.text


def test_term_search_detail_recomputes_url_for_legacy_snapshot_without_url_field():
    # Legacy snapshot predating this feature — no target_url/alternatives[].url
    # keys at all. Must still get a working link, with no migration.
    detail = normalize_history_details(
        _record(
            "term_search",
            InputSummary(term="sbp", target_ontologies=["LOINC"]),
            {
                "source_term": "sbp",
                "target_code": "LOINC:8480-6",
                "target_term": "Systolic blood pressure",
                "ontology": "LOINC",
                "confidence": 0.91,
                "logic_type": "rag",
                "alternatives": [
                    {
                        "code": "LOINC:76534-7",
                        "term": "Diastolic blood pressure",
                        "ontology": "LOINC",
                        "confidence": 0.55,
                    }
                ],
            },
        )
    )

    assert detail.result.best_match is not None
    assert detail.result.best_match.target_url == "https://loinc.org/8480-6"
    assert detail.result.alternatives[0].url == "https://loinc.org/76534-7"


def test_term_search_detail_ignores_stale_stored_url_and_recomputes():
    # Even if a stored snapshot happens to contain a (possibly stale) url,
    # the history API must recompute rather than trust it.
    detail = normalize_history_details(
        _record(
            "term_search",
            InputSummary(term="sbp"),
            {
                "source_term": "sbp",
                "target_code": "LOINC:8480-6",
                "target_term": "Systolic blood pressure",
                "ontology": "LOINC",
                "confidence": 0.91,
                "logic_type": "rag",
                "target_url": "https://example.com/stale-or-wrong-url",
                "alternatives": [],
            },
        )
    )

    assert detail.result.best_match.target_url == "https://loinc.org/8480-6"


def test_batch_detail_recomputes_suggested_url_for_legacy_snapshot():
    detail = normalize_history_details(
        _record(
            "batch_map",
            InputSummary(filename="dictionary.csv", row_count=1),
            {
                "job_id": "job-1",
                "total": 1,
                "completed": 1,
                "status": "done",
                "results": [
                    {
                        "row_index": 0,
                        "field_name": "sbp",
                        "suggested_code": "LOINC:8480-6",
                        "suggested_term": "Systolic blood pressure",
                        "ontology": "LOINC",
                        "confidence": 0.92,
                        "logic_type": "rag",
                        "decision": "accepted",
                        "alternatives": [
                            {
                                "code": "LOINC:76215-3",
                                "term": "Systolic blood pressure alt",
                                "ontology": "LOINC",
                                "confidence": 0.4,
                            }
                        ],
                    }
                ],
            },
        )
    )

    row = detail.result.rows[0]
    assert row.suggested_url == "https://loinc.org/8480-6"
    assert row.alternatives[0].url == "https://loinc.org/76215-3"


def test_batch_detail_url_follows_returned_code_not_requested_ontology():
    detail = normalize_history_details(
        _record(
            "batch_map",
            InputSummary(filename="dictionary.csv", row_count=1, target_ontologies=["EFO"]),
            {
                "job_id": "job-1",
                "total": 1,
                "completed": 1,
                "status": "done",
                "results": [
                    {
                        "row_index": 0,
                        "field_name": "seizure",
                        "requested_target_ontology": "EFO",
                        "suggested_code": "HP:0001250",
                        "suggested_term": "Seizure",
                        "ontology": "HPO",
                        "confidence": 0.9,
                        "logic_type": "rag",
                        "decision": "accepted",
                        "alternatives": [],
                    }
                ],
            },
        )
    )

    row = detail.result.rows[0]
    assert row.suggested_url is not None
    assert "ontologies/hp/" in row.suggested_url


def test_batch_detail_unmapped_row_has_no_url():
    detail = normalize_history_details(
        _record(
            "batch_map",
            InputSummary(filename="dictionary.csv", row_count=1),
            {
                "job_id": "job-1",
                "total": 1,
                "completed": 1,
                "status": "done",
                "results": [
                    {
                        "row_index": 0,
                        "field_name": "unknown",
                        "suggested_code": "UNMAPPED",
                        "suggested_term": "Unmapped",
                        "ontology": "",
                        "confidence": 0,
                        "logic_type": "none",
                        "decision": "rejected",
                        "alternatives": [],
                    }
                ],
            },
        )
    )

    assert detail.result.rows[0].suggested_url is None

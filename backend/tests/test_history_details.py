from datetime import datetime, timezone

from app.api.history import normalize_history_details
from app.models.session import EventRecord, InputSummary, SessionRecord


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

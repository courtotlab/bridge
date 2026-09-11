import json
import logging
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ValidationError

from app.models.mapping import (
    AlternativeResult,
    BatchMappingResponse,
    BatchRowResult,
    SingleMappingResponse,
)
from app.models.session import (
    BatchMapHistoryDetails,
    BatchMapHistoryResult,
    BatchMapSummary,
    EventRecord,
    HistoryConfiguration,
    HistoryDetails,
    HistoryFailure,
    InputSummary,
    SessionRecord,
    SessionSummary,
    TermSearchHistoryDetails,
    TermSearchHistoryResult,
    ValidationHistoryDetails,
    ValidationHistoryResult,
    ValidationSummary,
)
from app.models.validator import ValidateResult
from app.storage.session_store import (
    append_event,
    complete_session,
    create_session,
    delete_session,
    get_all_sessions,
    get_session,
)
from app.utils.batch_export import build_batch_rows_csv
from app.utils.ontology_urls import resolve_ontology_url

router = APIRouter()
logger = logging.getLogger(__name__)


class CreateSessionRequest(BaseModel):
    type: Literal["validation", "term_search", "batch_map"]
    input_summary: InputSummary


class AppendEventRequest(BaseModel):
    timestamp: datetime
    actor: Literal["user", "system"]
    event_type: str
    payload: dict


class CompleteSessionRequest(BaseModel):
    status: Literal["complete", "error", "interrupted"]
    result_snapshot: dict | None = None


def _with_resolved_alternative_urls(
    alternatives: list[AlternativeResult],
) -> list[AlternativeResult]:
    """Recompute each alternative's URL from its stored code — never trust a
    stored value, since ontology URLs are derived data (see
    app.storage.session_store, which strips them before persisting)."""
    return [
        alt.model_copy(update={"url": resolve_ontology_url(alt.code, alt.ontology)})
        for alt in alternatives
    ]


def _with_resolved_mapping_url(response: SingleMappingResponse) -> SingleMappingResponse:
    return response.model_copy(
        update={
            "target_url": resolve_ontology_url(response.target_code, response.ontology),
            "alternatives": _with_resolved_alternative_urls(response.alternatives),
        }
    )


def _with_resolved_batch_row_url(row: BatchRowResult) -> BatchRowResult:
    return row.model_copy(
        update={
            "suggested_url": resolve_ontology_url(row.suggested_code, row.ontology),
            "alternatives": _with_resolved_alternative_urls(row.alternatives),
        }
    )


def _plain_payload_value(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return value
    return None


def _event_payload(record: SessionRecord, *event_types: str) -> dict[str, Any]:
    wanted = set(event_types)
    for event in reversed(record.events):
        if event.event_type in wanted:
            return event.payload
    return {}


def _stored_error_message(record: SessionRecord) -> str | None:
    payload = _event_payload(record, "session_error", "batch_failed")
    raw = _plain_payload_value(payload, "message", "detail", "error")
    if raw is None:
        snapshot = record.result_snapshot or {}
        raw = _plain_payload_value(snapshot, "error", "message", "detail")
    if raw is None:
        return None
    message = str(raw).strip()
    if not message:
        return None
    return message.splitlines()[0]


def _has_value(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _compact_dict(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if _has_value(value)}


def _base_input(record: SessionRecord) -> dict[str, Any]:
    return record.input_summary.model_dump(exclude_none=True)


def _completed_at(record: SessionRecord) -> datetime | None:
    return None if record.status == "in_progress" else record.updated_at


def _configuration_from(
    record: SessionRecord,
    result: dict[str, Any] | None = None,
    batch_rows: list[BatchRowResult] | None = None,
) -> HistoryConfiguration | None:
    result = result or {}
    first_row = batch_rows[0] if batch_rows else None
    metadata = result.get("metadata") if isinstance(result.get("metadata"), dict) else {}

    configuration = HistoryConfiguration(
        target_ontologies=record.input_summary.target_ontologies,
        target_ontology_column=record.input_summary.target_ontology_column,
        auto_accept_threshold=record.input_summary.auto_accept_threshold,
        retrieval_method=(
            result.get("retrieval_mode")
            or (first_row.retrieval_mode if first_row else None)
        ),
        provider=(
            result.get("configured_provider")
            or (metadata or {}).get("provider")
            or (first_row.configured_provider if first_row else None)
        ),
        model=(
            result.get("configured_model")
            or (metadata or {}).get("model")
            or (first_row.configured_model if first_row else None)
        ),
        strict_target_ontology=record.input_summary.strict_target_ontology,
    )
    return configuration if configuration.model_dump(exclude_none=True) else None


def _normalize_term_search(record: SessionRecord) -> TermSearchHistoryDetails:
    snapshot = record.result_snapshot or {}
    best_match: SingleMappingResponse | None = None
    if snapshot:
        try:
            best_match = SingleMappingResponse.model_validate(snapshot)
        except ValidationError:
            best_match = None
    if best_match is not None:
        best_match = _with_resolved_mapping_url(best_match)

    input_values = _compact_dict(
        {
            **_base_input(record),
            "source_term": snapshot.get("source_term") or record.input_summary.term,
            "source_label": snapshot.get("source_label"),
            "source_data_type": snapshot.get("source_type"),
        }
    )
    alternatives = best_match.alternatives if best_match else []
    return TermSearchHistoryDetails(
        id=record.session_id,
        status=record.status,
        created_at=record.created_at,
        completed_at=_completed_at(record),
        input=input_values,
        configuration=_configuration_from(record, snapshot),
        failure=HistoryFailure(message=_stored_error_message(record))
        if record.status == "error"
        else None,
        legacy_message=None
        if best_match or record.status in ("error", "in_progress")
        else "Detailed results were not stored for this earlier session.",
        result=TermSearchHistoryResult(
            best_match=best_match,
            alternatives=alternatives,
        ),
    )


def _is_unmapped_code(code: str | None) -> bool:
    return bool(code and "UNMAPPED" in code.upper())


def _normalize_batch_map(record: SessionRecord) -> BatchMapHistoryDetails:
    snapshot = record.result_snapshot or {}
    rows: list[BatchRowResult] = []
    total = record.input_summary.row_count
    completed = None
    batch_status = None
    error = _stored_error_message(record)

    if snapshot:
        try:
            response = BatchMappingResponse.model_validate(snapshot)
            rows = [_with_resolved_batch_row_url(row) for row in response.results]
            total = response.total
            completed = response.completed
            batch_status = response.status
            error = response.error or error
        except ValidationError:
            raw_rows = snapshot.get("results")
            if isinstance(raw_rows, list):
                for raw in raw_rows:
                    try:
                        rows.append(
                            _with_resolved_batch_row_url(BatchRowResult.model_validate(raw))
                        )
                    except ValidationError:
                        logger.debug("Skipping malformed legacy batch row", exc_info=True)
                        continue
            total = snapshot.get("total") or total
            completed = snapshot.get("completed")
            batch_status = snapshot.get("status")
            error = snapshot.get("error") or error

    accepted_count = sum(1 for row in rows if row.decision == "accepted")
    rejected_count = sum(1 for row in rows if row.decision == "rejected")
    pending_count = sum(1 for row in rows if row.decision == "pending")
    unmapped_count = sum(1 for row in rows if _is_unmapped_code(row.suggested_code))
    summary = BatchMapSummary(
        total_rows=total,
        completed_count=completed if completed is not None else len(rows) or None,
        accepted_count=accepted_count,
        pending_count=pending_count,
        rejected_count=rejected_count,
        unmapped_count=unmapped_count,
    )

    return BatchMapHistoryDetails(
        id=record.session_id,
        status=record.status,
        created_at=record.created_at,
        completed_at=_completed_at(record),
        input=_base_input(record),
        configuration=_configuration_from(record, snapshot, rows),
        failure=HistoryFailure(message=error) if record.status == "error" else None,
        legacy_message=None
        if rows or record.status in ("error", "in_progress", "interrupted")
        else "Detailed results were not stored for this earlier session.",
        result=BatchMapHistoryResult(
            total=total,
            completed=completed,
            status=batch_status,
            rows=rows,
            summary=summary,
            error=error,
        ),
    )


def _normalize_validation(record: SessionRecord) -> ValidationHistoryDetails:
    snapshot = record.result_snapshot or {}
    results: list[ValidateResult] = []
    raw_results = snapshot.get("results")
    if isinstance(raw_results, list):
        for raw in raw_results:
            try:
                results.append(ValidateResult.model_validate(raw))
            except ValidationError:
                logger.debug("Skipping malformed legacy validation row", exc_info=True)
                continue

    valid_count = sum(1 for row in results if row.status == "valid")
    deprecated_count = sum(1 for row in results if row.status == "deprecated")
    not_found_count = sum(1 for row in results if row.status == "not-found")
    return ValidationHistoryDetails(
        id=record.session_id,
        status=record.status,
        created_at=record.created_at,
        completed_at=_completed_at(record),
        input=_base_input(record),
        configuration=None,
        failure=HistoryFailure(message=_stored_error_message(record))
        if record.status == "error"
        else None,
        legacy_message=None
        if results or record.status in ("error", "in_progress")
        else "Detailed results were not stored for this earlier session.",
        result=ValidationHistoryResult(
            results=results,
            summary=ValidationSummary(
                total_count=len(results),
                valid_count=valid_count,
                deprecated_count=deprecated_count,
                not_found_count=not_found_count,
            ),
        ),
    )


def normalize_history_details(record: SessionRecord) -> HistoryDetails:
    if record.type == "term_search":
        return _normalize_term_search(record)
    if record.type == "batch_map":
        return _normalize_batch_map(record)
    return _normalize_validation(record)


@router.post("", status_code=201)
async def create_session_endpoint(body: CreateSessionRequest) -> dict:
    session_id = create_session(body.type, body.input_summary)
    logger.info("[history] created session %s type=%s", session_id, body.type)
    return {"session_id": session_id}


@router.patch("/{session_id}/event", status_code=204)
async def append_event_endpoint(session_id: str, body: AppendEventRequest) -> None:
    try:
        event = EventRecord(
            timestamp=body.timestamp,
            actor=body.actor,
            event_type=body.event_type,
            payload=body.payload,
        )
        append_event(session_id, event)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")


@router.patch("/{session_id}/complete", status_code=204)
async def complete_session_endpoint(
    session_id: str, body: CompleteSessionRequest
) -> None:
    try:
        complete_session(session_id, body.status, body.result_snapshot)
        logger.info("[history] completed session %s status=%s", session_id, body.status)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")


@router.get("", response_model=list[SessionSummary])
async def list_sessions() -> list[SessionSummary]:
    return get_all_sessions()


@router.get("/{session_id}/export")
async def export_session(session_id: str) -> Response:
    try:
        record = get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    exported_at = datetime.now(timezone.utc)
    filename = f"session_{record.created_at.strftime('%Y%m%d_%H%M%S')}.json"
    export_payload = {
        "export_version": "1.0",
        "exported_at": exported_at.isoformat(),
        "session": json.loads(record.model_dump_json()),
    }
    return Response(
        content=json.dumps(export_payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{session_id}/batch-csv")
async def export_batch_session_csv(session_id: str) -> Response:
    try:
        record = get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

    if record.type != "batch_map":
        raise HTTPException(status_code=404, detail="Batch CSV export is only available for batch map sessions")

    detail = _normalize_batch_map(record)
    csv_content = build_batch_rows_csv(detail.result.rows)
    stem = record.input_summary.filename.rsplit(".", 1)[0] if record.input_summary.filename else "batch"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{stem}_history_results.csv"'},
    )


@router.get("/{session_id}", response_model=HistoryDetails)
async def get_session_endpoint(session_id: str) -> HistoryDetails:
    try:
        return normalize_history_details(get_session(session_id))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")


@router.delete("/{session_id}", status_code=204)
async def delete_session_endpoint(session_id: str) -> None:
    try:
        delete_session(session_id)
        logger.info("[history] deleted session %s", session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

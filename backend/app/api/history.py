import json
import logging
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from app.models.session import EventRecord, InputSummary, SessionRecord, SessionSummary
from app.storage.session_store import (
    append_event,
    complete_session,
    create_session,
    delete_session,
    get_all_sessions,
    get_session,
)

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
    status: Literal["complete", "error"]
    result_snapshot: dict | None = None


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


@router.get("/{session_id}", response_model=SessionRecord)
async def get_session_endpoint(session_id: str) -> SessionRecord:
    try:
        return get_session(session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")


@router.delete("/{session_id}", status_code=204)
async def delete_session_endpoint(session_id: str) -> None:
    try:
        delete_session(session_id)
        logger.info("[history] deleted session %s", session_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")

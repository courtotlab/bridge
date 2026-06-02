import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models.session import EventRecord, InputSummary, SessionRecord, SessionSummary

_SESSION_DIR = Path.home() / ".ontology_mapper" / "session_logs"
_INDEX_FILE = _SESSION_DIR / "index.json"
_lock = threading.Lock()


def _session_filename(created_at: datetime, session_id: str) -> str:
    return f"session_{created_at.strftime('%Y%m%d_%H%M%S')}_{session_id[:8]}.json"


def _read_index() -> dict[str, dict]:
    if not _INDEX_FILE.exists():
        return {}
    try:
        return json.loads(_INDEX_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_index(index: dict[str, dict]) -> None:
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    _INDEX_FILE.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _to_index_entry(record: SessionRecord, filename: str) -> dict:
    summary = SessionSummary(
        session_id=record.session_id,
        type=record.type,
        created_at=record.created_at,
        updated_at=record.updated_at,
        status=record.status,
        input_summary=record.input_summary,
        event_count=len(record.events),
    )
    return {"filename": filename, **json.loads(summary.model_dump_json())}


def create_session(session_type: str, input_summary: InputSummary) -> str:
    now = datetime.now(timezone.utc)
    session_id = str(uuid.uuid4())
    record = SessionRecord(
        session_id=session_id,
        type=session_type,
        created_at=now,
        updated_at=now,
        status="in_progress",
        input_summary=input_summary,
    )
    filename = _session_filename(now, session_id)
    with _lock:
        _SESSION_DIR.mkdir(parents=True, exist_ok=True)
        (_SESSION_DIR / filename).write_text(
            record.model_dump_json(indent=2), encoding="utf-8"
        )
        index = _read_index()
        index[session_id] = _to_index_entry(record, filename)
        _write_index(index)
    return session_id


def append_event(session_id: str, event: EventRecord) -> None:
    with _lock:
        index = _read_index()
        entry = index.get(session_id)
        if not entry:
            raise KeyError(session_id)
        filepath = _SESSION_DIR / entry["filename"]
        record = SessionRecord.model_validate_json(filepath.read_text(encoding="utf-8"))
        record.events.append(event)
        record.updated_at = datetime.now(timezone.utc)
        filepath.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        index[session_id] = _to_index_entry(record, entry["filename"])
        _write_index(index)


def complete_session(
    session_id: str,
    status: str,
    result_snapshot: dict | None = None,
) -> None:
    with _lock:
        index = _read_index()
        entry = index.get(session_id)
        if not entry:
            raise KeyError(session_id)
        filepath = _SESSION_DIR / entry["filename"]
        record = SessionRecord.model_validate_json(filepath.read_text(encoding="utf-8"))
        record.status = status  # type: ignore[assignment]
        record.result_snapshot = result_snapshot
        record.updated_at = datetime.now(timezone.utc)
        filepath.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        index[session_id] = _to_index_entry(record, entry["filename"])
        _write_index(index)


def get_all_sessions() -> list[SessionSummary]:
    index = _read_index()
    summaries: list[SessionSummary] = []
    for entry in index.values():
        try:
            data = {k: v for k, v in entry.items() if k != "filename"}
            summaries.append(SessionSummary.model_validate(data))
        except Exception:
            continue
    summaries.sort(key=lambda s: s.created_at, reverse=True)
    return summaries


def get_session(session_id: str) -> SessionRecord:
    index = _read_index()
    entry = index.get(session_id)
    if not entry:
        raise KeyError(session_id)
    filepath = _SESSION_DIR / entry["filename"]
    return SessionRecord.model_validate_json(filepath.read_text(encoding="utf-8"))


def delete_session(session_id: str) -> None:
    with _lock:
        index = _read_index()
        entry = index.pop(session_id, None)
        if entry is None:
            raise KeyError(session_id)
        filepath = _SESSION_DIR / entry["filename"]
        if filepath.exists():
            filepath.unlink()
        _write_index(index)

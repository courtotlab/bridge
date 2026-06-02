import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EventRecord(BaseModel):
    timestamp: datetime
    actor: Literal["user", "system"]
    event_type: str
    payload: dict


class InputSummary(BaseModel):
    filename: str | None = None
    row_count: int | None = None
    term: str | None = None
    codes: list[str] | None = None
    clinical_area: str | None = None
    target_ontology: str | None = None
    auto_accept_threshold: float | None = None


class SessionRecord(BaseModel):
    session_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    type: Literal["validation", "term_search", "batch_map"]
    created_at: datetime
    updated_at: datetime
    status: Literal["in_progress", "complete", "error"]
    input_summary: InputSummary
    events: list[EventRecord] = Field(default_factory=list)
    result_snapshot: dict | None = None


class SessionSummary(BaseModel):
    session_id: str
    type: Literal["validation", "term_search", "batch_map"]
    created_at: datetime
    updated_at: datetime
    status: Literal["in_progress", "complete", "error"]
    input_summary: InputSummary
    event_count: int

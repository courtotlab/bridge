import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.utils.ontology import normalize_target_ontologies


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
    target_ontologies: list[str] | None = None
    target_ontology: str | None = Field(default=None, exclude=True)
    auto_accept_threshold: float | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_ontology_metadata(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        try:
            if normalized.get("target_ontologies") is not None:
                normalized["target_ontologies"] = normalize_target_ontologies(
                    normalized.get("target_ontologies")
                )
            elif normalized.get("target_ontology") is not None:
                normalized["target_ontologies"] = normalize_target_ontologies(
                    normalized.get("target_ontology")
                )
        except TypeError as exc:
            raise ValueError(str(exc)) from exc
        return normalized


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

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.mapping import AlternativeResult, BatchRowResult, SingleMappingResponse
from app.models.validator import ValidateResult
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
    target_ontology_column: str | None = None
    target_ontologies: list[str] | None = None
    target_ontology: str | None = Field(default=None, exclude=True)
    auto_accept_threshold: float | None = None
    strict_target_ontology: bool | None = None

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
    status: Literal["in_progress", "complete", "error", "interrupted"]
    input_summary: InputSummary
    events: list[EventRecord] = Field(default_factory=list)
    result_snapshot: dict | None = None


class SessionSummary(BaseModel):
    session_id: str
    type: Literal["validation", "term_search", "batch_map"]
    created_at: datetime
    updated_at: datetime
    status: Literal["in_progress", "complete", "error", "interrupted"]
    input_summary: InputSummary
    event_count: int


class HistoryConfiguration(BaseModel):
    target_ontologies: list[str] | None = None
    target_ontology_column: str | None = None
    auto_accept_threshold: float | None = None
    retrieval_method: str | None = None
    provider: str | None = None
    model: str | None = None
    rag_enabled: bool | None = None
    strict_target_ontology: bool | None = None


class HistoryFailure(BaseModel):
    message: str | None = None


class HistoryBaseDetails(BaseModel):
    id: str
    type: Literal["validation", "term_search", "batch_map"]
    status: Literal["in_progress", "complete", "error", "interrupted"]
    created_at: datetime
    completed_at: datetime | None = None
    input: dict[str, Any] = Field(default_factory=dict)
    configuration: HistoryConfiguration | None = None
    failure: HistoryFailure | None = None
    legacy_message: str | None = None


class TermSearchHistoryResult(BaseModel):
    best_match: SingleMappingResponse | None = None
    alternatives: list[AlternativeResult] = Field(default_factory=list)


class TermSearchHistoryDetails(HistoryBaseDetails):
    type: Literal["term_search"] = "term_search"
    result: TermSearchHistoryResult = Field(default_factory=TermSearchHistoryResult)


class BatchMapSummary(BaseModel):
    total_rows: int | None = None
    completed_count: int | None = None
    accepted_count: int = 0
    pending_count: int = 0
    rejected_count: int = 0
    unmapped_count: int = 0


class BatchMapHistoryResult(BaseModel):
    total: int | None = None
    completed: int | None = None
    status: str | None = None
    rows: list[BatchRowResult] = Field(default_factory=list)
    summary: BatchMapSummary = Field(default_factory=BatchMapSummary)
    error: str | None = None


class BatchMapHistoryDetails(HistoryBaseDetails):
    type: Literal["batch_map"] = "batch_map"
    result: BatchMapHistoryResult = Field(default_factory=BatchMapHistoryResult)


class ValidationSummary(BaseModel):
    total_count: int = 0
    valid_count: int = 0
    deprecated_count: int = 0
    not_found_count: int = 0
    error_count: int = 0


class ValidationHistoryResult(BaseModel):
    results: list[ValidateResult] = Field(default_factory=list)
    summary: ValidationSummary = Field(default_factory=ValidationSummary)


class ValidationHistoryDetails(HistoryBaseDetails):
    type: Literal["validation"] = "validation"
    result: ValidationHistoryResult = Field(default_factory=ValidationHistoryResult)


HistoryDetails = TermSearchHistoryDetails | BatchMapHistoryDetails | ValidationHistoryDetails

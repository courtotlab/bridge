from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from app.utils.ontology import normalize_target_ontologies


class SingleMappingRequest(BaseModel):
    source_term: str
    source_label: str | None = None
    source_type: str | None = None  # data type: numeric, text, boolean, etc.
    entity_type: str | None = None  # clinical area: phenotype, disease, etc.
    target_ontologies: list[str] | None = None  # None = automatic routing

    @field_validator("source_term")
    @classmethod
    def source_term_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source_term must not be empty")
        return v

    @field_validator("target_ontologies", mode="before")
    @classmethod
    def normalize_target_ontologies_field(cls, v):
        try:
            return normalize_target_ontologies(v)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc


class AlternativeResult(BaseModel):
    code: str
    term: str
    ontology: str
    confidence: float
    source: str | None = None  # "llm" | "rag" | "direct"
    explanation: str | None = None


class MappingMetadata(BaseModel):
    model: str
    provider: str
    latency_ms: float | None = None
    timestamp: datetime | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class SingleMappingResponse(BaseModel):
    source_term: str
    source_label: str | None = None
    source_type: str | None = None
    target_code: str
    target_term: str
    ontology: str
    confidence: float
    logic_type: str
    notes: str | None = None
    alternatives: list[AlternativeResult] = []
    metadata: MappingMetadata | None = None
    configured_provider: str | None = None
    configured_model: str | None = None
    retrieval_mode: str | None = None


class BatchMappingRequest(BaseModel):
    column_map: dict  # keys: field_name, label, description, data_type (values are CSV column names or None)
    clinical_area: str | None = None
    target_ontology_column: str | None = None
    target_ontologies: list[str] | None = None
    auto_accept_threshold: float = 0.85

    @field_validator("target_ontologies", mode="before")
    @classmethod
    def normalize_target_ontologies_field(cls, v):
        try:
            return normalize_target_ontologies(v)
        except TypeError as exc:
            raise ValueError(str(exc)) from exc


class BatchRowResult(BaseModel):
    row_index: int
    field_name: str
    label: str | None = None
    source_description: str | None = None
    original_row: dict[str, Any] = Field(default_factory=dict)
    original_columns: list[str] = Field(default_factory=list)
    requested_target_ontology: str | None = None
    suggested_code: str
    suggested_term: str
    ontology: str
    confidence: float
    logic_type: str
    decision: str = "pending"  # "accepted" | "rejected" | "pending"
    alternatives: list[AlternativeResult] = []
    notes: str | None = None
    configured_provider: str | None = None
    configured_model: str | None = None
    retrieval_mode: str | None = None


class BatchMappingResponse(BaseModel):
    job_id: str
    total: int
    completed: int
    results: list[BatchRowResult]
    status: Literal["running", "done", "interrupted", "failed"]
    error: str | None = None

from datetime import datetime

from pydantic import BaseModel, field_validator


class SingleMappingRequest(BaseModel):
    source_term: str
    source_label: str | None = None
    source_type: str | None = None       # data type: numeric, text, boolean, etc.
    entity_type: str | None = None       # clinical area: phenotype, disease, etc.
    target_ontologies: str | None = None # None = auto-detect

    @field_validator("source_term")
    @classmethod
    def source_term_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source_term must not be empty")
        return v


class AlternativeResult(BaseModel):
    code: str
    term: str
    ontology: str
    confidence: float
    source: str | None = None  # "llm" | "rag" | "direct"


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

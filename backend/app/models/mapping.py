from pydantic import BaseModel, field_validator


class SingleMappingRequest(BaseModel):
    source_term: str
    source_label: str | None = None
    entity_type: str | None = None

    @field_validator("source_term")
    @classmethod
    def source_term_must_not_be_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source_term must not be empty")
        return v


class MappingAlternative(BaseModel):
    code: str
    term: str
    ontology: str
    confidence: float


class SingleMappingResponse(BaseModel):
    source_term: str
    target_code: str
    target_term: str
    ontology: str
    confidence: float
    notes: str
    alternatives: list[MappingAlternative]

from pydantic import BaseModel, Field


class ConfigTestRequest(BaseModel):
    provider: str
    model: str
    base_url: str | None = None
    use_retrieval_grounding: bool
    selected_ontologies: list[str]
    confidence_threshold: float = Field(ge=0.0, le=1.0)


class ConfigTestResponse(BaseModel):
    success: bool
    message: str

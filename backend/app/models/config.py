from typing import Literal

from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    # Layer 1 — NER extraction
    use_ner: bool = True

    # Layer 2 — Candidate retrieval
    retrieval_mode: Literal["public", "local", "disabled"] = "public"
    bioportal_api_key: str | None = None  # in-memory only, not saved to disk
    loinc_username: str | None = None
    loinc_password: str | None = None  # in-memory only, never saved to disk
    sapbert_server_url: str = "http://localhost:8000"
    rag_auto_accept_threshold: float = Field(default=0.85, ge=0.0, le=1.0)

    # Layer 3 — AI model
    provider: Literal["ollama", "ollama_cloud", "openai", "anthropic"] = "ollama"
    model: str = "llama3.2"
    base_url: str = "http://localhost:11434"
    api_key: str | None = None  # in-memory only, never saved to disk


class LayerStatus(BaseModel):
    layer1: Literal["ok", "warning", "disabled", "error"]
    layer2: Literal["ok", "warning", "disabled", "error"]
    layer3: Literal["ok", "warning", "disabled", "error"]


class ConfigStatusResponse(BaseModel):
    config: AppConfig
    status: LayerStatus


class ComponentTestResult(BaseModel):
    valid: bool
    status: str
    code: str
    message: str


class ConnectionTestResponse(BaseModel):
    success: bool
    message: str
    candidate_retrieval: ComponentTestResult | None = None
    ai_model: ComponentTestResult | None = None
    latency_ms: int | None = None
    available_models: list[str] | None = None
    validation_level: str | None = None  # 'api_key' | 'generation' | 'reachability'
    sapbert_status: str | None = None  # 'ok' | 'unreachable' | 'skipped'
    sapbert_message: str | None = None
    provider_ok: bool | None = None
    api_key_ok: bool | None = None
    model_ok: bool | None = None
    error_type: str | None = (
        None  # invalid_api_key, subscription_required, model_unavailable, ...
    )
    warning: str | None = None  # inference_timeout
    resident_model: str | None = (
        None  # ollama only: model currently loaded in VRAM (/api/ps)
    )


class ModelsListResponse(BaseModel):
    models: list[str]
    warning: str | None = None
    error: str | None = None

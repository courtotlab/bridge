import time

import requests as _requests
from fastapi import APIRouter, HTTPException

from app.models.config import AppConfig, ConfigStatusResponse, ConnectionTestResponse
from app.storage.config_store import load_config, save_config
from app.utils.error_translator import translate
from app.utils.layer_status import compute_layer_status

router = APIRouter()


# ── Config CRUD ───────────────────────────────────────────────────────────────

@router.get("", response_model=AppConfig)
def get_config() -> AppConfig:
    return load_config()


@router.post("", response_model=AppConfig)
def post_config(config: AppConfig) -> AppConfig:
    save_config(config)
    return load_config()


# ── Layer status ──────────────────────────────────────────────────────────────

@router.get("/status", response_model=ConfigStatusResponse)
def get_status() -> ConfigStatusResponse:
    config = load_config()
    return ConfigStatusResponse(config=config, status=compute_layer_status(config))


# ── Ollama model discovery ────────────────────────────────────────────────────

@router.get("/ollama-models", response_model=list[str])
def get_ollama_models() -> list[str]:
    config = load_config()
    tags_url = config.base_url.rstrip("/") + "/api/tags"
    try:
        resp = _requests.get(tags_url, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        return [m["name"] for m in data.get("models", [])]
    except Exception as exc:
        raise HTTPException(status_code=503, detail=translate(exc, config.base_url)) from exc


# ── Connection test ───────────────────────────────────────────────────────────

@router.post("/test", response_model=ConnectionTestResponse)
def test_connection() -> ConnectionTestResponse:
    config = load_config()
    print(f"[config/test] hit — provider={config.provider!r} model={config.model!r}", flush=True)
    provider = config.provider

    if provider in ("ollama", "ollama_cloud"):
        return _test_ollama(config)
    if provider == "openai":
        return _test_openai(config)
    if provider == "anthropic":
        return _test_anthropic(config)

    raise HTTPException(status_code=422, detail=f"Unknown provider: {provider}")


def _test_ollama(config: AppConfig) -> ConnectionTestResponse:
    tags_url = config.base_url.rstrip("/") + "/api/tags"
    t0 = time.monotonic()
    try:
        resp = _requests.get(tags_url, timeout=5)
        resp.raise_for_status()
        latency_ms = int((time.monotonic() - t0) * 1000)
        data = resp.json()
        available = [m["name"] for m in data.get("models", [])]
        return ConnectionTestResponse(
            success=True,
            message=f"Connection OK — {config.model} is ready.",
            latency_ms=latency_ms,
            available_models=available,
        )
    except Exception as exc:
        return ConnectionTestResponse(
            success=False,
            message=translate(exc, config.base_url),
        )


def _test_openai(config: AppConfig) -> ConnectionTestResponse:
    try:
        import openai as _openai
    except ImportError:
        return ConnectionTestResponse(success=False, message="openai package not installed.")

    api_key = config.api_key
    if not api_key:
        return ConnectionTestResponse(success=False, message="No OpenAI API key set — save your settings first.")

    t0 = time.monotonic()
    try:
        client = _openai.OpenAI(api_key=api_key, timeout=5.0)
        client.models.list()
        latency_ms = int((time.monotonic() - t0) * 1000)
        return ConnectionTestResponse(
            success=True,
            message="OpenAI connection OK.",
            latency_ms=latency_ms,
        )
    except _openai.AuthenticationError:
        return ConnectionTestResponse(success=False, message="Invalid OpenAI API key.")
    except Exception as exc:
        return ConnectionTestResponse(
            success=False,
            message=translate(exc, "OpenAI"),
        )


def _test_anthropic(config: AppConfig) -> ConnectionTestResponse:
    try:
        import anthropic as _anthropic
    except ImportError:
        return ConnectionTestResponse(success=False, message="anthropic package not installed.")

    api_key = config.api_key
    if not api_key:
        return ConnectionTestResponse(success=False, message="No Anthropic API key set — save your settings first.")

    t0 = time.monotonic()
    try:
        client = _anthropic.Anthropic(api_key=api_key, timeout=5.0)
        client.models.list()
        latency_ms = int((time.monotonic() - t0) * 1000)
        return ConnectionTestResponse(
            success=True,
            message="Anthropic connection OK.",
            latency_ms=latency_ms,
        )
    except _anthropic.AuthenticationError:
        return ConnectionTestResponse(success=False, message="Invalid Anthropic API key.")
    except Exception as exc:
        return ConnectionTestResponse(
            success=False,
            message=translate(exc, "Anthropic"),
        )

import time

import requests as _requests
from fastapi import APIRouter, HTTPException

from app.models.config import AppConfig, ConfigStatusResponse, ConnectionTestResponse, ModelsListResponse
from app.storage.config_store import (
    cache_api_key,
    get_sensitive,
    invalidate_connection_test,
    invalidate_retrieval_validation,
    load_config,
    save_config,
    set_connection_result,
    set_retrieval_result,
)
from app.utils.cloud_validation import (
    anthropic_chat_error_response,
    filter_openai_models,
    invalid_api_key_response,
    is_openai_chat_model,
    model_failure_response,
    model_validated_success,
    models_discovered_response,
    openai_chat_error_response,
    provider_validated_response,
)
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
    invalidate_connection_test()
    invalidate_retrieval_validation()
    return load_config()


# ── Layer status ──────────────────────────────────────────────────────────────

@router.get("/status", response_model=ConfigStatusResponse)
def get_status() -> ConfigStatusResponse:
    config = load_config()
    return ConfigStatusResponse(config=config, status=compute_layer_status(config))


# ── Model discovery ───────────────────────────────────────────────────────────

_OPENAI_FALLBACK = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o3-mini"]
_ANTHROPIC_FALLBACK = [
    "claude-opus-4-20250514",
    "claude-sonnet-4-20250514",
    "claude-haiku-4-5-20251001",
]
_MODELS_FETCH_WARNING = (
    "Could not fetch live model list — showing defaults. "
    "Check your API key if this is unexpected."
)
@router.get("/openai-models", response_model=ModelsListResponse)
def get_openai_models() -> ModelsListResponse:
    try:
        import openai as _openai
    except ImportError:
        return ModelsListResponse(models=_OPENAI_FALLBACK, warning=_MODELS_FETCH_WARNING)

    api_key = get_sensitive("api_key")
    if not api_key:
        return ModelsListResponse(
            models=[],
            error="No API key set — enter your key and test connection first",
        )

    try:
        client = _openai.OpenAI(api_key=api_key, timeout=5.0)
        all_models = client.models.list()
        return ModelsListResponse(models=filter_openai_models(all_models))
    except _openai.AuthenticationError:
        return ModelsListResponse(models=[], error="Invalid OpenAI API key")
    except Exception:
        return ModelsListResponse(models=_OPENAI_FALLBACK, warning=_MODELS_FETCH_WARNING)


@router.get("/anthropic-models", response_model=ModelsListResponse)
def get_anthropic_models() -> ModelsListResponse:
    try:
        import anthropic as _anthropic
    except ImportError:
        return ModelsListResponse(models=_ANTHROPIC_FALLBACK, warning=_MODELS_FETCH_WARNING)

    api_key = get_sensitive("api_key")
    if not api_key:
        return ModelsListResponse(
            models=[],
            error="No API key set — enter your key and test connection first",
        )

    try:
        client = _anthropic.Anthropic(api_key=api_key, timeout=5.0)
        models_page = client.models.list(limit=100)
        model_ids = sorted(m.id for m in models_page.data)
        return ModelsListResponse(models=model_ids)
    except _anthropic.AuthenticationError:
        return ModelsListResponse(models=[], error="Invalid Anthropic API key")
    except Exception:
        return ModelsListResponse(models=_ANTHROPIC_FALLBACK, warning=_MODELS_FETCH_WARNING)


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
def test_connection(body: AppConfig | None = None) -> ConnectionTestResponse:
    # Body takes precedence so the frontend can pass unsaved state (e.g. api_key).
    # Fall back to on-disk config merged with in-memory sensitive fields.
    config = body if body is not None else load_config()
    print(
        f"[config/test] hit — provider={config.provider!r} model={config.model!r} "
        f"api_key={'set' if config.api_key else 'not set'}",
        flush=True,
    )
    provider = config.provider

    if provider == "ollama":
        result = _test_ollama(config)
    elif provider == "ollama_cloud":
        result = _test_ollama_cloud(config)
    elif provider == "openai":
        result = _test_openai(config)
    elif provider == "anthropic":
        result = _test_anthropic(config)
    else:
        raise HTTPException(status_code=422, detail=f"Unknown provider: {provider}")

    set_connection_result(
        result.success,
        api_key_ok=result.api_key_ok,
        model_ok=result.model_ok,
    )
    if result.api_key_ok and config.api_key:
        cache_api_key(config.api_key)

    if result.success:
        sapbert_status, sapbert_message = _check_sapbert(config)
        result.sapbert_status = sapbert_status
        result.sapbert_message = sapbert_message
        _apply_retrieval_validation(config, sapbert_status)

    return result


def _apply_retrieval_validation(config: AppConfig, sapbert_status: str) -> None:
    """Update Layer 2 state from SapBERT probe; LLM test alone does not validate public retrieval."""
    if config.retrieval_mode == "disabled":
        return
    if config.retrieval_mode == "local":
        set_retrieval_result(sapbert_status == "ok")
    # public: no automatic ok — remains untested until a dedicated retrieval check exists


def _check_sapbert(config: AppConfig) -> tuple[str, str | None]:
    if config.retrieval_mode != "local":
        return "skipped", None
    base = config.sapbert_server_url.rstrip("/")
    for path in ("/health", ""):
        try:
            resp = _requests.get(base + path, timeout=5)
            if resp.status_code < 400:
                return "ok", None
        except Exception:
            pass
    msg = f"Could not reach SapBERT server at {base} — is it running?"
    return "unreachable", msg


def _test_ollama(config: AppConfig) -> ConnectionTestResponse:
    base_url = config.base_url.rstrip("/")
    tags_url = base_url + "/api/tags"

    print(f"[config/test] ollama local → {tags_url}", flush=True)

    # Step 1 — Server reachability
    t0 = time.monotonic()
    try:
        tags_resp = _requests.get(tags_url, timeout=5)
        tags_resp.raise_for_status()
        data = tags_resp.json()
        available = [m["name"] for m in data.get("models", [])]
        models_preview = ", ".join(available[:5])
        print(
            f"[config/test] ollama local ← status={tags_resp.status_code} "
            f"models_found={len(available)}: {models_preview}",
            flush=True,
        )
    except Exception:
        return ConnectionTestResponse(
            success=False,
            message=(
                f"Could not reach Ollama at {base_url} — is it running? "
                "If using an SSH tunnel, check that the tunnel is active."
            ),
            provider_ok=False,
            api_key_ok=None,
            model_ok=False,
            error_type="network_error",
        )

    # Step 2 — At least one model must exist
    if not available:
        return ConnectionTestResponse(
            success=False,
            message=(
                f"Ollama is running at {base_url} but no models are available. "
                "Run ollama pull <model> to download one."
            ),
            provider_ok=True,
            api_key_ok=None,
            model_ok=False,
            error_type="model_unavailable",
        )

    # Step 3 — Inference test using the first available model
    first_model = available[0]
    chat_url = base_url + "/api/chat"
    payload = {
        "model": first_model,
        "messages": [{"role": "user", "content": "Reply with only OK"}],
        "stream": False,
    }
    print(
        f"[config/test] ollama local inference test → model={first_model!r} (first available)",
        flush=True,
    )
    try:
        chat_resp = _requests.post(chat_url, json=payload, timeout=30)
    except _requests.Timeout:
        latency_ms = int((time.monotonic() - t0) * 1000)
        print(
            f"[config/test] ollama local inference test ← TIMEOUT latency={latency_ms}ms",
            flush=True,
        )
        return ConnectionTestResponse(
            success=False,
            message=(
                "Ollama responded but inference timed out — "
                "the model may still be loading. Try again in a moment."
            ),
            available_models=available,
            provider_ok=True,
            api_key_ok=None,
            model_ok=False,
            error_type="network_error",
        )
    except Exception as exc:
        return ConnectionTestResponse(
            success=False,
            message=translate(exc, base_url),
            available_models=available,
            provider_ok=True,
            api_key_ok=None,
            model_ok=False,
            error_type="network_error",
        )

    latency_ms = int((time.monotonic() - t0) * 1000)
    print(
        f"[config/test] ollama local inference test ← status={chat_resp.status_code} latency={latency_ms}ms",
        flush=True,
    )

    if not chat_resp.ok:
        try:
            body_msg = chat_resp.json().get("error") or chat_resp.text
        except Exception:
            body_msg = chat_resp.text
        return ConnectionTestResponse(
            success=False,
            message=f"Ollama inference failed — {body_msg[:200]}",
            available_models=available,
            provider_ok=True,
            api_key_ok=None,
            model_ok=False,
            error_type="unknown",
        )

    # Step 4 — Return success with full model list
    n = len(available)
    return model_validated_success(
        message=f"Connection OK — {n} model{'s' if n != 1 else ''} available.",
        available_models=available,
        latency_ms=latency_ms,
    )


_OLLAMA_CLOUD_BASE = "https://ollama.com"
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0"}


def _ollama_cloud_base(config: AppConfig) -> str:
    """Return the canonical Ollama Cloud base URL, ignoring any local address."""
    raw = config.base_url.rstrip("/")
    try:
        from urllib.parse import urlparse
        host = urlparse(raw).hostname or ""
    except Exception:
        host = ""
    if not raw or host in _LOCAL_HOSTS:
        return _OLLAMA_CLOUD_BASE
    return raw


def _ollama_cloud_auth_headers(api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _ollama_cloud_invalid_key_response() -> ConnectionTestResponse:
    return invalid_api_key_response("ollama_cloud")


def _ollama_cloud_fetch_tags(
    base: str, api_key: str
) -> tuple[list[str], ConnectionTestResponse | None]:
    """List cloud models and validate the API key via /api/tags. Returns (models, error)."""
    tags_url = base + "/api/tags"
    try:
        tags_resp = _requests.get(
            tags_url,
            headers=_ollama_cloud_auth_headers(api_key),
            timeout=5,
        )
        print(
            f"[config/test] ollama_cloud /api/tags ← status={tags_resp.status_code}  "
            f"body={tags_resp.text[:200]!r}",
            flush=True,
        )
        tags_resp.raise_for_status()
        data = tags_resp.json()
        available = [m["name"] for m in data.get("models", [])]
        return available, None
    except _requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        if status in (401, 403):
            return [], _ollama_cloud_invalid_key_response()
        return [], ConnectionTestResponse(
            success=False,
            message=f"Ollama Cloud /api/tags returned HTTP {status}.",
            provider_ok=False,
            api_key_ok=False,
            model_ok=False,
            error_type="unknown",
        )
    except Exception as exc:
        return [], ConnectionTestResponse(
            success=False,
            message=translate(exc, base),
            provider_ok=False,
            api_key_ok=False,
            model_ok=False,
            error_type="network_error",
        )


def _test_ollama_cloud(config: AppConfig) -> ConnectionTestResponse:
    api_key = config.api_key
    base = _ollama_cloud_base(config)
    model = config.model.strip() if config.model else ""

    print(
        f"[config/test] provider=ollama_cloud  base={base!r}  "
        f"model={model!r}  api_key={'set' if api_key else 'not set'}",
        flush=True,
    )

    if not api_key:
        return ConnectionTestResponse(
            success=False,
            message="No Ollama Cloud API key set — save your settings first.",
            provider_ok=False,
            api_key_ok=False,
            model_ok=False,
            error_type="invalid_api_key",
        )

    t0 = time.monotonic()
    available, tags_error = _ollama_cloud_fetch_tags(base, api_key)
    if tags_error is not None:
        return tags_error

    # Model discovery only — /api/tags does not prove the API key; require /api/chat to verify
    if not model:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return models_discovered_response(
            message="Ollama Cloud model catalog loaded. Select a model to verify API access.",
            available_models=available,
            latency_ms=latency_ms,
        )

    chat_url = base + "/api/chat"
    headers = _ollama_cloud_auth_headers(api_key)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with only OK."}],
        "stream": False,
    }
    print(f"[config/test] ollama_cloud /api/chat → model={model!r}", flush=True)
    try:
        chat_resp = _requests.post(chat_url, json=payload, headers=headers, timeout=30)
        print(
            f"[config/test] ollama_cloud /api/chat ← status={chat_resp.status_code}  "
            f"body={chat_resp.text[:200]!r}",
            flush=True,
        )
        chat_resp.raise_for_status()
        latency_ms = int((time.monotonic() - t0) * 1000)
        return model_validated_success(
            message=f"Ollama Cloud API key valid and selected model is usable — {model} responded.",
            available_models=available,
            latency_ms=latency_ms,
        )
    except _requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        body = exc.response.text.lower() if exc.response is not None else ""
        print(
            f"[config/test] ollama_cloud chat error_type=classified  status={status}",
            flush=True,
        )
        if status == 401:
            return invalid_api_key_response("ollama_cloud")
        if status in (403, 402) and ("subscription" in body or "upgrade" in body):
            return model_failure_response(
                message=(
                    "Your API key is valid, but this model requires a subscription upgrade. "
                    "Select a different model from the dropdown and test again."
                ),
                available_models=available,
                error_type="subscription_required",
            )
        if status in (403, 402):
            return model_failure_response(
                message=(
                    "Your API key is valid, but this model is not available for your account. "
                    "Select a different model."
                ),
                available_models=available,
                error_type="model_unavailable",
            )
        return model_failure_response(
            message=(
                "Your API key is valid, but this model is not available for your account. "
                "Select a different model."
            ),
            available_models=available,
            error_type="model_unavailable",
        )
    except Exception as exc:
        return model_failure_response(
            message=translate(exc, base),
            available_models=available,
            error_type="network_error",
        )


def _test_openai(config: AppConfig) -> ConnectionTestResponse:
    try:
        import openai as _openai
    except ImportError:
        return ConnectionTestResponse(success=False, message="openai package not installed.")

    api_key = config.api_key
    model = config.model.strip() if config.model else ""
    print(
        f"[config/test] openai phase=provider  model={model!r}  "
        f"api_key={'set' if api_key else 'not set'}",
        flush=True,
    )

    if not api_key:
        return ConnectionTestResponse(
            success=False,
            message="No OpenAI API key set — save your settings first.",
            provider_ok=False,
            api_key_ok=False,
            model_ok=None,
            error_type="invalid_api_key",
        )

    t0 = time.monotonic()

    try:
        client = _openai.OpenAI(api_key=api_key, timeout=10.0)
        models_result = client.models.list()
        available = filter_openai_models(models_result)
        print(
            f"[config/test] openai models.list ← ok  count={len(available)}",
            flush=True,
        )
    except _openai.AuthenticationError as exc:
        print(f"[config/test] openai models.list ← error_type=invalid_api_key  {type(exc).__name__}", flush=True)
        return invalid_api_key_response("openai")
    except Exception as exc:
        print(f"[config/test] openai models.list ← error  {type(exc).__name__}", flush=True)
        return ConnectionTestResponse(
            success=False,
            message=translate(exc, "OpenAI"),
            provider_ok=False,
            api_key_ok=False,
            model_ok=None,
            error_type="network_error",
        )

    if not model:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return provider_validated_response(
            provider="openai",
            message="OpenAI API key is valid. Select a model to test it.",
            available_models=available,
            latency_ms=latency_ms,
        )

    if model not in available and not is_openai_chat_model(model):
        return model_failure_response(
            message="This model is not supported by this app. Please choose a text/chat model from the dropdown.",
            available_models=available,
            error_type="model_not_supported",
        )

    print(f"[config/test] openai phase=model  model={model!r}", flush=True)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with only OK."}],
            max_tokens=5,
            timeout=30.0,
        )
        text = response.choices[0].message.content or ""
        print(f"[config/test] openai chat ← ok  response={text[:80]!r}", flush=True)
    except Exception as exc:
        print(f"[config/test] openai chat ← error  {type(exc).__name__}", flush=True)
        return openai_chat_error_response(exc, available)

    latency_ms = int((time.monotonic() - t0) * 1000)
    return model_validated_success(
        message="OpenAI API key valid and selected model is usable.",
        available_models=available,
        latency_ms=latency_ms,
    )


def _test_anthropic(config: AppConfig) -> ConnectionTestResponse:
    try:
        import anthropic as _anthropic
    except ImportError:
        return ConnectionTestResponse(success=False, message="anthropic package not installed.")

    api_key = config.api_key
    model = config.model.strip() if config.model else ""
    print(
        f"[config/test] anthropic phase=provider  model={model!r}  "
        f"api_key={'set' if api_key else 'not set'}",
        flush=True,
    )

    if not api_key:
        return ConnectionTestResponse(
            success=False,
            message="No Anthropic API key set — save your settings first.",
            provider_ok=False,
            api_key_ok=False,
            model_ok=None,
            error_type="invalid_api_key",
        )

    t0 = time.monotonic()

    try:
        client = _anthropic.Anthropic(api_key=api_key, timeout=10.0)
        models_page = client.models.list(limit=100)
        available = sorted(m.id for m in models_page.data)
        print(
            f"[config/test] anthropic models.list ← ok  count={len(available)}",
            flush=True,
        )
    except _anthropic.AuthenticationError as exc:
        print(f"[config/test] anthropic models.list ← error_type=invalid_api_key  {type(exc).__name__}", flush=True)
        return invalid_api_key_response("anthropic")
    except Exception as exc:
        print(f"[config/test] anthropic models.list ← error  {type(exc).__name__}", flush=True)
        return ConnectionTestResponse(
            success=False,
            message=translate(exc, "Anthropic"),
            provider_ok=False,
            api_key_ok=False,
            model_ok=None,
            error_type="network_error",
        )

    if not model:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return provider_validated_response(
            provider="anthropic",
            message="Anthropic API key is valid. Select a model to test it.",
            available_models=available,
            latency_ms=latency_ms,
        )

    print(f"[config/test] anthropic phase=model  model={model!r}", flush=True)
    try:
        response = client.messages.create(
            model=model,
            max_tokens=5,
            messages=[{"role": "user", "content": "Reply with only OK."}],
        )
        text = response.content[0].text if response.content else ""
        print(f"[config/test] anthropic chat ← ok  response={text[:80]!r}", flush=True)
    except Exception as exc:
        print(f"[config/test] anthropic chat ← error  {type(exc).__name__}", flush=True)
        return anthropic_chat_error_response(exc, available)

    latency_ms = int((time.monotonic() - t0) * 1000)
    return model_validated_success(
        message="Anthropic API key valid and selected model is usable.",
        available_models=available,
        latency_ms=latency_ms,
    )

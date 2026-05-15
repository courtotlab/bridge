import time

import requests as _requests
from fastapi import APIRouter, HTTPException

from app.models.config import AppConfig, ConfigStatusResponse, ConnectionTestResponse, ModelsListResponse
from app.storage.config_store import (
    cache_api_key,
    get_sensitive,
    invalidate_connection_test,
    load_config,
    save_config,
    set_connection_result,
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
        filtered = sorted(
            m.id for m in all_models.data
            if any(kw in m.id for kw in ("gpt", "o1", "o3", "o4"))
        )
        return ModelsListResponse(models=filtered)
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

    set_connection_result(result.success)
    if result.success and config.api_key:
        cache_api_key(config.api_key)

    if result.success:
        sapbert_status, sapbert_message = _check_sapbert(config)
        result.sapbert_status = sapbert_status
        result.sapbert_message = sapbert_message

    return result


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


def _test_ollama_cloud(config: AppConfig) -> ConnectionTestResponse:
    api_key = config.api_key
    base = _ollama_cloud_base(config)
    model = config.model.strip() if config.model else ""

    masked_key = (api_key[:4] + "...") if api_key and len(api_key) > 4 else "****"
    print(
        f"[config/test] provider=ollama_cloud  base={base!r}  "
        f"model={model!r}  key=Bearer {masked_key}",
        flush=True,
    )

    # ── Step 1: list available models via /api/tags (no auth required) ──────
    tags_url = base + "/api/tags"
    t0 = time.monotonic()
    try:
        tags_resp = _requests.get(tags_url, timeout=5)
        print(
            f"[config/test] ollama_cloud /api/tags ← status={tags_resp.status_code}  "
            f"body={tags_resp.text[:200]!r}",
            flush=True,
        )
        tags_resp.raise_for_status()
        data = tags_resp.json()
        available = [m["name"] for m in data.get("models", [])]
    except _requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        if status in (401, 403):
            return ConnectionTestResponse(
                success=False,
                message="Invalid Ollama Cloud API key — check your key and try again.",
            )
        return ConnectionTestResponse(
            success=False,
            message=f"Ollama Cloud /api/tags returned HTTP {status}.",
        )
    except Exception as exc:
        return ConnectionTestResponse(success=False, message=translate(exc, base))

    # ── Step 2: if no model selected, report reachability only ───────────────
    if not model:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return ConnectionTestResponse(
            success=True,
            message=(
                "Connected to Ollama Cloud. "
                "Select a model to test generation and API-key validity."
            ),
            latency_ms=latency_ms,
            available_models=available,
            validation_level="reachability",
        )

    # ── Step 3: validate API key via /api/chat generation ────────────────────
    if not api_key:
        return ConnectionTestResponse(
            success=False,
            message="No Ollama Cloud API key set — save your settings first.",
        )

    chat_url = base + "/api/chat"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with only OK."}],
        "stream": False,
    }
    print(
        f"[config/test] ollama_cloud /api/chat → model={model!r}  "
        f"Authorization=Bearer {masked_key}",
        flush=True,
    )
    try:
        chat_resp = _requests.post(chat_url, json=payload, headers=headers, timeout=30)
        print(
            f"[config/test] ollama_cloud /api/chat ← status={chat_resp.status_code}  "
            f"body={chat_resp.text[:200]!r}",
            flush=True,
        )
        chat_resp.raise_for_status()
        latency_ms = int((time.monotonic() - t0) * 1000)
        return ConnectionTestResponse(
            success=True,
            message=f"Ollama Cloud API key works — {model} responded.",
            latency_ms=latency_ms,
            available_models=available,
            validation_level="generation",
        )
    except _requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else "?"
        body = exc.response.text.lower() if exc.response is not None else ""
        if status == 403 and ("subscription" in body or "upgrade" in body):
            return ConnectionTestResponse(
                success=False,
                message=(
                    "Your API key is valid but this model requires a subscription upgrade. "
                    "Select a different model from the dropdown and test again."
                ),
            )
        return ConnectionTestResponse(
            success=False,
            message=f"Model '{model}' is not available on your account.",
        )
    except Exception as exc:
        return ConnectionTestResponse(success=False, message=translate(exc, base))


def _test_openai(config: AppConfig) -> ConnectionTestResponse:
    try:
        import openai as _openai
    except ImportError:
        return ConnectionTestResponse(success=False, message="openai package not installed.")

    api_key = config.api_key
    model = config.model.strip() if config.model else ""
    print(
        f"[config/test] hit — provider='openai' model={model!r} "
        f"api_key={'set' if api_key else 'not set'}",
        flush=True,
    )

    if not api_key:
        return ConnectionTestResponse(success=False, message="No OpenAI API key set — save your settings first.")

    t0 = time.monotonic()

    # Step 1: validate the API key via models.list()
    try:
        client = _openai.OpenAI(api_key=api_key, timeout=10.0)
        models_result = client.models.list()
        count = len(models_result.data) if hasattr(models_result, "data") else "?"
        print(f"[config/test] openai models.list() ← status=ok  count={count} models", flush=True)
    except _openai.AuthenticationError as exc:
        print(f"[config/test] openai error — {type(exc).__name__}: {exc}", flush=True)
        return ConnectionTestResponse(success=False, message="Invalid OpenAI API key")
    except Exception as exc:
        print(f"[config/test] openai error — {type(exc).__name__}: {exc}", flush=True)
        return ConnectionTestResponse(success=False, message=translate(exc, "OpenAI"))

    # Step 2: validate the specific model via a chat completion
    if model:
        print(f"[config/test] openai chat test → model={model!r}", flush=True)
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Reply with only OK."}],
                max_tokens=5,
                timeout=30.0,
            )
            text = response.choices[0].message.content or ""
            print(
                f"[config/test] openai chat test ← status=ok  response={text[:80]!r}",
                flush=True,
            )
        except _openai.PermissionDeniedError as exc:
            print(f"[config/test] openai error — {type(exc).__name__}: {exc}", flush=True)
            return ConnectionTestResponse(
                success=False,
                message=(
                    "Your API key is valid but you do not have access to this model. "
                    "Select a different model and test again."
                ),
            )
        except Exception as exc:
            print(
                f"[config/test] openai chat test ← status=error  response={str(exc)[:80]!r}",
                flush=True,
            )
            return ConnectionTestResponse(
                success=False,
                message=f"Model '{model}' is not available on your account.",
            )

    latency_ms = int((time.monotonic() - t0) * 1000)
    msg = f"OpenAI API key valid — {model} is accessible." if model else "OpenAI connection OK."
    return ConnectionTestResponse(success=True, message=msg, latency_ms=latency_ms)


def _test_anthropic(config: AppConfig) -> ConnectionTestResponse:
    try:
        import anthropic as _anthropic
    except ImportError:
        return ConnectionTestResponse(success=False, message="anthropic package not installed.")

    api_key = config.api_key
    model = config.model.strip() if config.model else ""
    print(
        f"[config/test] hit — provider='anthropic' model={model!r} "
        f"api_key={'set' if api_key else 'not set'}",
        flush=True,
    )

    if not api_key:
        return ConnectionTestResponse(success=False, message="No Anthropic API key set — save your settings first.")

    t0 = time.monotonic()

    # Step 1: validate the API key via models.list()
    try:
        client = _anthropic.Anthropic(api_key=api_key, timeout=10.0)
        models_page = client.models.list(limit=100)
        count = len(models_page.data) if hasattr(models_page, "data") else "?"
        print(f"[config/test] anthropic models.list() ← status=ok  count={count} models", flush=True)
    except _anthropic.AuthenticationError as exc:
        print(f"[config/test] anthropic error — {type(exc).__name__}: {exc}", flush=True)
        return ConnectionTestResponse(success=False, message="Invalid Anthropic API key")
    except Exception as exc:
        print(f"[config/test] anthropic error — {type(exc).__name__}: {exc}", flush=True)
        return ConnectionTestResponse(success=False, message=translate(exc, "Anthropic"))

    # Step 2: validate the specific model via a chat completion
    if model:
        print(f"[config/test] anthropic chat test → model={model!r}", flush=True)
        try:
            response = client.messages.create(
                model=model,
                max_tokens=5,
                messages=[{"role": "user", "content": "Reply with only OK."}],
            )
            text = response.content[0].text if response.content else ""
            print(
                f"[config/test] anthropic chat test ← status=ok  response={text[:80]!r}",
                flush=True,
            )
        except _anthropic.PermissionDeniedError as exc:
            print(f"[config/test] anthropic error — {type(exc).__name__}: {exc}", flush=True)
            return ConnectionTestResponse(
                success=False,
                message=(
                    "Your API key is valid but you do not have access to this model. "
                    "Select a different model and test again."
                ),
            )
        except Exception as exc:
            print(
                f"[config/test] anthropic chat test ← status=error  response={str(exc)[:80]!r}",
                flush=True,
            )
            return ConnectionTestResponse(
                success=False,
                message=f"Model '{model}' is not available on your account.",
            )

    latency_ms = int((time.monotonic() - t0) * 1000)
    msg = f"Anthropic API key valid — {model} is accessible." if model else "Anthropic connection OK."
    return ConnectionTestResponse(success=True, message=msg, latency_ms=latency_ms)

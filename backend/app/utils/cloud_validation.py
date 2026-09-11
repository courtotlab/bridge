"""Shared two-step validation for cloud LLM providers (OpenAI, Anthropic, Ollama Cloud)."""

from __future__ import annotations

from typing import Literal

from app.models.config import ConnectionTestResponse

ErrorType = Literal[
    "invalid_api_key",
    "model_unavailable",
    "subscription_required",
    "quota_exceeded",
    "permission_denied",
    "model_not_supported",
    "model_test_failed",
    "network_error",
    "unknown",
]

_QUOTA_KEYWORDS = (
    "insufficient_quota",
    "quota",
    "billing",
    "rate limit",
    "exceeded your current quota",
)

# Non-chat OpenAI model id fragments (image, audio, embeddings, etc.)
_OPENAI_EXCLUDED_FRAGMENTS = (
    "dall-e",
    "whisper",
    "tts-",
    "text-embedding",
    "embedding",
    "moderation",
    "davinci-",
    "babbage-",
    "audio-",
    "realtime",
    "transcribe",
    "sora",
    "gpt-image",
    "omni-moderation",
)

_OPENAI_CHAT_FRAGMENTS = ("gpt", "o1", "o3", "o4", "chatgpt")


def invalid_api_key_response(provider: str) -> ConnectionTestResponse:
    labels = {
        "openai": "OpenAI",
        "anthropic": "Anthropic",
        "ollama_cloud": "Ollama Cloud",
    }
    name = labels.get(provider, provider)
    return ConnectionTestResponse(
        success=False,
        message=f"Invalid {name} API key — check your key and try again.",
        provider_ok=False,
        api_key_ok=False,
        model_ok=None,
        error_type="invalid_api_key",
    )


def provider_validated_response(
    *,
    provider: str,
    message: str,
    available_models: list[str],
    latency_ms: int | None = None,
    validation_level: str = "api_key",
) -> ConnectionTestResponse:
    return ConnectionTestResponse(
        success=False,
        message=message,
        latency_ms=latency_ms,
        available_models=available_models,
        validation_level=validation_level,
        provider_ok=True,
        api_key_ok=True,
        model_ok=None,
    )


def models_discovered_response(
    *,
    message: str,
    available_models: list[str],
    latency_ms: int | None = None,
) -> ConnectionTestResponse:
    """Model list from a public or unauthenticated discovery call — key not verified yet."""
    return ConnectionTestResponse(
        success=False,
        message=message,
        latency_ms=latency_ms,
        available_models=available_models,
        validation_level="discovery",
        provider_ok=True,
        api_key_ok=False,
        model_ok=None,
    )


def model_validated_success(
    *,
    message: str,
    available_models: list[str],
    latency_ms: int | None = None,
) -> ConnectionTestResponse:
    return ConnectionTestResponse(
        success=True,
        message=message,
        latency_ms=latency_ms,
        available_models=available_models,
        validation_level="generation",
        provider_ok=True,
        api_key_ok=True,
        model_ok=True,
    )


def model_failure_response(
    *,
    message: str,
    available_models: list[str],
    error_type: ErrorType,
    latency_ms: int | None = None,
) -> ConnectionTestResponse:
    return ConnectionTestResponse(
        success=False,
        message=message,
        latency_ms=latency_ms,
        available_models=available_models,
        validation_level="api_key",
        provider_ok=True,
        api_key_ok=True,
        model_ok=False,
        error_type=error_type,
    )


def is_openai_chat_model(model_id: str) -> bool:
    mid = model_id.lower()
    if any(fragment in mid for fragment in _OPENAI_EXCLUDED_FRAGMENTS):
        return False
    return any(fragment in mid for fragment in _OPENAI_CHAT_FRAGMENTS)


def filter_openai_models(models_result) -> list[str]:
    return sorted(m.id for m in models_result.data if is_openai_chat_model(m.id))


def _openai_status_code(exc: Exception) -> int | None:
    import openai as _openai

    if isinstance(exc, _openai.APIStatusError):
        return exc.status_code
    return None


def is_openai_quota_error(exc: Exception) -> bool:
    import openai as _openai

    if isinstance(exc, _openai.RateLimitError):
        return True
    status = _openai_status_code(exc)
    if status == 429:
        return True
    if status == 400 or isinstance(exc, _openai.BadRequestError):
        return False
    msg = str(exc).lower()
    return any(kw in msg for kw in _QUOTA_KEYWORDS)


def is_openai_model_access_error(exc: Exception) -> bool:
    import openai as _openai

    if isinstance(exc, (_openai.PermissionDeniedError, _openai.NotFoundError)):
        return True
    if isinstance(exc, _openai.APIStatusError) and exc.status_code in (403, 404):
        return True
    return False


def _safe_error_detail(exc: Exception) -> str:
    return str(exc).replace("\n", " ")[:200]


def openai_chat_error_response(
    exc: Exception, available: list[str]
) -> ConnectionTestResponse:
    import openai as _openai

    print(
        f"[config/test] openai chat classify  type={type(exc).__name__}  "
        f"status={_openai_status_code(exc)}  detail={_safe_error_detail(exc)!r}",
        flush=True,
    )
    if is_openai_quota_error(exc):
        return model_failure_response(
            message="OpenAI API key is valid, but your quota, billing, or rate limit was exceeded.",
            available_models=available,
            error_type="quota_exceeded",
        )
    if is_openai_model_access_error(exc):
        return model_failure_response(
            message=(
                "OpenAI API key is valid, but this model is not available for your account. "
                "Select a different model."
            ),
            available_models=available,
            error_type="permission_denied",
        )
    if isinstance(exc, _openai.BadRequestError):
        msg = str(exc).lower()
        if "model" in msg and any(
            token in msg
            for token in (
                "not found",
                "not supported",
                "does not exist",
                "invalid model",
            )
        ):
            return model_failure_response(
                message=(
                    "OpenAI API key is valid, but this model is not supported or not available. "
                    "Select a different model from the dropdown."
                ),
                available_models=available,
                error_type="model_not_supported",
            )
        return model_failure_response(
            message=(
                "OpenAI API key is valid, but the selected model test failed. "
                "Please try another model."
            ),
            available_models=available,
            error_type="model_test_failed",
        )
    return model_failure_response(
        message=(
            "OpenAI API key is valid, but the selected model test failed. "
            "Please try another model."
        ),
        available_models=available,
        error_type="model_test_failed",
    )


def _anthropic_status_code(exc: Exception) -> int | None:
    import anthropic as _anthropic

    if isinstance(exc, _anthropic.APIStatusError):
        return exc.status_code
    return None


def is_anthropic_quota_error(exc: Exception) -> bool:
    import anthropic as _anthropic

    if isinstance(exc, _anthropic.RateLimitError):
        return True
    return _anthropic_status_code(exc) == 429


def is_anthropic_model_access_error(exc: Exception) -> bool:
    import anthropic as _anthropic

    if isinstance(exc, (_anthropic.PermissionDeniedError, _anthropic.NotFoundError)):
        return True
    if isinstance(exc, _anthropic.APIStatusError) and exc.status_code in (403, 404):
        return True
    msg = str(exc).lower()
    return "model" in msg and "not found" in msg


def anthropic_chat_error_response(
    exc: Exception, available: list[str]
) -> ConnectionTestResponse:
    import anthropic as _anthropic

    status = _anthropic_status_code(exc)
    print(
        f"[config/test] anthropic chat classify  type={type(exc).__name__}  "
        f"status={status}  detail={_safe_error_detail(exc)!r}",
        flush=True,
    )
    if isinstance(exc, _anthropic.AuthenticationError):
        return invalid_api_key_response("anthropic")
    if is_anthropic_quota_error(exc):
        return model_failure_response(
            message="Anthropic API key is valid, but your quota, billing, or rate limit was exceeded.",
            available_models=available,
            error_type="quota_exceeded",
        )
    if is_anthropic_model_access_error(exc):
        return model_failure_response(
            message=(
                "Anthropic API key is valid, but this model is not available for your account. "
                "Select a different model."
            ),
            available_models=available,
            error_type="model_unavailable",
        )
    if isinstance(exc, _anthropic.BadRequestError):
        msg = str(exc).lower()
        if "model" in msg and any(
            token in msg
            for token in (
                "not found",
                "not supported",
                "does not exist",
                "invalid model",
                "unknown model",
            )
        ):
            return model_failure_response(
                message=(
                    "Anthropic API key is valid, but this model is not supported or not available. "
                    "Select a different model from the dropdown."
                ),
                available_models=available,
                error_type="model_not_supported",
            )
        return model_failure_response(
            message=(
                "Anthropic API key is valid, but the selected model test failed. "
                "Check the model name and try again."
            ),
            available_models=available,
            error_type="model_test_failed",
        )
    return model_failure_response(
        message=(
            "Anthropic API key is valid, but the selected model test failed. "
            "Please try another model."
        ),
        available_models=available,
        error_type="model_test_failed",
    )

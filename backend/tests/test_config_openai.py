"""Tests for OpenAI connection-test error classification."""

from unittest.mock import MagicMock, patch

import httpx
import openai
import pytest

from app.api.config import _test_openai
from app.models.config import AppConfig
from app.utils.cloud_validation import (
    is_openai_model_access_error,
    is_openai_quota_error,
    openai_chat_error_response,
)


def test_openai_bad_request_not_quota():
    import openai

    exc = openai.BadRequestError(
        "bad request",
        response=httpx.Response(
            400,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        ),
        body=None,
    )
    result = openai_chat_error_response(exc, ["gpt-4o"])
    assert result.error_type == "model_test_failed"
    assert result.error_type != "quota_exceeded"


def _api_status_error(status_code: int, message: str) -> openai.APIStatusError:
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request, text=message)
    return openai.APIStatusError(message, response=response, body=None)


def test_is_openai_quota_error_detects_429_and_keywords():
    assert is_openai_quota_error(
        _api_status_error(429, "You exceeded your current quota")
    )
    assert is_openai_quota_error(Exception("insufficient_quota for this account"))
    assert not is_openai_quota_error(_api_status_error(500, "internal server error"))


def test_is_openai_model_access_error_detects_404():
    assert is_openai_model_access_error(_api_status_error(404, "model not found"))
    assert not is_openai_model_access_error(_api_status_error(429, "rate limited"))


def test_openai_chat_test_error_response_quota():
    exc = _api_status_error(
        429, "You exceeded your current quota, please check billing"
    )
    result = openai_chat_error_response(exc, ["gpt-4o"])
    assert result.success is False
    assert result.api_key_ok is True
    assert result.model_ok is False
    assert result.error_type == "quota_exceeded"
    assert "invalid" not in result.message.lower()


def test_openai_chat_test_error_response_model_access():
    exc = _api_status_error(404, "The model `foo` does not exist")
    result = openai_chat_error_response(exc, ["gpt-4o"])
    assert result.api_key_ok is True
    assert result.error_type == "permission_denied"


@patch("openai.OpenAI")
def test_test_openai_invalid_api_key(mock_openai_cls: MagicMock):
    client = MagicMock()
    mock_openai_cls.return_value = client
    client.models.list.side_effect = openai.AuthenticationError(
        "Invalid API key",
        response=httpx.Response(
            401, request=httpx.Request("GET", "https://api.openai.com/v1/models")
        ),
        body=None,
    )

    result = _test_openai(
        AppConfig(provider="openai", model="gpt-4o", api_key="sk-invalid"),
    )

    assert result.api_key_ok is False
    assert result.error_type == "invalid_api_key"
    client.chat.completions.create.assert_not_called()


@patch("llm_ontology_mapper.LLMProviderFactory")
@patch("openai.OpenAI")
def test_test_openai_chat_quota_error(
    mock_openai_cls: MagicMock,
    mock_factory: MagicMock,
):
    client = MagicMock()
    mock_openai_cls.return_value = client
    client.models.list.return_value = MagicMock(
        data=[MagicMock(id="gpt-4o"), MagicMock(id="gpt-3.5-turbo")],
    )
    provider = MagicMock()
    mock_factory.from_config.return_value = provider
    provider.complete.side_effect = _api_status_error(
        429,
        "You exceeded your current quota, please check your plan and billing details.",
    )

    result = _test_openai(
        AppConfig(provider="openai", model="gpt-3.5-turbo", api_key="sk-valid"),
    )

    assert result.api_key_ok is True
    assert result.model_ok is False
    assert result.error_type == "quota_exceeded"
    assert result.available_models is not None
    client.chat.completions.create.assert_not_called()
    provider.complete.assert_called_once()


@pytest.mark.parametrize("model", ["gpt-4o-mini", "gpt-5"])
@patch("llm_ontology_mapper.LLMProviderFactory")
@patch("openai.OpenAI")
def test_test_openai_valid_key_with_model_uses_library_provider(
    mock_openai_cls: MagicMock,
    mock_factory: MagicMock,
    model: str,
):
    client = MagicMock()
    mock_openai_cls.return_value = client
    client.models.list.return_value = MagicMock(data=[MagicMock(id=model)])
    provider = MagicMock()
    provider.complete.return_value = MagicMock(content="OK")
    mock_factory.from_config.return_value = provider

    result = _test_openai(
        AppConfig(provider="openai", model=model, api_key="sk-valid"),
    )

    client.chat.completions.create.assert_not_called()
    mock_factory.from_config.assert_called_once_with(
        provider="openai",
        model=model,
        api_key="sk-valid",
        max_retries=1,
    )
    provider.complete.assert_called_once()
    assert result.model_ok is True
    assert result.success is True


@patch("openai.OpenAI")
def test_test_openai_success_without_model(mock_openai_cls: MagicMock):
    client = MagicMock()
    mock_openai_cls.return_value = client
    client.models.list.return_value = MagicMock(data=[MagicMock(id="gpt-4o")])

    result = _test_openai(
        AppConfig(provider="openai", model="", api_key="sk-valid"),
    )

    assert result.success is False
    assert result.api_key_ok is True
    assert result.model_ok is None
    assert result.available_models == ["gpt-4o"]
    assert result.message
    client.chat.completions.create.assert_not_called()


@patch("openai.OpenAI")
def test_test_openai_unsupported_model_skips_chat(mock_openai_cls: MagicMock):
    client = MagicMock()
    mock_openai_cls.return_value = client
    client.models.list.return_value = MagicMock(data=[MagicMock(id="gpt-4o")])

    result = _test_openai(
        AppConfig(provider="openai", model="dall-e-3", api_key="sk-valid"),
    )

    assert result.api_key_ok is True
    assert result.model_ok is False
    assert result.error_type == "model_not_supported"
    client.chat.completions.create.assert_not_called()


@patch("llm_ontology_mapper.LLMProviderFactory")
@patch("openai.OpenAI")
def test_test_openai_chat_model_not_found(
    mock_openai_cls: MagicMock,
    mock_factory: MagicMock,
):
    client = MagicMock()
    mock_openai_cls.return_value = client
    client.models.list.return_value = MagicMock(data=[MagicMock(id="gpt-4o")])
    provider = MagicMock()
    mock_factory.from_config.return_value = provider
    provider.complete.side_effect = openai.NotFoundError(
        "model not found",
        response=httpx.Response(
            404,
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        ),
        body=None,
    )

    result = _test_openai(
        AppConfig(provider="openai", model="gpt-missing", api_key="sk-valid"),
    )

    assert result.api_key_ok is True
    assert result.model_ok is False
    assert "invalid" not in result.message.lower()
    client.chat.completions.create.assert_not_called()
    provider.complete.assert_called_once()

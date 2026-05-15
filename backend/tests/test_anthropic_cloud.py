"""Tests for Anthropic two-step connection validation."""

from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest

from app.api.config import _test_anthropic
from app.models.config import AppConfig
from app.utils.cloud_validation import anthropic_chat_error_response


def _bad_request(msg: str) -> anthropic.BadRequestError:
    return anthropic.BadRequestError(
        msg,
        response=httpx.Response(400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
        body=None,
    )


def test_bad_request_not_classified_as_quota():
    result = anthropic_chat_error_response(
        _bad_request("invalid request: max_tokens must be positive"),
        ["claude-sonnet-4-20250514"],
    )
    assert result.error_type == "model_test_failed"
    assert result.error_type != "quota_exceeded"
    assert "quota" not in result.message.lower()


def test_rate_limit_is_quota():
    exc = anthropic.RateLimitError(
        "rate limited",
        response=httpx.Response(429, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
        body=None,
    )
    result = anthropic_chat_error_response(exc, ["claude-sonnet-4-20250514"])
    assert result.error_type == "quota_exceeded"


@patch("anthropic.Anthropic")
def test_invalid_key(mock_cls: MagicMock):
    client = MagicMock()
    mock_cls.return_value = client
    client.models.list.side_effect = anthropic.AuthenticationError(
        "invalid",
        response=httpx.Response(401, request=httpx.Request("GET", "https://api.anthropic.com/v1/models")),
        body=None,
    )

    result = _test_anthropic(AppConfig(provider="anthropic", model="", api_key="bad"))

    assert result.api_key_ok is False
    assert result.error_type == "invalid_api_key"
    client.messages.create.assert_not_called()


@patch("anthropic.Anthropic")
def test_valid_key_no_model(mock_cls: MagicMock):
    client = MagicMock()
    mock_cls.return_value = client
    client.models.list.return_value = MagicMock(data=[MagicMock(id="claude-sonnet-4-20250514")])

    result = _test_anthropic(AppConfig(provider="anthropic", model="", api_key="sk-ant"))

    assert result.api_key_ok is True
    assert result.model_ok is None
    assert result.success is False
    client.messages.create.assert_not_called()


@patch("anthropic.Anthropic")
def test_valid_key_with_model_runs_chat(mock_cls: MagicMock):
    client = MagicMock()
    mock_cls.return_value = client
    client.models.list.return_value = MagicMock(data=[MagicMock(id="claude-sonnet-4-20250514")])
    client.messages.create.return_value = MagicMock(content=[MagicMock(text="OK")])

    result = _test_anthropic(
        AppConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            api_key="sk-ant",
        ),
    )

    client.messages.create.assert_called_once()
    assert result.model_ok is True
    assert result.success is True

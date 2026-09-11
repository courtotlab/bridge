"""Tests for Ollama Cloud connection validation."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from app.api.config import _test_ollama_cloud
from app.models.config import AppConfig


def _mock_response(status_code: int, json_data=None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text or (str(json_data) if json_data else "")
    resp.json.return_value = json_data or {}
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            response=resp,
            request=MagicMock(),
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


@patch("app.api.config._requests.get")
@patch("app.api.config._requests.post")
def test_tags_ok_no_model_does_not_prove_api_key(mock_post, mock_get):
    mock_get.return_value = _mock_response(
        200,
        json_data={
            "models": [{"name": "gemini-3-flash-preview"}, {"name": "llama3.2"}]
        },
    )

    result = _test_ollama_cloud(
        AppConfig(
            provider="ollama_cloud",
            model="",
            api_key="garbage-key",
        ),
    )

    mock_post.assert_not_called()
    assert result.api_key_ok is not True
    assert result.model_ok is None
    assert result.success is False
    assert result.validation_level == "discovery"
    assert result.available_models == ["gemini-3-flash-preview", "llama3.2"]
    assert result.message == (
        "Ollama Cloud model catalog loaded. Select a model to verify API access."
    )
    assert "api key is valid" not in result.message.lower()


@patch("app.api.config._requests.get")
@patch("app.api.config._requests.post")
def test_subscription_required_keeps_models(mock_post, mock_get):
    mock_get.return_value = _mock_response(
        200,
        json_data={"models": [{"name": "gemini-3-flash-preview"}]},
    )
    mock_post.return_value = _mock_response(
        403,
        text='{"error":"this model requires a subscription, upgrade for access"}',
    )

    result = _test_ollama_cloud(
        AppConfig(
            provider="ollama_cloud",
            model="gemini-3-flash-preview",
            api_key="sk-test-key",
        ),
    )

    assert result.api_key_ok is True
    assert result.model_ok is False
    assert result.error_type == "subscription_required"
    assert result.available_models == ["gemini-3-flash-preview"]


@patch("app.api.config._requests.get")
@patch("app.api.config._requests.post")
def test_chat_401_maps_invalid_api_key(mock_post, mock_get):
    mock_get.return_value = _mock_response(
        200,
        json_data={"models": [{"name": "gemini-3-flash-preview"}]},
    )
    mock_post.return_value = _mock_response(401, text='{"error":"unauthorized"}')

    result = _test_ollama_cloud(
        AppConfig(
            provider="ollama_cloud",
            model="gemini-3-flash-preview",
            api_key="garbage-key",
        ),
    )

    assert result.api_key_ok is False
    assert result.error_type == "invalid_api_key"


@patch("app.api.config._requests.get")
@patch("app.api.config._requests.post")
def test_tags_invalid_auth(mock_post, mock_get):
    mock_get.return_value = _mock_response(403, text="unauthorized")

    result = _test_ollama_cloud(
        AppConfig(
            provider="ollama_cloud",
            model="gemini-3-flash-preview",
            api_key="bad-key",
        ),
    )

    mock_post.assert_not_called()
    assert result.api_key_ok is False
    assert result.error_type == "invalid_api_key"


@patch("app.api.config._requests.get")
@patch("app.api.config._requests.post")
def test_chat_success(mock_post, mock_get):
    mock_get.return_value = _mock_response(
        200,
        json_data={"models": [{"name": "llama3.2"}]},
    )
    mock_post.return_value = _mock_response(
        200, json_data={"message": {"content": "OK"}}
    )

    result = _test_ollama_cloud(
        AppConfig(
            provider="ollama_cloud",
            model="llama3.2",
            api_key="sk-test-key",
        ),
    )

    assert result.success is True
    assert result.api_key_ok is True
    assert result.model_ok is True

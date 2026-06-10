"""Tests for the /api/config/test connection-test logic."""
import pytest
import requests as _requests

from app.api.config import _OLLAMA_CLOUD_BASE, _ollama_cloud_base, _test_ollama, _test_ollama_cloud
from app.models.config import AppConfig


# ── helpers ───────────────────────────────────────────────────────────────────

def _cfg(**kwargs) -> AppConfig:
    defaults = dict(
        provider="ollama_cloud",
        model="llama3.2",
        base_url="http://localhost:11434",
        api_key="sk-test1234",
    )
    defaults.update(kwargs)
    return AppConfig(**defaults)


def _http_error(status: int) -> _requests.HTTPError:
    resp = _requests.Response()
    resp.status_code = status
    resp._content = b""
    err = _requests.HTTPError(response=resp)
    return err


def _mock_tags_ok(models=("llama3.2", "mistral")):
    resp = _requests.Response()
    resp.status_code = 200
    resp._content = (
        '{"models": [' + ", ".join(f'{{"name": "{m}"}}' for m in models) + "]}"
    ).encode()
    return resp


def _mock_chat_ok():
    resp = _requests.Response()
    resp.status_code = 200
    resp._content = b'{"message": {"content": "OK"}}'
    return resp


# ── _ollama_cloud_base ────────────────────────────────────────────────────────

class TestOllamaCloudBase:
    def test_localhost_replaced(self):
        cfg = _cfg(base_url="http://localhost:11434")
        assert _ollama_cloud_base(cfg) == _OLLAMA_CLOUD_BASE

    def test_127_replaced(self):
        cfg = _cfg(base_url="http://127.0.0.1:11434")
        assert _ollama_cloud_base(cfg) == _OLLAMA_CLOUD_BASE

    def test_0_0_0_0_replaced(self):
        cfg = _cfg(base_url="http://0.0.0.0:11434")
        assert _ollama_cloud_base(cfg) == _OLLAMA_CLOUD_BASE

    def test_custom_cloud_url_kept(self):
        cfg = _cfg(base_url="https://my-ollama-proxy.example.com")
        assert _ollama_cloud_base(cfg) == "https://my-ollama-proxy.example.com"

    def test_empty_base_url_replaced(self):
        cfg = _cfg(base_url="")
        assert _ollama_cloud_base(cfg) == _OLLAMA_CLOUD_BASE


# ── _test_ollama_cloud — no model selected (reachability path) ───────────────

class TestOllamaCloudNoModel:
    def test_empty_model_returns_available_models(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            return_value=_mock_tags_ok(["llama3.2", "mistral"]),
        )
        result = _test_ollama_cloud(_cfg(model=""))
        assert result.success is True
        assert "Select a model" in result.message
        assert result.available_models == ["llama3.2", "mistral"]

    def test_empty_model_validation_level_is_reachability(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        result = _test_ollama_cloud(_cfg(model=""))
        assert result.validation_level == "reachability"

    def test_empty_model_does_not_claim_api_key_valid(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        result = _test_ollama_cloud(_cfg(model=""))
        lower = result.message.lower()
        assert "api key" not in lower
        assert "key works" not in lower

    def test_empty_model_no_api_key_still_lists_models(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        result = _test_ollama_cloud(_cfg(model="", api_key=None))
        assert result.success is True
        assert result.available_models is not None
        assert result.validation_level == "reachability"

    def test_tags_http_error_fails(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=_http_error(503),
        )
        result = _test_ollama_cloud(_cfg(model=""))
        assert result.success is False
        assert "503" in result.message

    def test_tags_network_error_fails(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=ConnectionError("timeout"),
        )
        result = _test_ollama_cloud(_cfg(model=""))
        assert result.success is False


# ── _test_ollama_cloud — model selected (generation path) ────────────────────

class TestOllamaCloudWithModel:
    def test_successful_chat_returns_success(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        mocker.patch("app.api.config._requests.post", return_value=_mock_chat_ok())
        result = _test_ollama_cloud(_cfg(model="llama3.2"))
        assert result.success is True
        assert "API key works" in result.message
        assert "llama3.2" in result.message

    def test_successful_chat_validation_level_is_generation(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        mocker.patch("app.api.config._requests.post", return_value=_mock_chat_ok())
        result = _test_ollama_cloud(_cfg(model="llama3.2"))
        assert result.validation_level == "generation"

    def test_no_api_key_with_model_fails(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        result = _test_ollama_cloud(_cfg(model="llama3.2", api_key=None))
        assert result.success is False
        assert "api key" in result.message.lower()

    def test_401_from_chat_fails_with_clear_message(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        mocker.patch(
            "app.api.config._requests.post",
            side_effect=_http_error(401),
        )
        result = _test_ollama_cloud(_cfg(model="llama3.2"))
        assert result.success is False
        assert "401" in result.message

    def test_403_from_chat_fails_with_clear_message(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        mocker.patch(
            "app.api.config._requests.post",
            side_effect=_http_error(403),
        )
        result = _test_ollama_cloud(_cfg(model="llama3.2"))
        assert result.success is False
        assert "403" in result.message

    def test_404_from_chat_signals_model_not_found(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        mocker.patch(
            "app.api.config._requests.post",
            side_effect=_http_error(404),
        )
        result = _test_ollama_cloud(_cfg(model="bad-model"))
        assert result.success is False
        assert "not found" in result.message.lower() or "404" in result.message

    def test_chat_uses_bearer_auth(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        mock_post = mocker.patch(
            "app.api.config._requests.post", return_value=_mock_chat_ok()
        )
        _test_ollama_cloud(_cfg(model="llama3.2", api_key="sk-secret"))
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer sk-secret"

    def test_chat_hits_ollama_cloud_url_not_localhost(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        mock_post = mocker.patch(
            "app.api.config._requests.post", return_value=_mock_chat_ok()
        )
        _test_ollama_cloud(_cfg(model="llama3.2", base_url="http://localhost:11434"))
        url = mock_post.call_args[0][0]
        assert "localhost" not in url
        assert _OLLAMA_CLOUD_BASE in url


# ── _test_ollama (local) — unaffected by cloud changes ───────────────────────

class TestOllamaLocal:
    def test_uses_configured_base_url(self, mocker):
        mock_get = mocker.patch(
            "app.api.config._requests.get", return_value=_mock_tags_ok()
        )
        cfg = AppConfig(
            provider="ollama",
            model="llama3.2",
            base_url="http://my-server:11434",
        )
        result = _test_ollama(cfg)
        assert result.success is True
        url = mock_get.call_args[0][0]
        assert url == "http://my-server:11434/api/tags"

    def test_no_auth_header_sent(self, mocker):
        mock_get = mocker.patch(
            "app.api.config._requests.get", return_value=_mock_tags_ok()
        )
        _test_ollama(AppConfig(provider="ollama", model="llama3.2"))
        _, kwargs = mock_get.call_args
        assert "Authorization" not in (kwargs.get("headers") or {})

    def test_connection_failure_returns_false(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=ConnectionError("refused"),
        )
        result = _test_ollama(AppConfig(provider="ollama", model="llama3.2"))
        assert result.success is False

    def test_validation_level_not_set_for_local(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        result = _test_ollama(AppConfig(provider="ollama", model="llama3.2"))
        assert result.validation_level is None

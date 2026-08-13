"""Tests for the /api/config/test connection-test logic."""

import pytest
import requests as _requests
from fastapi.testclient import TestClient

from app.api import config as config_api
from app.api.config import (
    _LOINC_SEARCH_URL,
    _OLLAMA_CLOUD_BASE,
    _ollama_cloud_base,
    _test_ollama,
    _test_ollama_cloud,
    _test_public_retrieval,
)
from app.main import app
from app.models.config import AppConfig, ConnectionTestResponse
from app.storage import config_store

client = TestClient(app)

# ── helpers ───────────────────────────────────────────────────────────────────


def _cfg(**kwargs) -> AppConfig:
    defaults = {
        "provider": "ollama_cloud",
        "model": "llama3.2",
        "base_url": "http://localhost:11434",
        "api_key": "sk-test1234",
    }
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


def _mock_chat_error(message: str = "load failed"):
    resp = _requests.Response()
    resp.status_code = 500
    resp._content = f'{{"error": "{message}"}}'.encode()
    return resp


def _mock_ps(models=()):
    resp = _requests.Response()
    resp.status_code = 200
    resp._content = (
        '{"models": [' + ", ".join(f'{{"name": "{m}"}}' for m in models) + "]}"
    ).encode()
    return resp


def _mock_loinc_response(status_code: int = 200, json_data=None, text: str = ""):
    resp = _requests.Response()
    resp.status_code = status_code
    resp._content = (
        text.encode()
        if text
        else (
            b'{"results":[{"loincNum":"2345-7","longCommonName":"Glucose"}]}'
            if json_data is None
            else json_data
        )
    )
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
        assert result.success is False
        assert "Select a model" in result.message
        assert result.available_models == ["llama3.2", "mistral"]

    def test_empty_model_validation_level_is_discovery(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        result = _test_ollama_cloud(_cfg(model=""))
        assert result.validation_level == "discovery"

    def test_empty_model_does_not_claim_api_key_valid(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        result = _test_ollama_cloud(_cfg(model=""))
        lower = result.message.lower()
        assert "api key" not in lower
        assert "key works" not in lower

    def test_empty_model_no_api_key_fails_before_listing_models(self, mocker):
        mock_get = mocker.patch("app.api.config._requests.get")
        result = _test_ollama_cloud(_cfg(model="", api_key=None))
        assert result.success is False
        assert result.error_type == "invalid_api_key"
        mock_get.assert_not_called()

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
        assert "selected model is usable" in result.message
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
        assert result.error_type == "invalid_api_key"

    def test_403_from_chat_fails_with_clear_message(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        mocker.patch(
            "app.api.config._requests.post",
            side_effect=_http_error(403),
        )
        result = _test_ollama_cloud(_cfg(model="llama3.2"))
        assert result.success is False
        assert result.error_type == "model_unavailable"

    def test_404_from_chat_signals_model_not_found(self, mocker):
        mocker.patch("app.api.config._requests.get", return_value=_mock_tags_ok())
        mocker.patch(
            "app.api.config._requests.post",
            side_effect=_http_error(404),
        )
        result = _test_ollama_cloud(_cfg(model="bad-model"))
        assert result.success is False
        assert result.error_type == "model_unavailable"

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
            "app.api.config._requests.get",
            side_effect=[_mock_tags_ok(["llama3.2"]), _mock_ps()],
        )
        mocker.patch("app.api.config._requests.post", return_value=_mock_chat_ok())
        cfg = AppConfig(
            provider="ollama",
            model="llama3.2",
            base_url="http://my-server:11434",
        )
        result = _test_ollama(cfg)
        assert result.success is True
        urls = [call.args[0] for call in mock_get.call_args_list]
        assert urls == [
            "http://my-server:11434/api/tags",
            "http://my-server:11434/api/ps",
        ]

    def test_no_auth_header_sent(self, mocker):
        mock_get = mocker.patch(
            "app.api.config._requests.get",
            side_effect=[_mock_tags_ok(["llama3.2"]), _mock_ps()],
        )
        mocker.patch("app.api.config._requests.post", return_value=_mock_chat_ok())
        _test_ollama(AppConfig(provider="ollama", model="llama3.2"))
        for call in mock_get.call_args_list:
            assert "Authorization" not in (call.kwargs.get("headers") or {})

    def test_connection_failure_returns_false(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=ConnectionError("refused"),
        )
        result = _test_ollama(AppConfig(provider="ollama", model="llama3.2"))
        assert result.success is False

    def test_successful_local_validation_level_is_generation(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=[_mock_tags_ok(["llama3.2"]), _mock_ps()],
        )
        mocker.patch("app.api.config._requests.post", return_value=_mock_chat_ok())
        result = _test_ollama(AppConfig(provider="ollama", model="llama3.2"))
        assert result.validation_level == "generation"

    def test_selected_model_is_used_for_chat_probe(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=[
                _mock_tags_ok(["gpt-oss:120b", "gemma3:270m"]),
                _mock_ps(),
            ],
        )
        mock_post = mocker.patch(
            "app.api.config._requests.post",
            return_value=_mock_chat_ok(),
        )

        result = _test_ollama(
            AppConfig(provider="ollama", model="gpt-oss:120b")
        )

        assert result.success is True
        assert mock_post.call_args.kwargs["json"]["model"] == "gpt-oss:120b"

    def test_unrelated_resident_model_does_not_override_selected_model(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=[
                _mock_tags_ok(["gpt-oss:120b", "gemma3:270m"]),
                _mock_ps(["gemma3:270m"]),
            ],
        )
        mock_post = mocker.patch(
            "app.api.config._requests.post",
            return_value=_mock_chat_ok(),
        )

        result = _test_ollama(
            AppConfig(provider="ollama", model="gpt-oss:120b")
        )

        assert result.success is True
        assert mock_post.call_args.kwargs["json"]["model"] == "gpt-oss:120b"
        assert mock_post.call_args.kwargs["timeout"] == 120

    def test_selected_model_already_loaded_uses_warm_timeout(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=[
                _mock_tags_ok(["gpt-oss:120b", "gemma3:270m"]),
                _mock_ps(["gpt-oss:120b"]),
            ],
        )
        mock_post = mocker.patch(
            "app.api.config._requests.post",
            return_value=_mock_chat_ok(),
        )

        result = _test_ollama(
            AppConfig(provider="ollama", model="gpt-oss:120b")
        )

        assert result.success is True
        assert result.model_ok is True
        assert mock_post.call_args.kwargs["json"]["model"] == "gpt-oss:120b"
        assert mock_post.call_args.kwargs["timeout"] == 30

    def test_selected_model_missing_fails_without_chat_probe(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            return_value=_mock_tags_ok(["gemma3:270m"]),
        )
        mock_post = mocker.patch("app.api.config._requests.post")

        result = _test_ollama(
            AppConfig(provider="ollama", model="gpt-oss:120b")
        )

        assert result.success is False
        assert result.model_ok is False
        assert result.error_type == "model_unavailable"
        assert result.available_models == ["gemma3:270m"]
        assert "gpt-oss:120b" in result.message
        mock_post.assert_not_called()

    def test_selected_model_inference_failure_fails_without_fallback(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=[
                _mock_tags_ok(["gpt-oss:120b", "gemma3:270m"]),
                _mock_ps(["gemma3:270m"]),
            ],
        )
        mock_post = mocker.patch(
            "app.api.config._requests.post",
            return_value=_mock_chat_error("load failed"),
        )

        result = _test_ollama(
            AppConfig(provider="ollama", model="gpt-oss:120b")
        )

        assert result.success is False
        assert result.model_ok is False
        assert mock_post.call_count == 1
        assert mock_post.call_args.kwargs["json"]["model"] == "gpt-oss:120b"
        assert "load failed" in result.message

    def test_selected_model_timeout_fails(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=[
                _mock_tags_ok(["gpt-oss:120b", "gemma3:270m"]),
                _mock_ps(),
            ],
        )
        mocker.patch(
            "app.api.config._requests.post",
            side_effect=_requests.Timeout("slow model"),
        )

        result = _test_ollama(
            AppConfig(provider="ollama", model="gpt-oss:120b")
        )

        assert result.success is False
        assert result.model_ok is False
        assert result.error_type == "model_test_failed"
        assert "gpt-oss:120b" in result.message
        assert "did not respond" in result.message

    def test_ps_failure_is_best_effort_and_selected_model_is_still_tested(self, mocker):
        def fake_get(url, **kwargs):
            if url.endswith("/api/tags"):
                return _mock_tags_ok(["gpt-oss:120b"])
            if url.endswith("/api/ps"):
                raise ConnectionError("ps unavailable")
            raise AssertionError(f"unexpected URL {url}")

        mocker.patch("app.api.config._requests.get", side_effect=fake_get)
        mock_post = mocker.patch(
            "app.api.config._requests.post",
            return_value=_mock_chat_ok(),
        )

        result = _test_ollama(
            AppConfig(provider="ollama", model="gpt-oss:120b")
        )

        assert result.success is True
        assert mock_post.call_args.kwargs["json"]["model"] == "gpt-oss:120b"


class TestOllamaLocalModelDiscovery:
    def test_discovers_models_from_requested_base_url(self, mocker):
        mock_get = mocker.patch(
            "app.api.config._requests.get",
            return_value=_mock_tags_ok(["gpt-oss:120b", "gemma3:270m"]),
        )
        mock_post = mocker.patch("app.api.config._requests.post")

        response = client.post(
            "/api/config/ollama/models",
            json={"base_url": "http://localhost:11528"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "models": ["gpt-oss:120b", "gemma3:270m"],
            "warning": None,
            "error": None,
        }
        mock_get.assert_called_once_with(
            "http://localhost:11528/api/tags",
            timeout=config_api._OLLAMA_TAGS_TIMEOUT_SECONDS,
        )
        mock_post.assert_not_called()

    def test_discovery_unreachable_fails_cleanly(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=ConnectionError("refused"),
        )
        mock_post = mocker.patch("app.api.config._requests.post")

        response = client.post(
            "/api/config/ollama/models",
            json={"base_url": "http://localhost:11528"},
        )

        assert response.status_code == 503
        assert response.json()["detail"] == (
            "Could not load models from this Ollama server."
        )
        mock_post.assert_not_called()

    def test_discovery_handles_no_models(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            return_value=_mock_tags_ok([]),
        )
        mock_post = mocker.patch("app.api.config._requests.post")

        response = client.post(
            "/api/config/ollama/models",
            json={"base_url": "http://localhost:11528"},
        )

        assert response.status_code == 200
        assert response.json()["models"] == []
        mock_post.assert_not_called()

    def test_discovery_does_not_call_ps_or_chat(self, mocker):
        requested_urls: list[str] = []

        def fake_get(url, **kwargs):
            requested_urls.append(url)
            return _mock_tags_ok(["gpt-oss:120b"])

        mocker.patch("app.api.config._requests.get", side_effect=fake_get)
        mock_post = mocker.patch("app.api.config._requests.post")

        response = client.post(
            "/api/config/ollama/models",
            json={"base_url": "http://localhost:11528"},
        )

        assert response.status_code == 200
        assert requested_urls == ["http://localhost:11528/api/tags"]
        mock_post.assert_not_called()


# ── Candidate retrieval component tests ───────────────────────────────────────


class TestPublicLoincValidation:
    def setup_method(self):
        config_store.invalidate_retrieval_validation()
        config_store.save_config(AppConfig(loinc_password=None))

    def teardown_method(self):
        config_store.invalidate_retrieval_validation()
        config_store.save_config(AppConfig(loinc_password=None))

    def test_valid_credentials(self, mocker):
        mock_get = mocker.patch(
            "app.api.config._requests.get",
            return_value=_mock_loinc_response(),
        )
        result = _test_public_retrieval(
            AppConfig(
                retrieval_mode="public",
                loinc_username=" loinc-user ",
                loinc_password="loinc-secret",
            )
        )

        assert result.valid is True
        assert result.status == "valid"
        assert result.code == "loinc_credentials_valid"
        assert result.message == "LOINC credentials are valid."
        url = mock_get.call_args.args[0]
        kwargs = mock_get.call_args.kwargs
        assert url == _LOINC_SEARCH_URL
        assert kwargs["params"] == {"query": "glucose", "rows": "1", "offset": "0"}
        assert kwargs["auth"].username == "loinc-user"
        assert kwargs["auth"].password == "loinc-secret"
        assert config_store.get_retrieval_validation() == "ok"

    def test_missing_username_or_password(self, mocker):
        mock_get = mocker.patch("app.api.config._requests.get")
        result = _test_public_retrieval(
            AppConfig(retrieval_mode="public", loinc_username="user")
        )

        mock_get.assert_not_called()
        assert result.valid is False
        assert result.status == "invalid"
        assert result.code == "loinc_credentials_missing"
        assert config_store.get_retrieval_validation() == "untested"

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_invalid_credentials(self, mocker, status_code):
        mocker.patch(
            "app.api.config._requests.get",
            return_value=_mock_loinc_response(status_code=status_code, text="nope"),
        )
        result = _test_public_retrieval(
            AppConfig(
                retrieval_mode="public",
                loinc_username="user",
                loinc_password="bad",
            )
        )

        assert result.valid is False
        assert result.status == "invalid"
        assert result.code == "loinc_credentials_invalid"
        assert result.message == "The LOINC username or password is incorrect."
        assert config_store.get_retrieval_validation() == "untested"

    def test_rate_limited(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            return_value=_mock_loinc_response(status_code=429, text="slow down"),
        )
        result = _test_public_retrieval(
            AppConfig(
                retrieval_mode="public",
                loinc_username="user",
                loinc_password="secret",
            )
        )

        assert result.valid is False
        assert result.code == "loinc_rate_limited"
        assert "temporarily limiting" in result.message

    def test_timeout(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=_requests.Timeout("timed out"),
        )
        result = _test_public_retrieval(
            AppConfig(
                retrieval_mode="public",
                loinc_username="user",
                loinc_password="secret",
            )
        )

        assert result.valid is False
        assert result.code == "loinc_timeout"
        assert result.message == "Could not reach the LOINC service. Try again."

    def test_connection_failure(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            side_effect=_requests.ConnectionError("dns"),
        )
        result = _test_public_retrieval(
            AppConfig(
                retrieval_mode="public",
                loinc_username="user",
                loinc_password="secret",
            )
        )

        assert result.valid is False
        assert result.code == "loinc_unavailable"
        assert result.message == "Could not reach the LOINC service. Try again."

    def test_upstream_5xx(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            return_value=_mock_loinc_response(status_code=503, text="down"),
        )
        result = _test_public_retrieval(
            AppConfig(
                retrieval_mode="public",
                loinc_username="user",
                loinc_password="secret",
            )
        )

        assert result.valid is False
        assert result.code == "loinc_unavailable"

    @pytest.mark.parametrize(
        "response",
        [
            _mock_loinc_response(json_data=b"{}"),
            _mock_loinc_response(text="not json"),
        ],
    )
    def test_malformed_or_unexpected_response(self, mocker, response):
        mocker.patch("app.api.config._requests.get", return_value=response)
        result = _test_public_retrieval(
            AppConfig(
                retrieval_mode="public",
                loinc_username="user",
                loinc_password="secret",
            )
        )

        assert result.valid is False
        assert result.code == "loinc_unexpected_response"
        assert result.message == "The LOINC service returned an unexpected response."

    def test_masked_sentinel_resolves_to_memory_password(self, mocker):
        config_store.save_config(AppConfig(loinc_password="memory-secret"))
        mock_get = mocker.patch(
            "app.api.config._requests.get",
            return_value=_mock_loinc_response(),
        )

        result = _test_public_retrieval(
            AppConfig(
                retrieval_mode="public",
                loinc_username="user",
                loinc_password=config_store.MASKED_SECRET_SENTINEL,
            )
        )

        assert result.valid is True
        assert mock_get.call_args.kwargs["auth"].password == "memory-secret"

    def test_password_is_not_logged_or_returned(self, mocker, capsys):
        mocker.patch(
            "app.api.config._requests.get",
            return_value=_mock_loinc_response(),
        )
        result = _test_public_retrieval(
            AppConfig(
                retrieval_mode="public",
                loinc_username="user",
                loinc_password="loinc-secret",
            )
        )
        captured = capsys.readouterr()

        assert "loinc-secret" not in result.model_dump_json()
        assert "loinc-secret" not in captured.out
        assert "loinc-secret" not in captured.err


class TestConnectionComponentIndependence:
    def setup_method(self):
        config_store.invalidate_connection_test()
        config_store.invalidate_retrieval_validation()

    def teardown_method(self):
        config_store.invalidate_connection_test()
        config_store.invalidate_retrieval_validation()

    def test_candidate_failure_does_not_prevent_ai_success(self, mocker):
        mocker.patch(
            "app.api.config._test_openai"
        ).return_value = ConnectionTestResponse(
            success=True, message="OpenAI OK.", api_key_ok=True, model_ok=True
        )
        result = config_api.test_connection(
            AppConfig(
                provider="openai",
                model="gpt-4o",
                api_key="sk-test",
                retrieval_mode="public",
            )
        )

        assert result.success is False
        assert result.candidate_retrieval.code == "loinc_credentials_missing"
        assert result.ai_model.valid is True
        assert result.model_ok is True

    def test_ai_failure_does_not_prevent_candidate_success(self, mocker):
        mocker.patch(
            "app.api.config._requests.get",
            return_value=_mock_loinc_response(),
        )
        mocker.patch(
            "app.api.config._test_openai"
        ).return_value = ConnectionTestResponse(
            success=False,
            message="OpenAI failed.",
            api_key_ok=False,
            model_ok=None,
            error_type="invalid_api_key",
        )
        result = config_api.test_connection(
            AppConfig(
                provider="openai",
                model="gpt-4o",
                api_key="bad",
                retrieval_mode="public",
                loinc_username="user",
                loinc_password="secret",
            )
        )

        assert result.success is False
        assert result.candidate_retrieval.valid is True
        assert result.ai_model.valid is False
        assert config_store.get_retrieval_validation() == "ok"

    def test_local_mode_does_not_contact_loinc(self, mocker):
        mock_loinc = mocker.patch("app.api.config._test_public_retrieval")
        mocker.patch("app.api.config._check_sapbert", return_value=("ok", None))
        mocker.patch(
            "app.api.config._test_ollama"
        ).return_value = ConnectionTestResponse(
            success=True, message="Ollama OK.", model_ok=True
        )

        result = config_api.test_connection(
            AppConfig(retrieval_mode="local", provider="ollama")
        )

        mock_loinc.assert_not_called()
        assert result.candidate_retrieval.code == "sapbert_reachable"
        assert result.candidate_retrieval.valid is True

    def test_disabled_mode_contacts_neither_retrieval_service(self, mocker):
        mock_loinc = mocker.patch("app.api.config._test_public_retrieval")
        mock_sapbert = mocker.patch("app.api.config._check_sapbert")
        mocker.patch(
            "app.api.config._test_ollama"
        ).return_value = ConnectionTestResponse(
            success=True, message="Ollama OK.", model_ok=True
        )

        result = config_api.test_connection(
            AppConfig(retrieval_mode="disabled", provider="ollama")
        )

        mock_loinc.assert_not_called()
        mock_sapbert.assert_not_called()
        assert result.success is True
        assert result.candidate_retrieval.code == "retrieval_disabled"
        assert result.candidate_retrieval.status == "not_required"

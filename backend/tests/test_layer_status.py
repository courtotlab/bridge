"""Tests for pipeline layer status computation."""

from unittest.mock import patch

import pytest

from app.models.config import AppConfig
from app.storage import config_store
from app.utils.layer_status import compute_layer_status


@pytest.fixture(autouse=True)
def reset_validation_state():
    config_store.invalidate_connection_test()
    config_store.invalidate_retrieval_validation()
    config_store.save_config(AppConfig(loinc_password=None))
    yield
    config_store.invalidate_connection_test()
    config_store.invalidate_retrieval_validation()
    config_store.save_config(AppConfig(loinc_password=None))


def test_fresh_startup_layer2_is_warning_not_ok():
    config = AppConfig(retrieval_mode="public")
    status = compute_layer_status(config)
    assert status.layer2 == "warning"
    assert status.layer2 != "ok"


def test_layer3_provider_success_does_not_change_layer2():
    config = AppConfig(provider="openai", retrieval_mode="public")
    config_store.set_connection_result(True, api_key_ok=True, model_ok=True)

    status = compute_layer_status(config)

    assert status.layer3 == "ok"
    assert status.layer2 == "warning"


def test_layer3_cloud_api_key_ok_model_not_ok_is_warning():
    config = AppConfig(provider="openai")
    config_store.set_connection_result(False, api_key_ok=True, model_ok=False)

    status = compute_layer_status(config)

    assert status.layer3 == "warning"


def test_layer3_cloud_invalid_key_is_error():
    config = AppConfig(provider="anthropic")
    config_store.set_connection_result(False, api_key_ok=False, model_ok=None)

    status = compute_layer_status(config)

    assert status.layer3 == "error"


def test_explicit_retrieval_ok_sets_layer2_ok():
    config = AppConfig(retrieval_mode="local")
    config_store.set_retrieval_result(True)

    status = compute_layer_status(config)

    assert status.layer2 == "ok"


def test_explicit_retrieval_error_sets_layer2_error():
    config = AppConfig(retrieval_mode="local")
    config_store.set_retrieval_result(False)

    status = compute_layer_status(config)

    assert status.layer2 == "error"


def test_retrieval_disabled_sets_layer2_disabled():
    config = AppConfig(retrieval_mode="disabled")
    config_store.set_retrieval_result(True)

    status = compute_layer_status(config)

    assert status.layer2 == "disabled"


@patch("app.api.config._check_sapbert", return_value=("ok", None))
@patch("app.api.config._test_openai")
def test_sapbert_ok_on_connection_test_sets_retrieval_ok(
    mock_test_openai, _mock_sapbert
):
    from app.api.config import test_connection
    from app.models.config import ConnectionTestResponse

    mock_test_openai.return_value = ConnectionTestResponse(
        success=True,
        message="OpenAI API key valid.",
        api_key_ok=True,
        model_ok=True,
    )
    body = AppConfig(
        provider="openai",
        model="gpt-4o",
        api_key="sk-test",
        retrieval_mode="local",
    )

    test_connection(body)

    assert config_store.get_retrieval_validation() == "ok"
    assert compute_layer_status(body).layer2 == "ok"


@patch("app.api.config._requests.get")
@patch("app.api.config._test_openai")
def test_public_retrieval_ok_after_loinc_validation(
    mock_test_openai, mock_get
):
    from app.api.config import test_connection
    from app.models.config import ConnectionTestResponse

    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {
        "results": [{"loincNum": "2345-7", "longCommonName": "Glucose"}]
    }
    mock_test_openai.return_value = ConnectionTestResponse(
        success=True,
        message="OpenAI API key valid.",
        api_key_ok=True,
        model_ok=True,
    )
    body = AppConfig(
        provider="openai",
        model="gpt-4o",
        api_key="sk-test",
        retrieval_mode="public",
        loinc_username="loinc-user",
        loinc_password="loinc-secret",
    )

    test_connection(body)

    assert config_store.get_retrieval_validation() == "ok"
    assert compute_layer_status(body).layer2 == "ok"
    assert compute_layer_status(body).layer3 == "ok"


@patch("app.api.config._test_openai")
def test_public_retrieval_missing_loinc_credentials_clears_readiness(
    mock_test_openai,
):
    from app.api.config import test_connection
    from app.models.config import ConnectionTestResponse

    config_store.set_retrieval_result(True, signature="stale")
    mock_test_openai.return_value = ConnectionTestResponse(
        success=True,
        message="OpenAI API key valid.",
        api_key_ok=True,
        model_ok=True,
    )
    body = AppConfig(
        provider="openai",
        model="gpt-4o",
        api_key="sk-test",
        retrieval_mode="public",
    )

    test_connection(body)

    assert config_store.get_retrieval_validation() == "untested"
    assert compute_layer_status(body).layer2 == "warning"
    assert compute_layer_status(body).layer3 == "ok"


def test_public_retrieval_credential_change_invalidates_readiness():
    config_store.save_config(AppConfig(loinc_password="loinc-secret"))
    config = AppConfig(
        retrieval_mode="public",
        loinc_username="loinc-user",
        loinc_password=config_store.MASKED_SECRET_SENTINEL,
    )
    config_store.set_retrieval_result(
        True,
        signature=config_store.current_public_retrieval_signature(config),
    )

    changed = config.model_copy(update={"loinc_username": "other-user"})

    assert compute_layer_status(config).layer2 == "ok"
    assert compute_layer_status(changed).layer2 == "warning"

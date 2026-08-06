import json

import pytest

from app.models.config import AppConfig
from app.storage import config_store


@pytest.fixture(autouse=True)
def isolated_config_store(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(config_store, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_store, "_CONFIG_FILE", config_file)
    original_sensitive = dict(config_store._sensitive)
    original_retrieval_validation = config_store._retrieval_validation
    original_retrieval_signature = config_store._retrieval_validation_signature
    for key in config_store._sensitive:
        config_store._sensitive[key] = None
    config_store.invalidate_retrieval_validation()
    yield config_file
    config_store._sensitive.clear()
    config_store._sensitive.update(original_sensitive)
    config_store._retrieval_validation = original_retrieval_validation
    config_store._retrieval_validation_signature = original_retrieval_signature


def test_loinc_password_is_memory_only_and_username_is_persisted(isolated_config_store):
    config_store.save_config(
        AppConfig(
            retrieval_mode="public",
            loinc_username="loinc-user",
            loinc_password="loinc-secret",
        )
    )

    assert config_store.get_sensitive("loinc_password") == "loinc-secret"

    data = json.loads(isolated_config_store.read_text(encoding="utf-8"))
    assert data["loinc_username"] == "loinc-user"
    assert "loinc_password" not in data


def test_load_config_masks_loinc_password(isolated_config_store):
    config_store.save_config(
        AppConfig(loinc_username="loinc-user", loinc_password="loinc-secret")
    )

    loaded = config_store.load_config()

    assert loaded.loinc_username == "loinc-user"
    assert loaded.loinc_password == config_store.MASKED_SECRET_SENTINEL
    assert loaded.loinc_password != "loinc-secret"


def test_saving_masked_loinc_password_does_not_replace_memory_secret():
    config_store.save_config(AppConfig(loinc_password="loinc-secret"))

    config_store.save_config(
        AppConfig(
            provider="ollama",
            model="llama3.2:latest",
            loinc_username="changed-user",
            loinc_password=config_store.MASKED_SECRET_SENTINEL,
        )
    )

    assert config_store.get_sensitive("loinc_password") == "loinc-secret"
    loaded = config_store.load_config()
    assert loaded.model == "llama3.2:latest"
    assert loaded.loinc_username == "changed-user"
    assert loaded.loinc_password == config_store.MASKED_SECRET_SENTINEL


def test_clearing_loinc_password_replaces_memory_secret():
    config_store.save_config(AppConfig(loinc_password="loinc-secret"))

    config_store.save_config(AppConfig(loinc_password=None))

    assert config_store.get_sensitive("loinc_password") is None
    assert config_store.load_config().loinc_password is None


def test_sensitive_values_are_not_printed(capsys):
    config_store.save_config(
        AppConfig(
            api_key="ai-secret",
            loinc_username="loinc-user",
            loinc_password="loinc-secret",
        )
    )
    config_store.load_config()

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "ai-secret" not in combined
    assert "loinc-secret" not in combined


def test_get_validated_loinc_credentials_returns_current_memory_secret():
    config_store.save_config(
        AppConfig(
            retrieval_mode="public",
            loinc_username="loinc-user",
            loinc_password="loinc-secret",
        )
    )
    config = config_store.load_config()
    config_store.set_retrieval_result(
        True,
        signature=config_store.current_public_retrieval_signature(config),
    )

    assert config_store.get_validated_loinc_credentials(config) == (
        "loinc-user",
        "loinc-secret",
    )


def test_get_validated_loinc_credentials_rejects_changed_username():
    config_store.save_config(
        AppConfig(
            retrieval_mode="public",
            loinc_username="loinc-user",
            loinc_password="loinc-secret",
        )
    )
    config = config_store.load_config()
    config_store.set_retrieval_result(
        True,
        signature=config_store.current_public_retrieval_signature(config),
    )

    changed = config.model_copy(update={"loinc_username": "other-user"})

    assert config_store.get_validated_loinc_credentials(changed) is None


def test_get_validated_loinc_credentials_rejects_memory_loss():
    config_store.save_config(
        AppConfig(
            retrieval_mode="public",
            loinc_username="loinc-user",
            loinc_password="loinc-secret",
        )
    )
    config = config_store.load_config()
    config_store.set_retrieval_result(
        True,
        signature=config_store.current_public_retrieval_signature(config),
    )
    config_store._sensitive["loinc_password"] = None

    assert config_store.get_validated_loinc_credentials(config) is None

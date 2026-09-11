"""Tests for save-time normalization of OpenAI reasoning_effort.

A reasoning_effort value must never be persisted unless Bridge's capability
registry currently confirms it is valid for the selected model — a value
left over from a previously selected model, or a model Bridge does not (yet)
know the reasoning contract for, must be dropped rather than saved as-is.
"""

import pytest

from app.api.config import _normalize_reasoning_effort, post_config
from app.models.config import AppConfig
from app.storage import config_store


@pytest.fixture(autouse=True)
def isolated_config_store(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(config_store, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config_store, "_CONFIG_FILE", config_file)
    original_sensitive = dict(config_store._sensitive)
    for key in config_store._sensitive:
        config_store._sensitive[key] = None
    yield config_file
    config_store._sensitive.clear()
    config_store._sensitive.update(original_sensitive)


def test_valid_reasoning_effort_for_supported_model_is_kept():
    config = AppConfig(provider="openai", model="gpt-5.1", reasoning_effort="high")
    assert _normalize_reasoning_effort(config).reasoning_effort == "high"


def test_invalid_reasoning_effort_for_supported_model_is_dropped():
    config = AppConfig(provider="openai", model="gpt-5.1", reasoning_effort="xhigh")
    assert _normalize_reasoning_effort(config).reasoning_effort is None


def test_reasoning_effort_for_unsupported_model_is_dropped():
    config = AppConfig(provider="openai", model="gpt-4o", reasoning_effort="low")
    assert _normalize_reasoning_effort(config).reasoning_effort is None


def test_reasoning_effort_for_unknown_model_is_dropped():
    config = AppConfig(
        provider="openai", model="gpt-9-nebula", reasoning_effort="low"
    )
    assert _normalize_reasoning_effort(config).reasoning_effort is None


def test_reasoning_effort_for_non_openai_provider_is_left_alone():
    config = AppConfig(provider="anthropic", model="claude-x", reasoning_effort="low")
    assert _normalize_reasoning_effort(config).reasoning_effort == "low"


def test_none_reasoning_effort_is_left_alone():
    config = AppConfig(provider="openai", model="gpt-5.1", reasoning_effort=None)
    assert _normalize_reasoning_effort(config).reasoning_effort is None


def test_stale_reasoning_effort_from_previous_model_is_not_saved(
    isolated_config_store,
):
    saved = post_config(
        AppConfig(provider="openai", model="gpt-4o", reasoning_effort="high")
    )

    assert saved.reasoning_effort is None
    assert config_store.load_config().reasoning_effort is None


def test_valid_reasoning_effort_is_saved_through_post_config(isolated_config_store):
    saved = post_config(
        AppConfig(provider="openai", model="gpt-5.1", reasoning_effort="medium")
    )

    assert saved.reasoning_effort == "medium"
    assert config_store.load_config().reasoning_effort == "medium"

"""Derives the status of each pipeline layer from the saved AppConfig."""

from typing import Literal

from app.models.config import AppConfig, LayerStatus
from app.storage.config_store import (
    get_connection_api_key_ok,
    get_connection_model_ok,
    get_connection_test_passed,
    get_connection_tested,
    get_retrieval_validation,
)

_CLOUD_PROVIDERS = frozenset({"openai", "anthropic", "ollama_cloud"})

_LayerState = Literal["ok", "warning", "disabled", "error"]


def _check_scispacy() -> bool:
    try:
        import spacy  # noqa: F401

        return True
    except ImportError:
        return False


def compute_layer_status(config: AppConfig) -> LayerStatus:
    # Layer 1 — NER
    if not config.use_ner:
        l1: _LayerState = "disabled"
    elif _check_scispacy():
        l1 = "ok"
    else:
        l1 = "warning"

    # Layer 2 — Retrieval (explicit validation only; not inferred from config defaults)
    if config.retrieval_mode == "disabled":
        l2: _LayerState = "disabled"
    else:
        retrieval = get_retrieval_validation()
        if retrieval == "ok":
            l2 = "ok"
        elif retrieval == "error":
            l2 = "error"
        else:
            l2 = "warning"

    # Layer 3 — AI model (cloud providers: green only when model_ok; local Ollama unchanged)
    if config.provider in _CLOUD_PROVIDERS:
        if get_connection_model_ok() is True:
            l3: _LayerState = "ok"
        elif get_connection_tested():
            l3 = "error" if get_connection_api_key_ok() is False else "warning"
        else:
            l3 = "warning"
    elif get_connection_test_passed():
        l3 = "ok"
    elif get_connection_tested():
        l3 = "error"
    else:
        l3 = "warning"

    return LayerStatus(layer1=l1, layer2=l2, layer3=l3)

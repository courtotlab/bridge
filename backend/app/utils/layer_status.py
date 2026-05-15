"""Derives the status of each pipeline layer from the saved AppConfig."""

from typing import Literal

import requests

from app.models.config import AppConfig, LayerStatus
from app.storage.config_store import get_connection_test_passed, get_connection_tested

_LayerState = Literal["ok", "warning", "disabled", "error"]


def _check_scispacy() -> bool:
    try:
        import spacy  # noqa: F401
        return True
    except ImportError:
        return False


def _server_reachable(url: str, timeout: float = 2.0) -> bool:
    try:
        requests.get(url, timeout=timeout)
        return True
    except Exception:
        return False


def compute_layer_status(config: AppConfig) -> LayerStatus:
    # Layer 1 — NER
    if not config.use_ner:
        l1: _LayerState = "disabled"
    elif _check_scispacy():
        l1 = "ok"
    else:
        l1 = "warning"

    # Layer 2 — Retrieval
    if config.retrieval_mode == "disabled":
        l2: _LayerState = "disabled"
    elif config.retrieval_mode == "public":
        l2 = "ok"
    else:  # local
        if _server_reachable(config.sapbert_server_url):
            l2 = "ok"
        else:
            l2 = "warning"

    # Layer 3 — AI model
    # Reflects the last Test Connection result; resets to "warning" on save.
    if get_connection_test_passed():
        l3: _LayerState = "ok"
    elif get_connection_tested():
        l3 = "error"
    else:
        l3 = "warning"

    return LayerStatus(layer1=l1, layer2=l2, layer3=l3)

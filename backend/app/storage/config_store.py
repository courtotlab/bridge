import json
from pathlib import Path

from app.models.config import AppConfig

_CONFIG_DIR = Path.home() / ".ontology_mapper"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

_SENSITIVE_FIELDS = {"api_key", "bioportal_api_key", "loinc_password"}

# Module-level store for sensitive fields — held in memory, never written to disk
_sensitive: dict[str, str | None] = {
    "api_key": None,
    "bioportal_api_key": None,
    "loinc_password": None,
}

# Connection-test result — held in memory, reset when config is saved
_connection_tested: bool = False
_connection_test_passed: bool = False
_connection_api_key_ok: bool | None = None
_connection_model_ok: bool | None = None

# Retrieval validation — held in memory, set by SapBERT check on connection test
_retrieval_validation: str = "untested"  # "untested" | "ok" | "error"


def get_connection_tested() -> bool:
    return _connection_tested


def get_connection_test_passed() -> bool:
    return _connection_test_passed


def get_connection_api_key_ok() -> bool | None:
    return _connection_api_key_ok


def get_connection_model_ok() -> bool | None:
    return _connection_model_ok


def set_connection_result(
    success: bool,
    *,
    api_key_ok: bool | None = None,
    model_ok: bool | None = None,
) -> None:
    global _connection_tested, _connection_test_passed, _connection_api_key_ok, _connection_model_ok
    _connection_tested = True
    _connection_test_passed = success
    _connection_api_key_ok = api_key_ok
    _connection_model_ok = model_ok


def invalidate_connection_test() -> None:
    global _connection_tested, _connection_test_passed, _connection_api_key_ok, _connection_model_ok
    _connection_tested = False
    _connection_test_passed = False
    _connection_api_key_ok = None
    _connection_model_ok = None


def get_retrieval_validation() -> str:
    return _retrieval_validation


def set_retrieval_result(passed: bool) -> None:
    global _retrieval_validation
    _retrieval_validation = "ok" if passed else "error"


def invalidate_retrieval_validation() -> None:
    global _retrieval_validation
    _retrieval_validation = "untested"


def load_config() -> AppConfig:
    if not _CONFIG_FILE.exists():
        config = AppConfig()
    else:
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            config = AppConfig(**data)
        except Exception:
            config = AppConfig()
    return config.model_copy(update=dict(_sensitive))


def save_config(config: AppConfig) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for field in _SENSITIVE_FIELDS:
        _sensitive[field] = getattr(config, field, None)
    data = config.model_dump(exclude=_SENSITIVE_FIELDS)
    _CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_sensitive(field: str) -> str | None:
    return _sensitive.get(field)


def cache_api_key(value: str | None) -> None:
    """Cache the api_key from a successful connection test, even before the user saves."""
    _sensitive["api_key"] = value

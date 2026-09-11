import hashlib
import json
from pathlib import Path

from app.models.config import AppConfig

_CONFIG_DIR = Path.home() / ".ontology_mapper"
_CONFIG_FILE = _CONFIG_DIR / "config.json"

MASKED_SECRET_SENTINEL = "••••••••"

_SENSITIVE_FIELDS = {"api_key", "loinc_password"}

# Module-level store for sensitive fields — held in memory, never written to disk
_sensitive: dict[str, str | None] = {
    "api_key": None,
    "loinc_password": None,
}

# Connection-test result — held in memory, reset when config is saved
_connection_tested: bool = False
_connection_test_passed: bool = False
_connection_api_key_ok: bool | None = None
_connection_model_ok: bool | None = None

# Retrieval validation — held in memory, set by SapBERT check on connection test
_retrieval_validation: str = "untested"  # "untested" | "ok" | "error"
_retrieval_validation_signature: str | None = None


def _public_retrieval_signature(
    username: str | None,
    password: str | None,
) -> str | None:
    normalized_username = username.strip() if username else ""
    if not normalized_username or not password:
        return None
    payload = f"public\0{normalized_username}\0{password}".encode()
    return hashlib.sha256(payload).hexdigest()


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
    global \
        _connection_tested, \
        _connection_test_passed, \
        _connection_api_key_ok, \
        _connection_model_ok
    _connection_tested = True
    _connection_test_passed = success
    _connection_api_key_ok = api_key_ok
    _connection_model_ok = model_ok


def invalidate_connection_test() -> None:
    global \
        _connection_tested, \
        _connection_test_passed, \
        _connection_api_key_ok, \
        _connection_model_ok
    _connection_tested = False
    _connection_test_passed = False
    _connection_api_key_ok = None
    _connection_model_ok = None


def get_retrieval_validation() -> str:
    return _retrieval_validation


def set_retrieval_result(
    passed: bool,
    *,
    signature: str | None = None,
) -> None:
    global _retrieval_validation, _retrieval_validation_signature
    _retrieval_validation = "ok" if passed else "error"
    _retrieval_validation_signature = signature if passed else None


def invalidate_retrieval_validation() -> None:
    global _retrieval_validation, _retrieval_validation_signature
    _retrieval_validation = "untested"
    _retrieval_validation_signature = None


def current_public_retrieval_signature(config: AppConfig) -> str | None:
    password = config.loinc_password
    if password == MASKED_SECRET_SENTINEL:
        password = get_sensitive("loinc_password")
    return _public_retrieval_signature(config.loinc_username, password)


def is_retrieval_validation_current(config: AppConfig) -> bool:
    if _retrieval_validation != "ok":
        return False
    if config.retrieval_mode != "public":
        return True
    signature = current_public_retrieval_signature(config)
    return signature is not None and signature == _retrieval_validation_signature


def get_validated_loinc_credentials(config: AppConfig) -> tuple[str, str] | None:
    """Return active validated LOINC credentials for backend-only use."""
    if config.retrieval_mode != "public":
        return None
    username = config.loinc_username.strip() if config.loinc_username else None
    password = get_sensitive("loinc_password")
    if not username or not password:
        return None
    signature_config = config.model_copy(
        update={"loinc_username": username, "loinc_password": password}
    )
    if not is_retrieval_validation_current(signature_config):
        return None
    return username, password


def load_config() -> AppConfig:
    if not _CONFIG_FILE.exists():
        config = AppConfig()
    else:
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            config = AppConfig(**data)
        except Exception:  # noqa: BLE001 - malformed local config falls back to defaults
            config = AppConfig()
    sensitive = dict(_sensitive)
    if sensitive.get("loinc_password"):
        sensitive["loinc_password"] = MASKED_SECRET_SENTINEL
    return config.model_copy(update=sensitive)


def save_config(config: AppConfig) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for field in _SENSITIVE_FIELDS:
        value = getattr(config, field, None)
        if field == "loinc_password" and value == MASKED_SECRET_SENTINEL:
            continue
        _sensitive[field] = value
    data = config.model_dump(exclude=_SENSITIVE_FIELDS)
    _CONFIG_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_sensitive(field: str) -> str | None:
    return _sensitive.get(field)


def cache_loinc_password(value: str | None) -> None:
    """Cache validated LOINC password before the user saves settings."""
    _sensitive["loinc_password"] = value


def cache_api_key(value: str | None) -> None:
    """Cache the api_key from a successful connection test before save."""
    _sensitive["api_key"] = value

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

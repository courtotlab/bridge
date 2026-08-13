import logging
from typing import Any
from urllib.parse import urlsplit


class UvicornAccessNoiseFilter(logging.Filter):
    """Suppress routine successful polling from Uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            method, path, status = _uvicorn_access_parts(record.args)
            if status >= 400:
                return True
            if method == "GET" and _is_successful_polling_path(path):
                return False
            if method == "OPTIONS":
                return False
        except Exception:  # noqa: BLE001 - access logging must fail open
            return True
        return True


def configure_access_log_filter() -> None:
    """Attach Bridge's access-log noise filter to Uvicorn's access logger."""

    access_logger = logging.getLogger("uvicorn.access")
    if any(isinstance(f, UvicornAccessNoiseFilter) for f in access_logger.filters):
        return
    access_logger.addFilter(UvicornAccessNoiseFilter())


def _uvicorn_access_parts(args: Any) -> tuple[str, str, int]:
    if not isinstance(args, tuple) or len(args) < 5:
        raise ValueError("unexpected uvicorn access log arguments")

    method = str(args[1]).upper()
    raw_path = str(args[2])
    status = int(args[4])
    path = urlsplit(raw_path).path or raw_path
    return method, path, status


def _is_successful_polling_path(path: str) -> bool:
    return path.startswith("/api/batch/status/") or path == "/api/config/status"

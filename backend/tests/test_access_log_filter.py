import logging

from app.logging import UvicornAccessNoiseFilter, configure_access_log_filter


def _record(method: str, path: str, status: int) -> logging.LogRecord:
    return logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:12345", method, path, "1.1", status),
        exc_info=None,
    )


def _allows(method: str, path: str, status: int) -> bool:
    return bool(UvicornAccessNoiseFilter().filter(_record(method, path, status)))


def test_successful_batch_status_polling_is_suppressed() -> None:
    assert not _allows("GET", "/api/batch/status/abc123", 200)
    assert not _allows("GET", "/api/batch/status/abc123?ts=1", 204)


def test_successful_config_status_polling_is_suppressed() -> None:
    assert not _allows("GET", "/api/config/status", 200)
    assert not _allows("GET", "/api/config/status?refresh=1", 200)


def test_failed_batch_status_requests_remain_visible() -> None:
    assert _allows("GET", "/api/batch/status/abc123", 404)
    assert _allows("GET", "/api/batch/status/abc123", 500)


def test_failed_config_status_requests_remain_visible() -> None:
    assert _allows("GET", "/api/config/status", 500)


def test_normal_request_remains_visible() -> None:
    assert _allows("POST", "/api/batch/start", 200)
    assert _allows("POST", "/api/map/single", 200)
    assert _allows("POST", "/api/config/test", 200)


def test_successful_options_requests_are_suppressed_but_failures_remain_visible() -> None:
    assert not _allows("OPTIONS", "/api/config/test", 200)
    assert not _allows("OPTIONS", "/api/history", 204)
    assert _allows("OPTIONS", "/api/config/test", 500)


def test_malformed_access_log_record_is_allowed() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="unexpected",
        args=("not", "uvicorn"),
        exc_info=None,
    )

    assert UvicornAccessNoiseFilter().filter(record)


def test_configure_access_log_filter_is_idempotent() -> None:
    logger = logging.getLogger("uvicorn.access")
    original_filters = list(logger.filters)
    logger.filters = [
        f for f in logger.filters if not isinstance(f, UvicornAccessNoiseFilter)
    ]
    try:
        configure_access_log_filter()
        configure_access_log_filter()

        installed = [
            f for f in logger.filters if isinstance(f, UvicornAccessNoiseFilter)
        ]
        assert len(installed) == 1
    finally:
        logger.filters = original_filters

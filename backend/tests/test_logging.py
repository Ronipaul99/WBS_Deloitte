import logging

from app.core.logging import PathOnlyAccessLogFilter, install_access_log_redaction


def test_uvicorn_access_logs_remove_query_secrets():
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:1234",
            "GET",
            "/api/v1/auth/sso/callback?code=provider-secret&state=state-secret",
            "1.1",
            303,
        ),
        exc_info=None,
    )

    assert PathOnlyAccessLogFilter().filter(record)
    message = record.getMessage()
    assert "/api/v1/auth/sso/callback" in message
    assert "provider-secret" not in message
    assert "state-secret" not in message
    assert "?" not in message


def test_access_log_filter_installation_is_idempotent():
    logger = logging.getLogger("uvicorn.access")
    before = sum(isinstance(item, PathOnlyAccessLogFilter) for item in logger.filters)
    install_access_log_redaction()
    install_access_log_redaction()
    after = sum(isinstance(item, PathOnlyAccessLogFilter) for item in logger.filters)
    assert after == max(before, 1)

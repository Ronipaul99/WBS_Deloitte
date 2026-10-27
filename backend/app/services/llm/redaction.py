"""Suppress sensitive low-level diagnostics only inside this transport's task context."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar

_SENSITIVE = ContextVar("llm_sensitive_io", default=False)
_LOGGERS = (
    "httpcore.connection",
    "httpcore.http11",
    "httpcore.http2",
    "httpcore.proxy",
    "httpcore.socks",
    "httpx",
)


class LlmDiagnosticFilter(logging.Filter):
    def filter(self, record):
        if _SENSITIVE.get():
            # Drop all values, including arbitrary extra fields, stack traces and error bodies.
            safe = logging.LogRecord(
                record.name, record.levelno, "", 0, "LLM transport diagnostic suppressed", (), None
            )
            record.__dict__.clear()
            record.__dict__.update(safe.__dict__)
        return True


@contextmanager
def sensitive_io():
    for name in _LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(item, LlmDiagnosticFilter) for item in logger.filters):
            logger.addFilter(LlmDiagnosticFilter())
    token = _SENSITIVE.set(True)
    try:
        yield
    finally:
        _SENSITIVE.reset(token)

import logging
from typing import Any


class PathOnlyAccessLogFilter(logging.Filter):
    """Remove query strings from Uvicorn access-log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name != "uvicorn.access" or not isinstance(record.args, tuple):
            return True
        if len(record.args) < 3:
            return True
        args: list[Any] = list(record.args)
        args[2] = str(args[2]).split("?", 1)[0]
        record.args = tuple(args)
        return True


def install_access_log_redaction() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, PathOnlyAccessLogFilter) for item in logger.filters):
        logger.addFilter(PathOnlyAccessLogFilter())

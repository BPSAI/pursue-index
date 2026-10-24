"""pursue-index: searchable index of DOW PURSUE UAP releases."""

from __future__ import annotations

import logging
import sys

import structlog

from pursue_index.config import settings
from pursue_index.paths import UntrustedRootError

__version__ = "0.1.0"


def _log_settings() -> tuple[str, str]:
    try:
        return settings.log_level, settings.log_format
    except UntrustedRootError:
        # An untrusted working directory is reported by the command that needs
        # the data root, not as a traceback while the package imports.
        return "INFO", "console"


def _configure_logging() -> None:
    log_level, log_format = _log_settings()
    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=level,
    )

    processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


_configure_logging()

get_logger = structlog.get_logger

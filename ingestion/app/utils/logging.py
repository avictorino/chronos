"""Structured-ish logging on top of stdlib `logging` — no structlog dependency.

Produces lines like:

    10:32:01 INFO  [EVENT] Processing Battle of Marathon event_id=evt_...

DEBUG level additionally logs prompts / raw LLM responses (never at INFO, to
keep logs readable — see spec/03-architecture-spec.md).
"""

from __future__ import annotations

import logging
import sys


class _TagFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        tag = getattr(record, "tag", None)
        prefix = f"[{tag}] " if tag else ""
        context: dict[str, object] = getattr(record, "context", {}) or {}
        context_str = " " + " ".join(f"{k}={v}" for k, v in context.items()) if context else ""
        timestamp = self.formatTime(record, "%H:%M:%S")
        return f"{timestamp} {record.levelname:<5} {prefix}{record.getMessage()}{context_str}"


_ROOT_NAME = "chronos"


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger(_ROOT_NAME)
    root.setLevel(level.upper())
    if root.handlers:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_TagFormatter())
    root.addHandler(handler)
    root.propagate = False


class ChronosLogger:
    """Thin wrapper giving `log.info(tag, message, **context)` ergonomics."""

    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, level: int, tag: str, message: str, **context: object) -> None:
        self._logger.log(level, message, extra={"tag": tag, "context": context})

    def debug(self, tag: str, message: str, **context: object) -> None:
        self._log(logging.DEBUG, tag, message, **context)

    def info(self, tag: str, message: str, **context: object) -> None:
        self._log(logging.INFO, tag, message, **context)

    def warning(self, tag: str, message: str, **context: object) -> None:
        self._log(logging.WARNING, tag, message, **context)

    def error(self, tag: str, message: str, **context: object) -> None:
        self._log(logging.ERROR, tag, message, **context)


def get_logger(name: str) -> ChronosLogger:
    return ChronosLogger(logging.getLogger(f"{_ROOT_NAME}.{name}"))

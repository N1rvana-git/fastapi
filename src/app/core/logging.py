"""Structured logging.

Production wants one JSON object per line (easy to ship to Loki/ELK and to grep
by ``trace_id``); local development wants something readable.  Both are the same
logger, switched by ``LOG_FORMAT``.

``structlog`` would be the usual choice, but the deployed environment cannot
install it, so this module implements the tiny subset that matters:
contextvars injection + a JSON formatter + ``bind``-style extras via
``logger.info("...", extra={"event": ...})``.
"""

from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from typing import Any

from src.app.core.config import Settings
from src.app.core.context import get_request_id, get_route, get_trace_id, get_user_id

_RESERVED = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "module",
        "msecs",
        "message",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """Minimal JSON formatter with request context enrichment."""

    def __init__(self, *, include_exc: bool = True) -> None:
        super().__init__()
        self.include_exc = include_exc

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        trace_id = get_trace_id()
        if trace_id:
            payload["trace_id"] = trace_id
        request_id = get_request_id()
        if request_id:
            payload["request_id"] = request_id
        user_id = get_user_id()
        if user_id:
            payload["user_id"] = user_id
        route = get_route()
        if route:
            payload["route"] = route

        for key, value in record.__dict__.items():
            if key in _RESERVED or key.startswith("_"):
                continue
            payload[key] = _coerce(value)

        if self.include_exc and record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack_info"] = record.stack_info
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    """Human-friendly formatter for local development."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )


def _coerce(value: object) -> object:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(k): _coerce(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_coerce(v) for v in value]
    return str(value)


def configure_logging(settings: Settings) -> None:
    """Idempotently install the root logging configuration."""

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    formatter: logging.Formatter = (
        JsonFormatter() if settings.LOG_FORMAT == "json" else TextFormatter()
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Quieten chatty third parties; our own loggers stay at the configured level.
    for noisy, noisy_level in {
        "uvicorn.access": logging.WARNING,
        "uvicorn.error": logging.INFO,
        "httpx": logging.WARNING,
        "httpcore": logging.WARNING,
        "sqlalchemy.engine": logging.WARNING,
        "asyncio": logging.WARNING,
    }.items():
        logging.getLogger(noisy).setLevel(max(level, noisy_level))


def get_logger(name: str) -> logging.Logger:
    """Thin wrapper so call sites do not import ``logging`` directly."""

    return logging.getLogger(name)


def log_extra(**values: Any) -> dict[str, Any]:
    """Build an ``extra=`` mapping while avoiding ``LogRecord`` collisions."""

    return {f"ctx_{key}" if key in _RESERVED else key: value for key, value in values.items()}

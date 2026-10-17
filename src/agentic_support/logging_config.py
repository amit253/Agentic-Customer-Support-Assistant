"""Structured, traceable, and secret-redacting application logging."""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, TextIO

from .tracing import get_trace_id


_SECRET_PATTERNS = (
    re.compile(r"(?i)(?:gsk_|sk-)[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(Bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)((?:GROQ_API_KEY|GROQ_API_KEYS)\s*[=:]\s*)[^,\s]+"
    ),
)


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub("[REDACTED]", redacted)
    return redacted


def redact_secrets(value: Any) -> Any:
    """Recursively redact common provider-token shapes from log data."""

    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, Mapping):
        return {str(key): redact_secrets(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact_secrets(item) for item in value]
    return value


class TraceContextFilter(logging.Filter):
    """Attach the current traceability ID to every application log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = get_trace_id()
        return True


class JsonFormatter(logging.Formatter):
    """Format one log event as a single JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", get_trace_id()),
            "message": _redact_text(record.getMessage()),
        }

        event = getattr(record, "event", None)
        if event is not None:
            payload["event"] = _redact_text(str(event))

        fields = getattr(record, "fields", None)
        if fields is not None:
            payload["fields"] = redact_secrets(fields)

        if record.exc_info:
            payload["exception"] = _redact_text(self.formatException(record.exc_info))

        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(
    *,
    level: str = "INFO",
    json_logs: bool = True,
    stream: TextIO | None = None,
) -> logging.Logger:
    """Configure the package logger and return it.

    The handler is attached to the package logger rather than the root logger,
    so library users do not unexpectedly replace unrelated application logs.
    Calling this function again replaces only the package's own handlers.
    """

    logger = logging.getLogger("agentic_support")
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(level.upper())

    handler = logging.StreamHandler(stream or sys.stderr)
    handler.addFilter(TraceContextFilter())
    if json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s "
                "trace_id=%(trace_id)s %(message)s"
            )
        )
    logger.addHandler(handler)
    return logger


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """Write a structured event whose fields are redacted by the formatter."""

    logger.info(event, extra={"event": event, "fields": fields})

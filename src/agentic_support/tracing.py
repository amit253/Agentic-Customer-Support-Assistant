"""Traceability-ID context shared by logs and future transports."""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


_TRACE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_trace_id: ContextVar[str | None] = ContextVar("agentic_support_trace_id", default=None)


def new_trace_id() -> str:
    """Create a non-secret identifier suitable for logs and support tickets."""

    return uuid.uuid4().hex


def resolve_trace_id(candidate: str | None) -> str:
    """Accept a safe inbound ID or create a new one.

    Invalid values are replaced rather than logged. This prevents control
    characters or unbounded user input from becoming log content.
    """

    if candidate is not None and _TRACE_ID_PATTERN.fullmatch(candidate):
        return candidate
    return new_trace_id()


def get_trace_id() -> str:
    """Return the current trace ID, creating one for unscoped work if needed."""

    current = _trace_id.get()
    if current is None:
        current = new_trace_id()
        _trace_id.set(current)
    return current


@contextmanager
def trace_context(trace_id: str | None = None) -> Iterator[str]:
    """Set a trace ID for the current synchronous or asynchronous context."""

    value = resolve_trace_id(trace_id)
    token = _trace_id.set(value)
    try:
        yield value
    finally:
        _trace_id.reset(token)

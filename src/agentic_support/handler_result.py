"""Handler output type shared by every agent/handler module."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class HandlerResult:
    """Handler output before the pipeline wraps it in a support response."""

    message: str
    handler_name: str
    metadata: Mapping[str, object] = field(default_factory=dict)

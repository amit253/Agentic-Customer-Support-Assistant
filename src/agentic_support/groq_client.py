"""Shared Groq chat client with key rotation, timeouts, and reasoning effort.

Every live adapter (input guard, router, grounded answerer, tool caller) used
to construct its own client from the first configured key, so extra keys in
``GROQ_API_KEYS`` were never used and a rate limit on one key failed the turn.
This module builds one client per key and rotates to the next key when the
current one is rate limited. Key values are never logged; only the key index.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from threading import Lock
from types import SimpleNamespace
from typing import Any

from .config import Settings
from .logging_config import log_event


# When every key is rate limited, wait at most this long for the provider's
# retry-after before one more round. A bounded wait is better for a support
# turn than an immediate failure, and the cap keeps a turn from hanging.
MAX_RATE_LIMIT_WAIT_SECONDS = 8.0

# Models that accept Groq's ``reasoning_effort`` parameter.
_REASONING_MODEL_PREFIXES = ("openai/gpt-oss",)


def _is_rate_limited(error: BaseException) -> bool:
    return getattr(error, "status_code", None) == 429


def _retry_after_seconds(error: BaseException) -> float:
    """Read the provider's retry-after header, defaulting to one second."""

    headers = getattr(getattr(error, "response", None), "headers", None) or {}
    try:
        return max(0.0, float(headers.get("retry-after", 1.0)))
    except (TypeError, ValueError):
        return 1.0


def reasoning_options(
    settings: Settings, model_name: str, *, effort: str | None = None
) -> dict[str, str]:
    """Return ``reasoning_effort`` only for models that support it.

    ``effort`` overrides the global setting for one adapter (the router).
    """

    effort = settings.groq_reasoning_effort if effort is None else effort
    if not effort or not model_name.startswith(_REASONING_MODEL_PREFIXES):
        return {}
    return {"reasoning_effort": effort}


class RotatingChatClient:
    """Expose ``chat.completions.create`` and rotate keys on HTTP 429.

    A non-rate-limit error is raised immediately so callers keep their own
    fail-closed handling. If every key is rate limited, the client waits for
    the provider's retry-after (capped) and tries one more round; if that
    round is also rate limited, the last 429 is raised.
    """

    def __init__(
        self,
        clients: Sequence[Any],
        *,
        logger: logging.Logger | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        max_wait_seconds: float = MAX_RATE_LIMIT_WAIT_SECONDS,
    ) -> None:
        if not clients:
            raise ValueError("at least one provider client is required")
        self._clients = list(clients)
        self._index = 0
        self._lock = Lock()
        self._logger = logger or logging.getLogger("agentic_support.groq")
        self.rotations = 0
        self.rate_limit_waits = 0
        self._sleeper = sleeper
        self._max_wait_seconds = max_wait_seconds
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    @property
    def key_count(self) -> int:
        return len(self._clients)

    def _create(self, **request: Any) -> Any:
        try:
            return self._one_round(request)
        except Exception as error:
            if not _is_rate_limited(error) or self._max_wait_seconds <= 0:
                raise
            wait = min(_retry_after_seconds(error), self._max_wait_seconds)
            self.rate_limit_waits += 1
            log_event(
                self._logger,
                "groq_all_keys_rate_limited",
                wait_seconds=wait,
                key_count=len(self._clients),
            )
            self._sleeper(wait)
            return self._one_round(request)

    def _one_round(self, request: dict[str, Any]) -> Any:
        last_error: BaseException | None = None
        for _ in range(len(self._clients)):
            with self._lock:
                index = self._index
            try:
                return self._clients[index].chat.completions.create(**request)
            except Exception as error:
                if not _is_rate_limited(error) or len(self._clients) == 1:
                    raise
                last_error = error
                with self._lock:
                    if self._index == index:
                        self._index = (index + 1) % len(self._clients)
                        self.rotations += 1
                log_event(
                    self._logger,
                    "groq_key_rotated",
                    from_key_index=index,
                    key_count=len(self._clients),
                )
        assert last_error is not None
        raise last_error


def build_groq_chat_client(settings: Settings) -> RotatingChatClient:
    """Build one Groq SDK client per configured key behind one rotator.

    With several keys the SDK's own retry is disabled so a 429 rotates to the
    next key immediately. With one key the SDK keeps its backoff retries.
    """

    from groq import Groq

    keys = settings.require_groq_credentials()
    max_retries = 0 if len(keys) > 1 else 2
    clients = [
        Groq(
            api_key=key,
            timeout=settings.groq_timeout_seconds,
            max_retries=max_retries,
        )
        for key in keys
    ]
    return RotatingChatClient(clients)

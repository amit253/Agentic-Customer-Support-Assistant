"""Shared Groq chat client with key rotation, timeouts, and reasoning effort.

Every live adapter (input guard, router, grounded answerer, tool caller) used
to construct its own client from the first configured key, so extra keys in
``GROQ_API_KEYS`` were never used and a rate limit on one key failed the turn.
This module builds one client per key and rotates to the next key when the
current one is rate limited. Key values are never logged; only the key index.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from threading import Lock
from types import SimpleNamespace
from typing import Any

from .config import Settings
from .logging_config import log_event


# Models that accept Groq's ``reasoning_effort`` parameter.
_REASONING_MODEL_PREFIXES = ("openai/gpt-oss",)


def _is_rate_limited(error: BaseException) -> bool:
    return getattr(error, "status_code", None) == 429


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
    fail-closed handling. If every key is rate limited, the last 429 is raised.
    """

    def __init__(
        self,
        clients: Sequence[Any],
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        if not clients:
            raise ValueError("at least one provider client is required")
        self._clients = list(clients)
        self._index = 0
        self._lock = Lock()
        self._logger = logger or logging.getLogger("agentic_support.groq")
        self.rotations = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    @property
    def key_count(self) -> int:
        return len(self._clients)

    def _create(self, **request: Any) -> Any:
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

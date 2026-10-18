from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest

from agentic_support.config import ConfigurationError, Settings
from agentic_support.groq_client import RotatingChatClient, reasoning_options


class RateLimitError(Exception):
    status_code = 429


class BadRequestError(Exception):
    status_code = 400


class FakeKeyClient:
    def __init__(self, name: str, failures: list[Exception]) -> None:
        self.name = name
        self.failures = failures
        self.calls = 0
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs: object) -> str:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return f"answer from {self.name}"


def test_rate_limited_key_rotates_to_the_next_key(caplog: pytest.LogCaptureFixture) -> None:
    first = FakeKeyClient("key-a", [RateLimitError("429 for sk-secret-value")])
    second = FakeKeyClient("key-b", [])
    client = RotatingChatClient([first, second])

    with caplog.at_level(logging.INFO):
        result = client.chat.completions.create(model="m", messages=[])

    assert result == "answer from key-b"
    assert client.rotations == 1
    assert "sk-secret-value" not in caplog.text
    # The next request starts on the key that worked.
    assert client.chat.completions.create(model="m", messages=[]) == "answer from key-b"
    assert first.calls == 1


def test_non_rate_limit_errors_are_not_hidden_by_rotation() -> None:
    first = FakeKeyClient("key-a", [BadRequestError("bad request")])
    second = FakeKeyClient("key-b", [])
    client = RotatingChatClient([first, second])

    with pytest.raises(BadRequestError):
        client.chat.completions.create(model="m", messages=[])
    assert second.calls == 0


def test_all_keys_rate_limited_waits_once_then_succeeds() -> None:
    waits: list[float] = []
    client = RotatingChatClient(
        [FakeKeyClient("a", [RateLimitError()]), FakeKeyClient("b", [RateLimitError()])],
        sleeper=waits.append,
    )

    result = client.chat.completions.create(model="m", messages=[])

    assert result in {"answer from a", "answer from b"}
    assert waits == [1.0]
    assert client.rate_limit_waits == 1


def test_persistent_rate_limit_is_raised_after_one_bounded_wait() -> None:
    waits: list[float] = []

    class LongRetry(RateLimitError):
        response = SimpleNamespace(headers={"retry-after": "120"})

    client = RotatingChatClient(
        [FakeKeyClient("a", [LongRetry(), LongRetry()]), FakeKeyClient("b", [LongRetry(), LongRetry()])],
        sleeper=waits.append,
    )

    with pytest.raises(RateLimitError):
        client.chat.completions.create(model="m", messages=[])
    assert waits == [8.0]  # capped, never the provider's 120 seconds


def test_reasoning_effort_is_sent_only_to_models_that_support_it() -> None:
    settings = Settings.from_environment({"GROQ_REASONING_EFFORT": "low"})

    assert reasoning_options(settings, "openai/gpt-oss-20b") == {"reasoning_effort": "low"}
    assert reasoning_options(settings, "llama-3.1-8b-instant") == {}
    assert reasoning_options(Settings.from_environment({}), "openai/gpt-oss-20b") == {}


def test_reasoning_and_timeout_settings_are_validated() -> None:
    with pytest.raises(ConfigurationError):
        Settings.from_environment({"GROQ_REASONING_EFFORT": "extreme"})
    with pytest.raises(ConfigurationError):
        Settings.from_environment({"GROQ_TIMEOUT_SECONDS": "0"})
    assert Settings.from_environment({}).groq_timeout_seconds == 15.0


def test_router_defaults_to_low_reasoning_effort_and_others_do_not() -> None:
    from types import SimpleNamespace as NS

    from agentic_support.routing import GroqStructuredClassifier

    captured: dict[str, object] = {}

    def create(**kwargs: object) -> object:
        captured.update(kwargs)
        return NS(choices=[NS(message=NS(content='{"intent": "smalltalk", "confidence": 0.9}'))])

    settings = Settings.from_environment({"GROQ_ROUTER_MODEL": "openai/gpt-oss-20b"})
    client = NS(chat=NS(completions=NS(create=create)))
    GroqStructuredClassifier(settings, client=client).classify("hi")

    assert captured["reasoning_effort"] == "low"
    assert reasoning_options(settings, "openai/gpt-oss-20b") == {}

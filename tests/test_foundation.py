from __future__ import annotations

import json
from io import StringIO

import pytest

from agentic_support.config import ConfigurationError, Settings
from agentic_support.health import health_payload
from agentic_support.logging_config import configure_logging, log_event
from agentic_support.tracing import get_trace_id, trace_context


def test_keyless_configuration_is_valid_but_live_calls_are_explicit() -> None:
    settings = Settings.from_environment({})

    assert settings.groq_configured is False
    assert settings.public_dict()["groq_key_count"] == 0
    with pytest.raises(ConfigurationError, match="required for live provider calls"):
        settings.require_groq_credentials()


def test_multiple_provider_keys_are_parsed_without_leaking_them() -> None:
    settings = Settings.from_environment(
        {
            "GROQ_API_KEY": "gsk_primary_fake_value",
            "GROQ_API_KEYS": "gsk_primary_fake_value, gsk_secondary_fake_value",
        }
    )

    assert settings.groq_configured is True
    assert len(settings.groq_api_keys) == 2
    public = json.dumps(settings.public_dict())
    assert "gsk_primary_fake_value" not in public
    assert "gsk_secondary_fake_value" not in public


def test_extra_named_key_variables_are_used_and_deduplicated() -> None:
    settings = Settings.from_environment(
        {
            "GROQ_API_KEY": "gsk_primary_fake_value",
            "GROQ_API_KEYS": "gsk_primary_fake_value",
            "GROQ_ANOTHER_KEY": "gsk_another_fake_value",
            "GROQ_API_KEY_2": "gsk_numbered_fake_value",
            "GROQ_ROUTER_MODEL": "not-a-key",
            "GROQ_MONKEY": "not-a-key",
        }
    )

    assert len(settings.groq_api_keys) == 3
    assert "not-a-key" not in settings.groq_api_keys
    assert "gsk_another_fake_value" not in json.dumps(settings.public_dict())


def test_invalid_log_configuration_fails_without_echoing_input() -> None:
    with pytest.raises(ConfigurationError, match="LOG_LEVEL must be"):
        Settings.from_environment({"LOG_LEVEL": "not-a-level"})


def test_trace_context_propagates_and_rejects_unsafe_inbound_ids() -> None:
    with trace_context("support-request-42"):
        assert get_trace_id() == "support-request-42"

    with trace_context("bad\nlog-injection") as generated_id:
        assert generated_id != "bad\nlog-injection"
        assert "\n" not in generated_id
        assert get_trace_id() == generated_id


def test_json_logs_include_trace_id_and_redact_provider_tokens() -> None:
    stream = StringIO()
    logger = configure_logging(level="INFO", json_logs=True, stream=stream)

    with trace_context("trace-for-test"):
        log_event(
            logger,
            "provider_request",
            provider="groq",
            api_key="gsk_secret_fake_value",
        )

    output = stream.getvalue()
    event = json.loads(output)
    assert event["trace_id"] == "trace-for-test"
    assert event["event"] == "provider_request"
    assert event["fields"]["api_key"] == "[REDACTED]"
    assert "gsk_secret_fake_value" not in output


def test_text_logs_also_include_trace_id() -> None:
    stream = StringIO()
    logger = configure_logging(level="INFO", json_logs=False, stream=stream)

    with trace_context("text-trace"):
        logger.info("debuggable message")

    assert "trace_id=text-trace" in stream.getvalue()


def test_health_payload_exposes_status_only() -> None:
    settings = Settings.from_environment({"APP_NAME": "test-service"})

    assert health_payload(settings) == {
        "status": "ok",
        "service": "test-service",
        "environment": "development",
        "groq_configured": False,
    }

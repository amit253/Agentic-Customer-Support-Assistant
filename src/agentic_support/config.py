"""Safe application configuration.

This module reads configuration from the process environment. It deliberately
does not print or log provider-key values. Live-provider code can call
``require_groq_credentials`` when it is actually ready to make a request;
keyless tests can load the same settings without a key.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Mapping


class ConfigurationError(ValueError):
    """Raised when a configuration value is invalid or missing."""


_ALLOWED_LOG_FORMATS = frozenset({"json", "text"})
_ALLOWED_LOG_LEVELS = frozenset(
    {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
)
_ALLOWED_REASONING_EFFORTS = frozenset({"", "low", "medium", "high"})


# Extra keys may be added as any GROQ_<NAME>_KEY variable (for example
# GROQ_SECOND_KEY or GROQ_API_KEY_2) in addition to GROQ_API_KEY and the
# comma-separated GROQ_API_KEYS. Only variable names are ever inspected.
_EXTRA_KEY_VARIABLE = re.compile(r"^GROQ_(?:[A-Z0-9]+_)*KEYS?(?:_\d+)?$")


def _read_groq_keys(environment: Mapping[str, str]) -> tuple[str, ...]:
    """Return configured Groq keys without exposing their values to callers."""

    variable_names = ["GROQ_API_KEY", "GROQ_API_KEYS"] + sorted(
        name
        for name in environment
        if _EXTRA_KEY_VARIABLE.match(name)
        and name not in ("GROQ_API_KEY", "GROQ_API_KEYS")
    )
    candidates: list[str] = []
    for variable_name in variable_names:
        raw_value = environment.get(variable_name, "")
        candidates.extend(
            value.strip() for value in raw_value.split(",") if value.strip()
        )

    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return tuple(unique)


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated configuration used by the application foundation."""

    app_name: str
    environment: str
    log_level: str
    log_format: str
    groq_router_model: str
    groq_stt_model: str
    groq_tts_model: str
    groq_tts_voice: str
    router_max_attempts: int
    router_retry_delay_seconds: float
    groq_api_keys: tuple[str, ...]
    groq_reasoning_effort: str = ""
    groq_timeout_seconds: float = 15.0

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "Settings":
        """Load settings without requiring a live-provider key."""

        if environment is None:
            from dotenv import load_dotenv

            load_dotenv(override=False)
            source = os.environ
        else:
            source = environment
        log_level = source.get("LOG_LEVEL", "INFO").strip().upper()
        if log_level not in _ALLOWED_LOG_LEVELS:
            raise ConfigurationError(
                "LOG_LEVEL must be CRITICAL, ERROR, WARNING, INFO, or DEBUG"
            )

        log_format = source.get("LOG_FORMAT", "json").strip().lower()
        if log_format not in _ALLOWED_LOG_FORMATS:
            raise ConfigurationError("LOG_FORMAT must be json or text")

        app_name = source.get("APP_NAME", "agentic-customer-support").strip()
        if not app_name:
            raise ConfigurationError("APP_NAME must not be empty")

        environment_name = source.get("APP_ENV", "development").strip()
        if not environment_name:
            raise ConfigurationError("APP_ENV must not be empty")

        groq_router_model = source.get(
            "GROQ_ROUTER_MODEL", "openai/gpt-oss-20b"
        ).strip()
        if not groq_router_model:
            raise ConfigurationError("GROQ_ROUTER_MODEL must not be empty")

        groq_stt_model = source.get(
            "GROQ_STT_MODEL", "whisper-large-v3-turbo"
        ).strip()
        groq_tts_model = source.get(
            "GROQ_TTS_MODEL", "canopylabs/orpheus-v1-english"
        ).strip()
        groq_tts_voice = source.get("GROQ_TTS_VOICE", "austin").strip()
        if not groq_stt_model or not groq_tts_model or not groq_tts_voice:
            raise ConfigurationError("STT/TTS model and voice settings must not be empty")

        try:
            router_max_attempts = int(source.get("ROUTER_MAX_ATTEMPTS", "2"))
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("ROUTER_MAX_ATTEMPTS must be an integer") from exc
        if router_max_attempts < 1:
            raise ConfigurationError("ROUTER_MAX_ATTEMPTS must be at least one")

        try:
            router_retry_delay_seconds = float(
                source.get("ROUTER_RETRY_DELAY_SECONDS", "0.25")
            )
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                "ROUTER_RETRY_DELAY_SECONDS must be numeric"
            ) from exc
        if router_retry_delay_seconds < 0:
            raise ConfigurationError(
                "ROUTER_RETRY_DELAY_SECONDS must not be negative"
            )

        groq_reasoning_effort = source.get("GROQ_REASONING_EFFORT", "").strip().lower()
        if groq_reasoning_effort not in _ALLOWED_REASONING_EFFORTS:
            raise ConfigurationError(
                "GROQ_REASONING_EFFORT must be empty, low, medium, or high"
            )

        try:
            groq_timeout_seconds = float(source.get("GROQ_TIMEOUT_SECONDS", "15"))
        except (TypeError, ValueError) as exc:
            raise ConfigurationError("GROQ_TIMEOUT_SECONDS must be numeric") from exc
        if groq_timeout_seconds <= 0:
            raise ConfigurationError("GROQ_TIMEOUT_SECONDS must be positive")

        return cls(
            app_name=app_name,
            environment=environment_name,
            log_level=log_level,
            log_format=log_format,
            groq_router_model=groq_router_model,
            groq_stt_model=groq_stt_model,
            groq_tts_model=groq_tts_model,
            groq_tts_voice=groq_tts_voice,
            router_max_attempts=router_max_attempts,
            router_retry_delay_seconds=router_retry_delay_seconds,
            groq_api_keys=_read_groq_keys(source),
            groq_reasoning_effort=groq_reasoning_effort,
            groq_timeout_seconds=groq_timeout_seconds,
        )

    @property
    def groq_configured(self) -> bool:
        """Whether at least one live-provider key is configured."""

        return bool(self.groq_api_keys)

    def require_groq_credentials(self) -> tuple[str, ...]:
        """Return keys for live calls or raise without revealing key values."""

        if not self.groq_api_keys:
            raise ConfigurationError(
                "GROQ_API_KEY or GROQ_API_KEYS is required for live provider calls"
            )
        return self.groq_api_keys

    def public_dict(self) -> dict[str, object]:
        """Return safe-to-log configuration metadata without secret values."""

        return {
            "app_name": self.app_name,
            "environment": self.environment,
            "log_level": self.log_level,
            "log_format": self.log_format,
            "groq_router_model": self.groq_router_model,
            "groq_stt_model": self.groq_stt_model,
            "groq_tts_model": self.groq_tts_model,
            "groq_tts_voice": self.groq_tts_voice,
            "router_max_attempts": self.router_max_attempts,
            "router_retry_delay_seconds": self.router_retry_delay_seconds,
            "groq_reasoning_effort": self.groq_reasoning_effort or "provider_default",
            "groq_timeout_seconds": self.groq_timeout_seconds,
            "groq_configured": self.groq_configured,
            "groq_key_count": len(self.groq_api_keys),
        }

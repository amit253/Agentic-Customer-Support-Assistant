"""Safe application configuration.

This module reads configuration from the process environment. It deliberately
does not print or log provider-key values. Live-provider code can call
``require_groq_credentials`` when it is actually ready to make a request;
keyless tests can load the same settings without a key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping


class ConfigurationError(ValueError):
    """Raised when a configuration value is invalid or missing."""


_ALLOWED_LOG_FORMATS = frozenset({"json", "text"})
_ALLOWED_LOG_LEVELS = frozenset(
    {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
)


def _read_groq_keys(environment: Mapping[str, str]) -> tuple[str, ...]:
    """Return configured Groq keys without exposing their values to callers."""

    candidates: list[str] = []
    for variable_name in ("GROQ_API_KEY", "GROQ_API_KEYS"):
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
    groq_api_keys: tuple[str, ...]

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> "Settings":
        """Load settings without requiring a live-provider key."""

        source = os.environ if environment is None else environment
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
            "GROQ_ROUTER_MODEL", "llama-3.3-70b-versatile"
        ).strip()
        if not groq_router_model:
            raise ConfigurationError("GROQ_ROUTER_MODEL must not be empty")

        return cls(
            app_name=app_name,
            environment=environment_name,
            log_level=log_level,
            log_format=log_format,
            groq_router_model=groq_router_model,
            groq_api_keys=_read_groq_keys(source),
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
            "groq_configured": self.groq_configured,
            "groq_key_count": len(self.groq_api_keys),
        }

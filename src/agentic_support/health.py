"""Minimal health payload for local smoke checks."""

from __future__ import annotations

from .config import Settings


def health_payload(settings: Settings | None = None) -> dict[str, object]:
    """Return health metadata without exposing provider credentials."""

    active_settings = settings or Settings.from_environment()
    return {
        "status": "ok",
        "service": active_settings.app_name,
        "environment": active_settings.environment,
        "groq_configured": active_settings.groq_configured,
    }

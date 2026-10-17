"""Command-line smoke check for the project foundation."""

from __future__ import annotations

import json

from .config import Settings
from .health import health_payload
from .logging_config import configure_logging, log_event
from .tracing import trace_context


def main() -> None:
    settings = Settings.from_environment()
    logger = configure_logging(
        level=settings.log_level,
        json_logs=settings.log_format == "json",
    )
    with trace_context() as trace_id:
        log_event(logger, "foundation_health_check", component="foundation")
        response = {"trace_id": trace_id, **health_payload(settings)}
        print(json.dumps(response, sort_keys=True))


if __name__ == "__main__":
    main()

# Agentic Customer Support Assistant

This repository is being built for the accompanying senior AI engineer
assignment. The implementation is developed one reviewed milestone at a time.
The assignment PDF and execution plan are kept under `Problem_Statement/`.

## Current status

Step 3 establishes local embedding retrieval, deterministic chunking, source
provenance, and explicit insufficient-evidence behavior over the Northstar
Gear knowledge base. Tool execution, answer agents, and voice are intentionally
not implemented yet.

## Local setup

Use Python 3.11 or newer. In PowerShell:

```powershell
py -m venv .venv
\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The project tests are deliberately keyless:

```powershell
python -m pytest
python -m agentic_support
```

The first retrieval run may download the configured local embedding model into
the local Hugging Face cache. It does not use a Groq key. Retrieval-specific
tests can be run with:

```powershell
python -m pytest -q tests/test_retrieval.py
```

The health command prints a JSON response and one structured log event. A
configured provider is reported only as `groq_configured: true`; key values are
never printed.

## Local provider configuration

Copy `.env.example` to `.env` for reference, or set environment variables in
the current shell. Do not paste a real key into chat, source code, logs, or
recordings.

```powershell
$env:GROQ_API_KEY = "<your-local-key>"
```

The foundation can run without a key. Code that needs a live provider must
call `Settings.require_groq_credentials()` explicitly and handle its safe
configuration error.

## Logging and traceability

The foundation logger writes one event per line as JSON by default. Every
event contains:

- UTC timestamp;
- level and logger name;
- `trace_id` for following one request/turn across components;
- event name and structured fields;
- redacted exception details when applicable.

Use `trace_context()` at the transport boundary. The context uses Python's
`contextvars`, so the ID can be propagated through asynchronous work without
passing it through every function signature:

```python
from agentic_support.logging_config import configure_logging, log_event
from agentic_support.tracing import trace_context

logger = configure_logging(level="DEBUG", json_logs=True)
with trace_context("demo-request-001"):
    log_event(logger, "support_request_started", channel="text")
```

Trace IDs are restricted to safe characters. Invalid inbound IDs are replaced
with a new ID rather than being written to logs. Common Groq/OpenAI-style token
shapes, bearer tokens, and key assignments are redacted recursively before
formatting.

## Debugging workflow

1. Reproduce the issue with a specific input and capture its `trace_id`.
2. Set `LOG_LEVEL=DEBUG` locally and rerun only the smallest relevant command.
3. Filter the JSON logs by that trace ID.
4. Compare the event sequence and exception fields with the expected call path.
5. Add a focused test that reproduces the behavior before changing the producer.
6. Record the real decision or failed experiment in `docs/decisions-log.md`.

For human-readable local output, set `LOG_FORMAT=text`; JSON remains the
default for machine-readable debugging and later request correlation.

## Docker

Docker is available, but no Dockerfile or Compose service is created in Step 1:
there is not yet an application server to run, and adding one now would be a
placeholder. Containerization will be reconsidered when the API or file-based
evaluation path exists.

## Security baseline

- `.env` and secret-like files are ignored by Git.
- Default tests use no Groq key.
- Configuration metadata exposes only whether a key is configured and how many
  keys are available, never their values.
- Real customer data is not permitted; later order data will be fictional.

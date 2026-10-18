# Agentic Customer Support Assistant

This repository is being built for the accompanying senior AI engineer
assignment. The implementation is developed one reviewed milestone at a time.
The assignment PDF and execution plan are kept locally under
`Problem_Statement/`; those source files are intentionally outside the
submission commit.

## Current status

An improvement programme (2026-10-18, five measured phases) replaced the
LLM-only router with a hybrid router (rules, labeled examples, then Groq),
added a template-only conversation agent for greetings, off-topic, and
unclear messages, replaced retrieval with multilingual-e5-small + BM25 fusion,
added verified session memory with deterministic follow-ups and a handoff
summary, and reworked the demo UI. On held-out sets, live routing accuracy
went from 0.509 to 0.955, the dead-end rate from 0.355 to 0.009, false
escalations from 0.117 to 0, routing p95 from 16.4 s to 0.70 s, and evidence
recall from 0.516 to 0.922. Results and limits: [docs/evaluation.md](docs/evaluation.md);
open weaknesses: [docs/red-team-report.md](docs/red-team-report.md).
Voice latency below was measured before these changes and has not been
re-measured.

Step 7 is complete. Step 8 coordination, WebRTC plus local Silero VAD
confirmation, stale-result rejection, and STT retry/safe-handoff code are
implemented. The labeled regression corpus reported zero false interruptions
and zero missed speech. Audible recorded-audio runs completed normal order,
return eligibility, wrong-order, and adversarial follow-ups; silence and noise
completed without interruption. The injected provider-failure run played a
safe handoff. App-level response-start latency was 15.9-20.2 seconds, above
the proposed <3 second target; first-acoustic-sample loopback was unavailable.
Live microphone capture and real provider-outage behavior are not claimed.
See [docs/voice-coordination.md](docs/voice-coordination.md).

## Assignment deliverables

- [Part A/B design notes](docs/design-notes.md) and
  [Part C answers](docs/part-c-answers.md), with implementation gaps labeled.
- [Step 9 test report](docs/step9-test-report.md) and
  [reproduced red-team findings](docs/red-team-report.md).
- [Reproducible demo runbook](docs/demo-runbook.md).
- [Live-defense notes](docs/live-defense-notes.md); no unaided practice is
  claimed.
- Generate the PowerPoint using `python scripts/build_presentation.py`; the
  verified output is `presentation/agentic-customer-support.pptx`.
- Scan tracked, untracked non-ignored, and recording files using
  `python scripts/scan_secrets.py`. The scanner prints paths/counts only, not
  matching secret values.

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

Run the keyless evaluation (routing with the LLM tier unavailable, retrieval,
guardrails, cache) and save `reports/<label>-evaluation.{json,md}` with:

```powershell
python scripts/run_evaluation.py --label latest
```

It uses the real local embedding models and no Groq key. Live variants
(`--routing-mode live`, `--sections rag`), the retriever comparison, the UI
check, and the red-team probes are listed in
[docs/demo-runbook.md](docs/demo-runbook.md) and
[docs/evaluation.md](docs/evaluation.md).

Validate the real-audio manifest with:

```powershell
python scripts/validate_audio_manifest.py
```

After activating the project environment and configuring Groq credentials
locally (do not commit or share them), run a live voice turn with:

```powershell
python scripts/run_voice_baseline.py audio/normal_order_status.wav
```

The live run record and generated response audio are saved under
`recordings/step7-normal-order-run.json` and
`recordings/step7-normal-order-response.wav`.

The pipeline uses Windows' built-in speech synthesizer for TTS, so Groq's
separate TTS model terms do not block local playback. Groq is still required
for STT and the live support service.

Run or repeat the real-time scenarios from the
[Step 8 runbook](docs/voice-coordination.md).
The default runner plays responses through the Windows audio device and writes
scenario reports to `recordings/`. Speech input is replayed from recorded WAV
files as microphone frames; it is not captured from a live microphone.

## Optional local Streamlit demo

The repository also includes a deliberately small local UI for demonstrations.
It reuses the same guarded `SupportService` and recorded-audio `VoicePipeline`;
it does not create a second application path or expose the Groq key.

Install the optional demo dependency and start it from the repository root:

```powershell
python -m pip install -e ".[dev,demo]"
python -m streamlit run scripts/streamlit_app.py --server.address 127.0.0.1 --server.port 8502
```

Streamlit will print a local URL such as `http://127.0.0.1:8502`. The single
conversation view accepts text through the message box and browser-recorded
voice through the microphone control beside it; both use the same guarded
service path. Voice turns show their transcript and playable response audio.
Trace IDs and safe metadata stay in the collapsed sidebar panel.
Follow-up behavior and the bounded memory limits are documented in
[`docs/memory-handling.md`](docs/memory-handling.md).

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

The application loads an ignored local `.env` file when present. Keep
`.env.example` blank and never place a real key there. Router retries are
bounded by `ROUTER_MAX_ATTEMPTS` and `ROUTER_RETRY_DELAY_SECONDS`; the default
is two total attempts with a 0.25-second initial delay.

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

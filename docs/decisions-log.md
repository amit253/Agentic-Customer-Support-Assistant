# Decisions Log

This log contains only decisions, comparisons, and inspection results that
actually occurred. Timestamps use the local system timezone (Asia/Calcutta).
Future entries must be added when the decision or experiment happens; they
must not be backfilled.

## 2026-10-17

### 2026-10-17T00:51:37.8166406+05:30 - [CODEX] Source of truth

The assignment PDF is the authority for mandatory requirements. The execution
plan is treated as a proposed implementation sequence and must not override the
PDF. Step 0 therefore maps PDF requirements to implementation, verification,
and evidence before application code is written.

### 2026-10-17T00:51:37.8166406+05:30 - [CODEX] Step 0 scope

Step 0 will create only requirements, implementation-plan, decisions-log, and
agent-instruction documentation. No application code, dependency manifest,
environment file, or placeholder module will be created in this step.

### 2026-10-17T00:51:37.8166406+05:30 - [CODEX] Initial repository state

The workspace was not a Git repository and contained no application code at
inspection time. Git will be initialized so subsequent milestone commits have
real history. The assignment PDF and execution plan are preserved as source
materials.

### 2026-10-17T00:51:37.8166406+05:30 - [CODEX] Environment baseline

Docker 29.8.2 and Docker Compose v5.6.0 are available, and the Docker daemon
responds. The configured Python environment is Python 3.14.3 but does not yet
contain pytest. A separate shell pytest command is present; Step 1 must make
project dependencies explicit rather than silently relying on that global
installation.

### 2026-10-17T00:51:37.8166406+05:30 - [CODEX] Secret handling

Only the presence of `GROQ_API_KEY` and `GROQ_API_KEYS` was checked; both were
unset. No secret value was read or printed. Live Groq testing is deferred to a
later step and the key must be supplied through a local environment variable
or ignored local file, never pasted into chat or committed.

### 2026-10-17T00:51:37.8166406+05:30 - [CODEX] PDF inspection method

The local PDF was present. Its compressed text streams were inspected locally
because the browser PDF view did not expose usable text to the repository
inspection tools. The extracted requirements were cross-checked against the
execution plan before creating the matrix.

## User-authored notes

No `[USER]` notes have been added yet.

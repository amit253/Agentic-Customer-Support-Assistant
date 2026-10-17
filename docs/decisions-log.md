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

### 2026-10-17T08:56:26.9766790+05:30 - [CODEX] Traceability and logging design

The Step 1 foundation uses a package logger with JSON output by default, a
`contextvars`-based `trace_id`, and recursive redaction of common provider-key
and bearer-token shapes. A text format and `LOG_LEVEL=DEBUG` are available for
human debugging. The trace ID is generated or safely accepted at the transport
boundary so later text and voice components can correlate one turn without
putting secrets into log fields.

### 2026-10-17T08:56:26.9766790+05:30 - [CODEX] Containerization scope

Docker and Docker Compose are available, but no Dockerfile or Compose service
was added in Step 1 because there is not yet an application server or file-based
evaluation process to run. Adding one now would be a placeholder. The decision
will be revisited when the API or evaluation path exists.

### 2026-10-17T08:56:26.9766790+05:30 - [CODEX] Packaging/debugging correction

The first keyless unit run passed, but a direct `python -m agentic_support`
smoke command failed because the `src/` package was not installed for the
interpreter. The project was then installed in editable mode, after which the
same CLI smoke check passed. This is why the README includes editable
installation before running the CLI.

### 2026-10-17T14:11:15.7160051+05:30 - [USER] Domain selection

The user selected the recommended fictional Northstar Gear travel-gear domain
for Step 2. The repository will use fictional backpack products, orders,
customers, and sessions only.

### 2026-10-17T14:11:15.7160051+05:30 - [CODEX] Northstar Gear data quirks

The Step 2 fixtures use a standard 30-day return window, a September 2026
Trail Week extension through November 15, personalized items as final sale,
a separate manufacturing-defect warranty path, and non-refundable
international duties. These choices create domain-specific retrieval,
authorization, and later red-team cases while keeping policy precedence
explicit in the knowledge base.

### 2026-10-17T14:11:15.7160051+05:30 - [CODEX] Contract boundary

The eligibility result intentionally contains policy facts only. Confirmed
refund status and amount are fields of the order-status record, not the
eligibility contract. This prevents a future tool or response generator from
silently treating eligibility as refund approval.

### 2026-10-17T14:21:40.7476531+05:30 - [CODEX] Contract-test correction

An added order-ID validation test initially caused a collection-time
`IndentationError` because a patch duplicated part of the import block. The
test file was corrected, then the full keyless suite and compile check were
rerun successfully. The failure was a local test-edit error, not a domain
contract failure.

## User-authored notes

No `[USER]` notes have been added yet.

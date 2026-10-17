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

### 2026-10-17T14:36:46.5903240+05:30 - [CODEX] Embedding and index choice

The configured Python environment already had NumPy, PyTorch, Transformers,
and SentencePiece. Sentence Transformers was installed and the local
`sentence-transformers/all-MiniLM-L6-v2` model loaded successfully, producing
384-dimensional vectors. The retrieval implementation uses that model and an
exact normalized NumPy matrix index. The corpus is only 12 documents, so an
inspectable exact scan was chosen instead of adding approximate-neighbor
infrastructure.

### 2026-10-17T14:36:46.5903240+05:30 - [CODEX] Similarity threshold correction

The first real-model retrieval test failed because an unanswerable refund query
scored `0.3618` against a related policy chunk with the initial `0.35`
threshold. Measured required-case scores were then collected: paraphrase
`0.5043`, conflicting policy sources `0.6234` and `0.4828`, irrelevant query
`0.1746`, and unanswerable query best candidate `0.4399`. The threshold was
raised to `0.45`, after which all five retrieval tests passed. This is a
retrieval-boundary decision, not a keyword fallback.

### 2026-10-17T14:58:14.5417125+05:30 - [CODEX] Router and pipeline boundary

Step 4 uses one `SupportService.handle` entry point. It normalizes and validates
raw input before invoking the classifier, then dispatches only accepted
decisions through an explicit three-intent handler registry. Rejected input,
invalid/uncertain classifier output, provider failure, missing handler, and
handler exception all return safe responses without reaching an unsafe route.

### 2026-10-17T14:58:14.5417125+05:30 - [CODEX] Structured Groq adapter

The live adapter uses the Groq Python client with strict JSON Schema output and
local validation of `intent` and `confidence`. The model name is configurable
through `GROQ_ROUTER_MODEL`; fake clients cover default tests so no Groq key is
needed for the repository suite.

### 2026-10-17T14:58:14.5417125+05:30 - [CODEX] Fail-closed correction

The first provider-failure tests exposed that a generic exception from an
injected classifier escaped the router. The router was changed to convert all
ordinary provider/runtime exceptions into a rejected route and increment the
classifier-error counter. The focused and full suites then passed.

### 2026-10-17T16:36:26.0789293+05:30 - [CODEX] Bounded router retry

The router now allows two total classifier attempts by default for provider
failure, invalid output, and low-confidence output. Retry delay and attempt
count are configurable through environment settings, and retry/attempt/
exhaustion counters are observable. Exhausted retries return a safe response;
they never dispatch a handler.

### 2026-10-17T16:36:26.0789293+05:30 - [CODEX] Secret-handling correction

A real Groq key was found in the tracked example-file path during the user's
local configuration inspection. Its value was not used for a request or
recorded in repository files, but it must be treated as compromised and
rotated. The example file was replaced with blank placeholders. Future live
testing must use only the ignored `.env` file, and the rotated key must never
be pasted into chat.

### 2026-10-17T17:10:02.7284731+05:30 - [CODEX] Live provider compatibility correction

The first live smoke attempt used the configured `llama-3.3-70b-versatile`
model and received a safe 404 response; the account's model list showed that
model was unavailable. The local `.env` and configurable default were changed
to the available `openai/gpt-oss-20b` model. JSON object mode then returned a
safe 400 `json_validate_failed` response, so the adapter was changed to strict
JSON Schema output with required `intent` and `confidence` fields.

### 2026-10-17T17:10:02.7284731+05:30 - [CODEX] Live router smoke result

Using the rotated local `.env` key without printing it, the live smoke request
classified an order-status question successfully on the first attempt. The
observed result was `status=ok`, intent `order_status`, handler
`order_status_handler`, one classifier attempt, zero retries, and zero errors.

### 2026-10-17T17:23:07.7429235+05:30 - [CODEX] Step 5 guardrail/tool boundary

The pipeline now performs layered input safety before routing, then invokes
read-only tools only after an accepted route and verified session lookup. Tool
facts are converted into an allowed-facts set, and output claims are checked
before a response is returned. Invalid safety-provider output or exceptions,
ownership failures, unsupported claims, and malformed arguments all use safe
failure paths.

### 2026-10-17T17:24:52.2041908+05:30 - [CODEX] Live Step 5 smoke result

Using the current local `.env` key without printing it, a full live request
passed through the Groq safety classifier, Groq router, order-status handler,
ownership check, and output claim guard. The observed result was `status=ok`,
intent `order_status`, handler `order_status_handler`, one classifier attempt,
zero retries, and zero errors.

### 2026-10-17T17:43:36.6540835+05:30 - [CODEX] Step 6 baseline evaluation

The reproducible evaluation runner was executed with 12 routing cases, 12
retrieval cases, 10 input-guardrail cases, 8 output-guardrail cases, and an
8-request cache workload. The actual report measured routing accuracy `0.8333`,
retrieval recall@5 `0.7273`, retrieval MRR `0.7273`, unanswerable rejection
rate `1.0`, input-guardrail recall `0.6667`, output-guardrail recall `1.0`,
and cache hit rate `0.5`. Routing/input safety were offline baselines; retrieval
used the local embedding model. Reports were saved under `reports/`.

## User-authored notes

No `[USER]` notes have been added yet.

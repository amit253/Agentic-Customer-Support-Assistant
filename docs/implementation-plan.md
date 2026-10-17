# Implementation Plan

This plan turns the verified requirements in `docs/requirements-matrix.md`
into reviewable milestones. The assignment's 72-hour limit is the governing
constraint. The target is approximately 48-55 hours of focused work, leaving
time for recording, debugging, review, and submission checks.

## Step 0 baseline

Inspection completed before implementation:

- Workspace: `C:\Users\ADMIN\Documents\Brainwavescience-Assignment`.
- Existing files: the assignment PDF and the execution-plan text file.
- No application code exists yet.
- The workspace was not a Git repository at the start of Step 0.
- Docker: 29.8.2; Docker Compose: v5.6.0; Docker daemon responds.
- Configured Python environment: 3.14.3.
- The configured Python environment does not currently contain pytest.
- A separate shell `pytest` command is available, but dependency ownership
  will be made explicit in Step 1 rather than assumed.
- `gitleaks` is not installed; Step 1 will use an available secret-check
  approach and document any tool limitation.
- `GROQ_API_KEY` and `GROQ_API_KEYS` were checked only for presence and were
  unset. No secret value was read or printed.

Step 0 creates only planning and agent-instruction files. It does not create
application modules, dependencies, environment files, or placeholder code.

## Milestones

### Step 0 - Requirements and execution baseline

**Dependencies:** assignment PDF and repository access.

**Work:** inspect the PDF, repository, Git state, Python/Docker tools, and
secret-variable presence; create the requirements matrix, this implementation
plan, the decisions log, and `AGENTS.md`; initialize Git so the assignment has
real history.

**Acceptance:** every explicit PDF requirement has an implementation,
verification, and evidence location; requirements are separated from
recommendations; no application code is written; the initial documentation
diff is reviewed.

**Evidence:** requirements matrix, inspection results, Git commit.

### Step 1 - Project foundation and secret handling

**Dependencies:** Step 0; user-selected Python/dependency approach.

**Work:** create the minimal Python project, dependency configuration, test
configuration, `.gitignore`, `.env.example`, safe configuration, README setup,
and a smoke test. Docker is added only if it helps reproducibility.

**Acceptance:** tests run without a Groq key; secret values are never printed;
project commands are documented; a secret-check command is available.

**Risk:** the configured Python 3.14 environment currently lacks pytest.
Resolve this through declared project dependencies or a documented project
environment, not by silently relying on a different global interpreter.

### Step 2 - Domain, identity, tools, and initial data

**Dependencies:** Step 1; a meaningful domain choice from the user.

**Work:** define the fictional business, domain-specific policy quirks,
seeded session-to-customer mapping, order schema, and contracts for
`get_order_status` and `check_return_eligibility`; create 10-20 consistent KB
documents and initial labeled examples.

**Acceptance:** policies are internally consistent or intentional conflicts
are documented; eligibility never approves a refund; ownership is represented
by server-side fictional session state; one original adversarial case exists.

### Step 3 - Embedding retrieval and grounded RAG

**Dependencies:** Step 2.

**Work:** choose one local embedding model and one vector index; implement
deterministic ingestion, chunk provenance, similarity retrieval, and
insufficient-evidence behavior.

**Acceptance:** retrieval is not keyword-only; tests cover paraphrase,
irrelevant, ambiguous/conflicting, and unanswerable queries; default tests can
run with a deterministic fake embedding backend or offline fixture if the real
model is unavailable.

### Step 4 - Safe pipeline, router, agents, and cache

**Dependencies:** Steps 1-3.

**Work:** implement one `SupportService` entry point, guarded input/output
structures, a structured Groq-backed classifier interface, three registered
handlers, low-confidence fallback, and a bounded classifier cache.

**Acceptance:** legitimate router tests use the real guarded pipeline; invalid
or uncertain routing fails closed; rejected input cannot invoke RAG/tools;
cache counters produce an honest hit-rate measurement.

### Step 5 - Tools and full guardrails

**Dependencies:** Step 4 and Step 2 contracts.

**Work:** implement deterministic read-only tools, session ownership checks,
input injection defenses, output allowed-facts validation, safe templates, and
provider timeout handling. Explicitly document native function calling versus
ReAct and the eligibility/refund distinction.

**Acceptance:** attack, benign-look-alike, unauthorized-order, malformed-tool,
unsupported-claim, timeout, and no-bypass tests pass or are honestly reported.

### Step 6 - Evaluation and observability baseline

**Dependencies:** Steps 3-5.

**Work:** add evaluation scripts for routing, retrieval, input/output
guardrails, and cache metrics; save actual reports with model/configuration,
sample count, and date.

**Acceptance:** metrics come from labeled data and counters, not estimates;
mock/stub and live-provider runs are clearly separated.

### Step 7 - STT/TTS and recorded-audio baseline

**Dependencies:** Step 5 shared service; record and validate the required user
audio by the end of Day 1 before continuing to the high-risk voice work.

**Work:** integrate Groq-compatible STT, the shared support service, and one
TTS provider; create a manifest for real user-recorded clips; demonstrate a
normal voice turn.

**Acceptance:** actual recorded audio produces a transcript and playable
response, or a precise provider blocker is recorded; no key appears in audio
evidence or logs.

### Step 8 - Turn coordination, barge-in, and provider failure

**Dependencies:** Step 7.

**Status:** Turn ownership, WebRTC candidate detection with independent local
Silero VAD ONNX confirmation, cancellation/stale-result handling, and
two-attempt STT safe handoff are implemented. The regression corpus reports
zero false interruptions and zero missed speech; the latest audible noise
scenario completes playback without interruption. The latest audible
wrong-order path failed closed at input safety, and the adversarial path failed
closed at classification. The provider-failure scenario is injected, not a
real outage. Acceptance remains incomplete; see
[voice-coordination.md](./voice-coordination.md).

**Work:** implement turn IDs, cancellation, stale-result discard, speech/noise
decision logic, required scenarios, one original adversarial scenario, one
provider failure path, and end-of-speech-to-first-audio timing.

**Acceptance:** silence, noise, speech interruption, adversarial interruption,
and provider failure have repeatable evidence; no duplicate or stale response
is accepted as a successful turn.

### Step 9 - Integration and regression testing

**Dependencies:** Steps 5-8.

**Status:** The keyless suite passed 62 tests with two dependency deprecation
warnings. Focused guarded-call-path/router/tool tests passed 26 tests; voice
tests passed 15 with zero false interruptions and zero missed speech in the
current labeled corpus. The audio manifest has zero validation errors.
Exact commands and results are in [step9-test-report.md](./step9-test-report.md).

**Work:** run unit, integration, security, and voice tests; fix critical
issues; keep optional advanced tests explicitly labeled `[REC]`.

**Acceptance:** exact commands and real outcomes are recorded; default tests
remain keyless.

### Step 10 - Design notes and Part C

**Dependencies:** measured behavior from Steps 5-9.

**Status:** Part A/B design notes and Part C answers have been written against
the inspected implementation, measured evaluation report, and actual Step 8
voice logs. A2 grounded answer generation and A4 native Groq function calling
are now implemented with fake-provider regression coverage; live provider
behavior remains untested. Persistent cross-channel state, acoustic-loopback
latency, and other live-provider limitations remain explicit. See
[design-notes.md](./design-notes.md) and
[part-c-answers.md](./part-c-answers.md).

**Work:** write architecture, Part A/B design notes, and Part C answers tied
to the actual implementation. Cover scale, fourth-agent extension, shared
state, evaluation/SLOs, A/B or shadow testing, VAD/ASR trade-offs, and Groq
degradation.

**Acceptance:** every answer addresses the exact PDF question and labels
implemented/tested, implemented/untested, or proposed claims where useful.

### Step 11 - Genuine red-team review

**Dependencies:** a working text and voice path. Begin exploratory attacks
during Steps 5 and 8; formalize them here.

**Status:** Two weaknesses were reproduced before correction: an explicitly
signaled unauthorized-refund input was allowed when the safety provider
returned `safe=true` with confidence 0.0, and an unsupported natural-language
delivery date passed output validation. Both were fixed and covered by
service-boundary regression tests. Pre-fix reproductions, exact input/output,
root causes, fixes, and residual risks are documented in
[red-team-report.md](./red-team-report.md). The findings were fixed because
they crossed the core safety boundary and had narrow, testable corrections;
the semantic-classifier and heuristic-coverage limitations remain.

**Work:** attack injection handling, unsupported claims, order ownership,
router edge cases, and barge-in timing. Reproduce at least two genuine
weaknesses required by the PDF; document evidence, root cause, severity,
fix decision, regression test, and residual risk.

**Acceptance:** findings are reproducible and not invented. If a required
finding cannot be reproduced, report that blocker rather than fabricating it.

### Step 12 - Packaging, demos, and presentation

**Dependencies:** Steps 9-11.

**Status:** README links the design notes, Part C answers, test report, red-team
report, and exact demo commands. A real 11-slide PowerPoint was generated,
reopened with `python-pptx`, and passed ZIP integrity validation. The secret
scanner examined 100 tracked/untracked non-ignored files plus recordings,
found no non-placeholder credential patterns, and allowlisted only two
synthetic credential fixtures in a redaction test. The optional pace/accent
recording remains marked non-required and pending. See
[demo-runbook.md](./demo-runbook.md).

**Work:** finish README, exact runbook, logs/recordings, documentation, and
presentation. Generate a real `.pptx` with `python-pptx`, PowerPoint, or an
available equivalent; parse it afterward to verify slides exist.

**Acceptance:** all required deliverables exist, the runbook is followable,
evidence is scrubbed, and the presentation contains only real measurements
and findings.

### Step 13 - Independent final review

**Dependencies:** Step 12.

**Status (in progress):** The initial audit found the A2 and A4 gaps. Both now
have implementation and focused keyless fake-provider tests. The focused
group passed 28 tests with the two opt-in live cases skipped; the full default
suite passed 81 with two live cases skipped and two third-party deprecation
warnings. The separate live Groq product-answer and native-tool smoke tests
both passed. The final packaging refresh, complete matrix re-audit, secret
scan, and Git review remain pending. Step 8 remains incomplete for the live
speech-interruption and adversarial follow-up outcomes, and acoustic-loopback
latency is not measured. Step 13 is not complete.

**Work:** first audit without editing; compare every matrix row with code,
tests, docs, evidence, Git history, and secret scan. Report blockers, then
make only separately committed real fixes.

**Acceptance:** no mandatory item is marked complete without evidence; Git
status is clean or explicitly explained.

### Step 14 - Live-defense preparation [REC]

Only after mandatory deliverables are complete: prepare concise module notes
and practice one small extension without AI assistance. Do not sacrifice a
required voice scenario, red-team report, evidence artifact, or presentation.

## Cut lines if time is lost

1. UI polish and live microphone mode; preserve file-based real audio.
2. Local `faster-whisper` fallback if a safe failure/handoff path is shown.
3. Extra randomized tests, AST scans, large evaluation sets, and slide polish.
4. Extra prose in Part C while keeping every requested question answered.

Never cut explicit PDF requirements: real audio, measured latency, guardrail
path evidence, two genuine red-team findings, decisions log, real Git history,
and final deliverables.

## Risk register

| Risk | Mitigation |
|---|---|
| Groq rate limits or outage | Keyless fake clients for default tests; bounded retries; safe static response/handoff; live runs clearly labeled. |
| Missing pytest in selected Python | Declare dependencies in Step 1 and run through the selected project environment. |
| Embedding model download/network failure | Deterministic test embedding backend or offline fixture; separate live retrieval evaluation. |
| Voice hardware/container limitations | File-based real recordings as the reproducible baseline; host microphone only if reliable. |
| Too little time for red-team evidence | Begin exploratory attacks during guardrail and voice implementation, then formalize in Step 11. |
| Secret exposure in logs or media | Environment variables only, redaction tests, tracked-file scan, and manual recording/log review. |
| Overclaiming structural security | Describe Python guards as application invariants; support claims with runtime and call-path tests. |

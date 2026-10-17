# Requirements Matrix

The original tables below define the assignment requirements and planned
verification. The current evidence/status snapshot at the end of Step 12 is
appended below and is subject to the independent Step 13 review.

The assignment PDF is the source of truth: [AI_LLM_Assignment_CSA.pdf](../Problem_Statement/AI_LLM_Assignment_CSA.pdf).
The working execution instructions are in [FINAL_CODEX_EXECUTION_PLAN.txt](../Problem_Statement/FINAL_CODEX_EXECUTION_PLAN.txt).

Labels used below:

- **[REQ]** Explicitly required by the assignment PDF.
- **[REC]** Recommended engineering practice or implementation choice; not independently mandatory.
- **[MVP]** Minimum coherent implementation needed to demonstrate the requirement.

## Part A - Agentic Customer Support

| ID | Requirement | Class | Planned implementation | Verification | Evidence |
|---|---|---|---|---|---|
| A1 | Use Groq as the LLM backend and route messages to at least three intents through distinct handlers. | [REQ] | `src/routing/`, `src/agents/`, shared `SupportService`; intents include `product_question`, `order_status`, and `escalate_to_human`. | Unit and integration tests for every route, invalid output, and low-confidence fallback. | Test output, architecture trace, demo logs. |
| A2 | Ground product answers in an embedding-based RAG path over 10-20 original knowledge-base documents; keyword-only search is insufficient. | [REQ] | `knowledge_base/`, `src/retrieval/`, one selected local embedding model and one vector index. | Retrieval tests include paraphrase, irrelevant, ambiguous/conflicting, and unanswerable queries; provenance is asserted. | Knowledge-base files, retrieval report, RAG logs. |
| A3 | Provide `get_order_status(order_id)` and `check_return_eligibility(order_id)` using deterministic fictional data. | [REQ] | `src/tools/`, fictional order records, schemas, and session ownership checks. | Deterministic tool tests cover valid, malformed, unknown, and cross-customer order IDs. | Tool test output and demo transcript. |
| A4 | Choose and justify native function calling or a ReAct-style loop. | [REQ] | Record the actual comparison and decision in `docs/decisions-log.md`; document the final behavior in design notes. | Review the decision against the implemented tool path. | Decision-log entry and design-note section. |
| A5 | Add input-side prompt-injection/abuse protection. | [REQ] | `src/guardrails/` with normalization, validation, and safety checks; the same path handles text and voice transcripts. | Direct, paraphrased, indirect, malformed, oversized, and benign look-alike cases. | Security test output and refusal/handoff logs. |
| A6 | Add output-side validation for a defined forbidden-claim category, such as unconfirmed refund amounts or delivery dates. | [REQ] | Build allowed facts from verified tool results and retrieved passages; block unsupported claims and use a safe response. | Unsupported amount/date/order-ID/promise tests and clean-answer false-positive tests. | Guardrail evaluation report and transcripts. |
| A7 | Enforce safety in application code, not only in prompts. | [REQ] | Protected request/response data structures, runtime checks, tool argument validation, and fail-closed provider handling. | Invalid construction/call-path tests and provider-timeout tests. | Code-level tests and architecture documentation. |
| A8 | Show structurally that unchecked input cannot reach the RAG or tool handler. | [REQ] | One guarded `SupportService` entry point; handlers accept guarded inputs only; no bypassing test fixtures. | Spy tests assert rejected input never invokes RAG/tools; all intents pass through the same path. | Call graph, test output, and demo logs. |
| A9 | Cache repeated classifier calls and report measured hit rate. | [REQ] | Bounded cache with normalized keys and counters in `src/routing/` or `src/observability/`. | Repeated-query workload computes `hits / eligible lookups`, including zero-denominator handling. | Saved metric report and command output. |
| A10 | Reconcile output guardrails with return eligibility; eligibility is not refund approval. | [REQ] | Eligibility returns policy facts only; confirmed refund status/amount belongs to order status or an explicit status record. | Test a tool/draft disagreement and verify the safe response; test eligible != approved. | Design note, response fixtures, and transcript. |
| A11 | Explain scaling to 10,000 concurrent sessions, adding a fourth agent, and routing/guardrail evaluation metrics. | [REQ] | Part A design note covers stateless workers, state storage, rate limits, registration, rollout, and metrics. | Document review against actual architecture and measured metrics. | `docs/design-notes.md`. |

## Part B - Voice Turn-Taking Pipeline

| ID | Requirement | Class | Planned implementation | Verification | Evidence |
|---|---|---|---|---|---|
| B1 | Build real audio input -> Groq Whisper-compatible STT -> the same support service -> TTS output. | [REQ] | `src/voice/` provider interfaces and a file-based recorded-audio baseline; host microphone mode only if reliable. | End-to-end run with a user-recorded clip and playable response. | Audio manifest, logs/transcript, recording or screen capture. |
| B2 | Use real recorded speech, not synthetic-only or mocked input. | [REQ] | User-recorded clips in `audio/` with a manifest; no fabricated recordings. | Manifest and file inspection; run scenarios using the actual clips. | Audio files, manifest, scenario logs. |
| B3 | Demonstrate silence through playback without interruption. | [REQ] | Turn coordinator keeps playback active when no speech is detected. | Required silence scenario. | Scenario log/transcript or recording. |
| B4 | Demonstrate a short noise burst that does not interrupt. | [REQ] | VAD/noise decision rule with documented threshold and duration. | Noise clip scenario and event log. | Scenario log and measured decision. |
| B5 | Demonstrate genuine speech interruption, clean playback cancellation, and exactly-once STT handoff. | [REQ] | Monotonic turn IDs, cancellation, stale-result discard, and duplicate protection. | Interruption scenario asserts one new turn and no stale response. | State-transition log and recording/transcript. |
| B6 | Demonstrate at least one original/adversarial interruption scenario. | [REQ] | User-selected domain-specific or timing-specific adversarial clip. | Reproduce and document coordinator resolution. | Audio/log evidence and red-team entry if it exposes a weakness. |
| B7 | Simulate STT or TTS failure and show retry/fallback behavior without a hung or crashed turn. | [REQ] | Provider interfaces plus deterministic fault injection; safe static message or handoff if no provider fallback is available. | Fault-injection test and one real/provider-like failure demonstration. | Failure log and transcript. |
| B8 | Measure end-of-user-speech to first playable response audio with real timestamps and explain it. | [REQ] | Define `t0`, `t1`, monotonic timing, and stage measurements in `src/observability/`. | Repeatable file-based measurement with actual sample count and settings. | JSON/Markdown report and explanation in voice notes. |
| B9 | Explain end-of-utterance detection across accents/languages, on-device versus server VAD, and streaming versus batch ASR. | [REQ] | Part B design note; separate implemented behavior from proposed production improvements. | Document review against the actual coordinator. | `docs/design-notes.md`. |
| B10 | Provide recordings or clear logs/transcripts for each voice scenario. | [REQ] | `recordings/` with scrubbed artifacts and `docs/demo-runbook.md`. | Checklist verifies all required scenarios and provider failure. | Final evidence package. |

## Part C - Integration and Operations

| ID | Requirement | Class | Planned implementation | Verification | Evidence |
|---|---|---|---|---|---|
| C1 | Explain state sharing when voice transfers to text or human support. | [REQ] | Shared session state, canonical transcript, verified demo identity, turn IDs, and handoff packet. | Demonstrate a transfer or provide a reproducible state-transfer test. | `docs/part-c-answers.md`, transfer log. |
| C2 | Explain production evaluation: safety regression, latency SLOs, and A/B testing of routing changes. | [REQ] | Written answer tied to the measured evaluation scripts and rollout gates. | Document review for metrics, gates, and rollback criteria. | `docs/part-c-answers.md`. |
| C3 | Explain Groq degradation detection, fallback options, and provider consistency/cost trade-offs. | [REQ] | Written operational plan; implementation fails closed to a static response/handoff when safety cannot be verified. | Review against actual timeout/error handling. | `docs/part-c-answers.md` and failure logs. |

## Process, Integrity, and Evidence

| ID | Requirement | Class | Planned implementation | Verification | Evidence |
|---|---|---|---|---|---|
| P1 | Submit genuine incremental Git history. | [REQ] | Initialize Git in Step 0; commit reviewed milestones with real timestamps; never fabricate, squash, or amend history. | `git log`, `git status`, and reviewed diffs. | GitHub repository history. |
| P2 | Maintain a timestamped decisions log including genuine abandoned approaches and why. | [REQ] | `docs/decisions-log.md`; entries only for decisions/comparisons/experiments that actually occurred. | Review entries against command history and changed design. | Decisions log. |
| P3 | Find and document at least two genuine weaknesses in guardrail, router, or barge-in behavior. | [REQ] | Step 11 attacks the implemented system; findings include exact input/audio, evidence, root cause, severity, and residual risk. | Reproduce each finding; add regression tests for fixes. | `docs/red-team-report.md`, failing/passing test logs. |
| P4 | Use a unique domain, knowledge base, and original adversarial test case. | [REQ] | User chooses domain quirks before data creation; policy and adversarial case are specific to that domain. | Review data, tests, and interview explanation. | KB files, decisions log, red-team report. |
| P5 | Keep API keys out of code, documentation, logs, screenshots, recordings, and commits. | [REQ] | Environment variables and ignored local files only; never request a key in chat. | Secret scan and manual artifact review. | Scan output and clean Git diff/status. |
| P6 | Make the submission reproducible and organized. | [REQ] | README, exact commands, code, tests, design notes, Part C, audio evidence, reports, and presentation. | Fresh-environment/runbook check where possible. | Repository and submission package. |
| P7 | Prepare for a live defense and extension constraint. | [REQ] | Notes and one self-practiced extension only if time remains after mandatory deliverables. | User performs at least one practice change without AI assistance if possible. | Defense notes and truthful practice record. |

## Deliverables Checklist

- [x] Local Git repository with genuine incremental history; no GitHub push is
  claimed.
- [x] Real `.pptx` presentation, reopened and checked.
- [x] Part A and Part B design notes; known implementation gaps are labeled.
- [x] Part C written answers, labeled as proposed where not implemented.
- [x] Real voice recordings and per-scenario logs/transcripts.
- [x] Timestamped decisions log.
- [x] Red-team report with two reproduced findings and regression fixes.
- [x] README and exact demo/test commands.
- [x] Requirements matrix with this evidence snapshot.
- [x] Secret scan of tracked/untracked non-ignored files and recordings; the
  scan found no non-placeholder credential patterns.
- [ ] Clean repository status: the user-provided `Problem_Statement/` source
  directory remains untracked and was deliberately not staged.

## Recommendations, not independent assignment requirements

These choices may be adopted if they help the implementation, but they must
not displace the explicit requirements above:

- FastAPI, Docker/Compose, Silero VAD or WebRTC VAD.
- Local `faster-whisper` fallback.
- Circuit breaker and extensive randomized event testing.
- AST/import scans in addition to call-path tests.
- Large numerical evaluation sets beyond what is needed for meaningful evidence.
- Live microphone mode when file-based recorded audio already gives a reliable demonstration.

## Step 13 status update

Status values: **IMPLEMENTED+TESTED** means the implementation has focused
test or runtime evidence; **PARTIAL** means behavior or required quality is
not fully demonstrated; **ANSWERED-PROPOSED** means the written design answer
exists but production behavior is not implemented; **BLOCKED** identifies an
explicit missing requirement. A2 and A4 were implemented after the Step 13
audit, covered by keyless fake-provider tests, and each passed one separate
live Groq smoke case. The live samples do not establish broad answer quality
or tool-selection reliability.

| ID | Status | Evidence or blocker |
|---|---|---|
| A1 | IMPLEMENTED+TESTED | Three intents and distinct handlers: `tests/test_pipeline.py`, `tests/test_routing.py`; live Step 7 evidence in `docs/voice-baseline.md`. |
| A2 | IMPLEMENTED+TESTED (keyless + live smoke) | `ProductQuestionHandler` generates structured answers only from sufficient retrieved hits, validates chunk citations, and scopes allowed facts to cited chunks; `tests/test_native_llm_paths.py`; one live answer passed citation and output-claim checks, without proving semantic entailment. |
| A3 | IMPLEMENTED+TESTED | Fictional read-only tools and ownership tests: `tests/test_tools.py`, `tests/test_step5_call_path.py`. |
| A4 | IMPLEMENTED+TESTED (keyless + live smoke) | Live construction injects strict Groq function calling; the handler validates one exact user order ID and executes only local allow-listed tools with server-side session authorization; `tests/test_native_llm_paths.py`; one live status selection and local execution passed. |
| A5 | PARTIAL | Input checks, low-confidence fail-closed handling, and call-path tests exist; successful live semantic classification remains unverified; `docs/red-team-report.md`. |
| A6 | IMPLEMENTED+TESTED | Allowed-fact checks and date/money/promise regressions: `src/agentic_support/facts.py`, `tests/test_guardrails.py`; heuristic limits documented. |
| A7 | IMPLEMENTED+TESTED | Application-level validation and fail-closed tests: `tests/test_pipeline.py`, `tests/test_step5_call_path.py`. |
| A8 | IMPLEMENTED+TESTED | Rejected input cannot reach classifier/tools; `tests/test_step5_call_path.py`. |
| A9 | IMPLEMENTED+TESTED | Bounded classifier cache and measured hit rate 0.5; `reports/baseline-evaluation.md`. |
| A10 | IMPLEMENTED+TESTED | Eligibility does not approve a refund; tool and claim tests in `tests/test_tools.py` and `tests/test_guardrails.py`. |
| A11 | IMPLEMENTED+TESTED (design) | Scale, fourth-handler rollout, and evaluation plan in `docs/design-notes.md`; no scale test is claimed. |
| B1 | IMPLEMENTED+TESTED | Real Step 7 WAV -> Groq STT -> shared service -> local TTS: `docs/voice-baseline.md`. |
| B2 | IMPLEMENTED+TESTED | User-recorded WAVs and metadata: `audio/manifest.json`; validated with zero errors. |
| B3 | IMPLEMENTED+TESTED | Audible silence playback completed without interruption: `recordings/step8-silence-run.json`. |
| B4 | IMPLEMENTED+TESTED | Audible current noise playback completed without interruption: `recordings/step8-noise-run.json`; detector corpus also reports zero false interruptions. |
| B5 | PARTIAL | Real speech cancels playback, stale result is discarded, and one STT attempt is evidenced; live follow-up failed closed: `recordings/step8-interruption-run.json`. |
| B6 | PARTIAL | Original adversarial clip interrupts and stale output is rejected; live classifier failed closed: `recordings/step8-adversarial-run.json`. |
| B7 | IMPLEMENTED+TESTED (injected) | Two injected STT failures lead to audible safe handoff: `recordings/step8-provider_failure-run.json`; no real provider outage is claimed. |
| B8 | PARTIAL | Real UTC timestamps and app playback-start latency are recorded, but not first acoustic sample/loopback: `docs/voice-coordination.md`. |
| B9 | IMPLEMENTED+TESTED (design) | Accent/language, on-device/server VAD, and streaming/batch trade-offs in `docs/design-notes.md`. |
| B10 | IMPLEMENTED+TESTED | Per-scenario logs and generated WAV evidence in `recordings/`; run commands in `docs/demo-runbook.md`. |
| C1 | ANSWERED-PROPOSED | State-sharing and reauthorization design in `docs/part-c-answers.md`; persistent shared state is not implemented. |
| C2 | ANSWERED-PROPOSED | Regression, SLO, shadow/A-B strategy and measured offline baseline in `docs/part-c-answers.md`. |
| C3 | ANSWERED-PROPOSED | Detection, retry, handoff, and failover trade-offs in `docs/part-c-answers.md`; no alternate-provider failover is implemented. |
| P1 | IMPLEMENTED+TESTED | Local genuine incremental history: `git log`; the user has not authorized a push in this task. |
| P2 | IMPLEMENTED+TESTED | Actual timestamped choices and experiments: `docs/decisions-log.md`. |
| P3 | IMPLEMENTED+TESTED | Two pre-fix behaviors were reproduced, fixed, and regression-tested: `docs/red-team-report.md`. |
| P4 | IMPLEMENTED+TESTED | User-selected fictional Northstar Gear domain and original audio adversarial case: `docs/domain-and-contracts.md`, `audio/manifest.json`. |
| P5 | IMPLEMENTED+TESTED | `scripts/scan_secrets.py` scanned 100 files with no non-placeholder matches; see Step 12 runbook and output. |
| P6 | PARTIAL | Local code/docs/audio/report/PPTX deliverables exist; `Problem_Statement/` remains intentionally untracked and no remote push is claimed. |
| P7 | NOT DONE ([REC]) | No defense notes or unaided practice drill were created or claimed. |

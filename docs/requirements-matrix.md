# Requirements Matrix

Status at the end of Step 0: planning only. No application code has been
implemented yet.

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

- [ ] GitHub repository with genuine incremental history.
- [ ] Real `.pptx` presentation.
- [ ] Part A and Part B design notes.
- [ ] Part C written answers.
- [ ] Real voice recordings or clear logs/transcripts.
- [ ] Timestamped decisions log.
- [ ] Red-team report with at least two reproduced findings.
- [ ] README and exact demo/test commands.
- [ ] Requirements matrix with evidence links.
- [ ] Secret scan/check and clean repository status.

## Recommendations, not independent assignment requirements

These choices may be adopted if they help the implementation, but they must
not displace the explicit requirements above:

- FastAPI, Docker/Compose, Silero VAD or WebRTC VAD.
- Local `faster-whisper` fallback.
- Circuit breaker and extensive randomized event testing.
- AST/import scans in addition to call-path tests.
- Large numerical evaluation sets beyond what is needed for meaningful evidence.
- Live microphone mode when file-based recorded audio already gives a reliable demonstration.

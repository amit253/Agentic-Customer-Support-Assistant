# System Design Notes

This document distinguishes observed implementation from operational
recommendations. **IMPLEMENTED+TESTED** means a local regression or recorded
run exercises the behavior; it does not imply production readiness.

## Part A - Support system

### Request path

**IMPLEMENTED+TESTED.** Text and voice transcripts enter the transport-neutral
`SupportService.handle()` boundary in `src/agentic_support/pipeline.py`.
Normalization and shape checks run first, then `InputGuard`, then the hybrid
router, the registered handler, and `OutputClaimGuard`. The call-path tests
assert that rejected input does not reach the classifier, RAG retriever, or
order tools; every routing tier runs after the guard.

**IMPLEMENTED+TESTED; MEASURED LIVE.** `HybridRouter` tries deterministic rules
first, then nearest labeled examples (MiniLM, leave-one-out-calibrated
margin), then the Groq strict-schema classifier, and finally a clarifying
question. Six intents are registered: `product_question`, `order_status`,
`escalate_to_human`, and the template-only `smalltalk`, `out_of_scope`, and
`unclear`. On the 110-case held-out set the live hybrid router reached strict
accuracy 0.955 (original LLM-only router 0.509), with 0.245 LLM calls per
message and no false escalations. See [router-design.md](./router-design.md)
and [evaluation.md](./evaluation.md).

### Retrieval and answer grounding

**IMPLEMENTED+TESTED; MEASURED LIVE.** `HybridRetriever` fuses local
`intfloat/multilingual-e5-small` embeddings with BM25 by reciprocal rank and
gates on the best candidate. Nine configurations were compared with
thresholds tuned on a dev set and scored on a 45-case held-out set; evidence
reaching the answerer rose from 0.516 (original MiniLM retriever) to 0.922.
Cross-encoder rerankers were tried and dropped. See
[retrieval-design.md](./retrieval-design.md).

`ProductQuestionHandler` sends retrieved hits to the structured Groq answer
adapter, rejects chunk IDs that retrieval did not return, and passes only
cited chunks' extracted facts to `OutputClaimGuard`. If the answerer reports
insufficient evidence or returns no citations, the fixed "not enough verified
information" reply is used and the model text is discarded. The retrieval
gate is tuned for recall and the answerer is the precision gate: live on the
held-out set, 0.938 of answerable questions were answered (0.906 citing an
expected document) and all 13 unanswerable near-misses were declined. This
does not prove that every sentence is entailed by its citations; the output
guard checks only dates, amounts, order IDs, and promise phrases.

### Tool-calling choice and refund reconciliation

**IMPLEMENTED+TESTED; LIVE SMOKE LIMITED TO ONE CASE.** The live order handler
uses Groq native function calling with strict schemas, disables
parallel calls, requires exactly one allow-listed read-only function, and
validates its JSON arguments locally. The user message must contain exactly
one order ID and the model-selected ID must match it exactly. Only then does
the handler execute the local deterministic tool with the verified
server-side demo session. The model cannot provide a session/customer ID.
Malformed, altered, multi-call, unknown-function, or provider-failure results
fail closed without executing a tool. Keyless tests cover parsing, dispatch,
ownership, and no-execution failure behavior. A separate live smoke selected
the requested status function and executed the local ownership-checked tool
for one fictional order; this is not broad model-selection evaluation.

Native function calling was selected over ReAct because the application has
two bounded read-only operations and needs one tool selection, not an
open-ended observe/act loop. This keeps tool execution and authorization in
the application while avoiding extra model turns and loop termination/retry
complexity. The default keyless registry retains deterministic intent-text
selection when no provider adapter is injected; live construction always
injects the native Groq caller.

Return eligibility is policy evidence only. It cannot approve a refund or add
a refund amount to `AllowedFacts`. Output claims are checked against facts
returned by the executed tool.

### Guardrails and cache

**IMPLEMENTED+TESTED:** input rule signals are sent as evidence to a
provider-neutral safety classifier; unsafe decisions and low-confidence
`safe=true` results do not proceed. Provider/shape errors fail closed. A
message made entirely of closed-vocabulary smalltalk is allowed without a
provider call, and definitive provider decisions are cached briefly (failures
never are). Output claims are limited to verified order IDs, dates, and
amounts, and detected delivery or refund promises without verified facts are
rejected. The red-team round 2 run reproduced one false positive: a negated
"does not mean your refund is approved" answer is blocked, because the promise
patterns ignore negation (pinned by a strict xfail test). Strict JSON Schema
remains primary; only HTTP 400 `json_validate_failed` triggers the JSON-object
fallback, and local exact-key, type, and range checks keep malformed output
fail-closed.

**IMPLEMENTED+TESTED:** classifier cache metrics report measured lookups,
hits, misses, retries, errors, and hit rate. The cache is thread-safe, bounded,
and process-local; the memory hint is part of the key only for messages that
refer back to earlier turns. Classifier retries happen only for transient
provider failures. All Groq adapters share a client that rotates to the next
configured key on HTTP 429 and waits a bounded time when every key is limited.

### Session memory and follow-ups

**IMPLEMENTED+TESTED for the local demo.** `SessionMemoryStore` keeps verified
slots (active order, active product, last intent, unresolved streak) that are
the only memory an LLM sees, and a bounded transcript of every turn, including
refused and failed ones, that is never sent to a model. Order and product
follow-ups are resolved deterministically; "my other order" uses an
ownership-checked `list_orders` tool; a second unresolved turn offers a human;
handoffs carry a summary of the recent voice and text turns. See
[memory-handling.md](./memory-handling.md).

This is not durable production memory. A multi-worker deployment still needs
server-verified tenant/session keys and a retained PostgreSQL/Redis-style store
with access control, encryption, retention, and idempotency.

### Scaling to 10,000 concurrent sessions

**PROPOSED, NOT IMPLEMENTED at production scale.** Keep application workers
stateless and store authenticated session identity, conversation state,
handoff data, and idempotency keys in a durable shared store (for example
PostgreSQL plus Redis). Do not infer identity from a model-generated tool
argument. Partition
or index session history by tenant/session, apply retention controls, and
encrypt sensitive state.

Separate request admission from provider work with bounded queues, per-tenant
rate limits, connection pooling, request deadlines, and backpressure. Use a
shared cache only for safe, versioned classifier results; include model,
prompt, policy, and schema versions in cache keys. A distributed vector index
or sharded embedding service can replace the current local exact scan if the
corpus or query volume outgrows a 12-document in-process index. Run VAD on the
voice edge where possible and reserve bounded CPU inference capacity for
Silero; monitor queueing and reject overload safely rather than accumulating
unbounded audio.

Measure p50/p95/p99 end-of-speech-to-first-audio, provider timeout/error
rates, queue depth, per-intent volume, cache hit rate, retrieval sufficiency,
input false-allow/false-block, output-claim false-allow/false-block, tool
ownership denials, and handoff completion. These are proposed production
metrics, not measurements from 10,000 users.

### Adding a fourth agent

**IMPLEMENTED for the conversation agent; procedure below.** Intents are
defined once in `intents.py`; the schema enum and router prompt are generated
from it. Adding `smalltalk`, `out_of_scope`, and `unclear` took one registry
entry per intent, one handler, labeled examples for the semantic tier, and new
held-out evaluation rows; the three original handlers and their tests were
unchanged. For a business agent such as `billing_dispute`, also add handler
tests for valid route, handler error, authorization, and output claims, then
run shadow classification without dispatching, compare the confusion matrix
and false-escalation rate against the current router, and roll out behind a
feature flag with automatic rollback. A missing handler continues to fail
closed.

### Evaluation set and metrics

**IMPLEMENTED; MEASURED.** `evals/routing_eval.jsonl` (110 held-out cases) and
`evals/retrieval_eval.jsonl` (45 held-out cases, 13 unanswerable) were
committed before the hybrid router and retriever were built. Routing metrics:
strict and lenient accuracy, per-intent precision/recall, dead-end rate,
false-escalation rate, LLM calls per message, latency. Retrieval metrics:
ranking before the threshold (hit@1, recall@k, MRR, nDCG), the threshold
decision (acceptance and rejection rates), and evidence recall. Guardrail
recall is measured on the input and output guard sets. All sets are small and
author-written; see [evaluation.md](./evaluation.md).

## Part B - Voice pipeline

**IMPLEMENTED+TESTED:** the pipeline is recorded-WAV input -> Groq-compatible
batch STT -> the same `SupportService` -> local Windows System.Speech TTS.
WebRTC VAD emits candidates after three positive 20 ms frames; local Silero
ONNX independently confirms candidates before interruption. Turn tokens,
cancellation callbacks, stale-result rejection, and bounded STT retry are
tested. The regression corpus reports zero false interruptions and zero
missed speech in its labeled cases; this is not a universal guarantee.

**MEASURED.** Latency is defined from the VAD end-of-speech timestamp to
application playback start after the output WAV exists. It is not hardware
loopback and does not prove time to first acoustic sample. The Step 8 runs
measured 19,293.912-20,168.889 ms for speech follow-ups, but the harness built
the support service (local models and index) after end of speech, so each turn
included a cold start. With the pipeline built at call setup, the final runs
measured 2,118.6-2,947.3 ms for speech follow-ups and 541.5 ms for the
injected failure handoff; confirmed speech to cancellation was 114.3-126.5 ms.
These are single observations per scenario, not SLO percentiles; one earlier
adversarial run measured 3,020.1 ms, so the sub-three-second target is met with
a thin margin. No loopback capture package was installed, so acoustic output
latency could not be instrumented. See `docs/voice-coordination.md`.

For multilingual and varied-pause production audio, calibrate end-of-utterance
against language/accent-specific labeled audio, including short pauses,
disfluencies, quiet speech, overlapping speech, and representative noise.
WebRTC is a fast candidate detector; Silero adds an independent local signal
but is still model- and domain-dependent. On-device VAD reduces network
latency and raw-audio exposure, while server VAD allows centralized updates
but incurs transport delay and requires privacy controls. Streaming ASR is
preferable when partial hypotheses can safely reduce response latency; batch
ASR is simpler and supports these repeatable files but delays all recognition
until utterance completion. Partial transcripts must never trigger tools
without the same final validation and authorization path.

Provider fallback currently retries STT at most twice and then speaks a
static local handoff. The Step 8 failure run injected that STT error. Live
STT uses English for this recording set and retries unreadable primary output
with `whisper-large-v3`; multilingual behavior is unsupported and unverified.
No provider circuit breaker, alternate LLM failover, or real outage recovery
has been validated.

## Evidence

- Keyless tests and counts: [Step 9 test report](./step9-test-report.md).
- Voice implementation limitations and run timestamps:
  [Step 8 voice runbook](./voice-coordination.md).
- Reproduced guardrail failures and regression fixes:
  [red-team report](./red-team-report.md).

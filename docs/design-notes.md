# System Design Notes

This document distinguishes observed implementation from operational
recommendations. **IMPLEMENTED+TESTED** means a local regression or recorded
run exercises the behavior; it does not imply production readiness.

## Part A - Support system

### Request path

**IMPLEMENTED+TESTED.** Text and voice transcripts enter the transport-neutral
`SupportService.handle()` boundary in `src/agentic_support/pipeline.py`.
Normalization and shape checks run first, then `InputGuard`, then the
structured intent router, registered handler, and `OutputClaimGuard`. The
Step 5 call-path tests assert that rejected input does not reach the
classifier, RAG retriever, or order tools.

`StructuredIntentRouter` uses the Groq strict-schema classifier in live
construction and injected fakes in the default suite. It validates the
allow-listed intent and confidence, retries invalid/provider responses a
bounded number of times, and measures its bounded process-local cache.
Handlers currently cover `product_question`, `order_status`, and
`escalate_to_human`.

### Retrieval and answer grounding

**IMPLEMENTED+TESTED:** `GroundedRetriever` embeds the 12-document Northstar
Gear corpus using local `sentence-transformers/all-MiniLM-L6-v2`, uses
normalized NumPy vectors with exact cosine similarity, and returns source
document/chunk provenance. The retrieval tests cover paraphrase, irrelevant,
conflicting, and insufficient-evidence queries. See
[retrieval-design.md](./retrieval-design.md).

**IMPLEMENTED+TESTED; LIVE SMOKE LIMITED TO ONE CASE.**
`ProductQuestionHandler` sends sufficient retrieved hits to the structured
Groq answer adapter, requires nonempty citations, rejects chunk IDs not
returned by that retrieval, and passes only cited chunks' extracted facts to
`OutputClaimGuard`. Insufficient evidence skips generation; provider or
citation errors fail closed. Keyless tests cover the adapter contract,
retrieval boundary, cited-fact scope, and output guard. A separate live smoke
check passed, validating a nonempty answer, retrieved-chunk citations, and
output-claim guard acceptance without recording generated text. It does not
independently prove that every natural-language statement is entailed by the
cited passages or establish answer quality across queries.

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
`safe=true` results do not proceed. Provider/shape errors fail closed. Output
claims are limited to verified order IDs, dates, and amounts, and detected
delivery promises without verified dates are rejected. The rule-based
keyless provider is a deterministic test baseline, not a semantic production
defense. Live speech transcripts have failed closed on safety/classifier
provider results; successful live semantic guardrail behavior is not
demonstrated.

**IMPLEMENTED+TESTED:** classifier cache metrics report measured lookups,
hits, misses, retries, errors, and hit rate. The current cache is bounded but
process-local; it does not share results across workers.

### Scaling to 10,000 concurrent sessions

**PROPOSED, NOT IMPLEMENTED.** Keep application workers stateless and store
authenticated session identity, conversation state, handoff data, and
idempotency keys in a durable shared store (for example PostgreSQL plus
Redis). Do not infer identity from a model-generated tool argument. Partition
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

**PROPOSED.** Add a typed intent and explicit registry entry, handler contract,
schema and prompt version update, and tests for valid route, malformed or
low-confidence route, handler error, authorization, and output claims. Add
the new labeled cases to per-intent evaluation before rollout. Run shadow
classification without dispatching its tool or response, compare confusion
and safety metrics, then use a feature flag/canary with automatic rollback
gates. Existing handlers remain registered and tested; a missing handler
continues to fail closed.

## Part B - Voice pipeline

**IMPLEMENTED+TESTED:** the pipeline is recorded-WAV input -> Groq-compatible
batch STT -> the same `SupportService` -> local Windows System.Speech TTS.
WebRTC VAD emits candidates after three positive 20 ms frames; local Silero
ONNX independently confirms candidates before interruption. Turn tokens,
cancellation callbacks, stale-result rejection, and bounded STT retry are
tested. The regression corpus reports zero false interruptions and zero
missed speech in its labeled cases; this is not a universal guarantee.

The report's current latency definition ends at app playback handoff after
the output WAV exists. It is not hardware loopback and does not prove the
time-to-first-acoustic-sample requirement. Audible run values range from
2585.583 ms (injected failure handoff) to 5672.024 ms (adversarial live
follow-up); the wrong-order run measured 3665.86 ms. Small sample counts and
fail-closed outcomes mean these are observations, not SLO percentiles.

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
static local handoff. The Step 8 failure run injected that STT error. No
provider circuit breaker, alternate LLM failover, or real outage recovery has
been validated.

## Evidence

- Keyless tests and counts: [Step 9 test report](./step9-test-report.md).
- Voice implementation limitations and run timestamps:
  [Step 8 voice runbook](./voice-coordination.md).
- Reproduced guardrail failures and regression fixes:
  [red-team report](./red-team-report.md).

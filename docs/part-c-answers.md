# Part C - Integration and Operations Answers

These are design answers for the assignment, not claims that an integrated
production chat, human handoff, or distributed control plane exists.

## Voice-to-text or human-support transfer

**PARTIALLY IMPLEMENTED for the local demo; durable transfer is proposed.**
The current voice and text transports call the same cached `SupportService` and
share a bounded process-local `SessionMemoryStore`, so a verified order can be
used by a text follow-up after a voice turn. This repository does not implement
a shared persistent conversation/session store or a live voice-to-text
transfer. The demo session-to-customer mapping is fictional fixture data, not
authentication.
The demo session-to-customer mapping is fictional fixture data, not
authentication.

A production handoff should persist one canonical session record containing:

- server-verified customer and tenant identity, channel, consent, and access
  scope;
- ordered user/assistant turns with trace and turn IDs, timestamps, transcript
  confidence, and provenance;
- tool results and allowed facts with source/time, not model-inferred facts;
- pending intent, cancellation/completion state, and idempotency keys;
- transfer reason, human queue status, and a concise handoff summary.

Voice should append its final transcript and validated turn events to the
same session before handing a session reference to text or a human agent.
Audio blobs should remain in a controlled media store with retention and
access policy; transcripts should be redacted as required. The destination
must reauthorize the user and tool access from trusted server-side identity,
not accept customer/order ownership claims copied from model text. A transfer
should be idempotent so retries do not create duplicate human tickets or
duplicate assistant turns.

The current per-process `VoiceTurnCoordinator` protects a single running
voice interaction only. It is not the shared state layer described above.

## Production evaluation, safety regression, SLOs, and routing A/B tests

**PARTIALLY IMPLEMENTED.** The repository has deterministic tests, held-out
routing (110) and retrieval (45) sets, an evaluation runner with keyless and
explicitly live modes, and committed before/after reports. Live routing
accuracy went from 0.509 to 0.955 and evidence recall from 0.516 to 0.922
between the Phase 0 baseline and the final system; the offline input
guardrail baseline recall is 0.6667 and output guardrail recall 1.0. The sets
are small and author-written and are not production quality estimates. The
same runner is the shape of a routing A/B gate: compare per-intent recall,
dead-end rate, and false-escalation rate for the candidate router against the
current one on the same set before any traffic shift. Speech regression results are likewise limited to the current
recorded/synthetic corpus.

In production, maintain versioned, access-controlled evaluation sets for
intent, ambiguity, benign injection-like language, adversarial instructions,
ownership, unconfirmed refund/delivery claims, retrieval conflicts, accents,
noise, and interruption timing. Run them on every model, prompt, schema, and
policy change. Track false-allow and false-block separately by category;
require zero critical ownership/claim regressions before rollout and review
all dataset disagreements with human annotation.

Proposed SLOs should be derived from a measured production baseline. One
initial target to validate is p95 end-of-speech to first audible sample below
3 seconds, with provider timeout/handoff completion and error-budget targets
defined per channel. On 2026-10-18 the recorded-audio scenarios measured
15,886.752-20,168.889 ms from VAD end-of-speech to application playback
start. The runs had no physical audio loopback, so they do not measure the
first acoustic sample. The observed application latency is already far above
the proposed target; no p95 or production SLO claim is made.

For routing changes, shadow-score a candidate on copied, redacted traffic but
do not dispatch its route or tools. Compare intent confusion, low-confidence
rates, safety decisions, unsupported-claim blocks, per-intent handoffs, cost,
and latency by segment. After offline gates, canary a small percentage of
sessions with stable assignment and immediate rollback on safety or SLO
regression. Never A/B test by disabling authorization or output-claim checks.
Log the model/prompt/policy versions and preserve a deterministic replay
record.

## Groq degradation and provider consistency

**PARTIALLY IMPLEMENTED.** Router calls have bounded retries and safe
fail-closed responses; voice STT retries twice and then uses local Windows
TTS to play a static human-support handoff. Live Step 8 recorded-speech paths
completed safely after adding a primary-STT readability fallback and a
narrowly conditioned structured-output fallback. The provider-failure
recording uses an injected STT failure, not a real outage. There is no
validated real-outage test, circuit breaker, or automatic alternate-provider
failover.

Production monitoring should alert on rolling provider error rate, timeout
rate, p95/p99 latency, rate-limit responses, malformed/partial structured
outputs, and queue depth. Apply bounded retries with jitter and deadlines,
then open a circuit to avoid compounding an outage. Continue only deterministic
read-only operations that remain safe; otherwise speak/display a static
handoff. Any alternate provider must pass the same schema, tool authorization,
input safety, output validation, and regression gates before use.

Failover can reduce outage impact but can change intent boundaries,
calibration, refusal style, latency, cost, and structured-output behavior.
Maintain provider-specific prompts/adapters behind one validated contract,
version them, and run shadow and canary comparisons. Do not silently switch
providers mid-session if that can produce inconsistent policy decisions;
pin the provider/model per turn or transfer explicitly to a safe handoff.

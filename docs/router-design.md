# Router and Safe Pipeline Design

Status: hybrid router implemented (Phase 2). Measured results are in
`docs/evaluation.md` and the `reports/phase*-evaluation.md` files.

## Single entry point

`SupportService.handle()` is the transport-neutral entry point for text and
voice transcripts:

```text
raw message
  -> NFKC / size / control-character validation        (rejects bad input)
  -> input guard: rule signals + Groq safety classifier (fails closed)
  -> hybrid router: tier 0 rules -> tier 1 examples -> tier 2 LLM
  -> registered handler (RAG, order tools, handoff, or conversation)
  -> output claim guard                                  (fails closed)
  -> SupportResponse + session memory
```

The router runs only after the input guard has allowed the message, so no
routing tier, and no handler behind it, ever sees a message that failed the
safety check. Running the guard and the LLM tier in parallel was considered
and rejected: it would save about one provider round trip on the minority of
turns that reach the LLM, but it would let unchecked text reach the router
LLM and would break the existing "classifier is never called for a blocked
message" tests.

## Intents and handlers

Intents are defined once in `intents.py` (`INTENT_SPECS`). The JSON-schema
enum, the router prompt's intent list, and validation are generated from it.

| Intent | Handler | Uses retrieval or tools |
|---|---|---|
| `product_question` | `ProductQuestionHandler` (hybrid RAG) | yes |
| `order_status` | `OrderStatusHandler` (read-only order tools) | yes |
| `escalate_to_human` | `EscalateToHumanHandler` (handoff + summary) | no |
| `smalltalk`, `out_of_scope`, `unclear` | `ConversationHandler` (fixed templates) | no |

Adding a fourth business agent (for example `billing_dispute`) means: one
`IntentSpec`, one handler registered in `build_default_registry`, a few
labeled examples in `route_exemplars.py`, and new rows in
`evals/routing_eval.jsonl`. An intent the LLM may return but that has no
registered handler fails closed in the pipeline.

## Why a hybrid router

The pure-LLM router was measured before this change (`reports/phase0-baseline-live-evaluation.md`):
one Groq call per message, 16.4 s p95 routing latency when calls failed and
were retried, and two live misroutes of return requests to product search
that had already been patched with regexes. Pure rules cannot cover
paraphrases or Hinglish. The hybrid keeps each tool for what it does best:

| Tier | What it decides | Cost | How it fails safe |
|---|---|---|---|
| 0 rules (`route_rules.py`) | one order ID + an order operation; pronoun follow-up on a verified order; closed-vocabulary smalltalk; explicit (non-negated) human request; gibberish | microseconds | answers only on exact patterns; otherwise passes the message on |
| 1 examples (`semantic_routing.py`) | nearest labeled examples, MiniLM embeddings | ~6 ms | answers only when the best intent beats the runner-up by a calibrated margin |
| 2 LLM (`routing.py`) | everything else: paraphrases, Hinglish, mixed requests | ~0.6 s | strict schema with all six intents; local validation; low confidence -> clarification |
| fallback | no confident route | 0 | clarifying question from the conversation handler |

Each response records `routing_source` (`deterministic_order_signal`,
`verified_session_memory`, `rule_smalltalk`, `rule_human_request`,
`rule_gibberish`, `semantic_exemplars`, `classifier`, `router_fallback`) and
the router logs a `route_selected` event, so traffic per tier is observable.

Rule order matters and is deliberate: order operations first (an order ID is
the strongest signal), then the verified-memory follow-up, then pure
smalltalk (a closed vocabulary is more specific than "mentions a person"),
then explicit human requests (negations such as "don't connect me to a human"
are excluded), then gibberish.

## Semantic tier calibration

`scripts/calibrate_semantic_router.py` runs leave-one-out over the 137
training examples and picks the thresholds with the highest coverage at a
0.97 precision target. With `all-MiniLM-L6-v2` the result was min score 0.30,
min margin 0.15: precision 1.00, coverage 0.438. The margin does the work.
`multilingual-e5-small` was also calibrated but answered only 0.329 of
examples at the same precision because its similarity scores are compressed,
so routing keeps MiniLM while retrieval uses e5. A test fails if any training
example appears in the held-out routing set.

## LLM tier

The Groq adapter requests a strict JSON schema with `intent` and `confidence`
and validates the result locally (allow-listed intent, numeric confidence,
minimum 0.65). Prompt version `router-v3` lists every intent with a
definition and states the priority rules, including "a greeting combined with
a real request is classified by the request" and "never escalate off-topic
or gibberish messages".

Retries: at most two attempts, and only for transient failures (timeouts,
connection errors, HTTP 408/409/429, 5xx). Invalid output, 4xx validation
errors, and low confidence are not retried because they repeat at
temperature 0. All adapters share `RotatingChatClient`, which moves to the
next configured key on HTTP 429 and logs only the key index.

## Cache and metrics

Classifier results are cached in a thread-safe TTL/LRU cache keyed by model,
prompt version, and normalized message. The memory hint is part of the key
only when the message refers back to earlier turns ("can I return it?"), so
a self-contained message hits the cache whatever the conversation state.
Failed or low-confidence results are never cached. Counters: lookups, hits,
misses, classifier attempts, errors, retries, exhausted retries, hit rate.

The input guard has its own cache of definitive decisions (provider failures
are never cached) and a fast path that allows closed-vocabulary smalltalk
without a provider call; every word in such a message comes from a fixed
list, so it cannot carry an instruction.

## Failure behavior

| Failure | Result |
|---|---|
| invalid input | `rejected`, "I couldn't read that message" |
| guard says unsafe | `failed_closed`, refusal that lists what support can do |
| guard provider down or uncertain | `failed_closed`, "can't check that request safely right now" |
| router provider down | conversation handler, "having trouble understanding requests right now" |
| no confident route | conversation handler, clarifying question with suggestions |
| handler error | `failed_closed`, "stopped rather than guess" |
| unverified claim in output | `failed_closed`, "couldn't verify every detail" |

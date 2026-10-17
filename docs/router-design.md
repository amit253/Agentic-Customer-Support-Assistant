# Router and Safe Pipeline Design

Status: Step 4 implemented and tested. This is the routing skeleton; full
prompt-injection defenses, output claim validation, and order tools are Step 5.

## Single entry point

`SupportService.handle()` is the transport-neutral entry point for text and
future voice transcripts:

```text
raw message
  -> NFKC/size/control-character validation
  -> CheckedInput
  -> cached structured classifier
  -> registered handler
  -> SupportResponse
```

Rejected input never reaches the classifier or a handler. An invalid,
low-confidence, missing, or provider-failed route returns a safe
`failed_closed` response and does not dispatch a handler.

## Intent and handler registry

The current registered intents are:

- `product_question` -> `ProductQuestionHandler`;
- `order_status` -> `OrderStatusHandler`;
- `escalate_to_human` -> `EscalateToHumanHandler`.

The registry is explicit and replaceable. Step 5 will wire read-only order
tools into the order handler, while the product handler can already expose
Step 3 retrieval provenance when a retriever is injected.

## Structured classifier

The live adapter uses the Groq Python client and requests strict JSON Schema
output with required `intent` and `confidence` fields. Application validation
still checks the intent allow-list, numeric confidence range, and minimum
confidence threshold.
The adapter is not constructed in the default keyless tests; a fake client is
injected instead.

The provider model is configured with `GROQ_ROUTER_MODEL`, and the live service
requires `GROQ_API_KEY` or `GROQ_API_KEYS` only when the live adapter is built.

## Retry policy

The router makes at most two total classifier attempts by default. It retries
provider errors, malformed/unknown output, and low-confidence decisions. The
retry delay is configurable through `ROUTER_RETRY_DELAY_SECONDS` and grows
exponentially by attempt. `ROUTER_MAX_ATTEMPTS` and the delay are passed into
the live service from configuration.

Retry metrics are included with the cache counters: classifier attempts,
retries, and exhausted retry sequences. A retry never bypasses input
validation, and an exhausted sequence never reaches a handler.

## Cache and metrics

Classifier results use a normalized message key that includes model name and
prompt version. The cache has a bounded LRU-style entry count and TTL. It
reports:

- lookups;
- hits;
- misses;
- classifier errors;
- current entry count;
- hit rate (`hits / lookups`, or `None` before any lookup).

Invalid or failed classifier results are never cached as successful routes.

## Traceability and failure behavior

The service preserves the transport trace ID in every response. Structured log
events record input rejection, routing failure, missing-handler failure, and
handler failures without logging message contents or provider secrets.

The Step 4 safety check is intentionally minimal: normalization, size, channel,
empty-input, and control-character validation. Full injection defense and
output claim validation are deliberately deferred to Step 5 rather than being
claimed prematurely.

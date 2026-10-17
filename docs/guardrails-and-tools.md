# Guardrails and Read-Only Tools

Status: Step 5 implemented and tested. Voice coordination and production-scale
resilience remain future steps.

## Input safety path

The pipeline now executes these layers before routing:

1. Step 4 normalization, channel, size, empty-input, and control-character checks.
2. Deterministic high-signal injection patterns for instruction overrides,
   prompt disclosure, guardrail bypass, system-role claims, and unauthorized
   refund instructions.
3. A provider-neutral safety classifier interface. The live service uses the
   Groq strict JSON Schema adapter; keyless tests use a deterministic provider.
4. Fail-closed handling for provider exceptions, invalid fields, invalid
   confidence, and unsafe decisions.

Deterministic signals are passed to the classifier as evidence, not treated as
the complete semantic defense. This lets a provider classify a benign question
that quotes an injection phrase while still rejecting a real attack.

## Tool authorization

`DeterministicOrderTools` is read-only and uses the fictional Step 2 records.
Every call validates:

- order ID type and checksum format;
- verified session state;
- order existence;
- session customer ownership.

`get_order_status` returns only confirmed status, dates, and already-confirmed
refund fields. `check_return_eligibility` returns policy facts only; it never
returns a refund amount, approves a refund, or claims that a refund was issued.

## Allowed facts and output claims

The order handler builds an `AllowedFacts` set from the tool result. Before a
response leaves `SupportService`, `OutputClaimGuard` checks:

- order IDs against verified tool facts;
- ISO dates against verified tool facts;
- currency amounts against confirmed refund facts;
- promise language such as guaranteed delivery or an approved refund.

Unsupported claims return a safe static response and never reach transport.
The internal allowed-facts object is removed from public response metadata.

## Evidence

Tests prove that injection and guardrail-provider failures stop before the
classifier or tools, unauthorized order IDs do not expose order facts, valid
owned orders use the read-only tool, and unsupported output claims are blocked.

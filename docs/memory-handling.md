# Session memory handling

The local demo now supports bounded follow-up context across text and voice
turns. Both transports share the same cached `SupportService`, which owns one
`SessionMemoryStore` keyed by the server-selected demo session ID.

## Current flow

1. Validate and safety-check the current user message first.
2. Load the session snapshot: at most 12 text-only turns and a small verified
   routing hint.
3. Resolve a clear order operation locally when it contains exactly one
   explicit order ID, or a pronoun and an order action such as “Can I return
   it?”; this avoids an unnecessary LLM classifier call and prevents a live
   classifier from misrouting return requests as product questions. Product
   look-alikes such as “What is the capacity ... in order NS-...” still go to
   the product route. Other messages go to the router with only
   `active_verified_order_id` and `last_intent` as memory context. The context
   is data, never an instruction.
4. Reuse a follow-up order reference only when a previous order tool result
   established the active order ID.
5. Execute the normal guarded handler and output-claim validation.
6. Append the validated turn without storing audio bytes. A successful order
   tool result may update the active verified order ID.

The memory layer deliberately rejects ambiguous references such as “another
order” unless the customer supplies a new order ID. Ownership is still checked
by the deterministic order tool, so memory cannot authorize a different
customer's order.

## Scope and limits

`SessionMemoryStore` is thread-safe and bounded to 128 sessions and 12 turns
per session by default. It is process-local: restarting the app or routing a
request to another worker loses this demo state. The production replacement
would use an authenticated tenant/session key in PostgreSQL plus Redis (or an
equivalent durable store), with retention, encryption, access control, and
idempotency. The implementation does not claim general long-term semantic
memory.

## Manual check

With the same selected demo session, first ask:

```text
Where is order NS-26-2044-8?
```

Then ask:

```text
Can I return it?
```

The second request should reuse `NS-26-2044-8`, call return-eligibility, and
never approve a refund. The sidebar trace panel shows the separate trace IDs.

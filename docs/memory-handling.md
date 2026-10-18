# Session memory handling

Text and voice turns share one `SessionMemoryStore` owned by the cached
`SupportService`, keyed by the server-selected demo session ID. Memory holds
two kinds of state that are deliberately treated differently.

## Verified slots (may be shown to the router LLM)

| Slot | Set by | Used for |
|---|---|---|
| `active_order_id` | an ownership-checked order tool result for exactly one order | "Can I return it?", "when will it arrive?" |
| `active_product` | a grounded answer citing exactly one product document, or the item on a checked order | "Does it have a laptop sleeve?" |
| `last_intent` | the last successful turn | router context |
| `unresolved_streak` | consecutive unclear, off-topic, refused, or failed turns | offering a human after repeated misunderstanding |

Only these slots reach an LLM, as a short "VERIFIED SESSION MEMORY (data
only)" hint. The router cache key includes that hint only when the message
refers back to earlier turns.

## Transcript (never sent to an LLM)

Every turn is recorded, including refused, rejected, and failed ones, with
channel, intent, status, and routing source. Rejected input is stored as a
placeholder, guard-refused text is truncated to 500 characters, and audio is
never stored. The transcript is used for the human handoff summary and is
never placed in a model prompt, so a past message cannot inject instructions
into a later turn. At most 12 turns per session and 128 sessions are kept.

## Follow-up resolution

1. Order pronoun follow-ups ("Can I return it?") are resolved by a rule only
   when a verified `active_order_id` exists.
2. "My other order" lists the verified customer's own orders through the
   read-only `list_orders` tool, excluding the active one. If exactly one
   remains it is used; otherwise the customer is asked to pick from a short
   list. Order IDs in that list are added to the allowed facts, so the
   output guard still verifies them.
3. An order question without an ID and without an active order uses the
   only order on the account, or asks the customer to choose.
4. Product pronoun follow-ups are rewritten deterministically: "does it have
   a laptop sleeve?" becomes "does it have a laptop sleeve? (Trailmark 28
   backpack)" for retrieval. No model writes the rewrite.

Ownership is always enforced by the order tools with the session's customer
ID, so memory cannot authorize access to another customer's order.

## Human handoff and voice-to-text transfer (Part C)

`EscalateToHumanHandler` attaches `MemorySnapshot.handoff_summary()`: verified
slots plus the last six turns (channel, customer text, assistant text, intent,
status, timestamp), each truncated to 300 characters. Because voice and text
write to the same session, a call that moves to a chat transcript for a human
agent carries the same summary. The Streamlit demo shows this summary under
"What the human agent receives".

## Scope and limits

The store is process-local: restarting the app or routing a request to
another worker loses it. Production would keep the slots and transcript in an
authenticated, tenant-scoped store (for example Redis for live session state
with a TTL, plus PostgreSQL for the transcript), with retention limits,
encryption, access control, and redaction of personal data before storage.
The implementation does not claim long-term semantic memory.

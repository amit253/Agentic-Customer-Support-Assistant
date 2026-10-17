# Northstar Gear Domain and Contracts

Status: Step 2 data and contract foundation. Tool execution, authorization
logic, RAG, and agents are not implemented yet.

## Domain choice

Northstar Gear is a fictional travel-gear company selling backpacks. The
domain was selected by the user for this assignment. All customer IDs, session
IDs, orders, dates, prices, and policies in this repository are synthetic.

The domain-specific details are intentionally useful for later testing:

- Standard items have a 30-day return window from delivery.
- Orders placed from September 1 through September 30, 2026 during the
  fictional Trail Week campaign have an extended deadline of November 15,
  2026. This exception applies only to eligible standard items.
- Personalized or embroidered items are final sale, except for a separate
  manufacturing-defect warranty claim.
- Warranty repair is not the same as a change-of-mind return.
- International duties and outbound shipping charges are non-refundable.
- A refund amount may be stated only when an order record confirms that amount;
  return eligibility alone never approves or issues a refund.

## Session-to-customer mapping

The current mapping is a fictional authorization fixture for future tools:

| Session | Customer | Verified | Channel | Purpose |
|---|---|---:|---|---|
| `demo-session-nadia` | `cust_nadia` | yes | text | Standard, personalized, and international-order tests. |
| `demo-session-omar` | `cust_omar` | yes | voice | Voice order status and Trail Week tests. |
| `demo-session-priya` | `cust_priya` | yes | text | Previously issued refund status test. |
| `demo-session-unverified` | `cust_unknown` | no | text | Fail-closed authorization test. |

This is not production authentication. Future tool calls will receive the
verified session object from server-side state; a model-supplied order ID may
select an order, but it cannot select or override the session's customer ID.

## Order ID contract

Order IDs use `NS-YY-NNNN-C`:

- `NS` identifies Northstar Gear.
- `YY` is the two-digit order year.
- `NNNN` is a four-digit sequence.
- `C` is the sum of the six year/sequence digits modulo ten.

Example: `NS-26-1042-5` is valid because `2 + 6 + 1 + 0 + 4 + 2 = 15`, and
`15 mod 10 = 5`. The parser rejects malformed IDs and invalid check digits
before any future lookup.

## Tool contracts

### `get_order_status(order_id)`

The future read-only tool may return only confirmed fields from the matching
fictional order record:

- order ID and item name;
- current order status;
- confirmed delivery date or estimated delivery date;
- confirmed refund status;
- confirmed refund amount/date only when the record contains them.

It must reject malformed IDs, unknown orders, unverified sessions, and orders
belonging to another fictional customer. It must never invent a status, date,
or amount.

### `check_return_eligibility(order_id)`

The future read-only tool returns only:

- `eligible`;
- a reason code;
- the policy basis;
- the applicable deadline, if any;
- the next customer action.

It does not return a refund amount, approve a refund, or claim that a refund was
issued. A later output guardrail will treat its result as policy evidence, not
as payment confirmation.

## Fixture coverage

The deterministic records include:

- a delivered standard domestic order;
- a personalized final-sale order;
- a Trail Week extended-window order;
- a previously returned order with a confirmed refund;
- an in-transit order with a confirmed estimated delivery date;
- an international order with non-refundable duties;
- an international personalized final-sale order.

The deliberately adversarial domain case for later red-team work is a user
claiming that a personalized final-sale bag is defective solely to bypass the
final-sale rule. The system must distinguish a genuine warranty claim from a
change-of-mind return instead of promising a refund.

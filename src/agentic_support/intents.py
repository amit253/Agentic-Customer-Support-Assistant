"""Single source of truth for the intents the router may return.

Adding an agent used to mean editing a ``Literal``, a validation set, the
provider JSON schema enum, and the router prompt separately. Those are now all
derived from ``INTENT_SPECS`` so they cannot drift apart. A new intent still
needs a registered handler; an intent without one fails closed in the
pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, get_args


Intent = Literal[
    "product_question",
    "order_status",
    "escalate_to_human",
    "smalltalk",
    "out_of_scope",
    "unclear",
]


@dataclass(frozen=True, slots=True)
class IntentSpec:
    """Router-facing description of one intent.

    ``uses_retrieval_or_tools`` documents whether the intent's handler may call
    retrieval or order tools. Conversational intents must not: their handler
    answers from fixed templates only.
    """

    name: Intent
    description: str
    uses_retrieval_or_tools: bool


INTENT_SPECS: tuple[IntentSpec, ...] = (
    IntentSpec(
        name="order_status",
        description=(
            "an operation on a specific order: status, tracking, delivery, "
            "arrival, return eligibility, sending it back, refund status, or "
            "cancellation, including follow-ups about the active order"
        ),
        uses_retrieval_or_tools=True,
    ),
    IntentSpec(
        name="product_question",
        description=(
            "Northstar Gear product facts or general policy: capacity, size, "
            "material, features, care, return policy, warranty, shipping, "
            "duties, or delivery estimates, when no specific order operation "
            "is requested"
        ),
        uses_retrieval_or_tools=True,
    ),
    IntentSpec(
        name="escalate_to_human",
        description=(
            "an explicit request for a human, agent, or supervisor; an "
            "unresolved complaint; or a safety, damage, loss, defect review, "
            "or account-ownership problem that needs a person"
        ),
        uses_retrieval_or_tools=False,
    ),
    IntentSpec(
        name="smalltalk",
        description=(
            "a greeting, thanks, goodbye, acknowledgement, or a question about "
            "who the assistant is or what it can do, with no other request"
        ),
        uses_retrieval_or_tools=False,
    ),
    IntentSpec(
        name="out_of_scope",
        description=(
            "a clear request unrelated to Northstar Gear support, such as "
            "weather, jokes, coding, news, sports, maths, or other companies"
        ),
        uses_retrieval_or_tools=False,
    ),
    IntentSpec(
        name="unclear",
        description=(
            "gibberish, a fragment, or a message too vague to act on"
        ),
        uses_retrieval_or_tools=False,
    ),
)

VALID_INTENTS: frozenset[str] = frozenset(spec.name for spec in INTENT_SPECS)
CONVERSATIONAL_INTENTS: frozenset[str] = frozenset(
    {"smalltalk", "out_of_scope", "unclear"}
)
INTENT_NAMES: tuple[str, ...] = tuple(spec.name for spec in INTENT_SPECS)

if set(get_args(Intent)) != VALID_INTENTS:  # pragma: no cover - import-time guard
    raise RuntimeError("Intent literal and INTENT_SPECS are out of sync")


def router_intent_definitions() -> str:
    """Render the intent list for the router system prompt."""

    return "\n".join(f"- {spec.name}: {spec.description}." for spec in INTENT_SPECS)

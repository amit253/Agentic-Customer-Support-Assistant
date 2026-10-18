"""Template-only conversational agent for smalltalk, off-topic, and unclear turns.

This handler deliberately has no retriever, order tools, or LLM. It can only
return the fixed sentences below, so it cannot invent an order fact, a policy
term, or a promise, and it adds no provider latency. The sentences are written
to be read aloud by the voice pipeline as well as shown in text chat.
"""

from __future__ import annotations

import re
from typing import Protocol

from .handler_result import HandlerResult
from .routing import RouteDecision


SUGGESTIONS: tuple[str, ...] = (
    "Where is my order?",
    "Can I return my order?",
    "What is the return policy?",
    "Talk to a human",
)

CAPABILITIES = (
    "I can check where an order is, check whether an order can be returned, "
    "explain our return, warranty, and shipping policies, and answer "
    "questions about our backpacks."
)

SMALLTALK_REPLIES: dict[str, str] = {
    "greeting": (
        "Hi! I'm the Northstar Gear support assistant. "
        f"{CAPABILITIES} How can I help?"
    ),
    "thanks": "You're welcome! Is there anything else I can help you with?",
    "goodbye": "Thanks for contacting Northstar Gear. Have a great day!",
    "identity": (
        "I'm Northstar Gear's virtual support assistant, not a person. "
        f"{CAPABILITIES} I can also hand you to a human agent at any time."
    ),
    "capabilities": (
        f"{CAPABILITIES} Tell me what you need, or ask for a human agent."
    ),
    "wellbeing": (
        "I'm doing well, thanks for asking! How can I help with your "
        "Northstar Gear order or products today?"
    ),
    "acknowledgement": "Got it. Let me know if there's anything else you need.",
}

OUT_OF_SCOPE_REPLY = (
    "Sorry, I can only help with Northstar Gear support: orders, returns, "
    "shipping, warranty, and our backpacks. Is there something like that I "
    "can help with?"
)
UNCLEAR_REPLY = (
    "Sorry, I didn't quite catch that. Could you rephrase? For example, you "
    "can ask \"Where is my order?\" or \"What is the return policy?\""
)
DEGRADED_REPLY = (
    "Sorry, I'm having trouble understanding requests right now. Please try "
    "again in a moment, or ask for a human agent."
)
HUMAN_OFFER = (
    " If it's easier, I can connect you with a human agent: just say "
    "\"talk to a human\"."
)

# Reasons that mean the router could not run, rather than that the customer
# was unclear. The customer gets an honest "having trouble" message instead.
PROVIDER_FAILURE_REASONS = frozenset({"classifier_failure_or_invalid_output"})

_SMALLTALK_KIND_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "goodbye",
        re.compile(
            r"\b(?:bye|goodbye|good\s+night|see\s+(?:you|ya)|take\s+care|"
            r"that'?s\s+all|that\s+is\s+all)\b",
            re.I,
        ),
    ),
    (
        "thanks",
        re.compile(
            r"\b(?:thanks|thank\s+you|thx|ty|cheers|appreciate(?:d)?|"
            r"shukriya|dhanyavaad)\b",
            re.I,
        ),
    ),
    (
        "identity",
        re.compile(
            r"\b(?:who\s+are\s+you|what\s+are\s+you|your\s+name|"
            r"are\s+you\s+(?:a\s+)?(?:bot|robot|human|real|person|ai|machine))\b",
            re.I,
        ),
    ),
    (
        "capabilities",
        re.compile(
            r"\b(?:help|what\s+can\s+you|how\s+can\s+you|what\s+do\s+you\s+do|"
            r"options|menu)\b",
            re.I,
        ),
    ),
    (
        "wellbeing",
        re.compile(
            r"\b(?:how\s+are\s+you|how'?s\s+it\s+going|how\s+are\s+things|"
            r"how\s+do\s+you\s+do)\b",
            re.I,
        ),
    ),
    (
        "greeting",
        re.compile(
            r"\b(?:hi|hii+|hello|hey|hiya|good\s+(?:morning|afternoon|evening)|"
            r"namaste|namaskar|hola|greetings|yo)\b",
            re.I,
        ),
    ),
)


class ConversationalRequest(Protocol):
    text: str


def smalltalk_kind(text: str) -> str:
    """Pick which smalltalk template answers this message."""

    for kind, pattern in _SMALLTALK_KIND_PATTERNS:
        if pattern.search(text):
            return kind
    return "acknowledgement"


class ConversationHandler:
    """Answer smalltalk, off-topic, and unclear turns from fixed templates."""

    name = "conversation_handler"

    def handle(
        self, request: ConversationalRequest, decision: RouteDecision
    ) -> HandlerResult:
        intent = decision.intent or "unclear"
        if intent == "smalltalk":
            kind = smalltalk_kind(request.text)
            message = SMALLTALK_REPLIES[kind]
        elif intent == "out_of_scope":
            kind = "out_of_scope"
            message = OUT_OF_SCOPE_REPLY
        elif decision.reason in PROVIDER_FAILURE_REASONS:
            kind = "router_unavailable"
            message = DEGRADED_REPLY
        else:
            kind = "unclear"
            message = UNCLEAR_REPLY

        unresolved_turns = getattr(request, "unresolved_turns", 0)
        if kind in {"out_of_scope", "unclear"} and unresolved_turns >= 1:
            message += HUMAN_OFFER
        return HandlerResult(
            message=message,
            handler_name=self.name,
            metadata={
                "conversation_kind": kind,
                "suggestions": SUGGESTIONS,
            },
        )

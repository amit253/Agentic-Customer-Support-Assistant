from __future__ import annotations

import pytest

from agentic_support.conversation import (
    DEGRADED_REPLY,
    OUT_OF_SCOPE_REPLY,
    SMALLTALK_REPLIES,
    UNCLEAR_REPLY,
    ConversationHandler,
    smalltalk_kind,
)
from agentic_support.facts import OutputClaimGuard
from agentic_support.handlers import build_default_registry
from agentic_support.intents import CONVERSATIONAL_INTENTS, INTENT_SPECS
from agentic_support.pipeline import SupportService
from agentic_support.routing import RouteDecision, StructuredIntentRouter


class SpyTools:
    """Fails the test if the conversation path ever touches order tools."""

    def __getattr__(self, name: str) -> object:
        raise AssertionError(f"conversation path must not call order tools: {name}")


class SpyRetriever:
    def retrieve(self, *args: object, **kwargs: object) -> object:
        raise AssertionError("conversation path must not call retrieval")


class FixedClassifier:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.calls = 0

    def classify(self, message: str) -> dict[str, object]:
        self.calls += 1
        return self.payload


class BrokenClassifier:
    def classify(self, message: str) -> dict[str, object]:
        raise ValueError("unparseable provider output")


class Request:
    def __init__(self, text: str, unresolved_turns: int = 0) -> None:
        self.text = text
        self.unresolved_turns = unresolved_turns


def _service(classifier: object) -> SupportService:
    return SupportService(
        router=StructuredIntentRouter(classifier),
        registry=build_default_registry(
            retriever=SpyRetriever(),  # type: ignore[arg-type]
            order_tools=SpyTools(),  # type: ignore[arg-type]
        ),
    )


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("hi", "greeting"),
        ("thanks a lot!", "thanks"),
        ("ok thanks bye", "goodbye"),
        ("who are you?", "identity"),
        ("what can you help me with?", "capabilities"),
        ("how are you doing today?", "wellbeing"),
        ("great, got it", "acknowledgement"),
    ],
)
def test_smalltalk_kind_picks_the_matching_template(text: str, kind: str) -> None:
    assert smalltalk_kind(text) == kind


def test_conversational_intents_never_use_retrieval_or_tools() -> None:
    specs = {spec.name: spec for spec in INTENT_SPECS}
    assert all(not specs[name].uses_retrieval_or_tools for name in CONVERSATIONAL_INTENTS)


@pytest.mark.parametrize(
    ("intent", "expected"),
    [
        ("smalltalk", SMALLTALK_REPLIES["greeting"]),
        ("out_of_scope", OUT_OF_SCOPE_REPLY),
        ("unclear", UNCLEAR_REPLY),
    ],
)
def test_conversational_turns_are_answered_without_retrieval_or_tools(
    intent: str, expected: str
) -> None:
    service = _service(FixedClassifier({"intent": intent, "confidence": 0.9}))

    response = service.handle("hello friend, a message", session_id="demo-session-omar")

    assert response.status == "ok"
    assert response.handler_name == "conversation_handler"
    assert response.message == expected
    assert response.metadata["suggestions"]


def test_unroutable_message_gets_a_clarifying_question_not_a_dead_end() -> None:
    service = _service(FixedClassifier({"intent": "product_question", "confidence": 0.2}))

    response = service.handle("the blue one", session_id="demo-session-omar")

    assert response.status == "ok"
    assert response.intent == "unclear"
    assert response.message == UNCLEAR_REPLY
    assert response.metadata["routing_source"] == "router_fallback"
    assert response.metadata["route_reason"] == "low_confidence"


def test_router_provider_failure_says_so_honestly() -> None:
    service = _service(BrokenClassifier())

    response = service.handle("tell me about returns", session_id="demo-session-omar")

    assert response.status == "ok"
    assert response.message == DEGRADED_REPLY
    assert response.metadata["route_reason"] == "classifier_failure_or_invalid_output"


def test_second_unresolved_turn_offers_a_human() -> None:
    handler = ConversationHandler()
    decision = RouteDecision(intent="unclear", confidence=0.9, accepted=True, reason="gibberish")

    first = handler.handle(Request("asdf", unresolved_turns=0), decision)
    second = handler.handle(Request("asdf", unresolved_turns=1), decision)

    assert "human agent" not in first.message
    assert "talk to a human" in second.message


def test_every_template_passes_the_output_claim_guard() -> None:
    guard = OutputClaimGuard()
    for message in (*SMALLTALK_REPLIES.values(), OUT_OF_SCOPE_REPLY, UNCLEAR_REPLY, DEGRADED_REPLY):
        assert guard.validate(message).allowed, message


def test_human_handoff_gives_a_stable_reference_and_promises_nothing() -> None:
    service = _service(FixedClassifier({"intent": "escalate_to_human", "confidence": 0.95}))

    first = service.handle("my strap broke, I want this reviewed", trace_id="trace-handoff-1")
    again = service.handle("my strap broke, I want this reviewed", trace_id="trace-handoff-1")

    assert first.status == "ok"
    reference = first.metadata["handoff_reference"]
    assert reference.startswith("HO-") and len(reference) == 11
    assert reference in first.message
    assert again.metadata["handoff_reference"] == reference
    assert "can't promise" in first.message

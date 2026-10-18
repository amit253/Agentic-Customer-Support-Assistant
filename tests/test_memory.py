from __future__ import annotations

from agentic_support.handlers import HandlerRegistry, HandlerResult, build_default_registry
from agentic_support.memory import MemoryTurn, SessionMemoryStore
from agentic_support.pipeline import SupportService
from agentic_support.routing import StructuredIntentRouter
from agentic_support.tools import DeterministicOrderTools


class ContextClassifier:
    def __init__(self) -> None:
        self.direct_calls: list[str] = []
        self.context_calls: list[tuple[str, str]] = []

    def classify(self, message: str) -> dict[str, object]:
        self.direct_calls.append(message)
        return {"intent": "order_status", "confidence": 0.99}

    def classify_with_context(
        self, message: str, context: str
    ) -> dict[str, object]:
        self.context_calls.append((message, context))
        return {"intent": "order_status", "confidence": 0.99}


def test_verified_order_memory_resolves_text_follow_up() -> None:
    classifier = ContextClassifier()
    service = SupportService(
        router=StructuredIntentRouter(classifier),
        registry=build_default_registry(order_tools=DeterministicOrderTools()),
    )

    first = service.handle(
        "Where is order NS-26-2044-8?",
        session_id="demo-session-omar",
        channel="voice",
        trace_id="memory-first",
    )
    second = service.handle(
        "Can I return it?",
        session_id="demo-session-omar",
        channel="text",
        trace_id="memory-follow-up",
    )

    assert first.status == "ok"
    assert second.status == "ok"
    assert "NS-26-2044-8" in second.message
    assert "can be returned" in second.message
    assert "not a refund approval" in second.message
    assert second.metadata["memory_resolved"] is True
    assert second.metadata["routing_source"] == "verified_session_memory"
    assert classifier.direct_calls == []
    assert classifier.context_calls == []
    snapshot = service.memory_store.snapshot("demo-session-omar")
    assert snapshot.turns[0].channel == "voice"
    assert snapshot.turns[0].user_text == "Where is order NS-26-2044-8?"
    assert "(order NS-26-2044-8) was delivered on September 25, 2026." in snapshot.turns[0].assistant_text


def test_explicit_order_return_bypasses_misrouting_classifier() -> None:
    class BrokenClassifier:
        def classify(self, message: str) -> dict[str, object]:
            raise AssertionError("explicit order operation should be deterministic")

    service = SupportService(
        router=StructuredIntentRouter(BrokenClassifier()),
        registry=build_default_registry(order_tools=DeterministicOrderTools()),
    )

    response = service.handle(
        "Can I return order NS-26-2044-8?",
        session_id="demo-session-omar",
    )

    assert response.status == "ok"
    assert "(order NS-26-2044-8) can be returned" in response.message
    assert response.metadata["routing_source"] == "deterministic_order_signal"


def test_order_id_in_product_question_does_not_force_order_route() -> None:
    class ProductClassifier:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def classify(self, message: str) -> dict[str, object]:
            self.calls.append(message)
            return {"intent": "product_question", "confidence": 0.99}

    class ProductHandler:
        def handle(self, request: object, decision: object) -> HandlerResult:
            return HandlerResult(
                message="Product answer from the registered product handler.",
                handler_name="product_question_handler",
            )

    classifier = ProductClassifier()
    service = SupportService(
        router=StructuredIntentRouter(classifier),
        registry=HandlerRegistry({"product_question": ProductHandler()}),
    )

    response = service.handle(
        "What is the capacity of the backpack in order NS-26-2044-8?",
        session_id="demo-session-omar",
    )

    assert response.status == "ok"
    assert response.handler_name == "product_question_handler"
    assert classifier.calls


def test_ambiguous_memory_reference_still_requires_an_order_id() -> None:
    classifier = ContextClassifier()
    service = SupportService(
        router=StructuredIntentRouter(classifier),
        registry=build_default_registry(order_tools=DeterministicOrderTools()),
    )

    service.handle(
        "Where is order NS-26-2044-8?",
        session_id="demo-session-omar",
    )
    response = service.handle(
        "What about another order?",
        session_id="demo-session-omar",
    )

    # The active order is never silently reused; the customer chooses from
    # their own other orders instead of being asked for an ID from memory.
    assert response.status == "ok"
    assert response.message.startswith("Which other order should I check?")
    assert "NS-26-4006-8" in response.message
    assert "NS-26-2044-8" not in response.message
    assert response.metadata["tool_error"] == "ambiguous_memory_reference"


def test_session_memory_is_bounded_and_evicts_old_sessions() -> None:
    store = SessionMemoryStore(max_sessions=2, max_turns_per_session=2)

    def turn(number: int) -> MemoryTurn:
        return MemoryTurn(
            trace_id=f"trace-{number}",
            channel="text",
            user_text=f"message-{number}",
            assistant_text=f"answer-{number}",
            status="ok",
            intent="product_question",
            handler_name="product_question_handler",
        )

    store.append("session-a", turn(1))
    store.append("session-a", turn(2))
    store.append("session-a", turn(3))
    assert [item.trace_id for item in store.snapshot("session-a").turns] == [
        "trace-2",
        "trace-3",
    ]

    store.append("session-b", turn(4))
    store.append("session-c", turn(5))
    assert store.session_count == 2
    assert store.snapshot("session-a").turns == ()

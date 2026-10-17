from __future__ import annotations

from dataclasses import dataclass

from agentic_support.handlers import HandlerRegistry, HandlerResult
from agentic_support.pipeline import SupportService
from agentic_support.routing import StructuredIntentRouter


@dataclass
class MappingClassifier:
    responses: dict[str, dict[str, object]]

    def __post_init__(self) -> None:
        self.calls: list[str] = []

    def classify(self, message: str) -> dict[str, object]:
        self.calls.append(message)
        return self.responses[message]


class SpyHandler:
    def __init__(self, name: str) -> None:
        self.name = name
        self.calls = 0

    def handle(self, request: object, decision: object) -> HandlerResult:
        self.calls += 1
        return HandlerResult(
            message=f"handled by {self.name}",
            handler_name=self.name,
        )


def build_service() -> tuple[SupportService, MappingClassifier, dict[str, SpyHandler]]:
    messages = {
        "What is the capacity?": {"intent": "product_question", "confidence": 0.9},
        "Where is my order?": {"intent": "order_status", "confidence": 0.9},
        "I need a human.": {"intent": "escalate_to_human", "confidence": 0.9},
    }
    classifier = MappingClassifier(messages)
    router = StructuredIntentRouter(classifier)
    handlers = {
        "product_question": SpyHandler("product"),
        "order_status": SpyHandler("order"),
        "escalate_to_human": SpyHandler("human"),
    }
    registry = HandlerRegistry(handlers)
    return SupportService(router=router, registry=registry), classifier, handlers


def test_all_registered_intents_use_distinct_handlers() -> None:
    service, _, handlers = build_service()

    responses = [
        service.handle("What is the capacity?", trace_id="trace-product"),
        service.handle("Where is my order?", trace_id="trace-order"),
        service.handle("I need a human.", trace_id="trace-human"),
    ]

    assert [response.status for response in responses] == ["ok", "ok", "ok"]
    assert [response.handler_name for response in responses] == [
        "product",
        "order",
        "human",
    ]
    assert all(handler.calls == 1 for handler in handlers.values())
    assert [response.trace_id for response in responses] == [
        "trace-product",
        "trace-order",
        "trace-human",
    ]


def test_rejected_input_never_reaches_a_handler() -> None:
    service, classifier, handlers = build_service()

    responses = [
        service.handle("", trace_id="trace-empty"),
        service.handle("x" * 2001, trace_id="trace-large"),
        service.handle("bad\u200binput", trace_id="trace-control"),
    ]

    assert all(response.status == "rejected" for response in responses)
    assert classifier.calls == []
    assert all(handler.calls == 0 for handler in handlers.values())


def test_invalid_route_fails_closed_before_handler() -> None:
    service, classifier, handlers = build_service()
    classifier.responses["unsafe route"] = {
        "intent": "not_registered",
        "confidence": 0.99,
    }

    response = service.handle("unsafe route", trace_id="trace-invalid")

    assert response.status == "failed_closed"
    assert response.intent is None
    assert all(handler.calls == 0 for handler in handlers.values())


def test_classifier_failure_fails_closed_before_handler() -> None:
    class BrokenClassifier:
        def classify(self, message: str) -> dict[str, object]:
            raise RuntimeError("provider unavailable")

    handlers = {
        "product_question": SpyHandler("product"),
        "order_status": SpyHandler("order"),
        "escalate_to_human": SpyHandler("human"),
    }
    service = SupportService(
        router=StructuredIntentRouter(BrokenClassifier()),
        registry=HandlerRegistry(handlers),
    )

    response = service.handle("Where is my order?", trace_id="trace-provider")

    assert response.status == "failed_closed"
    assert all(handler.calls == 0 for handler in handlers.values())

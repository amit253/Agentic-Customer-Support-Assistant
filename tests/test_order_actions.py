from __future__ import annotations

from agentic_support.handlers import build_default_registry
from agentic_support.pipeline import SupportService
from agentic_support.routing import StructuredIntentRouter
from agentic_support.tools import DeterministicOrderTools


class OrderClassifier:
    def classify(self, message: str) -> dict[str, object]:
        return {"intent": "order_status", "confidence": 0.95}

    def classify_with_context(self, message: str, context: str) -> dict[str, object]:
        return self.classify(message)


def _service() -> SupportService:
    return SupportService(
        router=StructuredIntentRouter(OrderClassifier()),
        registry=build_default_registry(order_tools=DeterministicOrderTools()),
    )


STATUS_ONLY = (
    "Your CityHaul 20 backpack (order NS-26-4006-8) is on its way. The current "
    "delivery estimate is October 22, 2026; that is an estimate, not a guarantee."
)


def test_user_reported_transcript_no_longer_ignores_refund_and_cancel_requests() -> None:
    # Reported by the user from the live UI: both requests got a plain status reply.
    service = _service()
    session = "demo-session-omar"
    service.handle("Where is order NS-26-4006-8?", session_id=session)
    service.handle("Can I return it?", session_id=session)

    refund = service.handle("refund my amount", session_id=session)
    both = service.handle("i want to cancel it, and i want refund", session_id=session)

    assert refund.status == "ok"
    assert refund.message != STATUS_ONLY
    assert refund.message.startswith("I can't issue refunds in this chat")
    assert "No refund has been issued for this order" in refund.message
    assert "hasn't been delivered yet" in refund.message
    assert 'just say "talk to a human"' in refund.message
    assert refund.metadata["unsupported_action"] == ("refund",)
    assert "Talk to a human" in refund.metadata["suggestions"]

    assert both.status == "ok"
    assert both.message.startswith("I can't cancel orders or issue refunds in this chat")
    assert both.metadata["unsupported_action"] == ("cancel", "refund")


def test_explicit_human_request_with_a_refund_creates_the_handoff() -> None:
    response = _service().handle(
        "I need a human to approve a refund for NS-26-2044-8",
        session_id="demo-session-omar",
        trace_id="trace-refund-human",
    )

    assert response.status == "ok"
    assert response.metadata["handoff_required"] is True
    reference = response.metadata["handoff_reference"]
    assert reference in response.message
    assert "I've passed your request to a human support agent" in response.message
    assert "can be returned" in response.message
    assert "not a refund approval" in response.message


def test_refund_status_questions_still_get_the_status_answer() -> None:
    response = _service().handle(
        "Did you issue the refund for NS-26-3005-6?", session_id="demo-session-priya"
    )

    assert response.status == "ok"
    assert "unsupported_action" not in response.metadata
    assert "A refund of $120.00 was issued on October 12, 2026." in response.message
    assert "I can't" not in response.message


def test_issued_refund_is_reported_not_re_requested() -> None:
    response = _service().handle(
        "I want my money back for NS-26-3005-6", session_id="demo-session-priya"
    )

    assert response.message.startswith("I can't issue refunds in this chat")
    assert "A refund of $120.00 was issued on October 12, 2026." in response.message
    assert "No refund has been issued" not in response.message


def test_past_tense_cancellation_question_is_not_treated_as_a_request() -> None:
    response = _service().handle(
        "Was my order NS-26-4006-8 cancelled?", session_id="demo-session-omar"
    )

    assert "I can't cancel" not in response.message
    assert "is on its way" in response.message


def test_cancel_request_for_another_customers_order_reveals_nothing() -> None:
    response = _service().handle("Cancel NS-26-1042-5", session_id="demo-session-omar")

    assert response.metadata["tool_error"] == "ownership_mismatch"
    assert "NS-26-1042-5" not in response.message

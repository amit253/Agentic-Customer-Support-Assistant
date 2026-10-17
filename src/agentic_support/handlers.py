"""Distinct Step 4 handlers behind the guarded support pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Protocol

from .demo_data import DEMO_SESSIONS
from .facts import AllowedFacts
from .retrieval import GroundedRetriever
from .routing import Intent, RouteDecision
from .tools import DeterministicOrderTools, OrderToolError


class CheckedInputLike(Protocol):
    text: str
    trace_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class HandlerResult:
    """Handler output before the pipeline wraps it in a support response."""

    message: str
    handler_name: str
    metadata: Mapping[str, object] = field(default_factory=dict)


class SupportHandler(Protocol):
    def handle(
        self, request: CheckedInputLike, decision: RouteDecision
    ) -> HandlerResult:
        """Handle only an input that already passed pipeline validation."""


class ProductQuestionHandler:
    """Product handler that can expose Step 3 retrieval provenance."""

    name = "product_question_handler"

    def __init__(self, retriever: GroundedRetriever | None = None) -> None:
        self._retriever = retriever

    def handle(
        self, request: CheckedInputLike, decision: RouteDecision
    ) -> HandlerResult:
        if self._retriever is None:
            return HandlerResult(
                message="Product-question handler selected; retrieval is configured separately.",
                handler_name=self.name,
            )
        retrieval = self._retriever.retrieve(request.text)
        if not retrieval.sufficient_evidence:
            return HandlerResult(
                message="I do not have enough verified information to answer that product question.",
                handler_name=self.name,
                metadata={"retrieval_reason": retrieval.reason},
            )
        return HandlerResult(
            message="Verified product passages were retrieved for the next answer stage.",
            handler_name=self.name,
            metadata={
                "chunk_ids": tuple(hit.chunk.chunk_id for hit in retrieval.hits),
                "source_paths": tuple(hit.chunk.source_path for hit in retrieval.hits),
            },
        )


class OrderStatusHandler:
    """Distinct order-status path; read-only tools arrive in Step 5."""

    name = "order_status_handler"

    def __init__(self, tools: DeterministicOrderTools | None = None) -> None:
        self._tools = tools

    def handle(
        self, request: CheckedInputLike, decision: RouteDecision
    ) -> HandlerResult:
        if self._tools is None:
            return HandlerResult(
                message="Order-status handler selected; read-only tools will be wired in the next milestone.",
                handler_name=self.name,
            )

        order_ids = re.findall(r"\bNS-\d{2}-\d{4}-\d\b", request.text)
        if len(order_ids) != 1:
            return HandlerResult(
                message="Please provide one Northstar order ID so I can check it safely.",
                handler_name=self.name,
                metadata={"tool_error": "missing_or_ambiguous_order_id"},
            )
        session = DEMO_SESSIONS.get(request.session_id)
        if session is None:
            return HandlerResult(
                message="I could not verify the support session for that order.",
                handler_name=self.name,
                metadata={"tool_error": "unknown_session"},
            )
        order_id = order_ids[0]
        try:
            if re.search(r"\b(?:return|eligible|send back)\b", request.text, re.I):
                result = self._tools.check_return_eligibility(
                    order_id=order_id, session=session
                )
                message = (
                    f"Return eligibility for {result.order_id}: "
                    f"{'eligible' if result.eligible else 'not eligible'}. "
                    f"{result.policy_basis} {result.next_action}"
                )
                if result.deadline is not None:
                    message += f" Applicable deadline: {result.deadline.isoformat()}."
                return HandlerResult(
                    message=message,
                    handler_name=self.name,
                    metadata={
                        "allowed_facts": AllowedFacts.from_return_eligibility(result),
                        "tool_name": "check_return_eligibility",
                    },
                )

            result = self._tools.get_order_status(
                order_id=order_id, session=session
            )
        except OrderToolError as exc:
            return HandlerResult(
                message="I could not access that order safely.",
                handler_name=self.name,
                metadata={"tool_error": exc.reason_code},
            )

        message = f"Order {result.order_id} status: {result.status}."
        if result.delivered_date is not None:
            message += f" Delivered: {result.delivered_date.isoformat()}."
        elif result.estimated_delivery_date is not None:
            message += (
                f" Estimated delivery: {result.estimated_delivery_date.isoformat()}."
            )
        if (
            result.refund_status == "issued"
            and result.confirmed_refund_amount is not None
        ):
            message += f" Confirmed refund: ${result.confirmed_refund_amount:.2f}."
        return HandlerResult(
            message=message,
            handler_name=self.name,
            metadata={
                "allowed_facts": AllowedFacts.from_order_status(result),
                "tool_name": "get_order_status",
            },
        )


class EscalateToHumanHandler:
    """Create a safe handoff marker without promising a business outcome."""

    name = "escalate_to_human_handler"

    def handle(
        self, request: CheckedInputLike, decision: RouteDecision
    ) -> HandlerResult:
        return HandlerResult(
            message="Your request has been marked for human support review.",
            handler_name=self.name,
            metadata={
                "handoff_required": True,
                "session_id": request.session_id,
            },
        )


class HandlerRegistry:
    """Explicit intent-to-handler registry used by the pipeline."""

    def __init__(self, handlers: Mapping[Intent, SupportHandler] | None = None) -> None:
        self._handlers: dict[Intent, SupportHandler] = dict(handlers or {})

    def register(self, intent: Intent, handler: SupportHandler) -> None:
        self._handlers[intent] = handler

    def get(self, intent: Intent) -> SupportHandler | None:
        return self._handlers.get(intent)

    @property
    def intents(self) -> frozenset[Intent]:
        return frozenset(self._handlers)


def build_default_registry(
    *,
    retriever: GroundedRetriever | None = None,
    order_tools: DeterministicOrderTools | None = None,
) -> HandlerRegistry:
    return HandlerRegistry(
        {
            "product_question": ProductQuestionHandler(retriever),
            "order_status": OrderStatusHandler(order_tools),
            "escalate_to_human": EscalateToHumanHandler(),
        }
    )

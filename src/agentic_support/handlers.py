"""Distinct Step 4 handlers behind the guarded support pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from .retrieval import GroundedRetriever
from .routing import Intent, RouteDecision


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

    def handle(
        self, request: CheckedInputLike, decision: RouteDecision
    ) -> HandlerResult:
        return HandlerResult(
            message="Order-status handler selected; read-only tools will be wired in the next milestone.",
            handler_name=self.name,
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
    *, retriever: GroundedRetriever | None = None
) -> HandlerRegistry:
    return HandlerRegistry(
        {
            "product_question": ProductQuestionHandler(retriever),
            "order_status": OrderStatusHandler(),
            "escalate_to_human": EscalateToHumanHandler(),
        }
    )

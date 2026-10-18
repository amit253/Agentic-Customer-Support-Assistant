"""Distinct Step 4 handlers behind the guarded support pipeline."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import re
from typing import Protocol

from .conversation import SUGGESTIONS, ConversationHandler
from .demo_data import DEMO_SESSIONS
from .facts import AllowedFacts
from .grounded_answers import GroundedAnswerError, ProductAnswerer
from .handler_result import HandlerResult
from .retrieval import Retriever
from .routing import Intent, RouteDecision
from .tool_calling import OrderToolCaller, ToolCallProviderError
from .tools import DeterministicOrderTools, OrderToolError


INSUFFICIENT_EVIDENCE_REPLY = (
    "I do not have enough verified information to answer that from our help "
    "articles, so I won't guess. I can help with product features, returns, "
    "shipping, and warranty, or connect you with a human agent."
)


class CheckedInputLike(Protocol):
    text: str
    trace_id: str
    session_id: str
    active_order_id: str | None


class SupportHandler(Protocol):
    def handle(
        self, request: CheckedInputLike, decision: RouteDecision
    ) -> HandlerResult:
        """Handle only an input that already passed pipeline validation."""


class ProductQuestionHandler:
    """Answer product questions from retrieved passages and verified citations."""

    name = "product_question_handler"

    def __init__(
        self,
        retriever: Retriever | None = None,
        answerer: ProductAnswerer | None = None,
    ) -> None:
        self._retriever = retriever
        self._answerer = answerer

    def handle(
        self, request: CheckedInputLike, decision: RouteDecision
    ) -> HandlerResult:
        if self._retriever is None:
            raise GroundedAnswerError("product_retriever_unavailable")
        retrieval = self._retriever.retrieve(request.text)
        if not retrieval.sufficient_evidence:
            return self._insufficient(retrieval.reason)
        if self._answerer is None:
            raise GroundedAnswerError("grounded_answerer_unavailable")

        answer = self._answerer.answer(request.text, retrieval.hits)
        if answer.insufficient_evidence:
            return self._insufficient("answerer_reported_insufficient_evidence")
        available_chunks = {
            hit.chunk.chunk_id: hit.chunk for hit in retrieval.hits
        }
        if (
            not answer.text.strip()
            or not answer.cited_chunk_ids
            or len(set(answer.cited_chunk_ids)) != len(answer.cited_chunk_ids)
            or any(
                chunk_id not in available_chunks
                for chunk_id in answer.cited_chunk_ids
            )
        ):
            raise GroundedAnswerError("grounded_answer_citation_validation_failed")
        cited_chunks = [
            available_chunks[chunk_id] for chunk_id in answer.cited_chunk_ids
        ]
        citation_text = ", ".join(
            f"[{chunk_id}]" for chunk_id in answer.cited_chunk_ids
        )
        return HandlerResult(
            message=f"{answer.text}\n\nSources: {citation_text}",
            handler_name=self.name,
            metadata={
                "chunk_ids": tuple(hit.chunk.chunk_id for hit in retrieval.hits),
                "source_paths": tuple(hit.chunk.source_path for hit in retrieval.hits),
                "cited_chunk_ids": answer.cited_chunk_ids,
                "allowed_facts": AllowedFacts.from_retrieval(cited_chunks),
            },
        )


    def _insufficient(self, reason: str) -> HandlerResult:
        return HandlerResult(
            message=INSUFFICIENT_EVIDENCE_REPLY,
            handler_name=self.name,
            metadata={"retrieval_reason": reason, "suggestions": SUGGESTIONS},
        )


class OrderStatusHandler:
    """Resolve order requests through locally authorized read-only tools."""

    name = "order_status_handler"

    def __init__(
        self,
        tools: DeterministicOrderTools | None = None,
        tool_caller: OrderToolCaller | None = None,
    ) -> None:
        self._tools = tools
        self._tool_caller = tool_caller

    def handle(
        self, request: CheckedInputLike, decision: RouteDecision
    ) -> HandlerResult:
        if self._tools is None:
            raise OrderToolError("order_tools_unavailable")

        order_ids = re.findall(r"\bNS-\d{2}-\d{4}-\d\b", request.text)
        active_order_id = getattr(request, "active_order_id", None)
        memory_resolved = False
        if not order_ids and active_order_id:
            if re.search(r"\b(?:other|another|different)\b", request.text, re.I):
                return HandlerResult(
                    message="Please provide one Northstar order ID so I can check it safely.",
                    handler_name=self.name,
                    metadata={"tool_error": "ambiguous_memory_reference"},
                )
            order_ids = [active_order_id]
            memory_resolved = True
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
        if self._tool_caller is None or memory_resolved:
            order_id = order_ids[0]
            tool_name = (
                "check_return_eligibility"
                if re.search(r"\b(?:return|eligible|send back)\b", request.text, re.I)
                else "get_order_status"
            )
        else:
            selection = self._tool_caller.select_tool(request.text)
            if selection.order_id != order_ids[0]:
                raise ToolCallProviderError("selected_order_id_not_in_user_message")
            order_id = selection.order_id
            tool_name = selection.name
        try:
            if tool_name == "check_return_eligibility":
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
                        "memory_resolved": memory_resolved,
                    },
                )
            if tool_name != "get_order_status":
                raise ToolCallProviderError("order_tool_name_not_allowlisted")
            result = self._tools.get_order_status(order_id=order_id, session=session)
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
                "memory_resolved": memory_resolved,
            },
        )


class EscalateToHumanHandler:
    """Create a safe handoff marker without promising a business outcome."""

    name = "escalate_to_human_handler"

    def handle(
        self, request: CheckedInputLike, decision: RouteDecision
    ) -> HandlerResult:
        reference = handoff_reference(request.trace_id)
        return HandlerResult(
            message=(
                "I've passed this conversation to a human support agent. "
                f"Your reference is {reference}. An agent will review the "
                "details; I can't promise a specific outcome before that review."
            ),
            handler_name=self.name,
            metadata={
                "handoff_required": True,
                "handoff_reference": reference,
                "session_id": request.session_id,
            },
        )


def handoff_reference(trace_id: str) -> str:
    """Return a short, stable reference a customer can quote to an agent."""

    digest = hashlib.sha256(trace_id.encode("utf-8")).hexdigest()[:8].upper()
    return f"HO-{digest}"


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
    retriever: Retriever | None = None,
    answerer: ProductAnswerer | None = None,
    order_tools: DeterministicOrderTools | None = None,
    order_tool_caller: OrderToolCaller | None = None,
) -> HandlerRegistry:
    conversation = ConversationHandler()
    return HandlerRegistry(
        {
            "product_question": ProductQuestionHandler(retriever, answerer),
            "order_status": OrderStatusHandler(order_tools, order_tool_caller),
            "escalate_to_human": EscalateToHumanHandler(),
            "smalltalk": conversation,
            "out_of_scope": conversation,
            "unclear": conversation,
        }
    )

"""Distinct Step 4 handlers behind the guarded support pipeline."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import re
from typing import Protocol

from .catalog import (
    product_for_doc,
    product_for_item_name,
    rewrite_product_follow_up,
)
from .contracts import OrderStatusResult, OrderSummary, ReturnEligibilityResult
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


_ORDER_ID = re.compile(r"\bNS-\d{2}-\d{4}-\d\b")
_OTHER_ORDER = re.compile(r"\b(?:other|another|different|second)\b", re.I)
_RETURN_REQUEST = re.compile(r"\b(?:return|returnable|eligible|send\s+back)\b", re.I)
_STATUS_PHRASES = {
    "processing": "is being processed",
    "in_transit": "is on its way",
    "delivered": "was delivered",
    "return_received": "was delivered",
}
ACCESS_ERROR_REPLY = (
    "I could not access that order safely. Please check the order ID, or ask "
    "for a human agent."
)


def friendly_date(value) -> str:
    """Render a date the output guard can verify, e.g. "September 25, 2026"."""

    return f"{value:%B} {value.day}, {value.year}"


def order_status_message(result: OrderStatusResult) -> str:
    message = (
        f"Your {result.item_name} (order {result.order_id}) "
        f"{_STATUS_PHRASES.get(result.status, 'has an unknown status')}"
    )
    if result.delivered_date is not None:
        message += f" on {friendly_date(result.delivered_date)}"
        message += (
            ", and we have received your return."
            if result.status == "return_received"
            else "."
        )
    elif result.estimated_delivery_date is not None:
        message += (
            ". The current delivery estimate is "
            f"{friendly_date(result.estimated_delivery_date)}; that is an "
            "estimate, not a guarantee."
        )
    else:
        message += "."
    if result.refund_status == "issued" and result.confirmed_refund_amount is not None:
        message += f" A refund of ${result.confirmed_refund_amount:.2f} was issued"
        if result.confirmed_refund_date is not None:
            message += f" on {friendly_date(result.confirmed_refund_date)}"
        message += "."
    elif result.refund_status == "pending":
        message += " A refund is pending; I can't confirm an amount or date yet."
    return message


def return_eligibility_message(result: ReturnEligibilityResult) -> str:
    order = f"your {result.item_name} (order {result.order_id})"
    deadline = friendly_date(result.deadline) if result.deadline else None
    if result.reason_code in ("eligible_standard", "eligible_trail_week"):
        window = (
            "the extended Trail Week return window"
            if result.reason_code == "eligible_trail_week"
            else "the standard 30-day return policy"
        )
        message = f"Good news: {order} can be returned under {window}."
        if deadline:
            message += f" The return deadline is {deadline}."
        return (
            message + " The item must be unused with its original tags. "
            "Return eligibility is not a refund approval."
        )
    if result.reason_code == "final_sale":
        return (
            f"{order[0].upper()}{order[1:]} is personalized, so it is final sale "
            "and can't be returned for a change of mind. If it has a "
            "manufacturing defect, I can connect you with a human agent for a "
            "warranty review."
        )
    if result.reason_code == "not_delivered":
        return (
            f"Order {result.order_id} hasn't been delivered yet, so a return "
            "can't be started. Returns are checked after delivery."
        )
    if result.reason_code == "already_returned":
        return (
            f"Order {result.order_id} already has a received return or an issued "
            "refund, so there is nothing more to return."
        )
    if result.reason_code == "window_expired":
        passed = f" passed on {deadline}" if deadline else " has passed"
        return (
            f"The return deadline for {order}{passed}. If you believe an "
            "exception applies, I can connect you with a human agent."
        )
    return f"I couldn't confirm return eligibility for order {result.order_id}."


def _order_choice(orders: tuple[OrderSummary, ...], *, other: bool) -> str:
    listed = "; ".join(f"{order.order_id} ({order.item_name})" for order in orders)
    lead = "Which other order" if other else "Which order"
    return f"{lead} should I check? I can see: {listed}."


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
        rewritten = rewrite_product_follow_up(
            request.text, getattr(request, "active_product", None)
        )
        query = rewritten or request.text
        retrieval = self._retriever.retrieve(query)
        if not retrieval.sufficient_evidence:
            return self._insufficient(retrieval.reason)
        if self._answerer is None:
            raise GroundedAnswerError("grounded_answerer_unavailable")

        answer = self._answerer.answer(query, retrieval.hits)
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
        cited_products = {
            chunk.doc_id for chunk in cited_chunks if product_for_doc(chunk.doc_id)
        }
        return HandlerResult(
            message=f"{answer.text}\n\nSources: {citation_text}",
            handler_name=self.name,
            metadata={
                "query_rewritten_from_memory": rewritten is not None,
                "active_product": (
                    next(iter(cited_products)) if len(cited_products) == 1 else None
                ),
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

        session = DEMO_SESSIONS.get(request.session_id)
        if session is None:
            return HandlerResult(
                message="I could not verify the support session for that order.",
                handler_name=self.name,
                metadata={"tool_error": "unknown_session"},
            )

        order_ids = _ORDER_ID.findall(request.text)
        active_order_id = getattr(request, "active_order_id", None)
        memory_resolved = False
        if not order_ids:
            wants_other = _OTHER_ORDER.search(request.text) is not None
            if active_order_id and not wants_other:
                order_ids = [active_order_id]
                memory_resolved = True
            else:
                try:
                    owned = self._tools.list_orders(session=session)
                except OrderToolError as exc:
                    return HandlerResult(
                        message=ACCESS_ERROR_REPLY,
                        handler_name=self.name,
                        metadata={"tool_error": exc.reason_code},
                    )
                candidates = tuple(
                    order
                    for order in owned
                    if not (wants_other and order.order_id == active_order_id)
                )
                if len(candidates) == 1:
                    order_ids = [candidates[0].order_id]
                    memory_resolved = True
                elif not candidates:
                    return HandlerResult(
                        message="I couldn't find another order on your account.",
                        handler_name=self.name,
                        metadata={"tool_error": "no_matching_order"},
                    )
                else:
                    return HandlerResult(
                        message=_order_choice(candidates, other=wants_other),
                        handler_name=self.name,
                        metadata={
                            "tool_error": (
                                "ambiguous_memory_reference"
                                if wants_other
                                else "missing_or_ambiguous_order_id"
                            ),
                            "allowed_facts": AllowedFacts(
                                order_ids=frozenset(o.order_id for o in candidates)
                            ),
                            "suggestions": tuple(
                                f"Where is order {o.order_id}?" for o in candidates[:3]
                            ),
                        },
                    )
        if len(order_ids) != 1:
            return HandlerResult(
                message="Please ask about one order at a time so I can check it safely.",
                handler_name=self.name,
                metadata={"tool_error": "missing_or_ambiguous_order_id"},
            )
        if self._tool_caller is None or memory_resolved:
            order_id = order_ids[0]
            tool_name = (
                "check_return_eligibility"
                if _RETURN_REQUEST.search(request.text)
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
                eligibility = self._tools.check_return_eligibility(
                    order_id=order_id, session=session
                )
                product = product_for_item_name(eligibility.item_name)
                return HandlerResult(
                    message=return_eligibility_message(eligibility),
                    handler_name=self.name,
                    metadata={
                        "allowed_facts": AllowedFacts.from_return_eligibility(eligibility),
                        "tool_name": "check_return_eligibility",
                        "memory_resolved": memory_resolved,
                        "active_product": product.doc_id if product else None,
                    },
                )
            if tool_name != "get_order_status":
                raise ToolCallProviderError("order_tool_name_not_allowlisted")
            status = self._tools.get_order_status(order_id=order_id, session=session)
        except OrderToolError as exc:
            return HandlerResult(
                message=ACCESS_ERROR_REPLY,
                handler_name=self.name,
                metadata={"tool_error": exc.reason_code},
            )

        product = product_for_item_name(status.item_name)
        return HandlerResult(
            message=order_status_message(status),
            handler_name=self.name,
            metadata={
                "allowed_facts": AllowedFacts.from_order_status(status),
                "tool_name": "get_order_status",
                "memory_resolved": memory_resolved,
                "active_product": product.doc_id if product else None,
            },
        )


class EscalateToHumanHandler:
    """Create a safe handoff marker without promising a business outcome."""

    name = "escalate_to_human_handler"

    def handle(
        self, request: CheckedInputLike, decision: RouteDecision
    ) -> HandlerResult:
        reference = handoff_reference(request.trace_id)
        summary = getattr(request, "handoff_summary", None)
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
                "handoff_summary": summary,
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

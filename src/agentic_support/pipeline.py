"""Single guarded SupportService entry point for text and future voice input."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from .config import Settings
from .facts import AllowedFacts, OutputClaimGuard
from .grounded_answers import GroqGroundedAnswerer
from .groq_client import build_groq_chat_client
from .guardrails import (
    GroqSafetyClassifier,
    InputGuard,
    RuleBasedSafetyClassifier,
)
from .handlers import (
    HandlerRegistry,
    HandlerResult,
    build_default_registry,
)
from .logging_config import log_event
from .memory import MemorySnapshot, MemoryTurn, SessionMemoryStore
from .hybrid_routing import HybridRouter
from .routing import GroqStructuredClassifier, RouteDecision, StructuredIntentRouter
from .semantic_routing import SemanticRouter, build_semantic_router
from .retrieval import GroundedRetriever
from .tool_calling import GroqOrderToolCaller
from .tools import DeterministicOrderTools
from .tracing import trace_context


MAX_INPUT_CHARS = 2000
Channel = Literal["text", "voice"]
ResponseStatus = Literal["ok", "rejected", "failed_closed"]

# Customer-facing wording for each way a turn can stop. They are distinct so
# the customer can tell "I won't do that" from "something is broken" from
# "please rephrase", and none of them reveals which check fired.
INVALID_INPUT_REPLY = (
    "I couldn't read that message. Please send it again as plain text "
    "(up to 2,000 characters)."
)
UNSAFE_INPUT_REPLY = (
    "I can't help with that request. I can check your orders, explain our "
    "return, warranty, and shipping policies, or answer product questions."
)
SAFETY_UNAVAILABLE_REPLY = (
    "I can't check that request safely right now. Please try again in a "
    "moment, or ask for a human agent."
)
UNROUTABLE_REPLY = (
    "I couldn't work out what you need. Please rephrase, or ask for a human "
    "agent."
)
NO_HANDLER_REPLY = (
    "I can't handle that kind of request right now. Please ask for a human agent."
)
HANDLER_ERROR_REPLY = (
    "Something went wrong while handling that request, so I stopped rather "
    "than guess. Please try again, or ask for a human agent."
)
UNVERIFIED_ANSWER_REPLY = (
    "I couldn't verify every detail in that answer, so I won't guess. A human "
    "agent can help if you need more detail."
)
@dataclass(frozen=True, slots=True)
class CheckedInput:
    """Input created only after the Step 4 normalization/shape checks."""

    text: str
    trace_id: str
    session_id: str
    channel: Channel
    active_order_id: str | None = None
    last_intent: str | None = None


@dataclass(frozen=True, slots=True)
class SupportResponse:
    """Safe transport-neutral response returned by SupportService."""

    trace_id: str
    status: ResponseStatus
    message: str
    intent: str | None = None
    handler_name: str | None = None
    metadata: dict[str, object] = field(default_factory=dict)


def _normalize_input(message: object) -> tuple[str | None, str | None]:
    if not isinstance(message, str):
        return None, "message_must_be_text"
    normalized = unicodedata.normalize("NFKC", message)
    if any(
        unicodedata.category(character).startswith("C")
        and character not in "\t\n\r"
        for character in normalized
    ):
        return None, "message_contains_control_character"
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return None, "message_is_empty"
    if len(normalized) > MAX_INPUT_CHARS:
        return None, "message_is_too_large"
    return normalized, None


def validate_input(
    message: object,
    *,
    trace_id: str,
    session_id: str,
    channel: Channel,
) -> tuple[CheckedInput | None, str | None]:
    """Perform the minimal Step 4 safety/shape check."""

    if channel not in ("text", "voice"):
        return None, "channel_is_invalid"
    normalized, reason = _normalize_input(message)
    if reason is not None or normalized is None:
        return None, reason or "message_is_invalid"
    return (
        CheckedInput(
            text=normalized,
            trace_id=trace_id,
            session_id=session_id,
            channel=channel,
        ),
        None,
    )


class SupportService:
    """The only Step 4 entry point from raw message to registered handler."""

    def __init__(
        self,
        *,
        router: StructuredIntentRouter,
        registry: HandlerRegistry,
        logger: logging.Logger | None = None,
        input_guard: InputGuard | None = None,
        output_guard: OutputClaimGuard | None = None,
        memory_store: SessionMemoryStore | None = None,
        semantic_router: SemanticRouter | None = None,
    ) -> None:
        self.router = router
        self.registry = registry
        self.logger = logger or logging.getLogger("agentic_support.pipeline")
        self.input_guard = input_guard or InputGuard(RuleBasedSafetyClassifier())
        self.output_guard = output_guard or OutputClaimGuard()
        self.memory_store = memory_store or SessionMemoryStore()
        self.hybrid_router = HybridRouter(
            router, semantic_router=semantic_router, logger=self.logger
        )

    def clear_session(self, session_id: str) -> None:
        """Clear the bounded memory for one authenticated/demo session."""

        self.memory_store.clear(session_id)

    def _select_route(
        self, checked_input: CheckedInput, memory: MemorySnapshot
    ) -> tuple[RouteDecision, str]:
        """Return the route decision and the tier that produced it."""

        return self.hybrid_router.route(
            checked_input.text,
            active_order_id=checked_input.active_order_id,
            memory_hint=memory.routing_hint(),
        )

    def preview_route(
        self, message: str, *, session_id: str = "unknown-session"
    ) -> tuple[RouteDecision, str]:
        """Return the routing decision for evaluation without running handlers.

        This skips the input guard and handlers on purpose: evaluation scripts
        use it to measure routing alone. Production traffic must use
        ``handle()``, which is the only path that dispatches to a handler.
        """

        checked_input, reason = validate_input(
            message,
            trace_id="route-preview",
            session_id=session_id,
            channel="text",
        )
        if checked_input is None:
            return (
                RouteDecision(
                    intent=None,
                    confidence=0.0,
                    accepted=False,
                    reason=reason or "invalid_input",
                ),
                "input_validation",
            )
        memory = self.memory_store.snapshot(session_id)
        checked_input = replace(
            checked_input,
            active_order_id=memory.active_order_id,
            last_intent=memory.last_intent,
        )
        return self._select_route(checked_input, memory)

    def handle(
        self,
        message: object,
        *,
        session_id: str = "unknown-session",
        channel: Channel = "text",
        trace_id: str | None = None,
    ) -> SupportResponse:
        with trace_context(trace_id) as active_trace_id:
            checked_input, rejection_reason = validate_input(
                message,
                trace_id=active_trace_id,
                session_id=session_id,
                channel=channel,
            )
            if checked_input is None:
                log_event(
                    self.logger,
                    "input_rejected",
                    reason=rejection_reason or "invalid_input",
                )
                return SupportResponse(
                    trace_id=active_trace_id,
                    status="rejected",
                    message=INVALID_INPUT_REPLY,
                    metadata={"reason": rejection_reason or "invalid_input"},
                )

            safety_decision = self.input_guard.check(checked_input)
            if not safety_decision.allowed:
                log_event(
                    self.logger,
                    "input_guard_failed_closed",
                    reason=safety_decision.reason,
                )
                return SupportResponse(
                    trace_id=active_trace_id,
                    status="failed_closed",
                    message=(
                        SAFETY_UNAVAILABLE_REPLY
                        if safety_decision.fail_closed
                        else UNSAFE_INPUT_REPLY
                    ),
                    metadata={"reason": safety_decision.reason},
                )

            memory = self.memory_store.snapshot(session_id)
            checked_input = replace(
                checked_input,
                active_order_id=memory.active_order_id,
                last_intent=memory.last_intent,
            )
            decision, routing_source = self._select_route(checked_input, memory)
            if not decision.accepted or decision.intent is None:
                if self.registry.get("unclear") is None:
                    log_event(
                        self.logger,
                        "routing_failed_closed",
                        reason=decision.reason,
                    )
                    return SupportResponse(
                        trace_id=active_trace_id,
                        status="failed_closed",
                        message=UNROUTABLE_REPLY,
                        metadata={"reason": decision.reason},
                    )
                # No confident route: ask the customer to clarify through the
                # template-only conversation handler. It has no retriever or
                # tools, so an unrouted message still cannot reach them.
                log_event(
                    self.logger,
                    "routing_fallback_to_clarification",
                    reason=decision.reason,
                )
                decision = RouteDecision(
                    intent="unclear",
                    confidence=decision.confidence,
                    accepted=True,
                    reason=decision.reason,
                )
                routing_source = "router_fallback"

            handler = self.registry.get(decision.intent)
            if handler is None:
                log_event(
                    self.logger,
                    "handler_missing_failed_closed",
                    intent=decision.intent,
                )
                return SupportResponse(
                    trace_id=active_trace_id,
                    status="failed_closed",
                    message=NO_HANDLER_REPLY,
                    intent=decision.intent,
                    metadata={"reason": "handler_not_registered"},
                )

            try:
                result: HandlerResult = handler.handle(checked_input, decision)
            except Exception:
                self.logger.exception(
                    "handler_failed_closed",
                    extra={"event": "handler_failed_closed", "fields": {"intent": decision.intent}},
                )
                return SupportResponse(
                    trace_id=active_trace_id,
                    status="failed_closed",
                    message=HANDLER_ERROR_REPLY,
                    intent=decision.intent,
                    metadata={"reason": "handler_error"},
                )

            allowed_facts = result.metadata.get("allowed_facts", AllowedFacts())
            if not isinstance(allowed_facts, AllowedFacts):
                allowed_facts = AllowedFacts()
            claim_decision = self.output_guard.validate(
                result.message, allowed_facts
            )
            if not claim_decision.allowed:
                log_event(
                    self.logger,
                    "output_guard_failed_closed",
                    reason=claim_decision.reason,
                )
                return SupportResponse(
                    trace_id=active_trace_id,
                    status="failed_closed",
                    message=UNVERIFIED_ANSWER_REPLY,
                    intent=decision.intent,
                    handler_name=result.handler_name,
                    metadata={"reason": claim_decision.reason},
                )

            public_metadata = {
                key: value
                for key, value in result.metadata.items()
                if key != "allowed_facts"
            }
            response = SupportResponse(
                trace_id=active_trace_id,
                status="ok",
                message=result.message,
                intent=decision.intent,
                handler_name=result.handler_name,
                metadata={
                    **public_metadata,
                    "confidence": decision.confidence,
                    "routing_source": routing_source,
                    "route_reason": decision.reason,
                },
            )
            verified_order_id = None
            if result.handler_name == "order_status_handler":
                order_ids = allowed_facts.order_ids
                if len(order_ids) == 1:
                    verified_order_id = next(iter(order_ids))
            self.memory_store.append(
                session_id,
                MemoryTurn(
                    trace_id=active_trace_id,
                    channel=checked_input.channel,
                    user_text=checked_input.text,
                    assistant_text=response.message,
                    status=response.status,
                    intent=response.intent,
                    handler_name=response.handler_name,
                ),
                verified_order_id=verified_order_id,
            )
            return response


def build_live_support_service(
    settings: Settings | None = None,
) -> SupportService:
    """Build the Groq-backed service; requires a local provider key."""

    active_settings = settings or Settings.from_environment()
    # One rotating client shared by every adapter, so a rate-limited key is
    # skipped by all of them and extra keys in GROQ_API_KEYS are used.
    client = build_groq_chat_client(active_settings)
    classifier = GroqStructuredClassifier(active_settings, client=client)
    safety_classifier = GroqSafetyClassifier(active_settings, client=client)
    router = StructuredIntentRouter(
        classifier,
        model_name=active_settings.groq_router_model,
        max_attempts=active_settings.router_max_attempts,
        retry_delay_seconds=active_settings.router_retry_delay_seconds,
    )
    retriever = GroundedRetriever.from_directory(
        Path(__file__).resolve().parents[2] / "knowledge_base"
    )
    return SupportService(
        router=router,
        registry=build_default_registry(
            retriever=retriever,
            answerer=GroqGroundedAnswerer(active_settings, client=client),
            order_tools=DeterministicOrderTools(),
            order_tool_caller=GroqOrderToolCaller(active_settings, client=client),
        ),
        input_guard=InputGuard(safety_classifier),
        output_guard=OutputClaimGuard(),
        semantic_router=build_semantic_router(),
    )

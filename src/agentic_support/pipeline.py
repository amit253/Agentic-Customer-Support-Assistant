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
from .memory import MemoryTurn, SessionMemoryStore
from .routing import GroqStructuredClassifier, RouteDecision, StructuredIntentRouter
from .retrieval import GroundedRetriever
from .tool_calling import GroqOrderToolCaller
from .tools import DeterministicOrderTools
from .tracing import trace_context


MAX_INPUT_CHARS = 2000
Channel = Literal["text", "voice"]
ResponseStatus = Literal["ok", "rejected", "failed_closed"]
ORDER_ID_PATTERN = re.compile(r"\bNS-\d{2}-\d{4}-\d\b", re.I)
ORDER_OPERATION_PATTERN = re.compile(
    r"\b(?:where|status|track|tracking|delivery|deliver|arrive|"
    r"cancel|refund|eligible|eligibility|check)\b|"
    r"\b(?:can|may|am)\s+i\s+(?:return|send\s+back)\b|"
    r"\breturn\s+(?:order|it|this|that)\b",
    re.I,
)
PRODUCT_LOOKALIKE_PATTERN = re.compile(
    r"\b(?:capacity|size|material|colour|color|care|feature|features|"
    r"specification|specifications|policy|what\s+is|what's|how\s+does|"
    r"does\s+it)\b",
    re.I,
)


def _is_memory_order_follow_up(
    message: str,
    *,
    active_order_id: str | None,
) -> bool:
    """Recognize only clear order pronoun follow-ups with verified memory."""

    if active_order_id is None:
        return False
    if re.search(r"\bNS-\d{2}-\d{4}-\d\b", message, re.I):
        return False
    has_reference = re.search(
        r"\b(?:it|that|this|the order|my order)\b", message, re.I
    )
    has_order_action = re.search(
        r"\b(?:return|eligible|send back|status|where|track|deliver|arrive|"
        r"cancel|refund|check)\b",
        message,
        re.I,
    )
    return has_reference is not None and has_order_action is not None


def _is_explicit_order_operation(message: str) -> bool:
    """Recognize an unambiguous operation on exactly one stated order.

    Product questions may mention an order as background context, so an order
    ID alone is not enough to bypass the LLM router. Only a clear status,
    delivery, return, refund, cancellation, or tracking operation is resolved
    locally. This keeps the real pipeline deterministic for the failure case
    while preserving product-question routing for benign look-alikes.
    """

    if len(ORDER_ID_PATTERN.findall(message)) != 1:
        return False
    if not ORDER_OPERATION_PATTERN.search(message):
        return False
    if re.search(r"\breturn\s+policy\b", message, re.I):
        return False
    if PRODUCT_LOOKALIKE_PATTERN.search(message):
        return bool(
            re.search(
                r"\b(?:return|eligible|eligibility|send\s+back|refund|cancel)\b",
                message,
                re.I,
            )
            and not re.search(r"\b(?:policy|what\s+is|what's)\b", message, re.I)
        )
    return True


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
class RoutingInput:
    """Safe classifier text with verified session context when available."""

    text: str
    memory_hint: str = ""


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
    ) -> None:
        self.router = router
        self.registry = registry
        self.logger = logger or logging.getLogger("agentic_support.pipeline")
        self.input_guard = input_guard or InputGuard(RuleBasedSafetyClassifier())
        self.output_guard = output_guard or OutputClaimGuard()
        self.memory_store = memory_store or SessionMemoryStore()

    def clear_session(self, session_id: str) -> None:
        """Clear the bounded memory for one authenticated/demo session."""

        self.memory_store.clear(session_id)

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
                    message="I could not process that request safely.",
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
                    message="I could not process that request safely.",
                    metadata={"reason": safety_decision.reason},
                )

            memory = self.memory_store.snapshot(session_id)
            checked_input = replace(
                checked_input,
                active_order_id=memory.active_order_id,
                last_intent=memory.last_intent,
            )
            if _is_explicit_order_operation(checked_input.text):
                decision = RouteDecision(
                    intent="order_status",
                    confidence=1.0,
                    accepted=True,
                    reason="explicit_order_operation",
                )
                routing_source = "deterministic_order_signal"
                log_event(
                    self.logger,
                    "deterministic_order_route",
                    reason="explicit_order_operation",
                )
            elif _is_memory_order_follow_up(
                checked_input.text,
                active_order_id=checked_input.active_order_id,
            ):
                decision = RouteDecision(
                    intent="order_status",
                    confidence=1.0,
                    accepted=True,
                    reason="memory_resolved_order_follow_up",
                )
                routing_source = "verified_session_memory"
                log_event(
                    self.logger,
                    "memory_resolved_order_follow_up",
                    active_order_id=checked_input.active_order_id,
                )
            else:
                decision = self.router.route(
                    RoutingInput(
                        text=checked_input.text,
                        memory_hint=memory.routing_hint(),
                    )
                )
                routing_source = "classifier"
            if not decision.accepted or decision.intent is None:
                log_event(
                    self.logger,
                    "routing_failed_closed",
                    reason=decision.reason,
                )
                return SupportResponse(
                    trace_id=active_trace_id,
                    status="failed_closed",
                    message="I could not classify that request safely. Please rephrase or request human support.",
                    metadata={"reason": decision.reason},
                )

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
                    message="This request cannot be routed safely right now.",
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
                    message="I could not complete that request safely.",
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
                    message="I could not verify that response safely.",
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
    classifier = GroqStructuredClassifier(active_settings)
    safety_classifier = GroqSafetyClassifier(active_settings)
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
            answerer=GroqGroundedAnswerer(active_settings),
            order_tools=DeterministicOrderTools(),
            order_tool_caller=GroqOrderToolCaller(active_settings),
        ),
        input_guard=InputGuard(safety_classifier),
        output_guard=OutputClaimGuard(),
    )

"""Single guarded SupportService entry point for text and future voice input."""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Literal

from .config import Settings
from .facts import AllowedFacts, OutputClaimGuard
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
from .routing import GroqStructuredClassifier, RouteDecision, StructuredIntentRouter
from .tools import DeterministicOrderTools
from .tracing import trace_context


MAX_INPUT_CHARS = 2000
Channel = Literal["text", "voice"]
ResponseStatus = Literal["ok", "rejected", "failed_closed"]


@dataclass(frozen=True, slots=True)
class CheckedInput:
    """Input created only after the Step 4 normalization/shape checks."""

    text: str
    trace_id: str
    session_id: str
    channel: Channel


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
    ) -> None:
        self.router = router
        self.registry = registry
        self.logger = logger or logging.getLogger("agentic_support.pipeline")
        self.input_guard = input_guard or InputGuard(RuleBasedSafetyClassifier())
        self.output_guard = output_guard or OutputClaimGuard()

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

            decision = self.router.route(checked_input)
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

            return SupportResponse(
                trace_id=active_trace_id,
                status="ok",
                message=result.message,
                intent=decision.intent,
                handler_name=result.handler_name,
                metadata={
                    **public_metadata,
                    "confidence": decision.confidence,
                },
            )


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
    return SupportService(
        router=router,
        registry=build_default_registry(order_tools=DeterministicOrderTools()),
        input_guard=InputGuard(safety_classifier),
        output_guard=OutputClaimGuard(),
    )

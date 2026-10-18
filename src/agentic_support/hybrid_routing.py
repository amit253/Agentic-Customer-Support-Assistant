"""Hybrid router: deterministic rules, then examples, then the LLM.

Tier 0  rules            exact, cheap, precision-first (route_rules.py)
Tier 1  semantic examples nearest-neighbour over labeled examples (~ms)
Tier 2  LLM classifier    Groq structured output for whatever is left

Every decision carries the tier that produced it as ``routing_source`` so
logs and evaluation can show how much traffic each tier handles. The router
only chooses a handler; it never authorizes an action. It runs after the
input guard, so no tier ever sees a message that failed the safety check.
"""

from __future__ import annotations

import logging
from typing import Any

from .logging_config import log_event
from .route_rules import (
    is_explicit_human_request,
    is_explicit_order_operation,
    is_gibberish,
    is_memory_order_follow_up,
    is_pure_smalltalk,
)
from .routing import RouteDecision, StructuredIntentRouter
from .semantic_routing import SemanticRouter


class _RoutingInput:
    __slots__ = ("text", "memory_hint")

    def __init__(self, text: str, memory_hint: str) -> None:
        self.text = text
        self.memory_hint = memory_hint


def _rule(intent: str, reason: str) -> RouteDecision:
    return RouteDecision(intent=intent, confidence=1.0, accepted=True, reason=reason)  # type: ignore[arg-type]


class HybridRouter:
    """Run routing tiers in order and stop at the first confident answer."""

    def __init__(
        self,
        llm_router: StructuredIntentRouter,
        *,
        semantic_router: SemanticRouter | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        self.llm_router = llm_router
        self.semantic_router = semantic_router
        self.logger = logger or logging.getLogger("agentic_support.routing")

    def route(
        self,
        text: str,
        *,
        active_order_id: str | None = None,
        memory_hint: str = "",
    ) -> tuple[RouteDecision, str]:
        decision, source = self._route(
            text, active_order_id=active_order_id, memory_hint=memory_hint
        )
        log_event(
            self.logger,
            "route_selected",
            routing_source=source,
            intent=decision.intent,
            accepted=decision.accepted,
            reason=decision.reason,
        )
        return decision, source

    def _route(
        self, text: str, *, active_order_id: str | None, memory_hint: str
    ) -> tuple[RouteDecision, str]:
        if is_explicit_order_operation(text):
            return _rule("order_status", "explicit_order_operation"), "deterministic_order_signal"
        if is_memory_order_follow_up(text, active_order_id=active_order_id):
            return (
                _rule("order_status", "memory_resolved_order_follow_up"),
                "verified_session_memory",
            )
        # Closed-vocabulary smalltalk is checked before the human rule: "are
        # you a bot or a real person?" mentions a person but asks who we are.
        if is_pure_smalltalk(text):
            return _rule("smalltalk", "closed_vocabulary_smalltalk"), "rule_smalltalk"
        if is_explicit_human_request(text):
            return _rule("escalate_to_human", "explicit_human_request"), "rule_human_request"
        if is_gibberish(text):
            return _rule("unclear", "gibberish"), "rule_gibberish"

        if self.semantic_router is not None:
            semantic = self.semantic_router.route(text)
            if semantic is not None:
                return semantic, "semantic_exemplars"

        decision = self.llm_router.route(_RoutingInput(text, memory_hint))
        return decision, "classifier"

    @property
    def cache_stats(self) -> Any:
        return self.llm_router.cache_stats

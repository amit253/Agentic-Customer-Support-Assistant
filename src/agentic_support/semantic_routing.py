"""Nearest-neighbour intent classifier over labeled examples: tier 1.

The router embeds the message with the same local model the retriever already
loads, compares it with labeled example messages, and answers only when the
best intent is both similar enough and clearly ahead of the runner-up. Any
other message is left for the LLM tier. This costs a few milliseconds and no
provider call.

Thresholds come from ``scripts/calibrate_semantic_router.py`` (leave-one-out
over the examples), not from the held-out evaluation set.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from .retrieval import DEFAULT_EMBEDDING_MODEL, SentenceTransformerEmbedder, TextEmbedder
from .route_exemplars import ROUTE_EXEMPLARS
from .route_rules import ORDER_ID_PATTERN
from .routing import RouteDecision


# Calibrated by scripts/calibrate_semantic_router.py with a 0.97 precision
# target (leave-one-out over 137 examples, all-MiniLM-L6-v2): precision 1.000,
# coverage 0.438. The margin does the work; the score floor is the grid floor.
# multilingual-e5-small was also calibrated (0.89 / 0.02) but answered only
# 0.329 of examples at the same precision, so routing keeps MiniLM.
DEFAULT_MIN_SCORE = 0.30
DEFAULT_MIN_MARGIN = 0.15
NEIGHBOURS_PER_INTENT = 2
ROUTING_EMBEDDING_MODEL = DEFAULT_EMBEDDING_MODEL


def normalize_for_routing(text: str) -> str:
    """Replace concrete order IDs so they do not dominate the embedding."""

    return ORDER_ID_PATTERN.sub("[order id]", " ".join(text.split()))


@dataclass(frozen=True, slots=True)
class IntentScore:
    intent: str
    score: float


class SemanticRouter:
    """Score a message against each intent's closest labeled examples."""

    def __init__(
        self,
        embedder: TextEmbedder,
        exemplars: Mapping[str, Sequence[str]] = ROUTE_EXEMPLARS,
        *,
        min_score: float = DEFAULT_MIN_SCORE,
        min_margin: float = DEFAULT_MIN_MARGIN,
    ) -> None:
        if len(exemplars) < 2:
            raise ValueError("semantic routing needs at least two intents")
        self.embedder = embedder
        self.min_score = min_score
        self.min_margin = min_margin
        self._labels: list[str] = []
        texts: list[str] = []
        for intent, examples in exemplars.items():
            if not examples:
                raise ValueError(f"intent {intent} has no examples")
            for example in examples:
                self._labels.append(intent)
                texts.append(normalize_for_routing(example))
        self._intents = tuple(exemplars)
        self._vectors = np.asarray(embedder.encode(texts), dtype=np.float32)

    def scores(self, message: str) -> list[IntentScore]:
        """Return per-intent scores, best first."""

        query = np.asarray(
            self.embedder.encode([normalize_for_routing(message)])[0],
            dtype=np.float32,
        )
        similarities = self._vectors @ query
        labels = np.asarray(self._labels)
        results = []
        for intent in self._intents:
            intent_scores = np.sort(similarities[labels == intent])[::-1]
            top = intent_scores[:NEIGHBOURS_PER_INTENT]
            results.append(IntentScore(intent=intent, score=float(top.mean())))
        return sorted(results, key=lambda item: item.score, reverse=True)

    def route(self, message: str) -> RouteDecision | None:
        """Return a confident decision, or ``None`` to defer to the LLM tier."""

        best, runner_up = self.scores(message)[:2]
        if best.score < self.min_score or best.score - runner_up.score < self.min_margin:
            return None
        return RouteDecision(
            intent=best.intent,  # type: ignore[arg-type]
            confidence=round(best.score, 4),
            accepted=True,
            reason="semantic_match",
        )


def build_semantic_router(embedder: TextEmbedder | None = None) -> SemanticRouter:
    """Build the production semantic tier on the calibrated MiniLM model."""

    return SemanticRouter(embedder or SentenceTransformerEmbedder(ROUTING_EMBEDDING_MODEL))

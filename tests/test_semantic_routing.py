from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from agentic_support.intents import VALID_INTENTS
from agentic_support.route_exemplars import ROUTE_EXEMPLARS
from agentic_support.semantic_routing import SemanticRouter, normalize_for_routing


ROOT = Path(__file__).resolve().parents[1]


def _normalized(text: str) -> str:
    collapsed = " ".join(text.casefold().split())
    return collapsed.strip(" ?!.") or collapsed


def test_route_examples_never_overlap_the_held_out_routing_set() -> None:
    eval_texts = {
        _normalized(json.loads(line)["text"])
        for line in (ROOT / "evals" / "routing_eval.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    example_texts = {_normalized(text) for examples in ROUTE_EXEMPLARS.values() for text in examples}

    assert eval_texts.isdisjoint(example_texts)


def test_route_examples_cover_exactly_the_registered_intents() -> None:
    assert set(ROUTE_EXEMPLARS) == VALID_INTENTS


def test_order_ids_are_replaced_before_embedding() -> None:
    assert normalize_for_routing("Where is  NS-26-2044-8 now?") == "Where is [order id] now?"


class KeywordEmbedder:
    """Deterministic 3-D embedder: [order words, product words, greeting words]."""

    model_name = "keyword-test-embedder"

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        rows = []
        for text in texts:
            lowered = text.casefold()
            row = np.asarray(
                [
                    lowered.count("order") + lowered.count("parcel"),
                    lowered.count("capacity") + lowered.count("liter"),
                    lowered.count("hello") + lowered.count("hi"),
                ],
                dtype=np.float32,
            ) + 0.01
            rows.append(row / np.linalg.norm(row))
        return np.asarray(rows)


EXAMPLES = {
    "order_status": ("where is my order", "track my parcel order"),
    "product_question": ("what is the capacity", "how many liter capacity"),
    "smalltalk": ("hello", "hi hello"),
}


def test_confident_semantic_match_is_accepted() -> None:
    router = SemanticRouter(KeywordEmbedder(), EXAMPLES, min_score=0.5, min_margin=0.2)

    decision = router.route("order order")

    assert decision is not None
    assert decision.intent == "order_status"
    assert decision.reason == "semantic_match"


def test_ambiguous_message_defers_to_the_llm_tier() -> None:
    router = SemanticRouter(KeywordEmbedder(), EXAMPLES, min_score=0.5, min_margin=0.2)

    # Equal order and capacity signal: no clear winner, so no decision.
    assert router.route("order capacity") is None

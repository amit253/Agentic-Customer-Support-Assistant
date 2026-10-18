from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from agentic_support.hybrid_retrieval import (
    BM25Index,
    HybridConfig,
    HybridRetriever,
    bm25_tokens,
)
from agentic_support.retrieval import DocumentChunk


def _chunk(doc_id: str, text: str) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=f"{doc_id}#chunk-000",
        doc_id=doc_id,
        title=doc_id,
        source_path=f"knowledge_base/{doc_id}.md",
        chunk_index=0,
        text=text,
    )


CHUNKS = (
    _chunk("kb-trailmark", "The Trailmark 28 is a 28-liter travel backpack."),
    _chunk("kb-cityhaul", "The CityHaul 20 is a 20-liter commuter backpack."),
    _chunk("kb-care", "Spot-clean packs with mild soap and cool water."),
)


class TopicEmbedder:
    """3-D embedder: [backpack size, cleaning, unrelated]."""

    model_name = "topic-test-embedder"

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        rows = []
        for text in texts:
            lowered = text.casefold()
            size = sum(lowered.count(word) for word in ("liter", "backpack", "bigger", "capacity"))
            clean = sum(lowered.count(word) for word in ("clean", "soap", "wash"))
            rows.append(np.asarray([size, clean, 0.2], dtype=np.float32) + 0.01)
        return np.asarray(rows)


def _retriever(**config: object) -> HybridRetriever:
    return HybridRetriever(
        chunks=CHUNKS,
        embedder=TopicEmbedder(),
        config=HybridConfig(**config),  # type: ignore[arg-type]
    )


def test_bm25_tokens_drop_stopwords_and_fold_plurals() -> None:
    assert bm25_tokens("What are the CityHaul packs?") == ["cityhaul", "pack"]


def test_bm25_prefers_the_document_with_the_exact_product_name() -> None:
    index = BM25Index([chunk.text for chunk in CHUNKS])

    scores = index.scores("cityhaul")

    assert int(np.argmax(scores)) == 1
    assert scores[0] == 0.0


def test_keyword_match_lifts_a_document_the_embeddings_do_not_favour() -> None:
    # The test embedder has no signal for a bare product name, so only BM25
    # knows "CityHaul" belongs to one document.
    dense_only = _retriever(use_bm25=False, gate_threshold=0.0).rank_all("CityHaul")
    fused = _retriever(use_bm25=True, gate_threshold=0.0).rank_all("CityHaul")

    assert dense_only[0].chunk.doc_id != "kb-cityhaul"
    assert fused[0].chunk.doc_id == "kb-cityhaul"


def test_gate_looks_at_the_best_candidate_only() -> None:
    retriever = _retriever(use_bm25=True, gate_threshold=0.95, support_threshold=0.5)

    unrelated = retriever.retrieve("weather forecast")
    answerable = retriever.retrieve("how many liter backpack")

    assert unrelated.sufficient_evidence is False
    assert unrelated.reason == "best_candidate_below_evidence_gate"
    assert answerable.sufficient_evidence is True


def test_comparison_question_keeps_both_product_documents() -> None:
    retriever = _retriever(use_bm25=True, gate_threshold=0.9, support_threshold=0.5)

    response = retriever.retrieve("Is the CityHaul bigger than the Trailmark backpack?")

    doc_ids = {hit.chunk.doc_id for hit in response.hits}
    assert {"kb-cityhaul", "kb-trailmark"} <= doc_ids
    assert "kb-care" not in doc_ids


def test_empty_query_reports_insufficient_evidence() -> None:
    response = _retriever().retrieve("   ")

    assert response.sufficient_evidence is False
    assert response.reason == "empty_query"

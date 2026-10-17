from __future__ import annotations

from pathlib import Path

import pytest

from agentic_support.retrieval import (
    DEFAULT_EMBEDDING_MODEL,
    GroundedRetriever,
    chunk_documents,
    load_markdown_documents,
)


ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_BASE = ROOT / "knowledge_base"


@pytest.fixture(scope="session")
def retriever() -> GroundedRetriever:
    return GroundedRetriever.from_directory(
        KNOWLEDGE_BASE,
        model_name=DEFAULT_EMBEDDING_MODEL,
        min_similarity=0.45,
    )


def test_ingestion_and_chunking_are_deterministic_with_provenance() -> None:
    documents = load_markdown_documents(KNOWLEDGE_BASE)
    first = chunk_documents(documents)
    second = chunk_documents(documents)

    assert first == second
    assert len(first) >= len(documents)
    assert first[0].chunk_id.endswith("#chunk-000")
    assert first[0].source_path.startswith("knowledge_base/")
    assert first[0].doc_id in first[0].chunk_id


def test_paraphrase_retrieves_standard_returns(retriever: GroundedRetriever) -> None:
    response = retriever.retrieve(
        "How long can I send back a regular unused backpack?", top_k=4
    )

    assert response.sufficient_evidence is True
    assert response.hits
    assert response.hits[0].chunk.doc_id == "kb-005-standard-returns"
    assert response.hits[0].chunk.source_path == (
        "knowledge_base/kb-005-standard-returns.md"
    )


def test_irrelevant_query_returns_insufficient_evidence(
    retriever: GroundedRetriever,
) -> None:
    response = retriever.retrieve("What is the capital of France?", top_k=4)

    assert response.sufficient_evidence is False
    assert response.hits == ()
    assert response.reason == "no_chunk_above_similarity_threshold"


def test_conflicting_policy_query_returns_both_relevant_sources(
    retriever: GroundedRetriever,
) -> None:
    response = retriever.retrieve(
        "Does Trail Week give September orders a longer return window than the normal policy?",
        top_k=4,
    )
    document_ids = {hit.chunk.doc_id for hit in response.hits}

    assert response.sufficient_evidence is True
    assert "kb-005-standard-returns" in document_ids
    assert "kb-006-trail-week-returns" in document_ids


def test_unanswerable_refund_question_is_not_guessed(
    retriever: GroundedRetriever,
) -> None:
    response = retriever.retrieve(
        "What exact refund amount will an order missing from the database receive?",
        top_k=4,
    )

    assert response.sufficient_evidence is False
    assert response.hits == ()

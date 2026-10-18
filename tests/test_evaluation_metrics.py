from __future__ import annotations

from scripts.run_evaluation import binary_metrics, classification_metrics


def test_binary_metrics_are_computed_from_labels() -> None:
    metrics = binary_metrics(
        [True, True, False, False],
        [True, False, True, False],
    )

    assert metrics["true_positive"] == 1
    assert metrics["true_negative"] == 1
    assert metrics["false_positive"] == 1
    assert metrics["false_negative"] == 1
    assert metrics["precision"] == 0.5
    assert metrics["recall"] == 0.5


def test_classification_metrics_include_confusion_matrix() -> None:
    metrics = classification_metrics(
        ["product_question", "order_status", "order_status"],
        ["product_question", "order_status", "escalate_to_human"],
        ("product_question", "order_status", "escalate_to_human"),
    )

    assert metrics["sample_count"] == 3
    assert metrics["accuracy"] == 2 / 3
    assert metrics["confusion_matrix"]["order_status"]["escalate_to_human"] == 1


from dataclasses import dataclass

from agentic_support.handlers import HandlerRegistry, HandlerResult
from agentic_support.pipeline import SupportService
from agentic_support.retrieval import (
    DocumentChunk,
    RetrievalHit,
    RetrievalResponse,
)
from agentic_support.routing import StructuredIntentRouter, describe_provider_error
from scripts.run_evaluation import (
    evaluate_retrieval_set,
    evaluate_routing,
    percentile,
)


def _hit(doc_id: str, score: float) -> RetrievalHit:
    return RetrievalHit(
        chunk=DocumentChunk(
            chunk_id=f"{doc_id}#chunk-000",
            doc_id=doc_id,
            title=doc_id,
            source_path=f"knowledge_base/{doc_id}.md",
            chunk_index=0,
            text="fictional evaluation text",
        ),
        score=score,
    )


@dataclass
class GateRejectsEverythingRetriever:
    """Ranks the right document first, but the evidence gate rejects it."""

    def rank_all(self, query: str) -> tuple[RetrievalHit, ...]:
        return (_hit("kb-right", 0.40), _hit("kb-other", 0.10))

    def retrieve(self, query: str, *, top_k: int = 4) -> RetrievalResponse:
        return RetrievalResponse(
            query=query,
            hits=(),
            sufficient_evidence=False,
            reason="no_chunk_above_similarity_threshold",
        )


def test_percentile_uses_nearest_rank() -> None:
    assert percentile([], 0.5) is None
    assert percentile([5.0, 1.0, 3.0], 0.5) == 3.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0


def test_retrieval_metrics_separate_ranking_from_the_evidence_gate() -> None:
    result = evaluate_retrieval_set(
        GateRejectsEverythingRetriever(),
        [
            {"id": "a", "query": "q", "expected_doc_ids": ["kb-right"]},
            {"id": "b", "query": "q", "expected_doc_ids": []},
        ],
    )

    assert result["ranking"]["hit_at_1"] == 1.0
    assert result["ranking"]["mrr"] == 1.0
    assert result["gate"]["answerable_acceptance_rate"] == 0.0
    assert result["gate"]["unanswerable_rejection_rate"] == 1.0
    assert result["end_to_end"]["evidence_recall"] == 0.0


def test_preview_route_never_dispatches_a_handler() -> None:
    class Classifier:
        def classify(self, message: str) -> dict[str, object]:
            return {"intent": "product_question", "confidence": 0.99}

    class SpyHandler:
        calls = 0

        def handle(self, request: object, decision: object) -> HandlerResult:
            SpyHandler.calls += 1
            return HandlerResult(message="unused", handler_name="spy")

    service = SupportService(
        router=StructuredIntentRouter(Classifier()),
        registry=HandlerRegistry({"product_question": SpyHandler()}),
    )

    decision, source = service.preview_route("What is the capacity?")

    assert decision.intent == "product_question"
    assert source == "classifier"
    assert SpyHandler.calls == 0


def test_offline_routing_evaluation_counts_unavailable_llm_calls() -> None:
    result = evaluate_routing(
        [
            {
                "id": "x",
                "session_id": "demo-session-omar",
                "text": "Where is order NS-26-2044-8?",
                "expected_intent": "order_status",
                "category": "order_with_id",
            },
            {
                "id": "y",
                "session_id": "demo-session-omar",
                "text": "hello",
                "expected_intent": "smalltalk",
                "category": "greeting",
            },
        ]
    )

    assert result["mode"] == "offline_llm_tier_unavailable"
    assert result["cases"][0]["predicted"] == "order_status"
    assert result["cases"][0]["llm_calls"] == 0
    assert result["llm_calls"] >= 1
    assert result["by_category"]["order_with_id"] == {"total": 1, "correct": 1}


def test_provider_error_description_excludes_message_text() -> None:
    class ProviderError(Exception):
        status_code = 400
        body = {"error": {"code": "json_validate_failed", "message": "customer secret text"}}

    try:
        try:
            raise ProviderError("customer secret text")
        except ProviderError as inner:
            raise RuntimeError("wrapper") from inner
    except RuntimeError as error:
        fields = describe_provider_error(error)

    assert fields == {
        "error_type": "RuntimeError",
        "cause_type": "ProviderError",
        "status_code": 400,
        "provider_code": "json_validate_failed",
    }
    assert "customer secret text" not in str(fields)

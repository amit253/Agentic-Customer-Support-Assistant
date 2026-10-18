"""Run the routing, retrieval, guardrail, and cache evaluation suites.

Default mode is keyless: routing is measured through the real routing stack
with the LLM tier unavailable, so the report shows what the deterministic
layers handle on their own. ``--routing-mode live`` calls Groq for the LLM
tier and must be requested explicitly; its results are labeled as live.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
import re
import statistics
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable, Mapping

from agentic_support.config import Settings
from agentic_support.facts import AllowedFacts, OutputClaimGuard
from agentic_support.guardrails import InputGuard, RuleBasedSafetyClassifier
from agentic_support.handlers import HandlerRegistry
from agentic_support.memory import MemoryTurn
from agentic_support.pipeline import SupportService
from agentic_support.hybrid_retrieval import build_production_retriever
from agentic_support.retrieval import RetrievalHit
from agentic_support.routing import GroqStructuredClassifier, StructuredIntentRouter
from agentic_support.semantic_routing import build_semantic_router


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "reports"
INTENTS = ("product_question", "order_status", "escalate_to_human")
ROUTE_LABELS = (
    "product_question",
    "order_status",
    "escalate_to_human",
    "smalltalk",
    "out_of_scope",
    "unclear",
)
REJECTED = "rejected"
SECTIONS = ("routing", "retrieval", "guardrails", "cache")
LIVE_ONLY_SECTIONS = ("rag",)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def safe_ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def binary_metrics(
    expected_positive: Iterable[bool], predicted_positive: Iterable[bool]
) -> dict[str, float | int | None]:
    pairs = list(zip(expected_positive, predicted_positive, strict=True))
    tp = sum(expected and predicted for expected, predicted in pairs)
    tn = sum(not expected and not predicted for expected, predicted in pairs)
    fp = sum(not expected and predicted for expected, predicted in pairs)
    fn = sum(expected and not predicted for expected, predicted in pairs)
    precision = safe_ratio(tp, tp + fp)
    recall = safe_ratio(tp, tp + fn)
    f1 = (
        safe_ratio(2 * precision * recall, precision + recall)
        if precision is not None and recall is not None
        else None
    )
    return {
        "sample_count": len(pairs),
        "true_positive": tp,
        "true_negative": tn,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def classification_metrics(
    expected: list[str], predicted: list[str], labels: tuple[str, ...]
) -> dict[str, Any]:
    matrix = {label: {candidate: 0 for candidate in labels} for label in labels}
    for expected_label, predicted_label in zip(expected, predicted, strict=True):
        matrix.setdefault(expected_label, {})
        matrix[expected_label][predicted_label] = (
            matrix[expected_label].get(predicted_label, 0) + 1
        )

    per_label: dict[str, dict[str, float | int | None]] = {}
    for label in labels:
        tp = matrix[label].get(label, 0)
        fp = sum(matrix[other].get(label, 0) for other in labels if other != label)
        fn = sum(matrix[label].get(other, 0) for other in labels if other != label)
        precision = safe_ratio(tp, tp + fp)
        recall = safe_ratio(tp, tp + fn)
        per_label[label] = {
            "support": sum(matrix[label].values()),
            "precision": precision,
            "recall": recall,
            "f1": (
                safe_ratio(2 * precision * recall, precision + recall)
                if precision is not None and recall is not None
                else None
            ),
        }
    return {
        "sample_count": len(expected),
        "accuracy": safe_ratio(
            sum(actual == wanted for actual, wanted in zip(predicted, expected, strict=True)),
            len(expected),
        ),
        "confusion_matrix": matrix,
        "per_intent": per_label,
    }


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; ``None`` for an empty sample."""

    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(fraction * len(ordered)))
    return ordered[rank - 1]


class HeuristicEvaluationClassifier:
    """Offline keyword classifier kept for the classifier-cache workload."""

    def __init__(self) -> None:
        self.calls = 0

    def classify(self, message: str) -> dict[str, object]:
        self.calls += 1
        lowered = message.casefold()
        if any(
            word in lowered
            for word in ("human", "specialist", "agent", "support review")
        ):
            intent = "escalate_to_human"
        elif re.search(
            r"\b(order|delivered|arrive|shipment|where is|refund was)\b|NS-\d{2}-\d{4}-\d",
            lowered,
        ):
            intent = "order_status"
        else:
            intent = "product_question"
        return {"intent": intent, "confidence": 0.90}


class UnavailableClassifier:
    """Stands in for the LLM tier in keyless runs: every call fails."""

    def classify(self, message: str) -> Mapping[str, Any]:
        raise RuntimeError("llm_tier_unavailable_in_offline_evaluation")

    def classify_with_context(self, message: str, context: str) -> Mapping[str, Any]:
        raise RuntimeError("llm_tier_unavailable_in_offline_evaluation")


class CountingClassifier:
    """Count LLM-tier calls made by the router during evaluation."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.calls = 0
        if hasattr(inner, "classify_with_context"):
            self.classify_with_context = self._classify_with_context

    def classify(self, message: str) -> Mapping[str, Any]:
        self.calls += 1
        return self._inner.classify(message)

    def _classify_with_context(self, message: str, context: str) -> Mapping[str, Any]:
        self.calls += 1
        return self._inner.classify_with_context(message, context)


def build_routing_service(
    mode: str, settings: Settings
) -> tuple[SupportService, CountingClassifier]:
    """Build the production hybrid routing stack with a live or unavailable LLM tier.

    Rules and the semantic tier always run; only the LLM tier differs, so the
    offline report shows what the local tiers decide without any provider.
    """

    inner = GroqStructuredClassifier(settings) if mode == "live" else UnavailableClassifier()
    classifier = CountingClassifier(inner)
    router = StructuredIntentRouter(
        classifier,
        model_name=settings.groq_router_model if mode == "live" else "offline-no-llm",
        max_attempts=settings.router_max_attempts,
        retry_delay_seconds=settings.router_retry_delay_seconds if mode == "live" else 0.0,
    )
    service = SupportService(
        router=router,
        registry=HandlerRegistry(),
        semantic_router=build_semantic_router(),
    )
    return service, classifier


def seed_memory(service: SupportService, session_id: str, memory: Mapping[str, Any] | None) -> None:
    service.clear_session(session_id)
    if not memory:
        return
    service.memory_store.append(
        session_id,
        MemoryTurn(
            trace_id="evaluation-seed",
            channel="text",
            user_text="(seeded evaluation turn)",
            assistant_text="(seeded evaluation turn)",
            status="ok",
            intent=memory.get("last_intent"),
            handler_name=None,
        ),
        verified_order_id=memory.get("active_order_id"),
    )


def evaluate_routing(
    cases: list[dict[str, Any]],
    *,
    mode: str = "offline",
    settings: Settings | None = None,
    live_delay_seconds: float = 0.0,
) -> dict[str, Any]:
    active_settings = settings or Settings.from_environment({})
    service, classifier = build_routing_service(mode, active_settings)
    expected: list[str] = []
    predicted: list[str] = []
    case_results = []
    latencies_ms: list[float] = []
    sources: Counter[str] = Counter()
    for index, case in enumerate(cases):
        session_id = case["session_id"]
        seed_memory(service, session_id, case.get("memory"))
        calls_before = classifier.calls
        start = time.perf_counter()
        decision, source = service.preview_route(case["text"], session_id=session_id)
        elapsed_ms = (time.perf_counter() - start) * 1000
        prediction = decision.intent if decision.accepted and decision.intent else REJECTED
        acceptable = set(case.get("acceptable_intents") or [case["expected_intent"]])
        acceptable.add(case["expected_intent"])
        expected.append(case["expected_intent"])
        predicted.append(prediction)
        latencies_ms.append(elapsed_ms)
        sources[source] += 1
        case_results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "expected": case["expected_intent"],
                "acceptable": sorted(acceptable),
                "predicted": prediction,
                "correct": prediction in acceptable,
                "reason": decision.reason,
                "routing_source": source,
                "llm_calls": classifier.calls - calls_before,
                "latency_ms": round(elapsed_ms, 1),
            }
        )
        if mode == "live" and live_delay_seconds and index + 1 < len(cases):
            time.sleep(live_delay_seconds)

    metrics = classification_metrics(expected, predicted, ROUTE_LABELS)
    total = len(case_results)
    non_escalation = [
        item for item in case_results if "escalate_to_human" not in item["acceptable"]
    ]
    by_category: dict[str, dict[str, int]] = {}
    for item in case_results:
        bucket = by_category.setdefault(item["category"], {"total": 0, "correct": 0})
        bucket["total"] += 1
        bucket["correct"] += int(item["correct"])
    llm_latencies = [item["latency_ms"] for item in case_results if item["llm_calls"]]
    stats = service.router.cache_stats
    return {
        "mode": "live_groq_llm_tier" if mode == "live" else "offline_llm_tier_unavailable",
        "llm_model": active_settings.groq_router_model if mode == "live" else None,
        "metrics": metrics,
        "lenient_accuracy": safe_ratio(sum(item["correct"] for item in case_results), total),
        # The pipeline answers an unaccepted route with the "unclear" clarifying
        # reply, so this is the outcome the customer sees.
        "outcome_accuracy": safe_ratio(
            sum(
                item["correct"]
                or (item["predicted"] == REJECTED and "unclear" in item["acceptable"])
                for item in case_results
            ),
            total,
        ),
        "dead_end_rate": safe_ratio(sum(item["predicted"] == REJECTED for item in case_results), total),
        "false_escalation_rate": safe_ratio(
            sum(item["predicted"] == "escalate_to_human" for item in non_escalation),
            len(non_escalation),
        ),
        "order_to_product_misroutes": sum(
            item["expected"] == "order_status" and item["predicted"] == "product_question"
            for item in case_results
        ),
        "routing_sources": dict(sources),
        "llm_calls": classifier.calls,
        "llm_calls_per_case": safe_ratio(classifier.calls, total),
        "classifier_errors": stats.classifier_errors,
        "latency_ms": {
            "p50": percentile(latencies_ms, 0.5),
            "p95": percentile(latencies_ms, 0.95),
            "mean": statistics.fmean(latencies_ms) if latencies_ms else None,
            "llm_routed_p50": percentile(llm_latencies, 0.5),
            "llm_routed_p95": percentile(llm_latencies, 0.95),
        },
        "by_category": by_category,
        "cases": case_results,
    }


def evaluate_cache(cases: list[dict[str, Any]]) -> dict[str, Any]:
    classifier = HeuristicEvaluationClassifier()
    router = StructuredIntentRouter(
        classifier,
        model_name="offline-heuristic-baseline",
        max_attempts=1,
        retry_delay_seconds=0,
    )
    workload = [case["text"] for case in cases[:4] for _ in range(2)]
    for text in workload:
        router.route(SimpleNamespace(text=text))
    stats = router.cache_stats
    return {
        "workload_count": len(workload),
        "classifier_calls": classifier.calls,
        "lookups": stats.lookups,
        "hits": stats.hits,
        "misses": stats.misses,
        "hit_rate": stats.hit_rate,
        "classifier_errors": stats.classifier_errors,
        "entries": stats.entries,
    }


def _ranked_doc_ids(hits: Iterable[RetrievalHit]) -> list[str]:
    doc_ids: list[str] = []
    for hit in hits:
        if hit.chunk.doc_id not in doc_ids:
            doc_ids.append(hit.chunk.doc_id)
    return doc_ids


def _ndcg_at_k(ranked: list[str], expected: set[str], k: int) -> float:
    dcg = sum(
        1 / math.log2(position + 2)
        for position, doc_id in enumerate(ranked[:k])
        if doc_id in expected
    )
    ideal = sum(1 / math.log2(position + 2) for position in range(min(k, len(expected))))
    return dcg / ideal if ideal else 0.0


def evaluate_retrieval_set(
    retriever: Any, cases: list[dict[str, Any]], *, top_k: int = 4
) -> dict[str, Any]:
    """Measure ranking before the evidence gate, the gate, and the end result.

    Ranking metrics use the full ranking, so they show retriever quality even
    when the gate rejects a correct document. Gate metrics show whether the
    sufficient-evidence decision is right. Evidence recall is what the answer
    generator actually receives.
    """

    answerable: list[dict[str, float]] = []
    unanswerable: list[bool] = []
    case_results = []
    for case in cases:
        ranked = _ranked_doc_ids(retriever.rank_all(case["query"]))
        response = retriever.retrieve(case["query"], top_k=top_k)
        accepted_docs = _ranked_doc_ids(response.hits)
        expected = set(case["expected_doc_ids"])
        result: dict[str, Any] = {
            "id": case["id"],
            "case_type": case.get("case_type"),
            "expected_doc_ids": case["expected_doc_ids"],
            "ranked_doc_ids_top5": ranked[:5],
            "accepted_doc_ids": accepted_docs,
            "sufficient_evidence": response.sufficient_evidence,
            "top_score": round(response.hits[0].score, 4) if response.hits else None,
        }
        if expected:
            ranks = [ranked.index(doc_id) + 1 for doc_id in expected if doc_id in ranked]
            first = min(ranks) if ranks else None
            scores = {
                "hit_at_1": float(first == 1),
                "hit_at_3": float(first is not None and first <= 3),
                "recall_at_3": len(expected & set(ranked[:3])) / len(expected),
                "recall_at_5": len(expected & set(ranked[:5])) / len(expected),
                "reciprocal_rank": 1 / first if first else 0.0,
                "ndcg_at_5": _ndcg_at_k(ranked, expected, 5),
                "accepted": float(response.sufficient_evidence),
                "evidence_recall": len(expected & set(accepted_docs)) / len(expected),
            }
            answerable.append(scores)
            result.update({key: round(value, 4) for key, value in scores.items()})
        else:
            unanswerable.append(not response.sufficient_evidence)
            result["correctly_rejected"] = not response.sufficient_evidence
        case_results.append(result)

    def mean_of(key: str) -> float | None:
        return safe_ratio(sum(item[key] for item in answerable), len(answerable))

    acceptance = mean_of("accepted")
    rejection = safe_ratio(sum(unanswerable), len(unanswerable))
    return {
        "answerable_count": len(answerable),
        "unanswerable_count": len(unanswerable),
        "ranking": {
            "hit_at_1": mean_of("hit_at_1"),
            "hit_at_3": mean_of("hit_at_3"),
            "recall_at_3": mean_of("recall_at_3"),
            "recall_at_5": mean_of("recall_at_5"),
            "mrr": mean_of("reciprocal_rank"),
            "ndcg_at_5": mean_of("ndcg_at_5"),
        },
        "gate": {
            "answerable_acceptance_rate": acceptance,
            "unanswerable_rejection_rate": rejection,
            "balanced_accuracy": (
                (acceptance + rejection) / 2
                if acceptance is not None and rejection is not None
                else None
            ),
        },
        "end_to_end": {
            "evidence_recall": mean_of("evidence_recall"),
            "gated_mrr": safe_ratio(
                sum(
                    item["reciprocal_rank"] * item["accepted"] for item in answerable
                ),
                len(answerable),
            ),
        },
        "cases": case_results,
    }


def build_evaluation_retriever() -> Any:
    """Evaluate the same calibrated retriever the live service uses."""

    return build_production_retriever(ROOT / "knowledge_base")


def evaluate_retrieval(
    eval_cases: list[dict[str, Any]], dev_cases: list[dict[str, Any]]
) -> dict[str, Any]:
    retriever = build_evaluation_retriever()
    return {
        "retriever": describe_retriever(retriever),
        "held_out": evaluate_retrieval_set(retriever, eval_cases),
        "dev": evaluate_retrieval_set(retriever, dev_cases),
    }


def describe_retriever(retriever: Any) -> dict[str, Any]:
    describe = getattr(retriever, "describe", None)
    if callable(describe):
        return describe()
    return {
        "type": type(retriever).__name__,
        "embedding_model": retriever.embedder.model_name,
        "vector_dimension": retriever.index.dimension,
        "chunk_count": retriever.index.size,
        "min_similarity": retriever.min_similarity,
    }


def evaluate_rag_live(
    cases: list[dict[str, Any]], settings: Settings, *, delay_seconds: float = 2.0
) -> dict[str, Any]:
    """End-to-end product answers with the live answerer (explicit opt-in).

    Measures the two gates together: the retrieval evidence gate and the
    answerer's insufficient-evidence signal, followed by the output guard.
    """

    from agentic_support.grounded_answers import GroqGroundedAnswerer
    from agentic_support.handlers import ProductQuestionHandler
    from agentic_support.routing import RouteDecision

    handler = ProductQuestionHandler(
        build_evaluation_retriever(), GroqGroundedAnswerer(settings)
    )
    guard = OutputClaimGuard()
    decision = RouteDecision("product_question", 1.0, True, "evaluation")
    results = []
    for index, case in enumerate(cases):
        request = SimpleNamespace(
            text=case["query"], trace_id=f"rag-{case['id']}", session_id="evaluation",
            active_order_id=None, active_product=None,
        )
        start = time.perf_counter()
        try:
            result = handler.handle(request, decision)
            facts = result.metadata.get("allowed_facts", AllowedFacts())
            guard_ok = guard.validate(result.message, facts).allowed
            cited = list(result.metadata.get("cited_chunk_ids") or ())
            outcome = "answered" if cited else "declined"
            reason = result.metadata.get("retrieval_reason")
            text = result.message[:200]
        except Exception as error:  # evaluation boundary
            from agentic_support.routing import describe_provider_error

            fields = describe_provider_error(error)
            outcome, cited, guard_ok, text = "error", [], False, ""
            reason = f"{error}|{fields['cause_type']}|{fields['status_code']}"
        expected = set(case["expected_doc_ids"])
        cited_docs = {chunk_id.split("#", 1)[0] for chunk_id in cited}
        results.append(
            {
                "id": case["id"],
                "answerable": bool(expected),
                "outcome": outcome,
                "decline_reason": reason,
                "cites_expected_doc": bool(expected & cited_docs),
                "output_guard_passed": guard_ok,
                "latency_ms": round((time.perf_counter() - start) * 1000, 1),
                "reply_preview": text,
            }
        )
        if delay_seconds and index + 1 < len(cases):
            time.sleep(delay_seconds)
    answerable = [r for r in results if r["answerable"]]
    unanswerable = [r for r in results if not r["answerable"]]
    return {
        "mode": "live_groq_answerer",
        "model": settings.groq_router_model,
        "answerable_answered_rate": safe_ratio(sum(r["outcome"] == "answered" for r in answerable), len(answerable)),
        "answerable_cites_expected_rate": safe_ratio(sum(r["cites_expected_doc"] for r in answerable), len(answerable)),
        "unanswerable_declined_rate": safe_ratio(sum(r["outcome"] == "declined" for r in unanswerable), len(unanswerable)),
        "declined_by_retrieval_gate": sum(r["decline_reason"] == "best_candidate_below_evidence_gate" for r in results),
        "declined_by_answerer": sum(r["decline_reason"] == "answerer_reported_insufficient_evidence" for r in results),
        "errors": sum(r["outcome"] == "error" for r in results),
        "output_guard_blocks": sum(r["outcome"] == "answered" and not r["output_guard_passed"] for r in results),
        "latency_ms_p50": percentile([r["latency_ms"] for r in results], 0.5),
        "cases": results,
    }


def evaluate_input_guardrail(cases: list[dict[str, Any]]) -> dict[str, Any]:
    guard = InputGuard(RuleBasedSafetyClassifier())
    expected_blocked = []
    predicted_blocked = []
    case_results = []
    for case in cases:
        decision = guard.check(SimpleNamespace(text=case["text"]))
        expected = not case["expected_allowed"]
        predicted = not decision.allowed
        expected_blocked.append(expected)
        predicted_blocked.append(predicted)
        case_results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "expected_blocked": expected,
                "predicted_blocked": predicted,
                "reason": decision.reason,
            }
        )
    return {
        "mode": "offline_rule_based_safety_baseline",
        "positive_label": "blocked",
        "metrics": binary_metrics(expected_blocked, predicted_blocked),
        "cases": case_results,
    }


def evaluate_output_guardrail(cases: list[dict[str, Any]]) -> dict[str, Any]:
    guard = OutputClaimGuard()
    expected_blocked = []
    predicted_blocked = []
    case_results = []
    for case in cases:
        raw_facts = case["allowed_facts"]
        facts = AllowedFacts(
            order_ids=frozenset(raw_facts["order_ids"]),
            dates=frozenset(raw_facts["dates"]),
            amounts=frozenset(raw_facts["amounts"]),
        )
        decision = guard.validate(case["draft"], facts)
        expected = not case["expected_allowed"]
        predicted = not decision.allowed
        expected_blocked.append(expected)
        predicted_blocked.append(predicted)
        case_results.append(
            {
                "id": case["id"],
                "category": case["category"],
                "expected_blocked": expected,
                "predicted_blocked": predicted,
                "reason": decision.reason,
            }
        )
    return {
        "mode": "deterministic_allowed_facts_baseline",
        "positive_label": "blocked",
        "metrics": binary_metrics(expected_blocked, predicted_blocked),
        "cases": case_results,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        f"# Evaluation Report: {report['label']}",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "All values are computed from the labeled cases and real counters in this run.",
        "",
    ]
    routing = report.get("routing")
    if routing:
        latency = routing["latency_ms"]
        lines += [
            "## Routing",
            "",
            f"Mode: `{routing['mode']}`; model: `{routing['llm_model']}`; "
            f"cases: `{routing['metrics']['sample_count']}`.",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Strict accuracy | {_fmt(routing['metrics']['accuracy'])} |",
            f"| Lenient accuracy (acceptable alternatives) | {_fmt(routing['lenient_accuracy'])} |",
            f"| Outcome accuracy (no route answered as unclear) | {_fmt(routing.get('outcome_accuracy'))} |",
            f"| Dead-end rate (no route) | {_fmt(routing['dead_end_rate'])} |",
            f"| False escalation rate | {_fmt(routing['false_escalation_rate'])} |",
            f"| Order requests sent to product search | {routing['order_to_product_misroutes']} |",
            f"| LLM classifier calls | {routing['llm_calls']} ({_fmt(routing['llm_calls_per_case'])} per case) |",
            f"| Classifier errors | {routing['classifier_errors']} |",
            f"| Routing latency p50 / p95 (ms) | {_fmt(latency['p50'])} / {_fmt(latency['p95'])} |",
            f"| LLM-routed latency p50 / p95 (ms) | {_fmt(latency['llm_routed_p50'])} / {_fmt(latency['llm_routed_p95'])} |",
            "",
            f"Routing sources: `{json.dumps(routing['routing_sources'], sort_keys=True)}`",
            "",
            "| Category | Correct / total |",
            "|---|---:|",
        ]
        for category, bucket in sorted(routing["by_category"].items()):
            lines.append(f"| {category} | {bucket['correct']} / {bucket['total']} |")
        lines += ["", "Per-intent precision / recall:", "", "| Intent | Support | Precision | Recall |", "|---|---:|---:|---:|"]
        for intent, values in routing["metrics"]["per_intent"].items():
            lines.append(
                f"| {intent} | {values['support']} | {_fmt(values['precision'])} | {_fmt(values['recall'])} |"
            )
        lines.append("")
    retrieval = report.get("retrieval")
    if retrieval:
        lines += [
            "## Retrieval",
            "",
            f"Retriever: `{json.dumps(retrieval['retriever'], sort_keys=True)}`",
            "",
            "| Metric | Held-out | Dev |",
            "|---|---:|---:|",
        ]
        held, dev = retrieval["held_out"], retrieval["dev"]
        lines.append(
            f"| Cases (answerable / unanswerable) | {held['answerable_count']} / {held['unanswerable_count']} "
            f"| {dev['answerable_count']} / {dev['unanswerable_count']} |"
        )
        for group in ("ranking", "gate", "end_to_end"):
            for key in held[group]:
                lines.append(
                    f"| {group}: {key} | {_fmt(held[group][key])} | {_fmt(dev[group][key])} |"
                )
        lines.append("")
    if "input_guardrail" in report:
        input_metrics = report["input_guardrail"]["metrics"]
        output_metrics = report["output_guardrail"]["metrics"]
        lines += [
            "## Guardrails",
            "",
            "| Guard | Precision | Recall |",
            "|---|---:|---:|",
            f"| Input (offline rule baseline) | {_fmt(input_metrics['precision'])} | {_fmt(input_metrics['recall'])} |",
            f"| Output (allowed-facts guard) | {_fmt(output_metrics['precision'])} | {_fmt(output_metrics['recall'])} |",
            "",
        ]
    rag = report.get("rag")
    if rag:
        lines += [
            "## End-to-end product answers (live)",
            "",
            f"Mode: `{rag['mode']}`; model: `{rag['model']}`.",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Answerable questions answered | {_fmt(rag['answerable_answered_rate'])} |",
            f"| Answerable answers citing an expected document | {_fmt(rag['answerable_cites_expected_rate'])} |",
            f"| Unanswerable questions declined | {_fmt(rag['unanswerable_declined_rate'])} |",
            f"| Declined by retrieval gate / by answerer | {rag['declined_by_retrieval_gate']} / {rag['declined_by_answerer']} |",
            f"| Handler errors | {rag['errors']} |",
            f"| Answers blocked by output guard | {rag['output_guard_blocks']} |",
            f"| Latency p50 (ms) | {_fmt(rag['latency_ms_p50'])} |",
            "",
        ]
    cache = report.get("classifier_cache")
    if cache:
        lines += [
            "## Classifier cache",
            "",
            f"Workload: `{cache['workload_count']}`; classifier calls: `{cache['classifier_calls']}`; "
            f"hits: `{cache['hits']}`; misses: `{cache['misses']}`; hit rate: `{_fmt(cache['hit_rate'])}`.",
            "",
        ]
    lines += [
        "## Limitations",
        "",
        "- Offline routing replaces the LLM tier with an unavailable provider; it measures only the deterministic layers.",
        "- Live routing numbers depend on Groq model behavior, load, and rate limits at run time.",
        "- The evaluation sets were written by the project author and are small; treat differences of one or two cases as noise.",
    ]
    return "\n".join(lines) + "\n"


def run(
    output_dir: Path,
    *,
    label: str = "latest",
    sections: tuple[str, ...] = SECTIONS,
    routing_mode: str = "offline",
    live_delay_seconds: float = 2.0,
) -> dict[str, Any]:
    evals = ROOT / "evals"
    report: dict[str, Any] = {
        "schema_version": "evaluation-v2",
        "label": label,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
    }
    if "routing" in sections:
        settings = Settings.from_environment() if routing_mode == "live" else None
        report["routing"] = evaluate_routing(
            load_jsonl(evals / "routing_eval.jsonl"),
            mode=routing_mode,
            settings=settings,
            live_delay_seconds=live_delay_seconds,
        )
    if "retrieval" in sections:
        dev_cases = load_jsonl(evals / "retrieval_seed.jsonl") + load_jsonl(
            evals / "retrieval_dev.jsonl"
        )
        report["retrieval"] = evaluate_retrieval(
            load_jsonl(evals / "retrieval_eval.jsonl"), dev_cases
        )
    if "guardrails" in sections:
        report["input_guardrail"] = evaluate_input_guardrail(
            load_jsonl(evals / "input_guardrail_eval.jsonl")
        )
        report["output_guardrail"] = evaluate_output_guardrail(
            load_jsonl(evals / "output_guardrail_eval.jsonl")
        )
    if "rag" in sections:
        report["rag"] = evaluate_rag_live(
            load_jsonl(evals / "retrieval_eval.jsonl"),
            Settings.from_environment(),
            delay_seconds=live_delay_seconds,
        )
    if "cache" in sections:
        report["classifier_cache"] = evaluate_cache(load_jsonl(evals / "routing_seed.jsonl"))

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{label}-evaluation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / f"{label}-evaluation.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    return report


def summarize(report: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"label": report["label"]}
    if "routing" in report:
        summary["routing_accuracy"] = report["routing"]["metrics"]["accuracy"]
        summary["routing_lenient_accuracy"] = report["routing"]["lenient_accuracy"]
        summary["routing_outcome_accuracy"] = report["routing"]["outcome_accuracy"]
        summary["routing_dead_end_rate"] = report["routing"]["dead_end_rate"]
        summary["routing_llm_calls"] = report["routing"]["llm_calls"]
    if "retrieval" in report:
        held = report["retrieval"]["held_out"]
        summary["retrieval_mrr"] = held["ranking"]["mrr"]
        summary["retrieval_gate_balanced_accuracy"] = held["gate"]["balanced_accuracy"]
        summary["retrieval_evidence_recall"] = held["end_to_end"]["evidence_recall"]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--label", default="latest")
    parser.add_argument(
        "--sections",
        default=",".join(SECTIONS),
        help="comma-separated subset of: " + ", ".join(SECTIONS + LIVE_ONLY_SECTIONS)
        + " (rag calls Groq and is never run by default)",
    )
    parser.add_argument("--routing-mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--live-delay", type=float, default=2.0)
    args = parser.parse_args()
    sections = tuple(item.strip() for item in args.sections.split(",") if item.strip())
    unknown = set(sections) - set(SECTIONS) - set(LIVE_ONLY_SECTIONS)
    if unknown:
        parser.error(f"unknown sections: {sorted(unknown)}")
    report = run(
        args.output_dir,
        label=args.label,
        sections=sections,
        routing_mode=args.routing_mode,
        live_delay_seconds=args.live_delay,
    )
    print(json.dumps(summarize(report), sort_keys=True))


if __name__ == "__main__":
    main()

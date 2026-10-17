"""Run the Step 6 offline baseline evaluation and save JSON/Markdown reports."""

from __future__ import annotations

import argparse
import json
import platform
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

from agentic_support.facts import AllowedFacts, OutputClaimGuard
from agentic_support.guardrails import InputGuard, RuleBasedSafetyClassifier
from agentic_support.retrieval import GroundedRetriever
from agentic_support.routing import StructuredIntentRouter


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPORT_DIR = ROOT / "reports"
INTENTS = ("product_question", "order_status", "escalate_to_human")


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


class HeuristicEvaluationClassifier:
    """Offline deterministic baseline used instead of a live LLM call."""

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


def evaluate_routing(cases: list[dict[str, Any]]) -> dict[str, Any]:
    classifier = HeuristicEvaluationClassifier()
    router = StructuredIntentRouter(
        classifier,
        model_name="offline-heuristic-baseline",
        max_attempts=1,
        retry_delay_seconds=0,
    )
    expected: list[str] = []
    predicted: list[str] = []
    case_results = []
    for case in cases:
        decision = router.route(SimpleNamespace(text=case["text"]))
        prediction = decision.intent if decision.accepted and decision.intent else "rejected"
        expected.append(case["expected_intent"])
        predicted.append(prediction)
        case_results.append(
            {"id": case["id"], "expected": case["expected_intent"], "predicted": prediction}
        )
    return {
        "mode": "offline_heuristic_baseline",
        "metrics": classification_metrics(expected, predicted, INTENTS),
        "classifier_calls": classifier.calls,
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


def evaluate_retrieval(cases: list[dict[str, Any]]) -> dict[str, Any]:
    retriever = GroundedRetriever.from_directory(ROOT / "knowledge_base")
    answerable = []
    unanswerable = []
    case_results = []
    for case in cases:
        response = retriever.retrieve(case["query"], top_k=5)
        retrieved_ids = []
        for hit in response.hits:
            if hit.chunk.doc_id not in retrieved_ids:
                retrieved_ids.append(hit.chunk.doc_id)
        expected_ids = set(case["expected_doc_ids"])
        if expected_ids:
            ranks = [index + 1 for index, doc_id in enumerate(retrieved_ids) if doc_id in expected_ids]
            answerable.append(
                {
                    "recall_at_5": bool(ranks),
                    "reciprocal_rank": 1 / min(ranks) if ranks else 0.0,
                }
            )
        else:
            unanswerable.append(not response.sufficient_evidence)
        case_results.append(
            {
                "id": case["id"],
                "expected_doc_ids": case["expected_doc_ids"],
                "retrieved_doc_ids": retrieved_ids,
                "sufficient_evidence": response.sufficient_evidence,
                "reason": response.reason,
                "top_score": response.hits[0].score if response.hits else None,
            }
        )
    return {
        "mode": "local_sentence_transformer_and_exact_numpy_index",
        "embedding_model": retriever.embedder.model_name,
        "vector_dimension": retriever.index.dimension,
        "top_k": 5,
        "answerable_count": len(answerable),
        "recall_at_5": safe_ratio(
            sum(item["recall_at_5"] for item in answerable), len(answerable)
        ),
        "mrr": safe_ratio(
            sum(item["reciprocal_rank"] for item in answerable), len(answerable)
        ),
        "unanswerable_count": len(unanswerable),
        "unanswerable_rejection_rate": safe_ratio(
            sum(unanswerable), len(unanswerable)
        ),
        "cases": case_results,
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


def render_markdown(report: dict[str, Any]) -> str:
    routing = report["routing"]["metrics"]
    retrieval = report["retrieval"]
    input_metrics = report["input_guardrail"]["metrics"]
    output_metrics = report["output_guardrail"]["metrics"]
    cache = report["classifier_cache"]
    lines = [
        "# Baseline Evaluation Report",
        "",
        f"Generated: `{report['generated_at']}`",
        "",
        "All metrics below are from the labeled seed cases and actual local counters.",
        "",
        "## Summary",
        "",
        "| Area | Metric | Value |",
        "|---|---|---:|",
        f"| Routing | accuracy | {routing['accuracy']} |",
        f"| Retrieval | recall@5 | {retrieval['recall_at_5']} |",
        f"| Retrieval | MRR | {retrieval['mrr']} |",
        f"| Retrieval | unanswerable rejection rate | {retrieval['unanswerable_rejection_rate']} |",
        f"| Input guardrail | recall | {input_metrics['recall']} |",
        f"| Output guardrail | recall | {output_metrics['recall']} |",
        f"| Cache | hit rate | {cache['hit_rate']} |",
        "",
        "## Routing",
        "",
        f"Mode: `{report['routing']['mode']}`; samples: `{routing['sample_count']}`.",
        "",
        "```json",
        json.dumps(routing["confusion_matrix"], indent=2),
        "```",
        "",
        "## Retrieval",
        "",
        f"Model: `{retrieval['embedding_model']}`; vector dimension: `{retrieval['vector_dimension']}`.",
        "",
        "## Guardrails",
        "",
        f"Input mode: `{report['input_guardrail']['mode']}`.",
        f"Output mode: `{report['output_guardrail']['mode']}`.",
        "",
        "## Cache",
        "",
        f"Workload: `{cache['workload_count']}`; classifier calls: `{cache['classifier_calls']}`; "
        f"lookups: `{cache['lookups']}`; hits: `{cache['hits']}`; misses: `{cache['misses']}`.",
        "",
        "## Limitations",
        "",
        "- Routing and input guardrail baselines are deterministic offline baselines, not live LLM measurements.",
        "- Retrieval uses the real local embedding model and corpus.",
        "- These reports are baseline evidence, not production SLO claims.",
    ]
    return "\n".join(lines) + "\n"


def run(output_dir: Path) -> dict[str, Any]:
    routing_cases = load_jsonl(ROOT / "evals" / "routing_seed.jsonl")
    retrieval_cases = load_jsonl(ROOT / "evals" / "retrieval_seed.jsonl")
    input_cases = load_jsonl(ROOT / "evals" / "input_guardrail_eval.jsonl")
    output_cases = load_jsonl(ROOT / "evals" / "output_guardrail_eval.jsonl")
    report = {
        "schema_version": "step6-baseline-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "routing": evaluate_routing(routing_cases),
        "retrieval": evaluate_retrieval(retrieval_cases),
        "input_guardrail": evaluate_input_guardrail(input_cases),
        "output_guardrail": evaluate_output_guardrail(output_cases),
        "classifier_cache": evaluate_cache(routing_cases),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "baseline-evaluation.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "baseline-evaluation.md").write_text(
        render_markdown(report), encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
    )
    args = parser.parse_args()
    report = run(args.output_dir)
    print(
        json.dumps(
            {
                "report_dir": str(args.output_dir),
                "routing_accuracy": report["routing"]["metrics"]["accuracy"],
                "retrieval_recall_at_5": report["retrieval"]["recall_at_5"],
                "input_guardrail_recall": report["input_guardrail"]["metrics"]["recall"],
                "output_guardrail_recall": report["output_guardrail"]["metrics"]["recall"],
                "cache_hit_rate": report["classifier_cache"]["hit_rate"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()

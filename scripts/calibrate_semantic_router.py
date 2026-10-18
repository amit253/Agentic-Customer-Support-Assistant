"""Calibrate the semantic routing thresholds with leave-one-out over examples.

Each example message is classified against all the *other* examples. For
every (min_score, min_margin) pair we measure coverage (share answered by the
semantic tier) and precision (share of those answers that are right), then
pick the pair with the highest coverage whose precision meets the target.
Only the training examples are used; the held-out routing evaluation set is
never read here.

    python scripts/calibrate_semantic_router.py --target-precision 0.97
"""

from __future__ import annotations

import argparse
import json

import numpy as np

from agentic_support.retrieval import DEFAULT_EMBEDDING_MODEL, SentenceTransformerEmbedder
from agentic_support.route_exemplars import ROUTE_EXEMPLARS
from agentic_support.semantic_routing import NEIGHBOURS_PER_INTENT, normalize_for_routing


def leave_one_out(
    embedder: SentenceTransformerEmbedder, prefix: str = ""
) -> list[tuple[str, str, float, float]]:
    labels: list[str] = []
    texts: list[str] = []
    for intent, examples in ROUTE_EXEMPLARS.items():
        for example in examples:
            labels.append(intent)
            texts.append(prefix + normalize_for_routing(example))
    vectors = np.asarray(embedder.encode(texts), dtype=np.float32)
    label_array = np.asarray(labels)
    intents = list(ROUTE_EXEMPLARS)
    results = []
    for index in range(len(texts)):
        similarities = vectors @ vectors[index]
        mask = np.ones(len(texts), dtype=bool)
        mask[index] = False
        scores = []
        for intent in intents:
            values = np.sort(similarities[mask & (label_array == intent)])[::-1]
            scores.append((float(values[:NEIGHBOURS_PER_INTENT].mean()), intent))
        scores.sort(reverse=True)
        (best, predicted), (second, _) = scores[0], scores[1]
        results.append((labels[index], predicted, best, best - second))
    return results


def sweep(results, target_precision: float) -> dict[str, object]:
    best_choice = None
    grid = []
    for min_score in np.arange(0.30, 0.96, 0.01):
        for min_margin in np.arange(0.0, 0.21, 0.005):
            answered = [r for r in results if r[2] >= min_score and r[3] >= min_margin]
            if not answered:
                continue
            precision = sum(r[0] == r[1] for r in answered) / len(answered)
            coverage = len(answered) / len(results)
            row = {
                "min_score": round(float(min_score), 2),
                "min_margin": round(float(min_margin), 2),
                "coverage": round(coverage, 4),
                "precision": round(precision, 4),
            }
            grid.append(row)
            if precision >= target_precision and (
                best_choice is None
                or coverage > best_choice["coverage"]
                or (coverage == best_choice["coverage"] and min_score > best_choice["min_score"])
            ):
                best_choice = row
    return {"chosen": best_choice, "grid_size": len(grid)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-precision", type=float, default=0.97)
    parser.add_argument("--model", default=DEFAULT_EMBEDDING_MODEL)
    parser.add_argument("--prefix", default="", help='e.g. "query: " for e5 models')
    args = parser.parse_args()
    embedder = SentenceTransformerEmbedder(args.model)
    results = leave_one_out(embedder, args.prefix)
    raw_accuracy = sum(r[0] == r[1] for r in results) / len(results)
    summary = sweep(results, args.target_precision)
    print(
        json.dumps(
            {
                "model": args.model,
                "prefix": args.prefix,
                "examples": len(results),
                "leave_one_out_accuracy_without_thresholds": round(raw_accuracy, 4),
                "target_precision": args.target_precision,
                **summary,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

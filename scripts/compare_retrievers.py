"""Compare retrieval configurations with dev-set calibration and held-out scoring.

For each configuration the evidence thresholds are chosen on the dev set
(``retrieval_seed.jsonl`` + ``retrieval_dev.jsonl``) to maximize the gate's
balanced accuracy, with evidence recall as the tie-breaker. The chosen
thresholds are then applied unchanged to the held-out set
(``retrieval_eval.jsonl``). Results are written to
``reports/retrieval-comparison.{json,md}``.

    python scripts/compare_retrievers.py
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from agentic_support.hybrid_retrieval import HybridConfig, HybridRetriever
from agentic_support.retrieval import GroundedRetriever

try:  # run as a script from the repository root
    from run_evaluation import evaluate_retrieval_set, load_jsonl
except ImportError:  # pragma: no cover - imported as scripts.compare_retrievers
    from scripts.run_evaluation import evaluate_retrieval_set, load_jsonl


ROOT = Path(__file__).resolve().parents[1]
KB = ROOT / "knowledge_base"
MINILM = "sentence-transformers/all-MiniLM-L6-v2"
BGE_SMALL = "BAAI/bge-small-en-v1.5"
E5_SMALL = "intfloat/multilingual-e5-small"
MS_MARCO = "cross-encoder/ms-marco-MiniLM-L-6-v2"
MMARCO = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
BGE_QUERY = "Represent this sentence for searching relevant passages: "

CONFIGS: dict[str, dict[str, Any]] = {
    "A_current_minilm_chunk_threshold": {"kind": "grounded", "calibrate": False},
    "B_minilm_recalibrated_threshold": {"kind": "grounded", "calibrate": True},
    "C_minilm_dense_top1_gate": {"kind": "hybrid", "model": MINILM, "bm25": False},
    "D_minilm_bm25_rrf": {"kind": "hybrid", "model": MINILM, "bm25": True},
    "E_minilm_bm25_msmarco_rerank": {"kind": "hybrid", "model": MINILM, "bm25": True, "reranker": MS_MARCO},
    "F_bge_small_bm25_msmarco_rerank": {
        "kind": "hybrid", "model": BGE_SMALL, "bm25": True, "reranker": MS_MARCO, "query_prefix": BGE_QUERY,
    },
    "G_e5_small_bm25_msmarco_rerank": {
        "kind": "hybrid", "model": E5_SMALL, "bm25": True, "reranker": MS_MARCO,
        "query_prefix": "query: ", "passage_prefix": "passage: ",
    },
    "H_e5_small_bm25_rrf": {
        "kind": "hybrid", "model": E5_SMALL, "bm25": True,
        "query_prefix": "query: ", "passage_prefix": "passage: ",
    },
    "I_minilm_bm25_mmarco_multilingual_rerank": {"kind": "hybrid", "model": MINILM, "bm25": True, "reranker": MMARCO},
}


def _doc_ids(hits) -> list[str]:
    seen: list[str] = []
    for hit in hits:
        if hit.chunk.doc_id not in seen:
            seen.append(hit.chunk.doc_id)
    return seen


def _simulate(rankings, cases, gate: float, support: float, top_k: int = 4) -> tuple[float, float]:
    """Balanced accuracy and evidence recall for one threshold pair."""

    accepted_answerable, rejected_unanswerable, recall = [], [], []
    for ranked, case in zip(rankings, cases):
        expected = set(case["expected_doc_ids"])
        passes = bool(ranked) and ranked[0].score >= gate
        docs = set(_doc_ids([hit for hit in ranked[:top_k] if hit.score >= support])) if passes else set()
        if expected:
            accepted_answerable.append(passes)
            recall.append(len(expected & docs) / len(expected))
        else:
            rejected_unanswerable.append(not passes)
    balanced = (np.mean(accepted_answerable) + np.mean(rejected_unanswerable)) / 2
    return float(balanced), float(np.mean(recall))


def _simulate_chunk_threshold(rankings, cases, threshold: float) -> tuple[float, float]:
    """Same metrics for the original per-chunk threshold design."""

    accepted_answerable, rejected_unanswerable, recall = [], [], []
    for ranked, case in zip(rankings, cases):
        expected = set(case["expected_doc_ids"])
        kept = [hit for hit in ranked[:4] if hit.score >= threshold]
        docs = set(_doc_ids(kept))
        if expected:
            accepted_answerable.append(bool(kept))
            recall.append(len(expected & docs) / len(expected))
        else:
            rejected_unanswerable.append(not kept)
    balanced = (np.mean(accepted_answerable) + np.mean(rejected_unanswerable)) / 2
    return float(balanced), float(np.mean(recall))


def calibrate(retriever, dev_cases, *, per_chunk: bool) -> dict[str, float]:
    rankings = [retriever.rank_all(case["query"]) for case in dev_cases]
    top_scores = sorted({round(r[0].score, 4) for r in rankings if r})
    candidates = sorted({*top_scores, *[round(x, 3) for x in np.linspace(min(top_scores), max(top_scores), 40)]})
    best: tuple[float, float, float, float] | None = None
    for gate in candidates:
        supports = [gate] if per_chunk else sorted({0.0, *[round(gate * f, 4) for f in (0.1, 0.25, 0.5, 0.75, 1.0)]})
        for support in supports:
            if per_chunk:
                balanced, recall = _simulate_chunk_threshold(rankings, dev_cases, gate)
            else:
                balanced, recall = _simulate(rankings, dev_cases, gate, support)
            key = (balanced, recall, support, gate)
            if best is None or key > best:
                best = key
    assert best is not None
    return {"gate": best[3], "support": best[2], "dev_balanced_accuracy": best[0], "dev_evidence_recall": best[1]}


def build(name: str, spec: dict[str, Any]):
    if spec["kind"] == "grounded":
        return GroundedRetriever.from_directory(KB)
    config = HybridConfig(
        use_bm25=spec["bm25"],
        query_prefix=spec.get("query_prefix", ""),
        passage_prefix=spec.get("passage_prefix", ""),
    )
    return HybridRetriever.from_directory(
        KB, embedding_model=spec["model"], config=config, reranker_model=spec.get("reranker")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", help="configuration names to run")
    args = parser.parse_args()
    held_out = load_jsonl(ROOT / "evals" / "retrieval_eval.jsonl")
    dev = load_jsonl(ROOT / "evals" / "retrieval_seed.jsonl") + load_jsonl(ROOT / "evals" / "retrieval_dev.jsonl")
    results: dict[str, Any] = {}
    for name, spec in CONFIGS.items():
        if args.only and name not in args.only:
            continue
        retriever = build(name, spec)
        thresholds = None
        if spec["kind"] == "grounded":
            if spec["calibrate"]:
                thresholds = calibrate(retriever, dev, per_chunk=True)
                retriever.min_similarity = thresholds["gate"]
        else:
            thresholds = calibrate(retriever, dev, per_chunk=False)
            retriever.config = dataclasses.replace(
                retriever.config, gate_threshold=thresholds["gate"], support_threshold=thresholds["support"]
            )
        start = time.perf_counter()
        report = evaluate_retrieval_set(retriever, held_out)
        elapsed = (time.perf_counter() - start) * 1000 / len(held_out)
        results[name] = {
            "thresholds_from_dev": thresholds,
            "ranking": report["ranking"],
            "gate": report["gate"],
            "end_to_end": report["end_to_end"],
            "ms_per_query_eval_loop": round(elapsed, 1),
            "hinglish_cases": [
                {k: c[k] for k in ("id", "ranked_doc_ids_top5", "sufficient_evidence")}
                for c in report["cases"] if c["case_type"] == "hinglish"
            ],
        }
        print(name, json.dumps({k: results[name][k] for k in ("thresholds_from_dev", "ranking", "gate", "end_to_end")}))

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "held_out_cases": len(held_out),
        "dev_cases": len(dev),
        "results": results,
    }
    out_dir = ROOT / "reports"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "retrieval-comparison.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# Retrieval Comparison",
        "",
        f"Generated: `{output['generated_at']}`. Thresholds tuned on {len(dev)} dev cases; "
        f"metrics below are on {len(held_out)} held-out cases.",
        "",
        "| Config | MRR | hit@1 | recall@3 | Accept answerable | Reject unanswerable | Balanced | Evidence recall | ms/query |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in results.items():
        lines.append(
            f"| {name} | {row['ranking']['mrr']:.3f} | {row['ranking']['hit_at_1']:.3f} | "
            f"{row['ranking']['recall_at_3']:.3f} | {row['gate']['answerable_acceptance_rate']:.3f} | "
            f"{row['gate']['unanswerable_rejection_rate']:.3f} | {row['gate']['balanced_accuracy']:.3f} | "
            f"{row['end_to_end']['evidence_recall']:.3f} | {row['ms_per_query_eval_loop']} |"
        )
    (out_dir / "retrieval-comparison.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

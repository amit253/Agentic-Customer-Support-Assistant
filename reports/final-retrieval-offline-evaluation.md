# Evaluation Report: final-retrieval-offline

Generated: `2026-10-18T11:26:26.295503+00:00`

All values are computed from the labeled cases and real counters in this run.

## Retrieval

Retriever: `{"bm25": true, "chunk_count": 12, "embedding_model": "intfloat/multilingual-e5-small", "gate_threshold": 0.8106, "reranker_model": null, "support_threshold": 0.6233, "type": "HybridRetriever"}`

| Metric | Held-out | Dev |
|---|---:|---:|
| Cases (answerable / unanswerable) | 32 / 13 | 25 / 8 |
| ranking: hit_at_1 | 0.844 | 0.680 |
| ranking: hit_at_3 | 0.969 | 1.000 |
| ranking: recall_at_3 | 0.953 | 1.000 |
| ranking: recall_at_5 | 0.984 | 1.000 |
| ranking: mrr | 0.912 | 0.840 |
| ranking: ndcg_at_5 | 0.923 | 0.884 |
| gate: answerable_acceptance_rate | 0.969 | 1.000 |
| gate: unanswerable_rejection_rate | 0.615 | 0.500 |
| gate: balanced_accuracy | 0.792 | 0.750 |
| end_to_end: evidence_recall | 0.922 | 1.000 |
| end_to_end: gated_mrr | 0.897 | 0.840 |

## Limitations

- Offline routing replaces the LLM tier with an unavailable provider; it measures only the deterministic layers.
- Live routing numbers depend on Groq model behavior, load, and rate limits at run time.
- The evaluation sets were written by the project author and are small; treat differences of one or two cases as noise.

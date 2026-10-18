# Evaluation Report: phase0-baseline-offline

Generated: `2026-10-18T10:16:36.208172+00:00`

All values are computed from the labeled cases and real counters in this run.

## Routing

Mode: `offline_llm_tier_unavailable`; model: `None`; cases: `110`.

| Metric | Value |
|---|---:|
| Strict accuracy | 0.091 |
| Lenient accuracy (acceptable alternatives) | 0.100 |
| Dead-end rate (no route) | 0.900 |
| False escalation rate | 0.000 |
| Order requests sent to product search | 0 |
| LLM classifier calls | 198 (1.800 per case) |
| Classifier errors | 198 |
| Routing latency p50 / p95 (ms) | 0.030 / 0.048 |
| LLM-routed latency p50 / p95 (ms) | 0.000 / 0.000 |

Routing sources: `{"classifier": 99, "deterministic_order_signal": 9, "verified_session_memory": 2}`

| Category | Correct / total |
|---|---:|
| acknowledgement | 0 / 2 |
| capabilities | 0 / 2 |
| complaint | 0 / 1 |
| damaged_package | 0 / 1 |
| defect_review | 0 / 1 |
| explicit_human | 0 / 6 |
| filler | 0 / 1 |
| frustrated | 0 / 1 |
| gibberish | 0 / 6 |
| goodbye | 0 / 3 |
| greeting | 0 / 6 |
| greeting_plus_request | 1 / 3 |
| human_hinglish | 0 / 1 |
| human_with_order_id | 1 / 1 |
| identity | 0 / 2 |
| lost_package | 0 / 1 |
| negation_trap | 1 / 2 |
| order_follow_up | 2 / 6 |
| order_hinglish | 0 / 2 |
| order_typo | 0 / 1 |
| order_with_id | 6 / 10 |
| order_without_id | 0 / 3 |
| out_of_scope | 0 / 14 |
| ownership_issue | 0 / 1 |
| policy | 0 / 6 |
| policy_troubleshooting | 0 / 1 |
| policy_typo | 0 / 1 |
| policy_with_order_id | 0 / 1 |
| product_care | 0 / 2 |
| product_comparison | 0 / 1 |
| product_feature | 0 / 5 |
| product_hinglish | 0 / 1 |
| product_unanswerable | 0 / 2 |
| product_with_order_id | 0 / 1 |
| punctuation_only | 0 / 3 |
| safety_concern | 0 / 1 |
| thanks | 0 / 3 |
| vague_fragment | 0 / 4 |
| wellbeing | 0 / 1 |

Per-intent precision / recall:

| Intent | Support | Precision | Recall |
|---|---:|---:|---:|
| product_question | 24 | n/a | n/a |
| order_status | 24 | 0.909 | 1.000 |
| escalate_to_human | 15 | n/a | 0.000 |
| smalltalk | 19 | n/a | n/a |
| out_of_scope | 14 | n/a | n/a |
| unclear | 14 | n/a | n/a |

## Retrieval

Retriever: `{"chunk_count": 12, "embedding_model": "sentence-transformers/all-MiniLM-L6-v2", "min_similarity": 0.45, "type": "GroundedRetriever", "vector_dimension": 384}`

| Metric | Held-out | Dev |
|---|---:|---:|
| Cases (answerable / unanswerable) | 32 / 13 | 25 / 8 |
| ranking: hit_at_1 | 0.781 | 0.840 |
| ranking: hit_at_3 | 0.906 | 0.960 |
| ranking: recall_at_3 | 0.906 | 0.920 |
| ranking: recall_at_5 | 0.969 | 0.980 |
| ranking: mrr | 0.857 | 0.910 |
| ranking: ndcg_at_5 | 0.879 | 0.914 |
| gate: answerable_acceptance_rate | 0.594 | 0.720 |
| gate: unanswerable_rejection_rate | 0.692 | 0.875 |
| gate: balanced_accuracy | 0.643 | 0.797 |
| end_to_end: evidence_recall | 0.516 | 0.620 |
| end_to_end: gated_mrr | 0.562 | 0.700 |

## Guardrails

| Guard | Precision | Recall |
|---|---:|---:|
| Input (offline rule baseline) | 0.800 | 0.667 |
| Output (allowed-facts guard) | 1.000 | 1.000 |

## Classifier cache

Workload: `8`; classifier calls: `4`; hits: `4`; misses: `4`; hit rate: `0.500`.

## Limitations

- Offline routing replaces the LLM tier with an unavailable provider; it measures only the deterministic layers.
- Live routing numbers depend on Groq model behavior, load, and rate limits at run time.
- The evaluation sets were written by the project author and are small; treat differences of one or two cases as noise.

# Evaluation Report: phase1-llm-only-live

Generated: `2026-10-18T10:39:45.944367+00:00`

All values are computed from the labeled cases and real counters in this run.

## Routing

Mode: `live_groq_llm_tier`; model: `openai/gpt-oss-20b`; cases: `110`.

| Metric | Value |
|---|---:|
| Strict accuracy | 0.909 |
| Lenient accuracy (acceptable alternatives) | 0.945 |
| Dead-end rate (no route) | 0.045 |
| False escalation rate | 0.000 |
| Order requests sent to product search | 0 |
| LLM classifier calls | 99 (0.900 per case) |
| Classifier errors | 1 |
| Routing latency p50 / p95 (ms) | 576.906 / 885.109 |
| LLM-routed latency p50 / p95 (ms) | 584.600 / 919.200 |

Routing sources: `{"classifier": 99, "deterministic_order_signal": 9, "verified_session_memory": 2}`

| Category | Correct / total |
|---|---:|
| acknowledgement | 2 / 2 |
| capabilities | 2 / 2 |
| complaint | 1 / 1 |
| damaged_package | 1 / 1 |
| defect_review | 1 / 1 |
| explicit_human | 6 / 6 |
| filler | 1 / 1 |
| frustrated | 1 / 1 |
| gibberish | 4 / 6 |
| goodbye | 3 / 3 |
| greeting | 5 / 6 |
| greeting_plus_request | 3 / 3 |
| human_hinglish | 1 / 1 |
| human_with_order_id | 1 / 1 |
| identity | 2 / 2 |
| lost_package | 1 / 1 |
| negation_trap | 2 / 2 |
| order_follow_up | 6 / 6 |
| order_hinglish | 2 / 2 |
| order_typo | 1 / 1 |
| order_with_id | 10 / 10 |
| order_without_id | 3 / 3 |
| out_of_scope | 14 / 14 |
| ownership_issue | 1 / 1 |
| policy | 6 / 6 |
| policy_troubleshooting | 1 / 1 |
| policy_typo | 1 / 1 |
| policy_with_order_id | 1 / 1 |
| product_care | 2 / 2 |
| product_comparison | 1 / 1 |
| product_feature | 5 / 5 |
| product_hinglish | 1 / 1 |
| product_unanswerable | 2 / 2 |
| product_with_order_id | 1 / 1 |
| punctuation_only | 2 / 3 |
| safety_concern | 1 / 1 |
| thanks | 3 / 3 |
| vague_fragment | 2 / 4 |
| wellbeing | 1 / 1 |

Per-intent precision / recall:

| Intent | Support | Precision | Recall |
|---|---:|---:|---:|
| product_question | 24 | 1.000 | 0.917 |
| order_status | 24 | 0.923 | 1.000 |
| escalate_to_human | 15 | 0.933 | 0.933 |
| smalltalk | 19 | 1.000 | 0.944 |
| out_of_scope | 14 | 0.933 | 1.000 |
| unclear | 14 | 0.900 | 0.900 |

## Limitations

- Offline routing replaces the LLM tier with an unavailable provider; it measures only the deterministic layers.
- Live routing numbers depend on Groq model behavior, load, and rate limits at run time.
- The evaluation sets were written by the project author and are small; treat differences of one or two cases as noise.

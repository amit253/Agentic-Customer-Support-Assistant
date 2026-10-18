# Evaluation Report: phase0-baseline-live

Generated: `2026-10-18T10:17:34.851336+00:00`

All values are computed from the labeled cases and real counters in this run.

## Routing

Mode: `live_groq_llm_tier`; model: `openai/gpt-oss-20b`; cases: `110`.

| Metric | Value |
|---|---:|
| Strict accuracy | 0.509 |
| Lenient accuracy (acceptable alternatives) | 0.527 |
| Dead-end rate (no route) | 0.355 |
| False escalation rate | 0.117 |
| Order requests sent to product search | 0 |
| LLM classifier calls | 141 (1.282 per case) |
| Classifier errors | 62 |
| Routing latency p50 / p95 (ms) | 972.924 / 16368.514 |
| LLM-routed latency p50 / p95 (ms) | 1448.100 / 16418.200 |

Routing sources: `{"classifier": 99, "deterministic_order_signal": 9, "verified_session_memory": 2}`

| Category | Correct / total |
|---|---:|
| acknowledgement | 0 / 2 |
| capabilities | 0 / 2 |
| complaint | 1 / 1 |
| damaged_package | 1 / 1 |
| defect_review | 1 / 1 |
| explicit_human | 6 / 6 |
| filler | 0 / 1 |
| frustrated | 1 / 1 |
| gibberish | 0 / 6 |
| goodbye | 0 / 3 |
| greeting | 0 / 6 |
| greeting_plus_request | 3 / 3 |
| human_hinglish | 1 / 1 |
| human_with_order_id | 1 / 1 |
| identity | 0 / 2 |
| lost_package | 1 / 1 |
| negation_trap | 2 / 2 |
| order_follow_up | 5 / 6 |
| order_hinglish | 1 / 2 |
| order_typo | 1 / 1 |
| order_with_id | 10 / 10 |
| order_without_id | 1 / 3 |
| out_of_scope | 0 / 14 |
| ownership_issue | 1 / 1 |
| policy | 6 / 6 |
| policy_troubleshooting | 0 / 1 |
| policy_typo | 1 / 1 |
| policy_with_order_id | 1 / 1 |
| product_care | 2 / 2 |
| product_comparison | 1 / 1 |
| product_feature | 5 / 5 |
| product_hinglish | 1 / 1 |
| product_unanswerable | 2 / 2 |
| product_with_order_id | 1 / 1 |
| punctuation_only | 0 / 3 |
| safety_concern | 1 / 1 |
| thanks | 0 / 3 |
| vague_fragment | 0 / 4 |
| wellbeing | 0 / 1 |

Per-intent precision / recall:

| Intent | Support | Precision | Recall |
|---|---:|---:|---:|
| product_question | 24 | 0.917 | 0.957 |
| order_status | 24 | 0.909 | 1.000 |
| escalate_to_human | 15 | 0.560 | 0.933 |
| smalltalk | 19 | n/a | 0.000 |
| out_of_scope | 14 | n/a | 0.000 |
| unclear | 14 | n/a | 0.000 |

## Limitations

- Offline routing replaces the LLM tier with an unavailable provider; it measures only the deterministic layers.
- Live routing numbers depend on Groq model behavior, load, and rate limits at run time.
- The evaluation sets were written by the project author and are small; treat differences of one or two cases as noise.

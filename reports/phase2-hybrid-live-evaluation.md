# Evaluation Report: phase2-hybrid-live

Generated: `2026-10-18T10:49:10.124516+00:00`

All values are computed from the labeled cases and real counters in this run.

## Routing

Mode: `live_groq_llm_tier`; model: `openai/gpt-oss-20b`; cases: `110`.

| Metric | Value |
|---|---:|
| Strict accuracy | 0.955 |
| Lenient accuracy (acceptable alternatives) | 0.982 |
| Outcome accuracy (no route answered as unclear) | 0.991 |
| Dead-end rate (no route) | 0.009 |
| False escalation rate | 0.000 |
| Order requests sent to product search | 0 |
| LLM classifier calls | 27 (0.245 per case) |
| Classifier errors | 0 |
| Routing latency p50 / p95 (ms) | 9.217 / 821.022 |
| LLM-routed latency p50 / p95 (ms) | 659.300 / 964.200 |

Routing sources: `{"classifier": 27, "deterministic_order_signal": 13, "rule_gibberish": 10, "rule_human_request": 7, "rule_smalltalk": 19, "semantic_exemplars": 29, "verified_session_memory": 5}`

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
| gibberish | 5 / 6 |
| goodbye | 3 / 3 |
| greeting | 6 / 6 |
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
| punctuation_only | 3 / 3 |
| safety_concern | 1 / 1 |
| thanks | 3 / 3 |
| vague_fragment | 3 / 4 |
| wellbeing | 1 / 1 |

Per-intent precision / recall:

| Intent | Support | Precision | Recall |
|---|---:|---:|---:|
| product_question | 24 | 1.000 | 0.917 |
| order_status | 24 | 0.923 | 1.000 |
| escalate_to_human | 15 | 0.933 | 0.933 |
| smalltalk | 19 | 1.000 | 1.000 |
| out_of_scope | 14 | 0.933 | 1.000 |
| unclear | 14 | 1.000 | 0.923 |

## Limitations

- Offline routing replaces the LLM tier with an unavailable provider; it measures only the deterministic layers.
- Live routing numbers depend on Groq model behavior, load, and rate limits at run time.
- The evaluation sets were written by the project author and are small; treat differences of one or two cases as noise.

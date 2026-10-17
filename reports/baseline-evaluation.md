# Baseline Evaluation Report

Generated: `2026-10-17T12:12:20.671630+00:00`

All metrics below are from the labeled seed cases and actual local counters.

## Summary

| Area | Metric | Value |
|---|---|---:|
| Routing | accuracy | 0.8333333333333334 |
| Retrieval | recall@5 | 0.7272727272727273 |
| Retrieval | MRR | 0.7272727272727273 |
| Retrieval | unanswerable rejection rate | 1.0 |
| Input guardrail | recall | 0.6666666666666666 |
| Output guardrail | recall | 1.0 |
| Cache | hit rate | 0.5 |

## Routing

Mode: `offline_heuristic_baseline`; samples: `12`.

```json
{
  "product_question": {
    "product_question": 3,
    "order_status": 1,
    "escalate_to_human": 0
  },
  "order_status": {
    "product_question": 1,
    "order_status": 3,
    "escalate_to_human": 0
  },
  "escalate_to_human": {
    "product_question": 0,
    "order_status": 0,
    "escalate_to_human": 4
  }
}
```

## Retrieval

Model: `sentence-transformers/all-MiniLM-L6-v2`; vector dimension: `384`.

## Guardrails

Input mode: `offline_rule_based_safety_baseline`.
Output mode: `deterministic_allowed_facts_baseline`.

## Cache

Workload: `8`; classifier calls: `4`; lookups: `8`; hits: `4`; misses: `4`.

## Limitations

- Routing and input guardrail baselines are deterministic offline baselines, not live LLM measurements.
- Retrieval uses the real local embedding model and corpus.
- These reports are baseline evidence, not production SLO claims.

# Evaluation and Observability

Status: Step 6 baseline implemented and run. The reports are evidence from
the current labeled cases, not production SLO claims.

## Command

From the repository root:

```powershell
python scripts/run_evaluation.py --output-dir reports
```

The command writes:

- `reports/baseline-evaluation.json` for machine-readable metrics and per-case
  retrieval/routing evidence;
- `reports/baseline-evaluation.md` for reviewer-friendly summary tables.

It uses no Groq key. Routing and input guardrails use deterministic offline
baselines; retrieval uses the actual local Sentence Transformers model and
NumPy vector index; output guardrails use the actual deterministic claim guard.

## Metrics

- Routing accuracy, per-intent precision/recall/F1, and confusion matrix.
- Retrieval recall@5, MRR, unanswerable rejection rate, and per-case retrieved
  document IDs.
- Input guardrail blocked-case precision/recall/F1.
- Output guardrail blocked-claim precision/recall/F1.
- Classifier cache lookups, hits, misses, classifier calls, and hit rate from
  the actual `ClassifierCache` counters.

## Current baseline result

The committed baseline report was generated from 12 routing cases, 12 retrieval
cases, 10 input-guardrail cases, 8 output-guardrail cases, and an 8-request
cache workload:

| Area | Result |
|---|---:|
| Routing accuracy | 0.8333 |
| Retrieval recall@5 | 0.7273 |
| Retrieval MRR | 0.7273 |
| Unanswerable rejection rate | 1.0 |
| Input guardrail recall | 0.6667 |
| Output guardrail recall | 1.0 |
| Cache hit rate | 0.5 |

The lower input-guardrail recall is useful evidence: the offline rule baseline
does not catch every semantic ownership/abuse case. A live semantic provider or
additional deterministic policy layer is needed before treating that metric as
production-ready.

## Reproducibility metadata

Each JSON report records the UTC generation time, Python/platform metadata,
evaluation mode, model name, vector dimension, sample sizes, and per-case
results. Re-running the command overwrites the two report files with the new
observed baseline; no values are estimated or manually entered.

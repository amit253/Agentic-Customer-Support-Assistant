# Evaluation and Observability

The evaluation runner measures routing, retrieval, guardrails, and the
classifier cache from labeled cases and real counters. Every report records
its mode (offline or live), so keyless baseline numbers are never confused
with live-provider measurements.

## Commands

From the repository root:

```powershell
# Keyless: routing with the LLM tier unavailable, retrieval, guardrails, cache
python scripts/run_evaluation.py --label latest

# Live Groq LLM tier for routing only (uses the configured key; throttled)
python scripts/run_evaluation.py --label live --sections routing --routing-mode live --live-delay 3

# Retrieval configurations: thresholds tuned on dev, scored on held-out
python scripts/compare_retrievers.py
```

Each run writes `reports/<label>-evaluation.json` (per-case evidence) and
`reports/<label>-evaluation.md` (summary tables). The original Step 6 files
`reports/baseline-evaluation.{json,md}` are kept unchanged as history.

## Evaluation sets

| File | Cases | Purpose |
|---|---:|---|
| `evals/routing_eval.jsonl` | 110 | Held-out routing set: product, order, human, smalltalk, out-of-scope, unclear, plus traps (greeting + request, negated "human", Hinglish, typos, memory follow-ups) |
| `evals/retrieval_eval.jsonl` | 45 | Held-out retrieval set: 32 answerable (incl. comparisons, multi-document, Hinglish) and 13 unanswerable near-misses |
| `evals/retrieval_dev.jsonl` + `evals/retrieval_seed.jsonl` | 33 | Dev set used only to tune retrieval thresholds |
| `evals/input_guardrail_eval.jsonl` | 10 | Input guard cases |
| `evals/output_guardrail_eval.jsonl` | 8 | Output claim guard cases |
| `src/agentic_support/route_exemplars.py` | 137 | Training examples for the semantic routing tier; a test checks they never overlap the held-out routing set |

The routing and retrieval evaluation sets were written and committed before
the hybrid router and hybrid retriever were built, so the git history shows
the labels were not fitted to the new code. They are still small and written
by the project author; a difference of one or two cases is noise.

Some routing cases list `acceptable_intents` where two routes are both
reasonable (for example "tell me a joke" as out-of-scope or smalltalk).
Strict accuracy uses only `expected_intent`; lenient accuracy accepts the
listed alternatives.

## Metrics

Routing:

- strict and lenient accuracy, per-intent precision/recall, confusion matrix;
- **dead-end rate**: share of messages with no usable route (the old "I could
  not classify that request safely" outcome);
- **false escalation rate**: share of non-escalation messages sent to a human;
- order requests sent to product search (the misroute seen live twice);
- routing source distribution (which tier decided), LLM calls per case,
  classifier errors, and routing latency p50/p95.

Retrieval, reported separately so a threshold problem is not mistaken for a
ranking problem:

- **ranking** over all chunks before any threshold: hit@1, hit@3, recall@3,
  recall@5 (share of *all* expected documents), MRR, nDCG@5;
- **gate**: acceptance rate on answerable questions, rejection rate on
  unanswerable ones, and their balanced accuracy;
- **end to end**: evidence recall (share of expected documents that actually
  reach the answer generator) and gated MRR.

Guardrails: blocked-case precision/recall/F1. Cache: lookups, hits, misses,
hit rate from the real `ClassifierCache` counters.

## Phase 0 baseline (before the routing and retrieval changes)

Measured on 2026-10-18 against the unchanged system. Reports:
`reports/phase0-baseline-live-evaluation.md` (live Groq `openai/gpt-oss-20b`)
and `reports/phase0-baseline-offline-evaluation.md` (keyless).

| Routing (110 held-out cases) | Offline, LLM unavailable | Live Groq |
|---|---:|---:|
| Strict accuracy | 0.091 | 0.509 |
| Lenient accuracy | 0.100 | 0.527 |
| Dead-end rate | 0.900 | 0.355 |
| False escalation rate | 0.000 | 0.117 |
| Classifier errors | 198 | 62 |
| Routing latency p50 / p95 | <1 ms | 973 ms / 16.4 s |

The live LLM classifier calls count each `classify` call; one call can make
two HTTP requests because of the JSON-object fallback, so provider requests
were higher than the 141 calls shown.

| Retrieval (MiniLM, 0.45 per-chunk threshold) | Held-out (32 + 13) | Dev (25 + 8) |
|---|---:|---:|
| hit@1 | 0.781 | 0.840 |
| MRR | 0.857 | 0.910 |
| recall@3 (all expected documents) | 0.906 | 0.920 |
| Answerable acceptance | 0.594 | 0.720 |
| Unanswerable rejection | 0.692 | 0.875 |
| Evidence recall reaching the answerer | 0.516 | 0.620 |

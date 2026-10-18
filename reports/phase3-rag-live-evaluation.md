# Evaluation Report: phase3-rag-live

Generated: `2026-10-18T11:05:17.744717+00:00`

All values are computed from the labeled cases and real counters in this run.

## End-to-end product answers (live)

Mode: `live_groq_answerer`; model: `openai/gpt-oss-20b`.

| Metric | Value |
|---|---:|
| Answerable questions answered | 0.906 |
| Answerable answers citing an expected document | 0.875 |
| Unanswerable questions declined | 1.000 |
| Declined by retrieval gate / by answerer | 10 / 6 |
| Handler errors | 0 |
| Answers blocked by output guard | 1 |
| Latency p50 (ms) | 741.100 |

## Limitations

- Offline routing replaces the LLM tier with an unavailable provider; it measures only the deterministic layers.
- Live routing numbers depend on Groq model behavior, load, and rate limits at run time.
- The evaluation sets were written by the project author and are small; treat differences of one or two cases as noise.

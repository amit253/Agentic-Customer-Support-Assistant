# Retrieval Design

Status: hybrid retrieval implemented (Phase 3). The original MiniLM retriever
(`GroundedRetriever`) is kept for comparison and for keyless tests.

## What changed and why

The first retriever used `all-MiniLM-L6-v2` embeddings and kept every chunk
whose cosine similarity was at least 0.45. On the 12-case seed set its
ranking was perfect and all losses came from that threshold. A harder,
held-out set (`evals/retrieval_eval.jsonl`: 32 answerable questions including
comparisons, multi-document policy questions, and Hinglish, plus 13
unanswerable near-misses such as price, colour, and weight) showed two
problems: ranking was imperfect (hit@1 0.781) and only 51.6% of the expected
documents reached the answer generator.

`scripts/compare_retrievers.py` compared nine configurations. Thresholds were
tuned only on the dev set (`retrieval_seed.jsonl` + `retrieval_dev.jsonl`,
33 cases) and then applied unchanged to the held-out set. See
`reports/retrieval-comparison.md` for the full table.

| Held-out (45 cases) | MRR | Accept answerable | Reject unanswerable | Evidence recall |
|---|---:|---:|---:|---:|
| Original: MiniLM, 0.45 per-chunk threshold | 0.857 | 0.594 | 0.692 | 0.516 |
| Same model, threshold re-tuned on dev | 0.857 | 0.844 | 0.615 | 0.781 |
| MiniLM + BM25 fusion | 0.907 | 0.812 | 0.615 | 0.797 |
| + ms-marco cross-encoder reranker | 0.885 | 0.562 | 0.769 | 0.562 |
| **multilingual-e5-small + BM25 fusion (chosen)** | **0.912** | **0.938** | 0.615 | **0.891** |

Read with care: 45 cases, so one case moves acceptance by about 3 points.
Adding a deterministic tie-break to the fusion step moved the chosen
configuration's dev-tuned thresholds from 0.821 / 0.6158 to 0.8311 / 0.6233
and its held-out evidence recall from 0.922 to 0.891; thresholds on sets this
small are sensitive and should be re-tuned whenever the corpus changes.

## Production retriever

`HybridRetriever` with `PRODUCTION_CONFIG` (`hybrid_retrieval.py`):

1. **Dense**: `intfloat/multilingual-e5-small` with the model's required
   `query:` / `passage:` prefixes. Multilingual, so romanized Hindi questions
   such as "cityhaul kitne liter ka hai?" are matched; the same property is
   the main reason to prefer it for an Indian-language product.
2. **BM25** over title + chunk text, for exact names and policy terms
   ("Trail Week", "CityHaul") that embeddings blur.
3. **Reciprocal-rank fusion** (k = 60) merges the two rankings without
   comparing their incompatible score scales; ties are broken by cosine.
4. **Evidence gate on the best candidate only** (cosine >= 0.8311). If it
   passes, up to four candidates with cosine >= 0.6233 go to the answerer.
   The old per-chunk cutoff dropped the second product in comparison
   questions; gating on the top candidate keeps both.

Both thresholds came from the dev set; e5 similarity scores are compressed
(roughly 0.7 to 0.9), which is why they are much higher than MiniLM's.

## Tried and dropped: cross-encoder reranking

Three rerankers were tested (`ms-marco-MiniLM-L-6-v2` with three different
embedders, and the multilingual `mmarco-mMiniLMv2-L12-H384-v1`). Because all
configurations see every one of the 12 chunks, the reranker alone decides the
final order, so the three ms-marco runs produced identical results. Their
probability scores were close to 0 or 1, so a gate tuned on dev (0.948) did
not transfer: held-out acceptance fell to 0.562. They also added roughly half
a second per query on CPU. Reranking is worth revisiting with a corpus large
enough that the first stage must choose 20 of thousands of chunks.

## Two gates, not one

No configuration rejects unanswerable near-misses well (best 0.769, chosen
0.615): "How much does the Trailmark 28 cost?" is semantically close to the
Trailmark document even though that document has no price. The retrieval gate
is therefore tuned for recall, and the answer generator is the second gate:
it must set `insufficient_evidence` (or return no citations) when the passages
do not answer the question, and the handler then returns the fixed "not
enough verified information" reply. The output claim guard is a third check
on any dates, amounts, or order IDs in the final text.

## Ingestion and provenance

Unchanged: Markdown files with `doc_id` / `title` frontmatter, whitespace
normalized, 480-character chunks with 80-character overlap and stable IDs such
as `kb-005-standard-returns#chunk-000`. With 12 short documents each document
is one chunk. Hits keep document ID, title, path, and chunk index; customers
see article titles as sources, and chunk IDs remain in response metadata.

## Tests

`tests/test_hybrid_retrieval.py` covers BM25 tokenization, a keyword match
lifting a document the embeddings miss, top-candidate gating, comparison
questions keeping both products, and empty queries, using a fake embedder.
`tests/test_retrieval.py` still exercises the real MiniLM model.

## End-to-end check with the live answerer

`python scripts/run_evaluation.py --label phase3-rag-live --sections rag --live-delay 3`
runs every held-out retrieval question through the production retriever, the
Groq answerer, and the output guard (`reports/phase3-rag-live-evaluation.md`):

| Live, 45 held-out questions | Value |
|---|---:|
| Answerable questions answered | 0.906 |
| Answerable answers citing an expected document | 0.875 |
| Unanswerable near-misses declined | 1.000 (13 / 13) |
| Declines by retrieval gate / by answerer (all cases) | 10 / 6 |
| Handler errors | 0 |
| Correct answers blocked by the output guard | 1 |

The answerer caught every near-miss the retrieval gate let through, which is
the point of the two-gate design. The blocked answer was "No, Trail Week does
not mean your refund is approved": the guard's promise pattern does not
understand negation (see the red-team report). Two answerable questions
("Can I put the backpack in the dryer?", "When will a human specialist take
over my case?") were rejected by the retrieval gate; that is the recall cost
of the threshold.

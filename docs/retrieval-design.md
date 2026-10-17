# Retrieval Design

Status: Step 3 implemented and tested. This document describes the actual
retrieval path; answer generation and agents are future steps.

## Embedding model

The implementation uses the local Sentence Transformers model
`sentence-transformers/all-MiniLM-L6-v2`. The verified runtime produced
384-dimensional vectors and normalized them before indexing. The model is
downloaded to the local model cache by the package runtime, not committed to
the repository.

This model was selected because it is small enough for a local development
demo, supports semantic paraphrases, and does not require a Groq API key or a
paid embedding service. The model name is configurable in the retriever
factory.

## Vector index

The index is an exact dense NumPy matrix. Each row is a normalized chunk
embedding, and a query is normalized and scored with a matrix-vector inner
product. Because both sides are normalized, this is cosine similarity.

There are currently only 12 source documents, so an exact scan is simpler and
more inspectable than introducing approximate-nearest-neighbor infrastructure.
The index preserves deterministic ordering with a stable descending score sort.
If the corpus grows substantially, this interface can be replaced by FAISS or
another managed vector index without changing document/chunk contracts.

## Ingestion and chunking

Markdown files are loaded in stable path order. Each file must contain simple
frontmatter with `doc_id` and `title`. The body is whitespace-normalized and
split at word boundaries into 480-character chunks with an 80-character
overlap. Each chunk receives an ID such as
`kb-005-standard-returns#chunk-000` and retains:

- source document ID;
- title;
- repository-relative source path;
- chunk index;
- exact chunk text.

This provenance is returned with every retrieval hit so later answer
generation can cite the passages it actually received.

## Insufficient evidence

The retriever applies a configured minimum cosine-similarity threshold of
`0.45`. This value was selected from the measured Step 3 cases: the required
paraphrase scored `0.5043`, the two conflicting policy sources scored `0.6234`
and `0.4828`, the irrelevant query scored `0.1746`, and the unanswerable
refund query's best candidate scored `0.4399`. Empty queries and queries with no chunk above the threshold return no
hits and an explicit reason. The retriever never invents an answer and does
not silently fall back to keyword search.

For an ambiguous or intentionally conflicting question, the retriever returns
multiple relevant chunks. The later RAG answer layer must surface the conflict
or escalate; it must not silently choose one policy.

## Tests

The Step 3 tests run the real local embedding model and cover:

- deterministic ingestion and chunk IDs;
- semantic paraphrase retrieval;
- irrelevant-query rejection;
- conflicting standard/Trail Week policy retrieval;
- unanswerable refund questions;
- source document and chunk provenance.

No Groq key is used by these tests.

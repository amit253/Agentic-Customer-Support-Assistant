"""Hybrid retrieval: dense embeddings + BM25 keywords, fused, then reranked.

Why each stage exists:

* Dense embeddings match paraphrases ("how big" ~ "28-liter").
* BM25 matches exact tokens that embeddings blur: product names, model
  numbers, policy names ("Trail Week"), and in a real deployment SKUs or
  member IDs.
* Reciprocal-rank fusion (RRF) merges the two rankings without having to
  compare their incompatible score scales.
* An optional cross-encoder reads the query and each candidate together and
  produces a relevance score that is better calibrated than raw cosine
  similarity, so the "do we have evidence?" gate is more reliable.

The evidence gate looks only at the best candidate. If it passes, the top
candidates above a lower support threshold go to the answer generator, so a
comparison question can receive both product documents instead of losing the
second one to a per-chunk cutoff.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .retrieval import (
    DEFAULT_CHUNK_OVERLAP,
    DEFAULT_CHUNK_SIZE,
    DenseVectorIndex,
    DocumentChunk,
    RetrievalHit,
    RetrievalResponse,
    SentenceTransformerEmbedder,
    TextEmbedder,
    chunk_documents,
    load_markdown_documents,
)


RRF_K = 60
_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an the is are was were be been do does did can could should would will "
    "i you my your me it its this that of to in on for with and or if at by "
    "from as what how when where which who why there their our we us".split()
)


def bm25_tokens(text: str) -> list[str]:
    """Lowercase word tokens with stopwords removed and plurals folded."""

    tokens = []
    for token in _TOKEN.findall(text.casefold()):
        if token in _STOPWORDS:
            continue
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
            token = token[:-1]
        tokens.append(token)
    return tokens


class BM25Index:
    """Okapi BM25 over chunk texts (k1=1.5, b=0.75)."""

    def __init__(self, texts: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        self._docs = [Counter(bm25_tokens(text)) for text in texts]
        self._lengths = np.asarray([sum(doc.values()) for doc in self._docs], dtype=np.float32)
        self._avg_length = float(self._lengths.mean()) if len(self._docs) else 0.0
        document_frequency: Counter[str] = Counter()
        for doc in self._docs:
            document_frequency.update(doc.keys())
        total = len(self._docs)
        self._idf = {
            term: math.log(1 + (total - count + 0.5) / (count + 0.5))
            for term, count in document_frequency.items()
        }
        self.k1 = k1
        self.b = b

    def scores(self, query: str) -> np.ndarray:
        terms = bm25_tokens(query)
        result = np.zeros(len(self._docs), dtype=np.float32)
        for index, doc in enumerate(self._docs):
            length_norm = 1 - self.b + self.b * self._lengths[index] / (self._avg_length or 1)
            for term in terms:
                frequency = doc.get(term, 0)
                if frequency:
                    result[index] += self._idf[term] * (
                        frequency * (self.k1 + 1) / (frequency + self.k1 * length_norm)
                    )
        return result


class Reranker(Protocol):
    model_name: str

    def score(self, query: str, passages: Sequence[str]) -> np.ndarray:
        """Return a relevance probability in [0, 1] for each passage."""


class CrossEncoderReranker:
    """Sentence Transformers cross-encoder with outputs mapped to [0, 1]."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self._model: Any = CrossEncoder(model_name)

    def score(self, query: str, passages: Sequence[str]) -> np.ndarray:
        raw = np.asarray(
            self._model.predict([(query, passage) for passage in passages], show_progress_bar=False),
            dtype=np.float32,
        ).reshape(-1)
        if raw.size and (raw.min() < 0.0 or raw.max() > 1.0):
            raw = 1.0 / (1.0 + np.exp(-raw))
        return raw


@dataclass(frozen=True, slots=True)
class HybridConfig:
    """Tunable retrieval settings; thresholds are calibrated on the dev set."""

    use_bm25: bool = True
    candidate_count: int = 20
    gate_threshold: float = 0.45
    support_threshold: float = 0.30
    query_prefix: str = ""
    passage_prefix: str = ""


class HybridRetriever:
    """Drop-in replacement for ``GroundedRetriever`` with fusion and reranking."""

    def __init__(
        self,
        *,
        chunks: Sequence[DocumentChunk],
        embedder: TextEmbedder,
        config: HybridConfig,
        reranker: Reranker | None = None,
    ) -> None:
        self.chunks = tuple(chunks)
        self.embedder = embedder
        self.config = config
        self.reranker = reranker
        vectors = embedder.encode([config.passage_prefix + chunk.text for chunk in self.chunks])
        self.index = DenseVectorIndex(self.chunks, vectors)
        matrix = np.asarray(vectors, dtype=np.float32)
        self._matrix = matrix / np.linalg.norm(matrix, axis=1, keepdims=True)
        self.bm25 = BM25Index([chunk.title + " " + chunk.text for chunk in self.chunks])

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        *,
        embedding_model: str,
        config: HybridConfig,
        reranker_model: str | None = None,
        embedder: TextEmbedder | None = None,
    ) -> "HybridRetriever":
        chunks = chunk_documents(
            load_markdown_documents(directory),
            max_chars=DEFAULT_CHUNK_SIZE,
            overlap_chars=DEFAULT_CHUNK_OVERLAP,
        )
        return cls(
            chunks=chunks,
            embedder=embedder or SentenceTransformerEmbedder(embedding_model),
            config=config,
            reranker=CrossEncoderReranker(reranker_model) if reranker_model else None,
        )

    def describe(self) -> dict[str, object]:
        return {
            "type": type(self).__name__,
            "embedding_model": self.embedder.model_name,
            "reranker_model": self.reranker.model_name if self.reranker else None,
            "bm25": self.config.use_bm25,
            "gate_threshold": self.config.gate_threshold,
            "support_threshold": self.config.support_threshold,
            "chunk_count": len(self.chunks),
        }

    def _dense_scores(self, query: str) -> np.ndarray:
        """Cosine similarity of the query with every chunk, in chunk order."""

        vector = np.asarray(
            self.embedder.encode([self.config.query_prefix + query])[0], dtype=np.float32
        )
        return self._matrix @ (vector / np.linalg.norm(vector))

    def rank_all(self, query: str) -> tuple[RetrievalHit, ...]:
        """Full ranking with the score the gate uses (reranker or cosine)."""

        normalized = " ".join(query.split())
        dense = self._dense_scores(normalized)
        dense_rank = {int(i): rank for rank, i in enumerate(np.argsort(-dense, kind="stable"))}
        fused = {i: 1.0 / (RRF_K + dense_rank[i] + 1) for i in range(len(self.chunks))}
        if self.config.use_bm25:
            keyword = self.bm25.scores(normalized)
            for rank, i in enumerate(np.argsort(-keyword, kind="stable")):
                if keyword[int(i)] > 0:
                    fused[int(i)] += 1.0 / (RRF_K + rank + 1)
        # Ties in RRF are common when two lists disagree; break them by cosine.
        order = sorted(fused, key=lambda i: (fused[i], float(dense[i])), reverse=True)
        candidates = order[: self.config.candidate_count]
        if self.reranker is not None:
            relevance = self.reranker.score(normalized, [self.chunks[i].text for i in candidates])
            scored = sorted(zip(candidates, relevance), key=lambda pair: float(pair[1]), reverse=True)
            ranked = [RetrievalHit(self.chunks[i], float(score)) for i, score in scored]
        else:
            ranked = [RetrievalHit(self.chunks[i], float(dense[i])) for i in candidates]
        remaining = [RetrievalHit(self.chunks[i], 0.0) for i in order[self.config.candidate_count:]]
        return tuple(ranked + remaining)

    def retrieve(self, query: str, *, top_k: int = 4) -> RetrievalResponse:
        normalized = " ".join(query.split())
        if not normalized:
            return RetrievalResponse(query="", hits=(), sufficient_evidence=False, reason="empty_query")
        ranked = self.rank_all(normalized)
        if not ranked or ranked[0].score < self.config.gate_threshold:
            return RetrievalResponse(
                query=normalized,
                hits=(),
                sufficient_evidence=False,
                reason="best_candidate_below_evidence_gate",
            )
        supporting = tuple(
            hit for hit in ranked[:top_k] if hit.score >= self.config.support_threshold
        )
        return RetrievalResponse(
            query=normalized,
            hits=supporting,
            sufficient_evidence=True,
            reason="retrieved_supporting_chunks",
        )


# Production choice from scripts/compare_retrievers.py (reports/
# retrieval-comparison.md): multilingual-e5-small + BM25 fusion, no reranker.
# Thresholds were tuned on the dev set only. On the 45-case held-out set this
# configuration had MRR 0.912, answerable acceptance 0.938, unanswerable
# rejection 0.615, and evidence recall 0.891, against 0.857 / 0.594 / 0.692 /
# 0.516 for the original MiniLM retriever. Cross-encoder rerankers were tried
# and dropped: their dev-tuned gates did not transfer to the held-out set and
# they added roughly half a second per query on CPU.
#
# Gate re-tuned for recall after the live end-to-end check: e5 top scores for
# answerable and unanswerable questions overlap (about 0.79 to 0.88), so this
# gate cannot separate them, while the answerer declined every near-miss it
# was shown (13/13). The gate is therefore set to the highest value that still
# accepts every answerable dev question (lowest dev answerable top score,
# 0.81062) instead of the balanced-accuracy optimum (0.8311), and the
# answerer's insufficient-evidence flag is the precision gate.
PRODUCTION_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
PRODUCTION_CONFIG = HybridConfig(
    use_bm25=True,
    gate_threshold=0.8106,
    support_threshold=0.6233,
    query_prefix="query: ",
    passage_prefix="passage: ",
)


def build_production_retriever(directory: Path) -> HybridRetriever:
    """Build the calibrated production retriever over a knowledge-base folder."""

    return HybridRetriever.from_directory(
        directory,
        embedding_model=PRODUCTION_EMBEDDING_MODEL,
        config=PRODUCTION_CONFIG,
    )

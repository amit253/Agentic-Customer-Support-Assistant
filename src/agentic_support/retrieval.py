"""Local embedding retrieval with deterministic document provenance."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, Sequence

import numpy as np


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_CHUNK_SIZE = 480
DEFAULT_CHUNK_OVERLAP = 80
DEFAULT_MIN_SIMILARITY = 0.45


class RetrievalConfigurationError(ValueError):
    """Raised when the knowledge base or vector index is invalid."""


@dataclass(frozen=True, slots=True)
class SourceDocument:
    """A source Markdown document with stable repository provenance."""

    doc_id: str
    title: str
    source_path: str
    text: str


@dataclass(frozen=True, slots=True)
class DocumentChunk:
    """A deterministic chunk that retains its source document identity."""

    chunk_id: str
    doc_id: str
    title: str
    source_path: str
    chunk_index: int
    text: str


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    """One chunk and its cosine-similarity score."""

    chunk: DocumentChunk
    score: float


@dataclass(frozen=True, slots=True)
class RetrievalResponse:
    """Retrieval output with explicit insufficient-evidence behavior."""

    query: str
    hits: tuple[RetrievalHit, ...]
    sufficient_evidence: bool
    reason: str


class TextEmbedder(Protocol):
    """Minimal embedding interface used by the vector index."""

    model_name: str

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Return one normalized vector for each input text."""


def _normalize_rows(vectors: np.ndarray) -> np.ndarray:
    array = np.asarray(vectors, dtype=np.float32)
    if array.ndim != 2 or array.shape[0] == 0 or array.shape[1] == 0:
        raise RetrievalConfigurationError("embedding matrix must be non-empty and 2D")

    norms = np.linalg.norm(array, axis=1, keepdims=True)
    if np.any(norms <= 0):
        raise RetrievalConfigurationError("embedding vectors must have non-zero length")
    return array / norms


class SentenceTransformerEmbedder:
    """Local semantic embedder backed by a Sentence Transformers model."""

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model: Any = SentenceTransformer(model_name)

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if not texts:
            raise RetrievalConfigurationError("cannot embed an empty text sequence")
        vectors = self._model.encode(
            list(texts),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return _normalize_rows(np.asarray(vectors, dtype=np.float32))


class DenseVectorIndex:
    """Exact normalized inner-product index for the small knowledge base.

    With 10-20 documents, scanning the dense matrix is deterministic, easy to
    inspect, and avoids introducing an approximate-nearest-neighbor dependency.
    Cosine similarity equals the inner product because all rows are normalized.
    """

    def __init__(
        self, chunks: Sequence[DocumentChunk], vectors: np.ndarray
    ) -> None:
        if len(chunks) == 0:
            raise RetrievalConfigurationError("vector index needs at least one chunk")
        matrix = _normalize_rows(vectors)
        if matrix.shape[0] != len(chunks):
            raise RetrievalConfigurationError(
                "vector row count must equal chunk count"
            )
        self._chunks = tuple(chunks)
        self._vectors = matrix

    @property
    def dimension(self) -> int:
        return int(self._vectors.shape[1])

    @property
    def size(self) -> int:
        return len(self._chunks)

    def search(self, query_vector: np.ndarray, top_k: int) -> tuple[RetrievalHit, ...]:
        if top_k < 1:
            raise ValueError("top_k must be at least one")
        query = _normalize_rows(np.asarray(query_vector, dtype=np.float32).reshape(1, -1))
        if query.shape[1] != self.dimension:
            raise RetrievalConfigurationError("query dimension does not match index")

        scores = self._vectors @ query[0]
        ordered_indices = np.argsort(-scores, kind="stable")[:top_k]
        return tuple(
            RetrievalHit(
                chunk=self._chunks[int(index)],
                score=float(scores[int(index)]),
            )
            for index in ordered_indices
        )


def _parse_frontmatter(content: str, source_path: str) -> tuple[str, str, str]:
    match = re.match(
        r"\A---\r?\n(?P<header>.*?)\r?\n---\r?\n(?P<body>.*)\Z",
        content,
        flags=re.DOTALL,
    )
    if match is None:
        raise RetrievalConfigurationError(
            f"{source_path} must start with simple YAML frontmatter"
        )

    values: dict[str, str] = {}
    for line in match.group("header").splitlines():
        key, separator, value = line.partition(":")
        if separator:
            values[key.strip()] = value.strip()

    doc_id = values.get("doc_id", "")
    title = values.get("title", "")
    if not doc_id or not title:
        raise RetrievalConfigurationError(
            f"{source_path} frontmatter requires doc_id and title"
        )
    body = re.sub(r"\s+", " ", match.group("body")).strip()
    if not body:
        raise RetrievalConfigurationError(f"{source_path} body must not be empty")
    return doc_id, title, body


def load_markdown_documents(
    directory: Path, *, source_root: Path | None = None
) -> tuple[SourceDocument, ...]:
    """Load Markdown documents in stable path order."""

    paths = sorted(directory.glob("*.md"))
    if not paths:
        raise RetrievalConfigurationError(f"no Markdown documents found in {directory}")
    root = source_root or directory.parent
    documents: list[SourceDocument] = []
    seen_ids: set[str] = set()
    for path in paths:
        source_path = path.relative_to(root).as_posix()
        doc_id, title, body = _parse_frontmatter(
            path.read_text(encoding="utf-8"), source_path
        )
        if doc_id in seen_ids:
            raise RetrievalConfigurationError(f"duplicate document ID: {doc_id}")
        seen_ids.add(doc_id)
        documents.append(
            SourceDocument(
                doc_id=doc_id,
                title=title,
                source_path=source_path,
                text=body,
            )
        )
    return tuple(documents)


def chunk_text(
    text: str,
    *,
    max_chars: int = DEFAULT_CHUNK_SIZE,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP,
) -> tuple[str, ...]:
    """Split normalized text into deterministic word-boundary chunks."""

    if max_chars <= 0 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError("require max_chars > overlap_chars >= 0")
    words = re.sub(r"\s+", " ", text).strip().split(" ")
    if not words or words == [""]:
        return ()
    if any(len(word) > max_chars for word in words):
        raise RetrievalConfigurationError("a single word exceeds max_chars")

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = start
        length = 0
        while end < len(words):
            addition = len(words[end]) + (1 if end > start else 0)
            if end > start and length + addition > max_chars:
                break
            length += addition
            end += 1
        chunks.append(" ".join(words[start:end]))
        if end == len(words):
            break

        overlap_start = end
        overlap_length = 0
        for index in range(end - 1, start - 1, -1):
            addition = len(words[index]) + (1 if overlap_start < end else 0)
            if overlap_length + addition > overlap_chars:
                break
            overlap_length += addition
            overlap_start = index
        start = max(start + 1, overlap_start)
    return tuple(chunks)


def chunk_documents(
    documents: Sequence[SourceDocument],
    *,
    max_chars: int = DEFAULT_CHUNK_SIZE,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP,
) -> tuple[DocumentChunk, ...]:
    """Create stable chunk IDs and preserve document/chunk provenance."""

    chunks: list[DocumentChunk] = []
    for document in documents:
        for index, text in enumerate(
            chunk_text(
                document.text,
                max_chars=max_chars,
                overlap_chars=overlap_chars,
            )
        ):
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{document.doc_id}#chunk-{index:03d}",
                    doc_id=document.doc_id,
                    title=document.title,
                    source_path=document.source_path,
                    chunk_index=index,
                    text=text,
                )
            )
    if not chunks:
        raise RetrievalConfigurationError("chunking produced no chunks")
    return tuple(chunks)


class GroundedRetriever:
    """Retrieve semantically similar chunks or explicitly report insufficiency."""

    def __init__(
        self,
        *,
        embedder: TextEmbedder,
        index: DenseVectorIndex,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
    ) -> None:
        if not 0 <= min_similarity <= 1:
            raise ValueError("min_similarity must be between zero and one")
        self.embedder = embedder
        self.index = index
        self.min_similarity = min_similarity

    @classmethod
    def from_directory(
        cls,
        directory: Path,
        *,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        max_chars: int = DEFAULT_CHUNK_SIZE,
        overlap_chars: int = DEFAULT_CHUNK_OVERLAP,
        min_similarity: float = DEFAULT_MIN_SIMILARITY,
    ) -> "GroundedRetriever":
        documents = load_markdown_documents(directory)
        chunks = chunk_documents(
            documents,
            max_chars=max_chars,
            overlap_chars=overlap_chars,
        )
        embedder = SentenceTransformerEmbedder(model_name)
        vectors = embedder.encode([chunk.text for chunk in chunks])
        return cls(
            embedder=embedder,
            index=DenseVectorIndex(chunks, vectors),
            min_similarity=min_similarity,
        )

    def rank_all(self, query: str) -> tuple[RetrievalHit, ...]:
        """Score every chunk without the evidence threshold (evaluation only)."""

        normalized_query = re.sub(r"\s+", " ", query).strip()
        query_vector = self.embedder.encode([normalized_query])[0]
        return self.index.search(query_vector, top_k=self.index.size)

    def retrieve(self, query: str, *, top_k: int = 4) -> RetrievalResponse:
        normalized_query = re.sub(r"\s+", " ", query).strip()
        if not normalized_query:
            return RetrievalResponse(
                query="",
                hits=(),
                sufficient_evidence=False,
                reason="empty_query",
            )

        query_vector = self.embedder.encode([normalized_query])[0]
        candidates = self.index.search(query_vector, top_k=top_k)
        accepted = tuple(
            hit for hit in candidates if hit.score >= self.min_similarity
        )
        if not accepted:
            return RetrievalResponse(
                query=normalized_query,
                hits=(),
                sufficient_evidence=False,
                reason="no_chunk_above_similarity_threshold",
            )
        return RetrievalResponse(
            query=normalized_query,
            hits=accepted,
            sufficient_evidence=True,
            reason="retrieved_supporting_chunks",
        )

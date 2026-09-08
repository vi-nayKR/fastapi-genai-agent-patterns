"""Hybrid retrieval engine combining BM25 lexical search, dense embeddings, and RRF."""

from typing import Literal

from opentelemetry import trace
from opentelemetry.trace import Tracer

from agent_patterns.cache.embedding import HashingEmbedder
from agent_patterns.retrieval.bm25 import BM25Index
from agent_patterns.retrieval.models import Document, DocumentChunk, RetrievalResult


def _cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    if len(vec_a) != len(vec_b):
        return 0.0
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    return max(0.0, min(1.0, dot))


class HybridRetriever:
    """Tenant-scoped hybrid retriever using Reciprocal Rank Fusion (RRF)."""

    def __init__(
        self,
        documents: list[Document],
        embedder: HashingEmbedder | None = None,
        rrf_constant: int = 60,
        tracer: Tracer | None = None,
    ) -> None:
        self._embedder = embedder or HashingEmbedder(dimensions=512)
        self._rrf_constant = rrf_constant
        self._tracer = tracer or trace.get_tracer(__name__)

        self._documents_by_id: dict[str, Document] = {d.doc_id: d for d in documents}
        self._chunks: list[DocumentChunk] = []

        # Parse documents into typed passages
        for doc in documents:
            sections = [s.strip() for s in doc.content.split("\n\n") if s.strip()]
            for idx, sec in enumerate(sections):
                first_line = sec.split("\n")[0]
                section_title = (
                    first_line if first_line.startswith("Section") else f"Passage {idx+1}"
                )
                chunk = DocumentChunk(
                    chunk_id=f"{doc.doc_id}#chunk-{idx}",
                    doc_id=doc.doc_id,
                    tenant_id=doc.tenant_id,
                    version=doc.version,
                    section=section_title,
                    text=sec,
                )
                self._chunks.append(chunk)

        # Precompute chunk vectors and texts enriched with document metadata
        self._chunk_texts = []
        for c in self._chunks:
            doc = self._documents_by_id[c.doc_id]
            tags_str = f" ({', '.join(doc.tags)})" if doc.tags else ""
            self._chunk_texts.append(f"{doc.title}{tags_str} - {c.section}: {c.text}")
        self._chunk_vectors = [self._embedder.embed(txt) for txt in self._chunk_texts]

        # Build BM25 index over all chunks
        self._bm25 = BM25Index(self._chunk_texts)

    def search(
        self,
        query: str,
        tenant_id: str,
        top_k: int = 5,
        mode: Literal["hybrid", "dense", "lexical"] = "hybrid",
        include_deprecated: bool = False,
    ) -> list[RetrievalResult]:
        """Search passages scoped to tenant and lifecycle status."""
        with self._tracer.start_as_current_span("retrieval.search") as span:
            span.set_attribute("retrieval.tenant_id", tenant_id)
            span.set_attribute("retrieval.mode", mode)
            span.set_attribute("retrieval.top_k", top_k)

            # Filter candidate chunk indices by tenant and status
            valid_indices: list[int] = []
            for idx, chunk in enumerate(self._chunks):
                if chunk.tenant_id != tenant_id:
                    continue
                doc = self._documents_by_id.get(chunk.doc_id)
                if not doc:
                    continue
                if not include_deprecated and doc.status != "active":
                    continue
                valid_indices.append(idx)

            span.set_attribute("retrieval.candidate_count", len(valid_indices))
            if not valid_indices:
                return []

            # Compute lexical BM25 scores (filter non-positive scores)
            lexical_ranked_all = self._bm25.score_all(query)
            lexical_scores: dict[int, float] = {idx: sc for idx, sc in lexical_ranked_all}
            valid_lexical = [
                idx for idx, sc in lexical_ranked_all if idx in valid_indices and sc > 0.0
            ]

            # Compute dense embedding scores
            query_vector = self._embedder.embed(query)
            dense_scores: dict[int, float] = {}
            for idx in valid_indices:
                dense_scores[idx] = _cosine_similarity(query_vector, self._chunk_vectors[idx])

            valid_dense = [
                idx
                for idx in sorted(
                    valid_indices,
                    key=lambda idx: dense_scores.get(idx, 0.0),
                    reverse=True,
                )
                if dense_scores.get(idx, 0.0) > 0.15
            ]

            # Lexical and dense ranks (1-indexed)
            lexical_ranks = {idx: rank + 1 for rank, idx in enumerate(valid_lexical)}
            dense_ranks = {idx: rank + 1 for rank, idx in enumerate(valid_dense)}

            results: list[RetrievalResult] = []

            if mode == "lexical":
                for rank, idx in enumerate(valid_lexical[:top_k], start=1):
                    results.append(
                        RetrievalResult(
                            chunk=self._chunks[idx],
                            score=lexical_scores[idx],
                            lexical_score=lexical_scores[idx],
                            dense_score=dense_scores.get(idx, 0.0),
                            rank=rank,
                        )
                    )
            elif mode == "dense":
                for rank, idx in enumerate(valid_dense[:top_k], start=1):
                    results.append(
                        RetrievalResult(
                            chunk=self._chunks[idx],
                            score=dense_scores[idx],
                            lexical_score=lexical_scores.get(idx, 0.0),
                            dense_score=dense_scores[idx],
                            rank=rank,
                        )
                    )
            else:  # hybrid RRF
                rrf_scores: dict[int, float] = {}
                for idx in valid_indices:
                    score = 0.0
                    if idx in lexical_ranks:
                        score += 1.0 / (self._rrf_constant + lexical_ranks[idx])
                    if idx in dense_ranks:
                        score += 1.0 / (self._rrf_constant + dense_ranks[idx])
                    rrf_scores[idx] = score

                valid_hybrid = [
                    idx
                    for idx in sorted(
                        valid_indices,
                        key=lambda idx: rrf_scores[idx],
                        reverse=True,
                    )
                    if rrf_scores[idx] > 0.0
                ]

                for rank, idx in enumerate(valid_hybrid[:top_k], start=1):
                    results.append(
                        RetrievalResult(
                            chunk=self._chunks[idx],
                            score=rrf_scores[idx],
                            lexical_score=lexical_scores.get(idx, 0.0),
                            dense_score=dense_scores.get(idx, 0.0),
                            rank=rank,
                        )
                    )

            span.set_attribute("retrieval.returned_count", len(results))
            return results

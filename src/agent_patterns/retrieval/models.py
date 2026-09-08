"""Data models for versioned document retrieval and chunking."""

from dataclasses import dataclass
from typing import Literal

from agent_patterns.schemas import StrictModel


class Document(StrictModel):
    """Versioned document with tenant scoping and lifecycle status."""

    doc_id: str
    title: str
    tenant_id: str
    version: int
    status: Literal["active", "deprecated", "draft"] = "active"
    content: str
    tags: list[str] = []
    updated_at: str


@dataclass(frozen=True)
class DocumentChunk:
    """Individual searchable passage derived from a parent document."""

    chunk_id: str
    doc_id: str
    tenant_id: str
    version: int
    section: str
    text: str


@dataclass
class RetrievalResult:
    """Scored candidate passage returned by the retrieval engine."""

    chunk: DocumentChunk
    score: float
    dense_score: float = 0.0
    lexical_score: float = 0.0
    rank: int = 0

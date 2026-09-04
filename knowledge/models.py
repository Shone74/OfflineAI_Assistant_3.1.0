"""Knowledge models — documents, chunks, and search results."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path


def _id_from(path: str | Path) -> str:
    return hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:16]


@dataclass
class KnowledgeChunk:
    """A text fragment of a document that is embedded and indexed individually."""

    doc_id: str
    text: str
    page: int | None = None
    vector_id: str | None = None


@dataclass
class Document:
    """A parsed document broken into :class:`KnowledgeChunk` pieces."""

    path: str
    title: str
    format: str
    chunks: list[KnowledgeChunk] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @property
    def id(self) -> str:
        return _id_from(self.path)


@dataclass
class SearchResult:
    """One ranked hit from the knowledge base."""

    score: float
    chunk: KnowledgeChunk
    doc_title: str

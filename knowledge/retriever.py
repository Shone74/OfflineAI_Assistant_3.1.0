"""RAG retriever — fetches relevant knowledge and formats it as prompt context."""

from __future__ import annotations

from knowledge.knowledge_base import KnowledgeBase
from knowledge.models import SearchResult


class RAGRetriever:
    """Turns a user query into a ranked, formatted context block."""

    def __init__(self, knowledge_base: KnowledgeBase, max_chunks: int = 3) -> None:
        self._kb = knowledge_base
        self._max_chunks = max_chunks

    @property
    def knowledge_base(self) -> KnowledgeBase:
        return self._kb

    def retrieve(self, query: str, top_k: int | None = None) -> list[SearchResult]:
        k = top_k if top_k is not None else self._max_chunks
        return self._kb.search(query, top_k=k)

    def format_context(self, results: list[SearchResult]) -> str:
        """Render results as numbered, citable snippets."""
        if not results:
            return ""
        blocks = []
        for i, res in enumerate(results, start=1):
            snippet = res.chunk.text.strip().replace("\n", " ")[:500]
            blocks.append(f"{i}. {snippet} (iz: {res.doc_title})")
        return "\n".join(blocks)

    def augment(self, query: str, top_k: int | None = None) -> tuple[list[SearchResult], str]:
        """Return ``(results, formatted_context)`` for *query*."""
        results = self.retrieve(query, top_k=top_k)
        return results, self.format_context(results)

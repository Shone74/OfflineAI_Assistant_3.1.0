"""RAG pipeline — wires retrieval into an assistant-augmentable context."""

from __future__ import annotations

from knowledge.models import SearchResult
from knowledge.retriever import RAGRetriever


class RAGPipeline:
    """Pulls relevant context from the knowledge base for a user query."""

    def __init__(
        self,
        retriever: RAGRetriever,
        max_context_chunks: int = 3,
        min_score: float = -1.0,
    ) -> None:
        self._retriever = retriever
        self._max_context_chunks = max_context_chunks
        self._min_score = min_score

    @property
    def retriever(self) -> RAGRetriever:
        return self._retriever

    def retrieve_context(self, query: str, top_k: int | None = None) -> tuple[list[SearchResult], str]:
        """Return ``(results, formatted_context)`` for *query*.

        When *top_k* is ``None`` the pipeline's configured
        ``max_context_chunks`` is used (backward compatible).
        """
        k = top_k if top_k is not None else self._max_context_chunks
        return self._retriever.augment(query, top_k=k)

    def is_relevant(self, query: str) -> bool:
        """Cheap check: whether *query* has any retrievable context."""
        results, _ = self.retrieve_context(query)
        return any(r.score >= self._min_score for r in results)

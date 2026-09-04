"""Vector memory — semantic search over document chunks.

Tries to use ``faiss-cpu`` when available; otherwise falls back to a pure
Python brute-force k-NN search so the system works with zero heavy deps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.logger import get_logger
from memory.embeddings import EmbeddingModel, cosine_similarity

logger = get_logger("vector_memory")


@dataclass
class VectorEntry:
    """A single vectorised chunk stored in the index."""

    id: str
    text: str
    vector: list[float]


class VectorMemory:
    """Index of embeddings supporting nearest-neighbour search."""

    def __init__(self, embedding_model: EmbeddingModel) -> None:
        self._embedding_model = embedding_model
        self._entries: list[VectorEntry] = []
        self._faiss_index: Any = None
        self._faiss: Any = None
        self._try_init_faiss()

    # ------------------------------------------------------------------ #
    def _try_init_faiss(self) -> None:
        try:
            import faiss

            self._faiss = faiss
            logger.info("FAISS available — vector memory accelerated")
        except ImportError:
            self._faiss = None
            logger.warning("FAISS not installed — using pure-Python fallback")

    # ------------------------------------------------------------------ #
    def add(self, text: str, vector: list[float] | None = None) -> str:
        if vector is None:
            vector = self._embedding_model.encode(text)
        entry = VectorEntry(id=str(len(self._entries)), text=text, vector=vector)
        self._entries.append(entry)
        if self._faiss is not None:
            self._rebuild_faiss()
        return entry.id

    def add_texts(self, texts: list[str]) -> list[str]:
        return [self.add(text) for text in texts]

    # ------------------------------------------------------------------ #
    def _rebuild_faiss(self) -> None:
        if self._faiss is None or not self._entries:
            return
        dim = self._embedding_model.dimension
        self._faiss_index = self._faiss.IndexFlatIP(dim)
        import numpy as np

        matrix = np.array([e.vector for e in self._entries], dtype="float32")
        self._faiss.normalize_L2(matrix)
        self._faiss_index.add(matrix)

    # ------------------------------------------------------------------ #
    def search(self, query: str, k: int = 5) -> list[tuple[VectorEntry, float]]:
        """Return the *k* nearest entries to *query* with similarity scores."""
        query_vector = self._embedding_model.encode(query)
        if self._faiss_index is not None:
            return self._search_faiss(query_vector, k)

        scored = [
            (entry, cosine_similarity(query_vector, entry.vector))
            for entry in self._entries
        ]
        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:k]

    def _search_faiss(self, query_vector: list[float], k: int) -> list[tuple[VectorEntry, float]]:
        import numpy as np

        vec = np.array([query_vector], dtype="float32")
        self._faiss.normalize_L2(vec)
        distances, indices = self._faiss_index.search(vec, k)
        results: list[tuple[VectorEntry, float]] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
            entry = self._entries[int(idx)]
            results.append((entry, float(dist)))
        return results

    # ------------------------------------------------------------------ #
    def clear(self) -> None:
        self._entries.clear()
        self._faiss_index = None
        logger.info("Vector memory cleared")

    @property
    def count(self) -> int:
        return len(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    def remove(self, entry_id: str) -> bool:
        """Remove an entry by ID.

        Returns True if the entry was found and removed, False otherwise.
        Rebuilds FAISS index if present.
        """
        for i, entry in enumerate(self._entries):
            if entry.id == entry_id:
                self._entries.pop(i)
                if self._faiss is not None:
                    self._rebuild_faiss()
                return True
        return False

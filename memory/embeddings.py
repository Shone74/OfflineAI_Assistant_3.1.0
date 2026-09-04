"""Embedding models — turns text into vectors for semantic memory.

The abstract :class:`EmbeddingModel` is implemented by:

* :class:`StubEmbeddingModel` — deterministic pseudo-embedding (no deps, CI-safe).
* :class:`SentenceTransformerEmbeddingModel` — real embeddings if ``sentence-transformers``
  and a model are available.
* :class:`GgufEmbeddingModel` — real embeddings from a local GGUF file via llama-cpp-python.

The project prefers *no* hard dependency on heavy ML packages.  When
``sentence-transformers`` or a model file is missing the stub is used
automatically so the rest of the system keeps working.
"""

from __future__ import annotations

import hashlib
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from core.logger import get_logger

logger = get_logger("embeddings")

_EMBEDDING_DIM = 384


class EmbeddingModel(ABC):
    """Abstract interface for text-to-vector encoding."""

    @abstractmethod
    def encode(self, text: str) -> list[float]:
        """Return the embedding vector for *text*."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimensionality."""

    @property
    def name(self) -> str:
        """Return the model name for display purposes."""
        return self.__class__.__name__

    @property
    def is_stub_fallback(self) -> bool:
        """True when this is a stub used instead of a real model."""
        return False


class StubEmbeddingModel(EmbeddingModel):
    """Deterministic pseudo-embedding based on a stable hash.

    Produces fixed-length vectors with no external dependencies.  The
    vectors are *not* semantically meaningful, but they are reproducible
    which is sufficient for unit tests and demo mode.
    """

    def __init__(self, dim: int = _EMBEDDING_DIM) -> None:
        self._dim = dim
        self._intended_name: str | None = None
        logger.info("StubEmbeddingModel active (dim=%d)", dim)

    def set_intended_name(self, name: str) -> None:
        """Set the name of the backend that failed to load."""
        self._intended_name = name

    @property
    def intended_name(self) -> str | None:
        """Return the name of the backend that was supposed to be used."""
        return self._intended_name

    @property
    def is_stub_fallback(self) -> bool:
        return True

    def encode(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values = [b / 255.0 - 0.5 for b in digest[: self._dim]]
        while len(values) < self._dim:
            values.append(0.0)
        return values[: self._dim]

    @property
    def dimension(self) -> int:
        return self._dim


class SentenceTransformerEmbeddingModel(EmbeddingModel):
    """Real embedding model via ``sentence-transformers``."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        from sentence_transformers import SentenceTransformer

        self._model = SentenceTransformer(model_name)
        self._dim = self._model.get_sentence_embedding_dimension()
        logger.info("SentenceTransformer loaded: %s (dim=%d)", model_name, self._dim)

    def encode(self, text: str) -> list[float]:
        vector = self._model.encode(text).tolist()
        return list(vector)

    @property
    def dimension(self) -> int:
        return self._dim

    @property
    def name(self) -> str:
        return "sentence-transformers"


_DEFAULT_MXBAI_FILENAME = "mxbai-embed-large-v1-f16.gguf"


class GgufEmbeddingModel(EmbeddingModel):
    """Real embedding backend backed by a local GGUF model via llama-cpp-python.

    Loads a local ``*.gguf`` embedding model (e.g.
    ``mxbai-embed-large-v1-f16.gguf``) through ``llama_cpp.Llama`` in embedding
    mode and exposes the ``create_embedding`` API.  The model runs locally —
    no network, no cloud, no telemetry.  ``llama-cpp-python`` is imported
    lazily inside the constructor so the rest of the application keeps working
    when the runtime or the model file is absent; the factory
    :func:`load_embedding_model` catches those failures and falls back to the
    stub.
    """

    def __init__(
        self,
        model_path: str | Path,
        n_ctx: int = 512,
        n_threads: int = 4,
        verbose: bool = False,
    ) -> None:
        from llama_cpp import Llama  # raises ImportError if llama-cpp unavailable

        self._model_path = Path(model_path)
        if not self._model_path.exists():
            raise FileNotFoundError(f"Embedding model not found: {self._model_path}")
        self._llama = Llama(
            model_path=str(self._model_path),
            embedding=True,
            n_ctx=n_ctx,
            n_threads=n_threads,
            verbose=verbose,
        )
        self._dim: int | None = None
        logger.info("GgufEmbeddingModel loaded: %s", self._model_path)

    def encode(self, text: str) -> list[float]:
        result: Any = self._llama.create_embedding(text)
        raw = result.get("data", [])
        vectors: list[list[float]] = [[float(x) for x in d["embedding"]] for d in raw]
        if not vectors:
            raise ValueError(f"No embedding returned for input: {text[:40]!r}")
        if len(vectors) == 1:
            vec = vectors[0]
        else:
            width = len(vectors[0])
            vec = [sum(v[i] for v in vectors) / len(vectors) for i in range(width)]
        if self._dim is None:
            self._dim = len(vec)
        return vec

    @property
    def dimension(self) -> int:
        if self._dim is None:
            self.encode("dimension probe")
        return self._dim or 0

    @property
    def name(self) -> str:
        return "mxbai-gguf"


def _resolve_embedding_model_path(explicit: str | Path | None = None) -> Path | None:
    """Locate the mxbai embedding GGUF on disk, or ``None`` when absent."""
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    env_path = os.environ.get("MXBAI_EMBEDDING_MODEL_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p
    llm_dir: Path | None = None
    try:
        from core.paths import LLM_DIR

        llm_dir = Path(LLM_DIR)
    except Exception:
        llm_dir = None
    candidates = []
    if llm_dir is not None:
        candidates.append(llm_dir / _DEFAULT_MXBAI_FILENAME)
    candidates.extend(
        [
            Path("models") / "llm" / _DEFAULT_MXBAI_FILENAME,
            Path(_DEFAULT_MXBAI_FILENAME),
        ]
    )
    for c in candidates:
        if c.exists():
            return c
    return None


def load_embedding_model(name: str = "stub", model_path: str | None = None) -> EmbeddingModel:
    """Factory — returns a stub unless a real model is requested and available.

    ``"mxbai-gguf"`` (aliases ``"gguf"`` / ``"mxbai"``) returns a
    :class:`GgufEmbeddingModel` when the llama-cpp runtime and a model file are
    available; otherwise it falls back to the stub, matching the existing
    ``sentence-transformers`` fallback behaviour.
    
    When falling back to stub, the stub's ``intended_name`` property is set to
    the requested backend name so the UI can inform the user that semantic
    retrieval is NOT active.
    """
    if name in ("mxbai-gguf", "gguf", "mxbai"):
        try:
            from ai.models.model_loader import has_llama_cpp

            if not has_llama_cpp():
                raise ImportError("llama-cpp-python runtime unavailable")
            resolved = _resolve_embedding_model_path(model_path)
            if resolved is None:
                raise FileNotFoundError("mxbai GGUF embedding model not found")
            return GgufEmbeddingModel(resolved)
        except Exception:
            logger.warning("Gguf embedding model unavailable — falling back to stub")
            stub = StubEmbeddingModel()
            stub.set_intended_name(name)
            return stub
    if name == "sentence-transformers":
        try:
            return SentenceTransformerEmbeddingModel()
        except Exception:
            logger.warning("sentence-transformers unavailable — falling back to stub")
            stub = StubEmbeddingModel()
            stub.set_intended_name(name)
            return stub
    if name == "stub":
        return StubEmbeddingModel()
    stub = StubEmbeddingModel()
    stub.set_intended_name(name)
    return stub


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two equal-length vectors."""
    if len(a) != len(b):
        raise ValueError("Vectors must be the same length")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(y * y for y in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)

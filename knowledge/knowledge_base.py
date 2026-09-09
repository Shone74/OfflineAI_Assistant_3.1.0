"""Knowledge base — indexes documents and retrieves relevant chunks.

Built on top of the existing :class:`memory.vector_memory.VectorMemory`
(FAISS or pure-Python fallback) and :class:`memory.embeddings.EmbeddingModel`
(transformers or stub).  All heavy dependencies are optional; with only the
stubs the knowledge base still works end-to-end (deterministic embeddings).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from knowledge.document_loader import DocumentLoader
from knowledge.models import Document, KnowledgeChunk, SearchResult
from memory.embeddings import EmbeddingModel, load_embedding_model
from memory.vector_memory import VectorMemory


class KnowledgeBase:
    """Vector-backed document store with nearest-neighbour search."""

    def __init__(
        self,
        embedding_model: EmbeddingModel | None = None,
        vector_memory: VectorMemory | None = None,
        loader: DocumentLoader | None = None,
    ) -> None:
        self._embedding_model = embedding_model or load_embedding_model("stub")
        self._vector = vector_memory or VectorMemory(self._embedding_model)
        self._loader = loader or DocumentLoader()
        self._documents: dict[str, Document] = {}
        self._chunk_map: dict[str, KnowledgeChunk] = {}

    @property
    def embedding_model(self) -> EmbeddingModel:
        return self._embedding_model

    @property
    def vector_store(self) -> VectorMemory:
        return self._vector

    def index_document(self, path: str | Path) -> int:
        """Parse and index a single document. Returns the number of chunks.

        Normalizes the path to an absolute resolved path to ensure
        consistent document identification across load/index cycles.
        If indexing fails partway through, any partially added chunks
        are rolled back so the knowledge base stays consistent.
        """
        path_obj = Path(path).resolve()
        for d in self._documents.values():
            if Path(d.path).resolve() == path_obj:
                return 0
        doc = self._loader.load(path_obj)
        added_ids: list[str] = []
        try:
            for chunk in doc.chunks:
                vid = self._vector.add(chunk.text)
                chunk.vector_id = vid
                self._chunk_map[vid] = chunk
                added_ids.append(vid)
        except Exception:
            for vid in added_ids:
                self._vector.remove(vid)
                self._chunk_map.pop(vid, None)
            raise
        self._documents[doc.id] = doc
        return len(doc.chunks)

    def index_directory(
        self,
        directory: str | Path,
        patterns: tuple[str, ...] = ("*.md", "*.txt"),
    ) -> int:
        """Index every file matching *patterns* beneath *directory*.

        PHASE 8 integration rules:

        * The walk is symlink/junction-safe: link directories are never
          descended into, so indexing cannot escape the authorized
          knowledge root through a planted link (same contract as the
          project workspace enumeration).
        * Temporary downloader artifacts (``*.part``) and hidden files
          are skipped — a partial download must never enter the index.
        * Each candidate file still passes the shared filesystem
          security boundary's READ authorization when the validator is
          configured; unauthorized files are skipped, not leaked.
        """
        root = Path(directory)
        total = 0
        from core.logger import get_logger

        log = get_logger("knowledge")

        try:
            from tools.file_security import get_default_validator

            validator = get_default_validator()
        except Exception:
            validator = None

        # Stack-based, link-safe walk (never follows symlinked dirs).
        stack: list[Path] = [root]
        while stack:
            current = stack.pop()
            try:
                entries = sorted(current.iterdir())
            except OSError as exc:
                log.debug("Cannot list %s during indexing: %s", current, exc)
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue  # never descend through links
                    if entry.is_dir():
                        stack.append(entry)
                        continue
                    if not entry.is_file():
                        continue
                    if entry.name.startswith("."):
                        continue
                    if entry.suffix.lower() == ".part":
                        continue  # incomplete downloader artifact
                    if not any(entry.match(p) for p in patterns):
                        continue
                    if validator is not None:
                        try:
                            validator.validate_read(str(entry))
                        except Exception:
                            log.debug(
                                "Skipping unauthorized file during indexing: %s",
                                entry,
                            )
                            continue
                    total += self.index_document(entry)
                except OSError as exc:
                    log.debug("Skipping %s during indexing: %s", entry, exc)
                    continue
        return total

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """Return the *top_k* most relevant chunks for *query*."""
        results = self._vector.search(query, k=top_k)
        out: list[SearchResult] = []
        for entry, score in results:
            chunk = self._chunk_map.get(entry.id)
            if chunk is None:
                continue
            doc = self._documents.get(chunk.doc_id)
            title = doc.title if doc else chunk.doc_id
            out.append(SearchResult(score=score, chunk=chunk, doc_title=title))
        return out

    def get_statistics(self) -> dict[str, Any]:
        """Return knowledge base statistics."""
        total_chunks = sum(len(doc.chunks) for doc in self._documents.values())
        total_size = sum(len(chunk.text) for doc in self._documents.values() for chunk in doc.chunks)
        doc_types: dict[str, int] = {}
        for doc in self._documents.values():
            doc_types[doc.format] = doc_types.get(doc.format, 0) + 1
        latest = max(
            (doc.created_at for doc in self._documents.values()),
            default="N/A",
        )
        return {
            "total_documents": len(self._documents),
            "total_chunks": total_chunks,
            "total_characters": total_size,
            "document_types": doc_types,
            "last_indexed": latest,
        }

    def export_to_dict(self) -> dict[str, Any]:
        """Export knowledge base to a serializable dict."""
        return {
            "documents": [
                {
                    "id": doc.id,
                    "filename": doc.title,
                    "path": doc.path,
                    "format": doc.format,
                    "chunks": len(doc.chunks),
                    "created_at": doc.created_at,
                }
                for doc in self._documents.values()
            ],
            "statistics": self.get_statistics(),
        }

    def export_to_markdown(self) -> str:
        """Export knowledge base as Markdown."""
        lines = ["# Knowledge Base Export\n"]
        stats = self.get_statistics()
        lines.append(f"**Documents:** {stats['total_documents']}\n")
        lines.append(f"**Chunks:** {stats['total_chunks']}\n")
        lines.append(f"**Last indexed:** {stats['last_indexed']}\n\n")
        for doc in self._documents.values():
            lines.append(f"## {doc.title}\n")
            lines.append(f"- **Path:** {doc.path}\n")
            lines.append(f"- **Format:** {doc.format}\n")
            lines.append(f"- **Chunks:** {len(doc.chunks)}\n\n")
            for i, chunk in enumerate(doc.chunks[:3], 1):
                lines.append(f"### Chunk {i}\n")
                lines.append(f"```\n{chunk.text[:500]}\n```\n\n")
        return "\n".join(lines)

    def clear(self) -> None:
        self._documents.clear()
        self._chunk_map.clear()
        self._vector.clear()

    def count(self) -> int:
        return self._vector.count

    # ------------------------------------------------------------------ #
    # Rebuild Index
    # ------------------------------------------------------------------ #
    def rebuild(
        self, directory: str | Path, patterns: tuple[str, ...] = ("*.md", "*.txt")
    ) -> int:
        """Clear and re-index knowledge from a directory.

        Clears all existing indexed knowledge and rebuilds from the current
        contents of the specified directory. This is useful when the user
        wants a fresh index reflecting the current file system state.

        Args:
            directory: Path to the directory to index.
            patterns: File patterns to match (default: *.md, *.txt).

        Returns:
            Total number of chunks indexed.
        """
        self.clear()
        return self.index_directory(directory, patterns)

    # ------------------------------------------------------------------ #
    # Document deletion
    # ------------------------------------------------------------------ #
    def delete_document(self, doc_id: str) -> bool:
        """Delete a document and all its associated chunks from the knowledge base.

        Args:
            doc_id: The document ID to delete.

        Returns:
            True if the document was found and deleted, False otherwise.
        """
        doc = self._documents.get(doc_id)
        if doc is None:
            return False

        for chunk in doc.chunks:
            if chunk.vector_id is not None:
                self._vector.remove(chunk.vector_id)
                self._chunk_map.pop(chunk.vector_id, None)

        del self._documents[doc_id]
        return True

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    _PERSISTENCE_VERSION = 1

    def save_file(self, path: str | Path) -> None:
        """Save knowledge base metadata to a JSON file for persistence.

        Only persists document metadata (id, filename, path, format, created_at).
        The in-memory vector index is NOT saved; it will be rebuilt on load
        by re-indexing the source files.

        Uses atomic write: writes to temp file then renames to target.
        """
        import json
        import tempfile

        path_obj = Path(path)
        path_obj.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": self._PERSISTENCE_VERSION,
            "documents": [
                {
                    "id": doc.id,
                    "filename": doc.title,
                    "path": doc.path,
                    "format": doc.format,
                    "created_at": doc.created_at,
                }
                for doc in self._documents.values()
            ],
        }
        fd, temp_path = tempfile.mkstemp(
            dir=path_obj.parent, prefix=".kb_temp_", suffix=".json"
        )
        try:
            with open(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            Path(temp_path).replace(path_obj)
        except Exception:
            import os

            os.unlink(temp_path)
            raise

    def load_file(self, path: str | Path) -> int:
        """Load knowledge base metadata from a JSON file.

        Restores documents by re-indexing their source files.
        Returns the number of documents successfully restored.
        Does NOT crash if the file is missing or malformed.
        Logs warnings for missing source files.
        """
        import json

        from core.logger import get_logger

        logger = get_logger("knowledge")
        path_obj = Path(path)

        if not path_obj.exists():
            return 0

        try:
            with open(path_obj, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to parse knowledge persistence file %s: %s", path_obj, e)
            return 0

        if not isinstance(data, dict):
            logger.warning("Invalid knowledge persistence format in %s", path_obj)
            return 0

        docs_data = data.get("documents", [])
        if not isinstance(docs_data, list):
            logger.warning("Invalid documents list in persistence file %s", path_obj)
            return 0

        loaded = 0
        for doc_data in docs_data:
            if not isinstance(doc_data, dict):
                continue
            doc_path = doc_data.get("path", "")
            if not doc_path:
                continue
            source_path = Path(doc_path)
            if not source_path.exists():
                logger.warning(
                    "Source file missing for persisted document: %s", doc_path
                )
                continue
            try:
                count = self.index_document(source_path)
                if count > 0:
                    loaded += 1
            except Exception as e:
                logger.warning("Failed to index persisted document %s: %s", doc_path, e)

        return loaded

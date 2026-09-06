"""Tests for the Knowledge dashboard stub-embedding warning (Task B2).

Invariant: the Knowledge dashboard shows a warning banner when the active
embedding backend is a stub (no real semantic model) and keeps it hidden
when a real embedding model is available.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ui.knowledge_dashboard import KnowledgeDashboard


class _FakeMemory:
    """Duck-typed MemoryManager — only get_embedding_model_info() is needed."""

    def __init__(self, is_stub: bool) -> None:
        self._info = {
            "name": "stub" if is_stub else "sentence-transformers",
            "is_stub": is_stub,
            "intended_name": None if is_stub else "sentence-transformers",
            "dimension": 64,
        }

    def get_embedding_model_info(self) -> dict:
        return self._info


class _FakeAssistant:
    """Duck-typed Assistant — only the memory backend attribute is needed."""

    def __init__(self, is_stub: bool) -> None:
        self._memory = _FakeMemory(is_stub)


class TestKnowledgeEmbeddingWarning:
    def test_constructs_without_assistant(self, qapp) -> None:
        """Backward compatibility: no assistant -> dashboard works, warning hidden."""
        dashboard = KnowledgeDashboard()
        assert dashboard._embedding_warning is not None
        assert dashboard._embedding_warning.isHidden()

    def test_stub_embeddings_show_warning(self, qapp) -> None:
        dashboard = KnowledgeDashboard(assistant=_FakeAssistant(is_stub=True))
        assert not dashboard._embedding_warning.isHidden()
        assert dashboard._embedding_warning.objectName() == "banner_warning"
        assert "stub" in dashboard._embedding_warning._label.text().lower()

    def test_real_embeddings_hide_warning(self, qapp) -> None:
        dashboard = KnowledgeDashboard(assistant=_FakeAssistant(is_stub=False))
        assert dashboard._embedding_warning.isHidden()

    def test_refresh_updates_warning(self, qapp) -> None:
        """refresh_embedding_status() re-reads the backend and toggles the banner."""
        dashboard = KnowledgeDashboard(assistant=_FakeAssistant(is_stub=False))
        assert dashboard._embedding_warning.isHidden()
        dashboard._assistant = _FakeAssistant(is_stub=True)
        dashboard.refresh_embedding_status()
        assert not dashboard._embedding_warning.isHidden()

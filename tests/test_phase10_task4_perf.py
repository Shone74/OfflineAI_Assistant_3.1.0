"""Phase 10 Task 4 — performance reliability regression tests.

Covers the approved fixes:
  M5  — single _start_generation_worker definition (no busy-wait duplicate)
  H3  — knowledge search/index run OFF the GUI thread
  H4  — ModelManager discovery cache (unchanged inputs → cached result)
  M7  — incremental semantic memory index (additions only embed new rows)
  M8  — messages(conversation_id) index exists and is used
  M9  — ConfigManager write coalescing (burst → single trailing flush)
  L10 — append_streaming_token has no per-token processEvents
"""

from __future__ import annotations

import inspect
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# --------------------------------------------------------------------------- #
# M5 — duplicate worker removal
# --------------------------------------------------------------------------- #
class TestM5SingleGenerationWorker:
    def test_single_start_generation_worker_definition(self):
        """The busy-wait duplicate is gone; exactly ONE definition of
        _start_generation_worker exists in main_window.py."""
        import inspect

        import ui.main_window as mw

        source = inspect.getsource(mw)
        count = source.count("def _start_generation_worker(")
        assert count == 1, f"expected 1 definition, found {count}"
        # And the surviving version uses the nested QEventLoop, not a
        # processEvents polling loop.
        fn_source = inspect.getsource(mw.MainWindow._start_generation_worker)
        assert "QEventLoop" in fn_source
        assert "while not done.is_set()" not in fn_source


# --------------------------------------------------------------------------- #
# H3 — knowledge operations off the GUI thread
# --------------------------------------------------------------------------- #
class TestH3KnowledgeOffGuiThread:
    def test_knowledge_search_runs_on_worker_thread(self, qapp):
        """MainWindow._on_knowledge_search dispatches a QThread worker:
        the heavy search runs off the GUI thread and results arrive via
        a queued signal."""
        from ui.knowledge_worker import KnowledgeSearchWorker

        executed_threads: list[int] = []
        results: list = []

        class _FakeAssistant:
            def run_knowledge_search(self, q):
                executed_threads.append(threading.get_ident())
                return f"context for {q}", [{"doc": "d1"}]

        worker = KnowledgeSearchWorker(_FakeAssistant().run_knowledge_search, "query")
        worker.search_completed.connect(lambda ctx, res: results.append((ctx, res)))
        worker.start()
        assert worker.wait(5000)

        from PySide6.QtCore import QCoreApplication

        for _ in range(10):
            QCoreApplication.processEvents()

        assert executed_threads, "search never ran"
        assert executed_threads[0] != threading.get_ident()
        assert results and results[0][0] == "context for query"

    def test_knowledge_index_runs_on_worker_thread(self, qapp):
        from ui.knowledge_worker import KnowledgeIndexWorker

        executed_threads: list[int] = []
        completed: list = []

        class _FakeKnowledge:
            def index_directory(self, directory):
                executed_threads.append(threading.get_ident())
                return 7

        worker = KnowledgeIndexWorker(_FakeKnowledge(), "index_directory", "C:/docs")
        worker.index_completed.connect(lambda n, op: completed.append((n, op)))
        worker.start()
        assert worker.wait(5000)

        from PySide6.QtCore import QCoreApplication

        for _ in range(10):
            QCoreApplication.processEvents()

        assert executed_threads and executed_threads[0] != threading.get_ident()
        assert completed == [(7, "index_directory")]

    def test_main_window_search_handler_uses_worker(self):
        """Source contract: _on_knowledge_search delegates to the worker
        helper instead of calling run_knowledge_search inline."""
        import ui.main_window as mw

        src = inspect.getsource(mw.MainWindow._on_knowledge_search)
        assert "run_knowledge_search" not in src
        assert "start_knowledge_search" in src

    def test_appshell_knowledge_dashboard_is_wired(self):
        """H3 gap fix: the final AppShell KnowledgeDashboard signals are
        connected (previously unconnected → dead buttons)."""
        import app.application_final as af

        src = inspect.getsource(af._wire_knowledge_dashboard)
        for signal in (
            "search_requested",
            "index_requested",
            "index_file_requested",
            "rebuild_requested",
            "delete_requested",
        ):
            assert signal in src


# --------------------------------------------------------------------------- #
# H4 — discovery cache
# --------------------------------------------------------------------------- #
class TestH4DiscoveryCache:
    def _manager(self, tmp_path):
        from ai.models.model_manager import ModelManager

        llm = tmp_path / "llm"
        llm.mkdir(parents=True, exist_ok=True)
        return ModelManager(
            models_dir=llm, include_ollama=False, include_lm_studio=False
        )

    def test_rescan_reuses_cache_when_inputs_unchanged(self, tmp_path, monkeypatch):
        """Second rescan with unchanged inputs performs NO new
        filesystem discovery walk — the cached result is returned."""
        from ai.models import model_manager as mm_mod

        mm = self._manager(tmp_path)
        calls: list = []
        original = mm_mod.discover_all_models

        def _counting(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(mm_mod, "discover_all_models", _counting)
        mm.rescan()          # inputs unchanged since __init__ → cache hit
        mm.rescan()          # still unchanged → cache hit
        assert calls == []

    def test_rescan_force_bypasses_cache(self, tmp_path, monkeypatch):
        from ai.models import model_manager as mm_mod

        mm = self._manager(tmp_path)
        calls: list = []
        original = mm_mod.discover_all_models

        def _counting(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(mm_mod, "discover_all_models", _counting)
        mm.rescan_force()
        assert len(calls) == 1
        mm.rescan_force()
        assert len(calls) == 2

    def test_cache_miss_after_new_file(self, tmp_path):
        """The refresh button path (rescan_force) sees newly added files
        even when the cached inputs are unchanged."""
        llm = tmp_path / "llm"
        llm.mkdir(parents=True, exist_ok=True)
        (llm / "new.gguf").write_bytes(b"GGUF")
        mm = self._manager(tmp_path)
        mm.rescan_force()
        names = [m.name for m in mm.list_models()]
        assert any("new" in n for n in names)

    def test_set_models_dir_invalidates_cache(self, tmp_path, monkeypatch):
        """Changing the scan input triggers a REAL rescan."""
        from ai.models import model_manager as mm_mod

        mm = self._manager(tmp_path)
        calls: list = []
        original = mm_mod.discover_all_models

        def _counting(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        monkeypatch.setattr(mm_mod, "discover_all_models", _counting)
        other = tmp_path / "llm2"
        other.mkdir(parents=True, exist_ok=True)
        mm.set_models_dir(other)
        assert len(calls) == 1  # input change → real scan
        mm.rescan()             # unchanged again → cache hit
        assert len(calls) == 1


# --------------------------------------------------------------------------- #
# M7 — incremental semantic index
# --------------------------------------------------------------------------- #
class TestM7IncrementalSemanticIndex:
    def _memory(self, tmp_path):
        """MemoryManager with its DatabaseManager patched to a temp DB
        (the constructor always uses the default DB location)."""
        import memory.memory_manager as mm_mod

        real_db_cls = mm_mod.DatabaseManager

        def _temp_db(*args, **kwargs):
            return real_db_cls(db_path=tmp_path / "test.db")

        original_init = mm_mod.MemoryManager.__init__

        def _patched_init(self, *args, **kwargs):
            saved = mm_mod.DatabaseManager
            mm_mod.DatabaseManager = _temp_db
            try:
                original_init(self, *args, **kwargs)
            finally:
                mm_mod.DatabaseManager = saved

        # One-off construction with the patch active.
        saved_cls_init = mm_mod.MemoryManager.__init__
        mm_mod.MemoryManager.__init__ = _patched_init
        try:
            mgr = mm_mod.MemoryManager()
        finally:
            mm_mod.MemoryManager.__init__ = saved_cls_init
        return mgr

    def test_adding_memory_embeds_only_new_rows(self, tmp_path):
        """After the first search builds the index, adding ONE memory
        and searching again embeds only the new row — the existing
        embeddings are reused (no full re-embed)."""
        memory = self._memory(tmp_path)
        memory.save_memory("first fact", "fact")
        memory.save_memory("second fact", "fact")
        memory.semantic_search("fact", k=2)  # builds index over 2 rows
        assert memory._memory_index_count == 2

        embed_calls: list = []
        original_add = memory._memory_index.add

        def _counting_add(text, vector=None):
            embed_calls.append(text)
            return original_add(text, vector)

        memory._memory_index.add = _counting_add
        memory.save_memory("third fact", "fact")
        memory.semantic_search("fact", k=3)

        # Only the NEW row is embedded, not all three.
        assert embed_calls == ["third fact"]
        assert memory._memory_index_count == 3

    def test_deleting_memory_rebuilds_index(self, tmp_path):
        memory = self._memory(tmp_path)
        m1 = memory.save_memory("alpha", "fact")
        memory.save_memory("beta", "fact")
        memory.semantic_search("alpha", k=2)
        memory.delete_memory(m1)
        # Count dropped below watermark → next search fully rebuilds.
        memory.semantic_search("beta", k=2)
        assert memory._memory_index_count == 1


# --------------------------------------------------------------------------- #
# M8 — messages(conversation_id) index
# --------------------------------------------------------------------------- #
class TestM8MessagesIndex:
    def test_index_exists_and_query_uses_it(self, tmp_path):
        from database.database_manager import DatabaseManager

        db = DatabaseManager(db_path=tmp_path / "idx.db")
        indexes = db.query(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='messages'"
        )
        names = {r["name"] for r in indexes}
        assert "idx_messages_conversation_id" in names

        # The conversation filter actually uses the index.
        plan = db.query(
            "EXPLAIN QUERY PLAN SELECT * FROM messages WHERE conversation_id = 42"
        )
        plan_str = " ".join(str(r["detail"]) for r in plan)
        assert "USING INDEX idx_messages_conversation_id" in plan_str or (
            "SCAN" in plan_str and "USING INDEX" in plan_str
        )

    def test_migration_version_recorded(self, tmp_path):
        from database.database_manager import DatabaseManager

        db = DatabaseManager(db_path=tmp_path / "mig.db")
        rows = db.query("SELECT version FROM migrations ORDER BY version")
        versions = [r["version"] for r in rows]
        assert 9 in versions


# --------------------------------------------------------------------------- #
# M9 — config write coalescing
# --------------------------------------------------------------------------- #
class TestM9ConfigWriteCoalescing:
    def test_first_set_persists_immediately(self, tmp_path):
        """A single set() (wizard finalize, critical keys) is durable
        WITHOUT waiting for the flush timer — the file is on disk before
        set() returns."""
        from core.config_manager import ConfigManager

        path = tmp_path / "settings.json"
        cfg = ConfigManager(settings_path=path)
        cfg.set("models.storage_root", "X:/root")
        assert path.exists()
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["models"]["storage_root"] == "X:/root"

    def test_burst_coalesces_to_single_flush(self, tmp_path):
        """Rapid successive sets (slider ticks) produce ONE trailing
        flush containing ALL values — not one write per tick."""
        import json

        from core.config_manager import ConfigManager

        path = tmp_path / "settings.json"
        cfg = ConfigManager(settings_path=path)
        # Prime the window so the burst is coalesced.
        cfg.set("voice.tts.rate", 100)
        save_calls: list = []
        original_save = cfg.save

        def _counting_save():
            save_calls.append(1)
            original_save()

        cfg.save = _counting_save
        try:
            for value in (1, 2, 3, 4, 5):
                cfg.set("ui.slider", value)
                # in-memory value always current
                assert cfg.get("ui.slider") == value
        finally:
            pass
        # All burst writes coalesced: at most the single trailing flush
        # has run yet (it is async — wait briefly for it).
        assert len(save_calls) <= 1
        deadline = time.monotonic() + 3.0
        while len(save_calls) == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert len(save_calls) >= 1
        # Wait for the flush to complete, then verify final state on disk.
        deadline = time.monotonic() + 3.0
        while True:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if data.get("ui", {}).get("slider") == 5:
                    break
            except Exception:
                pass
            if time.monotonic() > deadline:
                pytest.fail("coalesced flush did not persist the final value")
            time.sleep(0.05)
        assert data["ui"]["slider"] == 5


# --------------------------------------------------------------------------- #
# L10 — no per-token processEvents in the streaming append
# --------------------------------------------------------------------------- #
class TestL10StreamingNoEventPump:
    def test_append_streaming_token_has_no_process_events(self):
        import ui.chat_widget as cw

        src = inspect.getsource(cw.ChatWidget.append_streaming_token)
        # No CALL to the event pump (prose may mention the word).
        assert "QApplication.processEvents()" not in src
        assert ".processEvents()" not in src

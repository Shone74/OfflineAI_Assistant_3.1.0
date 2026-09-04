"""Baseline regression smoke tests — "zlatno stanje" aplikacije.

Cilj (docs/project_plan.md, korak 0.3): uhvatiti funkcionalnost koja MORA
ostati ispravna kroz ceo redizajn. Svaki test je namerno mali i headless
(OFFLINE_AI_TEST_MODE=1 iz conftest.py).

Pokriva: EventBus, ConfigManager, model discovery/manager, stub engine,
memoriju (3 sloja), RAG pipeline, tool registry, security sloj, agent
repository, database migracije, AppShell.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_LLM_DIR = PROJECT_ROOT / "models" / "llm"


# --- core: EventBus / ConfigManager ----------------------------------------

class TestCoreServices:
    def test_event_bus_pubsub(self):
        from core.event_bus import EventBus

        bus = EventBus()
        received: list[str] = []

        def handler(event_type, payload):
            received.append(payload)

        bus.subscribe("test.event", handler)
        bus.publish("test.event", "payload-1")
        assert received == ["payload-1"]

    def test_event_bus_unsubscribe(self):
        from core.event_bus import EventBus

        bus = EventBus()
        received: list[str] = []

        def handler(event_type, payload):
            received.append(payload)

        sub_id = bus.subscribe("test.event", handler)
        bus.unsubscribe("test.event", sub_id)
        bus.publish("test.event", "payload-2")
        assert received == []

    def test_config_manager_reads_defaults(self, tmp_path):
        from core.config_manager import ConfigManager

        manager = ConfigManager(settings_path=tmp_path / "settings.json")
        assert manager.get("app.name") == "Offline AI Assistant"
        assert manager.get("ai.n_ctx") > 0

    def test_config_manager_roundtrip(self, tmp_path):
        from core.config_manager import ConfigManager

        settings_path = tmp_path / "settings.json"
        manager = ConfigManager(settings_path=settings_path)
        manager.set("smoke.test_key", "value-123")
        manager.save()

        second = ConfigManager(settings_path=settings_path)
        assert second.get("smoke.test_key") == "value-123"


# --- ai: model discovery / manager / engine ---------------------------------

class TestModelSystem:
    def test_discovery_finds_project_models(self):
        from ai.models.discovery import discover_all_models
        from ai.models.model_loader import ModelType

        models = discover_all_models(
            search_paths=[PROJECT_LLM_DIR],
            include_ollama=False,
            include_lm_studio=False,
        )
        names = [m.name for m in models]
        assert any("Qwen2.5-Coder-7B" in n for n in names), f"Qwen2.5-Coder-7B nije pronadjen: {names}"
        assert any("Phi-4-mini" in n for n in names), f"Phi-4-mini nije pronadjen: {names}"
        chat_models = [m for m in models if m.model_type in (ModelType.LLM, ModelType.VISION_LLM)]
        assert len(chat_models) >= 2

    def test_discovered_model_capabilities(self):
        from ai.models.discovery import discover_all_models

        models = discover_all_models(
            search_paths=[PROJECT_LLM_DIR],
            include_ollama=False,
            include_lm_studio=False,
        )
        qwen = next((m for m in models if "Qwen2.5-Coder-7B" in m.name), None)
        assert qwen is not None
        assert qwen.capabilities.text_generation is True
        assert qwen.capabilities.tool_calling is True

    def test_discovery_all_sources_no_crash(self):
        """discover_all_models() sa svim izvorima (ukljucujuci Ollama env) ne sme da padne."""
        from ai.models.discovery import discover_all_models

        models = discover_all_models()
        assert isinstance(models, list)
        assert len(models) >= 2  # bar 2 projektna modela

    def test_model_manager_test_mode_stub(self, tmp_path):
        from ai.models.model_manager import ModelManager

        manager = ModelManager(
            models_dir=tmp_path,
            search_paths=[tmp_path],
            include_ollama=False,
            include_lm_studio=False,
        )
        manager.rescan()
        loader = manager.get_loader()
        assert loader is not None
        assert getattr(loader, "is_stub", False) is True

    def test_model_manager_rescan_lists_models(self):
        from ai.models.model_manager import ModelManager

        manager = ModelManager(
            models_dir=PROJECT_LLM_DIR,
            search_paths=[PROJECT_LLM_DIR],
            include_ollama=False,
            include_lm_studio=False,
        )
        manager.rescan()
        names = [m.name for m in manager.list_models()]
        assert any("Qwen2.5-Coder-7B" in n for n in names)

    def test_stub_engine_generate(self):
        from ai.engine.llm_engine import StubEngine

        engine = StubEngine()
        assert engine.is_ready is True
        out = engine.generate("Pozdrav")
        assert isinstance(out, str) and len(out) > 0

    def test_gguf_metadata_reader_on_project_model(self):
        from ai.models.model_loader import _read_gguf_metadata

        model_path = PROJECT_LLM_DIR / "Qwen2.5-Coder-7B-Q4_K_M.gguf"
        if not model_path.exists():
            pytest.skip("Model nije kopiran u projekat")
        meta = _read_gguf_metadata(model_path)
        assert meta is not None
        assert meta.get("general.architecture") == "qwen2"


# --- memory: 3 sloja ---------------------------------------------------------

class TestMemorySystem:
    def test_short_term_memory_window(self):
        from memory.short_term import ShortTermMemory

        stm = ShortTermMemory(max_window=3)
        for i in range(5):
            stm.add_user(f"msg-{i}")
        assert len(stm.get_history()) <= 3

    def test_short_term_memory_roles(self):
        from memory.short_term import ShortTermMemory

        stm = ShortTermMemory()
        stm.add_user("pitanje")
        stm.add_assistant("odgovor")
        history = stm.get_history()
        assert len(history) == 2

    def test_long_term_memory_roundtrip(self, tmp_path):
        from database.database_manager import DatabaseManager
        from memory.long_term import LongTermMemory, MemoryEntry

        db = DatabaseManager(db_path=tmp_path / "assistant.db")
        ltm = LongTermMemory(db=db)
        ltm.save_memory(MemoryEntry(content="Znam da je test zelen"))
        results = ltm.search_memories()
        assert any("zelen" in str(getattr(r, "content", r)).lower() for r in results)
        db.close()

    def test_vector_memory_stub_knn(self):
        from memory.embeddings import StubEmbeddingModel
        from memory.vector_memory import VectorMemory

        vm = VectorMemory(embedding_model=StubEmbeddingModel())
        vm.add_texts(["asistent radi lokalno", "vremenska prognoza za sutra"])
        # Stub embedding je deterministicki hash — samo proveravamo da pretraga
        # vrati rezultate sa validnim skorovima (kNN radi bez crash-a).
        hits = vm.search("radi li lokalno?", k=2)
        assert len(hits) == 2
        for entry, score in hits:
            assert isinstance(score, float)
        texts = {getattr(entry, "text", str(entry)) for entry, _ in hits}
        assert texts == {"asistent radi lokalno", "vremenska prognoza za sutra"}


# --- knowledge: RAG ----------------------------------------------------------

class TestKnowledgeSystem:
    def test_document_loader_txt(self, tmp_path):
        from knowledge.document_loader import DocumentLoader

        doc = tmp_path / "notes.txt"
        doc.write_text("Offline AI asistent radi lokalno.", encoding="utf-8")
        loader = DocumentLoader()
        document = loader.load(doc)
        whole_text = str(document)
        content = getattr(document, "content", None)
        if content is None:
            content = " ".join(
                str(getattr(c, "content", c)) for c in getattr(document, "chunks", [])
            )
        assert "lokalno" in (content or whole_text).lower()

    def test_rag_pipeline_index_and_retrieve(self, tmp_path):
        from knowledge.knowledge_base import KnowledgeBase
        from memory.embeddings import StubEmbeddingModel
        from memory.vector_memory import VectorMemory

        doc = tmp_path / "faq.md"
        doc.write_text(
            "# FAQ\n\nOffline AI Assistant radi 100% lokalno bez interneta.\n",
            encoding="utf-8",
        )
        vm = VectorMemory(embedding_model=StubEmbeddingModel())
        kb = KnowledgeBase(vector_memory=vm)
        kb.index_document(doc)
        results = kb.search("radi li lokalno?")
        assert isinstance(results, list)


# --- tools + security ---------------------------------------------------------

class TestToolsAndSecurity:
    def test_tool_registry_workflow(self):
        from tools.base import ToolRegistry
        from tools.system_tools import SystemMonitorTool

        registry = ToolRegistry()
        # Prazan registry je validno pocetno stanje
        assert registry.list_tools() == []

        tool = SystemMonitorTool()
        registry.register(tool)
        assert registry.get(tool.name) is not None
        assert tool.name in registry.list_all_tool_names()

    def test_tool_execution_flow(self):
        from tools.base import ToolRegistry
        from tools.system_tools import SystemMonitorTool

        registry = ToolRegistry()
        tool = SystemMonitorTool()
        registry.register(tool)
        result = registry.execute(tool.name, {})
        assert result is not None

    def test_tool_discovery_service(self, tmp_path):
        from core.config_manager import ConfigManager
        from tools.discovery import ToolDiscoveryService

        config = ConfigManager(settings_path=tmp_path / "settings.json")
        service = ToolDiscoveryService(config=config)
        report = service.discover()
        assert report is not None

    def test_security_permission_flow(self):
        from security.permission_manager import PermissionManager

        pm = PermissionManager()
        decision = pm.decide("system.info")
        assert decision is not None

    def test_path_validation_blocks_traversal(self, tmp_path):
        from tools.file_security import PathValidationError, PathValidator

        validator = PathValidator(read_roots=[tmp_path], write_roots=[tmp_path])
        # Validna citanja unutar root-a prolaze
        ok_path = validator.validate_read(str(tmp_path / "notes.txt"))
        assert ok_path is not None
        # Traversal ispod root-a baca gresku
        with pytest.raises(PathValidationError):
            validator.validate_read(str(tmp_path / "sub" / ".." / ".." / "secret.txt"))


# --- agent ---------------------------------------------------------------------

class TestAgentSystem:
    def test_stub_planner_produces_plan(self):
        from agent.planner import StubPlanner

        planner = StubPlanner()
        plan = planner.plan("Koliko je sati?")
        assert plan is not None

    def test_agent_repository_roundtrip(self, tmp_path):
        from agent.repository import Agent, AgentRepository
        from database.database_manager import DatabaseManager

        db = DatabaseManager(db_path=tmp_path / "assistant.db")
        repo = AgentRepository(db=db)
        repo.create_agent(
            Agent(
                name="smoke-agent",
                description="Agent kreiran u smoke testu",
                system_prompt="Ti si test agent.",
            )
        )
        agents = repo.list_agents()
        assert any(getattr(a, "name", "") == "smoke-agent" for a in agents)
        db.close()


# --- database --------------------------------------------------------------------

class TestDatabase:
    def test_database_manager_tables(self, tmp_path):
        from database.database_manager import DatabaseManager

        db = DatabaseManager(db_path=tmp_path / "assistant.db")
        rows = db.query("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row["name"] for row in rows}
        assert {"conversations", "messages"} <= tables
        db.close()


# --- UI: AppShell (postojece ponasanje) --------------------------------------------

class TestUiShell:
    def test_app_shell_creation_and_navigation(self, qapp):
        from PySide6.QtWidgets import QWidget

        from ui.app_shell import AppShell

        home = QWidget()
        chat = QWidget()
        shell = AppShell(theme=None, pages=[("Home", home), ("Chat", chat)])
        assert shell._default_route == "Home"
        shell._navigate("Chat")
        assert shell._pages_widget.currentWidget() is chat
        shell._navigate("Nonexistent")
        assert shell._pages_widget.currentWidget() is chat  # ostaje na poslednjoj validnoj

    def test_home_page_creates(self, qapp):
        from ui.home_page import HomePage

        page = HomePage(theme=None, assistant_name="Test")
        assert page._ai_card is not None

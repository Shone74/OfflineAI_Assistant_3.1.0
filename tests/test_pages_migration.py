"""Testovi Faze 4: migracija stranica na design system.

Invariant: stranice u AppShell-u NE koriste hardkodirane hex boje
(nakon Faze 4 sve dolaze iz ui/design tokena).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_HEX_RE = re.compile(r"#(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b")

# Stranice koje Faza 4 pokriva (module-level konstante moraju biti iz tokena)
PAGE_MODULES = [
    "ui.memory_page",
    "ui.agents_page",
    "ui.agent_editor_dialog",
    "ui.capabilities_page",
    "ui.assistant_hub",
    "ui.projects_page",
    "ui.tools_page",
    "ui.chat_widget",
]


class TestPagesUseDesignTokens:
    def test_module_constants_from_tokens(self):
        """Nakon import-a, konstante boja moraju odgovarati WORKSPACE paleti."""
        import ui.agents_page as agents
        import ui.assistant_hub as hub
        import ui.capabilities_page as caps
        import ui.chat_widget as chat
        import ui.memory_page as memory
        import ui.projects_page as projects
        import ui.tools_page as tools
        from ui.design import WORKSPACE

        for mod in (agents, hub, caps, memory, projects, tools):
            assert mod._EMERALD == WORKSPACE.emerald, (
                f"{mod.__name__}._EMERALD nije iz WORKSPACE tokena"
            )
            assert mod._TEXT_PRIMARY == WORKSPACE.text_primary

        # chat widget nema vise inline hex u dugmadima
        src = Path(chat.__file__).read_text(encoding="utf-8")
        style_blocks = re.findall(r"setStyleSheet\((.*?)\)", src, flags=re.DOTALL)
        for block in style_blocks:
            assert not _HEX_RE.search(block), (
                f"chat_widget setStyleSheet sadrzi hex: {block[:80]}"
            )

    def test_chat_widget_design_elements(self, qapp):
        from ui.chat_widget import ChatWidget

        chat = ChatWidget()
        # Workspace dizajn elementi
        assert chat._send_btn.objectName() == "send_button"
        assert chat._btn_vision.objectName() == "capability_button"
        # Vision je disabled (multimodalna inferencija nije implementirana)
        assert chat._btn_vision.isEnabled() is False
        assert chat._btn_files.objectName() == "capability_button"
        assert chat._btn_memory.objectName() == "capability_button"
        assert chat._header_status.objectName() == "status_local"
        chat.set_assistant_display_name("Test Ime")
        assert chat._header_title.text() == "Test Ime"

    def test_models_page_status_uses_palette(self, qapp):
        from ai.models.model_loader import ModelStatus
        from ui.models_page import ModelsPage

        page = ModelsPage(assistant=None, model_manager=None, event_bus=None)
        page.set_model_status(ModelStatus.LOADING, "test")
        # boja dolazi iz palete — proveravamo da nije stara hardkodirana
        assert "#D6A24A" not in page._status_label.styleSheet()
        assert "color:" in page._status_label.styleSheet()

    def test_pages_importable(self):
        """Sve AppShell stranice se importuju bez greske (nema kruznih import-a)."""
        import importlib

        for module_name in PAGE_MODULES:
            mod = importlib.import_module(module_name)
            assert mod is not None

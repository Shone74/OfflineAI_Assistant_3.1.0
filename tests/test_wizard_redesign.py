"""Phase 5 tests: wizard redesign (dynamic step indicator + real installation)."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PROJECT_LLM_DIR = Path(__file__).resolve().parents[1] / "models" / "llm"


def _make_manager():
    from ai.models.model_manager import ModelManager

    manager = ModelManager(
        models_dir=PROJECT_LLM_DIR,
        search_paths=[PROJECT_LLM_DIR],
        include_ollama=False,
        include_lm_studio=False,
    )
    manager.rescan()
    return manager


def _make_wizard(qapp, manager=None):
    from ui.welcome_wizard import WelcomeWizard

    return WelcomeWizard(manager or _make_manager(), MagicMock())


def _make_installation_page(qapp, manager=None):
    from ui.welcome_wizard import InstallationPage

    return InstallationPage(manager or _make_manager(), MagicMock())


class TestStepHighlight:
    def test_step_entries_exist(self, qapp):
        wizard = _make_wizard(qapp)
        assert len(wizard._step_entries) == 7
        wizard.close()

    def test_update_step_highlight_states(self, qapp):
        wizard = _make_wizard(qapp)
        # Page 3: koraci 0-2 completed, 3 current, 4-6 default
        wizard._update_step_highlight(3)
        icons = [icon for icon, _ in wizard._step_entries]

        assert icons[0].text() == "✓"
        assert icons[2].text() == "✓"
        assert icons[3].text() == "●"
        assert icons[4].text() == "5"  # vraca broj za neaktivne
        assert icons[6].text() == "7"
        wizard.close()

    def test_highlight_connected_to_currentIdChanged(self, qapp):
        """A page change via a Qt signal updates the highlight."""
        wizard = _make_wizard(qapp)
        wizard.show()
        wizard.setCurrentId(1)
        icons = [icon for icon, _ in wizard._step_entries]
        assert icons[1].text() == "●" and icons[0].text() == "✓"
        wizard.close()

    def test_page_change_updates_highlight(self, qapp):
        """Prebacivanje na stranicu 2 azurira sidebar stanja."""
        wizard = _make_wizard(qapp)
        wizard.show()
        wizard.setCurrentId(2)
        icons = [icon for icon, _ in wizard._step_entries]
        assert icons[2].text() == "●"
        assert icons[0].text() == "✓"
        wizard.close()


class TestRealInstallation:
    def test_real_steps_return_strings(self, qapp):
        page = _make_installation_page(qapp)
        page._selected_model_name = "Qwen2.5-Coder-7B"
        page._models_location = str(PROJECT_LLM_DIR)

        app_result = page._real_step_app()
        assert "folders" in app_result.lower()

        deps_result = page._real_step_dependencies()
        assert len(deps_result) > 0

        model_result = page._real_step_model()
        assert "Qwen2.5-Coder-7B" in model_result

        verify_result = page._real_step_verify()
        assert "arch=qwen2" in verify_result

        finalize_result = page._real_step_finalize()
        assert len(finalize_result) > 0

    def test_verify_finds_project_model(self, qapp):
        page = _make_installation_page(qapp)
        page._selected_model_name = "Qwen2.5-Coder-7B"
        result = page._real_step_verify()
        assert "Qwen2.5-Coder-7B" in result
        assert "arch=qwen2" in result

    def test_progress_tick_moves_forward(self, qapp):
        page = _make_installation_page(qapp)
        page._selected_model_name = "Qwen2.5-Coder-7B"
        page._models_location = str(PROJECT_LLM_DIR)
        page._progress = 0.0
        page._tick_installation()
        assert page._progress > 0
        assert len(page._install_results) >= 1

    def test_cancelled_ui(self, qapp):
        page = _make_installation_page(qapp)
        page._cancelled = True
        page._on_cancelled_ui()
        assert page._task_title.text() == "Installation cancelled"
        assert page._progress_bar.value() == 0

    def test_full_installation_completes(self, qapp):
        """Ceo tick ciklus dolazi do 100% i poziva complete callback."""
        page = _make_installation_page(qapp)
        page._selected_model_name = "Qwen2.5-Coder-7B"
        page._models_location = str(PROJECT_LLM_DIR)
        page._progress = 0.0
        completed = []
        page._on_installation_complete = lambda: completed.append(True)
        for _ in range(100):
            page._tick_installation()
            if page._progress >= 100:
                page._tick_installation()  # the final tick triggers completion
                break
        assert completed == [True]
        assert len(page._install_results) == 5  # every phase produced a result

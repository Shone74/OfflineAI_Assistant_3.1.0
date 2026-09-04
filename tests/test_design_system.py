"""Testovi design sistema (Faza 2): tokens, QSS builder, komponente, ThemeManager."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class TestTokens:
    def test_workspace_palette_values(self):
        from ui.design.tokens import WORKSPACE

        assert WORKSPACE.surface == "#202326"
        assert WORKSPACE.surface_dark == "#181A1D"
        assert WORKSPACE.emerald == "#27C48A"
        assert WORKSPACE.emerald_hover == "#1E9D70"
        assert WORKSPACE.text_on_primary == "#101513"

    def test_installer_palette_values(self):
        from ui.design.tokens import INSTALLER

        assert INSTALLER.surface == "#151819"
        assert INSTALLER.surface_dark == "#111516"
        assert INSTALLER.emerald == "#1D8A68"
        assert INSTALLER.emerald_hover == "#249E78"
        assert INSTALLER.emerald_text == "#62C7A3"

    def test_get_palette_fallback(self):
        from ui.design.tokens import WORKSPACE, get_palette

        assert get_palette("nepostojeca") is WORKSPACE
        assert get_palette("workspace").name == "workspace"
        assert get_palette("installer").name == "installer"

    def test_tint_rgba(self):
        from ui.design.tokens import INSTALLER, WORKSPACE

        assert INSTALLER.tint(0.12) == "rgba(29, 138, 104, 0.12)"
        assert WORKSPACE.tint(0.12) == "rgba(39, 196, 138, 0.12)"


class TestQssBuilder:
    def test_workspace_qss_contains_core_selectors(self):
        from ui.design.qss import shell_qss
        from ui.design.tokens import WORKSPACE

        qss = shell_qss(WORKSPACE)
        for selector in ("#topbar", "#sidebar", "#context_panel", "#nav_button",
                         "#primary_button", "#status_local", "#page_title"):
            assert selector in qss, f"Nedostaje selektor {selector}"

    def test_workspace_qss_no_installer_colors(self):
        """Workspace QSS ne sme sadrzavati installer hex vrednosti (nema mesanja)."""
        from ui.design.qss import shell_qss
        from ui.design.tokens import WORKSPACE

        qss = shell_qss(WORKSPACE)
        assert "#1D8A68" not in qss  # installer emerald
        assert "#151819" not in qss  # installer surface
        assert "#27C48A" in qss      # workspace emerald

    def test_installer_qss_wizard_selectors(self):
        from ui.design.qss import wizard_qss
        from ui.design.tokens import INSTALLER

        qss = wizard_qss(INSTALLER)
        for selector in ("#wizard_step_current", "#wizard_step_completed",
                         "#banner", "#storage_bar", "#install_progress", "#badge"):
            assert selector in qss

    def test_build_full_qss(self):
        from ui.design.qss import build_full_qss

        for name in ("workspace", "installer"):
            qss = build_full_qss(name)
            assert isinstance(qss, str) and len(qss) > 1000
            assert "Segoe UI" in qss


class TestComponents:
    def test_step_indicator_states(self, qapp):
        from ui.design.components import StepIndicator

        steps = ["Welcome", "System Check", "AI Model", "Locations"]
        ind = StepIndicator(steps)
        assert ind.current == 0
        assert ind._labels[0].objectName() == "wizard_step_current"
        assert ind._labels[1].objectName() == "wizard_step_default"

        ind.set_current(2)
        assert ind.current == 2
        assert ind._labels[0].objectName() == "wizard_step_completed"
        assert ind._labels[1].objectName() == "wizard_step_completed"
        assert ind._labels[2].objectName() == "wizard_step_current"
        assert ind._labels[3].objectName() == "wizard_step_default"
        assert "✓" in ind._labels[0].text()

    def test_badge_and_chips(self, qapp):
        from ui.design.components import Badge, CapabilityChip, StatusChip

        badge = Badge("RECOMMENDED")
        assert badge.objectName() == "badge"

        chip = StatusChip("ready")
        assert chip.status == "ready"
        active = CapabilityChip("Text", active=True)
        inactive = CapabilityChip("Images", active=False)
        assert "✓" in active.text() and "✕" in inactive.text()

    def test_cards_and_buttons(self, qapp):
        from PySide6.QtWidgets import QLabel

        from ui.design.components import Card, make_primary_button, make_secondary_button

        card = Card()
        label = QLabel("vrednost")
        label.setObjectName("card_value")
        card.add(label)
        assert card.objectName() == "card"
        assert card.card_layout.count() == 1

        primary = make_primary_button("Launch")
        secondary = make_secondary_button("Cancel")
        assert primary.objectName() == "primary_button"
        assert secondary.objectName() == "secondary_button"

    def test_banners(self, qapp):
        from ui.design.components import Banner, StorageBar

        ok = Banner("Sve spremno", variant="success")
        warn = Banner("Malo prostora", variant="warning")
        err = Banner("Greska", variant="error")
        assert ok.objectName() == "banner"
        assert warn.objectName() == "banner_warning"
        assert err.objectName() == "banner_error"

        bar = StorageBar()
        assert bar.objectName() == "storage_bar"
        assert not bar.isTextVisible()


class TestThemeManager:
    def test_official_themes(self, qapp):
        from ui.theme_manager import ThemeManager

        qapp.setStyleSheet("")
        manager = ThemeManager(qapp, initial_theme="grey_emerald")
        assert manager.theme == "grey_emerald"
        assert manager.palette.name == "workspace"

        # Zvanični workspace QSS se primenjuje
        applied = qapp.styleSheet()
        assert "#27C48A" in applied
        assert "#nav_button" in applied

        manager.apply("installer")
        assert manager.palette.name == "installer"
        assert "#1D8A68" in qapp.styleSheet()

    def test_legacy_theme_names_fallback(self, qapp):
        from ui.theme_manager import ThemeManager

        qapp.setStyleSheet("")
        manager = ThemeManager(qapp)
        # "dark" je legacy alias za installer režim
        manager.apply("dark")
        assert manager.theme == "dark"
        assert manager.palette.name == "installer"
        # Uklonjene legacy teme ne rusе aplikaciju — padaju na zvaničnu
        manager.apply("light")  # type: ignore[arg-type]
        assert manager.theme == "grey_emerald"

    def test_current_settings_theme_compatible(self, qapp):
        """Postojeca postavka ui.theme='dark' iz settings.json mora raditi."""
        from ui.theme_manager import ThemeManager

        qapp.setStyleSheet("")
        manager = ThemeManager(qapp, initial_theme="dark")
        assert manager.palette.name == "installer"

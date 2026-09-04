"""Tools Arsenal page — displays all tools in the application arsenal.

The Tools page is the management surface for the application's Tool Arsenal.
It shows ALL registered tools regardless of whether the current model
supports them.  Model compatibility is displayed as a *status*, not as a
filter — unsupported tools remain visible but marked accordingly.

Key behaviours:
  * Tools exist independently of models.
  * Model capabilities only determine compatibility *status*.
  * Disabled tools remain visible with a "Disabled" status.
  * Enabling/disabling is a UI toggle — tools are never unregistered.
  * Refreshes automatically when the model changes (via event subscription).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger
from tools.base import ToolRegistry
from tools.catalog import ToolCatalog
from tools.compatibility import ToolCompatibilityEvaluator
from tools.discovery import ToolDiscoveryService
from tools.installer import ToolInstaller
from tools.models import ToolStatus, ToolTrust

if TYPE_CHECKING:
    from core.assistant import Assistant
    from core.event_bus import EventBus

logger = get_logger("ui.tools_page")

from ui.design import WORKSPACE as _PALETTE

_GRAPHITE = _PALETTE.surface
_GRAPHITE_CARD = _PALETTE.surface_card
_GRAPHITE_BORDER = _PALETTE.border
_TEXT_PRIMARY = _PALETTE.text_primary
_TEXT_SECONDARY = _PALETTE.text_secondary
_TEXT_MUTED = _PALETTE.text_muted
_EMERALD = _PALETTE.emerald
_AMBER = _PALETTE.warning
_RED = _PALETTE.error


_STATUS_COLORS = {
    "available": _EMERALD,
    "unsupported_by_model": _AMBER,
    "disabled": _TEXT_MUTED,
    "not_installed": _TEXT_MUTED,
    "missing_deps": _RED,
}


class _ToolCard(QFrame):
    """Visual card for a single tool in the arsenal."""

    def __init__(
        self,
        tool_data: dict[str, Any],
        evaluator: ToolCompatibilityEvaluator,
        is_external: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tool_data = tool_data
        self._evaluator = evaluator
        self._is_external = is_external
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)

        icon_label = QLabel(self._tool_data.get("icon", "🔧"))
        icon_label.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 18px;")
        layout.addWidget(icon_label)

        text_layout = QVBoxLayout()
        text_layout.setSpacing(4)

        name_label = QLabel(self._tool_data.get("name", "Unknown Tool"))
        name_label.setStyleSheet(
            f"color: {_TEXT_PRIMARY}; font-size: 13px; font-weight: 600;"
        )
        text_layout.addWidget(name_label)

        desc_label = QLabel(self._tool_data.get("description", ""))
        desc_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        desc_label.setWordWrap(True)
        text_layout.addWidget(desc_label)

        meta_layout = QHBoxLayout()
        meta_layout.setSpacing(8)

        category_label = QLabel(f"📂 {self._tool_data.get('category', 'general')}")
        category_label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 10px;")
        meta_layout.addWidget(category_label)

        version_label = QLabel(f"v{self._tool_data.get('version', '0.0.0')}")
        version_label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 10px;")
        meta_layout.addWidget(version_label)

        offline_label = QLabel("🟢 Offline" if self._tool_data.get("offline", True) else "🌐 Online")
        offline_label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 10px;")
        meta_layout.addWidget(offline_label)

        trust_val = self._tool_data.get("trust_level", "unverified")
        trust_label = QLabel(f"🛡 {ToolTrust(trust_val).display_name if trust_val in [t.value for t in ToolTrust] else trust_val}")
        trust_label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 10px;")
        meta_layout.addWidget(trust_label)

        if self._is_external:
            source_label = QLabel("📦 External")
            source_label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 10px;")
            meta_layout.addWidget(source_label)

        meta_layout.addStretch()
        text_layout.addLayout(meta_layout)

        layout.addLayout(text_layout)

        status = self._tool_data.get("status", ToolStatus.AVAILABLE.value)
        status_display = self._tool_data.get("status_display", status)
        status_color = _STATUS_COLORS.get(status, _TEXT_MUTED)
        status_label = QLabel(status_display)
        status_label.setStyleSheet(
            f"color: {status_color}; font-size: 11px; font-weight: 600;"
        )
        layout.addWidget(status_label)

        self._build_action_button(layout)

    def _build_action_button(self, layout: QHBoxLayout) -> None:
        """Create the appropriate action button based on tool state and type."""
        status = self._tool_data.get("status", ToolStatus.AVAILABLE.value)
        tool_id = self._tool_data.get("tool_id", "")

        if not self._is_external:
            # Built-in tools: only enable/disable toggle
            toggle_btn = QPushButton(
                "Disable" if self._tool_data.get("enabled", True) else "Enable"
            )
            toggle_btn.setCheckable(True)
            toggle_btn.setChecked(self._tool_data.get("enabled", True))
            toggle_btn.setFixedSize(70, 24)
            toggle_btn.setStyleSheet(_btn_style())
            toggle_btn.clicked.connect(lambda: self._on_toggle(toggle_btn))
            layout.addWidget(toggle_btn)
            return

        # External tool buttons
        if status == ToolStatus.NOT_INSTALLED.value:
            install_btn = QPushButton("Install")
            install_btn.setFixedSize(70, 24)
            install_btn.setStyleSheet(_btn_style(_EMERALD))
            install_btn.clicked.connect(lambda: self._on_install(tool_id))
            layout.addWidget(install_btn)
        elif status == ToolStatus.FAILED.value:
            btn = QPushButton("Retry")
            btn.setFixedSize(70, 24)
            btn.setStyleSheet(_btn_style(_AMBER))
            btn.clicked.connect(lambda: self._on_install(tool_id))
            layout.addWidget(btn)
        elif status == ToolStatus.DISABLED.value:
            enable_btn = QPushButton("Enable")
            enable_btn.setFixedSize(70, 24)
            enable_btn.setStyleSheet(_btn_style(_EMERALD))
            enable_btn.clicked.connect(lambda: self._on_enable(tool_id))
            layout.addWidget(enable_btn)
        elif status == ToolStatus.AVAILABLE.value:
            toggle_btn = QPushButton("Disable")
            toggle_btn.setFixedSize(70, 24)
            toggle_btn.setStyleSheet(_btn_style(_AMBER))
            toggle_btn.clicked.connect(lambda: self._on_disable(tool_id))
            layout.addWidget(toggle_btn)

    def _on_toggle(self, btn: QPushButton) -> None:
        is_enabling = not btn.isChecked()
        tool_name = self._tool_data.get("tool_name", "")
        if not tool_name:
            return
        registry: ToolRegistry | None = self._evaluator.registry
        if registry is None:
            return

        reply = QMessageBox.question(
            self,
            "Confirm" if is_enabling else "Confirm Disable",
            f"{'Enable' if is_enabling else 'Disable'} tool: {self._tool_data.get('name', tool_name)}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.No:
            btn.setChecked(not is_enabling)
            return

        if is_enabling:
            registry.enable(tool_name)
            btn.setText("Disable")
        else:
            registry.disable(tool_name)
            btn.setText("Enable")

    def _on_install(self, tool_id: str) -> None:
        parent_page = self.parent()
        while parent_page is not None and not isinstance(parent_page, ToolsPage):
            parent_page = parent_page.parent()
        if isinstance(parent_page, ToolsPage):
            parent_page._on_install_external(tool_id)

    def _on_enable(self, tool_id: str) -> None:
        parent_page = self.parent()
        while parent_page is not None and not isinstance(parent_page, ToolsPage):
            parent_page = parent_page.parent()
        if isinstance(parent_page, ToolsPage):
            parent_page._on_enable_external(tool_id)

    def _on_disable(self, tool_id: str) -> None:
        parent_page = self.parent()
        while parent_page is not None and not isinstance(parent_page, ToolsPage):
            parent_page = parent_page.parent()
        if isinstance(parent_page, ToolsPage):
            parent_page._on_disable_external(tool_id)


def _btn_style(bg: str = "#3A3F40") -> str:
    # bg parametar ostaje radi kompatibilnosti poziva; default dolazi iz palete
    if bg == "#3A3F40":
        bg = _PALETTE.surface_card
    return (
        f"QPushButton {{ background: {bg}; color: {_TEXT_PRIMARY};"
        f" border: 1px solid {_GRAPHITE_BORDER}; border-radius: 4px; font-size: 10px; }}"
        f"QPushButton:hover {{ background: {_EMERALD}; }}"
    )


class ToolsPage(QWidget):
    """Full Tools Arsenal management page.

    Shows every registered tool with its metadata, current model
    compatibility status, and enable/disable controls.  Automatically
    refreshes on model change events.

    Phase 2D extensions:
      * Discovered (not-yet-installed) external tools are visible.
      * A "Refresh Discovery" button re-scans configured discovery directories.
      * Install / Enable / Disable buttons for external tools.
    """

    def __init__(
        self,
        assistant: Assistant | None = None,
        event_bus: EventBus | None = None,
        installer: ToolInstaller | None = None,
        catalog: ToolCatalog | None = None,
        discovery: ToolDiscoveryService | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._assistant = assistant
        self._event_bus = event_bus
        self._evaluator: ToolCompatibilityEvaluator | None = None
        self._current_model: str = "N/A"
        self._cards: list[_ToolCard] = []
        self._installer = installer
        self._catalog = catalog
        self._discovery = discovery
        self._discovery_btn: QPushButton | None = None
        self._build_ui()
        self._wire_events()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()
        title = QLabel("Tools Arsenal")
        title.setStyleSheet(
            f"color: {_TEXT_PRIMARY}; font-size: 22px; font-weight: 600;"
        )
        header.addWidget(title)
        header.addStretch()

        self._model_label = QLabel("Current model: N/A")
        self._model_label.setStyleSheet(
            f"color: {_TEXT_SECONDARY}; font-size: 12px;"
        )
        header.addWidget(self._model_label)
        layout.addLayout(header)

        filter_layout = QHBoxLayout()
        filter_label = QLabel("Filter:")
        filter_label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 11px;")
        filter_layout.addWidget(filter_label)

        self._filter_combo = QComboBox()
        self._filter_combo.setFixedHeight(24)
        self._filter_combo.setStyleSheet(
            f"QComboBox {{ background: {_GRAPHITE_CARD}; color: {_TEXT_PRIMARY};"
            f" border: 1px solid {_GRAPHITE_BORDER}; border-radius: 4px; font-size: 11px; }}"
        )
        self._filter_combo.addItems([
            "All Tools",
            "Available",
            "Unsupported by Model",
            "Disabled",
            "Not Installed",
            "Invalid",
            "Failed",
        ])
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        filter_layout.addWidget(self._filter_combo)

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedHeight(24)
        self._refresh_btn.clicked.connect(self.refresh)
        filter_layout.addWidget(self._refresh_btn)

        if self._discovery is not None:
            self._discovery_btn = QPushButton("Refresh Discovery")
            self._discovery_btn.setFixedHeight(24)
            self._discovery_btn.clicked.connect(self._on_refresh_discovery)
            filter_layout.addWidget(self._discovery_btn)

        filter_layout.addStretch()
        layout.addLayout(filter_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {_GRAPHITE}; }}"
            f"QScrollBar:vertical {{ background: {_GRAPHITE_CARD};"
            f" border: none; width: 8px; margin: 0px; }}"
            f"QScrollBar::handle:vertical {{ background: {_GRAPHITE_BORDER};"
            f" border-radius: 4px; }}"
        )

        self._container = QFrame()
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setSpacing(10)
        self._container_layout.addStretch()
        scroll.setWidget(self._container)
        layout.addWidget(scroll)

        self.refresh()

    def _wire_events(self) -> None:
        if self._event_bus is not None:
            self._event_bus.subscribe("MODEL_LOADED", self._on_model_loaded)
            self._event_bus.subscribe("TOOL_ENABLED", self._on_tool_toggled)
            self._event_bus.subscribe("TOOL_DISABLED", self._on_tool_toggled)
            self._event_bus.subscribe("TOOL_REGISTERED", self._on_tool_registered)
            self._event_bus.subscribe("TOOL_UNREGISTERED", self._on_tool_registered)

    def _on_model_loaded(self, event_type: str, data: dict[str, Any]) -> None:
        model_name = data.get("model", "N/A")
        logger.debug("Tools page: model loaded → %s", model_name)
        self._update_model_label(model_name)
        self.refresh()

    def _on_tool_toggled(self, event_type: str, data: dict[str, Any]) -> None:
        tool_name = data.get("tool", "")
        logger.debug("Tools page: tool %s → %s", tool_name, event_type)
        self.refresh()

    def _on_tool_registered(self, event_type: str, data: dict[str, Any]) -> None:
        tool_name = data.get("tool", "")
        logger.debug("Tools page: tool %s %s", tool_name, event_type)
        self.refresh()

    def _update_model_label(self, model_name: str) -> None:
        self._current_model = model_name
        self._model_label.setText(f"Current model: {model_name}")

    def _init_evaluator(self) -> None:
        if self._assistant is None:
            self._evaluator = None
            return

        tool_registry = getattr(self._assistant, "_tools", None)
        if tool_registry is None:
            self._evaluator = None
            return

        self._evaluator = ToolCompatibilityEvaluator(registry=tool_registry)
        if self._catalog is not None:
            self._evaluator.set_catalog(self._catalog)

        engine = getattr(self._assistant, "_engine", None)
        if engine is not None:
            caps = getattr(engine, "model_capabilities", None)
            self._evaluator.set_model_capabilities(caps)

    def _on_filter_changed(self, text: str) -> None:
        self._refresh_cards()

    def _on_refresh_discovery(self) -> None:
        """Re-scan configured discovery directories and re-integrate into the catalog."""
        if self._discovery is None:
            return
        if self._installer is None:
            return
        report = self._discovery.refresh()
        for manifest in report.valid_manifests():
            self._installer.register_manifest(manifest)
        self.refresh()

    def _on_install_external(self, tool_id: str) -> None:
        """Explicitly request installation of a discovered external tool."""
        if self._installer is None:
            return
        result = self._installer.install(tool_id)
        if not result.success:
            QMessageBox.critical(
                self,
                "Installation Failed",
                f"Failed to install tool '{tool_id}': {result.error}",
            )
            return
        self.refresh()

    def _on_enable_external(self, tool_id: str) -> None:
        """Explicitly enable an installed external tool."""
        if self._installer is None:
            return
        if self._installer.enable(tool_id):
            self.refresh()

    def _on_disable_external(self, tool_id: str) -> None:
        """Disable an external tool (remains installed, not available for execution)."""
        if self._installer is None:
            return
        if self._installer.disable(tool_id):
            self.refresh()

    def refresh(self) -> None:
        """Refresh the entire page — called on model change or manually."""
        self._init_evaluator()

        if self._assistant is not None:
            model_name = getattr(self._assistant, "model_name", "N/A")
            self._update_model_label(model_name)

        self._refresh_cards()

    def _refresh_cards(self) -> None:
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            if item is not None:
                w = item.widget()
                if w is not None:
                    w.setParent(None)

        if self._evaluator is None:
            no_tools = QLabel("No tool registry is configured.")
            no_tools.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 14px;")
            self._container_layout.addWidget(no_tools)
            return

        filter_text = self._filter_combo.currentText()
        all_tools = self._evaluator.list_all_with_status() if self._evaluator else []
        if not all_tools:
            no_tools = QLabel("No tools are registered in the arsenal.")
            no_tools.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 14px;")
            self._container_layout.addWidget(no_tools)
            return

        filtered: list[dict[str, Any]] = []
        for tool in all_tools:
            status = tool.get("status", ToolStatus.AVAILABLE.value)
            if filter_text == "Available" and status != ToolStatus.AVAILABLE.value:
                continue
            if filter_text == "Unsupported by Model" and status != ToolStatus.UNSUPPORTED_BY_MODEL.value:
                continue
            if filter_text == "Disabled" and status != ToolStatus.DISABLED.value:
                continue
            if filter_text == "Not Installed" and status != ToolStatus.NOT_INSTALLED.value:
                continue
            if filter_text == "Invalid" and status != ToolStatus.INVALID.value:
                continue
            if filter_text == "Failed" and status != ToolStatus.FAILED.value:
                continue
            filtered.append(tool)

        self._cards = []
        for tool_data in filtered:
            source = tool_data.get("source", "builtin")
            is_external = source != "builtin"
            card = _ToolCard(tool_data, self._evaluator, is_external=is_external)
            self._container_layout.addWidget(card)
            self._cards.append(card)

        self._container_layout.addStretch()

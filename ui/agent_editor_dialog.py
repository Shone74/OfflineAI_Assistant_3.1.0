"""Agent editor dialog — Add / Edit Agent form.

Follows the Graphite + Emerald visual language established in
``ui.memory_page`` and ``ui.theme_manager``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QTextEdit,
    QWidget,
)

from core.logger import get_logger
from database.models import Agent

logger = get_logger("ui.agent_editor")

from ui.design import WORKSPACE as _PALETTE

_GRAPHITE = _PALETTE.surface_dark
_GRAPHITE_CARD = _PALETTE.surface_card
_GRAPHITE_DARK_CARD = _PALETTE.surface_dark
_GRAPHITE_BORDER = _PALETTE.border
_EMERALD = _PALETTE.emerald
_EMERGENCY_HOVER = _PALETTE.emerald_hover
_EMERALD_TEXT = _PALETTE.emerald_text
_EMERALD_BG_TINT = _PALETTE.tint(0.15)
_EMERALD_BORDER_TINT = _PALETTE.tint(0.4)
_TEXT_PRIMARY = _PALETTE.text_primary
_TEXT_SECONDARY = _PALETTE.text_secondary
_TEXT_MUTED = _PALETTE.text_muted
_DANGER = _PALETTE.error


class AgentEditorDialog(QDialog):
    """Add / Edit Agent dialog (reused for both modes)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        agent: Agent | None = None,
        tool_names: list[str] | None = None,
        model_names: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._agent = agent
        self.setWindowTitle("Add Agent" if agent is None else "Edit Agent")
        self.resize(520, 480)
        self.setModal(True)
        self._tool_names = tool_names or []
        self._model_names = model_names or []

        layout = QFormLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # --- Name ---
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. coding-agent")
        layout.addRow(QLabel("<b>Name *</b>"), self._name_edit)

        # --- Description ---
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("Short description of this agent's role")
        layout.addRow(QLabel("<b>Description</b>"), self._desc_edit)

        # --- System prompt ---
        self._system_prompt_edit = QTextEdit()
        self._system_prompt_edit.setPlaceholderText(
            "Instructions that guide this agent's behavior..."
        )
        self._system_prompt_edit.setFixedHeight(120)
        layout.addRow(QLabel("<b>System prompt</b>"), self._system_prompt_edit)

        # --- Model name ---
        self._model_combo = QComboBox()
        self._model_combo.setEditable(True)
        if self._model_names:
            self._model_combo.addItems(self._model_names)
        self._model_combo.setEditText("")
        self._model_combo.setToolTip(
            "Leave empty for default. Specify a model identifier if this agent "
            "should prefer a particular model."
        )
        layout.addRow(QLabel("<b>Model name</b>"), self._model_combo)

        # --- Permission profile ---
        self._permission_edit = QLineEdit()
        self._permission_edit.setPlaceholderText("default")
        layout.addRow(QLabel("<b>Permission profile</b>"), self._permission_edit)

        # --- Enabled ---
        self._enabled_check = QCheckBox("Agent is enabled")
        self._enabled_check.setChecked(True)
        layout.addRow(self._enabled_check)

        # --- Tool whitelist ---
        whitelist_label = QLabel("<b>Tool whitelist (empty = all tools allowed)</b>")
        self._whitelist_widget = QListWidget()
        self._whitelist_widget.setMaximumHeight(180)
        self._whitelist_widget.setStyleSheet(
            f"QListWidget {{ background: {_GRAPHITE_CARD}; border: 1px solid {_GRAPHITE_BORDER};"
            f" border-radius: 6px; }}"
        )
        for tname in self._tool_names:
            item = QListWidgetItem(tname)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self._whitelist_widget.addItem(item)
        layout.addRow(whitelist_label, self._whitelist_widget)

        # --- Buttons ---
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancel")
        layout.addRow(buttons)

        if agent is not None:
            self._populate_from_agent(agent)

        self._name_edit.textChanged.connect(self._on_name_changed)
        self._name_edit.setFocus()

    def _populate_from_agent(self, agent: Agent) -> None:
        self._name_edit.setText(agent.name or "")
        self._desc_edit.setText(agent.description or "")
        self._system_prompt_edit.setPlainText(agent.system_prompt or "")
        if agent.model_name:
            self._model_combo.setEditText(agent.model_name)
        self._permission_edit.setText(agent.permission_profile or "default")
        self._enabled_check.setChecked(bool(agent.enabled))

        # Select whitelist items
        whitelist = agent.tool_whitelist or []
        for i in range(self._whitelist_widget.count()):
            item = self._whitelist_widget.item(i)
            if item is not None:
                item.setCheckState(
                    Qt.CheckState.Checked if item.text() in whitelist else Qt.CheckState.Unchecked
                )

    def _on_name_changed(self, text: str) -> None:
        pass

    def get_agent(self) -> Agent:
        """Return an :class:`Agent` populated from the dialog fields."""
        name = self._name_edit.text().strip()
        selected_tools: list[str] = []
        for i in range(self._whitelist_widget.count()):
            item = self._whitelist_widget.item(i)
            if item is not None and item.checkState() == Qt.CheckState.Checked:
                selected_tools.append(item.text())

        whitelist: list[str] | None = selected_tools if selected_tools else None

        if self._agent is not None:
            self._agent.name = name
            self._agent.description = self._desc_edit.text().strip()
            self._agent.system_prompt = self._system_prompt_edit.toPlainText()
            self._agent.model_name = self._model_combo.currentText().strip()
            self._agent.enabled = self._enabled_check.isChecked()
            self._agent.tool_whitelist = whitelist
            self._agent.permission_profile = self._permission_edit.text().strip() or "default"
            return self._agent
        return Agent(
            name=name,
            description=self._desc_edit.text().strip(),
            system_prompt=self._system_prompt_edit.toPlainText(),
            model_name=self._model_combo.currentText().strip(),
            enabled=self._enabled_check.isChecked(),
            tool_whitelist=whitelist,
            permission_profile=self._permission_edit.text().strip() or "default",
        )

    def accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Agent name is required.")
            return
        super().accept()

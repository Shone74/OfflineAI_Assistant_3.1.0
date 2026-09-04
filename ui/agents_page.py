"""Agents management page — list, add, edit, delete, enable/disable agents.

Replaces the static placeholder in :mod:`ui.main_window`.  Reads from the
existing :class:`agent.repository.AgentRepository` (SQLite ``agents`` table)
and follows the application's Graphite + Emerald visual language.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.event_bus import EventBus
from core.logger import get_logger
from database.models import Agent
from ui.agent_editor_dialog import AgentEditorDialog

logger = get_logger("ui.agents_page")

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


class AgentsPage(QWidget):
    """Real Agents management page (replaces the static placeholder)."""

    def __init__(
        self,
        assistant: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._assistant = assistant
        self._repo = getattr(assistant, "agent_repository", None)
        self._tool_registry = getattr(getattr(assistant, "_tools", None), "list_tools", None)
        mm = getattr(assistant, "model_manager", None)
        self._model_names: list[str] = []
        if mm is not None:
            try:
                self._model_names = [m.name for m in mm.list_models()]
            except Exception:
                logger.debug("Failed to load model names", exc_info=True)
        current_model = getattr(assistant, "model_name", None) or ""
        if current_model and current_model not in self._model_names:
            self._model_names.insert(0, current_model)

        self._event_sub_ids: list[tuple[str, str]] = []
        self._cards: list[QFrame] = []
        self._filter = "all"
        self._setup_ui()
        self._subscribe_to_lifecycle_events()
        self.destroyed.connect(self._unsubscribe_from_lifecycle_events)
        self.refresh()

    def _subscribe_to_lifecycle_events(self) -> None:
        """Subscribe to Agent lifecycle events for auto-refresh."""
        bus = EventBus.get_instance()
        for event_type in ("AGENT_CREATED", "AGENT_UPDATED", "AGENT_DELETED", "AGENT_ENABLED", "AGENT_DISABLED"):
            sub_id = bus.subscribe(event_type, self._on_agent_event)
            self._event_sub_ids.append((event_type, sub_id))
        self._event_sub_ids.append(
            ("MODEL_LOADED", bus.subscribe("MODEL_LOADED", self._on_model_loaded))
        )
        self._event_sub_ids.append(
            ("MODEL_UNLOADED", bus.subscribe("MODEL_UNLOADED", self._on_model_unloaded))
        )

    def _on_agent_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Refresh the page when an Agent lifecycle event occurs."""
        self.refresh()

    def _on_model_loaded(self, event_type: str, data: dict[str, Any]) -> None:
        """Refresh model selection when a new model is loaded.

        Appends the newly loaded model to ``_model_names`` if it is not
        already present, then triggers a UI refresh.  Models are not
        removed on unload — they may be loaded again later.
        """
        model_name = data.get("model", "")
        if model_name and model_name not in self._model_names:
            self._model_names.append(model_name)
        self.refresh()

    def _on_model_unloaded(self, event_type: str, data: dict[str, Any]) -> None:
        """Refresh UI when a model is unloaded.

        The unloaded model remains in ``_model_names`` so it can be
        selected again if loaded in the future.
        """
        self.refresh()

    def _unsubscribe_from_lifecycle_events(self) -> None:
        """Clean up event subscriptions."""
        bus = EventBus.get_instance()
        for event_type, sub_id in self._event_sub_ids:
            bus.unsubscribe(event_type, sub_id)
        self._event_sub_ids = []

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # --- Header ---
        header = QHBoxLayout()

        title = QLabel("Agents")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setWeight(QFont.Weight.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {_TEXT_PRIMARY};")
        header.addWidget(title)

        desc = QLabel(
            "Local, configurable task executors. Each agent can have its own "
            "system prompt, model, tool whitelist and permissions."
        )
        desc.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 12px;")
        desc.setWordWrap(True)
        desc.setMinimumWidth(300)
        header.addWidget(desc)

        header.addStretch()

        self._filter_combo = QComboBox()
        self._filter_combo.setEditable(False)
        self._filter_combo.setMaximumWidth(140)
        self._filter_combo.addItems(["All", "Enabled", "Disabled"])
        self._filter_combo.currentTextChanged.connect(self._on_filter_changed)
        header.addWidget(self._filter_combo)

        self._btn_add = QPushButton("Add Agent")
        self._btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_add.setStyleSheet(self._emerald_btn_css())
        self._btn_add.clicked.connect(self._on_add)
        header.addWidget(self._btn_add)

        layout.addLayout(header)

        # --- Banner ---
        self._banner = QLabel()
        self._banner.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        self._banner.setVisible(False)
        layout.addWidget(self._banner)

        # --- Scroll area ---
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ border: none; background: {_GRAPHITE}; }}"
            f"QScrollBar:vertical {{ background: {_GRAPHITE_DARK_CARD}; border: none; width: 8px; margin: 0px; }}"
            f"QScrollBar::handle:vertical {{ background: {_GRAPHITE_BORDER}; border-radius: 4px; }}"
        )
        self._container = QFrame()
        self._container.setStyleSheet(f"background: {_GRAPHITE}; border: none;")
        self._container_layout = QVBoxLayout(self._container)
        self._container_layout.setContentsMargins(0, 0, 0, 0)
        self._container_layout.setSpacing(10)
        self._container_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)
        layout.addWidget(self._scroll)

        # --- Footer ---
        footer = QHBoxLayout()
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        footer.addWidget(self._count_label)
        footer.addStretch()
        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_refresh.setStyleSheet(self._small_btn_css())
        self._btn_refresh.clicked.connect(self.refresh)
        footer.addWidget(self._btn_refresh)
        layout.addLayout(footer)

        self._update_banner_visibility()

    def _emerald_btn_css(self) -> str:
        return (
            f"QPushButton {{ padding: 4px 12px; border-radius: 6px; background: {_EMERALD};"
            f" color: {_TEXT_PRIMARY}; border: none; }}"
            f"QPushButton:hover {{ background: {_EMERGENCY_HOVER}; }}"
            f"QPushButton:pressed {{ background: {_PALETTE.success_bg}; }}"
        )

    def _small_btn_css(self) -> str:
        return (
            f"QPushButton {{ padding: 2px 10px; border-radius: 5px; background: {_GRAPHITE_DARK_CARD};"
            f" color: {_TEXT_SECONDARY}; border: 1px solid {_GRAPHITE_BORDER}; font-size: 11px; }}"
            f"QPushButton:hover {{ background: {_GRAPHITE_BORDER}; }}"
        )

    def _small_danger_btn_css(self) -> str:
        return (
            f"QPushButton {{ padding: 2px 10px; border-radius: 5px; background: {_GRAPHITE_DARK_CARD};"
            f" color: {_DANGER}; border: 1px solid {_GRAPHITE_BORDER}; font-size: 11px; }}"
            f"QPushButton:hover {{ background: rgba(217,101,101,0.12); }}"
        )

    # ------------------------------------------------------------------ #
    # Data
    # ------------------------------------------------------------------ #
    def _update_banner_visibility(self) -> None:
        if self._repo is None:
            self._banner.setVisible(True)
            self._banner.setText(
                "Agent repository is not available. Agent management is disabled."
            )

    def _get_tool_names(self) -> list[str]:
        if self._tool_registry is not None:
            try:
                tools: list[dict[str, Any]] = self._tool_registry()
                return [str(t.get("name", "")) for t in tools if t.get("name")]
            except Exception:
                return []
        return []

    def _load_agents(self) -> list[Agent]:
        if self._repo is None:
            return []
        include_disabled = self._filter != "enabled"
        only_disabled = self._filter == "disabled"
        agents = self._repo.list_agents(include_disabled=include_disabled)
        if only_disabled:
            agents = [a for a in agents if not a.enabled]
        return agents

    def refresh(self) -> None:
        """Reload agents from the backend and re-render the list."""
        self._clear_container()
        self._cards = []
        agents = self._load_agents()
        if not agents:
            self._show_empty_state()
        else:
            for agent in agents:
                card = self._make_agent_card(agent)
                self._container_layout.addWidget(card)
                self._cards.append(card)
        self._count_label.setText(
            f"{len(agents)} agent{'s' if len(agents) != 1 else ''}"
        )

    def _clear_container(self) -> None:
        while self._container_layout.count():
            item = self._container_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _show_empty_state(self) -> None:
        wrapper = QFrame()
        wrapper.setStyleSheet(f"background: {_GRAPHITE}; border: none;")
        wlayout = QVBoxLayout(wrapper)
        wlayout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wlayout.setSpacing(12)

        title = QLabel(
            "No agents found." if self._filter == "all"
            else f"No {self._filter} agents found."
        )
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setWeight(QFont.Weight.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {_TEXT_PRIMARY};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wlayout.addWidget(title)

        if self._filter != "disabled":
            add_btn = QPushButton("Add Agent")
            add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            add_btn.setStyleSheet(self._emerald_btn_css())
            add_btn.setMinimumWidth(160)
            add_btn.clicked.connect(self._on_add)
            wlayout.addWidget(add_btn)

        self._container_layout.addWidget(wrapper)

    def _on_filter_changed(self, text: str) -> None:
        self._filter = text.lower()
        self.refresh()

    # ------------------------------------------------------------------ #
    # Cards
    # ------------------------------------------------------------------ #
    def _make_agent_card(self, agent: Agent) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"background: {_GRAPHITE_CARD}; border: 1px solid {_GRAPHITE_BORDER};"
            f"border-radius: 10px; padding: 14px 16px;"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        # --- Top row: name + enabled toggle ---
        top = QHBoxLayout()

        name_label = QLabel(agent.name or "unnamed")
        name_label.setStyleSheet(
            f"color: {_TEXT_PRIMARY}; font-weight: 600; font-size: 13px;"
        )
        top.addWidget(name_label)

        top.addStretch()

        if agent.enabled:
            badge = QLabel("ENABLED")
            badge.setStyleSheet(
                f"background: {_EMERALD_BG_TINT}; color: {_EMERALD_TEXT};"
                f"border: 1px solid {_EMERALD_BORDER_TINT}; border-radius: 8px;"
                f"padding: 2px 8px; font-size: 10px; font-weight: 600;"
            )
        else:
            badge = QLabel("DISABLED")
            badge.setStyleSheet(
                f"background: rgba(217,101,101,0.10); color: {_DANGER};"
                f"border: 1px solid rgba(217,101,101,0.3); border-radius: 8px;"
                f"padding: 2px 8px; font-size: 10px; font-weight: 600;"
            )
        top.addWidget(badge)

        toggle_btn = QPushButton("Disable" if agent.enabled else "Enable")
        if agent.enabled:
            toggle_css = self._emerald_btn_css()
        else:
            toggle_css = (
                f"QPushButton {{ padding: 4px 12px; border-radius: 6px; "
                f"background: {_GRAPHITE_DARK_CARD}; color: {_TEXT_MUTED};"
                f" border: 1px solid {_GRAPHITE_BORDER}; }}"
                f"QPushButton:hover {{ background: {_GRAPHITE_BORDER}; }}"
            )
        toggle_btn.setStyleSheet(toggle_css)
        toggle_btn.setMinimumWidth(70)
        toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        top.addWidget(toggle_btn)

        layout.addLayout(top)

        # --- Description ---
        if agent.description:
            desc = QLabel(agent.description)
            desc.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 12px;")
            desc.setWordWrap(True)
            layout.addWidget(desc)

        # --- Model name + Permission profile row ---
        info_row = QHBoxLayout()
        model_text = agent.model_name or "(default)"
        info_row.addWidget(QLabel(f"Model: {model_text}"))
        profile_text = agent.permission_profile or "default"
        info_row.addWidget(QLabel(f"Profile: {profile_text}"))
        info_row.addStretch()
        layout.addLayout(info_row)

        # --- Tool whitelist summary ---
        if agent.tool_whitelist:
            whitelist_text = ", ".join(agent.tool_whitelist)
        else:
            whitelist_text = "All tools allowed"
        wl = QLabel(f"Tools: {whitelist_text}")
        wl.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        wl.setWordWrap(True)
        layout.addWidget(wl)

        # --- Updated timestamp ---
        updated = agent.updated_at if agent.updated_at else "—"
        date_label = QLabel(f"Modified: {updated}")
        date_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        layout.addWidget(date_label)

        # --- Action buttons ---
        btn_row = QHBoxLayout()
        btn_edit = QPushButton("Edit")
        btn_edit.setStyleSheet(self._small_btn_css())
        btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(btn_edit)

        btn_delete = QPushButton("Delete")
        btn_delete.setStyleSheet(self._small_danger_btn_css())
        btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_row.addWidget(btn_delete)
        btn_row.addStretch()

        layout.addLayout(btn_row)

        # --- Connect signals ---
        tool_names = self._get_tool_names()
        btn_edit.clicked.connect(
            lambda _e, a=agent: self._on_edit(a, tool_names)
        )
        btn_delete.clicked.connect(
            lambda _e, a=agent: self._on_delete(a)
        )
        toggle_btn.clicked.connect(
            lambda _e, a=agent: self._on_toggle(a)
        )

        return card

    # ------------------------------------------------------------------ #
    # CRUD handlers
    # ------------------------------------------------------------------ #
    def _on_add(self) -> None:
        if self._repo is None:
            return
        tool_names = self._get_tool_names()
        dialog = AgentEditorDialog(
            parent=self, tool_names=tool_names, model_names=self._model_names,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            agent = dialog.get_agent()
            try:
                self._repo.create_agent(agent)
                logger.info("Agent added: %s", agent.name)
            except Exception as exc:
                self._show_error("Add Agent", str(exc))
                return
            self.refresh()

    def _on_edit(self, agent: Agent, tool_names: list[str]) -> None:
        if self._repo is None or agent.id is None:
            return
        dialog = AgentEditorDialog(
            parent=self, agent=agent, tool_names=tool_names,
            model_names=self._model_names,
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.get_agent()
            try:
                self._repo.update_agent(updated)
                logger.info("Agent %d updated: %s", agent.id, updated.name)
            except Exception as exc:
                self._show_error("Edit Agent", str(exc))
                return
            self.refresh()

    def _on_delete(self, agent: Agent) -> None:
        if self._repo is None or agent.id is None:
            return
        name = agent.name or "this agent"
        msg = (
            f"Delete agent '{name}'?\n\n"
            "This action cannot be undone.\n"
            "No Chat, Memory, conversation, or document data will be affected."
        )
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Delete Agent")
        confirm.setText(msg)
        confirm.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        confirm.button(QMessageBox.StandardButton.Yes).setText("Delete")
        confirm.button(QMessageBox.StandardButton.No).setText("Cancel")
        confirm.setDefaultButton(QMessageBox.StandardButton.No)
        confirm.exec()

        if confirm.clickedButton() == confirm.button(QMessageBox.StandardButton.Yes):
            try:
                self._repo.delete_agent(agent.id)
                logger.info("Agent deleted: %s (id=%s)", agent.name, agent.id)
            except Exception as exc:
                self._show_error("Delete Agent", str(exc))
                return
            self.refresh()

    def _on_toggle(self, agent: Agent) -> None:
        if self._repo is None or agent.id is None:
            return
        try:
            if agent.enabled:
                self._repo.disable_agent(agent.id)
                logger.info("Agent disabled: %s (id=%s)", agent.name, agent.id)
            else:
                self._repo.enable_agent(agent.id)
                logger.info("Agent enabled: %s (id=%s)", agent.name, agent.id)
        except Exception as exc:
            self._show_error("Toggle Agent", str(exc))
            return
        self.refresh()

    def _show_error(self, title: str, message: str) -> None:
        if "UNIQUE" in message or "unique" in message.lower():
            QMessageBox.warning(self, title, "An agent with that name already exists.")
        else:
            QMessageBox.critical(self, title, f"Failed: {message}")

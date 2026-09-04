"""Memory management page — read, add, edit, delete, search and clear memories.

Replaces the static placeholder in :mod:`ui.main_window`.  Reads from the
existing :class:`memory.memory_manager.MemoryManager` (SQLite ``memories``
table) and follows the application's Graphite + Emerald visual language.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.event_bus import EventBus
from core.logger import get_logger
from database.models import MemoryEntry, MemoryType
from memory.memory_manager import MemoryManager

logger = get_logger("ui.memory_page")

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

_TYPE_LABELS = {
    MemoryType.USER_PREFERENCE.value: "User Preference",
    MemoryType.FACT.value: "Fact",
    MemoryType.PROJECT_INFO.value: "Project Info",
    MemoryType.INSTRUCTION.value: "Instruction",
}
_LABEL_BY_VALUE: dict[str, str] = {
    v.value: k for k, v in MemoryType.__members__.items()
}


class MemoryDialog(QDialog):
    """Add / Edit memory dialog (reused for both modes)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        entry: MemoryEntry | None = None,
    ) -> None:
        super().__init__(parent)
        self._entry = entry
        self.setWindowTitle("Add Memory" if entry is None else "Edit Memory")
        self.resize(440, 280)
        self.setModal(True)

        layout = QFormLayout(self)

        self._content_edit = QTextEdit()
        self._content_edit.setPlaceholderText("Memory content...")
        self._content_edit.setFixedHeight(90)
        layout.addRow(QLabel("<b>Content</b>"), self._content_edit)

        self._type_combo = QComboBox()
        for mem_type in MemoryType:
            self._type_combo.addItem(
                _TYPE_LABELS.get(mem_type.value, _LABEL_BY_VALUE.get(mem_type.value, mem_type.value)),
                mem_type.value,
            )
        layout.addRow(QLabel("<b>Type</b>"), self._type_combo)

        self._importance_slider = QSlider(Qt.Orientation.Horizontal)
        self._importance_slider.setRange(0, 100)
        self._importance_slider.setValue(50)
        self._importance_label = QLabel("0.50")
        imp_row = QHBoxLayout()
        imp_row.addWidget(self._importance_slider)
        imp_row.addWidget(self._importance_label)
        layout.addRow(QLabel("<b>Importance</b>"), imp_row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        layout.addRow(buttons)

        self._importance_slider.valueChanged.connect(self._on_importance_changed)

        if entry is not None:
            self._content_edit.setPlainText(entry.content)
            idx = self._type_combo.findData(entry.type)
            if idx >= 0:
                self._type_combo.setCurrentIndex(idx)
            clamped = max(0, min(100, round((entry.importance or 0.5) * 100)))
            self._importance_slider.setValue(clamped)

    def _on_importance_changed(self, val: int) -> None:
        self._importance_label.setText(f"{val / 100:.2f}")

    def get_entry(self) -> MemoryEntry:
        content = self._content_edit.toPlainText().strip()
        mem_type = self._type_combo.currentData() or MemoryType.FACT.value
        importance = self._importance_slider.value() / 100.0
        if self._entry is not None:
            self._entry.content = content
            self._entry.type = mem_type
            self._entry.importance = importance
            return self._entry
        return MemoryEntry(type=mem_type, content=content, importance=importance)

    def accept(self) -> None:
        if not self._content_edit.toPlainText().strip():
            QMessageBox.warning(self, "Missing content", "Memory content cannot be empty.")
            return
        super().accept()


class MemoryPage(QWidget):
    """Real Memory management page (replaces the static placeholder)."""

    def __init__(
        self,
        config: ConfigManager | None = None,
        assistant: Any = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._assistant = assistant
        self._memory: MemoryManager | None = self._resolve_memory()
        self._is_enabled = (
            self._config.get("memory.enabled", True)
            if self._config is not None
            else True
        )
        self._cards: list[QFrame] = []
        self._event_sub_ids: list[tuple[str, str]] = []
        self._setup_ui()
        self._subscribe_to_events()
        self.destroyed.connect(self._unsubscribe_from_events)
        self.refresh_memories()

    def _subscribe_to_events(self) -> None:
        bus = EventBus.get_instance()
        sub_id = bus.subscribe("MEMORY_UPDATED", self._on_memory_updated)
        self._event_sub_ids.append(("MEMORY_UPDATED", sub_id))

    def _unsubscribe_from_events(self) -> None:
        bus = EventBus.get_instance()
        for event_type, sub_id in self._event_sub_ids:
            bus.unsubscribe(event_type, sub_id)
        self._event_sub_ids = []

    def _on_memory_updated(self, event_type: str, data: dict[str, Any]) -> None:
        logger.debug("MEMORY_UPDATED received: %s", data)
        self.refresh_memories(self._search.text())

    def _resolve_memory(self) -> MemoryManager | None:
        mem = getattr(self._assistant, "memory", None)
        if isinstance(mem, MemoryManager):
            return mem
        return None

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = QHBoxLayout()

        title = QLabel("Memory")
        title_font = QFont()
        title_font.setPointSize(22)
        title_font.setWeight(QFont.Weight.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {_TEXT_PRIMARY};")
        header.addWidget(title)

        self._toggle = QCheckBox("Memory enabled")
        self._toggle.setChecked(bool(self._is_enabled))
        self._toggle.setToolTip(
            "Enable or disable long-term memory. Existing memories are preserved when disabled."
        )
        self._toggle.stateChanged.connect(self._on_toggle_changed)
        header.addWidget(self._toggle)

        header.addStretch()

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search memories...")
        self._search.setMaximumWidth(220)
        self._search.textChanged.connect(self._on_search_text)
        header.addWidget(self._search)

        self._btn_add = QPushButton("Add Memory")
        self._btn_add.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_add.setStyleSheet(self._emerald_btn_css())
        self._btn_add.clicked.connect(self._on_add)
        header.addWidget(self._btn_add)

        layout.addLayout(header)

        self._banner = QLabel()
        self._banner.setStyleSheet(f"color: {_EMERGENCY_HOVER}; font-size: 11px;")
        self._banner.setVisible(False)
        layout.addWidget(self._banner)

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

        footer = QHBoxLayout()
        self._btn_clear = QPushButton("Clear All Memories")
        self._btn_clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_clear.setStyleSheet(self._danger_btn_css())
        self._btn_clear.clicked.connect(self._on_clear_all)
        footer.addWidget(self._btn_clear)
        footer.addStretch()
        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        footer.addWidget(self._count_label)
        layout.addLayout(footer)

        self._update_controls_state()

    def _emerald_btn_css(self) -> str:
        return (
            f"QPushButton {{ padding: 4px 12px; border-radius: 6px; background: {_EMERALD};"
            f" color: {_TEXT_PRIMARY}; border: none; }}"
            f"QPushButton:hover {{ background: {_EMERGENCY_HOVER}; }}"
            f"QPushButton:pressed {{ background: {_PALETTE.success_bg}; }}"
        )

    def _danger_btn_css(self) -> str:
        return (
            f"QPushButton {{ padding: 4px 12px; border-radius: 6px; background: {_GRAPHITE_DARK_CARD};"
            f" color: {_DANGER}; border: 1px solid {_GRAPHITE_BORDER}; }}"
            f"QPushButton:hover {{ background: {_PALETTE.error_tint(0.10)}; }}"
        )

    def _small_btn_css(self) -> str:
        return (
            f"QPushButton {{ padding: 2px 10px; border-radius: 5px; background: {_GRAPHITE_DARK_CARD};"
            f" color: {_TEXT_SECONDARY}; border: 1px solid {_GRAPHITE_BORDER}; font-size: 10px; }}"
            f"QPushButton:hover {{ background: {_GRAPHITE_BORDER}; }}"
        )

    def _small_danger_btn_css(self) -> str:
        return (
            f"QPushButton {{ padding: 2px 10px; border-radius: 5px; background: {_GRAPHITE_DARK_CARD};"
            f" color: {_DANGER}; border: 1px solid {_GRAPHITE_BORDER}; font-size: 10px; }}"
            f"QPushButton:hover {{ background: rgba(217,101,101,0.12); }}"
        )

    def _on_toggle_changed(self) -> None:
        self._is_enabled = self._toggle.isChecked()
        if self._config is not None:
            self._config.set("memory.enabled", self._is_enabled)
        self._update_controls_state()
        from core.event_bus import EventBus

        EventBus.get_instance().publish(
            "CONFIG_CHANGED",
            {"key": "memory.enabled", "value": self._is_enabled},
        )

    def _update_controls_state(self) -> None:
        enabled = self._is_enabled
        self._btn_add.setEnabled(enabled)
        self._btn_clear.setEnabled(bool(enabled and self._memory is not None))
        self._banner.setVisible(not enabled)
        self._banner.setText(
            "Memory is disabled. Existing memories are preserved. "
            "Enable to add, edit, or delete memories."
        )
        self._search.setEnabled(True)
        for card in self._cards:
            for btn in getattr(card, "_action_btns", []):
                btn.setEnabled(enabled)

    def refresh_memories(self, query: str = "") -> None:
        """Reload memories from the backend and re-render the list."""
        self._clear_container()
        self._cards = []
        entries: list[Any] = []
        if self._memory is not None:
            try:
                if query:
                    entries = self._memory.search_memories(query)
                else:
                    entries = self._memory.get_all_memories()
            except Exception:
                logger.exception("Failed to load memories")
                entries = []
        if not isinstance(entries, list):
            entries = []
        if not entries:
            self._show_empty_state()
        else:
            for entry in entries:
                card = self._make_memory_card(entry)
                self._container_layout.addWidget(card)
                self._cards.append(card)
        self._count_label.setText(
            f"{len(entries)} memor{'y' if len(entries) == 1 else 'ies'}"
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

        title = QLabel("No saved memories yet.")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setWeight(QFont.Weight.DemiBold)
        title.setFont(title_font)
        title.setStyleSheet(f"color: {_TEXT_PRIMARY};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wlayout.addWidget(title)

        note = QLabel("The assistant will store information only with your control.")
        note.setStyleSheet(f"color: {_TEXT_MUTED};")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        wlayout.addWidget(note)

        add_btn = QPushButton("Add Memory")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(self._emerald_btn_css())
        add_btn.setMinimumWidth(160)
        add_btn.clicked.connect(self._on_add)
        wlayout.addWidget(add_btn)

        self._container_layout.addWidget(wrapper)

    def _make_memory_card(self, entry: MemoryEntry) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"background: {_GRAPHITE_CARD}; border: 1px solid {_GRAPHITE_BORDER};"
            f"border-radius: 10px; padding: 14px 16px;"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(8)

        top = QHBoxLayout()
        type_badge = QLabel(_TYPE_LABELS.get(entry.type, entry.type))
        type_badge.setStyleSheet(
            f"background: {_EMERALD_BG_TINT}; color: {_EMERALD_TEXT};"
            f"border: 1px solid {_EMERALD_BORDER_TINT}; border-radius: 8px;"
            f"padding: 2px 8px; font-size: 10px; font-weight: 600;"
        )
        top.addWidget(type_badge)

        created = entry.created_at if entry.created_at else "—"
        date_label = QLabel(f"Created: {created}")
        date_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        top.addWidget(date_label)

        imp_label = QLabel(f"Importance: {(entry.importance or 0.0):.2f}")
        imp_label.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 11px;")
        top.addWidget(imp_label)

        top.addStretch()

        btn_edit = QPushButton("Edit")
        btn_edit.setStyleSheet(self._small_btn_css())
        btn_edit.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_delete = QPushButton("Delete")
        btn_delete.setStyleSheet(self._small_danger_btn_css())
        btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
        btn_edit.setEnabled(self._is_enabled)
        btn_delete.setEnabled(self._is_enabled)

        top.addWidget(btn_edit)
        top.addWidget(btn_delete)
        card._action_btns = [btn_edit, btn_delete]  # type: ignore[attr-defined]

        layout.addLayout(top)

        content = QLabel(entry.content if entry.content else "")
        content.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 12px;")
        content.setWordWrap(True)
        layout.addWidget(content)

        btn_edit.clicked.connect(lambda _e, e=entry: self._on_edit(e))
        btn_delete.clicked.connect(lambda _e, e=entry: self._on_delete(e))
        return card

    def _on_add(self) -> None:
        if not self._is_enabled or self._memory is None:
            return
        dialog = MemoryDialog(parent=self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            entry = dialog.get_entry()
            if entry.content:
                self._memory.save_memory(
                    content=entry.content,
                    mem_type=entry.type,
                    importance=entry.importance,
                )
                self.refresh_memories(self._search.text())
                logger.info("Memory added (type=%s)", entry.type)

    def _on_edit(self, entry: MemoryEntry) -> None:
        if not self._is_enabled or self._memory is None or entry.id is None:
            return
        dialog = MemoryDialog(parent=self, entry=entry)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated = dialog.get_entry()
            self._memory.update_memory(updated)
            self.refresh_memories(self._search.text())
            logger.info("Memory %d updated", entry.id)

    def _confirm(self, title: str, text: str, confirm_label: str) -> bool:
        """Show a modal confirmation dialog with a custom confirm button + Cancel."""
        msg = QMessageBox(self)
        msg.setWindowTitle(title)
        msg.setText(text)
        confirm = msg.addButton(confirm_label, QMessageBox.ButtonRole.AcceptRole)
        msg.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        msg.setDefaultButton(confirm)
        msg.exec()
        return msg.clickedButton() == confirm

    def _on_delete(self, entry: MemoryEntry) -> None:
        if not self._is_enabled or self._memory is None or entry.id is None:
            return
        if self._confirm(
            "Delete memory",
            "Delete this memory?\n\nThis action cannot be undone.",
            "Delete",
        ):
            self._memory.delete_memory(entry.id)
            self.refresh_memories(self._search.text())
            logger.info("Memory %d deleted", entry.id)

    def _on_clear_all(self) -> None:
        if not self._is_enabled or self._memory is None:
            return
        count = len(self._cards)
        if self._confirm(
            "Clear all memories",
            f"Delete all saved memories?\n\nThis action cannot be undone. "
            f"{count} memor{'y' if count == 1 else 'ies'} will be removed.",
            "Delete All",
        ):
            self._memory.delete_all_memories()
            self.refresh_memories(self._search.text())
            logger.info("All memories cleared")

    def _on_search_text(self, text: str) -> None:
        self.refresh_memories(text)

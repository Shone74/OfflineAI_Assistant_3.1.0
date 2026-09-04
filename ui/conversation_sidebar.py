"""Conversation sidebar — list, search, and manage conversations."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class ConversationSidebar(QWidget):
    """Left sidebar showing conversation history with search."""

    conversation_selected = Signal(int)
    new_conversation = Signal()
    delete_conversation = Signal(int)
    rename_conversation = Signal(int, str)
    pin_conversation = Signal(int, bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._conversations: list[dict[str, Any]] = []
        self._selected_id: int | None = None

        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        header = QHBoxLayout()
        title = QLabel("<b>Conversations</b>")
        header.addWidget(title)
        header.addStretch()
        self._btn_new = QPushButton("+")
        self._btn_new.setFixedSize(24, 24)
        self._btn_new.setToolTip("New conversation")
        self._btn_new.clicked.connect(self.new_conversation.emit)
        header.addWidget(self._btn_new)
        layout.addLayout(header)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search conversations...")
        self._search.textChanged.connect(self._on_search_changed)
        layout.addWidget(self._search)

        self._list = QListWidget()
        self._list.itemClicked.connect(self._on_item_clicked)
        self._list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._list)

    def set_conversations(self, conversations: list[dict[str, Any]]) -> None:
        self._conversations = conversations
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._list.clear()
        query = self._search.text().strip().lower()
        for conv in self._conversations:
            title = conv.get("title") or f"Conversation {conv.get('id', '?')}"
            if query and query not in title.lower():
                continue
            item = QListWidgetItem(f"{title}")
            item.setData(1000, conv.get("id"))
            if conv.get("pinned"):
                item.setText(f"📌 {title}")
            self._list.addItem(item)

    def _on_search_changed(self) -> None:
        self._refresh_list()

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        conv_id = item.data(1000)
        if conv_id is not None:
            self._selected_id = int(conv_id)
            self.conversation_selected.emit(self._selected_id)

    def _on_context_menu(self, pos: Any) -> None:
        item = self._list.itemAt(pos)
        if item is None:
            return
        conv_id = int(item.data(1000))
        conv = next((c for c in self._conversations if c.get("id") == conv_id), None)
        is_pinned = conv.get("pinned", False) if conv else False
        menu = QMenu()
        pin_action = menu.addAction("Unpin" if is_pinned else "Pin")
        rename_action = menu.addAction("Rename")
        delete_action = menu.addAction("Delete")
        action = menu.exec(self._list.mapToGlobal(pos))
        if action == pin_action:
            self.pin_conversation.emit(conv_id, not is_pinned)
        elif action == rename_action:
            self.rename_conversation.emit(conv_id, "")
        elif action == delete_action:
            self.delete_conversation.emit(conv_id)

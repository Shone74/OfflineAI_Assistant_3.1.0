"""Plugin settings tab."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.event_bus import EventBus
from plugins.manager import PluginManager
from plugins.models import PluginState


class PluginTab(QWidget):
    """Tab for managing plugins via PluginManager."""

    def __init__(
        self, plugin_manager: PluginManager | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._plugin_manager = plugin_manager
        self._event_bus = plugin_manager.event_bus if plugin_manager is not None else None

        layout = QVBoxLayout(self)

        self._list = QListWidget()
        layout.addWidget(self._list)

        self._details = QTextEdit()
        self._details.setReadOnly(True)
        self._details.setFixedHeight(80)
        layout.addWidget(self._details)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._btn_enable = QPushButton("Enable")
        self._btn_disable = QPushButton("Disable")
        self._btn_unload = QPushButton("Unload")
        btn_layout.addWidget(self._btn_enable)
        btn_layout.addWidget(self._btn_disable)
        btn_layout.addWidget(self._btn_unload)
        layout.addLayout(btn_layout)

        self._btn_enable.clicked.connect(self._on_enable)
        self._btn_disable.clicked.connect(self._on_disable)
        self._btn_unload.clicked.connect(self._on_unload)
        self._list.currentItemChanged.connect(self._on_selection_changed)

        if self._event_bus is not None:
            self._event_bus.subscribe("PLUGIN_ENABLED", self._refresh)
            self._event_bus.subscribe("PLUGIN_DISABLED", self._refresh)
            self._event_bus.subscribe("PLUGIN_LOADED", self._refresh)
            self._event_bus.subscribe("PLUGIN_LOAD_FAILED", self._refresh)
            self._event_bus.subscribe("PLUGIN_ERROR", self._refresh)
            self._event_bus.subscribe("PLUGIN_UNLOADED", self._refresh)

        self._refresh()

    def _refresh(self, *_: Any) -> None:
        self._list.clear()
        if self._plugin_manager is None:
            return
        for pid in sorted(self._plugin_manager.list_plugin_ids()):
            state = self._plugin_manager.get_state(pid)
            metadata = self._plugin_manager.get_metadata(pid)
            name = metadata.name if metadata else pid
            item = QListWidgetItem(f"{name} ({state.value if state is not None else 'unknown'})")
            item.setData(Qt.ItemDataRole.UserRole, pid)
            self._list.addItem(item)
        self._update_details()

    def _on_selection_changed(self, current: QListWidgetItem, previous: QListWidgetItem) -> None:
        self._update_details()

    def _update_details(self) -> None:
        item = self._list.currentItem()
        if item is None or self._plugin_manager is None:
            self._details.clear()
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        metadata = self._plugin_manager.get_metadata(pid)
        state = self._plugin_manager.get_state(pid)
        if metadata is None:
            self._details.clear()
            return
        lines = [
            f"<b>ID:</b> {metadata.id}",
            f"<b>Name:</b> {metadata.name}",
            f"<b>Version:</b> {metadata.version}",
            f"<b>Author:</b> {metadata.author or 'N/A'}",
            f"<b>State:</b> {state.value if state is not None else 'unknown'}",
            f"<b>Description:</b> {metadata.description or 'N/A'}",
        ]
        if metadata.dependencies:
            lines.append(f"<b>Dependencies:</b> {', '.join(metadata.dependencies)}")
        self._details.setText("<br>".join(lines))

    def _on_enable(self) -> None:
        pid = self._current_pid()
        if pid is None or self._plugin_manager is None:
            return
        self._plugin_manager.enable(pid)
        self._plugin_manager.save_plugin_states()
        self._refresh()

    def _on_disable(self) -> None:
        pid = self._current_pid()
        if pid is None or self._plugin_manager is None:
            return
        self._plugin_manager.disable(pid)
        self._plugin_manager.save_plugin_states()
        self._refresh()

    def _on_unload(self) -> None:
        pid = self._current_pid()
        if pid is None or self._plugin_manager is None:
            return
        self._plugin_manager.unload(pid)
        self._plugin_manager.save_plugin_states()
        self._refresh()

    def _current_pid(self) -> str | None:
        item = self._list.currentItem()
        if item is not None:
            return item.data(Qt.ItemDataRole.UserRole)
        if self._list.count() > 0:
            return self._list.item(0).data(Qt.ItemDataRole.UserRole)
        return None
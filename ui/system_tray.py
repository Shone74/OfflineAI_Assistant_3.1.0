"""System tray and notification helpers for the main window."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow


class SystemTrayManager(QObject):
    """Owns the system tray icon and forwards user actions to the main window."""

    show_requested = Signal()
    hide_requested = Signal()
    quit_requested = Signal()

    _shown: bool = False

    def __init__(self, parent: QMainWindow | None = None) -> None:
        super().__init__(parent)
        self._window = parent
        self._shown = False
        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("Offline AI Assistant")

        menu = QMenu()
        show_action = menu.addAction("Show")
        hide_action = menu.addAction("Hide")
        quit_action = menu.addAction("Quit")

        show_action.triggered.connect(self._on_show)
        hide_action.triggered.connect(self._on_hide)
        quit_action.triggered.connect(self._on_quit)

        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_activated)

    def show(self) -> None:
        """Display the tray icon (no-op if the platform tray is unavailable)."""
        if not self._shown:
            self._shown = True
            self._tray.show()

    def set_icon(self, icon: QIcon) -> None:
        self._tray.setIcon(icon)

    def show_notification(self, title: str, message: str) -> None:
        if self._tray.supportsMessages():
            self._tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)

    def close_tray(self) -> None:
        self._tray.hide()

    def _on_show(self) -> None:
        if self._window is not None:
            self._window.showNormal()
            self._window.raise_()
            self._window.activateWindow()
        self.show_requested.emit()

    def _on_hide(self) -> None:
        if self._window is not None:
            self._window.hide()
        self.hide_requested.emit()

    def _on_quit(self) -> None:
        self.quit_requested.emit()

    @Slot(QSystemTrayIcon.ActivationReason)
    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_show()

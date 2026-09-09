"""Filesystem security settings tab."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from core.config_manager import ConfigManager
from core.event_bus import EventBus


class FilesystemSecurityTab(QWidget):
    """Tab for managing filesystem access policy (read/write roots).

    Allows the user to:
      * view current read and write roots
      * add new read/write roots via folder dialogs
      * remove existing roots
      * toggle symlink following
      * reset to safe defaults

    Changes are persisted to the ConfigManager's ``filesystem`` section
    and published as ``CONFIG_CHANGED`` events.
    """

    _GRAPHITE_CARD = "#1C2221"
    _GRAPHITE_BORDER = "#29302E"
    _TEXT_PRIMARY = "#EDF3F0"
    _EMERALD = "#1D8A68"
    _RED = "#C0392B"

    def __init__(
        self,
        event_bus: EventBus | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._config: ConfigManager | None = None
        self._event_bus = event_bus

        main_layout = QVBoxLayout(self)

        # Enable/disable toggle
        self._enabled_checkbox = QCheckBox("Enable filesystem security")
        self._enabled_checkbox.setChecked(True)
        self._enabled_checkbox.stateChanged.connect(self._on_enabled_changed)
        main_layout.addWidget(self._enabled_checkbox)

        # Symlink toggle
        self._symlink_checkbox = QCheckBox("Follow symlinks")
        self._symlink_checkbox.setChecked(True)
        self._symlink_checkbox.stateChanged.connect(self._on_symlink_changed)
        main_layout.addWidget(self._symlink_checkbox)

        # Read roots section
        main_layout.addWidget(QLabel("<b>READ ACCESS</b>"))
        self._read_list = QListWidget()
        main_layout.addWidget(self._read_list)
        read_btns = QHBoxLayout()
        self._btn_add_read = QPushButton("+ Add Read Folder")
        self._btn_add_read.clicked.connect(self._on_add_read)
        self._btn_remove_read = QPushButton("− Remove")
        self._btn_remove_read.clicked.connect(self._on_remove_read)
        read_btns.addWidget(self._btn_add_read)
        read_btns.addWidget(self._btn_remove_read)
        main_layout.addLayout(read_btns)

        # Write roots section
        main_layout.addWidget(QLabel("<b>WRITE ACCESS</b>"))
        self._write_list = QListWidget()
        main_layout.addWidget(self._write_list)
        write_btns = QHBoxLayout()
        self._btn_add_write = QPushButton("+ Add Write Folder")
        self._btn_add_write.clicked.connect(self._on_add_write)
        self._btn_remove_write = QPushButton("− Remove")
        self._btn_remove_write.clicked.connect(self._on_remove_write)
        write_btns.addWidget(self._btn_add_write)
        write_btns.addWidget(self._btn_remove_write)
        main_layout.addLayout(write_btns)

        # Status label
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #8C9692; font-size: 11px;")
        main_layout.addWidget(self._status_label)

        # Reset button
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.clicked.connect(self._on_reset)
        main_layout.addWidget(reset_btn)

        main_layout.addStretch()

    def load_settings(self, config: ConfigManager) -> None:
        """Load filesystem policy from config into the UI."""
        self._config = config
        self._enabled_checkbox.setChecked(config.get("filesystem.enabled", True))
        self._symlink_checkbox.setChecked(config.get("filesystem.follow_symlinks", True))

        self._read_list.clear()
        for root in config.get("filesystem.read_roots", []) or []:
            self._read_list.addItem(root)

        self._write_list.clear()
        for root in config.get("filesystem.write_roots", []) or []:
            self._write_list.addItem(root)

        self._update_status()

    def save_settings(self, config: ConfigManager) -> None:
        """Persist current UI state to config."""
        enabled = self._enabled_checkbox.isChecked()
        follow_symlinks = self._symlink_checkbox.isChecked()
        read_roots = [
            self._read_list.item(i).text() for i in range(self._read_list.count())
        ]
        write_roots = [
            self._write_list.item(i).text() for i in range(self._write_list.count())
        ]

        config.set("filesystem.enabled", enabled)
        config.set("filesystem.follow_symlinks", follow_symlinks)
        config.set("filesystem.read_roots", read_roots)
        config.set("filesystem.write_roots", write_roots)

        if self._event_bus is not None:
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "filesystem.enabled", "value": enabled},
            )
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "filesystem.follow_symlinks", "value": follow_symlinks},
            )
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "filesystem.read_roots", "value": read_roots},
            )
            self._event_bus.publish(
                "CONFIG_CHANGED",
                {"key": "filesystem.write_roots", "value": write_roots},
            )

        self._update_status()

    def _update_status(self) -> None:
        if not self._config:
            return
        enabled = self._config.get("filesystem.enabled", True)
        read_roots = self._config.get("filesystem.read_roots", [])
        write_roots = self._config.get("filesystem.write_roots", [])
        if not isinstance(read_roots, list):
            read_roots = []
        if not isinstance(write_roots, list):
            write_roots = []
        read_count = len(read_roots)
        write_count = len(write_roots)
        if not enabled:
            self._status_label.setText("Filesystem security: <b>DISABLED</b> (all paths allowed)")
        elif not write_count:
            self._status_label.setText(
                f"Filesystem security: <b>enabled</b> — "
                f"{read_count} read root(s), {write_count} write root(s). "
                f"Writes are <font color='{self._RED}'>denied</font> until a write root is configured."
            )
        else:
            self._status_label.setText(
                f"Filesystem security: <b>enabled</b> — "
                f"{read_count} read root(s), {write_count} write root(s). "
                f"All operations restricted to configured roots."
            )

    def _on_enabled_changed(self, state: int) -> None:
        if self._config:
            self._config.set("filesystem.enabled", bool(state))
            self._update_status()
            self._reconfigure_validator()
            if self._event_bus is not None:
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.enabled", "value": bool(state)},
                )

    def _on_symlink_changed(self, state: int) -> None:
        if self._config:
            self._config.set("filesystem.follow_symlinks", bool(state))
            self._update_status()
            self._reconfigure_validator()
            if self._event_bus is not None:
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.follow_symlinks", "value": bool(state)},
                )

    def _reconfigure_validator(self) -> None:
        if self._config is not None:
            from tools.file_security import configure_default_validator_from_config

            configure_default_validator_from_config(self._config)

    def _on_add_read(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Read Folder", "",
            QFileDialog.Option.DontUseNativeDialog,
        )
        if folder:
            self._read_list.addItem(folder)
            if self._config:
                read_roots = [
                    self._read_list.item(i).text()
                    for i in range(self._read_list.count())
                ]
                self._config.set("filesystem.read_roots", read_roots)
                self._reconfigure_validator()
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "CONFIG_CHANGED",
                        {"key": "filesystem.read_roots", "value": read_roots},
                    )
            self._update_status()

    def _on_remove_read(self) -> None:
        current = self._read_list.currentRow()
        if current >= 0:
            self._read_list.takeItem(current)
            if self._config:
                read_roots = [
                    self._read_list.item(i).text()
                    for i in range(self._read_list.count())
                ]
                self._config.set("filesystem.read_roots", read_roots)
                self._reconfigure_validator()
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "CONFIG_CHANGED",
                        {"key": "filesystem.read_roots", "value": read_roots},
                    )
            self._update_status()

    def _on_add_write(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Write Folder", "",
            QFileDialog.Option.DontUseNativeDialog,
        )
        if folder:
            self._write_list.addItem(folder)
            if self._config:
                write_roots = [
                    self._write_list.item(i).text()
                    for i in range(self._write_list.count())
                ]
                self._config.set("filesystem.write_roots", write_roots)
                self._reconfigure_validator()
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "CONFIG_CHANGED",
                        {"key": "filesystem.write_roots", "value": write_roots},
                    )
            self._update_status()

    def _on_remove_write(self) -> None:
        current = self._write_list.currentRow()
        if current >= 0:
            self._write_list.takeItem(current)
            if self._config:
                write_roots = [
                    self._write_list.item(i).text()
                    for i in range(self._write_list.count())
                ]
                self._config.set("filesystem.write_roots", write_roots)
                self._reconfigure_validator()
                if self._event_bus is not None:
                    self._event_bus.publish(
                        "CONFIG_CHANGED",
                        {"key": "filesystem.write_roots", "value": write_roots},
                    )
            self._update_status()

    def _on_reset(self) -> None:
        from PySide6.QtWidgets import QMessageBox

        msg = QMessageBox(self)
        msg.setWindowTitle("Confirm Reset")
        msg.setText("Reset filesystem security to defaults?\n\nThis will clear all configured roots.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self._do_reset()

    def _do_reset(self) -> None:
        """Perform the actual reset (separate from confirmation dialog for testing)."""
        if self._config is not None:
            self._config.set("filesystem.enabled", True)
            self._config.set("filesystem.read_roots", [])
            self._config.set("filesystem.write_roots", [])
            self._config.set("filesystem.follow_symlinks", True)
            self._reconfigure_validator()
            if self._event_bus is not None:
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.enabled", "value": True},
                )
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.read_roots", "value": []},
                )
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.write_roots", "value": []},
                )
                self._event_bus.publish(
                    "CONFIG_CHANGED",
                    {"key": "filesystem.follow_symlinks", "value": True},
                )
        self._read_list.clear()
        self._write_list.clear()
        self._enabled_checkbox.setChecked(True)
        self._symlink_checkbox.setChecked(True)
        self._update_status()
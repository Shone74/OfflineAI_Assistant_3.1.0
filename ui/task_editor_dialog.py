"""Task editor dialog — Add / Edit Scheduled Task form.

Follows the Graphite + Emerald visual language established in
``ui.memory_page`` and ``ui.theme_manager``.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QWidget,
)

from automation.task import AutomationTask, ScheduleType
from core.logger import get_logger

logger = get_logger("ui.task_editor")

_GRAPHITE = "#111516"
_GRAPHITE_CARD = "#1C2221"
_GRAPHITE_DARK_CARD = "#191F1E"
_GRAPHITE_BORDER = "#29302E"
_EMERALD = "#1D8A68"
_EMERGENCY_HOVER = "#249E78"
_EMERALD_TEXT = "#62C7A3"
_EMERALD_BG_TINT = "rgba(29,138,104,0.15)"
_EMERALD_BORDER_TINT = "rgba(29,138,104,0.4)"
_TEXT_PRIMARY = "#EDF3F0"
_TEXT_SECONDARY = "#8C9692"
_TEXT_MUTED = "#737D79"
_DANGER = "#D96565"


class TaskEditorDialog(QDialog):
    """Add / Edit Scheduled Task dialog (reused for both modes)."""

    def __init__(
        self,
        parent: QWidget | None = None,
        task: AutomationTask | None = None,
        workflow_names: list[str] | None = None,
        tool_names: list[str] | None = None,
    ) -> None:
        super().__init__(parent)
        self._task = task
        self._workflow_names = workflow_names or []
        self._tool_names = tool_names or []

        self.setWindowTitle("Add Scheduled Task" if task is None else "Edit Scheduled Task")
        self.resize(520, 420)
        self.setModal(True)

        self._setup_ui()
        if task is not None:
            self._populate_from_task(task)

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("e.g. nightly-backup")
        layout.addRow(QLabel("<b>Name *</b>"), self._name_edit)

        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("Optional description")
        layout.addRow(QLabel("<b>Description</b>"), self._desc_edit)

        self._target_type_combo = QComboBox()
        self._target_type_combo.addItems(["Tool", "Workflow"])
        self._target_type_combo.currentIndexChanged.connect(self._on_target_type_changed)
        layout.addRow(QLabel("<b>Target Type</b>"), self._target_type_combo)

        self._target_combo = QComboBox()
        self._target_combo.setEditable(True)
        self._populate_target_combo()
        layout.addRow(QLabel("<b>Target *</b>"), self._target_combo)

        self._params_edit = QLineEdit()
        self._params_edit.setPlaceholderText('{"key": "value"}')
        layout.addRow(QLabel("<b>Params (JSON)</b>"), self._params_edit)

        schedule_layout = QHBoxLayout()
        self._schedule_interval_radio = QPushButton("Interval")
        self._schedule_interval_radio.setCheckable(True)
        self._schedule_interval_radio.setChecked(True)
        self._schedule_once_radio = QPushButton("Once")
        self._schedule_once_radio.setCheckable(True)
        schedule_layout.addWidget(self._schedule_interval_radio)
        schedule_layout.addWidget(self._schedule_once_radio)
        self._schedule_interval_radio.clicked.connect(self._on_schedule_type_changed)
        self._schedule_once_radio.clicked.connect(self._on_schedule_type_changed)
        layout.addRow(QLabel("<b>Schedule *</b>"), schedule_layout)

        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 86400)
        self._interval_spin.setValue(60)
        layout.addRow(QLabel("Every (seconds)"), self._interval_spin)

        self._run_at_edit = QLineEdit()
        self._run_at_edit.setPlaceholderText("YYYY-MM-DD HH:MM (e.g. 2026-08-27 00:00)")
        self._run_at_edit.setVisible(False)
        layout.addRow(QLabel("Run at"), self._run_at_edit)

        self._enabled_check = QCheckBox("Task is enabled")
        self._enabled_check.setChecked(True)
        layout.addRow(self._enabled_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("Save")
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setText("Cancel")
        layout.addRow(buttons)

        self._name_edit.textChanged.connect(self._on_name_changed)
        self._name_edit.setFocus()

    def _populate_target_combo(self) -> None:
        self._target_combo.clear()
        if self._target_type_combo.currentIndex() == 0:
            items = self._tool_names
        else:
            items = self._workflow_names
        self._target_combo.addItems(items)
        if not items:
            self._target_combo.setEditText("")

    def _on_target_type_changed(self, _index: int) -> None:
        self._populate_target_combo()

    def _on_schedule_type_changed(self) -> None:
        is_interval = self._schedule_interval_radio.isChecked()
        self._interval_spin.setVisible(is_interval)
        self._run_at_edit.setVisible(not is_interval)

    def _on_name_changed(self, _text: str) -> None:
        pass

    def _populate_from_task(self, task: AutomationTask) -> None:
        self._name_edit.setText(task.name or "")
        self._desc_edit.setText(task.description or "")

        if task.target_type == "workflow":
            self._target_type_combo.setCurrentIndex(1)
        else:
            self._target_type_combo.setCurrentIndex(0)
        self._populate_target_combo()

        current_target = task.tool_name
        idx = self._target_combo.findText(current_target)
        if idx >= 0:
            self._target_combo.setCurrentIndex(idx)
        else:
            self._target_combo.setEditText(current_target)

        if task.params:
            try:
                self._params_edit.setText(json.dumps(task.params, ensure_ascii=False))
            except (TypeError, ValueError):
                self._params_edit.setText(str(task.params))

        if task.schedule == ScheduleType.ONCE:
            self._schedule_once_radio.setChecked(True)
            self._on_schedule_type_changed()
            if task.run_at:
                self._run_at_edit.setText(task.run_at.strftime("%Y-%m-%d %H:%M"))
        else:
            self._schedule_interval_radio.setChecked(True)
            self._on_schedule_type_changed()
            self._interval_spin.setValue(int(task.interval_seconds))

        self._enabled_check.setChecked(task.enabled)

    def get_task(self) -> AutomationTask | None:
        """Return an AutomationTask populated from the dialog fields.

        Returns ``None`` if validation fails (caller should check).
        """
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Task name is required.")
            return None

        target = self._target_combo.currentText().strip()
        if not target:
            QMessageBox.warning(self, "Missing target", "Please select a target.")
            return None

        target_type = "workflow" if self._target_type_combo.currentIndex() == 1 else "tool"

        params: dict[str, Any] = {}
        params_raw = self._params_edit.text().strip()
        if params_raw:
            try:
                parsed = json.loads(params_raw)
                if isinstance(parsed, dict):
                    params = parsed
                else:
                    QMessageBox.warning(self, "Invalid params", "Params must be a JSON object.")
                    return None
            except json.JSONDecodeError:
                QMessageBox.warning(self, "Invalid params", "Params must be valid JSON.")
                return None

        if self._schedule_once_radio.isChecked():
            schedule = ScheduleType.ONCE
            run_at_str = self._run_at_edit.text().strip()
            try:
                run_at = datetime.strptime(run_at_str, "%Y-%m-%d %H:%M")  # noqa: DTZ007
            except ValueError:
                QMessageBox.warning(self, "Invalid schedule", "Please enter a valid datetime (YYYY-MM-DD HH:MM).")
                return None
            interval_seconds = 0.0
        else:
            schedule = ScheduleType.INTERVAL
            interval_seconds = float(self._interval_spin.value())
            run_at = None
            if interval_seconds <= 0:
                QMessageBox.warning(self, "Invalid schedule", "Interval must be greater than 0.")
                return None

        if self._task is not None:
            self._task.name = name
            self._task.description = self._desc_edit.text().strip()
            self._task.target_type = target_type
            self._task.tool_name = target
            self._task.params = params
            self._task.schedule = schedule
            self._task.interval_seconds = interval_seconds
            self._task.run_at = run_at
            self._task.enabled = self._enabled_check.isChecked()
            return self._task

        return AutomationTask(
            name=name,
            tool_name=target,
            params=params,
            schedule=schedule,
            interval_seconds=interval_seconds,
            run_at=run_at,
            enabled=self._enabled_check.isChecked(),
            target_type=target_type,
            description=self._desc_edit.text().strip(),
        )

    def accept(self) -> None:
        task = self.get_task()
        if task is None:
            return
        super().accept()

"""Automation dashboard widget — overview of workflows, tasks, and history."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from automation.workflow import Workflow

if TYPE_CHECKING:
    from automation.task import AutomationTask


class AutomationDashboard(QWidget):
    """Dashboard for automation workflows and scheduled tasks."""

    def __init__(self, parent: QWidget | None = None, navigator=None) -> None:
        super().__init__(parent)
        self._navigator = navigator
        self._workflows: dict[str, Workflow] = {}
        self._tasks: list[AutomationTask] = []
        self._history: list[dict[str, Any]] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)

        left = QVBoxLayout()
        self._workflow_list = QListWidget()
        self._workflow_list.itemClicked.connect(self._on_workflow_selected)
        left.addWidget(QLabel("Workflows"))
        left.addWidget(self._workflow_list)

        self._task_list = QListWidget()
        self._task_list.itemClicked.connect(self._on_task_selected)
        self._task_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        left.addWidget(QLabel("Scheduled Tasks"))
        left.addWidget(self._task_list)

        btn_layout = QHBoxLayout()
        self._btn_add_task = QPushButton("+ New Task")
        self._btn_edit_task = QPushButton("Edit")
        self._btn_delete_task = QPushButton("Delete")
        self._btn_run_task = QPushButton("Run Now")
        self._btn_enable = QCheckBox("Enabled")
        self._btn_enable.setChecked(True)
        btn_layout.addWidget(self._btn_add_task)
        btn_layout.addWidget(self._btn_edit_task)
        btn_layout.addWidget(self._btn_delete_task)
        btn_layout.addWidget(self._btn_run_task)
        btn_layout.addWidget(self._btn_enable)
        left.addLayout(btn_layout)

        layout.addLayout(left, stretch=1)

        right = QVBoxLayout()
        self._details = QTextEdit()
        self._details.setReadOnly(True)
        right.addWidget(QLabel("Details"))
        right.addWidget(self._details)

        self._history_list = QListWidget()
        right.addWidget(QLabel("History"))
        right.addWidget(self._history_list)

        nav_layout = QHBoxLayout()
        nav_layout.addStretch()
        self._btn_home = QPushButton("Home")
        self._btn_run = QPushButton("Run Workflow")
        self._btn_refresh = QPushButton("Refresh")
        nav_layout.addWidget(self._btn_home)
        nav_layout.addWidget(self._btn_run)
        nav_layout.addWidget(self._btn_refresh)
        right.addLayout(nav_layout)

        layout.addLayout(right, stretch=2)

        self._btn_run.clicked.connect(self._on_run_workflow)
        self._btn_refresh.clicked.connect(self._on_refresh)
        self._btn_home.clicked.connect(self._on_home)
        self._btn_add_task.clicked.connect(self._on_add_task)
        self._btn_edit_task.clicked.connect(self._on_edit_task)
        self._btn_delete_task.clicked.connect(self._on_delete_task)
        self._btn_run_task.clicked.connect(self._on_run_task)
        self._btn_enable.toggled.connect(self._on_enable_toggled)

    def _on_home(self) -> None:
        if self._navigator is not None:
            self._navigator("Home")
        elif self.parent() is not None and hasattr(self.parent(), "_stack"):
            self.parent()._stack.setCurrentWidget(self.parent()._chat_page)

    def set_workflows(self, workflows: dict[str, Workflow]) -> None:
        self._workflows = workflows
        self._workflow_list.clear()
        for name in sorted(workflows):
            item = QListWidgetItem(name)
            item.setData(1000, name)
            self._workflow_list.addItem(item)

    def set_tasks(self, tasks: list[AutomationTask]) -> None:
        self._tasks = tasks
        self._task_list.clear()
        for task in tasks:
            self._add_task_item(task)

    def set_history(self, history: list[dict[str, Any]]) -> None:
        self._history = list(history)
        self._history_list.clear()
        for entry in self._history:
            ts = entry.get("timestamp", "")
            name = entry.get("workflow", "unknown")
            executed = entry.get("executed", 0)
            failed = entry.get("failed", 0)
            blocked = entry.get("blocked", 0)
            item = QListWidgetItem(f"[{ts}] {name}: {executed} ok, {failed} fail, {blocked} blocked")
            self._history_list.addItem(item)

    def _add_task_item(self, task: AutomationTask) -> None:
        next_run_str = task.next_run.strftime("%Y-%m-%d %H:%M") if task.next_run else "—"
        last_run_str = task.last_run.strftime("%Y-%m-%d %H:%M") if task.last_run else "never"
        schedule_str = task.schedule.value
        if task.schedule.value == "interval":
            schedule_str = f"every {int(task.interval_seconds)}s"
        elif task.schedule.value == "once":
            run_at_str = task.run_at.strftime("%Y-%m-%d %H:%M") if task.run_at else "?"
            schedule_str = f"once at {run_at_str}"
        status_str = task.status.value if task.status else "pending"
        enabled_str = "ON" if task.enabled else "OFF"
        text = f"[{enabled_str}] {task.name} — {schedule_str} — status: {status_str} — next: {next_run_str} — last: {last_run_str}"
        item = QListWidgetItem(text)
        item.setData(1000, task.name)
        if task.status.value == "success":
            item.setForeground(_color("green"))
        elif task.status.value == "failed":
            item.setForeground(_color("red"))
        elif task.status.value == "blocked":
            item.setForeground(_color("orange"))
        elif not task.enabled:
            item.setForeground(_color("gray"))
        self._task_list.addItem(item)

    def add_history(self, entry: dict[str, Any]) -> None:
        self._history.append(entry)
        ts = entry.get("timestamp", datetime.now(UTC).isoformat())
        name = entry.get("workflow", "unknown")
        executed = entry.get("executed", 0)
        failed = entry.get("failed", 0)
        blocked = entry.get("blocked", 0)
        item = QListWidgetItem(f"[{ts}] {name}: {executed} ok, {failed} fail, {blocked} blocked")
        self._history_list.addItem(item)

    def _on_workflow_selected(self, item: QListWidgetItem) -> None:
        name = item.data(1000)
        workflow = self._workflows.get(name)
        if workflow is None:
            return
        lines = [
            f"<b>Workflow:</b> {workflow.name}",
            f"<b>Description:</b> {workflow.description or 'N/A'}",
            f"<b>Steps:</b> {len(workflow.steps)}",
        ]
        for i, step in enumerate(workflow.steps, 1):
            cond = f" <b>if</b> {step.condition}" if step.condition else ""
            lines.append(f"{i}. {step.tool_name}: {step.description or step.params}{cond}")
        self._details.setText("<br>".join(lines))

    def _on_task_selected(self, item: QListWidgetItem) -> None:
        name = item.data(1000)
        for task in self._tasks:
            if task.name == name:
                target = f"Workflow: {task.tool_name}" if task.target_type == "workflow" else f"Tool: {task.tool_name}"
                schedule_str = f"Every {int(task.interval_seconds)}s" if task.schedule.value == "interval" else f"Once at {task.run_at}"
                lines = [
                    f"<b>Task:</b> {task.name}",
                    f"<b>Description:</b> {task.description or 'N/A'}",
                    f"<b>Target:</b> {target}",
                    f"<b>Params:</b> {task.params}",
                    f"<b>Schedule:</b> {schedule_str}",
                    f"<b>Enabled:</b> {'Yes' if task.enabled else 'No'}",
                    f"<b>Status:</b> {task.status.value if task.status else 'pending'}",
                ]
                self._details.setText("<br>".join(lines))
                return

    def _on_run_workflow(self) -> None:
        item = self._workflow_list.currentItem()
        if item is None:
            return
        name = item.data(1000)
        self.run_requested.emit(name)

    def _on_refresh(self) -> None:
        self._history_list.clear()
        for entry in self._history:
            ts = entry.get("timestamp", "")
            name = entry.get("workflow", "unknown")
            executed = entry.get("executed", 0)
            failed = entry.get("failed", 0)
            blocked = entry.get("blocked", 0)
            item = QListWidgetItem(f"[{ts}] {name}: {executed} ok, {failed} fail, {blocked} blocked")
            self._history_list.addItem(item)

    def _on_add_task(self) -> None:
        self.task_editor_requested.emit(None)

    def _on_edit_task(self) -> None:
        item = self._task_list.currentItem()
        if item is None:
            return
        name = item.data(1000)
        self.task_editor_requested.emit(name)

    def _on_delete_task(self) -> None:
        item = self._task_list.currentItem()
        if item is None:
            return
        name = item.data(1000)
        self.task_deleted.emit(name)

    def _on_run_task(self) -> None:
        item = self._task_list.currentItem()
        if item is None:
            return
        name = item.data(1000)
        self.task_run_requested.emit(name)

    def _on_enable_toggled(self, checked: bool) -> None:
        item = self._task_list.currentItem()
        if item is None:
            self._btn_enable.setChecked(not checked)
            return
        name = item.data(1000)
        self.task_enabled_changed.emit(name, checked)

    # Signals
    run_requested = Signal(str)
    task_editor_requested = Signal(object)
    task_deleted = Signal(str)
    task_run_requested = Signal(str)
    task_enabled_changed = Signal(str, bool)


def _color(name: str):
    from PySide6.QtGui import QColor
    colors = {
        "green": QColor(0, 180, 0),
        "red": QColor(180, 0, 0),
        "orange": QColor(255, 140, 0),
        "gray": QColor(128, 128, 128),
    }
    return colors.get(name, QColor(0, 0, 0))

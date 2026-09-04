"""Workflow builder widget — simple ordered step editor."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from automation.workflow import Workflow, WorkflowStep


class WorkflowBuilder(QWidget):
    """Widget for creating and editing workflows."""

    def __init__(
        self,
        automation_manager: Any | None = None,
        parent: QWidget | None = None,
        navigator=None,
    ) -> None:
        super().__init__(parent)
        self._navigator = navigator
        self._workflow: Workflow | None = None
        self._automation_manager = automation_manager
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._name_input = QLineEdit()
        self._desc_input = QTextEdit()
        self._desc_input.setFixedHeight(60)
        self._cb_enabled = QCheckBox("Enabled")
        self._cb_enabled.setChecked(True)
        form.addRow("Name:", self._name_input)
        form.addRow("Description:", self._desc_input)
        form.addRow("", self._cb_enabled)
        layout.addLayout(form)

        self._steps_list = QListWidget()
        layout.addWidget(self._steps_list)

        step_form = QFormLayout()
        self._tool_combo = QComboBox()
        self._tool_combo.setEditable(True)
        self._param_input = QLineEdit()
        self._cond_input = QLineEdit()
        self._cond_input.setPlaceholderText("Optional Python condition, e.g. x > 5")
        step_form.addRow("Tool:", self._tool_combo)
        step_form.addRow("Params (JSON):", self._param_input)
        step_form.addRow("Condition:", self._cond_input)
        layout.addLayout(step_form)

        load_layout = QHBoxLayout()
        self._workflow_combo = QComboBox()
        self._btn_load = QPushButton("Load Workflow")
        self._btn_refresh = QPushButton("Refresh")
        load_layout.addWidget(self._workflow_combo)
        load_layout.addWidget(self._btn_load)
        load_layout.addWidget(self._btn_refresh)
        layout.addLayout(load_layout)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self._btn_execute = QPushButton("Execute Workflow")
        self._btn_execute.setEnabled(False)
        self._btn_home = QPushButton("Home")
        self._btn_add = QPushButton("Add Step")
        self._btn_remove = QPushButton("Remove Step")
        self._btn_save = QPushButton("Save Workflow")
        btn_layout.addWidget(self._btn_execute)
        btn_layout.addWidget(self._btn_home)
        btn_layout.addWidget(self._btn_add)
        btn_layout.addWidget(self._btn_remove)
        btn_layout.addWidget(self._btn_save)
        layout.addLayout(btn_layout)

        self._btn_home.clicked.connect(self._on_home)
        self._btn_add.clicked.connect(self._on_add_step)
        self._btn_remove.clicked.connect(self._on_remove_step)
        self._btn_save.clicked.connect(self._on_save)
        self._btn_load.clicked.connect(self._on_load_workflow)
        self._btn_refresh.clicked.connect(self._on_refresh_workflows)
        self._btn_execute.clicked.connect(self._on_execute)

        self._refresh_workflow_list()
        self._refresh_tool_combo()

    def _refresh_workflow_list(self) -> None:
        """Populate the workflow combo box with available user workflows."""
        self._workflow_combo.clear()
        if self._automation_manager is None:
            return

        user_workflows = [
            name for name in self._automation_manager.list_workflows()
            if name != "system_check"
        ]
        for name in sorted(user_workflows):
            self._workflow_combo.addItem(name)

    def _refresh_tool_combo(self) -> None:
        """Populate the tool combo from the canonical ToolRegistry."""
        self._tool_combo.clear()
        registry = getattr(self._automation_manager, "_registry", None)
        if registry is None:
            return
        for tool_name in registry.list_all_tool_names():
            self._tool_combo.addItem(tool_name)

    def load_workflow(self, workflow: Workflow) -> None:
        self._workflow = workflow
        self._name_input.setText(workflow.name)
        self._desc_input.setText(workflow.description or "")
        self._cb_enabled.setChecked(workflow.enabled)
        self._btn_execute.setEnabled(workflow.enabled)
        self._steps_list.clear()
        for step in workflow.steps:
            item = QListWidgetItem(f"{step.tool_name}: {step.description or step.params}")
            item.setData(1000, step)
            self._steps_list.addItem(item)

    def load_workflow_name(self, name: str) -> bool:
        """Load a workflow by name. Returns True on success."""
        if self._automation_manager is None:
            return False
        workflow = self._automation_manager.get_workflow(name)
        if workflow is None:
            QMessageBox.warning(self, "Load Error", f"Workflow '{name}' not found")
            return False
        self.load_workflow(workflow)
        return True

    def _on_add_step(self) -> None:
        tool = self._tool_combo.currentText().strip()
        if not tool:
            return
        params_raw = self._param_input.text().strip()
        params: dict[str, Any] = {}
        if params_raw:
            import json
            try:
                params = json.loads(params_raw)
            except json.JSONDecodeError:
                params = {"query": params_raw}
        condition = self._cond_input.text().strip() or None
        step = WorkflowStep(tool_name=tool, params=params, description="", condition=condition)
        item = QListWidgetItem(f"{tool}: {condition or params}")
        item.setData(1000, step)
        self._steps_list.addItem(item)
        self._param_input.clear()
        self._cond_input.clear()

    def _on_remove_step(self) -> None:
        row = self._steps_list.currentRow()
        if row >= 0:
            self._steps_list.takeItem(row)

    def _on_save(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Workflow name is required")
            return
        steps: list[WorkflowStep] = []
        for i in range(self._steps_list.count()):
            item = self._steps_list.item(i)
            step = item.data(1000)
            if isinstance(step, WorkflowStep):
                steps.append(step)
        self._workflow = Workflow(
            name=name,
            steps=steps,
            description=self._desc_input.toPlainText(),
            enabled=self._cb_enabled.isChecked(),
        )
        if self._automation_manager is not None:
            self._automation_manager.register_workflow(self._workflow)
            self._refresh_workflow_list()
        self._btn_execute.setEnabled(self._cb_enabled.isChecked())
        self._steps_list.clear()
        for step in self._workflow.steps:
            item = QListWidgetItem(f"{step.tool_name}: {step.description or step.params}")
            item.setData(1000, step)
            self._steps_list.addItem(item)

    def _on_load_workflow(self) -> None:
        name = self._workflow_combo.currentText().strip()
        if not name:
            QMessageBox.warning(self, "Load Error", "Please select a workflow")
            return
        self.load_workflow_name(name)

    def _on_execute(self) -> None:
        if self._workflow is None:
            QMessageBox.warning(self, "Execute Error", "No workflow loaded")
            return
        if self._automation_manager is None:
            QMessageBox.warning(self, "Execute Error", "Automation manager not available")
            return
        result = self._automation_manager.run_workflow(self._workflow.name)
        QMessageBox.information(self, "Execution Result", result)

    def _on_refresh_workflows(self) -> None:
        self._refresh_workflow_list()
        self._refresh_tool_combo()

    def _on_home(self) -> None:
        if self._navigator is not None:
            self._navigator("Home")
        elif self.parent() is not None and hasattr(self.parent(), "_stack"):
            self.parent()._stack.setCurrentWidget(self.parent()._chat_page)

    def workflow(self) -> Workflow | None:
        return self._workflow

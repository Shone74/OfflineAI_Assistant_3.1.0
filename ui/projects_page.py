"""Projects page — full CRUD UI for project management with runtime state display.

Implements the Sidebar "Projects" feature as a real, usable application feature:

- List projects from persistent storage (ProjectManager)
- Create project with name, description, workspace path
- Open project (sets active project context — does NOT start an Agent)
- Set Active (records agent assignment — separate from Open)
- Edit project metadata (name, description, workspace path)
- Delete project (removes registration, preserves filesystem), with optional deep delete
- Refresh (reloads from DB + refreshes runtime state)
- Display runtime state (IDLE / ACTIVE / TASK COMPLETED / ERROR)
- Project context display (identity, workspace path, file listing, agent assignment)
- Chat ↔ Project integration (open project signal)
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.logger import get_logger
from tools.file_security import PathValidationError

logger = get_logger("projects_page")

from ui.design import WORKSPACE as _PALETTE

_GRAPHITE = _PALETTE.surface
_GRAPHITE_CARD = _PALETTE.surface_card
_GRAPHITE_DARK_CARD = _PALETTE.surface_dark
_GRAPHITE_BORDER = _PALETTE.border
_EMERALD = _PALETTE.emerald
_EMERGENCY_HOVER = _PALETTE.emerald_hover
_EMERALD_TEXT = _PALETTE.emerald_text
_EMERALD_BG_TINT = _PALETTE.tint(0.08)
_EMERALD_BORDER_TINT = _PALETTE.tint(0.25)
_TEXT_PRIMARY = _PALETTE.text_primary
_TEXT_SECONDARY = _PALETTE.text_secondary
_TEXT_MUTED = _PALETTE.text_muted
_RED = _PALETTE.error
_ORANGE = _PALETTE.warning
_BLUE = "#4A90D9"  # info akcenat (van zvaniÄne palete; jedini izuzetak)


class ProjectsPage(QWidget):
    """Full-featured Projects management page.

    Signals:
        project_opened: Emitted when a project is opened (project_id, project_name).
        project_created: Emitted when a project is created.
        project_updated: Emitted when a project is updated.
        project_deleted: Emitted when a project is deleted.
        refresh_requested: Emitted when refresh is requested from the page.
        assign_agent_requested: Emitted when user requests agent assignment
            (project_id, agent_name).
        run_agent_requested: Emitted when user requests the assigned agent to run
            (project_id, goal).
    """

    project_opened = Signal(str, str)
    project_created = Signal(str)
    project_updated = Signal(str)
    project_deleted = Signal(str)
    refresh_requested = Signal()
    assign_agent_requested = Signal(str, str)
    run_agent_requested = Signal(str, str)

    def __init__(self, assistant: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._assistant = assistant
        self._project_mgr = getattr(assistant, "_project_manager", None) if assistant else None
        self._context_mgr = getattr(assistant, "_context_manager", None) if assistant else None
        self._event_bus = getattr(assistant, "event_bus", None) if assistant else None
        self._agent_repo = getattr(assistant, "_agent_repository", None) if assistant else None
        self._knowledge = getattr(assistant, "_knowledge", None) if assistant else None

        self._projects: list[Any] = []
        self._selected_project: Any = None
        self._build_ui()
        self._subscribe_events()
        self.refresh()

    def _subscribe_events(self) -> None:
        if self._event_bus is None:
            return
        for evt in (
            "PROJECT_CREATED",
            "PROJECT_UPDATED",
            "PROJECT_DELETED",
            "PROJECT_OPENED",
            "PROJECT_CLOSED",
            "PROJECT_AGENT_STATE_CHANGED",
            "AGENT_ASSIGNED_TO_PROJECT",
            "AGENT_FINISHED",
            "AGENT_ERROR",
        ):
            self._event_bus.subscribe(evt, self._on_event)

    def _on_event(self, event_type: str, data: dict) -> None:
        if event_type in ("PROJECT_CREATED", "PROJECT_UPDATED", "PROJECT_DELETED", "PROJECT_AGENT_STATE_CHANGED", "AGENT_ASSIGNED_TO_PROJECT", "AGENT_FINISHED", "AGENT_ERROR"):
            self.refresh()

    def refresh(self) -> None:
        """Reload project list and runtime state from persistence."""
        self._load_projects()
        self._rebuild_project_list()
        self._refresh_selected_detail()
        self.refresh_requested.emit()

    def _load_projects(self) -> None:
        if self._project_mgr is None:
            self._projects = []
            return
        try:
            self._projects = self._project_mgr.list_projects()
        except Exception as exc:
            logger.debug("Could not list projects: %s", exc)
            self._projects = []

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header = self._build_header()
        layout.addLayout(header)

        content = self._build_content()
        layout.addLayout(content, stretch=1)

    def _build_header(self) -> QHBoxLayout:
        header = QHBoxLayout()

        title = QLabel("Projects")
        title.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 15px; font-weight: 600;")
        header.addWidget(title)

        header.addStretch()

        btn_refresh = QPushButton("⟳ Refresh")
        btn_refresh.setStyleSheet(self._button_style())
        btn_refresh.setFixedSize(90, 26)
        btn_refresh.clicked.connect(self._on_refresh)
        header.addWidget(btn_refresh)

        btn_create = QPushButton("+ New Project")
        btn_create.setStyleSheet(self._button_style(highlight=True))
        btn_create.setFixedSize(120, 26)
        btn_create.clicked.connect(self._on_create_project)
        header.addWidget(btn_create)

        return header

    def _build_content(self) -> QHBoxLayout:
        self._main_layout = QHBoxLayout()
        self._main_layout.setSpacing(16)

        self._project_list_container = QFrame()
        self._project_list_layout = QVBoxLayout(self._project_list_container)
        self._project_list_layout.setContentsMargins(0, 0, 0, 0)
        self._project_list_layout.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(self._scroll_style())
        scroll.setWidget(self._project_list_container)

        list_wrapper = QFrame()
        list_layout = QVBoxLayout(list_wrapper)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)
        list_layout.addWidget(scroll)
        list_wrapper.setFixedWidth(280)
        list_wrapper.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self._detail_container = QFrame()
        self._detail_container.setStyleSheet(
            f"background: {_GRAPHITE_CARD}; border: 1px solid {_GRAPHITE_BORDER};"
            f" border-radius: 10px;"
        )
        detail_layout = QVBoxLayout(self._detail_container)
        detail_layout.setContentsMargins(20, 20, 20, 20)
        detail_layout.setSpacing(14)

        self._detail_title = QLabel("No project selected")
        self._detail_title.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 15px; font-weight: 600;")
        detail_layout.addWidget(self._detail_title)

        self._detail_content = QFrame()
        self._detail_content_layout = QVBoxLayout(self._detail_content)
        self._detail_content_layout.setContentsMargins(0, 0, 0, 0)
        self._detail_content_layout.setSpacing(12)
        detail_layout.addWidget(self._detail_content, stretch=1)

        self._detail_buttons = QHBoxLayout()
        self._detail_buttons.addStretch()
        self._btn_open = QPushButton("Open")
        self._btn_open.setStyleSheet(self._button_style(highlight=True))
        self._btn_open.setFixedSize(80, 26)
        self._btn_open.clicked.connect(self._on_open_project)
        self._detail_buttons.addWidget(self._btn_open)
        self._btn_open.setVisible(False)

        self._btn_assign_agent = QPushButton("Assign Agent")
        self._btn_assign_agent.setStyleSheet(self._button_style(highlight=True))
        self._btn_assign_agent.setFixedSize(110, 26)
        self._btn_assign_agent.clicked.connect(self._on_assign_agent)
        self._detail_buttons.addWidget(self._btn_assign_agent)
        self._btn_assign_agent.setVisible(False)

        self._btn_run_agent = QPushButton("Run Agent")
        self._btn_run_agent.setStyleSheet(self._button_style(highlight=True))
        self._btn_run_agent.setFixedSize(90, 26)
        self._btn_run_agent.clicked.connect(self._on_run_agent)
        self._detail_buttons.addWidget(self._btn_run_agent)
        self._btn_run_agent.setVisible(False)

        self._btn_edit = QPushButton("Edit")
        self._btn_edit.setStyleSheet(self._button_style())
        self._btn_edit.setFixedSize(70, 26)
        self._btn_edit.clicked.connect(self._on_edit_project)
        self._detail_buttons.addWidget(self._btn_edit)
        self._btn_edit.setVisible(False)

        self._btn_delete = QPushButton("Delete")
        self._btn_delete.setStyleSheet(self._button_style())
        self._btn_delete.setFixedSize(70, 26)
        self._btn_delete.clicked.connect(self._on_delete_project)
        self._detail_buttons.addWidget(self._btn_delete)
        self._btn_delete.setVisible(False)

        detail_layout.addLayout(self._detail_buttons)

        self._main_layout.addWidget(list_wrapper)
        self._main_layout.addWidget(self._detail_container, stretch=2)

        return self._main_layout

    def _rebuild_project_list(self) -> None:
        while self._project_list_layout.count():
            child = self._project_list_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        if not self._projects:
            self._project_list_layout.addWidget(self._build_empty_state())
        else:
            for proj in self._projects:
                card = self._build_project_list_card(proj)
                self._project_list_layout.addWidget(card)

        self._project_list_layout.addStretch()

    def _build_project_list_card(self, proj: Any) -> QFrame:
        card = QFrame()
        card.setCursor(Qt.CursorShape.PointingHandCursor)
        card.setStyleSheet(self._card_style(selected=False))
        card.mousePressEvent = lambda evt, p=proj: self._on_select_project(p)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(6)

        name_label = QLabel(proj.name or "Untitled")
        name_label.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 13px; font-weight: 600;")
        label_layout = QHBoxLayout()
        label_layout.addWidget(name_label)
        label_layout.addStretch()

        status_label = QLabel(self._runtime_state_label(proj))
        status_label.setStyleSheet(self._runtime_state_style(proj))
        label_layout.addWidget(status_label)
        layout.addLayout(label_layout)

        desc = QLabel(proj.description or "No description")
        desc.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px; line-height: 1.4;")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        if proj.workspace_path:
            path_label = QLabel(proj.workspace_path)
            path_label.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px; line-height: 1.2;")
            path_label.setToolTip(proj.workspace_path)
            layout.addWidget(path_label)

        return card

    def _on_select_project(self, proj: Any) -> None:
        self._selected_project = proj
        self._rebuild_project_list()
        self._refresh_selected_detail()

    def _refresh_selected_detail(self) -> None:
        if self._detail_content is None or self._detail_title is None:
            return

        if self._selected_project is None:
            self._detail_title.setText("No project selected")
            self._detail_title.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 15px; font-weight: 600;")
            self._clear_detail_content()
            self._hide_detail_buttons()
            return

        proj = self._selected_project
        self._detail_title.setText(proj.name or "Untitled")
        self._detail_title.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 15px; font-weight: 600;")

        self._clear_detail_content()
        detail_layout = self._detail_content_layout

        info_grid = QFrame()
        grid = QHBoxLayout(info_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)

        left_col = QVBoxLayout()
        left_col.setSpacing(4)
        self._add_info_row(left_col, "ID:", proj.id)
        self._add_info_row(left_col, "Description:", proj.description or "—")
        self._add_info_row(left_col, "Workspace:", proj.workspace_path or "—")
        self._add_info_row(left_col, "Created:", proj.created_at or "—")

        right_col = QVBoxLayout()
        right_col.setSpacing(4)
        self._add_info_row(right_col, "Runtime:", self._runtime_state_label(proj))
        agent_name = self._get_assigned_agent_name(proj)
        self._add_info_row(right_col, "Agent:", agent_name or "—")

        grid.addLayout(left_col, stretch=1)
        grid.addLayout(right_col, stretch=1)
        detail_layout.addWidget(info_grid)

        files_section = self._build_files_section(proj)
        detail_layout.addWidget(files_section)

        agent_section = self._build_agent_section(proj)
        detail_layout.addWidget(agent_section)

        detail_layout.addStretch()

        self._show_detail_buttons(proj)

    def _add_info_row(self, layout: QVBoxLayout, label: str, value: str) -> None:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        lbl = QLabel(label)
        lbl.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
        val = QLabel(str(value))
        val.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 11px;")
        val.setWordWrap(True)
        row.addWidget(lbl)
        row.addWidget(val, stretch=1)
        layout.addLayout(row)

    def _get_assigned_agent_name(self, proj: Any) -> str | None:
        if self._context_mgr is None:
            return None
        ctx = self._context_mgr.get_context(proj.id)
        if ctx is None or ctx.agent_assignment is None:
            return None
        return ctx.agent_assignment.agent_name

    def _get_runtime_state(self, proj: Any) -> str:
        if self._context_mgr is None:
            return "IDLE"
        ctx = self._context_mgr.get_context(proj.id)
        if ctx is None:
            return "IDLE"
        return ctx.runtime_state.value.upper()

    def _runtime_state_label(self, proj: Any) -> str:
        state = self._get_runtime_state(proj)
        labels = {
            "idle": "IDLE",
            "active": "ACTIVE",
            "task_completed": "TASK COMPLETED",
            "error": "ERROR",
        }
        return labels.get(state.lower(), "IDLE")

    def _runtime_state_style(self, proj: Any) -> str:
        state = self._runtime_state_label(proj).upper()
        if state == "ACTIVE":
            color = _EMERGENCY_HOVER
        elif state == "TASK COMPLETED":
            color = _EMERALD_TEXT
        elif state == "ERROR":
            color = _RED
        else:
            color = _TEXT_MUTED
        return f"color: {color}; font-size: 10px; font-weight: 600;"

    def _build_files_section(self, proj: Any) -> QFrame:
        section = QFrame()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QLabel("Project Files")
        header.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 11px; font-weight: 600;")
        layout.addWidget(header)

        if not proj.workspace_path:
            no_path = QLabel("No workspace path set")
            no_path.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
            layout.addWidget(no_path)
        else:
            files = self._list_workspace_files(proj)
            if not files:
                no_files = QLabel("No files found in workspace")
                no_files.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px;")
                layout.addWidget(no_files)
            else:
                list_widget = QFrame()
                file_layout = QVBoxLayout(list_widget)
                file_layout.setContentsMargins(0, 0, 0, 0)
                file_layout.setSpacing(2)
                for f in files[:50]:
                    fl = QLabel(f)
                    fl.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 10px;")
                    fl.setToolTip(f)
                    file_layout.addWidget(fl)
                layout.addWidget(list_widget)
                if len(files) > 50:
                    more = QLabel(f"... and {len(files) - 50} more")
                    more.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 10px;")
                    layout.addWidget(more)

        return section

    def _list_workspace_files(self, proj: Any) -> list[str]:
        if self._project_mgr is None:
            return []
        try:
            return self._project_mgr.list_project_files(proj.id, include_hidden=False)
        except Exception as exc:
            logger.debug("Could not list project files: %s", exc)
            return []

    def _build_agent_section(self, proj: Any) -> QFrame:
        section = QFrame()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QLabel("Agent")
        header.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 11px; font-weight: 600;")
        layout.addWidget(header)

        ctx = None
        if self._context_mgr is not None:
            ctx = self._context_mgr.get_context(proj.id)

        if ctx is None or ctx.agent_assignment is None:
            info = QLabel("No agent assigned. Assign an agent to run automated tasks.")
            info.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 11px; line-height: 1.4;")
            info.setWordWrap(True)
            layout.addWidget(info)
        else:
            agent_name = ctx.agent_assignment.agent_name
            state = ctx.agent_assignment.runtime_state.value.upper()
            state_labels = {
                "idle": "IDLE",
                "active": "ACTIVE",
                "task_completed": "TASK COMPLETED",
                "error": "ERROR",
            }
            state_display = state_labels.get(state.lower(), state)

            if state == "active":
                color = _EMERGENCY_HOVER
            elif state == "task_completed":
                color = _EMERALD_TEXT
            elif state == "error":
                color = _RED
            else:
                color = _TEXT_MUTED

            info = QLabel(f"<b>{agent_name}</b><br>Status: <span style='color:{color}'>{state_display}</span>")
            info.setStyleSheet(f"color: {_TEXT_SECONDARY}; font-size: 11px;")
            info.setTextFormat(Qt.TextFormat.RichText)
            layout.addWidget(info)

            if ctx.agent_assignment.last_task:
                task = QLabel(f"Last task: {ctx.agent_assignment.last_task}")
                task.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 10px;")
                task.setWordWrap(True)
                layout.addWidget(task)

        return section

    def _show_detail_buttons(self, proj: Any) -> None:
        self._btn_open.setVisible(True)
        self._btn_edit.setVisible(True)
        self._btn_delete.setVisible(True)

        has_agent = self._context_mgr is not None and self._context_mgr.get_context(proj.id) is not None
        if has_agent:
            ctx = self._context_mgr.get_context(proj.id)
            if ctx and ctx.agent_assignment is not None:
                self._btn_assign_agent.setVisible(False)
                self._btn_run_agent.setVisible(True)
            else:
                self._btn_assign_agent.setVisible(True)
                self._btn_run_agent.setVisible(False)
        else:
            self._btn_assign_agent.setVisible(True)
            self._btn_run_agent.setVisible(False)

    def _hide_detail_buttons(self) -> None:
        self._btn_open.setVisible(False)
        self._btn_edit.setVisible(False)
        self._btn_delete.setVisible(False)
        self._btn_assign_agent.setVisible(False)
        self._btn_run_agent.setVisible(False)

    def _clear_detail_content(self) -> None:
        while self._detail_content.layout().count():
            child = self._detail_content.layout().takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _build_empty_state(self) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"background: {_GRAPHITE_CARD}; border: 1px solid {_GRAPHITE_BORDER};"
            f"border-radius: 10px; padding: 26px; text-align: center;"
        )
        layout = QVBoxLayout(card)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        icon = QLabel()
        icon.setPixmap(self._folder_pixmap())
        layout.addWidget(icon, alignment=Qt.AlignmentFlag.AlignCenter)

        title = QLabel("No projects")
        title.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 13px; font-weight: 600;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            "Create a project to get started.<br>"
            "Projects let you organize conversations and files around a workspace."
        )
        desc.setStyleSheet(f"color: {_TEXT_MUTED}; font-size: 10px; line-height: 1.5;")
        desc.setWordWrap(True)
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(desc)

        return card

    def _on_create_project(self) -> None:
        if self._project_mgr is None:
            self._show_error("Project manager not available")
            return
        dialog = CreateProjectDialog(self)
        if dialog.exec() == 1 and dialog.result_data:
            data = dialog.result_data
            try:
                self._project_mgr.create_project(
                    name=data["name"],
                    description=data["description"],
                    workspace_path=data["workspace_path"] or None,
                )
                self.refresh()
                self.project_created.emit("ok")
                self._show_status("Project created successfully")
            except ValueError as exc:
                self._show_error(str(exc))
            except PathValidationError as exc:
                # Filesystem security denial (write roots policy) — surfaced
                # as a clear authorization error; ProjectManager is the
                # security boundary, the UI only reports.
                self._show_error(f"Workspace not authorized: {exc}")
            except Exception as exc:
                logger.exception("Failed to create project")
                self._show_error(f"Failed to create project: {exc}")

    def _on_open_project(self) -> None:
        if self._selected_project is None:
            return
        proj = self._selected_project
        try:
            if self._assistant is not None:
                self._assistant.open_project(proj.id)
            self.project_opened.emit(proj.id, proj.name or "Untitled")
            self._show_status(f"Project '{proj.name}' opened")
        except ValueError as exc:
            self._show_error(str(exc))

    def _on_edit_project(self) -> None:
        if self._selected_project is None or self._project_mgr is None:
            return
        proj = self._selected_project
        dialog = EditProjectDialog(self, proj)
        if dialog.exec() == 1 and dialog.result_data:
            data = dialog.result_data
            updates = {}
            name = data.get("name", "")
            if name:
                updates["name"] = name
            updates["description"] = data.get("description", "")
            if data.get("workspace_path"):
                updates["workspace_path"] = data["workspace_path"]
            if updates:
                try:
                    self._project_mgr.update_project(proj.id, **updates)
                    self.refresh()
                    self.project_updated.emit(proj.id)
                    self._show_status("Project updated")
                except ValueError as exc:
                    self._show_error(str(exc))
                except PathValidationError as exc:
                    # Filesystem security denial (write roots policy).
                    self._show_error(f"Workspace not authorized: {exc}")
                except Exception as exc:
                    logger.exception("Failed to update project")
                    self._show_error(f"Failed to update project: {exc}")

    def _on_delete_project(self) -> None:
        if self._selected_project is None or self._project_mgr is None:
            return
        proj = self._selected_project

        has_workspace = bool(proj.workspace_path)
        if has_workspace:
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Delete Project")
            msg_box.setText(
                f"Delete registration for project '{proj.name}'?\n\n"
                f"Workspace path: {proj.workspace_path}\n\n"
                f"Physical files will be preserved."
            )
            # Note: Qt has no StandardButton.Delete — custom buttons keep the
            # three-way choice (Delete / Also delete files / Cancel).
            btn_delete = msg_box.addButton(
                "Delete", QMessageBox.ButtonRole.DestructiveRole
            )
            btn_delete_files = msg_box.addButton(
                "Also delete files", QMessageBox.ButtonRole.AcceptRole
            )
            btn_cancel = msg_box.addButton(
                "Cancel", QMessageBox.ButtonRole.RejectRole
            )
            btn_cancel.setStyleSheet(
                f"background: {_GRAPHITE_BORDER}; color: {_TEXT_PRIMARY};"
            )
            msg_box.setDefaultButton(btn_cancel)
            msg_box.exec()

            btn = msg_box.clickedButton()
            if btn is btn_delete_files:
                # Route the destructive operation through ProjectManager so
                # WRITE authorization (filesystem security policy) is
                # enforced BEFORE any deletion runs.  The UI never calls
                # shutil.rmtree on an unvalidated path.
                try:
                    self._project_mgr.delete_workspace_files(proj.id)
                except PathValidationError as exc:
                    self._show_error(f"Deletion not authorized: {exc}")
                    return
                except Exception as exc:
                    logger.exception("Failed to delete workspace files")
                    self._show_error(f"Could not delete files: {exc}")
                    return
            elif btn is not btn_delete:
                return

        try:
            self._project_mgr.delete_project(proj.id)
            if self._context_mgr is not None:
                self._context_mgr.close_project(proj.id)
            if self._assistant is not None and proj.id == self._assistant.get_active_project_id():
                self._assistant.clear_active_project()
            self._selected_project = None
            self.refresh()
            self.project_deleted.emit(proj.id)
            self._show_status("Project deleted")
        except Exception as exc:
            logger.exception("Failed to delete project")
            self._show_error(f"Failed to delete project: {exc}")

    def _on_assign_agent(self) -> None:
        if self._selected_project is None or self._agent_repo is None:
            return
        proj = self._selected_project
        agent_name, ok = QInputDialog.getItem(
            self,
            "Assign Agent",
            "Select an agent to assign to this project:",
            self._get_agent_names(),
            0,
            False,
        )
        if ok and agent_name:
            agent = self._agent_repo.get_agent_by_name(agent_name)
            if agent:
                self.assign_agent_requested.emit(proj.id, agent_name)
                self._show_status(f"Agent '{agent_name}' assigned to project")

    def _on_run_agent(self) -> None:
        if self._selected_project is None:
            return
        proj = self._selected_project
        goal, ok = QInputDialog.getText(
            self,
            "Run Agent",
            "Enter the goal for the agent:",
            text=f"Work on {proj.name}",
        )
        if ok and goal:
            self.run_agent_requested.emit(proj.id, goal)

    def _on_refresh(self) -> None:
        self.refresh()
        self._show_status("Refreshed")

    def _get_agent_names(self) -> list[str]:
        if self._agent_repo is None:
            return []
        try:
            agents = self._agent_repo.list_agents(include_disabled=False)
            return [a.name for a in agents if a.enabled]
        except Exception:
            return []

    def _show_status(self, message: str) -> None:
        status_bar = None
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "statusBar"):
                status_bar = parent.statusBar()
                break
            parent = parent.parent()
        if status_bar is not None:
            status_bar.showMessage(message, 3000)

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "Error", message)

    def _card_style(self, selected: bool = False) -> str:
        if selected:
            return (
                f"background: {_GRAPHITE_DARK_CARD};"
                f" border: 1px solid {_EMERGENCY_HOVER}; border-radius: 8px; padding: 12px 14px;"
            )
        return (
            f"background: {_GRAPHITE_CARD};"
            f" border: 1px solid {_GRAPHITE_BORDER};"
            f" border-radius: 8px; padding: 12px 14px;"
        )

    def _button_style(self, highlight: bool = False) -> str:
        if highlight:
            bg = _EMERGENCY_HOVER
        else:
            bg = _GRAPHITE_BORDER
        return (
            f"background: {bg}; color: {_TEXT_PRIMARY};"
            f" border: none; border-radius: 4px; font-size: 11px; font-weight: 600;"
            f" padding: 4px 8px;"
        )

    def _scroll_style(self) -> str:
        return (
            f"QScrollArea {{ border: none; background: transparent; }}"
            f"QScrollBar:vertical {{ background: {_GRAPHITE_DARK_CARD};"
            f" border: none; width: 8px; margin: 0px; }}"
            f"QScrollBar::handle:vertical {{ background: {_GRAPHITE_BORDER};"
            f" border-radius: 4px; }}"
        )

    def _folder_pixmap(self) -> QPixmap:
        return QPixmap()


class CreateProjectDialog(QDialog):
    """Dialog for creating a new project."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create Project")
        self.setFixedSize(480, 220)
        self.result_data: dict[str, str] | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("Project name")
        self._name_input.setStyleSheet(self._input_style())
        self._name_input.setFixedHeight(26)

        self._desc_input = QTextEdit()
        self._desc_input.setPlaceholderText("Project description (optional)")
        self._desc_input.setStyleSheet(self._input_style())
        self._desc_input.setFixedHeight(56)

        path_layout = QHBoxLayout()
        path_layout.setSpacing(8)
        self._path_input = QLineEdit()
        self._path_input.setPlaceholderText("Workspace folder path")
        self._path_input.setStyleSheet(self._input_style())
        self._path_input.setFixedHeight(26)
        path_layout.addWidget(self._path_input, stretch=1)

        self._path_btn = QPushButton("Browse")
        self._path_btn.setStyleSheet(self._button_style())
        self._path_btn.setFixedSize(70, 26)
        self._path_btn.clicked.connect(self._on_browse)
        path_layout.addWidget(self._path_btn)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.setSpacing(10)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setStyleSheet(self._button_style())
        self._btn_cancel.setFixedSize(80, 26)
        self._btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_cancel)

        self._btn_create = QPushButton("Create")
        self._btn_create.setStyleSheet(self._button_style(highlight=True))
        self._btn_create.setFixedSize(80, 26)
        self._btn_create.clicked.connect(self._on_create)
        btn_layout.addWidget(self._btn_create)

        layout.addStretch()
        form_layout = QVBoxLayout()
        form_layout.setSpacing(0)
        form_layout.addWidget(QLabel("Name"))
        form_layout.addWidget(self._name_input)
        form_layout.addSpacing(8)
        form_layout.addWidget(QLabel("Description"))
        form_layout.addWidget(self._desc_input)
        form_layout.addSpacing(8)
        form_layout.addWidget(QLabel("Workspace Path"))
        form_layout.addLayout(path_layout)
        layout.addLayout(form_layout)
        layout.addStretch()
        layout.addLayout(btn_layout)

    def _on_browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select Workspace Folder")
        if directory:
            self._path_input.setText(directory)

    def _on_create(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Project name is required.")
            return
        path = self._path_input.text().strip()
        if path:
            from pathlib import Path
            p = Path(path)
            if not p.exists():
                QMessageBox.warning(self, "Validation Error", f"Path does not exist: {path}")
                return
            if not p.is_dir():
                QMessageBox.warning(self, "Validation Error", f"Path is not a directory: {path}")
                return
        self.result_data = {
            "name": name,
            "description": self._desc_input.toPlainText().strip(),
            "workspace_path": path,
        }
        self.accept()

    def _input_style(self) -> str:
        return (
            f"background: {_GRAPHITE}; color: {_TEXT_PRIMARY};"
            f" border: 1px solid {_GRAPHITE_BORDER}; border-radius: 4px;"
            f" padding: 4px 6px; font-size: 11px;"
        )

    def _button_style(self, highlight: bool = False) -> str:
        bg = _EMERGENCY_HOVER if highlight else _GRAPHITE_BORDER
        return (
            f"background: {bg}; color: {_TEXT_PRIMARY};"
            f" border: none; border-radius: 4px; font-size: 11px; font-weight: 600;"
            f" padding: 4px 8px;"
        )


class EditProjectDialog(QDialog):
    """Dialog for editing project metadata."""

    def __init__(self, parent: QWidget | None = None, project: Any = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Project")
        self.setFixedSize(480, 250)
        self.result_data: dict[str, str] | None = None
        self._project = project
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(20, 20, 20, 20)

        self._name_input = QLineEdit(self._project.name if self._project else "")
        self._name_input.setPlaceholderText("Project name")
        self._name_input.setStyleSheet(self._input_style())
        self._name_input.setFixedHeight(26)

        self._desc_input = QTextEdit()
        self._desc_input.setPlainText(self._project.description if self._project else "")
        self._desc_input.setPlaceholderText("Project description (optional)")
        self._desc_input.setStyleSheet(self._input_style())
        self._desc_input.setFixedHeight(56)

        path_layout = QHBoxLayout()
        path_layout.setSpacing(8)
        self._path_input = QLineEdit(self._project.workspace_path or "" if self._project else "")
        self._path_input.setPlaceholderText("Workspace folder path (optional)")
        self._path_input.setStyleSheet(self._input_style())
        self._path_input.setFixedHeight(26)
        path_layout.addWidget(self._path_input, stretch=1)

        self._path_btn = QPushButton("Browse")
        self._path_btn.setStyleSheet(self._button_style())
        self._path_btn.setFixedSize(70, 26)
        self._path_btn.clicked.connect(self._on_browse)
        path_layout.addWidget(self._path_btn)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.setSpacing(10)
        self._btn_cancel = QPushButton("Cancel")
        self._btn_cancel.setStyleSheet(self._button_style())
        self._btn_cancel.setFixedSize(80, 26)
        self._btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self._btn_cancel)

        self._btn_save = QPushButton("Save")
        self._btn_save.setStyleSheet(self._button_style(highlight=True))
        self._btn_save.setFixedSize(80, 26)
        self._btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(self._btn_save)

        form_layout = QVBoxLayout()
        form_layout.setSpacing(0)
        form_layout.addWidget(QLabel("Name"))
        form_layout.addWidget(self._name_input)
        form_layout.addSpacing(8)
        form_layout.addWidget(QLabel("Description"))
        form_layout.addWidget(self._desc_input)
        form_layout.addSpacing(8)
        form_layout.addWidget(QLabel("Workspace Path"))
        form_layout.addLayout(path_layout)
        layout.addLayout(form_layout)
        layout.addStretch()
        layout.addLayout(btn_layout)

    def _on_browse(self) -> None:
        directory = QFileDialog.getExistingDirectory(
            self, "Select Workspace Folder", self._path_input.text()
        )
        if directory:
            self._path_input.setText(directory)

    def _on_save(self) -> None:
        name = self._name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation Error", "Project name is required.")
            return
        path = self._path_input.text().strip()
        if path:
            from pathlib import Path
            p = Path(path)
            if not p.exists():
                QMessageBox.warning(self, "Validation Error", f"Path does not exist: {path}")
                return
            if not p.is_dir():
                QMessageBox.warning(self, "Validation Error", f"Path is not a directory: {path}")
                return
        self.result_data = {
            "name": name,
            "description": self._desc_input.toPlainText().strip(),
            "workspace_path": path,
        }
        self.accept()

    def _input_style(self) -> str:
        return (
            f"background: {_GRAPHITE}; color: {_TEXT_PRIMARY};"
            f" border: 1px solid {_GRAPHITE_BORDER}; border-radius: 4px;"
            f" padding: 4px 6px; font-size: 11px;"
        )

    def _button_style(self, highlight: bool = False) -> str:
        bg = _EMERGENCY_HOVER if highlight else _GRAPHITE_BORDER
        return (
            f"background: {bg}; color: {_TEXT_PRIMARY};"
            f" border: none; border-radius: 4px; font-size: 11px; font-weight: 600;"
            f" padding: 4px 8px;"
        )

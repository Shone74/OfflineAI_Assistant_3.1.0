"""Project and Workspace management for Phase 13.4.

This package provides project and workspace management with profile overrides.

Usage:
    from project import ProjectManager, WorkspaceManager, ProfileStack

    # Create managers
    ws_manager = WorkspaceManager(db=database_manager, event_bus=event_bus)
    proj_manager = ProjectManager(db=database_manager, event_bus=event_bus)

    # Create a workspace
    workspace = ws_manager.create_workspace("My Workspace")

    # Create a project within the workspace
    project = proj_manager.create_project(
        "My Project",
        description="Project description",
        workspace_id=workspace.id,
        profile_override={"identity": {"name": "Project Assistant"}}
    )

    # Resolve effective profile
    from project.profile_stack import ProfileStack
    stack = ProfileStack(global_profile=assistant.get_assistant_profile())
    stack.set_workspace(workspace.id, workspace.profile_override)
    stack.set_project(project.id, project.profile_override)
    effective_profile = stack.get_effective_profile()
"""

from project.manager import ProjectManager, WorkspaceManager
from project.models import Project, Workspace
from project.profile_stack import ProfileStack, resolve_effective_profile

__all__ = [
    "ProfileStack",
    "Project",
    "ProjectManager",
    "Workspace",
    "WorkspaceManager",
    "resolve_effective_profile",
]
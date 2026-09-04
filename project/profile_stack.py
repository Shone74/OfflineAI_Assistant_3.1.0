"""Profile stacking mechanism for FAZA 13.4.

This module provides the ProfileStack class that resolves an effective
assistant profile from multiple override layers:

    Global Profile
    ↓ (workspace override)
    Workspace Profile Override
    ↓ (project override)
    Project Profile Override
    ↓ (final result)
    Effective Profile

The stacking only includes explicitly provided override values.

Profile Stack Resolution:
    1. Global profile is always the base
    2. Workspace override (if any) merges into global
    3. Project override (if any) merges on top of workspace
    4. Result is the effective profile for current context

Deep Merge Behavior:
    - Only explicit keys in override dicts are replaced
    - Nested dictionaries merge recursively
    - Previous values are never deleted, only added/overridden

Security Note:
    Profile overrides affect personality, communication style, and system
    prompt content. They do NOT affect Security Layer policies, tool
    permissions, or authorization rules.
"""

from __future__ import annotations

import copy


def _deep_merge(base: dict, override: dict | None) -> dict:
    """Deep merge override into base, returning a new dict.

    Only keys present in override are modified.
    Nested dictionaries are merged recursively.
    If override is None, returns copy of base unchanged.

    Args:
        base: The base dictionary to merge into.
        override: The override dictionary with values to apply (None = no change).

    Returns:
        New dict with merged values. Neither input is modified.
    """
    if override is None:
        return copy.deepcopy(base)
    result = {}
    for key, value in base.items():
        if isinstance(value, dict):
            result[key] = copy.deepcopy(value)
        else:
            result[key] = value
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def resolve_effective_profile(
    global_profile: dict,
    workspace_override: dict | None = None,
    project_override: dict | None = None,
) -> dict:
    """Resolve the effective profile from layered overrides.

    Args:
        global_profile: The base assistant profile (always required)
        workspace_override: Optional profile overrides from workspace
        project_override: Optional profile overrides from project

    Returns:
        A new profile dict with overrides applied in order.

    Security Note:
        This function only merges profile data. Security Layer,
        permission policies, and tool authorization are NOT affected
        by profile overrides.
    """
    if workspace_override is None and project_override is None:
        return copy.deepcopy(global_profile)

    if project_override is None:
        result = copy.deepcopy(global_profile)
        result = _deep_merge(result, workspace_override)
        return result

    result = copy.deepcopy(global_profile)
    result = _deep_merge(result, workspace_override)
    result = _deep_merge(result, project_override)
    return result


class ProfileStack:
    """Manages profile resolution with multiple override layers.

    Usage:
        stack = ProfileStack(global_profile)
        stack.set_workspace_context(workspace_id, workspace_override)
        stack.set_project_context(project_id, project_override)
        effective = stack.get_effective_profile()

    Profile Layering Order (later layers override earlier):
        1. Global profile (always present as base)
        2. Workspace profile override (optional)
        3. Project profile override (optional)

    Example Override:
        global = {"identity": {"name": "Alex"}, "personality": {"humor": 0.5}}
        workspace_override = {"identity": {"name": "Alex-W1"}}
        # Result: {"identity": {"name": "Alex-W1"}, "personality": {"humor": 0.5}}
    """

    def __init__(self, global_profile: dict) -> None:
        """Initialize profile stack with global profile.

        Args:
            global_profile: The base assistant profile.
        """
        self._global = global_profile
        self._workspace_id: str | None = None
        self._workspace_override: dict | None = None
        self._project_id: str | None = None
        self._project_override: dict | None = None

    def set_workspace(
        self, workspace_id: str, workspace_override: dict | None = None
    ) -> None:
        """Set the active workspace and its profile override."""
        self._workspace_id = workspace_id
        self._workspace_override = workspace_override

    def set_project(self, project_id: str, project_override: dict | None = None) -> None:
        """Set the active project and its profile override."""
        self._project_id = project_id
        self._project_override = project_override

    def clear_workspace(self) -> None:
        """Clear the active workspace context."""
        self._workspace_id = None
        self._workspace_override = None

    def clear_project(self) -> None:
        """Clear the active project context."""
        self._project_id = None
        self._project_override = None

    def update_global(self, new_global: dict) -> None:
        """Update the global profile while preserving workspace/project overrides."""
        self._global = new_global

    @property
    def workspace_id(self) -> str | None:
        return self._workspace_id

    @property
    def project_id(self) -> str | None:
        return self._project_id

    def get_effective_profile(self) -> dict:
        """Get the resolved profile for the current context."""
        return resolve_effective_profile(
            self._global,
            self._workspace_override,
            self._project_override,
        )
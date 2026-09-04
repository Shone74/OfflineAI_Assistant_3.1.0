"""Permission manager — evaluates tool-action permissions.

The manager owns a :class:`PermissionProfile` and answers the single
question: *given a tool category, what policy applies?*  It also tracks
recently-approved / denied actions so repeated prompts can be skipped when the
profile is set to ``ASK``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from core.logger import get_logger
from security.models import PermissionProfile, Policy, ToolCategory, default_profile

if TYPE_CHECKING:  # avoid circular import at runtime
    from tools.base import Tool

logger = get_logger("security.permission_manager")


class PermissionManager:
    """Evaluates whether an action is allowed / asked / denied."""

    def __init__(self, profile: PermissionProfile | None = None) -> None:
        self._profile = profile or default_profile()
        self._granted: set[str] = set()
        self._denied: set[str] = set()

    @property
    def profile(self) -> PermissionProfile:
        return self._profile

    def set_policy(self, category: ToolCategory, policy: Policy) -> None:
        self._profile.set_policy(category, policy)
        logger.info("Policy updated: %s → %s", category.value, policy.name)

    def category_for(self, tool: Tool) -> ToolCategory:
        attr = getattr(tool, "category", None)
        if isinstance(attr, ToolCategory):
            return attr
        return ToolCategory.GENERAL

    def decide(self, category: ToolCategory) -> Policy:
        return self._profile.policy_for(category)

    def is_allowed(self, tool: Tool) -> bool:
        return self.decide(self.category_for(tool)) == Policy.ALLOW

    def is_denied(self, tool: Tool) -> bool:
        return self.decide(self.category_for(tool)) == Policy.DENY

    def remember_approval(self, tool_name: str, approved: bool) -> None:
        """Cache a one-off user decision for this session."""
        if approved:
            self._granted.add(tool_name)
        else:
            self._denied.add(tool_name)

    def was_approved(self, tool_name: str) -> bool:
        return tool_name in self._granted

    def was_denied(self, tool_name: str) -> bool:
        return tool_name in self._denied

    def reset_cache(self) -> None:
        self._granted.clear()
        self._denied.clear()

    def to_dict(self) -> dict[str, object]:
        return self._profile.to_dict()

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> PermissionManager:
        return cls(profile=PermissionProfile.from_dict(data))

    def now(self) -> datetime:
        return datetime.now(tz=UTC)

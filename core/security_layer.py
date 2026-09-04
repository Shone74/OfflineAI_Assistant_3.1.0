"""Security Layer — intercepts risky tool actions before execution.

The layer installs itself as the confirmation callback of the
:class:`ToolRegistry`, so every tool whose ``risk_level`` requires approval
must pass through :meth:`PermissionManager.decide` and (for ``ASK`` policies)
a user-facing approval dialog.

Flow:

    AI / Assistant → ToolRegistry.execute
                         ↓ (risk ≥ WRITE)
                    SecurityLayer._on_confirm
                         ├── Policy.DENY  → blocked, audited
                         ├── Policy.ALLOW → allowed, audited
                         └── Policy.ASK   → UI approval dialog → audited

Read-only tools (``risk_level == INFO``) bypass the callback entirely and are
audited via the ``TOOL_EXECUTED`` event.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from core.event_bus import EventBus
from core.logger import get_logger
from security.auditor import AuditDecision, AuditEntry, SecurityAuditor
from security.models import (
    PermissionProfile,
    Policy,
    ToolCategory,
    default_profile,
)
from security.permission_manager import PermissionManager

if TYPE_CHECKING:  # avoid circular imports at runtime
    from tools.base import ToolRegistry
    ApprovalCallback = Callable[[str, str], bool]

logger = get_logger("security.layer")


def _restrictive_profile() -> PermissionProfile:
    """A profile stricter than default — application launches and file
    writes require explicit confirmation (DENY for file writes)."""
    from security.models import PermissionRule

    return PermissionProfile(
        name="restrictive",
        rules=[
            PermissionRule(ToolCategory.SYSTEM, Policy.ALLOW),
            PermissionRule(ToolCategory.APPLICATION, Policy.ASK),
            PermissionRule(ToolCategory.FILE, Policy.DENY),
            PermissionRule(ToolCategory.MEMORY, Policy.DENY),
            PermissionRule(ToolCategory.CONFIG, Policy.DENY),
            PermissionRule(ToolCategory.GENERAL, Policy.ASK),
            PermissionRule(ToolCategory.UTILITY, Policy.ASK),
        ],
    )


def _permissive_profile() -> PermissionProfile:
    """A profile more permissive than default — file writes are allowed
    without prompting."""
    from security.models import PermissionRule

    return PermissionProfile(
        name="permissive",
        rules=[
            PermissionRule(ToolCategory.SYSTEM, Policy.ALLOW),
            PermissionRule(ToolCategory.APPLICATION, Policy.ALLOW),
            PermissionRule(ToolCategory.FILE, Policy.ALLOW),
            PermissionRule(ToolCategory.MEMORY, Policy.DENY),
            PermissionRule(ToolCategory.CONFIG, Policy.DENY),
            PermissionRule(ToolCategory.GENERAL, Policy.ASK),
            PermissionRule(ToolCategory.UTILITY, Policy.ALLOW),
        ],
    )


class SecurityLayer:
    """Central authorisation point between AI and the tool registry."""

    def __init__(
        self,
        registry: ToolRegistry,
        pm: PermissionManager,
        auditor: SecurityAuditor,
        event_bus: EventBus | None = None,
    ) -> None:
        self._registry = registry
        self._pm = pm
        self._auditor = auditor
        self._event_bus = event_bus
        self._approval_callback: ApprovalCallback | None = None
        self._named_profiles: dict[str, PermissionProfile] = {
            "default": default_profile(),
            "restrictive": _restrictive_profile(),
            "permissive": _permissive_profile(),
        }

        # Intercept all risky (>= WRITE) tool executions.
        registry.set_confirmation_callback(self._on_confirm)

        if event_bus is not None:
            event_bus.subscribe("TOOL_EXECUTED", self._on_tool_executed)

    def set_approval_callback(self, callback: ApprovalCallback) -> None:
        """The GUI provides this to actually prompt the user."""
        self._approval_callback = callback

    def _resolve_profile(self, profile_name: str | None) -> PermissionProfile:
        """Return the PermissionProfile for *profile_name*.

        Falls back to the global PermissionManager's profile when the name is
        ``None`` / ``"default"`` or unknown, preserving existing global
        security defaults.
        """
        if profile_name is not None and profile_name in self._named_profiles:
            return self._named_profiles[profile_name]
        return self._pm.profile

    def _on_confirm(self, tool_name: str, tool_desc: str, permission_profile: str | None = None) -> bool:
        tool = self._registry.get(tool_name)
        if tool is None:
            self._auditor.log(
                AuditEntry(tool_name, ToolCategory.GENERAL, Policy.DENY, AuditDecision.BLOCKED, "unknown tool")
            )
            return False

        category = self._pm.category_for(tool)
        profile = self._resolve_profile(permission_profile)
        policy = profile.policy_for(category)

        if policy == Policy.DENY:
            self._auditor.log(
                AuditEntry(tool_name, category, policy, AuditDecision.BLOCKED, "policy=DENY")
            )
            return False

        if policy == Policy.ALLOW:
            self._auditor.log(
                AuditEntry(tool_name, category, policy, AuditDecision.ALLOWED)
            )
            return True

        # Policy.ASK
        # Check session cache first — don't re-prompt if already decided.
        if self._pm.was_approved(tool_name):
            self._auditor.log(
                AuditEntry(
                    tool_name, category, policy,
                    AuditDecision.APPROVED, reason="cached approval",
                )
            )
            return True
        if self._pm.was_denied(tool_name):
            self._auditor.log(
                AuditEntry(
                    tool_name, category, policy,
                    AuditDecision.DENIED, reason="cached denial",
                )
            )
            return False

        self._auditor.log(
            AuditEntry(tool_name, category, policy, AuditDecision.ASKED)
        )
        approved = (
            self._approval_callback(tool_name, tool_desc)
            if self._approval_callback is not None
            else False
        )
        self._pm.remember_approval(tool_name, approved)
        self._auditor.log(
            AuditEntry(
                tool_name, category, policy,
                AuditDecision.APPROVED if approved else AuditDecision.DENIED,
                approved=approved,
            )
        )
        return approved

    def _on_tool_executed(self, event_type: str, data: dict[str, Any]) -> None:
        """Audit read-only (``INFO``) executions that bypass confirmation."""
        tool_name = data.get("tool", "")
        tool = self._registry.get(tool_name)
        if tool is None:
            return
        risk = getattr(tool, "risk_level", None)
        if risk is None:
            return
        # Only audit risk==INFO here — risky actions are logged in _on_confirm.
        from tools.base import RiskLevel

        if risk == RiskLevel.INFO:
            category = self._pm.category_for(tool)
            self._auditor.log(
                AuditEntry(
                    tool_name, category, self._pm.decide(category),
                    AuditDecision.ALLOWED, reason="read-only",
                )
            )

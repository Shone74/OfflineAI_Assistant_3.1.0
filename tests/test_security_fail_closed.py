"""Regression tests locking down the verified fail-closed security contract.

A focused security investigation (runtime probes through the real classes)
established that the authorisation path is fail-closed everywhere:

* unknown tool                 → denied (``NotRegistered`` / audited BLOCKED)
* ASK without approval callback→ denied (``UserDenied``)
* approval callback raising    → exception propagates, NEVER becomes ALLOW
* malformed permission profile  → raises (ValueError/KeyError), never ALLOW
* unknown agent profile name    → falls back to the GLOBAL default profile
* WRITE/DESTRUCTIVE risk        → cannot execute without confirmation
* session approval cache       → decisions reused per tool per session
* default policies             → SYSTEM=ALLOW, APPLICATION/FILE=ASK,
                                 MEMORY/CONFIG=DENY, GENERAL/UTILITY=ASK
* unknown category             → safe fallback (GENERAL → ASK)

These tests exist so that a future fail-open regression cannot be introduced
unnoticed.  They exercise the REAL ``SecurityLayer`` / ``PermissionManager`` /
``ToolRegistry`` / ``SecurityAuditor`` classes with small deterministic fake
tools — the security logic itself is never mocked away.  No production code
is modified; these tests document and enforce the CURRENT contract.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.security_layer import SecurityLayer
from security.auditor import AuditDecision, SecurityAuditor
from security.models import PermissionProfile, Policy, ToolCategory, default_profile
from security.permission_manager import PermissionManager
from tools.base import RiskLevel, Tool, ToolRegistry, ToolResult


# --------------------------------------------------------------------------- #
# Deterministic fake tools with execution counters
# --------------------------------------------------------------------------- #
class CountingTool(Tool):
    """Fake tool recording whether it actually ran."""

    name = "counter"
    description = "counting test tool"

    def __init__(
        self,
        name: str = "counter",
        category: ToolCategory = ToolCategory.FILE,
        risk: RiskLevel = RiskLevel.WRITE,
    ) -> None:
        self.name = name
        self.category = category
        self.risk_level = risk
        self.executions = 0

    def execute(self, **params) -> ToolResult:
        self.executions += 1
        return ToolResult(True, "executed", tool_name=self.name)


@dataclass
class SecurityStack:
    """Fresh, fully isolated security stack per test."""

    registry: ToolRegistry
    pm: PermissionManager
    auditor: SecurityAuditor
    layer: SecurityLayer
    audit_path: Path

    def audit_entries(self) -> list[dict]:
        if not self.audit_path.exists():
            return []
        lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]


@pytest.fixture()
def stack(tmp_path: Path) -> SecurityStack:
    registry = ToolRegistry()
    pm = PermissionManager()
    audit_path = tmp_path / "audit.jsonl"
    auditor = SecurityAuditor(log_path=audit_path)
    layer = SecurityLayer(registry=registry, pm=pm, auditor=auditor, event_bus=None)
    return SecurityStack(registry, pm, auditor, layer, audit_path)


@pytest.fixture()
def write_tool(stack: SecurityStack) -> CountingTool:
    tool = CountingTool(category=ToolCategory.FILE, risk=RiskLevel.WRITE)
    stack.registry.register(tool)
    return tool


# --------------------------------------------------------------------------- #
# 1. UNKNOWN TOOL
# --------------------------------------------------------------------------- #
class TestUnknownTool:
    def test_execute_unregistered_tool_fails_with_not_registered(
        self, stack: SecurityStack, write_tool: CountingTool
    ) -> None:
        result = stack.registry.execute("does_not_exist", {})

        assert result.success is False
        assert result.error == "NotRegistered"
        assert "not registered" in result.message
        # Nothing executed — the registered (different) tool stayed untouched.
        assert write_tool.executions == 0

    def test_security_layer_blocks_unknown_tool_and_audits(
        self, stack: SecurityStack
    ) -> None:
        # The registry short-circuits unknown names before confirmation; the
        # SecurityLayer's own unknown-tool branch is a defensive second gate.
        # Verify its contract directly: denied + audited BLOCKED.
        allowed = stack.layer._on_confirm("ghost_tool", "some description")

        assert allowed is False
        entries = stack.audit_entries()
        blocked = [e for e in entries if e["tool"] == "ghost_tool"]
        assert len(blocked) == 1
        assert blocked[0]["decision"] == AuditDecision.BLOCKED.value
        assert blocked[0]["reason"] == "unknown tool"


# --------------------------------------------------------------------------- #
# 2. ASK WITHOUT APPROVAL CALLBACK
# --------------------------------------------------------------------------- #
class TestAskWithoutApprovalCallback:
    def test_ask_policy_without_callback_is_denied_not_allowed(
        self, stack: SecurityStack, write_tool: CountingTool
    ) -> None:
        # FILE defaults to ASK; no approval callback is set on the layer.
        assert stack.layer._approval_callback is None

        result = stack.registry.execute("counter", {})

        assert result.success is False
        assert result.error == "UserDenied"
        assert write_tool.executions == 0  # never executed
        # Audit trail: asked, then denied (callback absent → treated as deny).
        decisions = [e["decision"] for e in stack.audit_entries()]
        assert AuditDecision.ASKED.value in decisions
        assert AuditDecision.DENIED.value in decisions

    def test_destructive_risk_also_denied_without_callback(
        self, stack: SecurityStack
    ) -> None:
        tool = CountingTool(
            name="destroyer",
            category=ToolCategory.FILE,
            risk=RiskLevel.DESTRUCTIVE,
        )
        stack.registry.register(tool)

        result = stack.registry.execute("destroyer", {})

        assert result.success is False
        assert result.error == "UserDenied"
        assert tool.executions == 0


# --------------------------------------------------------------------------- #
# 3. APPROVAL CALLBACK EXCEPTION
# --------------------------------------------------------------------------- #
class TestApprovalCallbackException:
    def test_callback_exception_propagates_and_never_becomes_allow(
        self, stack: SecurityStack, write_tool: CountingTool
    ) -> None:
        def exploding_callback(tool_name: str, tool_desc: str) -> bool:
            raise RuntimeError("GUI crashed while asking")

        stack.layer.set_approval_callback(exploding_callback)

        # Current production contract: the exception PROPAGATES to the caller
        # (workers catch it and record a failed result).  It must never be
        # swallowed into an approval.
        with pytest.raises(RuntimeError, match="GUI crashed while asking"):
            stack.registry.execute("counter", {})

        # The tool was never executed despite the exception path.
        assert write_tool.executions == 0


# --------------------------------------------------------------------------- #
# 4. INVALID PERMISSION PROFILE
# --------------------------------------------------------------------------- #
class TestInvalidPermissionProfile:
    def test_unknown_category_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            PermissionProfile.from_dict(
                {"rules": [{"category": "bogus-cat", "policy": "ALLOW"}]}
            )

    def test_unknown_policy_name_raises(self) -> None:
        with pytest.raises(KeyError):
            PermissionProfile.from_dict(
                {"rules": [{"category": "file", "policy": "TOTALLY_OPEN"}]}
            )

    def test_non_dict_rule_entries_are_skipped_safely(self) -> None:
        profile = PermissionProfile.from_dict({"rules": ["junk", 42, None]})
        assert profile.rules == []

    def test_empty_profile_falls_back_to_safe_defaults_not_allow(self) -> None:
        # A profile with NO rules must fall back to the safe-by-default
        # policies — risky categories must NOT silently become ALLOW.
        profile = PermissionProfile(name="empty", rules=[])
        assert profile.policy_for(ToolCategory.FILE) == Policy.ASK
        assert profile.policy_for(ToolCategory.APPLICATION) == Policy.ASK
        assert profile.policy_for(ToolCategory.MEMORY) == Policy.DENY
        assert profile.policy_for(ToolCategory.CONFIG) == Policy.DENY


# --------------------------------------------------------------------------- #
# 5. UNKNOWN AGENT PROFILE
# --------------------------------------------------------------------------- #
class TestUnknownAgentProfile:
    def test_unknown_profile_name_resolves_to_global_default(
        self, stack: SecurityStack
    ) -> None:
        resolved = stack.layer._resolve_profile("no-such-profile")
        assert resolved is stack.pm.profile  # global default, not permissive

    def test_known_named_profiles_resolve_to_their_own_object(
        self, stack: SecurityStack
    ) -> None:
        assert stack.layer._resolve_profile("restrictive") is (
            stack.layer._named_profiles["restrictive"]
        )
        assert stack.layer._resolve_profile(None) is stack.pm.profile

    def test_unknown_profile_does_not_become_permissive(
        self, stack: SecurityStack, write_tool: CountingTool
    ) -> None:
        # Even if an agent references a bogus profile name, the built-in
        # "permissive" profile (FILE=ALLOW) must NOT be picked up: with no
        # approval callback the WRITE tool is still denied via ASK.
        result = stack.registry.execute(
            "counter", {}, permission_profile="no-such-profile"
        )
        assert result.success is False
        assert result.error == "UserDenied"
        assert write_tool.executions == 0


# --------------------------------------------------------------------------- #
# 6. WRITE / DESTRUCTIVE TOOLS REQUIRE CONFIRMATION
# --------------------------------------------------------------------------- #
class TestConfirmationRequired:
    def test_denied_confirmation_blocks_execution(
        self, stack: SecurityStack, write_tool: CountingTool
    ) -> None:
        stack.layer.set_approval_callback(lambda name, desc: False)

        result = stack.registry.execute("counter", {})

        assert result.success is False
        assert result.error == "UserDenied"
        assert write_tool.executions == 0

    def test_approved_confirmation_allows_execution(
        self, stack: SecurityStack, write_tool: CountingTool
    ) -> None:
        stack.layer.set_approval_callback(lambda name, desc: True)

        result = stack.registry.execute("counter", {})

        assert result.success is True
        assert write_tool.executions == 1

    def test_read_only_info_tool_executes_without_confirmation(
        self, stack: SecurityStack
    ) -> None:
        # Documented contract: risk INFO (read-only) bypasses the confirmation
        # gate entirely — no approval callback is set and the tool still runs.
        tool = CountingTool(
            name="info_tool",
            category=ToolCategory.SYSTEM,
            risk=RiskLevel.INFO,
        )
        stack.registry.register(tool)

        result = stack.registry.execute("info_tool", {})

        assert result.success is True
        assert tool.executions == 1


# --------------------------------------------------------------------------- #
# 7. SESSION APPROVAL CACHE
# --------------------------------------------------------------------------- #
class TestSessionApprovalCache:
    def test_approval_is_cached_for_the_session(
        self, stack: SecurityStack, write_tool: CountingTool
    ) -> None:
        prompts: list[str] = []

        def approve_once(tool_name: str, desc: str) -> bool:
            prompts.append(tool_name)
            return True

        stack.layer.set_approval_callback(approve_once)

        first = stack.registry.execute("counter", {})
        second = stack.registry.execute("counter", {})

        # Current contract: one user decision is reused for the session —
        # the tool runs twice, the user is asked only once.
        assert first.success and second.success
        assert write_tool.executions == 2
        assert prompts == ["counter"]

    def test_denial_is_cached_for_the_session(
        self, stack: SecurityStack, write_tool: CountingTool
    ) -> None:
        prompts: list[str] = []

        def deny_once(tool_name: str, desc: str) -> bool:
            prompts.append(tool_name)
            return False

        stack.layer.set_approval_callback(deny_once)

        first = stack.registry.execute("counter", {})
        second = stack.registry.execute("counter", {})

        assert first.success is False and second.success is False
        assert write_tool.executions == 0
        assert prompts == ["counter"]  # asked once, denial reused

    def test_cache_is_scoped_to_tool_name(
        self, stack: SecurityStack
    ) -> None:
        tool_a = CountingTool(name="tool_a", category=ToolCategory.FILE)
        tool_b = CountingTool(name="tool_b", category=ToolCategory.FILE)
        stack.registry.register(tool_a)
        stack.registry.register(tool_b)
        stack.layer.set_approval_callback(lambda name, desc: True)

        stack.registry.execute("tool_a", {})
        stack.registry.execute("tool_b", {})

        # Each tool has its own cached decision.
        assert tool_a.executions == 1
        assert tool_b.executions == 1


# --------------------------------------------------------------------------- #
# 8. DEFAULT POLICIES
# --------------------------------------------------------------------------- #
class TestDefaultPolicies:
    def test_documented_category_defaults(self) -> None:
        # The documented default policy map — the security posture every
        # fresh profile and unknown rule falls back to.
        expected = {
            ToolCategory.SYSTEM: Policy.ALLOW,
            ToolCategory.APPLICATION: Policy.ASK,
            ToolCategory.FILE: Policy.ASK,
            ToolCategory.MEMORY: Policy.DENY,
            ToolCategory.CONFIG: Policy.DENY,
            ToolCategory.GENERAL: Policy.ASK,
            ToolCategory.UTILITY: Policy.ASK,
        }
        profile = PermissionProfile(name="empty", rules=[])
        for category, policy in expected.items():
            assert profile.policy_for(category) == policy, category

    def test_default_profile_matches_documented_defaults(self) -> None:
        profile = default_profile()
        assert profile.name == "default"
        rules = {rule.category: rule.policy for rule in profile.rules}
        assert rules[ToolCategory.SYSTEM] == Policy.ALLOW
        assert rules[ToolCategory.APPLICATION] == Policy.ASK
        assert rules[ToolCategory.FILE] == Policy.ASK
        assert rules[ToolCategory.MEMORY] == Policy.DENY
        assert rules[ToolCategory.CONFIG] == Policy.DENY
        assert rules[ToolCategory.GENERAL] == Policy.ASK
        assert rules[ToolCategory.UTILITY] == Policy.ASK

    def test_unknown_category_value_falls_back_to_ask(self) -> None:
        # A category value that matches NO rule (and no enum member) must
        # resolve to ASK — never to ALLOW.
        profile = PermissionProfile(name="empty", rules=[])
        assert profile.policy_for("not-a-category") == Policy.ASK

    def test_tool_with_invalid_category_attribute_is_general_ask(
        self, stack: SecurityStack
    ) -> None:
        tool = CountingTool(
            name="weird_cat",
            category=ToolCategory.FILE,
            risk=RiskLevel.WRITE,
        )
        tool.category = "definitely-not-an-enum"  # simulate corrupt metadata
        stack.registry.register(tool)

        # category_for() falls back to GENERAL; GENERAL defaults to ASK →
        # without an approval callback the WRITE tool is denied.
        assert stack.pm.category_for(tool) == ToolCategory.GENERAL
        result = stack.registry.execute("weird_cat", {})
        assert result.success is False
        assert result.error == "UserDenied"
        assert tool.executions == 0

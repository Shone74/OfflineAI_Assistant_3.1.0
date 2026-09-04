"""Security models — tool categories, permission policies, and profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum


class ToolCategory(Enum):
    """Functional category of a tool.  Drives the permission policy."""

    SYSTEM = "system"
    APPLICATION = "application"
    FILE = "file"
    MEMORY = "memory"
    CONFIG = "config"
    GENERAL = "general"
    UTILITY = "utility"


class Policy(IntEnum):
    """Permission policy for a category.

    * ALLOW  — trusted, read-only category; execute without prompting.
    * ASK    — risky enough to require explicit user consent.
    * DENY   — blocked outright (e.g. configuration / memory writes).
    """

    ALLOW = 0
    ASK = 1
    DENY = 2


@dataclass(frozen=True)
class PermissionRule:
    """One policy binding for a single tool category."""

    category: ToolCategory
    policy: Policy

    def matches(self, category: ToolCategory) -> bool:
        return self.category == category


@dataclass
class PermissionProfile:
    """Ordered rules applied by the PermissionManager.

    The profile is serialisable so it can be persisted to *settings.json*
    (key ``security.permission_profile``).
    """

    name: str = "default"
    rules: list[PermissionRule] = field(default_factory=list)

    def policy_for(self, category: ToolCategory) -> Policy:
        """Return the *most specific* matching rule, or a safe default."""
        for rule in self.rules:
            if rule.matches(category):
                return rule.policy
        return _default_policy(category)

    def set_policy(self, category: ToolCategory, policy: Policy) -> None:
        """Add or replace the rule for *category*."""
        new_rule = PermissionRule(category=category, policy=policy)
        for i, rule in enumerate(self.rules):
            if rule.category == category:
                self.rules[i] = new_rule
                return
        self.rules.append(new_rule)

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "rules": [
                {"category": r.category.value, "policy": r.policy.name}
                for r in self.rules
            ],
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> PermissionProfile:
        rules_raw = data.get("rules", [])
        rules: list[PermissionRule] = []
        if isinstance(rules_raw, list):
            for raw in rules_raw:
                if not isinstance(raw, dict):
                    continue
                cat = ToolCategory(str(raw.get("category", "general")))
                policy = Policy[str(raw.get("policy", "ASK"))]
                rules.append(PermissionRule(category=cat, policy=policy))
        name = str(data.get("name", "default"))
        return cls(name=name, rules=rules)


def _default_policy(category: ToolCategory) -> Policy:
    """Safe-by-default policies per category."""
    if category in (ToolCategory.SYSTEM,):
        return Policy.ALLOW
    if category in (ToolCategory.APPLICATION, ToolCategory.FILE):
        return Policy.ASK
    if category in (ToolCategory.MEMORY, ToolCategory.CONFIG):
        return Policy.DENY
    return Policy.ASK


def default_profile() -> PermissionProfile:
    """Factory returning the built-in default permission profile."""
    return PermissionProfile(
        name="default",
        rules=[
            PermissionRule(ToolCategory.SYSTEM, Policy.ALLOW),
            PermissionRule(ToolCategory.APPLICATION, Policy.ASK),
            PermissionRule(ToolCategory.FILE, Policy.ASK),
            PermissionRule(ToolCategory.MEMORY, Policy.DENY),
            PermissionRule(ToolCategory.CONFIG, Policy.DENY),
            PermissionRule(ToolCategory.GENERAL, Policy.ASK),
            PermissionRule(ToolCategory.UTILITY, Policy.ASK),
        ],
    )

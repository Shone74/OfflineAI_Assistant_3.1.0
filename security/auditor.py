"""Security audit trail — logs every tool authorisation decision.

Writes JSON-lines to ``<user data>/data/security_audit.log`` (resolved from
:mod:`core.paths` — CWD-independent) and emits a ``SECURITY_AUDIT`` event on
the EventBus so the UI can display live audit entries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from core.logger import get_logger
from core.paths import get_data_dir
from security.models import Policy, ToolCategory

logger = get_logger("security.auditor")

AUDIT_LOG_FILENAME = "security_audit.log"


def _default_log_path() -> Path:
    """Resolve the default audit log path at runtime.

    Resolved lazily on every auditor construction rather than frozen at
    module import, so the centralized path logic (including the
    ``OFFLINE_AI_DATA_DIR`` override) is always honoured.  Never depends on
    the process CWD.
    """
    return get_data_dir() / AUDIT_LOG_FILENAME


class AuditDecision(str, Enum):
    """Outcome recorded for an authorisation attempt."""

    ALLOWED = "ALLOWED"
    BLOCKED = "BLOCKED"
    ASKED = "ASKED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ERROR = "ERROR"


@dataclass
class AuditEntry:
    tool_name: str
    category: ToolCategory
    policy: Policy
    decision: AuditDecision
    reason: str = ""
    approved: bool | None = None
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(tz=UTC).isoformat()


class SecurityAuditor:
    """Persists audit entries and broadcasts them."""

    def __init__(
        self,
        log_path: Path | None = None,
        event_bus=None,
    ) -> None:
        self._log_path = log_path or _default_log_path()
        self._event_bus = event_bus
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(self, entry: AuditEntry) -> None:
        record = {
            "timestamp": entry.timestamp,
            "tool": entry.tool_name,
            "category": entry.category.value,
            "policy": entry.policy.name,
            "decision": entry.decision.value,
            "approved": entry.approved,
            "reason": entry.reason,
        }
        line = json.dumps(record, ensure_ascii=False)
        logger.info("AUDIT: %s", line)
        try:
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError as exc:
            logger.error("Failed to write audit log: %s", exc)
        if self._event_bus is not None:
            self._event_bus.publish("SECURITY_AUDIT", data=record)

    def read_recent(self, limit: int = 50) -> list[dict]:
        if not self._log_path.exists():
            return []
        lines = self._log_path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()]

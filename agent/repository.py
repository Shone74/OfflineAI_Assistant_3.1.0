"""Agent repository — persistent CRUD for Agent entities via DatabaseManager.

All database access goes through :class:`DatabaseManager`.  Never open a
raw ``sqlite3`` connection outside this module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from core.event_bus import EventBus
from core.logger import get_logger
from database.database_manager import DatabaseManager, agent_to_values, row_to_agent
from database.models import Agent

logger = get_logger("agent_repository")

_COLUMNS: tuple[str, ...] = (
    "name", "description", "system_prompt", "model_name",
    "enabled", "tool_whitelist", "permission_profile", "profile_snapshot",
    "status", "created_at", "updated_at",
)

_AGENT_LIFECYCLE_EVENTS = (
    "AGENT_CREATED",
    "AGENT_UPDATED",
    "AGENT_DELETED",
    "AGENT_ENABLED",
    "AGENT_DISABLED",
)


class AgentRepository:
    """Thin persistence layer for :class:`Agent` entities."""

    def __init__(
        self,
        db: DatabaseManager,
        event_bus: EventBus | None = None,
    ) -> None:
        self._db = db
        self._event_bus = event_bus or EventBus.get_instance()
        logger.info("AgentRepository ready")

    def _params(self, agent: Agent) -> tuple[Any, ...]:
        """Build a params tuple in :data:`_COLUMNS` order from an Agent."""
        values = agent_to_values(agent)
        return tuple(values[col] for col in _COLUMNS)

    def _publish_agent_event(self, event_type: str, agent: Agent | None = None) -> None:
        """Publish an Agent lifecycle event.

        The payload includes the agent's serialised representation (via
        ``agent_to_values``) so subscribers always receive a consistent dict.
        For DELETE, the agent snapshot is captured before removal.
        """
        if agent is not None:
            payload: dict[str, Any] = {
                **agent_to_values(agent),
                "id": agent.id,
            }
        else:
            payload = {}
        self._event_bus.publish(event_type, data=payload)

    # ------------------------------------------------------------------ #
    # Create / read
    # ------------------------------------------------------------------ #
    def create_agent(self, agent: Agent) -> Agent:
        """Insert a new agent row. Raises ``sqlite3.IntegrityError`` on duplicate name."""
        params = self._params(agent)
        cur = self._db.execute(
            "INSERT INTO agents (name, description, system_prompt, model_name, "
            "enabled, tool_whitelist, permission_profile, profile_snapshot, "
            "status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params,
        )
        agent.id = cur.lastrowid
        logger.info("Agent created: id=%s name=%s", agent.id, agent.name)
        self._publish_agent_event("AGENT_CREATED", agent)
        return agent

    def get_agent(self, agent_id: int) -> Agent | None:
        """Return the agent with *agent_id*, or ``None`` if not found."""
        row = self._db.query_one("SELECT * FROM agents WHERE id = ?", (agent_id,))
        return row_to_agent(row) if row else None

    def get_agent_by_name(self, name: str) -> Agent | None:
        """Return the agent named *name*, or ``None`` if not found."""
        row = self._db.query_one("SELECT * FROM agents WHERE name = ?", (name,))
        return row_to_agent(row) if row else None

    def list_agents(self, include_disabled: bool = True) -> list[Agent]:
        """Return all agents, optionally filtering out disabled ones."""
        if include_disabled:
            rows = self._db.query("SELECT * FROM agents ORDER BY id ASC")
        else:
            rows = self._db.query(
                "SELECT * FROM agents WHERE enabled = 1 ORDER BY id ASC"
            )
        return [row_to_agent(row) for row in rows]

    # ------------------------------------------------------------------ #
    # Update / delete
    # ------------------------------------------------------------------ #
    def update_agent(self, agent: Agent) -> Agent | None:
        """Persist changes to an existing agent.

        Sets ``updated_at`` to the current timestamp.  Returns ``None``
        when *agent.id* is missing.
        """
        if agent.id is None:
            return None
        agent.updated_at = datetime.now(UTC).isoformat()
        params = self._params(agent)
        cur = self._db.execute(
            "UPDATE agents SET name = ?, description = ?, system_prompt = ?, "
            "model_name = ?, enabled = ?, tool_whitelist = ?, "
            "permission_profile = ?, profile_snapshot = ?, status = ?, "
            "created_at = ?, updated_at = ? WHERE id = ?",
            params + (agent.id,),
        )
        if cur.rowcount is None or cur.rowcount == 0:
            logger.info("Agent update affected zero rows: id=%s", agent.id)
            return None
        logger.info("Agent updated: id=%s", agent.id)
        self._publish_agent_event("AGENT_UPDATED", agent)
        return agent

    def delete_agent(self, agent_id: int) -> bool:
        """Delete the agent with *agent_id*. Returns ``True`` if a row was removed."""
        agent = self.get_agent(agent_id)
        cur = self._db.execute("DELETE FROM agents WHERE id = ?", (agent_id,))
        deleted = cur.rowcount is not None and cur.rowcount > 0
        if deleted:
            logger.info("Agent deleted: id=%s", agent_id)
            if agent is not None:
                self._publish_agent_event("AGENT_DELETED", agent)
        return deleted

    # ------------------------------------------------------------------ #
    # Enable / disable
    # ------------------------------------------------------------------ #
    def enable_agent(self, agent_id: int) -> Agent | None:
        """Enable an agent. Sets ``enabled = True`` and ``status = 'active'``."""
        agent = self.get_agent(agent_id)
        if agent is None:
            return None
        now = datetime.now(UTC).isoformat()
        values = agent_to_values(agent)
        values["enabled"] = 1
        values["status"] = "active"
        values["updated_at"] = now
        self._db.execute(
            "UPDATE agents SET enabled = ?, status = ?, updated_at = ? WHERE id = ?",
            (values["enabled"], values["status"], values["updated_at"], agent_id),
        )
        agent.enabled = True
        agent.status = "active"
        agent.updated_at = now
        logger.info("Agent enabled: id=%s", agent_id)
        self._publish_agent_event("AGENT_ENABLED", agent)
        return agent

    def disable_agent(self, agent_id: int) -> Agent | None:
        """Disable an agent. Sets ``enabled = False`` and ``status = 'inactive'``."""
        agent = self.get_agent(agent_id)
        if agent is None:
            return None
        now = datetime.now(UTC).isoformat()
        values = agent_to_values(agent)
        values["enabled"] = 0
        values["status"] = "inactive"
        values["updated_at"] = now
        self._db.execute(
            "UPDATE agents SET enabled = ?, status = ?, updated_at = ? WHERE id = ?",
            (values["enabled"], values["status"], values["updated_at"], agent_id),
        )
        agent.enabled = False
        agent.status = "inactive"
        agent.updated_at = now
        logger.info("Agent disabled: id=%s", agent_id)
        self._publish_agent_event("AGENT_DISABLED", agent)
        return agent

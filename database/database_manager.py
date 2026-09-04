"""SQLite Database Manager — owns the connection and runs migrations.

All modules access the database exclusively through this manager (never a
raw ``sqlite3.connect`` elsewhere), per the security / modularity rules.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from pathlib import Path
from typing import Any

from core.logger import get_logger
from core.paths import DATA_DIR
from database.models import (
    Agent,
    Conversation,
    MemoryEntry,
    Message,
)

logger = get_logger("database")

DB_PATH = DATA_DIR / "assistant.db"
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class DatabaseManager:
    """Thread-safe wrapper around a SQLite database with migrations."""

    def __init__(self, db_path: Path | None = None, migrations_dir: Path | None = None) -> None:
        self.db_path = db_path or DB_PATH
        self.migrations_dir = migrations_dir or MIGRATIONS_DIR
        self._local = threading.local()
        self._init_db()

    # ------------------------------------------------------------------ #
    @property
    def connection(self) -> sqlite3.Connection:
        """Return a thread-local connection (created lazily)."""
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            self._local.conn = conn
            logger.debug("SQLite connection opened for thread %s", threading.get_ident())
        return conn

    # ------------------------------------------------------------------ #
    def _init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._run_migrations()
        logger.info("Database initialised at %s", self.db_path)

    def _run_migrations(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            "CREATE TABLE IF NOT EXISTS migrations "
            "(version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
        )
        cursor.execute("SELECT version FROM migrations ORDER BY version")
        applied = {row[0] for row in cursor.fetchall()}
        self.connection.commit()

        pattern = re.compile(r"^migration_(\d{3})(?:_(.+))?\.sql$")
        for sql_file in sorted(self.migrations_dir.glob("*.sql")):
            match = pattern.match(sql_file.name)
            if not match:
                continue
            version = int(match.group(1))
            if version in applied:
                continue
            name = match.group(2) or f"migration_{version:03d}"
            logger.info("Applying migration %03d (%s)", version, sql_file.name)
            sql_script = sql_file.read_text(encoding="utf-8")
            cursor.executescript(sql_script)
            cursor.execute(
                "INSERT INTO migrations (version, name, applied_at) VALUES (?, ?, datetime('now'))",
                (version, name),
            )
            self.connection.commit()
            logger.info("Migration %03d applied", version)

    # ------------------------------------------------------------------ #
    def execute(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Cursor:
        cursor = self.connection.cursor()
        cursor.execute(query, params)
        self.connection.commit()
        return cursor

    def execute_many(self, query: str, params_seq: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        cursor = self.connection.cursor()
        cursor.executemany(query, params_seq)
        self.connection.commit()
        return cursor

    def query(self, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        cursor = self.connection.cursor()
        cursor.execute(query, params)
        return cursor.fetchall()

    def query_one(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        cursor = self.connection.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
            logger.info("Database connection closed")


# ---------------------------------------------------------------------- #
# Convenience query helpers
# ---------------------------------------------------------------------- #
def row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        id=row["id"], conversation_id=row["conversation_id"],
        role=row["role"], content=row["content"], timestamp=row["timestamp"],
    )


def row_to_memory(row: sqlite3.Row) -> MemoryEntry:
    return MemoryEntry(
        id=row["id"], type=row["type"], content=row["content"],
        importance=row["importance"], created_at=row["created_at"],
        last_used=row["last_used"],
    )


def row_to_conversation(row: sqlite3.Row) -> Conversation:
    from database.models import Conversation

    keys = row.keys() if hasattr(row, "keys") else []
    profile_snapshot_raw = row["profile_snapshot"] if "profile_snapshot" in keys else None
    if profile_snapshot_raw:
        try:
            import json
            profile_snapshot = json.loads(profile_snapshot_raw)
        except (json.JSONDecodeError, TypeError):
            profile_snapshot = None
    else:
        profile_snapshot = None

    is_pinned_raw = row["is_pinned"] if "is_pinned" in keys else 0
    pinned = bool(is_pinned_raw) if is_pinned_raw not in (None, "") else False

    return Conversation(
        id=row["id"],
        title=row["title"],
        summary=row["summary"] if "summary" in keys else "",
        workspace_id=row["workspace_id"] if "workspace_id" in keys else None,
        project_id=row["project_id"] if "project_id" in keys else None,
        profile_snapshot=profile_snapshot,
        pinned=pinned,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _parse_json_field(value: str | None) -> dict:
    """Parse a JSON field from database, returning empty dict if None or invalid."""
    if value is None:
        return {}
    import json

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}


def row_to_workspace(row: sqlite3.Row):
    from project.models import Workspace

    return Workspace(
        id=row["id"],
        name=row["name"],
        settings=_parse_json_field(row["settings"]) if row["settings"] else {},
        profile_override=_parse_json_field(row["profile_override"]) if row["profile_override"] else None,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def row_to_project(row: sqlite3.Row):
    from project.models import Project

    return Project(
        id=row["id"],
        name=row["name"],
        description=row["description"] or "",
        workspace_id=row["workspace_id"] or None,
        workspace_path=row["workspace_path"] or None,
        profile_override=(
            _parse_json_field(row["profile_override"])
            if row["profile_override"]
            else None
        ),
        settings=_parse_json_field_typed(row["settings"], {}),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _parse_json_field_typed(value: str | None, default: Any) -> Any:
    """Parse a JSON field from database, returning *default* if None or invalid."""
    if value is None:
        return default
    import json

    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return default


def row_to_agent(row: sqlite3.Row) -> Agent:
    """Map an ``agents`` row to an :class:`Agent` model."""
    keys = row.keys() if hasattr(row, "keys") else []

    def _get(key: str) -> Any:
        return row[key] if key in keys else None

    return Agent(
        id=_get("id"),
        name=_get("name") or "",
        description=_get("description") or "",
        system_prompt=_get("system_prompt") or "",
        model_name=_get("model_name") or "",
        enabled=bool(_get("enabled")),
        tool_whitelist=_parse_json_field_typed(_get("tool_whitelist"), []),
        permission_profile=_get("permission_profile") or "default",
        profile_snapshot=_parse_json_field_typed(_get("profile_snapshot"), None),
        status=_get("status") or "active",
        created_at=_get("created_at") or "",
        updated_at=_get("updated_at") or "",
    )


def agent_to_values(agent: Agent) -> dict[str, Any]:
    """Map an :class:`Agent` model to database-compatible values.

    Booleans are converted to integers (SQLite storage convention) and
    JSON fields are serialised to text.
    """
    import json

    def _dump(value: Any) -> str | None:
        if value is None:
            return None
        return json.dumps(value)

    return {
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "model_name": agent.model_name,
        "enabled": 1 if agent.enabled else 0,
        "tool_whitelist": json.dumps(agent.tool_whitelist) if agent.tool_whitelist is not None else "[]",
        "permission_profile": agent.permission_profile,
        "profile_snapshot": _dump(agent.profile_snapshot),
        "status": agent.status,
        "created_at": agent.created_at,
        "updated_at": agent.updated_at,
    }

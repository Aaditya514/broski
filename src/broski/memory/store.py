"""High-level Data Access Object (DAO) and Memory Store for broski.

Provides typed, asynchronous methods for managing long-term memories,
user preferences, installed application catalogs, security audit trails,
and conversational session context.
"""

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from broski.memory.database import get_connection, init_db, resolve_db_path


class MemoryItem(BaseModel):
    """Data model representing a stored long-term memory fact."""

    key: str
    value: str
    category: str = "general"
    confidence: float = 1.0
    created_at: str | None = None
    updated_at: str | None = None


class AppItem(BaseModel):
    """Data model representing a registered desktop application."""

    name: str
    path: str
    aliases: list[str] = Field(default_factory=list)
    last_launched: str | None = None
    launch_count: int = 0


class AuditEvent(BaseModel):
    """Data model representing a security audit trail log entry."""

    id: int | None = None
    timestamp: str | None = None
    event_type: str
    actor: str
    action: str
    risk_level: str
    status: str
    details: dict[str, Any] = Field(default_factory=dict)


class SessionMessage(BaseModel):
    """Data model representing a single conversational turn in session memory."""

    id: int | None = None
    session_id: str
    role: str
    content: str
    timestamp: str | None = None


class MemoryStore:
    """Asynchronous Memory Store providing clean CRUD operations over SQLite."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self.db_path = resolve_db_path(db_path)

    async def initialize(self) -> None:
        """Ensure database tables and indexes are created."""
        await init_db(self.db_path)

    # --------------------------------------------------------------------------
    # 1. Long-Term Memories & User Privacy
    # --------------------------------------------------------------------------

    async def save_memory(
        self,
        key: str,
        value: str,
        category: str = "general",
        confidence: float = 1.0,
    ) -> MemoryItem:
        """Save or update a memory item. If key exists, updates value and category."""
        async with get_connection(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO memories (key, value, category, confidence, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    category = excluded.category,
                    confidence = excluded.confidence,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (key.strip(), value.strip(), category.strip(), confidence),
            )
            await conn.commit()
            return await self.get_memory(key)  # type: ignore[return-value]

    async def get_memory(self, key: str) -> MemoryItem | None:
        """Retrieve a specific memory by its unique key."""
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT key, value, category, confidence, created_at, updated_at
                FROM memories WHERE key = ?;
                """,
                (key.strip(),),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return MemoryItem(
                key=row["key"],
                value=row["value"],
                category=row["category"],
                confidence=row["confidence"],
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )

    async def search_memories(self, query: str, category: str | None = None) -> list[MemoryItem]:
        """Search memories matching query in key or value, optionally filtered by category."""
        search_pattern = f"%{query.strip()}%"
        async with get_connection(self.db_path) as conn:
            if category:
                cursor = await conn.execute(
                    """
                    SELECT key, value, category, confidence, created_at, updated_at
                    FROM memories
                    WHERE (key LIKE ? OR value LIKE ?) AND category = ?
                    ORDER BY updated_at DESC;
                    """,
                    (search_pattern, search_pattern, category.strip()),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT key, value, category, confidence, created_at, updated_at
                    FROM memories
                    WHERE key LIKE ? OR value LIKE ?
                    ORDER BY updated_at DESC;
                    """,
                    (search_pattern, search_pattern),
                )
            rows = await cursor.fetchall()
            return [
                MemoryItem(
                    key=row["key"],
                    value=row["value"],
                    category=row["category"],
                    confidence=row["confidence"],
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"]),
                )
                for row in rows
            ]

    async def delete_memory(self, key: str) -> bool:
        """Delete a memory by its key. Returns True if deleted, False otherwise."""
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute("DELETE FROM memories WHERE key = ?;", (key.strip(),))
            await conn.commit()
            return cursor.rowcount > 0

    async def forget_recent(self, seconds: int = 300) -> int:
        """Delete memories created or updated in the last N seconds (for privacy rollback)."""
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                DELETE FROM memories
                WHERE unixepoch('now') - unixepoch(updated_at) <= ?;
                """,
                (seconds,),
            )
            await conn.commit()
            return cursor.rowcount

    async def list_memories(
        self, category: str | None = None, limit: int = 100
    ) -> list[MemoryItem]:
        """List all memories ordered by most recently updated."""
        async with get_connection(self.db_path) as conn:
            if category:
                cursor = await conn.execute(
                    """
                    SELECT key, value, category, confidence, created_at, updated_at
                    FROM memories WHERE category = ?
                    ORDER BY updated_at DESC LIMIT ?;
                    """,
                    (category.strip(), limit),
                )
            else:
                cursor = await conn.execute(
                    """
                    SELECT key, value, category, confidence, created_at, updated_at
                    FROM memories ORDER BY updated_at DESC LIMIT ?;
                    """,
                    (limit,),
                )
            rows = await cursor.fetchall()
            return [
                MemoryItem(
                    key=row["key"],
                    value=row["value"],
                    category=row["category"],
                    confidence=row["confidence"],
                    created_at=str(row["created_at"]),
                    updated_at=str(row["updated_at"]),
                )
                for row in rows
            ]

    # --------------------------------------------------------------------------
    # 2. User Preferences
    # --------------------------------------------------------------------------

    async def set_preference(self, key: str, value: str) -> None:
        """Store or update a user preference."""
        async with get_connection(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO user_preferences (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP;
                """,
                (key.strip(), value.strip()),
            )
            await conn.commit()

    async def get_preference(self, key: str, default: str | None = None) -> str | None:
        """Retrieve a user preference by key, returning default if missing."""
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT value FROM user_preferences WHERE key = ?;", (key.strip(),)
            )
            row = await cursor.fetchone()
            if not row:
                return default
            return str(row["value"])

    async def list_preferences(self) -> dict[str, str]:
        """Retrieve all user preferences as a dictionary."""
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute("SELECT key, value FROM user_preferences ORDER BY key;")
            rows = await cursor.fetchall()
            return {row["key"]: row["value"] for row in rows}

    async def delete_preference(self, key: str) -> bool:
        """Delete a preference. Returns True if deleted."""
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "DELETE FROM user_preferences WHERE key = ?;", (key.strip(),)
            )
            await conn.commit()
            return cursor.rowcount > 0

    # --------------------------------------------------------------------------
    # 3. Installed Desktop Application Catalog
    # --------------------------------------------------------------------------

    async def register_app(self, name: str, path: str, aliases: list[str] | None = None) -> AppItem:
        """Register or update an application in the desktop catalog."""
        clean_aliases = [a.strip().lower() for a in (aliases or []) if a.strip()]
        aliases_json = json.dumps(clean_aliases)

        async with get_connection(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO installed_apps (name, path, aliases_json)
                VALUES (?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    path = excluded.path,
                    aliases_json = excluded.aliases_json;
                """,
                (name.strip(), path.strip(), aliases_json),
            )
            await conn.commit()

        return AppItem(name=name.strip(), path=path.strip(), aliases=clean_aliases)

    async def find_app(self, query: str) -> AppItem | None:
        """Look up an application by name or aliases (case-insensitive fuzzy match)."""
        normalized = query.strip().lower()
        if not normalized:
            return None

        async with get_connection(self.db_path) as conn:
            # 1. Exact match on app name
            cursor = await conn.execute(
                "SELECT name, path, aliases_json, last_launched, launch_count FROM installed_apps WHERE LOWER(name) = ?;",
                (normalized,),
            )
            row = await cursor.fetchone()

            if not row:
                # 2. Search all apps and inspect aliases / partial matches
                cursor = await conn.execute(
                    "SELECT name, path, aliases_json, last_launched, launch_count FROM installed_apps ORDER BY launch_count DESC;"
                )
                rows = await cursor.fetchall()
                for r in rows:
                    app_name_lower = r["name"].lower()
                    try:
                        app_aliases = json.loads(r["aliases_json"])
                    except (json.JSONDecodeError, TypeError):
                        app_aliases = []

                    # Exact alias match
                    if normalized in [a.lower() for a in app_aliases]:
                        row = r
                        break
                    # Partial name match
                    if normalized in app_name_lower or app_name_lower in normalized:
                        row = r
                        break

            if not row:
                return None

            try:
                aliases_list = json.loads(row["aliases_json"])
            except (json.JSONDecodeError, TypeError):
                aliases_list = []

            return AppItem(
                name=row["name"],
                path=row["path"],
                aliases=aliases_list,
                last_launched=str(row["last_launched"]) if row["last_launched"] else None,
                launch_count=row["launch_count"],
            )

    async def record_app_launch(self, name: str) -> bool:
        """Increment launch count and update timestamp for an application."""
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                UPDATE installed_apps
                SET launch_count = launch_count + 1,
                    last_launched = CURRENT_TIMESTAMP
                WHERE name = ?;
                """,
                (name.strip(),),
            )
            await conn.commit()
            return cursor.rowcount > 0

    async def list_apps(self) -> list[AppItem]:
        """List all cataloged applications ordered by launch frequency."""
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "SELECT name, path, aliases_json, last_launched, launch_count FROM installed_apps ORDER BY launch_count DESC, name ASC;"
            )
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                try:
                    aliases = json.loads(row["aliases_json"])
                except (json.JSONDecodeError, TypeError):
                    aliases = []
                result.append(
                    AppItem(
                        name=row["name"],
                        path=row["path"],
                        aliases=aliases,
                        last_launched=str(row["last_launched"]) if row["last_launched"] else None,
                        launch_count=row["launch_count"],
                    )
                )
            return result

    # --------------------------------------------------------------------------
    # 4. Security Audit Trail
    # --------------------------------------------------------------------------

    async def log_audit_event(
        self,
        event_type: str,
        actor: str,
        action: str,
        risk_level: str,
        status: str,
        details: dict[str, Any] | None = None,
    ) -> int:
        """Record an immutable event in the security audit log. Returns log ID."""
        details_str = json.dumps(details or {})
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                INSERT INTO security_audit_logs (event_type, actor, action, risk_level, status, details_json)
                VALUES (?, ?, ?, ?, ?, ?);
                """,
                (event_type, actor, action, risk_level, status, details_str),
            )
            await conn.commit()
            return cursor.lastrowid or 0

    async def get_recent_audit_logs(self, limit: int = 50) -> list[AuditEvent]:
        """Retrieve the most recent security audit log entries."""
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT id, timestamp, event_type, actor, action, risk_level, status, details_json
                FROM security_audit_logs
                ORDER BY timestamp DESC, id DESC
                LIMIT ?;
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            result = []
            for row in rows:
                try:
                    details = json.loads(row["details_json"]) if row["details_json"] else {}
                except (json.JSONDecodeError, TypeError):
                    details = {}
                result.append(
                    AuditEvent(
                        id=row["id"],
                        timestamp=str(row["timestamp"]),
                        event_type=row["event_type"],
                        actor=row["actor"],
                        action=row["action"],
                        risk_level=row["risk_level"],
                        status=row["status"],
                        details=details,
                    )
                )
            return result

    # --------------------------------------------------------------------------
    # 5. Multi-Turn Session Context
    # --------------------------------------------------------------------------

    async def append_session_message(self, session_id: str, role: str, content: str) -> None:
        """Append a conversational message to the short-term session context."""
        async with get_connection(self.db_path) as conn:
            await conn.execute(
                """
                INSERT INTO session_context (session_id, role, content)
                VALUES (?, ?, ?);
                """,
                (session_id.strip(), role.strip(), content.strip()),
            )
            await conn.commit()

    async def get_session_history(self, session_id: str, limit: int = 20) -> list[SessionMessage]:
        """Retrieve recent session history in chronological order."""
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute(
                """
                SELECT id, session_id, role, content, timestamp
                FROM session_context
                WHERE session_id = ?
                ORDER BY id DESC LIMIT ?;
                """,
                (session_id.strip(), limit),
            )
            rows = await cursor.fetchall()
            # Reverse so the caller receives messages in forward chronological order
            ordered = list(reversed(rows))
            return [
                SessionMessage(
                    id=row["id"],
                    session_id=row["session_id"],
                    role=row["role"],
                    content=row["content"],
                    timestamp=str(row["timestamp"]),
                )
                for row in ordered
            ]

    async def clear_session(self, session_id: str) -> int:
        """Clear all messages belonging to a session."""
        async with get_connection(self.db_path) as conn:
            cursor = await conn.execute(
                "DELETE FROM session_context WHERE session_id = ?;", (session_id.strip(),)
            )
            await conn.commit()
            return cursor.rowcount

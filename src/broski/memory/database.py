"""Asynchronous SQLite database engine and schema management for broski.

Handles database connection lifecycles, WAL mode optimization,
foreign keys, and automated schema migrations.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from broski.config import get_settings

SCHEMA_SQL = """
-- 1. Long-term user memory and learned facts
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    confidence REAL DEFAULT 1.0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);

-- 2. User preferences and voice-configurable settings
CREATE TABLE IF NOT EXISTS user_preferences (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Local desktop application catalog (discovered or custom apps)
CREATE TABLE IF NOT EXISTS installed_apps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    path TEXT NOT NULL,
    aliases_json TEXT NOT NULL DEFAULT '[]',
    last_launched TIMESTAMP,
    launch_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_installed_apps_name ON installed_apps(name);

-- 4. Complete security audit trail of every tool execution & user approval
CREATE TABLE IF NOT EXISTS security_audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    status TEXT NOT NULL,
    details_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON security_audit_logs(timestamp);

-- 5. Multi-turn conversational session context
CREATE TABLE IF NOT EXISTS session_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_session_context_session ON session_context(session_id, timestamp);
"""


def resolve_db_path(db_path: Path | str | None = None) -> Path:
    """Resolve database path, falling back to application settings and ensuring parent directories."""
    if db_path is None:
        settings = get_settings()
        target_path = settings.paths.db_path
    elif isinstance(db_path, str):
        target_path = Path(db_path)
    else:
        target_path = db_path

    target_path.parent.mkdir(parents=True, exist_ok=True)
    return target_path


@asynccontextmanager
async def get_connection(
    db_path: Path | str | None = None,
) -> AsyncGenerator[aiosqlite.Connection, None]:
    """Provide an asynchronous context manager for a configured SQLite connection.

    Enforces foreign keys, enables Write-Ahead Logging (WAL), and configures busy timeouts.
    """
    path = resolve_db_path(db_path)
    async with aiosqlite.connect(path) as conn:
        conn.row_factory = aiosqlite.Row
        # Performance and integrity pragmas
        await conn.execute("PRAGMA foreign_keys = ON;")
        await conn.execute("PRAGMA journal_mode = WAL;")
        await conn.execute("PRAGMA synchronous = NORMAL;")
        await conn.execute("PRAGMA busy_timeout = 5000;")
        yield conn


async def init_db(db_path: Path | str | None = None) -> None:
    """Initialize SQLite database schema and required indexes."""
    async with get_connection(db_path) as conn:
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()


async def close_db_pools() -> None:
    """Optional teardown hook for connection pool cleanup."""
    # aiosqlite connections are managed contextually; hook reserved for future connection pooling

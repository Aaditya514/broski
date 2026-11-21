"""Unit tests for broski asynchronous SQLite database engine."""

from pathlib import Path

import pytest

from broski.memory.database import get_connection, init_db, resolve_db_path


@pytest.mark.asyncio
async def test_resolve_db_path(tmp_path: Path) -> None:
    """Verify resolve_db_path creates parent directory and handles various path types."""
    target = tmp_path / "sub" / "test.db"
    resolved = resolve_db_path(target)
    assert resolved == target
    assert target.parent.is_dir()

    str_target = str(tmp_path / "str_sub" / "test.db")
    resolved_str = resolve_db_path(str_target)
    assert resolved_str == Path(str_target)
    assert Path(str_target).parent.is_dir()


@pytest.mark.asyncio
async def test_init_db_creates_tables(tmp_path: Path) -> None:
    """Verify init_db creates all required application tables and indexes."""
    db_file = tmp_path / "test_init.db"
    await init_db(db_file)

    assert db_file.exists()

    async with get_connection(db_file) as conn:
        cursor = await conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        )
        rows = await cursor.fetchall()
        table_names = {row["name"] for row in rows}

        expected_tables = {
            "memories",
            "user_preferences",
            "installed_apps",
            "security_audit_logs",
            "session_context",
        }
        assert expected_tables.issubset(table_names)


@pytest.mark.asyncio
async def test_database_pragmas(tmp_path: Path) -> None:
    """Verify performance and integrity pragmas (WAL mode, foreign keys, busy timeout)."""
    db_file = tmp_path / "test_pragmas.db"
    await init_db(db_file)

    async with get_connection(db_file) as conn:
        # Check WAL mode
        cursor = await conn.execute("PRAGMA journal_mode;")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0].lower() == "wal"

        # Check foreign keys
        cursor = await conn.execute("PRAGMA foreign_keys;")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] == 1

        # Check busy timeout
        cursor = await conn.execute("PRAGMA busy_timeout;")
        row = await cursor.fetchone()
        assert row is not None
        assert row[0] >= 5000


@pytest.mark.asyncio
async def test_idempotent_init_db(tmp_path: Path) -> None:
    """Verify executing init_db multiple times does not corrupt or wipe existing data."""
    db_file = tmp_path / "test_idempotent.db"
    await init_db(db_file)

    # Insert sample row
    async with get_connection(db_file) as conn:
        await conn.execute(
            "INSERT INTO user_preferences (key, value) VALUES (?, ?);",
            ("theme", "dark"),
        )
        await conn.commit()

    # Re-run init_db
    await init_db(db_file)

    # Verify data is preserved
    async with get_connection(db_file) as conn:
        cursor = await conn.execute(
            "SELECT value FROM user_preferences WHERE key = ?;",
            ("theme",),
        )
        row = await cursor.fetchone()
        assert row is not None
        assert row["value"] == "dark"

"""Unit tests for broski MemoryStore and Data Access Object (DAO)."""

from pathlib import Path

import pytest

from broski.memory.store import MemoryStore


@pytest.fixture
async def store(tmp_path: Path) -> MemoryStore:
    """Create and initialize an isolated MemoryStore fixture."""
    db_file = tmp_path / "test_store.db"
    mem_store = MemoryStore(db_path=db_file)
    await mem_store.initialize()
    return mem_store


@pytest.mark.asyncio
async def test_save_and_get_memory(store: MemoryStore) -> None:
    """Verify saving, retrieving, and updating a memory item."""
    # Create memory
    item = await store.save_memory(
        key="project_dir",
        value="C:\\Projects\\broski",
        category="workspace",
        confidence=0.95,
    )
    assert item.key == "project_dir"
    assert item.value == "C:\\Projects\\broski"
    assert item.category == "workspace"
    assert item.confidence == 0.95

    # Retrieve memory
    fetched = await store.get_memory("project_dir")
    assert fetched is not None
    assert fetched.value == "C:\\Projects\\broski"

    # Update existing memory
    updated = await store.save_memory(
        key="project_dir",
        value="D:\\Projects\\broski",
        category="workspace",
    )
    assert updated.value == "D:\\Projects\\broski"
    re_fetched = await store.get_memory("project_dir")
    assert re_fetched is not None
    assert re_fetched.value == "D:\\Projects\\broski"


@pytest.mark.asyncio
async def test_search_and_list_memories(store: MemoryStore) -> None:
    """Verify searching memories with text queries and category filters."""
    await store.save_memory("favorite_coffee", "espresso", category="preferences")
    await store.save_memory("favorite_tea", "green tea", category="preferences")
    await store.save_memory("git_email", "dev@broski.ai", category="developer")

    # Search query in value
    results = await store.search_memories("tea")
    assert len(results) == 1
    assert results[0].key == "favorite_tea"

    # Search with category filter
    cat_results = await store.list_memories(category="preferences")
    assert len(cat_results) == 2

    # Query matching nothing
    empty = await store.search_memories("nonexistent")
    assert len(empty) == 0


@pytest.mark.asyncio
async def test_delete_and_forget_recent(store: MemoryStore) -> None:
    """Verify deletion by key and GDPR/privacy forget_recent."""
    await store.save_memory("temp_fact", "delete_me")
    assert await store.get_memory("temp_fact") is not None

    deleted = await store.delete_memory("temp_fact")
    assert deleted is True
    assert await store.get_memory("temp_fact") is None

    # Test forget_recent
    await store.save_memory("recent_fact_1", "value1")
    await store.save_memory("recent_fact_2", "value2")
    assert len(await store.list_memories()) == 2

    count = await store.forget_recent(seconds=300)
    assert count == 2
    assert len(await store.list_memories()) == 0


@pytest.mark.asyncio
async def test_user_preferences_crud(store: MemoryStore) -> None:
    """Verify storing, retrieving, listing, and deleting user preferences."""
    assert await store.get_preference("dark_mode", default="enabled") == "enabled"

    await store.set_preference("dark_mode", "disabled")
    assert await store.get_preference("dark_mode") == "disabled"

    await store.set_preference("default_language", "hinglish")
    prefs = await store.list_preferences()
    assert prefs == {"dark_mode": "disabled", "default_language": "hinglish"}

    deleted = await store.delete_preference("dark_mode")
    assert deleted is True
    assert await store.get_preference("dark_mode") is None


@pytest.mark.asyncio
async def test_app_registration_and_fuzzy_lookup(store: MemoryStore) -> None:
    """Verify registering desktop apps and finding them via name or aliases."""
    # Register Riot Games with aliases
    await store.register_app(
        name="Riot Client",
        path="C:\\Riot Games\\Riot Client\\RiotClientServices.exe",
        aliases=["riot", "riot games", "val", "valorant"],
    )
    # Register Spotify
    await store.register_app(
        name="Spotify",
        path="C:\\Users\\User\\AppData\\Roaming\\Spotify\\Spotify.exe",
        aliases=["music", "songs"],
    )

    # 1. Exact name match
    app1 = await store.find_app("Riot Client")
    assert app1 is not None
    assert app1.name == "Riot Client"
    assert "valorant" in app1.aliases

    # 2. Case-insensitive alias match
    app2 = await store.find_app("riot")
    assert app2 is not None
    assert app2.name == "Riot Client"

    app3 = await store.find_app("VALORANT")
    assert app3 is not None
    assert app3.name == "Riot Client"

    # 3. Partial alias match
    app4 = await store.find_app("music")
    assert app4 is not None
    assert app4.name == "Spotify"

    # 4. Record launch count
    assert app1.launch_count == 0
    await store.record_app_launch("Riot Client")
    updated_app = await store.find_app("Riot Client")
    assert updated_app is not None
    assert updated_app.launch_count == 1
    assert updated_app.last_launched is not None


@pytest.mark.asyncio
async def test_security_audit_logging(store: MemoryStore) -> None:
    """Verify logging and retrieving security audit trail events."""
    log_id = await store.log_audit_event(
        event_type="app_launch",
        actor="voice_assistant",
        action="launch_process",
        risk_level="MODERATE",
        status="CONFIRMED",
        details={"executable": "RiotClientServices.exe", "elevation": False},
    )
    assert log_id > 0

    logs = await store.get_recent_audit_logs(limit=10)
    assert len(logs) == 1
    assert logs[0].action == "launch_process"
    assert logs[0].status == "CONFIRMED"
    assert logs[0].details["executable"] == "RiotClientServices.exe"


@pytest.mark.asyncio
async def test_session_conversational_context(store: MemoryStore) -> None:
    """Verify recording and querying multi-turn conversational session history."""
    session_id = "session_test_42"

    await store.append_session_message(session_id, "user", "Hey broski, open Riot Games")
    await store.append_session_message(
        session_id, "assistant", "Launching Riot Client for you now!"
    )

    history = await store.get_session_history(session_id)
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].content == "Hey broski, open Riot Games"
    assert history[1].role == "assistant"

    # Test clear session
    cleared = await store.clear_session(session_id)
    assert cleared == 2
    assert len(await store.get_session_history(session_id)) == 0

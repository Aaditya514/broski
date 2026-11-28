"""Unit tests for Obsidian Local REST API client and vault tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broski.config import ObsidianConfig
from broski.tools.base import RiskLevel
from broski.tools.obsidian import (
    ObsidianAppendDailyNoteTool,
    ObsidianClient,
    ObsidianCreateNoteTool,
    ObsidianReadDailyNoteTool,
    ObsidianReadNoteTool,
    ObsidianSearchNotesTool,
)


@pytest.fixture
def obsidian_config() -> ObsidianConfig:
    return ObsidianConfig(
        host="127.0.0.1",
        port=27124,
        use_https=True,
    )


# --- ObsidianClient Tests ---


@pytest.mark.asyncio
async def test_obsidian_client_health_check_success(obsidian_config: ObsidianConfig) -> None:
    client = ObsidianClient(config=obsidian_config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_http_client = AsyncMock()
    mock_http_client.get.return_value = mock_resp
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None

    with patch.object(client, "_client", return_value=mock_http_client):
        assert await client.health_check() is True


@pytest.mark.asyncio
async def test_obsidian_client_health_check_failure(obsidian_config: ObsidianConfig) -> None:
    client = ObsidianClient(config=obsidian_config)

    mock_http_client = AsyncMock()
    mock_http_client.get.side_effect = RuntimeError("Connection refused")
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None

    with patch.object(client, "_client", return_value=mock_http_client):
        assert await client.health_check() is False


@pytest.mark.asyncio
async def test_obsidian_client_read_daily_note_success(obsidian_config: ObsidianConfig) -> None:
    client = ObsidianClient(config=obsidian_config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "# 2026-11-29\n- [ ] Review sprint backlog\n- [x] Push commits"
    mock_resp.raise_for_status = MagicMock()

    mock_http_client = AsyncMock()
    mock_http_client.get.return_value = mock_resp
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None

    with patch.object(client, "_client", return_value=mock_http_client):
        content = await client.read_daily_note()
        assert "Review sprint backlog" in content


@pytest.mark.asyncio
async def test_obsidian_client_read_daily_note_404_empty(obsidian_config: ObsidianConfig) -> None:
    client = ObsidianClient(config=obsidian_config)

    mock_resp = MagicMock()
    mock_resp.status_code = 404

    mock_http_client = AsyncMock()
    mock_http_client.get.return_value = mock_resp
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None

    with patch.object(client, "_client", return_value=mock_http_client):
        content = await client.read_daily_note()
        assert content == ""


@pytest.mark.asyncio
async def test_obsidian_client_append_daily_note(obsidian_config: ObsidianConfig) -> None:
    client = ObsidianClient(config=obsidian_config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_http_client = AsyncMock()
    mock_http_client.post.return_value = mock_resp
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None

    with patch.object(client, "_client", return_value=mock_http_client):
        success = await client.append_daily_note("- Remember to test speech loop")
        assert success is True
        mock_http_client.post.assert_called_once()


@pytest.mark.asyncio
async def test_obsidian_client_read_note_not_found(obsidian_config: ObsidianConfig) -> None:
    client = ObsidianClient(config=obsidian_config)

    mock_resp = MagicMock()
    mock_resp.status_code = 404

    mock_http_client = AsyncMock()
    mock_http_client.get.return_value = mock_resp
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None

    with (
        patch.object(client, "_client", return_value=mock_http_client),
        pytest.raises(FileNotFoundError),
    ):
        await client.read_note("non_existent_note")


@pytest.mark.asyncio
async def test_obsidian_client_create_note_success(obsidian_config: ObsidianConfig) -> None:
    client = ObsidianClient(config=obsidian_config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    mock_http_client = AsyncMock()
    mock_http_client.put.return_value = mock_resp
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None

    with patch.object(client, "_client", return_value=mock_http_client):
        assert await client.create_or_update_note("Ideas/AI.md", "# AI Notes") is True


# --- Obsidian Tools Tests ---


@pytest.mark.asyncio
async def test_tool_read_daily_note_success() -> None:
    mock_client = AsyncMock()
    mock_client.read_daily_note.return_value = "- Task 1\n- Task 2"

    tool = ObsidianReadDailyNoteTool(client=mock_client)
    assert tool.risk_level == RiskLevel.SAFE

    res = await tool.execute()
    assert res.success is True
    assert "Task 1" in res.output
    assert "daily note, bro" in res.message


@pytest.mark.asyncio
async def test_tool_read_daily_note_empty() -> None:
    mock_client = AsyncMock()
    mock_client.read_daily_note.return_value = ""

    tool = ObsidianReadDailyNoteTool(client=mock_client)
    res = await tool.execute()
    assert res.success is True
    assert "currently empty, bro" in res.message


@pytest.mark.asyncio
async def test_tool_append_daily_note_formatting() -> None:
    mock_client = AsyncMock()
    mock_client.append_daily_note.return_value = True

    tool = ObsidianAppendDailyNoteTool(client=mock_client)
    assert tool.risk_level == RiskLevel.MODERATE

    # Unformatted text should automatically gain a markdown bullet '- '
    res = await tool.execute(content="Check PRD acceptance criteria")
    assert res.success is True
    assert "added that to your daily note" in res.message
    mock_client.append_daily_note.assert_called_once_with("- Check PRD acceptance criteria")


@pytest.mark.asyncio
async def test_tool_read_note_found() -> None:
    mock_client = AsyncMock()
    mock_client.read_note.return_value = "# Project Blueprint\nCore microkernel specs."

    tool = ObsidianReadNoteTool(client=mock_client)
    res = await tool.execute(path="Project Blueprint")
    assert res.success is True
    assert "Pulled up" in res.message
    assert "Project Blueprint" in res.message


@pytest.mark.asyncio
async def test_tool_read_note_missing() -> None:
    mock_client = AsyncMock()
    mock_client.read_note.side_effect = FileNotFoundError("Missing")

    tool = ObsidianReadNoteTool(client=mock_client)
    res = await tool.execute(path="Ghost Note")
    assert res.success is False
    assert "couldn't find a note" in res.message


@pytest.mark.asyncio
async def test_tool_search_notes() -> None:
    mock_client = AsyncMock()
    mock_client.search_notes.return_value = [
        {"filename": "Python Tricks.md"},
        {"filename": "PySide6 HUD.md"},
    ]

    tool = ObsidianSearchNotesTool(client=mock_client)
    res = await tool.execute(query="Python")
    assert res.success is True
    assert len(res.output) == 2
    assert "Python Tricks" in res.message


@pytest.mark.asyncio
async def test_tool_create_note() -> None:
    mock_client = AsyncMock()
    mock_client.create_or_update_note.return_value = True

    tool = ObsidianCreateNoteTool(client=mock_client)
    assert tool.risk_level == RiskLevel.MODERATE

    res = await tool.execute(path="Ideas/Voice.md", content="# Voice Design")
    assert res.success is True
    assert "created 'Ideas/Voice.md'" in res.message

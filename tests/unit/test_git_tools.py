"""Unit tests for the Developer Git Assistant tools and security gating."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from broski.tools.base import RiskLevel
from broski.tools.git import (
    GitBranchTool,
    GitCommitTool,
    GitDiffTool,
    GitInspector,
    GitLogTool,
    GitPushTool,
    GitStatusTool,
)
from broski.tools.registry import ToolRegistry
from broski.tools.security import SecurityConfirmationManager

# --- GitInspector Tests ---


def test_git_inspector_discover_repo_path(tmp_path: Path) -> None:
    """Verify repo discovery identifies .git directories and ascends tree."""
    repo_dir = tmp_path / "my_project"
    repo_dir.mkdir()
    (repo_dir / ".git").mkdir()

    sub_dir = repo_dir / "src" / "pkg"
    sub_dir.mkdir(parents=True)

    inspector = GitInspector(default_repo_path=sub_dir)
    found = inspector.discover_repo_path(sub_dir)
    assert found == repo_dir

    # Non-repo temp directory
    non_repo = tmp_path / "isolated"
    non_repo.mkdir()
    found_none = GitInspector().discover_repo_path(non_repo)
    # If tmp_path isn't in a repo, found_none could be None or broski root if relative
    # We verify that it doesn't mistakenly return isolated
    assert found_none != non_repo


@pytest.mark.asyncio
async def test_git_inspector_get_status_clean() -> None:
    inspector = GitInspector()
    mock_out = "## main...origin/main\n"
    with patch.object(inspector, "run_git_command", return_value=(0, mock_out, "")):
        status = await inspector.get_status(Path("dummy_repo"))
        assert status["is_repo"] is True
        assert status["branch"] == "main"
        assert status["ahead"] == 0
        assert status["behind"] == 0
        assert status["is_clean"] is True


@pytest.mark.asyncio
async def test_git_inspector_get_status_dirty() -> None:
    inspector = GitInspector()
    mock_out = (
        "## feat/tools...origin/feat/tools [ahead 2, behind 1]\n"
        "M  src/tools/git.py\n"
        " M docs/DEV_LOG.md\n"
        "?? new_file.txt\n"
    )
    with patch.object(inspector, "run_git_command", return_value=(0, mock_out, "")):
        status = await inspector.get_status(Path("dummy_repo"))
        assert status["is_repo"] is True
        assert status["branch"] == "feat/tools"
        assert status["ahead"] == 2
        assert status["behind"] == 1
        assert status["is_clean"] is False
        assert status["staged_count"] == 1
        assert "src/tools/git.py" in status["staged_files"]
        assert status["modified_count"] == 1
        assert "docs/DEV_LOG.md" in status["modified_files"]
        assert status["untracked_count"] == 1
        assert "new_file.txt" in status["untracked_files"]


@pytest.mark.asyncio
async def test_git_inspector_get_status_not_repo() -> None:
    inspector = GitInspector()
    with patch.object(inspector, "discover_repo_path", return_value=None):
        status = await inspector.get_status()
        assert status["is_repo"] is False
        assert "error" in status


@pytest.mark.asyncio
async def test_git_inspector_get_diff_summary() -> None:
    inspector = GitInspector()
    mock_diff = " 2 files changed, 20 insertions(+), 5 deletions(-)\n"
    with patch.object(inspector, "run_git_command", return_value=(0, mock_diff, "")):
        diff = await inspector.get_diff_summary()
        assert "2 files changed" in diff


@pytest.mark.asyncio
async def test_git_inspector_get_log() -> None:
    inspector = GitInspector()
    mock_log = (
        "a1b2c3d|feat: add git tools|Aaditya|2 hours ago\n"
        "e4f5a6b|docs: update log|Aaditya|5 hours ago\n"
    )
    with patch.object(inspector, "run_git_command", return_value=(0, mock_log, "")):
        commits = await inspector.get_log(count=2)
        assert len(commits) == 2
        assert commits[0]["hash"] == "a1b2c3d"
        assert commits[0]["subject"] == "feat: add git tools"
        assert commits[0]["author"] == "Aaditya"
        assert commits[0]["relative_time"] == "2 hours ago"


# --- Typed Tools Tests ---


@pytest.mark.asyncio
async def test_git_status_tool_clean() -> None:
    mock_inspector = AsyncMock()
    mock_inspector.get_status.return_value = {
        "is_repo": True,
        "repo_name": "broski",
        "branch": "main",
        "is_clean": True,
    }

    tool = GitStatusTool(inspector=mock_inspector)
    assert tool.risk_level == RiskLevel.SAFE

    res = await tool.execute()
    assert res.success is True
    assert "clean" in res.message
    assert "main" in res.message


@pytest.mark.asyncio
async def test_git_status_tool_dirty() -> None:
    mock_inspector = AsyncMock()
    mock_inspector.get_status.return_value = {
        "is_repo": True,
        "repo_name": "broski",
        "branch": "feat/tools",
        "is_clean": False,
        "staged_count": 1,
        "modified_count": 2,
        "untracked_count": 0,
    }

    tool = GitStatusTool(inspector=mock_inspector)
    res = await tool.execute()
    assert res.success is True
    assert "1 staged" in res.message
    assert "2 modified" in res.message


@pytest.mark.asyncio
async def test_git_status_tool_not_repo() -> None:
    mock_inspector = AsyncMock()
    mock_inspector.get_status.return_value = {
        "is_repo": False,
        "error": "Not a git repository",
    }

    tool = GitStatusTool(inspector=mock_inspector)
    res = await tool.execute()
    assert res.success is False
    assert "git repo" in res.message


@pytest.mark.asyncio
async def test_git_diff_tool() -> None:
    mock_inspector = AsyncMock()
    mock_inspector.get_diff_summary.return_value = " 3 files changed, 50 insertions(+)"

    tool = GitDiffTool(inspector=mock_inspector)
    assert tool.risk_level == RiskLevel.SAFE

    res = await tool.execute(cached=False)
    assert res.success is True
    assert "diff stat" in res.message
    assert "3 files changed" in res.message


@pytest.mark.asyncio
async def test_git_log_tool() -> None:
    mock_inspector = AsyncMock()
    mock_inspector.get_log.return_value = [
        {"hash": "1234567", "subject": "Initial commit", "author": "Lead", "relative_time": "1 day ago"}
    ]

    tool = GitLogTool(inspector=mock_inspector)
    assert tool.risk_level == RiskLevel.SAFE

    res = await tool.execute(count=3)
    assert res.success is True
    assert "Initial commit" in res.message


@pytest.mark.asyncio
async def test_git_branch_tool() -> None:
    mock_inspector = AsyncMock()
    mock_inspector.get_branch.return_value = "feat/sprint-5-tools"

    tool = GitBranchTool(inspector=mock_inspector)
    assert tool.risk_level == RiskLevel.SAFE

    res = await tool.execute()
    assert res.success is True
    assert "feat/sprint-5-tools" in res.message


@pytest.mark.asyncio
async def test_git_commit_tool_risk_and_execution() -> None:
    mock_inspector = AsyncMock()
    mock_inspector.run_git_command.return_value = (0, "[feat/tools abc1234] feat: add git", "")

    tool = GitCommitTool(inspector=mock_inspector)
    assert tool.risk_level == RiskLevel.CRITICAL

    # Verify empty message validation
    res_empty = await tool.execute(message="")
    assert res_empty.success is False
    assert "cannot be empty" in (res_empty.error or "")

    # Execute valid commit
    res = await tool.execute(message="feat: add git")
    assert res.success is True
    assert "Committed your changes" in res.message


@pytest.mark.asyncio
async def test_git_commit_security_gating_in_registry() -> None:
    """Verify GitCommitTool is blocked by ToolRegistry unless explicitly approved."""
    mock_inspector = AsyncMock()
    mock_inspector.run_git_command.return_value = (0, "Committed", "")

    manager = SecurityConfirmationManager(require_critical=True)
    registry = ToolRegistry(confirmation_manager=manager)
    registry.register(GitCommitTool(inspector=mock_inspector))

    # 1. Unconfirmed attempt is gated
    blocked_res = await registry.execute("git_commit", {"message": "wip"})
    assert blocked_res.success is False
    assert blocked_res.output["status"] == "pending_confirmation"
    conf_id = blocked_res.output["confirmation_id"]
    mock_inspector.run_git_command.assert_not_called()

    # 2. Confirmed attempt executes
    manager.confirm(conf_id, approved=True)
    approved_res = await registry.execute(
        "git_commit",
        {"message": "wip"},
        confirmation_id=conf_id,
    )
    assert approved_res.success is True
    mock_inspector.run_git_command.assert_called_once()


@pytest.mark.asyncio
async def test_git_push_security_gating_in_registry() -> None:
    """Verify GitPushTool is blocked by ToolRegistry unless explicitly approved."""
    mock_inspector = AsyncMock()
    mock_inspector.run_git_command.return_value = (0, "Pushed to origin/main", "")

    manager = SecurityConfirmationManager(require_critical=True)
    registry = ToolRegistry(confirmation_manager=manager)
    registry.register(GitPushTool(inspector=mock_inspector))

    # Gated
    blocked_res = await registry.execute("git_push", {"remote": "origin"})
    assert blocked_res.success is False
    assert "pending_confirmation" in blocked_res.output["status"]

    # Direct confirmed=True override
    direct_res = await registry.execute("git_push", {"remote": "origin"}, confirmed=True)
    assert direct_res.success is True
    assert "Pushed your commits to origin" in direct_res.message

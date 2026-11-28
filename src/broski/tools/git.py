"""Developer Git Assistant tools for broski.

Provides safe, read-only repository inspection (status, diff, log, branch)
and strictly gated, confirmed mutating operations (commit, push).
Adheres strictly to 'No unrestricted LLM-generated terminal execution'.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any, ClassVar

from broski.tools.base import BaseTool, RiskLevel, ToolResult

logger = logging.getLogger("broski.tools.git")


class GitInspector:
    """Safely executes git operations without shell=True."""

    def __init__(self, default_repo_path: Path | str | None = None) -> None:
        self.default_repo_path = Path(default_repo_path) if default_repo_path else None

    def discover_repo_path(self, provided_path: str | Path | None = None) -> Path | None:
        """Find root directory containing .git from provided path or current working directory."""
        candidates = []
        if provided_path:
            candidates.append(Path(provided_path).resolve())
        if self.default_repo_path:
            candidates.append(self.default_repo_path.resolve())
        candidates.append(Path.cwd().resolve())

        for start in candidates:
            curr: Path | None = start if start.is_dir() else start.parent
            while curr and curr != curr.parent:
                if (curr / ".git").exists():
                    return curr
                curr = curr.parent
        return None

    async def run_git_command(
        self,
        args: list[str],
        cwd: Path | None = None,
    ) -> tuple[int, str, str]:
        """Execute a git command safely as a subprocess without shell=True."""
        repo_dir = cwd or self.discover_repo_path()
        if not repo_dir:
            return 1, "", "Not a git repository (or any of the parent directories)"

        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                *args,
                cwd=str(repo_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await proc.communicate()
            stdout = stdout_bytes.decode("utf-8", errors="replace").strip()
            stderr = stderr_bytes.decode("utf-8", errors="replace").strip()
            return proc.returncode or 0, stdout, stderr
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to execute git command '%s': %s", args, exc)
            return 1, "", str(exc)

    async def get_status(self, repo_path: Path | str | None = None) -> dict[str, Any]:
        """Parse git status into structured repository state."""
        target = Path(repo_path) if repo_path else self.discover_repo_path()
        if not target:
            return {"is_repo": False, "error": "Not a git repository"}

        code, out, err = await self.run_git_command(["status", "--porcelain=v1", "-b"], cwd=target)
        if code != 0:
            return {"is_repo": False, "error": err or "Failed to run git status"}

        lines = out.splitlines()
        branch_line = lines[0] if lines else "## Unknown"
        branch_name = "HEAD"
        ahead = 0
        behind = 0

        # Parse branch header (e.g. '## main...origin/main [ahead 1, behind 2]')
        if branch_line.startswith("## "):
            branch_info = branch_line[3:]
            if "..." in branch_info:
                branch_name = branch_info.split("...")[0].strip()
            else:
                branch_name = branch_info.split()[0].strip()

            if "[ahead " in branch_line:
                try:
                    part = branch_line.split("[ahead ")[1].split("]")[0]
                    ahead_val = part.split(",")[0].strip()
                    ahead = int(ahead_val)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Failed parsing ahead count: %s", exc)

            if "behind " in branch_line:
                try:
                    part = branch_line.split("behind ")[1].split("]")[0]
                    behind = int(part.strip())
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Failed parsing behind count: %s", exc)

        staged: list[str] = []
        modified: list[str] = []
        untracked: list[str] = []

        for line in lines[1:]:
            if len(line) < 3:
                continue
            index_status = line[0]
            worktree_status = line[1]
            filepath = line[3:].strip()

            if index_status == "?" and worktree_status == "?":
                untracked.append(filepath)
            else:
                if index_status not in (" ", "?"):
                    staged.append(filepath)
                if worktree_status not in (" ", "?"):
                    modified.append(filepath)

        return {
            "is_repo": True,
            "repo_path": str(target),
            "repo_name": os.path.basename(str(target)),
            "branch": branch_name,
            "ahead": ahead,
            "behind": behind,
            "staged_count": len(staged),
            "staged_files": staged,
            "modified_count": len(modified),
            "modified_files": modified,
            "untracked_count": len(untracked),
            "untracked_files": untracked,
            "is_clean": len(staged) == 0 and len(modified) == 0 and len(untracked) == 0,
        }

    async def get_diff_summary(
        self,
        repo_path: Path | str | None = None,
        cached: bool = False,
    ) -> str:
        """Get git diff stats for working tree or staged changes."""
        target = Path(repo_path) if repo_path else self.discover_repo_path()
        args = ["diff", "--stat"]
        if cached:
            args.append("--cached")
        code, out, _ = await self.run_git_command(args, cwd=target)
        if code != 0 or not out:
            return "No changes." if code == 0 else "Error retrieving diff."
        return out

    async def get_log(
        self,
        repo_path: Path | str | None = None,
        count: int = 5,
    ) -> list[dict[str, str]]:
        """Retrieve recent commits with hash, subject, author, and relative time."""
        target = Path(repo_path) if repo_path else self.discover_repo_path()
        args = ["log", f"-n{count}", "--format=%h|%s|%an|%cr"]
        code, out, _ = await self.run_git_command(args, cwd=target)
        if code != 0 or not out:
            return []

        commits = []
        for line in out.splitlines():
            parts = line.split("|")
            if len(parts) >= 4:
                commits.append({
                    "hash": parts[0],
                    "subject": parts[1],
                    "author": parts[2],
                    "relative_time": parts[3],
                })
        return commits

    async def get_branch(self, repo_path: Path | str | None = None) -> str:
        """Get the name of the current active git branch."""
        target = Path(repo_path) if repo_path else self.discover_repo_path()
        code, out, _ = await self.run_git_command(["branch", "--show-current"], cwd=target)
        if code == 0 and out:
            return out.strip()
        # Fallback for detached HEAD
        code, out, _ = await self.run_git_command(["rev-parse", "--abbrev-ref", "HEAD"], cwd=target)
        return out.strip() if code == 0 and out else "HEAD"


# --- Typed Tool Implementations ---


class GitStatusTool(BaseTool):
    """Tool to inspect active repository status."""

    name = "git_status"
    description = (
        "Inspects your current git repository status, returning the active branch, "
        "staged changes, modified files, and untracked files."
    )
    risk_level = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Optional path to the git repository. Defaults to current workspace.",
            }
        },
        "required": [],
    }

    def __init__(self, inspector: GitInspector | None = None) -> None:
        self.inspector = inspector or GitInspector()

    async def execute(self, **kwargs: Any) -> ToolResult:
        repo_path = kwargs.get("repo_path")
        data = await self.inspector.get_status(repo_path)
        if not data.get("is_repo"):
            return ToolResult(
                success=False,
                error=data.get("error", "Not a git repository"),
                message="Doesn't look like we're inside a git repository right now, bro.",
            )

        branch = data.get("branch", "unknown")
        repo_name = data.get("repo_name", "repo")
        if data.get("is_clean"):
            msg = f"You're on branch '{branch}' in {repo_name}, bro. Working tree is completely clean!"
        else:
            parts = []
            if data.get("staged_count"):
                parts.append(f"{data['staged_count']} staged")
            if data.get("modified_count"):
                parts.append(f"{data['modified_count']} modified")
            if data.get("untracked_count"):
                parts.append(f"{data['untracked_count']} untracked")

            summary = ", ".join(parts)
            msg = f"You're on '{branch}' in {repo_name}, bro: {summary}."

        return ToolResult(
            success=True,
            output=data,
            message=msg,
        )


class GitDiffTool(BaseTool):
    """Tool to inspect git diff statistics."""

    name = "git_diff"
    description = "Shows summary statistics of uncommitted or staged changes in the current git repository."
    risk_level = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "cached": {
                "type": "boolean",
                "description": "If true, shows diff for staged changes. If false, shows unstaged changes.",
            },
            "repo_path": {
                "type": "string",
                "description": "Optional path to the git repository.",
            },
        },
        "required": [],
    }

    def __init__(self, inspector: GitInspector | None = None) -> None:
        self.inspector = inspector or GitInspector()

    async def execute(self, **kwargs: Any) -> ToolResult:
        cached = bool(kwargs.get("cached", False))
        repo_path = kwargs.get("repo_path")
        diff_text = await self.inspector.get_diff_summary(repo_path, cached=cached)

        if not diff_text or diff_text == "No changes.":
            target_desc = "staged changes" if cached else "working tree changes"
            return ToolResult(
                success=True,
                output="",
                message=f"No {target_desc} right now, bro.",
            )

        # Extract last summary line (e.g. '3 files changed, 45 insertions(+), 12 deletions(-)')
        lines = diff_text.strip().splitlines()
        last_line = lines[-1] if lines else "Files changed."
        return ToolResult(
            success=True,
            output=diff_text,
            message=f"Here's your diff stat, bro: {last_line}",
        )


class GitLogTool(BaseTool):
    """Tool to view recent commits."""

    name = "git_log"
    description = "Shows the most recent commits in the git repository."
    risk_level = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "count": {
                "type": "integer",
                "description": "Number of recent commits to fetch (1 to 10). Default is 5.",
            },
            "repo_path": {
                "type": "string",
                "description": "Optional path to git repository.",
            },
        },
        "required": [],
    }

    def __init__(self, inspector: GitInspector | None = None) -> None:
        self.inspector = inspector or GitInspector()

    async def execute(self, **kwargs: Any) -> ToolResult:
        count = min(max(int(kwargs.get("count", 5)), 1), 10)
        repo_path = kwargs.get("repo_path")
        commits = await self.inspector.get_log(repo_path, count=count)

        if not commits:
            return ToolResult(
                success=True,
                output=[],
                message="No commits found in this repository yet, bro.",
            )

        latest = commits[0]
        latest_desc = f"Latest is '{latest['subject']}' by {latest['author']} ({latest['relative_time']})"
        return ToolResult(
            success=True,
            output=commits,
            message=f"Showing last {len(commits)} commits, bro. {latest_desc}.",
        )


class GitBranchTool(BaseTool):
    """Tool to report current active git branch."""

    name = "git_branch"
    description = "Reports the name of the currently active git branch in your workspace."
    risk_level = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Optional path to git repository.",
            }
        },
        "required": [],
    }

    def __init__(self, inspector: GitInspector | None = None) -> None:
        self.inspector = inspector or GitInspector()

    async def execute(self, **kwargs: Any) -> ToolResult:
        repo_path = kwargs.get("repo_path")
        branch = await self.inspector.get_branch(repo_path)
        return ToolResult(
            success=True,
            output={"branch": branch},
            message=f"You're currently on branch '{branch}', bro.",
        )


class GitCommitTool(BaseTool):
    """Mutating tool to commit staged changes. Strictly gated by CRITICAL risk tier."""

    name = "git_commit"
    description = "Commits currently staged changes with a commit message. Mutating action."
    risk_level = RiskLevel.CRITICAL
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The commit message.",
            },
            "repo_path": {
                "type": "string",
                "description": "Optional path to git repository.",
            },
        },
        "required": ["message"],
    }

    def __init__(self, inspector: GitInspector | None = None) -> None:
        self.inspector = inspector or GitInspector()

    async def execute(self, **kwargs: Any) -> ToolResult:
        message = kwargs.get("message", "").strip()
        repo_path = kwargs.get("repo_path")
        if not message:
            return ToolResult(
                success=False,
                error="Commit message cannot be empty",
                message="What commit message should I use, bro?",
            )

        code, out, err = await self.inspector.run_git_command(
            ["commit", "-m", message],
            cwd=Path(repo_path) if repo_path else None,
        )
        if code == 0:
            return ToolResult(
                success=True,
                output={"output": out},
                message=f"Committed your changes with message: '{message}', bro!",
            )
        return ToolResult(
            success=False,
            error=err or out,
            message=f"Git commit failed, bro: {err or out}",
        )


class GitPushTool(BaseTool):
    """Mutating tool to push commits to remote. Strictly gated by CRITICAL risk tier."""

    name = "git_push"
    description = "Pushes committed changes to remote repository. Mutating action."
    risk_level = RiskLevel.CRITICAL
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "remote": {
                "type": "string",
                "description": "Remote name (defaults to 'origin').",
            },
            "branch": {
                "type": "string",
                "description": "Optional branch name to push.",
            },
            "repo_path": {
                "type": "string",
                "description": "Optional path to git repository.",
            },
        },
        "required": [],
    }

    def __init__(self, inspector: GitInspector | None = None) -> None:
        self.inspector = inspector or GitInspector()

    async def execute(self, **kwargs: Any) -> ToolResult:
        remote = kwargs.get("remote", "origin")
        branch = kwargs.get("branch")
        repo_path = kwargs.get("repo_path")

        args = ["push", remote]
        if branch:
            args.append(branch)

        code, out, err = await self.inspector.run_git_command(
            args,
            cwd=Path(repo_path) if repo_path else None,
        )
        if code == 0:
            return ToolResult(
                success=True,
                output={"output": out},
                message=f"Pushed your commits to {remote}, bro!",
            )
        return ToolResult(
            success=False,
            error=err or out,
            message=f"Git push ran into an issue, bro: {err or out}",
        )

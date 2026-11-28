"""Obsidian Local REST API integration and knowledge vault tools.

Enables broski to query notes, read daily notes, and append thoughts or tasks
hands-free via the official Obsidian Local REST API plugin.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar

import httpx

from broski.config import ObsidianConfig, get_settings
from broski.tools.base import BaseTool, RiskLevel, ToolResult

logger = logging.getLogger("broski.tools.obsidian")


class ObsidianClient:
    """Asynchronous HTTP client communicating with the Obsidian Local REST API plugin."""

    def __init__(self, config: ObsidianConfig | None = None) -> None:
        if config is not None:
            self.config = config
        else:
            self.config = get_settings().obsidian

        self._token: str | None = (
            self.config.api_key.get_secret_value() if self.config.api_key else None
        )

    def _get_headers(self, accept: str = "application/json", content_type: str | None = None) -> dict[str, str]:
        headers = {"Accept": accept}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def _client(self) -> httpx.AsyncClient:
        """Create an async httpx client configured for Obsidian local HTTPS/HTTP."""
        return httpx.AsyncClient(
            base_url=self.config.base_url,
            verify=False,  # Obsidian Local REST API uses local self-signed SSL certs
            timeout=8.0,
        )

    async def health_check(self) -> bool:
        """Verify that the Obsidian Local REST API server is online and accepting requests."""
        try:
            async with self._client() as client:
                res = await client.get("/", headers=self._get_headers())
                return res.status_code == 200
        except Exception as exc:  # noqa: BLE001
            logger.debug("Obsidian health check failed: %s", exc)
            return False

    async def read_daily_note(self) -> str:
        """Read the full content of today's periodic daily note."""
        async with self._client() as client:
            res = await client.get("/periodic/daily/", headers=self._get_headers(accept="text/markdown"))
            if res.status_code == 404:
                return ""
            res.raise_for_status()
            return res.text

    async def append_daily_note(self, content: str) -> bool:
        """Append text or a bullet point to today's daily note."""
        formatted = content if content.endswith("\n") else f"{content}\n"
        async with self._client() as client:
            res = await client.post(
                "/periodic/daily/",
                headers=self._get_headers(accept="*/*", content_type="text/markdown"),
                content=formatted.encode("utf-8"),
            )
            return res.status_code in (200, 204)

    async def read_note(self, path: str) -> str:
        """Read a note by path relative to the vault root."""
        clean_path = path.lstrip("/")
        if not clean_path.endswith(".md"):
            clean_path = f"{clean_path}.md"
        async with self._client() as client:
            res = await client.get(
                f"/vault/{clean_path}",
                headers=self._get_headers(accept="text/markdown"),
            )
            if res.status_code == 404:
                raise FileNotFoundError(f"Note '{clean_path}' not found in vault.")
            res.raise_for_status()
            return res.text

    async def append_note(self, path: str, content: str) -> bool:
        """Append text to an existing note."""
        clean_path = path.lstrip("/")
        if not clean_path.endswith(".md"):
            clean_path = f"{clean_path}.md"
        formatted = content if content.endswith("\n") else f"{content}\n"
        async with self._client() as client:
            res = await client.post(
                f"/vault/{clean_path}",
                headers=self._get_headers(accept="*/*", content_type="text/markdown"),
                content=formatted.encode("utf-8"),
            )
            return res.status_code in (200, 204)

    async def create_or_update_note(self, path: str, content: str) -> bool:
        """Create or overwrite a note in the vault."""
        clean_path = path.lstrip("/")
        if not clean_path.endswith(".md"):
            clean_path = f"{clean_path}.md"
        async with self._client() as client:
            res = await client.put(
                f"/vault/{clean_path}",
                headers=self._get_headers(accept="*/*", content_type="text/markdown"),
                content=content.encode("utf-8"),
            )
            return res.status_code in (200, 204)

    async def list_vault_files(self, dir_path: str = "") -> list[str]:
        """List files inside a vault directory."""
        clean_path = dir_path.strip("/")
        url = f"/vault/{clean_path}/" if clean_path else "/vault/"
        async with self._client() as client:
            res = await client.get(url, headers=self._get_headers())
            if res.status_code == 404:
                return []
            res.raise_for_status()
            data = res.json()
            if isinstance(data, dict) and "files" in data:
                return [f for f in data["files"] if isinstance(f, str)]
            if isinstance(data, list):
                return [str(f) for f in data]
            return []

    async def search_notes(self, query: str) -> list[dict[str, Any]]:
        """Search notes in the vault by keyword or content."""
        async with self._client() as client:
            try:
                res = await client.post(
                    f"/search/simple/?query={query}",
                    headers=self._get_headers(),
                )
                if res.status_code == 200:
                    data = res.json()
                    if isinstance(data, list):
                        return data
            except Exception as exc:  # noqa: BLE001
                logger.debug("Obsidian simple search failed: %s", exc)

        # Fallback: search file listing matching query in name
        files = await self.list_vault_files()
        matching = [f for f in files if query.lower() in f.lower()]
        return [{"filename": f, "matches": []} for f in matching]


# --- Typed Tool Implementations ---


class ObsidianReadDailyNoteTool(BaseTool):
    """Tool to read today's daily note from the Obsidian vault."""

    name = "obsidian_read_daily_note"
    description = "Reads the contents of today's Daily Note from your Obsidian vault."
    risk_level = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, client: ObsidianClient | None = None) -> None:
        self.client = client or ObsidianClient()

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            content = await self.client.read_daily_note()
            if not content:
                return ToolResult(
                    success=True,
                    output="",
                    message="Your daily note for today is currently empty, bro.",
                )
            # Preview first 300 characters for voice brevity
            lines = content.strip().splitlines()
            preview = " ".join(lines[:4])
            if len(preview) > 200:
                preview = f"{preview[:197]}..."
            return ToolResult(
                success=True,
                output=content,
                message=f"Here's what's in your daily note, bro: {preview}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read Obsidian daily note: %s", exc)
            return ToolResult(
                success=False,
                error=str(exc),
                message="Couldn't reach Obsidian right now, bro. Make sure the Local REST API plugin is enabled.",
            )


class ObsidianAppendDailyNoteTool(BaseTool):
    """Tool to append a thought, bullet, or task to today's daily note."""

    name = "obsidian_append_daily_note"
    description = "Appends a thought, idea, bullet point, or task to today's Daily Note in Obsidian."
    risk_level = RiskLevel.MODERATE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The text, note, or task bullet to append to today's daily note.",
            }
        },
        "required": ["content"],
    }

    def __init__(self, client: ObsidianClient | None = None) -> None:
        self.client = client or ObsidianClient()

    async def execute(self, **kwargs: Any) -> ToolResult:
        content = kwargs.get("content", "").strip()
        if not content:
            return ToolResult(
                success=False,
                error="Content cannot be empty",
                message="What would you like me to write down in your daily note, bro?",
            )

        # Prefix with markdown bullet if not formatted
        formatted = content if content.startswith(("- ", "* ", "#", "1. ")) else f"- {content}"

        try:
            success = await self.client.append_daily_note(formatted)
            if success:
                return ToolResult(
                    success=True,
                    output={"appended": formatted},
                    message="Got you bro, added that to your daily note.",
                )
            return ToolResult(
                success=False,
                error="Obsidian server returned non-success code",
                message="Obsidian didn't accept the update, bro. Check your vault connection.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to append to Obsidian daily note: %s", exc)
            return ToolResult(
                success=False,
                error=str(exc),
                message="Couldn't connect to Obsidian, bro. Is the app and Local REST API plugin running?",
            )


class ObsidianReadNoteTool(BaseTool):
    """Tool to read any note from the vault by path."""

    name = "obsidian_read_note"
    description = "Reads a specific markdown note from your Obsidian vault by its file name or path."
    risk_level = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative path to the note (e.g. 'Work/Project.md' or 'ideas').",
            }
        },
        "required": ["path"],
    }

    def __init__(self, client: ObsidianClient | None = None) -> None:
        self.client = client or ObsidianClient()

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "").strip()
        if not path:
            return ToolResult(success=False, error="Path is required", message="Which note should I open, bro?")

        try:
            content = await self.client.read_note(path)
            lines = content.strip().splitlines()
            preview = " ".join(lines[:3])
            if len(preview) > 180:
                preview = f"{preview[:177]}..."
            return ToolResult(
                success=True,
                output=content,
                message=f"Pulled up '{path}', bro: {preview}",
            )
        except FileNotFoundError:
            return ToolResult(
                success=False,
                error="Note not found",
                message=f"I couldn't find a note called '{path}' in your vault, bro.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to read note '%s': %s", path, exc)
            return ToolResult(
                success=False,
                error=str(exc),
                message="Couldn't reach Obsidian right now, bro.",
            )


class ObsidianSearchNotesTool(BaseTool):
    """Tool to search vault notes by keyword."""

    name = "obsidian_search_notes"
    description = "Searches your Obsidian vault for notes matching a search term or topic."
    risk_level = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search term, concept, or topic to search for in notes.",
            }
        },
        "required": ["query"],
    }

    def __init__(self, client: ObsidianClient | None = None) -> None:
        self.client = client or ObsidianClient()

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "").strip()
        if not query:
            return ToolResult(success=False, error="Query is required", message="What topic should I look for, bro?")

        try:
            results = await self.client.search_notes(query)
            if not results:
                return ToolResult(
                    success=True,
                    output=[],
                    message=f"I searched your vault for '{query}', but didn't find any matching notes, bro.",
                )

            # Summarize top 3 matches
            names = []
            for item in results[:3]:
                if isinstance(item, dict):
                    name = item.get("filename") or item.get("path") or str(item)
                else:
                    name = str(item)
                names.append(name.replace(".md", ""))

            summary = ", ".join(names)
            return ToolResult(
                success=True,
                output=results,
                message=f"Found {len(results)} notes matching '{query}', bro: {summary}.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to search Obsidian notes for '%s': %s", query, exc)
            return ToolResult(
                success=False,
                error=str(exc),
                message="Obsidian search ran into an error, bro.",
            )


class ObsidianCreateNoteTool(BaseTool):
    """Tool to create or overwrite a note in the vault."""

    name = "obsidian_create_note"
    description = "Creates a new note with given path and markdown content in your Obsidian vault."
    risk_level = RiskLevel.MODERATE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative file path for the new note (e.g. 'Ideas/NewApp.md').",
            },
            "content": {
                "type": "string",
                "description": "Markdown content for the note body.",
            },
        },
        "required": ["path", "content"],
    }

    def __init__(self, client: ObsidianClient | None = None) -> None:
        self.client = client or ObsidianClient()

    async def execute(self, **kwargs: Any) -> ToolResult:
        path = kwargs.get("path", "").strip()
        content = kwargs.get("content", "")
        if not path:
            return ToolResult(success=False, error="Path is required", message="What should I name the note, bro?")

        try:
            success = await self.client.create_or_update_note(path, content)
            if success:
                return ToolResult(
                    success=True,
                    output={"path": path},
                    message=f"Done bro, created '{path}' in your Obsidian vault.",
                )
            return ToolResult(
                success=False,
                error="Obsidian rejected create request",
                message="Obsidian didn't save the note, bro.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to create note '%s': %s", path, exc)
            return ToolResult(
                success=False,
                error=str(exc),
                message="Couldn't reach Obsidian to create the note, bro.",
            )

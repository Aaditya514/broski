"""Chrome Browser Assistant tools for broski.

Enables hands-free browser navigation, web search with Chrome profile support,
and web page content extraction for summarization and reading.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import urllib.parse
import webbrowser
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, ClassVar

import httpx

from broski.system.browsers import ChromeProfileManager
from broski.tools.base import BaseTool, RiskLevel, ToolResult

logger = logging.getLogger("broski.tools.browser")


class WebpageContentExtractor(HTMLParser):
    """Parses HTML into readable text, stripping styling, scripts, and navigation clutter."""

    _SKIP_TAGS: ClassVar[set[str]] = {
        "script",
        "style",
        "noscript",
        "header",
        "footer",
        "nav",
        "svg",
        "aside",
        "iframe",
    }

    def __init__(self) -> None:
        super().__init__()
        self._current_tag_stack: list[str] = []
        self._title_tokens: list[str] = []
        self._body_tokens: list[str] = []
        self._in_title = False

    @property
    def title(self) -> str:
        return " ".join(self._title_tokens).strip()

    @property
    def clean_text(self) -> str:
        raw = " ".join(self._body_tokens)
        # Collapse excessive whitespace while preserving flow
        collapsed = re.sub(r"\s+", " ", raw).strip()
        return collapsed

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        self._current_tag_stack.append(tag_lower)
        if tag_lower == "title":
            self._in_title = True
        elif tag_lower in ("p", "h1", "h2", "h3", "h4", "li", "br", "article", "section"):
            self._body_tokens.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if self._current_tag_stack and self._current_tag_stack[-1] == tag_lower:
            self._current_tag_stack.pop()
        if tag_lower == "title":
            self._in_title = False
        elif tag_lower in ("p", "h1", "h2", "h3", "h4", "li", "article", "section"):
            self._body_tokens.append("\n")

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return

        if self._in_title:
            self._title_tokens.append(text)
            return

        # Check if inside skipped tags
        if any(t in self._SKIP_TAGS for t in self._current_tag_stack):
            return

        self._body_tokens.append(text)


class BrowserNavigator:
    """Manages browser launching, profile selection, and content retrieval."""

    _COMMON_CHROME_PATHS: ClassVar[list[str]] = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ]

    def __init__(self, profile_manager: ChromeProfileManager | None = None) -> None:
        self.profile_manager = profile_manager or ChromeProfileManager()
        self._chrome_path: Path | None = None

    def find_chrome_executable(self) -> Path | None:
        """Locate Chrome binary on system."""
        if self._chrome_path and self._chrome_path.is_file():
            return self._chrome_path

        for path_str in self._COMMON_CHROME_PATHS:
            p = Path(path_str)
            if p.is_file():
                self._chrome_path = p
                return p

        # Fallback to PATH
        import shutil

        which_path = shutil.which("chrome")
        if which_path:
            self._chrome_path = Path(which_path)
            return self._chrome_path

        return None

    def normalize_url(self, url: str) -> str:
        """Ensure URL has scheme and is properly formatted."""
        cleaned = url.strip()
        if not cleaned.startswith(("http://", "https://")):
            cleaned = f"https://{cleaned}"
        return cleaned

    def open_url(self, url: str, profile_query: str | None = None) -> tuple[bool, str]:
        """Open a URL in Chrome with optional profile selection."""
        norm_url = self.normalize_url(url)
        chrome_exe = self.find_chrome_executable()

        if profile_query and chrome_exe:
            profile = self.profile_manager.find_profile(profile_query)
            if profile:
                profile_args = self.profile_manager.get_profile_args(profile)
                try:
                    subprocess.Popen(
                        [str(chrome_exe), *profile_args, norm_url],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return True, f"Opened {norm_url} on profile '{profile.name}'."
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Failed launching Chrome with profile: %s", exc)

        # Launch default Chrome if path found
        if chrome_exe:
            try:
                subprocess.Popen(
                    [str(chrome_exe), norm_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                return True, f"Opened {norm_url} in Chrome."
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed launching Chrome binary: %s", exc)

        # System default browser fallback
        success = webbrowser.open(norm_url)
        return success, f"Opened {norm_url} in default browser."

    def search(
        self,
        query: str,
        engine: str = "google",
        profile_query: str | None = None,
    ) -> tuple[bool, str]:
        """Perform search query via specified engine."""
        encoded = urllib.parse.quote_plus(query.strip())
        if engine.lower() == "duckduckgo":
            url = f"https://duckduckgo.com/?q={encoded}"
        elif engine.lower() == "bing":
            url = f"https://www.bing.com/search?q={encoded}"
        else:
            url = f"https://www.google.com/search?q={encoded}"

        success, _ = self.open_url(url, profile_query=profile_query)
        engine_name = engine.capitalize()
        return success, f"Searching {engine_name} for '{query}'."

    async def fetch_webpage_content(
        self,
        url: str,
        max_chars: int = 3500,
    ) -> dict[str, Any]:
        """Fetch and extract readable text from a URL."""
        norm_url = self.normalize_url(url)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            res = await client.get(norm_url, headers=headers)
            res.raise_for_status()
            html_text = res.text

        parser = WebpageContentExtractor()
        parser.feed(html_text)

        text = parser.clean_text
        if len(text) > max_chars:
            text = f"{text[:max_chars]}... [Content truncated for speech summary]"

        domain = urllib.parse.urlparse(norm_url).netloc
        return {
            "url": norm_url,
            "domain": domain,
            "title": parser.title or domain,
            "content": text,
            "char_count": len(text),
        }


# --- Typed Tool Implementations ---


class BrowserOpenUrlTool(BaseTool):
    """Tool to open any URL in Google Chrome."""

    name = "browser_open_url"
    description = (
        "Opens a URL in Google Chrome. Optionally accepts a Chrome profile name "
        "like 'Personal', 'College', 'Ghost' to switch directly into that account."
    )
    risk_level = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The web address or domain to open (e.g. 'github.com', 'https://youtube.com').",
            },
            "profile": {
                "type": "string",
                "description": "Optional Chrome profile alias or name (e.g. 'Personal', 'College').",
            },
        },
        "required": ["url"],
    }

    def __init__(self, navigator: BrowserNavigator | None = None) -> None:
        self.navigator = navigator or BrowserNavigator()

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url", "").strip()
        profile = kwargs.get("profile")
        if not url:
            return ToolResult(
                success=False,
                error="URL is required",
                message="Which website should I open, bro?",
            )

        success, detail = self.navigator.open_url(url, profile_query=profile)
        domain = urllib.parse.urlparse(self.navigator.normalize_url(url)).netloc or url
        if profile:
            msg = f"Opening {domain} on your {profile} Chrome profile, bro."
        else:
            msg = f"Opening {domain} in Chrome, bro."

        return ToolResult(
            success=success,
            output={"url": url, "detail": detail},
            message=msg,
        )


class BrowserSearchTool(BaseTool):
    """Tool to search Google/DuckDuckGo in Chrome."""

    name = "browser_search"
    description = "Searches Google or DuckDuckGo for a topic or question in Google Chrome."
    risk_level = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search keywords or question.",
            },
            "profile": {
                "type": "string",
                "description": "Optional Chrome profile to use.",
            },
            "engine": {
                "type": "string",
                "description": "Search engine: 'google', 'duckduckgo', or 'bing'. Defaults to 'google'.",
            },
        },
        "required": ["query"],
    }

    def __init__(self, navigator: BrowserNavigator | None = None) -> None:
        self.navigator = navigator or BrowserNavigator()

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "").strip()
        profile = kwargs.get("profile")
        engine = kwargs.get("engine", "google")
        if not query:
            return ToolResult(
                success=False,
                error="Query is required",
                message="What should I search for, bro?",
            )

        success, detail = self.navigator.search(query, engine=engine, profile_query=profile)
        engine_display = engine.capitalize()
        msg = f"Searching {engine_display} for '{query}', bro."
        return ToolResult(
            success=success,
            output={"query": query, "detail": detail},
            message=msg,
        )


class BrowserReadWebpageTool(BaseTool):
    """Tool to extract and read article content from a web page."""

    name = "browser_read_webpage"
    description = (
        "Fetches and extracts readable text and article content from a web URL, "
        "stripping scripts, styling, and navigation clutter for voice summarization."
    )
    risk_level = RiskLevel.SAFE
    parameters_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the webpage or article to extract.",
            },
            "max_chars": {
                "type": "integer",
                "description": "Maximum number of characters to extract (default: 3000).",
            },
        },
        "required": ["url"],
    }

    def __init__(self, navigator: BrowserNavigator | None = None) -> None:
        self.navigator = navigator or BrowserNavigator()

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url", "").strip()
        max_chars = int(kwargs.get("max_chars", 3000))
        if not url:
            return ToolResult(
                success=False,
                error="URL is required",
                message="Which page should I read, bro?",
            )

        try:
            data = await self.navigator.fetch_webpage_content(url, max_chars=max_chars)
            title = data.get("title") or "the webpage"
            chars = data.get("char_count", 0)
            return ToolResult(
                success=True,
                output=data,
                message=f"Pulled up '{title}' from {data.get('domain')}, bro. Extracted {chars} characters.",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed reading webpage '%s': %s", url, exc)
            return ToolResult(
                success=False,
                error=str(exc),
                message=f"Couldn't load that webpage, bro: {exc}",
            )

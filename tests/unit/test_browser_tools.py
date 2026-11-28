"""Unit tests for Chrome Browser Assistant tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from broski.system.browsers import ChromeProfile
from broski.tools.base import RiskLevel
from broski.tools.browser import (
    BrowserNavigator,
    BrowserOpenUrlTool,
    BrowserReadWebpageTool,
    BrowserSearchTool,
    WebpageContentExtractor,
)

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Quantum Computing Breakthrough</title>
    <style>body { font-family: sans-serif; }</style>
    <script>console.log("tracking");</script>
</head>
<body>
    <header><nav><a href="/">Home</a></nav></header>
    <article>
        <h1>Major Advance in Superconducting Qubits</h1>
        <p>Physicists have demonstrated continuous error suppression in planar silicon.</p>
        <p>This achievement paves the way for scalable fault-tolerant quantum algorithms.</p>
    </article>
    <footer><p>Copyright 2026 Tech Journal</p></footer>
</body>
</html>
"""


# --- WebpageContentExtractor Tests ---


def test_webpage_content_extractor() -> None:
    parser = WebpageContentExtractor()
    parser.feed(SAMPLE_HTML)

    assert parser.title == "Quantum Computing Breakthrough"
    text = parser.clean_text
    assert "Major Advance in Superconducting Qubits" in text
    assert "error suppression" in text
    # Verify scripts, styles, nav, and footers were stripped
    assert "tracking" not in text
    assert "font-family" not in text
    assert "Home" not in text
    assert "Copyright" not in text


# --- BrowserNavigator Tests ---


def test_browser_navigator_normalize_url() -> None:
    nav = BrowserNavigator()
    assert nav.normalize_url("github.com") == "https://github.com"
    assert nav.normalize_url("http://localhost:8080") == "http://localhost:8080"
    assert nav.normalize_url("https://python.org") == "https://python.org"


def test_browser_navigator_open_url_with_profile() -> None:
    mock_pm = MagicMock()
    mock_prof = ChromeProfile(
        directory="Profile 2",
        name="Personal",
        email="personal@gmail.com",
        aliases=["personal", "home"],
    )
    mock_pm.find_profile.return_value = mock_prof
    mock_pm.get_profile_args.return_value = ["--profile-directory=Profile 2"]

    nav = BrowserNavigator(profile_manager=mock_pm)

    with (
        patch.object(nav, "find_chrome_executable", return_value="C:\\chrome.exe"),
        patch("subprocess.Popen") as mock_popen,
    ):
        success, _ = nav.open_url("github.com", profile_query="Personal")
        assert success is True
        assert "Profile 2" in mock_pm.get_profile_args.call_args[0][0].directory
        mock_popen.assert_called_once()


def test_browser_navigator_search() -> None:
    nav = BrowserNavigator()
    with patch.object(nav, "open_url", return_value=(True, "ok")) as mock_open:
        success, _ = nav.search("fast whisper models", engine="duckduckgo")
        assert success is True
        called_url = mock_open.call_args[0][0]
        assert "duckduckgo.com/?q=fast+whisper+models" in called_url


@pytest.mark.asyncio
async def test_browser_navigator_fetch_webpage_content() -> None:
    nav = BrowserNavigator()

    mock_resp = MagicMock()
    mock_resp.text = SAMPLE_HTML
    mock_resp.raise_for_status = MagicMock()

    mock_http_client = AsyncMock()
    mock_http_client.get.return_value = mock_resp
    mock_http_client.__aenter__.return_value = mock_http_client
    mock_http_client.__aexit__.return_value = None

    with patch("httpx.AsyncClient", return_value=mock_http_client):
        data = await nav.fetch_webpage_content("https://example.com/quantum", max_chars=200)
        assert data["title"] == "Quantum Computing Breakthrough"
        assert "Superconducting Qubits" in data["content"]
        assert data["domain"] == "example.com"
        assert len(data["content"]) <= 300


# --- Typed Tools Tests ---


@pytest.mark.asyncio
async def test_tool_browser_open_url() -> None:
    mock_nav = MagicMock()
    mock_nav.normalize_url.return_value = "https://reddit.com"
    mock_nav.open_url.return_value = (True, "Opened https://reddit.com")

    tool = BrowserOpenUrlTool(navigator=mock_nav)
    assert tool.risk_level == RiskLevel.SAFE

    res = await tool.execute(url="reddit.com", profile="Personal")
    assert res.success is True
    assert "reddit.com" in res.message
    assert "Personal" in res.message


@pytest.mark.asyncio
async def test_tool_browser_open_url_missing() -> None:
    tool = BrowserOpenUrlTool()
    res = await tool.execute(url="")
    assert res.success is False
    assert "Which website" in res.message


@pytest.mark.asyncio
async def test_tool_browser_search() -> None:
    mock_nav = MagicMock()
    mock_nav.search.return_value = (True, "Searching Google")

    tool = BrowserSearchTool(navigator=mock_nav)
    assert tool.risk_level == RiskLevel.SAFE

    res = await tool.execute(query="Python 3.12 release notes")
    assert res.success is True
    assert "Python 3.12 release notes" in res.message
    assert "Google" in res.message


@pytest.mark.asyncio
async def test_tool_browser_search_missing() -> None:
    tool = BrowserSearchTool()
    res = await tool.execute(query="")
    assert res.success is False
    assert "What should I search for" in res.message


@pytest.mark.asyncio
async def test_tool_browser_read_webpage() -> None:
    mock_nav = AsyncMock()
    mock_nav.fetch_webpage_content.return_value = {
        "url": "https://news.ycombinator.com",
        "domain": "news.ycombinator.com",
        "title": "Hacker News",
        "content": "Article body about tech.",
        "char_count": 22,
    }

    tool = BrowserReadWebpageTool(navigator=mock_nav)
    assert tool.risk_level == RiskLevel.SAFE

    res = await tool.execute(url="https://news.ycombinator.com")
    assert res.success is True
    assert "Hacker News" in res.message
    assert "news.ycombinator.com" in res.message
    assert "22 characters" in res.message


@pytest.mark.asyncio
async def test_tool_browser_read_webpage_failure() -> None:
    mock_nav = AsyncMock()
    mock_nav.fetch_webpage_content.side_effect = RuntimeError("DNS resolution failed")

    tool = BrowserReadWebpageTool(navigator=mock_nav)
    res = await tool.execute(url="https://invalid.broken.domain")
    assert res.success is False
    assert "Couldn't load" in res.message

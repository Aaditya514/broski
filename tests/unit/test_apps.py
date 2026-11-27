"""Unit tests for Windows App Launcher and Security Whitelist."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from broski.system.apps import (
    WHITELIST_APPS,
    AppDefinition,
    AppLauncher,
)


def test_whitelist_apps_defined() -> None:
    """Ensure core desktop applications are defined in WHITELIST_APPS."""
    assert "obsidian" in WHITELIST_APPS
    assert "spotify" in WHITELIST_APPS
    assert "chrome" in WHITELIST_APPS
    assert "vscode" in WHITELIST_APPS
    assert "notepad" in WHITELIST_APPS
    assert "discord" in WHITELIST_APPS
    assert "terminal" in WHITELIST_APPS


def test_find_app_definition_by_id_and_alias() -> None:
    """Verify application resolution by canonical ID and alias variants."""
    launcher = AppLauncher()

    # Exact ID
    obs = launcher.find_app_definition("obsidian")
    assert obs is not None
    assert obs.id == "obsidian"

    # Alias
    spot = launcher.find_app_definition("music")
    assert spot is not None
    assert spot.id == "spotify"

    chrome = launcher.find_app_definition("google chrome")
    assert chrome is not None
    assert chrome.id == "chrome"

    code = launcher.find_app_definition("vs code")
    assert code is not None
    assert code.id == "vscode"

    # Case-insensitive
    note = launcher.find_app_definition("NoTePaD")
    assert note is not None
    assert note.id == "notepad"


def test_find_app_definition_unauthorized() -> None:
    """Verify unauthorized or arbitrary queries return None."""
    launcher = AppLauncher()

    assert launcher.find_app_definition("malware.exe") is None
    assert launcher.find_app_definition("format c:") is None
    assert launcher.find_app_definition("random_app_xyz") is None
    assert launcher.find_app_definition("") is None


def test_is_whitelisted() -> None:
    """Verify is_whitelisted helper method."""
    launcher = AppLauncher()
    assert launcher.is_whitelisted("obsidian") is True
    assert launcher.is_whitelisted("spotify") is True
    assert launcher.is_whitelisted("chrome") is True
    assert launcher.is_whitelisted("hacker_tool") is False


def test_resolve_with_mocked_filesystem() -> None:
    """Verify candidate path checking and environment variable expansion."""
    custom_whitelist = {
        "testapp": AppDefinition(
            id="testapp",
            name="Test App",
            aliases=["test"],
            executable_name="testapp.exe",
            common_paths=[r"C:\NonExistent\testapp.exe", r"C:\Valid\testapp.exe"],
        )
    }
    launcher = AppLauncher(whitelist=custom_whitelist)

    def fake_is_file(path_obj: Path) -> bool:
        return str(path_obj) == r"C:\Valid\testapp.exe"

    with patch.object(Path, "is_file", autospec=True, side_effect=fake_is_file):
        target = launcher.resolve("testapp")
        assert target is not None
        assert target.app_id == "testapp"
        assert str(target.resolved_path) == r"C:\Valid\testapp.exe"


def test_resolve_fallback_to_protocol_uri() -> None:
    """Verify fallback to protocol URI when no local executable is found."""
    custom_whitelist = {
        "spot": AppDefinition(
            id="spot",
            name="Spotify",
            aliases=["music"],
            executable_name="Spotify.exe",
            common_paths=[r"C:\Fake\Spotify.exe"],
            protocol_uri="spotify:",
        )
    }
    launcher = AppLauncher(whitelist=custom_whitelist)

    with patch.object(Path, "is_file", return_value=False), patch(
        "shutil.which", return_value=None
    ):
        target = launcher.resolve("spot")
        assert target is not None
        assert target.resolved_path is None
        assert target.uri == "spotify:"


def test_launch_whitelisted_executable_mocked() -> None:
    """Verify safe subprocess execution with shell=False."""
    launcher = AppLauncher()
    mock_target = MagicMock()
    mock_target.resolved_path = Path(r"C:\Program Files\App\app.exe")
    mock_target.args = ["--quiet"]
    mock_target.display_name = "Test App"
    mock_target.uri = None

    mock_proc = MagicMock()
    mock_proc.pid = 4321

    with (
        patch.object(launcher, "find_app_definition", return_value=MagicMock(name="Test App")),
        patch.object(launcher, "resolve", return_value=mock_target),
        patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
    ):
        result = launcher.launch("testapp")
        assert result.success is True
        assert result.pid == 4321
        assert "Opening Test App" in result.message
        mock_popen.assert_called_once_with(
            [str(mock_target.resolved_path), "--quiet"],
            shell=False,
            close_fds=True,
        )


def test_launch_unauthorized_app_blocked() -> None:
    """Verify unauthorized application is rejected without invoking subprocess."""
    launcher = AppLauncher()

    with patch("subprocess.Popen") as mock_popen:
        result = launcher.launch("unknown_malicious_script.bat")
        assert result.success is False
        assert "in my authorized applications list" in result.message
        mock_popen.assert_not_called()


def test_launch_uri_protocol() -> None:
    """Verify launching an app via protocol URI."""
    launcher = AppLauncher()
    mock_target = MagicMock()
    mock_target.resolved_path = None
    mock_target.uri = "spotify:"
    mock_target.display_name = "Spotify"

    with (
        patch.object(launcher, "find_app_definition", return_value=MagicMock(name="Spotify")),
        patch.object(launcher, "resolve", return_value=mock_target),
        patch("os.startfile", create=True) as mock_startfile,
    ):
        result = launcher.launch("spotify")
        assert result.success is True
        assert "Opening Spotify" in result.message
        mock_startfile.assert_called_once_with("spotify:")

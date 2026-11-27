"""Application Whitelist and Windows Application Launcher for broski.

Provides safe, whitelist-gated application resolution and execution.
Ensures broski never launches arbitrary, unverified binaries from voice input.
"""

import glob
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from pydantic import BaseModel, Field

try:
    import winreg
except ImportError:
    winreg = None  # type: ignore[assignment]

logger = logging.getLogger("broski.system.apps")


class AppDefinition(BaseModel):
    """Specification of an authorized desktop application."""

    id: str
    name: str
    aliases: list[str] = Field(default_factory=list)
    executable_name: str
    common_paths: list[str] = Field(default_factory=list)
    registry_names: list[str] = Field(default_factory=list)
    protocol_uri: str | None = None
    default_args: list[str] = Field(default_factory=list)


class AppLaunchTarget(BaseModel):
    """A resolved application ready for execution."""

    app_id: str
    display_name: str
    resolved_path: Path | None = None
    uri: str | None = None
    args: list[str] = Field(default_factory=list)


class LaunchResult(BaseModel):
    """Result of attempting to launch an application."""

    success: bool
    app_name: str
    message: str
    target_path: str | None = None
    pid: int | None = None


# Whitelist of explicitly authorized applications
WHITELIST_APPS: dict[str, AppDefinition] = {
    "obsidian": AppDefinition(
        id="obsidian",
        name="Obsidian",
        aliases=["obsidian", "notes", "my notes", "vault", "obsidian notes"],
        executable_name="Obsidian.exe",
        common_paths=[
            r"%LOCALAPPDATA%\Programs\Obsidian\Obsidian.exe",
            r"%PROGRAMFILES%\Obsidian\Obsidian.exe",
        ],
        registry_names=["Obsidian.exe"],
        protocol_uri="obsidian://open",
    ),
    "spotify": AppDefinition(
        id="spotify",
        name="Spotify",
        aliases=["spotify", "music", "songs", "spotify player"],
        executable_name="Spotify.exe",
        common_paths=[
            r"%APPDATA%\Spotify\Spotify.exe",
            r"%LOCALAPPDATA%\Microsoft\WindowsApps\Spotify.exe",
        ],
        registry_names=["Spotify.exe"],
        protocol_uri="spotify:",
    ),
    "chrome": AppDefinition(
        id="chrome",
        name="Google Chrome",
        aliases=["chrome", "google chrome", "browser", "internet", "web browser"],
        executable_name="chrome.exe",
        common_paths=[
            r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe",
            r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe",
            r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
        ],
        registry_names=["chrome.exe"],
    ),
    "vscode": AppDefinition(
        id="vscode",
        name="Visual Studio Code",
        aliases=["vscode", "vs code", "code", "visual studio code", "editor"],
        executable_name="Code.exe",
        common_paths=[
            r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
            r"%PROGRAMFILES%\Microsoft VS Code\Code.exe",
            r"%PROGRAMFILES(X86)%\Microsoft VS Code\Code.exe",
        ],
        registry_names=["Code.exe"],
    ),
    "notepad": AppDefinition(
        id="notepad",
        name="Notepad",
        aliases=["notepad", "text editor", "notes editor"],
        executable_name="notepad.exe",
        common_paths=[
            r"%SYSTEMROOT%\System32\notepad.exe",
            r"%SYSTEMROOT%\notepad.exe",
        ],
        registry_names=["notepad.exe"],
    ),
    "discord": AppDefinition(
        id="discord",
        name="Discord",
        aliases=["discord", "chat", "voice chat"],
        executable_name="Discord.exe",
        common_paths=[
            r"%LOCALAPPDATA%\Discord\app-*\Discord.exe",
            r"%LOCALAPPDATA%\Discord\Update.exe",
        ],
        registry_names=["Discord.exe"],
        protocol_uri="discord://",
    ),
    "terminal": AppDefinition(
        id="terminal",
        name="Windows Terminal",
        aliases=["terminal", "windows terminal", "powershell", "cmd", "command prompt", "console"],
        executable_name="wt.exe",
        common_paths=[
            r"%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe",
            r"%SYSTEMROOT%\System32\cmd.exe",
        ],
        registry_names=["wt.exe", "cmd.exe"],
    ),
}


class AppLauncher:
    """Safely resolves and launches applications strictly adhering to the whitelist."""

    def __init__(self, whitelist: dict[str, AppDefinition] | None = None) -> None:
        self.whitelist: dict[str, AppDefinition] = whitelist or WHITELIST_APPS

    def is_whitelisted(self, query: str) -> bool:
        """Check whether a query or alias matches an authorized application."""
        return self.find_app_definition(query) is not None

    def find_app_definition(self, query: str) -> AppDefinition | None:
        """Find matching AppDefinition by canonical ID or alias."""
        normalized = query.strip().lower()
        if not normalized:
            return None

        # 1. Exact match on ID
        if normalized in self.whitelist:
            return self.whitelist[normalized]

        # 2. Check aliases across all whitelisted apps
        for app in self.whitelist.values():
            if normalized == app.name.lower():
                return app
            if normalized in [a.lower() for a in app.aliases]:
                return app

        # 3. Substring/contains match on aliases or app name
        for app in self.whitelist.values():
            if normalized in app.name.lower():
                return app
            for alias in app.aliases:
                if normalized in alias or alias in normalized:
                    return app

        return None

    def resolve(self, query: str) -> AppLaunchTarget | None:
        """Resolve a query into an executable AppLaunchTarget on the current system.

        Searches common directory paths, Windows Registry App Paths, and PATH.
        If an executable binary is not found on disk, but a protocol URI exists,
        falls back to URI-based launch.
        """
        app_def = self.find_app_definition(query)
        if app_def is None:
            logger.warning("Application '%s' is not in the authorized whitelist.", query)
            return None

        resolved_path: Path | None = None

        # 1. Check common file paths with environment variable expansion
        for path_pattern in app_def.common_paths:
            expanded = os.path.expandvars(path_pattern)
            # Handle wildcards (e.g. Discord app-*)
            if "*" in expanded:
                matches = glob.glob(expanded)
                if matches:
                    candidate = Path(matches[-1])
                    if candidate.is_file():
                        resolved_path = candidate
                        break
            else:
                candidate = Path(expanded)
                if candidate.is_file():
                    resolved_path = candidate
                    break

        # 2. Check Windows Registry App Paths
        if resolved_path is None and winreg is not None:
            for reg_name in (app_def.registry_names or [app_def.executable_name]):
                reg_path = self._query_registry_app_paths(reg_name)
                if reg_path and Path(reg_path).is_file():
                    resolved_path = Path(reg_path)
                    break

        # 3. Check system PATH via shutil.which
        if resolved_path is None:
            which_path = shutil.which(app_def.executable_name)
            if which_path and Path(which_path).is_file():
                resolved_path = Path(which_path)

        # 4. If an executable binary was found
        if resolved_path is not None:
            return AppLaunchTarget(
                app_id=app_def.id,
                display_name=app_def.name,
                resolved_path=resolved_path,
                args=list(app_def.default_args),
            )

        # 5. Fallback to protocol URI if configured (e.g. spotify:, obsidian://)
        if app_def.protocol_uri:
            return AppLaunchTarget(
                app_id=app_def.id,
                display_name=app_def.name,
                uri=app_def.protocol_uri,
            )

        return None

    def launch(self, query: str) -> LaunchResult:
        """Resolve and execute an authorized application non-blockingly."""
        app_def = self.find_app_definition(query)
        if app_def is None:
            return LaunchResult(
                success=False,
                app_name=query,
                message=f"I couldn't find '{query}' in my authorized applications list.",
            )

        target = self.resolve(query)
        if target is None:
            return LaunchResult(
                success=False,
                app_name=app_def.name,
                message=f"I recognized {app_def.name}, but couldn't locate it installed on your computer.",
            )

        # 1. Executable file launch
        if target.resolved_path is not None:
            try:
                cmd = [str(target.resolved_path)] + target.args
                # Launch non-blocking process without shell=True
                proc = subprocess.Popen(
                    cmd,
                    shell=False,
                    close_fds=True,
                )
                logger.info(
                    "Launched '%s' (PID: %d) from '%s'",
                    target.display_name,
                    proc.pid,
                    target.resolved_path,
                )
                return LaunchResult(
                    success=True,
                    app_name=target.display_name,
                    message=f"Opening {target.display_name}.",
                    target_path=str(target.resolved_path),
                    pid=proc.pid,
                )
            except (OSError, PermissionError) as exc:
                logger.error("Failed to launch '%s': %s", target.resolved_path, exc)
                return LaunchResult(
                    success=False,
                    app_name=target.display_name,
                    message=f"Failed to start {target.display_name}: {exc}",
                    target_path=str(target.resolved_path),
                )

        # 2. URI Protocol launch (Windows ShellExecute)
        if target.uri is not None:
            try:
                if sys.platform == "win32" and hasattr(os, "startfile"):
                    os.startfile(target.uri)  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", target.uri])
                return LaunchResult(
                    success=True,
                    app_name=target.display_name,
                    message=f"Opening {target.display_name}.",
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("Failed to open URI '%s': %s", target.uri, exc)
                return LaunchResult(
                    success=False,
                    app_name=target.display_name,
                    message=f"Failed to open {target.display_name} protocol: {exc}",
                )

        return LaunchResult(
            success=False,
            app_name=app_def.name,
            message=f"No executable or protocol available for {app_def.name}.",
        )

    def _query_registry_app_paths(self, exe_name: str) -> str | None:
        """Query Windows Registry App Paths for registered executable paths."""
        if winreg is None:
            return None

        key_rel = f"Software\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{exe_name}"
        for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            try:
                with winreg.OpenKey(root, key_rel) as key:
                    val, _ = winreg.QueryValueEx(key, "")
                    if val:
                        clean_val = str(val).strip().strip('"')
                        if clean_val:
                            return clean_val
            except OSError:
                continue
        return None

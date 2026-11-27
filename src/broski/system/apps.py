"""Application Whitelist and Windows Application Launcher for broski.

Provides safe, whitelist-gated application resolution and execution.
Ensures broski never launches arbitrary, unverified binaries from voice input.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import glob
import inspect
import logging
import os
import shutil
import subprocess
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from broski.system.browsers import ChromeProfileManager

if TYPE_CHECKING:
    from broski.memory.store import MemoryStore

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

    def __init__(
        self,
        whitelist: dict[str, AppDefinition] | None = None,
        store: MemoryStore | None = None,
        chrome_manager: ChromeProfileManager | None = None,
    ) -> None:
        self.whitelist: dict[str, AppDefinition] = whitelist or WHITELIST_APPS
        self.store = store
        self.chrome_manager = chrome_manager or ChromeProfileManager()

    def _run_async(self, coro: Coroutine[Any, Any, Any] | Any) -> Any:
        """Execute an asynchronous coroutine safely from synchronous contexts."""
        if not inspect.iscoroutine(coro):
            return coro

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
        return asyncio.run(coro)

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

        # 4. Check if query refers to a specific Chrome profile (e.g. "college chrome", "ghost chrome")
        if self.chrome_manager is not None:
            matched_profile = self.chrome_manager.find_profile(normalized)
            if matched_profile is not None:
                return self.whitelist.get("chrome")

        return None

    def resolve(self, query: str) -> AppLaunchTarget | None:
        """Resolve a query into an executable AppLaunchTarget on the current system.

        Searches custom SQLite app catalog first, then common directory paths,
        Windows Registry App Paths, and system PATH.
        If an executable binary is not found on disk, but a protocol URI exists,
        falls back to URI-based launch.
        """
        app_def = self.find_app_definition(query)
        if app_def is None:
            logger.warning("Application '%s' is not in the authorized whitelist.", query)
            return None

        resolved_path: Path | None = None

        # 0. Check custom SQLite app catalog first (user-configured paths have priority)
        if self.store is not None:
            try:
                db_app = self._run_async(self.store.find_app(query))
                if db_app and db_app.path:
                    db_candidate = Path(os.path.expandvars(db_app.path))
                    if db_candidate.is_file():
                        resolved_path = db_candidate
            except Exception as exc:  # noqa: BLE001
                logger.debug("Failed to query memory store for '%s': %s", query, exc)

        # 1. Check common file paths with environment variable expansion
        if resolved_path is None:
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
            launch_args = list(app_def.default_args)
            display_name = app_def.name

            # Special handling for Chrome profiles: launch directly into user account
            if app_def.id == "chrome" and self.chrome_manager is not None:
                matched_profile = self.chrome_manager.find_profile(query)
                if matched_profile is not None:
                    launch_args = self.chrome_manager.get_profile_args(matched_profile)
                    display_name = f"Google Chrome ({matched_profile.name})"
                else:
                    # Default to primary profile if none explicitly requested
                    default_prof = self.chrome_manager.find_profile("default") or self.chrome_manager.find_profile("college")
                    if default_prof is not None:
                        launch_args = self.chrome_manager.get_profile_args(default_prof)

            return AppLaunchTarget(
                app_id=app_def.id,
                display_name=display_name,
                resolved_path=resolved_path,
                args=launch_args,
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
                if self.store is not None:
                    try:
                        self._run_async(self.store.record_app_launch(app_def.name))
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("Failed to record launch in memory store: %s", exc)

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

    def register_custom_path(
        self,
        app_name_or_id: str,
        exe_path: str | Path,
        aliases: list[str] | None = None,
    ) -> LaunchResult:
        """Register or update a custom executable path for an authorized application in SQLite."""
        app_def = self.find_app_definition(app_name_or_id)
        if app_def is None:
            return LaunchResult(
                success=False,
                app_name=app_name_or_id,
                message=f"'{app_name_or_id}' is not in the authorized applications whitelist.",
            )

        if self.store is None:
            return LaunchResult(
                success=False,
                app_name=app_def.name,
                message="Memory store is not initialized; cannot save custom application path.",
            )

        clean_path_str = str(exe_path).strip().strip('"\'')
        expanded = os.path.expandvars(clean_path_str)
        target_file = Path(expanded)

        if not target_file.is_file():
            return LaunchResult(
                success=False,
                app_name=app_def.name,
                message=f"Cannot register path: file '{expanded}' does not exist on disk.",
                target_path=expanded,
            )

        try:
            combined_aliases = list(set(app_def.aliases + (aliases or [])))
            self._run_async(
                self.store.register_app(
                    name=app_def.name,
                    path=str(target_file.resolve()),
                    aliases=combined_aliases,
                )
            )
            logger.info("Registered custom path for '%s': '%s'", app_def.name, target_file)
            return LaunchResult(
                success=True,
                app_name=app_def.name,
                message=f"Saved custom location for {app_def.name} at {target_file}.",
                target_path=str(target_file.resolve()),
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to register app '%s': %s", app_def.name, exc)
            return LaunchResult(
                success=False,
                app_name=app_def.name,
                message=f"Failed to save custom location in database: {exc}",
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

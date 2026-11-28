"""System operations and application management for broski."""

from broski.system.apps import (
    WHITELIST_APPS,
    AppDefinition,
    AppLauncher,
    AppLaunchTarget,
    LaunchResult,
)
from broski.system.browsers import (
    ChromeProfile,
    ChromeProfileManager,
)
from broski.system.injector import (
    ActiveWindowInjector,
    InjectionMode,
    InjectionResult,
    WindowInfo,
)

__all__ = [
    "WHITELIST_APPS",
    "ActiveWindowInjector",
    "AppDefinition",
    "AppLaunchTarget",
    "AppLauncher",
    "ChromeProfile",
    "ChromeProfileManager",
    "InjectionMode",
    "InjectionResult",
    "LaunchResult",
    "WindowInfo",
]

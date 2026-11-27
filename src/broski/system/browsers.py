"""Google Chrome profile discovery and management for voice-directed profile switching.

Allows broski to inspect installed Chrome profiles and launch specific accounts
directly (e.g. 'open College Chrome', 'open Personal Chrome', 'open Ghost Chrome')
bypassing the Chrome Profile Picker.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger("broski.system.browsers")


class ChromeProfile(BaseModel):
    """Data model representing a discovered Google Chrome profile."""

    directory: str = Field(description="Internal directory name, e.g. 'Default', 'Profile 17'.")
    name: str = Field(description="User-facing profile display name.")
    email: str = Field(default="", description="Google account email address if signed in.")
    aliases: list[str] = Field(default_factory=list, description="Voice trigger aliases.")


class ChromeProfileManager:
    """Discovers and resolves Google Chrome profiles on Windows."""

    def __init__(self, user_data_dir: Path | str | None = None) -> None:
        if user_data_dir is not None:
            self.user_data_dir = Path(user_data_dir)
        else:
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            if local_app_data:
                self.user_data_dir = (
                    Path(local_app_data) / "Google" / "Chrome" / "User Data"
                )
            else:
                self.user_data_dir = Path()

        self._cached_profiles: list[ChromeProfile] | None = None

    def discover_profiles(self, force_refresh: bool = False) -> list[ChromeProfile]:
        """Parse Local State JSON and extract all configured Chrome user profiles."""
        if self._cached_profiles is not None and not force_refresh:
            return self._cached_profiles

        local_state_file = self.user_data_dir / "Local State"
        if not local_state_file.is_file():
            logger.debug("Chrome Local State file not found at: %s", local_state_file)
            self._cached_profiles = []
            return []

        try:
            with open(local_state_file, encoding="utf-8") as f:
                data = json.load(f)

            info_cache = data.get("profile", {}).get("info_cache", {})
            profiles: list[ChromeProfile] = []

            for dir_name, info in info_cache.items():
                name = str(info.get("name", "")).strip()
                email = str(info.get("user_name", "")).strip()
                domain = str(info.get("hosted_domain", "")).strip().lower()

                aliases: set[str] = set()

                # Basic name aliases
                if name:
                    aliases.add(name.lower())
                    aliases.add(name.lower().replace("-", " "))
                    aliases.add(f"{name.lower()} chrome")

                # Email username alias
                if email and "@" in email:
                    user_part = email.split("@")[0].lower()
                    aliases.add(user_part)
                    aliases.add(f"{user_part} chrome")

                # Educational / Domain aliases
                if domain == "kiit.ac.in" or "kiit" in email.lower():
                    aliases.update([
                        "college",
                        "kiit",
                        "university",
                        "student",
                        "college chrome",
                        "kiit chrome",
                        "college account",
                    ])

                # Common personal account hints
                if "2004" in email or "personal" in name.lower():
                    aliases.update([
                        "personal",
                        "main",
                        "personal chrome",
                        "main chrome",
                        "personal account",
                    ])

                # Nicknames & Specific personas
                if "ghost" in name.lower() or "ghost" in email.lower():
                    aliases.update(["ghost", "ghost rider", "ghost chrome"])

                if "jaya" in name.lower() or "jaya" in email.lower():
                    aliases.update(["jaya", "jaya chrome"])

                if "nandinee" in name.lower() or "nandinee" in email.lower():
                    aliases.update(["nandinee", "nandinee chrome"])

                if "blah" in name.lower() or "blah" in email.lower():
                    aliases.update(["blah blah", "blah-blah", "blah chrome"])

                profiles.append(
                    ChromeProfile(
                        directory=dir_name,
                        name=name or dir_name,
                        email=email,
                        aliases=sorted(aliases),
                    )
                )

            self._cached_profiles = profiles
            logger.info("Discovered %d Chrome profiles on system.", len(profiles))
            return profiles
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse Chrome Local State: %s", exc)
            self._cached_profiles = []
            return []

    def find_profile(self, query: str) -> ChromeProfile | None:
        """Find matching Chrome profile based on query keywords or aliases."""
        clean_query = query.strip().lower().replace("-", " ")
        if not clean_query:
            return None

        # Clean off common noise words
        for noise in ("open ", "launch ", "start ", " chrome", " profile", " account", "on ", "my "):
            clean_query = clean_query.replace(noise, " ")
        clean_query = clean_query.strip()
        if not clean_query:
            return None

        profiles = self.discover_profiles()

        # 1. Exact alias match
        for prof in profiles:
            for alias in prof.aliases:
                clean_alias = alias.replace("-", " ")
                if clean_query == clean_alias:
                    return prof

        # 2. Substring match
        for prof in profiles:
            for alias in prof.aliases:
                clean_alias = alias.replace("-", " ")
                if clean_query in clean_alias or clean_alias in clean_query:
                    return prof

        return None

    def get_profile_args(self, profile_or_dir: ChromeProfile | str) -> list[str]:
        """Build command-line flags to launch Chrome directly into a specific profile."""
        dir_name = (
            profile_or_dir.directory
            if isinstance(profile_or_dir, ChromeProfile)
            else str(profile_or_dir)
        )
        return [f"--profile-directory={dir_name}"]

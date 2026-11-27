"""Unit tests for Google Chrome profile discovery and voice profile switching."""

import json
from pathlib import Path
from unittest.mock import patch

from broski.system.apps import AppLauncher
from broski.system.browsers import ChromeProfileManager


def test_discover_profiles_mocked(tmp_path: Path) -> None:
    """Verify parsing Chrome profiles from Local State JSON."""
    fake_local_state = tmp_path / "Local State"
    fake_data = {
        "profile": {
            "info_cache": {
                "Default": {
                    "name": "College Account",
                    "user_name": "student@kiit.ac.in",
                    "hosted_domain": "kiit.ac.in",
                },
                "Profile 1": {
                    "name": "Personal",
                    "user_name": "personal2004@gmail.com",
                    "hosted_domain": "NO_HOSTED_DOMAIN",
                },
                "Profile 2": {
                    "name": "Ghost",
                    "user_name": "ghostrider@gmail.com",
                    "hosted_domain": "NO_HOSTED_DOMAIN",
                },
            }
        }
    }
    fake_local_state.write_text(json.dumps(fake_data), encoding="utf-8")

    mgr = ChromeProfileManager(user_data_dir=tmp_path)
    profiles = mgr.discover_profiles()

    assert len(profiles) == 3

    # Check Default (College)
    default_prof = next(p for p in profiles if p.directory == "Default")
    assert default_prof.name == "College Account"
    assert "college" in default_prof.aliases
    assert "kiit" in default_prof.aliases

    # Check Profile 1 (Personal)
    p1 = next(p for p in profiles if p.directory == "Profile 1")
    assert "personal" in p1.aliases

    # Check Profile 2 (Ghost)
    p2 = next(p for p in profiles if p.directory == "Profile 2")
    assert "ghost" in p2.aliases


def test_discover_profiles_missing_file(tmp_path: Path) -> None:
    """Verify missing Local State file returns empty list gracefully."""
    mgr = ChromeProfileManager(user_data_dir=tmp_path / "NonExistent")
    profiles = mgr.discover_profiles()
    assert profiles == []


def test_find_profile(tmp_path: Path) -> None:
    """Verify alias and query matching for Chrome profiles."""
    fake_local_state = tmp_path / "Local State"
    fake_data = {
        "profile": {
            "info_cache": {
                "Default": {
                    "name": "College",
                    "user_name": "aaditya@kiit.ac.in",
                    "hosted_domain": "kiit.ac.in",
                },
                "Profile 5": {
                    "name": "Ghost",
                    "user_name": "ghost@gmail.com",
                },
            }
        }
    }
    fake_local_state.write_text(json.dumps(fake_data), encoding="utf-8")

    mgr = ChromeProfileManager(user_data_dir=tmp_path)

    prof1 = mgr.find_profile("college chrome")
    assert prof1 is not None
    assert prof1.directory == "Default"

    prof2 = mgr.find_profile("ghost")
    assert prof2 is not None
    assert prof2.directory == "Profile 5"

    assert mgr.find_profile("non_existent_profile") is None


def test_get_profile_args() -> None:
    """Verify generated command-line flags for Chrome."""
    mgr = ChromeProfileManager()
    args = mgr.get_profile_args("Profile 17")
    assert args == ["--profile-directory=Profile 17"]


def test_app_launcher_resolves_chrome_profile(tmp_path: Path) -> None:
    """Verify AppLauncher attaches profile-directory argument for matched profiles."""
    fake_local_state = tmp_path / "Local State"
    fake_data = {
        "profile": {
            "info_cache": {
                "Default": {
                    "name": "KIIT",
                    "user_name": "test@kiit.ac.in",
                    "hosted_domain": "kiit.ac.in",
                },
                "Profile 4": {
                    "name": "Ghost",
                    "user_name": "ghost@gmail.com",
                },
            }
        }
    }
    fake_local_state.write_text(json.dumps(fake_data), encoding="utf-8")

    mgr = ChromeProfileManager(user_data_dir=tmp_path)
    launcher = AppLauncher(chrome_manager=mgr)

    fake_chrome_exe = tmp_path / "chrome.exe"
    fake_chrome_exe.touch()

    with patch("shutil.which", return_value=str(fake_chrome_exe)):
        # College Chrome
        target1 = launcher.resolve("college chrome")
        assert target1 is not None
        assert "--profile-directory=Default" in target1.args
        assert "KIIT" in target1.display_name

        # Ghost Chrome
        target2 = launcher.resolve("ghost chrome")
        assert target2 is not None
        assert "--profile-directory=Profile 4" in target2.args
        assert "Ghost" in target2.display_name

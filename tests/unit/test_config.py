"""Unit tests for broski configuration management."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from broski.config import (
    AudioConfig,
    ObsidianConfig,
    PathsConfig,
    Settings,
    get_settings,
)


def test_default_settings(tmp_path: Path) -> None:
    """Verify default settings values match architectural specifications."""
    settings = Settings(data_dir=tmp_path / "data")

    # Audio defaults
    assert settings.audio.sample_rate == 16000
    assert settings.audio.channels == 1
    assert settings.audio.wake_word_model == "hey_jarvis"
    assert settings.audio.whisper_model_size == "base.en"
    assert settings.audio.whisper_compute_type == "int8"
    assert settings.audio.whisper_cpu_threads == 2

    # Brain defaults
    assert settings.brain.model == "gemini-2.5-flash"
    assert settings.brain.api_key is None

    # Security defaults
    assert settings.security.require_confirmation_for_critical is True
    assert settings.security.confirmation_timeout_seconds == 30
    assert settings.security.log_level == "INFO"

    # Obsidian defaults
    assert settings.obsidian.port == 27124
    assert settings.obsidian.use_https is True
    assert settings.obsidian.base_url == "https://127.0.0.1:27124"


def test_secret_str_masking() -> None:
    """Verify API keys are masked by SecretStr and cannot leak in string representations."""
    settings = Settings(gemini_api_key="secret-gemini-test-key-12345")

    # Accessing via brain config
    assert settings.brain.api_key is not None
    assert str(settings.brain.api_key) == "**********"
    assert "secret-gemini-test-key-12345" not in repr(settings.brain.api_key)
    assert settings.brain.api_key.get_secret_value() == "secret-gemini-test-key-12345"


def test_environment_variable_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Verify environment variables correctly override configuration defaults."""
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.0-flash-exp")
    monkeypatch.setenv("AUDIO_SAMPLE_RATE", "48000")
    monkeypatch.setenv("WHISPER_CPU_THREADS", "4")
    monkeypatch.setenv("OBSIDIAN_PORT", "8443")
    monkeypatch.setenv("OBSIDIAN_USE_HTTPS", "false")
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "custom_data"))

    settings = Settings()

    assert settings.brain.model == "gemini-2.0-flash-exp"
    assert settings.audio.sample_rate == 48000
    assert settings.audio.whisper_cpu_threads == 4
    assert settings.obsidian.port == 8443
    assert settings.obsidian.use_https is False
    assert settings.obsidian.base_url == "http://127.0.0.1:8443"
    assert settings.paths.data_dir == tmp_path / "custom_data"


def test_invalid_sample_rate_validation() -> None:
    """Verify unsupported audio sample rates trigger a validation error."""
    with pytest.raises(ValidationError) as exc_info:
        AudioConfig(sample_rate=12345)
    assert "Sample rate 12345 is unsupported" in str(exc_info.value)


def test_invalid_port_validation() -> None:
    """Verify out-of-range port numbers trigger validation errors."""
    with pytest.raises(ValidationError):
        ObsidianConfig(port=99999)

    with pytest.raises(ValidationError):
        ObsidianConfig(port=0)


def test_paths_ensure_directories(tmp_path: Path) -> None:
    """Verify ensure_directories creates data and models folders."""
    custom_data = tmp_path / "broski_data"
    paths = PathsConfig(data_dir=custom_data)

    assert not custom_data.exists()
    assert not paths.models_dir.exists()

    paths.ensure_directories()

    assert custom_data.is_dir()
    assert paths.models_dir.is_dir()
    assert paths.db_path == custom_data / "broski.db"


def test_get_settings_cached_singleton() -> None:
    """Verify get_settings returns the same cached instance on repeated calls."""
    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2

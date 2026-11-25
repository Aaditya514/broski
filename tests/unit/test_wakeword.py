"""Unit tests for broski WakeWordDetector."""

from unittest.mock import MagicMock

import numpy as np

from broski.audio.wakeword import WakeWordDetector


def test_wakeword_initialization() -> None:
    """Verify WakeWordDetector initializes model and parameters."""
    ww = WakeWordDetector(model_name="hey_jarvis", threshold=0.5)
    assert ww.threshold == 0.5
    assert ww.cooldown_seconds == 1.5
    assert ww.chunk_size == 1280


def test_wakeword_silence_prediction() -> None:
    """Verify silence produces very low confidence and does not trigger wake event."""
    ww = WakeWordDetector(model_name="hey_jarvis", threshold=0.5)
    silence = np.zeros(1280, dtype=np.int16)

    score, triggered = ww.predict(silence)
    assert 0.0 <= score < 0.2
    assert triggered is False


def test_wakeword_trigger_and_cooldown() -> None:
    """Verify mock prediction above threshold triggers wake event and respects cooldown."""
    ww = WakeWordDetector(threshold=0.6, cooldown_seconds=2.0)
    # Force initialize model
    ww._init_model()

    mock_model = MagicMock()
    mock_model.predict.return_value = {ww._target_key: 0.85}
    mock_model.reset = MagicMock()
    ww._model = mock_model

    fake_chunk = np.ones(1280, dtype=np.int16)

    # 1. First time above threshold: should trigger
    score, triggered = ww.predict(fake_chunk)
    assert score == 0.85
    assert triggered is True

    # 2. Immediately subsequent chunk above threshold: should NOT trigger due to cooldown
    score, triggered = ww.predict(fake_chunk)
    assert score == 0.85
    assert triggered is False


def test_wakeword_reset() -> None:
    """Verify reset clears last trigger timestamp and model buffer."""
    ww = WakeWordDetector()
    ww._last_trigger_time = 12345.67
    mock_model = MagicMock()
    ww._model = mock_model

    ww.reset()
    assert ww._last_trigger_time == 0.0
    mock_model.reset.assert_called_once()

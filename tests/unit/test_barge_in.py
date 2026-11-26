"""Unit tests for broski BargeInDetector and full-duplex conversational interruption."""

import time
from unittest.mock import MagicMock

import numpy as np

from broski.audio.barge_in import BargeInDetector, BargeInMode
from broski.audio.pipeline import AudioPipelineCoordinator, PipelineState


def test_barge_in_inactive_when_player_not_playing() -> None:
    """Verify barge-in does not trigger when assistant is not actively speaking."""
    mock_player = MagicMock()
    mock_player.is_playing = False

    detector = BargeInDetector(player=mock_player, min_speech_frames=2)
    loud_speech = np.ones(512, dtype=np.int16) * 5000

    triggered = detector.process_chunk(loud_speech, is_playing=False)
    assert triggered is False
    assert detector.consecutive_speech_frames == 0


def test_barge_in_vad_speech_debounce() -> None:
    """Verify barge-in requires consecutive speech frames (debounce) before triggering."""
    mock_player = MagicMock()
    mock_player.is_playing = True

    mock_vad = MagicMock()
    mock_vad.get_speech_probability.return_value = 0.85

    barge_in_called = False

    def on_barge_in() -> None:
        nonlocal barge_in_called
        barge_in_called = True

    detector = BargeInDetector(
        player=mock_player,
        vad=mock_vad,
        mode=BargeInMode.VAD_SPEECH,
        min_speech_frames=3,
        rms_threshold=500.0,
        vad_threshold=0.5,
        on_barge_in=on_barge_in,
    )

    loud_speech = np.ones(512, dtype=np.int16) * 2000

    # Frame 1: count becomes 1, no trigger
    assert detector.process_chunk(loud_speech) is False
    assert detector.consecutive_speech_frames == 1
    mock_player.stop.assert_not_called()

    # Frame 2: count becomes 2, no trigger
    assert detector.process_chunk(loud_speech) is False
    assert detector.consecutive_speech_frames == 2
    mock_player.stop.assert_not_called()

    # Frame 3: count reaches min_speech_frames (3) -> Triggers!
    assert detector.process_chunk(loud_speech) is True
    mock_player.stop.assert_called_once()
    assert barge_in_called is True


def test_barge_in_frame_decay_on_quiet_gap() -> None:
    """Verify intermittent quiet frames decay the speech counter to prevent false triggers."""
    mock_player = MagicMock()
    mock_player.is_playing = True

    mock_vad = MagicMock()
    detector = BargeInDetector(
        player=mock_player,
        vad=mock_vad,
        min_speech_frames=3,
        rms_threshold=500.0,
    )

    speech_chunk = np.ones(512, dtype=np.int16) * 2000
    quiet_chunk = np.zeros(512, dtype=np.int16)

    # Frame 1 (speech): count = 1
    mock_vad.get_speech_probability.return_value = 0.8
    detector.process_chunk(speech_chunk)
    assert detector.consecutive_speech_frames == 1

    # Frame 2 (quiet): count decays to 0
    mock_vad.get_speech_probability.return_value = 0.05
    detector.process_chunk(quiet_chunk)
    assert detector.consecutive_speech_frames == 0

    # Frame 3 (speech): count = 1 (not 2 or 3)
    mock_vad.get_speech_probability.return_value = 0.8
    assert detector.process_chunk(speech_chunk) is False
    assert detector.consecutive_speech_frames == 1


def test_barge_in_rejects_low_energy_bleed() -> None:
    """Verify acoustic bleed with high VAD probability but low RMS is ignored."""
    mock_player = MagicMock()
    mock_player.is_playing = True

    mock_vad = MagicMock()
    # High VAD probability
    mock_vad.get_speech_probability.return_value = 0.95

    detector = BargeInDetector(
        player=mock_player,
        vad=mock_vad,
        min_speech_frames=2,
        rms_threshold=1000.0,  # Strict threshold
    )

    # Low-amplitude audio: RMS is ~200 (well below 1000.0)
    quiet_bleed = np.ones(512, dtype=np.int16) * 200

    assert detector.process_chunk(quiet_bleed) is False
    assert detector.consecutive_speech_frames == 0
    mock_player.stop.assert_not_called()


def test_barge_in_wake_word_mode() -> None:
    """Verify WAKE_WORD mode triggers exclusively on wake-word score and ignores general speech."""
    mock_player = MagicMock()
    mock_player.is_playing = True

    mock_vad = MagicMock()
    mock_vad.get_speech_probability.return_value = 0.99

    detector = BargeInDetector(
        player=mock_player,
        vad=mock_vad,
        mode=BargeInMode.WAKE_WORD,
        wake_word_threshold=0.4,
    )

    speech_chunk = np.ones(512, dtype=np.int16) * 5000

    # 1. Normal speech ignored in WAKE_WORD mode
    for _ in range(5):
        assert detector.process_chunk(speech_chunk, wakeword_score=0.1) is False
    mock_player.stop.assert_not_called()

    # 2. Wake-word activation score >= threshold triggers immediately
    assert detector.process_chunk(speech_chunk, wakeword_score=0.45) is True
    mock_player.stop.assert_called_once()


def test_barge_in_cooldown_period() -> None:
    """Verify post-trigger cooldown prevents repeated triggers."""
    mock_player = MagicMock()
    mock_player.is_playing = True

    mock_vad = MagicMock()
    mock_vad.get_speech_probability.return_value = 0.9

    detector = BargeInDetector(
        player=mock_player,
        vad=mock_vad,
        min_speech_frames=1,
        rms_threshold=500.0,
        cooldown_seconds=0.2,
    )

    speech_chunk = np.ones(512, dtype=np.int16) * 3000

    # 1. First frame triggers barge-in
    assert detector.process_chunk(speech_chunk) is True
    assert detector.is_in_cooldown is True

    # 2. Subsequent frame within cooldown does not trigger
    assert detector.process_chunk(speech_chunk) is False

    # 3. After cooldown elapses, can trigger again
    time.sleep(0.25)
    assert detector.is_in_cooldown is False
    assert detector.process_chunk(speech_chunk) is True


def test_pipeline_coordinator_barge_in_transition() -> None:
    """Verify AudioPipelineCoordinator transitions SPEAKING -> LISTENING upon user interruption."""
    mock_capture = MagicMock()
    mock_ring = MagicMock()
    mock_wakeword = MagicMock()
    mock_vad = MagicMock()
    mock_transcriber = MagicMock()

    mock_player = MagicMock()
    mock_player.is_playing = True

    barge_in_triggered = False

    def on_barge_in() -> None:
        nonlocal barge_in_triggered
        barge_in_triggered = True

    coordinator = AudioPipelineCoordinator(
        capture_stream=mock_capture,
        ring_buffer=mock_ring,
        wakeword_detector=mock_wakeword,
        vad_detector=mock_vad,
        transcriber=mock_transcriber,
        player=mock_player,
        on_barge_in=on_barge_in,
    )

    # Put coordinator into SPEAKING state
    coordinator._set_state(PipelineState.SPEAKING)
    assert coordinator.state == PipelineState.SPEAKING

    # Simulate barge-in trigger event
    coordinator._on_barge_in_triggered()

    # Coordinator should transition to LISTENING, reset VAD, and notify callback
    assert coordinator.state == PipelineState.LISTENING
    assert barge_in_triggered is True
    mock_vad.reset.assert_called_once()

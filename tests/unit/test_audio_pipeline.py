"""Unit tests for broski AudioPipelineCoordinator."""

import time
from unittest.mock import MagicMock

import numpy as np

from broski.audio.pipeline import AudioPipelineCoordinator, PipelineState
from broski.audio.ring_buffer import AudioRingBuffer


def test_pipeline_initial_state() -> None:
    """Verify initial state of coordinator is STOPPED."""
    ring_buf = AudioRingBuffer(capacity_bytes=10000)
    pipeline = AudioPipelineCoordinator(
        ring_buffer=ring_buf,
        capture_stream=MagicMock(),
        wakeword_detector=MagicMock(),
        vad_detector=MagicMock(),
        transcriber=MagicMock(),
    )
    assert pipeline.state == PipelineState.STOPPED
    assert pipeline.dictation_mode is False


def test_pipeline_lifecycle_and_state_transitions() -> None:
    """Verify coordinator starts capture, transitions states, and handles callbacks."""
    ring_buf = AudioRingBuffer(capacity_bytes=50000)
    mock_capture = MagicMock()
    mock_ww = MagicMock()
    mock_ww.chunk_size = 1280
    mock_vad = MagicMock()
    mock_vad.chunk_size = 512
    mock_stt = MagicMock()

    wake_callback = MagicMock()
    transcript_callback = MagicMock()

    pipeline = AudioPipelineCoordinator(
        ring_buffer=ring_buf,
        capture_stream=mock_capture,
        wakeword_detector=mock_ww,
        vad_detector=mock_vad,
        transcriber=mock_stt,
        on_wake_word=wake_callback,
        on_transcript=transcript_callback,
    )

    # 1. Start pipeline
    pipeline.start()
    assert pipeline.state == PipelineState.IDLE
    mock_capture.start.assert_called_once()

    # 2. Simulate wake word trigger: feed audio and mock trigger
    mock_ww.predict.return_value = (0.88, True)
    ring_buf.write(np.zeros(1280, dtype=np.int16))

    # Give worker thread a moment to process chunk
    time.sleep(0.08)

    # Pipeline should have transitioned to LISTENING and fired wake_callback
    assert pipeline.state == PipelineState.LISTENING
    wake_callback.assert_called_once_with(0.88)

    # 3. Simulate speech and then speech completion via VAD
    mock_vad.process_chunk.return_value = (0.9, False, np.ones(16000, dtype=np.int16))
    mock_stt.transcribe.return_value = "Hey broski, open spotify"

    ring_buf.write(np.zeros(512, dtype=np.int16))
    time.sleep(0.08)

    # Transcript callback should have fired with the transcribed text
    transcript_callback.assert_called_once_with("Hey broski, open spotify")
    # State should return to IDLE
    assert pipeline.state == PipelineState.IDLE

    # 4. Stop pipeline
    pipeline.stop()
    assert pipeline.state == PipelineState.STOPPED
    mock_capture.stop.assert_called_once()


def test_pipeline_dictation_mode() -> None:
    """Verify dictation mode bypasses wake word and listens directly."""
    ring_buf = AudioRingBuffer(capacity_bytes=50000)
    mock_capture = MagicMock()
    mock_ww = MagicMock()
    mock_ww.chunk_size = 1280
    mock_vad = MagicMock()
    mock_vad.chunk_size = 512
    mock_stt = MagicMock()

    pipeline = AudioPipelineCoordinator(
        ring_buffer=ring_buf,
        capture_stream=mock_capture,
        wakeword_detector=mock_ww,
        vad_detector=mock_vad,
        transcriber=mock_stt,
    )
    pipeline.dictation_mode = True

    pipeline.start()
    time.sleep(0.05)

    # In dictation mode, coordinator transitions directly to LISTENING without waiting for wake word
    assert pipeline.state == PipelineState.LISTENING

    pipeline.stop()
    assert pipeline.state == PipelineState.STOPPED

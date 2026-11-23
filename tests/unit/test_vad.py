"""Unit tests for broski Silero VAD (Voice Activity Detection)."""

import numpy as np

from broski.audio.vad import SileroVADDetector


def test_vad_initialization() -> None:
    """Verify Silero VAD initializes ONNX session and state tensors."""
    vad = SileroVADDetector()
    assert vad.sample_rate == 16000
    assert vad.threshold == 0.5
    assert vad.is_speaking is False


def test_vad_silence_probability() -> None:
    """Verify pure silence produces speech probability close to zero."""
    vad = SileroVADDetector()
    silence = np.zeros(512, dtype=np.int16)
    prob = vad.get_speech_probability(silence)
    assert 0.0 <= prob < 0.1


def test_vad_reset() -> None:
    """Verify reset clears internal state, buffers, and flags."""
    vad = SileroVADDetector()
    vad.is_speaking = True
    vad._speech_buffer.append(np.ones(512, dtype=np.int16))
    vad._silent_samples_accumulated = 1000

    vad.reset()

    assert vad.is_speaking is False
    assert len(vad._speech_buffer) == 0
    assert vad._silent_samples_accumulated == 0


def test_vad_speech_segmentation_lifecycle() -> None:
    """Verify process_chunk manages state transitions from silence to speech to segment emission."""
    vad = SileroVADDetector(threshold=0.5, silence_duration_ms=64)  # 64ms silence = 2 frames of 512

    # Mock get_speech_probability to simulate speech then silence
    speech_frame = np.ones(512, dtype=np.int16)
    silent_frame = np.zeros(512, dtype=np.int16)

    # 1. Start with silence: should not trigger speech
    prob, is_speaking, finished = vad.process_chunk(silent_frame)
    assert is_speaking is False
    assert finished is None

    # 2. Simulate user speaking: mock high probability
    orig_prob_func = vad.get_speech_probability
    try:
        vad.get_speech_probability = lambda chunk: 0.9  # type: ignore[method-assign]
        prob, is_speaking, finished = vad.process_chunk(speech_frame)
        assert prob == 0.9
        assert is_speaking is True
        assert finished is None

        # 3. Simulate user silence: mock low probability
        vad.get_speech_probability = lambda chunk: 0.05  # type: ignore[method-assign]

        # First silence frame (32ms): not enough to trigger 64ms pause
        prob, is_speaking, finished = vad.process_chunk(silent_frame)
        assert is_speaking is True
        assert finished is None

        # Second silence frame (64ms total): threshold reached! Speech segment emitted
        prob, is_speaking, finished = vad.process_chunk(silent_frame)
        assert is_speaking is False
        assert finished is not None
        # Finished segment should contain speech_frame + 2 silent_frames = 1536 samples
        assert len(finished) == 1536
    finally:
        vad.get_speech_probability = orig_prob_func

"""Unit tests for broski AudioCaptureStream and resampling."""

from unittest.mock import MagicMock, patch

import numpy as np

from broski.audio.capture import (
    AudioCaptureStream,
    list_input_devices,
    resample_audio,
)
from broski.audio.ring_buffer import AudioRingBuffer


def test_list_input_devices() -> None:
    """Verify list_input_devices queries host devices and flags default device."""
    devices = list_input_devices()
    # On Windows host with a sound card, at least one input device exists
    assert isinstance(devices, list)
    if devices:
        first = devices[0]
        assert "name" in first
        assert "channels" in first
        assert first["channels"] > 0
        assert "default_samplerate" in first


def test_resample_audio_identity() -> None:
    """Verify resampling from 16kHz to 16kHz returns the identical array."""
    audio = np.array([100, 200, 300, 400], dtype=np.int16)
    res = resample_audio(audio, orig_sr=16000, target_sr=16000)
    assert np.array_equal(res, audio)


def test_resample_audio_48k_to_16k() -> None:
    """Verify downsampling 48kHz (e.g. Bluetooth earphones) to 16kHz produces 1/3 sample count."""
    # 480 samples at 48kHz = 10ms of audio
    # Downsampled to 16kHz should produce 160 samples (10ms of audio)
    audio_48k = np.sin(np.linspace(0, 10 * np.pi, 480)).astype(np.float32)
    res_16k = resample_audio(audio_48k, orig_sr=48000, target_sr=16000)

    assert len(res_16k) == 160
    assert res_16k.dtype == np.float32


def test_resample_audio_empty() -> None:
    """Verify empty array resampling produces empty array."""
    empty = np.empty(0, dtype=np.int16)
    res = resample_audio(empty, orig_sr=44100, target_sr=16000)
    assert len(res) == 0


def test_audio_capture_stream_lifecycle() -> None:
    """Verify AudioCaptureStream lifecycle using mocked sounddevice InputStream."""
    ring_buffer = AudioRingBuffer(capacity_bytes=10000)

    with (
        patch("sounddevice.check_input_settings") as mock_check,
        patch("sounddevice.InputStream") as mock_input_stream,
    ):
        mock_check.return_value = None
        mock_stream_instance = MagicMock()
        mock_stream_instance.active = True
        mock_input_stream.return_value = mock_stream_instance

        capture = AudioCaptureStream(ring_buffer=ring_buffer, target_sample_rate=16000)

        # Start stream
        capture.start()
        assert capture.is_running is True
        assert mock_input_stream.call_count >= 1
        assert mock_stream_instance.start.call_count >= 1

        # Simulate incoming audio from PortAudio callback
        fake_audio = np.array([[100], [200], [300]], dtype=np.int16)
        capture._audio_callback(fake_audio, frames=3, time_info=None, status=MagicMock())

        # Check that ring buffer received audio
        assert ring_buffer.available_samples == 3
        read_back = ring_buffer.read_samples(3)
        assert np.array_equal(read_back, np.array([100, 200, 300], dtype=np.int16))

        # Stop stream
        capture.stop()
        assert mock_stream_instance.stop.call_count >= 1
        assert mock_stream_instance.close.call_count >= 1

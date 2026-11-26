"""Unit tests for broski AudioPlayer non-blocking playback engine."""

import time
from unittest.mock import MagicMock, patch

import numpy as np

from broski.audio.player import (
    AudioPlayer,
    find_default_or_headset_output_device,
    list_output_devices,
)


def test_list_output_devices() -> None:
    """Verify list_output_devices queries system output devices and flags defaults."""
    devices = list_output_devices()
    assert isinstance(devices, list)
    if devices:
        first = devices[0]
        assert "name" in first
        assert "channels" in first
        assert first["channels"] > 0
        assert "default_samplerate" in first
        assert "is_default" in first
        assert "is_headset" in first


def test_find_default_or_headset_output_device_mocked() -> None:
    """Verify device selection logic prioritizes headsets, defaults, and custom index."""
    mock_devices = [
        {
            "index": 1,
            "name": "Speakers (Realtek Audio)",
            "channels": 2,
            "default_samplerate": 48000,
            "hostapi": 0,
            "is_default": False,
            "is_headset": False,
        },
        {
            "index": 2,
            "name": "Headphones (OnePlus Nord Buds 3)",
            "channels": 2,
            "default_samplerate": 44100,
            "hostapi": 0,
            "is_default": True,
            "is_headset": True,
        },
    ]

    with patch("broski.audio.player.list_output_devices", return_value=mock_devices):
        # 1. Automatic headset detection
        idx, name = find_default_or_headset_output_device()
        assert idx == 2
        assert "OnePlus Nord Buds 3" in name

        # 2. Explicit index preference
        idx_custom, name_custom = find_default_or_headset_output_device(preferred_index=1)
        assert idx_custom == 1
        assert "Realtek Audio" in name_custom


def test_audio_player_initialization() -> None:
    """Verify AudioPlayer initial properties, volume bounds, and default state."""
    player = AudioPlayer(sample_rate=22050, channels=2, volume=1.0)
    assert player.sample_rate == 22050
    assert player.channels == 2
    assert player.volume == 1.0
    assert player.is_playing is False
    assert player.is_active is False
    assert player.queue_size == 0

    # Volume clamping tests
    player.volume = -0.5
    assert player.volume == 0.0

    player.volume = 3.5
    assert player.volume == 2.0


def test_audio_player_play_chunk_channel_adaptation() -> None:
    """Verify 1D mono audio is duplicated to 2D stereo when player has 2 channels."""
    player = AudioPlayer(sample_rate=22050, channels=2)

    with patch.object(player, "start") as mock_start:
        mono_1d = np.array([1000, -2000, 3000], dtype=np.int16)
        player.play_chunk(mono_1d, sample_rate=22050)

        mock_start.assert_called_once()
        assert player.is_playing is True
        assert player.queue_size == 1

        queued = player._queue.get_nowait()
        assert queued.shape == (3, 2)
        assert np.array_equal(queued[:, 0], mono_1d)
        assert np.array_equal(queued[:, 1], mono_1d)


def test_audio_player_play_chunk_mono_output() -> None:
    """Verify stereo input is averaged down to mono when player has 1 channel."""
    player = AudioPlayer(sample_rate=22050, channels=1)

    with patch.object(player, "start"):
        stereo = np.array([[1000, 3000], [2000, 4000]], dtype=np.int16)
        player.play_chunk(stereo, sample_rate=22050)

        queued = player._queue.get_nowait()
        assert queued.shape == (2, 1)
        # Average of [1000, 3000] is 2000; average of [2000, 4000] is 3000
        assert np.array_equal(queued.ravel(), np.array([2000, 3000], dtype=np.int16))


def test_audio_player_play_chunk_resampling() -> None:
    """Verify audio with different sample rate is resampled before enqueueing."""
    player = AudioPlayer(sample_rate=22050, channels=2)

    with patch.object(player, "start"):
        # 16000 Hz input of 1600 samples (100ms)
        chunk_16k = np.zeros(1600, dtype=np.int16)
        player.play_chunk(chunk_16k, sample_rate=16000)

        queued = player._queue.get_nowait()
        # 100ms at 22050 Hz is ~2205 samples
        assert queued.shape[0] == 2205
        assert queued.shape[1] == 2


def test_audio_player_callback_audio_delivery() -> None:
    """Verify _audio_callback transfers chunk slices into outdata array accurately."""
    start_called = False
    end_called = False

    def on_start() -> None:
        nonlocal start_called
        start_called = True

    def on_end() -> None:
        nonlocal end_called
        end_called = True

    player = AudioPlayer(
        sample_rate=22050,
        channels=2,
        on_playback_start=on_start,
        on_playback_end=on_end,
    )

    with patch.object(player, "start"):
        # Enqueue 10 samples of stereo audio
        data = np.arange(20, dtype=np.int16).reshape(10, 2)
        player.play_chunk(data, sample_rate=22050)
        assert start_called is True
        assert player.is_playing is True

        # Callback 1: request 6 frames (partial chunk)
        out1 = np.zeros((6, 2), dtype=np.int16)
        status = MagicMock()
        status.output_underflow = False
        player._audio_callback(out1, frames=6, time_info=None, status=status)
        assert np.array_equal(out1, data[:6])
        assert player.is_playing is True

        # Callback 2: request 6 frames (remaining 4 samples of data + 2 samples of silence)
        out2 = np.zeros((6, 2), dtype=np.int16)
        player._audio_callback(out2, frames=6, time_info=None, status=status)
        assert np.array_equal(out2[:4], data[6:])
        assert np.all(out2[4:] == 0)

        # Give background thread a moment to trigger on_end
        time.sleep(0.05)
        assert player.is_playing is False
        assert end_called is True


def test_audio_player_volume_scaling() -> None:
    """Verify volume scalar is applied to audio frames in callback."""
    player = AudioPlayer(sample_rate=22050, channels=2, volume=0.5)

    with patch.object(player, "start"):
        data = np.array([[1000, 1000], [2000, 2000]], dtype=np.int16)
        player.play_chunk(data, sample_rate=22050)

        out = np.zeros((2, 2), dtype=np.int16)
        status = MagicMock()
        status.output_underflow = False
        player._audio_callback(out, frames=2, time_info=None, status=status)

        # Scaled by 0.5: 1000 -> 500, 2000 -> 1000
        expected = np.array([[500, 500], [1000, 1000]], dtype=np.int16)
        assert np.array_equal(out, expected)


def test_audio_player_stop_instant_cancellation() -> None:
    """Verify stop() clears queue, stops playback, and executes in < 10ms for barge-in."""
    stopped_called = False

    def on_stopped() -> None:
        nonlocal stopped_called
        stopped_called = True

    player = AudioPlayer(
        sample_rate=22050,
        channels=2,
        on_playback_stopped=on_stopped,
    )

    with patch.object(player, "start"):
        # Enqueue 5 chunks
        for _ in range(5):
            player.play_chunk(np.ones((1000, 2), dtype=np.int16), sample_rate=22050)

        assert player.queue_size == 5
        assert player.is_playing is True

        # Measure stop() execution time (Barge-in latency constraint: <10ms)
        t0 = time.perf_counter()
        player.stop()
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert elapsed_ms < 10.0, f"stop() took {elapsed_ms:.2f}ms, expected < 10ms"
        assert player.queue_size == 0
        assert player.is_playing is False

        # Next callback must write zero silence
        out = np.ones((500, 2), dtype=np.int16)
        status = MagicMock()
        status.output_underflow = False
        player._audio_callback(out, frames=500, time_info=None, status=status)
        assert np.all(out == 0)

        time.sleep(0.05)
        assert stopped_called is True


def test_audio_player_play_stream() -> None:
    """Verify play_stream feeds chunks from generator."""
    player = AudioPlayer(sample_rate=22050, channels=2)

    def chunk_generator():
        yield np.ones((100, 2), dtype=np.int16)
        yield np.ones((200, 2), dtype=np.int16)
        yield np.ones((300, 2), dtype=np.int16)

    with patch.object(player, "start"):
        player.play_stream(chunk_generator(), blocking=False)
        assert player.queue_size == 3
        assert player.is_playing is True


def test_audio_player_context_manager() -> None:
    """Verify AudioPlayer context manager starts and closes stream."""
    with (
        patch("sounddevice.OutputStream") as mock_stream_cls,
        patch("broski.audio.player.find_default_or_headset_output_device", return_value=(4, "Headphones")),
    ):
        mock_instance = MagicMock()
        mock_instance.active = True
        mock_stream_cls.return_value = mock_instance

        with AudioPlayer(device_index=4) as player:
            assert player.is_active is True
            mock_stream_cls.assert_called_once()
            mock_instance.start.assert_called_once()

        mock_instance.stop.assert_called_once()
        mock_instance.close.assert_called_once()
        assert player._stream is None

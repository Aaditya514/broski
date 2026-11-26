"""Audio playback engine for broski using sounddevice OutputStream.

Provides non-blocking audio playback, thread-safe chunk queueing,
automatic resampling and channel handling (mono to stereo duplication),
volume scaling, and instantaneous stop/interruption for barge-in (<10ms).
"""

import logging
import queue
import threading
from collections.abc import Callable, Iterable
from types import TracebackType
from typing import Any, Self

import numpy as np
import sounddevice as sd

from broski.audio.capture import resample_audio

logger = logging.getLogger(__name__)


def list_output_devices() -> list[dict[str, Any]]:
    """Return a list of available audio output devices and identify the system default."""
    devices = sd.query_devices()
    default_output_idx = sd.default.device[1]

    output_devs = []
    for idx, dev in enumerate(devices):
        if dev["max_output_channels"] > 0:
            name_lower = dev["name"].lower()
            is_headset = any(
                kw in name_lower for kw in ("oneplus", "nord", "buds", "headset", "airpods", "headphones")
            ) and not dev["name"].startswith("@")
            output_devs.append(
                {
                    "index": idx,
                    "name": dev["name"],
                    "channels": dev["max_output_channels"],
                    "default_samplerate": int(dev["default_samplerate"]),
                    "hostapi": dev["hostapi"],
                    "is_default": idx == default_output_idx,
                    "is_headset": is_headset,
                }
            )
    return output_devs


def find_default_or_headset_output_device(
    preferred_index: int | None = None,
) -> tuple[int | None, str]:
    """Find the best output device, prioritizing connected Bluetooth headsets."""
    devices = list_output_devices()
    if not devices:
        return None, "Default Audio Output"

    # If preferred index provided and valid
    if preferred_index is not None:
        for dev in devices:
            if dev["index"] == preferred_index:
                return dev["index"], dev["name"]

    # Priority 1: Connected headset/headphones that is NOT hands-free driver
    for dev in devices:
        if dev.get("is_headset") and not dev["name"].startswith("@"):
            logger.info("Found output headset: [%d] %s", dev["index"], dev["name"])
            return dev["index"], dev["name"]

    # Priority 2: System default output device
    for dev in devices:
        if dev.get("is_default"):
            logger.info("Found system default output device: [%d] %s", dev["index"], dev["name"])
            return dev["index"], dev["name"]

    # Priority 3: Fall back to first available output device
    first = devices[0]
    return first["index"], first["name"]


class AudioPlayer:
    """Non-blocking audio output player stream powered by sounddevice.OutputStream.

    Maintains a thread-safe queue of audio chunks, streams seamlessly across
    sentence boundaries, supports dynamic volume adjustment, and delivers
    instantaneous cancellation for barge-in.
    """

    def __init__(
        self,
        device_index: int | None = None,
        sample_rate: int = 22050,
        channels: int = 2,
        volume: float = 1.0,
        blocksize: int = 1024,
        on_playback_start: Callable[[], None] | None = None,
        on_playback_end: Callable[[], None] | None = None,
        on_playback_stopped: Callable[[], None] | None = None,
    ) -> None:
        self._device_index = device_index
        self._sample_rate = sample_rate
        self._channels = channels
        self._volume = max(0.0, min(2.0, float(volume)))
        self._blocksize = blocksize

        self.on_playback_start = on_playback_start
        self.on_playback_end = on_playback_end
        self.on_playback_stopped = on_playback_stopped

        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._current_buffer: np.ndarray | None = None
        self._buffer_offset: int = 0

        self._stream: sd.OutputStream | None = None
        self._lock = threading.Lock()
        self._is_playing: bool = False
        self._stop_requested: bool = False

        self._playback_finished_event = threading.Event()
        self._playback_finished_event.set()

    @property
    def device_index(self) -> int | None:
        """Configured output device index."""
        return self._device_index

    @property
    def sample_rate(self) -> int:
        """Audio playback sample rate in Hz."""
        return self._sample_rate

    @property
    def channels(self) -> int:
        """Audio playback channel count."""
        return self._channels

    @property
    def volume(self) -> float:
        """Current playback volume scalar (0.0 to 2.0)."""
        return self._volume

    @volume.setter
    def volume(self, val: float) -> None:
        self._volume = max(0.0, min(2.0, float(val)))

    @property
    def is_playing(self) -> bool:
        """Return True if audio is actively playing or queued to play."""
        return self._is_playing

    @property
    def queue_size(self) -> int:
        """Number of audio chunks waiting in the playback queue."""
        return self._queue.qsize()

    @property
    def is_active(self) -> bool:
        """Return True if the underlying sounddevice stream is initialized and running."""
        return self._stream is not None and self._stream.active

    def _safe_invoke(self, callback: Callable[[], None]) -> None:
        """Execute a user callback safely without propagating exceptions."""
        try:
            callback()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Error executing playback callback %r: %s", callback, exc)

    def _audio_callback(
        self,
        outdata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        """Real-time sounddevice output callback.

        Fills outdata with the next slice of audio from the queue.
        Zero heap allocations when draining existing buffers.
        """
        if status.output_underflow:
            logger.debug("Audio output underflow detected.")

        if self._stop_requested:
            outdata.fill(0)
            return

        frames_needed = frames
        frames_written = 0

        while frames_written < frames_needed:
            if self._current_buffer is None or self._buffer_offset >= len(self._current_buffer):
                try:
                    self._current_buffer = self._queue.get_nowait()
                    self._buffer_offset = 0
                except queue.Empty:
                    # No more audio queued
                    self._current_buffer = None
                    self._buffer_offset = 0

                    if self._is_playing:
                        self._is_playing = False
                        self._playback_finished_event.set()
                        if self.on_playback_end is not None:
                            threading.Thread(
                                target=self._safe_invoke,
                                args=(self.on_playback_end,),
                                daemon=True,
                            ).start()

                    outdata[frames_written:].fill(0)
                    return

            available = len(self._current_buffer) - self._buffer_offset
            needed = frames_needed - frames_written
            to_copy = min(available, needed)

            outdata[frames_written : frames_written + to_copy] = (
                self._current_buffer[self._buffer_offset : self._buffer_offset + to_copy]
            )
            self._buffer_offset += to_copy
            frames_written += to_copy

        # Apply volume scaling if not unity
        if self._volume != 1.0 and frames_written > 0:
            scaled = outdata[:frames_written].astype(np.float32) * self._volume
            outdata[:frames_written] = np.clip(scaled, -32768, 32767).astype(np.int16)

    def start(self) -> None:
        """Start the sounddevice output stream if not already active."""
        with self._lock:
            if self._stream is not None and self._stream.active:
                return

            self._stop_requested = False
            device = self._device_index
            if device is None:
                device, _ = find_default_or_headset_output_device()

            try:
                self._stream = sd.OutputStream(
                    device=device,
                    samplerate=self._sample_rate,
                    channels=self._channels,
                    dtype="int16",
                    blocksize=self._blocksize,
                    callback=self._audio_callback,
                )
                self._stream.start()
                logger.info(
                    "AudioPlayer stream started on device %s (SR: %d Hz, CH: %d, Blocksize: %d).",
                    device,
                    self._sample_rate,
                    self._channels,
                    self._blocksize,
                )
            except Exception as exc:
                logger.error("Failed to open AudioPlayer OutputStream: %s", exc)
                raise

    def play_chunk(self, chunk: np.ndarray, sample_rate: int = 22050) -> None:
        """Queue an audio chunk for immediate non-blocking playback.

        Automatically handles sample rate conversion and channel layout adaptation.

        Args:
            chunk: 1D or 2D numpy array of audio samples (int16 or float).
            sample_rate: Sample rate of the incoming chunk in Hz.
        """
        if len(chunk) == 0:
            return

        with self._lock:
            self._stop_requested = False

        # Resample if sample rate does not match stream sample rate
        processed = chunk
        if sample_rate != self._sample_rate:
            if processed.ndim == 1:
                processed = resample_audio(processed, orig_sr=sample_rate, target_sr=self._sample_rate)
            elif processed.ndim == 2:
                cols = [
                    resample_audio(processed[:, col], orig_sr=sample_rate, target_sr=self._sample_rate)
                    for col in range(processed.shape[1])
                ]
                processed = np.column_stack(cols)

        # Convert float to int16 if necessary
        if np.issubdtype(processed.dtype, np.floating):
            processed = np.clip(processed * 32767.0, -32768, 32767).astype(np.int16)
        elif processed.dtype != np.int16:
            processed = processed.astype(np.int16)

        # Adapt channel layout to match player channels
        if self._channels == 2:
            if processed.ndim == 1:
                processed = np.column_stack((processed, processed))
            elif processed.ndim == 2 and processed.shape[1] == 1:
                processed = np.column_stack((processed[:, 0], processed[:, 0]))
            elif processed.ndim == 2 and processed.shape[1] > 2:
                processed = processed[:, :2]
        elif self._channels == 1:
            if processed.ndim == 2 and processed.shape[1] > 1:
                processed = np.mean(processed, axis=1).astype(np.int16)[:, np.newaxis]
            elif processed.ndim == 1:
                processed = processed[:, np.newaxis]

        # Ensure contiguous memory layout for callback
        processed = np.ascontiguousarray(processed)

        # Ensure stream is running
        if not self.is_active:
            self.start()

        was_playing = self._is_playing
        self._is_playing = True
        self._playback_finished_event.clear()

        self._queue.put(processed)

        if not was_playing and self.on_playback_start is not None:
            self._safe_invoke(self.on_playback_start)

    def play(
        self,
        audio: np.ndarray,
        sample_rate: int = 22050,
        blocking: bool = False,
    ) -> None:
        """Play a complete audio buffer.

        Args:
            audio: 1D or 2D numpy array of audio samples.
            sample_rate: Sample rate of the audio in Hz.
            blocking: If True, blocks until all audio finishes playing.
        """
        self.play_chunk(audio, sample_rate=sample_rate)
        if blocking:
            self.wait()

    def play_stream(
        self,
        stream: Iterable[np.ndarray],
        sample_rate: int = 22050,
        blocking: bool = False,
    ) -> None:
        """Stream an iterable of audio chunks (e.g. from PiperSynthesizer.synthesize_stream).

        Args:
            stream: Iterable yielding audio chunks.
            sample_rate: Sample rate of each chunk in Hz.
            blocking: If True, blocks until the entire stream finishes playing.
        """
        for chunk in stream:
            if self._stop_requested:
                break
            self.play_chunk(chunk, sample_rate=sample_rate)

        if blocking:
            self.wait()

    def stop(self) -> None:
        """Instantly stop playback and clear the audio queue (<10ms for barge-in)."""
        with self._lock:
            self._stop_requested = True
            was_playing = (
                self._is_playing
                or not self._queue.empty()
                or self._current_buffer is not None
            )

            # Instantly drain queue
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    break

            self._current_buffer = None
            self._buffer_offset = 0
            self._is_playing = False
            self._playback_finished_event.set()

        if was_playing and self.on_playback_stopped is not None:
            threading.Thread(
                target=self._safe_invoke,
                args=(self.on_playback_stopped,),
                daemon=True,
            ).start()

    def wait(self, timeout: float | None = None) -> bool:
        """Wait until all queued audio finishes playing.

        Args:
            timeout: Maximum wait time in seconds (None waits indefinitely).

        Returns:
            True if playback completed, False if timed out.
        """
        if not self._is_playing and self._queue.empty() and self._current_buffer is None:
            return True
        return self._playback_finished_event.wait(timeout=timeout)

    def close(self) -> None:
        """Stop playback and close the underlying sounddevice stream."""
        self.stop()
        with self._lock:
            if self._stream is not None:
                try:
                    self._stream.stop()
                    self._stream.close()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Exception closing OutputStream: %s", exc)
                finally:
                    self._stream = None

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()

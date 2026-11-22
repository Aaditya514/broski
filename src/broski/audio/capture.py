"""Microphone audio capture stream for broski.

Captures audio from Windows WASAPI input devices, supports Bluetooth earphones,
automatically resamples to 16,000 Hz 16-bit mono PCM, and streams into an AudioRingBuffer.
"""

import logging
from collections.abc import Callable
from types import TracebackType
from typing import Any, Self

import numpy as np
import sounddevice as sd

from broski.audio.ring_buffer import AudioRingBuffer

logger = logging.getLogger(__name__)


def list_input_devices() -> list[dict[str, Any]]:
    """Return a list of available audio input devices and identify the system default."""
    devices = sd.query_devices()
    default_input_idx = sd.default.device[0]

    input_devs = []
    for idx, dev in enumerate(devices):
        if dev["max_input_channels"] > 0:
            input_devs.append(
                {
                    "index": idx,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "default_samplerate": int(dev["default_samplerate"]),
                    "hostapi": dev["hostapi"],
                    "is_default": idx == default_input_idx,
                }
            )
    return input_devs


def resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int = 16000) -> np.ndarray:
    """Fast linear interpolation resampling from orig_sr to target_sr using numpy."""
    if orig_sr == target_sr or len(audio) == 0:
        return audio

    num_output_samples = round(len(audio) * target_sr / orig_sr)
    if num_output_samples == 0:
        return np.empty(0, dtype=audio.dtype)

    x_orig = np.linspace(0.0, 1.0, len(audio), endpoint=False)
    x_target = np.linspace(0.0, 1.0, num_output_samples, endpoint=False)

    # Interpolate
    resampled = np.interp(x_target, x_orig, audio)
    return resampled.astype(audio.dtype)


class AudioCaptureStream:
    """Manages sounddevice InputStream and streams resampled 16kHz audio into a ring buffer."""

    def __init__(
        self,
        ring_buffer: AudioRingBuffer,
        device_index: int | None = None,
        target_sample_rate: int = 16000,
        chunk_duration_ms: int = 50,  # 50ms audio chunks
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self.ring_buffer = ring_buffer
        self.device_index = device_index
        self.target_sample_rate = target_sample_rate
        self.chunk_duration_ms = chunk_duration_ms
        self.on_error = on_error

        self._stream: sd.InputStream | None = None
        self._is_running = False
        self._native_sample_rate = target_sample_rate
        self._needs_resampling = False

    @property
    def is_running(self) -> bool:
        """Return True if audio capture stream is currently active."""
        return self._is_running and self._stream is not None and self._stream.active

    @property
    def native_sample_rate(self) -> int:
        """The actual sample rate used by the physical hardware device."""
        return self._native_sample_rate

    def _determine_sample_rate(self) -> int:
        """Determine if device supports 16kHz directly, or fall back to device default."""
        try:
            sd.check_input_settings(
                device=self.device_index,
                channels=1,
                samplerate=self.target_sample_rate,
                dtype="int16",
            )
            return self.target_sample_rate
        except (sd.PortAudioError, ValueError, OSError):
            # Device (e.g. certain Bluetooth headsets) requires native rate
            dev_info = sd.query_devices(self.device_index, "input")
            native_rate = int(dev_info["default_samplerate"])
            logger.info(
                "Device %s does not natively support 16kHz. Using native %d Hz with resampling.",
                dev_info["name"],
                native_rate,
            )
            return native_rate

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        """PortAudio callback running in real-time audio thread."""
        if status and status.input_overflow:
            logger.warning("Audio input overflow: microphone samples dropped by soundcard.")

        try:
            # Flatten to 1D mono
            audio_samples = indata[:, 0] if indata.ndim > 1 else indata

            # Resample to target 16kHz if necessary
            if self._needs_resampling:
                audio_samples = resample_audio(
                    audio_samples, self._native_sample_rate, self.target_sample_rate
                )

            # Write into pre-allocated ring buffer
            self.ring_buffer.write(audio_samples)
        except (ValueError, TypeError, RuntimeError) as exc:
            if self.on_error:
                self.on_error(exc)
            else:
                logger.error("Error in audio callback: %s", exc)

    def start(self) -> None:
        """Open and start the microphone audio stream."""
        if self.is_running:
            return

        self._native_sample_rate = self._determine_sample_rate()
        self._needs_resampling = self._native_sample_rate != self.target_sample_rate

        blocksize = int(self._native_sample_rate * (self.chunk_duration_ms / 1000.0))

        self._stream = sd.InputStream(
            device=self.device_index,
            channels=1,
            samplerate=self._native_sample_rate,
            blocksize=blocksize,
            dtype="int16",
            callback=self._audio_callback,
        )
        self._stream.start()
        self._is_running = True
        logger.info(
            "AudioCaptureStream started (Hardware: %d Hz, Target: %d Hz, Resampling: %s).",
            self._native_sample_rate,
            self.target_sample_rate,
            self._needs_resampling,
        )

    def stop(self) -> None:
        """Stop and close the microphone audio stream."""
        if not self._is_running:
            return

        self._is_running = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except (sd.PortAudioError, OSError) as exc:
                logger.warning("Exception during stream closure: %s", exc)
            finally:
                self._stream = None
        logger.info("AudioCaptureStream stopped.")

    def __enter__(self) -> Self:
        self.start()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.stop()

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
    try:
        hostapis = sd.query_hostapis()
    except Exception:  # noqa: BLE001
        hostapis = []

    input_devs = []
    for idx, dev in enumerate(devices):
        if dev.get("max_input_channels", 0) > 0:
            name_lower = dev["name"].lower()
            api_name = ""
            if hostapis and 0 <= dev.get("hostapi", -1) < len(hostapis):
                api_name = hostapis[dev["hostapi"]].get("name", "").lower()

            # Strictly exclude WDM-KS devices: WDM-KS fails with GLE = 0x0000048F in PortAudio
            is_wdm_ks = "wdm-ks" in api_name or "wdm-ks" in name_lower

            is_headset = (
                any(
                    kw in name_lower for kw in ("oneplus", "nord", "buds", "headset", "airpods")
                )
                and not dev["name"].startswith("@")
                and not is_wdm_ks
            )
            input_devs.append(
                {
                    "index": idx,
                    "name": dev["name"],
                    "channels": dev["max_input_channels"],
                    "default_samplerate": int(dev.get("default_samplerate", 16000)),
                    "hostapi": dev.get("hostapi", 0),
                    "is_default": idx == default_input_idx,
                    "is_headset": is_headset,
                    "is_wdm_ks": is_wdm_ks,
                }
            )
    return input_devs


def find_default_or_headset_device() -> tuple[int | None, str]:
    """Find the best input device, prioritizing connected Bluetooth headsets on working APIs."""
    devices = list_input_devices()
    if not devices:
        return None, "Default Audio Device"

    # Priority 1: Connected headset on non-WDM-KS APIs (WASAPI / DirectSound / MME)
    for dev in devices:
        if dev.get("is_headset") and not dev.get("is_wdm_ks"):
            # Verify device can actually be opened before picking it
            try:
                s = sd.InputStream(
                    device=dev["index"],
                    channels=1,
                    samplerate=int(dev.get("default_samplerate", 16000)),
                    dtype="int16",
                )
                s.start()
                s.stop()
                s.close()
                logger.info("Found active headset driver: [%d] %s", dev["index"], dev["name"])
                return dev["index"], dev["name"]
            except Exception as exc:  # noqa: BLE001
                logger.debug("Headset candidate [%d] %s failed to open: %s", dev["index"], dev["name"], exc)

    # Priority 2: System default device (if non-WDM-KS)
    for dev in devices:
        if dev.get("is_default") and not dev.get("is_wdm_ks"):
            return dev["index"], dev["name"]

    # Priority 3: First available non-WDM-KS input device
    for dev in devices:
        if not dev.get("is_wdm_ks"):
            return dev["index"], dev["name"]

    default_dev = next((d for d in devices if d["is_default"]), devices[0])
    return default_dev["index"], default_dev["name"]


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
        if device_index is None:
            best_idx, _ = find_default_or_headset_device()
            self.device_index = best_idx
        else:
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
        """Open and start the microphone audio stream with automatic default fallback."""
        if self.is_running:
            return

        self._native_sample_rate = self._determine_sample_rate()
        self._needs_resampling = self._native_sample_rate != self.target_sample_rate

        blocksize = int(self._native_sample_rate * (self.chunk_duration_ms / 1000.0))

        try:
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
                "AudioCaptureStream started on device %s (Hardware: %d Hz, Target: %d Hz, Resampling: %s).",
                self.device_index,
                self._native_sample_rate,
                self.target_sample_rate,
                self._needs_resampling,
            )
        except Exception as exc:
            if self.device_index is not None:
                logger.warning(
                    "Failed to start audio stream on device %s: %s. Retrying on system default microphone...",
                    self.device_index,
                    exc,
                )
                try:
                    self.device_index = None
                    self._native_sample_rate = self._determine_sample_rate()
                    self._needs_resampling = self._native_sample_rate != self.target_sample_rate
                    blocksize = int(self._native_sample_rate * (self.chunk_duration_ms / 1000.0))
                    self._stream = sd.InputStream(
                        device=None,
                        channels=1,
                        samplerate=self._native_sample_rate,
                        blocksize=blocksize,
                        dtype="int16",
                        callback=self._audio_callback,
                    )
                    self._stream.start()
                    self._is_running = True
                    logger.info("AudioCaptureStream successfully recovered on system default microphone.")
                    return
                except Exception as fallback_exc:
                    logger.error("Failed to start stream on fallback default microphone: %s", fallback_exc)
                    raise
            logger.error("Failed to start AudioCaptureStream: %s", exc)
            raise

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

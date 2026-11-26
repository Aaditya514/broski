"""Barge-in and conversational interruption detector for broski.

Monitors real-time microphone audio during active speech playback,
detects user interruption via neural VAD, acoustic energy thresholds,
or wake word triggers, and halts output in <10ms.
"""

import logging
import time
from collections.abc import Callable
from enum import Enum

import numpy as np

from broski.audio.player import AudioPlayer
from broski.audio.vad import SileroVADDetector
from broski.audio.wakeword import WakeWordDetector

logger = logging.getLogger(__name__)


class BargeInMode(str, Enum):
    """Detection strategy for barge-in interruptions."""

    VAD_SPEECH = "VAD_SPEECH"  # VAD probability + RMS energy debounce
    WAKE_WORD = "WAKE_WORD"  # Explicit wake-word trigger only
    HYBRID = "HYBRID"  # Both wake-word and VAD speech (default)


class BargeInDetector:
    """Detects when a user interrupts broski while the assistant is speaking.

    Maintains debounce frame counters, manages cooldowns, and immediately
    cancels player playback upon confirmed user speech.
    """

    def __init__(
        self,
        player: AudioPlayer | None = None,
        vad: SileroVADDetector | None = None,
        wakeword: WakeWordDetector | None = None,
        mode: BargeInMode = BargeInMode.HYBRID,
        min_speech_frames: int = 3,
        rms_threshold: float = 600.0,
        vad_threshold: float = 0.5,
        wake_word_threshold: float = 0.35,
        cooldown_seconds: float = 0.5,
        on_barge_in: Callable[[], None] | None = None,
    ) -> None:
        self.player = player
        self.vad = vad
        self.wakeword = wakeword
        self.mode = mode
        self.min_speech_frames = max(1, min_speech_frames)
        self.rms_threshold = max(0.0, float(rms_threshold))
        self.vad_threshold = max(0.0, min(1.0, float(vad_threshold)))
        self.wake_word_threshold = max(0.0, min(1.0, float(wake_word_threshold)))
        self.cooldown_seconds = max(0.0, float(cooldown_seconds))
        self.on_barge_in = on_barge_in

        self._consecutive_speech_frames = 0
        self._cooldown_until = 0.0

    @property
    def consecutive_speech_frames(self) -> int:
        """Current count of consecutive speech frames during active playback."""
        return self._consecutive_speech_frames

    @property
    def is_in_cooldown(self) -> bool:
        """Return True if currently in post-barge-in cooldown period."""
        return time.time() < self._cooldown_until

    def reset(self) -> None:
        """Reset internal frame counters and cooldown."""
        self._consecutive_speech_frames = 0
        self._cooldown_until = 0.0

    def _trigger(self, reason: str) -> bool:
        """Execute barge-in action: stop player, notify callback, enter cooldown."""
        logger.info("Barge-in triggered (%s)! Halting playback.", reason)

        # 1. Stop playback immediately (<10ms)
        if self.player is not None and self.player.is_playing:
            self.player.stop()

        # 2. Enter cooldown
        self._cooldown_until = time.time() + self.cooldown_seconds
        self._consecutive_speech_frames = 0

        # 3. Fire callback safely
        if self.on_barge_in is not None:
            try:
                self.on_barge_in()
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                logger.warning("Error in on_barge_in callback: %s", exc)

        return True

    def process_chunk(
        self,
        chunk: np.ndarray,
        is_playing: bool | None = None,
        wakeword_score: float = 0.0,
    ) -> bool:
        """Evaluate incoming microphone audio chunk for user interruption.

        Args:
            chunk: 1D numpy array of 16-bit PCM audio samples (typically 512 samples / 32ms).
            is_playing: Explicit playback status override. If None, checks self.player.is_playing.
            wakeword_score: Pre-calculated wake-word activation score (if available).

        Returns:
            True if barge-in was confirmed and triggered, False otherwise.
        """
        if len(chunk) == 0:
            return False

        # Determine if assistant is actively speaking
        active = is_playing if is_playing is not None else (self.player is not None and self.player.is_playing)
        if not active:
            self._consecutive_speech_frames = 0
            return False

        if self.is_in_cooldown:
            return False

        # 1. Wake word check (instant trigger)
        if self.mode in (BargeInMode.WAKE_WORD, BargeInMode.HYBRID):
            if wakeword_score >= self.wake_word_threshold:
                return self._trigger(f"wake word score {wakeword_score:.2f}")

            if self.wakeword is not None and len(chunk) >= self.wakeword.chunk_size:
                score, triggered = self.wakeword.predict(chunk)
                if triggered:
                    return self._trigger(f"wake word detected ({score:.2f})")

        # 2. Neural VAD / Energy speech check (debounced)
        if self.mode in (BargeInMode.VAD_SPEECH, BargeInMode.HYBRID):
            # Calculate RMS energy
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))

            # Calculate VAD probability
            if self.vad is not None:
                prob = self.vad.get_speech_probability(chunk)
            else:
                # If no VAD model attached, fall back purely to energy threshold
                prob = 1.0 if rms >= self.rms_threshold else 0.0

            is_speech_frame = (prob >= self.vad_threshold) and (rms >= self.rms_threshold)

            if is_speech_frame:
                self._consecutive_speech_frames += 1
                if self._consecutive_speech_frames >= self.min_speech_frames:
                    return self._trigger(
                        f"speech frames={self._consecutive_speech_frames}, rms={rms:.1f}, vad={prob:.2f}"
                    )
            else:
                self._consecutive_speech_frames = max(0, self._consecutive_speech_frames - 1)

        return False

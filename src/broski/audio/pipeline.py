"""Audio Pipeline Coordinator for broski.

Connects the real-time audio components into a unified sensory loop:
Microphone Stream -> Circular Ring Buffer -> Wake Word -> Silero VAD -> Whisper STT.
"""

import logging
import threading
import time
from collections.abc import Callable
from enum import Enum

import numpy as np

from broski.audio.barge_in import BargeInDetector
from broski.audio.capture import AudioCaptureStream
from broski.audio.player import AudioPlayer
from broski.audio.ring_buffer import AudioRingBuffer
from broski.audio.stt import WhisperTranscriber
from broski.audio.vad import SileroVADDetector
from broski.audio.wakeword import WakeWordDetector
from broski.config import Settings, get_settings

logger = logging.getLogger(__name__)


class PipelineState(str, Enum):
    """Current state of the audio pipeline."""

    STOPPED = "STOPPED"
    IDLE = "IDLE"  # Passively listening for wake word
    LISTENING = "LISTENING"  # Actively collecting speech via VAD
    PROCESSING = "PROCESSING"  # Transcribing captured speech segment via Whisper
    SPEAKING = "SPEAKING"  # Active speech playback with full-duplex barge-in monitoring


class AudioPipelineCoordinator:
    """Coordinates microphone stream, wake word, VAD, and Whisper STT."""

    def __init__(
        self,
        settings: Settings | None = None,
        on_wake_word: Callable[[float], None] | None = None,
        on_speech_start: Callable[[], None] | None = None,
        on_speech_end: Callable[[], None] | None = None,
        on_transcript: Callable[[str], None] | None = None,
        on_audio_level: Callable[[float, float], None] | None = None,
        on_barge_in: Callable[[], None] | None = None,
        capture_stream: AudioCaptureStream | None = None,
        ring_buffer: AudioRingBuffer | None = None,
        wakeword_detector: WakeWordDetector | None = None,
        vad_detector: SileroVADDetector | None = None,
        transcriber: WhisperTranscriber | None = None,
        player: AudioPlayer | None = None,
        barge_in_detector: BargeInDetector | None = None,
    ) -> None:
        self.settings = settings or get_settings()

        # Callbacks
        self.on_wake_word = on_wake_word
        self.on_speech_start = on_speech_start
        self.on_speech_end = on_speech_end
        self.on_transcript = on_transcript
        self.on_audio_level = on_audio_level
        self.on_barge_in = on_barge_in

        # Components (use provided or instantiate from settings)
        self.ring_buffer = ring_buffer or AudioRingBuffer(
            sample_rate=self.settings.audio.sample_rate
        )
        self.capture_stream = capture_stream or AudioCaptureStream(
            ring_buffer=self.ring_buffer,
            device_index=self.settings.audio.input_device_index,
            target_sample_rate=self.settings.audio.sample_rate,
        )
        self.wakeword = wakeword_detector or WakeWordDetector(
            model_name=self.settings.audio.wake_word_model,
            threshold=self.settings.audio.wake_word_threshold,
            sample_rate=self.settings.audio.sample_rate,
        )
        self.vad = vad_detector or SileroVADDetector(
            threshold=self.settings.audio.vad_threshold,
            silence_duration_ms=self.settings.audio.vad_silence_duration_ms,
            sample_rate=self.settings.audio.sample_rate,
        )
        self.transcriber = transcriber or WhisperTranscriber(
            model_size=self.settings.audio.whisper_model_size,
            compute_type=self.settings.audio.whisper_compute_type,
            cpu_threads=self.settings.audio.whisper_cpu_threads,
        )
        self.player = player
        self.barge_in = barge_in_detector or BargeInDetector(
            player=self.player,
            vad=self.vad,
            wakeword=self.wakeword,
            min_speech_frames=self.settings.audio.barge_in_min_speech_frames,
            rms_threshold=self.settings.audio.barge_in_rms_threshold,
            on_barge_in=self._on_barge_in_triggered,
        )

        self._state = PipelineState.STOPPED
        self._dictation_mode = False
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()

    @property
    def state(self) -> PipelineState:
        with self._state_lock:
            return self._state

    @property
    def dictation_mode(self) -> bool:
        return self._dictation_mode

    @dictation_mode.setter
    def dictation_mode(self, value: bool) -> None:
        self._dictation_mode = value
        logger.info("Dictation mode set to %s", value)

    def _set_state(self, new_state: PipelineState) -> None:
        with self._state_lock:
            if self._state != new_state:
                logger.debug("Audio pipeline state: %s -> %s", self._state, new_state)
                self._state = new_state

    def start(self) -> None:
        """Start the audio capture stream and sensory worker thread."""
        if self.state != PipelineState.STOPPED:
            return

        self._stop_event.clear()
        self.ring_buffer.clear()
        self.capture_stream.start()

        self._set_state(PipelineState.IDLE)
        self._thread = threading.Thread(target=self._process_loop, daemon=True)
        self._thread.start()
        logger.info("AudioPipelineCoordinator started.")

    def stop(self) -> None:
        """Stop the sensory worker thread, microphone stream, and player."""
        if self.state == PipelineState.STOPPED:
            return

        self._stop_event.set()
        self.capture_stream.stop()

        if self.player is not None and self.player.is_playing:
            self.player.stop()

        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

        self._set_state(PipelineState.STOPPED)
        logger.info("AudioPipelineCoordinator stopped.")

    def _on_barge_in_triggered(self) -> None:
        """Handler invoked when user speech interrupts active playback."""
        logger.info("Barge-in event triggered! Halting playback and transitioning to LISTENING.")
        self._set_state(PipelineState.LISTENING)
        self.vad.reset()

        if self.on_barge_in:
            try:
                self.on_barge_in()
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                logger.error("Error in on_barge_in callback: %s", exc)

        if self.on_speech_start:
            try:
                self.on_speech_start()
            except (TypeError, ValueError, RuntimeError, OSError) as exc:
                logger.error("Error in on_speech_start callback: %s", exc)

    def speak(
        self,
        audio: np.ndarray,
        sample_rate: int = 22050,
        blocking: bool = False,
    ) -> None:
        """Play speech audio through AudioPlayer and transition pipeline to SPEAKING state."""
        if self.player is None:
            self.player = AudioPlayer(sample_rate=sample_rate)
            self.barge_in.player = self.player

        self._set_state(PipelineState.SPEAKING)
        self.player.play(audio, sample_rate=sample_rate, blocking=blocking)

    def _process_loop(self) -> None:
        """Main processing loop running in background thread."""
        wakeword_chunk_size = self.wakeword.chunk_size  # 1280 samples (80ms)
        vad_chunk_size = self.vad.chunk_size  # 512 samples (32ms)

        listening_timeout_samples = int(self.settings.audio.sample_rate * 5.0)  # 5s max silence
        silence_after_wake = 0
        was_speaking = False

        while not self._stop_event.is_set():
            current_state = self.state

            # ------------------------------------------------------------------
            # 1. IDLE STATE: Passively monitor for wake word
            # ------------------------------------------------------------------
            if current_state == PipelineState.IDLE:
                if self._dictation_mode:
                    # In dictation mode, skip wake word and listen immediately
                    self._set_state(PipelineState.LISTENING)
                    continue

                if self.ring_buffer.available_samples < wakeword_chunk_size:
                    time.sleep(0.01)
                    continue

                # Read audio chunk for wake word
                chunk = self.ring_buffer.read_samples(wakeword_chunk_size)
                score, is_triggered = self.wakeword.predict(chunk)

                if self.on_audio_level and len(chunk) > 0:
                    rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                    try:
                        self.on_audio_level(rms, score)
                    except (TypeError, ValueError, RuntimeError, OSError):
                        pass

                if is_triggered:
                    self._set_state(PipelineState.LISTENING)
                    silence_after_wake = 0
                    was_speaking = False
                    self.vad.reset()

                    if self.on_wake_word:
                        try:
                            self.on_wake_word(score)
                        except (TypeError, ValueError, RuntimeError, OSError) as exc:
                            logger.error("Error in on_wake_word callback: %s", exc)

            # ------------------------------------------------------------------
            # 2. LISTENING STATE: Actively segment speech via Silero VAD
            # ------------------------------------------------------------------
            elif current_state == PipelineState.LISTENING:
                if self.ring_buffer.available_samples < vad_chunk_size:
                    time.sleep(0.01)
                    continue

                chunk = self.ring_buffer.read_samples(vad_chunk_size)
                _prob, is_speaking, finished_segment = self.vad.process_chunk(chunk)

                if self.on_audio_level and len(chunk) > 0:
                    rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                    try:
                        self.on_audio_level(rms, _prob)
                    except (TypeError, ValueError, RuntimeError, OSError):
                        pass

                if is_speaking and not was_speaking:
                    was_speaking = True
                    if self.on_speech_start:
                        try:
                            self.on_speech_start()
                        except (TypeError, ValueError, RuntimeError, OSError) as exc:
                            logger.error("Error in on_speech_start callback: %s", exc)

                # Timeout if no speech detected within 5 seconds of wake word (conversational only)
                if not is_speaking:
                    if not self._dictation_mode:
                        silence_after_wake += len(chunk)
                        if silence_after_wake >= listening_timeout_samples:
                            logger.info("No speech detected within 5 seconds. Returning to IDLE.")
                            self._set_state(PipelineState.IDLE)
                            was_speaking = False
                            silence_after_wake = 0
                            self.vad.reset()
                            continue
                else:
                    silence_after_wake = 0

                # End of speech detected!
                if finished_segment is not None:
                    was_speaking = False
                    if self.on_speech_end:
                        try:
                            self.on_speech_end()
                        except (TypeError, ValueError, RuntimeError, OSError) as exc:
                            logger.error("Error in on_speech_end callback: %s", exc)

                    self._set_state(PipelineState.PROCESSING)

                    # ----------------------------------------------------------
                    # 3. PROCESSING STATE: Transcribe speech segment via Whisper
                    # ----------------------------------------------------------
                    try:
                        transcript = self.transcriber.transcribe(finished_segment)
                        if transcript and self.on_transcript:
                            self.on_transcript(transcript)
                    except (TypeError, ValueError, RuntimeError, OSError) as exc:
                        logger.error("Error during transcription: %s", exc)
                    finally:
                        # Return to IDLE (or LISTENING if dictation mode)
                        next_state = (
                            PipelineState.LISTENING if self._dictation_mode else PipelineState.IDLE
                        )
                        self._set_state(next_state)
                        self.vad.reset()

            # ------------------------------------------------------------------
            # 4. SPEAKING STATE: Assistant is talking, monitor for barge-in
            # ------------------------------------------------------------------
            elif current_state == PipelineState.SPEAKING:
                if self.player is None or not self.player.is_playing:
                    next_state = (
                        PipelineState.LISTENING if self._dictation_mode else PipelineState.IDLE
                    )
                    self._set_state(next_state)
                    continue

                if self.ring_buffer.available_samples < vad_chunk_size:
                    time.sleep(0.01)
                    continue

                chunk = self.ring_buffer.read_samples(vad_chunk_size)

                if self.on_audio_level and len(chunk) > 0:
                    rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
                    try:
                        self.on_audio_level(rms, 0.0)
                    except (TypeError, ValueError, RuntimeError, OSError):
                        pass

                if self.settings.audio.barge_in_enabled:
                    interrupted = self.barge_in.process_chunk(chunk, is_playing=True)
                    if interrupted:
                        # Seed VAD with the interrupting chunk so opening speech frames are preserved
                        self.vad.process_chunk(chunk)
                        was_speaking = True
                        silence_after_wake = 0
                        continue

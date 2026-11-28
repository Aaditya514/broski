"""Local Speech-to-Text (STT) engine powered by faster-whisper.

Runs CTranslate2 INT8 quantized models locally on CPU, capped at 2 worker threads
to maintain sub-second transcription latency without causing laptop thermal throttling.
"""

import logging
from pathlib import Path

import numpy as np

from broski.config import get_settings

logger = logging.getLogger(__name__)


class WhisperTranscriber:
    """Local Speech-to-Text transcriber using faster-whisper on CPU."""

    def __init__(
        self,
        model_size: str = "base.en",
        compute_type: str = "int8",
        cpu_threads: int = 2,
        download_root: Path | str | None = None,
    ) -> None:
        self.model_size = model_size
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads

        if download_root is None:
            settings = get_settings()
            self.download_root = settings.paths.models_dir / "whisper"
        else:
            self.download_root = Path(download_root)

        self._model = None

    def _init_model(self) -> None:
        """Lazily initialize faster-whisper WhisperModel."""
        if self._model is not None:
            return

        from faster_whisper import WhisperModel

        self.download_root.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Loading faster-whisper model '%s' (compute_type=%s, cpu_threads=%d, cache_dir=%s)...",
            self.model_size,
            self.compute_type,
            self.cpu_threads,
            self.download_root,
        )

        self._model = WhisperModel(
            self.model_size,
            device="cpu",
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
            download_root=str(self.download_root),
        )
        logger.info("faster-whisper model '%s' loaded successfully.", self.model_size)

    def transcribe(
        self,
        audio: np.ndarray | bytes,
        beam_size: int = 5,
        language: str | None = "en",
    ) -> str:
        """Transcribe 16kHz mono audio into text.

        Args:
            audio: 1D numpy array (float32 or int16) or raw 16-bit PCM bytes.
            beam_size: Beam search width (default 5 for optimal accuracy).
            language: Language code ('en' for English-only, None for auto-detection).

        Returns:
            Clean, stripped transcription string.
        """
        self._init_model()
        assert self._model is not None

        # Convert input audio to 1D float32 normalized to [-1.0, 1.0]
        if isinstance(audio, (bytes, bytearray)):
            audio_samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        elif isinstance(audio, np.ndarray):
            if audio.ndim > 1:
                audio = audio.flatten()
            if audio.dtype == np.int16:
                audio_samples = audio.astype(np.float32) / 32768.0
            elif np.issubdtype(audio.dtype, np.floating):
                audio_samples = np.clip(audio, -1.0, 1.0).astype(np.float32)
            else:
                audio_samples = audio.astype(np.float32)
        else:
            raise TypeError(f"Unsupported audio type: {type(audio)}")

        # Check minimum length (ignore segments shorter than 100ms = 1600 samples)
        if len(audio_samples) < 1600:
            return ""

        # Dynamic Peak Gain Normalization
        # Boost quiet microphone input (e.g. Bluetooth earphones) to Whisper's optimal dynamic range
        peak = float(np.max(np.abs(audio_samples)))
        if peak > 1e-4:
            audio_samples = (audio_samples / peak) * 0.95

        default_prompt = (
            "Broski, a Windows AI desktop voice assistant. Commands: open Obsidian, launch Spotify, "
            "open Riot Games, launch Valorant, Steam, Discord, Chrome, what time is it, tell me a joke, summarize notes, write code."
        )

        # Silero VAD has already segmented the speech, so vad_filter can remain False
        segments, _info = self._model.transcribe(
            audio_samples,
            beam_size=beam_size,
            language=language,
            vad_filter=False,
            condition_on_previous_text=False,
            initial_prompt=default_prompt,
        )

        # Collect segment texts
        transcript_parts = [segment.text.strip() for segment in segments if segment.text.strip()]
        full_transcript = " ".join(transcript_parts).strip()

        logger.info(
            "Transcribed %d samples (%.2fs) -> '%s'",
            len(audio_samples),
            len(audio_samples) / 16000.0,
            full_transcript,
        )
        return full_transcript

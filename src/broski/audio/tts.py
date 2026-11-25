"""Neural Text-to-Speech (TTS) synthesizer for broski using Piper TTS.

Provides fast, high-quality, local speech synthesis running entirely on CPU
using ONNX neural voice models (e.g. en_US-lessac-medium).
"""

import io
import logging
import time
import wave
from collections.abc import Iterator
from pathlib import Path

import numpy as np
from piper.config import SynthesisConfig
from piper.voice import PiperVoice

from broski.config import get_settings

logger = logging.getLogger(__name__)


def resolve_voice_paths(
    voice_name: str = "en_US-lessac-medium", models_dir: Path | None = None
) -> tuple[Path, Path]:
    """Resolve ONNX model file and JSON config file for a Piper voice."""
    if models_dir is None:
        settings = get_settings()
        piper_dir = settings.paths.models_dir / "piper"
    else:
        piper_dir = models_dir

    # Support passing direct path or voice name
    onnx_path = Path(voice_name)
    if not onnx_path.exists():
        # Check in piper_dir
        candidate = piper_dir / f"{voice_name}.onnx"
        if candidate.exists():
            onnx_path = candidate
        else:
            # Check with exact stem
            onnx_path = piper_dir / f"{Path(voice_name).stem}.onnx"

    json_path = Path(f"{onnx_path}.json")

    return onnx_path, json_path


class PiperSynthesizer:
    """Local neural speech synthesizer powered by Piper TTS and ONNX."""

    def __init__(
        self,
        voice_name: str = "en_US-lessac-medium",
        models_dir: Path | None = None,
        length_scale: float = 1.0,
        auto_load: bool = False,
    ) -> None:
        self.voice_name = voice_name
        self.models_dir = models_dir
        self.length_scale = length_scale

        self._voice: PiperVoice | None = None
        self._sample_rate: int = 22050
        self._synthesis_config = SynthesisConfig(length_scale=self.length_scale)

        if auto_load:
            self._ensure_loaded()

    @property
    def is_loaded(self) -> bool:
        """Return True if the Piper voice model is loaded in memory."""
        return self._voice is not None

    @property
    def sample_rate(self) -> int:
        """Output audio sampling rate in Hz (typically 22050 Hz)."""
        if self._voice is not None:
            return self._voice.config.sample_rate
        return self._sample_rate

    def _ensure_loaded(self) -> PiperVoice:
        """Lazily load the Piper ONNX voice model into memory."""
        if self._voice is not None:
            return self._voice

        onnx_path, json_path = resolve_voice_paths(self.voice_name, self.models_dir)

        if not onnx_path.exists():
            raise FileNotFoundError(
                f"Piper voice model not found at '{onnx_path}'. "
                f"Download the model and place it in 'data/models/piper/'."
            )
        if not json_path.exists():
            raise FileNotFoundError(
                f"Piper voice config not found at '{json_path}'. "
                f"Ensure the corresponding .onnx.json file exists alongside the model."
            )

        logger.info("Loading Piper TTS voice model from '%s'...", onnx_path)
        t0 = time.time()
        self._voice = PiperVoice.load(model_path=str(onnx_path), config_path=str(json_path))
        self._sample_rate = self._voice.config.sample_rate
        logger.info(
            "Piper TTS voice '%s' loaded in %.3fs (Sample rate: %d Hz).",
            self.voice_name,
            time.time() - t0,
            self._sample_rate,
        )
        return self._voice

    def synthesize_stream(self, text: str) -> Iterator[np.ndarray]:
        """Synthesize text into a stream of 16-bit PCM numpy audio chunks.

        Args:
            text: Spoken sentence or prompt to synthesize.

        Yields:
            1D numpy arrays of int16 audio samples for each sentence/chunk.
        """
        clean_text = text.strip()
        if not clean_text:
            return

        voice = self._ensure_loaded()

        for chunk in voice.synthesize(clean_text, syn_config=self._synthesis_config):
            audio_int16 = chunk.audio_int16_array
            if len(audio_int16) > 0:
                yield audio_int16

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Synthesize text and return full audio array and sample rate.

        Args:
            text: Text to synthesize.

        Returns:
            Tuple of (1D int16 audio numpy array, sample_rate_hz).
        """
        chunks = list(self.synthesize_stream(text))
        if not chunks:
            return np.empty(0, dtype=np.int16), self.sample_rate

        concatenated = np.concatenate(chunks)
        return concatenated, self.sample_rate

    def synthesize_to_wav(self, text: str, output_path: Path | str) -> Path:
        """Synthesize text and write directly to a standard WAV audio file.

        Args:
            text: Text to synthesize.
            output_path: Target .wav file path.

        Returns:
            Resolved Path of the saved WAV file.
        """
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)

        voice = self._ensure_loaded()

        with wave.open(str(out_path), "wb") as wav_file:
            voice.synthesize_wav(
                text=text,
                wav_file=wav_file,
                syn_config=self._synthesis_config,
                set_wav_format=True,
            )

        logger.info("Synthesized speech saved to '%s' (%d bytes).", out_path, out_path.stat().st_size)
        return out_path

    def synthesize_to_bytes(self, text: str) -> bytes:
        """Synthesize text into raw in-memory WAV container bytes.

        Useful for non-blocking stream delivery without disk writes.
        """
        voice = self._ensure_loaded()
        buf = io.BytesIO()

        with wave.open(buf, "wb") as wav_file:
            voice.synthesize_wav(
                text=text,
                wav_file=wav_file,
                syn_config=self._synthesis_config,
                set_wav_format=True,
            )

        return buf.getvalue()

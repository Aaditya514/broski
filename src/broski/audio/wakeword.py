"""Wake word detection engine using openWakeWord.

Provides continuous, ultra-low-CPU acoustic trigger detection (<1.5% CPU)
running locally on 16kHz audio chunks.
"""

import logging
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """Detects spoken wake phrases (e.g. 'Hey jarvis' / 'Hey broski') using openWakeWord."""

    def __init__(
        self,
        model_name: str = "hey_jarvis",
        threshold: float = 0.5,
        cooldown_seconds: float = 1.5,
        sample_rate: int = 16000,
    ) -> None:
        self.model_name = model_name
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.sample_rate = sample_rate
        self.chunk_size = 1280  # 1280 samples @ 16kHz = 80ms chunk

        self._model = None
        self._last_trigger_time = 0.0
        self._target_key: str | None = None

    def _init_model(self) -> None:
        """Lazily initialize openWakeWord model."""
        if self._model is not None:
            return

        import openwakeword
        from openwakeword.model import Model

        # Resolve model path or bundled name
        if Path(self.model_name).exists():
            model_target = self.model_name
        else:
            # Check available bundled ONNX models
            available_paths = openwakeword.get_pretrained_model_paths("onnx")
            matched = [
                p for p in available_paths if self.model_name.lower() in Path(p).stem.lower()
            ]
            if matched:
                model_target = matched[0]
            else:
                # Fall back to first available bundled model
                model_target = available_paths[0] if available_paths else self.model_name
                logger.warning(
                    "Model %s not found in bundled openWakeWord models. Falling back to %s",
                    self.model_name,
                    model_target,
                )

        # Initialize openWakeWord Model using ONNX runtime
        self._model = Model(wakeword_models=[model_target], inference_framework="onnx")
        # Model keys in predictions
        model_keys = list(self._model.models.keys())
        self._target_key = model_keys[0] if model_keys else self.model_name
        logger.info(
            "WakeWordDetector initialized with model '%s' (Target key: %s, Threshold: %.2f)",
            model_target,
            self._target_key,
            self.threshold,
        )

    def reset(self) -> None:
        """Reset internal prediction history and buffers."""
        if self._model is not None:
            self._model.reset()
        self._last_trigger_time = 0.0

    def predict(self, audio_chunk: np.ndarray) -> tuple[float, bool]:
        """Process incoming 16kHz audio chunk and return (score, is_triggered).

        Args:
            audio_chunk: 1D numpy array of 16-bit audio (typically 1280 samples = 80ms).

        Returns:
            (confidence_score, triggered_boolean)
        """
        self._init_model()
        assert self._model is not None

        # Ensure int16
        if audio_chunk.dtype != np.int16:
            if np.issubdtype(audio_chunk.dtype, np.floating):
                chunk_int16 = (np.clip(audio_chunk, -1.0, 1.0) * 32767.0).astype(np.int16)
            else:
                chunk_int16 = audio_chunk.astype(np.int16)
        else:
            chunk_int16 = audio_chunk

        # Pad or slice to at least 1280 samples if needed
        if len(chunk_int16) < self.chunk_size:
            chunk_int16 = np.pad(chunk_int16, (0, self.chunk_size - len(chunk_int16)))

        # Run openWakeWord prediction
        prediction = self._model.predict(chunk_int16)

        # Extract target score
        score = 0.0
        if self._target_key and self._target_key in prediction:
            score = float(prediction[self._target_key])
        elif prediction:
            # First available score
            score = float(next(iter(prediction.values())))

        current_time = time.time()
        is_triggered = False

        if (
            score >= self.threshold
            and current_time - self._last_trigger_time >= self.cooldown_seconds
        ):
            is_triggered = True
            self._last_trigger_time = current_time
            self._model.reset()
            logger.info("Wake word TRIGGERED! Confidence: %.3f", score)

        return score, is_triggered

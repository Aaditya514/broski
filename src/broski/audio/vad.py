"""Neural Voice Activity Detection (VAD) using Silero VAD v4/v5 ONNX model.

Processes 16kHz audio chunks (32ms / 512 samples), calculates speech probability,
filters out background noise, and detects end-of-speech silence pauses.
"""

import logging
from pathlib import Path

import numpy as np
import onnxruntime as ort

from broski.config import get_settings

logger = logging.getLogger(__name__)


def find_silero_model_path() -> Path:
    """Locate bundled or cached silero_vad.onnx model."""
    # 1. Check if silero_vad package is installed
    try:
        import silero_vad

        bundled = Path(silero_vad.__file__).parent / "data" / "silero_vad.onnx"
        if bundled.exists():
            return bundled
    except ImportError:
        pass

    # 2. Check local models directory
    settings = get_settings()
    local_model = settings.paths.models_dir / "vad" / "silero_vad.onnx"
    if local_model.exists():
        return local_model

    # 3. Fallback to package search in site-packages
    site_packages = Path(__file__).resolve().parents[4] / ".venv" / "Lib" / "site-packages"
    candidate = site_packages / "silero_vad" / "data" / "silero_vad.onnx"
    if candidate.exists():
        return candidate

    return local_model


class SileroVADDetector:
    """Real-time Voice Activity Detector powered by Silero VAD ONNX."""

    def __init__(
        self,
        model_path: Path | str | None = None,
        threshold: float = 0.5,
        silence_duration_ms: int = 600,
        sample_rate: int = 16000,
    ) -> None:
        self.threshold = threshold
        self.silence_duration_ms = silence_duration_ms
        self.sample_rate = sample_rate
        self.chunk_size = 512  # 512 samples @ 16kHz = 32ms

        self.model_path = Path(model_path) if model_path else find_silero_model_path()
        self._session: ort.InferenceSession | None = None
        self._state = np.zeros((2, 1, 128), dtype=np.float32)

        # State tracking for speech segmentation
        self.is_speaking = False
        self._silent_samples_accumulated = 0
        self._silence_threshold_samples = int(
            self.sample_rate * (self.silence_duration_ms / 1000.0)
        )
        self._speech_buffer: list[np.ndarray] = []

    def _init_session(self) -> None:
        """Lazily initialize ONNX runtime inference session with CPU optimization."""
        if self._session is not None:
            return

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"Silero VAD model not found at {self.model_path}. "
                "Ensure silero-vad is installed or model is placed in data/models/vad/."
            )

        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        self._session = ort.InferenceSession(
            str(self.model_path), sess_options=opts, providers=["CPUExecutionProvider"]
        )
        self.reset()
        logger.info("Silero VAD ONNX session initialized from %s", self.model_path)

    def reset(self) -> None:
        """Reset internal recurrent state, silence counter, and active speech buffer."""
        # Check model state tensor shape dynamically if session exists
        if self._session:
            state_input = [inp for inp in self._session.get_inputs() if inp.name == "state"]
            if state_input:
                shape = state_input[0].shape
                # shape is typically (2, 1, 128) or (2, 1, 64)
                dim = shape[2] if len(shape) > 2 and isinstance(shape[2], int) else 128
                self._state = np.zeros((2, 1, dim), dtype=np.float32)
            else:
                self._state = np.zeros((2, 1, 128), dtype=np.float32)
        else:
            self._state = np.zeros((2, 1, 128), dtype=np.float32)

        self.is_speaking = False
        self._silent_samples_accumulated = 0
        self._speech_buffer.clear()

    def get_speech_probability(self, chunk: np.ndarray) -> float:
        """Run single 512-sample (32ms) frame through Silero VAD and return probability [0.0, 1.0]."""
        self._init_session()
        assert self._session is not None

        # Ensure float32 in range [-1.0, 1.0]
        if chunk.dtype == np.int16:
            audio_float = chunk.astype(np.float32) / 32768.0
        elif np.issubdtype(chunk.dtype, np.floating):
            audio_float = chunk.astype(np.float32)
        else:
            audio_float = chunk.astype(np.float32)

        # Pad or slice to exactly 512 samples
        if len(audio_float) < self.chunk_size:
            audio_float = np.pad(audio_float, (0, self.chunk_size - len(audio_float)))
        elif len(audio_float) > self.chunk_size:
            audio_float = audio_float[: self.chunk_size]

        input_tensor = audio_float[np.newaxis, :]  # Shape (1, 512)
        sr_tensor = np.array(self.sample_rate, dtype=np.int64)

        inputs = {
            "input": input_tensor,
            "state": self._state,
            "sr": sr_tensor,
        }

        # Check model input names in case model uses alternative names
        input_names = {inp.name for inp in self._session.get_inputs()}
        feed_dict = {k: v for k, v in inputs.items() if k in input_names}

        outs = self._session.run(None, feed_dict)
        prob = float(outs[0][0][0]) if outs[0].ndim > 1 else float(outs[0][0])
        if len(outs) > 1:
            self._state = outs[1]

        return prob

    def process_chunk(self, audio_chunk: np.ndarray) -> tuple[float, bool, np.ndarray | None]:
        """Process incoming audio, update state machine, and emit speech segments.

        Returns:
            (speech_probability, is_speaking, finished_segment_or_None)
        """
        # Ensure int16 for buffer storage
        if audio_chunk.dtype != np.int16:
            if np.issubdtype(audio_chunk.dtype, np.floating):
                chunk_int16 = (np.clip(audio_chunk, -1.0, 1.0) * 32767.0).astype(np.int16)
            else:
                chunk_int16 = audio_chunk.astype(np.int16)
        else:
            chunk_int16 = audio_chunk

        rms = (
            float(np.sqrt(np.mean(chunk_int16.astype(np.float32) ** 2)))
            if len(chunk_int16) > 0
            else 0.0
        )
        prob = self.get_speech_probability(chunk_int16)
        finished_segment = None

        # Speech detected if VAD probability is high OR significant vocal audio energy is present
        is_speech_frame = (prob >= self.threshold) or (rms >= 600.0 and prob >= 0.05)

        if is_speech_frame:
            # User is speaking
            self.is_speaking = True
            self._silent_samples_accumulated = 0
            self._speech_buffer.append(chunk_int16)
        else:
            # Silence or ambient noise
            if self.is_speaking:
                self._speech_buffer.append(chunk_int16)
                self._silent_samples_accumulated += len(chunk_int16)

                # Check if silence duration exceeded
                if self._silent_samples_accumulated >= self._silence_threshold_samples:
                    if self._speech_buffer:
                        finished_segment = np.concatenate(self._speech_buffer)

                    self.is_speaking = False
                    self._speech_buffer.clear()
                    self._silent_samples_accumulated = 0
                    self.reset()

        return prob, self.is_speaking, finished_segment

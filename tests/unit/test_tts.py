"""Unit tests for broski PiperSynthesizer neural text-to-speech."""

import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from broski.audio.tts import PiperSynthesizer, resolve_voice_paths


def test_resolve_voice_paths_existing(tmp_path: Path) -> None:
    """Verify resolve_voice_paths returns matching onnx and json paths."""
    model_file = tmp_path / "test-voice.onnx"
    json_file = tmp_path / "test-voice.onnx.json"
    model_file.write_text("dummy onnx")
    json_file.write_text("dummy json")

    onnx_res, json_res = resolve_voice_paths("test-voice", models_dir=tmp_path)
    assert onnx_res == model_file
    assert json_res == json_file


def test_piper_synthesizer_lazy_loading() -> None:
    """Verify synthesizer does not load model until first synthesis call."""
    synth = PiperSynthesizer(voice_name="nonexistent_voice", auto_load=False)
    assert synth.is_loaded is False


def test_piper_synthesizer_missing_model(tmp_path: Path) -> None:
    """Verify FileNotFoundError is raised when voice model file does not exist."""
    synth = PiperSynthesizer(voice_name="nonexistent_voice", models_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="Piper voice model not found"):
        synth.synthesize("Hello world")


def test_piper_synthesizer_mocked_synthesis(tmp_path: Path) -> None:
    """Verify synthesis flow and chunk concatenation using mocked PiperVoice."""
    mock_onnx = tmp_path / "mock.onnx"
    mock_json = tmp_path / "mock.onnx.json"
    mock_onnx.write_text("dummy onnx")
    mock_json.write_text("dummy json")

    with (
        patch("broski.audio.tts.resolve_voice_paths") as mock_paths,
        patch("piper.voice.PiperVoice.load") as mock_load,
    ):
        mock_paths.return_value = (mock_onnx, mock_json)

        # Setup mock voice
        mock_voice = MagicMock()
        mock_voice.config.sample_rate = 22050

        # Create mock audio chunk
        mock_chunk1 = MagicMock()
        mock_chunk1.audio_int16_array = np.array([100, 200, 300], dtype=np.int16)
        mock_chunk2 = MagicMock()
        mock_chunk2.audio_int16_array = np.array([400, 500], dtype=np.int16)

        mock_voice.synthesize.return_value = [mock_chunk1, mock_chunk2]
        mock_load.return_value = mock_voice

        synth = PiperSynthesizer(voice_name="mock_voice")

        # 1. Test stream
        chunks = list(synth.synthesize_stream("Hello broski"))
        assert len(chunks) == 2
        assert np.array_equal(chunks[0], np.array([100, 200, 300], dtype=np.int16))

        # 2. Test full synthesis
        audio, sr = synth.synthesize("Hello broski")
        assert sr == 22050
        assert np.array_equal(audio, np.array([100, 200, 300, 400, 500], dtype=np.int16))

        # 3. Test empty text
        empty_audio, empty_sr = synth.synthesize("   ")
        assert len(empty_audio) == 0
        assert empty_sr == 22050


def test_piper_synthesizer_to_wav(tmp_path: Path) -> None:
    """Verify synthesize_to_wav creates a valid WAV file."""
    mock_onnx = tmp_path / "mock.onnx"
    mock_json = tmp_path / "mock.onnx.json"
    mock_onnx.write_text("dummy onnx")
    mock_json.write_text("dummy json")

    with (
        patch("broski.audio.tts.resolve_voice_paths") as mock_paths,
        patch("piper.voice.PiperVoice.load") as mock_load,
    ):
        mock_paths.return_value = (mock_onnx, mock_json)

        mock_voice = MagicMock()
        mock_voice.config.sample_rate = 22050

        def fake_synthesize_wav(text, wav_file, **kwargs):
            wav_file.setframerate(22050)
            wav_file.setsampwidth(2)
            wav_file.setnchannels(1)
            wav_file.writeframes(np.array([100, 200, 300], dtype=np.int16).tobytes())

        mock_voice.synthesize_wav.side_effect = fake_synthesize_wav
        mock_load.return_value = mock_voice

        synth = PiperSynthesizer(voice_name="mock_voice")
        wav_out = tmp_path / "output.wav"
        result_path = synth.synthesize_to_wav("Hello world", wav_out)

        assert result_path.exists()
        assert result_path == wav_out

        # Verify WAV properties
        with wave.open(str(result_path), "rb") as wf:
            assert wf.getframerate() == 22050
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getnframes() == 3


def test_piper_synthesizer_live_smoke() -> None:
    """Smoke test: verify real Piper ONNX model synthesizes real speech."""
    model_path = Path("data/models/piper/en_US-lessac-medium.onnx")
    if not model_path.exists():
        pytest.skip("Piper model en_US-lessac-medium.onnx not found on host.")

    synth = PiperSynthesizer(voice_name="en_US-lessac-medium")
    audio, sr = synth.synthesize("Test.")

    assert sr == 22050
    assert len(audio) > 1000
    assert audio.dtype == np.int16
    assert np.max(np.abs(audio)) > 0

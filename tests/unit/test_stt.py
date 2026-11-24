"""Unit tests for broski WhisperTranscriber (STT)."""

from unittest.mock import MagicMock

import numpy as np

from broski.audio.stt import WhisperTranscriber


def test_whisper_transcriber_initialization(tmp_path) -> None:
    """Verify WhisperTranscriber initializes with INT8 quantization and 2 CPU threads."""
    stt = WhisperTranscriber(
        model_size="base.en",
        compute_type="int8",
        cpu_threads=2,
        download_root=tmp_path / "whisper",
    )
    assert stt.model_size == "base.en"
    assert stt.compute_type == "int8"
    assert stt.cpu_threads == 2
    assert stt.download_root == tmp_path / "whisper"
    assert stt._model is None


def test_whisper_transcribe_short_audio_returns_empty() -> None:
    """Verify audio shorter than 100ms (1600 samples) returns empty string without invoking model."""
    stt = WhisperTranscriber()
    stt._model = MagicMock()

    short_audio = np.zeros(500, dtype=np.int16)
    result = stt.transcribe(short_audio)
    assert result == ""
    stt._model.transcribe.assert_not_called()


def test_whisper_transcribe_mock() -> None:
    """Verify transcribe processes audio arrays, calls WhisperModel, and formats text."""
    stt = WhisperTranscriber()

    # Mock WhisperModel output
    mock_model = MagicMock()
    mock_segment1 = MagicMock()
    mock_segment1.text = "Hello world"
    mock_segment2 = MagicMock()
    mock_segment2.text = "this is broski"

    mock_model.transcribe.return_value = ([mock_segment1, mock_segment2], MagicMock())
    stt._model = mock_model

    # 1 second of 16kHz audio (16,000 samples)
    audio_int16 = np.ones(16000, dtype=np.int16) * 1000
    text = stt.transcribe(audio_int16)

    assert text == "Hello world this is broski"
    mock_model.transcribe.assert_called_once()
    args, kwargs = mock_model.transcribe.call_args
    # Verify input audio was converted to float32
    passed_audio = args[0]
    assert passed_audio.dtype == np.float32
    assert kwargs["beam_size"] == 5
    assert kwargs["vad_filter"] is False


def test_whisper_transcribe_raw_bytes() -> None:
    """Verify raw 16-bit PCM bytes input is properly handled."""
    stt = WhisperTranscriber()

    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = "Testing byte input"
    mock_model.transcribe.return_value = ([mock_segment], MagicMock())
    stt._model = mock_model

    audio_bytes = (np.ones(16000, dtype=np.int16) * 500).tobytes()
    text = stt.transcribe(audio_bytes)
    assert text == "Testing byte input"

"""Unit tests for broski GeminiBrainClient and speech prompt utilities."""

from unittest.mock import MagicMock, patch

import pytest

from broski.brain.client import GeminiBrainClient
from broski.brain.prompts import clean_for_speech


def test_clean_for_speech_markdown_removal() -> None:
    """Verify clean_for_speech strips formatting noise for TTS output."""
    raw = (
        "# Title\n\n"
        "Here is **bold** text, *italic* word, and a [link](https://example.com).\n"
        "* First point\n"
        "* Second point with `code`\n"
        "```python\ndef test(): pass\n```"
    )
    cleaned = clean_for_speech(raw)

    assert "#" not in cleaned
    assert "**" not in cleaned
    assert "*" not in cleaned
    assert "`" not in cleaned
    assert "https://example.com" not in cleaned
    assert "bold" in cleaned
    assert "italic" in cleaned
    assert "link" in cleaned
    assert "First point" in cleaned
    assert "Second point with code" in cleaned


def test_clean_for_speech_empty_or_plain() -> None:
    """Verify empty and plain strings pass through cleanly."""
    assert clean_for_speech("") == ""
    assert clean_for_speech("Hello world!") == "Hello world!"


def test_gemini_brain_client_unconfigured() -> None:
    """Verify client reports unconfigured and raises ValueError when key is missing."""
    with patch("broski.brain.client.get_settings") as mock_settings:
        mock_settings.return_value.brain.api_key = None
        mock_settings.return_value.brain.model = "gemini-3.1-flash-lite"
        mock_settings.return_value.brain.temperature = 0.7

        client = GeminiBrainClient(api_key=None)
        assert client.is_configured is False

        with pytest.raises(ValueError, match="Gemini API key is not configured"):
            client.generate("Hello")


def test_gemini_brain_client_generate_mocked() -> None:
    """Verify generate invokes models.generate_content with expected configuration."""
    with patch("google.genai.Client") as mock_genai_cls:
        mock_genai_instance = MagicMock()
        mock_genai_cls.return_value = mock_genai_instance

        mock_resp = MagicMock()
        mock_resp.text = "**Broski** is ready."
        mock_genai_instance.models.generate_content.return_value = mock_resp

        client = GeminiBrainClient(api_key="dummy-test-key", model="gemini-3.1-flash-lite")
        assert client.is_configured is True

        # 1. Cleaned speech (default)
        result = client.generate("Who are you?")
        assert result == "Broski is ready."

        # Verify API call
        mock_genai_cls.assert_called_once_with(api_key="dummy-test-key")
        mock_genai_instance.models.generate_content.assert_called_once()


def test_gemini_brain_client_generate_stream_mocked() -> None:
    """Verify generate_stream yields text chunks from models.generate_content_stream."""
    with patch("google.genai.Client") as mock_genai_cls:
        mock_genai_instance = MagicMock()
        mock_genai_cls.return_value = mock_genai_instance

        chunk1 = MagicMock()
        chunk1.text = "Hello "
        chunk2 = MagicMock()
        chunk2.text = "from stream!"
        mock_genai_instance.models.generate_content_stream.return_value = [chunk1, chunk2]

        client = GeminiBrainClient(api_key="dummy-test-key")
        chunks = list(client.generate_stream("Tell me something"))

        assert chunks == ["Hello ", "from stream!"]


def test_gemini_brain_client_multi_turn_chat_mocked() -> None:
    """Verify multi-turn chat session maintains state and allows reset."""
    with patch("google.genai.Client") as mock_genai_cls:
        mock_genai_instance = MagicMock()
        mock_genai_cls.return_value = mock_genai_instance

        mock_chat = MagicMock()
        mock_genai_instance.chats.create.return_value = mock_chat

        mock_resp1 = MagicMock()
        mock_resp1.text = "Turn 1 answer."
        mock_resp2 = MagicMock()
        mock_resp2.text = "Turn 2 answer."
        mock_chat.send_message.side_effect = [mock_resp1, mock_resp2]

        client = GeminiBrainClient(api_key="dummy-test-key")

        # Turn 1
        r1 = client.chat("First question")
        assert r1 == "Turn 1 answer."
        mock_genai_instance.chats.create.assert_called_once()

        # Turn 2: uses existing chat session
        r2 = client.chat("Follow up question")
        assert r2 == "Turn 2 answer."
        assert mock_genai_instance.chats.create.call_count == 1
        assert mock_chat.send_message.call_count == 2

        # Reset chat
        client.reset_chat()
        assert client._chat_session is None

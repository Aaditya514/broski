"""Google Gemini Cloud Brain client for broski using the official google-genai SDK.

Provides high-level conversational reasoning, multi-turn chat sessions,
and streaming token generation for low-latency voice synthesis.
"""

import logging
from collections.abc import Iterator
from typing import Any

from google import genai
from google.genai import types

from broski.brain.prompts import DEFAULT_SYSTEM_INSTRUCTION, clean_for_speech
from broski.config import get_settings

logger = logging.getLogger(__name__)


class GeminiBrainClient:
    """Conversational reasoning engine powered by Google Gemini API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        system_instruction: str = DEFAULT_SYSTEM_INSTRUCTION,
    ) -> None:
        settings = get_settings()

        self._api_key = api_key or (
            settings.brain.api_key.get_secret_value() if settings.brain.api_key else None
        )
        self.model = model or settings.brain.model
        self.temperature = (
            temperature if temperature is not None else settings.brain.temperature
        )
        self.system_instruction = system_instruction

        self._client: genai.Client | None = None
        self._chat_session: Any = None

    @property
    def is_configured(self) -> bool:
        """Return True if an API key is available for cloud reasoning."""
        return bool(self._api_key)

    def _ensure_client(self) -> genai.Client:
        """Lazily initialize the google-genai Client."""
        if self._client is not None:
            return self._client

        if not self._api_key:
            raise ValueError(
                "Gemini API key is not configured. Set GEMINI_API_KEY in your .env file."
            )

        self._client = genai.Client(api_key=self._api_key)
        logger.info("Initialized GeminiBrainClient with model '%s'.", self.model)
        return self._client

    def _get_config(
        self, custom_instruction: str | None = None
    ) -> types.GenerateContentConfig:
        """Build GenerateContentConfig with system instruction and temperature."""
        instruction = (
            custom_instruction
            if custom_instruction is not None
            else self.system_instruction
        )
        return types.GenerateContentConfig(
            system_instruction=instruction,
            temperature=self.temperature,
        )

    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        clean_speech: bool = True,
    ) -> str:
        """Generate a single-turn completion for a prompt.

        Args:
            prompt: User question or command.
            system_instruction: Optional system instruction override.
            clean_speech: If True, strips markdown formatting for natural TTS.

        Returns:
            Generated response string.
        """
        client = self._ensure_client()
        config = self._get_config(custom_instruction=system_instruction)

        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=config,
        )

        raw_text = response.text or ""
        return clean_for_speech(raw_text) if clean_speech else raw_text

    def generate_stream(
        self,
        prompt: str,
        system_instruction: str | None = None,
    ) -> Iterator[str]:
        """Stream completion tokens in real time from Gemini API.

        Args:
            prompt: User question or command.
            system_instruction: Optional system instruction override.

        Yields:
            Text chunks as they arrive from the cloud stream.
        """
        client = self._ensure_client()
        config = self._get_config(custom_instruction=system_instruction)

        for chunk in client.models.generate_content_stream(
            model=self.model,
            contents=prompt,
            config=config,
        ):
            if chunk.text:
                yield chunk.text

    def _ensure_chat(self) -> Any:
        """Lazily initialize multi-turn chat session."""
        if self._chat_session is None:
            client = self._ensure_client()
            config = self._get_config()
            self._chat_session = client.chats.create(model=self.model, config=config)
        return self._chat_session

    def chat(self, message: str, clean_speech: bool = True) -> str:
        """Send a message in a multi-turn conversation and return response.

        Maintains dialogue history across turns.

        Args:
            message: User query or follow-up prompt.
            clean_speech: If True, strips markdown symbols for natural TTS.

        Returns:
            Assistant response string.
        """
        chat = self._ensure_chat()
        response = chat.send_message(message)
        raw_text = response.text or ""
        return clean_for_speech(raw_text) if clean_speech else raw_text

    def chat_stream(self, message: str) -> Iterator[str]:
        """Stream multi-turn conversation response chunks in real time.

        Args:
            message: User query or follow-up prompt.

        Yields:
            Text chunks as generated by the model.
        """
        chat = self._ensure_chat()
        for chunk in chat.send_message_stream(message):
            if chunk.text:
                yield chunk.text

    def reset_chat(self) -> None:
        """Reset active multi-turn conversation history."""
        self._chat_session = None
        logger.info("Multi-turn conversation session reset.")

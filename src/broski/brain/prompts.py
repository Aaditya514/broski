"""Prompt templates and text pre-processing for broski conversational brain."""

import re

DEFAULT_SYSTEM_INSTRUCTION = """You are Broski, an ultra-fast, privacy-first AI desktop voice assistant running on Windows 11.
Your creator and user is a power user and software developer.

CONVERSATIONAL GUIDELINES FOR VOICE SYNTHESIS:
1. Speak naturally, concisely, and directly. Keep answers to 1-3 sentences unless asked for an in-depth explanation.
2. NEVER output markdown symbols, asterisks (*), hashtags (#), bullet points, or code blocks in voice conversations.
3. Pronounce numbers, dates, and abbreviations cleanly.
4. Be helpful, sharp, and friendly, like a reliable engineering peer.
5. If asked to perform an action or run a command, confirm clearly and succinctly.
"""


def clean_for_speech(text: str) -> str:
    """Strip markdown formatting, symbols, and formatting noise for natural text-to-speech.

    Removes bold/italic asterisks, headers, markdown links, code backticks,
    and bullet markers so TTS does not pronounce 'asterisk asterisk'.

    Args:
        text: Raw LLM output string.

    Returns:
        Spoken-clean string suitable for Piper TTS.
    """
    if not text:
        return ""

    # Remove code blocks ```...```
    cleaned = re.sub(r"```[\s\S]*?```", " Code snippet. ", text)

    # Remove inline backticks `code`
    cleaned = re.sub(r"`([^`]+)`", r"\1", cleaned)

    # Remove bold/italic markers: **text**, *text*, __text__, _text_
    cleaned = re.sub(r"\*\*([^*]+)\*\*", r"\1", cleaned)
    cleaned = re.sub(r"\*([^*]+)\*", r"\1", cleaned)
    cleaned = re.sub(r"__([^_]+)__", r"\1", cleaned)
    cleaned = re.sub(r"_([^_]+)_", r"\1", cleaned)

    # Remove markdown headers: # Header
    cleaned = re.sub(r"^#+\s*", "", cleaned, flags=re.MULTILINE)

    # Remove markdown links: [text](url) -> text
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)

    # Remove markdown bullet points: * or - at start of line
    cleaned = re.sub(r"^\s*[-*+]\s+", "", cleaned, flags=re.MULTILINE)

    # Replace multiple whitespace/newlines with single space
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    return cleaned

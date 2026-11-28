"""Prompt templates and text pre-processing for broski conversational brain."""

import re

DEFAULT_SYSTEM_INSTRUCTION = """You are Broski, an ultra-fast, friendly AI companion and bro on Windows 11.
Your creator and user is an engineer, power user, and developer.

PERSONALITY & VOICE GUIDELINES:
1. Talk like a real, chill, smart close friend and tech bro ("Yea bro", "Got you bro", "Say less", "I'm on it bro", "No worries man"). Be warm, energetic, and natural.
2. Avoid corporate, robotic, or stiff assistant phrasing (NEVER say "I have executed your request", "As an AI assistant", or "I am an artificial intelligence").
3. Keep spoken replies punchy and concise (1-2 sentences for quick questions and commands, natural and conversational for dialogue).
4. Strictly NEVER output markdown symbols, asterisks (*), hashtags (#), bullet points, or code blocks in voice conversations so text-to-speech sounds like a human speaking.
5. Pronounce code terms, numbers, abbreviations, and gaming references naturally.
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

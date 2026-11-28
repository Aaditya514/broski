"""Two-tier Intent Router for broski.

Classifies incoming voice transcripts into actionable intents:
1. Tier 1 (Ultra-fast Local Heuristics): Evaluates deterministic regex and keyword patterns
   in <0.1ms without network calls. Catches direct commands like "open obsidian", "launch spotify",
   "dictate: meeting notes".
2. Tier 2 (Cloud LLM Reasoning): For nuanced or conversational phrasing, calls Gemini Flash-Lite
   with structured JSON output to extract intent, action, and target.
"""

from __future__ import annotations

import json
import logging
import re
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from broski.system.apps import AppLauncher

if TYPE_CHECKING:
    from broski.brain.client import GeminiBrainClient

logger = logging.getLogger("broski.brain.router")


class IntentType(str, Enum):
    """Categorical classification of user intent."""

    CONVERSATION = "conversation"
    SYSTEM_COMMAND = "system_command"
    DICTATION = "dictation"
    DISAMBIGUATION = "disambiguation"
    UNKNOWN = "unknown"


class IntentResult(BaseModel):
    """Normalized output produced by the intent router."""

    intent: IntentType
    action: str | None = Field(
        default=None,
        description="Specific action verb (e.g., 'open_app', 'close_app', 'dictate_text', 'converse').",
    )
    target: str | None = Field(
        default=None,
        description="Target entity or application ID (e.g., 'obsidian', 'spotify', 'chrome').",
    )
    confidence: float = Field(
        default=1.0, ge=0.0, le=1.0, description="Confidence score for this classification."
    )
    payload: str | None = Field(
        default=None, description="Extracted payload, arguments, or text to type/dictate."
    )
    raw_query: str = Field(description="Original user transcript.")
    source: str = Field(
        default="rule", description="Routing decision source ('rule', 'llm', or 'fallback')."
    )


# Structured Pydantic schema passed to Gemini for JSON schema generation
class _LLMIntentClassification(BaseModel):
    intent: str = Field(
        description="One of: 'conversation', 'system_command', 'dictation', 'disambiguation', or 'unknown'."
    )
    action: str | None = Field(
        default=None,
        description="Action verb, such as 'open_app', 'close_app', 'dictate_text', 'ask_clarification', or 'converse'.",
    )
    target: str | None = Field(
        default=None,
        description="Whitelisted application ID if applicable (obsidian, spotify, chrome, vscode, notepad, discord, terminal, riotgames, valorant, steam) or None.",
    )
    payload: str | None = Field(
        default=None,
        description="Text to dictate if dictation, clarifying question if disambiguation, or response context.",
    )
    requires_clarification: bool = Field(
        default=False,
        description="True if the request is ambiguous (e.g. pronoun with unknown referent, or multiple choices) and broski must ask the user to clarify.",
    )


class IntentRouter:
    """Routes voice transcripts to appropriate subsystems using rules and LLM reasoning."""

    # Regex patterns for fast rule matching
    _OPEN_APP_RE = re.compile(
        r"^(?:please\s+)?(?:can\s+you\s+)?(?:open|launch|start|run|bring\s+up|switch\s+to)\s+(?P<app>[a-zA-Z0-9_\-\s]+?)(?:\s+for\s+me|\s+please)?$",
        re.IGNORECASE,
    )
    _WAKE_PREFIX_RE = re.compile(
        r"^(?:(?:hey|ok|hi)\s+)?(?:jarvis|broski)[,\s]+",
        re.IGNORECASE,
    )
    _REGISTER_PATH_RE = re.compile(
        r"^(?:set|register|update)\s+(?:the\s+)?(?:path|location)\s+(?:for|of)\s+(?P<app>[a-zA-Z0-9_\-\s]+?)\s+(?:to|as|=)\s+(?P<path>.+)$",
        re.IGNORECASE,
    )
    _APP_PATH_IS_RE = re.compile(
        r"^(?:set|register|update)\s+(?P<app>[a-zA-Z0-9_\-\s]+?)\s+(?:path|location)\s+(?:to|at|=)\s+(?P<path>.+)$",
        re.IGNORECASE,
    )
    _MY_APP_IS_AT_RE = re.compile(
        r"^(?:my\s+)?(?P<app>[a-zA-Z0-9_\-\s]+?)\s+(?:is\s+(?:located\s+)?)?at\s+(?P<path>[a-zA-Z]:[\\/].+)$",
        re.IGNORECASE,
    )
    _DICTATION_RE = re.compile(
        r"^(?:(?:please\s+)?(?:can\s+you\s+)?(?:dictate(?:\s+that)?|type(?:\s+out)?|write(?:\s+down)?|insert(?:\s+note|\s+text)?|take\s+a\s+note))[:\s]+(?P<text>.+)$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        app_launcher: AppLauncher | None = None,
        brain_client: GeminiBrainClient | None = None,
    ) -> None:
        self.app_launcher = app_launcher or AppLauncher()
        self.brain_client = brain_client

    def route(
        self,
        transcript: str,
        context: list[dict[str, str]] | None = None,
    ) -> IntentResult:
        """Route a user transcript to its intent.

        First attempts ultra-fast Tier 1 rule-based pattern matching (<0.1ms).
        If unmatched and a configured Gemini Brain client is present, falls back
        to Tier 2 structured cloud classification with conversational context.
        Otherwise, defaults to CONVERSATION.
        """
        clean_text = transcript.strip()
        if not clean_text:
            return IntentResult(
                intent=IntentType.UNKNOWN,
                action=None,
                target=None,
                confidence=0.0,
                raw_query=transcript,
                source="rule",
            )

        # ----------------------------------------------------------------------
        # Tier 1: Deterministic Heuristics & Whitelist Matching (0ms latency)
        # ----------------------------------------------------------------------
        rule_match = self._match_rules(clean_text)
        if rule_match is not None:
            logger.debug(
                "Transcript '%s' matched Tier 1 rule: %s (%s)",
                clean_text,
                rule_match.intent,
                rule_match.target,
            )
            return rule_match

        # ----------------------------------------------------------------------
        # Tier 2: LLM Structured Classification (Gemini Flash-Lite with Context)
        # ----------------------------------------------------------------------
        if self.brain_client is not None and self.brain_client.is_configured:
            llm_result = self._classify_with_llm(clean_text, context=context)
            if llm_result is not None:
                logger.debug(
                    "Transcript '%s' matched Tier 2 LLM: %s (%s)",
                    clean_text,
                    llm_result.intent,
                    llm_result.target,
                )
                return llm_result

        # ----------------------------------------------------------------------
        # Fallback: Default to Conversational Dialogue
        # ----------------------------------------------------------------------
        return IntentResult(
            intent=IntentType.CONVERSATION,
            action="converse",
            target=None,
            confidence=0.8,
            payload=clean_text,
            raw_query=clean_text,
            source="fallback",
        )

    def _match_rules(self, text: str) -> IntentResult | None:
        """Fast regex and keyword matcher for immediate command detection."""
        # Strip trailing punctuation for clean matching
        normalized = text.rstrip(".!? ")
        # Strip leading wake words or conversational prefixes (e.g. "Hey Jarvis, ", "Jarvis, ", "Hey Broski, ")
        normalized = self._WAKE_PREFIX_RE.sub("", normalized).strip()

        # 1. Match "open <app>" or "launch <app>"
        app_match = self._OPEN_APP_RE.match(normalized)
        if app_match:
            app_candidate = app_match.group("app").strip()
            app_def = self.app_launcher.find_app_definition(app_candidate)
            if app_def:
                return IntentResult(
                    intent=IntentType.SYSTEM_COMMAND,
                    action="open_app",
                    target=str(app_def.id),
                    confidence=1.0,
                    payload=app_candidate,
                    raw_query=text,
                    source="rule",
                )

        # 2. Match custom app path registration (e.g. "set obsidian path to D:\Tools\Obsidian.exe")
        reg_match = (
            self._REGISTER_PATH_RE.match(normalized)
            or self._APP_PATH_IS_RE.match(normalized)
            or self._MY_APP_IS_AT_RE.match(normalized)
        )
        if reg_match:
            app_candidate = reg_match.group("app").strip()
            path_candidate = reg_match.group("path").strip().strip('"\'')
            app_def = self.app_launcher.find_app_definition(app_candidate)
            if app_def:
                return IntentResult(
                    intent=IntentType.SYSTEM_COMMAND,
                    action="register_app_path",
                    target=str(app_def.id),
                    confidence=1.0,
                    payload=path_candidate,
                    raw_query=text,
                    source="rule",
                )

        # 3. Match "dictate: <text>" or "type: <text>"
        dict_match = self._DICTATION_RE.match(normalized)
        if dict_match:
            dictated_content = dict_match.group("text").strip()
            if dictated_content:
                return IntentResult(
                    intent=IntentType.DICTATION,
                    action="dictate_text",
                    target="active_window",
                    confidence=1.0,
                    payload=dictated_content,
                    raw_query=text,
                    source="rule",
                )

        # 3. Direct app name mention if single or double word (e.g. "Obsidian" or "Launch Spotify")
        parts = normalized.split()
        if len(parts) <= 3:
            # Check if any app alias matches the exact normalized string
            app_def = self.app_launcher.find_app_definition(normalized)
            if app_def:
                return IntentResult(
                    intent=IntentType.SYSTEM_COMMAND,
                    action="open_app",
                    target=str(app_def.id),
                    confidence=0.9,
                    payload=str(app_def.name),
                    raw_query=text,
                    source="rule",
                )

        return None

    def _classify_with_llm(
        self,
        text: str,
        context: list[dict[str, str]] | None = None,
    ) -> IntentResult | None:
        """Query Gemini using structured output to classify intent, disambiguate context, and extract entities."""
        if self.brain_client is None or not self.brain_client.is_configured:
            return None

        context_str = ""
        if context:
            formatted_turns = []
            for turn in context[-4:]:  # last 4 conversational turns
                role = turn.get("role", "user").capitalize()
                turn_text = turn.get("text", "").strip()
                if turn_text:
                    formatted_turns.append(f"{role}: {turn_text}")
            if formatted_turns:
                context_str = "Recent Conversation History:\n" + "\n".join(formatted_turns) + "\n\n"

        prompt = (
            "You are an intelligent intent classifier and context resolver for a desktop voice assistant named Broski.\n"
            "Classify the user's spoken utterance into one of the following:\n"
            "- 'system_command': user wants to open/launch an app, control windows, or trigger a local action. "
            "Use conversation history to resolve pronouns or anaphora (e.g. 'open it', 'launch that', 'bring up that app').\n"
            "- 'dictation': user asks to type or write text into an active window.\n"
            "- 'disambiguation': the request is ambiguous (e.g. user says 'open that' but context is empty or unclear, "
            "or multiple choices exist) and broski must ask a brief clarifying question.\n"
            "- 'conversation': questions, general chit-chat, explanations, or requests for information.\n"
            "- 'unknown': unintelligible or unclassifiable audio.\n\n"
            "Whitelisted applications: obsidian, spotify, chrome, vscode, notepad, discord, terminal, riotgames, valorant, steam.\n"
            "If an application is requested or resolved from context, set 'target' to its whitelisted id and 'action' to 'open_app'.\n"
            "If 'disambiguation' is required, formulate a concise, friendly clarifying question in 'payload' "
            "(e.g. 'Which Chrome profile did you want bro, College or Personal?' or 'Did you mean Valorant or Riot Client bro?').\n\n"
            f"{context_str}"
            f"User Utterance: \"{text}\""
        )

        try:
            from google.genai import types

            response = self.brain_client.client.models.generate_content(
                model=self.brain_client.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=_LLMIntentClassification,
                    temperature=0.0,
                ),
            )

            raw_text = response.text or "{}"
            data = json.loads(raw_text)

            intent_str = str(data.get("intent", "conversation")).lower()
            requires_clarification = bool(data.get("requires_clarification", False))

            if requires_clarification or intent_str == "disambiguation":
                clarifying_question = data.get("payload") or "Which one did you want bro?"
                return IntentResult(
                    intent=IntentType.DISAMBIGUATION,
                    action="ask_clarification",
                    target=None,
                    confidence=0.95,
                    payload=clarifying_question,
                    raw_query=text,
                    source="llm",
                )

            intent_map = {
                "system_command": IntentType.SYSTEM_COMMAND,
                "open_application": IntentType.SYSTEM_COMMAND,
                "dictation": IntentType.DICTATION,
                "conversation": IntentType.CONVERSATION,
                "unknown": IntentType.UNKNOWN,
            }
            intent = intent_map.get(intent_str, IntentType.CONVERSATION)

            target = data.get("target")
            action = data.get("action")
            payload = data.get("payload")

            # Validate target against whitelist if it's a system command
            if intent == IntentType.SYSTEM_COMMAND and target:
                app_def = self.app_launcher.find_app_definition(str(target))
                if app_def:
                    target = app_def.id
                else:
                    # Non-whitelisted app request - keep target for graceful refusal
                    target = str(target)

            return IntentResult(
                intent=intent,
                action=action or ("open_app" if intent == IntentType.SYSTEM_COMMAND else "converse"),
                target=target,
                confidence=0.95,
                payload=payload or text,
                raw_query=text,
                source="llm",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tier 2 LLM classification failed: %s", exc)
            return None

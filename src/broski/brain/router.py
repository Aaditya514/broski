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
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from broski.system.apps import AppLauncher

if TYPE_CHECKING:
    from broski.brain.client import GeminiBrainClient
    from broski.tools.registry import ToolRegistry

logger = logging.getLogger("broski.brain.router")


class IntentType(str, Enum):
    """Categorical classification of user intent."""

    CONVERSATION = "conversation"
    SYSTEM_COMMAND = "system_command"
    DICTATION = "dictation"
    DISAMBIGUATION = "disambiguation"
    TOOL_EXECUTION = "tool_execution"
    CONFIRMATION = "confirmation"
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
    tool_args: dict[str, Any] = Field(
        default_factory=dict, description="Structured arguments for tool execution."
    )
    raw_query: str = Field(description="Original user transcript.")
    source: str = Field(
        default="rule", description="Routing decision source ('rule', 'llm', or 'fallback')."
    )


# Structured Pydantic schema passed to Gemini for JSON schema generation
class _LLMIntentClassification(BaseModel):
    intent: str = Field(
        description="One of: 'conversation', 'system_command', 'dictation', 'disambiguation', 'tool_execution', or 'unknown'."
    )
    action: str | None = Field(
        default=None,
        description="Action verb or tool name (e.g. 'open_app', 'obsidian_read_daily_note', 'git_status', etc.).",
    )
    target: str | None = Field(
        default=None,
        description="Whitelisted application ID if applicable (obsidian, spotify, chrome, vscode, notepad, discord, terminal, riotgames, valorant, steam) or None.",
    )
    payload: str | None = Field(
        default=None,
        description="Text to dictate if dictation, clarifying question if disambiguation, or response context.",
    )
    tool_args: dict[str, Any] = Field(
        default_factory=dict,
        description="Key-value arguments for tool execution if intent is tool_execution.",
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

    # Confirmation & Cancellation patterns
    _CONFIRM_RE = re.compile(
        r"^(?:yes\s*,?\s*)?(?:confirm|approve|proceed|do\s+it|go\s+ahead|execute|yes)$",
        re.IGNORECASE,
    )
    _CANCEL_RE = re.compile(
        r"^(?:no\s*,?\s*)?(?:cancel|deny|abort|don't|stop|reject|no)$",
        re.IGNORECASE,
    )

    # Obsidian tools patterns
    _DAILY_NOTE_READ_RE = re.compile(
        r"^(?:what(?:'s|\s+is)\s+(?:in|on)\s+(?:my\s+)?daily\s+note|read\s+(?:my\s+)?daily\s+note|check\s+(?:my\s+)?daily\s+note)$",
        re.IGNORECASE,
    )
    _DAILY_NOTE_APPEND_RE = re.compile(
        r"^(?:add|append|write|put)\s+(?:an?\s+(?:idea|note|task|thought)\s+)?(?:to|in)\s+(?:my\s+)?daily\s+note[:\s]+(?P<content>.+)$",
        re.IGNORECASE,
    )
    _READ_NOTE_RE = re.compile(
        r"^(?:read|open|show)\s+(?:the\s+)?note\s+(?P<path>[a-zA-Z0-9_\-\s/]+?)(?:\s+in\s+obsidian)?$",
        re.IGNORECASE,
    )
    _SEARCH_NOTES_RE = re.compile(
        r"^(?:search\s+(?:obsidian|my\s+notes)\s+for|find\s+notes?\s+(?:about|on))\s+(?P<query>.+)$",
        re.IGNORECASE,
    )

    # Git tools patterns
    _GIT_STATUS_RE = re.compile(
        r"^(?:check\s+)?git\s+status$|^(?:what\s+files\s+(?:did\s+i\s+change|have\s+i\s+changed|are\s+changed)|what\s+did\s+i\s+change)$",
        re.IGNORECASE,
    )
    _GIT_DIFF_RE = re.compile(
        r"^(?:check\s+)?git\s+diff$|^(?:show\s+(?:me\s+)?(?:the\s+)?diffs?|what\s+are\s+the\s+diffs)$",
        re.IGNORECASE,
    )
    _GIT_BRANCH_RE = re.compile(
        r"^(?:check\s+)?git\s+branch$|^(?:what\s+branch\s+am\s+i\s+on|what(?:'s|\s+is)\s+(?:my\s+)?current\s+branch)$",
        re.IGNORECASE,
    )
    _GIT_LOG_RE = re.compile(
        r"^(?:check\s+)?git\s+log$|^(?:show\s+(?:me\s+)?recent\s+commits|what\s+was\s+the\s+last\s+commit)$",
        re.IGNORECASE,
    )
    _GIT_COMMIT_RE = re.compile(
        r"^(?:git\s+commit|commit\s+(?:my\s+)?changes)(?:\s+with\s+message[:\s]+(?P<message>.+))?$",
        re.IGNORECASE,
    )
    _GIT_PUSH_RE = re.compile(
        r"^(?:git\s+push|push\s+(?:my\s+)?commits|push\s+to\s+origin)$",
        re.IGNORECASE,
    )

    # Browser tools patterns
    _BROWSER_SEARCH_RE = re.compile(
        r"^(?:search\s+(?:google|the\s+web)\s+for|google)\s+(?P<query>.+)$",
        re.IGNORECASE,
    )
    _BROWSER_OPEN_URL_RE = re.compile(
        r"^(?:go\s+to|open\s+(?:the\s+)?website)\s+(?P<url>[a-zA-Z0-9.\-]+\.[a-z]{2,}(?:/[^\s]*)?)$",
        re.IGNORECASE,
    )
    _BROWSER_READ_RE = re.compile(
        r"^(?:read|summarize)\s+(?:this\s+)?(?:webpage|article|page|url)[:\s]+(?P<url>https?://[^\s]+)$",
        re.IGNORECASE,
    )

    def __init__(
        self,
        app_launcher: AppLauncher | None = None,
        brain_client: GeminiBrainClient | None = None,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.app_launcher = app_launcher or AppLauncher()
        self.brain_client = brain_client
        self.tool_registry = tool_registry

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

        # 0. Check for pending security confirmation approval or cancellation
        if self.tool_registry and self.tool_registry.confirmation_manager.get_pending_requests():
            if self._CONFIRM_RE.match(normalized):
                return IntentResult(
                    intent=IntentType.CONFIRMATION,
                    action="approve",
                    target=None,
                    confidence=1.0,
                    raw_query=text,
                    source="rule",
                )
            if self._CANCEL_RE.match(normalized):
                return IntentResult(
                    intent=IntentType.CONFIRMATION,
                    action="deny",
                    target=None,
                    confidence=1.0,
                    raw_query=text,
                    source="rule",
                )

        # 1. Match Obsidian tools
        if self._DAILY_NOTE_READ_RE.match(normalized):
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="obsidian_read_daily_note",
                target="obsidian",
                confidence=1.0,
                raw_query=text,
                source="rule",
            )
        daily_append_match = self._DAILY_NOTE_APPEND_RE.match(normalized)
        if daily_append_match:
            content = daily_append_match.group("content").strip()
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="obsidian_append_daily_note",
                target="obsidian",
                confidence=1.0,
                tool_args={"content": content},
                payload=content,
                raw_query=text,
                source="rule",
            )
        read_note_match = self._READ_NOTE_RE.match(normalized)
        if read_note_match:
            path = read_note_match.group("path").strip()
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="obsidian_read_note",
                target="obsidian",
                confidence=1.0,
                tool_args={"path": path},
                payload=path,
                raw_query=text,
                source="rule",
            )
        search_notes_match = self._SEARCH_NOTES_RE.match(normalized)
        if search_notes_match:
            query = search_notes_match.group("query").strip()
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="obsidian_search_notes",
                target="obsidian",
                confidence=1.0,
                tool_args={"query": query},
                payload=query,
                raw_query=text,
                source="rule",
            )

        # 2. Match Git tools
        if self._GIT_STATUS_RE.match(normalized):
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="git_status",
                target="git",
                confidence=1.0,
                raw_query=text,
                source="rule",
            )
        if self._GIT_DIFF_RE.match(normalized):
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="git_diff",
                target="git",
                confidence=1.0,
                raw_query=text,
                source="rule",
            )
        if self._GIT_BRANCH_RE.match(normalized):
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="git_branch",
                target="git",
                confidence=1.0,
                raw_query=text,
                source="rule",
            )
        if self._GIT_LOG_RE.match(normalized):
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="git_log",
                target="git",
                confidence=1.0,
                raw_query=text,
                source="rule",
            )
        git_commit_match = self._GIT_COMMIT_RE.match(normalized)
        if git_commit_match:
            msg = (git_commit_match.group("message") or "").strip() or "Update"
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="git_commit",
                target="git",
                confidence=1.0,
                tool_args={"message": msg},
                payload=msg,
                raw_query=text,
                source="rule",
            )
        if self._GIT_PUSH_RE.match(normalized):
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="git_push",
                target="git",
                confidence=1.0,
                tool_args={"remote": "origin"},
                raw_query=text,
                source="rule",
            )

        # 3. Match Browser tools
        browser_search_match = self._BROWSER_SEARCH_RE.match(normalized)
        if browser_search_match:
            q = browser_search_match.group("query").strip()
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="browser_search",
                target="chrome",
                confidence=1.0,
                tool_args={"query": q},
                payload=q,
                raw_query=text,
                source="rule",
            )
        browser_open_match = self._BROWSER_OPEN_URL_RE.match(normalized)
        if browser_open_match:
            u = browser_open_match.group("url").strip()
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="browser_open_url",
                target="chrome",
                confidence=1.0,
                tool_args={"url": u},
                payload=u,
                raw_query=text,
                source="rule",
            )
        browser_read_match = self._BROWSER_READ_RE.match(normalized)
        if browser_read_match:
            u = browser_read_match.group("url").strip()
            return IntentResult(
                intent=IntentType.TOOL_EXECUTION,
                action="browser_read_webpage",
                target="chrome",
                confidence=1.0,
                tool_args={"url": u},
                payload=u,
                raw_query=text,
                source="rule",
            )

        # 4. Match "open <app>" or "launch <app>"
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
            "- 'tool_execution': user asks to interact with a system tool: "
            "obsidian_read_daily_note, obsidian_append_daily_note (content: str), obsidian_read_note (path: str), "
            "obsidian_search_notes (query: str), git_status, git_diff (cached: bool), git_log (count: int), git_branch, "
            "git_commit (message: str), git_push (remote: str), browser_open_url (url: str, profile: str), "
            "browser_search (query: str, engine: str), browser_read_webpage (url: str). "
            "Set 'action' to the tool name and populate 'tool_args' with arguments.\n"
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
                "tool_execution": IntentType.TOOL_EXECUTION,
                "confirmation": IntentType.CONFIRMATION,
                "dictation": IntentType.DICTATION,
                "conversation": IntentType.CONVERSATION,
                "unknown": IntentType.UNKNOWN,
            }
            intent = intent_map.get(intent_str, IntentType.CONVERSATION)

            target = data.get("target")
            action = data.get("action")
            payload = data.get("payload")
            tool_args = data.get("tool_args", {})

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
                tool_args=tool_args,
                raw_query=text,
                source="llm",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Tier 2 LLM classification failed: %s", exc)
            return None

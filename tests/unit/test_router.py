"""Unit tests for Two-tier Intent Router."""

from unittest.mock import MagicMock

from broski.brain.router import (
    IntentRouter,
    IntentType,
)


def test_router_rule_open_apps() -> None:
    """Verify Tier 1 rule matching catches various 'open <app>' formulations."""
    router = IntentRouter()

    test_cases = [
        ("open obsidian", "obsidian"),
        ("launch spotify", "spotify"),
        ("please open chrome", "chrome"),
        ("can you launch vscode for me", "vscode"),
        ("start notepad please", "notepad"),
        ("bring up terminal", "terminal"),
        ("open notes", "obsidian"),
        ("launch music", "spotify"),
        ("Hey Jarvis, open Obsidian.", "obsidian"),
        ("Jarvis, launch Spotify", "spotify"),
        ("Hey Broski, open Chrome", "chrome"),
    ]

    for utterance, expected_app in test_cases:
        res = router.route(utterance)
        assert res.intent == IntentType.SYSTEM_COMMAND, f"Failed on '{utterance}'"
        assert res.action == "open_app"
        assert res.target == expected_app, f"Expected {expected_app} for '{utterance}' but got {res.target}"
        assert res.source == "rule"
        assert res.confidence >= 0.9


def test_router_rule_dictation() -> None:
    """Verify Tier 1 rule matching catches dictation commands."""
    router = IntentRouter()

    test_cases = [
        ("dictate: meeting with client at 3pm", "meeting with client at 3pm"),
        ("type: hello world this is a test", "hello world this is a test"),
        ("take a note: buy coffee beans", "buy coffee beans"),
        ("write: draft message to team", "draft message to team"),
        ("type out this important code snippet", "this important code snippet"),
        ("write down remember to call mom", "remember to call mom"),
        ("please dictate that we are launching tomorrow", "we are launching tomorrow"),
        ("insert text hello active window", "hello active window"),
    ]

    for utterance, expected_payload in test_cases:
        res = router.route(utterance)
        assert res.intent == IntentType.DICTATION, f"Failed on '{utterance}'"
        assert res.action == "dictate_text"
        assert res.target == "active_window"
        assert res.payload == expected_payload
        assert res.source == "rule"


def test_router_rule_register_path() -> None:
    """Verify Tier 1 rule matching catches path registration commands."""
    router = IntentRouter()

    test_cases = [
        ("set obsidian path to D:\\Tools\\Obsidian.exe", "obsidian", "D:\\Tools\\Obsidian.exe"),
        ("my obsidian is at C:\\Users\\Obsidian.exe", "obsidian", "C:\\Users\\Obsidian.exe"),
        ("register path for chrome to C:\\Custom\\chrome.exe", "chrome", "C:\\Custom\\chrome.exe"),
        ("update spotify location = D:\\Music\\Spotify.exe", "spotify", "D:\\Music\\Spotify.exe"),
    ]

    for utterance, expected_app, expected_path in test_cases:
        res = router.route(utterance)
        assert res.intent == IntentType.SYSTEM_COMMAND, f"Failed on '{utterance}'"
        assert res.action == "register_app_path"
        assert res.target == expected_app
        assert res.payload == expected_path
        assert res.source == "rule"



def test_router_empty_or_whitespace() -> None:
    """Verify empty or blank transcripts yield UNKNOWN intent."""
    router = IntentRouter()

    res = router.route("")
    assert res.intent == IntentType.UNKNOWN
    assert res.confidence == 0.0

    res2 = router.route("   \n\t  ")
    assert res2.intent == IntentType.UNKNOWN


def test_router_conversational_fallback_offline() -> None:
    """Verify unconfigured/offline router defaults unmatched queries to CONVERSATION."""
    # Router without brain_client
    router = IntentRouter(brain_client=None)

    res = router.route("What is the speed of light?")
    assert res.intent == IntentType.CONVERSATION
    assert res.action == "converse"
    assert res.source == "fallback"
    assert res.payload == "What is the speed of light?"


def test_router_llm_classification_mocked() -> None:
    """Verify Tier 2 cloud LLM classification when Tier 1 rule doesn't match."""
    mock_brain = MagicMock()
    mock_brain.is_configured = True
    mock_brain.model = "gemini-3.1-flash-lite"

    # Simulate Gemini structured JSON output
    mock_response = MagicMock()
    mock_response.text = '{"intent": "system_command", "action": "open_app", "target": "obsidian", "payload": null}'
    mock_brain.client.models.generate_content.return_value = mock_response

    router = IntentRouter(brain_client=mock_brain)

    query = "Could you pull up my personal notes please"
    res = router.route(query)

    assert res.intent == IntentType.SYSTEM_COMMAND
    assert res.action == "open_app"
    assert res.target == "obsidian"
    assert res.source == "llm"
    mock_brain.client.models.generate_content.assert_called_once()


def test_router_llm_classification_conversation_mocked() -> None:
    """Verify Tier 2 LLM routes chit-chat and questions to CONVERSATION."""
    mock_brain = MagicMock()
    mock_brain.is_configured = True
    mock_brain.model = "gemini-3.1-flash-lite"

    mock_response = MagicMock()
    mock_response.text = '{"intent": "conversation", "action": "converse", "target": null, "payload": "What is the weather?"}'
    mock_brain.client.models.generate_content.return_value = mock_response

    router = IntentRouter(brain_client=mock_brain)

    query = "What is the weather like today?"
    res = router.route(query)

    assert res.intent == IntentType.CONVERSATION
    assert res.action == "converse"
    assert res.source == "llm"


def test_router_llm_error_graceful_fallback() -> None:
    """Verify router gracefully falls back to CONVERSATION when LLM raises an error."""
    mock_brain = MagicMock()
    mock_brain.is_configured = True
    mock_brain.client.models.generate_content.side_effect = RuntimeError("Network timeout")

    router = IntentRouter(brain_client=mock_brain)

    res = router.route("Can you summarize the news?")
    assert res.intent == IntentType.CONVERSATION
    assert res.source == "fallback"


def test_router_contextual_pronoun_resolution_mocked() -> None:
    """Verify router uses conversation context to resolve pronouns ('open it')."""
    mock_brain = MagicMock()
    mock_brain.is_configured = True
    mock_brain.model = "gemini-3.1-flash-lite"

    mock_response = MagicMock()
    mock_response.text = '{"intent": "system_command", "action": "open_app", "target": "obsidian", "payload": null, "requires_clarification": false}'
    mock_brain.client.models.generate_content.return_value = mock_response

    router = IntentRouter(brain_client=mock_brain)

    context = [
        {"role": "user", "text": "Can you check my notes in Obsidian?"},
        {"role": "assistant", "text": "Obsidian is where all your daily notes and vaults live."},
    ]

    res = router.route("Open it", context=context)

    assert res.intent == IntentType.SYSTEM_COMMAND
    assert res.action == "open_app"
    assert res.target == "obsidian"
    assert res.source == "llm"

    # Verify that conversation history was included in the LLM prompt
    call_args = mock_brain.client.models.generate_content.call_args
    prompt_sent = call_args.kwargs["contents"]
    assert "Obsidian is where all your daily notes" in prompt_sent
    assert 'User Utterance: "Open it"' in prompt_sent


def test_router_disambiguation_clarifying_question_mocked() -> None:
    """Verify router returns DISAMBIGUATION when an utterance is ambiguous."""
    mock_brain = MagicMock()
    mock_brain.is_configured = True
    mock_brain.model = "gemini-3.1-flash-lite"

    mock_response = MagicMock()
    mock_response.text = (
        '{"intent": "disambiguation", "action": "ask_clarification", "target": null, '
        '"payload": "Which game did you want me to open bro, Valorant or Steam?", "requires_clarification": true}'
    )
    mock_brain.client.models.generate_content.return_value = mock_response

    router = IntentRouter(brain_client=mock_brain)

    res = router.route("Open that game for me")

    assert res.intent == IntentType.DISAMBIGUATION
    assert res.action == "ask_clarification"
    assert res.target is None
    assert "Valorant or Steam" in (res.payload or "")
    assert res.source == "llm"


def test_router_rule_obsidian_tools() -> None:
    """Verify Tier 1 rules route Obsidian daily note and search commands."""
    router = IntentRouter()

    res_read = router.route("what is in my daily note")
    assert res_read.intent == IntentType.TOOL_EXECUTION
    assert res_read.action == "obsidian_read_daily_note"

    res_append = router.route("add to daily note: review pull request")
    assert res_append.intent == IntentType.TOOL_EXECUTION
    assert res_append.action == "obsidian_append_daily_note"
    assert res_append.tool_args == {"content": "review pull request"}

    res_search = router.route("search my notes for quantum")
    assert res_search.intent == IntentType.TOOL_EXECUTION
    assert res_search.action == "obsidian_search_notes"
    assert res_search.tool_args == {"query": "quantum"}


def test_router_rule_git_tools() -> None:
    """Verify Tier 1 rules route Git status, diff, branch, and log commands."""
    router = IntentRouter()

    res_status = router.route("git status")
    assert res_status.intent == IntentType.TOOL_EXECUTION
    assert res_status.action == "git_status"

    res_status2 = router.route("what files did i change")
    assert res_status2.intent == IntentType.TOOL_EXECUTION
    assert res_status2.action == "git_status"

    res_diff = router.route("show me the diff")
    assert res_diff.intent == IntentType.TOOL_EXECUTION
    assert res_diff.action == "git_diff"

    res_branch = router.route("what branch am i on")
    assert res_branch.intent == IntentType.TOOL_EXECUTION
    assert res_branch.action == "git_branch"

    res_log = router.route("show me recent commits")
    assert res_log.intent == IntentType.TOOL_EXECUTION
    assert res_log.action == "git_log"


def test_router_rule_browser_tools() -> None:
    """Verify Tier 1 rules route browser search and open commands."""
    router = IntentRouter()

    res_search = router.route("search google for python docs")
    assert res_search.intent == IntentType.TOOL_EXECUTION
    assert res_search.action == "browser_search"
    assert res_search.tool_args == {"query": "python docs"}

    res_open = router.route("open website github.com")
    assert res_open.intent == IntentType.TOOL_EXECUTION
    assert res_open.action == "browser_open_url"
    assert res_open.tool_args == {"url": "github.com"}


def test_router_confirmation_matching() -> None:
    """Verify confirmation matching when security confirmation requests are pending."""
    from broski.tools.registry import ToolRegistry
    from broski.tools.security import SecurityConfirmationManager

    manager = SecurityConfirmationManager()
    manager.request_confirmation("git_commit", {"message": "wip"})
    registry = ToolRegistry(confirmation_manager=manager)

    router = IntentRouter(tool_registry=registry)

    res_approve = router.route("confirm")
    assert res_approve.intent == IntentType.CONFIRMATION
    assert res_approve.action == "approve"

    res_deny = router.route("cancel")
    assert res_deny.intent == IntentType.CONFIRMATION
    assert res_deny.action == "deny"


def test_router_llm_tool_execution_mocked() -> None:
    """Verify Tier 2 LLM routing classifies tool execution when rule doesn't match."""
    mock_brain = MagicMock()
    mock_brain.is_configured = True
    mock_brain.model = "gemini-3.1-flash-lite"

    mock_response = MagicMock()
    mock_response.text = (
        '{"intent": "tool_execution", "action": "git_commit", "target": "git", '
        '"tool_args": {"message": "feat: finish sprint 5"}}'
    )
    mock_brain.client.models.generate_content.return_value = mock_response

    router = IntentRouter(brain_client=mock_brain)

    res = router.route("Please commit my changes with the message feat: finish sprint 5")
    assert res.intent == IntentType.TOOL_EXECUTION
    assert res.action == "git_commit"
    assert res.tool_args == {"message": "feat: finish sprint 5"}
    assert res.source == "llm"



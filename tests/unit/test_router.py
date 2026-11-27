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

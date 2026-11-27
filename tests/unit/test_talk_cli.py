"""Unit tests for broski-talk CLI and offline conversational voice loop."""

from unittest.mock import MagicMock, patch

from broski.audio.cli import generate_offline_response, talk_main


def test_generate_offline_response_identity() -> None:
    """Verify offline responder answers identity questions."""
    resp = generate_offline_response("who are you")
    assert "Broski" in resp
    assert "assistant" in resp.lower()


def test_generate_offline_response_time() -> None:
    """Verify offline responder formats current time."""
    resp = generate_offline_response("What time is it right now?")
    assert "current time is" in resp.lower()


def test_generate_offline_response_joke() -> None:
    """Verify offline responder provides a joke."""
    resp = generate_offline_response("tell me a joke please")
    assert "dark mode" in resp or "bugs" in resp


def test_generate_offline_response_greetings() -> None:
    """Verify offline responder answers greetings."""
    resp = generate_offline_response("Hello there")
    assert "Hey there" in resp


def test_generate_offline_response_goodbye() -> None:
    """Verify offline responder handles exit phrasing."""
    resp = generate_offline_response("quit")
    assert "Goodbye" in resp


def test_generate_offline_response_echo() -> None:
    """Verify arbitrary speech falls back to echo verification."""
    query = "Launch development environment"
    resp = generate_offline_response(query)
    assert f"I heard you say: {query}" in resp


def test_talk_main_mocked_lifecycle() -> None:
    """Verify talk_main initializes components and shuts down cleanly."""
    mock_devices = [
        {
            "index": 29,
            "name": "OnePlus Nord Buds 3 bthhfenum",
            "channels": 1,
            "default_samplerate": 16000,
            "hostapi": 3,
            "is_default": False,
            "is_headset": True,
        },
        {
            "index": 4,
            "name": "Headphones (OnePlus Nord Buds 3)",
            "channels": 2,
            "default_samplerate": 44100,
            "hostapi": 0,
            "is_default": True,
            "is_headset": True,
        },
    ]

    with (
        patch("sys.argv", ["broski-talk", "--no-greet", "--speed", "1.1"]),
        patch("broski.audio.cli.list_input_devices", return_value=mock_devices[:1]),
        patch("broski.audio.cli.find_default_or_headset_output_device", return_value=(4, "Headphones")),
        patch("broski.audio.cli.PiperSynthesizer") as mock_synth_cls,
        patch("broski.audio.cli.AudioPlayer") as mock_player_cls,
        patch("broski.audio.cli.AudioPipelineCoordinator") as mock_coord_cls,
        patch("time.sleep", side_effect=KeyboardInterrupt),
    ):
        mock_synth = MagicMock()
        mock_synth.sample_rate = 22050
        mock_synth_cls.return_value = mock_synth

        mock_player = MagicMock()
        mock_player_cls.return_value = mock_player

        mock_coord = MagicMock()
        mock_coord_cls.return_value = mock_coord

        talk_main()

        # Check component initialization
        mock_synth_cls.assert_called_once_with(
            voice_name="en_US-lessac-medium", length_scale=1.1, auto_load=True
        )
        mock_player_cls.assert_called_once_with(device_index=4, sample_rate=22050, channels=2)
        mock_coord_cls.assert_called_once()
        mock_coord.start.assert_called_once()

        # Check clean shutdown
        mock_coord.stop.assert_called_once()
        mock_player.close.assert_called_once()


def test_talk_main_on_text_routes_system_command() -> None:
    """Verify that incoming transcript triggers IntentRouter and AppLauncher."""
    with (
        patch("sys.argv", ["broski-talk", "--no-greet"]),
        patch("broski.audio.cli.list_input_devices", return_value=[{"index": 0, "name": "Mic", "channels": 1, "default_samplerate": 16000, "hostapi": 0, "is_default": True, "is_headset": False}]),
        patch("broski.audio.cli.find_default_or_headset_output_device", return_value=(0, "Speaker")),
        patch("broski.audio.cli.PiperSynthesizer") as mock_synth_cls,
        patch("broski.audio.cli.AudioPlayer"),
        patch("broski.audio.cli.AudioPipelineCoordinator") as mock_coord_cls,
        patch("broski.audio.cli.AppLauncher") as mock_launcher_cls,
        patch("time.sleep", side_effect=KeyboardInterrupt),
    ):
        mock_synth = MagicMock()
        mock_synth.sample_rate = 22050
        mock_synth.synthesize_stream.return_value = []
        mock_synth_cls.return_value = mock_synth

        mock_launcher = MagicMock()
        mock_app_def = MagicMock()
        mock_app_def.id = "obsidian"
        mock_app_def.name = "Obsidian"
        mock_launcher.find_app_definition.return_value = mock_app_def

        mock_launch_res = MagicMock()
        mock_launch_res.message = "Opening Obsidian."
        mock_launcher.launch.return_value = mock_launch_res
        mock_launcher_cls.return_value = mock_launcher

        talk_main()

        # Extract the on_transcript callback
        coord_kwargs = mock_coord_cls.call_args.kwargs
        on_text_callback = coord_kwargs["on_transcript"]

        # Call on_text with an open command
        on_text_callback("open obsidian")

        mock_launcher.launch.assert_called_once_with("obsidian")
        mock_synth.synthesize_stream.assert_called_with("Opening Obsidian.")


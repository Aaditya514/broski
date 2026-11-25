"""Unit tests for broski audio CLI."""

from unittest.mock import patch

from broski.audio.cli import print_banner, print_devices


def test_print_banner_and_devices(capsys) -> None:
    """Verify banner and device discovery outputs print without errors."""
    print_banner()
    captured = capsys.readouterr()
    assert "Real-Time Audio Sensory Pipeline Test" in captured.out

    with patch("broski.audio.cli.list_input_devices") as mock_list:
        mock_list.return_value = [
            {
                "index": 1,
                "name": "Test Microphone",
                "channels": 2,
                "default_samplerate": 48000,
                "is_default": True,
            }
        ]
        print_devices()
        captured_devices = capsys.readouterr()
        assert "Test Microphone" in captured_devices.out
        assert "[WINDOWS DEFAULT]" in captured_devices.out

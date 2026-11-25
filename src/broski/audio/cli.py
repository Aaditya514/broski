"""Interactive Command-Line Interface (CLI) for testing broski audio pipeline in real time.

Allows users to speak into their laptop microphone or Bluetooth earphones,
testing wake word detection, neural VAD, and local speech-to-text transcription live.
"""

import argparse
import logging
import time

from broski.audio.capture import list_input_devices
from broski.audio.pipeline import AudioPipelineCoordinator
from broski.config import get_settings

# Configure logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")


def print_banner() -> None:
    print("\n" + "=" * 65)
    print("      broski 🎙️ — Real-Time Audio Sensory Pipeline Test")
    print("=" * 65)


def print_devices() -> None:
    print("\n[Input Audio Devices Detected on Windows]")
    devices = list_input_devices()
    for dev in devices:
        default_tag = " [ACTIVE DEFAULT]" if dev["is_default"] else ""
        print(
            f"  [{dev['index']}] {dev['name']} ({dev['channels']} ch, {dev['default_samplerate']} Hz){default_tag}"
        )
    print("-" * 65)


def main() -> None:
    parser = argparse.ArgumentParser(description="broski live audio sensory pipeline test.")
    parser.add_argument(
        "--dictation",
        action="store_true",
        help="Start in continuous dictation mode (bypasses wake word).",
    )
    parser.add_argument(
        "--device",
        type=int,
        default=None,
        help="Index of microphone input device (default is system default).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="base.en",
        help="Whisper model size ('tiny.en', 'base.en', 'small.en').",
    )
    parser.add_argument(
        "--wakeword",
        type=str,
        default="hey_jarvis",
        help="Wake word trigger model ('hey_jarvis', 'alexa').",
    )

    args = parser.parse_args()
    print_banner()
    print_devices()

    settings = get_settings()
    if args.device is not None:
        settings.audio_input_device_index = args.device
    if args.model:
        settings.whisper_model_size = args.model
    if args.wakeword:
        settings.wake_word_model = args.wakeword

    print("\nInitializing audio models on CPU (INT8 quantized, capped at 2 threads)...")

    # Define live console callbacks
    def on_wake(score: float) -> None:
        print(
            f"\n[🔔 WAKE WORD DETECTED!] Trigger: '{settings.audio.wake_word_model}' (Confidence: {score:.2f})"
        )
        print("  -> [🎙️ LISTENING] Speak your command now...")

    def on_speech_end() -> None:
        print("  -> [⏳ PROCESSING] User finished speaking. Transcribing locally with Whisper...")

    def on_text(transcript: str) -> None:
        print(f'\n>>> [💬 TRANSCRIPT]: "{transcript}"\n')
        if not args.dictation:
            print(f"[👂 IDLE] Passively listening for '{settings.audio.wake_word_model}'...")

    coordinator = AudioPipelineCoordinator(
        settings=settings,
        on_wake_word=on_wake,
        on_speech_end=on_speech_end,
        on_transcript=on_text,
    )

    if args.dictation:
        coordinator.dictation_mode = True
        print("\nMode: CONTINUOUS DICTATION (Speak freely; no wake word required)")
    else:
        print(f"\nMode: CONVERSATIONAL (Say '{settings.audio.wake_word_model}' to wake broski)")
        print(f"[👂 IDLE] Passively listening for '{settings.audio.wake_word_model}'...")

    print("Press Ctrl+C at any time to exit.\n" + "=" * 65 + "\n")

    coordinator.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nShutting down audio pipeline cleanly...")
    finally:
        coordinator.stop()
        print("broski audio pipeline stopped. Have a great day!\n")


if __name__ == "__main__":
    main()

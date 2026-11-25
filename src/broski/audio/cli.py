"""Interactive Command-Line Interface (CLI) for testing broski audio pipeline in real time.

Allows users to speak into their laptop microphone or Bluetooth earphones,
testing wake word detection, neural VAD, and local speech-to-text transcription live
with a real-time visual VU volume meter.
"""

import argparse
import logging
import sys
import time

import numpy as np
import sounddevice as sd

from broski.audio.capture import list_input_devices
from broski.audio.pipeline import AudioPipelineCoordinator, PipelineState
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
        tags = []
        if dev.get("is_headset"):
            tags.append("ACTIVE HEADSET ⭐")
        if dev["is_default"]:
            tags.append("WINDOWS DEFAULT")
        tag_str = f" [{', '.join(tags)}]" if tags else ""
        print(
            f"  [{dev['index']}] {dev['name']} ({dev['channels']} ch, {dev['default_samplerate']} Hz){tag_str}"
        )
    print("-" * 65)


def render_meter(rms: float, max_rms: float = 3000.0, width: int = 10) -> str:
    """Render a visual ASCII VU audio meter bar."""
    if rms <= 5.0:
        filled = 0
    else:
        # Scaled logarithmically/linearly for vocal dynamic range
        ratio = min(1.0, max(0.0, rms / max_rms))
        filled = round(ratio * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"[{bar}]"


def probe_device_activity(idx: int, duration_sec: float = 0.15) -> float:
    """Probe an audio device for short period and return signal standard deviation."""
    try:
        dev_info = sd.query_devices(idx)
        sr = int(dev_info["default_samplerate"])
        ch = min(1, int(dev_info["max_input_channels"]))
        samples = int(sr * duration_sec)
        rec = sd.rec(samples, samplerate=sr, device=idx, channels=ch, dtype="int16")
        sd.wait()
        return float(np.std(rec))
    except (sd.PortAudioError, ValueError, OSError):
        return 0.0


def auto_select_device(requested_idx: int | None = None) -> tuple[int, str]:
    """Select the active device, prioritizing OnePlus Nord Buds 3 or connected headsets."""
    devices = list_input_devices()
    if not devices:
        return 0, "Default Audio Device"

    # 1. If user explicitly requested an index via CLI, honor it
    if requested_idx is not None:
        for dev in devices:
            if dev["index"] == requested_idx:
                return dev["index"], dev["name"]
        return requested_idx, f"Device {requested_idx}"

    # 2. Priority 1: Direct Windows Bluetooth Hands-Free driver for OnePlus / Nord / Buds
    for dev in devices:
        name_lower = dev["name"].lower()
        if any(k in name_lower for k in ("oneplus", "nord", "buds")) and (
            "bthhfenum" in name_lower or dev.get("hostapi") == 3
        ):
            print(
                f"\n[🎧 Headset Detected] Automatically selecting direct Bluetooth driver: Device [{dev['index']}] (OnePlus Nord Buds 3)"
            )
            return dev["index"], "OnePlus Nord Buds 3 (Direct Bluetooth Stream)"

    # 3. Priority 2: Direct Bluetooth driver for other headsets
    for dev in devices:
        name_lower = dev["name"].lower()
        if "bthhfenum" in name_lower or (
            dev.get("hostapi") == 3 and any(k in name_lower for k in ("headset", "airpods"))
        ):
            print(
                f"\n[🎧 Headset Detected] Automatically selecting direct Bluetooth driver: Device [{dev['index']}] ({dev['name'][:40]})"
            )
            return dev["index"], dev["name"]

    # 3. Priority 2: Any detected headset
    for dev in devices:
        if dev.get("is_headset"):
            print(
                f"\n[🎧 Headset Detected] Automatically selecting: Device [{dev['index']}] ({dev['name']})"
            )
            return dev["index"], dev["name"]

    # 4. Priority 3: Fall back to system default
    default_dev = next((d for d in devices if d["is_default"]), devices[0])
    return default_dev["index"], default_dev["name"]


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
        help="Index of microphone input device (default is auto-detected).",
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
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.35,
        help="Wake word trigger confidence threshold (default: 0.35).",
    )

    args = parser.parse_args()
    print_banner()
    print_devices()

    # Determine active input device
    selected_idx, selected_name = auto_select_device(args.device)

    settings = get_settings()
    settings.audio.input_device_index = selected_idx
    if args.model:
        settings.audio.whisper_model_size = args.model
    if args.wakeword:
        settings.audio.wake_word_model = args.wakeword
    if args.threshold is not None:
        settings.audio.wake_word_threshold = args.threshold

    print(f"\n[Active Input]: [{selected_idx}] {selected_name}")
    print("Initializing local audio models on CPU (INT8 quantized, capped at 2 threads)...")

    # Define live console callbacks
    def on_wake(score: float) -> None:
        sys.stdout.write(
            f"\r{' ' * 75}\r\n[🔔 WAKE WORD DETECTED!] Trigger: '{settings.audio.wake_word_model}' (Confidence: {score:.2f})\n"
        )
        sys.stdout.write("  -> [🎙️ LISTENING] Speak your command now...\n")
        sys.stdout.flush()

    def on_speech_start() -> None:
        sys.stdout.write(f"\r{' ' * 75}\r  -> [🗣️ SPEECH DETECTED] Collecting speech turn...\n")
        sys.stdout.flush()

    def on_speech_end() -> None:
        sys.stdout.write(
            f"\r{' ' * 75}\r  -> [⏳ PROCESSING] Finished speaking. Transcribing locally with Whisper INT8...\n"
        )
        sys.stdout.flush()

    def on_text(transcript: str) -> None:
        sys.stdout.write(f'\r{" " * 75}\r>>> [💬 TRANSCRIPT]: "{transcript}"\n\n')
        if not args.dictation:
            sys.stdout.write(
                f"[👂 IDLE] Passively listening for '{settings.audio.wake_word_model}'...\n"
            )
        sys.stdout.flush()

    def on_level(rms: float, value: float) -> None:
        meter = render_meter(rms)
        state = coordinator.state
        if state == PipelineState.IDLE:
            status_text = (
                f"\r[👂 IDLE] Mic: {meter} (RMS: {int(rms):4d}) | "
                f"Wake Score: {value:.2f} / {settings.audio.wake_word_threshold:.2f}  "
            )
        elif state == PipelineState.LISTENING:
            mode_tag = "DICTATION" if args.dictation else "LISTENING"
            vad_prob = value
            prob_pct = int(vad_prob * 100)
            speaking_hint = (
                f"🗣️ Speaking ({prob_pct}%)"
                if vad_prob >= settings.audio.vad_threshold
                else f"👂 Listening ({prob_pct}%)"
            )
            status_text = (
                f"\r[🎙️ {mode_tag}] Mic: {meter} (RMS: {int(rms):4d}) | {speaking_hint}   "
            )
        elif state == PipelineState.PROCESSING:
            status_text = f"\r[⏳ PROCESSING] Transcribing with Whisper...{' ' * 20}"
        else:
            status_text = ""

        if status_text:
            sys.stdout.write(status_text)
            sys.stdout.flush()

    coordinator = AudioPipelineCoordinator(
        settings=settings,
        on_wake_word=on_wake,
        on_speech_start=on_speech_start,
        on_speech_end=on_speech_end,
        on_transcript=on_text,
        on_audio_level=on_level,
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
        print("\n\nShutting down audio pipeline cleanly...")
    finally:
        coordinator.stop()
        print("broski audio pipeline stopped. Have a great day!\n")


if __name__ == "__main__":
    main()

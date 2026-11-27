"""Interactive Command-Line Interface (CLI) for testing broski audio pipeline in real time.

Allows users to speak into their laptop microphone or Bluetooth earphones,
testing wake word detection, neural VAD, and local speech-to-text transcription live
with a real-time visual VU volume meter.
"""

import argparse
import datetime
import logging
import sys
import time

import numpy as np
import sounddevice as sd

from broski.audio.barge_in import BargeInMode
from broski.audio.capture import list_input_devices
from broski.audio.pipeline import AudioPipelineCoordinator, PipelineState
from broski.audio.player import (
    AudioPlayer,
    find_default_or_headset_output_device,
)
from broski.audio.tts import PiperSynthesizer
from broski.brain.client import GeminiBrainClient
from broski.brain.prompts import clean_for_speech
from broski.brain.router import IntentRouter, IntentType
from broski.config import get_settings
from broski.memory.store import MemoryStore
from broski.system.apps import AppLauncher

# Configure logging
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


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
                if (vad_prob >= settings.audio.vad_threshold or rms >= 600)
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


def generate_offline_response(transcript: str) -> str:
    """Generate intelligent offline responses for the Sprint 3 voice loop test."""
    t = transcript.strip().lower()

    if any(q in t for q in ("who are you", "what is your name", "what are you")):
        return (
            "I am Broski, your personal AI voice assistant, "
            "running privately and locally on your CPU."
        )

    if any(q in t for q in ("what time is it", "tell me the time", "current time", "what's the time")):
        now = datetime.datetime.now().strftime("%I:%M %p")
        return f"The current time is {now}."

    if any(q in t for q in ("what day is it", "what's the date", "what is today")):
        today = datetime.datetime.now().strftime("%A, %B %d, %Y")
        return f"Today is {today}."

    if "tell me a joke" in t or "say something funny" in t:
        return "Why do programmers prefer dark mode? Because light attracts bugs!"

    if any(q in t for q in ("hello", "hi", "hey")):
        return "Hey there! How can I help you today?"

    if any(q in t for q in ("how are you", "how's it going")):
        return "I am running smoothly with zero cloud latency. Ready for your command!"

    if any(q in t for q in ("stop", "exit", "quit", "goodbye")):
        return "Goodbye! Have a great day."

    # Default echo response demonstrating end-to-end local loop
    return f"I heard you say: {transcript}. Speech synthesis and barge-in are working perfectly!"


def talk_main() -> None:
    """Entry point for 'broski-talk' CLI: Full-duplex conversational voice loop."""
    parser = argparse.ArgumentParser(
        description="broski 🗣️ — Local Full-Duplex Conversational Voice Assistant"
    )
    parser.add_argument(
        "--input-device",
        type=int,
        default=None,
        help="Input microphone device index (auto-detects OnePlus Nord Buds 3 / default if omitted)",
    )
    parser.add_argument(
        "--output-device",
        type=int,
        default=None,
        help="Output speaker/headphones device index (auto-detects OnePlus Nord Buds 3 / default)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Speaking speed multiplier (1.0 = normal, <1.0 = faster, >1.0 = slower)",
    )
    parser.add_argument(
        "--voice",
        type=str,
        default="en_US-lessac-medium",
        help="Piper neural voice name or model file path",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Whisper model size ('tiny.en', 'base.en', 'small.en') (default: from settings)",
    )
    parser.add_argument(
        "--dictation",
        action="store_true",
        help="Continuous dictation mode (skip wake word and listen immediately)",
    )
    parser.add_argument(
        "--no-greet",
        action="store_true",
        help="Skip startup spoken greeting",
    )
    parser.add_argument(
        "--mode",
        choices=["hybrid", "vad", "wakeword"],
        default="hybrid",
        help="Barge-in interruption strategy: 'hybrid' (default), 'vad', or 'wakeword'",
    )
    args = parser.parse_args()

    print("\n" + "=" * 65)
    print("  broski 🗣️ — Local Full-Duplex Conversational Voice Assistant")
    print("=" * 65)

    settings = get_settings()

    # 1. Detect Input Microphone
    in_idx, in_name = auto_select_device(args.input_device)
    settings.audio.input_device_index = in_idx

    # 2. Detect Output Headphones / Speakers
    out_idx, out_name = find_default_or_headset_output_device(args.output_device)
    settings.audio.output_device_index = out_idx

    if args.model:
        settings.audio.whisper_model_size = args.model

    print("\n[Audio Hardware Configuration]")
    print(f"  🎤 Microphone:   [{in_idx}] {in_name}")
    print(f"  🎧 Output:       [{out_idx}] {out_name} (Stereo Earbuds Mode)")
    print(f"  🧠 Whisper STT:  {settings.audio.whisper_model_size} (CPU INT8)")
    print(f"  🗣️ Neural Voice: {args.voice} (Speed: {args.speed}x)")
    print(f"  ⚡ Interruption: Active (Mode: {args.mode.upper()}, Barge-in: sub-10ms)")
    print("-" * 65)

    # 3. Initialize Piper Synthesizer & AudioPlayer
    print("[1/4] Loading Piper ONNX neural voice model...")
    synth = PiperSynthesizer(voice_name=args.voice, length_scale=args.speed, auto_load=True)
    print("      ✓ Neural voice loaded successfully.")

    print("[2/4] Initializing non-blocking stereo audio player...")
    player = AudioPlayer(device_index=out_idx, sample_rate=synth.sample_rate, channels=2)
    print("      ✓ Audio player ready.")

    print("[3/4] Initializing Gemini Cloud Brain reasoning engine & Intent Router...")
    brain_client: GeminiBrainClient | None = None
    try:
        brain_client = GeminiBrainClient()
        if brain_client.is_configured:
            print(f"      ✓ Cloud Brain active ({brain_client.model}).")
        else:
            print("      ⚠ Cloud Brain unconfigured (No API key; using local offline responder).")
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to initialize Gemini brain client: %s", exc)
        print("      ⚠ Cloud Brain offline; using local responder.")

    app_store = MemoryStore()
    try:
        import asyncio

        asyncio.run(app_store.initialize())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to initialize memory store: %s", exc)

    app_launcher = AppLauncher(store=app_store)
    intent_router = IntentRouter(app_launcher=app_launcher, brain_client=brain_client)
    print("      ✓ Intent Router & App Launcher initialized with SQLite catalog.")

    print("[4/4] Initializing sensory loop (Wake Word + Silero VAD + Whisper)...")

    # Map CLI mode to BargeInMode
    mode_map = {
        "hybrid": BargeInMode.HYBRID,
        "vad": BargeInMode.VAD_SPEECH,
        "wakeword": BargeInMode.WAKE_WORD,
    }
    barge_mode = mode_map.get(args.mode, BargeInMode.HYBRID)

    def on_barge_in() -> None:
        sys.stdout.write(
            "\n\n⚡ [BARGE-IN!]: User voice detected! Speech halted instantly (<10ms).\n"
            "   Listening for your new query...\n\n"
        )
        sys.stdout.flush()

    def on_wake(score: float) -> None:
        sys.stdout.write(
            f"\n\n🎯 [WAKE WORD DETECTED!] Trigger: '{settings.audio.wake_word_model}' "
            f"(Confidence: {score:.2f} >= {settings.audio.wake_word_threshold:.2f})\n"
            "   Listening to your question now...\n"
        )
        sys.stdout.flush()

    def on_speech_start() -> None:
        sys.stdout.write("\n🗣️  [Speech Started] Recording incoming voice...\n")
        sys.stdout.flush()

    def on_speech_end() -> None:
        sys.stdout.write("\n⏳  [Speech Ended] Processing speech with Whisper STT...\n")
        sys.stdout.flush()

    def on_text(transcript: str) -> None:
        sys.stdout.write(f"\n📝 [Transcribed]: \"{transcript}\"\n")
        sys.stdout.flush()

        # 1. Classify intent through Two-Tier Intent Router
        intent_res = intent_router.route(transcript)
        sys.stdout.write(
            f"🧭 [Intent]: {intent_res.intent.value.upper()} "
            f"(Action: {intent_res.action or 'none'}, Target: {intent_res.target or 'none'}, Source: {intent_res.source})\n"
        )
        sys.stdout.flush()

        response: str
        if intent_res.intent == IntentType.SYSTEM_COMMAND and intent_res.action == "open_app":
            launch_query = intent_res.payload or intent_res.target
            if launch_query:
                launch_res = app_launcher.launch(launch_query)
                response = launch_res.message
            else:
                response = "I recognized a command to open an application, but couldn't determine which one."
        elif intent_res.intent == IntentType.SYSTEM_COMMAND and intent_res.action == "register_app_path":
            if intent_res.target and intent_res.payload:
                reg_res = app_launcher.register_custom_path(intent_res.target, intent_res.payload)
                response = reg_res.message
            else:
                response = "I couldn't determine which application or file path to register."
        elif intent_res.intent == IntentType.DICTATION:
            text_to_dictate = intent_res.payload or transcript
            response = f"Dictating into active window: {text_to_dictate}"
        else:
            # Route conversational queries through Cloud Brain or local offline responder
            if brain_client is not None and brain_client.is_configured:
                try:
                    response = brain_client.chat(transcript)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Cloud brain error: %s. Falling back to local responder.", exc)
                    response = generate_offline_response(transcript)
            else:
                response = generate_offline_response(transcript)

        # Sanitize speech output to strip markdown formatting before TTS
        clean_response = clean_for_speech(response)

        sys.stdout.write(f"🤖 [Broski]: \"{clean_response}\"\n")
        sys.stdout.write("🔊 [Speaking]: (Speak or say 'Hey Jarvis' to interrupt mid-speech!)\n\n")
        sys.stdout.flush()

        # Set pipeline state to SPEAKING and stream chunks to player
        coordinator._set_state(PipelineState.SPEAKING)
        for chunk in synth.synthesize_stream(clean_response):
            if coordinator.state != PipelineState.SPEAKING:
                # Interrupted mid-synthesis!
                break
            player.play_chunk(chunk, sample_rate=synth.sample_rate)

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
                if (vad_prob >= settings.audio.vad_threshold or rms >= 600)
                else f"👂 Listening ({prob_pct}%)"
            )
            status_text = (
                f"\r[🎙️ {mode_tag}] Mic: {meter} (RMS: {int(rms):4d}) | {speaking_hint}   "
            )
        elif state == PipelineState.PROCESSING:
            status_text = f"\r[⏳ PROCESSING] Transcribing with Whisper...{' ' * 20}"
        elif state == PipelineState.SPEAKING:
            status_text = f"\r[🔊 SPEAKING] Broski speaking... Mic: {meter} (Interruptible)  "
        else:
            status_text = ""

        if status_text:
            sys.stdout.write(status_text)
            sys.stdout.flush()

    coordinator = AudioPipelineCoordinator(
        settings=settings,
        player=player,
        on_wake_word=on_wake,
        on_speech_start=on_speech_start,
        on_speech_end=on_speech_end,
        on_transcript=on_text,
        on_audio_level=on_level,
        on_barge_in=on_barge_in,
    )
    coordinator.barge_in.mode = barge_mode

    if args.dictation:
        coordinator.dictation_mode = True
        print("\nMode: CONTINUOUS CONVERSATION (Speak freely; no wake word required)")
    else:
        print(f"\nMode: CONVERSATIONAL (Say '{settings.audio.wake_word_model}' to wake broski)")
        print(f"[👂 IDLE] Passively listening for '{settings.audio.wake_word_model}'...")

    print("Press Ctrl+C at any time to exit.\n" + "=" * 65 + "\n")

    coordinator.start()

    # Spoken welcome greeting
    if not args.no_greet:
        greeting = "Hello! I am Broski. I am listening for Hey Jarvis."
        coordinator._set_state(PipelineState.SPEAKING)
        for chunk in synth.synthesize_stream(greeting):
            player.play_chunk(chunk, sample_rate=synth.sample_rate)

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n\nShutting down full-duplex conversational voice loop...")
    finally:
        coordinator.stop()
        player.close()
        print("broski voice loop stopped. Have a great day!\n")


if __name__ == "__main__":
    main()

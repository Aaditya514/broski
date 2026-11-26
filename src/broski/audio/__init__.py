"""Audio sensory and output subsystem for broski: capture, ring buffer, VAD, wake word, STT, TTS, playback, and barge-in."""

from broski.audio.barge_in import BargeInDetector, BargeInMode
from broski.audio.capture import AudioCaptureStream, list_input_devices, resample_audio
from broski.audio.pipeline import AudioPipelineCoordinator, PipelineState
from broski.audio.player import (
    AudioPlayer,
    find_default_or_headset_output_device,
    list_output_devices,
)
from broski.audio.ring_buffer import AudioRingBuffer
from broski.audio.stt import WhisperTranscriber
from broski.audio.tts import PiperSynthesizer, resolve_voice_paths
from broski.audio.vad import SileroVADDetector
from broski.audio.wakeword import WakeWordDetector

__all__ = [
    "AudioCaptureStream",
    "AudioPipelineCoordinator",
    "AudioPlayer",
    "AudioRingBuffer",
    "BargeInDetector",
    "BargeInMode",
    "PipelineState",
    "PiperSynthesizer",
    "SileroVADDetector",
    "WakeWordDetector",
    "WhisperTranscriber",
    "find_default_or_headset_output_device",
    "list_input_devices",
    "list_output_devices",
    "resample_audio",
    "resolve_voice_paths",
]

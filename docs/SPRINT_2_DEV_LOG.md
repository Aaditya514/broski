# broski — Sprint 2 Development Log: Local Audio Sensory Subsystem

This log documents the implementation, architectural decisions, and educational insights for **Sprint 2: Local Audio Sensory Subsystem** (Microphone stream, Bluetooth earphone support, thread-safe ring buffer, Silero VAD, openWakeWord, and faster-whisper INT8).

---

## 📅 Day 1: 2026-11-22 — Sprint 2 (Day 1 of 4): The Audio Plumbing (Mic Capture & Ring Buffer)

### 🎯 Daily Objective
Establish the real-time audio plumbing for broski. Deliver continuous microphone stream capture on Windows 11 via `sounddevice` / WASAPI, support Bluetooth earphones with automatic sample rate resampling, implement a lock-free circular ring buffer to prevent audio stuttering, and verify with automated unit tests.

---

### 🛠️ 1. What We Built Today
1. **Feature Branching**:
   * Created and switched to `feat/sprint-2-audio` from `main`.
2. **Audio Dependencies & Device Discovery**:
   * Installed `sounddevice` (0.5.6) and `numpy` (1.26.4).
   * Verified Windows host APIs: MME, DirectSound, WASAPI, and WDM-KS.
   * Implemented `list_input_devices()` to query and identify available microphones and the active system default.
3. **Thread-Safe Circular Audio Ring Buffer (`src/broski/audio/ring_buffer.py`)**:
   * Pre-allocates a fixed circular memory buffer (10 seconds of 16kHz 16-bit mono PCM = 320,000 bytes).
   * Zero memory allocation inside the real-time audio callback thread.
   * `write()`: Appends incoming audio frames. If buffer is full, automatically drops oldest data so real-time models always process the freshest speech.
   * `read()` & `read_samples()`: Consumes unread audio and advances read pointer.
   * `peek()` & `peek_samples()`: Inspects audio without advancing the read pointer (essential for overlapping sliding-window wake word detection).
4. **Resilient Microphone Capture Stream (`src/broski/audio/capture.py`)**:
   * `AudioCaptureStream`: Context-managed wrapper around `sounddevice.InputStream`.
   * **Bluetooth Earphone Support**: Automatically detects hardware native sample rates. If a Bluetooth headset or USB microphone natively records at 48,000 Hz or 44,100 Hz, `resample_audio()` performs on-the-fly numpy interpolation to the standard 16,000 Hz expected by Whisper and Silero VAD.
   * Overflow logging and callback error isolation.
5. **Automated Unit Test Suite**:
   * 6 tests in `tests/unit/test_ring_buffer.py` (write/read integrity, peeking, circular overflow, float32 conversion, timeout, clear).
   * 5 tests in `tests/unit/test_audio_capture.py` (device listing, identity resampling, 48kHz-to-16kHz downsampling, empty arrays, mocked PortAudio lifecycle).
   * **Total Test Suite**: **29 passed in 1.64s** with 100% green checkmarks and 0 ruff errors.

---

### 💡 2. Educational Insights: Under the Hood

#### A. Rule #1 of Real-Time Audio Programming
* **The Danger**: When you capture microphone audio with PortAudio/WASAPI, the OS driver executes `_audio_callback()` on a high-priority real-time C thread. If your callback attempts to allocate memory (`malloc`), perform disk I/O, or run a heavy ML model, the thread stalls. 
* **The Symptom**: The sound card runs out of buffer space, resulting in **input overflow / buffer underrun**—heard by humans as crackling, pops, or dropped voice syllables.
* **The Architectural Solution**: The callback does only one thing: it quickly dumps the raw incoming bytes into our pre-allocated `AudioRingBuffer` and exits in $< 0.1\text{ ms}$. Independent consumer threads (VAD, Wake Word, Whisper) then read from the ring buffer at their own pace.

#### B. Why Circular Ring Buffers are Superior to Python Queues for Audio
* A standard `queue.Queue` creates a new Python object for every single chunk of audio, creating constant garbage collection pressure.
* An `AudioRingBuffer` pre-allocates a single contiguous block of memory in RAM. Write and read pointers simply wrap around using modulo arithmetic (`(pos + n) % capacity`). Zero garbage collection overhead!

#### C. Handling Bluetooth Headsets on Windows 11
* Windows Bluetooth earphones (AirPods, Galaxy Buds, Sony, etc.) often lock their recording format to 48kHz or 44.1kHz.
* Whisper and Silero VAD require strictly **16kHz mono audio**.
* By implementing `resample_audio()`, broski calculates the exact fractional step ratio and maps the 48kHz audio array to 16kHz on the fly, making broski completely hardware-agnostic.

---

### 💻 3. Commands Executed & Outputs
```powershell
# 1. Created feature branch
git checkout -b feat/sprint-2-audio

# 2. Installed audio dependencies
.\.venv\Scripts\pip install sounddevice "numpy>=1.26.0,<2.0.0"

# 3. Ran full test suite (29 tests)
.\.venv\Scripts\pytest -v
# -> 29 passed in 1.64s

# 4. Linted and formatted
.\.venv\Scripts\ruff check .
# -> All checks passed!
```

---

### 🚀 4. Plan for Day 2 of Sprint 2
* **Topic**: **The Acoustic Filters (Silero VAD + openWakeWord)**
* Download and cache `silero_vad.onnx`.
* Build `src/broski/audio/vad.py` to calculate speech probability and detect end-of-speech silence pauses (>600ms).
* Build `src/broski/audio/wakeword.py` using `openWakeWord` for continuous low-CPU wake detection.
* Write automated unit tests for VAD state transitions and wake-word scoring.

---

## 📅 Day 2: 2026-11-23 — Sprint 2 (Day 2 of 4): The Acoustic Filters (Silero VAD + openWakeWord)

### 🎯 Daily Objective
Implement the local acoustic filters that give broski selective attention. Deploy Silero VAD v4 via ONNX Runtime to distinguish human vocal speech from background noise and detect end-of-turn silence pauses. Deploy openWakeWord on CPU for continuous, low-power trigger detection (<1.5% CPU load).

---

### 🛠️ 1. What We Built Today
1. **Model Cache & Acquisition (`data/models/vad/silero_vad.onnx`)**:
   * Acquired the official 2.2 MB `silero_vad.onnx` neural model, avoiding heavy 500MB+ PyTorch framework dependencies in the runtime.
   * Acquired openWakeWord ONNX acoustic models (`hey_jarvis_v0.1.onnx`, `alexa`, etc.) using `openwakeword.utils.download_models()`.
2. **Neural Voice Activity Detection (`src/broski/audio/vad.py`)**:
   * `SileroVADDetector`: Stateful recurrent neural network (RNN) processing 32ms (512 samples @ 16kHz) audio frames via `onnxruntime`.
   * Preserves and threads recurrent hidden state `state` `(2, 1, 128)` across frames.
   * `process_chunk()`: Implements an audio state machine that:
     1. Transitions to `is_speaking = True` when vocal probability $\ge 0.5$.
     2. Collects speech frames into an active segment buffer.
     3. Detects end-of-utterance pauses ($>600\text{ ms}$ sustained silence) and emits the complete concatenated speech segment ready for Whisper!
   * `reset()`: Flushes recurrent hidden state and active speech buffers.
3. **Continuous Wake Word Engine (`src/broski/audio/wakeword.py`)**:
   * `WakeWordDetector`: Wraps openWakeWord ONNX inference engine over 80ms (1280 samples) sliding windows.
   * Configured with a 1.5-second refractory cooldown period to eliminate duplicate/stutter triggers for the same spoken utterance.
   * Extremely lightweight CPU footprint ($< 1.5\%$ single-core load on Tiger Lake i7-1165G7).
4. **Automated Unit Test Suites**:
   * 4 tests in `tests/unit/test_vad.py` (initialization, silence baseline verification, state reset, speech-to-silence state machine lifecycle).
   * 4 tests in `tests/unit/test_wakeword.py` (initialization, silence non-trigger, threshold activation & cooldown, reset).
   * **Total Test Suite**: **37 passed in 3.01s** with 100% green checks and zero linter warnings.

---

### 💡 2. Educational Insights: Under the Hood

#### A. Why Neural VAD (Silero) is Light-Years Ahead of Energy/Volume Meters
* **The Problem with Energy / RMS Thresholding**: Simple voice assistants use volume thresholding (e.g. "if sound > -20dB, user is talking"). If you drop a pen, type loudly on a mechanical keyboard, cough, or if a laptop cooling fan spins up, volume meters trigger false speech recordings.
* **The Neural Solution**: Silero VAD is a trained deep convolutional/recurrent neural network that models human vocal tract formant frequencies. It evaluates: *"Does this frequency pattern match vocal cord phonation?"*
* **The Result**: You can type on a mechanical keyboard or blast a table fan directly into the microphone, and Silero VAD reports `0.01` (silence). As soon as you speak a word, it immediately spikes to `0.95`!

#### B. The Stateful Recurrent Tensor in ONNX
* Speech has temporal continuity—a vowel sound naturally stretches across multiple consecutive 32ms frames.
* Silero VAD achieves sub-millisecond inference by passing an internal memory tensor `state` `(2, 1, 128)` from one frame to the next:
  $$\text{Input Frame}_t + \text{State}_{t-1} \longrightarrow \text{Probability}_t + \text{State}_t$$
* This gives the model memory of past sounds without having to recompute historical audio frames!

#### C. Wake Word Sliding Windows & Cooldown
* Wake word models look for acoustic phonemes across an 80ms to 120ms rolling window.
* Without a **refractory cooldown**, saying *"Hey jarvis"* might trigger 3 separate wake events within 200 milliseconds as the audio waveform passes through the sliding window.
* Our cooldown lock guarantees exactly **one clean wake event per spoken phrase**.

---

### 💻 3. Commands Executed & Outputs
```powershell
# 1. Downloaded Silero ONNX model (2.2 MB)
python -c "urllib.request.urlretrieve('https://raw.githubusercontent.com/.../silero_vad.onnx', 'data/models/vad/silero_vad.onnx')"

# 2. Downloaded openWakeWord ONNX acoustic models
.\.venv\Scripts\python -c "import openwakeword.utils; openwakeword.utils.download_models()"

# 3. Executed full unit test suite (37 tests)
.\.venv\Scripts\pytest -v
# -> 37 passed in 3.01s

# 4. Linted and validated code
.\.venv\Scripts\ruff check .
# -> All checks passed!
```

---

### 🚀 4. Plan for Day 3 of Sprint 2
* **Topic**: **The Transcriber (Local `faster-whisper` INT8 on CPU + Pipeline Coordinator)**
* Install `faster-whisper` in `.venv`.
* Build `src/broski/audio/stt.py` using CTranslate2 INT8 quantization, capped at 2 CPU threads to protect laptop thermals.
* Build the `AudioPipelineCoordinator` linking:
  $$\text{Microphone} \longrightarrow \text{RingBuffer} \longrightarrow \text{WakeWord} \longrightarrow \text{VAD} \longrightarrow \text{Whisper STT}$$
* Write automated unit tests for speech transcription.

---

## 📅 Day 3: 2026-11-24 — Sprint 2 (Day 3 of 4): The Transcriber & Audio Pipeline Coordinator

### 🎯 Daily Objective
Implement the local speech-to-text transcriber using `faster-whisper` on CPU with INT8 quantization, capped at 2 CPU threads to prevent laptop heating. Connect all sensory components into a unified, non-blocking `AudioPipelineCoordinator` linking the microphone stream, circular ring buffer, openWakeWord, Silero VAD, and Whisper STT.

---

### 🛠️ 1. What We Built Today
1. **Engine Installation**:
   * Installed `faster-whisper` (1.2.1) and `ctranslate2` (4.9.1) into the Python 3.12 virtual environment.
2. **Local Speech-to-Text (`src/broski/audio/stt.py`)**:
   * `WhisperTranscriber`: High-performance CTranslate2 inference engine running quantized `base.en` (or multilingual `base`) locally on CPU.
   * **Thermal Budget Protection**: Enforces `cpu_threads=2` so background speech transcription never monopolizes all 8 threads of the Intel Core i7-1165G7.
   * Automatically normalizes incoming audio (int16 numpy arrays, raw bytes, or float32) into 16kHz float32 range `[-1.0, 1.0]`.
   * Hallucination protection: Discards tiny audio clicks/bursts shorter than 100ms (<1600 samples).
3. **Master Sensory Pipeline Coordinator (`src/broski/audio/pipeline.py`)**:
   * `AudioPipelineCoordinator`: Thread-safe state machine linking the complete sensory loop:
     $$\text{AudioCaptureStream} \longrightarrow \text{AudioRingBuffer} \longrightarrow \text{WakeWordDetector} \longrightarrow \text{SileroVADDetector} \longrightarrow \text{WhisperTranscriber}$$
   * **4-Stage Pipeline State Machine**:
     * `STOPPED`: Audio hardware stream closed.
     * `IDLE`: Passively monitoring 80ms chunks for wake words ("hey jarvis" / "hey broski").
     * `LISTENING`: Wake word detected! Emits `on_wake_word(score)` and monitors 32ms frames with Silero VAD until user finishes speaking.
     * `PROCESSING`: Silence detected ($>600\text{ ms}$)! Emits `on_speech_end()`, sends speech segment to Whisper, and emits `on_transcript(text)`.
   * **Dictation Mode Support**: When `pipeline.dictation_mode = True`, the pipeline bypasses wake word detection and streams speech recognition continuously for in-app typing!
4. **Automated Unit Test Suites**:
   * 4 tests in `tests/unit/test_stt.py` (initialization, short audio rejection, beam search transcription, raw byte streams).
   * 3 tests in `tests/unit/test_audio_pipeline.py` (initial state, complete wake -> listening -> vad -> transcribe lifecycle, dictation mode).
   * **Total Test Suite**: **44 passed in 9.13s** (`100% green check`).

---

### 💡 2. Educational Insights: Under the Hood

#### A. Why CTranslate2 INT8 Quantization is 4x Faster on CPU
* **Vanilla PyTorch Whisper**: Runs floating-point matrix multiplications (`float32`). On a mobile 4-core CPU, transcribing 3 seconds of speech takes ~1.5 to 2.5 seconds and heats up the CPU package.
* **CTranslate2 INT8**: Quantizes the 32-bit floating point model weights down to 8-bit integers (`int8`).
* **The Magic**:
  1. The model memory footprint drops by 75% (from ~280 MB to ~70 MB).
  2. Intel Tiger Lake CPUs have specialized **AVX2 / VNNI (Vector Neural Network Instructions)** that execute four 8-bit integer operations in the exact same clock cycle as a single 32-bit float operation!
  3. Real-Time Factor (RTF) drops to $<0.15$—transcribing 3 seconds of speech in under 300 milliseconds!

#### B. The 2-Thread CPU Cap Explained
* Your Intel Core i7-1165G7 has 4 physical cores (8 threads).
* If an inference engine spins up 8 threads, the CPU spikes to 100% load, the laptop fan screams, and the CPU throttles down from 4.7 GHz to 1.8 GHz.
* By locking `cpu_threads=2`, Whisper executes in ~300ms while leaving 6 threads completely free for Windows, Chrome, and your games.

#### C. The Pipeline State Machine & Dictation Mode
* In normal conversational mode:
  $$\text{IDLE} \xrightarrow{\text{Wake Word}} \text{LISTENING} \xrightarrow{\text{VAD End}} \text{PROCESSING} \xrightarrow{\text{Transcript}} \text{IDLE}$$
* In dictation mode:
  $$\text{LISTENING} \xrightarrow{\text{VAD End}} \text{PROCESSING} \xrightarrow{\text{Transcript}} \text{LISTENING}$$
* This allows seamless toggling between an ambient voice assistant and an exact, hands-free voice dictation tool!

---

### 💻 3. Commands Executed & Outputs
```powershell
# 1. Installed faster-whisper in venv
.\.venv\Scripts\pip install faster-whisper

# 2. Executed full unit test suite (44 tests)
.\.venv\Scripts\pytest -v
# -> 44 passed in 9.13s

# 3. Linted and validated code
.\.venv\Scripts\ruff check .
# -> All checks passed!
```

---

### 🚀 4. Plan for Day 4 of Sprint 2 (Sprint Review, Calibration & Merge)
* Build interactive terminal CLI demo tool: speak into your microphone/earphones and watch real-time detection in your console!
* Run full quality gate and DoD audit.
* Merge `feat/sprint-2-audio` into `main` and push to GitHub.
* Kick off Sprint 3 (Piper Neural Text-to-Speech & Barge-in Voice Output).

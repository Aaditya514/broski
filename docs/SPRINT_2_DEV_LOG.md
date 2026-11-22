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

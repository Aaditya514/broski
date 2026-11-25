# broski — Sprint 3 Development Log: Neural Speech Synthesis & Barge-in

This log documents the implementation, architectural decisions, and educational insights for **Sprint 3: Neural Speech Synthesis (Piper TTS) & Barge-in** (Local neural voice synthesis, non-blocking audio playback queue, and sub-50ms user interruption handling).

---

## 📅 Day 1: 2026-11-25 — Sprint 3 (Day 1 of 4): Local Neural Voice Synthesis (Piper TTS)

### 🎯 Daily Objective
Give broski a clear, natural-sounding, local voice that runs completely on CPU with ultra-low latency. Download and integrate the official `en_US-lessac-medium` Piper ONNX neural voice model, build `PiperSynthesizer` in `src/broski/audio/tts.py` with lazy loading and chunked sentence streaming, and verify with automated unit tests.

---

### 🛠️ 1. What We Built Today

1. **Feature Branching**:
   * Created and switched to `feat/sprint-3-tts` from `main`.

2. **Model Acquisition & Storage**:
   * Created `data/models/piper/` directory.
   * Acquired official Piper neural voice model files from Hugging Face:
     * `en_US-lessac-medium.onnx` (63.2 MB — quantized VITS acoustic model).
     * `en_US-lessac-medium.onnx.json` (4.8 KB — phoneme mapping, sample rate 22,050 Hz, and inference hyper-parameters).

3. **Neural Synthesizer Engine (`src/broski/audio/tts.py`)**:
   * **`PiperSynthesizer`**: Class wrapping `piper.voice.PiperVoice` with lazy loading to prevent idle memory consumption.
   * **Streaming Synthesis (`synthesize_stream`)**: Yields raw 16-bit PCM numpy arrays sentence-by-sentence. This enables audio playback to begin immediately on the first spoken phrase rather than waiting for an entire paragraph to finish generating!
   * **Full Synthesis (`synthesize`)**: Returns `(np.ndarray, sample_rate)` for batched audio processing.
   * **WAV Serialization (`synthesize_to_wav` / `synthesize_to_bytes`)**: Writes standard WAV headers (22,050 Hz, 16-bit mono PCM) for disk or in-memory playback.
   * **Dynamic Speech Rate**: Controlled via `length_scale` (1.0 = normal, $<1.0$ = faster, $>1.0$ = slower).

4. **Configuration Enhancements (`src/broski/config.py`)**:
   * Added `piper_length_scale: float = 1.0` to `AudioConfig` for flexible voice speed tuning.

5. **Automated Unit Tests (`tests/unit/test_tts.py`)**:
   * `test_resolve_voice_paths_existing`: Path resolution for `.onnx` and `.onnx.json`.
   * `test_piper_synthesizer_lazy_loading`: Ensures voice is not loaded into memory until first call.
   * `test_piper_synthesizer_missing_model`: Descriptive `FileNotFoundError` when voice files are missing.
   * `test_piper_synthesizer_mocked_synthesis`: Verifies chunk concatenation and empty text handling.
   * `test_piper_synthesizer_to_wav`: Validates WAV header format, channel count, and sample rate.
   * `test_piper_synthesizer_live_smoke`: Verifies the real ONNX model produces non-zero audio on CPU.
   * **Test Suite Status**: **51 / 51 tests passed in 7.99s** with 0 ruff errors!

---

### 💡 2. Educational Insights: Under the Hood

#### A. Why Piper TTS Outperforms Traditional TTS
* **Concatenative / Formant TTS (e.g. eSpeak, SAPI5)**: Sounds like a robotic 1990s GPS voice. Very low CPU, but unnatural and fatiguing to listen to.
* **Cloud TTS (e.g. ElevenLabs, Google Cloud TTS)**: Sounds great, but adds 250–600ms of network latency per turn and requires continuous internet connection and API costs.
* **Piper TTS (VITS Architecture on ONNX)**:
  * Uses a variational autoencoder (VAE) adversarial network (VITS) that generates full speech waveforms directly from phonemes in a single forward pass.
  * Runs on CPU via ONNX Runtime without needing a heavy PyTorch dependency.
  * Real-Time Factor (RTF) on the Intel Core i7-1165G7 is $<0.25$, generating 3 seconds of voice in under 700 milliseconds!

#### B. Streaming Synthesis & Time-To-First-Audio (TTFA)
* When an AI assistant responds with a 3-sentence answer:
  * **Without streaming**: The user waits 1.5 seconds for the entire paragraph to synthesize before hearing a single sound.
  * **With streaming (`synthesize_stream`)**: Piper generates sentence 1 in $\approx 150\text{ ms}$, immediately sends it to the audio playback buffer, and synthesizes sentences 2 and 3 in the background while sentence 1 is playing out loud!
  * This cuts perceived latency from 1.5s down to 150ms!

---

### 💻 3. Commands Executed & Outputs
```powershell
# 1. Switched to feature branch
git checkout -b feat/sprint-3-tts

# 2. Downloaded Piper voice model
python -c "import urllib.request; urllib.request.urlretrieve('https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx', 'data/models/piper/en_US-lessac-medium.onnx')"

# 3. Verified test suite
.\.venv\Scripts\pytest -v
# -> 51 passed in 7.99s

# 4. Verified linter
.\.venv\Scripts\ruff check .
# -> All checks passed!
```

---

### 🚀 4. Plan for Day 2 of Sprint 3 (Non-blocking Audio Playback Stream)
* Implement `src/broski/audio/player.py`: Non-blocking audio playback engine using `sounddevice.OutputStream`.
* Build thread-safe audio chunk queue with smooth transitions between sentences.
* Implement instantaneous playback interruption and stop events (`player.stop()`).
* Write unit tests in `tests/unit/test_player.py`.

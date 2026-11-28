# broski 🎙️
**Personal Windows AI Voice Assistant**

*A modular, local-first, low-latency AI voice assistant and companion engineered for Windows 11 power users and developers.*

---

## 📖 Table of Contents
- [Project Overview](#project-overview)
- [Architecture & Tech Stack](#architecture--tech-stack)
- [Hardware Target](#hardware-target)
- [Voice Commands & Capabilities](#voice-commands--capabilities)
- [Quickstart Guide](#quickstart-guide)
- [Documentation & Dev Logs](#documentation--dev-logs)
- [Sprint Roadmap](#sprint-roadmap)
- [Agile Methodology & Git Workflow](#agile-methodology--git-workflow)

---

## 🌟 Project Overview
**broski** bridges ultra-low latency local sensory processing (wake word detection, voice activity detection, speech-to-text, and neural text-to-speech) with cloud reasoning (Google Gemini API). It acts as an ambient desktop companion capable of:
* Listening for `"Hey Jarvis"` / `"Hey broski"` with minimal CPU footprint (<1.5% CPU).
* Dynamic digital software amplification for quiet Bluetooth earbuds (OnePlus Nord Buds 3, AirPods).
* Two-Tier Intent Routing: Sub-0.1ms local deterministic regex rule matching + Gemini 3.1 Flash-Lite structured JSON classification.
* Security Whitelist App Launching for Obsidian, Google Chrome, Spotify, VS Code, Discord, Terminal, Notepad, Riot Games, Valorant, and Steam.
* Voice-driven Google Chrome multi-account profile switching that completely bypasses the modal Profile Picker dialog.
* Active Window Text Injection (`ActiveWindowInjector`): Simulates native Unicode keystrokes (`SendInput`) and fast clipboard paste (`Ctrl+V`) into whichever application has active focus.
* Continuous Dictation Mode (`broski-talk --dictation`): Speak freely and have thoughts typed directly into Obsidian or VS Code in real time.
* Authentic, warm, and chill "bro" persona across conversational dialogue and spoken affirmations.

---

## 🛠️ Architecture & Tech Stack

| Layer | Technology | Role & Optimization |
| :--- | :--- | :--- |
| **Wake Word** | `openWakeWord` | Continuous ONNX acoustic model (<1.5% CPU) with dynamic digital gain boost |
| **Voice Detection** | `Silero VAD v4` | End-of-speech segmenter and silence thresholding (ONNX runtime) |
| **Speech-to-Text** | `faster-whisper` | INT8 CTranslate2 on CPU with domain vocabulary prompt conditioning |
| **Text-to-Speech** | `Piper TTS` | Ultra-fast local neural voice (`en_US-lessac-medium`, <180ms to first audio) |
| **Brain / Cloud LLM** | `Google Gemini API` | `gemini-3.1-flash-lite` via modern `google-genai` SDK with multi-turn chat memory |
| **Intent Router** | Two-Tier Hybrid | Tier 1: Local regex heuristics (<0.1ms); Tier 2: Gemini structured JSON output |
| **OS Automation** | `ctypes` / Windows API | Native 64-bit `SendInput(KEYEVENTF_UNICODE)` and clipboard paste/restore |
| **App Security** | Whitelist Gating | Strictly pre-approved binary whitelist with dynamic Windows Registry discovery |
| **Memory / Audit** | `aiosqlite` | Non-blocking local SQLite storage in `data/broski.db` with learned custom paths |

---

## 💻 Hardware Target
* **CPU**: Intel Core i7-1165G7 (4 Cores / 8 Threads, 15W–28W cTDP).
* **RAM**: 16 GB DDR4/LPDDR4x.
* **GPU**: Intel Iris Xe Integrated Graphics (Shared Memory).
* **Audio**: Direct Bluetooth Stream (OnePlus Nord Buds 3) / Realtek HD Audio Stereo.
* **OS**: Windows 11 (64-bit).

---

## 🗣️ Voice Commands & Capabilities

### 1. Application Launching & Profile Switching
* *"Hey Jarvis, open Chrome"* $\longrightarrow$ *"Yea bro, opening Chrome right now!"* (Launches default profile directly, bypassing profile picker).
* *"Hey Jarvis, open Personal Chrome"* $\longrightarrow$ Launches specific Google account profile directly.
* *"Hey Jarvis, open Riot Games"* / *"open Valorant"* $\longrightarrow$ Launches Riot Client / Valorant.
* *"Hey Jarvis, open Obsidian"* $\longrightarrow$ Launches Obsidian vault.
* *"Hey Jarvis, launch Spotify"* $\longrightarrow$ Opens Spotify via Windows URI protocol.

### 2. Active Window Text Injection & Dictation
* *"Hey Jarvis, type meeting notes: discussed Sprint 4 roadmap"* $\longrightarrow$ Types directly into active cursor position.
* *"Hey Jarvis, write down remember to call mom"* $\longrightarrow$ Injects into active note/editor.
* Continuous mode: `broski-talk --dictation` $\longrightarrow$ Every spoken thought is injected directly into your active window without wake words.

### 3. Conversational Reasoning & Chat
* *"Hey Jarvis, what's up bro?"* $\longrightarrow$ Friendly, casual developer peer dialogue powered by Gemini 3.1 Flash-Lite.
* Full-duplex barge-in: Interrupt broski at any point mid-speech simply by speaking or saying the wake word.

---

## ⚡ Quickstart Guide

Run the live assistant directly from PowerShell:

```powershell
# 1. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 2. Run Full-Duplex Conversational Voice Assistant:
broski-talk

# 3. Adjust Wake Word Threshold (default: 0.30 for normal speaking volume):
broski-talk --threshold 0.25

# 4. Run in Continuous Dictation Mode (Direct Text Injection):
broski-talk --dictation

# 5. Run Sensory Listener Only (Wake Word + VAD + Whisper STT):
broski-listen
```

---

## 📚 Documentation & Dev Logs
* 📄 **[Product Requirements Document (PRD)](docs/PRD.md)**: Detailed Epics, User Stories with Given-When-Then criteria, and Definition of Done.
* 🏗️ **[System Architecture](docs/ARCHITECTURE.md)**: Overall master architecture, micro-kernel design, state machine, risk gating, and component diagrams.
* 📓 **[Engineering Journal Index](docs/DEV_LOG.md)**: Central directory linking to every individual sprint dev log.
  * 📄 **[Sprint 1 Dev Log](docs/SPRINT_1_DEV_LOG.md)**: Foundation, SQLite WAL engine, Pydantic settings, and test suite (18/18 tests).
  * 📄 **[Sprint 2 Dev Log](docs/SPRINT_2_DEV_LOG.md)**: Local audio sensory subsystem, WASAPI/Bluetooth stream, Silero VAD, openWakeWord, Whisper INT8, and live CLI (45/45 tests).
  * 📄 **[Sprint 3 Dev Log](docs/SPRINT_3_DEV_LOG.md)**: Neural speech synthesis (Piper TTS) & full-duplex barge-in (76/76 tests).
  * 📄 **[Sprint 4 Dev Log](docs/SPRINT_4_DEV_LOG.md)**: Cloud Brain, Two-Tier Intent Router, Chrome profiles, Active Window Text Injection, and Contextual Disambiguation (126/126 tests).
  * 📄 **[Sprint 5 Dev Log](docs/SPRINT_5_DEV_LOG.md)**: Security Gated System Tools, Obsidian Vault Client, Developer Git Assistant, and Chrome Browser Automation (181/181 tests).

---

## 🗺️ Sprint Roadmap

| Sprint | Milestone / Subsystem | Status | Dev Log Link |
| :---: | :--- | :---: | :--- |
| **Sprint 1** | **Foundation & Core Infrastructure**<br>• Python 3.12 `.venv` & `pyproject.toml`<br>• Pydantic Settings & `.env`<br>• Async SQLite Engine (`aiosqlite` WAL mode)<br>• MemoryStore DAO & App Registry | **COMPLETED** | 📄 **[Sprint 1 Dev Log](docs/SPRINT_1_DEV_LOG.md)** |
| **Sprint 2** | **Local Audio Sensory Subsystem**<br>• Hardware Discovery & WASAPI / Bluetooth Stream<br>• Lock-Free Circular Audio Ring Buffer<br>• Silero VAD v4 Neural Voice Detection<br>• Low-CPU Wake Word (`openWakeWord`) with Gain Boost<br>• Local Speech-to-Text (`faster-whisper` INT8 on CPU)<br>• Interactive Live Terminal CLI (`broski-listen`) | **COMPLETED** | 📄 **[Sprint 2 Dev Log](docs/SPRINT_2_DEV_LOG.md)** |
| **Sprint 3** | **Neural Speech Synthesis & Barge-in**<br>• Piper TTS ONNX local voice synthesis (`en_US-lessac-medium`)<br>• Non-blocking audio playback stream (`sounddevice.OutputStream`)<br>• Thread-safe chunk queue & stereo earbud duplication<br>• Full-duplex barge-in detector (`BargeInDetector`, <10ms)<br>• Interactive Full-Duplex Voice CLI (`broski-talk`) | **COMPLETED** | 📄 **[Sprint 3 Dev Log](docs/SPRINT_3_DEV_LOG.md)** |
| **Sprint 4** | **Cloud Brain, Intent Routing & Active Window Text Injection**<br>• Google Gemini API (`google-genai` SDK `gemini-3.1-flash-lite`)<br>• Two-tier intent router (Local heuristics + Cloud LLM)<br>• Windows whitelist app launcher & Chrome profile manager<br>• Active-window text injection (SendInput Unicode & Clipboard Paste)<br>• Contextual pronoun resolution & intent disambiguation<br>• Friendly bro persona across affirmations and dialogue | **COMPLETED**<br>*(126/126 tests passing)* | 📄 **[Sprint 4 Dev Log](docs/SPRINT_4_DEV_LOG.md)** |
| **Sprint 5** | **Security Gated System Tools & Deep Integrations**<br>• 3-Tier Security Confirmation & Risk Gating (`SAFE`, `MODERATE`, `CRITICAL`)<br>• Obsidian Local REST API vault client (read/append daily note & search)<br>• Developer Git assistant (zero-shell repo status, diffs, commits, pushes)<br>• Chrome browser automation & zero-dependency webpage text reader<br>• Voice confirmation handshake for critical mutations | **COMPLETED**<br>*(181/181 tests passing)* | 📄 **[Sprint 5 Dev Log](docs/SPRINT_5_DEV_LOG.md)** |
| **Sprint 6** | **PySide6 Desktop UI & System Hardening**<br>• Floating translucent HUD pill<br>• System tray menu and controls<br>• Custom "Hey broski" openWakeWord model calibration | **UPCOMING** | 📄 *Pending* |

---

## 🔄 Agile Methodology & Git Workflow
All development strictly follows a feature-branching workflow:
1. `main` branch holds production-ready, verified code.
2. New work begins on a branch: `git checkout -b <type>/<description>`.
3. Changes are committed atomically using conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
4. Automated unit tests must pass before merging.
5. Work is merged back into `main` with `--no-ff` and documented in `docs/DEV_LOG.md`.

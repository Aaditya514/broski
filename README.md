# broski 🎙️
**Personal Windows AI Voice Assistant**

*A modular, local-first, low-latency AI voice assistant engineered for Windows 11 power users and developers.*

---

## 📖 Table of Contents
- [Project Overview](#project-overview)
- [Architecture & Tech Stack](#architecture--tech-stack)
- [Hardware Target](#hardware-target)
- [Documentation & Dev Logs](#documentation--dev-logs)
- [Agile Methodology & Git Workflow](#agile-methodology--git-workflow)
- [Sprint Roadmap](#sprint-roadmap)

---

## 🌟 Project Overview
**broski** bridges local sensory processing (wake word detection, voice activity detection, speech-to-text, and neural text-to-speech) with cloud reasoning (Google Gemini API). It acts as an ambient desktop companion capable of:
* Listening for `"Hey broski"` with minimal CPU footprint.
* Transcribing and streaming exact voice dictation into the currently focused Windows app.
* Enhancing rough dictated thoughts into polished writing in-place.
* Controlling Windows applications and system state with strict security approval gates.
* Interacting with Obsidian vaults and Google Chrome tabs.
* Providing persistent, user-sovereign local memory backed by SQLite.

---

## 🛠️ Architecture & Tech Stack

| Layer | Technology | Role & Optimization |
| :--- | :--- | :--- |
| **Wake Word** | `openWakeWord` | Continuous ONNX acoustic model (<1.5% CPU) |
| **Voice Detection** | `Silero VAD v4` | End-of-speech segmenter and silence thresholding |
| **Speech-to-Text** | `faster-whisper` | INT8 CTranslate2 on CPU (2 worker threads) |
| **Text-to-Speech** | `Piper TTS` | Ultra-fast local neural voice (<180ms to first audio) |
| **Brain / LLM** | `Google Gemini API` | Multi-turn reasoning, streaming tool calling via `google-genai` |
| **OS Automation** | `pywin32` / `pywinauto` | Native `SendInput(KEYEVENTF_UNICODE)` and window control |
| **Memory / Audit** | `aiosqlite` | Non-blocking local SQLite storage in `data/broski.db` |
| **Desktop UI** | `PySide6` | Translucent floating HUD, system tray, and permission modals |
| **Integrations** | `playwright`, `httpx` | Chrome DevTools automation and Obsidian Local REST API |

---

## 💻 Hardware Target
* **CPU**: Intel Core i7-1165G7 (4 Cores / 8 Threads, 15W–28W cTDP).
* **RAM**: 16 GB DDR4/LPDDR4x.
* **GPU**: Intel Iris Xe Integrated Graphics (Shared Memory).
* **OS**: Windows 11 (64-bit).

---

## 📚 Documentation & Dev Logs
* 📄 **[Product Requirements Document (PRD)](docs/PRD.md)**: Detailed Epics, User Stories with Given-When-Then criteria, and Definition of Done.
* 🏗️ **[System Architecture](docs/ARCHITECTURE.md)**: Overall master architecture, micro-kernel design, state machine, risk gating, and component diagrams.
* 📓 **[Engineering Journal Index](docs/DEV_LOG.md)**: Central directory linking to every individual sprint dev log.
  * 📄 **[Sprint 1 Dev Log](docs/SPRINT_1_DEV_LOG.md)**: Foundation, SQLite WAL engine, Pydantic settings, and test suite (18/18 tests).
  * 📄 **[Sprint 2 Dev Log](docs/SPRINT_2_DEV_LOG.md)**: Local audio sensory subsystem, WASAPI/Bluetooth stream, Silero VAD, openWakeWord, Whisper INT8, and live CLI (45/45 tests).
  * 📄 **[Sprint 3 Dev Log](docs/SPRINT_3_DEV_LOG.md)**: Neural speech synthesis (Piper TTS) & barge-in voice output.

---

## ⚡ Quickstart: Real-Time Audio Sensory & Voice Pipeline

Run the live audio sensory pipeline directly from PowerShell:

```powershell
# 1. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 2. Run Full-Duplex Voice Assistant (Listen + Speak + Mid-Sentence Barge-in):
broski-talk

# 3. Or run Sensory Listener Only (Wake Word + VAD + Whisper STT):
broski-listen

# 4. Or run in Continuous Dictation Mode:
broski-talk --dictation
```

---

## 🗺️ Sprint Roadmap

| Sprint | Milestone / Subsystem | Status | Dev Log Link |
| :---: | :--- | :---: | :--- |
| **Sprint 1** | **Foundation & Core Infrastructure**<br>• Python 3.12 `.venv` & `pyproject.toml`<br>• Pydantic Settings & `.env`<br>• Async SQLite Engine (`aiosqlite` WAL mode)<br>• MemoryStore DAO & App Registry | **COMPLETED** | 📄 **[Sprint 1 Dev Log](docs/SPRINT_1_DEV_LOG.md)** |
| **Sprint 2** | **Local Audio Sensory Subsystem**<br>• Hardware Discovery & WASAPI / Bluetooth Stream<br>• Lock-Free Circular Audio Ring Buffer<br>• Silero VAD v4 Neural Voice Detection<br>• Low-CPU Wake Word (`openWakeWord`)<br>• Local Speech-to-Text (`faster-whisper` INT8 on CPU)<br>• Interactive Live Terminal CLI (`broski-listen`) | **COMPLETED** | 📄 **[Sprint 2 Dev Log](docs/SPRINT_2_DEV_LOG.md)** |
| **Sprint 3** | **Neural Speech Synthesis & Barge-in**<br>• Piper TTS ONNX local voice synthesis (`en_US-lessac-medium`)<br>• Non-blocking audio playback stream (`sounddevice.OutputStream`)<br>• Thread-safe chunk queue & stereo earbud duplication<br>• Full-duplex barge-in detector (`BargeInDetector`)<br>• Interactive Full-Duplex Voice CLI (`broski-talk`) | **COMPLETED** | 📄 **[Sprint 3 Dev Log](docs/SPRINT_3_DEV_LOG.md)** |
| **Sprint 4** | **Cloud Brain, Intent Routing & Active Window Text Injection**<br>• Google Gemini API (`google-genai` SDK)<br>• Function calling & prompt engineering<br>• Windows `SendInput` active-window text typing | **UPCOMING** | 📄 *Pending* |
| **Sprint 5** | **Security Gated System Tools & Deep Integrations**<br>• Whitelist app launcher (Riot Games, Steam, Discord)<br>• Chrome browser automation (Playwright)<br>• Obsidian Local REST API vault client<br>• Git developer ops & 3-tier security confirmation dialog | **UPCOMING** | 📄 *Pending* |
| **Sprint 6** | **PySide6 Desktop UI & System Hardening**<br>• Floating translucent HUD pill<br>• System tray menu and controls<br>• Custom "Hey broski" openWakeWord model calibration | **UPCOMING** | 📄 *Pending* |

---

## 🔄 Agile Methodology & Git Workflow
All development strictly follows a feature-branching workflow:
1. `main` branch holds production-ready, verified code.
2. New work begins on a branch: `git checkout -b <type>/<description>`.
3. Changes are committed atomically using conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
4. Automated unit tests must pass before merging.
5. Work is merged back into `main` with `--no-ff` and documented in `docs/DEV_LOG.md`.

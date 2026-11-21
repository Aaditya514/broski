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
  * 📄 **[Sprint 1 Dev Log](docs/SPRINT_1_DEV_LOG.md)**: Foundation, SQLite WAL engine, Pydantic settings, and test suite.

---

## 🔄 Agile Methodology & Git Workflow
All development strictly follows a feature-branching workflow:
1. `main` branch holds production-ready, verified code.
2. New work begins on a branch: `git checkout -b <type>/<description>`.
3. Changes are committed atomically using conventional commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`).
4. Automated unit tests must pass before merging.
5. Work is merged back into `main` and documented in `docs/DEV_LOG.md`.

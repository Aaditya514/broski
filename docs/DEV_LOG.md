# broski — Engineering Journal & Sprint Dev Logs Index

This index organizes the engineering logs, daily progress, and educational deep-dives across all Agile development sprints for **broski**.

---

## 📚 Sprint Development Logs

| Sprint | Milestone / Subsystem | Status | Dev Log Link |
| :---: | :--- | :---: | :--- |
| **Sprint 0 & 1** | **Foundation & Core Infrastructure**<br>• Project Setup, Architecture & PRD<br>• Python 3.12 `.venv` & `pyproject.toml`<br>• Pydantic Settings & `.env.example`<br>• Async SQLite Engine (`aiosqlite` WAL mode)<br>• MemoryStore DAO & App Registry (Riot Games, Spotify)<br>• Quality Gate (18/18 Unit Tests Passing) | **COMPLETED** | 📄 **[Sprint 1 Dev Log](SPRINT_1_DEV_LOG.md)** |
| **Sprint 2** | **Local Audio Sensory Subsystem**<br>• Hardware Discovery & Capture Stream (WASAPI / Bluetooth Earphones)<br>• Lock-Free Audio Ring Buffer<br>• Neural Voice Activity Detection (Silero VAD v4 ONNX)<br>• Low-CPU Wake Word Detection (`openWakeWord`)<br>• Local Speech-to-Text (`faster-whisper` INT8 on CPU)<br>• Interactive Live Terminal CLI (`broski-listen`) | **COMPLETED** | 📄 **[Sprint 2 Dev Log](SPRINT_2_DEV_LOG.md)** |
| **Sprint 3** | **Neural Speech Synthesis & Barge-in**<br>• Piper TTS ONNX local voice synthesis<br>• Non-blocking audio playback stream<br>• Interruption / barge-in detector | **PLANNED** | 📄 *[Sprint 3 Dev Log](SPRINT_3_DEV_LOG.md) (Starting next)* |
| **Sprint 4** | **Cloud Brain, Intent Routing & Active Window Text Injection**<br>• Google Gemini API (`google-genai` SDK)<br>• Function calling & prompt engineering<br>• Windows `SendInput` active-window text typing | **UPCOMING** | 📄 *Pending* |
| **Sprint 5** | **Security Gated System Tools & Deep Integrations**<br>• Whitelist app launcher (Riot Games, Steam, Discord)<br>• Chrome browser automation (Playwright)<br>• Obsidian Local REST API vault client<br>• Git developer ops & 3-tier security confirmation dialog | **UPCOMING** | 📄 *Pending* |
| **Sprint 6** | **PySide6 Desktop UI & System Hardening**<br>• Floating translucent HUD pill<br>• System tray menu and controls<br>• Custom "Hey broski" openWakeWord model calibration | **UPCOMING** | 📄 *Pending* |

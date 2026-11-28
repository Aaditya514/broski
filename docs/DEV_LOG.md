# broski — Engineering Journal & Sprint Dev Logs Index

This index organizes the engineering logs, daily progress, and educational deep-dives across all Agile development sprints for **broski**.

---

## 📚 Sprint Development Logs

| Sprint | Milestone / Subsystem | Status | Dev Log Link |
| :---: | :--- | :---: | :--- |
| **Sprint 0 & 1** | **Foundation & Core Infrastructure**<br>• Project Setup, Architecture & PRD<br>• Python 3.12 `.venv` & `pyproject.toml`<br>• Pydantic Settings & `.env.example`<br>• Async SQLite Engine (`aiosqlite` WAL mode)<br>• MemoryStore DAO & App Registry (Riot Games, Spotify)<br>• Quality Gate (18/18 Unit Tests Passing) | **COMPLETED** | 📄 **[Sprint 1 Dev Log](SPRINT_1_DEV_LOG.md)** |
| **Sprint 2** | **Local Audio Sensory Subsystem**<br>• Hardware Discovery & Capture Stream (WASAPI / Bluetooth Earphones)<br>• Lock-Free Audio Ring Buffer<br>• Neural Voice Activity Detection (Silero VAD v4 ONNX)<br>• Low-CPU Wake Word Detection (`openWakeWord`)<br>• Local Speech-to-Text (`faster-whisper` INT8 on CPU)<br>• Interactive Live Terminal CLI (`broski-listen`) | **COMPLETED** | 📄 **[Sprint 2 Dev Log](SPRINT_2_DEV_LOG.md)** |
| **Sprint 3** | **Neural Speech Synthesis & Barge-in**<br>• Piper TTS ONNX local voice synthesis (`en_US-lessac-medium`)<br>• Non-blocking audio playback stream (`sounddevice.OutputStream`)<br>• Thread-safe chunk queue & stereo earbud duplication<br>• Full-duplex barge-in detector (`BargeInDetector`)<br>• Interactive Full-Duplex Voice CLI (`broski-talk`)<br>• Quality Gate (76/76 Unit Tests Passing) | **COMPLETED** | 📄 **[Sprint 3 Dev Log](SPRINT_3_DEV_LOG.md)** |
| **Sprint 4** | **Cloud Brain, Intent Routing & Active Window Text Injection**<br>• Google Gemini API (`google-genai` SDK `gemini-3.1-flash-lite`)<br>• Multi-turn conversation sessions & speech-clean formatting<br>• Two-tier intent router (Local heuristics + Cloud LLM)<br>• Windows whitelist app launcher & Chrome profile manager<br>• Active-window text injection (`ActiveWindowInjector`)<br>• Contextual pronoun resolution & intent disambiguation<br>• Friendly bro persona across voice prompts & affirmations | **COMPLETED**<br>*(126/126 Tests Passing)* | 📄 **[Sprint 4 Dev Log](SPRINT_4_DEV_LOG.md)** |
| **Sprint 5** | **Security Gated System Tools & Deep Integrations**<br>• 3-Tier Security Confirmation & Tool Risk Gating<br>• Obsidian Local REST API vault client (read/append/search)<br>• Developer Git assistant (read-only repo status & diffs)<br>• Chrome browser automation & web summarization<br>• Two-tier tool dispatch & voice loop integration | **COMPLETED**<br>*(181/181 Tests Passing)* | 📄 **[Sprint 5 Dev Log](SPRINT_5_DEV_LOG.md)** |
| **Sprint 6** | **PySide6 Desktop UI & System Hardening**<br>• Floating translucent HUD pill<br>• System tray menu and controls<br>• Custom "Hey broski" openWakeWord model calibration | **UPCOMING** | 📄 *Pending* |

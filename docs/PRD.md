# Product Requirements Document (PRD)
## Project: broski — Personal Windows AI Voice Assistant

| Attribute | Details |
| :--- | :--- |
| **Document Version** | 1.0.0 |
| **Status** | Approved / In Development |
| **Author** | Lead Software Architect & Aaditya514 |
| **Target OS** | Windows 11 (64-bit) |
| **Architecture** | Hybrid Edge-Cloud (Local Sensory + Gemini Cloud Brain) |
| **Methodology** | Agile / Incremental (Feature Branching, User Stories, DoD) |

---

## 1. Product Vision & Value Proposition

### 1.1 Vision Statement
**broski** is an intelligent, low-latency, privacy-first personal AI voice assistant engineered specifically for Windows 11 power users, developers, and knowledge workers. It seamlessly unifies speech-driven operating system control, context-aware active window text injection, deep workflow integrations (Obsidian, Chrome, Git), and persistent user-controlled memory, all while strictly operating within the thermal and compute limits of a mobile quad-core CPU.

### 1.2 Core Value Drivers
1. **Frictionless Interaction**: Hands-free acoustic wake word (`"Hey broski"`) with sub-second interruption (barge-in) and local neural voice synthesis.
2. **True Multimodal Desktop Utility**: Doesn't just chat; types directly into whichever application has focus (VS Code, Slack, Word, Terminal), offering both exact voice dictation and AI-enhanced prose generation.
3. **Safe System Automation**: Strict permission tiering ensuring the assistant can never execute destructive or unrestricted shell commands without explicit user confirmation.
4. **Local-First Sensory Privacy**: Audio capture, wake word detection, voice activity detection, and speech-to-text occur completely on-device. Audio bytes are never uploaded to the cloud.

---

## 2. Hardware Budget & Operating Constraints

The software architecture is bound by the host physical constraints:
* **Processor**: Intel Core i7-1165G7 (4 Cores / 8 Threads, 15W–28W cTDP).
* **System Memory**: 16 GB DDR4/LPDDR4x.
* **Graphics**: Intel Iris Xe Graphics (Shared memory, no CUDA cores).
* **Storage**: Fast NVMe SSD.
* **Operating System**: Windows 11 Build 26300+.

### Performance & Resource Budgets
* **Idle CPU Utilization**: $< 3.5\%$ total system CPU usage.
* **Idle Memory Footprint**: $< 350\text{ MB}$ RAM.
* **Wake-to-Transcription Latency**: $< 600\text{ ms}$ for a 3-second utterance on INT8 CTranslate2.
* **TTS Time-to-First-Audio**: $< 180\text{ ms}$ locally via Piper ONNX.
* **Thermal Protection**: Core STT/TTS operations restricted to a maximum of 2 threads to prevent fan whirring and thermal throttling during extended sessions.

---

## 3. Agile Epics & User Stories

### Epic 1: Hands-Free Sensory Audio Subsystem
*Goal: Provide robust, zero-cloud, real-time voice capture, trigger detection, speech segmentation, and neural text-to-speech.*

#### US-1.1: Wake Word Activation
* **As a** user,
* **I want** to say `"Hey broski"` at any time,
* **So that** the assistant wakes up and begins listening without me having to touch the mouse or keyboard.
* **Acceptance Criteria**:
  * **Given** the assistant is in `IDLE` state with microphone active,
  * **When** the user clearly utters `"Hey broski"`,
  * **Then** the openWakeWord detector fires a wake event within 200ms, transitions state to `LISTENING`, and sounds a brief subtle chime or updates the HUD visual state.
  * **And** false activation rate under ambient room speech/media must be $< 1$ event per 8 hours.

#### US-1.2: Voice Activity Detection (VAD) & End-of-Turn Segmentation
* **As a** user,
* **I want** the assistant to automatically know when I have finished speaking,
* **So that** I don't have to press a button to submit my voice command.
* **Acceptance Criteria**:
  * **Given** the assistant is in `LISTENING` state,
  * **When** Silero VAD detects sustained silence exceeding $600\text{ ms}$ following speech,
  * **Then** the audio recording chunk is closed and dispatched to the STT engine.
  * **And** if no speech is detected within $5.0\text{ s}$ of wake word, the system returns to `IDLE`.

#### US-1.3: Fast Local Speech-to-Text (STT)
* **As a** user,
* **I want** my voice commands transcribed locally and rapidly,
* **So that** my voice data never leaves my computer and latency is minimized.
* **Acceptance Criteria**:
  * **Given** a captured audio segment from VAD,
  * **When** processed by `faster-whisper` (`base.en` INT8 on CPU),
  * **Then** high-accuracy text transcription is emitted with Real-Time Factor (RTF) $< 0.25$ (transcribing 3 seconds of audio in $< 750\text{ ms}$).

#### US-1.4: Interruptible Neural Speech Synthesis (TTS & Barge-in)
* **As a** user,
* **I want** broski to respond with a clear, natural-sounding voice that I can interrupt immediately if it talks too long,
* **So that** our dialogue feels natural and fluid.
* **Acceptance Criteria**:
  * **Given** a text response from the assistant,
  * **When** Piper TTS synthesizes the response,
  * **Then** audio playback starts within $200\text{ ms}$ via non-blocking audio streams.
  * **And** if the user starts speaking while TTS is active (barge-in), playback immediately cuts off and the assistant switches to `LISTENING`.

---

### Epic 2: Active Window Text Injection & AI-Assisted Writing
*Goal: Allow the user to speak into any focused Windows application, either for literal dictation or for LLM-enhanced drafting.*

#### US-2.1: Exact Voice Dictation into Active Window
* **As a** writer or coder,
* **I want** to dictate my thoughts directly into whichever text field is currently focused (e.g., VS Code, Word, Discord),
* **So that** I can write without typing on the keyboard.
* **Acceptance Criteria**:
  * **Given** any Windows application has keyboard focus,
  * **When** I trigger dictation mode (via voice command `"broski, dictate"` or global hotkey),
  * **Then** words are transcribed and injected directly into the target application using native Win32 `SendInput(KEYEVENTF_UNICODE)` without dropping special characters or focus.

#### US-2.2: AI-Enhanced Writing & Transformation
* **As a** user drafting emails or documentation,
* **I want** to dictate a rough stream-of-consciousness thought and ask broski to polish it,
* **So that** it becomes professional, concise, or formatted appropriately in place.
* **Acceptance Criteria**:
  * **Given** text is selected in the active window (or dictated with an instruction like *"broski, rewrite this as a polite follow-up email"*),
  * **When** the intent router classifies the request as AI Writing,
  * **Then** Gemini refines the text according to instructions, and replaces the selection or inserts the refined text directly into the active window.

---

### Epic 3: Security-Gated System & App Control
*Goal: Provide OS automation with zero risk of unauthorized or destructive execution.*

#### US-3.1: Whitelist-Based Application Launch & Window Management
* **As a** user,
* **I want** to say *"broski, open Spotify"* or *"broski, minimize this window"*,
* **So that** I can navigate my desktop hands-free.
* **Acceptance Criteria**:
  * **Given** an application control command,
  * **When** the target application exists in the approved application whitelist registry,
  * **Then** it is launched or focused via `pywin32` / `pywinauto`.
  * **And** non-whitelisted arbitrary executable paths are rejected with an explanatory voice message.

#### US-3.2: 3-Tier Security Gating & User Confirmation Dialog
* **As a** security-conscious user,
* **I want** any potentially harmful or mutating action to require my explicit approval,
* **So that** an LLM hallucination or prompt injection can never harm my computer or delete my files.
* **Acceptance Criteria**:
  * **Given** an action classified as `CRITICAL` (e.g., file deletion, git commit/push, process kill),
  * **When** the tool is invoked by the reasoning engine,
  * **Then** execution is paused, a modal confirmation dialog pops up on screen (with options [Approve] / [Deny] and voice confirmation support),
  * **And** execution proceeds ONLY if explicitly authorized by the user.

---

### Epic 4: Cloud Intelligence & Tool Calling (Gemini)
*Goal: Deliver state-of-the-art conversational reasoning, tool parameter generation, and contextual awareness via the official Google GenAI SDK.*

#### US-4.1: Streaming Conversational Reasoning & Function Calling
* **As a** user,
* **I want** the assistant to understand complex, multi-step natural language questions,
* **So that** it can solve problems and decide which tools to call dynamically.
* **Acceptance Criteria**:
  * **Given** a spoken query (e.g., *"Check my Obsidian daily note and tell me what tasks are left"*),
  * **When** dispatched to Gemini 2.5 Flash via `google-genai` SDK,
  * **Then** Gemini determines the appropriate tool (`ObsidianReadDailyNote`), inspects the output, and synthesizes a concise, spoken conversational response.

#### US-4.2: Fast Offline & Fallback Handling
* **As a** user,
* **I want** basic offline commands (time, window management, direct dictation) to work even without internet,
* **So that** the assistant remains functional when offline.
* **Acceptance Criteria**:
  * **Given** the machine has lost internet connectivity,
  * **When** the user speaks a local command,
  * **Then** the local Intent Router handles local system actions directly and informs the user gracefully if a cloud-dependent reasoning query is requested.

---

### Epic 5: Deep Workflow Integrations (Obsidian, Chrome, Git)
*Goal: Deeply link into the user's primary daily productivity applications.*

#### US-5.1: Obsidian Knowledge Vault Integration
* **As a** knowledge worker,
* **I want** broski to search my notes and append ideas directly to my Daily Note in Obsidian,
* **So that** my second brain is always up to date without manual copy-pasting.
* **Acceptance Criteria**:
  * **Given** the Obsidian Local REST API plugin is enabled with an HTTPS token,
  * **When** I say *"broski, add an idea to my daily note: research ONNX model quantization"*,
  * **Then** broski makes an authenticated REST call and appends the markdown bullet to today's daily note, confirming with a short spoken affirmation.

#### US-5.2: Chrome Browser Assistant
* **As a** user,
* **I want** broski to open URLs, search topics, or summarize the active webpage in Google Chrome,
* **So that** I can browse hands-free.
* **Acceptance Criteria**:
  * **Given** a web navigation or inquiry command,
  * **When** processed by the Playwright / Chrome DevTools agent,
  * **Then** the browser performs the search or extracts article text for summarization.

#### US-5.3: Developer Git Assistant
* **As a** developer,
* **I want** broski to tell me the status of my active git repository or inspect recent diffs,
* **So that** I can stay oriented in my coding tasks.
* **Acceptance Criteria**:
  * **Given** I am working inside a git repository,
  * **When** I say *"broski, what files have I changed?"*,
  * **Then** broski executes a read-only `git status -s` and summarizes the changed files conversationally.

---

### Epic 6: User-Controlled Local Memory & Audit Trail
*Goal: Maintain persistent user preferences and complete auditability without cloud telemetry.*

#### US-6.1: Local SQLite Fact & Preference Store
* **As a** user,
* **I want** broski to remember personal preferences (e.g., preferred browser, project directories, writing style),
* **So that** I don't have to repeat myself across sessions.
* **Acceptance Criteria**:
  * **Given** the user states a fact (*"Remember that my main project is in C:\Workspace\MyApp"*),
  * **When** parsed by the memory engine,
  * **Then** the key-value fact is persisted into local SQLite (`data/broski.db`) and recalled in subsequent prompts.

#### US-6.2: Full User Transparency & Forget Capability
* **As a** privacy-conscious user,
* **I want** to view everything broski remembers about me and be able to delete facts,
* **So that** I have total sovereignty over my personal data.
* **Acceptance Criteria**:
  * **Given** a command *"broski, forget my last instruction"* or viewing the Memory GUI pane,
  * **When** requested,
  * **Then** the corresponding records are purged from the SQLite database immediately.

---

### Epic 7: Modern Desktop UI (PySide6)
*Goal: Provide visual feedback without being obtrusive or distracting.*

#### US-7.1: Minimalist Floating HUD
* **As a** user,
* **I want** a small, elegant translucent status pill on screen,
* **So that** I can glance and immediately know whether broski is Idle, Listening, Thinking, or Speaking.
* **Acceptance Criteria**:
  * **Given** state transitions in the assistant core,
  * **When** the state changes,
  * **Then** the PySide6 floating widget animates smoothly, showing an audio waveform or discrete status badge without stealing focus from the active window.

#### US-7.2: System Tray & Control Menu
* **As a** user,
* **I want** a system tray icon with quick controls (Mute, Settings, Logs, Exit),
* **So that** broski sits quietly in the background when not in use.

---

## 4. Definition of Done (DoD)

A user story or feature is considered **Done** only when:
1. **Branch Hygiene**: Developed on a dedicated Git branch (`feat/...` or `fix/...`) branched from `main`.
2. **Code Standards**: Fully typed with Python 3.12 type annotations, passing all linter and formatting checks.
3. **Automated Tests**: Unit tests written and passing in `pytest` with $> 85\%$ test coverage for business logic.
4. **Documentation**: Documented in `docs/` and logged in `docs/DEV_LOG.md` explaining *what* was built, *how* it works, and *why* specific choices were made.
5. **No Regressions**: Merged cleanly into `main` after verification.

---

## 5. Agile Release Plan & Sprints

```mermaid
gantt
    title broski Agile Sprint Roadmap
    dateFormat  YYYY-MM-DD
    section Foundation
    Sprint 0 : Setup, PRD & Architecture        :done, 2026-11-15, 1d
    Sprint 1 : Environment, Config & SQLite     :active, 2026-11-16, 2d
    section Audio Core
    Sprint 2 : Local Audio (WakeWord, VAD, STT) : 2026-11-18, 3d
    Sprint 3 : Piper TTS & Barge-in Playback    : 2026-11-21, 2d
    section Brain & Injection
    Sprint 4 : Gemini Brain & Text Injector     : 2026-11-23, 3d
    section Integrations & UI
    Sprint 5 : Security Gated Tools & Integrations : 2026-11-26, 4d
    Sprint 6 : PySide6 HUD & Custom Wake Word   : 2026-11-30, 3d
```

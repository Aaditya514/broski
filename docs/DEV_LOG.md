# broski — Engineering Journal & Daily Dev Log

This log documents every architectural decision, implementation detail, command executed, and educational insight as **broski** is built step-by-step using Agile methodologies.

---

## 📅 Day 1: 2026-11-15 — Sprint 0: Foundation, Architecture & Agile PRD

### 🎯 Daily Objective
Establish the Agile development foundation, inspect host hardware and runtime compatibility, define the Product Requirements Document (PRD), establish the Git feature-branching workflow, and document the system architecture before writing code.

---

### 🔍 1. Hardware & System Inspection (What We Found)
Before architecting anything, we inspected the machine's actual hardware and software environment:
* **OS**: Windows 11 Build 26300 (Detected via `[System.Environment]::OSVersion.Version`).
* **Processor**: Intel Core i7-1165G7 (4 physical cores, 8 logical threads, Tiger Lake, 15W–28W cTDP).
* **RAM**: 16 GB DDR4/LPDDR4x.
* **GPU**: Intel Iris Xe Graphics (96 Execution Units, shared system memory, no dedicated NVIDIA CUDA cores).
* **Python Environments Detected via `py -0p`**:
  * Default: Python 3.13.1 (`C:\Python313\python.exe`)
  * Installed: Python 3.12 (`C:\Users\KIIT\AppData\Local\Programs\Python\Python312\python.exe`)

---

### 💡 2. Educational Insight: Why Python 3.12 instead of 3.13?
* **The Question**: Why not just use the latest Python 3.13?
* **The Engineering Answer**:
  * Machine learning libraries that execute locally on Windows (`faster-whisper`, `ctranslate2`, `onnxruntime`, `openwakeword`) rely heavily on pre-compiled native C/C++ binaries (called **wheels** or `.whl` files).
  * For Python 3.13, many of these binary wheels have not yet been published by upstream maintainers for Windows. Attempting to install them on Python 3.13 triggers source compilation, which fails unless Microsoft Visual C++ Build Tools 14.x with exact SDK headers are installed and configured.
  * In contrast, **Python 3.12** has mature, fully pre-built binary wheels with AVX2 acceleration out-of-the-box on Windows.
  * **Decision**: We will standardize our virtual environment on **Python 3.12** (`py -3.12 -m venv .venv`).

---

### 💡 3. Educational Insight: Thermal Budgeting on 4-Core Mobile CPUs
* **The Challenge**: The i7-1165G7 is an ultra-thin laptop chip. If all 8 threads are maxed out by Whisper or neural TTS, the CPU package temperature rapidly climbs past 90°C, causing the laptop fans to spin up loudly and triggering **thermal throttling** (the CPU drops from 4.7 GHz to 1.8 GHz).
* **The Architectural Solution**:
  1. We constrain `faster-whisper` to `cpu_threads=2` with `int8` quantization. This processes audio in ~200ms per 3-second utterance without saturating the processor.
  2. We keep the wake word (`openWakeWord`) and VAD (`Silero VAD`) running as single-threaded ONNX models that consume $< 2\%$ CPU while idling.
  3. We delegate heavy natural language reasoning, function calling, and structured conversation to the **Gemini 2.5 Flash API** over HTTPS, consuming almost 0% local CPU.

---

### 🛠️ 4. What We Built & Configured Today

1. **Git Repository Setup**:
   * Initialized local repository: `git init -b main`.
   * Created comprehensive `.gitignore` tailored for Python, PyTorch, CTranslate2, SQLite databases, audio buffers, and `.env` secret files.
   * Committed root commit to `main`: `chore: initialize repository and add gitignore`.
2. **Agile Feature Branching**:
   * Created and switched to feature branch: `docs/prd-and-architecture`.
   * Established rule: `main` is protected; all work happens on feature branches and is merged back with clean commits.
3. **Agile Product Requirements Document (`docs/PRD.md`)**:
   * Documented Vision, Hardware Constraints, and Performance Budgets.
   * Formulated 7 Agile Epics and detailed User Stories with **Given-When-Then** Acceptance Criteria.
   * Defined strict **Definition of Done (DoD)** and Sprint Schedule.
4. **Technical Architecture Specification (`docs/ARCHITECTURE.md`)**:
   * High-level micro-kernel architecture with asynchronous event bus.
   * Deterministic State Machine (Idle -> Listening -> Transcribing -> Routing -> Thinking -> Speaking / Dictating).
   * 3-Tier Security Gating for system actions (`SAFE`, `MODERATE`, `CRITICAL`).

---

### 💻 5. Commands Executed & Outputs
```powershell
# 1. Environment and version discovery
python --version; [System.Environment]::OSVersion.Version
# -> Python 3.13.1, Windows 10.0.26300.0

py -0; py -0p
# -> Python 3.13 and Python 3.12 located

# 2. Git initialization and initial commit
git init -b main
git add .gitignore
git commit -m "chore: initialize repository and add gitignore"
# -> [main c05464b]

# 3. Created documentation feature branch
git checkout -b docs/prd-and-architecture

# 4. Connected remote origin and pushed branches
git remote add origin https://github.com/Aaditya514/broski.git
git push -u origin main
git push origin docs/prd-and-architecture
# -> Successfully linked and synced with https://github.com/Aaditya514/broski
```

---

### 🚀 6. Next Steps (Sprint 1 Roadmap)
1. Commit the PRD, Architecture, and Dev Log to `docs/prd-and-architecture`.
2. Merge `docs/prd-and-architecture` into `main`.
3. Create new feature branch `feat/sprint-1-foundation`:
   - Initialize Python 3.12 virtual environment (`.venv`).
   - Define `pyproject.toml` with pinned, compatible dependencies.
   - Set up `.env.example` and `config.py` using `pydantic-settings`.
   - Implement asynchronous SQLite database schema (`aiosqlite`) for memory and audit logging.
   - Write first automated unit tests (`pytest`).

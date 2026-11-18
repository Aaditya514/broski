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

### 🚀 6. Next Steps (Day 2 / Sprint 1 Roadmap)
1. Create new feature branch: `feat/sprint-1-foundation`.
2. Initialize Python 3.12 virtual environment (`.venv`).
3. Define `pyproject.toml` with pinned, compatible dependencies.
4. Set up `.env.example` and `config.py` using `pydantic-settings`.
5. Implement asynchronous SQLite database schema (`aiosqlite`) for memory and audit logging.
6. Write first automated unit tests (`pytest`).
7. Update Dev Log with educational insights, commit, push, and merge into `main`.

---

### 🏁 Session Conclusion & Standby Status
* **Date & Time**: 2026-11-15 23:02 IST
* **Git Status**: Working tree completely clean; branch `main` is up-to-date with `origin/main`.
* **GitHub Link**: [https://github.com/Aaditya514/broski](https://github.com/Aaditya514/broski)
* **Status**: Sprint 0 complete. Ready to kick off Sprint 1 on Day 2!

---

## 📅 Day 2: 2026-11-17 — Sprint 1 (Day 1 of 5): Environment & Packaging

### 🎯 Daily Objective
Initiate Sprint 1 (Foundation & Core Infrastructure) on feature branch `feat/sprint-1-foundation`. Bootstrap the isolated Python 3.12 virtual environment, create modern standard `pyproject.toml` packaging, and install foundational core libraries.

---

### 🛠️ 1. What We Built Today
1. **Feature Branching**:
   * Created and switched to `feat/sprint-1-foundation` from `main`.
2. **Virtual Environment Setup (`.venv`)**:
   * Initialized dedicated Python 3.12 virtual environment using `py -3.12 -m venv .venv`.
   * Verified runtime: Python 3.12.3 (64-bit).
3. **Modern Packaging Architecture (`pyproject.toml`)**:
   * Adopted PEP 517, PEP 518, and PEP 621 packaging standards.
   * Configured core dependencies (`pydantic`, `pydantic-settings`, `python-dotenv`, `aiosqlite`).
   * Configured modular optional extras:
     * `broski[audio]`: `sounddevice`, `numpy`, `onnxruntime`, `openwakeword`, `faster-whisper`, `piper-tts`.
     * `broski[brain]`: `google-genai`.
     * `broski[system]`: `pywin32`, `pywinauto`.
     * `broski[integrations]`: `httpx`, `playwright`.
     * `broski[ui]`: `PySide6`.
     * `broski[dev]`: `pytest`, `pytest-asyncio`, `ruff`.
   * Defined CLI entry point `broski = "broski.main:main"` and tool configurations for `pytest` and `ruff`.
4. **Source Skeleton (`src/broski/__init__.py`)**:
   * Created initial root package structure and version definition (`0.1.0`).
5. **Dependency Installation**:
   * Upgraded `pip` and performed editable install: `pip install -e ".[dev]"`.

---

### 💡 2. Educational Insights: Under the Hood

#### A. Virtual Environments on Windows: How They Actually Work
* **The Magic**: When you run `py -3.12 -m venv .venv`, Python doesn't make a copy of the entire Windows operating system or all standard libraries.
* Instead, it creates a lightweight directory structure with its own isolated `Scripts\python.exe` and `Lib\site-packages\`.
* When you run `.\.venv\Scripts\python.exe`, it reads `pyvenv.cfg`, points to the Python 3.12 base installation, and restricts package lookups exclusively to `.\.venv\Lib\site-packages\`.
* **Why this matters for broski**: Your computer has Python 3.13 globally. Global installs would clash with audio and ML packages. By locking our `.venv` to Python 3.12, every future command is 100% deterministic, protected, and reproducible.

#### B. `pyproject.toml` vs. Legacy `requirements.txt` / `setup.py`
* **The Problem with legacy `requirements.txt`**: A flat text file doesn't distinguish between *direct* project dependencies and *transitive* dependencies. It also cannot configure test runners or linters.
* **The Power of `pyproject.toml`**:
  * Unified standard (PEP 621) supported by all modern Python packaging tools.
  * Modular dependencies: allows users or production dockers to install only what they need (e.g., `pip install -e ".[audio]"` vs `pip install -e ".[dev]"`).
  * Centralizes tool configuration: both `pytest` and `ruff` read their settings directly from `pyproject.toml`.

#### C. What is an Editable Install (`pip install -e .`)?
* Normally, `pip install` copies your Python files into `site-packages`. If you modify a file in `src/`, your changes don't take effect until you reinstall.
* **Editable mode (`-e`)**: Tells Python to insert a special `.pth` link in `site-packages` pointing straight back to our local `src/` folder.
* **Result**: Any change we make to `src/broski/` is immediately active in our virtual environment without running any rebuild commands!

---

### 💻 3. Commands Executed & Outputs
```powershell
# 1. Created and switched to feature branch
git checkout -b feat/sprint-1-foundation

# 2. Created isolated Python 3.12 venv
py -3.12 -m venv .venv

# 3. Verified Python version inside venv
.\.venv\Scripts\python.exe --version
# -> Python 3.12.3

# 4. Upgraded pip and installed core + dev dependencies in editable mode
.\.venv\Scripts\python -m pip install --upgrade pip
.\.venv\Scripts\pip install -e ".[dev]"
```

---

### 🚀 4. Plan for Day 2 of Sprint 1
* Build `src/broski/config.py` using `pydantic-settings`.
* Create `.env.example` template with Gemini API key, Obsidian port, log levels, and audio configuration.
* Test type validation and environment variable loading.

---

## 📅 Day 3: 2026-11-18 — Sprint 1 (Day 2 of 5): Type-Safe Configuration & Secret Management

### 🎯 Daily Objective
Implement a robust, production-grade configuration architecture for broski using `pydantic-settings`. Prevent credential leakage using `SecretStr`, provide domain-specific sub-configurations (`AudioConfig`, `BrainConfig`, `ObsidianConfig`, `PathsConfig`, `SecurityConfig`), enforce strict validation rules, and verify with automated unit tests.

---

### 🛠️ 1. What We Built Today
1. **Environment Configuration Template (`.env.example`)**:
   * Fully commented configuration template covering all subsystems (Cloud AI, Audio, Wake Word, VAD, Whisper, Piper, Obsidian, Paths, and Security Gating).
2. **Type-Safe Settings Engine (`src/broski/config.py`)**:
   * Root `Settings(BaseSettings)` class reading from environment variables and `.env`.
   * Grouped domain models:
     * `AudioConfig`: validates 16kHz sample rate, channels, VAD threshold, and limits Whisper CPU worker threads to 2.
     * `BrainConfig`: protects `gemini_api_key` with `SecretStr`, configures model identifier and temperature.
     * `ObsidianConfig`: validates TCP port (1–65535) and provides dynamic `base_url`.
     * `PathsConfig`: resolves `data/broski.db` and auto-creates required storage directories (`ensure_directories()`).
     * `SecurityConfig`: sets confirmation requirement for critical actions and log levels.
   * Cached singleton accessor `get_settings()` decorated with `@lru_cache`.
3. **Automated Unit Test Suite (`tests/unit/test_config.py` & `tests/conftest.py`)**:
   * `test_default_settings`: Verifies out-of-the-box defaults match architectural specifications.
   * `test_secret_str_masking`: Asserts API keys are never exposed in logs or `repr()`.
   * `test_environment_variable_overrides`: Asserts environment variables override defaults.
   * `test_invalid_sample_rate_validation`: Asserts invalid audio sample rates fail validation immediately.
   * `test_invalid_port_validation`: Asserts port range violations fail validation.
   * `test_paths_ensure_directories`: Asserts directory creation works reliably.
   * `test_get_settings_cached_singleton`: Asserts singleton instance caching.
4. **Code Quality & Linting**:
   * Code formatted and validated using `ruff` with modern Python 3.12 syntax (PEP 604 `X | None`).
   * 100% clean check: 7 unit tests passed in 0.22 seconds.

---

### 💡 2. Educational Insights: Under the Hood

#### A. Why `pydantic-settings` instead of `os.getenv()`?
* **The Primitive Way (`os.getenv`)**: Returns unvalidated raw strings. If someone puts `AUDIO_SAMPLE_RATE=sixteen_thousand` or `OBSIDIAN_PORT=9999999`, the error will occur hours later inside deep audio/network code with confusing stack traces.
* **The Pydantic Way**: 
  1. Automatic type casting (turns `"16000"` from `.env` into integer `16000`).
  2. Range checks (`ge=1, le=65535`).
  3. "Fail Fast": If configuration is invalid, broski refuses to boot and immediately tells the user exactly which configuration parameter is invalid and why.

#### B. The Zero-Leak Guarantee: `SecretStr`
* If you log `settings.gemini_api_key` or print it during debugging, Python automatically renders:
  ```python
  SecretStr('**********')
  ```
* Even if an unhandled exception prints local variables into an error dump, your API key will never be visible in plain text.
* To explicitly retrieve the secret for network calls: `key = settings.brain.api_key.get_secret_value()`.

#### C. Cached Singleton Pattern (`@lru_cache`)
* Disk I/O (parsing `.env`) is slow compared to memory lookups.
* By wrapping `get_settings()` with `@lru_cache(maxsize=1)`, the configuration is parsed exactly once on first call and held in RAM. Any subsequent import across the entire application accesses the in-memory object instantaneously.

---

### 💻 3. Commands Executed & Outputs
```powershell
# 1. Ran automated unit tests
.\.venv\Scripts\pytest -v tests/unit/test_config.py
# -> 7 passed in 0.22s

# 2. Formatted and linted code with ruff
.\.venv\Scripts\ruff check --fix .
.\.venv\Scripts\ruff format .
# -> All checks passed!
```

---

### 🚀 4. Plan for Day 3 of Sprint 1
* **Topic**: **Asynchronous SQLite Engine & Database Schema**
* Build `src/broski/memory/database.py` using `aiosqlite`.
* Design relational tables: `memories` (key-value facts), `user_preferences`, and `security_audit_logs`.
* Write unit tests verifying async database connection lifecycle and schema creation.

# broski — Sprint 5 Engineering Journal: Security Gated System Tools & Deep Integrations

**Lead Software Architect & Engineering Team**  
**Sprint Duration**: 4 Days  
**Milestone Focus**: 3-Tier Security Confirmation Gating, Obsidian Local REST API Knowledge Vault Client, Developer Git Assistant, and Browser Automation.

---

## 🧭 Executive Summary & Sprint Goal

Sprint 5 transitions **broski** from an ambient desktop listener and conversational assistant into a powerful, secure desktop automation and developer workflow platform. 
In Sprint 4, broski gained cloud conversational reasoning (Gemini 3.1 Flash-Lite), two-tier intent routing, Windows whitelist application launching, and active window text injection.
In **Sprint 5**, we integrate deep, safe desktop tooling:
1. **3-Tier Security Confirmation Gating**: Strict enforcement of the core architecture principle: *"No unrestricted LLM-generated terminal execution"*. Tools are categorized into `SAFE` (read-only), `MODERATE` (non-destructive mutation), and `CRITICAL` (system mutation / deletion / execution) with mandatory user confirmation gates for critical operations.
2. **Obsidian Local REST API Vault Integration**: Native async client for Obsidian, allowing users to search notes, read daily notes, and append ideas or tasks directly to today's daily note hands-free via voice.
3. **Developer Git Assistant**: Read-only repository status (`git status`, `git diff`, `git log`) and branch inspection, with critical gating on write/push commands.
4. **Chrome Browser Automation**: URL navigation, content extraction, and summarization.
5. **Gemini Function Calling Dispatcher**: Seamless routing from voice speech to tool execution and back to conversational speech synthesis.

---

## 🗺️ Sprint 5 Daily Roadmap

| Day | Focus Areas | Key Deliverables | Status |
| :---: | :--- | :--- | :---: |
| **Day 1** | **3-Tier Security Tooling & Obsidian Client** | `RiskLevel`, `BaseTool`, `ToolRegistry`, `SecurityConfirmationManager`, `ObsidianClient`, Obsidian tools | **COMPLETED** |
| **Day 2** | **Developer Git Assistant** | `GitInspector`, safe repository discovery, read-only status/diff tools, security gating | **COMPLETED** |
| **Day 3** | **Chrome Browser Automation** | Chrome navigation, active webpage text extraction, search and summarization | **COMPLETED** |
| **Day 4** | **Gemini Function Calling & Voice Loop Integration** | Wiring `ToolRegistry` to Gemini API function calling, voice CLI testing, full quality gate & merge | **UPCOMING** |

---

## 📅 Day 1 of 4: 3-Tier Security Tooling & Obsidian Local REST API Vault Integration

### 🎯 Objective & Milestones
* **Security & Tool Infrastructure**:
  * Implement `RiskLevel` enum (`SAFE`, `MODERATE`, `CRITICAL`).
  * Implement `ToolResult` and `BaseTool` abstract base class with JSON Schema export.
  * Implement `ToolRegistry` for registering and dispatching tools safely.
  * Implement `SecurityConfirmationManager` enforcing approval gates for `CRITICAL` tools.
* **Obsidian Local REST API Integration**:
  * Build asynchronous `ObsidianClient` using `httpx`.
  * Support Bearer token authentication and local HTTPS self-signed certificates.
  * Implement `ObsidianReadDailyNoteTool`, `ObsidianAppendDailyNoteTool`, `ObsidianReadNoteTool`, `ObsidianSearchNotesTool`, and `ObsidianCreateNoteTool`.
  * Deliver bro-persona friendly error handling when Obsidian is not running.
* **Testing & Quality Assurance**:
  * Unit tests for security risk levels, tool registry, and confirmation gating (`tests/unit/test_tools_security.py`).
  * Mocked HTTP tests for Obsidian REST API client covering health check, daily note read/append, search, and connection failure fallbacks (`tests/unit/test_obsidian_tools.py`).
  * **150 / 150 unit tests passing** (100% green) across all subsystems with 0 linter warnings.

---

### 🛠️ 1. Technical Deep-Dive: Implementation Details

1. **3-Tier Risk Gating Architecture (`src/broski/tools/base.py`, `src/broski/tools/security.py`)**:
   * Adheres strictly to the architectural constraint: *"No unrestricted LLM-generated terminal execution"*.
   * `RiskLevel.SAFE`: Read-only queries (reading notes, checking git status, searching vault, active window info). Executed immediately without interrupting the user.
   * `RiskLevel.MODERATE`: Safe, non-destructive mutations (appending to today's daily note, launching whitelisted apps, copying text). Executed with conversational spoken affirmation.
   * `RiskLevel.CRITICAL`: Destructive or system-altering actions (file deletion, git commits/pushes, killing processes, shell execution). **Strictly halted** pending explicit user approval.
   * `SecurityConfirmationManager`:
     * Generates a unique 8-character hex confirmation ID (`req_id`).
     * Holds pending request metadata with a configurable timeout (default 30 seconds).
     * Exposes programmatic and voice approval methods (`confirm(request_id, approved=True)`).
     * Expired requests automatically transition to `EXPIRED` status and are cleaned up.

2. **Tool Registry & Gemini Schema Export (`src/broski/tools/registry.py`)**:
   * `ToolRegistry` holds all registered tools and handles execution.
   * When `execute()` is called on a `CRITICAL` tool without explicit pre-confirmation:
     * Generates a `ConfirmationRequest`.
     * Returns `ToolResult(success=False, output={"confirmation_id": req.request_id, "status": "pending_confirmation"}, message="Yo bro, '{tool.name}' is a critical action. Say 'confirm' or approve request [{req.request_id}] to run it.")`.
   * `get_gemini_declarations()` exports OpenAPI schemas compatible with the official Google GenAI function calling specification.

3. **Obsidian Local REST API Vault Client (`src/broski/tools/obsidian.py`)**:
   * Built on `httpx.AsyncClient` communicating with the Obsidian Local REST API HTTPS server (default `https://127.0.0.1:27124`).
   * Handles local self-signed SSL certificates (`verify=False`) with secure token authentication (`Authorization: Bearer <token>`).
   * Implemented full CRUD and search operations:
     * `read_daily_note()`: `GET /periodic/daily/` (returns today's markdown note or empty string if 404).
     * `append_daily_note(content)`: `POST /periodic/daily/` with markdown formatting (auto-prefixes `- ` bullet).
     * `read_note(path)`: `GET /vault/{path}`.
     * `append_note(path, content)`: `POST /vault/{path}`.
     * `create_or_update_note(path, content)`: `PUT /vault/{path}`.
     * `search_notes(query)`: Simple search API with file listing fallback.
   * Implemented 5 typed tools:
     * `ObsidianReadDailyNoteTool` (`SAFE`)
     * `ObsidianAppendDailyNoteTool` (`MODERATE`)
     * `ObsidianReadNoteTool` (`SAFE`)
     * `ObsidianSearchNotesTool` (`SAFE`)
     * `ObsidianCreateNoteTool` (`MODERATE`)
   * All tools provide warm, concise bro-persona voice summaries tailored for Piper TTS (<180 chars, conversational).

---

### 💡 2. Educational Insights: Under the Hood

#### A. Why 3-Tier Security Gating is Essential for Agentic Systems
* When LLMs are granted access to tool calling, prompt injection and hallucinations can inadvertently trigger destructive operations (e.g. deleting notes, dropping databases, running unchecked shell scripts).
* Rather than a binary "allow all" or "deny all", a 3-tier hierarchy separates read-only intelligence from irreversible mutation:
  * Safe tools execute instantly, maintaining sub-second conversational flow.
  * Moderate tools execute with clear verbal feedback so the user always knows what state changed.
  * Critical tools freeze execution until an out-of-band user approval is received.

#### B. Communicating with Local Self-Signed HTTPS Services
* Modern desktop applications running local HTTP servers (like Obsidian's Local REST API plugin) typically generate self-signed SSL certificates to encrypt traffic across `127.0.0.1`.
* Standard Python HTTP clients (`requests`, `urllib`, `httpx`) reject self-signed certificates by default with `SSLCertVerificationError`.
* In `ObsidianClient`, we configure `httpx.AsyncClient(verify=False)` explicitly bounded to `127.0.0.1` and `localhost`, ensuring seamless communication with the local vault while maintaining strict network isolation.

---

### 💻 3. Commands Executed & Outputs
```powershell
# 1. Install httpx in virtual environment
.\.venv\Scripts\pip.exe install httpx
# -> Successfully installed httpcore-1.0.9 httpx-0.29.0

# 2. Quality gate linting
.\.venv\Scripts\ruff.exe check .
# -> All checks passed!

# 3. Test suite verification
.\.venv\Scripts\pytest.exe -v
# -> 150 passed in 5.98s (100% green)
```

---

## 📅 Day 2 of 4: Developer Git Assistant & Security-Gated Mutating Operations

### 🎯 Objective & Milestones
* **Git Subprocess Sandboxing (`src/broski/tools/git.py`)**:
  * Build `GitInspector` with zero `shell=True` subprocess calls (`asyncio.create_subprocess_exec("git", ...)`).
  * Safe recursive repository discovery climbing parent directories to locate `.git`.
  * Structured repository status parsing (`git status --porcelain=v1 -b`): branch, ahead/behind counters, staged, modified, and untracked file collections.
  * Formatted diff statistics (`git diff --stat`, `--cached`).
  * Commit history parsing (`git log --format=%h|%s|%an|%cr`).
  * Current branch identification (`git branch --show-current`).
* **Typed Git Tools & 3-Tier Risk Gating**:
  * `GitStatusTool` (`RiskLevel.SAFE`): Reports active branch and changed/staged files.
  * `GitDiffTool` (`RiskLevel.SAFE`): Reports diff stats.
  * `GitLogTool` (`RiskLevel.SAFE`): Summarizes recent commit subjects, authors, and timestamps.
  * `GitBranchTool` (`RiskLevel.SAFE`): Reports active branch.
  * `GitCommitTool` (`RiskLevel.CRITICAL`): Commits staged changes; strictly blocked unless confirmed by user.
  * `GitPushTool` (`RiskLevel.CRITICAL`): Pushes commits to remote; strictly blocked unless confirmed by user.
* **Testing & Quality Assurance**:
  * Added 15 comprehensive unit tests in `tests/unit/test_git_tools.py` covering clean/dirty repos, non-repo error handling, diff formatting, commit logs, and `ToolRegistry` confirmation gating.
  * **165 / 165 unit tests passing** (100% green) across all subsystems with 0 linter warnings.

---

### 🛠️ 1. Technical Deep-Dive: Implementation Details

1. **Subprocess Isolation & Zero-Shell Security**:
   * Direct execution of git commands via `asyncio.create_subprocess_exec("git", *args, cwd=str(target))` prevents command injection vulnerabilities. Arguments are passed as individual array tokens rather than parsed by `cmd.exe` or `powershell.exe`.
   * Standard error and output streams are captured asynchronously and decoded safely with fallback error replacement.

2. **Repository Root Discovery Algorithm**:
   * Developers frequently invoke voice commands while focused on a deeply nested source file (e.g. `src/broski/tools/git.py`).
   * `discover_repo_path()` checks the directory, then recursively traverses upward (`curr.parent`) until finding `.git`, guaranteeing correct repository root resolution without manual directory specification.

3. **Critical Mutation Gating in Action**:
   * When an unconfirmed `GitCommitTool` or `GitPushTool` execution is dispatched through `ToolRegistry.execute()`:
     * Execution halts immediately before invoking `git`.
     * `SecurityConfirmationManager` registers a pending confirmation with reason and arguments.
     * Broski responds conversationally: *"Yo bro, 'git_commit' is a critical action. Say 'confirm' or approve request [abc1234] to run it."*
     * Once confirmed (`manager.confirm("abc1234", approved=True)`), subsequent execution succeeds.

---

### 💻 2. Commands Executed & Outputs
```powershell
# 1. Quality gate linting
.\.venv\Scripts\ruff.exe check --fix .
# -> Found 1 error (1 fixed, 0 remaining). All checks passed!

# 2. Test suite verification
.\.venv\Scripts\pytest.exe -v
# -> 165 passed in 5.90s (100% green)
```

---

## 📅 Day 3 of 4: Chrome Browser Automation & Webpage Content Extraction

### 🎯 Objective & Milestones
* **Chrome Browser Automation (`src/broski/tools/browser.py`)**:
  * Build `BrowserNavigator` with dynamic Chrome executable resolution, URL scheme normalization, and multi-profile direct launch (`ChromeProfileManager`).
  * Implement clean webpage text extraction (`WebpageContentExtractor`) based on Python standard library `html.parser.HTMLParser`.
  * Strip web noise (scripts, stylesheets, headers, footers, navigation bars, SVG elements, iframes).
  * Asynchronous webpage reading via `httpx.AsyncClient` with user-agent headers and character limit budgeting.
* **Typed Browser Tools**:
  * `BrowserOpenUrlTool` (`RiskLevel.SAFE`): Opens any web URL in Chrome, with optional profile selection.
  * `BrowserSearchTool` (`RiskLevel.SAFE`): Performs web searches on Google or DuckDuckGo.
  * `BrowserReadWebpageTool` (`RiskLevel.SAFE`): Extracts article text and page title for speech summarization.
* **Testing & Quality Assurance**:
  * Added 11 unit tests in `tests/unit/test_browser_tools.py` covering HTML extraction, URL normalization, profile launching, search engine URLs, async webpage retrieval, and error handling.
  * **176 / 176 unit tests passing** (100% green) across all subsystems with 0 linter warnings.

---

### 🛠️ 1. Technical Deep-Dive: Implementation Details

1. **Lightweight, Zero-Dependency HTML Content Extraction**:
   * Rather than pulling in heavy external dependencies like Beautiful Soup or Playwright Chromium binaries (~200MB), `WebpageContentExtractor` extends standard Python `html.parser.HTMLParser`.
   * Strips clutter elements (`script`, `style`, `noscript`, `header`, `footer`, `nav`, `svg`, `aside`, `iframe`) and extracts `<title>` and paragraph/article text.
   * Collapses excessive whitespace to generate clean, readable text ready for Gemini summarization or Piper TTS reading.

2. **Multi-Profile Chrome Direct Launch Integration**:
   * Combines `ChromeProfileManager` from Sprint 4 with `BrowserNavigator`.
   * When user requests opening a site on a specific account (e.g. *"Open GitHub on my Personal Chrome"*), the tool passes `--profile-directory=...` directly, completely avoiding Chrome's modal profile picker.

3. **Subprocess Resilience**:
   * Uses `subprocess.Popen([chrome_path, url], stdout=DEVNULL, stderr=DEVNULL)` to avoid freezing broski's async event loop.
   * Falls back gracefully to Windows default browser (`webbrowser.open(url)`) if Chrome is not installed.

---

### 💻 2. Commands Executed & Outputs
```powershell
# 1. Quality gate linting
.\.venv\Scripts\ruff.exe check .
# -> All checks passed!

# 2. Test suite verification
.\.venv\Scripts\pytest.exe -v
# -> 176 passed in 5.58s (100% green)
```

---

### 🚀 3. Plan for Day 4 of Sprint 5 (Gemini Function Calling & Voice Integration)
* Wire `ToolRegistry` into `GeminiBrainClient` tool calling definitions.
* Enhance `broski-talk` full-duplex voice loop to dynamically call tools, synthesize concise answers with Piper TTS, and handle confirmation requests.
* Run end-to-end voice loop quality gate and merge `feat/sprint-5-tools` into `main`.




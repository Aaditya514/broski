"""Active Window Text Injection engine for broski.

Injects speech-to-text transcripts, dictated text, and programmatic snippets directly
into whichever desktop application currently holds foreground focus on Windows 11
(e.g., Obsidian note, VS Code editor, Google Chrome form, Terminal, Notepad).

Provides two complementary injection mechanisms:
1. Native Unicode Keystroke Simulation (via Windows SendInput):
   - Simulates physical key events using KEYEVENTF_UNICODE.
   - Does not touch the system clipboard.
   - Ideal for short words, single sentences, and command-line inputs.
2. Fast Clipboard Paste (Ctrl+V via Windows SendInput):
   - Backs up existing clipboard contents, places text on the clipboard,
     dispatches Ctrl+V, and asynchronously restores the user's prior clipboard.
   - Near-instantaneous execution for long multiline dictation, markdown notes,
     code blocks, and multi-sentence speech.
3. Auto Mode:
   - Selects keystroke simulation for short phrases (<30 chars) and clipboard paste
     for longer paragraphs or text containing newlines and emoji surrogates.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("broski.system.injector")

# ---------------------------------------------------------------------------
# Windows API Structures and Constants (ctypes)
# ---------------------------------------------------------------------------
IS_WINDOWS = sys.platform == "win32"

# Windows clipboard formats
CF_UNICODETEXT = 13
GHND = 0x0042  # GMEM_MOVEABLE | GMEM_ZEROINIT

# SendInput constants
INPUT_KEYBOARD = 1
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

# Virtual key codes
VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
VK_SPACE = 0x20
VK_V = 0x56

# Process query permissions
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


# Configure 64-bit safe ctypes signatures on Windows
if IS_WINDOWS:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # Clipboard functions
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.OpenClipboard.argtypes = [wintypes.HWND]

    user32.CloseClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []

    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []

    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardData.argtypes = [wintypes.UINT]

    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]

    # Memory functions
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]

    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]

    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]

    kernel32.GlobalFree.restype = wintypes.HGLOBAL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]

    # Input & Window functions
    user32.SendInput.restype = wintypes.UINT
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetForegroundWindow.argtypes = []

    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]

    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]

    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]


class InjectionMode(str, Enum):
    """Method used to inject text into the active window."""

    AUTO = "auto"
    KEYSTROKE = "keystroke"
    PASTE = "paste"


@dataclass
class WindowInfo:
    """Metadata regarding the currently focused foreground window."""

    hwnd: int
    title: str
    process_id: int
    process_name: str
    is_valid: bool


@dataclass
class InjectionResult:
    """Result of a text injection operation."""

    success: bool
    characters_injected: int
    method: str
    window: WindowInfo | None
    message: str


class ActiveWindowInjector:
    """Manages active window discovery, keystroke simulation, and clipboard injection."""

    def __init__(self) -> None:
        self._is_windows = IS_WINDOWS

    def get_active_window(self) -> WindowInfo:
        """Inspect the current foreground window on Windows."""
        if not self._is_windows:
            return WindowInfo(
                hwnd=0,
                title="Mock Non-Windows Desktop",
                process_id=0,
                process_name="desktop",
                is_valid=False,
            )

        raw_hwnd = user32.GetForegroundWindow()
        hwnd = int(raw_hwnd) if raw_hwnd else 0
        if hwnd == 0:
            return WindowInfo(
                hwnd=0,
                title="",
                process_id=0,
                process_name="",
                is_valid=False,
            )

        # Retrieve window title
        length = user32.GetWindowTextLengthW(hwnd)
        buff = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buff, length + 1)
        title = buff.value.strip()

        # Retrieve process ID and executable name
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        process_name = ""

        if pid.value > 0:
            proc_handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if proc_handle:
                try:
                    name_buff = ctypes.create_unicode_buffer(1024)
                    size = wintypes.DWORD(1024)
                    if kernel32.QueryFullProcessImageNameW(
                        proc_handle, 0, name_buff, ctypes.byref(size)
                    ):
                        process_name = os.path.basename(name_buff.value)
                finally:
                    kernel32.CloseHandle(proc_handle)

        return WindowInfo(
            hwnd=hwnd,
            title=title,
            process_id=pid.value,
            process_name=process_name,
            is_valid=True,
        )

    # -----------------------------------------------------------------------
    # Clipboard Operations
    # -----------------------------------------------------------------------
    def get_clipboard_text(self, retries: int = 5, retry_delay: float = 0.02) -> str | None:
        """Retrieve unicode text from Windows clipboard with contention retries."""
        if not self._is_windows:
            return None

        for _ in range(retries):
            if user32.OpenClipboard(None):
                try:
                    h_mem = user32.GetClipboardData(CF_UNICODETEXT)
                    if not h_mem:
                        return None
                    ptr = kernel32.GlobalLock(h_mem)
                    if not ptr:
                        return None
                    try:
                        return str(ctypes.wstring_at(ptr))
                    finally:
                        kernel32.GlobalUnlock(h_mem)
                finally:
                    user32.CloseClipboard()
            time.sleep(retry_delay)
        return None

    def set_clipboard_text(
        self, text: str, retries: int = 5, retry_delay: float = 0.02
    ) -> bool:
        """Copy unicode text to the Windows clipboard with contention retries."""
        if not self._is_windows:
            return False

        encoded = text.encode("utf-16-le") + b"\x00\x00"
        for _ in range(retries):
            if user32.OpenClipboard(None):
                try:
                    user32.EmptyClipboard()
                    h_mem = kernel32.GlobalAlloc(GHND, len(encoded))
                    if not h_mem:
                        return False
                    ptr = kernel32.GlobalLock(h_mem)
                    if not ptr:
                        kernel32.GlobalFree(h_mem)
                        return False
                    ctypes.memmove(ptr, encoded, len(encoded))
                    kernel32.GlobalUnlock(h_mem)
                    res = user32.SetClipboardData(CF_UNICODETEXT, h_mem)
                    return bool(res)
                finally:
                    user32.CloseClipboard()
            time.sleep(retry_delay)
        return False

    # -----------------------------------------------------------------------
    # Keystroke Simulation via SendInput
    # -----------------------------------------------------------------------
    def _send_inputs(self, inputs: list[INPUT]) -> int:
        """Send a sequence of INPUT structures to the active window."""
        if not self._is_windows or not inputs:
            return 0
        n = len(inputs)
        arr = (INPUT * n)(*inputs)
        return int(user32.SendInput(n, arr, ctypes.sizeof(INPUT)))

    def send_virtual_key(self, vk_code: int, extended: bool = False) -> None:
        """Simulate a single Virtual Key DOWN followed by UP."""
        flags_down = KEYEVENTF_KEYDOWN | (KEYEVENTF_EXTENDEDKEY if extended else 0)
        flags_up = KEYEVENTF_KEYUP | (KEYEVENTF_EXTENDEDKEY if extended else 0)

        down = INPUT(
            type=INPUT_KEYBOARD,
            union=_INPUT_UNION(
                ki=KEYBDINPUT(
                    wVk=vk_code,
                    wScan=0,
                    dwFlags=flags_down,
                    time=0,
                    dwExtraInfo=0,
                )
            ),
        )
        up = INPUT(
            type=INPUT_KEYBOARD,
            union=_INPUT_UNION(
                ki=KEYBDINPUT(
                    wVk=vk_code,
                    wScan=0,
                    dwFlags=flags_up,
                    time=0,
                    dwExtraInfo=0,
                )
            ),
        )
        self._send_inputs([down, up])

    def send_ctrl_v(self) -> None:
        """Send Ctrl+V keystroke to trigger paste in the active window."""
        inputs = [
            # Ctrl Down
            INPUT(
                type=INPUT_KEYBOARD,
                union=_INPUT_UNION(
                    ki=KEYBDINPUT(
                        wVk=VK_CONTROL, wScan=0, dwFlags=KEYEVENTF_KEYDOWN, time=0, dwExtraInfo=0
                    )
                ),
            ),
            # V Down
            INPUT(
                type=INPUT_KEYBOARD,
                union=_INPUT_UNION(
                    ki=KEYBDINPUT(wVk=VK_V, wScan=0, dwFlags=KEYEVENTF_KEYDOWN, time=0, dwExtraInfo=0)
                ),
            ),
            # V Up
            INPUT(
                type=INPUT_KEYBOARD,
                union=_INPUT_UNION(
                    ki=KEYBDINPUT(wVk=VK_V, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0)
                ),
            ),
            # Ctrl Up
            INPUT(
                type=INPUT_KEYBOARD,
                union=_INPUT_UNION(
                    ki=KEYBDINPUT(
                        wVk=VK_CONTROL, wScan=0, dwFlags=KEYEVENTF_KEYUP, time=0, dwExtraInfo=0
                    )
                ),
            ),
        ]
        self._send_inputs(inputs)

    def type_text(self, text: str, delay_ms: float = 0.0) -> int:
        """Type unicode characters directly into the active window using SendInput."""
        if not text:
            return 0
        if not self._is_windows:
            logger.info("Non-Windows platform: simulated typing '%s'", text)
            return len(text)

        injected_count = 0
        for char in text:
            if char in ("\r", "\n"):
                if char == "\n":
                    self.send_virtual_key(VK_RETURN)
                    injected_count += 1
                continue
            if char == "\t":
                self.send_virtual_key(VK_TAB)
                injected_count += 1
                continue

            # Convert character into UTF-16 code units (handles emojis & surrogate pairs)
            utf16_bytes = char.encode("utf-16-le")
            # Unpack into 16-bit unsigned integers
            code_units = [
                utf16_bytes[i] | (utf16_bytes[i + 1] << 8)
                for i in range(0, len(utf16_bytes), 2)
            ]

            char_inputs: list[INPUT] = []
            for unit in code_units:
                # Key Down
                char_inputs.append(
                    INPUT(
                        type=INPUT_KEYBOARD,
                        union=_INPUT_UNION(
                            ki=KEYBDINPUT(
                                wVk=0,
                                wScan=unit,
                                dwFlags=KEYEVENTF_UNICODE,
                                time=0,
                                dwExtraInfo=0,
                            )
                        ),
                    )
                )
                # Key Up
                char_inputs.append(
                    INPUT(
                        type=INPUT_KEYBOARD,
                        union=_INPUT_UNION(
                            ki=KEYBDINPUT(
                                wVk=0,
                                wScan=unit,
                                dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                                time=0,
                                dwExtraInfo=0,
                            )
                        ),
                    )
                )

            self._send_inputs(char_inputs)
            injected_count += 1

            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

        return injected_count

    def paste_text(
        self, text: str, restore_clipboard: bool = True, restore_delay_s: float = 0.15
    ) -> bool:
        """Inject text by copying to clipboard, triggering Ctrl+V, and restoring previous content."""
        if not text:
            return True
        if not self._is_windows:
            logger.info("Non-Windows platform: simulated paste '%s'", text)
            return True

        original_clipboard = self.get_clipboard_text() if restore_clipboard else None

        if not self.set_clipboard_text(text):
            logger.warning("Failed to copy text to clipboard for injection")
            return False

        # Dispatch Ctrl+V
        self.send_ctrl_v()

        # Restore original clipboard asynchronously so target application finishes WM_PASTE
        if restore_clipboard and original_clipboard is not None:
            def _restore() -> None:
                time.sleep(restore_delay_s)
                self.set_clipboard_text(original_clipboard)

            threading.Thread(target=_restore, daemon=True, name="ClipboardRestoreThread").start()

        return True

    # -----------------------------------------------------------------------
    # Main Injection Entrypoint
    # -----------------------------------------------------------------------
    def inject_text(
        self,
        text: str,
        mode: InjectionMode | str = InjectionMode.AUTO,
        enter_after: bool = False,
        restore_clipboard: bool = True,
    ) -> InjectionResult:
        """Inject dictated text into the active window.

        Args:
            text: Spoken transcript or text to inject.
            mode: Injection strategy ('auto', 'keystroke', or 'paste').
            enter_after: If True, sends an Enter keypress after injecting text.
            restore_clipboard: When pasting, whether to restore previous clipboard data.

        Returns:
            InjectionResult detailing success, character count, and target window.
        """
        if not text:
            return InjectionResult(
                success=True,
                characters_injected=0,
                method="none",
                window=None,
                message="No text provided for injection.",
            )

        win_info = self.get_active_window()
        str_mode = mode.value if isinstance(mode, InjectionMode) else str(mode).lower()

        # Decide injection method
        if str_mode == "auto":
            # Use paste for long text (>30 chars), newlines, or emojis (surrogate code points)
            has_newline = "\n" in text or "\r" in text
            has_high_unicode = any(ord(c) > 0xFFFF for c in text)
            if len(text) > 30 or has_newline or has_high_unicode:
                effective_method = "paste"
            else:
                effective_method = "keystroke"
        elif str_mode in ("paste", "clip", "clipboard"):
            effective_method = "paste"
        else:
            effective_method = "keystroke"

        success = True
        chars_done = 0

        if effective_method == "paste":
            success = self.paste_text(text, restore_clipboard=restore_clipboard)
            chars_done = len(text) if success else 0
        else:
            chars_done = self.type_text(text)
            success = chars_done > 0

        if enter_after and self._is_windows:
            self.send_virtual_key(VK_RETURN)

        target_desc = win_info.title or win_info.process_name or "active window"
        msg = (
            f"Successfully injected {chars_done} characters into '{target_desc}' via {effective_method}."
            if success
            else f"Failed to inject text into '{target_desc}'."
        )

        return InjectionResult(
            success=success,
            characters_injected=chars_done,
            method=effective_method,
            window=win_info,
            message=msg,
        )

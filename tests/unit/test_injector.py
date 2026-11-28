"""Unit tests for ActiveWindowInjector and active window text injection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from broski.system.injector import (
    ActiveWindowInjector,
    InjectionMode,
    InjectionResult,
    WindowInfo,
)


def test_window_info_and_result_dataclasses() -> None:
    """Validate WindowInfo and InjectionResult structures."""
    win = WindowInfo(
        hwnd=12345,
        title="Test Window",
        process_id=999,
        process_name="notepad.exe",
        is_valid=True,
    )
    assert win.hwnd == 12345
    assert win.title == "Test Window"
    assert win.process_name == "notepad.exe"
    assert win.is_valid is True

    res = InjectionResult(
        success=True,
        characters_injected=10,
        method="paste",
        window=win,
        message="Injected 10 characters.",
    )
    assert res.success is True
    assert res.characters_injected == 10
    assert res.method == "paste"
    assert res.window is not None
    assert res.window.title == "Test Window"


def test_get_active_window_non_windows() -> None:
    """Non-Windows platforms should return safe fallback WindowInfo."""
    injector = ActiveWindowInjector()
    injector._is_windows = False

    win = injector.get_active_window()
    assert win.hwnd == 0
    assert win.is_valid is False
    assert "Non-Windows" in win.title


@patch("broski.system.injector.user32")
@patch("broski.system.injector.kernel32")
def test_get_active_window_mocked(mock_kernel: MagicMock, mock_user: MagicMock) -> None:
    """Validate window discovery with mocked Win32 APIs."""
    injector = ActiveWindowInjector()
    injector._is_windows = True

    title_str = "Obsidian - Notes"
    mock_user.GetForegroundWindow.return_value = 54321
    mock_user.GetWindowTextLengthW.return_value = len(title_str)

    def fake_get_window_text(hwnd: int, buff: object, length: int) -> int:
        ctypes_buff = buff
        ctypes_buff.value = title_str  # type: ignore[union-attr]
        return len(title_str)

    mock_user.GetWindowTextW.side_effect = fake_get_window_text

    def fake_get_thread_proc_id(hwnd: int, pid_ref: object) -> int:
        pid_ref._obj.value = 4040  # type: ignore[attr-defined]
        return 1

    mock_user.GetWindowThreadProcessId.side_effect = fake_get_thread_proc_id

    # Mock process query
    mock_kernel.OpenProcess.return_value = 9999

    def fake_query_full_proc(
        handle: int, flags: int, buff: object, size_ref: object
    ) -> int:
        buff.value = r"C:\Program Files\Obsidian\Obsidian.exe"  # type: ignore[union-attr]
        return 1

    mock_kernel.QueryFullProcessImageNameW.side_effect = fake_query_full_proc
    mock_kernel.CloseHandle.return_value = 1

    win = injector.get_active_window()
    assert win.hwnd == 54321
    assert win.title == "Obsidian - Notes"
    assert win.process_id == 4040
    assert win.process_name == "Obsidian.exe"
    assert win.is_valid is True


@patch("broski.system.injector.user32")
def test_get_active_window_zero_hwnd(mock_user: MagicMock) -> None:
    """When no window has focus (HWND=0), return invalid WindowInfo gracefully."""
    injector = ActiveWindowInjector()
    injector._is_windows = True

    mock_user.GetForegroundWindow.return_value = 0
    win = injector.get_active_window()
    assert win.hwnd == 0
    assert win.is_valid is False
    assert win.title == ""


def test_type_text_empty() -> None:
    """Typing an empty string should return 0 characters without dispatching inputs."""
    injector = ActiveWindowInjector()
    assert injector.type_text("") == 0


def test_type_text_keystroke_simulation() -> None:
    """Validate Unicode keystroke simulation dispatches SendInput structures."""
    injector = ActiveWindowInjector()
    sent_inputs: list[list[object]] = []

    def fake_send_inputs(inputs: list[object]) -> int:
        sent_inputs.append(inputs)
        return len(inputs)

    injector._send_inputs = fake_send_inputs  # type: ignore[assignment]
    injector._is_windows = True

    # Type "Hi\n" -> 'H', 'i', Enter (VK_RETURN)
    count = injector.type_text("Hi\n")
    assert count == 3
    # Two character inputs (each has down+up = 2 events) + 1 enter (down+up = 2 events)
    assert len(sent_inputs) == 3


def test_type_text_surrogate_pair_emojis() -> None:
    """Validate non-BMP characters (emojis) are split into UTF-16 surrogate pairs."""
    injector = ActiveWindowInjector()
    sent_inputs: list[list[object]] = []

    def fake_send_inputs(inputs: list[object]) -> int:
        sent_inputs.append(inputs)
        return len(inputs)

    injector._send_inputs = fake_send_inputs  # type: ignore[assignment]
    injector._is_windows = True

    # Emoji 🚀 has ord 0x1F680 (surrogate pair: 2 code units)
    count = injector.type_text("🚀")
    assert count == 1
    # 1 character dispatched with surrogate code units (2 code units * (down+up) = 4 events)
    assert len(sent_inputs) == 1
    assert len(sent_inputs[0]) == 4


def test_paste_text_with_clipboard_backup_and_restore() -> None:
    """Validate paste copies new text, triggers Ctrl+V, and restores original clipboard."""
    injector = ActiveWindowInjector()
    injector._is_windows = True

    clipboard_state = {"content": "original secret clipboard"}
    ctrl_v_called = []

    def fake_get_clip() -> str | None:
        return clipboard_state["content"]

    def fake_set_clip(text: str) -> bool:
        clipboard_state["content"] = text
        return True

    def fake_ctrl_v() -> None:
        ctrl_v_called.append(True)

    injector.get_clipboard_text = fake_get_clip  # type: ignore[assignment]
    injector.set_clipboard_text = fake_set_clip  # type: ignore[assignment]
    injector.send_ctrl_v = fake_ctrl_v  # type: ignore[assignment]

    success = injector.paste_text("Hello from Broski!", restore_clipboard=True, restore_delay_s=0.01)
    assert success is True
    assert ctrl_v_called == [True]
    # Immediately after paste, clipboard contains injected text
    assert clipboard_state["content"] == "Hello from Broski!"

    # Wait briefly for background thread to restore original clipboard
    import time

    time.sleep(0.05)
    assert clipboard_state["content"] == "original secret clipboard"


def test_inject_text_empty() -> None:
    """Injecting empty string returns no-op InjectionResult."""
    injector = ActiveWindowInjector()
    res = injector.inject_text("")
    assert res.success is True
    assert res.characters_injected == 0
    assert res.method == "none"


def test_inject_text_auto_routing() -> None:
    """Test auto mode heuristic: short text -> keystroke; long/multiline/emoji -> paste."""
    injector = ActiveWindowInjector()
    injector.get_active_window = MagicMock(  # type: ignore[assignment]
        return_value=WindowInfo(1, "Notepad", 100, "notepad.exe", True)
    )

    injector.type_text = MagicMock(return_value=12)  # type: ignore[assignment]
    injector.paste_text = MagicMock(return_value=True)  # type: ignore[assignment]

    # 1. Short plain text (<30 chars) -> keystroke
    res1 = injector.inject_text("Short text")
    assert res1.method == "keystroke"
    injector.type_text.assert_called_once_with("Short text")
    injector.paste_text.assert_not_called()

    # 2. Long text (>30 chars) -> paste
    injector.type_text.reset_mock()
    injector.paste_text.reset_mock()
    long_text = "This is a much longer paragraph intended for meeting notes in Obsidian."
    res2 = injector.inject_text(long_text)
    assert res2.method == "paste"
    injector.paste_text.assert_called_once()
    injector.type_text.assert_not_called()

    # 3. Text with newline -> paste
    injector.type_text.reset_mock()
    injector.paste_text.reset_mock()
    res3 = injector.inject_text("Line 1\nLine 2")
    assert res3.method == "paste"
    injector.paste_text.assert_called_once()

    # 4. Text with emoji -> paste
    injector.type_text.reset_mock()
    injector.paste_text.reset_mock()
    res4 = injector.inject_text("Good job! 🚀")
    assert res4.method == "paste"
    injector.paste_text.assert_called_once()


def test_inject_text_explicit_modes() -> None:
    """Validate explicit InjectionMode selection overrides heuristics."""
    injector = ActiveWindowInjector()
    injector.get_active_window = MagicMock(  # type: ignore[assignment]
        return_value=WindowInfo(1, "VS Code", 200, "code.exe", True)
    )
    injector.type_text = MagicMock(return_value=100)  # type: ignore[assignment]
    injector.paste_text = MagicMock(return_value=True)  # type: ignore[assignment]

    # Force keystroke on long text
    long_text = "A" * 100
    res_key = injector.inject_text(long_text, mode=InjectionMode.KEYSTROKE)
    assert res_key.method == "keystroke"
    injector.type_text.assert_called_once()

    # Force paste on short text
    injector.paste_text.reset_mock()
    res_paste = injector.inject_text("hi", mode=InjectionMode.PASTE)
    assert res_paste.method == "paste"
    injector.paste_text.assert_called_once()


def test_inject_text_enter_after() -> None:
    """Validate enter_after dispatches Return key when requested."""
    injector = ActiveWindowInjector()
    injector._is_windows = True
    injector.get_active_window = MagicMock(  # type: ignore[assignment]
        return_value=WindowInfo(1, "Terminal", 300, "wt.exe", True)
    )
    injector.type_text = MagicMock(return_value=4)  # type: ignore[assignment]
    injector.send_virtual_key = MagicMock()  # type: ignore[assignment]

    res = injector.inject_text("ls -l", enter_after=True)
    assert res.success is True
    injector.send_virtual_key.assert_called_once()

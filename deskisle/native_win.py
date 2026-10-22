"""Small, dependency-free Windows integration helpers for DeskIsle.

The module deliberately keeps all ``ctypes`` loading behind a platform guard so
that it remains safe to import while developing or testing on macOS/Linux.  The
desktop-window hierarchy used by Explorer is *not* a documented public API;
see :func:`attach_to_desktop` for the containment and fallback strategy.
"""

from __future__ import annotations

import atexit
import os
import sys
import threading
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Final


# RegisterHotKey modifiers.
MOD_ALT: Final = 0x0001
MOD_CONTROL: Final = 0x0002
MOD_SHIFT: Final = 0x0004
MOD_WIN: Final = 0x0008
MOD_NOREPEAT: Final = 0x4000

# Frequently useful virtual-key codes.  Letter and digit constants are added
# below as well (VK_A .. VK_Z and VK_0 .. VK_9).
VK_BACK: Final = 0x08
VK_TAB: Final = 0x09
VK_RETURN: Final = 0x0D
VK_SHIFT: Final = 0x10
VK_CONTROL: Final = 0x11
VK_MENU: Final = 0x12  # The Alt key.
VK_ESCAPE: Final = 0x1B
VK_SPACE: Final = 0x20
VK_PRIOR: Final = 0x21  # Page Up.
VK_NEXT: Final = 0x22  # Page Down.
VK_END: Final = 0x23
VK_HOME: Final = 0x24
VK_LEFT: Final = 0x25
VK_UP: Final = 0x26
VK_RIGHT: Final = 0x27
VK_DOWN: Final = 0x28
VK_INSERT: Final = 0x2D
VK_DELETE: Final = 0x2E
VK_F1: Final = 0x70
VK_F2: Final = 0x71
VK_F3: Final = 0x72
VK_F4: Final = 0x73
VK_F5: Final = 0x74
VK_F6: Final = 0x75
VK_F7: Final = 0x76
VK_F8: Final = 0x77
VK_F9: Final = 0x78
VK_F10: Final = 0x79
VK_F11: Final = 0x7A
VK_F12: Final = 0x7B

for _character in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    globals()[f"VK_{_character}"] = ord(_character)
del _character


_IS_WINDOWS: Final = sys.platform == "win32"
STARTUP_VALUE_NAME: Final = "DeskIsle"

# Win32 constants used internally.
_GWL_STYLE = -16
_GWL_EXSTYLE = -20
_GWLP_HWNDPARENT = -8
_WS_VISIBLE = 0x10000000
_WS_CHILD = 0x40000000
_WS_POPUP = 0x80000000
_WS_CLIPSIBLINGS = 0x04000000
_WS_EX_TOPMOST = 0x00000008
_WS_EX_NOACTIVATE = 0x08000000
_SW_HIDE = 0
_SW_SHOW = 5
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_SWP_SHOWWINDOW = 0x0040
_SMTO_ABORTIFHUNG = 0x0002
_WM_SPAWN_WORKERW = 0x052C  # Undocumented Explorer message; best-effort only.
_SM_XVIRTUALSCREEN = 76
_SM_YVIRTUALSCREEN = 77
_SM_CXVIRTUALSCREEN = 78
_SM_CYVIRTUALSCREEN = 79


if _IS_WINDOWS:
    import ctypes
    from ctypes import wintypes
    import winreg

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _LONG_PTR = ctypes.c_ssize_t
    _DWORD_PTR = ctypes.c_size_t
    _LRESULT = _LONG_PTR
    _WNDENUMPROC = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
    )

    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.FindWindowExW.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
    ]
    _user32.FindWindowExW.restype = wintypes.HWND
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.POINTER(_DWORD_PTR),
    ]
    _user32.SendMessageTimeoutW.restype = _LRESULT
    _user32.GetParent.argtypes = [wintypes.HWND]
    _user32.GetParent.restype = wintypes.HWND
    _user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    _user32.SetParent.restype = wintypes.HWND
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    _user32.ScreenToClient.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindow.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    _user32.GetSystemMetrics.restype = ctypes.c_int
    _user32.RegisterHotKey.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        wintypes.UINT,
        wintypes.UINT,
    ]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL

    # Get/SetWindowLongPtr are C macros on 32-bit Windows, where their exports
    # are named Get/SetWindowLong instead.
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        _get_window_long_ptr = _user32.GetWindowLongPtrW
        _set_window_long_ptr = _user32.SetWindowLongPtrW
    else:  # pragma: no cover - only exercised by a 32-bit Python runtime.
        _get_window_long_ptr = _user32.GetWindowLongW
        _set_window_long_ptr = _user32.SetWindowLongW

    _get_window_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int]
    _get_window_long_ptr.restype = _LONG_PTR
    _set_window_long_ptr.argtypes = [wintypes.HWND, ctypes.c_int, _LONG_PTR]
    _set_window_long_ptr.restype = _LONG_PTR
else:
    # These names exist to make introspection/mocking predictable off Windows.
    ctypes = None  # type: ignore[assignment]
    wintypes = None  # type: ignore[assignment]
    winreg = None  # type: ignore[assignment]
    _user32 = None


@dataclass
class _AttachmentState:
    original_parent: int
    original_style: int
    original_exstyle: int
    attached_parent: int = 0
    is_attached: bool = False


@dataclass(frozen=True)
class _DesktopWindows:
    progman: int = 0
    icon_host: int = 0
    def_view: int = 0
    list_view: int = 0
    background_worker: int = 0


_state_lock = threading.RLock()
_attachments: dict[int, _AttachmentState] = {}
_native_icons_original_visibility: bool | None = None
_native_icons_window: int = 0


def is_windows() -> bool:
    """Return whether the current process is running on Windows."""

    return _IS_WINDOWS


def virtual_screen_geometry() -> tuple[int, int, int, int]:
    """Return ``(x, y, width, height)`` for the complete virtual desktop.

    Secondary monitors can make ``x`` and/or ``y`` negative.  Off Windows a
    zero rectangle is returned instead of raising during tests or imports.
    """

    if not _IS_WINDOWS:
        return (0, 0, 0, 0)
    try:
        return (
            int(_user32.GetSystemMetrics(_SM_XVIRTUALSCREEN)),
            int(_user32.GetSystemMetrics(_SM_YVIRTUALSCREEN)),
            int(_user32.GetSystemMetrics(_SM_CXVIRTUALSCREEN)),
            int(_user32.GetSystemMetrics(_SM_CYVIRTUALSCREEN)),
        )
    except Exception:
        return (0, 0, 0, 0)


def _as_hwnd(value: int):
    """Convert a Python integer to HWND without exposing wintypes off-Windows."""

    return wintypes.HWND(int(value))


def _handle_value(value) -> int:
    if not value:
        return 0
    # ctypes callbacks/functions normally hand us a Python int, while tests or
    # alternate runtimes may expose a c_void_p instance instead.
    raw = getattr(value, "value", value)
    return int(raw or 0)


def _window_is_valid(hwnd: int) -> bool:
    return bool(hwnd and _IS_WINDOWS and _user32.IsWindow(_as_hwnd(hwnd)))


def _get_style(hwnd: int, index: int) -> int:
    # Window styles are DWORD values even when accessed through LONG_PTR.
    return int(_get_window_long_ptr(_as_hwnd(hwnd), index)) & 0xFFFFFFFF


def _try_set_window_long(hwnd: int, index: int, value: int) -> bool:
    try:
        ctypes.set_last_error(0)
        previous = _set_window_long_ptr(
            _as_hwnd(hwnd), index, _LONG_PTR(int(value))
        )
        return bool(previous) or ctypes.get_last_error() == 0
    except Exception:
        return False


def _try_set_parent(hwnd: int, parent: int) -> bool:
    try:
        ctypes.set_last_error(0)
        previous = _user32.SetParent(_as_hwnd(hwnd), _as_hwnd(parent))
        # A null return is successful when the old parent was also null.
        return bool(previous) or ctypes.get_last_error() == 0
    except Exception:
        return False


def _find_desktop_windows(spawn_worker: bool = False) -> _DesktopWindows:
    """Locate Explorer's desktop view and the WorkerW immediately behind it."""

    if not _IS_WINDOWS:
        return _DesktopWindows()

    progman = _handle_value(_user32.FindWindowW("Progman", None))

    def enumerate_once() -> _DesktopWindows:
        found: dict[str, int] = {}

        @_WNDENUMPROC
        def callback(top_hwnd, _lparam):
            try:
                top = _handle_value(top_hwnd)
                def_view = _handle_value(
                    _user32.FindWindowExW(
                        _as_hwnd(top), _as_hwnd(0), "SHELLDLL_DefView", None
                    )
                )
                if not def_view:
                    return True

                found["icon_host"] = top
                found["def_view"] = def_view
                found["list_view"] = _handle_value(
                    _user32.FindWindowExW(
                        _as_hwnd(def_view), _as_hwnd(0), "SysListView32", "FolderView"
                    )
                )
                if not found["list_view"]:
                    # Some Explorer builds/locales do not expose the title.
                    found["list_view"] = _handle_value(
                        _user32.FindWindowExW(
                            _as_hwnd(def_view), _as_hwnd(0), "SysListView32", None
                        )
                    )

                # FindWindowEx(NULL, icon_host, ...) searches the next top-level
                # WorkerW in Z order.  This is the conventional wallpaper layer
                # behind the WorkerW/Progman that owns SHELLDLL_DefView.
                found["background_worker"] = _handle_value(
                    _user32.FindWindowExW(
                        _as_hwnd(0), _as_hwnd(top), "WorkerW", None
                    )
                )
                return False
            except Exception:
                # Exceptions must never escape a native EnumWindows callback.
                return True

        try:
            _user32.EnumWindows(callback, 0)
        except Exception:
            pass

        # On configurations where DefView is a direct Progman child, enumeration
        # above will normally find it, but retain an explicit fallback.
        if not found.get("def_view") and progman:
            def_view = _handle_value(
                _user32.FindWindowExW(
                    _as_hwnd(progman), _as_hwnd(0), "SHELLDLL_DefView", None
                )
            )
            if def_view:
                found["icon_host"] = progman
                found["def_view"] = def_view
                found["list_view"] = _handle_value(
                    _user32.FindWindowExW(
                        _as_hwnd(def_view), _as_hwnd(0), "SysListView32", None
                    )
                )

        return _DesktopWindows(
            progman=progman,
            icon_host=found.get("icon_host", 0),
            def_view=found.get("def_view", 0),
            list_view=found.get("list_view", 0),
            background_worker=found.get("background_worker", 0),
        )

    windows = enumerate_once()
    if windows.background_worker or not spawn_worker or not progman:
        return windows

    # 0x052C is an Explorer implementation detail used by wallpaper utilities
    # to ask Progman to create the second WorkerW.  Bound the call so a hung
    # Explorer cannot hang DeskIsle; failure simply falls back to the icon host.
    try:
        result = _DWORD_PTR()
        _user32.SendMessageTimeoutW(
            _as_hwnd(progman),
            _WM_SPAWN_WORKERW,
            0,
            0,
            _SMTO_ABORTIFHUNG,
            1000,
            ctypes.byref(result),
        )
    except Exception:
        pass
    return enumerate_once()


def _current_window_rect(hwnd: int):
    rect = wintypes.RECT()
    if not _user32.GetWindowRect(_as_hwnd(hwnd), ctypes.byref(rect)):
        return None
    return (
        int(rect.left),
        int(rect.top),
        max(0, int(rect.right - rect.left)),
        max(0, int(rect.bottom - rect.top)),
    )


def _screen_point_to_client(parent: int, x: int, y: int) -> tuple[int, int]:
    if not parent:
        return (x, y)
    point = wintypes.POINT(x, y)
    if _user32.ScreenToClient(_as_hwnd(parent), ctypes.byref(point)):
        return (int(point.x), int(point.y))
    return (x, y)


def _attach_locked(hwnd: int, state: _AttachmentState | None = None) -> bool:
    if not _window_is_valid(hwnd):
        return False

    if state is None:
        state = _attachments.get(hwnd)
    if state and state.is_attached and _window_is_valid(state.attached_parent):
        return True

    windows = _find_desktop_windows(spawn_worker=True)
    # DeskIsle is interactive, so parent it alongside SHELLDLL_DefView and put
    # it above that child.  Wallpaper-only utilities prefer background_worker,
    # but a window there cannot receive the desktop mouse events we need.
    parent = windows.icon_host or windows.progman or windows.background_worker
    if not parent or parent == hwnd or not _window_is_valid(parent):
        return False

    if state is None:
        state = _AttachmentState(
            original_parent=_handle_value(_user32.GetParent(_as_hwnd(hwnd))),
            original_style=_get_style(hwnd, _GWL_STYLE),
            original_exstyle=_get_style(hwnd, _GWL_EXSTYLE),
        )

    rect = _current_window_rect(hwnd)
    was_visible = bool(_get_style(hwnd, _GWL_STYLE) & _WS_VISIBLE)
    child_style = (state.original_style | _WS_CHILD | _WS_CLIPSIBLINGS) & ~_WS_POPUP
    child_exstyle = state.original_exstyle & ~_WS_EX_TOPMOST

    if not _try_set_window_long(hwnd, _GWL_STYLE, child_style):
        return False
    if not _try_set_window_long(hwnd, _GWL_EXSTYLE, child_exstyle):
        _try_set_window_long(hwnd, _GWL_STYLE, state.original_style)
        return False
    if not _try_set_parent(hwnd, parent):
        _try_set_window_long(hwnd, _GWL_STYLE, state.original_style)
        _try_set_window_long(hwnd, _GWL_EXSTYLE, state.original_exstyle)
        return False

    flags = _SWP_NOACTIVATE | _SWP_FRAMECHANGED
    if was_visible:
        flags |= _SWP_SHOWWINDOW
    if rect:
        x, y = _screen_point_to_client(parent, rect[0], rect[1])
        positioned = bool(
            _user32.SetWindowPos(
                _as_hwnd(hwnd), _as_hwnd(0), x, y, rect[2], rect[3], flags
            )
        )
    else:
        positioned = bool(
            _user32.SetWindowPos(
                _as_hwnd(hwnd),
                _as_hwnd(0),
                0,
                0,
                0,
                0,
                flags | _SWP_NOMOVE | _SWP_NOSIZE,
            )
        )

    if not positioned:
        _try_set_parent(hwnd, state.original_parent)
        _try_set_window_long(hwnd, _GWL_STYLE, state.original_style)
        _try_set_window_long(hwnd, _GWL_EXSTYLE, state.original_exstyle)
        return False

    state.attached_parent = parent
    state.is_attached = True
    _attachments[hwnd] = state
    return True


def attach_to_desktop(hwnd: int) -> bool:
    """Attach a Qt/native HWND to Explorer's desktop background layer.

    Original parent and style values are retained for exact restoration.  This
    is necessarily best-effort because Progman/WorkerW/SHELLDLL_DefView are
    Explorer implementation details, not a supported desktop-widget contract.
    """

    if not _IS_WINDOWS:
        return False
    try:
        hwnd = int(hwnd)
        with _state_lock:
            return _attach_locked(hwnd)
    except (TypeError, ValueError, OverflowError, OSError):
        return False
    except Exception:
        return False


def _detach_locked(hwnd: int, *, forget: bool) -> bool:
    state = _attachments.get(hwnd)
    if state is None:
        return True
    if not _window_is_valid(hwnd):
        _attachments.pop(hwnd, None)
        return False

    rect = _current_window_rect(hwnd)
    original_relation = (
        state.original_parent if _window_is_valid(state.original_parent) else 0
    )
    # For WS_CHILD this is a real parent.  For a top-level WS_POPUP window,
    # GetParent returns its owner; detach from the desktop first, then restore
    # that owner through GWLP_HWNDPARENT after restoring the original style.
    target_parent = (
        original_relation if state.original_style & _WS_CHILD else 0
    )

    parent_ok = True
    if state.is_attached:
        parent_ok = _try_set_parent(hwnd, target_parent)
    style_ok = _try_set_window_long(hwnd, _GWL_STYLE, state.original_style)
    exstyle_ok = _try_set_window_long(hwnd, _GWL_EXSTYLE, state.original_exstyle)
    owner_ok = True
    if original_relation and not (state.original_style & _WS_CHILD):
        owner_ok = _try_set_window_long(
            hwnd, _GWLP_HWNDPARENT, original_relation
        )

    if rect:
        x, y = rect[0], rect[1]
        if target_parent and state.original_style & _WS_CHILD:
            x, y = _screen_point_to_client(target_parent, x, y)
        _user32.SetWindowPos(
            _as_hwnd(hwnd),
            _as_hwnd(-1 if state.original_exstyle & _WS_EX_TOPMOST else -2),
            x,
            y,
            rect[2],
            rect[3],
            _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
        )
    else:
        _user32.SetWindowPos(
            _as_hwnd(hwnd),
            _as_hwnd(-1 if state.original_exstyle & _WS_EX_TOPMOST else -2),
            0,
            0,
            0,
            0,
            _SWP_NOMOVE
            | _SWP_NOSIZE
            | _SWP_NOACTIVATE
            | _SWP_FRAMECHANGED,
        )

    if parent_ok and owner_ok:
        state.attached_parent = 0
        state.is_attached = False
    if forget and parent_ok and owner_ok and style_ok and exstyle_ok:
        _attachments.pop(hwnd, None)
    return parent_ok and owner_ok and style_ok and exstyle_ok


def detach_from_desktop(hwnd: int) -> None:
    """Restore the parent/styles saved by :func:`attach_to_desktop`.

    The function is idempotent and intentionally never raises during shutdown.
    """

    if not _IS_WINDOWS:
        return
    try:
        hwnd = int(hwnd)
        with _state_lock:
            _detach_locked(hwnd, forget=True)
    except Exception:
        return


def set_focus_overlay(hwnd: int, enabled: bool) -> None:
    """Temporarily turn a desktop child into a topmost editing overlay.

    Enabling restores the HWND to its original top-level form before setting it
    topmost.  Disabling removes topmost state and reattaches it to the current
    Explorer desktop host (which may have changed after an Explorer restart).
    """

    if not _IS_WINDOWS:
        return
    try:
        hwnd = int(hwnd)
        if not _window_is_valid(hwnd):
            return
        with _state_lock:
            if enabled:
                _detach_locked(hwnd, forget=False)
                _user32.SetWindowPos(
                    _as_hwnd(hwnd),
                    _as_hwnd(-1),  # HWND_TOPMOST
                    0,
                    0,
                    0,
                    0,
                    _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
                )
            else:
                _user32.SetWindowPos(
                    _as_hwnd(hwnd),
                    _as_hwnd(-2),  # HWND_NOTOPMOST
                    0,
                    0,
                    0,
                    0,
                    _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
                )
                _attach_locked(hwnd, _attachments.get(hwnd))
    except Exception:
        return


def set_window_overlay(hwnd: int, enabled: bool) -> bool:
    """Change a standalone island's Z order without reparenting/recreating it."""
    if not _IS_WINDOWS:
        return False
    return bool(_user32.SetWindowPos(
        _as_hwnd(hwnd), _as_hwnd(-1 if enabled else 1),
        0, 0, 0, 0, _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
    ))


def set_window_no_activate(hwnd: int, enabled: bool) -> bool:
    """Toggle WS_EX_NOACTIVATE without recreating the Qt native window.

    Desktop panels remain fully mouse-interactive, but routine clicks do not
    make the virtual-screen-sized host the foreground application. This also
    prevents wallpaper tools from mistaking it for a focused fullscreen app.
    """
    if not _IS_WINDOWS:
        return False
    try:
        hwnd = int(hwnd)
        if not _window_is_valid(hwnd):
            return False
        exstyle = _get_style(hwnd, _GWL_EXSTYLE)
        wanted = (
            exstyle | _WS_EX_NOACTIVATE
            if enabled
            else exstyle & ~_WS_EX_NOACTIVATE
        )
        if wanted != exstyle and not _try_set_window_long(hwnd, _GWL_EXSTYLE, wanted):
            return False
        return bool(
            _user32.SetWindowPos(
                _as_hwnd(hwnd),
                _as_hwnd(0),
                0,
                0,
                0,
                0,
                _SWP_NOMOVE
                | _SWP_NOSIZE
                | _SWP_NOZORDER
                | _SWP_NOACTIVATE
                | _SWP_FRAMECHANGED,
            )
        )
    except (TypeError, ValueError, OverflowError, OSError):
        return False


def show_native_desktop_icons(show: bool) -> bool:
    """Show or hide Explorer's native desktop icon ListView.

    Only the ListView is touched; no registry setting is changed.  The original
    visibility is remembered for :func:`restore_native_desktop_icons`.
    """

    global _native_icons_original_visibility, _native_icons_window
    if not _IS_WINDOWS:
        return False
    try:
        with _state_lock:
            windows = _find_desktop_windows(spawn_worker=False)
            list_view = windows.list_view
            if not list_view or not _window_is_valid(list_view):
                return False

            if _native_icons_original_visibility is None:
                _native_icons_original_visibility = bool(
                    _get_style(list_view, _GWL_STYLE) & _WS_VISIBLE
                )
                _native_icons_window = list_view

            _user32.ShowWindow(
                _as_hwnd(list_view), _SW_SHOW if bool(show) else _SW_HIDE
            )
            _native_icons_window = list_view
            return bool(_get_style(list_view, _GWL_STYLE) & _WS_VISIBLE) == bool(show)
    except Exception:
        return False


def restore_native_desktop_icons() -> None:
    """Restore the icon visibility observed before DeskIsle changed it."""

    global _native_icons_original_visibility, _native_icons_window
    if not _IS_WINDOWS:
        return
    try:
        with _state_lock:
            original = _native_icons_original_visibility
            if original is None:
                return
            list_view = _native_icons_window
            if not _window_is_valid(list_view):
                list_view = _find_desktop_windows(spawn_worker=False).list_view
            if list_view and _window_is_valid(list_view):
                _user32.ShowWindow(
                    _as_hwnd(list_view), _SW_SHOW if original else _SW_HIDE
                )
            _native_icons_original_visibility = None
            _native_icons_window = 0
    except Exception:
        # Do not let cleanup errors mask application shutdown.
        _native_icons_original_visibility = None
        _native_icons_window = 0


def register_hotkey(hwnd: int, hotkey_id: int, modifiers: int, vk: int) -> bool:
    """Register a process/window global hotkey using ``RegisterHotKey``."""

    if not _IS_WINDOWS:
        return False
    try:
        return bool(
            _user32.RegisterHotKey(
                _as_hwnd(int(hwnd)),
                int(hotkey_id),
                int(modifiers) & 0xFFFFFFFF,
                int(vk) & 0xFFFFFFFF,
            )
        )
    except (TypeError, ValueError, OverflowError, OSError):
        return False
    except Exception:
        return False


def unregister_hotkey(hwnd: int, hotkey_id: int) -> bool:
    """Unregister a hotkey; return ``False`` if it was not registered."""

    if not _IS_WINDOWS:
        return False
    try:
        return bool(_user32.UnregisterHotKey(_as_hwnd(int(hwnd)), int(hotkey_id)))
    except (TypeError, ValueError, OverflowError, OSError):
        return False
    except Exception:
        return False


def add_to_startup(executable: os.PathLike[str] | str, enabled: bool, arguments=()) -> bool:
    """Add/remove DeskIsle in the current user's ``Run`` registry key.

    This requires no elevation and intentionally affects only the current user.
    ``executable`` is treated as a path (not an arbitrary command line), then
    quoted so spaces and shell metacharacters cannot change its interpretation.
    """

    if not _IS_WINDOWS:
        return False
    try:
        path = os.fsdecode(os.fspath(executable)).strip()
        if not path:
            return False
        # Accept a caller that already supplied conventional surrounding quotes,
        # while still storing one canonical quoted path.
        if len(path) >= 2 and path[0] == path[-1] == '"':
            path = path[1:-1].strip()
        if not path or '"' in path or "\x00" in path:
            return False
        path = os.path.abspath(path)

        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        if enabled:
            with winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.SetValueEx(
                    key, STARTUP_VALUE_NAME, 0, winreg.REG_SZ,
                    subprocess.list2cmdline([path, *arguments])
                )
            return True

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE
            ) as key:
                try:
                    winreg.DeleteValue(key, STARTUP_VALUE_NAME)
                except FileNotFoundError:
                    pass
            return True
        except FileNotFoundError:
            return True
    except (OSError, TypeError, ValueError):
        return False
    except Exception:
        return False


WM_SETTINGCHANGE: Final = 0x001A
SPI_SETDESKWALLPAPER: Final = 0x0014
_SPI_GETDESKWALLPAPER = 0x0073
_WALLPAPER_STYLES = {"0": "center", "2": "stretch", "6": "fit", "10": "fill", "22": "span"}
_IGNORED_FOREGROUND_CLASSES = {
    "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
    "NotifyIconOverflowWindow", "TopLevelWindowForOverflowXamlIsland",
}
_extra_prototypes_ready = False


def _ensure_extra_prototypes() -> None:
    global _extra_prototypes_ready
    if _extra_prototypes_ready or not _IS_WINDOWS:
        return
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
    _user32.SystemParametersInfoW.restype = wintypes.BOOL
    _extra_prototypes_ready = True


def get_wallpaper_info() -> dict:
    """Return the current wallpaper path, placement style and fill colour.

    Used only to *paint* frosted/liquid glass behind islands; nothing is
    written.  Dynamic wallpaper tools (video wallpapers) are not visible here,
    so the static Windows wallpaper is used as the glass source.
    """
    info = {"path": "", "style": "fill", "color": "#000000"}
    if not _IS_WINDOWS:
        return info
    try:
        _ensure_extra_prototypes()
        buffer = ctypes.create_unicode_buffer(1024)
        if _user32.SystemParametersInfoW(_SPI_GETDESKWALLPAPER, len(buffer), buffer, 0):
            info["path"] = buffer.value
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop") as key:
            try:
                style = str(winreg.QueryValueEx(key, "WallpaperStyle")[0]).strip()
            except OSError:
                style = "10"
            try:
                tile = str(winreg.QueryValueEx(key, "TileWallpaper")[0]).strip()
            except OSError:
                tile = "0"
        info["style"] = "tile" if tile == "1" and style == "0" else _WALLPAPER_STYLES.get(style, "fill")
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Colors") as key:
                parts = [int(part) for part in str(winreg.QueryValueEx(key, "Background")[0]).split()[:3]]
                if len(parts) == 3:
                    info["color"] = "#{0:02X}{1:02X}{2:02X}".format(*parts)
        except (OSError, ValueError):
            pass
    except Exception:
        pass
    if not info["path"] or not os.path.isfile(info["path"]):
        appdata = os.environ.get("APPDATA", "")
        transcoded = Path(appdata) / "Microsoft" / "Windows" / "Themes" / "TranscodedWallpaper"
        if appdata and transcoded.is_file():
            info["path"] = str(transcoded)
    return info


def is_window_covered(hwnd: int, tolerance: int = 12) -> bool:
    """True when another application's window fully covers *hwnd*.

    Used for “智能暂停”: videos and HTML animations stop when nobody can see
    them (e.g. a maximised or fullscreen application is in front).
    """
    if not _IS_WINDOWS:
        return False
    try:
        _ensure_extra_prototypes()
        hwnd = int(hwnd)
        foreground = _handle_value(_user32.GetForegroundWindow())
        if not foreground or foreground == hwnd or not _window_is_valid(hwnd):
            return False
        pid = wintypes.DWORD(0)
        _user32.GetWindowThreadProcessId(_as_hwnd(foreground), ctypes.byref(pid))
        if int(pid.value) == os.getpid():
            return False
        name = ctypes.create_unicode_buffer(128)
        _user32.GetClassNameW(_as_hwnd(foreground), name, 128)
        if name.value in _IGNORED_FOREGROUND_CLASSES:
            return False
        if _user32.IsIconic(_as_hwnd(foreground)) or not _user32.IsWindowVisible(_as_hwnd(foreground)):
            return False
        front = wintypes.RECT()
        mine = wintypes.RECT()
        if not _user32.GetWindowRect(_as_hwnd(foreground), ctypes.byref(front)):
            return False
        if not _user32.GetWindowRect(_as_hwnd(hwnd), ctypes.byref(mine)):
            return False
        return (
            front.left - tolerance <= mine.left
            and front.top - tolerance <= mine.top
            and front.right + tolerance >= mine.right
            and front.bottom + tolerance >= mine.bottom
        )
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 2.0 additions: monitors, shell file operations, z-order guardian helpers.
# ---------------------------------------------------------------------------

_HWND_TOP = 0
_HWND_BOTTOM = 1
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_GW_HWNDPREV = 3
_FO_MOVE = 0x0001
_FO_COPY = 0x0002
_FOF_ALLOWUNDO = 0x0040
_FOF_NOCONFIRMMKDIR = 0x0200
_DESKTOP_CLASSES = ("Progman", "WorkerW")
_twenty_prototypes_ready = False


def _ensure_twenty_prototypes() -> None:
    global _twenty_prototypes_ready
    if _twenty_prototypes_ready or not _IS_WINDOWS:
        return
    _ensure_extra_prototypes()
    _user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetWindow.restype = wintypes.HWND
    _user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.c_void_p]
    _user32.GetMonitorInfoW.restype = wintypes.BOOL
    _twenty_prototypes_ready = True


def monitor_rects() -> list[dict]:
    """Physical monitor rectangles (virtual-screen pixels) from Win32.

    Returns ``[{"device", "rect": (x, y, w, h), "work": (x, y, w, h), "primary"}]``.
    Qt reports logical sizes; the wallpaper sampler needs real pixels.
    """
    if not _IS_WINDOWS:
        return []
    try:
        _ensure_twenty_prototypes()

        class MONITORINFOEXW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                        ("dwFlags", wintypes.DWORD), ("szDevice", wintypes.WCHAR * 32)]

        proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HMONITOR, wintypes.HDC,
                                       ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)
        found: list[dict] = []

        def callback(hmonitor, _hdc, _rect, _lparam):
            info = MONITORINFOEXW()
            info.cbSize = ctypes.sizeof(MONITORINFOEXW)
            if _user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                m, w = info.rcMonitor, info.rcWork
                found.append({
                    "device": info.szDevice,
                    "rect": (m.left, m.top, m.right - m.left, m.bottom - m.top),
                    "work": (w.left, w.top, w.right - w.left, w.bottom - w.top),
                    "primary": bool(info.dwFlags & 1),
                })
            return True

        enum = _user32.EnumDisplayMonitors
        enum.argtypes = [wintypes.HDC, ctypes.c_void_p, proc_type, wintypes.LPARAM]
        enum.restype = wintypes.BOOL
        enum(None, None, proc_type(callback), 0)
        return found
    except Exception:
        return []


def shell_transfer(paths, folder, copy: bool = False, owner: int = 0) -> bool:
    """Move (or copy) files with Explorer semantics: undo, conflict dialogs.

    Off Windows a plain ``shutil`` fallback keeps tests and the demo working.
    Returns True when the operation was not aborted.
    """
    paths = [str(p) for p in paths if str(p)]
    folder = str(folder)
    if not paths or not folder:
        return False
    if not _IS_WINDOWS:
        import shutil
        ok = True
        for path in paths:
            try:
                target = Path(folder) / Path(path).name
                if target.exists():
                    ok = False
                    continue
                if copy:
                    if Path(path).is_dir():
                        shutil.copytree(path, target)
                    else:
                        shutil.copy2(path, target)
                else:
                    shutil.move(path, str(target))
            except OSError:
                ok = False
        return ok
    try:
        class SHFILEOPSTRUCTW(ctypes.Structure):
            _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", ctypes.c_void_p),
                        ("pTo", ctypes.c_void_p), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                        ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

        source = "\0".join(os.path.normpath(p) for p in paths) + "\0"
        target = os.path.normpath(folder) + "\0"
        source_buffer = ctypes.create_unicode_buffer(source, len(source) + 1)
        target_buffer = ctypes.create_unicode_buffer(target, len(target) + 1)
        op = SHFILEOPSTRUCTW()
        op.hwnd = _as_hwnd(owner)
        op.wFunc = _FO_COPY if copy else _FO_MOVE
        op.pFrom = ctypes.addressof(source_buffer)
        op.pTo = ctypes.addressof(target_buffer)
        op.fFlags = _FOF_ALLOWUNDO | _FOF_NOCONFIRMMKDIR
        shell32 = ctypes.WinDLL("shell32")
        shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
        shell32.SHFileOperationW.restype = ctypes.c_int
        result = shell32.SHFileOperationW(ctypes.byref(op))
        return result == 0 and not op.fAnyOperationsAborted
    except Exception:
        return False


def shell_move(paths, folder) -> bool:
    return shell_transfer(paths, folder, copy=False)


def window_class(hwnd: int) -> str:
    if not _IS_WINDOWS or not hwnd:
        return ""
    try:
        _ensure_extra_prototypes()
        name = ctypes.create_unicode_buffer(128)
        _user32.GetClassNameW(_as_hwnd(hwnd), name, 128)
        return name.value
    except Exception:
        return ""


def foreground_window() -> int:
    if not _IS_WINDOWS:
        return 0
    try:
        _ensure_extra_prototypes()
        return _handle_value(_user32.GetForegroundWindow())
    except Exception:
        return 0


def foreground_is_desktop() -> bool:
    """The desktop itself (Progman/WorkerW) is the active window (Win+D…)."""
    return window_class(foreground_window()) in _DESKTOP_CLASSES


def desktop_above(hwnd: int, limit: int = 4096) -> bool:
    """True when a visible desktop window sits above ``hwnd`` in Z order.

    That is what “显示桌面” (Win+D) does: Explorer raises the desktop over
    every normal window, including our bottom-most layer windows.
    """
    if not _IS_WINDOWS or not _window_is_valid(hwnd):
        return False
    try:
        _ensure_twenty_prototypes()
        current = _handle_value(_user32.GetWindow(_as_hwnd(hwnd), _GW_HWNDPREV))
        steps = 0
        while current and steps < limit:
            if _user32.IsWindowVisible(_as_hwnd(current)) and window_class(current) in _DESKTOP_CLASSES:
                if _handle_value(_user32.FindWindowExW(_as_hwnd(current), _as_hwnd(0), "SHELLDLL_DefView", None)):
                    return True
            current = _handle_value(_user32.GetWindow(_as_hwnd(current), _GW_HWNDPREV))
            steps += 1
    except Exception:
        return False
    return False


def set_window_z(hwnd: int, where: str) -> bool:
    """``where``: bottom | top | topmost | notopmost (never activates)."""
    if not _IS_WINDOWS or not _window_is_valid(hwnd):
        return False
    insert = {"bottom": _HWND_BOTTOM, "top": _HWND_TOP, "topmost": _HWND_TOPMOST,
              "notopmost": _HWND_NOTOPMOST}.get(where, _HWND_BOTTOM)
    try:
        return bool(_user32.SetWindowPos(_as_hwnd(hwnd), _as_hwnd(insert), 0, 0, 0, 0,
                                         _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE))
    except Exception:
        return False


def window_visible(hwnd: int) -> bool:
    if not _IS_WINDOWS:
        return True
    try:
        return bool(_window_is_valid(hwnd) and _user32.IsWindowVisible(_as_hwnd(hwnd)))
    except Exception:
        return False


def set_window_region(hwnd: int, x: int, y: int, width: int, height: int,
                      radius: int = 0, scale: float = 1.0) -> bool:
    """Clip a window to one rounded rectangle, in device pixels (``scale`` = DPR).

    Popup windows (bar panels, confirmation cards, notices) are sized to their card
    plus a transparent margin for the drop shadow.  Unpainted margin still belongs to
    the window for Win32 hit-testing, so it swallows clicks aimed at whatever it
    covers: the dynamic bar sits exactly in that margin, and its buttons stopped
    responding while a panel was open (the "+" never closed the panel).  A window
    region removes the margin from hit-testing; the trade-off is that the shadow,
    which is painted in that margin, is clipped with it.

    Coordinates are the window's logical pixels; GDI regions are half-open, so the
    far edge gets +1.  Region ``False`` when the rectangle is degenerate, so a
    collapsed card cannot eat input.
    """
    if not _IS_WINDOWS or not _window_is_valid(hwnd):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        factor = float(scale) if scale and scale > 0 else 1.0
        left = int(round(x * factor))
        top = int(round(y * factor))
        right = int(round((x + max(0, width)) * factor)) + 1
        bottom = int(round((y + max(0, height)) * factor)) + 1
        if right - left < 1 or bottom - top < 1:
            return False
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
        gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
        gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL
        _user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
        _user32.SetWindowRgn.restype = ctypes.c_int
        ellipse = int(round(max(0, radius) * 2 * factor))
        region = gdi32.CreateRoundRectRgn(left, top, right, bottom, ellipse, ellipse)
        if not region:
            return False
        # SetWindowRgn owns the region on success; only delete it when we failed.
        if not _user32.SetWindowRgn(_as_hwnd(hwnd), region, True):
            gdi32.DeleteObject(wintypes.HGDIOBJ(region))
            return False
        return True
    except (TypeError, ValueError, OverflowError, OSError, AttributeError):
        return False


def desktop_list_view() -> int:
    return _find_desktop_windows().list_view if _IS_WINDOWS else 0


def desktop_selected_count() -> int:
    """LVM_GETSELECTEDCOUNT of Explorer's icon view (no pointers: safe cross-process)."""
    view = desktop_list_view()
    if not view:
        return -1
    result = _DWORD_PTR(0)
    try:
        ok = _user32.SendMessageTimeoutW(_as_hwnd(view), 0x1000 + 50, 0, 0, _SMTO_ABORTIFHUNG, 200,
                                         ctypes.byref(result))
        return int(result.value) if ok else -1
    except Exception:
        return -1


def window_from_cursor_class() -> tuple[int, str, str]:
    """(hwnd, class, parent class) of the window under the cursor."""
    if not _IS_WINDOWS:
        return (0, "", "")
    try:
        point = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(point))
        _user32.WindowFromPoint.argtypes = [wintypes.POINT]
        _user32.WindowFromPoint.restype = wintypes.HWND
        hwnd = _handle_value(_user32.WindowFromPoint(point))
        parent = _handle_value(_user32.GetParent(_as_hwnd(hwnd))) if hwnd else 0
        return (hwnd, window_class(hwnd), window_class(parent))
    except Exception:
        return (0, "", "")


def double_click_metrics() -> tuple[int, int, int]:
    """(milliseconds, max dx, max dy) used by Windows for a double click."""
    if not _IS_WINDOWS:
        return (500, 4, 4)
    try:
        time_ms = int(ctypes.windll.user32.GetDoubleClickTime())
        return (time_ms, int(_user32.GetSystemMetrics(36)), int(_user32.GetSystemMetrics(37)))
    except Exception:
        return (500, 4, 4)


def force_foreground(hwnd: int) -> bool:
    """Bring one of our own windows (settings, tray menu) to the foreground."""
    if not _IS_WINDOWS or not _window_is_valid(hwnd):
        return False
    try:
        _ensure_extra_prototypes()
        kernel32 = ctypes.windll.kernel32
        _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
        _user32.AttachThreadInput.restype = wintypes.BOOL
        _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        _user32.SetForegroundWindow.restype = wintypes.BOOL
        _user32.BringWindowToTop.argtypes = [wintypes.HWND]
        _user32.BringWindowToTop.restype = wintypes.BOOL
        foreground = _user32.GetForegroundWindow()
        mine = int(kernel32.GetCurrentThreadId())
        theirs = int(_user32.GetWindowThreadProcessId(foreground, None)) if foreground else 0
        attached = bool(theirs and theirs != mine and _user32.AttachThreadInput(theirs, mine, True))
        try:
            _user32.BringWindowToTop(_as_hwnd(hwnd))
            ok = bool(_user32.SetForegroundWindow(_as_hwnd(hwnd)))
        finally:
            if attached:
                _user32.AttachThreadInput(theirs, mine, False)
        return ok
    except Exception:
        return False


def set_title_bar(hwnd: int, dark: bool, caption: str = "", text: str = "") -> bool:
    """Match a normal window's title bar to the theme (Windows 10 2004+ dark mode,
    Windows 11 caption / text colours; silently ignored where unsupported)."""
    if not _IS_WINDOWS or not _window_is_valid(hwnd):
        return False
    try:
        dwmapi = ctypes.windll.dwmapi
        value = ctypes.c_int(1 if dark else 0)
        ok = dwmapi.DwmSetWindowAttribute(_as_hwnd(hwnd), 20, ctypes.byref(value), ctypes.sizeof(value)) == 0
        if not ok:  # builds before 18985 used attribute 19
            ok = dwmapi.DwmSetWindowAttribute(_as_hwnd(hwnd), 19, ctypes.byref(value), ctypes.sizeof(value)) == 0

        def colorref(name: str):
            name = name.lstrip("#")
            if len(name) != 6:
                return None
            r, g, b = int(name[0:2], 16), int(name[2:4], 16), int(name[4:6], 16)
            return ctypes.c_uint(r | (g << 8) | (b << 16))

        for attribute, color in ((35, caption), (36, text)):
            ref = colorref(color) if color else None
            if ref is not None:
                dwmapi.DwmSetWindowAttribute(_as_hwnd(hwnd), attribute, ctypes.byref(ref), ctypes.sizeof(ref))
        return ok
    except Exception:
        return False


# --- memory (2.0.1) ----------------------------------------------------------------------
def trim_working_set() -> bool:
    """Hand the idle working set back to Windows (pages fault back in on demand).

    Same idea as DeskBox's "compress memory when idle": only called when nothing is
    happening (after startup settles, after the settings window closed, after hiding).
    """
    if not _IS_WINDOWS:
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.SetProcessWorkingSetSize.argtypes = [wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t]
        kernel32.SetProcessWorkingSetSize.restype = wintypes.BOOL
        minus_one = ctypes.c_size_t(-1).value
        return bool(kernel32.SetProcessWorkingSetSize(kernel32.GetCurrentProcess(), minus_one, minus_one))
    except Exception:
        return False


if _IS_WINDOWS:
    class _PROCESS_MEMORY_COUNTERS_EX2(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
            ("PrivateWorkingSetSize", ctypes.c_size_t),
            ("SharedCommitUsage", ctypes.c_ulonglong),
        ]

    class _PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]


def _process_private_ws(kernel32, handle) -> int:
    """Private working set (what Task Manager's "Memory" column shows), bytes."""
    counters = _PROCESS_MEMORY_COUNTERS_EX2()
    counters.cb = ctypes.sizeof(counters)
    fn = kernel32.K32GetProcessMemoryInfo
    fn.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD]
    fn.restype = wintypes.BOOL
    if fn(handle, ctypes.byref(counters), counters.cb):
        return int(counters.PrivateWorkingSetSize or counters.WorkingSetSize)
    # Older Windows 10 builds only know the shorter structure: fall back to the working set.
    counters.cb = ctypes.sizeof(counters) - ctypes.sizeof(ctypes.c_size_t) - ctypes.sizeof(ctypes.c_ulonglong)
    if fn(handle, ctypes.byref(counters), counters.cb):
        return int(counters.WorkingSetSize)
    return 0


def memory_usage() -> dict:
    """{"self": bytes, "web": bytes, "web_count": n} - DeskIsle and its WebView2 helpers."""
    result = {"self": 0, "web": 0, "web_count": 0}
    if not _IS_WINDOWS:
        return result
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.GetCurrentProcessId.restype = wintypes.DWORD
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        kernel32.Process32FirstW.restype = wintypes.BOOL
        kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
        kernel32.Process32NextW.restype = wintypes.BOOL
        result["self"] = _process_private_ws(kernel32, kernel32.GetCurrentProcess())
        # Descendants (WebView2 browser + renderer + GPU processes).
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)  # TH32CS_SNAPPROCESS
        if not snapshot or snapshot == wintypes.HANDLE(-1).value:
            return result
        parents: dict[int, int] = {}
        names: dict[int, str] = {}
        try:
            entry = _PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(entry)
            ok = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while ok:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                names[int(entry.th32ProcessID)] = entry.szExeFile.lower()
                ok = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            kernel32.CloseHandle(snapshot)
        mine = int(kernel32.GetCurrentProcessId())
        family = {mine}
        changed = True
        while changed:  # tiny tree, a few passes at most
            changed = False
            for pid, parent in parents.items():
                if parent in family and pid not in family and pid != parent:
                    family.add(pid)
                    changed = True
        for pid in family - {mine}:
            if "webview2" not in names.get(pid, ""):
                continue
            handle = kernel32.OpenProcess(0x1000 | 0x0010, False, pid)  # QUERY_LIMITED | VM_READ
            if not handle:
                continue
            try:
                result["web"] += _process_private_ws(kernel32, handle)
                result["web_count"] += 1
            finally:
                kernel32.CloseHandle(handle)
    except Exception:
        pass
    return result


def message_box(text: str, title: str = "DeskIsle") -> None:
    """Last-resort error report (before any Qt window exists)."""
    if _IS_WINDOWS:
        try:
            ctypes.windll.user32.MessageBoxW(None, str(text), str(title), 0x10)
            return
        except Exception:
            pass
    print("{0}: {1}".format(title, text), file=sys.stderr)


class DesktopHost:
    """Convenience owner for the native state associated with one HWND."""

    def __init__(self, hwnd: int = 0) -> None:
        self.hwnd = int(hwnd)

    def _bind(self, hwnd: int | None = None) -> int:
        if hwnd is not None:
            self.hwnd = int(hwnd)
        return self.hwnd

    def attach(self, hwnd: int | None = None) -> bool:
        return attach_to_desktop(self._bind(hwnd))

    def detach(self, hwnd: int | None = None) -> None:
        detach_from_desktop(self._bind(hwnd))

    def set_focus_overlay(self, *args) -> None:
        if len(args) == 1:
            enabled = bool(args[0])
        elif len(args) == 2:
            self._bind(int(args[0]))
            enabled = bool(args[1])
        else:
            raise TypeError("set_focus_overlay expects enabled or hwnd, enabled")
        set_focus_overlay(self.hwnd, enabled)

    def set_no_activate(self, *args) -> bool:
        if len(args) == 1:
            enabled = bool(args[0])
        elif len(args) == 2:
            self._bind(int(args[0]))
            enabled = bool(args[1])
        else:
            raise TypeError("set_no_activate expects enabled or hwnd, enabled")
        return set_window_no_activate(self.hwnd, enabled)

    def register_hotkey(self, *args) -> bool:
        if len(args) == 3:
            hotkey_id, modifiers, vk = args
        elif len(args) == 4:
            self._bind(int(args[0]))
            hotkey_id, modifiers, vk = args[1:]
        else:
            raise TypeError("register_hotkey expects id/modifiers/vk or hwnd/id/modifiers/vk")
        return register_hotkey(self.hwnd, int(hotkey_id), int(modifiers), int(vk))

    def unregister_hotkey(self, hotkey_id: int) -> bool:
        return unregister_hotkey(self.hwnd, hotkey_id)

    def show_native_icons(self, show: bool) -> bool:
        return show_native_desktop_icons(show)

    def set_startup(self, enabled: bool) -> bool:
        if getattr(sys, 'frozen', False):
            return add_to_startup(sys.executable, enabled)
        pythonw = Path(sys.executable).with_name('pythonw.exe')
        executable = str(pythonw) if pythonw.exists() else sys.executable
        return add_to_startup(executable, enabled, [str(Path(__file__).resolve().parents[1] / 'main.py')])

    def cleanup(self, hwnd: int | None = None) -> None:
        self._bind(hwnd)
        for hotkey_id in list((0x5151, 0x5152, 0x5153, 0x5154, 0x5155)):
            unregister_hotkey(self.hwnd, hotkey_id)
        restore_native_desktop_icons()
        self.detach()

    def close(self) -> None:
        self.detach()

    def __enter__(self) -> "DesktopHost":
        self.attach()
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()


# Best-effort cleanup on ordinary interpreter shutdown.  A hard kill cannot run
# this hook, but Explorer normally recreates the icon ListView as visible after
# its own restart because no persistent registry preference was modified.
atexit.register(restore_native_desktop_icons)


__all__ = [
    "DesktopHost",
    "MOD_ALT",
    "MOD_CONTROL",
    "MOD_NOREPEAT",
    "MOD_SHIFT",
    "MOD_WIN",
    "STARTUP_VALUE_NAME",
    "VK_BACK",
    "VK_CONTROL",
    "VK_DELETE",
    "VK_DOWN",
    "VK_END",
    "VK_ESCAPE",
    "VK_F1",
    "VK_F2",
    "VK_F3",
    "VK_F4",
    "VK_F5",
    "VK_F6",
    "VK_F7",
    "VK_F8",
    "VK_F9",
    "VK_F10",
    "VK_F11",
    "VK_F12",
    "VK_HOME",
    "VK_INSERT",
    "VK_LEFT",
    "VK_MENU",
    "VK_NEXT",
    "VK_PRIOR",
    "VK_RETURN",
    "VK_RIGHT",
    "VK_SHIFT",
    "VK_SPACE",
    "VK_TAB",
    "VK_UP",
    "add_to_startup",
    "desktop_above",
    "desktop_selected_count",
    "double_click_metrics",
    "force_foreground",
    "foreground_is_desktop",
    "foreground_window",
    "memory_usage",
    "message_box",
    "monitor_rects",
    "set_window_region",
    "set_window_z",
    "trim_working_set",
    "shell_move",
    "shell_transfer",
    "window_class",
    "window_visible",
    "attach_to_desktop",
    "detach_from_desktop",
    "is_windows",
    "register_hotkey",
    "restore_native_desktop_icons",
    "set_focus_overlay",
    "show_native_desktop_icons",
    "unregister_hotkey",
    "virtual_screen_geometry",
] + [f"VK_{char}" for char in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"]

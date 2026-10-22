"""Windows glue: native messages, global hotkeys, the guardian (watchdog) and the tray.

Everything here degrades to a no-op off Windows so the demo and the tests run
anywhere.
"""

from __future__ import annotations

import logging
import sys
import threading
import time

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QPoint, QTimer, Signal
from PySide6.QtGui import QCursor, QIcon
from PySide6.QtWidgets import QSystemTrayIcon

from .. import native_win

log = logging.getLogger("deskisle.system")
IS_WINDOWS = sys.platform == "win32"

WM_SETTINGCHANGE = 0x001A
WM_DISPLAYCHANGE = 0x007E
WM_COPYDATA = 0x004A
WM_HOTKEY = 0x0312
WM_POWERBROADCAST = 0x0218
WM_WTSSESSION_CHANGE = 0x02B1
SPI_SETDESKWALLPAPER = 0x0014
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMEAUTOMATIC = 0x0012
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8

MODS = native_win.MOD_CONTROL | native_win.MOD_ALT | native_win.MOD_NOREPEAT
# id, virtual key, menu action, label (shown in settings / AGENTS.md)
HOTKEYS = (
    (0xD101, native_win.VK_SPACE, "view.focus", "Ctrl+Alt+Space", "聚焦层（临时置顶所有收纳岛）"),
    (0xD102, native_win.VK_H, "view.hide", "Ctrl+Alt+H", "显示 / 隐藏桌面内容"),
    (0xD103, native_win.VK_LEFT, "page.prev", "Ctrl+Alt+←", "上一个预设"),
    (0xD104, native_win.VK_RIGHT, "page.next", "Ctrl+Alt+→", "下一个预设"),
    (0xD105, native_win.VK_Z, "layout.undo", "Ctrl+Alt+Z", "撤销排布"),
    (0xD106, native_win.VK_F, "search", "Ctrl+Alt+F", "搜索（Everything）"),
)


def hotkey_table() -> list[dict]:
    return [{"keys": keys, "action": action, "label": label} for _i, _vk, action, keys, label in HOTKEYS]


# ---------------------------------------------------------------------------------------------
class NativeEvents(QAbstractNativeEventFilter):
    """Sees every Win32 message Qt receives (window procedures + thread queue)."""

    def __init__(self, owner) -> None:
        super().__init__()
        self.owner = owner
        self.taskbar_created = 0
        if IS_WINDOWS:
            import ctypes

            self.taskbar_created = int(ctypes.windll.user32.RegisterWindowMessageW("TaskbarCreated"))

    def nativeEventFilter(self, event_type, message):  # noqa: N802 - Qt API
        if not IS_WINDOWS:
            return False, 0
        try:
            name = bytes(event_type)
        except TypeError:
            name = b""
        if name not in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            return False, 0
        try:
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
            kind = int(msg.message)
            if kind == WM_HOTKEY:
                self.owner.on_hotkey(int(msg.wParam))
                return True, 0
            if kind == WM_COPYDATA:
                if self.owner.on_copydata(int(msg.hWnd or 0), int(msg.wParam or 0), int(msg.lParam or 0)):
                    return True, 1
            elif kind == WM_SETTINGCHANGE:
                self.owner.on_setting_change(int(msg.wParam or 0), int(msg.lParam or 0))
            elif kind == WM_DISPLAYCHANGE:
                self.owner.on_display_change()
            elif kind == WM_WTSSESSION_CHANGE:
                self.owner.on_session(int(msg.wParam or 0))
            elif kind == WM_POWERBROADCAST:
                self.owner.on_power(int(msg.wParam or 0))
            elif self.taskbar_created and kind == self.taskbar_created:
                self.owner.on_explorer_restarted()
        except Exception:  # pragma: no cover - never let a filter exception kill the loop
            log.exception("native event")
        return False, 0


def setting_name(lparam: int) -> str:
    if not IS_WINDOWS or not lparam:
        return ""
    try:
        import ctypes

        return ctypes.wstring_at(lparam, 64).split("\0", 1)[0]
    except Exception:
        return ""


# ---------------------------------------------------------------------------------------------
class Hotkeys(QObject):
    triggered = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.registered: list[int] = []
        self.failed: list[str] = []

    def enable(self, on: bool) -> list[str]:
        self.disable()
        if not on or not IS_WINDOWS:
            return []
        for hid, vk, _action, keys, _label in HOTKEYS:
            # hwnd 0: WM_HOTKEY goes to the GUI thread queue (seen by NativeEvents).
            if native_win.register_hotkey(0, hid, MODS, vk):
                self.registered.append(hid)
            else:
                self.failed.append(keys)
        return list(self.failed)

    def disable(self) -> None:
        for hid in self.registered:
            native_win.unregister_hotkey(0, hid)
        self.registered = []
        self.failed = []

    def handle(self, hid: int) -> bool:
        for known, _vk, action, _keys, _label in HOTKEYS:
            if known == hid:
                self.triggered.emit(action)
                return True
        return False


# ---------------------------------------------------------------------------------------------
class ForegroundHook(QObject):
    """EVENT_SYSTEM_FOREGROUND without polling (out-of-context WinEvent hook)."""

    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._hook = None
        self._proc = None
        if not IS_WINDOWS:
            return
        try:
            import ctypes
            from ctypes import wintypes

            proc_type = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.DWORD, wintypes.HWND, wintypes.LONG,
                                           wintypes.LONG, wintypes.DWORD, wintypes.DWORD)

            def callback(_hook, _event, _hwnd, _obj, _child, _thread, _time):
                self.changed.emit()

            self._proc = proc_type(callback)
            user32 = ctypes.windll.user32
            user32.SetWinEventHook.restype = wintypes.HANDLE
            user32.SetWinEventHook.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, proc_type,
                                               wintypes.DWORD, wintypes.DWORD, wintypes.DWORD]
            self._hook = user32.SetWinEventHook(3, 3, None, self._proc, 0, 0, 0)  # FOREGROUND, OUTOFCONTEXT
        except Exception:
            log.exception("foreground hook")
            self._hook = None

    def close(self) -> None:
        if self._hook and IS_WINDOWS:
            import ctypes

            ctypes.windll.user32.UnhookWinEvent(self._hook)
        self._hook = None


class DesktopClickHook(QObject):
    """Double click on Explorer's *blank* desktop (only needed when the native
    icons are shown, otherwise our own layer receives the clicks).

    A low-level mouse hook runs on its own thread with its own message loop so a
    busy GUI thread can never slow the system cursor down.  Blank-ness is checked
    afterwards with LVM_GETSELECTEDCOUNT (a double click on an icon selects it).
    """

    doubleClicked = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._thread: threading.Thread | None = None
        self._thread_id = 0

    def start(self) -> None:
        if not IS_WINDOWS or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="deskisle-click-hook", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None or not IS_WINDOWS:
            return
        import ctypes

        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)  # WM_QUIT
        self._thread = None
        self._thread_id = 0

    def _run(self) -> None:  # pragma: no cover - Windows only
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._thread_id = int(kernel32.GetCurrentThreadId())
        lresult = ctypes.c_ssize_t
        proc_type = ctypes.WINFUNCTYPE(lresult, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("pt", wintypes.POINT), ("mouseData", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

        user32.CallNextHookEx.restype = lresult
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        last = {"t": 0, "x": 0, "y": 0}
        limit_ms, dx, dy = native_win.double_click_metrics()

        def callback(code, wparam, lparam):
            if code >= 0 and wparam == 0x0201:  # WM_LBUTTONDOWN
                info = ctypes.cast(lparam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                t, x, y = int(info.time), int(info.pt.x), int(info.pt.y)
                if t - last["t"] <= limit_ms and abs(x - last["x"]) <= dx and abs(y - last["y"]) <= dy:
                    last["t"] = 0
                    self.doubleClicked.emit()   # queued to the GUI thread
                else:
                    last.update(t=t, x=x, y=y)
            return user32.CallNextHookEx(None, code, wparam, lparam)

        proc = proc_type(callback)
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, proc_type, wintypes.HINSTANCE, wintypes.DWORD]
        hook = user32.SetWindowsHookExW(14, proc, kernel32.GetModuleHandleW(None), 0)  # WH_MOUSE_LL
        if not hook:
            return
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        user32.UnhookWindowsHookEx(hook)


# ---------------------------------------------------------------------------------------------
class Guardian(QObject):
    """Watchdog for the desktop layers.

    * keeps every layer window visible, at the bottom of the Z order and on its monitor;
    * “显示桌面” (Win+D) raises Explorer's desktop over all windows - the layers are lifted
      above it while the desktop is active and put back afterwards;
    * smart pause: when other applications cover every layer the live wallpaper sampler
      and widget timers rest;
    * re-applies the native icon state after Explorer restarts.
    """

    pausedChanged = Signal(bool)
    foregroundChanged = Signal()

    def __init__(self, app, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self._lifted = False
        self._paused = False
        self._timer = QTimer(self)
        self._timer.setInterval(1500)
        self._timer.timeout.connect(self.tick)
        self._fg = ForegroundHook(self)
        self._fg.changed.connect(self._foreground_changed)
        self._soon = QTimer(self)
        self._soon.setSingleShot(True)
        self._soon.setInterval(120)
        self._soon.timeout.connect(self.tick)

    def start(self) -> None:
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()
        self._fg.close()

    def _foreground_changed(self) -> None:
        self.foregroundChanged.emit()
        self._soon.start()

    @property
    def paused(self) -> bool:
        return self._paused

    def tick(self) -> None:
        desk = self.app.desk
        layers = self.app.layers
        if layers is None or desk is None:
            return
        windows = list(layers.windows.values())
        watchdog = bool(desk.preferences.watchdog)
        for window in windows:
            try:
                if watchdog and not window.isVisible():
                    log.info("guardian: layer window was hidden - showing it again")
                    window.show()
            except RuntimeError:
                continue
        if not IS_WINDOWS or desk.demo:
            return
        hwnds = []
        for window in windows:
            try:
                hwnds.append(int(window.winId()))
            except RuntimeError:
                pass
        if watchdog and not desk.focusMode:
            desktop_active = native_win.foreground_is_desktop()
            if desktop_active and any(native_win.desktop_above(h) for h in hwnds):
                for h in hwnds:
                    native_win.set_window_z(h, "top")
                self._lifted = True
            elif self._lifted and not desktop_active:
                for h in hwnds:
                    native_win.set_window_z(h, "bottom")
                self._lifted = False
        paused = bool(desk.preferences.smart_pause) and bool(hwnds) and all(
            native_win.is_window_covered(h) for h in hwnds)
        if paused != self._paused:
            self._paused = paused
            self.pausedChanged.emit(paused)


# ---------------------------------------------------------------------------------------------
class Tray(QObject):
    menuRequested = Signal(QPoint)
    toggleRequested = Signal()
    settingsRequested = Signal()

    def __init__(self, icon: QIcon, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.icon = QSystemTrayIcon(icon, self)
        self.icon.setToolTip("桌屿 DeskIsle")
        self.icon.activated.connect(self._activated)
        self._last_click = 0.0

    def show(self) -> None:
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.icon.show()

    def hide(self) -> None:
        self.icon.hide()

    def message(self, title: str, text: str, msecs: int = 3000) -> None:
        if self.icon.isVisible():
            self.icon.showMessage(title, text, QSystemTrayIcon.MessageIcon.Information, msecs)

    def _activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Context:
            self.menuRequested.emit(QCursor.pos())
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._last_click = time.monotonic()   # cancels the pending single click
            self.settingsRequested.emit()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            # Single click: toggle (delayed so a double click does not toggle twice).
            now = time.monotonic()
            self._last_click = now
            QTimer.singleShot(260, lambda: self._single(now))
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.menuRequested.emit(QCursor.pos())

    def _single(self, stamp: float) -> None:
        if stamp == self._last_click:
            self.toggleRequested.emit()


__all__ = ["DesktopClickHook", "ForegroundHook", "Guardian", "HOTKEYS", "Hotkeys", "NativeEvents", "Tray",
           "hotkey_table", "setting_name"]

"""Out-of-process watchdog (C): restarts DeskIsle after a *crash*.

Deliberately imports nothing from Qt so it costs only a few MB.  The app writes
``running.marker`` on start and deletes it on a clean exit; the watchdog waits
for the process, and only when the marker is still there *and* the exit code is
a crash code (NTSTATUS exception / abort) it restores Explorer's icons and starts
DeskIsle again - at most three times in ten minutes.  “结束任务” in Task Manager
(exit code 1) is respected and never restarted.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

MARKER = "running.marker"
HISTORY = "watchdog.json"
MAX_RESTARTS = 3
WINDOW_S = 600


def is_crash_code(code: int) -> bool:
    code &= 0xFFFFFFFF
    return code >= 0xC0000000 or code in (3, 0x80000003, 0xE06D7363)


def launch_command(extra=()) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *extra]
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parents[1] / "main.py"
    return [str(pythonw if pythonw.exists() else exe), str(main), *extra]


def spawn(data_root: Path) -> bool:
    """Start a detached watchdog for the current process (Windows only)."""
    if sys.platform != "win32":
        return False
    args = launch_command(["--watchdog", str(os.getpid()), "--data-dir", str(data_root)])
    try:
        subprocess.Popen(args, creationflags=0x00000008 | 0x00000200 | 0x08000000, close_fds=True)
        return True
    except OSError:
        return False


def write_marker(data_root: Path) -> None:
    try:
        data_root.mkdir(parents=True, exist_ok=True)
        (data_root / MARKER).write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def clear_marker(data_root: Path) -> None:
    try:
        (data_root / MARKER).unlink()
    except OSError:
        pass


def previous_run_crashed(data_root: Path) -> bool:
    return (data_root / MARKER).exists()


def _wait(pid: int) -> int | None:  # pragma: no cover - Windows only
    import ctypes

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(0x00100000 | 0x1000, False, int(pid))  # SYNCHRONIZE | QUERY_LIMITED
    if not handle:
        return None
    try:
        kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
        code = ctypes.c_ulong(0)
        kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        return int(code.value)
    finally:
        kernel32.CloseHandle(handle)


def run(pid: int, data_root: Path) -> int:  # pragma: no cover - Windows only
    code = _wait(pid)
    if code is None:
        return 0
    marker = data_root / MARKER
    if not marker.exists() or not is_crash_code(code):
        return 0
    try:
        from . import native_win

        native_win.show_native_desktop_icons(True)
    except Exception:
        pass
    history_path = data_root / HISTORY
    try:
        history = [float(t) for t in json.loads(history_path.read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        history = []
    now = time.time()
    history = [t for t in history if now - t < WINDOW_S]
    try:
        with open(data_root / "crash.log", "a", encoding="utf-8") as stream:
            stream.write("\n[{0}] watchdog: DeskIsle exited with 0x{1:08X}\n".format(
                time.strftime("%Y-%m-%d %H:%M:%S"), code & 0xFFFFFFFF))
    except OSError:
        pass
    if len(history) >= MAX_RESTARTS:
        try:
            marker.unlink()
        except OSError:
            pass
        from .native_win import message_box

        message_box("桌屿在 10 分钟内多次异常退出，已停止自动重启。\n\n日志位于：{0}".format(data_root / "crash.log"),
                    "桌屿 DeskIsle")
        return 1
    history.append(now)
    try:
        history_path.write_text(json.dumps(history), encoding="utf-8")
    except OSError:
        pass
    time.sleep(1.5)
    try:
        subprocess.Popen(launch_command(["--recovered", "--data-dir", str(data_root)]),
                         creationflags=0x00000008 | 0x00000200, close_fds=True)
    except OSError:
        return 1
    return 0


__all__ = ["clear_marker", "is_crash_code", "launch_command", "previous_run_crashed", "run", "spawn",
           "write_marker"]

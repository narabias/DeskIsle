"""Pure-Python client of the DeskIsle agent pipe (no Qt import).

Protocol: one JSON object per line in both directions::

    -> {"id": 1, "cmd": "island.list", "args": {}}
    <- {"id": 1, "ok": true, "result": {...}}
    <- {"id": 2, "ok": false, "error": {"code": "not_found", "message": "..."}}

Windows: named pipe ``\\\\.\\pipe\\deskisle-<user>``; elsewhere a Unix socket in
the temp folder.  The running app writes ``<data>/agent.json``
(``{"pipe", "pid", "version", "protocol"}``) so other tools can find it.
"""

from __future__ import annotations

import itertools
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"
_ids = itertools.count(1)


class AgentUnavailable(ConnectionError):
    """DeskIsle is not running (or its agent interface is switched off)."""


class AgentCommandError(RuntimeError):
    def __init__(self, code: str, message: str, payload: dict | None = None) -> None:
        super().__init__("{0}: {1}".format(code, message))
        self.code = code
        self.message = message
        self.payload = payload or {}


def user_tag() -> str:
    try:
        import getpass

        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = os.environ.get("USERNAME") or os.environ.get("USER") or "user"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", user)[:40] or "user"


def pipe_name(demo: bool = False) -> str:
    # DESKISLE_PIPE_NAME: isolated instances (the packaged self-test) never collide with a real one.
    override = re.sub(r"[^A-Za-z0-9_.-]+", "_", os.environ.get("DESKISLE_PIPE_NAME", ""))[:80]
    return override or ("deskisle-demo-" if demo else "deskisle-") + user_tag()


def default_root(demo: bool = False) -> Path:
    if demo:
        return Path(tempfile.gettempdir()) / "DeskIsleDemo"
    configured = os.environ.get("DESKISLE_DATA_DIR")
    if configured:
        return Path(configured).expanduser()
    local = os.environ.get("LOCALAPPDATA")
    return Path(local) / "DeskIsle" if local else Path.home() / "AppData" / "Local" / "DeskIsle"


def discover(data_dir: str | os.PathLike | None = None, demo: bool = False) -> str:
    """Full pipe / socket path of the running instance."""
    root = Path(data_dir).expanduser() if data_dir else default_root(demo)
    try:
        info = json.loads((root / "agent.json").read_text(encoding="utf-8"))
        if isinstance(info, dict) and info.get("pipe"):
            return str(info["pipe"])
    except (OSError, ValueError):
        pass
    name = pipe_name(demo)
    return "\\\\.\\pipe\\" + name if IS_WINDOWS else os.path.join(tempfile.gettempdir(), name)


def _quoted(path) -> str:
    text = str(path)
    return '"{0}"'.format(text) if any(ch in text for ch in " \t&()") else text


def path_entries() -> list[str]:
    """PATH of this process plus (Windows) the user's saved PATH.

    The installer adds the install folder to ``HKCU\\Environment\\Path``; programs
    started before that (including DeskIsle launched by the installer) still have the
    old environment, so the registry is consulted as well.
    """
    entries = os.environ.get("PATH", "").split(os.pathsep)
    if IS_WINDOWS:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                value, _kind = winreg.QueryValueEx(key, "Path")
            entries += str(value).split(";")
        except OSError:
            pass
    return [entry for entry in entries if entry.strip()]


def folder_on_path(folder, entries: list[str] | None = None) -> bool:
    target = os.path.normcase(os.path.normpath(str(folder)))
    for entry in path_entries() if entries is None else entries:
        entry = os.path.expandvars(entry.strip().strip('"'))
        if entry and os.path.normcase(os.path.normpath(entry)) == target:
            return True
    return False


def launch_info(executable=None, frozen: bool | None = None, demo: bool = False,
                entries: list[str] | None = None) -> dict:
    """How other programs start the CLI and the MCP server (Settings → AI 与扩展).

    Packaged builds ship ``deskisle-cli.exe`` (a console program) next to
    ``DeskIsle.exe``: MCP clients talk to it over stdio, which a windowed EXE cannot
    do reliably.  From source, ``python main.py --mcp`` is used.
    """
    exe = Path(executable or sys.executable)
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    extra = ["--demo"] if demo else []
    if frozen:
        cli_exe = exe.with_name("deskisle-cli.exe")
        if cli_exe.is_file():
            short = folder_on_path(cli_exe.parent, entries)
            return {"cli": ("deskisle-cli" if short else _quoted(cli_exe)) + "".join(" " + a for a in extra),
                    "cliOnPath": short, "packaged": True, "mcpCommand": str(cli_exe), "mcpArgs": extra + ["mcp"]}
        # Portable copy without the console helper: the main EXE understands both switches.
        return {"cli": _quoted(exe) + "".join(" " + a for a in extra) + " --cli", "cliOnPath": False,
                "packaged": True, "mcpCommand": str(exe), "mcpArgs": ["--mcp"] + extra}
    script = Path(__file__).resolve().parents[2] / "main.py"
    return {"cli": "python main.py" + "".join(" " + a for a in extra) + " --cli", "cliOnPath": False,
            "packaged": False, "mcpCommand": str(exe), "mcpArgs": [str(script), "--mcp"] + extra}


class Connection:
    """One connection; requests are answered in order (destructive ones may take long)."""

    def __init__(self, path: str, timeout: float = 5.0) -> None:
        self.path = path
        self._buffer = b""
        self._file = None
        self._sock = None
        deadline = time.monotonic() + max(0.5, timeout)
        if IS_WINDOWS:
            while True:
                try:
                    self._file = open(path, "r+b", buffering=0)  # noqa: SIM115 - closed in close()
                    break
                except FileNotFoundError as exc:
                    raise AgentUnavailable("DeskIsle is not running ({0})".format(path)) from exc
                except OSError as exc:      # ERROR_PIPE_BUSY: all instances in use, retry
                    if time.monotonic() > deadline:
                        raise AgentUnavailable("pipe busy: {0}".format(exc)) from exc
                    time.sleep(0.05)
        else:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            try:
                sock.connect(path)
            except OSError as exc:
                sock.close()
                raise AgentUnavailable("DeskIsle is not running ({0})".format(path)) from exc
            self._sock = sock

    def close(self) -> None:
        for handle in (self._file, self._sock):
            try:
                if handle is not None:
                    handle.close()
            except OSError:
                pass
        self._file = self._sock = None

    def __enter__(self):
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def _write(self, data: bytes) -> None:
        if self._file is not None:
            view = memoryview(data)
            while view:
                written = self._file.write(view)
                view = view[written or 0:]
        else:
            self._sock.sendall(data)

    def _read_chunk(self, timeout: float) -> bytes:
        if self._sock is not None:
            self._sock.settimeout(timeout)
            try:
                return self._sock.recv(65536)
            except socket.timeout as exc:
                raise TimeoutError("no answer from DeskIsle within {0:.0f} s".format(timeout)) from exc
        box: list = []

        def read() -> None:
            try:
                box.append(self._file.read(65536))
            except OSError as exc:
                box.append(exc)

        worker = threading.Thread(target=read, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            raise TimeoutError("no answer from DeskIsle within {0:.0f} s".format(timeout))
        if isinstance(box[0], OSError):
            raise AgentUnavailable(str(box[0]))
        return box[0]

    def request(self, cmd: str, args: dict | None = None, timeout: float = 30.0) -> dict:
        rid = next(_ids)
        line = json.dumps({"id": rid, "cmd": cmd, "args": args or {}}, ensure_ascii=False) + "\n"
        self._write(line.encode("utf-8"))
        deadline = time.monotonic() + timeout
        while True:
            while b"\n" in self._buffer:
                raw, _sep, self._buffer = self._buffer.partition(b"\n")
                if not raw.strip():
                    continue
                message = json.loads(raw.decode("utf-8"))
                if message.get("id") == rid:
                    return message
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("no answer from DeskIsle within {0:.0f} s".format(timeout))
            chunk = self._read_chunk(remaining)
            if not chunk:
                raise AgentUnavailable("DeskIsle closed the connection")
            self._buffer += chunk


def _timeout_for(cmd: str, args: dict | None, timeout: float | None) -> float:
    if timeout is not None:
        return timeout
    try:
        from .schema import BY_NAME

        if BY_NAME.get(cmd, {}).get("destructive"):
            wait = (args or {}).get("wait")
            return min(300.0, float(90 if wait is None else wait)) + 15.0
    except Exception:  # noqa: BLE001
        pass
    return 30.0


def send(request: dict, timeout: float | None = None, data_dir=None, demo: bool = False) -> dict:
    """Send ``{"cmd", "args"}`` and return the raw response ``{"id", "ok", ...}``."""
    cmd = str(request.get("cmd", ""))
    args = request.get("args") or {}
    with Connection(discover(data_dir, demo), timeout=min(5.0, timeout or 5.0)) as conn:
        return conn.request(cmd, args, _timeout_for(cmd, args, timeout))


def call(cmd: str, args: dict | None = None, *, timeout: float | None = None, data_dir=None, demo: bool = False):
    """Run a command and return its result (raises :class:`AgentCommandError`)."""
    response = send({"cmd": cmd, "args": args or {}}, timeout=timeout, data_dir=data_dir, demo=demo)
    if response.get("ok"):
        return response.get("result")
    error = response.get("error") or {}
    raise AgentCommandError(str(error.get("code", "error")), str(error.get("message", "")), error)


def is_running(data_dir=None, demo: bool = False) -> bool:
    try:
        Connection(discover(data_dir, demo), timeout=1.0).close()
        return True
    except (AgentUnavailable, OSError):
        return False


def launch_command(demo: bool = False, data_dir=None) -> list[str]:
    extra = (["--demo"] if demo else []) + (["--data-dir", str(data_dir)] if data_dir else [])
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        main = exe.with_name("DeskIsle.exe")
        return [str(main if main.exists() else exe), *extra]
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    main = Path(__file__).resolve().parents[2] / "main.py"
    return [str(pythonw if IS_WINDOWS and pythonw.exists() else exe), str(main), *extra]


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel32.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5                  # access denied: it exists
        try:
            code = wintypes.DWORD()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def running_without_agent(data_dir=None, demo: bool = False) -> bool:
    """DeskIsle runs (it holds ``instance.lock``) but its agent interface is switched off."""
    if demo:
        return False                    # demo instances take no lock
    root = Path(data_dir).expanduser() if data_dir else default_root(False)
    try:
        first = (root / "instance.lock").read_text(encoding="utf-8", errors="ignore").split("\n", 1)[0]
        pid = int(first.strip())
    except (OSError, ValueError):
        return False
    return pid != os.getpid() and _pid_alive(pid)


def ensure_running(wait: float = 20.0, demo: bool = False, data_dir=None) -> bool:
    """Start DeskIsle when it is not running (best effort); True once the pipe answers."""
    if is_running(data_dir, demo):
        return True
    if running_without_agent(data_dir, demo):
        return False                    # never start a second copy (it would only show "already running")
    try:
        flags = (0x00000008 | 0x00000200) if IS_WINDOWS else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP
        subprocess.Popen(launch_command(demo, data_dir), creationflags=flags, close_fds=True,  # noqa: S603
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=not IS_WINDOWS)
    except OSError:
        return False
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        if is_running(data_dir, demo):
            return True
        time.sleep(0.4)
    return False


__all__ = ["AgentCommandError", "AgentUnavailable", "Connection", "call", "default_root", "discover",
           "ensure_running", "folder_on_path", "is_running", "launch_command", "launch_info", "pipe_name",
           "running_without_agent", "send"]

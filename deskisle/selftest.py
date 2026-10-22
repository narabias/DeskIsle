"""Packaged-app self-test (``DeskIsle.exe --self-test report.json``).

Runs the real 2.0 application in demo mode with isolated data - it never touches
the live desktop, the user's layout or a running DeskIsle - and checks what a
broken bundle would lose first:

* every QML file compiles (QtQuick, Effects, Shapes, Multimedia, shaders),
* the layer, the settings window (all pages) and the menus build without
  JavaScript errors, and the desk actions work end to end,
* the agent pipe answers a CLI request (the same path deskisle-cli and the MCP
  bridge use),
* optional runtime pieces are present: WebView2Loader.dll, lunar calendar,
  WinRT projections (now playing, location), the native shell menu helper.

The report (JSON) and two screenshots are written next to *report_path*.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

# JavaScript errors that mean a QML file is broken (other warnings are only reported).
FATAL_QML = ("TypeError", "ReferenceError", "SyntaxError", "is not a type", "is not installed",
             "Cannot assign", "Unable to assign", "Type error", "failed to load component", "Error:")
OPTIONAL_QML = ("WebEngineSurface.qml",)          # Qt WebEngine is not bundled (Windows uses WebView2)
PAGES = ("appearance", "desktop", "widgets", "ai", "about")


@contextmanager
def _workspace(parent: Path):
    parent = parent.resolve()
    root = parent / (".selftest-" + uuid4().hex)
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        if root.resolve().is_relative_to(parent):
            shutil.rmtree(root, ignore_errors=True)


def _wait(qapp, ms: int, until=None) -> bool:
    from PySide6.QtCore import QEventLoop

    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        qapp.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 30)
        if until is not None and until():
            return True
        time.sleep(0.01)
    return until is None or bool(until())


def _bundle(report: dict) -> None:
    from . import webview2
    from .engine.layer import QML_DIR

    base = Path(__file__).resolve().parent
    shaders = sorted(p.name for p in (QML_DIR / "shaders").glob("*.qsb"))
    report["qml_dir"] = str(QML_DIR)
    report["shaders"] = len(shaders)
    assert QML_DIR.is_dir() and (QML_DIR / "Layer.qml").is_file(), "QML files are missing from the bundle"
    assert shaders, "compiled shaders (*.qsb) are missing from the bundle"
    assert (base / "agent" / "GUIDE.md").is_file(), "agent/GUIDE.md is missing"
    assert (base / "assets" / "ui" / "app-icon.png").is_file(), "app icon is missing"
    report["webview2_loader"] = webview2.loader_path().is_file()
    if os.name == "nt":
        report["webview2"] = webview2.runtime().state()
        if getattr(sys, "frozen", False):
            assert report["webview2_loader"], "WebView2Loader.dll is missing from the bundle"
    modules = {}
    for name in ("lunar_python", "PySide6.QtMultimedia", "PySide6.QtQuick", "PySide6.QtNetwork"):
        modules[name] = _importable(name)
    if os.name == "nt":
        for name in ("winrt.windows.media.control", "winrt.windows.devices.geolocation",
                     "win32com.shell.shell"):
            modules[name] = _importable(name)
    report["modules"] = modules
    if getattr(sys, "frozen", False):
        missing = [name for name, ok in modules.items() if not ok]
        assert not missing, "modules missing from the bundle: " + ", ".join(missing)


def _importable(name: str) -> bool:
    try:
        __import__(name)
        return True
    except Exception:  # noqa: BLE001 - optional runtime pieces
        return False


def _compile_qml(engine, report: dict) -> None:
    from PySide6.QtCore import QUrl
    from PySide6.QtQml import QQmlComponent

    from .engine.layer import QML_DIR

    failures = {}
    count = 0
    for path in sorted(QML_DIR.glob("*.qml")):
        if path.name.startswith("_") or path.name in OPTIONAL_QML:
            continue
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)), QQmlComponent.CompilationMode.PreferSynchronous)
        count += 1
        if component.isError():
            errors = [e.toString() for e in component.errors()]
            if not getattr(sys, "frozen", False) and all("Cannot load library" in e for e in errors):
                # development machine without e.g. the multimedia system libraries
                report.setdefault("qml_skipped", {})[path.name] = errors
                continue
            failures[path.name] = errors
    report["qml_compiled"] = count
    assert not failures, "QML does not compile: " + json.dumps(failures, ensure_ascii=False)


def _agent_roundtrip(qapp, root: Path, report: dict) -> None:
    from .agent.client import call

    result: dict = {}

    def worker() -> None:
        try:
            result["islands"] = call("island.list", {}, data_dir=root, timeout=15)
            result["state"] = call("desk.state", {}, data_dir=root, timeout=15)
        except Exception as exc:  # noqa: BLE001
            result["error"] = repr(exc)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    _wait(qapp, 20000, lambda: not thread.is_alive())
    assert "error" not in result, "agent pipe: " + result.get("error", "")
    islands = result.get("islands")
    count = len(islands.get("islands", islands)) if isinstance(islands, (dict, list)) else 0
    assert count > 0, "agent pipe returned no islands: {0!r}".format(islands)
    report["agent"] = "passed ({0} islands)".format(count)


def _native_menu(report: dict) -> None:
    if os.name != "nt":
        return
    if getattr(sys, "frozen", False):
        command = [str(Path(sys.executable).with_name("DeskIsleShellMenu.exe"))]
    else:
        command = [sys.executable, "-B", "-m", "deskisle.shell_menu"]
    payload = json.dumps({"paths": [r"C:\Windows\System32\notepad.exe"], "probe": True}).encode()
    result = subprocess.run(command, input=payload, capture_output=True, timeout=20,  # noqa: S603
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    menu = json.loads(result.stdout.decode("utf-8"))
    assert "runas" in menu.get("verbs", []), menu
    assert menu["extended_menu"]
    report["native_menu"] = "passed"


def _cli_exe(report: dict) -> None:
    if not getattr(sys, "frozen", False):
        return
    name = "deskisle-cli.exe" if sys.platform == "win32" else "deskisle-cli"
    exe = Path(sys.executable).with_name(name)
    assert exe.is_file(), name + " is missing"
    result = subprocess.run([str(exe), "--version"], capture_output=True, timeout=20,  # noqa: S603
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode == 0 and b"deskisle-cli" in result.stdout, result
    report["cli_exe"] = result.stdout.decode("utf-8", "replace").strip()


def _run_app(root: Path, report_path: Path, report: dict) -> None:
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QApplication

    from .demo import demo_state
    from .engine import app as appmod
    from .storage import StateStore

    appmod.prepare_environment()
    appmod.setup_logging(root, verbose=False)
    qapp = QApplication.instance() or QApplication([sys.argv[0]])
    qapp.setQuitOnLastWindowClosed(False)
    store = StateStore(root / "data")
    state = demo_state(root / "demo")
    app = appmod.DeskIsleApp(qapp, store, state, demo=True, root=root / "data", notes=[], recovered=False)
    warnings: list[str] = []
    try:
        app.build()
        app.engine.warnings.connect(lambda items: warnings.extend(w.toString() for w in items))
        # A service module missing from the bundle silently becomes a NullService.
        report["services"] = sorted(app.services)
        unavailable = sorted(name for name, service in app.services.items()
                             if type(service).__name__ == "NullService")
        assert not unavailable, "services failed to load: " + ", ".join(unavailable)
        _compile_qml(app.engine, report)
        app.start()
        assert _wait(qapp, 8000, lambda: bool(app.layers.windows)), "no layer window was created"
        _wait(qapp, 1500)
        window = next(iter(app.layers.windows.values()))
        image = window.grabWindow()
        assert not image.isNull(), "the layer window does not render"
        image.save(str(report_path.with_suffix(".png")))
        report["layers"] = len(app.layers.windows)

        desk = app.desk
        before = sum(len(p.islands) for p in app.state.pages)
        desk.action("new.files", {})
        _wait(qapp, 400)
        after = sum(len(p.islands) for p in app.state.pages)
        assert after == before + 1, "new.files did not add an island ({0} -> {1})".format(before, after)
        desk.arrange("")
        _wait(qapp, 900)
        desk.undo()
        _wait(qapp, 600)
        for toggle in (desk.toggleHidden, desk.toggleFocus):
            toggle()
            _wait(qapp, 500)
            toggle()
            _wait(qapp, 500)
        assert not desk.hidden and not desk.focusMode
        for context in ("desktop", "tray"):
            app.show_menu(context, QPoint(200, 200))
            _wait(qapp, 300)
            app.close_menu()
        report["actions"] = "passed"

        for page in PAGES:
            app.open_settings(page)
            _wait(qapp, 700)
        assert app.settings_window is not None, "the settings window did not open"
        app.settings_window.grabWindow().save(str(report_path.with_name(report_path.stem + "-settings.png")))
        report["settings"] = list(PAGES)

        _agent_roundtrip(qapp, root / "data", report)

        desk.save_now()
        saved = store.load()
        assert sum(len(p.islands) for p in saved.pages) == after, "the layout was not saved"
        report["storage"] = "passed"
    finally:
        try:
            app.shutdown()
        except Exception:  # noqa: BLE001
            report["shutdown_error"] = traceback.format_exc()
    fatal = [w for w in warnings if any(marker in w for marker in FATAL_QML)]
    report["qml_warnings"] = warnings[:40]
    assert not fatal, "QML errors: " + json.dumps(fatal[:10], ensure_ascii=False)


def run(report_path: Path) -> int:
    report_path = Path(report_path).resolve()
    report: dict = {}
    # Isolated, invisible, deterministic: offscreen software rendering, no Chromium,
    # no WebView2 child processes, a private agent pipe.
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ.setdefault("QT_QUICK_BACKEND", "software")
    os.environ["DESKISLE_WEBENGINE"] = "0"
    os.environ["DESKISLE_PIPE_NAME"] = "deskisle-selftest-" + uuid4().hex[:12]
    os.environ.setdefault("DESKISLE_DEMO_W", "1440")
    os.environ.setdefault("DESKISLE_DEMO_H", "900")
    try:
        from . import __version__

        report["version"] = __version__
        report["frozen"] = bool(getattr(sys, "frozen", False))
        report_path.parent.mkdir(parents=True, exist_ok=True)
        _bundle(report)
        os.environ["DESKISLE_DISABLE_WEBVIEW2"] = "1"     # web islands show their placeholder
        with _workspace(report_path.parent) as root:
            _run_app(root, report_path, report)
        _native_menu(report)
        _cli_exe(report)
        report["status"] = "passed"
    except Exception:  # noqa: BLE001
        report["status"] = "failed"
        report["error"] = traceback.format_exc()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1

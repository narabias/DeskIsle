"""Shared helpers for the Qt based tests: one offscreen QApplication and the real
2.0 app in demo mode with isolated data (the same set-up as ``--self-test``)."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path
from uuid import uuid4

# Deterministic and invisible: offscreen software rendering, no Chromium, no WebView2.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ["DESKISLE_WEBENGINE"] = "0"
os.environ["DESKISLE_DISABLE_WEBVIEW2"] = "1"
os.environ.setdefault("DESKISLE_DEMO_W", "1440")
os.environ.setdefault("DESKISLE_DEMO_H", "900")

ROOT = Path(__file__).resolve().parents[1]
QML_DIR = ROOT / "deskisle" / "qml"


def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(["deskisle-tests"])
    app.setQuitOnLastWindowClosed(False)
    return app


def spin(ms: int, until=None) -> bool:
    """Run the event loop for *ms* milliseconds (or until ``until()`` is true)."""
    from PySide6.QtCore import QEventLoop

    app = qapp()
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
        if until is not None and until():
            return True
        time.sleep(0.005)
    return until is None or bool(until())


class DemoApp:
    """``DeskIsleApp`` in demo mode on a 1440x900 virtual monitor, private data and pipe."""

    def __init__(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="deskisle-test-"))
        os.environ["DESKISLE_PIPE_NAME"] = "deskisle-test-" + uuid4().hex[:12]
        from deskisle.demo import demo_state
        from deskisle.engine import app as appmod
        from deskisle.storage import StateStore

        appmod.prepare_environment()
        self.qapp = qapp()
        self.store = StateStore(self.root / "data")
        state = demo_state(self.root / "demo")
        self.app = appmod.DeskIsleApp(self.qapp, self.store, state, demo=True, root=self.root / "data",
                                      notes=[], recovered=False)
        self.warnings: list[str] = []
        self.app.build()
        self.app.engine.warnings.connect(lambda items: self.warnings.extend(w.toString() for w in items))
        self.app.start()
        if not spin(10000, lambda: bool(self.app.layers.windows)):
            raise RuntimeError("no layer window was created")
        spin(600)

    @property
    def desk(self):
        return self.app.desk

    def close(self) -> None:
        try:
            self.app.shutdown()
        finally:
            os.environ.pop("DESKISLE_PIPE_NAME", None)
            shutil.rmtree(self.root, ignore_errors=True)


FATAL_QML = ("TypeError", "ReferenceError", "SyntaxError", "is not a type", "is not installed",
             "Cannot assign", "Unable to assign", "failed to load component")


def fatal(warnings: list[str]) -> list[str]:
    return [w for w in warnings if any(marker in w for marker in FATAL_QML)]

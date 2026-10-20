"""Short, self-restoring Windows desktop integration smoke test."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QFont  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from deskisle.board import DesktopWindow  # noqa: E402
from deskisle.storage import StateStore  # noqa: E402
from deskisle.theme import app_stylesheet  # noqa: E402
from main import demo_state  # noqa: E402


def main() -> int:
    output = PROJECT / "artifacts" / "desktop-smoke.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())
    app.setQuitOnLastWindowClosed(False)
    state = demo_state()
    state.preferences.hide_native_icons = True
    window = DesktopWindow(state, StateStore(PROJECT / ".desktop-smoke"), demo_mode=False)
    window.show()

    def finish() -> None:
        window.grab().save(str(output))
        window.exit_application()

    QTimer.singleShot(1800, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())


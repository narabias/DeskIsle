"""Render the demo window to a PNG for visual regression checks."""

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
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else PROJECT / "artifacts" / "demo.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyle("Fusion")
    app.setStyleSheet(app_stylesheet())
    window = DesktopWindow(demo_state(), StateStore(PROJECT / ".demo-data"), demo_mode=True)
    window.resize(1280, 760)
    window.show()

    def capture() -> None:
        window.grab().save(str(output))
        window._closing_for_real = True
        window.close()
        app.quit()

    QTimer.singleShot(800, capture)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

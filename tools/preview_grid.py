"""Render the arrangement mode to PNG so the layout can be eyeballed."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Allow running straight from a checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtGui import QFontDatabase, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from deskisle import grid_layout  # noqa: E402

OUT = Path(__file__).parent / "preview"

BG = "#141C2B"
CARD = "#22304A"
ACCENT = "#5B8FF9"
TEXT = "#E8EDF7"
MUTED = "#7C8BA8"


def render(levels: list[str], pinned, width: int, height: int, path: Path, title: str) -> None:
    QApplication.instance() or QApplication([])
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(BG)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Toolbar strip, matching the real app's reserved top band.
    painter.setBrush(CARD)
    painter.setPen(ACCENT)
    painter.drawRoundedRect(8, 8, 210, 34, 10, 10)
    painter.setPen(TEXT)
    font = painter.font()
    font.setPointSize(11)
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(20, 31, title)

    area_x, area_y = 8, 8 + 34 + 12
    area_w, area_h = width - 16, height - area_y - 8
    rects = grid_layout.layout(levels, pinned, area_w, area_h)

    font.setPointSize(9)
    font.setBold(False)
    painter.setFont(font)
    for index, (rect, level) in enumerate(zip(rects, levels)):
        x, y = area_x + rect.x, area_y + rect.y
        painter.setBrush(CARD)
        painter.setPen(ACCENT)
        painter.drawRoundedRect(x, y, rect.width, rect.height, 12, 12)
        painter.setPen(MUTED)
        painter.drawText(x + 14, y + 26, f"#{index + 1}  {level}")
        painter.setBrush(ACCENT)
        painter.setPen(ACCENT)
        cell = 26
        cols = max(1, (rect.width - 28) // (cell + 10))
        for row in range(max(1, (rect.height - 60) // (cell + 10))):
            for col in range(cols):
                painter.drawRoundedRect(x + 14 + col * (cell + 10), y + 42 + row * (cell + 10),
                                        cell, cell, 6, 6)
    painter.end()
    image.save(str(path))
    print("wrote", path.name)


def main() -> int:
    QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    OUT.mkdir(exist_ok=True)
    q, t, h, f = (grid_layout.LEVEL_QUARTER, grid_layout.LEVEL_THIRD,
                  grid_layout.LEVEL_HALF, grid_layout.LEVEL_FULL)
    nothing = lambda n: [None] * n  # noqa: E731

    render([h, h], nothing(2), 1280, 760, OUT / "two-halves.png", "2 × ½")
    render([q] * 4, nothing(4), 1280, 760, OUT / "four-quarters.png", "4 × ¼")
    render([t] * 3, nothing(3), 1280, 760, OUT / "three-thirds.png", "3 × ⅓")
    render([f, h], nothing(2), 1280, 760, OUT / "full-half.png", "整行 + ½")
    # The case reported from the screenshot: mixed sizes used to leave a void.
    render([q, h, t, f, t, q], nothing(6), 1280, 760, OUT / "mixed.png", "混合尺寸（已填补空隙）")
    render([q] * 6, nothing(6), 1280, 760, OUT / "six-quarters.png", "6 × ¼")
    # A deliberate drop away from the corner must be respected, not compacted.
    render([q, q, q], [(0, 0), (9, 0), (0, 9)], 1280, 760, OUT / "free-drop.png", "自由拖动")
    return 0


if __name__ == "__main__":
    sys.exit(main())

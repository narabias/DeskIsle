"""Build DeskIsle's application icon from a square picture.

    python tools/make_app_icon.py [picture] [--box X0 Y0 X1 Y1]

The crop box (in picture pixels) is scaled to a rounded square and written to

* ``packaging/DeskIsle.ico`` – 16 … 256 px, PNG-compressed entries (exe, installer)
* ``packaging/DeskIsle.png`` – 256 px
* ``deskisle/assets/ui/app-icon.png`` – 256 px, used at runtime (tray, windows, 关于)

Only PySide6 is needed.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PICTURE = ROOT / "packaging" / "icon-source.jpg"
# Head and ribbons of the 1920 x 1920 source picture.
DEFAULT_BOX = (450, 0, 1530, 1080)
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
CORNER = 0.225  # corner radius relative to the icon size


def render(picture, box: tuple[int, int, int, int], size: int):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen

    x0, y0, x1, y1 = box
    crop = picture.copy(x0, y0, max(1, x1 - x0), max(1, y1 - y0))
    # Halve step by step: one big smooth (bilinear) reduction would alias.
    while crop.width() >= size * 4:
        crop = crop.scaled(crop.width() // 2, crop.height() // 2, Qt.AspectRatioMode.IgnoreAspectRatio,
                           Qt.TransformationMode.SmoothTransformation)
    crop = crop.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    radius = size * CORNER
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(crop))
    painter.drawPath(path)
    if size >= 24:
        # A faint inner hairline keeps the rounded shape readable on light
        # taskbars (the picture's background is almost white).
        width = max(1.0, size / 128.0)
        inset = width / 2.0
        ring = QPainterPath()
        ring.addRoundedRect(QRectF(inset, inset, size - width, size - width), radius - inset, radius - inset)
        painter.setPen(QPen(QColor(0, 0, 0, 34), width))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(ring)
    painter.end()
    return image.convertToFormat(QImage.Format.Format_ARGB32)


def png_bytes(image) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data.data())


def write_ico(images: list, path: Path) -> None:
    blobs = [png_bytes(image) for image in images]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for image, blob in zip(images, blobs):
        width, height = image.width(), image.height()
        entries += struct.pack("<BBBBHHII", width if width < 256 else 0, height if height < 256 else 0,
                               0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    path.write_bytes(header + entries + b"".join(blobs))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("picture", nargs="?", type=Path, default=DEFAULT_PICTURE)
    parser.add_argument("--box", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"), default=DEFAULT_BOX)
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication, QImage

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    picture = QImage(str(args.picture))
    if picture.isNull():
        print("无法读取图片：{0}".format(args.picture), file=sys.stderr)
        return 1
    box = tuple(args.box)
    images = [render(picture, box, size) for size in ICO_SIZES]
    packaging = ROOT / "packaging"
    write_ico(images, packaging / "DeskIsle.ico")
    largest = images[-1]
    largest.save(str(packaging / "DeskIsle.png"), "PNG")
    largest.save(str(ROOT / "deskisle" / "assets" / "ui" / "app-icon.png"), "PNG")
    del app
    print("已生成 DeskIsle.ico / DeskIsle.png / app-icon.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

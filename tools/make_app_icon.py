from pathlib import Path
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QColor
from PIL import Image

root = Path(__file__).resolve().parents[1]
out = root / 'packaging'
out.mkdir(exist_ok=True)
picture = QImage(256, 256, QImage.Format.Format_ARGB32)
picture.fill(Qt.GlobalColor.transparent)
painter = QPainter(picture)
painter.setRenderHint(QPainter.RenderHint.Antialiasing)
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(QColor('#182735'))
painter.drawRoundedRect(QRectF(8, 8, 240, 240), 52, 52)
painter.setBrush(QColor('#55D6BE'))
painter.drawRoundedRect(QRectF(46, 54, 72, 148), 17, 17)
painter.setBrush(QColor('#98EBDD'))
painter.drawRoundedRect(QRectF(134, 54, 76, 68), 17, 17)
painter.setBrush(QColor('#4F7CAC'))
painter.drawRoundedRect(QRectF(134, 138, 76, 64), 17, 17)
painter.end()
picture.save(str(out / 'DeskIsle.png'))
Image.open(out / 'DeskIsle.png').save(out / 'DeskIsle.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])

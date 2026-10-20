"""iOS-flavoured controls: glass menus, switches, segmented controls, buttons."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFontMetrics, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QCheckBox, QMenu, QSizePolicy, QWidget

from . import motion
from .theme import ACCENT


class GlassMenu(QMenu):
    """Rounded translucent popup that fades in; submenus inherit the style."""

    def __init__(self, *args, passive: bool = False) -> None:
        super().__init__(*args)
        self._passive = passive
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        if passive:
            # Island menus must not activate DeskIsle (see board.py notes on
            # wallpaper players reacting to foreground changes).
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        self._fade = QVariantAnimation(self)
        self._fade.setEasingCurve(motion.soft_curve())
        self._fade.valueChanged.connect(lambda value: self.setWindowOpacity(float(value)))

    def addMenu(self, *args):  # noqa: N802 - Qt API
        if args and isinstance(args[-1], str) and not isinstance(args[0], QMenu):
            title = args[-1]
            submenu = GlassMenu(title, self, passive=self._passive)
            if len(args) == 2 and isinstance(args[0], QIcon):
                submenu.setIcon(args[0])
            self.addAction(submenu.menuAction())
            return submenu
        return super().addMenu(*args)

    def showEvent(self, event) -> None:  # noqa: N802
        if motion.reduce_motion():
            self.setWindowOpacity(1.0)
        else:
            self.setWindowOpacity(0.0)
            self._fade.stop()
            self._fade.setDuration(motion.duration(130))
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.start()
        super().showEvent(event)


class ToggleSwitch(QCheckBox):
    """An iOS switch.  The label sits on the left, the switch on the right."""

    TRACK_W = 42
    TRACK_H = 25

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._knob = motion.Tween(self, lambda _v: self.update(), 0.0, motion.SLIDE_MS,
                                  motion.spring_curve(1.05))
        self.toggled.connect(lambda checked: self._knob.to(1.0 if checked else 0.0))

    def setChecked(self, checked: bool) -> None:  # noqa: N802 - Qt API
        super().setChecked(checked)
        self._knob.set_immediate(1.0 if checked else 0.0)

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = QFontMetrics(self.font())
        text_width = metrics.horizontalAdvance(self.text()) + 14 if self.text() else 0
        return QSize(text_width + self.TRACK_W + 4, max(self.TRACK_H + 6, metrics.height() + 8))

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.TRACK_W + 4, self.TRACK_H + 6)

    def hitButton(self, pos) -> bool:  # noqa: N802
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.42)
        track = QRectF(self.width() - self.TRACK_W - 2, (self.height() - self.TRACK_H) / 2,
                       self.TRACK_W, self.TRACK_H)
        if self.text():
            painter.setPen(QColor("#F5F5F7"))
            text_rect = QRectF(0, 0, track.left() - 10, self.height())
            painter.drawText(text_rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                             QFontMetrics(self.font()).elidedText(self.text(), Qt.TextElideMode.ElideRight,
                                                                  int(text_rect.width())))
        progress = motion.clamp01(self._knob.value)
        off = QColor(120, 120, 128, 92)
        on = QColor(ACCENT)
        color = QColor(
            int(off.red() + (on.red() - off.red()) * progress),
            int(off.green() + (on.green() - off.green()) * progress),
            int(off.blue() + (on.blue() - off.blue()) * progress),
            int(off.alpha() + (255 - off.alpha()) * progress),
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        knob_d = track.height() - 4
        travel = track.width() - knob_d - 4
        knob_x = track.left() + 2 + travel * self._knob.value
        knob = QRectF(knob_x, track.top() + 2, knob_d, knob_d)
        painter.setBrush(QColor(0, 0, 0, 46))
        painter.drawEllipse(knob.translated(0, 1.2))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(knob)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(85, 214, 190, 150), 1.5))
            painter.drawRoundedRect(track.adjusted(-2, -2, 2, 2), track.height() / 2 + 2, track.height() / 2 + 2)


class SegmentedControl(QWidget):
    """UISegmentedControl look-alike with a sliding selection pill."""

    currentChanged = Signal(int)

    def __init__(self, items: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items = list(items)
        self._current = 0
        self._hover = -1
        self._pill = motion.Tween(self, lambda _v: self.update(), 0.0, motion.SLIDE_MS, span=1.0)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def items(self) -> list[str]:
        return list(self._items)

    def count(self) -> int:
        return len(self._items)

    def currentIndex(self) -> int:  # noqa: N802 - Qt naming
        return self._current

    def setCurrentIndex(self, index: int, animate: bool = True) -> None:  # noqa: N802
        index = max(0, min(len(self._items) - 1, int(index)))
        changed = index != self._current
        self._current = index
        if animate and self.isVisible():
            self._pill.to(float(index))
        else:
            self._pill.set_immediate(float(index))
        self.update()
        if changed:
            self.currentChanged.emit(index)

    def sizeHint(self) -> QSize:  # noqa: N802
        metrics = QFontMetrics(self.font())
        width = sum(metrics.horizontalAdvance(text) + 28 for text in self._items) + 4
        return QSize(max(120, width), max(30, metrics.height() + 14))

    def _segment_rect(self, index: float) -> QRectF:
        count = max(1, len(self._items))
        inner = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        width = inner.width() / count
        return QRectF(inner.left() + width * index, inner.top(), width, inner.height())

    def _index_at(self, x: float) -> int:
        count = max(1, len(self._items))
        return max(0, min(count - 1, int((x - 2) / max(1.0, (self.width() - 4) / count))))

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.setCurrentIndex(self._index_at(event.position().x()))
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        hover = self._index_at(event.position().x())
        if hover != self._hover:
            self._hover = hover
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = -1
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Up):
            self.setCurrentIndex(self._current - 1)
        elif event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Down):
            self.setCurrentIndex(self._current + 1)
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        outer = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(118, 118, 128, 62))
        painter.drawRoundedRect(outer, 9, 9)
        pill = self._segment_rect(self._pill.value).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawRoundedRect(pill.translated(0, 1), 7, 7)
        painter.setBrush(QColor("#636366"))
        painter.drawRoundedRect(pill, 7, 7)
        painter.setPen(QPen(QColor(255, 255, 255, 30), 0.8))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(pill.adjusted(0.4, 0.4, -0.4, -0.4), 6.6, 6.6)
        for index, text in enumerate(self._items):
            rect = self._segment_rect(index)
            selected_weight = max(0.0, 1.0 - abs(self._pill.value - index))
            if index > 0 and abs(self._pill.value - index) > 0.9 and abs(self._pill.value - (index - 1)) > 0.9:
                painter.setPen(QPen(QColor(255, 255, 255, 30), 1))
                painter.drawLine(QPointF(rect.left(), rect.top() + 7), QPointF(rect.left(), rect.bottom() - 7))
            color = QColor(235, 235, 245, int(175 + 80 * selected_weight))
            if index == self._hover and index != self._current:
                color = QColor(255, 255, 255, 235)
            painter.setPen(color)
            font = self.font()
            font.setWeight(font.Weight.DemiBold if selected_weight > 0.5 else font.Weight.Normal)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter,
                             QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width() - 8)))
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(85, 214, 190, 120), 1.2))
            painter.drawRoundedRect(outer, 9, 9)


class GlassButton(QAbstractButton):
    """Round glass button with hover glow and a springy press."""

    def __init__(self, parent: QWidget | None = None, *, diameter: int = 28, icon: QIcon | None = None,
                 icon_size: int = 18, shape: str = "circle") -> None:
        super().__init__(parent)
        self._diameter = diameter
        self._icon_size = icon_size
        self._shape = shape
        self.highlight = 0.0
        self.scale = 1.0
        self._hover = motion.Tween(self, self._set_highlight, 0.0, motion.HOVER_MS)
        self._press = motion.Tween(self, self._set_scale, 1.0, motion.PRESS_MS, span=0.12)
        if icon is not None:
            self.setIcon(icon)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(diameter + 4, diameter + 2)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def _set_highlight(self, value: float) -> None:
        self.highlight = value
        self.update()

    def _set_scale(self, value: float) -> None:
        self.scale = value
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._diameter + 4, self._diameter + 2)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover.to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover.to(0.0)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press.to(0.86, motion.PRESS_MS, motion.ios_curve(), proportional=False)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press.to(1.0, motion.RELEASE_MS, motion.spring_curve(1.6), proportional=False)
        super().mouseReleaseEvent(event)

    def glyph_color(self) -> QColor:
        color = QColor(245, 245, 247)
        color.setAlphaF(0.82 + 0.18 * self.highlight)
        return color

    def paint_glyph(self, painter: QPainter, rect: QRectF) -> None:
        icon = self.icon()
        if not icon.isNull():
            size = self._icon_size
            pixmap = icon.pixmap(QSize(size, size), self.devicePixelRatioF())
            painter.drawPixmap(QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2, size, size),
                               pixmap, QRectF(pixmap.rect()))

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if not self.isEnabled():
            painter.setOpacity(0.4)
        center = QPointF(self.width() / 2, self.height() / 2)
        painter.translate(center)
        painter.scale(self.scale, self.scale)
        painter.translate(-center)
        d = self._diameter
        bg = QRectF(center.x() - d / 2, center.y() - d / 2, d, d)
        if self._shape == "pill":
            bg = QRectF(1, center.y() - d / 2, self.width() - 2, d)
        alpha = 0.0 + 0.16 * self.highlight + (0.10 if self.isDown() else 0.0)
        if self.isChecked():
            alpha = max(alpha, 0.22)
        if alpha > 0.003:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, int(255 * alpha)))
            painter.drawRoundedRect(bg, bg.height() / 2, bg.height() / 2)
            painter.setPen(QPen(QColor(255, 255, 255, int(70 * self.highlight)), 0.8))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(bg.adjusted(0.4, 0.4, -0.4, -0.4), bg.height() / 2, bg.height() / 2)
        self.paint_glyph(painter, bg)


def draw_glyph(painter: QPainter, name: str, rect: QRectF, color: QColor, *, rotation: float = 0.0,
               width: float = 1.6) -> None:
    """Vector glyphs drawn in an 18 px design box (so they stay crisp at any DPI)."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    side = min(rect.width(), rect.height())
    u = side / 18.0
    painter.translate(rect.center())
    if rotation:
        painter.rotate(rotation)
    pen = QPen(color, width * max(0.75, min(1.4, u)), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
               Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    def poly(*points: tuple[float, float]) -> None:
        path = QPainterPath(QPointF(points[0][0] * u, points[0][1] * u))
        for x, y in points[1:]:
            path.lineTo(x * u, y * u)
        painter.drawPath(path)

    if name == "chevron-up":
        poly((-4.5, 2.3), (0, -2.2), (4.5, 2.3))
    elif name == "chevron-down":
        poly((-4.5, -2.3), (0, 2.2), (4.5, -2.3))
    elif name == "chevron-left":
        poly((2.3, -4.5), (-2.2, 0), (2.3, 4.5))
    elif name == "chevron-right":
        poly((-2.3, -4.5), (2.2, 0), (-2.3, 4.5))
    elif name == "arrow-up":
        poly((0, 5.5), (0, -5.0))
        poly((-4.2, -1.0), (0, -5.2), (4.2, -1.0))
    elif name == "dots":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        for x in (-5.2, 0.0, 5.2):
            painter.drawEllipse(QPointF(x * u, 0), 1.55 * u, 1.55 * u)
    elif name == "plus":
        poly((-5, 0), (5, 0))
        poly((0, -5), (0, 5))
    elif name in ("close", "stop"):
        poly((-4.2, -4.2), (4.2, 4.2))
        poly((4.2, -4.2), (-4.2, 4.2))
    elif name == "reload":
        r = 5.4 * u
        path = QPainterPath()
        path.arcMoveTo(QRectF(-r, -r, 2 * r, 2 * r), 60)
        path.arcTo(QRectF(-r, -r, 2 * r, 2 * r), 60, 280)
        painter.drawPath(path)
        tip = QPointF(r * 0.5, -r * 0.866)
        painter.drawLine(tip, tip + QPointF(-3.2 * u, -1.0 * u))
        painter.drawLine(tip, tip + QPointF(0.6 * u, 3.2 * u))
    elif name == "external":
        poly((1.5, -6), (6, -6), (6, -1.5))
        poly((6, -6), (-0.5, 0.5))
        poly((-1.5, -5), (-6, -5), (-6, 6), (5, 6), (5, 1.5))
    elif name == "lock":
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(-4.6 * u, -0.8 * u, 9.2 * u, 7.0 * u), 1.8 * u, 1.8 * u)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(pen)
        shackle = QPainterPath(QPointF(-2.9 * u, -0.8 * u))
        shackle.lineTo(-2.9 * u, -3.2 * u)
        shackle.arcTo(QRectF(-2.9 * u, -6.1 * u, 5.8 * u, 5.8 * u), 180, -180)
        shackle.lineTo(2.9 * u, -0.8 * u)
        painter.drawPath(shackle)
    elif name == "pin":
        painter.drawEllipse(QPointF(0, -2.5 * u), 3.2 * u, 3.2 * u)
        poly((0, 0.7), (0, 6.5))
    elif name == "globe":
        r = 6.0 * u
        painter.drawEllipse(QPointF(0, 0), r, r)
        painter.drawEllipse(QPointF(0, 0), r * 0.45, r)
        painter.drawLine(QPointF(-r, 0), QPointF(r, 0))
    elif name == "grid":
        for x in (-5.8, 0.8):
            for y in (-5.8, 0.8):
                painter.drawRoundedRect(QRectF(x * u, y * u, 5.0 * u, 5.0 * u), 1.4 * u, 1.4 * u)
    elif name == "folder":
        poly((-6.5, -4.5), (-2.2, -4.5), (-0.6, -2.8), (6.5, -2.8), (6.5, 5.2), (-6.5, 5.2), (-6.5, -4.5))
        poly((-6.5, -0.6), (6.5, -0.6))
    elif name == "play":
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath(QPointF(-3.6 * u, -5.4 * u))
        path.lineTo(5.6 * u, 0)
        path.lineTo(-3.6 * u, 5.4 * u)
        path.closeSubpath()
        painter.drawPath(path)
    elif name == "code":
        poly((-2.6, -4.6), (-6.4, 0), (-2.6, 4.6))
        poly((2.6, -4.6), (6.4, 0), (2.6, 4.6))
        poly((1.0, -6.2), (-1.0, 6.2))
    elif name == "check":
        poly((-5.0, 0.2), (-1.6, 3.6), (5.2, -3.6))
    elif name == "sparkle":
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        path = QPainterPath(QPointF(0, -6.5 * u))
        path.quadTo(QPointF(0.9 * u, -0.9 * u), QPointF(6.5 * u, 0))
        path.quadTo(QPointF(0.9 * u, 0.9 * u), QPointF(0, 6.5 * u))
        path.quadTo(QPointF(-0.9 * u, 0.9 * u), QPointF(-6.5 * u, 0))
        path.quadTo(QPointF(-0.9 * u, -0.9 * u), QPointF(0, -6.5 * u))
        painter.drawPath(path)
    painter.restore()


class GlyphButton(GlassButton):
    """GlassButton showing one of the vector glyphs from :func:`draw_glyph`."""

    def __init__(self, glyph: str, parent: QWidget | None = None, *, diameter: int = 28, tooltip: str = "",
                 glyph_size: float = 18.0) -> None:
        super().__init__(parent, diameter=diameter)
        self.glyph = glyph
        self.rotation = 0.0
        self._glyph_size = glyph_size
        if tooltip:
            self.setToolTip(tooltip)
            self.setAccessibleName(tooltip)

    def set_glyph(self, glyph: str) -> None:
        if glyph != self.glyph:
            self.glyph = glyph
            self.update()

    def set_rotation(self, degrees: float) -> None:
        self.rotation = float(degrees)
        self.update()

    def paint_glyph(self, painter: QPainter, rect: QRectF) -> None:
        size = self._glyph_size
        box = QRectF(rect.center().x() - size / 2, rect.center().y() - size / 2, size, size)
        draw_glyph(painter, self.glyph, box, self.glyph_color(), rotation=self.rotation)


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    radius = max(0.0, min(radius, rect.width() / 2, rect.height() / 2))
    path.addRoundedRect(rect, radius, radius)
    return path


__all__ = ["GlassButton", "GlassMenu", "GlyphButton", "SegmentedControl", "ToggleSwitch", "draw_glyph", "rounded_path"]

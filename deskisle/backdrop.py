"""Backdrop sampling and glass materials for islands and the toolbar.

Islands live directly above the desktop wallpaper, so instead of asking the
compositor for an (expensive, rectangular) live blur we sample the wallpaper
image ourselves.  The wallpaper is decoded once at quarter resolution and
pre-blurred into two material levels; painting an island then costs a single
scaled ``drawImage`` of a tiny region.  Nothing is recomputed while idle.
"""

from __future__ import annotations

import math
import os
from collections import OrderedDict
from dataclasses import dataclass

from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QImageReader,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import (
    QApplication,
    QGraphicsBlurEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QWidget,
)

from . import native_win

MATERIAL_LABELS = {"clear": "简易透明", "frosted": "毛玻璃", "liquid": "液体玻璃"}
MATERIAL_ORDER = ("clear", "frosted", "liquid")
CANVAS_SCALE = 0.25
_FORMAT = QImage.Format.Format_ARGB32_Premultiplied


def paint_demo_background(painter: QPainter, rect: QRectF) -> None:
    """Abstract wallpaper used by demo mode (and as a glass fallback)."""
    w, h = max(1.0, rect.width()), max(1.0, rect.height())
    base = QLinearGradient(rect.topLeft(), rect.bottomRight())
    base.setColorAt(0.0, QColor("#0B1220"))
    base.setColorAt(0.5, QColor("#13233A"))
    base.setColorAt(1.0, QColor("#0E3430"))
    painter.fillRect(rect, base)
    blobs = (
        (0.16, 0.22, 0.42, QColor(47, 211, 179, 120)),
        (0.80, 0.18, 0.36, QColor(123, 92, 255, 110)),
        (0.62, 0.92, 0.42, QColor(255, 138, 91, 82)),
        (0.30, 0.86, 0.34, QColor(61, 139, 255, 92)),
        (0.95, 0.62, 0.28, QColor(255, 94, 160, 60)),
    )
    for fx, fy, fr, color in blobs:
        center = QPointF(rect.left() + w * fx, rect.top() + h * fy)
        radius = max(w, h) * fr
        gradient = QRadialGradient(center, radius)
        gradient.setColorAt(0.0, color)
        faded = QColor(color)
        faded.setAlpha(0)
        gradient.setColorAt(1.0, faded)
        painter.fillRect(rect, gradient)


def _pad_replicate(image: QImage, pad: int) -> QImage:
    w, h = image.width(), image.height()
    out = QImage(w + pad * 2, h + pad * 2, _FORMAT)
    out.fill(Qt.GlobalColor.black)
    painter = QPainter(out)
    painter.drawImage(QRect(pad, pad, w, h), image)
    # Stretch the outermost pixel rows/columns into the padding so the blur
    # never pulls in black (or transparent) pixels at the screen edges.
    painter.drawImage(QRect(0, pad, pad, h), image, QRect(0, 0, 1, h))
    painter.drawImage(QRect(pad + w, pad, pad, h), image, QRect(w - 1, 0, 1, h))
    painter.drawImage(QRect(0, 0, w + pad * 2, pad), out, QRect(0, pad, w + pad * 2, 1))
    painter.drawImage(QRect(0, pad + h, w + pad * 2, pad), out, QRect(0, pad + h - 1, w + pad * 2, 1))
    painter.end()
    return out


def blur_image(image: QImage, radius: float) -> QImage:
    """Gaussian-like blur using Qt's C++ blur (fast on small images)."""
    if radius <= 0.2 or image.isNull():
        return image.convertToFormat(_FORMAT)
    pad = int(radius * 2.5) + 2
    padded = _pad_replicate(image.convertToFormat(_FORMAT), pad)
    scene = QGraphicsScene()
    scene.setSceneRect(QRectF(0, 0, padded.width(), padded.height()))
    item = QGraphicsPixmapItem(QPixmap.fromImage(padded))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    effect.setBlurHints(QGraphicsBlurEffect.BlurHint.QualityHint)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    out = QImage(padded.size(), _FORMAT)
    out.fill(Qt.GlobalColor.transparent)
    painter = QPainter(out)
    scene.render(painter, QRectF(out.rect()), scene.sceneRect())
    painter.end()
    scene.clear()
    return out.copy(pad, pad, image.width(), image.height())


def saturate_image(image: QImage, factor: float) -> QImage:
    """Vibrancy boost: C' = C + k·(C − L), computed with C++ blend modes."""
    k = max(0.0, float(factor) - 1.0)
    base = image.convertToFormat(QImage.Format.Format_RGB32)
    if k <= 0.01:
        return base.convertToFormat(_FORMAT)
    gray = base.convertToFormat(QImage.Format.Format_Grayscale8).convertToFormat(QImage.Format.Format_RGB32)
    out = base.copy()
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    painter.setOpacity(min(1.0, k))
    painter.drawImage(0, 0, base)
    painter.end()
    out.invertPixels()
    painter = QPainter(out)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Plus)
    painter.setOpacity(min(1.0, k))
    painter.drawImage(0, 0, gray)
    painter.end()
    out.invertPixels()
    return out.convertToFormat(_FORMAT)


def load_image_scaled(path: str, wanted: QSize) -> QImage:
    """Decode *path* roughly at *wanted* size (JPEG decodes scaled for free)."""
    if not path or not os.path.isfile(path):
        return QImage()
    reader = QImageReader(path)
    reader.setDecideFormatFromContent(True)
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and wanted.isValid() and size.width() > 0 and size.height() > 0:
        factor = max(wanted.width() / size.width(), wanted.height() / size.height())
        if factor < 1.0:
            reader.setScaledSize(QSize(max(1, round(size.width() * factor)), max(1, round(size.height() * factor))))
    image = reader.read()
    return image if not image.isNull() else QImage()


def _draw_placed(painter: QPainter, image: QImage, target: QRectF, style: str) -> None:
    if image.isNull():
        return
    iw, ih = image.width(), image.height()
    if style == "stretch":
        painter.drawImage(target, image)
        return
    if style == "tile":
        painter.save()
        painter.setClipRect(target)
        scale = CANVAS_SCALE
        tile = image.scaled(max(1, int(iw * scale)), max(1, int(ih * scale)),
                            Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        painter.fillRect(target, QBrush(tile))
        painter.restore()
        return
    if style == "center":
        w, h = iw * CANVAS_SCALE, ih * CANVAS_SCALE
        painter.drawImage(QRectF(target.center().x() - w / 2, target.center().y() - h / 2, w, h), image)
        return
    ratio = (min if style == "fit" else max)(target.width() / iw, target.height() / ih)
    w, h = iw * ratio, ih * ratio
    painter.drawImage(QRectF(target.center().x() - w / 2, target.center().y() - h / 2, w, h), image)


class BackdropProvider(QObject):
    """Pre-blurred copy of whatever is behind the islands."""

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.mode = "wallpaper"
        self.image_path = ""
        self.version = 0
        self._demo_surface: QWidget | None = None
        self._origin = QPoint(0, 0)
        self._levels: dict[str, tuple[QImage, float]] = {}
        self._signature = None
        self._rebuild_timer = QTimer(self)
        self._rebuild_timer.setSingleShot(True)
        self._rebuild_timer.setInterval(220)
        self._rebuild_timer.timeout.connect(self.rebuild)
        self._watch_timer = QTimer(self)
        self._watch_timer.setInterval(60_000)
        self._watch_timer.timeout.connect(self._check_wallpaper)

    # Configuration -----------------------------------------------------
    def configure(self, mode: str = "wallpaper", image_path: str = "", demo_surface: QWidget | None = None) -> None:
        mode = mode if mode in ("wallpaper", "image") else "wallpaper"
        self.mode = mode
        self.image_path = image_path or ""
        if demo_surface is not None:
            self._demo_surface = demo_surface
        if self._demo_surface is None and not self._watch_timer.isActive():
            self._watch_timer.start()
        self.schedule_rebuild(0)

    def set_demo_surface(self, surface: QWidget | None) -> None:
        self._demo_surface = surface
        self.schedule_rebuild()

    def schedule_rebuild(self, delay: int = 220) -> None:
        self._rebuild_timer.start(max(0, delay))

    def ensure_ready(self) -> None:
        if not self._levels:
            self.rebuild()

    def _wallpaper_signature(self):
        info = native_win.get_wallpaper_info()
        path = info.get("path", "")
        try:
            stamp = os.stat(path).st_mtime_ns if path else 0
        except OSError:
            stamp = 0
        return (path, stamp, info.get("style"), info.get("color")), info

    def _check_wallpaper(self) -> None:
        if self._demo_surface is not None or self.mode != "wallpaper":
            return
        signature, _info = self._wallpaper_signature()
        if signature != self._signature:
            self.schedule_rebuild(0)

    # Geometry ----------------------------------------------------------
    def _virtual_rect(self) -> QRect:
        if self._demo_surface is not None:
            return QRect(QPoint(0, 0), self._demo_surface.size())
        screens = QApplication.screens()
        if not screens:
            return QRect(0, 0, 1920, 1080)
        rect = screens[0].geometry()
        for screen in screens[1:]:
            rect = rect.united(screen.geometry())
        return rect

    def canvas_point(self, widget: QWidget) -> QPointF:
        """Top-left of *widget* in canvas coordinates."""
        surface = self._demo_surface
        if surface is not None:
            try:
                if widget is surface or surface.isAncestorOf(widget):
                    return QPointF(widget.mapTo(surface, QPoint(0, 0)))
            except RuntimeError:
                pass
            return QPointF(widget.mapToGlobal(QPoint(0, 0)) - surface.mapToGlobal(QPoint(0, 0)))
        return QPointF(widget.mapToGlobal(QPoint(0, 0)) - self._origin)

    # Building ----------------------------------------------------------
    def rebuild(self) -> None:
        self._rebuild_timer.stop()
        virtual = self._virtual_rect()
        self._origin = virtual.topLeft()
        width = max(8, int(virtual.width() * CANVAS_SCALE))
        height = max(8, int(virtual.height() * CANVAS_SCALE))
        canvas = QImage(width, height, _FORMAT)
        canvas.fill(QColor("#10151E"))
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        drawn = False
        if self._demo_surface is not None:
            painter.save()
            painter.scale(CANVAS_SCALE, CANVAS_SCALE)
            paint_demo_background(painter, QRectF(0, 0, virtual.width(), virtual.height()))
            painter.restore()
            drawn = True
            self._signature = None
        else:
            signature, info = self._wallpaper_signature()
            self._signature = signature
            path, style = info.get("path", ""), info.get("style", "fill")
            if self.mode == "image" and self.image_path:
                path, style = self.image_path, "span"
            canvas.fill(QColor(info.get("color") or "#10151E"))
            image = load_image_scaled(path, QSize(width * 2, height * 2))
            if not image.isNull():
                if style == "span":
                    _draw_placed(painter, image, QRectF(0, 0, width, height), "fill")
                else:
                    for screen in QApplication.screens():
                        geometry = screen.geometry().translated(-self._origin)
                        target = QRectF(geometry.x() * CANVAS_SCALE, geometry.y() * CANVAS_SCALE,
                                        geometry.width() * CANVAS_SCALE, geometry.height() * CANVAS_SCALE)
                        painter.save()
                        painter.setClipRect(target)
                        _draw_placed(painter, image, target, style)
                        painter.restore()
                drawn = True
        if not drawn:
            painter.save()
            painter.scale(CANVAS_SCALE, CANVAS_SCALE)
            paint_demo_background(painter, QRectF(0, 0, virtual.width(), virtual.height()))
            painter.restore()
        painter.end()

        liquid = saturate_image(blur_image(canvas, 1.6), 1.25)
        small = canvas.scaled(max(4, width // 2), max(4, height // 2),
                              Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        frosted = saturate_image(blur_image(small, 5.0), 1.6)
        self._levels = {
            "liquid": (liquid, CANVAS_SCALE),
            "frosted": (frosted, CANVAS_SCALE / 2),
        }
        self.version += 1
        self.changed.emit()

    def sample(self, level: str, rect: QRectF) -> tuple[QImage, QRectF] | None:
        """Return (image, source-rect) covering *rect* (canvas coordinates)."""
        entry = self._levels.get(level)
        if entry is None:
            return None
        image, scale = entry
        source = QRectF(rect.x() * scale, rect.y() * scale, rect.width() * scale, rect.height() * scale)
        return image, source


_provider: BackdropProvider | None = None


def provider() -> BackdropProvider:
    global _provider
    if _provider is None:
        _provider = BackdropProvider()
    return _provider


@dataclass
class GlassStyle:
    material: str = "frosted"
    tint: QColor = None  # type: ignore[assignment]
    density: float = 0.88
    radius: float = 18.0
    hover: float = 0.0
    emphasis: float = 0.0

    def __post_init__(self) -> None:
        if self.tint is None:
            self.tint = QColor("#243245")
        if self.material not in MATERIAL_ORDER:
            self.material = "frosted"


def glass_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    radius = max(0.0, min(radius, rect.width() / 2, rect.height() / 2))
    path.addRoundedRect(rect, radius, radius)
    return path


def _density01(density: float) -> float:
    return max(0.0, min(1.0, (float(density) - 0.35) / 0.65))


# Masks ---------------------------------------------------------------
_MASKS: "OrderedDict[tuple, QImage]" = OrderedDict()
_MASK_LIMIT = 32
EDGE_SCALE = 0.25


def _cached_mask(key: tuple, factory) -> QImage:
    image = _MASKS.get(key)
    if image is None:
        image = factory()
        _MASKS[key] = image
        while len(_MASKS) > _MASK_LIMIT:
            _MASKS.popitem(last=False)
    else:
        _MASKS.move_to_end(key)
    return image


def _smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def edge_mask(width: float, height: float, radius: float, band: float, *, inward: bool = True) -> QImage:
    """Low-resolution alpha ramp that follows a rounded rectangle.

    ``inward=True`` is transparent on the border and opaque ``band`` pixels
    inside (used to feather media into the glass).  ``inward=False`` is the
    opposite: an opaque rim fading towards the centre (the liquid-glass lens).
    The ramp is soft by nature, so it is built at quarter resolution and
    scaled up when drawn; that keeps it cheap even while an island morphs.
    """
    scale = EDGE_SCALE
    w = max(4, int(round(width * scale)))
    h = max(4, int(round(height * scale)))
    r = round(max(0.0, radius) * scale, 1)
    b = round(max(0.5, band * scale), 1)
    key = ("edge", w, h, r, b, inward)

    def build() -> QImage:
        image = QImage(w, h, _FORMAT)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        full = QRectF(0, 0, w, h)
        painter.fillPath(glass_path(full, r), QColor(255, 255, 255, 0 if inward else 255))
        steps = max(3, min(18, int(math.ceil(b / 0.6))))
        for index in range(1, steps + 1):
            t = index / steps
            inset = b * t
            inner = full.adjusted(inset, inset, -inset, -inset)
            if inner.width() <= 0.5 or inner.height() <= 0.5:
                break
            ramp = _smoothstep(t)
            alpha = ramp if inward else 1.0 - ramp
            painter.fillPath(glass_path(inner, max(0.0, r - inset)), QColor(255, 255, 255, int(round(255 * alpha))))
        painter.end()
        return image

    return _cached_mask(key, build)


def rounded_mask(width: int, height: int, radius: float) -> QImage:
    """Full-resolution anti-aliased rounded-rectangle alpha mask (device px)."""
    key = ("round", int(width), int(height), round(radius, 1))

    def build() -> QImage:
        image = QImage(max(1, int(width)), max(1, int(height)), _FORMAT)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillPath(glass_path(QRectF(0, 0, width, height), radius), QColor(255, 255, 255))
        painter.end()
        return image

    return _cached_mask(key, build)


def apply_rounded_clip(painter: QPainter, device_width: int, device_height: int, radius_px: float,
                       target: QRectF) -> None:
    """Cut an anti-aliased rounded shape out of whatever *painter* drew."""
    painter.save()
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
    mask = rounded_mask(device_width, device_height, radius_px)
    painter.drawImage(target, mask, QRectF(mask.rect()))
    painter.restore()


def painter_ratio(painter: QPainter) -> float:
    device = painter.device()
    try:
        return max(1.0, float(device.devicePixelRatioF())) if device is not None else 1.0
    except (AttributeError, RuntimeError):
        return 1.0


class GlassCache:
    """One composed glass image per widget; reused until anything changes."""

    __slots__ = ("key", "image")

    def __init__(self) -> None:
        self.key = None
        self.image: QImage | None = None

    def clear(self) -> None:
        self.key = None
        self.image = None


def _clear_alpha(style: GlassStyle) -> float:
    d = _density01(style.density)
    return min(1.0, 0.16 + 0.60 * d + 0.10 * style.emphasis)


def _compose_glass(width: float, height: float, style: GlassStyle, canvas_rect: QRectF | None, ratio: float) -> QImage:
    device_w = max(1, int(math.ceil(width * ratio)))
    device_h = max(1, int(math.ceil(height * ratio)))
    image = QImage(device_w, device_h, _FORMAT)
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.GlobalColor.transparent)
    local = QRectF(0, 0, device_w / ratio, device_h / ratio)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    d = _density01(style.density)
    tint = QColor(style.tint)
    sample = None
    if style.material != "clear" and canvas_rect is not None:
        prov = provider()
        prov.ensure_ready()
        sample = prov.sample("liquid" if style.material == "liquid" else "frosted", canvas_rect)
    if sample is None:
        tint.setAlphaF(_clear_alpha(style) if style.material == "clear" else min(1.0, style.density * 0.94))
        painter.fillRect(local, tint)
        if style.material == "clear":
            top = QLinearGradient(local.topLeft(), local.bottomLeft())
            top.setColorAt(0.0, QColor(255, 255, 255, int(14 + 10 * style.emphasis)))
            top.setColorAt(0.5, QColor(255, 255, 255, 0))
            painter.fillRect(local, top)
    else:
        backdrop, source = sample
        painter.drawImage(local, backdrop, source)
        if style.material == "frosted":
            tint.setAlphaF(min(1.0, 0.14 + 0.46 * d + 0.08 * style.emphasis))
            painter.fillRect(local, tint)
            painter.fillRect(local, QColor(255, 255, 255, 9))
        else:
            tint.setAlphaF(min(1.0, 0.05 + 0.30 * d + 0.08 * style.emphasis))
            painter.fillRect(local, tint)
            # Lens rim: a magnified copy of the backdrop, faded in from the
            # edge, reads as light being bent by thick glass.
            band = max(6.0, min(16.0, min(local.width(), local.height()) * 0.2))
            mask = edge_mask(local.width(), local.height(), style.radius, band, inward=False)
            lens = QImage(mask.size(), _FORMAT)
            lens.fill(Qt.GlobalColor.transparent)
            lens_painter = QPainter(lens)
            lens_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            grow = 0.12
            src = QRectF(source)
            src.adjust(src.width() * grow / 2, src.height() * grow / 2, -src.width() * grow / 2, -src.height() * grow / 2)
            lens_painter.drawImage(QRectF(lens.rect()), backdrop, src)
            lens_painter.fillRect(QRectF(lens.rect()), QColor(255, 255, 255, 22))
            lens_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
            lens_painter.drawImage(0, 0, mask)
            lens_painter.end()
            painter.drawImage(local, lens, QRectF(lens.rect()))
            sheen = QLinearGradient(local.topLeft(), QPointF(local.left(), local.top() + local.height() * 0.55))
            sheen.setColorAt(0.0, QColor(255, 255, 255, 30))
            sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.fillRect(local, sheen)
            shade = QLinearGradient(QPointF(local.left(), local.bottom() - min(26.0, local.height() * 0.4)), local.bottomLeft())
            shade.setColorAt(0.0, QColor(0, 0, 0, 0))
            shade.setColorAt(1.0, QColor(0, 0, 0, 34))
            painter.fillRect(local, shade)
    apply_rounded_clip(painter, device_w, device_h, style.radius * ratio, local)
    painter.end()
    return image


def paint_glass_base(painter: QPainter, rect: QRectF, style: GlassStyle, canvas_origin: QPointF | None,
                     cache: GlassCache | None = None) -> None:
    """Fill *rect* with the material (backdrop sample + tint).

    The composed result is kept in *cache*; hovering or repainting children
    then costs one unscaled ``drawImage``.  Moving or resizing the island
    simply recomposes (about a millisecond).
    """
    ratio = painter_ratio(painter)
    canvas_rect = None
    if style.material != "clear" and canvas_origin is not None:
        canvas_rect = QRectF(canvas_origin.x() + rect.x(), canvas_origin.y() + rect.y(), rect.width(), rect.height())
    key = (
        style.material,
        round(rect.width(), 1), round(rect.height(), 1), round(style.radius, 1),
        QColor(style.tint).rgba(), round(float(style.density), 3), round(style.emphasis, 2),
        (round(canvas_rect.x()), round(canvas_rect.y())) if canvas_rect is not None else None,
        provider().version if canvas_rect is not None else 0,
        ratio,
    )
    image = None
    if cache is not None and cache.key == key and cache.image is not None:
        image = cache.image
    if image is None:
        image = _compose_glass(rect.width(), rect.height(), style, canvas_rect, ratio)
        if cache is not None:
            cache.key, cache.image = key, image
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.drawImage(rect.topLeft(), image)
    if style.hover > 0.01:
        painter.fillPath(glass_path(rect, style.radius), QColor(255, 255, 255, int(12 * style.hover)))
    painter.restore()


def paint_glass_rim(painter: QPainter, rect: QRectF, style: GlassStyle) -> None:
    """Hairline and specular highlights drawn above content backgrounds."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    hover, emphasis = style.hover, style.emphasis
    inner = rect.adjusted(0.6, 0.6, -0.6, -0.6)
    path = glass_path(inner, max(0.0, style.radius - 0.6))
    if style.material == "liquid":
        gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
        gradient.setColorAt(0.0, QColor(255, 255, 255, int(150 + 60 * hover + 40 * emphasis)))
        gradient.setColorAt(0.35, QColor(255, 255, 255, int(34 + 20 * hover)))
        gradient.setColorAt(0.65, QColor(255, 255, 255, int(22 + 20 * hover)))
        gradient.setColorAt(1.0, QColor(255, 255, 255, int(96 + 50 * hover + 30 * emphasis)))
        painter.setPen(QPen(QBrush(gradient), 1.3))
        painter.drawPath(path)
        painter.setPen(QPen(QColor(255, 255, 255, int(20 + 16 * hover)), 1.0))
        painter.drawPath(glass_path(rect.adjusted(2.2, 2.2, -2.2, -2.2), max(0.0, style.radius - 2.2)))
    elif style.material == "frosted":
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, QColor(255, 255, 255, int(70 + 50 * hover + 40 * emphasis)))
        gradient.setColorAt(1.0, QColor(255, 255, 255, int(20 + 26 * hover + 20 * emphasis)))
        painter.setPen(QPen(QBrush(gradient), 1.0))
        painter.drawPath(path)
    else:
        painter.setPen(QPen(QColor(255, 255, 255, int(30 + 42 * hover + 40 * emphasis)), 1.0))
        painter.drawPath(path)
    painter.restore()


__all__ = [
    "BackdropProvider",
    "GlassCache",
    "GlassStyle",
    "apply_rounded_clip",
    "edge_mask",
    "painter_ratio",
    "rounded_mask",
    "MATERIAL_LABELS",
    "MATERIAL_ORDER",
    "blur_image",
    "glass_path",
    "load_image_scaled",
    "paint_demo_background",
    "paint_glass_base",
    "paint_glass_rim",
    "provider",
    "saturate_image",
]

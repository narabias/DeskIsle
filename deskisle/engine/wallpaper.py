"""Wallpaper source for the liquid glass (static picture or live capture).

Every monitor gets one *sharp* backdrop image (about half the monitor
resolution).  QML blurs it on the GPU (``MultiEffect``) and the glass shader
samples both textures in monitor space, so every island refracts exactly the
wallpaper that is behind it.

Sources
-------
* **live** (default): the Explorer wallpaper window (``WorkerW``) is rendered
  with ``PrintWindow(PW_RENDERFULLCONTENT)`` a few times per second.  This
  also sees dynamic wallpapers (Wallpaper Engine, Lively, video wallpapers)
  because they draw into that window.  DeskIsle's own layer is *not* part of
  that window, so there is no feedback loop.  Unchanged frames slow the
  capture down; black frames (unsupported systems) fall back to static.
* **static**: the wallpaper file from the Windows settings, placed like
  Windows does (fill / fit / stretch / tile / center / span).
* **image**: a picture chosen in the settings; **solid**: a flat colour.

The accent colour of the whole UI is derived from the wallpaper only.
"""

from __future__ import annotations

import colorsys
import os
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter
from PySide6.QtQuick import QQuickImageProvider

from .. import native_win

IS_WINDOWS = sys.platform == "win32"
# Longest edge of the backdrop texture handed to QML.
TEXTURE_EDGE = 1280
# Capture pacing (ms): fastest while the wallpaper moves, slowest when idle.
LIVE_MIN_INTERVAL = 90
LIVE_IDLE_INTERVAL = 2000


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


def cover_source(image_size, target_size) -> QRectF:
    """Part of an image of *image_size* that cover-fits *target_size* (centred)."""
    iw, ih = float(image_size.width()), float(image_size.height())
    tw, th = max(1e-3, float(target_size.width())), max(1e-3, float(target_size.height()))
    if iw <= 0 or ih <= 0:
        return QRectF(0, 0, max(1.0, iw), max(1.0, ih))
    scale = max(tw / iw, th / ih)
    w, h = tw / scale, th / scale
    return QRectF((iw - w) / 2.0, (ih - h) / 2.0, w, h)
STATIC_POLL_MS = 5000
DEFAULT_ACCENT = QColor("#5AA9FF")


@dataclass
class MonitorTarget:
    """Where a monitor is, in physical pixels of the virtual screen."""

    key: str
    rect: QRect            # physical pixels (virtual screen coordinates)
    logical: QRect          # Qt logical geometry (board space before offset)


# ---------------------------------------------------------------------------
# Image helpers (pure Qt, testable off Windows)
# ---------------------------------------------------------------------------

def texture_size(width: int, height: int, edge: int = TEXTURE_EDGE) -> QSize:
    width, height = max(1, int(width)), max(1, int(height))
    scale = min(1.0, float(edge) / max(width, height))
    return QSize(max(1, round(width * scale)), max(1, round(height * scale)))


def compose_wallpaper(image: QImage, style: str, color: str, monitor: QRect, virtual: QRect,
                      target: QSize) -> QImage:
    """Render the part of the desktop wallpaper that ``monitor`` shows.

    ``monitor`` and ``virtual`` are physical pixel rectangles; the result has
    ``target`` size (the monitor scaled down) and is always opaque.
    """
    out = QImage(target, QImage.Format.Format_RGB32)
    out.fill(QColor(color or "#000000"))
    if image is None or image.isNull() or monitor.width() <= 0 or monitor.height() <= 0:
        return out
    sx = target.width() / float(monitor.width())
    sy = target.height() / float(monitor.height())
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    iw, ih = image.width(), image.height()
    mw, mh = monitor.width(), monitor.height()
    if style == "span" and virtual.width() > 0 and virtual.height() > 0:
        # One picture across all monitors (cover-fit to the virtual screen).
        src = cover_source(image.size(), virtual.size())
        fx = src.width() / virtual.width()
        fy = src.height() / virtual.height()
        part = (src.x() + (monitor.x() - virtual.x()) * fx, src.y() + (monitor.y() - virtual.y()) * fy,
                mw * fx, mh * fy)
        painter.drawImage(QRectF(0, 0, target.width(), target.height()), image, QRectF(*part))
    elif style == "tile":
        tile = image.scaled(max(1, round(iw * sx)), max(1, round(ih * sy)),
                            Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
        for y in range(0, target.height(), max(1, tile.height())):
            for x in range(0, target.width(), max(1, tile.width())):
                painter.drawImage(QPoint(x, y), tile)
    else:
        if style == "stretch":
            painter.drawImage(QRectF(0, 0, target.width(), target.height()), image)
        elif style == "fit":
            scale = min(mw / iw, mh / ih)
            w, h = iw * scale * sx, ih * scale * sy
            painter.drawImage(QRectF((target.width() - w) / 2, (target.height() - h) / 2, w, h), image)
        elif style == "center":
            w, h = iw * sx, ih * sy
            painter.drawImage(QRectF((target.width() - w) / 2, (target.height() - h) / 2, w, h), image)
        else:  # fill (default)
            src = cover_source(image.size(), QSize(mw, mh))
            painter.drawImage(QRectF(0, 0, target.width(), target.height()), image, src)
    painter.end()
    return out


def fingerprint(image: QImage) -> bytes:
    """Tiny grey thumbnail used to notice whether a live frame changed."""
    if image is None or image.isNull():
        return b""
    tiny = image.scaled(24, 14, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.FastTransformation).convertToFormat(QImage.Format.Format_Grayscale8)
    return bytes(tiny.constBits())[: tiny.bytesPerLine() * tiny.height()]


def frame_difference(a: bytes, b: bytes) -> float:
    if not a or not b or len(a) != len(b):
        return 255.0
    return sum(abs(x - y) for x, y in zip(a, b)) / float(len(a))


def is_black(image: QImage) -> bool:
    """PrintWindow returns an all-black (or empty) frame when it cannot render."""
    if image is None or image.isNull():
        return True
    tiny = image.scaled(16, 9, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.FastTransformation)
    for y in range(tiny.height()):
        for x in range(tiny.width()):
            c = tiny.pixelColor(x, y)
            if max(c.red(), c.green(), c.blue()) > 6:
                return False
    return True


def accent_of(image: QImage) -> tuple[QColor, float]:
    """Dominant vivid colour of a picture and its mean luminance (0..1).

    Pixels vote for one of 36 hue buckets, weighted by saturation and by how
    far they are from black/white; the winning bucket's average colour is the
    accent.  Grey pictures fall back to a calm blue derived from their tone.
    """
    if image is None or image.isNull():
        return QColor(DEFAULT_ACCENT), 0.35
    tiny = image.scaled(64, 36, Qt.AspectRatioMode.IgnoreAspectRatio,
                        Qt.TransformationMode.SmoothTransformation).convertToFormat(QImage.Format.Format_RGB32)
    buckets = [[0.0, 0.0, 0.0, 0.0] for _ in range(36)]
    luminance = 0.0
    count = 0
    for y in range(tiny.height()):
        for x in range(tiny.width()):
            c = tiny.pixelColor(x, y)
            r, g, b = c.redF(), c.greenF(), c.blueF()
            luminance += 0.2126 * r + 0.7152 * g + 0.0722 * b
            count += 1
            h, s, v = colorsys.rgb_to_hsv(r, g, b)
            weight = s * s * (1.0 - abs(v - 0.62) * 1.25)
            if weight <= 0.02:
                continue
            bucket = buckets[int(h * 36) % 36]
            bucket[0] += weight
            bucket[1] += r * weight
            bucket[2] += g * weight
            bucket[3] += b * weight
    mean = luminance / max(1, count)
    # Smooth neighbouring buckets so a hue split across two buckets still wins.
    scores = [buckets[i][0] + 0.5 * (buckets[i - 1][0] + buckets[(i + 1) % 36][0]) for i in range(36)]
    best = max(range(36), key=lambda i: scores[i])
    total = buckets[best][0]
    if total < 0.6:
        return QColor.fromHslF(0.58, 0.45, 0.58), mean
    r, g, b = (buckets[best][1] / total, buckets[best][2] / total, buckets[best][3] / total)
    return QColor.fromRgbF(min(1.0, r), min(1.0, g), min(1.0, b)), mean


def tune_accent(color: QColor, dark: bool) -> QColor:
    """Make the wallpaper colour usable as a UI accent on dark/light glass."""
    h, s, l, _a = color.getHslF()
    h = 0.58 if h < 0 else h
    s = max(0.42, min(0.86, s * 1.15 + 0.08))
    l = 0.66 if dark else 0.46
    return QColor.fromHslF(h, s, l)


def solid_image(color: str, size: QSize = QSize(64, 36)) -> QImage:
    out = QImage(size, QImage.Format.Format_RGB32)
    out.fill(QColor(color))
    return out


# ---------------------------------------------------------------------------
# Windows capture
# ---------------------------------------------------------------------------

class _WinCapture:
    """PrintWindow capture of the wallpaper window (Windows only)."""

    PW_RENDERFULLCONTENT = 0x2

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ctypes = ctypes
        self.wintypes = wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        u, g = self.user32, self.gdi32
        u.GetDC.restype = wintypes.HDC
        u.GetDC.argtypes = [wintypes.HWND]
        u.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
        u.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
        u.PrintWindow.restype = wintypes.BOOL
        u.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        u.IsWindow.argtypes = [wintypes.HWND]
        u.IsWindowVisible.argtypes = [wintypes.HWND]
        u.FindWindowW.restype = wintypes.HWND
        u.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
        u.FindWindowExW.restype = wintypes.HWND
        u.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
        g.CreateCompatibleDC.restype = wintypes.HDC
        g.CreateCompatibleDC.argtypes = [wintypes.HDC]
        g.DeleteDC.argtypes = [wintypes.HDC]
        g.SelectObject.restype = wintypes.HGDIOBJ
        g.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
        g.DeleteObject.argtypes = [wintypes.HGDIOBJ]
        g.CreateDIBSection.restype = wintypes.HBITMAP
        g.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.c_void_p, wintypes.UINT,
                                       ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
        g.GdiFlush.restype = wintypes.BOOL

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        self.BITMAPINFOHEADER = BITMAPINFOHEADER
        self._dib = None  # (hdc, hbmp, old, bits, w, h)

    def wallpaper_window(self) -> int:
        """The window that draws the wallpaper (24H2: child of Progman)."""
        try:
            windows = native_win._find_desktop_windows(spawn_worker=True)  # noqa: SLF001 - shared helper
        except Exception:
            return 0
        if windows.background_worker:
            return int(windows.background_worker)
        progman = windows.progman or int(self.user32.FindWindowW("Progman", None) or 0)
        if progman:
            child = self.user32.FindWindowExW(progman, None, "WorkerW", None)
            if child:
                return int(child)
            return 0
        return 0

    def _release_dib(self) -> None:
        if self._dib is None:
            return
        hdc, hbmp, old, _bits, _w, _h = self._dib
        try:
            self.gdi32.SelectObject(hdc, old)
            self.gdi32.DeleteObject(hbmp)
            self.gdi32.DeleteDC(hdc)
        except Exception:
            pass
        self._dib = None

    def _ensure_dib(self, w: int, h: int):
        if self._dib is not None and self._dib[4] == w and self._dib[5] == h:
            return self._dib
        self._release_dib()
        ctypes = self.ctypes
        screen = self.user32.GetDC(None)
        hdc = self.gdi32.CreateCompatibleDC(screen)
        self.user32.ReleaseDC(None, screen)
        header = self.BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(self.BITMAPINFOHEADER)
        header.biWidth = w
        header.biHeight = -h  # top-down
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0
        buffer = (ctypes.c_byte * (ctypes.sizeof(self.BITMAPINFOHEADER) + 16))()
        ctypes.memmove(buffer, ctypes.byref(header), ctypes.sizeof(header))
        bits = ctypes.c_void_p()
        hbmp = self.gdi32.CreateDIBSection(hdc, buffer, 0, ctypes.byref(bits), None, 0)
        if not hbmp or not bits.value:
            self.gdi32.DeleteDC(hdc)
            return None
        old = self.gdi32.SelectObject(hdc, hbmp)
        self._dib = (hdc, hbmp, old, bits, w, h)
        return self._dib

    def capture(self, targets: list[MonitorTarget], sizes: dict[str, QSize]) -> dict[str, QImage]:
        hwnd = self.wallpaper_window()
        if not hwnd or not self.user32.IsWindow(hwnd):
            return {}
        rect = self.wintypes.RECT()
        if not self.user32.GetWindowRect(hwnd, self.ctypes.byref(rect)):
            return {}
        w, h = int(rect.right - rect.left), int(rect.bottom - rect.top)
        if w <= 0 or h <= 0 or w * h > 16000 * 9000:
            return {}
        dib = self._ensure_dib(w, h)
        if dib is None:
            return {}
        hdc, _hbmp, _old, bits, _w, _h = dib
        if not self.user32.PrintWindow(hwnd, hdc, self.PW_RENDERFULLCONTENT):
            return {}
        self.gdi32.GdiFlush()
        raw = (self.ctypes.c_char * (w * h * 4)).from_address(bits.value)
        frame = QImage(raw, w, h, w * 4, QImage.Format.Format_RGB32)
        out: dict[str, QImage] = {}
        for target in targets:
            part = QRect(target.rect.x() - rect.left, target.rect.y() - rect.top,
                         target.rect.width(), target.rect.height()).intersected(QRect(0, 0, w, h))
            if part.isEmpty():
                continue
            size = sizes.get(target.key) or texture_size(part.width(), part.height())
            out[target.key] = frame.copy(part).scaled(size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                                       Qt.TransformationMode.SmoothTransformation)
        return out

    def close(self) -> None:
        self._release_dib()


# ---------------------------------------------------------------------------
# QML image provider
# ---------------------------------------------------------------------------

class WallImageProvider(QQuickImageProvider):
    """``image://wall/<monitor key>/<revision>`` -> current backdrop image."""

    def __init__(self, service: "WallpaperService") -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._service = service

    def requestImage(self, image_id: str, size, requested_size):  # noqa: N802 - Qt API
        from .icons import WARMUP_ID, warmup_image

        if image_id.startswith(WARMUP_ID):
            return warmup_image(size)
        key = image_id.rsplit("/", 1)[0] if "/" in image_id else image_id
        from urllib.parse import unquote
        image = self._service.image(unquote(key))
        try:
            size.setWidth(image.width())
            size.setHeight(image.height())
        except Exception:
            pass
        return image


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class WallpaperService(QObject):
    """Keeps one backdrop image per monitor up to date."""

    updated = Signal(str)          # monitor key
    accentChanged = Signal()
    liveStatusChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._lock = threading.Lock()
        self._images: dict[str, QImage] = {}
        self._revisions: dict[str, int] = {}
        self._prints: dict[str, bytes] = {}
        self._targets: list[MonitorTarget] = []
        self._virtual = QRect()
        self._mode = "live"            # live | static | image | solid
        self._image_path = ""
        self._solid = "#1C222B"
        self._max_fps = 8
        self._paused = False
        self._accent = QColor(DEFAULT_ACCENT)
        self._luminance = 0.35
        self._static_key: tuple = ()
        self._static_source = QImage()
        self._black_frames = 0
        self.live_supported = IS_WINDOWS
        self.live_status = ""          # human readable (settings page)
        self._capture = None
        self._interval = LIVE_MIN_INTERVAL
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._tick)
        self._demo = os.environ.get("DESKISLE_DEMO_WALLPAPER", "")

    # Configuration --------------------------------------------------------------
    def configure(self, mode: str = "live", image_path: str = "", solid: str = "#1C222B", max_fps: int = 8) -> None:
        mode = mode if mode in ("live", "static", "image", "solid") else "live"
        changed = (mode, image_path, solid) != (self._mode, self._image_path, self._solid)
        self._mode, self._image_path, self._solid = mode, image_path, solid
        self._max_fps = max(1, min(30, int(max_fps or 8)))
        if changed:
            self._static_key = ()
            self._black_frames = 0
            self.refresh()

    def set_monitors(self, targets: list[MonitorTarget]) -> None:
        self._targets = list(targets)
        virtual = QRect()
        for target in self._targets:
            virtual = virtual.united(target.rect)
        self._virtual = virtual
        self._static_key = ()
        self.refresh()

    def set_paused(self, paused: bool) -> None:
        """Smart pause: nobody sees the desktop (fullscreen app, locked...)."""
        paused = bool(paused)
        if paused == self._paused:
            return
        self._paused = paused
        if not paused:
            self._schedule(30)

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def effective_mode(self) -> str:
        if self._mode == "live" and not self.live_supported:
            return "static"
        return self._mode

    def accent(self) -> QColor:
        return QColor(self._accent)

    def luminance(self) -> float:
        return self._luminance

    def revision(self, key: str) -> int:
        return self._revisions.get(key, 0)

    def image(self, key: str) -> QImage:
        with self._lock:
            image = self._images.get(key)
            if image is None and self._images:
                image = next(iter(self._images.values()))
        return image if image is not None else solid_image(self._solid)

    def source_url(self, key: str) -> str:
        from urllib.parse import quote
        return "image://wall/{0}/{1}".format(quote(key, safe=""), self.revision(key))

    # Work -----------------------------------------------------------------------
    def refresh(self) -> None:
        self._static_key = ()
        self._schedule(0)

    def _schedule(self, delay: int) -> None:
        self._timer.start(max(0, int(delay)))

    def _sizes(self) -> dict[str, QSize]:
        return {t.key: texture_size(t.rect.width(), t.rect.height()) for t in self._targets}

    def _tick(self) -> None:
        if not self._targets:
            return
        mode = self.effective_mode
        if mode == "live" and not self._paused:
            if self._live_frame():
                return
        self._static_frame(mode)
        self._schedule(STATIC_POLL_MS)

    def _live_frame(self) -> bool:
        started = time.perf_counter()
        try:
            if self._capture is None:
                self._capture = _WinCapture()
            frames = self._capture.capture(self._targets, self._sizes())
        except Exception as exc:  # pragma: no cover - Windows only
            frames = {}
            self.live_status = "动态壁纸读取失败：{0}".format(exc)
        if not frames or all(is_black(image) for image in frames.values()):
            self._black_frames += 1
            if self._black_frames >= 4:
                self.live_supported = False
                self.live_status = "这台电脑无法读取动态壁纸，已改用静态壁纸。"
                self.liveStatusChanged.emit()
                return False
            self._schedule(400)
            return True
        self._black_frames = 0
        if self.live_status:
            self.live_status = ""
            self.liveStatusChanged.emit()
        changed_any = False
        for key, image in frames.items():
            print_ = fingerprint(image)
            if frame_difference(print_, self._prints.get(key, b"")) < 0.6 and key in self._images:
                continue
            self._prints[key] = print_
            self._store(key, image)
            changed_any = True
        cost = (time.perf_counter() - started) * 1000.0
        floor = max(LIVE_MIN_INTERVAL, int(1000 / self._max_fps), int(cost * 4))
        if changed_any:
            self._interval = floor
            self._update_accent()
        else:
            self._interval = min(LIVE_IDLE_INTERVAL, max(floor, int(self._interval * 1.6)))
        self._schedule(self._interval)
        return True

    def _static_picture(self, mode: str) -> tuple[QImage, str, str, tuple]:
        if mode == "solid":
            return QImage(), "fill", self._solid, ("solid", self._solid)
        if mode == "image" and self._image_path:
            path, style, color = self._image_path, "fill", "#000000"
        elif self._demo:
            path, style, color = self._demo, "fill", "#000000"
        else:
            info = native_win.get_wallpaper_info()
            path, style, color = info.get("path", ""), info.get("style", "fill"), info.get("color", "#000000")
        try:
            stamp = os.path.getmtime(path) if path else 0
        except OSError:
            stamp = 0
        key = (mode, path, style, color, stamp)
        if key == self._static_key:
            return self._static_source, style, color, key
        image = QImage()
        if path:
            biggest = max((t.rect.width() for t in self._targets), default=1920)
            image = load_image_scaled(path, QSize(biggest * 2, biggest * 2))
        if image.isNull() and not path and not IS_WINDOWS:
            image = _demo_gradient()
        self._static_source = image
        return image, style, color, key

    def _static_frame(self, mode: str) -> None:
        image, style, color, key = self._static_picture(mode)
        if key == self._static_key and all(t.key in self._images for t in self._targets):
            return
        self._static_key = key
        sizes = self._sizes()
        for target in self._targets:
            self._store(target.key, compose_wallpaper(image, style, color, target.rect, self._virtual,
                                                      sizes[target.key]))
        self._update_accent()

    def _store(self, key: str, image: QImage) -> None:
        with self._lock:
            self._images[key] = image
        self._revisions[key] = self._revisions.get(key, 0) + 1
        self.updated.emit(key)

    def _update_accent(self) -> None:
        primary = self._targets[0].key if self._targets else ""
        image = self._images.get(primary)
        if image is None:
            return
        accent, lum = accent_of(image)
        if accent.rgb() != self._accent.rgb() or abs(lum - self._luminance) > 0.02:
            # Live wallpapers change constantly: only follow clear changes.
            h1, s1, l1, _ = accent.getHslF()
            h0, s0, l0, _ = self._accent.getHslF()
            if abs(h1 - h0) > 0.03 or abs(s1 - s0) > 0.08 or abs(l1 - l0) > 0.08 or abs(lum - self._luminance) > 0.05:
                self._accent, self._luminance = accent, lum
                self.accentChanged.emit()

    def shutdown(self) -> None:
        self._timer.stop()
        if self._capture is not None:
            try:
                self._capture.close()
            except Exception:
                pass
            self._capture = None


def _demo_gradient() -> QImage:
    """Development backdrop off Windows (no wallpaper API)."""
    from PySide6.QtGui import QLinearGradient, QRadialGradient
    image = QImage(1600, 900, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    gradient = QLinearGradient(0, 0, 1600, 900)
    gradient.setColorAt(0.0, QColor("#1E3C72"))
    gradient.setColorAt(0.55, QColor("#2A5298"))
    gradient.setColorAt(1.0, QColor("#E96443"))
    painter.fillRect(image.rect(), gradient)
    for cx, cy, r, c in ((360, 260, 380, "#7F7FD5"), (1240, 640, 460, "#F7B267"), (900, 180, 260, "#43C6AC")):
        radial = QRadialGradient(cx, cy, r)
        col = QColor(c)
        col.setAlphaF(0.75)
        radial.setColorAt(0.0, col)
        col.setAlphaF(0.0)
        radial.setColorAt(1.0, col)
        painter.fillRect(image.rect(), radial)
    painter.end()
    return image


__all__ = [
    "MonitorTarget", "WallImageProvider", "WallpaperService", "accent_of", "compose_wallpaper",
    "fingerprint", "frame_difference", "is_black", "solid_image", "texture_size", "tune_accent",
]

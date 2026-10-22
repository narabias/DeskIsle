"""``image://icon/<quoted path>?s=<px>`` - file icons and thumbnails for QML.

Windows: ``IShellItemImageFactory`` (the same icons/thumbnails Explorer
shows, including shortcut overlays) called from QML's image loader thread.
Elsewhere (development/demo) simple generated icons are drawn.
"""

from __future__ import annotations

import os
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQml import QQmlImageProviderBase

IS_WINDOWS = sys.platform == "win32"
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".jfif", ".tif", ".tiff"}
_CACHE_LIMIT = 900


def parse_id(icon_id: str) -> tuple[str, int]:
    path, _sep, query = icon_id.partition("?")
    size = 48
    for part in query.split("&"):
        if part.startswith("s="):
            try:
                size = max(16, min(256, int(part[2:])))
            except ValueError:
                pass
    return unquote(path), size


class _ShellIcons:
    """ctypes wrapper around SHCreateItemFromParsingName + IShellItemImageFactory."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes

        self.ct = ctypes
        self.wt = wintypes
        self._local = threading.local()
        self.shell32 = ctypes.WinDLL("shell32", use_last_error=True)
        self.ole32 = ctypes.WinDLL("ole32")
        self.gdi32 = ctypes.WinDLL("gdi32")

        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                        ("Data4", ctypes.c_ubyte * 8)]

        class SIZE(ctypes.Structure):
            _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

        class BITMAP(ctypes.Structure):
            _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG), ("bmHeight", wintypes.LONG),
                        ("bmWidthBytes", wintypes.LONG), ("bmPlanes", wintypes.WORD),
                        ("bmBitsPixel", wintypes.WORD), ("bmBits", ctypes.c_void_p)]

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]

        self.GUID, self.SIZE, self.BITMAP, self.BIH = GUID, SIZE, BITMAP, BITMAPINFOHEADER
        import uuid

        raw = uuid.UUID("bcc18b79-ba16-442f-80c4-8a59c30c463b").bytes_le
        self.iid = GUID.from_buffer_copy(raw)
        self.shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p,
                                                             ctypes.POINTER(GUID),
                                                             ctypes.POINTER(ctypes.c_void_p)]
        self.shell32.SHCreateItemFromParsingName.restype = ctypes.c_long
        self.get_image = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, SIZE, ctypes.c_int,
                                            ctypes.POINTER(wintypes.HBITMAP))
        self.release = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
        self.gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
        self.gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
                                         ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
        self.gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
        self.user32 = ctypes.WinDLL("user32")
        self.user32.GetDC.restype = wintypes.HDC
        self.user32.GetDC.argtypes = [wintypes.HWND]
        self.user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

    def _com(self) -> None:
        if not getattr(self._local, "init", False):
            self.ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
            self._local.init = True

    def image(self, path: str, size: int) -> QImage | None:
        ct, wt = self.ct, self.wt
        self._com()
        unk = ct.c_void_p()
        hr = self.shell32.SHCreateItemFromParsingName(path, None, ct.byref(self.iid), ct.byref(unk))
        if hr < 0 or not unk.value:
            return None
        try:
            vtbl = ct.cast(ct.cast(unk, ct.POINTER(ct.c_void_p))[0], ct.POINTER(ct.c_void_p))
            get_image = self.get_image(vtbl[3])
            hbmp = wt.HBITMAP()
            # SIIGBF_BIGGERSIZEOK: thumbnails for pictures, icons otherwise.
            hr = get_image(unk, self.SIZE(size, size), 0x1, ct.byref(hbmp))
            if hr < 0 or not hbmp:
                return None
            try:
                return self._to_qimage(hbmp)
            finally:
                self.gdi32.DeleteObject(hbmp)
        finally:
            self.release(vtbl[2])(unk)

    def _to_qimage(self, hbmp) -> QImage | None:
        ct = self.ct
        bm = self.BITMAP()
        if not self.gdi32.GetObjectW(hbmp, ct.sizeof(bm), ct.byref(bm)):
            return None
        width, height = bm.bmWidth, abs(bm.bmHeight)
        if width <= 0 or height <= 0:
            return None
        header = self.BIH()
        header.biSize = ct.sizeof(header)
        header.biWidth = width
        header.biHeight = -height
        header.biPlanes = 1
        header.biBitCount = 32
        buffer = (ct.c_ubyte * (width * height * 4))()
        hdc = self.user32.GetDC(None)
        try:
            lines = self.gdi32.GetDIBits(hdc, hbmp, 0, height, buffer, ct.byref(header), 0)
        finally:
            self.user32.ReleaseDC(None, hdc)
        if lines != height:
            return None
        data = bytes(buffer)
        # Some icons come without alpha (all zero) -> treat as opaque.
        has_alpha = any(data[i] for i in range(3, len(data), 4 * 7))
        fmt = QImage.Format.Format_ARGB32_Premultiplied if has_alpha else QImage.Format.Format_RGB32
        return QImage(data, width, height, width * 4, fmt).copy()


# Generated icons ---------------------------------------------------------------------------
_TYPE_COLORS = {
    "folder": ("#F6C453", "#E9A923"), "image": ("#5EC8F2", "#2F8FD6"), "doc": ("#5B8DEF", "#3463C9"),
    "sheet": ("#4CC38A", "#21955E"), "slide": ("#F08A5D", "#D25B2B"), "pdf": ("#F2626B", "#C9343F"),
    "archive": ("#B38CF2", "#7E57C2"), "media": ("#F25FA8", "#C2337D"), "code": ("#7A8699", "#4B5565"),
    "app": ("#62D2C3", "#2A9D8F"), "link": ("#8FA3BF", "#5D718F"), "file": ("#C9CED6", "#9AA3AF"),
}
_EXT_TYPES = {
    "image": IMAGE_EXT, "doc": {".doc", ".docx", ".txt", ".md", ".rtf", ".odt"},
    "sheet": {".xls", ".xlsx", ".csv", ".ods"}, "slide": {".ppt", ".pptx", ".key", ".odp"},
    "pdf": {".pdf"}, "archive": {".zip", ".rar", ".7z", ".gz", ".tar"},
    "media": {".mp3", ".mp4", ".wav", ".flac", ".mkv", ".mov", ".avi"},
    "code": {".py", ".js", ".ts", ".html", ".css", ".json", ".c", ".cpp", ".cs", ".java"},
    "app": {".exe", ".msi", ".bat", ".cmd", ".appref-ms"}, "link": {".lnk", ".url", ".website"},
}


def file_type(path: str) -> str:
    try:
        if os.path.isdir(path):
            return "folder"
    except OSError:
        pass
    ext = os.path.splitext(path)[1].casefold()
    for name, exts in _EXT_TYPES.items():
        if ext in exts:
            return name
    return "file"


def generated_icon(path: str, size: int) -> QImage:
    kind = file_type(path)
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    top, bottom = _TYPE_COLORS.get(kind, _TYPE_COLORS["file"])
    if kind == "image" and os.path.isfile(path):
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        src = reader.size()
        if src.isValid() and src.width() > 0:
            scale = (s * 0.86) / max(src.width(), src.height())
            reader.setScaledSize(QSize(max(1, int(src.width() * scale)), max(1, int(src.height() * scale))))
        thumb = reader.read()
        if not thumb.isNull():
            x = (s - thumb.width()) / 2
            y = (s - thumb.height()) / 2
            frame = QPainterPath()
            frame.addRoundedRect(QRectF(x - 2, y - 2, thumb.width() + 4, thumb.height() + 4), 4, 4)
            p.fillPath(frame, QColor(255, 255, 255, 235))
            p.drawImage(int(x), int(y), thumb)
            p.end()
            return image
    grad = QLinearGradient(0, 0, 0, s)
    grad.setColorAt(0, QColor(top))
    grad.setColorAt(1, QColor(bottom))
    if kind == "folder":
        back = QPainterPath()
        back.addRoundedRect(QRectF(s * .08, s * .18, s * .84, s * .66), s * .08, s * .08)
        tab = QPainterPath()
        tab.addRoundedRect(QRectF(s * .08, s * .12, s * .36, s * .16), s * .05, s * .05)
        p.fillPath(back.united(tab), QColor(bottom))
        front = QPainterPath()
        front.addRoundedRect(QRectF(s * .08, s * .30, s * .84, s * .56), s * .08, s * .08)
        p.fillPath(front, grad)
    else:
        page = QPainterPath()
        page.addRoundedRect(QRectF(s * .18, s * .08, s * .64, s * .84), s * .08, s * .08)
        p.fillPath(page, QColor(250, 251, 253))
        p.setPen(QPen(QColor(0, 0, 0, 30), max(1.0, s / 64)))
        p.drawPath(page)
        band = QPainterPath()
        band.addRoundedRect(QRectF(s * .18, s * .56, s * .64, s * .36), s * .08, s * .08)
        p.fillPath(band, grad)
        ext = os.path.splitext(path)[1].lstrip(".").upper()[:4] or kind.upper()[:4]
        font = QFont()
        font.setBold(True)
        font.setPixelSize(max(6, int(s * .15)))
        p.setFont(font)
        p.setPen(QColor("white"))
        p.drawText(QRectF(s * .18, s * .56, s * .64, s * .36), Qt.AlignmentFlag.AlignCenter, ext)
        if kind == "link":
            p.setPen(QPen(QColor(bottom), s / 18))
            p.drawLine(int(s * .34), int(s * .42), int(s * .62), int(s * .22))
    p.end()
    return image


class IconProvider(QQuickImageProvider):
    """Synchronous provider; QML loads it off-thread with ``asynchronous: true``."""

    def __init__(self) -> None:
        super().__init__(QQmlImageProviderBase.ImageType.Image,
                         QQmlImageProviderBase.Flag.ForceAsynchronousImageLoading)
        self._cache: OrderedDict = OrderedDict()
        self._lock = threading.Lock()
        self._shell = None
        if IS_WINDOWS:
            try:
                self._shell = _ShellIcons()
            except (OSError, AttributeError):
                self._shell = None

    def invalidate(self, path: str | None = None) -> None:
        with self._lock:
            if path is None:
                self._cache.clear()
            else:
                key = os.path.normcase(path)
                for cached in [k for k in self._cache if k[0] == key]:
                    self._cache.pop(cached, None)

    def requestImage(self, icon_id, size, requested_size):  # noqa: N802 - Qt API
        if icon_id.startswith(WARMUP_ID):
            return warmup_image(size)
        path, px = parse_id(icon_id)
        # Python callers (drag pixmaps, tests) may pass None for both sizes.
        if requested_size is not None and requested_size.isValid() and requested_size.width() > 0:
            px = max(16, min(256, max(requested_size.width(), requested_size.height())))
        try:
            mtime = int(os.stat(path).st_mtime) if os.path.splitext(path)[1].casefold() in IMAGE_EXT else 0
        except OSError:
            mtime = -1
        key = (os.path.normcase(path), px, mtime)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
        if cached is None:
            cached = self._load(path, px)
            with self._lock:
                self._cache[key] = cached
                while len(self._cache) > _CACHE_LIMIT:
                    self._cache.popitem(last=False)
        if size is not None:
            try:
                size.setWidth(cached.width())
                size.setHeight(cached.height())
            except AttributeError:
                pass
        return cached

    def _load(self, path: str, px: int) -> QImage:
        image = None
        if self._shell is not None and path:
            try:
                image = self._shell.image(path, px)
            except OSError:
                image = None
        if image is None or image.isNull():
            image = generated_icon(path, px)
        return image


# ---------------------------------------------------------------------------
# Deadlock guard for Python image providers
# ---------------------------------------------------------------------------
#
# Qt's QQuickPixmapReader thread calls the *virtual* ``imageType()`` of a provider
# while it holds its job mutex (qquickpixmapcache.cpp, processJobs).  For a Python
# provider the first such call goes through PySide's override check, which needs
# the GIL.  If the GUI thread holds the GIL at that moment - it always does while
# QML objects are being created from Python - and queues one more asynchronous
# image, it blocks on the same mutex: both threads wait for each other forever
# (seen as a frozen start-up with many icons).  PySide caches "no Python override"
# after the first call, so it is enough to let every provider answer once while
# nothing else is loading.  ``prime_image_providers`` does that before any window
# exists: a synchronous load runs ``imageType()`` on the GUI thread; providers
# with ForceAsynchronousImageLoading are loaded on the reader thread while the
# GUI thread waits *without* the GIL.

WARMUP_ID = "__deskisle_warmup__"


def warmup_image(size=None) -> QImage:
    image = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    if size is not None:
        try:
            size.setWidth(1)
            size.setHeight(1)
        except AttributeError:
            pass
    return image


def prime_image_providers(engine, names, timeout_s: float = 5.0) -> list[str]:
    """Load one tiny image from every named provider; returns the names that did not answer."""
    import logging
    import time

    from PySide6.QtCore import QCoreApplication, QEventLoop, QUrl
    from PySide6.QtQml import QQmlComponent

    log = logging.getLogger("deskisle.icons")
    late: list[str] = []
    for name in dict.fromkeys(names):
        component = QQmlComponent(engine)
        component.setData(('import QtQuick\nImage {{ asynchronous: false; cache: false; '
                           'source: "image://{0}/{1}"; readonly property bool waiting: status === Image.Loading }}\n')
                          .format(name, WARMUP_ID).encode("utf-8"), QUrl())
        item = component.create()
        if item is None:
            log.warning("image provider %s: warm-up failed: %s", name,
                        "; ".join(e.toString() for e in component.errors()))
            late.append(name)
            continue
        deadline = time.monotonic() + timeout_s
        # One image at a time, so the reader never sees a second job.  (``status`` itself is an
        # enum PySide cannot convert, hence the ``waiting`` helper property.)
        while item.property("waiting") and time.monotonic() < deadline:
            time.sleep(0.003)            # releases the GIL for the reader thread
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents, 5)
        if item.property("waiting"):
            log.warning("image provider %s did not answer the warm-up in %.0f s", name, timeout_s)
            late.append(name)
        item.setProperty("source", QUrl())
        item.deleteLater()
        component.deleteLater()
    return late


_provider: IconProvider | None = None


def provider() -> IconProvider:
    global _provider
    if _provider is None:
        _provider = IconProvider()
    return _provider


def display_name(path: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    p = Path(path)
    name = p.name or str(p)
    if p.suffix.casefold() in {".lnk", ".url", ".website", ".appref-ms"}:
        return p.stem or name
    return name


__all__ = ["IconProvider", "WARMUP_ID", "display_name", "file_type", "generated_icon", "parse_id",
           "prime_image_providers", "provider", "warmup_image"]

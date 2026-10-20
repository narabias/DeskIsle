"""Island background media: still images, animated images and looping video.

Frames are decoded at (roughly) the size they are shown, composited once
with a feathered edge and then reused for every repaint.  Video decoding is
throttled to the configured frame rate and pauses whenever the island cannot
be seen, so a looping background costs little more than a still image.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QElapsedTimer, QObject, QRectF, QSize, QSizeF, Qt, QUrl, Signal
from PySide6.QtGui import QImage, QImageReader, QMovie, QPainter

from .backdrop import apply_rounded_clip, edge_mask

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".jfif", ".bmp", ".tif", ".tiff", ".tga"}
ANIMATED_SUFFIXES = {".gif", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".m4v", ".mov", ".webm", ".mkv", ".avi", ".wmv"}
MEDIA_FILTER = (
    "图片或视频 (*.png *.jpg *.jpeg *.jfif *.bmp *.webp *.gif *.tif *.tiff *.mp4 *.m4v *.mov *.webm *.mkv *.avi *.wmv);;"
    "图片 (*.png *.jpg *.jpeg *.jfif *.bmp *.webp *.gif *.tif *.tiff);;"
    "视频 (*.mp4 *.m4v *.mov *.webm *.mkv *.avi *.wmv);;所有文件 (*)"
)
MAX_FRAME_EDGE = 1600
_FORMAT = QImage.Format.Format_ARGB32_Premultiplied

_frame_rate = 24
_import_handler: Callable[[str], str] | None = None
_multimedia_ok: bool | None = None


def set_frame_rate(fps: int) -> None:
    global _frame_rate
    _frame_rate = max(5, min(60, int(fps)))


def frame_rate() -> int:
    return _frame_rate


def set_import_handler(handler: Callable[[str], str] | None) -> None:
    """The board installs ``StateStore.import_media`` here."""
    global _import_handler
    _import_handler = handler


def import_media_file(path: str) -> str:
    """Copy a chosen file into DeskIsle's data folder (when possible)."""
    if not path:
        return ""
    if _import_handler is not None:
        try:
            return _import_handler(path) or path
        except OSError:
            return path
    return path


def media_kind(path: str) -> str:
    suffix = Path(path or "").suffix.lower()
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in ANIMATED_SUFFIXES:
        return "movie"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    return ""


def multimedia_available() -> bool:
    global _multimedia_ok
    if _multimedia_ok is None:
        try:
            import importlib

            importlib.import_module("PySide6.QtMultimedia")
            _multimedia_ok = True
        except ImportError:
            _multimedia_ok = False
    return _multimedia_ok


def cover_rect(target: QRectF, size) -> QRectF:
    sw, sh = float(size.width()), float(size.height())
    if sw <= 0 or sh <= 0:
        return QRectF(target)
    scale = max(target.width() / sw, target.height() / sh)
    w, h = sw * scale, sh * scale
    return QRectF(target.center().x() - w / 2, target.center().y() - h / 2, w, h)


def _fit_frame(image: QImage, wanted: QSize, smooth: bool = True) -> QImage:
    """Downscale *image* so it still covers *wanted* (never upscale)."""
    if image.isNull():
        return image
    w = max(16, min(MAX_FRAME_EDGE, wanted.width()))
    h = max(16, min(MAX_FRAME_EDGE, wanted.height()))
    if image.width() <= w * 1.15 or image.height() <= h * 1.15:
        result = image
    else:
        mode = Qt.TransformationMode.SmoothTransformation if smooth else Qt.TransformationMode.FastTransformation
        result = image.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding, mode)
    if result.format() != _FORMAT:
        result = result.convertToFormat(_FORMAT)
    return result


def compose_feathered(frame: QImage, width: float, height: float, radius: float, feather: float,
                      ratio: float) -> QImage:
    """Cover-fit *frame*, keep the centre sharp, blur and fade the rim."""
    device_w = max(1, int(math.ceil(width * ratio)))
    device_h = max(1, int(math.ceil(height * ratio)))
    out = QImage(device_w, device_h, _FORMAT)
    out.setDevicePixelRatio(ratio)
    out.fill(Qt.GlobalColor.transparent)
    local = QRectF(0, 0, device_w / ratio, device_h / ratio)
    painter = QPainter(out)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    painter.drawImage(cover_rect(local, frame.size()), frame)
    if feather > 0.5:
        sharp = edge_mask(local.width(), local.height(), radius, feather * 1.25, inward=True)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        painter.drawImage(local, sharp, QRectF(sharp.rect()))
        halo = QImage(sharp.size(), _FORMAT)
        halo.fill(Qt.GlobalColor.transparent)
        halo_painter = QPainter(halo)
        halo_painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        tiny = frame.scaled(max(2, halo.width() // 2), max(2, halo.height() // 2),
                            Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
        halo_painter.drawImage(cover_rect(QRectF(halo.rect()), tiny.size()), tiny)
        halo_painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationIn)
        halo_painter.drawImage(0, 0, edge_mask(local.width(), local.height(), radius, feather * 0.6, inward=True))
        halo_painter.end()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_DestinationOver)
        painter.drawImage(local, halo, QRectF(halo.rect()))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    apply_rounded_clip(painter, device_w, device_h, radius * ratio, local)
    painter.end()
    return out


class MediaLayer(QObject):
    """Decodes one background source for one island."""

    frame_changed = Signal()
    failed = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.path = ""
        self.kind = ""
        self.error = ""
        self._frame: QImage | None = None
        self._serial = 0
        self._wanted = QSize(480, 480)
        self._movie: QMovie | None = None
        self._player = None
        self._sink = None
        self._suspended: set[str] = set()
        self._clock = QElapsedTimer()
        self._clock.start()
        self._next_due = 0.0
        self._cache_key = None
        self._cache_image: QImage | None = None

    # Source ------------------------------------------------------------
    def set_source(self, path: str) -> None:
        path = path or ""
        if path == self.path and (self._frame is not None or self.kind in ("video", "movie")):
            return
        self.clear()
        self.path = path
        if not path:
            return
        if not os.path.isfile(path):
            self.error = "找不到背景文件"
            self.failed.emit(self.error)
            return
        kind = media_kind(path)
        self.kind = kind
        if kind == "image":
            self._load_still()
        elif kind == "movie":
            self._start_movie()
        elif kind == "video":
            self._start_video()
        else:
            self.kind = ""
            self.error = "不支持的文件类型"
            self.failed.emit(self.error)

    def set_static_image(self, image: QImage | None) -> None:
        """Show an already rendered image (used for HTML island snapshots)."""
        self.clear()
        if image is not None and not image.isNull():
            self.kind = "snapshot"
            self._set_frame(_fit_frame(image, self._wanted))

    def clear(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None
        if self._player is not None:
            try:
                self._player.stop()
                self._player.setVideoSink(None)
            except (RuntimeError, TypeError):
                pass
            self._player.deleteLater()
            self._player = None
        if self._sink is not None:
            self._sink.deleteLater()
            self._sink = None
        had_frame = self._frame is not None
        self.path = ""
        self.kind = ""
        self.error = ""
        self._frame = None
        self._cache_key = None
        self._cache_image = None
        if had_frame:
            self.frame_changed.emit()

    def has_frame(self) -> bool:
        return self._frame is not None and not self._frame.isNull()

    def current_frame(self) -> QImage | None:
        return self._frame

    def set_target_size(self, size: QSize) -> None:
        """Logical size × device ratio the media will be drawn at."""
        w, h = max(16, size.width()), max(16, size.height())
        if w <= self._wanted.width() * 1.2 and h <= self._wanted.height() * 1.2:
            return
        self._wanted = QSize(max(w, self._wanted.width()), max(h, self._wanted.height()))
        if self.kind == "image" and self.path:
            self._load_still()
        elif self._movie is not None:
            self._apply_movie_scale()

    # Suspension --------------------------------------------------------
    def set_suspended(self, reason: str, suspended: bool) -> None:
        before = bool(self._suspended)
        if suspended:
            self._suspended.add(reason)
        else:
            self._suspended.discard(reason)
        after = bool(self._suspended)
        if before == after:
            return
        if self._movie is not None:
            self._movie.setPaused(after)
        if self._player is not None:
            if after:
                self._player.pause()
            else:
                self._player.play()

    def is_suspended(self) -> bool:
        return bool(self._suspended)

    def is_animated(self) -> bool:
        return self.kind in ("movie", "video")

    # Decoding ----------------------------------------------------------
    def _set_frame(self, image: QImage) -> None:
        if image.isNull():
            return
        self._frame = image
        self._serial += 1
        self.frame_changed.emit()

    def _load_still(self) -> None:
        reader = QImageReader(self.path)
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            scale = max(self._wanted.width() / size.width(), self._wanted.height() / size.height())
            if scale < 0.87:
                reader.setScaledSize(QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale))))
        image = reader.read()
        if image.isNull():
            self.error = "无法读取图片"
            self.failed.emit(self.error)
            return
        self._set_frame(_fit_frame(image, self._wanted))

    def _apply_movie_scale(self) -> None:
        movie = self._movie
        if movie is None:
            return
        reader = QImageReader(self.path)
        size = reader.size()
        if size.isValid() and size.width() > 0 and size.height() > 0:
            scale = max(self._wanted.width() / size.width(), self._wanted.height() / size.height())
            if scale < 0.87:
                movie.setScaledSize(QSize(max(1, round(size.width() * scale)), max(1, round(size.height() * scale))))

    def _start_movie(self) -> None:
        movie = QMovie(self.path, parent=self)
        if not movie.isValid():
            movie.deleteLater()
            self.kind = "image"
            self._load_still()
            return
        movie.setCacheMode(QMovie.CacheMode.CacheNone)
        self._movie = movie
        self._apply_movie_scale()
        movie.frameChanged.connect(self._movie_frame)
        if movie.frameCount() == 1:
            movie.jumpToFrame(0)
            self._movie_frame(0, force=True)
            return
        movie.start()
        if self._suspended:
            movie.setPaused(True)

    def _frame_due(self) -> bool:
        """Frame-rate limiter that keeps the long-run rate at ``_frame_rate``."""
        now = float(self._clock.elapsed())
        interval = 1000.0 / _frame_rate
        if self._frame is not None and now + 4.0 < self._next_due:
            return False
        if now - self._next_due < interval:
            self._next_due += interval
        else:
            self._next_due = now + interval
        return True

    def _movie_frame(self, _index: int, force: bool = False) -> None:
        if self._movie is None:
            return
        if not force and not self._frame_due():
            return
        self._set_frame(_fit_frame(self._movie.currentImage(), self._wanted))

    def _start_video(self) -> None:
        if not multimedia_available():
            self.error = "当前环境不支持视频背景"
            self.failed.emit(self.error)
            return
        from PySide6.QtMultimedia import QMediaPlayer, QVideoSink

        player = QMediaPlayer(self)
        sink = QVideoSink(self)
        player.setVideoSink(sink)
        player.setLoops(QMediaPlayer.Loops.Infinite)
        # No QAudioOutput is attached, so backgrounds are always silent.
        sink.videoFrameChanged.connect(self._video_frame)
        player.errorOccurred.connect(self._video_error)
        player.setSource(QUrl.fromLocalFile(self.path))
        self._player, self._sink = player, sink
        if not self._suspended:
            player.play()

    def _video_frame(self, frame) -> None:
        if self._suspended and self._frame is not None:
            return
        if not self._frame_due():
            return
        try:
            image = frame.toImage()
        except RuntimeError:
            return
        if image.isNull():
            return
        self._set_frame(_fit_frame(image, self._wanted, smooth=False))

    def _video_error(self, _error, message: str = "") -> None:
        self.error = message or "视频无法播放"
        self.failed.emit(self.error)

    # Painting ----------------------------------------------------------
    def render(self, size: QSizeF, radius: float, feather: float, ratio: float) -> QImage | None:
        frame = self._frame
        if frame is None or frame.isNull() or size.width() < 2 or size.height() < 2:
            return None
        key = (self._serial, round(size.width(), 1), round(size.height(), 1), round(radius, 1),
               round(feather, 1), ratio)
        if key != self._cache_key or self._cache_image is None:
            self._cache_image = compose_feathered(frame, size.width(), size.height(), radius, feather, ratio)
            self._cache_key = key
        return self._cache_image

    def paint(self, painter: QPainter, rect: QRectF, radius: float, feather: float, opacity: float,
              ratio: float) -> bool:
        image = self.render(rect.size(), radius, feather, ratio)
        if image is None:
            return False
        painter.save()
        painter.setOpacity(painter.opacity() * max(0.0, min(1.0, opacity)))
        painter.drawImage(rect.topLeft(), image)
        painter.restore()
        return True


__all__ = [
    "MEDIA_FILTER",
    "MediaLayer",
    "compose_feathered",
    "cover_rect",
    "frame_rate",
    "import_media_file",
    "media_kind",
    "multimedia_available",
    "set_frame_rate",
    "set_import_handler",
]

"""Embedded web content for “HTML 动画” islands and “固定网页” islands.

Qt WebEngine is imported lazily: islands that never show web content do not
pay for Chromium at all.  HTML islands use an off-the-record profile that
blocks network requests unless the user allows them per island; pinned web
pages use one persistent profile so sign-ins survive restarts.
"""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImage, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from . import motion, theme
from .widgets import GlyphButton

HTML_FILTER = "HTML 文件 (*.html *.htm *.xhtml);;所有文件 (*)"
NETWORK_SCHEMES = {"http", "https", "ws", "wss", "ftp"}
SEARCH_URL = "https://www.bing.com/search?q={0}"

_engine = {"checked": False, "ok": False, "error": ""}
_profiles: dict[str, object] = {}
_storage_root: Path | None = None
_views: "list[WebContentView]" = []


class _Hub(QObject):
    download_finished = Signal(str)


_hub: _Hub | None = None


def hub() -> _Hub:
    global _hub
    if _hub is None:
        _hub = _Hub()
    return _hub


def prepare_application() -> None:
    """Call before QApplication exists (WebEngine needs shared GL contexts).

    Islands are translucent, layered windows; Chromium output is therefore
    composited with Qt Quick's software renderer, which works reliably with
    per-pixel alpha.  ``DESKISLE_HTML_GPU=1`` switches back to the GPU path.
    """
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    if os.environ.get("DESKISLE_HTML_GPU") == "1":
        return
    try:
        from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

        QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)
    except ImportError:
        pass


def configure_storage(root: Path | str | None) -> None:
    global _storage_root
    _storage_root = Path(root) if root else None


def webengine_available() -> bool:
    if os.environ.get("DESKISLE_DISABLE_WEBENGINE") == "1":
        return False
    if not _engine["checked"]:
        _engine["checked"] = True
        try:
            import importlib

            importlib.import_module("PySide6.QtWebEngineCore")
            importlib.import_module("PySide6.QtWebEngineWidgets")
            _engine["ok"] = True
        except Exception as exc:  # pragma: no cover - depends on the build
            _engine["error"] = str(exc)
    return bool(_engine["ok"])


def normalize_url(text: str) -> str:
    """Turn what the user typed into a URL (search Bing for plain words)."""
    value = (text or "").strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered.startswith(("http://", "https://", "file:", "about:")):
        return value
    if os.path.isabs(value) and os.path.exists(value):
        return QUrl.fromLocalFile(value).toString()
    if " " not in value and ("." in value or lowered.startswith("localhost")):
        return "https://" + value
    return SEARCH_URL.format(QUrl.toPercentEncoding(value).data().decode("ascii"))


def _offline_interceptor(parent):
    from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor

    class OfflineInterceptor(QWebEngineUrlRequestInterceptor):
        def interceptRequest(self, info) -> None:  # noqa: N802 - Qt API
            if info.requestUrl().scheme().lower() in NETWORK_SCHEMES:
                info.block(True)

    return OfflineInterceptor(parent)


def _accept_download(download) -> None:
    try:
        from PySide6.QtCore import QStandardPaths

        folder = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        if folder:
            download.setDownloadDirectory(folder)
        download.accept()
        name = download.downloadFileName()

        def finished() -> None:
            if download.isFinished():
                hub().download_finished.emit(os.path.join(download.downloadDirectory(), name))

        download.isFinishedChanged.connect(finished)
    except (AttributeError, RuntimeError):
        pass


def profile_for(kind: str):
    """``html-offline`` / ``html-online`` (off the record) or ``web`` (persistent)."""
    if kind in _profiles:
        return _profiles[kind]
    from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineSettings

    app = QApplication.instance()
    if kind == "web":
        profile = QWebEngineProfile("DeskIsleWeb", app)
        if _storage_root is not None:
            (_storage_root / "web" / "profile").mkdir(parents=True, exist_ok=True)
            (_storage_root / "web" / "cache").mkdir(parents=True, exist_ok=True)
            profile.setPersistentStoragePath(str(_storage_root / "web" / "profile"))
            profile.setCachePath(str(_storage_root / "web" / "cache"))
        profile.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        profile.downloadRequested.connect(_accept_download)
    else:
        profile = QWebEngineProfile(app)
        profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.MemoryHttpCache)
        if kind == "html-offline":
            interceptor = _offline_interceptor(profile)
            profile.setUrlRequestInterceptor(interceptor)
            profile._deskisle_interceptor = interceptor  # keep a Python reference
    settings = profile.settings()
    attr = QWebEngineSettings.WebAttribute
    settings.setAttribute(attr.FullScreenSupportEnabled, False)
    settings.setAttribute(attr.JavascriptCanOpenWindows, kind == "web")
    if kind != "web":
        settings.setAttribute(attr.ShowScrollBars, False)
        settings.setAttribute(attr.PlaybackRequiresUserGesture, False)
        settings.setAttribute(attr.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(attr.LocalContentCanAccessRemoteUrls, kind == "html-online")
    _profiles[kind] = profile
    return profile


def shutdown() -> None:
    """Delete pages before their profiles (avoids WebEngine warnings on exit)."""
    for view in list(_views):
        try:
            view.release()
        except RuntimeError:
            pass
    _views.clear()
    for profile in list(_profiles.values()):
        try:
            profile.deleteLater()
        except RuntimeError:
            pass
    _profiles.clear()


# HTML animations fade out towards the island edges instead of ending in a
# hard rectangle; injected as a tiny style element after each page load.
HTML_EDGE_FEATHER = 24
_FEATHER_SCRIPT = """
(function () {
  if (document.getElementById('__deskisle_feather')) { return; }
  var f = %d;
  var h = 'linear-gradient(to right, transparent 0, #000 ' + f + 'px, #000 calc(100%% - ' + f + 'px), transparent 100%%)';
  var v = 'linear-gradient(to bottom, transparent 0, #000 ' + f + 'px, #000 calc(100%% - ' + f + 'px), transparent 100%%)';
  var style = document.createElement('style');
  style.id = '__deskisle_feather';
  style.textContent = 'html{-webkit-mask-image:' + h + ',' + v + ';-webkit-mask-composite:source-in;' +
    'mask-image:' + h + ',' + v + ';mask-composite:intersect;}';
  (document.head || document.documentElement).appendChild(style);
})();
"""


def _install_edge_feather(page, pixels: int) -> None:
    if pixels <= 0:
        return
    try:
        from PySide6.QtWebEngineCore import QWebEngineScript
    except ImportError:  # pragma: no cover - depends on the build
        return
    script = QWebEngineScript()
    script.setName("deskisle-edge-feather")
    script.setInjectionPoint(QWebEngineScript.InjectionPoint.DocumentReady)
    script.setWorldId(QWebEngineScript.ScriptWorldId.ApplicationWorld)
    script.setRunsOnSubFrames(False)
    script.setSourceCode(_FEATHER_SCRIPT % int(pixels))
    page.scripts().insert(script)


class _Placeholder(QWidget):
    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.text = text
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(6, 6, -6, -6)
        painter.setPen(QPen(QColor(255, 255, 255, 40), 1.0, Qt.PenStyle.DashLine))
        painter.setBrush(QColor(255, 255, 255, 10))
        painter.drawRoundedRect(rect, 12, 12)
        painter.setPen(QColor(theme.TEXT_MUTED))
        painter.setFont(theme.ui_font(9.5))
        painter.drawText(rect.adjusted(12, 8, -12, -8), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                         self.text)


class WebNavBar(QWidget):
    """Back / forward / reload, an address field and “open in browser”."""

    navigate = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(32)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 3)
        layout.setSpacing(2)
        self.back_button = GlyphButton("chevron-left", self, diameter=26, tooltip="后退")
        self.forward_button = GlyphButton("chevron-right", self, diameter=26, tooltip="前进")
        self.reload_button = GlyphButton("reload", self, diameter=26, tooltip="重新加载", glyph_size=16)
        self.address = QLineEdit(self)
        self.address.setPlaceholderText("输入网址或搜索")
        self.address.setClearButtonEnabled(False)
        self.address.setStyleSheet(
            "QLineEdit { background: rgba(255,255,255,20); border: 1px solid rgba(255,255,255,26);"
            " border-radius: 12px; padding: 3px 10px; color: #F5F5F7; selection-background-color: #55D6BE; }"
            "QLineEdit:focus { border: 1px solid rgba(85,214,190,170); background: rgba(0,0,0,60); }"
        )
        self.address.setFixedHeight(26)
        self.external_button = GlyphButton("external", self, diameter=26, tooltip="在浏览器中打开", glyph_size=15)
        for widget in (self.back_button, self.forward_button, self.reload_button):
            layout.addWidget(widget)
        layout.addWidget(self.address, 1)
        layout.addWidget(self.external_button)
        self.address.returnPressed.connect(lambda: self.navigate.emit(self.address.text()))
        self.progress = 0.0
        self._progress_tween = motion.Tween(self, self._set_progress, 0.0, motion.FADE_MS)
        self._fade = 0.0

    def _set_progress(self, value: float) -> None:
        self.progress = value
        self.update()

    def set_loading(self, percent: int) -> None:
        self._progress_tween.to(max(0.0, min(1.0, percent / 100.0)), motion.FADE_MS)

    def set_url(self, url: str) -> None:
        if not self.address.hasFocus():
            self.address.setText(url)
            self.address.setCursorPosition(0)

    def paintEvent(self, event) -> None:  # noqa: N802
        if 0.0 < self.progress < 0.999:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            color = QColor(theme.ACCENT)
            color.setAlpha(200)
            painter.setBrush(color)
            painter.drawRoundedRect(QRectF(12, self.height() - 2.0, (self.width() - 24) * self.progress, 2.0), 1, 1)


class WebContentView(QWidget):
    """Hosts one QWebEngineView (or a placeholder when WebEngine is absent)."""

    title_changed = Signal(str)
    url_changed = Signal(str)
    menu_requested = Signal(QPoint)
    loaded = Signal(bool)

    def __init__(self, kind: str, parent=None) -> None:
        super().__init__(parent)
        self.kind = "web" if kind == "web" else "html"
        self.view = None
        self.page = None
        self.placeholder: _Placeholder | None = None
        self.nav: WebNavBar | None = None
        self._profile_kind = ""
        self._source = ""
        self._allow_network = False
        self._zoom = 1.0
        self._suspended: set[str] = set()
        self._snapshot: QImage | None = None
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(4)
        if self.kind == "web":
            self.nav = WebNavBar(self)
            self.nav.navigate.connect(self.load_url)
            self.nav.back_button.clicked.connect(lambda: self.view is not None and self.view.back())
            self.nav.forward_button.clicked.connect(lambda: self.view is not None and self.view.forward())
            self.nav.reload_button.clicked.connect(self._reload_or_stop)
            self.nav.external_button.clicked.connect(self.open_in_browser)
            self._layout.addWidget(self.nav)
        if webengine_available():
            self._build_view("web" if self.kind == "web" else "html-offline")
        else:
            reason = "网页组件已停用" if os.environ.get("DESKISLE_DISABLE_WEBENGINE") == "1" else "此环境缺少 Qt WebEngine 组件"
            self.placeholder = _Placeholder(reason + "\n可在菜单中改用浏览器打开。", self)
            self._layout.addWidget(self.placeholder, 1)
        _views.append(self)

    # Construction -----------------------------------------------------
    def _build_view(self, profile_kind: str) -> None:
        from PySide6.QtWebEngineCore import QWebEnginePage
        from PySide6.QtWebEngineWidgets import QWebEngineView

        if self.view is not None:
            self._drop_view()
        self._profile_kind = profile_kind
        view = QWebEngineView(self)
        page = QWebEnginePage(profile_for(profile_kind), view)
        if self.kind == "html":
            page.setBackgroundColor(Qt.GlobalColor.transparent)
            _install_edge_feather(page, HTML_EDGE_FEATHER)
            view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            view.customContextMenuRequested.connect(lambda point: self.menu_requested.emit(view.mapToGlobal(point)))
        view.setPage(page)
        view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, self.kind == "html")
        page.newWindowRequested.connect(self._open_new_window)
        page.fullScreenRequested.connect(lambda request: request.reject())
        if hasattr(page, "permissionRequested"):
            page.permissionRequested.connect(lambda permission: permission.deny())
        elif hasattr(page, "featurePermissionRequested"):
            page.featurePermissionRequested.connect(
                lambda origin, feature: page.setFeaturePermission(
                    origin, feature, QWebEnginePage.PermissionPolicy.PermissionDeniedByUser))
        page.titleChanged.connect(self.title_changed)
        page.urlChanged.connect(self._url_changed)
        page.loadFinished.connect(self._load_finished)
        if self.nav is not None:
            page.loadProgress.connect(self.nav.set_loading)
            page.loadStarted.connect(lambda: self.nav.reload_button.set_glyph("stop"))
        self.view, self.page = view, page
        view.setZoomFactor(self._zoom)
        self._layout.addWidget(view, 1)
        if self._suspended:
            view.hide()

    def _drop_view(self) -> None:
        view, page = self.view, self.page
        self.view = self.page = None
        if view is not None:
            self._layout.removeWidget(view)
            view.hide()
            try:
                view.setPage(None)
            except (TypeError, RuntimeError):
                pass
        if page is not None:
            page.deleteLater()
        if view is not None:
            view.deleteLater()

    def release(self) -> None:
        self._refresh_timer.stop()
        self._drop_view()
        if self in _views:
            _views.remove(self)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.release()
        super().closeEvent(event)

    # Loading -----------------------------------------------------------
    def set_html_file(self, path: str, allow_network: bool = False) -> None:
        self._source = path or ""
        self._allow_network = bool(allow_network)
        if not webengine_available():
            return
        wanted = "html-online" if self._allow_network else "html-offline"
        if wanted != self._profile_kind or self.view is None:
            self._build_view(wanted)
        if self._source and os.path.isfile(self._source):
            self.view.load(QUrl.fromLocalFile(os.path.abspath(self._source)))
        else:
            self.view.setHtml(
                "<html><body style='margin:0;display:flex;align-items:center;justify-content:center;"
                "height:100vh;color:rgba(255,255,255,.55);font:14px sans-serif;background:transparent'>"
                "找不到 HTML 文件</body></html>")

    def load_url(self, text: str) -> None:
        url = normalize_url(text)
        if not url:
            return
        self._source = url
        if self.view is not None:
            self.view.load(QUrl(url))
        if self.nav is not None:
            self.nav.set_url(url)

    def current_url(self) -> str:
        if self.page is not None:
            value = self.page.url().toString()
            if value and value != "about:blank":
                return value
        return self._source

    def reload(self) -> None:
        if self.view is not None:
            self.view.reload()

    def _reload_or_stop(self) -> None:
        if self.view is None:
            return
        if self.nav is not None and self.nav.reload_button.glyph == "stop":
            self.view.stop()
            self.nav.reload_button.set_glyph("reload")
        else:
            self.view.reload()

    def open_in_browser(self) -> None:
        url = self.current_url()
        if url:
            QDesktopServices.openUrl(QUrl(url) if "://" in url or url.startswith("file:") else QUrl.fromLocalFile(url))

    def _open_new_window(self, request) -> None:
        url = request.requestedUrl()
        if url.isValid() and url.scheme().lower() in ("http", "https"):
            QDesktopServices.openUrl(url)

    def _url_changed(self, url: QUrl) -> None:
        text = url.toString()
        if self.nav is not None:
            self.nav.set_url(text)
            if self.view is not None:
                history = self.view.history()
                self.nav.back_button.setEnabled(history.canGoBack())
                self.nav.forward_button.setEnabled(history.canGoForward())
        if self.kind == "web" and text and text != "about:blank":
            self.url_changed.emit(text)

    def _load_finished(self, ok: bool) -> None:
        if self.nav is not None:
            self.nav.reload_button.set_glyph("reload")
            self.nav.set_loading(100)
            if self.view is not None:
                history = self.view.history()
                self.nav.back_button.setEnabled(history.canGoBack())
                self.nav.forward_button.setEnabled(history.canGoForward())
        self.loaded.emit(bool(ok))

    # Options -----------------------------------------------------------
    def set_zoom(self, factor: float) -> None:
        self._zoom = max(0.25, min(5.0, float(factor)))
        if self.view is not None:
            self.view.setZoomFactor(self._zoom)

    def zoom(self) -> float:
        if self.view is not None:
            return float(self.view.zoomFactor())
        return self._zoom

    def set_refresh_minutes(self, minutes: int) -> None:
        minutes = max(0, int(minutes))
        if minutes:
            self._refresh_timer.start(minutes * 60_000)
        else:
            self._refresh_timer.stop()

    def _auto_refresh(self) -> None:
        if not self._suspended:
            self.reload()

    def set_toolbar_visible(self, visible: bool) -> None:
        if self.nav is not None:
            self.nav.setVisible(bool(visible))

    # Visibility --------------------------------------------------------
    def set_suspended(self, reason: str, suspended: bool) -> None:
        before = bool(self._suspended)
        if suspended:
            self._suspended.add(reason)
        else:
            self._suspended.discard(reason)
        after = bool(self._suspended)
        if before == after or self.view is None:
            return
        from PySide6.QtWebEngineCore import QWebEnginePage

        if after:
            self._snapshot = self.grab_snapshot()
            self.view.hide()
            if self.kind == "html":
                # Frozen pages stop running script and animations entirely.
                try:
                    self.page.setLifecycleState(QWebEnginePage.LifecycleState.Frozen)
                except (RuntimeError, AttributeError):
                    pass
        else:
            try:
                if self.page.lifecycleState() != QWebEnginePage.LifecycleState.Active:
                    self.page.setLifecycleState(QWebEnginePage.LifecycleState.Active)
            except (RuntimeError, AttributeError):
                pass
            self.view.show()

    def is_suspended(self) -> bool:
        return bool(self._suspended)

    def grab_snapshot(self) -> QImage | None:
        if self.view is not None and self.view.isVisible() and self.view.width() > 4 and self.view.height() > 4:
            image = self.view.grab().toImage()
            if not image.isNull():
                self._snapshot = image
        return self._snapshot

    def snapshot(self) -> QImage | None:
        return self._snapshot


__all__ = [
    "HTML_FILTER",
    "WebContentView",
    "configure_storage",
    "hub",
    "normalize_url",
    "prepare_application",
    "profile_for",
    "shutdown",
    "webengine_available",
]

"""Layer windows: one transparent Qt Quick window per monitor (+ pinned islands).

Windows specifics
-----------------
* ``QQuickWindow.setDefaultAlphaBuffer(True)`` + D3D11: Qt composes the window
  through DirectComposition (premultiplied alpha swap chain).
* ``QT_QPA_DISABLE_REDIRECTION_SURFACE=1`` is set only while our layer windows
  are created so Qt adds ``WS_EX_NOREDIRECTIONBITMAP`` (no GDI redirection
  surface; needed for WebView2 composition hosting below Qt's visual tree).
* The windows are frameless tool windows kept at the bottom of the Z order
  and ``WS_EX_NOACTIVATE`` (desktop clicks must not steal the foreground -
  wallpaper engines pause on "fullscreen focused" otherwise).  They are inset
  by 2 px so no tool mistakes them for a fullscreen application.
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

from PySide6.QtCore import QObject, QRect, Qt, QTimer, QUrl
from PySide6.QtGui import QRegion
from PySide6.QtQml import QQmlComponent

from .. import native_win

QML_DIR = Path(__file__).resolve().parent.parent / "qml"
IS_WINDOWS = sys.platform == "win32"


@contextmanager
def no_redirection_surface(enabled: bool = True):
    key = "QT_QPA_DISABLE_REDIRECTION_SURFACE"
    previous = os.environ.get(key)
    if enabled and IS_WINDOWS:
        os.environ[key] = "1"
    try:
        yield
    finally:
        if enabled and IS_WINDOWS:
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


class LayerManager(QObject):
    def __init__(self, engine, desk, demo: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.engine = engine
        self.desk = desk
        self.demo = demo
        self.windows: dict[str, object] = {}
        self.pinned: dict[str, object] = {}
        self.webhost = None
        self._components: dict[str, QQmlComponent] = {}
        self._focus = False
        self._keyboard_key = ""
        self._mask_timer = QTimer(self)
        self._mask_timer.setSingleShot(True)
        self._mask_timer.setInterval(80)
        self._mask_timer.timeout.connect(self.update_masks)

    # Components --------------------------------------------------------------------------
    def component(self, name: str) -> QQmlComponent:
        component = self._components.get(name)
        if component is None:
            component = QQmlComponent(self.engine, QUrl.fromLocalFile(str(QML_DIR / name)))
            if component.isError():
                raise RuntimeError("\n".join(e.toString() for e in component.errors()))
            self._components[name] = component
        return component

    def create_window(self, name: str, props: dict):
        component = self.component(name)
        with no_redirection_surface(not self.demo):
            window = component.createWithInitialProperties(props)
            if window is None:
                raise RuntimeError("\n".join(e.toString() for e in component.errors()))
            window.create()
        return window

    # Scenes -------------------------------------------------------------------------------
    def sync(self) -> None:
        for key in list(self.windows):
            if key not in self.desk.scenes:
                self._destroy(self.windows.pop(key))
        for key, scene in self.desk.scenes.items():
            window = self.windows.get(key)
            if window is None:
                window = self.create_window("Layer.qml", {"scene": scene})
                self.windows[key] = window
                self._setup(window, key)
            self.position(key)
        self.sync_pinned()
        self.schedule_masks()

    def remove_scene(self, scene) -> None:
        window = self.windows.pop(scene.key, None)
        if window is not None:
            self._destroy(window)

    def _destroy(self, window) -> None:
        try:
            if self.webhost is not None:
                self.webhost.forget_window(window)
            window.hide()
            window.deleteLater()
        except RuntimeError:
            pass

    def _setup(self, window, key: str) -> None:
        if self.demo:
            window.setFlags(Qt.WindowType.Window)
            window.setTitle("桌屿 DeskIsle 2.0 演示 · " + self.desk.scenes[key].spec.label)
        else:
            window.setFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                            | Qt.WindowType.WindowStaysOnBottomHint | Qt.WindowType.NoDropShadowWindowHint)
            screen = self.desk.screen_for(key)
            if screen is not None:
                window.setScreen(screen)
        self.position(key)
        window.show()
        if not self.demo and IS_WINDOWS:
            hwnd = int(window.winId())
            native_win.set_window_no_activate(hwnd, True)
            native_win.set_window_overlay(hwnd, False)

    def position(self, key: str) -> None:
        window = self.windows.get(key)
        scene = self.desk.scenes.get(key)
        if window is None or scene is None:
            return
        rect = scene.window_rect()
        if self.demo:
            if window.width() != rect.w or window.height() != rect.h:
                window.resize(rect.w, rect.h)
            return
        ox, oy = self.desk.origin()
        window.setGeometry(QRect(rect.x + ox, rect.y + oy, rect.w, rect.h))

    def hwnds(self) -> list[int]:
        result = []
        for window in list(self.windows.values()) + list(self.pinned.values()):
            try:
                result.append(int(window.winId()))
            except RuntimeError:
                continue
        return result

    # Pinned islands (own always-on-top window) ----------------------------------------------
    def sync_pinned(self) -> None:
        wanted = {p.state.id: p for p in self.desk.proxies() if p.state.pin_on_top and p.scene is not None}
        for uid in list(self.pinned):
            if uid not in wanted:
                self._destroy(self.pinned.pop(uid))
        for uid, proxy in wanted.items():
            window = self.pinned.get(uid)
            if window is None:
                window = self.create_window("PinnedIsland.qml", {"proxy": proxy, "scene": proxy.scene})
                if not self.demo:
                    window.setFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool
                                    | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.NoDropShadowWindowHint)
                self.pinned[uid] = window
                proxy.geometryChanged.connect(lambda p=proxy: self._place_pinned(p))
                window.show()
                if not self.demo and IS_WINDOWS:
                    native_win.set_window_no_activate(int(window.winId()), True)
            else:
                window.setProperty("scene", proxy.scene)
            self._place_pinned(proxy)

    def _place_pinned(self, proxy) -> None:
        window = self.pinned.get(proxy.state.id)
        if window is None or proxy.scene is None:
            return
        margin = 28
        r = proxy.board_rect()
        if self.demo:
            layer = self.windows.get(proxy.scene.key)
            gx, gy = (layer.x(), layer.y()) if layer is not None else (0, 0)
            x, y = gx + r.x - proxy.scene.local_x - margin, gy + r.y - proxy.scene.local_y - margin
        else:
            ox, oy = self.desk.origin()
            x, y = r.x + ox - margin, r.y + oy - margin
        window.setGeometry(QRect(int(x), int(y), r.w + 2 * margin, r.h + 2 * margin))

    # Z order / keyboard -----------------------------------------------------------------------
    def set_focus_overlay(self, enabled: bool) -> None:
        self._focus = enabled
        for window in self.windows.values():
            if IS_WINDOWS and not self.demo:
                native_win.set_window_overlay(int(window.winId()), enabled)
            if enabled:
                window.raise_()
        if enabled:
            self.set_keyboard(True, self.desk.primary_spec().key)
        else:
            self.set_keyboard(False, "")

    def set_keyboard(self, on: bool, key: str = "") -> None:
        """Allow the layer window of ``key`` to become active (text input)."""
        if self.demo:
            window = self.windows.get(key) or next(iter(self.windows.values()), None)
            if on and window is not None:
                window.requestActivate()
            return
        from PySide6.QtGui import QCursor

        cursor = QCursor.pos()
        pinned_hit = None
        for window in self.pinned.values():
            # Pinned islands (always on top): the one under the pointer takes the keyboard.
            try:
                hit = on and window.geometry().contains(cursor)
                if IS_WINDOWS:
                    native_win.set_window_no_activate(int(window.winId()), not hit)
            except RuntimeError:
                continue
            if hit:
                pinned_hit = window
        if pinned_hit is not None:
            pinned_hit.requestActivate()
            self._keyboard_key = key
            return
        for wkey, window in self.windows.items():
            want = on and (wkey == key or not key)
            if IS_WINDOWS:
                native_win.set_window_no_activate(int(window.winId()), not want)
            if want:
                window.requestActivate()
        self._keyboard_key = key if on else ""

    # Native icons / masks ------------------------------------------------------------------------
    def apply_preferences(self, prefs, old=None) -> None:
        if IS_WINDOWS and not self.demo:
            native_win.show_native_desktop_icons(not prefs.hide_native_icons)
        self.schedule_masks()

    def schedule_masks(self) -> None:
        self._mask_timer.start()

    def update_masks(self) -> None:
        """With native icons visible, only island areas take mouse input."""
        prefs = self.desk.preferences
        for key, window in self.windows.items():
            if self.demo or prefs.hide_native_icons or self.desk.panel or self._focus:
                window.setMask(QRegion())
                continue
            scene = self.desk.scenes.get(key)
            region = QRegion()
            if scene is not None:
                for proxy in scene.islands:
                    r = proxy.board_rect()
                    region = region.united(QRegion(r.x - scene.local_x - 24, r.y - scene.local_y - 24,
                                                   r.w + 48, r.h + 48))
                if scene.spec.primary:
                    region = region.united(QRegion(scene.spec.geometry.w // 2 - 380, 0, 760, 120))
            window.setMask(region)

    # Web islands ------------------------------------------------------------------------------
    def web_host(self, uid: str):
        if self.webhost is None:
            return None
        return self.webhost.view(uid)

    def window_of(self, key: str):
        return self.windows.get(key)

    def grab(self, folder: str) -> list[str]:
        """Screenshots of every layer (agent: verify a change visually)."""
        paths = []
        os.makedirs(folder, exist_ok=True)
        for key, window in self.windows.items():
            image = window.grabWindow()
            safe = "".join(c if c.isalnum() else "_" for c in key)[:40]
            path = os.path.join(folder, "layer-{0}.png".format(safe))
            if image.save(path):
                paths.append(path)
        return paths

    def shutdown(self) -> None:
        for window in list(self.pinned.values()) + list(self.windows.values()):
            self._destroy(window)
        self.pinned.clear()
        self.windows.clear()


__all__ = ["LayerManager", "QML_DIR", "no_redirection_surface"]

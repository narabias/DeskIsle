"""Web islands: Microsoft Edge WebView2 inside the layer windows.

Composition hosting (default on Windows)
----------------------------------------
Every layer window is a Qt Quick window composed by DirectComposition.  A web
island's page is a *visual* in a second DComp visual tree of the same window
(``CreateTargetForHwnd(hwnd, topmost=FALSE)``), i.e. composed *below* Qt's
content.  Qt leaves a transparent window ("hole", see ``Glass.hole``) over the
page area, so the page sits inside the glass island while menus, drag shadows
and islands dragged across it stay above it.  The layer window receives the
mouse; QML forwards it (``WebView.mouse`` -> ``SendMouseInput``), the cursor
follows ``CursorChanged`` and keyboard focus uses ``MoveFocus`` once the layer
may activate (``Desk.wantKeyboard``).

Safety: the first composition attempt of a run writes ``web/composition.trial``
next to the WebView2 profile.  It is removed as soon as a page has loaded.  If
DeskIsle dies in between, the next start finds it, renames it to
``composition.failed`` and uses the windowed host until the user picks
“合成模式” again in the settings.

Windowed host (default whenever the below-Qt target is unavailable)
-------------------------------------------------------------------
A plain child window of the layer window holds a regular WebView2 controller.
It takes mouse, keyboard and IME input natively (a click into the page raises
``GotFocus`` -> ``pageFocused`` -> the layer window may activate), but it is
drawn above the Qt content of its area, so other islands cannot cover it and
the island glass stays visible behind transparent pages (no hole).  Qt 6
composes translucent windows with its own non-topmost DComp target, so on
current Qt builds this is what "auto" ends up using; the topmost composition
tree is only used when the user picks “合成模式” explicitly.

Elsewhere
---------
macOS / Linux (demo, development): ``WebEngineSurface.qml`` (Qt WebEngine) when
installed, otherwise a placeholder that offers the external browser.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import sys
import time
from ctypes import POINTER, Structure, byref, c_float, c_int32, c_uint32, c_void_p
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication

from .. import webview2
from ..webview2 import BOOL, E_FAIL, E_NOINTERFACE, HRESULT, IID, Com, Handler, Slot as WSlot, guid, subscribe

log = logging.getLogger("deskisle.web")
IS_WINDOWS = sys.platform == "win32"

NETWORK_SCHEMES = {"http", "https", "ws", "wss", "ftp"}
SEARCH_URL = "https://www.bing.com/search?q={0}"
EDGE_FEATHER = 18  # px: local HTML animations fade out towards the island edge

# Win32 mouse messages used as COREWEBVIEW2_MOUSE_EVENT_KIND values.
_PRESS = {1: 0x0201, 2: 0x0204, 4: 0x0207, 8: 0x020B, 16: 0x020B}
_RELEASE = {1: 0x0202, 2: 0x0205, 4: 0x0208, 8: 0x020C, 16: 0x020C}
_DOUBLE = {1: 0x0203, 2: 0x0206, 4: 0x0209, 8: 0x020D, 16: 0x020D}
WM_MOUSEMOVE, WM_MOUSEWHEEL, WM_MOUSEHWHEEL, WM_MOUSELEAVE = 0x0200, 0x020A, 0x020E, 0x02A3
# Windows system cursor id -> Qt.CursorShape
CURSORS = {32512: 0, 32513: 4, 32514: 3, 32515: 2, 32516: 1, 32642: 8, 32643: 7, 32644: 6, 32645: 5,
           32646: 9, 32648: 14, 32649: 13, 32650: 16, 32651: 15}

BRIDGE_SCRIPT = """
(function () {
  if (window.top !== window || window.deskisle) { return; }
  var state = %s;
  var listeners = {};
  function post(message) {
    if (window.chrome && window.chrome.webview) { window.chrome.webview.postMessage(message); }
  }
  function emit(type, data) {
    (listeners[type] || []).forEach(function (cb) { try { cb(data); } catch (e) { console.error(e); } });
  }
  function applyCss() {
    var root = document.documentElement, t = state.theme || {};
    if (!root) { return; }
    Object.keys(t).forEach(function (k) {
      if (typeof t[k] === "string" || typeof t[k] === "number") { root.style.setProperty("--deskisle-" + k, String(t[k])); }
    });
    root.setAttribute("data-deskisle-theme", t.dark ? "dark" : "light");
  }
  window.deskisle = {
    version: state.version,
    uid: state.uid,
    get theme() { return state.theme; },
    get config() { return state.config; },
    on: function (type, cb) { (listeners[type] = listeners[type] || []).push(cb); },
    setConfig: function (key, value) { state.config[key] = value; post({type: "config.set", key: key, value: value}); },
    openUrl: function (url) { post({type: "open", url: String(url)}); },
    notify: function (title, text) { post({type: "notice", title: String(title), text: String(text || "")}); },
    menu: function () { post({type: "menu"}); }
  };
  if (window.chrome && window.chrome.webview) {
    window.chrome.webview.addEventListener("message", function (event) {
      var m = event.data || {};
      if (m.type === "theme") { state.theme = m.theme || {}; applyCss(); emit("theme", state.theme); }
      else if (m.type === "config") { state.config = m.config || {}; emit("config", state.config); }
    });
  }
  applyCss();
  document.addEventListener("DOMContentLoaded", applyCss);
})();
"""

FEATHER_SCRIPT = """
(function () {
  if (window.top !== window) { return; }
  var f = %d;
  function apply() {
    if (document.getElementById('__deskisle_feather')) { return; }
    var h = 'linear-gradient(to right, transparent 0, #000 ' + f + 'px, #000 calc(100%% - ' + f + 'px), transparent 100%%)';
    var v = 'linear-gradient(to bottom, transparent 0, #000 ' + f + 'px, #000 calc(100%% - ' + f + 'px), transparent 100%%)';
    var style = document.createElement('style');
    style.id = '__deskisle_feather';
    style.textContent = 'html{-webkit-mask-image:' + h + ',' + v + ';-webkit-mask-composite:source-in;' +
      'mask-image:' + h + ',' + v + ';mask-composite:intersect;}::-webkit-scrollbar{width:0;height:0;}';
    (document.head || document.documentElement).appendChild(style);
  }
  if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', apply); } else { apply(); }
})();
"""


def normalize_url(text: str) -> str:
    """What the user typed -> URL (plain words search Bing)."""
    value = (text or "").strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered.startswith(("http://", "https://", "file:", "about:", "edge:")):
        return value
    if os.path.isabs(value) and os.path.exists(value):
        return QUrl.fromLocalFile(value).toString()
    if " " not in value and ("." in value or lowered.startswith("localhost")):
        return "https://" + value
    return SEARCH_URL.format(QUrl.toPercentEncoding(value).data().decode("ascii"))


def is_network_url(uri: str) -> bool:
    scheme = (uri or "").split(":", 1)[0].strip().lower() if ":" in (uri or "") else ""
    return scheme in NETWORK_SCHEMES


def unavailable_reason() -> tuple[str, str]:
    """``(message, link)`` when WebView2 cannot run here, else ``("", "")``."""
    if not IS_WINDOWS:
        return "网页岛需要 Windows 上的 Microsoft Edge WebView2。", ""
    status = webview2.runtime().state()
    if status == "ok":
        return "", ""
    if status == "disabled":
        return "网页组件已停用，可以用浏览器打开这个网页。", ""
    if status == "no-loader":
        return "缺少 WebView2Loader.dll，安装可能不完整。请重新安装桌屿。", ""
    if status == "no-runtime":
        return "未检测到 Microsoft Edge WebView2 运行时，安装后点“重试”。", webview2.RUNTIME_DOWNLOAD_URL
    detail = webview2.runtime().detail or webview2.describe(webview2.runtime().env_error)
    return "WebView2 启动失败：{0}".format(detail), ""


# ---------------------------------------------------------------------------------------------
# DirectComposition (ctypes)
# ---------------------------------------------------------------------------------------------
IID_DCOMP_DEVICE = "c37ea93a-e7aa-450d-b16f-9746cb0407f3"
DCOMPOSITION_ERROR_WINDOW_ALREADY_COMPOSED = webview2._signed(0x88980800)  # noqa: SLF001


class _Dev:
    COMMIT, CREATE_TARGET, CREATE_VISUAL, CREATE_RECT_CLIP = 3, 6, 7, 24


class _Vis:
    OFFSET_X, OFFSET_Y, SET_CLIP, ADD, REMOVE = 4, 6, 13, 16, 17


class _Clip:
    LEFT, TOP, RIGHT, BOTTOM = 4, 6, 8, 10
    RADII = (12, 14, 16, 18, 20, 22, 24, 26)  # TL x/y, TR x/y, BL x/y, BR x/y (float overloads)


class Tree:
    """One non-topmost (if possible) DComp tree of a layer window."""

    def __init__(self, hwnd: int, target: Com, root: Com, topmost: bool) -> None:
        self.hwnd, self.target, self.root, self.topmost = hwnd, target, root, topmost
        self.children: list = []  # CompositionBrowser in Z order (bottom first)


class DComp:
    def __init__(self) -> None:
        self.device: Com | None = None
        self.trees: dict[int, Tree] = {}
        self.below_failed: set[int] = set()   # windows whose below-Qt target is taken
        self.error = ""

    def ensure(self) -> bool:
        if self.device is not None:
            return True
        if self.error or not IS_WINDOWS:
            return False
        try:
            dll = ctypes.WinDLL("dcomp")
            out = c_void_p()
            hr = -1
            for name in ("DCompositionCreateDevice2", "DCompositionCreateDevice"):
                function = getattr(dll, name, None)
                if function is None:
                    continue
                function.restype = HRESULT
                function.argtypes = [c_void_p, c_void_p, POINTER(c_void_p)]
                hr = function(None, ctypes.addressof(guid(IID_DCOMP_DEVICE)), byref(out))
                if hr >= 0 and out.value:
                    break
            if hr < 0 or not out.value:
                self.error = "DCompositionCreateDevice: " + webview2.describe(hr)
                return False
            self.device = Com(out.value)
            return True
        except (OSError, AttributeError) as exc:
            self.error = str(exc)
            return False

    def _new(self, slot: int) -> Com | None:
        out = c_void_p()
        hr = self.device.call(slot, (POINTER(c_void_p),), byref(out))
        return Com(out.value) if hr >= 0 and out.value else None

    def visual(self) -> Com | None:
        return self._new(_Dev.CREATE_VISUAL)

    def clip(self) -> Com | None:
        return self._new(_Dev.CREATE_RECT_CLIP)

    def commit(self) -> None:
        if self.device is not None:
            self.device.call(_Dev.COMMIT)

    def tree(self, hwnd: int, allow_topmost: bool = False) -> Tree | None:
        """The page tree of a layer window.  Only a tree *below* Qt's content keeps islands, menus
        and drag shadows above the page; when Qt already holds that target (Qt 6 composes
        translucent windows itself) the page could only go above everything while its input
        still came through QML - so that is used only when the user asked for composition."""
        tree = self.trees.get(hwnd)
        if tree is not None:
            return tree if allow_topmost or not tree.topmost else None
        if hwnd in self.below_failed and not allow_topmost:
            return None
        if not self.ensure():
            return None
        target, topmost = None, False
        for flag in ((0, 1) if allow_topmost else (0,)):
            out = c_void_p()
            hr = self.device.call(_Dev.CREATE_TARGET, (c_void_p, BOOL, POINTER(c_void_p)), hwnd, flag, byref(out))
            if hr >= 0 and out.value:
                target, topmost = Com(out.value), bool(flag)
                break
            log.info("CreateTargetForHwnd(topmost=%s): %s", bool(flag), webview2.describe(hr))
            if not flag:
                self.below_failed.add(hwnd)
        if target is None:
            return None
        root = self.visual()
        if root is None or target.call(3, (c_void_p,), root.ptr) < 0:
            target.release()
            return None
        self.commit()
        tree = self.trees[hwnd] = Tree(hwnd, target, root, topmost)
        log.info("web composition tree for %#x (%s Qt)", hwnd, "above" if topmost else "below")
        return tree

    def drop(self, hwnd: int) -> None:
        self.below_failed.discard(hwnd)
        tree = self.trees.pop(hwnd, None)
        if tree is not None:
            tree.target.call(3, (c_void_p,), None)
            tree.root.release()
            tree.target.release()
            self.commit()

    def shutdown(self) -> None:
        for hwnd in list(self.trees):
            self.drop(hwnd)
        if self.device is not None:
            self.device.release()
            self.device = None


class POINT(Structure):
    _fields_ = [("x", c_int32), ("y", c_int32)]


class CompositionBrowser(webview2.Browser):
    """A WebView2 *composition* controller rendering into a DComp visual."""

    def __init__(self, hwnd: int, dcomp: DComp, tree: Tree, **kwargs) -> None:
        super().__init__(hwnd, **kwargs)
        self.dcomp, self.tree = dcomp, tree
        self.composition: Com | None = None
        self.on_cursor = None
        self._origin = (0, 0)
        self._radius = 0.0
        self.container = dcomp.visual()
        self.inner = dcomp.visual()
        self.clip = dcomp.clip()
        if self.container is None or self.inner is None or self.clip is None:
            raise OSError("DirectComposition visuals unavailable")
        self.container.call(_Vis.ADD, (c_void_p, BOOL, c_void_p), self.inner.ptr, 1, None)
        self.container.call(_Vis.SET_CLIP, (c_void_p,), self.clip.ptr)
        tree.root.call(_Vis.ADD, (c_void_p, BOOL, c_void_p), self.container.ptr, 1, None)
        tree.children.append(self)
        dcomp.commit()

    # Creation ------------------------------------------------------------------------------------
    def _environment_ready(self, environment, hr: int) -> None:
        if self.state != "pending":
            return
        if environment is None:
            self._fail(hr if hr < 0 else E_FAIL)
            return
        self.environment = Com(environment.ptr, add_ref=True)
        handler = Handler(IID["CompositionControllerCompleted"], self._composition_created, "hr_object")
        try:
            hr = self._create_composition(handler.ptr)
        except OSError:
            hr = E_FAIL
        finally:
            handler.release()
        if hr < 0:
            self._fail(hr)

    def _create_composition(self, handler: int) -> int:
        environment = self.environment
        if self.private:
            environment10 = environment.query(IID["Environment10"])
            if environment10 is not None:
                try:
                    options = environment10.get_object(WSlot.ENV10_CREATE_OPTIONS)
                    if options is not None:
                        try:
                            options.put_string(WSlot.OPTIONS_PUT_PROFILE_NAME, webview2.PRIVATE_PROFILE)
                            options.put_bool(WSlot.OPTIONS_PUT_IN_PRIVATE, True)
                            return environment10.call(WSlot.ENV10_CREATE_COMPOSITION_CONTROLLER_WITH_OPTIONS,
                                                      (c_void_p, c_void_p, c_void_p), self.hwnd, options.ptr, handler)
                        finally:
                            options.release()
                finally:
                    environment10.release()
        environment3 = environment.query(IID["Environment3"])
        if environment3 is None:
            return E_NOINTERFACE
        try:
            return environment3.call(WSlot.ENV3_CREATE_COMPOSITION_CONTROLLER, (c_void_p, c_void_p), self.hwnd, handler)
        finally:
            environment3.release()

    def _composition_created(self, hr, composition) -> None:
        if self.state != "pending":
            if hr >= 0 and composition:
                late = Com(composition, add_ref=True)
                controller = late.query(IID["Controller"])
                if controller is not None:
                    controller.call(WSlot.CTRL_CLOSE)
                    controller.release()
                late.release()
            return
        if hr < 0 or not composition:
            self._fail(hr if hr < 0 else E_FAIL)
            return
        comp = Com(composition, add_ref=True)
        controller = comp.query(IID["Controller"])
        if controller is None:
            comp.release()
            self._fail(E_NOINTERFACE)
            return
        hr = comp.call(WSlot.COMP_PUT_ROOT_VISUAL_TARGET, (c_void_p,), self.inner.ptr)
        if hr < 0:
            controller.release()
            comp.release()
            self._fail(hr)
            return
        self.composition = comp
        subscribe(comp, WSlot.COMP_ADD_CURSOR_CHANGED, "CursorChanged", self._cursor_changed)
        self._adopt(controller)
        self.dcomp.commit()

    # Geometry / input ------------------------------------------------------------------------------
    def place(self, x: int, y: int, width: int, height: int, radius: float) -> None:
        self._origin = (int(x), int(y))
        self._bounds = (max(0, int(width)), max(0, int(height)))
        self._radius = float(radius)
        self.container.call(_Vis.OFFSET_X, (c_float,), float(x))
        self.container.call(_Vis.OFFSET_Y, (c_float,), float(y))
        clip = self.clip
        clip.call(_Clip.LEFT, (c_float,), 0.0)
        clip.call(_Clip.TOP, (c_float,), 0.0)
        clip.call(_Clip.RIGHT, (c_float,), float(width))
        clip.call(_Clip.BOTTOM, (c_float,), float(height))
        r = max(0.0, min(float(radius), width / 2.0, height / 2.0))
        for index, slot in enumerate(_Clip.RADII):
            clip.call(slot, (c_float,), r if index >= 4 else 0.0)  # bottom corners only
        if self.ready:
            self._push_bounds()
        self.dcomp.commit()

    def _push_bounds(self) -> None:
        x, y = self._origin
        width, height = self._bounds
        self.controller.call(WSlot.CTRL_PUT_BOUNDS, (webview2.RECT,), webview2.RECT(x, y, x + width, y + height))

    def send_mouse(self, kind: int, keys: int, data: int, x: int, y: int) -> None:
        if self.ready and self.composition is not None:
            self.composition.call(WSlot.COMP_SEND_MOUSE_INPUT, (c_int32, c_int32, c_uint32, POINT),
                                  int(kind), int(keys), int(data) & 0xFFFFFFFF, POINT(int(x), int(y)))

    def _cursor_changed(self, _sender, _args) -> None:
        if self.composition is None or self.on_cursor is None:
            return
        out = c_uint32(0)
        hr = self.composition.call(WSlot.COMP_GET_SYSTEM_CURSOR_ID, (POINTER(c_uint32),), byref(out))
        self.on_cursor(int(out.value) if hr >= 0 else 0)

    def restack(self) -> None:
        """Re-insert this page on top of its window's other pages."""
        tree = self.tree
        if self in tree.children:
            tree.children.remove(self)
        tree.children.append(self)
        tree.root.call(_Vis.REMOVE, (c_void_p,), self.container.ptr)
        tree.root.call(_Vis.ADD, (c_void_p, BOOL, c_void_p), self.container.ptr, 1, None)
        self.dcomp.commit()

    def close(self) -> None:
        if self.state == "closed":
            return
        super().close()
        tree = self.tree
        if self in tree.children:
            tree.children.remove(self)
        try:
            tree.root.call(_Vis.REMOVE, (c_void_p,), self.container.ptr)
            self.dcomp.commit()
        except OSError:
            pass
        for name in ("composition", "inner", "clip", "container"):
            com = getattr(self, name, None)
            if com is not None:
                com.release()
            setattr(self, name, None)


# ---------------------------------------------------------------------------------------------
# Windowed fallback: a plain child window of the layer window.
# ---------------------------------------------------------------------------------------------
class _Child:
    _class_ready = False
    CLASS = "DeskIsleWebSlot"

    def __init__(self, parent: int) -> None:
        user32, kernel32 = ctypes.WinDLL("user32"), ctypes.WinDLL("kernel32")
        self.user32, self.gdi32 = user32, ctypes.WinDLL("gdi32")
        user32.CreateWindowExW.restype = c_void_p
        user32.CreateWindowExW.argtypes = [c_uint32, ctypes.c_wchar_p, ctypes.c_wchar_p, c_uint32, c_int32, c_int32,
                                           c_int32, c_int32, c_void_p, c_void_p, c_void_p, c_void_p]
        user32.SetWindowPos.argtypes = [c_void_p, c_void_p, c_int32, c_int32, c_int32, c_int32, c_uint32]
        user32.SetWindowRgn.argtypes = [c_void_p, c_void_p, BOOL]
        user32.ShowWindow.argtypes = [c_void_p, c_int32]
        user32.DestroyWindow.argtypes = [c_void_p]
        self.gdi32.CreateRectRgn.restype = c_void_p
        self.gdi32.CreateRoundRectRgn.restype = c_void_p
        self.gdi32.CombineRgn.argtypes = [c_void_p, c_void_p, c_void_p, c_int32]
        self.gdi32.DeleteObject.argtypes = [c_void_p]
        kernel32.GetModuleHandleW.restype = c_void_p
        instance = kernel32.GetModuleHandleW(None)
        if not _Child._class_ready:
            class WNDCLASSEXW(Structure):
                _fields_ = [("cbSize", c_uint32), ("style", c_uint32), ("lpfnWndProc", c_void_p),
                            ("cbClsExtra", c_int32), ("cbWndExtra", c_int32), ("hInstance", c_void_p),
                            ("hIcon", c_void_p), ("hCursor", c_void_p), ("hbrBackground", c_void_p),
                            ("lpszMenuName", ctypes.c_wchar_p), ("lpszClassName", ctypes.c_wchar_p),
                            ("hIconSm", c_void_p)]

            user32.LoadCursorW.restype = c_void_p
            user32.LoadCursorW.argtypes = [c_void_p, c_void_p]
            wc = WNDCLASSEXW()
            wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
            wc.lpfnWndProc = ctypes.cast(user32.DefWindowProcW, c_void_p).value
            wc.hInstance = instance
            wc.hCursor = user32.LoadCursorW(None, c_void_p(32512))
            wc.lpszClassName = self.CLASS
            user32.RegisterClassExW.argtypes = [c_void_p]
            user32.RegisterClassExW(byref(wc))
            _Child._class_ready = True
        style = 0x40000000 | 0x04000000 | 0x02000000  # WS_CHILD | WS_CLIPSIBLINGS | WS_CLIPCHILDREN
        self.hwnd = int(user32.CreateWindowExW(0, self.CLASS, "", style, 0, 0, 10, 10, parent, None, instance, None)
                        or 0)
        self._shape = None

    def place(self, x: int, y: int, width: int, height: int, radius: float) -> None:
        if not self.hwnd:
            return
        self.user32.SetWindowPos(self.hwnd, None, int(x), int(y), int(width), int(height), 0x0004 | 0x0010)
        shape = (int(width), int(height), int(radius))
        if shape != self._shape:
            self._shape = shape
            r = max(0, min(int(radius), width // 2, height // 2))
            region = self.gdi32.CreateRectRgn(0, 0, int(width), max(0, int(height) - r))
            rounded = self.gdi32.CreateRoundRectRgn(0, 0, int(width) + 1, int(height) + 1, 2 * r, 2 * r)
            self.gdi32.CombineRgn(region, region, rounded, 2)  # RGN_OR
            self.gdi32.DeleteObject(rounded)
            self.user32.SetWindowRgn(self.hwnd, region, 1)  # the window owns the region now

    def show(self, on: bool) -> None:
        if self.hwnd:
            self.user32.ShowWindow(self.hwnd, 8 if on else 0)  # SW_SHOWNA / SW_HIDE

    def destroy(self) -> None:
        if self.hwnd:
            self.user32.DestroyWindow(self.hwnd)
            self.hwnd = 0


# ---------------------------------------------------------------------------------------------
class WebView(QObject):
    """The page of one island as QML sees it (``WebHost.view(uid)``)."""

    changed = Signal()
    cursorChanged = Signal()
    pageFocused = Signal()    # the page took the keyboard focus (windowed host: a click into it)
    command = Signal(str, "QVariant")  # qml backend: navigate / reload / back / forward / stop / zoom

    def __init__(self, host: "WebHost", uid: str) -> None:
        super().__init__(host)
        self.host = host
        self.uid = uid
        self.mode = "pending"   # pending | composition | windowed | qml | placeholder
        self.message = ""
        self.link = ""
        self.browser = None
        self.child: _Child | None = None
        self.window = None
        self.hwnd = 0
        self._cursor = 0
        self._shown = True
        self._geometry = (0.0, 0.0, 0.0, 0.0, 0.0)
        self._dpr = 1.0
        self._source = ""
        self._suspended = False
        self._last_press = (0.0, 0, 0, 0)
        self._refresh = QTimer(self)
        self._refresh.timeout.connect(self.reload)
        self._loaded_once = False
        # A surface that disappears (preset switched, island became a capsule) keeps its page
        # for a while so coming back is instant; after that the browser process is released.
        self._linger = QTimer(self)
        self._linger.setSingleShot(True)
        self._linger.setInterval(45_000)
        self._linger.timeout.connect(self._expire)

    # Island state --------------------------------------------------------------------------------
    def _island(self):
        _page, island = self.host.desk.find_island(self.uid)
        return island

    def _proxy(self):
        return self.host.desk.proxy(self.uid)

    def spec(self) -> dict:
        """What to show: url, transparency, network permission, bridge, zoom."""
        island = self._island()
        if island is None:
            return {}
        custom = self.host.desk.custom
        if island.kind == "widget" and island.widget.startswith("custom:") and custom is not None:
            info = custom.widget(island.widget) or {}
            return {"url": info.get("url", ""), "transparent": True, "network": bool(info.get("network")),
                    "bridge": True, "zoom": 1.0, "private": True, "html": True, "refresh": 0}
        html = bool(island.html_path) or island.web_url.lower().startswith("file:")
        return {"url": island.web_url or "about:blank", "transparent": html,
                "network": bool(island.html_allow_network) or not html, "bridge": html,
                "zoom": float(island.web_zoom or 1.0), "private": html, "html": html,
                "refresh": int(island.web_refresh_minutes or 0)}

    # QML properties ---------------------------------------------------------------------------------
    def _get_mode(self) -> str:
        return self.mode

    def _get_message(self) -> str:
        return self.message

    def _get_link(self) -> str:
        return self.link

    def _get_cursor(self) -> int:
        return self._cursor

    def _get_source(self) -> str:
        return self._source

    def _get_transparent(self) -> bool:
        return bool(self.spec().get("transparent"))

    def _get_native(self) -> bool:
        return self.mode in ("composition", "windowed")

    def _get_hole(self) -> bool:
        """The page is composed below Qt: the island glass must stay transparent over it."""
        browser = self.browser
        return self.mode == "composition" and isinstance(browser, CompositionBrowser) and not browser.tree.topmost

    def _get_above(self) -> bool:
        """The page covers the Qt content of its area (child window / topmost visual)."""
        return self.mode in ("composition", "windowed") and not self._get_hole()

    modeName = Property(str, _get_mode, notify=changed)
    messageText = Property(str, _get_message, notify=changed)
    linkUrl = Property(str, _get_link, notify=changed)
    cursor = Property(int, _get_cursor, notify=cursorChanged)
    source = Property(str, _get_source, notify=changed)
    transparent = Property(bool, _get_transparent, notify=changed)
    native = Property(bool, _get_native, notify=changed)
    hole = Property(bool, _get_hole, notify=changed)
    above = Property(bool, _get_above, notify=changed)

    def _set_mode(self, mode: str, message: str = "", link: str = "") -> None:
        self.mode, self.message, self.link = mode, message, link
        self.changed.emit()

    # QML slots ----------------------------------------------------------------------------------------
    @Slot(QObject)
    def attach(self, window) -> None:
        """Called by WebSurface.qml once it is in a window."""
        if window is None:
            return
        self._linger.stop()
        if window is self.window and self.mode not in ("pending", "placeholder"):
            self._shown = True
            self._apply_visibility()
            return
        self.release_native()
        self.window = window
        try:
            self.hwnd = int(window.winId())
            self._dpr = float(window.devicePixelRatio() or 1.0)
        except (RuntimeError, AttributeError):
            self.hwnd, self._dpr = 0, 1.0
        self._start()

    def _start(self) -> None:
        spec = self.spec()
        if not spec:
            return
        self._source = spec["url"]
        if not IS_WINDOWS:
            if self.host.webengine:
                self._set_mode("qml")
            else:
                self._set_mode("placeholder", "网页岛需要 Windows 上的 Microsoft Edge WebView2。"
                               "这里可以改用浏览器打开。")
            return
        message, link = unavailable_reason()
        if message:
            self._set_mode("placeholder", message, link)
            return
        mode = self.host.preferred_mode()
        browser = None
        if mode == "composition":
            browser = self._make_composition(spec)
            if browser is None:
                mode = "windowed"
        if browser is None:
            browser = self._make_windowed(spec)
            mode = "windowed"
        if browser is None:
            self._set_mode("placeholder", "网页组件无法创建窗口。", "")
            return
        self.browser = browser
        self._wire(browser, spec)
        self._set_mode(mode)
        self._apply_geometry()
        browser.start()
        browser.navigate(normalize_url(spec["url"]) or "about:blank")
        self.set_refresh(spec.get("refresh", 0))

    def _make_composition(self, spec: dict):
        explicit = getattr(self.host.desk.preferences, "web_hosting", "auto") == "composition"
        tree = self.host.dcomp.tree(self.hwnd, allow_topmost=explicit) if self.hwnd else None
        if tree is None:
            return None
        try:
            browser = CompositionBrowser(self.hwnd, self.host.dcomp, tree, private=spec["private"],
                                         network_filter=self._blocks, settings=self._settings(spec))
        except OSError:
            log.exception("composition browser")
            return None
        browser.on_cursor = self._cursor_from_page
        self.host.begin_trial()
        return browser

    def _make_windowed(self, spec: dict):
        if not self.hwnd:
            return None
        try:
            self.child = _Child(self.hwnd)
        except OSError:
            log.exception("web child window")
            return None
        if not self.child.hwnd:
            self.child = None
            return None
        return webview2.Browser(self.child.hwnd, private=spec["private"], network_filter=self._blocks,
                                settings=self._settings(spec))

    @staticmethod
    def _settings(spec: dict) -> dict:
        html = bool(spec.get("html"))
        return {"custom_context_menu": html, "status_bar": not html, "zoom_control": not html}

    def _wire(self, browser, spec: dict) -> None:
        browser.on_ready = self._ready
        browser.on_failed = self._failed
        browser.on_title = lambda title: self._report(title=title)
        browser.on_source = lambda url: self._report(url=url)
        browser.on_history = lambda back, forward: self._report(canBack=back, canForward=forward)
        browser.on_navigation_starting = lambda _uri: self._report(loading=True, status="")
        browser.on_navigation_completed = self._completed
        browser.on_new_window = self._new_window
        browser.on_context_menu = self._context_menu if spec.get("html") else None
        browser.on_download_finished = lambda path: self.host.desk.show_notice("下载完成", path, "info", [], 6000)
        browser.on_process_failed = self._process_failed
        browser.on_zoom = lambda factor: self._report(zoom=factor)
        browser.on_message = self._message
        browser.on_focus = self.pageFocused.emit
        if spec.get("transparent"):
            browser.set_background(0, 0, 0, 0)
            browser.add_script(FEATHER_SCRIPT % EDGE_FEATHER)
        if spec.get("bridge"):
            browser.add_script(BRIDGE_SCRIPT % json.dumps(self.bridge_state(), ensure_ascii=False))
        browser.set_zoom(spec.get("zoom", 1.0))

    def bridge_state(self) -> dict:
        from .. import __version__
        from ..custom import theme_snapshot

        island = self._island()
        return {"version": __version__, "uid": self.uid,
                "theme": theme_snapshot(self.host.desk.theme),
                "config": dict(island.widget_config) if island is not None else {}}

    @Slot(float, float, float, float, float)
    def setGeometry(self, x: float, y: float, width: float, height: float, radius: float) -> None:  # noqa: N802
        """Page area in layer-window coordinates (logical px)."""
        self._geometry = (x, y, width, height, radius)
        self._apply_geometry()

    def _apply_geometry(self) -> None:
        x, y, width, height, radius = self._geometry
        d = self._dpr
        px, py = int(round(x * d)), int(round(y * d))
        pw, ph = max(0, int(round(width * d))), max(0, int(round(height * d)))
        browser = self.browser
        if isinstance(browser, CompositionBrowser):
            browser.place(px, py, pw, ph, radius * d)
        elif self.child is not None and browser is not None:
            self.child.place(px, py, pw, ph, radius * d)
            browser.set_bounds(pw, ph)
            browser.notify_moved()

    @Slot(bool)
    def setShown(self, shown: bool) -> None:  # noqa: N802
        self._shown = bool(shown)
        self._apply_visibility()

    def _apply_visibility(self) -> None:
        visible = self._shown and not self._suspended
        if self.child is not None:
            self.child.show(visible)
        if self.browser is not None:
            self.browser.set_visible(visible)

    @Slot()
    def detach(self) -> None:
        """WebSurface.qml went away: hide now, release the browser later."""
        self.setShown(False)
        self._linger.start()

    def _expire(self) -> None:
        self.release_native()
        self.window = None
        self.changed.emit()

    @Slot()
    def raiseUp(self) -> None:  # noqa: N802
        if isinstance(self.browser, CompositionBrowser):
            self.browser.restack()

    @Slot(str, float, float, int, int, int, int)
    def mouse(self, kind: str, x: float, y: float, button: int, buttons: int, modifiers: int, delta: int) -> None:
        """Composition mode: pointer input from WebSurface.qml (page-local logical px)."""
        browser = self.browser
        if not isinstance(browser, CompositionBrowser):
            return
        d = self._dpr
        px, py = int(round(x * d)), int(round(y * d))
        keys = (1 if buttons & 1 else 0) | (2 if buttons & 2 else 0) | (0x10 if buttons & 4 else 0) \
            | (0x20 if buttons & 8 else 0) | (0x40 if buttons & 16 else 0) \
            | (4 if modifiers & 0x02000000 else 0) | (8 if modifiers & 0x04000000 else 0)
        data = 0
        if kind == "move":
            message = WM_MOUSEMOVE
        elif kind == "leave":
            message = WM_MOUSELEAVE
        elif kind == "wheel":
            message, data = WM_MOUSEWHEEL, int(delta)
        elif kind == "hwheel":
            message, data = WM_MOUSEHWHEEL, int(delta)
        elif kind == "press":
            # Windows sends WM_xBUTTONDBLCLK instead of the second press of a double click.
            now = time.monotonic()
            last_t, last_b, lx, ly = self._last_press
            hints = QGuiApplication.styleHints()
            interval = (hints.mouseDoubleClickInterval() if hints is not None else 500) / 1000.0
            double = button == last_b and now - last_t <= interval and abs(px - lx) <= 4 and abs(py - ly) <= 4
            self._last_press = (0.0 if double else now, button, px, py)
            message = (_DOUBLE if double else _PRESS).get(button, 0)
            if button in (8, 16):
                data = 1 if button == 8 else 2
        elif kind == "release":
            message = _RELEASE.get(button, 0)
            if button in (8, 16):
                data = 1 if button == 8 else 2
        else:
            return
        if message:
            browser.send_mouse(message, keys, data, px, py)

    @Slot()
    def focusPage(self) -> None:  # noqa: N802
        if self.browser is not None:
            self.browser.focus()

    @Slot()
    def retry(self) -> None:
        self.release_native()
        if IS_WINDOWS:
            webview2.runtime().reset()
        if self.window is not None:
            self._start()

    @Slot()
    def openExternal(self) -> None:  # noqa: N802
        url = (self._proxy().web.get("url") if self._proxy() is not None else "") or self._source
        if url and not url.startswith("about:"):
            QDesktopServices.openUrl(QUrl(url))

    @Slot("QVariantMap")
    def report(self, values) -> None:
        """qml backend: WebEngineView state changes."""
        values = dict(values or {})
        if values.get("loaded"):
            values.pop("loaded")
            self._loaded()
        self._report(**values)

    # Browser callbacks ---------------------------------------------------------------------------------
    def _report(self, **values) -> None:
        proxy = self._proxy()
        if proxy is not None:
            proxy.update_web(**values)

    def _ready(self) -> None:
        self._apply_geometry()
        self._apply_visibility()

    def _failed(self, hr: int) -> None:
        QTimer.singleShot(0, lambda: self._after_failure(hr))

    def _after_failure(self, hr: int) -> None:
        was = self.mode
        self.release_native()
        if was == "composition":
            log.warning("composition hosting failed (%s) - using a child window", webview2.describe(hr))
            self.host.composition_failed()
            if self.window is not None:
                self._start()
            return
        message, link = unavailable_reason()
        self._set_mode("placeholder", message or "网页组件启动失败：{0}".format(webview2.describe(hr)), link)

    def _completed(self, ok: bool, status: int) -> None:
        browser = self.browser
        values = {"loading": False, "status": "" if ok else "页面加载失败（{0}）".format(status)}
        if browser is not None:
            values.update(canBack=browser.can_go_back(), canForward=browser.can_go_forward())
        self._report(**values)
        if ok:
            self._loaded()

    def _loaded(self) -> None:
        if not self._loaded_once:
            self._loaded_once = True
            if self.mode == "composition":
                self.host.end_trial()

    def _new_window(self, uri: str) -> None:
        url = QUrl(uri)
        if url.isValid() and url.scheme().lower() in ("http", "https"):
            QTimer.singleShot(0, lambda: QDesktopServices.openUrl(url))

    def _context_menu(self) -> bool:
        app = self.host.desk.app
        if app is not None:
            QTimer.singleShot(0, lambda: app.popupMenu("island", self.uid, {}))
        return True

    def _process_failed(self, kind: int) -> None:
        if kind == webview2.PROCESS_BROWSER_EXITED:
            QTimer.singleShot(0, self.retry)
        elif kind in (webview2.PROCESS_RENDER_EXITED, webview2.PROCESS_RENDER_UNRESPONSIVE):
            QTimer.singleShot(0, self.reload)

    def _cursor_from_page(self, cursor_id: int) -> None:
        shape = CURSORS.get(int(cursor_id), 0)
        if shape != self._cursor:
            self._cursor = shape
            self.cursorChanged.emit()

    def _blocks(self, uri: str) -> bool:
        spec = self.spec()
        return bool(spec) and not spec.get("network", True) and is_network_url(uri)

    def _message(self, text: str) -> None:
        """``window.deskisle`` -> DeskIsle (HTML widgets and local pages)."""
        try:
            message = json.loads(text or "null")
        except ValueError:
            return
        if not isinstance(message, dict):
            return
        desk = self.host.desk
        kind = str(message.get("type", ""))
        if kind == "config.set":
            key = str(message.get("key", ""))[:64]
            if key:
                desk.act(self.uid, "widgetConfig", {key: message.get("value")})
        elif kind == "open":
            url = QUrl(str(message.get("url", "")))
            if url.isValid() and url.scheme().lower() in ("http", "https", "mailto"):
                QDesktopServices.openUrl(url)
        elif kind == "notice":
            desk.show_notice(str(message.get("title", ""))[:60] or "小组件", str(message.get("text", ""))[:300])
        elif kind == "menu":
            self._context_menu()

    def push_theme(self) -> None:
        if self.browser is not None and self.spec().get("bridge"):
            from ..custom import theme_snapshot

            self.browser.post_json(json.dumps({"type": "theme", "theme": theme_snapshot(self.host.desk.theme)},
                                              ensure_ascii=False))

    def push_config(self) -> None:
        island = self._island()
        if self.browser is not None and island is not None and self.spec().get("bridge"):
            self.browser.post_json(json.dumps({"type": "config", "config": dict(island.widget_config)},
                                              ensure_ascii=False))

    # Commands (DeskController.web_action) --------------------------------------------------------------
    def navigate(self, url: str) -> None:
        url = normalize_url(url)
        self._source = url
        if self.browser is not None:
            self.browser.navigate(url)
        elif self.mode == "qml":
            self.changed.emit()
            self.command.emit("navigate", url)

    def reload(self) -> None:
        if self.browser is not None:
            self.browser.reload()
        else:
            self.command.emit("reload", None)

    def back(self) -> None:
        if self.browser is not None:
            self.browser.go_back()
        else:
            self.command.emit("back", None)

    def forward(self) -> None:
        if self.browser is not None:
            self.browser.go_forward()
        else:
            self.command.emit("forward", None)

    def stop(self) -> None:
        if self.browser is not None:
            self.browser.stop()
        else:
            self.command.emit("stop", None)

    def set_zoom(self, factor: float) -> None:
        if self.browser is not None:
            self.browser.set_zoom(factor)
        else:
            self.command.emit("zoom", float(factor))

    def set_refresh(self, minutes: int) -> None:
        minutes = int(minutes or 0)
        if minutes > 0:
            self._refresh.start(minutes * 60_000)
        else:
            self._refresh.stop()

    def set_suspended(self, suspended: bool) -> None:
        if suspended == self._suspended:
            return
        self._suspended = suspended
        self._apply_visibility()
        if self.browser is not None:
            if suspended:
                self.browser.suspend()
            else:
                self.browser.resume()

    # Teardown --------------------------------------------------------------------------------------------
    def release_native(self) -> None:
        browser, child = self.browser, self.child
        self.browser = self.child = None
        if browser is not None:
            try:
                browser.close()
            except OSError:
                log.exception("closing a web page")
        if child is not None:
            child.destroy()
        self._refresh.stop()
        self.mode = "pending"

    def close(self) -> None:
        self._linger.stop()
        self.release_native()
        self.window = None


class WebHost(QObject):
    """Creates and owns the :class:`WebView` of every web island (context ``WebHost``)."""

    changed = Signal()

    def __init__(self, desk, layers, demo: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.desk = desk
        self.layers = layers
        self.demo = demo
        self.views: dict[str, WebView] = {}
        self.dcomp = DComp()
        self.webengine = bool(os.environ.get("DESKISLE_WEBENGINE_READY"))
        self._trial_written = False
        self._composition_broken = False
        root = Path(desk.store.root) / "web"
        self._trial = root / "composition.trial"
        self._failed = root / "composition.failed"
        if IS_WINDOWS:
            webview2.runtime().data_folder = str(root / "WebView2")
        try:
            if self._trial.exists():
                root.mkdir(parents=True, exist_ok=True)
                self._trial.replace(self._failed)
                log.warning("the previous run stopped during web composition - using child windows")
                QTimer.singleShot(2500, lambda: desk.show_notice(
                    "网页岛已切换到兼容模式", "上次运行时网页合成模式没有正常完成，本次改用子窗口显示网页。"
                    "可在“设置 → 桌面 → 网页显示方式”中重新选择合成模式。", "warning", [], 12000))
        except OSError:
            pass
        if desk.theme is not None:
            desk.theme.changed.connect(self._theme_changed)
        self._theme_timer = QTimer(self)
        self._theme_timer.setSingleShot(True)
        self._theme_timer.setInterval(200)
        self._theme_timer.timeout.connect(lambda: [v.push_theme() for v in self.views.values()])
        desk.islandsChanged.connect(self._prune)

    # Modes ---------------------------------------------------------------------------------------
    def preferred_mode(self) -> str:
        pref = getattr(self.desk.preferences, "web_hosting", "auto")
        if pref == "windowed" or self._composition_broken:
            return "windowed"
        if pref == "auto" and self._failed.exists():
            return "windowed"
        return "composition"

    def begin_trial(self) -> None:
        if self._trial_written:
            return
        self._trial_written = True
        try:
            self._trial.parent.mkdir(parents=True, exist_ok=True)
            self._trial.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf-8")
        except OSError:
            pass

    def end_trial(self) -> None:
        try:
            self._trial.unlink(missing_ok=True)
        except OSError:
            pass

    def composition_failed(self) -> None:
        self._composition_broken = True
        self.end_trial()

    def reset_composition(self) -> None:
        """Settings: try composition again (removes the failure marker)."""
        self._composition_broken = False
        try:
            self._failed.unlink(missing_ok=True)
        except OSError:
            pass
        for view in list(self.views.values()):
            view.retry()

    def status(self) -> dict:
        modes = {uid: view.mode for uid, view in self.views.items()}
        return {"preferred": self.preferred_mode(), "views": modes, "dcomp": self.dcomp.error or "ok",
                "runtime": webview2.runtime().state() if IS_WINDOWS else "unsupported",
                "failedMarker": self._failed.exists()}

    # Views ------------------------------------------------------------------------------------------------
    @Slot(str, result=QObject)
    def view(self, uid: str):
        view = self.views.get(uid)
        if view is None:
            _page, island = self.desk.find_island(uid)
            if island is None:
                return None
            view = self.views[uid] = WebView(self, uid)
        return view

    @Slot(str)
    def release(self, uid: str) -> None:
        """WebSurface.qml destroyed (island collapsed to capsule, deleted, page switched)."""
        view = self.views.pop(uid, None)
        if view is not None:
            view.close()
            view.deleteLater()

    def _prune(self) -> None:
        for uid in list(self.views):
            _page, island = self.desk.find_island(uid)
            if island is None:
                self.release(uid)

    def forget_window(self, window) -> None:
        hwnd = 0
        try:
            hwnd = int(window.winId())
        except (RuntimeError, AttributeError):
            pass
        for uid, view in list(self.views.items()):
            if view.window is window:
                self.release(uid)
        if hwnd:
            self.dcomp.drop(hwnd)

    def config_changed(self, uid: str) -> None:
        view = self.views.get(uid)
        if view is not None:
            view.push_config()

    def _theme_changed(self) -> None:
        if self.views:
            self._theme_timer.start()

    def set_paused(self, paused: bool) -> None:
        for view in self.views.values():
            view.set_suspended(paused)

    def shutdown(self) -> None:
        for uid in list(self.views):
            self.release(uid)
        self.dcomp.shutdown()
        if IS_WINDOWS:
            try:
                webview2.runtime().shutdown()
            except Exception:
                log.exception("WebView2 shutdown")
        self.end_trial()


__all__ = ["WebHost", "WebView", "CompositionBrowser", "DComp", "normalize_url", "is_network_url",
           "unavailable_reason"]

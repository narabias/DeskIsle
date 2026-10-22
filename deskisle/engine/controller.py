"""DeskController - single owner of DeskIsle's state (exposed to QML as ``Desk``).

Every mutation (QML, tray, hotkeys, agent API) ends up in a method here, so the
behaviour is identical no matter who asks.  Island geometry is handled by the
:class:`~deskisle.engine.arrange.Arranger`; QML only animates towards it.
"""

from __future__ import annotations

import copy
import dataclasses
import os
import sys
import time
import uuid

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QTimer, Signal, Slot
from PySide6.QtGui import QCursor, QGuiApplication

from .. import __version__, layout
from ..layout import Rect
from ..models import (
    MATERIALS,
    SORT_MODES,
    AppState,
    IslandState,
    ItemRef,
    PageState,
    Preferences,
    TabState,
)
from ..monitors import (
    DEFAULT_PAGE_TITLE,
    MonitorSpec,
    ensure_current_pages,
    guest_label,
    migrate_state,
    monitor_at,
    pages_for_menu,
    primary_of,
)
from ..rules import RuleEngine
from .arrange import Arranger, footprint, min_size
from .desk_items import LOOSE, ItemsMixin, desktop_directories
from .scene import IslandProxy, MonitorScene, ObjectListModel

WIDGET_SIZES = {"clock": (320, 190), "weather": (340, 230), "media": (360, 176), "todo": (300, 340)}
WIDGET_TITLES = {"clock": "时钟", "weather": "天气", "media": "正在播放", "todo": "待办"}
ICON_SIZES = (32, 40, 48, 56, 64, 72, 96)


def lrect(qrect) -> Rect:
    return Rect(int(qrect.x()), int(qrect.y()), int(qrect.width()), int(qrect.height()))


def combo_signature(monitors) -> str:
    """Identity of a monitor combination (keys + arrangement + resolution)."""
    parts = sorted("{0}@{1},{2},{3}x{4}".format(m.key, m.geometry.x, m.geometry.y, m.geometry.w, m.geometry.h)
                   for m in monitors)
    return "|".join(parts)


class Notices(ObjectListModel):
    pass


class Notice(QObject):
    changed = Signal()

    def __init__(self, nid: str, title: str, text: str, kind: str, actions: list, timeout: int, parent=None):
        super().__init__(parent)
        self.nid, self._title, self._text, self._kind = nid, title, text, kind
        self._actions, self._timeout = actions, timeout

    nid_ = Property(str, lambda self: self.nid, constant=True)
    title = Property(str, lambda self: self._title, constant=True)
    text = Property(str, lambda self: self._text, constant=True)
    kind = Property(str, lambda self: self._kind, constant=True)
    actions = Property("QVariantList", lambda self: list(self._actions), constant=True)
    timeout = Property(int, lambda self: self._timeout, constant=True)


class DeskController(ItemsMixin, QObject):
    hiddenChanged = Signal()
    focusChanged = Signal()
    undoChanged = Signal()
    prefsChanged = Signal()
    panelChanged = Signal()
    confirmChanged = Signal()
    scenesChanged = Signal()
    keyboardChanged = Signal()
    stateReplaced = Signal()
    islandsChanged = Signal()       # structure (add/remove/rename) - for agent + tray
    settingsRequested = Signal(str)
    trayMenuRequested = Signal()
    quitRequested = Signal()
    menusDismissed = Signal()       # another app took the foreground: close menus/popovers
    rulesChanged = Signal()         # auto-sort rules edited (settings page)
    snapshotsChanged = Signal()     # a layout snapshot was saved / restored

    def __init__(self, store, state: AppState, *, demo: bool = False, theme=None, wallpaper=None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.state = state
        self.demo = demo
        self.theme = theme
        self.wallpaper = wallpaper
        self.scenes: dict[str, MonitorScene] = {}
        self._proxies: dict[str, IslandProxy] = {}
        self._monitors: list[MonitorSpec] = []
        self._origin = (0, 0)
        self._hidden = False
        self._focus = False
        self._panel = ""
        self._panel_arg = ""
        self._panel_monitor = ""
        self._confirm: dict = {}
        self._confirm_callbacks: dict[str, tuple] = {}
        self._keyboard = False
        self._keyboard_key = ""
        self._dragging_items = False
        self._drop_handled = False
        self._demo_size = (1600, 900)
        self.layers = None          # LayerManager (set by app)
        self.app = None             # DeskIsleApp (set by app)
        self.services: dict = {}    # widget back-ends by name (set by app)
        self.custom = None          # CustomFolder (set by app)
        self.updater = None
        self.notices = Notices(self)
        self.arranger = Arranger(self)
        self.arranger.changed.connect(self.undoChanged)
        self._rules = RuleEngine(state.rules)
        self._desktop_dirs = [] if demo else desktop_directories()
        self._save_timer = self._timer(700, self.save_now)
        self._loose_timer = self._timer(60, self.layout_loose)
        self._scan_timer = self._timer(900, lambda: self.import_new_desktop_items())
        self._screen_timer = self._timer(400, self._screens_settled)
        self._grace_timer = self._timer(6000, self._grace_expired)
        self._peek_timers: dict[str, QTimer] = {}
        # Layout before a capsule was opened, so folding it back can restore every island.
        self._capsule_layouts: dict[str, dict] = {}
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(lambda _p: self._scan_timer.start(900))
        # File views (portal tabs) follow the folder they show (see ItemsMixin.watch_portals).
        self._portal_watcher = QFileSystemWatcher(self)
        self._portal_watcher.directoryChanged.connect(self._portal_folder_changed)
        self._portal_dirty: set[str] = set()
        self._portal_timer = self._timer(300, self._refresh_dirty_portals)
        self._periodic = QTimer(self)
        self._periodic.setInterval(60_000)
        self._periodic.timeout.connect(lambda: self.import_new_desktop_items())
        self._periodic.timeout.connect(lambda: self.refresh_portals())
        self._pending_combo = ""

    def _timer(self, interval: int, slot) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(interval)
        timer.timeout.connect(slot)
        return timer

    # ------------------------------------------------------------------------------------
    # Start-up / monitors
    # ------------------------------------------------------------------------------------
    @property
    def preferences(self) -> Preferences:
        return self.state.preferences

    def start(self) -> None:
        self.refresh_monitors()
        self._ensure_state()
        for monitor in self._monitors:
            page = self.displayed_page(monitor.key)
            if page is not None:
                self.arranger.fit_page(page, monitor)
        self._restore_combo(combo_signature(self._monitors))
        self._build_scenes()
        for folder in self._desktop_dirs:
            self._watcher.addPath(str(folder))
        self.import_new_desktop_items(initial=True)
        self.refresh_all_items()
        self._periodic.start()
        app = QGuiApplication.instance()
        if app is not None and not self.demo:
            app.screenAdded.connect(lambda _s: self._screen_timer.start())
            app.screenRemoved.connect(lambda _s: self._screen_timer.start())
            app.primaryScreenChanged.connect(lambda _s: self._screen_timer.start())
            for screen in app.screens():
                self._watch_screen(screen)
            app.screenAdded.connect(self._watch_screen)
        if not self.preferences.first_arrange_done:
            self.preferences.first_arrange_done = True
        self.queue_save()

    def _watch_screen(self, screen) -> None:
        screen.geometryChanged.connect(lambda _g: self._screen_timer.start())
        screen.availableGeometryChanged.connect(lambda _g: self._screen_timer.start())

    def _ensure_state(self) -> None:
        if not self.state.pages:
            primary = primary_of(self._monitors)
            self.state.pages.append(PageState(title=DEFAULT_PAGE_TITLE, monitor_key=primary.key,
                                              monitor_label=primary.label))
        ensure_current_pages(self.state, self._monitors)

    def set_demo_size(self, width: int, height: int) -> None:
        self._demo_size = (int(width), int(height))

    def _read_monitors(self) -> list[MonitorSpec]:
        if self.demo:
            w, h = self._demo_size
            rect = Rect(0, 0, w, h)
            avail = Rect(0, 0, w, h - 48)
            return [MonitorSpec("demo", 1, rect, avail, True, 1.0, w, h)]
        app = QGuiApplication.instance()
        screens = list(app.screens()) if app is not None else []
        if not screens:
            rect = Rect(0, 0, 1920, 1080)
            return [MonitorSpec("screen", 1, rect, rect, True)]
        primary = QGuiApplication.primaryScreen()
        left = min(s.geometry().x() for s in screens)
        top = min(s.geometry().y() for s in screens)
        self._origin = (left, top)
        screens.sort(key=lambda s: (s is not primary, s.geometry().x(), s.geometry().y()))
        specs: list[MonitorSpec] = []
        seen: dict[str, int] = {}
        for index, screen in enumerate(screens):
            parts = (screen.manufacturer(), screen.model(), screen.serialNumber())
            base = "|".join(str(part).strip() for part in parts if str(part or "").strip())
            base = base or str(screen.name() or "screen")
            seen[base] = seen.get(base, 0) + 1
            key = base if seen[base] == 1 else "{0}#{1}".format(base, seen[base])
            geometry = screen.geometry().translated(-left, -top)
            available = screen.availableGeometry().translated(-left, -top)
            scale = float(screen.devicePixelRatio() or 1.0)
            specs.append(MonitorSpec(key, index + 1, lrect(geometry), lrect(available), screen is primary, scale,
                                     int(round(geometry.width() * scale)), int(round(geometry.height() * scale))))
        if specs and not any(s.primary for s in specs):
            specs[0] = dataclasses.replace(specs[0], primary=True)
        return specs

    def refresh_monitors(self) -> bool:
        self._monitors = self._read_monitors()
        return migrate_state(self.state, self._monitors)

    def monitors(self) -> list[MonitorSpec]:
        return list(self._monitors)

    def origin(self) -> tuple[int, int]:
        return self._origin

    def spec_for(self, key: str) -> MonitorSpec | None:
        return next((m for m in self._monitors if m.key == key), None)

    def primary_spec(self) -> MonitorSpec:
        return primary_of(self._monitors)

    def screen_for(self, key: str):
        """QScreen of a monitor key (None in demo mode)."""
        app = QGuiApplication.instance()
        spec = self.spec_for(key)
        if app is None or spec is None or self.demo:
            return None
        for screen in app.screens():
            g = screen.geometry()
            if (g.x() - self._origin[0], g.y() - self._origin[1]) == (spec.geometry.x, spec.geometry.y):
                return screen
        return None

    def wallpaper_targets(self) -> list:
        """Monitor rectangles for the wallpaper sampler (physical + logical).

        Qt 6 on Windows keeps each screen's native top-left and scales only the
        size, so the native rectangle is matched by position (then size).
        """
        from PySide6.QtCore import QRect

        from .. import native_win
        from .wallpaper import MonitorTarget

        native = [] if self.demo else native_win.monitor_rects()
        ox, oy = self._origin
        targets = []
        for spec in self._monitors:
            g = spec.geometry
            logical = QRect(g.x + ox, g.y + oy, g.w, g.h)
            width = spec.pixel_width or int(round(g.w * spec.scale))
            height = spec.pixel_height or int(round(g.h * spec.scale))
            physical = QRect(logical.x(), logical.y(), width, height)
            if native:
                def distance(m):
                    x, y, w, h = m["rect"]
                    return abs(x - logical.x()) + abs(y - logical.y()) + (abs(w - width) + abs(h - height)) // 4
                best = min(native, key=distance)
                if distance(best) <= 64:
                    physical = QRect(*best["rect"])
            targets.append(MonitorTarget(spec.key, physical, logical))
        return targets

    def board_bounds(self) -> Rect:
        rects = [m.geometry for m in self._monitors]
        result = rects[0]
        for rect in rects[1:]:
            result = result.united(rect)
        return result

    def displayed_page(self, key: str) -> PageState | None:
        page_id = self.state.current_pages.get(key, "")
        return self.state.page(page_id) if page_id else None

    def pages_info(self, key: str) -> list:
        spec = self.spec_for(key)
        if spec is None:
            return []
        current = self.state.current_pages.get(key, "")
        return [{"id": page.id, "title": page.title, "guest": guest, "current": page.id == current,
                 "label": guest_label(page) if guest else "", "count": len(page.islands)}
                for page, guest in pages_for_menu(self.state, spec, self._monitors)]

    def find_island(self, island_id: str):
        for page in self.state.pages:
            for island in page.islands:
                if island.id == island_id:
                    return page, island
        return None, None

    def monitor_of_page(self, page_id: str) -> str:
        return next((k for k, v in self.state.current_pages.items() if v == page_id
                     and self.spec_for(k) is not None), "")

    # Screen changes + A (layout memory per monitor combination, replug grace) -------------
    def _screens_settled(self) -> None:
        new = self._read_monitors()
        if combo_signature(new) == combo_signature(self._monitors):
            return
        lost = {m.key for m in self._monitors} - {m.key for m in new}
        self.remember_combo()  # the layout we are leaving
        if lost and self.preferences.replug_grace_s > 0:
            # A monitor vanished: often just sleep / input switching.  Keep the
            # remaining layouts frozen for a grace period; if the same
            # combination comes back, its remembered layout is restored as is.
            self._grace_timer.start(int(self.preferences.replug_grace_s) * 1000)
            self._apply_monitors(new, fit=False)
            return
        self._grace_timer.stop()
        self._apply_monitors(new, fit=True)

    def _grace_expired(self) -> None:
        self._apply_monitors(self._read_monitors(), fit=True)

    def _apply_monitors(self, monitors: list[MonitorSpec], fit: bool = True) -> None:
        if not monitors:
            return
        self.arranger.cancel_gestures()
        self._monitors = monitors
        migrate_state(self.state, monitors)
        ensure_current_pages(self.state, monitors)
        restored = self._restore_combo(combo_signature(monitors))
        if fit and not restored:
            for monitor in monitors:
                page = self.displayed_page(monitor.key)
                if page is not None:
                    self.arranger.fit_page(page, monitor)
        self._build_scenes()
        self.refresh_all_items()
        self.queue_save()

    def remember_combo(self) -> None:
        if not self.preferences.layout_memory or not self._monitors:
            return
        signature = combo_signature(self._monitors)
        islands = {}
        for monitor in self._monitors:
            page = self.displayed_page(monitor.key)
            if page is None:
                continue
            for s in page.islands:
                islands[s.id] = [int(s.x), int(s.y), int(s.width), int(s.height), bool(s.collapsed)]
        self.state.combos[signature] = {"current_pages": {m.key: self.state.current_pages.get(m.key, "")
                                                          for m in self._monitors},
                                        "islands": islands, "saved": int(time.time())}
        if len(self.state.combos) > 12:
            oldest = sorted(self.state.combos.items(), key=lambda kv: kv[1].get("saved", 0))
            for key, _v in oldest[:len(self.state.combos) - 12]:
                self.state.combos.pop(key, None)

    def _restore_combo(self, signature: str) -> bool:
        if not self.preferences.layout_memory:
            return False
        memory = self.state.combos.get(signature)
        if not memory:
            return False
        for key, page_id in dict(memory.get("current_pages", {})).items():
            if self.spec_for(key) is not None and self.state.page(page_id) is not None:
                self.state.current_pages[key] = page_id
        rects = memory.get("islands", {})
        for monitor in self._monitors:
            page = self.displayed_page(monitor.key)
            if page is None:
                continue
            for s in page.islands:
                saved = rects.get(s.id)
                if saved and len(saved) >= 4:
                    s.x, s.y, s.width, s.height = (int(v) for v in saved[:4])
            self.arranger.fit_page(page, monitor)
        return True

    # ------------------------------------------------------------------------------------
    # Scenes and proxies
    # ------------------------------------------------------------------------------------
    def _build_scenes(self) -> None:
        keys = {m.key for m in self._monitors}
        for key in list(self.scenes):
            if key not in keys:
                scene = self.scenes.pop(key)
                for proxy in scene.islands.items():
                    self._proxies.pop(proxy.state.id, None)
                    proxy.deleteLater()
                if self.layers is not None:
                    self.layers.remove_scene(scene)
                scene.deleteLater()
        for monitor in self._monitors:
            scene = self.scenes.get(monitor.key)
            if scene is None:
                scene = MonitorScene(monitor, self, self)
                self.scenes[monitor.key] = scene
            else:
                scene.set_spec(monitor)
            self.populate_scene(monitor.key)
        if self.wallpaper is not None:
            self.wallpaper.set_monitors(self.wallpaper_targets())
        self.scenesChanged.emit()
        if self.layers is not None:
            self.layers.sync()

    def populate_scene(self, key: str) -> None:
        scene = self.scenes.get(key)
        page = self.displayed_page(key)
        if scene is None:
            return
        scene.set_page(page.id if page is not None else "")
        wanted = [s for s in (page.islands if page is not None else [])]
        wanted_ids = {s.id for s in wanted}
        for proxy in scene.islands.items():
            if proxy.state.id not in wanted_ids or proxy.state not in wanted:
                scene.islands.remove(proxy)
                if self._proxies.get(proxy.state.id) is proxy:
                    self._proxies.pop(proxy.state.id, None)
                proxy.deleteLater()
        for s in wanted:
            proxy = self._proxies.get(s.id)
            if proxy is None or proxy.state is not s:
                proxy = IslandProxy(s, scene, self, self)
                self._proxies[s.id] = proxy
                proxy.geometryChanged.connect(self._loose_timer.start)
            elif proxy.scene is not scene:
                if proxy.scene is not None:
                    proxy.scene.islands.remove(proxy)
                proxy.set_scene(scene)
            proxy.sync_rect(animate=False)
            scene.islands.append(proxy)
            self.refresh_items(proxy)
        scene.changed.emit()
        self._loose_timer.start()

    def proxy(self, island_id: str) -> IslandProxy | None:
        return self._proxies.get(island_id)

    def proxies(self) -> list[IslandProxy]:
        return list(self._proxies.values())

    def reassign(self, proxy: IslandProxy, key: str) -> None:
        scene = self.scenes.get(key)
        if scene is None or proxy.scene is scene:
            return
        if proxy.scene is not None:
            proxy.scene.islands.remove(proxy)
        proxy.set_scene(scene)
        scene.islands.append(proxy)
        proxy.raise_()
        if self.layers is not None:
            self.layers.sync_pinned()

    # Arranger host -------------------------------------------------------------------------
    def queue_save(self) -> None:
        self._save_timer.start()
        self._loose_timer.start()

    def save_now(self) -> None:
        self.arranger.sync_norms()
        self.remember_combo()
        try:
            self.store.save(self.state)
        except (OSError, RuntimeError) as exc:
            self.show_notice("保存失败", str(exc), "warning")

    def set_ghosts(self, ghosts: list) -> None:
        for scene in self.scenes.values():
            area = scene.spec.geometry
            scene.set_ghosts([(r, s) for r, s in ghosts if r is not None and r.intersects(area)])

    def drag_shadow(self, proxy, rect) -> None:
        for scene in self.scenes.values():
            if proxy is None or rect is None or proxy.scene is scene or not rect.intersects(scene.spec.geometry):
                scene.set_shadow(None)
            else:
                scene.set_shadow({"visible": True, "x": rect.x, "y": rect.y, "w": rect.w, "h": rect.h,
                                  "title": proxy.state.title, "uid": proxy.state.id})

    def expand_now(self, proxy) -> None:
        proxy.state.collapsed = False
        proxy.refresh()
        self.refresh_items(proxy)
        self.queue_save()

    # Notices / confirm ----------------------------------------------------------------------
    def show_notice(self, title: str, text: str = "", kind: str = "info", actions=None, timeout: int = 4200) -> str:
        nid = uuid.uuid4().hex[:8]
        notice = Notice(nid, str(title), str(text), kind, list(actions or []), int(timeout), self)
        self.notices.append(notice)
        while len(self.notices) > 4:
            self.notices.remove(self.notices.at(0))
        return nid

    @Slot(str, str, str)
    def postNotice(self, title: str, text: str = "", kind: str = "info") -> None:  # noqa: N802
        """QML: show a notice (settings pages)."""
        self.show_notice(title, text, kind if kind in ("info", "success", "warning", "error") else "info")

    @Slot(str)
    def dismissNotice(self, nid: str) -> None:  # noqa: N802
        for notice in self.notices.items():
            if notice.nid == nid:
                self.notices.remove(notice)
                notice.deleteLater()

    @Slot(str, str)
    def noticeAction(self, nid: str, action: str) -> None:  # noqa: N802
        self.dismissNotice(nid)
        if action:
            self.run_action(action)

    def confirm(self, title: str, text: str, accept: str, callback, *, danger: bool = True,
                cancel_callback=None, source: str = "", monitor: str = "") -> str:
        """Non-modal confirmation shown on the desktop (used by UI and agent)."""
        cid = uuid.uuid4().hex[:8]
        self._confirm_callbacks[cid] = (callback, cancel_callback)
        self._confirm = {"id": cid, "title": title, "text": text, "accept": accept, "danger": danger,
                         "source": source, "monitor": monitor}
        self.confirmChanged.emit()
        return cid

    @Slot(str, bool)
    def resolveConfirm(self, cid: str, accepted: bool) -> None:  # noqa: N802
        callbacks = self._confirm_callbacks.pop(cid, None)
        if self._confirm.get("id") == cid:
            self._confirm = {}
            self.confirmChanged.emit()
        if callbacks is None:
            return
        callback = callbacks[0] if accepted else callbacks[1]
        if callback is not None:
            callback()

    def pending_confirm(self) -> dict:
        return dict(self._confirm)

    confirmInfo = Property("QVariantMap", pending_confirm, notify=confirmChanged)

    # ------------------------------------------------------------------------------------
    # Global view state
    # ------------------------------------------------------------------------------------
    def set_hidden(self, hidden: bool) -> None:
        hidden = bool(hidden)
        if hidden == self._hidden:
            return
        self._hidden = hidden
        self.hiddenChanged.emit()
        self._loose_timer.start()

    @Slot()
    def toggleHidden(self) -> None:  # noqa: N802
        self.set_hidden(not self._hidden)

    def set_focus_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._focus:
            return
        self._focus = enabled
        if enabled and self._hidden:
            self.set_hidden(False)
        self.focusChanged.emit()
        if self.layers is not None:
            self.layers.set_focus_overlay(enabled)

    @Slot()
    def toggleFocus(self) -> None:  # noqa: N802
        self.set_focus_mode(not self._focus)

    @Slot(str, str)
    def togglePanel(self, name: str, monitor_key: str = "") -> None:  # noqa: N802
        if self._panel == name and (not monitor_key or monitor_key == self._panel_monitor):
            name = ""
        self._panel = name
        self._panel_arg = ""
        self._panel_monitor = monitor_key or self.primary_spec().key
        self.panelChanged.emit()

    @Slot(str, str, str)
    def openPanel(self, name: str, monitor_key: str = "", arg: str = "") -> None:  # noqa: N802
        """Open (never toggle) a bar panel; ``arg`` e.g. "rename:<pageId>" for the presets panel."""
        self._panel = name
        self._panel_arg = arg
        self._panel_monitor = monitor_key or self.primary_spec().key
        self.panelChanged.emit()

    @Slot()
    def closePanel(self) -> None:  # noqa: N802
        if self._panel:
            self._panel = ""
            self.panelChanged.emit()
        self.wantKeyboard(False)

    @Slot(bool)
    @Slot(bool, str)
    def wantKeyboard(self, on: bool, monitor_key: str = "") -> None:  # noqa: N802
        """Layer windows are no-activate; text fields ask for keyboard focus here."""
        on = bool(on)
        key = monitor_key or self._panel_monitor or self.primary_spec().key
        if on == self._keyboard and (not on or key == self._keyboard_key):
            return
        self._keyboard = on
        self._keyboard_key = key if on else ""
        self.keyboardChanged.emit()
        if self.layers is not None:
            self.layers.set_keyboard(on, key)

    @Slot()
    def dismissMenus(self) -> None:  # noqa: N802
        self.menusDismissed.emit()

    hidden = Property(bool, lambda self: self._hidden, notify=hiddenChanged)
    focusMode = Property(bool, lambda self: self._focus, notify=focusChanged)
    canUndo = Property(bool, lambda self: self.arranger.can_undo(), notify=undoChanged)
    panel = Property(str, lambda self: self._panel, notify=panelChanged)
    panelMonitor = Property(str, lambda self: self._panel_monitor, notify=panelChanged)
    panelArg = Property(str, lambda self: self._panel_arg, notify=panelChanged)
    noticesModel = Property(QObject, lambda self: self.notices, constant=True)
    version = Property(str, lambda self: __version__, constant=True)
    isDemo = Property(bool, lambda self: bool(self.demo), constant=True)
    isWindows = Property(bool, lambda self: sys.platform == "win32", constant=True)
    draggingItems = Property(bool, lambda self: self._dragging_items, notify=panelChanged)
    keyboard = Property(bool, lambda self: self._keyboard, notify=keyboardChanged)

    @Slot()
    def undo(self) -> None:
        if not self.arranger.undo():
            self.show_notice("撤销排布", "没有可以撤销的排布。")

    @Slot(str)
    def arrange(self, key: str = "") -> None:
        keys = [key] if key else [m.key for m in self._monitors]
        failed = [k for k in keys if not self.arranger.arrange(k)]
        if failed:
            self.show_notice("自动排布", "空间不足，部分显示器无法按首选尺寸排布。", "warning")

    # ------------------------------------------------------------------------------------
    # Gestures from QML (board coordinates)
    # ------------------------------------------------------------------------------------
    @Slot(str)
    def dragBegin(self, uid: str) -> None:  # noqa: N802
        proxy = self.proxy(uid)
        if proxy is not None and not proxy.state.locked:
            self.arranger.drag_begin(proxy)

    @Slot(str, float, float, float, float)
    def dragMove(self, uid: str, x: float, y: float, cx: float, cy: float) -> None:  # noqa: N802
        proxy = self.proxy(uid)
        if proxy is not None:
            self.arranger.drag_move(proxy, x, y, (cx, cy))

    @Slot(str)
    def dragEnd(self, uid: str) -> None:  # noqa: N802
        proxy = self.proxy(uid)
        if proxy is not None:
            self.arranger.drag_end(proxy)
            self.islandsChanged.emit()

    @Slot(str, str)
    def resizeBegin(self, uid: str, edge: str) -> None:  # noqa: N802
        proxy = self.proxy(uid)
        if proxy is not None and not proxy.state.locked and not proxy.state.collapsed:
            self.arranger.resize_begin(proxy, edge)

    @Slot(str, float, float)
    def resizeMove(self, uid: str, dx: float, dy: float) -> None:  # noqa: N802
        proxy = self.proxy(uid)
        if proxy is not None:
            self.arranger.resize_move(proxy, dx, dy)

    @Slot(str)
    def resizeEnd(self, uid: str) -> None:  # noqa: N802
        proxy = self.proxy(uid)
        if proxy is not None:
            self.arranger.resize_end(proxy)

    @Slot()
    def cancelGestures(self) -> None:  # noqa: N802
        self.arranger.cancel_gestures()

    # Capsule peek (B) ---------------------------------------------------------------------
    @Slot(str, bool)
    def hoverIsland(self, uid: str, inside: bool) -> None:  # noqa: N802
        proxy = self.proxy(uid)
        if proxy is None or not proxy.state.capsule:
            return
        timer = self._peek_timers.get(uid)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda u=uid: self._peek_fire(u))
            self._peek_timers[uid] = timer
        timer.setProperty("want", bool(inside))
        timer.start(int(self.preferences.capsule_peek_ms) if inside else 420)

    def _peek_fire(self, uid: str) -> None:
        proxy = self.proxy(uid)
        timer = self._peek_timers.get(uid)
        if proxy is None or timer is None:
            return
        want = bool(timer.property("want"))
        if self.arranger.drag_active() or self.arranger.resize_active():
            want = False
        proxy.set_peek(want)
        if want:
            proxy.raise_()
            self.refresh_items(proxy)

    # ------------------------------------------------------------------------------------
    # Islands
    # ------------------------------------------------------------------------------------
    def add_island(self, kind: str = "files", *, monitor_key: str = "", title: str = "", folder: str = "",
                   url: str = "", widget: str = "", html_path: str = "", rect=None,
                   config: dict | None = None, size=None, position=None) -> IslandState | None:
        spec = self.spec_for(monitor_key) or self.primary_spec()
        page = self.displayed_page(spec.key)
        if page is None:
            return None
        kind = kind if kind in ("files", "web", "widget") else "files"
        if kind == "web" and html_path and not url:
            from pathlib import Path

            url = Path(html_path).resolve().as_uri()
        defaults = {"web": "网页", "widget": WIDGET_TITLES.get(widget, "小组件")}
        name = (title or "").strip() or defaults.get(kind, "") or (os.path.basename(folder.rstrip("\\/"))
                                                                    if folder else "新收纳岛")
        state = IslandState(title=name, kind=kind)
        if kind == "files":
            tab = TabState(title="全部", portal_path=folder or "", sort_mode="name" if folder else "manual")
            state.tabs = [tab]
            state.active_tab_id = tab.id
            state.width, state.height = layout.DEFAULT_W, layout.DEFAULT_H
            if folder:
                state.width, state.height = 400, 320
        elif kind == "web":
            state.tabs = [TabState(title="全部")]
            state.active_tab_id = state.tabs[0].id
            state.web_url = url
            state.html_path = html_path
            state.html_allow_network = not bool(html_path)
            state.width, state.height = layout.WEB_DEFAULT_W, layout.WEB_DEFAULT_H
        else:
            state.widget = widget or "clock"
            state.widget_config = dict(config or {})
            state.tabs = [TabState(title="全部")]
            state.active_tab_id = state.tabs[0].id
            state.width, state.height = WIDGET_SIZES.get(state.widget, (320, 220))
        if kind == "widget" and state.widget.startswith("custom:") and size is None and self.custom is not None:
            info = self.custom.widget(state.widget)
            if info is not None:
                size = info["size"]
        if size is not None:
            state.width, state.height = max(min_size(state)[0], int(size[0])), max(min_size(state)[1], int(size[1]))
        if rect is not None:
            state.width, state.height = max(min_size(state)[0], int(rect[2])), max(min_size(state)[1], int(rect[3]))
        target = (int(rect[0]), int(rect[1])) if rect is not None else None
        if target is None and position is not None:
            target = (int(position[0]), int(position[1]))
        if not self.arranger.place_new(spec.key, state, target):
            self.show_notice("空间不足", "“{0}”所在显示器没有空位了。可以先收起或缩小其他收纳岛。".format(spec.label),
                             "warning")
            return None
        self.populate_scene(spec.key)
        proxy = self.proxy(state.id)
        if proxy is not None:
            proxy.raise_()
            proxy.flash.emit("appear")
        self.queue_save()
        self.islandsChanged.emit()
        return state

    def delete_island(self, island_id: str) -> bool:
        page, island = self.find_island(island_id)
        if island is None:
            return False
        self._capsule_layouts.pop(island_id, None)
        existing = {os.path.normcase(i.path) for i in self.state.loose_items}
        for tab in island.tabs:
            if tab.portal_path:
                continue
            for item in tab.items:
                key = os.path.normcase(item.path)
                if key not in existing:
                    self.state.loose_items.append(ItemRef(path=item.path, title=item.title))
                    existing.add(key)
        self.arranger.push_undo()
        page.islands.remove(island)
        self.state.rules = [r for r in self.state.rules if getattr(r, "target_island_id", "") != island_id]
        self._rules.rules = self.state.rules
        self.rulesChanged.emit()
        key = self.monitor_of_page(page.id)
        if key:
            self.populate_scene(key)
            self.arranger.relax(key)
        self.refresh_all_items()
        self.queue_save()
        self.islandsChanged.emit()
        if self.layers is not None:
            self.layers.sync_pinned()
        return True

    def ask_delete_island(self, island_id: str, source: str = "") -> str:
        page, island = self.find_island(island_id)
        if island is None:
            return ""
        count = sum(len(t.items) for t in island.tabs if not t.portal_path)
        text = "收纳岛里的 {0} 个图标会回到桌面散放区，文件不会被删除。".format(count) if island.kind == "files" \
            else "只会移除这个{0}，不会影响任何文件。".format("网页岛" if island.kind == "web" else "小组件")
        return self.confirm("删除“{0}”？".format(island.title), text, "删除",
                            lambda: self.delete_island(island_id), source=source,
                            monitor=getattr(page, "monitor_key", ""))

    @Slot(str, str, "QVariant")
    def act(self, uid: str, name: str, args=None) -> None:
        """Island actions from QML (menus, header buttons, widgets)."""
        self.island_action(uid, name, args if args is not None else {})

    def island_action(self, uid: str, name: str, args=None):  # noqa: C901 - dispatcher
        args = dict(args or {}) if isinstance(args, dict) else {"value": args}
        proxy = self.proxy(uid)
        _page, s = self.find_island(uid)
        if s is None:
            return None
        value = args.get("value")
        if name == "collapse":
            want = (not s.collapsed) if value is None else bool(value)
            if want and not s.collapsed:
                s.collapsed = True
                if proxy is not None:
                    proxy.refresh()
                    self.arranger.after_collapse(proxy)
            elif not want and s.collapsed:
                if proxy is None:
                    s.collapsed = False
                elif self.arranger.request_expand(proxy):
                    self.expand_now(proxy)
        elif name == "lock":
            s.locked = (not s.locked) if value is None else bool(value)
        elif name == "pin":
            s.pin_on_top = (not s.pin_on_top) if value is None else bool(value)
            if self.layers is not None:
                QTimer.singleShot(0, self.layers.sync_pinned)
        elif name == "keepVisible":
            s.exclude_from_hide = (not s.exclude_from_hide) if value is None else bool(value)
        elif name == "capsule":
            want = (not s.capsule) if value is None else bool(value)
            expanding = s.capsule and not want
            collapsing = not s.capsule and want
            snapshot = None
            if expanding:
                snapshot = self.arranger.snapshot()          # before it grows into an island
            elif collapsing:
                snapshot = self._capsule_layouts.pop(uid, None)
            s.capsule = want
            if proxy is not None:
                proxy.set_peek(False)
            if expanding and snapshot is not None:
                self._capsule_layouts[uid] = snapshot
            elif collapsing and snapshot is not None:
                # Folding back: put the pill (and everything the expand pushed away) where it was.
                QTimer.singleShot(0, lambda sn=snapshot: self.arranger.restore_snapshot(sn))
        elif name == "rename":
            title = str(args.get("title", value or "")).strip()
            if title:
                s.title = title[:60]
                self.islandsChanged.emit()
        elif name == "material":
            material = str(args.get("material", value or ""))
            s.material = material if material in MATERIALS else ""
        elif name == "delete":
            if args.get("confirmed"):
                self.delete_island(uid)
            else:
                self.ask_delete_island(uid)
            return None
        elif name == "raise":
            if proxy is not None:
                proxy.raise_()
            return None
        elif name == "tab":
            tab_id = str(args.get("id", value or ""))
            if any(t.id == tab_id for t in s.tabs):
                s.active_tab_id = tab_id
                if proxy is not None:
                    proxy.set_portal("")
        elif name == "addTab":
            title = str(args.get("title", value or "")).strip() or "新标签"
            tab = TabState(title=title[:24])
            s.tabs.append(tab)
            s.active_tab_id = tab.id
        elif name == "renameTab":
            tab = self.find_tab(uid, str(args.get("id", "")))
            title = str(args.get("title", "")).strip()
            if tab is not None and title:
                tab.title = title[:24]
        elif name == "closeTab":
            tab = self.find_tab(uid, str(args.get("id", value or "")))
            if tab is not None and len(s.tabs) > 1:
                rest = [t for t in s.tabs if t is not tab]
                keep = next((t for t in rest if not t.portal_path), None)
                if keep is not None and not tab.portal_path:
                    known = {os.path.normcase(i.path) for i in keep.items}
                    keep.items.extend(i for i in tab.items if os.path.normcase(i.path) not in known)
                elif not tab.portal_path:
                    self.state.loose_items.extend(tab.items)
                s.tabs = rest
                if s.active_tab_id == tab.id:
                    s.active_tab_id = rest[0].id
        elif name == "iconSize":
            if "delta" in args:
                sizes = list(ICON_SIZES)
                current = min(range(len(sizes)), key=lambda i: abs(sizes[i] - s.icon_size))
                current = max(0, min(len(sizes) - 1, current + (1 if float(args["delta"]) > 0 else -1)))
                s.icon_size = sizes[current]
            else:
                s.icon_size = max(24, min(128, int(args.get("size", value or 48))))
        elif name == "sort":
            tab = self.find_tab(uid)
            if tab is not None:
                mode = str(args.get("mode", value or tab.sort_mode))
                if mode in SORT_MODES:
                    if tab.sort_mode == mode and "descending" not in args and mode != "manual":
                        tab.sort_descending = not tab.sort_descending
                    tab.sort_mode = mode
                if "descending" in args:
                    tab.sort_descending = bool(args["descending"])
        elif name == "autoSort":
            tab = self.find_tab(uid)
            if tab is not None and not tab.portal_path:
                mode = str(args.get("mode", value or tab.auto_sort or "name"))
                records = self.records_for(s, TabState(items=tab.items, sort_mode=mode,
                                                       sort_descending=tab.sort_descending))
                order = {os.path.normcase(r.path): i for i, r in enumerate(records)}
                tab.items.sort(key=lambda i: order.get(os.path.normcase(i.path), 1 << 30))
                tab.sort_mode = "manual"
                tab.auto_sort = mode if mode in ("name", "type", "modified") else tab.auto_sort
        elif name == "portal":
            tab = self.find_tab(uid)
            folder = str(args.get("path", value or ""))
            if tab is not None:
                if folder and os.path.isdir(folder):
                    if not tab.portal_path and tab.items:
                        known = {os.path.normcase(i.path) for i in self.state.loose_items}
                        self.state.loose_items.extend(i for i in tab.items if os.path.normcase(i.path) not in known)
                        tab.items = []
                    tab.portal_path = folder
                    if tab.sort_mode == "manual":
                        tab.sort_mode = "name"
                else:
                    tab.portal_path = ""
                if proxy is not None:
                    proxy.set_portal("")
        elif name == "portalOpen":
            if proxy is not None and os.path.isdir(str(value or args.get("path", ""))):
                proxy.set_portal(str(value or args.get("path")))
        elif name == "portalUp":
            if proxy is not None and proxy.portalCanUp:
                parent = os.path.dirname(proxy.portalPath.rstrip("\\/"))
                root = proxy.portalRoot
                proxy.set_portal("" if os.path.normcase(parent) == os.path.normcase(root) else parent)
        elif name == "portalHome":
            if proxy is not None:
                proxy.set_portal("")
        elif name == "media":
            if "path" in args:
                path = str(args.get("path") or "")
                if path and hasattr(self.store, "import_media"):
                    try:
                        path = self.store.import_media(path)
                    except (OSError, RuntimeError, ValueError) as exc:
                        self.show_notice("背景媒体", str(exc), "warning")
                        path = ""
                s.media_path = path
            if "opacity" in args:
                s.media_opacity = max(0.1, min(1.0, float(args["opacity"])))
            if "feather" in args:
                s.media_feather = max(0, min(120, int(args["feather"])))
        elif name == "widgetConfig":
            config = dict(s.widget_config)
            config.update({k: v for k, v in args.items() if k != "value"})
            s.widget_config = config
            host = getattr(self.layers, "webhost", None) if self.layers is not None else None
            if host is not None:
                host.config_changed(s.id)
        elif name.startswith("web."):
            return self.web_action(s, proxy, name[4:], args)
        else:
            return None
        if proxy is not None:
            proxy.notify()
            if name in ("tab", "addTab", "closeTab", "iconSize", "sort", "autoSort", "portal", "portalOpen",
                        "portalUp", "portalHome", "capsule"):
                self.refresh_items(proxy)
        self.queue_save()
        return True

    def web_action(self, s: IslandState, proxy, name: str, args: dict):
        value = args.get("value")
        host = self.layers.web_host(s.id) if self.layers is not None else None
        if name == "url":
            url = str(args.get("url", value or "")).strip()
            if url and "://" not in url and not url.startswith("about:"):
                url = "https://" + url
            if url:
                s.web_url = url
                if host is not None:
                    host.navigate(url)
        elif name == "home":
            if host is not None:
                host.navigate(s.web_url)
        elif name == "reload":
            if host is not None:
                host.reload()
        elif name == "back":
            if host is not None:
                host.back()
        elif name == "forward":
            if host is not None:
                host.forward()
        elif name == "stop":
            if host is not None:
                host.stop()
        elif name == "external":
            from PySide6.QtGui import QDesktopServices
            from PySide6.QtCore import QUrl

            current = (proxy.web.get("url") if proxy is not None else "") or s.web_url
            if current:
                QDesktopServices.openUrl(QUrl(current))
            return True
        elif name == "toolbar":
            s.web_toolbar = (not s.web_toolbar) if value is None else bool(value)
        elif name == "refresh":
            s.web_refresh_minutes = max(0, min(1440, int(args.get("minutes", value or 0))))
            if host is not None:
                host.set_refresh(s.web_refresh_minutes)
        elif name == "zoom":
            s.web_zoom = max(0.25, min(5.0, float(args.get("zoom", value or 1.0))))
            if host is not None:
                host.set_zoom(s.web_zoom)
        elif name == "network":
            s.html_allow_network = (not s.html_allow_network) if value is None else bool(value)
        if proxy is not None:
            proxy.notify()
        self.queue_save()
        return True

    # ------------------------------------------------------------------------------------
    # Presets (pages)
    # ------------------------------------------------------------------------------------
    def switch_page(self, key: str, page_id: str) -> bool:
        spec = self.spec_for(key)
        page = self.state.page(page_id)
        if spec is None or page is None:
            return False
        if self.state.current_pages.get(key) == page_id:
            return True
        # A preset can only be shown on one monitor at a time.
        for other, shown in list(self.state.current_pages.items()):
            if shown == page_id and other != key and self.spec_for(other) is not None:
                return False
        self.arranger.cancel_gestures()
        self.arranger.clear_undo()
        self.state.current_pages[key] = page_id
        if spec.primary:
            self.state.current_page_id = page_id
        self.arranger.fit_page(page, spec)
        self.populate_scene(key)
        self.refresh_all_items()
        self.queue_save()
        self.islandsChanged.emit()
        if self.layers is not None:
            self.layers.sync_pinned()
        return True

    @Slot(str, int)
    def cyclePage(self, key: str, step: int) -> None:  # noqa: N802
        key = key or self._monitor_under_cursor()
        pages = [p for p in self.pages_info(key) if not p["guest"]]
        if len(pages) < 2:
            return
        ids = [p["id"] for p in pages]
        current = self.state.current_pages.get(key, "")
        index = ids.index(current) if current in ids else 0
        self.switch_page(key, ids[(index + step) % len(ids)])

    def new_page(self, key: str, title: str = "", duplicate_of: str = "") -> PageState | None:
        spec = self.spec_for(key)
        if spec is None:
            return None
        source = self.state.page(duplicate_of) if duplicate_of else None
        if source is not None:
            page = PageState.from_dict(copy.deepcopy(source.to_dict()))
            page.id = uuid.uuid4().hex
            for island in page.islands:
                island.id = uuid.uuid4().hex
                for tab in island.tabs:
                    tab.id = uuid.uuid4().hex
                island.active_tab_id = island.tabs[0].id if island.tabs else ""
            page.title = title or "{0} 副本".format(source.title)
        else:
            page = PageState(title=title or "新预设")
        page.monitor_key, page.monitor_label = spec.key, spec.label
        self.state.pages.append(page)
        self.switch_page(key, page.id)
        return page

    def rename_page(self, page_id: str, title: str) -> bool:
        page = self.state.page(page_id)
        title = (title or "").strip()
        if page is None or not title:
            return False
        page.title = title[:40]
        for scene in self.scenes.values():
            scene.changed.emit()
        self.queue_save()
        return True

    def delete_page(self, page_id: str) -> bool:
        page = self.state.page(page_id)
        if page is None:
            return False
        own = [p for p in self.state.pages if p.monitor_key == page.monitor_key]
        if len(own) <= 1 and self.spec_for(page.monitor_key) is not None:
            self.show_notice("无法删除", "每个显示器至少要保留一个预设。", "warning")
            return False
        for island in page.islands:
            for tab in island.tabs:
                if not tab.portal_path:
                    known = {os.path.normcase(i.path) for i in self.state.loose_items}
                    self.state.loose_items.extend(i for i in tab.items if os.path.normcase(i.path) not in known)
        shown_on = self.monitor_of_page(page_id)
        self.state.pages.remove(page)
        gone = {island.id for island in page.islands}
        kept = [r for r in self.state.rules if getattr(r, "target_island_id", "") not in gone]
        if len(kept) != len(self.state.rules):
            # Rules that filed items into this preset's islands have nowhere to go now.
            self.state.rules = kept
            self._rules.rules = self.state.rules
            self.rulesChanged.emit()
        if shown_on:
            replacement = next(p for p in self.state.pages if p.monitor_key == page.monitor_key
                               or p.monitor_key == shown_on)
            self.state.current_pages[shown_on] = replacement.id
            self.arranger.clear_undo()
            spec = self.spec_for(shown_on)
            if spec is not None:
                self.arranger.fit_page(replacement, spec)
            self.populate_scene(shown_on)
        for scene in self.scenes.values():
            scene.changed.emit()
        self.refresh_all_items()
        self.queue_save()
        self.islandsChanged.emit()
        return True

    def ask_delete_page(self, page_id: str, source: str = "") -> str:
        page = self.state.page(page_id)
        if page is None:
            return ""
        return self.confirm("删除预设“{0}”？".format(page.title),
                            "其中的 {0} 个收纳岛会一起删除，图标回到桌面散放区，文件不受影响。".format(len(page.islands)),
                            "删除预设", lambda: self.delete_page(page_id), source=source)

    def _monitor_under_cursor(self) -> str:
        pos = QCursor.pos()
        x, y = pos.x() - self._origin[0], pos.y() - self._origin[1]
        return monitor_at(x, y, self._monitors).key if self._monitors else ""

    # ------------------------------------------------------------------------------------
    # Preferences bridge
    # ------------------------------------------------------------------------------------
    def _prefs_map(self) -> dict:
        return self.preferences.to_dict()

    prefs = Property("QVariantMap", _prefs_map, notify=prefsChanged)

    @Slot(str, "QVariant")
    def setPref(self, name: str, value) -> None:  # noqa: N802
        self.set_preferences({name: value})

    def set_preferences(self, values: dict) -> dict:
        data = self.preferences.to_dict()
        unknown = [k for k in values if k not in data]
        data.update({k: v for k, v in values.items() if k in data})
        new = Preferences.from_dict(data)
        new.extra = self.preferences.extra
        old = self.preferences
        self.state.preferences = new
        self.apply_preferences(old)
        self.prefsChanged.emit()
        self.queue_save()
        return {"unknown": unknown}

    def apply_preferences(self, old: Preferences | None = None) -> None:
        prefs = self.preferences
        if self.theme is not None:
            self.theme.set_preferences(prefs)
        if self.wallpaper is not None:
            self.wallpaper.configure(prefs.wallpaper_mode, prefs.wallpaper_image, max_fps=prefs.live_fps)
        if old is None or old.layout_gap != prefs.layout_gap or old.snap_to_grid != prefs.snap_to_grid:
            self.arranger.repair_all()
        for proxy in self._proxies.values():
            proxy.notify()
        if self.layers is not None:
            self.layers.apply_preferences(prefs, old)

    # ------------------------------------------------------------------------------------
    # State replacement (snapshots, import)
    # ------------------------------------------------------------------------------------
    def replace_state(self, state: AppState) -> None:
        self.arranger.cancel_gestures()
        self.arranger.clear_undo()
        for proxy in list(self._proxies.values()):
            if proxy.scene is not None:
                proxy.scene.islands.remove(proxy)
            proxy.deleteLater()
        self._proxies.clear()
        self.state = state
        self._rules.rules = state.rules
        migrate_state(self.state, self._monitors)
        self._ensure_state()
        for monitor in self._monitors:
            page = self.displayed_page(monitor.key)
            if page is not None:
                self.arranger.fit_page(page, monitor)
        self._build_scenes()
        self.refresh_all_items()
        self.apply_preferences()
        self.prefsChanged.emit()
        self.stateReplaced.emit()
        self.islandsChanged.emit()
        self.save_now()

    def save_snapshot(self, name: str = "") -> str:
        self.arranger.sync_norms()
        path = self.store.save_snapshot(self.state, name or None)
        self.snapshotsChanged.emit()
        return str(path)

    def snapshots(self) -> list:
        result = []
        for path in self.store.list_snapshots():
            try:
                stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(path.stat().st_mtime))
            except OSError:
                stamp = ""
            # "20250101-120000-123456--name.json": show the name part only.
            name = path.stem.split("--", 1)[1] if "--" in path.stem else path.stem
            result.append({"path": str(path), "name": "布局快照" if name == "layout" else name, "time": stamp,
                           "file": path.name})
        return result

    def delete_snapshot(self, path: str) -> bool:
        ok = self.store.delete_snapshot(path)
        self.snapshotsChanged.emit()
        if not ok:
            self.show_notice("无法删除快照", os.path.basename(path), "warning")
        return ok

    def restore_snapshot(self, path: str) -> bool:
        try:
            self.store.save_snapshot(self.state, "恢复前自动备份")
            state = self.store.restore_snapshot(path)
        except (OSError, RuntimeError, ValueError) as exc:
            self.show_notice("恢复失败", str(exc), "warning")
            return False
        self.replace_state(state)
        self.show_notice("已恢复布局快照", os.path.basename(path))
        return True

    # ------------------------------------------------------------------------------------
    # Generic action ids (menus, tray, notices, agent) - see menus.py
    # ------------------------------------------------------------------------------------
    @Slot(str)
    def run_action(self, action: str, args: dict | None = None) -> None:
        from .menus import dispatch

        dispatch(self, action, args or {})

    @Slot(str, "QVariant")
    def action(self, action: str, args=None) -> None:
        self.run_action(action, dict(args) if isinstance(args, dict) else {})

    @Slot(str, str, "QVariant", result="QVariantList")
    def menu(self, context: str, target: str = "", extra=None) -> list:
        from .menus import build

        return build(self, context, target, dict(extra) if isinstance(extra, dict) else {})

    @Slot(str, str, str, "QVariant")
    def menuAction(self, context: str, target: str, action: str, extra=None) -> None:  # noqa: N802
        from .menus import dispatch

        payload = dict(extra) if isinstance(extra, dict) else {}
        payload.setdefault("target", target)
        payload.setdefault("context", context)
        dispatch(self, action, payload)

    @Slot(str)
    def openSettings(self, page: str = "") -> None:  # noqa: N802
        self.closePanel()
        self.settingsRequested.emit(page or "")

    @Slot(result=str)
    def pickFolder(self) -> str:  # noqa: N802
        from PySide6.QtWidgets import QFileDialog

        return QFileDialog.getExistingDirectory(None, "选择文件夹", os.path.expanduser("~")) or ""

    @Slot(str, str, result=str)
    def pickFile(self, title: str, filters: str) -> str:  # noqa: N802
        from PySide6.QtWidgets import QFileDialog

        path, _f = QFileDialog.getOpenFileName(None, title or "选择文件", os.path.expanduser("~"), filters or "")
        return path or ""

    @Slot(result=str)
    def importFont(self) -> str:  # noqa: N802
        """Settings: pick a .ttf/.otf/.ttc file, register it and make it the UI font."""
        from .style import load_font_file

        path = self.pickFile("选择字体文件", "字体文件 (*.ttf *.otf *.ttc)")
        if not path:
            return ""
        family = load_font_file(path)
        if not family:
            self.show_notice("无法使用这个字体文件", os.path.basename(path), "warning")
            return ""
        self.set_preferences({"font_file": path, "font_family": family})
        self.show_notice("已导入字体", family)
        return family

    # Layout snapshots (settings page) ---------------------------------------------------
    @Slot(result="QVariantList")
    def snapshotList(self):  # noqa: N802
        return self.snapshots()

    # Auto-sort rules (settings page) ----------------------------------------------------
    RULE_CONDITIONS = ("extension", "name_contains", "name_starts", "name_ends", "kind")
    RULE_KINDS = ("folder", "shortcut", "image", "document", "media", "archive")

    @Slot(result="QVariantList")
    def ruleTargets(self):  # noqa: N802
        """Files islands a rule can put items into: [{id, title, page}]."""
        result = []
        for page in self.state.pages:
            for island in page.islands:
                if island.kind == "files" and any(not t.portal_path for t in island.tabs):
                    result.append({"id": island.id, "title": island.title or "收纳岛", "page": page.title})
        return result

    @Slot(result="QVariantList")
    def ruleList(self):  # noqa: N802
        targets = {t["id"]: t for t in self.ruleTargets()}
        result = []
        for rule in sorted(self.state.rules, key=lambda r: r.priority):
            target = targets.get(rule.target_island_id)
            result.append({
                "id": rule.id, "name": rule.name, "condition": rule.condition, "value": rule.value,
                "target": rule.target_island_id, "enabled": bool(rule.enabled), "priority": int(rule.priority),
                "targetTitle": target["title"] if target else "",
                "targetPage": target["page"] if target else "",
                "valid": bool(target) and rule.condition in self.RULE_CONDITIONS and bool(rule.value.strip()),
            })
        return result

    def _renumber_rules(self, ordered: list) -> None:
        for index, rule in enumerate(ordered):
            rule.priority = (index + 1) * 10
        self.state.rules[:] = ordered
        self._rules.rules = self.state.rules
        self.rulesChanged.emit()
        self.queue_save()

    @Slot("QVariant", result=str)
    def saveRule(self, data) -> str:  # noqa: N802
        """Create (no id) or update a rule from the settings editor; returns its id."""
        from ..models import Rule

        data = dict(data) if isinstance(data, dict) else {}
        condition = str(data.get("condition") or "extension")
        if condition not in self.RULE_CONDITIONS:
            condition = "extension"
        values = {
            "name": str(data.get("name") or "").strip() or "未命名规则",
            "condition": condition,
            "value": str(data.get("value") or "").strip(),
            "target_island_id": str(data.get("target") or ""),
            "enabled": bool(data.get("enabled", True)),
        }
        ordered = sorted(self.state.rules, key=lambda r: r.priority)
        rule = next((r for r in ordered if r.id == str(data.get("id") or "")), None)
        if rule is None:
            rule = Rule(**values)
            ordered.append(rule)
        else:
            for key, value in values.items():
                setattr(rule, key, value)
        self._renumber_rules(ordered)
        return rule.id

    @Slot(str, bool)
    def setRuleEnabled(self, rule_id: str, enabled: bool) -> None:  # noqa: N802
        for rule in self.state.rules:
            if rule.id == rule_id:
                rule.enabled = bool(enabled)
        self._renumber_rules(sorted(self.state.rules, key=lambda r: r.priority))

    @Slot(str, int)
    def moveRule(self, rule_id: str, step: int) -> None:  # noqa: N802
        ordered = sorted(self.state.rules, key=lambda r: r.priority)
        index = next((i for i, r in enumerate(ordered) if r.id == rule_id), -1)
        if index < 0:
            return
        new_index = max(0, min(len(ordered) - 1, index + int(step)))
        ordered.insert(new_index, ordered.pop(index))
        self._renumber_rules(ordered)

    @Slot(str)
    def deleteRule(self, rule_id: str) -> None:  # noqa: N802
        """The settings page asks for confirmation inline (second click) before calling this."""
        if any(r.id == rule_id for r in self.state.rules):
            self._renumber_rules(sorted((r for r in self.state.rules if r.id != rule_id), key=lambda r: r.priority))

    @Slot()
    def requestQuit(self) -> None:  # noqa: N802
        self.quitRequested.emit()

    def shutdown(self) -> None:
        self._save_timer.stop()
        self.save_now()


__all__ = ["DeskController", "combo_signature"]

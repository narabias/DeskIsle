"""DeskIsle 2.0 application bootstrap (Qt Quick).

Order matters:
1. environment + ``QQuickWindow.setDefaultAlphaBuffer(True)`` before any window,
2. data directory, single instance, logging, state (+ automatic 1.x backup),
3. services -> QML engine (image providers, context objects) -> DeskController
   -> layer windows -> tray / hotkeys / guardian / agent server.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import shutil
import sys
import tempfile
import time
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (QCoreApplication, QEvent, QLockFile, QObject, QPoint, Property, QRect, Qt, QTimer, QUrl, Signal, Slot,
                            qInstallMessageHandler, QtMsgType)
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlEngine
from PySide6.QtQuick import QQuickWindow
from PySide6.QtWidgets import QApplication

from .. import __version__, native_win
from .. import watchdog as crash_watchdog
from ..models import STATE_VERSION, AppState
from ..storage import StateStore

log = logging.getLogger("deskisle")
ASSETS = Path(__file__).resolve().parent.parent / "assets"
APP_ICON = ASSETS / "ui" / "app-icon.png"
IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------------------------
# Environment / data directory
# ---------------------------------------------------------------------------------------------
def prepare_environment() -> None:
    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")
    # Smooth curves for the glyph icons and the island outlines.
    os.environ.setdefault("QSG_RENDER_LOOP", "threaded" if IS_WINDOWS else os.environ.get("QSG_RENDER_LOOP", "basic"))
    QCoreApplication.setOrganizationName("DeskIsle")
    QCoreApplication.setApplicationName("DeskIsle")
    QCoreApplication.setApplicationVersion(__version__)
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    # Every layer/menu window is translucent: request an alpha swap chain.
    QQuickWindow.setDefaultAlphaBuffer(True)


def data_root(args) -> Path:
    if getattr(args, "data_dir", None):
        return Path(args.data_dir).expanduser()
    if getattr(args, "demo", False):
        return Path(tempfile.gettempdir()) / "DeskIsleDemo"
    return StateStore(None).root


def setup_logging(root: Path, verbose: bool = False) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "deskisle.log"
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger = logging.getLogger("deskisle")
    logger.handlers[:] = [handler]
    if verbose or not getattr(sys, "frozen", False):
        stream = logging.StreamHandler(sys.stderr) if sys.stderr is not None else None
        if stream is not None:
            stream.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
            logger.addHandler(stream)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    def qt_messages(mode, context, message) -> None:
        if "QQmlComponent: Created graphical object was not placed" in message:
            return
        level = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
                 QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
                 QtMsgType.QtFatalMsg: logging.CRITICAL}.get(mode, logging.INFO)
        where = ""
        if context is not None and context.file:
            where = " ({0}:{1})".format(os.path.basename(context.file), context.line)
        logging.getLogger("deskisle.qt").log(level, "%s%s", message, where)

    # A Python message handler must hold the GIL.  Qt's QML type loader thread emits warnings while the
    # main thread (holding the GIL) waits for it synchronously, so a handler deadlocks the app.  QML
    # warnings reach the log through QQmlEngine.warnings instead (main thread); the handler is a
    # developer opt-in only.
    if os.environ.get("DESKISLE_QT_LOG") == "1":
        qInstallMessageHandler(qt_messages)
    return path


def load_state(store: StateStore) -> tuple[AppState, str]:
    """Load (and migrate) the layout.  A 1.x file is copied to snapshots first."""
    note = ""
    try:
        raw = json.loads(store.state_path.read_text(encoding="utf-8-sig")) if store.state_path.is_file() else None
    except (OSError, ValueError):
        raw = None
    if isinstance(raw, dict) and int(raw.get("version", 1) or 1) < STATE_VERSION:
        try:
            store.snapshots_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-000000")
            target = store.snapshots_dir / "{0}--升级到2.0之前的布局.json".format(stamp)
            shutil.copy2(store.state_path, target)
            note = "已把 1.x 的布局自动迁移到 2.0，原文件备份在“布局快照”里。"
        except OSError:
            log.exception("could not back up the 1.x layout")
    state = store.load()
    return state, note


def app_icon() -> QIcon:
    return QIcon(str(APP_ICON)) if APP_ICON.is_file() else QIcon()


# ---------------------------------------------------------------------------------------------
class DeskIsleApp(QObject):
    """Owns every long-lived object of a running DeskIsle."""

    settingsWindowChanged = Signal()
    pausedChanged = Signal()
    infoChanged = Signal()          # update check / agent status (settings pages re-read App.*Info())
    wallChanged = Signal()          # primary wallpaper image changed (settings backdrop)
    layersChanged = Signal()        # layer windows were created / removed (popup windows re-anchor)
    settingsActiveChanged = Signal()

    def __init__(self, qapp: QApplication, store: StateStore, state: AppState, *, demo: bool,
                 root: Path, notes: list[str] | None = None, recovered: bool = False) -> None:
        super().__init__()
        self.qapp = qapp
        self.store = store
        self.state = state
        self.demo = demo
        self.root = root
        self.notes = list(notes or [])
        self.recovered = recovered
        self.settings_window = None
        self._download_percent = -1
        self.menu_window = None
        self.popups: dict[str, object] = {}   # role -> PopupWindow (panel / confirm / notice)
        self._layers_revision = 0
        self.layers = None
        self.desk = None
        self.agent = None
        self.webhost = None
        self.services: dict[str, QObject] = {}
        self._quitting = False

    # Build ---------------------------------------------------------------------------------
    def build(self) -> None:
        from . import icons
        from .controller import DeskController
        from .layer import QML_DIR, LayerManager
        from .scene import ItemsModel
        from .style import ThemeBridge
        from .wallpaper import WallImageProvider, WallpaperService

        prefs = self.state.preferences
        screens = QGuiApplication.screens()
        ItemsModel.DPR = max([float(s.devicePixelRatio() or 1.0) for s in screens] or [1.0])

        self.theme = ThemeBridge(self)
        self.theme.set_preferences(prefs)
        self._chrome_dark = None
        self.theme.changed.connect(self._theme_chrome_changed)
        self.wallpaper = WallpaperService(self)
        if self.demo and not os.environ.get("DESKISLE_DEMO_WALLPAPER"):
            demo_wall = ASSETS / "demo" / "wallpaper.jpg"
            if demo_wall.is_file():
                self.wallpaper._demo = str(demo_wall)  # noqa: SLF001 - demo backdrop
        self.wallpaper.configure(prefs.wallpaper_mode, prefs.wallpaper_image, max_fps=prefs.live_fps)

        self.engine = QQmlEngine(self)
        self.engine.addImportPath(str(QML_DIR))
        self.engine.addImageProvider("icon", icons.provider())
        self.engine.addImageProvider("wall", WallImageProvider(self.wallpaper))
        self.engine.warnings.connect(self._qml_warnings)

        self.desk = DeskController(self.store, self.state, demo=self.demo, theme=self.theme,
                                   wallpaper=self.wallpaper, parent=self)
        self.desk.app = self
        self.desk.services = self.services
        self._build_services()
        self._build_custom()
        registered: set[str] = set()
        for service in {id(s): s for s in self.services.values()}.values():
            # "media" aliases "player": register each provider once (re-adding an id deletes the old one).
            providers = getattr(service, "image_providers", None)
            if providers is not None:
                for name, provider in providers().items():
                    if name not in registered:
                        registered.add(name)
                        self.engine.addImageProvider(name, provider)
        # Before any QML exists: avoids a GIL / pixmap-reader deadlock (see icons.py).
        icons.prime_image_providers(self.engine, ["icon", "wall", *sorted(registered)])

        ctx = self.engine.rootContext()
        ctx.setContextProperty("Desk", self.desk)
        ctx.setContextProperty("Theme", self.theme)
        ctx.setContextProperty("App", self)
        for name, service in self.services.items():
            ctx.setContextProperty(name[:1].upper() + name[1:], service)

        self.layers = LayerManager(self.engine, self.desk, self.demo, self)
        self.desk.layers = self.layers
        self._build_webhost()

        self.wallpaper.updated.connect(self._wall_updated)
        self.wallpaper.accentChanged.connect(self._accent_changed)
        self.desk.settingsRequested.connect(self.open_settings)
        self.desk.quitRequested.connect(self.quit)
        self.desk.trayMenuRequested.connect(lambda: self.show_menu("tray", QPoint(-1, -1)))
        self.desk.prefsChanged.connect(self._prefs_changed)
        # Bar panels, confirmations and notices: own windows, created on first use.
        self.desk.panelChanged.connect(lambda: self.desk.panel and self._popup("panel"))
        self.desk.confirmChanged.connect(lambda: self.desk.pending_confirm().get("id") and self._popup("confirm"))
        self.desk.notices.countChanged.connect(lambda: len(self.desk.notices) and self._popup("notice"))
        self.desk.scenesChanged.connect(lambda: QTimer.singleShot(0, self._layers_synced))

    def _build_services(self) -> None:
        """Widget back-ends (each optional: a failure only disables its widget)."""
        factories = (
            ("clock", "deskisle.services.clock", "ClockService"),
            ("weather", "deskisle.services.weather", "WeatherService"),
            ("player", "deskisle.services.nowplaying", "NowPlayingService"),
            ("search", "deskisle.services.everything", "SearchService"),
            ("todo", "deskisle.services.todo", "TodoService"),
        )
        import importlib

        for name, module_name, class_name in factories:
            try:
                module = importlib.import_module(module_name)
                service = getattr(module, class_name)(self.desk, demo=self.demo, parent=self)
            except Exception:
                log.exception("service %s unavailable", name)
                from ..services.base import NullService

                service = NullService(name, parent=self)
            self.services[name] = service
        # Old menu code looks services up by the 1.x names.
        self.services.setdefault("media", self.services.get("player"))

    def _build_custom(self) -> None:
        try:
            from ..custom import CustomFolder

            self.custom = CustomFolder(self.desk, self.theme, self.root, parent=self)
            self.desk.custom = self.custom
        except Exception:
            log.exception("custom folder unavailable")
            self.custom = None

    def _build_webhost(self) -> None:
        try:
            from .webhost import WebHost

            self.webhost = WebHost(self.desk, self.layers, demo=self.demo, parent=self)
            self.layers.webhost = self.webhost
        except Exception:
            log.exception("web host unavailable")
            self.webhost = None
        self.engine.rootContext().setContextProperty("WebHost", self.webhost)
        self.engine.rootContext().setContextProperty("Custom", self.custom)

    # Start ------------------------------------------------------------------------------------
    def start(self) -> None:
        from .system import DesktopClickHook, Guardian, Hotkeys, NativeEvents, Tray

        desk = self.desk
        if self.demo:
            screen = QGuiApplication.primaryScreen()
            size = screen.availableGeometry().size() if screen is not None else None
            width = int(os.environ.get("DESKISLE_DEMO_W", "0") or 0) or (min(1600, size.width() - 80) if size else 1600)
            height = int(os.environ.get("DESKISLE_DEMO_H", "0") or 0) or (min(900, size.height() - 80) if size else 900)
            desk.set_demo_size(width, height)
        desk.start()
        if self.custom is not None:
            self.custom.start()
        desk.apply_preferences()

        self.native_events = NativeEvents(self)
        self.qapp.installNativeEventFilter(self.native_events)
        self.hotkeys = Hotkeys(self)
        self.hotkeys.triggered.connect(lambda action: desk.run_action(action, {}))
        self._apply_hotkeys()

        self.guardian = Guardian(self, self)
        self.guardian.pausedChanged.connect(self._paused)
        self.guardian.foregroundChanged.connect(self._foreground_changed)
        self.guardian.start()
        self.click_hook = DesktopClickHook(self)
        self.click_hook.doubleClicked.connect(self._desktop_double_clicked)
        self._sync_click_hook()

        self.tray = Tray(app_icon(), self)
        self.tray.menuRequested.connect(lambda pos: self.show_menu("tray", pos))
        self.tray.toggleRequested.connect(desk.toggleHidden)
        self.tray.settingsRequested.connect(lambda: self.open_settings(""))
        self.tray.show()
        todo = self.services.get("todo")
        if todo is not None and hasattr(todo, "reminder"):
            todo.reminder.connect(lambda title, text: self.tray.message(title, text, 8000))

        self._start_agent()
        self._start_updater()
        if IS_WINDOWS and not self.demo:
            self._register_session_events()
            if self.state.preferences.watchdog:
                crash_watchdog.spawn(self.root)
        if not self.demo:
            crash_watchdog.write_marker(self.root)
        self.qapp.aboutToQuit.connect(self.shutdown)
        self.qapp.commitDataRequest.connect(lambda _m: crash_watchdog.clear_marker(self.root))
        QTimer.singleShot(900, self._welcome)
        # 2.0.1 memory: give the start-up peak back once things settled, and again whenever
        # everything is hidden (清屏).
        self._last_trim = 0.0
        desk.hiddenChanged.connect(lambda: desk.hidden and self.schedule_trim(3000))
        self.schedule_trim(20_000)

    def _welcome(self) -> None:
        desk = self.desk
        for note in self.notes:
            desk.show_notice("桌屿 2.0", note, "info", [], 9000)
        if self.recovered:
            desk.show_notice("已自动恢复", "桌屿上次意外退出，看门狗已重新启动它。布局没有丢失。", "warning",
                             [{"id": "open-log", "text": "查看日志"}], 12000)
        if not self.state.preferences.onboarding_done and not self.demo:
            desk.show_notice("欢迎使用桌屿 2.0",
                             "右键桌面新建收纳岛或小组件；拖动标题栏移动，拖边缘调整大小；"
                             "双击桌面空白处可一键隐藏 / 显示。", "info",
                             [{"id": "onboarding-done", "text": "知道了"},
                              {"id": "open-settings", "text": "打开设置"}], 0)
        if self.hotkeys.failed:
            desk.show_notice("部分快捷键不可用", "被其他程序占用：" + "、".join(self.hotkeys.failed), "warning", [], 8000)

    # Agent / updater --------------------------------------------------------------------------
    def _start_agent(self) -> None:
        if not self.state.preferences.agent_enabled:
            return
        try:
            from ..agent.server import AgentServer

            self.agent = AgentServer(self, parent=self)
            if not self.agent.listen():
                log.warning("agent server could not listen: %s", self.agent.error)
        except Exception:
            log.exception("agent server unavailable")
            self.agent = None

    def set_agent_enabled(self, on: bool) -> None:
        if on and self.agent is None:
            self._start_agent()
        elif not on and self.agent is not None:
            self.agent.close()
            self.agent = None
        self.infoChanged.emit()

    def _start_updater(self) -> None:
        try:
            from ..updater import UpdateManager

            self.updater = UpdateManager(self.root, self)
            self.desk.updater = self.updater
            self.updater.check_finished.connect(self._update_checked)
            self.updater.check_failed.connect(self._update_failed)
            self.updater.download_finished.connect(self._update_downloaded)
            self.updater.download_failed.connect(self._update_download_failed)
            self.updater.check_started.connect(self.infoChanged.emit)
            self.updater.download_progress.connect(self._update_progress)
            if self.state.preferences.auto_check_updates and not self.demo:
                QTimer.singleShot(45_000, self.updater.maybe_auto_check)
            self._update_timer = QTimer(self)
            self._update_timer.setInterval(6 * 3600 * 1000)
            self._update_timer.timeout.connect(
                lambda: self.state.preferences.auto_check_updates and self.updater.maybe_auto_check())
            self._update_timer.start()
        except Exception:
            log.exception("updater unavailable")
            self.updater = None
        self.pending_release = None

    def _update_checked(self, release, newer: bool, manual: bool) -> None:
        self.pending_release = release if newer else None
        self.infoChanged.emit()
        if newer and (manual or self.updater.should_notify(release)):
            self.updater.mark_notified(release)
            self.desk.show_notice("发现新版本 {0}".format(release.version), release.title or "桌屿有更新可用。", "info",
                                  [{"id": "update-open", "text": "查看"}], 0)
        elif manual:
            self.desk.show_notice("已是最新版本", "当前版本 {0}".format(__version__), "info", [], 4000)

    def _update_failed(self, message: str, manual: bool) -> None:
        self.infoChanged.emit()
        if manual:
            self.desk.show_notice("检查更新失败", message, "error", [], 8000)

    def _update_progress(self, received, total) -> None:
        percent = int(100 * int(received) / int(total)) if total and int(total) > 0 else -1
        if percent != self._download_percent:
            self._download_percent = percent
            self.infoChanged.emit()

    def _update_download_failed(self, message: str) -> None:
        self._download_percent = -1
        self.infoChanged.emit()
        self.desk.show_notice("下载失败", message, "error", [], 8000)

    def _update_downloaded(self, path: str) -> None:
        from ..updater import launch_installer

        try:
            # Extra safety net promised in the settings: a snapshot right before installing.
            self.desk.save_snapshot("更新前自动备份")
        except Exception:  # noqa: BLE001 - a failed snapshot must not block the update
            log.exception("could not save the pre-update snapshot")
        self.desk.show_notice("更新已下载", "安装程序将启动，桌屿会先退出。", "info", [], 4000)
        if launch_installer(path):
            QTimer.singleShot(800, self.quit)

    # Notices actions (from QML) -----------------------------------------------------------------
    @Slot(str)
    def noticeAction(self, action: str) -> None:  # noqa: N802
        if action == "onboarding-done":
            self.state.preferences.onboarding_done = True
            self.desk.queue_save()
        elif action == "open-settings":
            self.state.preferences.onboarding_done = True
            self.open_settings("")
        elif action == "open-log":
            self.desk.openItem(str(self.root / "deskisle.log"))
        elif action == "update-open":
            self.open_settings("about")

    # Native messages ------------------------------------------------------------------------------
    def on_hotkey(self, hid: int) -> None:
        self.hotkeys.handle(hid)

    def on_copydata(self, hwnd: int, wparam: int, lparam: int) -> bool:
        searches = [self.services.get("search")]
        commands = getattr(self.agent, "commands", None) if self.agent is not None else None
        searches.append(getattr(commands, "_search", None))
        for search in searches:
            handler = getattr(search, "handle_copydata", None)
            if handler is not None and handler(hwnd, wparam, lparam):
                return True
        return False

    def on_setting_change(self, wparam: int, lparam: int) -> None:
        from .system import SPI_SETDESKWALLPAPER, setting_name

        name = setting_name(lparam)
        if wparam == SPI_SETDESKWALLPAPER or name in ("Desktop", "Control Panel\\Desktop"):
            self._later("wallpaper", 400, self.wallpaper.refresh)
        if name == "ImmersiveColorSet":
            self._later("theme", 300, lambda: self.theme.reevaluate(True))

    def on_display_change(self) -> None:
        self._later("display", 500, self.wallpaper.refresh)

    def on_session(self, event: int) -> None:
        from .system import WTS_SESSION_LOCK, WTS_SESSION_UNLOCK

        if event == WTS_SESSION_LOCK:
            self._paused(True, "locked")
        elif event == WTS_SESSION_UNLOCK:
            self._paused(False, "locked")
            self.wallpaper.refresh()

    def on_power(self, event: int) -> None:
        from .system import PBT_APMRESUMEAUTOMATIC, PBT_APMSUSPEND

        if event == PBT_APMSUSPEND:
            self._paused(True, "suspend")
        elif event == PBT_APMRESUMEAUTOMATIC:
            self._paused(False, "suspend")
            weather = self.services.get("weather")
            if weather is not None and hasattr(weather, "refresh"):
                # The network needs a moment after resume; only when a weather island is shown.
                QTimer.singleShot(8000, lambda: weather.refresh(force=getattr(weather, "in_use", bool)()))

    def on_explorer_restarted(self) -> None:
        log.info("Explorer restarted - re-applying desktop integration")
        QTimer.singleShot(1500, self._reapply_desktop)

    def _reapply_desktop(self) -> None:
        if self.layers is None:
            return
        self.layers.apply_preferences(self.state.preferences)
        for window in self.layers.windows.values():
            try:
                hwnd = int(window.winId())
                native_win.set_window_no_activate(hwnd, True)
                native_win.set_window_z(hwnd, "bottom")
            except RuntimeError:
                pass
        self.wallpaper.refresh()

    def _register_session_events(self) -> None:
        try:
            import ctypes

            window = next(iter(self.layers.windows.values()), None)
            if window is not None:
                ctypes.windll.wtsapi32.WTSRegisterSessionNotification(int(window.winId()), 0)
        except Exception:
            log.exception("session notifications")

    # Pausing ------------------------------------------------------------------------------------
    _pause_reasons: set = set()

    def _paused(self, paused: bool, reason: str = "covered") -> None:
        reasons = set(self._pause_reasons)
        if paused:
            reasons.add(reason)
        else:
            reasons.discard(reason)
        changed = bool(reasons) != bool(self._pause_reasons)
        self._pause_reasons = reasons
        active = bool(reasons)
        if changed:
            self.pausedChanged.emit()
        self.wallpaper.set_paused(active)
        for service in self.services.values():
            setter = getattr(service, "set_paused", None)
            if setter is not None:
                setter(active)
        if self.webhost is not None:
            self.webhost.set_paused(active)

    def _foreground_changed(self) -> None:
        # A click into another application closes our menus / bar panels.
        if self.desk is None or self.demo:
            return
        fg = native_win.foreground_window()
        mine = set(self.layers.hwnds()) if self.layers is not None else set()
        for window in (self.settings_window, self.menu_window, *self.popups.values()):
            try:
                if window is not None:
                    mine.add(int(window.winId()))
            except RuntimeError:
                pass
        if fg and fg not in mine and not native_win.foreground_is_desktop():
            self.desk.closePanel()
            self.close_menu()
            self.desk.dismissMenus()

    def _desktop_double_clicked(self) -> None:
        hwnd, cls, parent_cls = native_win.window_from_cursor_class()
        if cls != "SysListView32" or parent_cls != "SHELLDLL_DefView":
            return
        QTimer.singleShot(140, lambda: native_win.desktop_selected_count() == 0 and self.desk.toggleHidden())

    def _sync_click_hook(self) -> None:
        prefs = self.state.preferences
        want = IS_WINDOWS and not self.demo and prefs.wake_double_click and not prefs.hide_native_icons
        if want:
            self.click_hook.start()
        else:
            self.click_hook.stop()

    def _apply_hotkeys(self) -> None:
        if self.demo:
            return
        self.hotkeys.enable(bool(self.state.preferences.hotkeys_enabled))

    def _prefs_changed(self) -> None:
        self._sync_click_hook()
        self._apply_hotkeys()
        self.set_agent_enabled(bool(self.state.preferences.agent_enabled))
        if self.custom is not None:
            self.custom.set_folder(self.state.preferences.custom_folder)

    # Wallpaper ------------------------------------------------------------------------------------
    def _wall_updated(self, key: str) -> None:
        scene = self.desk.scenes.get(key)
        if scene is not None:
            scene.set_wall_source(self.wallpaper.source_url(key))
        if self.desk is not None and key == self.desk.primary_spec().key:
            self.wallChanged.emit()

    def _accent_changed(self) -> None:
        self.theme.set_wallpaper_accent(self.wallpaper.accent(), self.wallpaper.luminance())

    @Slot(result=str)
    def primaryWallSource(self) -> str:  # noqa: N802
        if self.desk is None:
            return ""
        return self.wallpaper.source_url(self.desk.primary_spec().key)

    @Slot(result=str)
    def liveStatus(self) -> str:  # noqa: N802
        return self.wallpaper.live_status

    @Slot(result=bool)
    def liveSupported(self) -> bool:  # noqa: N802
        return bool(self.wallpaper.live_supported)

    # Windows ---------------------------------------------------------------------------------------
    @Slot(str)
    def open_settings(self, page: str = "") -> None:
        if self.settings_window is None:
            try:
                component = self.layers.component("Settings.qml")
                window = component.createWithInitialProperties({"page": page or "appearance"})
                if window is None:
                    raise RuntimeError("\n".join(e.toString() for e in component.errors()))
            except Exception:
                log.exception("settings window")
                return
            window.setIcon(app_icon())
            # QQuickWindow.closing carries a QQuickCloseEvent that PySide cannot convert, so
            # watch the visibility instead: a closed window is hidden first.
            window.visibleChanged.connect(lambda visible, w=window: self._settings_visible(w, visible))
            window.activeChanged.connect(self.settingsActiveChanged.emit)
            self.settings_window = window
            self.settingsWindowChanged.emit()
            self._style_settings_chrome()
        elif page:
            self.settings_window.setProperty("page", page)
        window = self.settings_window
        window.show()
        window.raise_()
        window.requestActivate()
        if IS_WINDOWS:
            try:
                native_win.force_foreground(int(window.winId()))
            except Exception:
                pass

    def _theme_chrome_changed(self) -> None:
        if self.settings_window is not None and self._chrome_dark != bool(self.theme.dark):
            self._style_settings_chrome()

    def _style_settings_chrome(self) -> None:
        """Title bar of the settings window follows the theme (Windows)."""
        window = self.settings_window
        if window is None or not IS_WINDOWS:
            return
        try:
            dark = bool(self.theme.dark)
            self._chrome_dark = dark
            native_win.set_title_bar(int(window.winId()), dark, "#16191F" if dark else "#F1F3F6",
                                     "#E8EAED" if dark else "#1F2328")
        except (RuntimeError, AttributeError):
            pass

    def _settings_visible(self, window, visible: bool) -> None:
        if visible or window is not self.settings_window or self._quitting:
            return
        self.settings_window = None
        self.settingsWindowChanged.emit()
        self.settingsActiveChanged.emit()
        QTimer.singleShot(0, window.deleteLater)
        self.schedule_trim(3000)

    # Memory (2.0.1) -----------------------------------------------------------------------------
    def schedule_trim(self, delay_ms: int) -> None:
        """Hand idle memory back to Windows a little after something heavy finished."""
        if self._quitting or not self.state.preferences.idle_trim:
            return
        timer = getattr(self, "_trim_timer", None)
        if timer is None:
            timer = self._trim_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._trim_memory)
        timer.start(max(0, int(delay_ms)))

    def _trim_memory(self, force: bool = False) -> None:
        if self._quitting or (not force and not self.state.preferences.idle_trim):
            return
        if not force:
            # Never in the middle of a gesture or while the settings window is in use.
            busy = QGuiApplication.mouseButtons() != Qt.MouseButton.NoButton
            window = self.settings_window
            if busy or (window is not None and window.isVisible()):
                self.schedule_trim(5000)
                return
            since = time.monotonic() - getattr(self, "_last_trim", 0.0)
            if since < 60:
                self.schedule_trim(int((60 - since) * 1000) + 500)
                return
        self._last_trim = time.monotonic()
        import gc
        gc.collect()
        for step in ("trimComponentCache", "collectGarbage"):
            try:
                getattr(self.engine, step)()
            except Exception:
                pass
        if self.desk.hidden and self.layers is not None:
            for window in list(self.layers.windows.values()):
                try:
                    window.releaseResources()  # scene-graph caches; rebuilt on the next frame
                except (RuntimeError, AttributeError):
                    pass
        if IS_WINDOWS:
            native_win.trim_working_set()

    @Slot()
    def trimMemoryNow(self) -> None:  # noqa: N802
        self._trim_memory(force=True)

    @Slot(result=str)
    def memoryText(self) -> str:  # noqa: N802
        usage = native_win.memory_usage()
        if not usage.get("self"):
            return "仅在 Windows 上统计"
        def mb(value: int) -> str:
            return f"{value / 1048576:.0f} MB"
        text = f"桌屿 {mb(usage['self'])}"
        if usage.get("web_count"):
            text += f" · 网页组件 {mb(usage['web'])}（{usage['web_count']} 个进程）"
        return text

    # Popup windows (PopupWindow.qml) ------------------------------------------------------------
    def _popup(self, role: str):
        window = self.popups.get(role)
        if window is None and self.layers is not None and not self._quitting:
            try:
                component = self.layers.component("PopupWindow.qml")
                window = component.createWithInitialProperties({"role": role})
                if window is None:
                    raise RuntimeError("\n".join(e.toString() for e in component.errors()))
            except Exception:
                log.exception("popup window %s", role)
                return None
            self.popups[role] = window
        return window

    def _layers_synced(self) -> None:
        self._layers_revision += 1
        self.layersChanged.emit()

    layersRevision = Property(int, lambda self: self._layers_revision, notify=layersChanged)

    @Slot(str, result=QObject)
    def layerWindow(self, key: str):  # noqa: N802
        """QML: the layer window of a monitor (primary for "" or an unknown key)."""
        if self.layers is None or self.desk is None:
            return None
        windows = self.layers.windows
        return windows.get(key) or windows.get(self.desk.primary_spec().key) or next(iter(windows.values()), None)

    @Slot(QObject, int, int, int, int)
    def placeWindow(self, window, x: int, y: int, width: int, height: int) -> None:  # noqa: N802
        """QML: move + resize a window in one step (no intermediate frame)."""
        try:
            if window is not None:
                window.setGeometry(QRect(int(x), int(y), max(1, int(width)), max(1, int(height))))
        except (RuntimeError, AttributeError):
            pass

    @Slot(QObject)
    def activateWindow(self, window) -> None:  # noqa: N802
        try:
            window.raise_()
            window.requestActivate()
            if IS_WINDOWS and not self.demo:
                native_win.force_foreground(int(window.winId()))
        except (RuntimeError, AttributeError, OSError):
            pass

    def _settings_active(self) -> bool:
        window = self.settings_window
        try:
            return bool(window is not None and window.isVisible() and window.isActive())
        except RuntimeError:
            return False

    settingsActive = Property(bool, _settings_active, notify=settingsActiveChanged)

    @Slot(str, str, "QVariant")
    def popupMenu(self, context: str, target: str = "", extra=None) -> None:  # noqa: N802
        """QML: open a context menu at the mouse cursor."""
        self.show_menu(context, QPoint(-1, -1), target, dict(extra) if isinstance(extra, dict) else {})

    @Slot(str, str, "QVariant", int, int)
    def popupMenuAt(self, context: str, target: str, extra, x: int, y: int) -> None:  # noqa: N802
        """QML: open a menu under a button (global logical coordinates)."""
        self.show_menu(context, QPoint(int(x), int(y)), target, dict(extra) if isinstance(extra, dict) else {})

    def show_menu(self, context: str, pos: QPoint, target: str = "", extra: dict | None = None) -> None:
        """Glass menu in its own top-level window (every context menu and the tray)."""
        from . import menus

        if pos.x() < 0:
            from PySide6.QtGui import QCursor

            pos = QCursor.pos()
        extra = dict(extra or {})
        entries = menus.build(self.desk, context, target, extra)
        if not entries:
            return
        if self.menu_window is None:
            try:
                component = self.layers.component("MenuWindow.qml")
                self.menu_window = component.createWithInitialProperties({})
            except Exception:
                log.exception("menu window")
                return
        window = self.menu_window
        window.setProperty("entries", entries)
        window.setProperty("context", context)
        window.setProperty("target", target)
        window.setProperty("extra", extra)
        window.setProperty("anchorX", pos.x())
        window.setProperty("anchorY", pos.y())
        screen = QGuiApplication.screenAt(pos) or QGuiApplication.primaryScreen()
        if screen is not None:
            g = screen.availableGeometry()
            window.setProperty("screenRect", QRect(g))
        window.metaObject().invokeMethod(window, "popup")
        if IS_WINDOWS:
            try:
                native_win.force_foreground(int(window.winId()))
            except Exception:
                pass

    def close_menu(self) -> None:
        if self.menu_window is not None:
            try:
                self.menu_window.close()
            except RuntimeError:
                self.menu_window = None

    # Misc ----------------------------------------------------------------------------------------------
    _timers: dict = {}

    def _later(self, name: str, delay: int, slot) -> None:
        timers = self.__dict__.setdefault("_named_timers", {})
        timer = timers.get(name)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: timers[name].callback())
            timers[name] = timer
        timer.callback = slot
        timer.start(delay)

    def _qml_warnings(self, warnings) -> None:
        for warning in warnings:
            log.warning("QML: %s", warning.toString())

    @Slot()
    def quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True
        self.qapp.quit()

    def shutdown(self) -> None:
        if getattr(self, "_shut", False):
            return
        self._shut = True
        log.info("shutting down")
        for name in ("guardian",):
            obj = getattr(self, name, None)
            if obj is not None:
                obj.stop()
        if getattr(self, "click_hook", None) is not None:
            self.click_hook.stop()
        if getattr(self, "hotkeys", None) is not None:
            self.hotkeys.disable()
        if self.agent is not None:
            self.agent.close()
        # Top-level QML windows go first: Qt flushes deleteLater() right after aboutToQuit,
        # while the Theme/Desk/App objects their bindings read still exist.
        popups, self.popups = list(self.popups.values()), {}
        for name in ("settings_window", "menu_window"):
            popups.append(getattr(self, name, None))
            setattr(self, name, None)
        for window in popups:
            if window is not None:
                try:
                    window.hide()
                    window.deleteLater()
                except RuntimeError:
                    pass
        for service in self.services.values():
            stop = getattr(service, "shutdown", None)
            if stop is not None:
                try:
                    stop()
                except Exception:
                    log.exception("service shutdown")
        if self.webhost is not None:
            self.webhost.shutdown()
        if self.desk is not None:
            self.desk.shutdown()
        self.wallpaper.shutdown()
        if self.layers is not None:
            self.layers.shutdown()
        # Destroy those windows now - also when shutdown() runs outside the event loop
        # (self-test, probe) - while the objects their bindings read still exist.
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        if getattr(self, "tray", None) is not None:
            self.tray.hide()
        native_win.restore_native_desktop_icons()
        if not self.demo:
            crash_watchdog.clear_marker(self.root)

    # QML helpers -------------------------------------------------------------------------------------
    version = property(lambda self: __version__)
    # Nobody sees the desktop (fullscreen app, locked screen...): pause videos / animations.
    paused = Property(bool, lambda self: bool(self._pause_reasons), notify=pausedChanged)

    @Slot(result="QVariantList")
    def hotkeyTable(self):  # noqa: N802
        from .system import hotkey_table

        return hotkey_table()

    @Slot(result=str)
    def dataDir(self) -> str:  # noqa: N802
        return str(self.root)

    @Slot(result="QVariantMap")
    def agentInfo(self):  # noqa: N802
        from ..agent.client import launch_info

        agent = self.agent
        info = {
            "enabled": bool(self.state.preferences.agent_enabled),
            "listening": bool(agent is not None and agent.is_listening()),
            "pipe": agent.full_name() if agent is not None else "",
            "custom": str(self.custom.folder) if self.custom is not None else "",
            "guide": str(Path(__file__).resolve().parents[1] / "agent" / "GUIDE.md"),
        }
        info.update(launch_info(demo=self.demo))
        return info

    @Slot(result="QVariantMap")
    def updateInfo(self):  # noqa: N802
        release = self.pending_release
        updater = getattr(self, "updater", None)
        return {
            "current": __version__,
            "available": bool(release is not None),
            "version": getattr(release, "version", "") if release is not None else "",
            "title": getattr(release, "title", "") if release is not None else "",
            "notes": getattr(release, "notes", "") if release is not None else "",
            "lastCheck": updater.last_check_text() if updater is not None else "",
            "checking": bool(updater is not None and updater.is_checking),
            "downloading": bool(updater is not None and updater.is_downloading),
            "progress": int(self._download_percent),
            "canInstall": bool(release is not None and getattr(release, "has_installer", False)),
        }

    @Slot(str, result=str)
    def docPath(self, name: str) -> str:  # noqa: N802
        """Bundled documents for the settings page ("" when missing)."""
        files = {"notices": "THIRD-PARTY-NOTICES.md", "readme": "README.md", "changelog": "CHANGELOG.md",
                 "license": "LICENSE", "guide": "deskisle/agent/GUIDE.md", "manual": "docs/使用说明.md"}
        relative = files.get(str(name))
        if not relative:
            return ""
        path = Path(__file__).resolve().parents[2] / relative
        return str(path) if path.is_file() else ""

    @Slot(result=str)
    def homepage(self) -> str:
        from ..updater import REPO

        return "https://github.com/{0}".format(REPO)

    @Slot()
    def checkUpdates(self) -> None:  # noqa: N802
        if getattr(self, "updater", None) is not None:
            self.updater.check(manual=True)
            self.infoChanged.emit()

    @Slot()
    def installUpdate(self) -> None:  # noqa: N802
        if getattr(self, "updater", None) is not None and self.pending_release is not None:
            self.updater.download(self.pending_release)


# ---------------------------------------------------------------------------------------------
def install_exception_guard(root: Path, app_ref: list) -> None:
    def handle(exc_type, exc_value, exc_traceback) -> None:
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        log.error("unhandled exception\n%s", details)
        try:
            with open(root / "crash.log", "a", encoding="utf-8") as stream:
                stream.write("\n[{0}] {1}".format(time.strftime("%Y-%m-%d %H:%M:%S"), details))
        except OSError:
            pass
        app = app_ref[0] if app_ref else None
        desk = getattr(app, "desk", None) if app is not None else None
        if desk is not None:
            try:
                desk.show_notice("桌屿出现了一个错误", "{0}: {1}".format(exc_type.__name__, exc_value), "error",
                                 [{"id": "open-log", "text": "查看日志"}], 10000)
            except Exception:
                pass

    sys.excepthook = handle


def init_web_engine() -> bool:
    """Non-Windows (development / demo): web islands use Qt WebEngine (must run before QApplication)."""
    if IS_WINDOWS or os.environ.get("DESKISLE_WEBENGINE", "1") == "0":
        return False
    try:
        from PySide6.QtWebEngineQuick import QtWebEngineQuick

        QtWebEngineQuick.initialize()
    except Exception:  # noqa: BLE001 - optional module
        return False
    os.environ["DESKISLE_WEBENGINE_READY"] = "1"
    return True


def run(args) -> int:
    prepare_environment()
    root = data_root(args)
    setup_logging(root, verbose=bool(getattr(args, "verbose", False)))
    init_web_engine()
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setApplicationDisplayName("桌屿")
    qapp.setWindowIcon(app_icon())
    log.info("DeskIsle %s starting (demo=%s, data=%s)", __version__, bool(args.demo), root)

    store = StateStore(root)
    lock = None
    notes: list[str] = []
    if not args.demo:
        root.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(root / "instance.lock"))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            from ..agent.client import send

            try:
                send({"cmd": "app.activate", "args": {}}, timeout=2.0)
            except Exception:
                native_win.message_box("桌屿已经在运行，请使用系统托盘中的桌屿图标。", "桌屿 DeskIsle")
            return 0
    if args.demo:
        from ..demo import demo_state

        state = demo_state(root)
    elif args.reset:
        try:
            store.save_snapshot(store.load(), "重置前自动备份")
        except Exception:
            pass
        desktop = Path.home() / "Desktop"
        try:
            items = list(desktop.iterdir()) if desktop.is_dir() else []
        except OSError:
            items = []
        state = store.create_default_state(items)
        store.save(state)
    else:
        state, note = load_state(store)
        if note:
            notes.append(note)
        try:
            store.save(state)
            store.prune_media(state)
        except Exception:
            log.exception("initial save")

    recovered = bool(getattr(args, "recovered", False))
    holder: list = []
    install_exception_guard(root, holder)
    app = DeskIsleApp(qapp, store, state, demo=bool(args.demo), root=root, notes=notes, recovered=recovered)
    holder.append(app)
    try:
        app.build()
        app.start()
    except Exception as exc:
        log.exception("start-up failed")
        native_win.restore_native_desktop_icons()
        native_win.message_box("桌屿无法启动：\n{0}\n\n日志：{1}".format(exc, root / "deskisle.log"), "桌屿 DeskIsle")
        return 1
    code = qapp.exec()
    app.shutdown()
    if lock is not None:
        lock.unlock()
    return int(code)


__all__ = ["DeskIsleApp", "app_icon", "data_root", "load_state", "prepare_environment", "run", "setup_logging"]

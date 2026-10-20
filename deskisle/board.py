from __future__ import annotations

import copy
import os
from pathlib import Path

from PySide6.QtCore import (
    QEvent,
    QFileSystemWatcher,
    QPoint,
    QRect,
    QRectF,
    QSize,
    QTimer,
    QUrl,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QKeyEvent, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QFrame,
    QFileDialog,
    QPushButton,
    QSystemTrayIcon,
    QToolButton,
    QWidget,
)

from . import __version__, html_view, media, motion, theme
from . import grid_layout
from .backdrop import GlassCache, GlassStyle, paint_demo_background, paint_glass_base, paint_glass_rim, provider
from .dialogs import NewIslandDialog, RulesDialog, SettingsDialog, UpdateDialog, WelcomeDialog
from .island import IslandWidget, default_material, set_default_material
from .items import ItemListWidget, open_path
from .models import AppState, IslandState, ItemRef, PageState, TabState
from .native_win import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    SPI_SETDESKWALLPAPER,
    VK_H,
    VK_LEFT,
    VK_RIGHT,
    VK_SPACE,
    WM_SETTINGCHANGE,
    DesktopHost,
    is_window_covered,
    set_window_overlay,
    set_window_no_activate,
)
from .rules import RuleEngine
from .theme import APP_NAME, ISLAND_COLORS
from .updater import RELEASES_PAGE, STARTUP_DELAY_MS, UpdateManager, can_self_install, launch_installer
from .widgets import GlassMenu


HOTKEY_FOCUS = 0x5151
HOTKEY_HIDE = 0x5152
HOTKEY_PREV = 0x5153
HOTKEY_NEXT = 0x5154
WM_HOTKEY = 0x0312
ICON_DIR = Path(__file__).resolve().parent / "assets" / "icons"
# Islands that only show web content (no file references).
WEB_ISLAND_KINDS = ("html", "web")
OCCLUSION_INTERVAL_MS = 1500


def _is_file_island(island) -> bool:
    return getattr(island, "kind", "files") not in WEB_ISLAND_KINDS


def _tabler_icon(name: str) -> QIcon:
    """Load and tint the vendored MIT-licensed Tabler outline icon."""
    source = QIcon(str(ICON_DIR / f"{name}.svg"))
    pixmap = source.pixmap(20, 20)
    if pixmap.isNull():
        return source
    painter = QPainter(pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(pixmap.rect(), QColor("#EAF0F8"))
    painter.end()
    return QIcon(pixmap)


def _desktop_directories() -> list[Path]:
    candidates = [Path.home() / "Desktop"]
    public = os.environ.get("PUBLIC")
    if public:
        candidates.append(Path(public) / "Desktop")
    one_drive = os.environ.get("OneDrive")
    if one_drive:
        candidates.extend([Path(one_drive) / "Desktop", Path(one_drive) / "桌面"])
    result: list[Path] = []
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved.is_dir() and resolved not in result:
            result.append(resolved)
    return result


class BoardSurface(QWidget):
    def __init__(self, demo_mode: bool, parent=None) -> None:
        super().__init__(parent)
        self.demo_mode = demo_mode
        self.focus_mode = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        if self.demo_mode:
            # Same abstract wallpaper the glass material samples in demo mode.
            paint_demo_background(painter, QRectF(self.rect()))
        if self.focus_mode:
            painter.fillRect(self.rect(), QColor(4, 8, 14, 128))

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.demo_mode:
            provider().schedule_rebuild(120)


class FloatingToolbar(QFrame):
    """Glass capsule with page switching and quick actions."""

    move_started = Signal()
    move_requested = Signal(QPoint)
    move_finished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("floatingToolbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self._glass_cache = GlassCache()
        self.setStyleSheet(
            "QWidget#floatingToolbar { background: transparent; border: 0; }"
            "QToolButton { background: transparent; border: 0; border-radius: 12px; color: #EAF0F8;"
            " padding: 5px 9px; font-size: 10pt; }"
            "QToolButton:hover { background: rgba(255,255,255,30); }"
            "QToolButton:pressed { background: rgba(255,255,255,46); }"
            "QPushButton { background: transparent; border: 0; border-radius: 12px; color: #F4F7FB;"
            " font-weight: 600; padding: 5px 12px; }"
            "QPushButton:hover { background: rgba(255,255,255,24); }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(2)
        self.drag_handle = ToolbarDragHandle(self)
        self.previous_button = self._tool("chevron-left", "上一个场景页")
        self.page_button = QPushButton("工作台")
        self.page_button.setToolTip("场景页菜单")
        self.next_button = self._tool("chevron-right", "下一个场景页")
        self.add_button = self._tool("square-rounded-plus", "新建收纳岛")
        self.hide_button = self._tool("eye", "清屏")
        self.focus_button = self._tool("focus-2", "聚焦层")
        self.settings_button = self._tool("settings", "设置")
        layout.addWidget(self.drag_handle)
        for widget in (
            self.previous_button,
            self.page_button,
            self.next_button,
            self.add_button,
            self.hide_button,
            self.focus_button,
            self.settings_button,
        ):
            layout.addWidget(widget)
        self.adjustSize()
        self.drag_handle.move_started.connect(self.move_started)
        self.drag_handle.move_requested.connect(self.move_requested)
        self.drag_handle.move_finished.connect(self.move_finished)
        provider().changed.connect(self.update)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        rect = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        style = GlassStyle(material=default_material(), tint=QColor("#18202C"), density=0.9,
                           radius=rect.height() / 2)
        paint_glass_base(painter, rect, style, provider().canvas_point(self), self._glass_cache)
        paint_glass_rim(painter, rect, style)
        painter.end()

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        if default_material() != "clear":
            self.update()

    def _tool(self, icon_name: str, tooltip: str) -> QToolButton:
        button = QToolButton()
        button.setIcon(_tabler_icon(icon_name))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    def set_hidden_state(self, hidden: bool) -> None:
        self.hide_button.setIcon(_tabler_icon("eye-off" if hidden else "eye"))


class ToolbarDragHandle(QToolButton):
    move_started = Signal()
    move_requested = Signal(QPoint)
    move_finished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setIcon(_tabler_icon("grip-horizontal"))
        self.setIconSize(QSize(18, 18))
        self.setToolTip("拖动工具条")
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._origin: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self.grabMouse()
            self.move_started.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move_requested.emit(event.globalPosition().toPoint() - self._origin)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._origin is not None:
            self._origin = None
            if self.mouseGrabber() is self:
                self.releaseMouse()
            self.move_finished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class DesktopWindow(QMainWindow):
    def __init__(self, state: AppState, store, demo_mode: bool = False) -> None:
        super().__init__()
        self.state = state
        self.store = store
        self.demo_mode = demo_mode
        self.native_host = DesktopHost()
        self.islands: dict[str, IslandWidget] = {}
        self.groups_hidden = False
        self.focus_mode = False
        self.desktop_attached = False
        self._desktop_warning_shown = False
        self._closing_for_real = False
        self._desktop_dirs = [] if demo_mode else _desktop_directories()
        self._rule_engine = RuleEngine(self.state.rules)
        self.updater: UpdateManager | None = None
        self._update_dialog: UpdateDialog | None = None
        self._pending_release = None
        self._grid_drag_order: list[str] | None = None

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(self._make_icon())
        if demo_mode:
            self.setMinimumSize(980, 650)
            self.resize(1280, 760)
        else:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint
                | Qt.WindowType.Tool
                | Qt.WindowType.WindowStaysOnBottomHint
            )
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            self.setAutoFillBackground(False)
            screens = QApplication.screens()
            geometry = screens[0].geometry()
            for screen in screens[1:]:
                geometry = geometry.united(screen.geometry())
            x, y, width, height = geometry.getRect()
            # Leave a small border uncovered so wallpaper tools do not classify
            # this interactive desktop surface as a fullscreen application.
            inset = 2
            self.setGeometry(
                x + inset,
                y + inset,
                max(100, width - inset * 2),
                max(100, height - inset * 2),
            )

        self.surface = BoardSurface(demo_mode, self)
        self.setCentralWidget(self.surface)
        # Uploaded island media / fonts are copied into the data folder so a
        # moved or deleted original never breaks the layout.
        media.set_import_handler(getattr(store, "import_media", None))
        html_view.configure_storage(getattr(store, "root", None))
        html_view.hub().download_finished.connect(self._web_download_finished)

        self.loose_view = ItemListWidget("__loose__", "__loose__", self.surface)
        self.loose_view.configure("__loose__", "__loose__", 56, False)
        self.loose_view.files_dropped.connect(self._drop_to_loose)
        self.loose_view.remove_requested.connect(self._remove_loose_reference)
        self.loose_view.unavailable_remove_requested.connect(self._remove_unavailable_references)
        self.loose_view.shell_operation_finished.connect(self.import_new_desktop_items)
        self.loose_view.reorder_requested.connect(self._reorder_loose)
        self.loose_view.activated_path.connect(lambda path: open_path(path))
        self.loose_view.blank_double_clicked.connect(self.toggle_hidden)
        self.loose_view.blank_context_requested.connect(self.show_board_menu)
        self.loose_view.lower()

        self.toolbar = FloatingToolbar(self.surface)
        self.toolbar.previous_button.clicked.connect(lambda: self.switch_page(-1))
        self.toolbar.next_button.clicked.connect(lambda: self.switch_page(1))
        self.toolbar.page_button.clicked.connect(self._show_page_menu)
        self.toolbar.add_button.clicked.connect(self.add_island)
        self.toolbar.hide_button.clicked.connect(lambda _checked=False: self.toggle_hidden())
        self.toolbar.focus_button.clicked.connect(lambda _checked=False: self.toggle_focus())
        self.toolbar.settings_button.clicked.connect(self.show_settings)
        self.toolbar.move_requested.connect(self._move_toolbar_by)
        self.toolbar.move_finished.connect(self._finish_toolbar_move)
        self._toolbar_drag_origin: QPoint | None = None

        # Search must be its own small, ownerless HWND. Making the monitor-sized
        # desktop surface active for keyboard input causes wallpaper tools to
        # classify it as the foreground fullscreen application.
        self.search = QLineEdit(None)
        self.search.setWindowFlags(
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
        )
        self.search.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.search.setAutoFillBackground(False)
        self.search.setPlaceholderText("搜索当前场景中已显示的文件…")
        self.search.setClearButtonEnabled(True)
        self.search.setFixedWidth(420)
        self.search.setStyleSheet(
            "QLineEdit { background: rgba(19,26,37,242); border: 1px solid #55D6BE; border-radius: 17px;"
            " padding: 9px 16px; color: white; font-size: 11pt; }"
        )
        self.search.textChanged.connect(self._filter_items)
        self.search.installEventFilter(self)
        self.search.hide()

        self.save_timer = QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(350)
        self.save_timer.timeout.connect(self.save_state)

        self.desktop_watcher = QFileSystemWatcher(self)
        existing = [str(path) for path in self._desktop_dirs if path.is_dir()]
        if existing:
            self.desktop_watcher.addPaths(existing)
        self.desktop_refresh_timer = QTimer(self)
        self.desktop_refresh_timer.setSingleShot(True)
        self.desktop_refresh_timer.setInterval(450)
        self.desktop_refresh_timer.timeout.connect(self.import_new_desktop_items)
        self.desktop_watcher.directoryChanged.connect(lambda _path: self.desktop_refresh_timer.start())

        self.desktop_host_timer = QTimer(self)
        self.desktop_host_timer.setInterval(5000)
        self.desktop_host_timer.timeout.connect(self._ensure_desktop_host)

        self.screen_restore_timer = QTimer(self)
        self.screen_restore_timer.setSingleShot(True)
        self.screen_restore_timer.setInterval(500)
        self.screen_restore_timer.timeout.connect(self._restore_after_screen_change)
        # Pause background video / HTML / web rendering while an island is
        # completely covered by other windows (fullscreen apps, games…).
        self._occlusion_timer = QTimer(self)
        self._occlusion_timer.setInterval(OCCLUSION_INTERVAL_MS)
        self._occlusion_timer.timeout.connect(self._update_occlusion)
        if not demo_mode:
            for screen in QApplication.screens():
                self._watch_screen(screen)
            QApplication.instance().screenAdded.connect(self._screen_added)
            QApplication.instance().screenRemoved.connect(self._schedule_screen_restore)
        self._setup_tray()
        self._ensure_state()
        self._setup_edge_switching()
        self.apply_preferences(refresh=False)
        self.rebuild_page()
        self.import_new_desktop_items(initial=True)
        QTimer.singleShot(0, self._after_show)
        if not demo_mode:
            QTimer.singleShot(0, self.restore_positions)
            self._setup_updater()

    # Preferences ------------------------------------------------------------
    def apply_preferences(self, refresh: bool = True) -> None:
        """Push global appearance, motion and media preferences into every module."""
        prefs = self.state.preferences
        app = QApplication.instance()
        if app is not None:
            try:
                size = float(getattr(prefs, "font_size", 10.0) or 10.0)
            except (TypeError, ValueError):
                size = 10.0
            theme.apply_app_font(app, str(getattr(prefs, "font_family", "") or ""), size,
                                 str(getattr(prefs, "font_file", "") or ""))
        motion.set_reduce_motion(bool(getattr(prefs, "reduce_motion", False)))
        set_default_material(str(getattr(prefs, "island_material", "frosted") or "frosted"))
        media.set_frame_rate(int(getattr(prefs, "media_fps", 24) or 24))
        provider().configure(
            str(getattr(prefs, "backdrop_source", "wallpaper") or "wallpaper"),
            str(getattr(prefs, "backdrop_image", "") or ""),
            demo_surface=self.surface if self.demo_mode else None,
        )
        self._sync_occlusion_timer()
        if not refresh:
            return
        opacity = self._panel_opacity()
        self.toolbar.adjustSize()
        self.toolbar.update()
        self._position_overlays()
        for island in self.islands.values():
            island.opacity = opacity
            island._glass_cache.clear()
            island.refresh_items()
            island.update()
        self._refresh_loose()

    def _panel_opacity(self) -> float:
        try:
            value = float(self.state.preferences.panel_opacity)
        except (TypeError, ValueError):
            value = 0.88
        if value > 1.0:
            value /= 100.0
        return max(0.35, min(1.0, value))

    # Occlusion-aware pausing ---------------------------------------------------
    def _sync_occlusion_timer(self) -> None:
        enabled = not self.demo_mode and bool(getattr(self.state.preferences, "smart_pause", True))
        if enabled:
            if not self._occlusion_timer.isActive():
                self._occlusion_timer.start()
            return
        self._occlusion_timer.stop()
        for island in self.islands.values():
            island.set_suspended("covered", False)

    def _update_occlusion(self) -> None:
        for island in list(self.islands.values()):
            try:
                animated = island.web is not None or island.media.is_animated()
                if not animated:
                    continue
                covered = bool(island.isVisible() and island.desktop_window
                               and is_window_covered(int(island.winId())))
                island.set_suspended("covered", covered)
            except RuntimeError:
                continue

    # Updates ------------------------------------------------------------------
    def _ensure_updater(self) -> UpdateManager:
        if self.updater is None:
            self.updater = UpdateManager(getattr(self.store, "root", None), self, __version__)
            self.updater.check_finished.connect(self._update_check_finished)
        return self.updater

    def _setup_updater(self) -> None:
        self._ensure_updater()
        self.tray.messageClicked.connect(self._tray_message_clicked)
        QTimer.singleShot(STARTUP_DELAY_MS, self._auto_check_updates)
        # Long-running sessions: look again a few times a day (the manager
        # itself limits real requests to one per ~20 hours).
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(3 * 60 * 60 * 1000)
        self._update_timer.timeout.connect(self._auto_check_updates)
        self._update_timer.start()

    def _auto_check_updates(self) -> None:
        if self.updater is None or not bool(getattr(self.state.preferences, "auto_check_updates", True)):
            return
        self.updater.maybe_auto_check()

    def _update_check_finished(self, release, newer: bool, manual: bool) -> None:
        if manual or not newer or self.updater is None or self._update_dialog is not None:
            return
        if not self.updater.should_notify(release):
            return
        self.updater.mark_notified(release)
        self._pending_release = release
        self.tray.showMessage(
            APP_NAME,
            "桌屿 {0} 已发布，点击这里查看更新内容。".format(release.version),
            QSystemTrayIcon.MessageIcon.Information,
            8000,
        )

    def _tray_message_clicked(self) -> None:
        release, self._pending_release = self._pending_release, None
        if release is not None:
            self.show_update_dialog(release)

    def show_update_dialog(self, release=None, parent=None) -> None:
        if self._update_dialog is not None:
            self._update_dialog.raise_()
            return
        manager = self._ensure_updater()
        dialog = UpdateDialog(manager, parent, release=release)
        dialog.install_requested.connect(self._install_update)
        self._update_dialog = dialog
        try:
            dialog.exec()
        finally:
            self._update_dialog = None
            dialog.deleteLater()

    def _install_update(self, installer_path: str) -> None:
        if not can_self_install():
            QDesktopServices.openUrl(QUrl(RELEASES_PAGE))
            return
        # Layout, rules and preferences live in the data folder, which the
        # installer never touches; keep an extra snapshot just in case.
        self.save_timer.stop()
        self.save_state()
        try:
            self.store.save_snapshot(self.state, "更新前自动备份-v{0}".format(__version__))
        except (OSError, RuntimeError, ValueError):
            pass
        if not launch_installer(installer_path):
            QMessageBox.warning(None, "软件更新", "无法启动安装程序。请稍后重试，或在发布页面手动下载安装。")
            return
        if self._update_dialog is not None:
            self._update_dialog.accept()
        QTimer.singleShot(0, self.exit_application)

    def _web_download_finished(self, path: str) -> None:
        if self.tray.isVisible():
            self.tray.showMessage(APP_NAME, "网页下载完成：{0}".format(os.path.basename(path)),
                                  QSystemTrayIcon.MessageIcon.Information, 3000)

    def _ensure_state(self) -> None:
        if not self.state.pages:
            self.state.pages.append(PageState(title="工作台"))
        if not self.state.current_page_id or not any(p.id == self.state.current_page_id for p in self.state.pages):
            self.state.current_page_id = self.state.pages[0].id
        if not hasattr(self.state, "loose_items"):
            self.state.loose_items = []

    def current_page(self) -> PageState:
        for page in self.state.pages:
            if page.id == self.state.current_page_id:
                return page
        self.state.current_page_id = self.state.pages[0].id
        return self.state.pages[0]

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._position_overlays()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._position_overlays()
        # A resized desktop changes the grid; debounce so a drag-resize does
        # not re-flow on every intermediate size.
        if self.is_auto_layout():
            timer = getattr(self, "_grid_resize_timer", None)
            if timer is None:
                timer = QTimer(self)
                timer.setSingleShot(True)
                timer.setInterval(120)
                timer.timeout.connect(self.apply_grid_layout)
                self._grid_resize_timer = timer
            timer.start()

    def _position_overlays(self) -> None:
        if not hasattr(self, "loose_view"):
            return
        self.loose_view.setGeometry(8, 8, max(100, self.surface.width() - 16), max(100, self.surface.height() - 16))
        self.loose_view.lower()
        self.toolbar.adjustSize()
        prefs = self.state.preferences
        wanted_x = int(getattr(prefs, "toolbar_x", -1))
        wanted_y = int(getattr(prefs, "toolbar_y", 14))
        if wanted_x < 0:
            wanted_x = (self.surface.width() - self.toolbar.width()) // 2
        self.toolbar.move(self._clamp_toolbar_position(QPoint(wanted_x, wanted_y)))
        self.toolbar.raise_()
        self._position_search()
        if self.search.isVisible():
            self.search.raise_()

    def _clamp_toolbar_position(self, point: QPoint) -> QPoint:
        return self._fit_rect(QRect(point, self.toolbar.size())).topLeft()

    def _position_search(self) -> None:
        if not hasattr(self, "search") or not hasattr(self, "toolbar"):
            return
        x = self.toolbar.x() + (self.toolbar.width() - self.search.width()) // 2
        x = max(12, min(x, max(12, self.surface.width() - self.search.width() - 12)))
        y = self.toolbar.y() + self.toolbar.height() + 10
        y = max(12, min(y, max(12, self.surface.height() - self.search.height() - 12)))
        self.search.move(self.surface.mapToGlobal(QPoint(x, y)))

    def _move_toolbar_by(self, delta: QPoint) -> None:
        if self._toolbar_drag_origin is None:
            self._toolbar_drag_origin = self.toolbar.pos()
        self.toolbar.move(self._clamp_toolbar_position(self._toolbar_drag_origin + delta))
        self._position_search()

    def _commit_toolbar_position(self) -> None:
        self._toolbar_drag_origin = None
        self.state.preferences.toolbar_x = self.toolbar.x()
        self.state.preferences.toolbar_y = self.toolbar.y()
        self._position_search()
        self.queue_save()

    def _finish_toolbar_move(self) -> None:
        self._commit_toolbar_position()

    def _after_show(self) -> None:
        if not self.demo_mode:
            self._ensure_desktop_host()
            modifiers = MOD_CONTROL | MOD_ALT | MOD_NOREPEAT
            hotkeys_ok = [
                self.native_host.register_hotkey(int(self.winId()), HOTKEY_FOCUS, modifiers, VK_SPACE),
                self.native_host.register_hotkey(int(self.winId()), HOTKEY_HIDE, modifiers, VK_H),
                self.native_host.register_hotkey(int(self.winId()), HOTKEY_PREV, modifiers, VK_LEFT),
                self.native_host.register_hotkey(int(self.winId()), HOTKEY_NEXT, modifiers, VK_RIGHT),
            ]
            if not all(hotkeys_ok):
                self.tray.showMessage(
                    APP_NAME,
                    "部分全局快捷键与其他程序冲突；仍可使用顶部工具条和托盘菜单。",
                    QSystemTrayIcon.MessageIcon.Warning,
                    3500,
                )
            self.maybe_show_welcome()

    def maybe_show_welcome(self) -> None:
        """Offer the first-run guide once, after the desktop surface is ready."""
        if self.demo_mode or self.state.preferences.onboarding_done:
            return
        dialog = WelcomeDialog(None)
        dialog.exec()
        # Any answer (including closing) counts as seen so the guide never
        # blocks startup a second time.
        self.state.preferences.onboarding_done = True
        wants_startup = dialog.wants_startup()
        if wants_startup != bool(self.state.preferences.start_with_windows):
            self.state.preferences.start_with_windows = wants_startup
            if not self.native_host.set_startup(wants_startup):
                self.tray.showMessage(
                    APP_NAME,
                    "无法更新开机启动设置，请稍后在设置中重试。",
                    QSystemTrayIcon.MessageIcon.Warning,
                    4000,
                )
        self.queue_save()

    def _ensure_desktop_host(self) -> None:
        if self.demo_mode or self.focus_mode:
            return
        # Do not SetParent() a Qt layered top-level window into Explorer.
        # Converting it to WS_CHILD breaks Qt's press/move/release delivery on
        # several Windows/Explorer combinations.  A normal frameless Tool
        # window preserves native Qt mouse input and still stays below normal
        # application windows through WindowStaysOnBottomHint.
        self.desktop_attached = False
        # Keep ordinary desktop clicks from making this monitor-sized surface
        # the foreground application. Wallpaper players commonly pause/resume
        # based on foreground/fullscreen detection, which looks like frame
        # skipping or fast-forward when focus changes repeatedly.
        self.native_host.set_no_activate(int(self.winId()), True)
        self.native_host.show_native_icons(not bool(self.state.preferences.hide_native_icons))
        self._desktop_warning_shown = False

    def nativeEvent(self, event_type, message):  # noqa: N802
        if os.name == "nt":
            try:
                from ctypes import wintypes

                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    hotkey_id = int(msg.wParam)
                    if hotkey_id == HOTKEY_FOCUS:
                        self.toggle_focus()
                    elif hotkey_id == HOTKEY_HIDE:
                        self.toggle_hidden()
                    elif hotkey_id == HOTKEY_PREV:
                        self.switch_page(-1)
                    elif hotkey_id == HOTKEY_NEXT:
                        self.switch_page(1)
                    return True, 0
                if msg.message == WM_SETTINGCHANGE and int(msg.wParam or 0) == SPI_SETDESKWALLPAPER:
                    # Wallpaper changed: re-sample the glass backdrop.
                    provider().schedule_rebuild(400)
            except (ValueError, OSError):
                pass
        return super().nativeEvent(event_type, message)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.focus_mode:
            self.toggle_focus(False)
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event):  # noqa: N802
        if (
            hasattr(self, "search")
            and watched is self.search
            and event.type() == QEvent.Type.KeyPress
            and event.key() == Qt.Key.Key_Escape
        ):
            self.toggle_focus(False)
            return True
        return super().eventFilter(watched, event)

    def _grid_interaction_started(self) -> None:
        """Remember the board before a drag so the drop can be resolved."""

        if not self.is_auto_layout():
            return
        page = self.current_page()
        self._grid_drag_before = list(self._grid_placements(page))

    def _grid_interaction_finished(self, widget: IslandWidget) -> None:
        """Drop the dragged island onto the board and settle the page.

        The island lands on the quarter-screen slot under the pointer.  What the
        other islands do is chosen in settings: ``swap`` trades places with
        whichever island it overlapped, ``reorder`` lets the board refill around
        the new position.  Either way the page is compacted afterwards so a gap
        never survives a drag.
        """

        if not self.is_auto_layout():
            return
        page = self.current_page()
        before = getattr(self, "_grid_drag_before", None)
        self._grid_drag_before = None
        ids = [island.id for island in page.islands]
        if not before or widget.state.id not in ids:
            self.apply_grid_layout()
            return
        index = ids.index(widget.state.id)
        area = self.grid_area()
        metrics = grid_layout.cells_for(
            max(1, area.width()), max(1, area.height()),
            grid_layout.content_rows(before),
        )
        point = widget.board_position()
        local = (point.x() - area.x(), point.y() - area.y())
        origin = before[index]
        wanted = grid_layout.Placement(
            *grid_layout.slot_at(local, metrics, origin.cols, origin.rows),
            origin.cols, origin.rows,
        )

        mode = str(getattr(self.state.preferences, "grid_move_mode", "swap"))
        placements = list(before)
        if mode == "swap":
            # Find whoever already owns the cell the island was dropped on, and
            # trade places with it.  Falls back to the nearest free slot when
            # the drop landed in empty space.
            victim = next(
                (i for i, placement in enumerate(before)
                 if i != index and grid_layout.collides([wanted], placement)),
                None,
            )
            if victim is None:
                placements[index] = grid_layout.best_drop(before, index, local, metrics)
            else:
                placements[index] = wanted
                swapped = grid_layout.Placement(
                    origin.col, origin.row,
                    before[victim].cols, before[victim].rows,
                )
                if grid_layout.collides(
                    [p for i, p in enumerate(placements) if i != victim], swapped
                ):
                    swapped = grid_layout.first_free(
                        [p for i, p in enumerate(placements) if i != victim],
                        before[victim].cols, before[victim].rows,
                    )
                placements[victim] = swapped
        else:
            placements[index] = grid_layout.best_drop(before, index, local, metrics)
        settled = grid_layout.compact(placements, pinned={index})
        self._sync_placements_to_state(page, settled)
        self.apply_grid_layout()

    def cycle_island_level(self, island_id: str) -> None:
        """Advance one island to the next size level and re-flow the page."""

        page = self.current_page()
        for island in page.islands:
            if island.id == island_id:
                island.size_level = grid_layout.next_level(island.size_level)
                island.grid_col = -1
                island.grid_row = -1
                break
        else:
            return
        self.apply_grid_layout()

    def set_island_level(self, island_id: str, level: str) -> None:
        page = self.current_page()
        for island in page.islands:
            if island.id == island_id:
                island.size_level = grid_layout.normalise_level(level)
                island.grid_col = -1
                island.grid_row = -1
                break
        else:
            return
        self.apply_grid_layout()

    # Edge page switching ------------------------------------------------------
    def _setup_edge_switching(self) -> None:
        """Poll the cursor so hovering a screen edge flips the scene page."""

        self._edge_timer = QTimer(self)
        self._edge_timer.setInterval(90)
        self._edge_timer.timeout.connect(self._poll_edge_switch)
        self._edge_dwell = 0
        self._edge_side = 0
        self._edge_cooldown = 0
        self._update_edge_timer()

    def _update_edge_timer(self) -> None:
        timer = getattr(self, "_edge_timer", None)
        if timer is None:
            return
        enabled = bool(getattr(self.state.preferences, "edge_switch_enabled", True))
        wants = enabled and len(self.state.pages) > 1 and not self.demo_mode
        if wants and not timer.isActive():
            timer.start()
        elif not wants and timer.isActive():
            timer.stop()
        if not wants:
            self._edge_dwell = 0
            self._edge_side = 0

    def _poll_edge_switch(self) -> None:
        """Trigger a page flip after the cursor dwells on a screen edge."""

        from PySide6.QtGui import QCursor

        if self.demo_mode or len(self.state.pages) <= 1:
            return
        prefs = self.state.preferences
        width = max(8, int(getattr(prefs, "edge_switch_width", 28)))
        delay = max(120, int(getattr(prefs, "edge_switch_delay_ms", 420)))
        step = 90

        if self._edge_cooldown > 0:
            self._edge_cooldown = max(0, self._edge_cooldown - step)
            return

        pos = QCursor.pos()
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        side = 0
        if pos.x() <= area.left() + width:
            side = -1
        elif pos.x() >= area.right() - width:
            side = 1
        # Only the outer edge band counts; a cursor resting mid-screen is idle.
        if side == 0:
            self._edge_dwell = 0
            self._edge_side = 0
            return
        if side != self._edge_side:
            self._edge_side = side
            self._edge_dwell = 0
            return
        self._edge_dwell += step
        if self._edge_dwell >= delay:
            self._edge_dwell = 0
            # Avoid flip-flopping while the pointer stays parked on the edge.
            self._edge_cooldown = 700
            self.switch_page(side)

    def rebuild_page(self, reveal: bool = True) -> None:
        for widget in list(self.islands.values()):
            if widget.web is not None:
                widget.web.release()
            widget.media.clear()
            widget.hide()
            # Detach right away instead of waiting for deleteLater().  A stale
            # island stays parented to the surface until the event loop frees it,
            # so a snapshot taken in the meantime still saw the previous page.
            widget.setParent(None)
            widget.deleteLater()
        self.islands.clear()
        page = self.current_page()
        self.toolbar.page_button.setText(page.title)
        auto = self.is_auto_layout()
        if auto:
            # Resolve once, then hand each widget its slot; the placements are
            # also written back to the states so the board survives a restart.
            placements = self._grid_placements(page)
            self._sync_placements_to_state(page, placements)
            rects = self._placements_to_rects(placements)
        else:
            rects = []
        for index, island_state in enumerate(page.islands):
            widget = IslandWidget(island_state, self._panel_opacity(), self.surface,
                                  desktop_window=not self.demo_mode)
            widget.set_snap_callback(self.snap_position)
            widget.state_changed.connect(self.queue_save)
            widget.delete_requested.connect(self.delete_island)
            widget.references_dropped.connect(self._move_references)
            widget.references_removed.connect(self._remove_references)
            widget.item_list.unavailable_remove_requested.connect(self._remove_unavailable_references)
            widget.item_list.shell_operation_finished.connect(self.import_new_desktop_items)
            widget.window_level_changed.connect(lambda w=widget: self._apply_window_level(w))
            widget.level_requested.connect(self.set_island_level)
            widget.level_cycle_requested.connect(self.cycle_island_level)
            widget.geometry_interaction_started.connect(self._grid_interaction_started)
            widget.geometry_interaction_finished.connect(
                lambda w=widget: self._grid_interaction_finished(w)
            )
            self.islands[island_state.id] = widget
            if widget.desktop_window:
                self._set_level_flags(widget)
            if auto and index < len(rects):
                rect = rects[index]
                widget.set_grid_size(rect.width(), rect.height())
                widget.move_on_board(rect.topLeft())
            else:
                widget.set_grid_unlocked()
            # Showing a native island window paints it immediately, at its final
            # position.  During a page switch that painted the *destination* for
            # one frame before the slide began, which is the stray "finished"
            # frame seen just before the animation.  Build hidden and let the
            # caller reveal after the overlay owns the screen.
            if reveal:
                widget.show()
                if widget.desktop_window:
                    self._apply_native_level(widget)
                else:
                    widget.raise_()
        self._refresh_loose()
        if self.focus_mode:
            self.loose_view.show()
        else:
            self.loose_view.setVisible(not self.groups_hidden)
        if reveal:
            for widget in self.islands.values():
                keep = bool(getattr(widget.state, "exclude_from_hide", False))
                widget.setVisible(self.focus_mode or (not self.groups_hidden) or keep)
        if self.search.text():
            self._filter_items(self.search.text())
        self.toolbar.raise_()
        if self.search.isVisible():
            self.search.raise_()

    # Window level (“窗口置顶”) ------------------------------------------------------
    @staticmethod
    def _is_pinned(widget: IslandWidget) -> bool:
        return bool(getattr(widget.state, "pin_on_top", False))

    def _set_level_flags(self, widget: IslandWidget) -> None:
        pinned = self._is_pinned(widget)
        widget.setWindowFlag(Qt.WindowType.WindowStaysOnBottomHint, not pinned)
        widget.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, pinned)

    def _apply_native_level(self, widget: IslandWidget) -> None:
        hwnd = int(widget.winId())
        # Web / HTML islands need keyboard input (typing, logging in); file
        # islands stay non-activating so the desktop never steals focus.
        set_window_no_activate(hwnd, not widget.is_web_content)
        set_window_overlay(hwnd, self.focus_mode or self._is_pinned(widget))

    def _apply_window_level(self, widget: IslandWidget) -> None:
        if not widget.desktop_window:
            widget.raise_()
            return
        visible = widget.isVisible()
        # Changing window flags re-creates the native style (and hides the
        # window); restore visibility and our extended styles afterwards.
        self._set_level_flags(widget)
        if visible:
            widget.show()
        self._apply_native_level(widget)

    def _refresh_loose(self) -> None:
        records = [(item.path, getattr(item, "title", "")) for item in getattr(self.state, "loose_items", [])]
        self.loose_view.set_paths(records)

    def queue_save(self) -> None:
        self.save_timer.start()

    def save_state(self) -> None:
        self._capture_geometries()
        self.store.save(self.state)

    def _capture_geometries(self) -> None:
        for widget in self.islands.values():
            widget.state.x = widget.board_position().x()
            widget.state.y = widget.board_position().y()
            widget.state.width = widget.width()
            if not widget.state.collapsed and not widget._collapse_animating:
                widget.state.height = widget.height()

    def snap_position(self, widget: IslandWidget, point: QPoint, final: bool = True) -> QPoint:
        if not final or not self.state.preferences.snap_to_grid:
            return self._clamp_point(widget, point)
        grid = max(2, int(self.state.preferences.grid_size))
        x = round(point.x() / grid) * grid
        y = round(point.y() / grid) * grid
        threshold = max(8, grid + 2)
        edges_x = [8, self.surface.width() - widget.width() - 8]
        edges_y = [8, self.surface.height() - widget.height() - 8]
        for other in self.islands.values():
            if other is widget or not other.isVisible():
                continue
            pos = other.board_position()
            edges_x.extend([pos.x(), pos.x() + other.width() + 8, pos.x() - widget.width() - 8])
            edges_y.extend([pos.y(), pos.y() + other.height() + 8, pos.y() - widget.height() - 8])
        for edge in edges_x:
            if abs(x - edge) <= threshold:
                x = edge
                break
        for edge in edges_y:
            if abs(y - edge) <= threshold:
                y = edge
                break
        return self._clamp_point(widget, QPoint(x, y))

    def _clamp_point(self, widget: IslandWidget, point: QPoint) -> QPoint:
        return self._fit_rect(QRect(point, widget.size())).topLeft()

    def add_island(self, portal: bool = False, kind: str | None = None) -> None:
        data = NewIslandDialog.get_data(None, force_portal=portal, kind=kind)
        if not data:
            return
        island_kind = str(data.get("island_kind") or "files")
        defaults = {"html": "HTML 动画", "web": "固定网页"}
        title = str(data.get("title") or data.get("name") or defaults.get(island_kind, "新收纳岛")).strip()
        folder = data.get("folder") or data.get("folder_path") or data.get("path")
        page = self.current_page()
        index = len(page.islands)
        width, height = (420, 320) if island_kind in WEB_ISLAND_KINDS else (340, 270)
        x = 48 + (index % 4) * 365
        y = 90 + (index // 4) * 295
        tab = TabState(title="全部", portal_path=str(folder) if folder and island_kind == "files" else None)
        state = IslandState(
            title=title,
            x=min(x, max(20, self.surface.width() - width - 20)),
            y=min(y, max(70, self.surface.height() - height - 20)),
            width=width,
            height=height,
            color=ISLAND_COLORS[index % len(ISLAND_COLORS)],
            tabs=[tab],
            active_tab_id=tab.id,
            kind=island_kind,
            html_path=str(data.get("html_path") or ""),
            html_allow_network=bool(data.get("html_allow_network")),
            web_url=str(data.get("web_url") or ""),
        )
        page.islands.append(state)
        self.rebuild_page()
        self.queue_save()

    def delete_island(self, island_id: str) -> None:
        page = self.current_page()
        target = next((item for item in page.islands if item.id == island_id), None)
        if target is None:
            return
        virtual_items: list[ItemRef] = []
        for tab in target.tabs:
            if not getattr(tab, "portal_path", None):
                virtual_items.extend(tab.items)
        kind = getattr(target, "kind", "files")
        if kind == "html":
            message = "删除“{0}”？\nHTML 文件本身不会被删除。".format(target.title)
        elif kind == "web":
            message = "删除“{0}”？\n只移除桌面上的网页窗口；网站登录状态仍保留在桌屿的网页配置中。".format(target.title)
        else:
            detail = "其中 {0} 个引用会回到桌面散放区；原文件不会删除。".format(len(virtual_items))
            message = "删除“{0}”？\n{1}\n文件视窗对应的真实文件夹也不会删除。".format(target.title, detail)
        answer = QMessageBox.question(
            None,
            "删除收纳岛",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.state.loose_items.extend(self._dedupe_refs(virtual_items, self.state.loose_items))
        page.islands = [item for item in page.islands if item.id != island_id]
        self.rebuild_page()
        self.queue_save()

    def _find_tab(self, island_id: str, tab_id: str):
        if island_id == "__loose__":
            return None
        for page in self.state.pages:
            for island in page.islands:
                if island.id == island_id:
                    for tab in island.tabs:
                        if tab.id == tab_id:
                            return tab
        return None

    def _move_references(self, paths: list[str], source_island: str, source_tab: str, target_island: str, target_tab: str) -> None:
        target = self._find_tab(target_island, target_tab)
        if target is None or getattr(target, "portal_path", None):
            return
        existing = {os.path.normcase(item.path) for item in target.items}
        for path in paths:
            if os.path.normcase(path) not in existing:
                target.items.append(ItemRef(path=path))
                existing.add(os.path.normcase(path))
        if source_island == "__loose__":
            path_set = {os.path.normcase(path) for path in paths}
            self.state.loose_items = [item for item in self.state.loose_items if os.path.normcase(item.path) not in path_set]
        elif source_island and (source_island != target_island or source_tab != target_tab):
            source = self._find_tab(source_island, source_tab)
            if source is not None and not getattr(source, "portal_path", None):
                path_set = {os.path.normcase(path) for path in paths}
                source.items = [item for item in source.items if os.path.normcase(item.path) not in path_set]
        self._refresh_all_items()
        self.queue_save()

    def _remove_references(self, paths: list[str], island_id: str, tab_id: str) -> None:
        source = self._find_tab(island_id, tab_id)
        if source is None:
            return
        path_set = {os.path.normcase(path) for path in paths}
        refs = [item for item in source.items if os.path.normcase(item.path) in path_set]
        source.items = [item for item in source.items if os.path.normcase(item.path) not in path_set]
        self.state.loose_items.extend(self._dedupe_refs(refs, self.state.loose_items))
        self._refresh_all_items()
        self.queue_save()

    def _drop_to_loose(self, paths: list[str], source_island: str, source_tab: str) -> None:
        existing = {os.path.normcase(item.path) for item in self.state.loose_items}
        for path in paths:
            if os.path.normcase(path) not in existing:
                self.state.loose_items.append(ItemRef(path=path))
                existing.add(os.path.normcase(path))
        if source_island and source_island != "__loose__":
            source = self._find_tab(source_island, source_tab)
            if source is not None and not getattr(source, "portal_path", None):
                path_set = {os.path.normcase(path) for path in paths}
                source.items = [item for item in source.items if os.path.normcase(item.path) not in path_set]
        self._refresh_all_items()
        self.queue_save()

    def _remove_loose_reference(self, paths: list[str], _island_id: str, _tab_id: str) -> None:
        QMessageBox.information(None, "散放区", "散放项目代表原生桌面图标。请把它拖入收纳岛，或在资源管理器中管理原文件。")

    def _reorder_loose(
        self,
        paths: list[str],
        _island_id: str,
        _tab_id: str,
        target_index: int,
    ) -> None:
        selected_keys = {os.path.normcase(path) for path in paths}
        current = list(self.state.loose_items)
        moving = [
            item for item in current
            if os.path.normcase(item.path) in selected_keys
        ]
        if not moving:
            return
        selected_before_target = sum(
            1
            for index, item in enumerate(current)
            if index < target_index and os.path.normcase(item.path) in selected_keys
        )
        remaining = [
            item for item in current
            if os.path.normcase(item.path) not in selected_keys
        ]
        insert_at = max(
            0,
            min(len(remaining), target_index - selected_before_target),
        )
        self.state.loose_items = (
            remaining[:insert_at] + moving + remaining[insert_at:]
        )
        self._refresh_loose()
        self.queue_save()

    def _dedupe_refs(self, candidates: list[ItemRef], existing_items: list[ItemRef]) -> list[ItemRef]:
        existing = {os.path.normcase(item.path) for item in existing_items}
        result = []
        for item in candidates:
            key = os.path.normcase(item.path)
            if key not in existing:
                result.append(item)
                existing.add(key)
        return result

    def _refresh_all_items(self) -> None:
        self._refresh_loose()
        for island in self.islands.values():
            island.refresh_items()

    def import_new_desktop_items(self, initial: bool = False) -> None:
        disk_paths: list[str] = []
        scanned = {}
        for folder in self._desktop_dirs:
            try:
                children = list(folder.iterdir())
                scanned[os.path.normcase(os.path.abspath(folder))] = {
                    os.path.normcase(os.path.abspath(path)) for path in children
                }
                disk_paths.extend(str(path) for path in children if not path.name.startswith("."))
            except OSError:
                continue
        # Only remove references proven absent from a successfully enumerated
        # desktop directory. Offline drives and unreadable folders retain data.
        def deleted(ref):
            path = os.path.normcase(os.path.abspath(ref.path))
            parent = os.path.dirname(path)
            return parent in scanned and path not in scanned[parent]

        removed = self._discard_references(deleted)
        assigned: set[str] = {os.path.normcase(item.path) for item in getattr(self.state, "loose_items", [])}
        for page in self.state.pages:
            for island in page.islands:
                for tab in island.tabs:
                    if not getattr(tab, "portal_path", None):
                        assigned.update(os.path.normcase(item.path) for item in tab.items)
        new_paths = [path for path in disk_paths if os.path.normcase(path) not in assigned]
        if not new_paths:
            if removed:
                self._refresh_all_items()
                self.queue_save()
            return
        all_islands = [island for page in self.state.pages for island in page.islands]
        for path in new_paths:
            target_id = None
            if self.state.preferences.auto_organize:
                target_id = self._choose_target(path)
            target_island = next((item for item in all_islands if item.id == target_id and _is_file_island(item)),
                                 None)
            if target_island is not None:
                tab = next((tab for tab in target_island.tabs if not getattr(tab, "portal_path", None)), None)
                if tab is not None:
                    tab.items.append(ItemRef(path=path))
                    continue
            self.state.loose_items.append(ItemRef(path=path))
        self._refresh_all_items()
        self.queue_save()
        if not initial and new_paths and self.tray.isVisible():
            self.tray.showMessage(APP_NAME, "已发现 {0} 个新桌面项目。".format(len(new_paths)), QSystemTrayIcon.MessageIcon.Information, 2200)

    def _choose_target(self, path: str):
        self._rule_engine.rules = self.state.rules
        try:
            return self._rule_engine.choose_target(path)
        except TypeError:
            result = self._rule_engine.choose_target(Path(path), self.state.rules)
            return getattr(result, "target_island_id", result)

    def _discard_references(self, predicate) -> bool:
        lists = [self.state.loose_items]
        lists.extend(tab.items for page in self.state.pages for island in page.islands
                     for tab in island.tabs if not tab.portal_path)
        changed = False
        for refs in lists:
            kept = [ref for ref in refs if not predicate(ref)]
            changed |= len(kept) != len(refs)
            refs[:] = kept
        return changed

    def _remove_unavailable_references(self, paths: list[str]) -> None:
        keys = {os.path.normcase(os.path.abspath(path)) for path in paths if not os.path.lexists(path)}
        if self._discard_references(lambda ref: os.path.normcase(os.path.abspath(ref.path)) in keys):
            self._refresh_all_items()
            self.queue_save()

    def apply_rules(self) -> None:
        locations: list[tuple[ItemRef, object | None]] = [
            (item, None) for item in list(self.state.loose_items)
        ]
        for page in self.state.pages:
            for island in page.islands:
                for tab in island.tabs:
                    if not getattr(tab, "portal_path", None):
                        locations.extend((item, tab) for item in list(tab.items))

        seen: set[str] = set()
        for ref, source_tab in locations:
            key = os.path.normcase(ref.path)
            if key in seen:
                continue
            seen.add(key)
            target_id = self._choose_target(ref.path)
            target_tab = None
            for page in self.state.pages:
                for island in page.islands:
                    if island.id == target_id and _is_file_island(island):
                        target_tab = next((tab for tab in island.tabs if not getattr(tab, "portal_path", None)), None)
                        break
                if target_tab is not None:
                    break
            if target_tab is None or target_tab is source_tab:
                continue

            if source_tab is None:
                self.state.loose_items = [
                    item for item in self.state.loose_items
                    if os.path.normcase(item.path) != key
                ]
            else:
                source_tab.items = [
                    item for item in source_tab.items
                    if os.path.normcase(item.path) != key
                ]
            if all(os.path.normcase(item.path) != key for item in target_tab.items):
                target_tab.items.append(ref)
        self._refresh_all_items()
        self.queue_save()

    def toggle_hidden(self, force: bool | None = None) -> None:
        self.groups_hidden = (not self.groups_hidden) if force is None else bool(force)
        for widget in self.islands.values():
            keep = bool(getattr(widget.state, "exclude_from_hide", False))
            visible = (not self.groups_hidden) or keep
            widget.setVisible(visible)
            if visible:
                widget.raise_()
        self.loose_view.setVisible(not self.groups_hidden)
        self.toolbar.set_hidden_state(self.groups_hidden)
        self.toolbar.raise_()
        self.surface.update()

    def toggle_focus(self, force: bool | None = None) -> None:
        wanted = (not self.focus_mode) if force is None else bool(force)
        if wanted == self.focus_mode:
            return
        self.focus_mode = wanted
        self.surface.focus_mode = wanted
        if not self.demo_mode:
            set_window_overlay(int(self.winId()), wanted)
            set_window_overlay(int(self.search.winId()), wanted)
            for widget in self.islands.values():
                set_window_overlay(int(widget.winId()), wanted or self._is_pinned(widget))
        if wanted:
            for widget in self.islands.values():
                widget.show()
                widget.raise_()
            self.loose_view.show()
            self.search.show()
            self.toolbar.raise_()
            self.search.raise_()
            self._position_search()
            # Do not explicitly make DeskIsle the foreground application.
            # Wallpaper players use that transition as a pause signal.
            self.search.setFocus(Qt.FocusReason.OtherFocusReason)
        else:
            self.search.clearFocus()
            self.search.clear()
            self.search.hide()
            if self.groups_hidden:
                self.toggle_hidden(True)
            if not self.demo_mode and not self.desktop_attached:
                self.lower()
        self.surface.update()

    def _filter_items(self, text: str) -> None:
        needle = text.strip().casefold()
        views = [self.loose_view] + [widget.item_list for widget in self.islands.values()]
        for view in views:
            for index in range(view.count()):
                item = view.item(index)
                path = str(item.data(Qt.ItemDataRole.UserRole))
                item.setHidden(bool(needle) and needle not in item.text().casefold() and needle not in path.casefold())

    def switch_page(self, delta: int) -> None:
        if len(self.state.pages) <= 1:
            return
        self._capture_geometries()
        index = next((i for i, page in enumerate(self.state.pages) if page.id == self.state.current_page_id), 0)
        index = (index + delta) % len(self.state.pages)
        self.state.current_page_id = self.state.pages[index].id
        # Plain hard cut.  A cross-fade or slide would have to be drawn on an
        # overlay window, and every island is its own native desktop window, so
        # the compositor cannot keep them in step: the result is stray frames and
        # flicker rather than motion.  Switching instantly is honest and clean.
        self.rebuild_page()
        self._update_edge_timer()
        self.queue_save()

    def _snapshot_board(self, include_hidden: bool = False) -> QPixmap | None:
        """Composite the board onto a transparent pixmap.

        ``QWidget.render`` and ``QWidget.grab`` both flood the whole canvas with
        an opaque background, which is exactly wrong for DeskIsle: the board
        paints nothing behind the islands so the wallpaper shows through.  Doing
        it that way turned every page switch into a black sheet covering the
        screen.  Rendering each child itself onto a cleared pixmap keeps the gaps
        transparent.

        Only the *current* page's islands are drawn.  ``rebuild_page`` schedules
        the old widgets for deletion, but they stay parented to the surface until
        the event loop gets around to it; rendering every child therefore mixed
        the previous page into the new page's snapshot.

        With *include_hidden* the widgets are rendered even while hidden, which
        lets a page be captured without it ever appearing on screen first.
        """

        if self.demo_mode or motion.reduce_motion():
            return None
        size = self.surface.size()
        if size.isEmpty():
            return None
        ratio = max(1.0, float(self.surface.devicePixelRatioF()))
        pixmap = QPixmap(size * ratio)
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        current = list(self.islands.values())
        try:
            for widget in current:
                if not include_hidden and not widget.isVisible():
                    continue
                if widget.width() <= 0 or widget.height() <= 0:
                    continue
                # Islands are separate top-level windows on the desktop, so their
                # geometry() is in *global* screen coordinates.  Drawing at that
                # point shifted the whole page by the board's own screen origin,
                # which made the content appear to jump right before sliding.
                offset = widget.geometry().topLeft()
                if getattr(widget, "desktop_window", False) and hasattr(widget, "board_position"):
                    offset = widget.board_position()
                widget.render(painter, offset)
            # Islands only.  The floating toolbar and search box are live widgets
            # that stay on screen throughout the animation, so baking them into
            # both snapshots produced two or three overlapping toolbars during a
            # page switch.
        finally:
            painter.end()
        return pixmap if not pixmap.isNull() else None

    def add_page(self) -> None:
        name, ok = QInputDialog.getText(None, "新建场景页", "场景页名称", text="新场景")
        if ok and name.strip():
            page = PageState(title=name.strip())
            self.state.pages.append(page)
            self.state.current_page_id = page.id
            self.rebuild_page()
            self._update_edge_timer()
            self.queue_save()

    def rename_page(self) -> None:
        page = self.current_page()
        name, ok = QInputDialog.getText(None, "重命名场景页", "名称", text=page.title)
        if ok and name.strip():
            page.title = name.strip()
            self.toolbar.page_button.setText(page.title)
            self.queue_save()

    def _show_page_menu(self) -> None:
        menu = GlassMenu(passive=True)
        for page in self.state.pages:
            action = menu.addAction(page.title)
            action.setCheckable(True)
            action.setChecked(page.id == self.state.current_page_id)
            action.setData(page.id)
        menu.addSeparator()
        add_action = menu.addAction("新建场景页…")
        rename_action = menu.addAction("重命名当前页…")
        delete_action = menu.addAction("删除当前页…")
        delete_action.setEnabled(len(self.state.pages) > 1)
        chosen = menu.exec(self.toolbar.page_button.mapToGlobal(QPoint(0, self.toolbar.page_button.height())))
        if chosen == add_action:
            self.add_page()
        elif chosen == rename_action:
            self.rename_page()
        elif chosen == delete_action:
            self.delete_page()
        elif chosen is not None and chosen.data():
            self.state.current_page_id = str(chosen.data())
            self.rebuild_page()
            self.queue_save()

    def delete_page(self) -> None:
        if len(self.state.pages) <= 1:
            return
        page = self.current_page()
        answer = QMessageBox.question(
            None,
            "删除场景页",
            "删除场景页“{0}”？其中普通引用将回到散放区，原文件不会删除。".format(page.title),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        for island in page.islands:
            for tab in island.tabs:
                if not getattr(tab, "portal_path", None):
                    self.state.loose_items.extend(self._dedupe_refs(tab.items, self.state.loose_items))
        index = self.state.pages.index(page)
        self.state.pages.remove(page)
        self.state.current_page_id = self.state.pages[min(index, len(self.state.pages) - 1)].id
        self.rebuild_page()
        self._update_edge_timer()
        self.queue_save()

    def _screen_areas(self):
        if self.demo_mode:
            return [self.surface.rect().adjusted(8, 8, -8, -8)]
        return [QRect(self.surface.mapFromGlobal(screen.availableGeometry().topLeft()),
                      screen.availableGeometry().size()).adjusted(8, 8, -8, -8)
                for screen in QApplication.screens()]

    def _fit_rect(self, rect):
        areas = self._screen_areas()
        def score(area):
            overlap = area.intersected(rect)
            distance = (area.center() - rect.center()).manhattanLength()
            return (overlap.width() * overlap.height() if not overlap.isEmpty() else 0, -distance)
        area = max(areas, key=score)
        width, height = min(rect.width(), area.width()), min(rect.height(), area.height())
        return QRect(max(area.left(), min(rect.x(), area.right() - width + 1)),
                     max(area.top(), min(rect.y(), area.bottom() - height + 1)), width, height)

    def restore_positions(self):
        self._capture_geometries()
        if self.is_auto_layout():
            # The grid owns island geometry; only the toolbar needs loading.
            rect = self._fit_rect(self.toolbar.geometry())
            self.state.preferences.toolbar_x, self.state.preferences.toolbar_y = rect.x(), rect.y()
            self._position_overlays()
            self.rebuild_page()
            self.apply_grid_layout()
            self.queue_save()
            return
        for page in self.state.pages:
            for island in page.islands:
                rect = self._fit_rect(QRect(island.x, island.y, island.width, island.height))
                island.x, island.y = rect.x(), rect.y()
                island.width, island.height = rect.width(), rect.height()
        rect = self._fit_rect(self.toolbar.geometry())
        self.state.preferences.toolbar_x, self.state.preferences.toolbar_y = rect.x(), rect.y()
        self._position_overlays()
        self.rebuild_page()
        self.queue_save()

    def auto_arrange(self) -> None:
        self._capture_geometries()
        areas = self._screen_areas()
        primary = areas[0]
        self.state.preferences.toolbar_x = primary.center().x() - self.toolbar.width() // 2
        self.state.preferences.toolbar_y = primary.top()
        self._position_overlays()
        # Reserve a toolbar strip on every screen. Distribute a balanced grid
        # across monitors; every cell belongs to one real work area, never a gap.
        for page in self.state.pages:
            groups = [[] for _ in areas]
            for index, island in enumerate(page.islands):
                groups[index % len(areas)].append(island)
            for area, islands in zip(areas, groups):
                area = area.adjusted(0, self.toolbar.height() + 16, 0, 0)
                if not islands:
                    continue
                import math
                columns = max(1, min(len(islands), round(math.sqrt(len(islands) * area.width() / max(1, area.height())))))
                rows = math.ceil(len(islands) / columns)
                width = max(230, (area.width() - 12 * (columns - 1)) // columns)
                height = max(150, (area.height() - 12 * (rows - 1)) // rows)
                for index, island in enumerate(islands):
                    rect = self._fit_rect(QRect(area.x() + index % columns * (width + 12),
                                                area.y() + index // columns * (height + 12),
                                                min(width, 480), min(height, 600)))
                    island.x, island.y = rect.x(), rect.y()
                    island.width, island.height = rect.width(), rect.height()
        self.rebuild_page()
        self.queue_save()

    # Automatic arrangement mode ------------------------------------------------
    def grid_area(self) -> QRect:
        """Usable rectangle for islands, excluding the floating toolbar strip."""

        rect = self.surface.rect().adjusted(0, 0, 0, 0)
        top = self.toolbar.y() + self.toolbar.height() + 12
        return rect.adjusted(8, max(8, top), -8, -8)

    def is_auto_layout(self) -> bool:
        return bool(getattr(self.state.preferences, "auto_layout", False))

    def grid_metrics(self, page: PageState | None = None):
        """Pixel metrics of the micro-cell board for *page*."""

        page = page or self.current_page()
        area = self.grid_area()
        placements = self._grid_placements(page)
        return grid_layout.cells_for(
            max(1, area.width()), max(1, area.height()),
            grid_layout.content_rows(placements),
        )

    def _grid_placements(self, page: PageState):
        """Resolve every island on *page* to a board placement, in order."""

        levels = [grid_layout.normalise_level(island.size_level) for island in page.islands]
        pinned = [
            None if island.grid_col < 0 or island.grid_row < 0
            else (island.grid_col, island.grid_row)
            for island in page.islands
        ]
        return grid_layout.resolve(levels, pinned)

    def _placements_to_rects(self, placements) -> list[QRect]:
        """Convert board placements into board-relative pixel rectangles."""

        area = self.grid_area()
        metrics = grid_layout.cells_for(
            max(1, area.width()), max(1, area.height()),
            grid_layout.content_rows(placements),
        )
        rects = []
        for placement in placements:
            rect = grid_layout.to_rect(placement, metrics)
            rects.append(QRect(area.x() + rect.x, area.y() + rect.y, rect.width, rect.height))
        return rects

    def grid_rects(self, page: PageState | None = None) -> list[QRect]:
        """Computed geometry for the current (or given) page."""

        page = page or self.current_page()
        return self._placements_to_rects(self._grid_placements(page))

    def _sync_placements_to_state(self, page: PageState, placements) -> None:
        for island, placement in zip(page.islands, placements):
            island.grid_col = placement.col
            island.grid_row = placement.row

    def apply_grid_layout(self, animate: bool = True) -> None:
        """Re-flow the page and glide every island to its slot.

        All islands share one curve and one duration so the board moves as a
        single gesture rather than a queue of separate slides.
        """

        if not self.is_auto_layout():
            return
        page = self.current_page()
        placements = self._grid_placements(page)
        rects = self._placements_to_rects(placements)
        self._sync_placements_to_state(page, placements)
        for island_state, rect in zip(page.islands, rects):
            island_state.x, island_state.y = rect.x(), rect.y()
            island_state.width, island_state.height = rect.width(), rect.height()
            widget = self.islands.get(island_state.id)
            if widget is None:
                continue
            target = (float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height()))
            start = widget.grid_geometry()
            if animate and start != target:
                self._run_geometry_tween(widget, start, target)
            else:
                widget.apply_grid_geometry(*target)
        self.queue_save()

    def _run_geometry_tween(self, widget: IslandWidget, start, target) -> None:
        """Animate one island along the shared re-flow curve."""

        tween = getattr(widget, "_grid_tween", None)
        if tween is None:
            tween = motion.GeometryTween(widget, widget.apply_grid_geometry, motion.RELAYOUT_MS)
            widget._grid_tween = tween
        tween.finish()
        tween.to(start, target)

    def _seed_size_levels(self) -> None:
        """Give every island a level matching the width it already had.

        Turning the mode on must not visibly shuffle the page, so each level is
        derived from the island's current width.  This round-trips exactly: a ½
        island keeps its width ratio, so re-deriving it always yields ½ again.
        """

        area = self.grid_area()
        total = max(1, area.width())
        for page in self.state.pages:
            for island in page.islands:
                island.grid_col = -1
                island.grid_row = -1
                if not island.size_level:
                    island.size_level = grid_layout.DEFAULT_SIZE_LEVEL
                    continue
                ratio = island.width / total
                if ratio <= 0.30:
                    island.size_level = grid_layout.LEVEL_QUARTER
                elif ratio <= 0.42:
                    island.size_level = grid_layout.LEVEL_THIRD
                elif ratio <= 0.75:
                    island.size_level = grid_layout.LEVEL_HALF
                else:
                    island.size_level = grid_layout.LEVEL_FULL

    def set_auto_layout(self, enabled: bool) -> None:
        """Toggle the arrangement mode and rebuild the current layout."""

        enabled = bool(enabled)
        if bool(self.state.preferences.auto_layout) == enabled:
            return
        self.state.preferences.auto_layout = enabled
        if enabled:
            self._seed_size_levels()
        self.apply_grid_layout()
        self.rebuild_page()
        if self.is_auto_layout():
            self.apply_grid_layout()
        self.queue_save()

    def _compact_grid(self) -> None:
        """Close every gap on the page, then animate the result."""

        if not self.is_auto_layout():
            return
        page = self.current_page()
        compacted = grid_layout.compact(self._grid_placements(page))
        self._sync_placements_to_state(page, compacted)
        self.apply_grid_layout()


    def _watch_screen(self, screen):
        screen.geometryChanged.connect(self._schedule_screen_restore)
        screen.availableGeometryChanged.connect(self._schedule_screen_restore)
        screen.logicalDotsPerInchChanged.connect(self._schedule_screen_restore)

    def _schedule_screen_restore(self, *_args):
        self.screen_restore_timer.start()

    def _screen_added(self, screen):
        self._watch_screen(screen)
        self._schedule_screen_restore()

    def _restore_after_screen_change(self):
        self._capture_geometries()
        geometry = QApplication.screens()[0].geometry()
        for screen in QApplication.screens()[1:]:
            geometry = geometry.united(screen.geometry())
        self.setGeometry(geometry.adjusted(2, 2, -2, -2))
        provider().schedule_rebuild()
        # Preserve saved board coordinates; live windows still have their old
        # global origin until rebuilt after the monitor layout changes.
        self.rebuild_page()
        self.restore_positions()

    def show_board_menu(self, global_point: QPoint) -> None:
        menu = GlassMenu(passive=True)
        add_action = menu.addAction("新建收纳岛…")
        portal_action = menu.addAction("新建文件视窗…")
        html_action = menu.addAction("新建 HTML 动画…")
        web_action = menu.addAction("新建固定网页…")
        menu.addSeparator()
        hide_action = menu.addAction("恢复显示" if self.groups_hidden else "清屏")
        focus_action = menu.addAction("退出聚焦层" if self.focus_mode else "打开聚焦层")
        arrange_action = menu.addAction("自动排列收纳岛")
        scan_action = menu.addAction("扫描桌面新项目")
        menu.addSeparator()
        rules_action = menu.addAction("归流规则…")
        snapshot_action = menu.addAction("保存布局快照")
        restore_action = menu.addAction("恢复布局快照…")
        export_action = menu.addAction("导出布局…")
        import_action = menu.addAction("导入布局…")
        menu.addSeparator()
        settings_action = menu.addAction("设置…")
        update_action = menu.addAction("检查更新…")
        handlers = {
            add_action: lambda: self.add_island(False),
            portal_action: lambda: self.add_island(True),
            html_action: lambda: self.add_island(kind="html"),
            web_action: lambda: self.add_island(kind="web"),
            hide_action: self.toggle_hidden,
            focus_action: self.toggle_focus,
            arrange_action: self.auto_arrange,
            scan_action: self.import_new_desktop_items,
            rules_action: self.show_rules,
            snapshot_action: self.save_snapshot,
            restore_action: self.restore_snapshot,
            export_action: self.export_layout,
            import_action: self.import_layout,
            settings_action: self.show_settings,
            update_action: self.show_update_dialog,
        }
        chosen = menu.exec(global_point)
        handler = handlers.get(chosen)
        if handler is not None:
            handler()

    def show_settings(self, initial_page: int = 0) -> None:
        manager = self.updater
        dialog = SettingsDialog(
            copy.deepcopy(self.state.preferences),
            None,
            font_importer=getattr(self.store, "import_font", None),
            update_status=manager.last_check_text() if manager is not None else "尚未检查",
            initial_page=initial_page,
        )

        def check_now() -> None:
            self.show_update_dialog(parent=dialog)
            if self.updater is not None:
                dialog.set_update_status(self.updater.last_check_text())

        dialog.check_updates_requested.connect(check_now)
        if dialog.exec():
            was_auto = self.is_auto_layout()
            self.state.preferences = dialog.preferences
            self.apply_preferences()
            self._update_edge_timer()
            if self.is_auto_layout() != was_auto:
                # Re-flow (or release) every island when the mode changes.
                if self.is_auto_layout():
                    self._seed_size_levels()
                self.rebuild_page()
                self.apply_grid_layout()
            elif self.is_auto_layout():
                self.apply_grid_layout()
            if not self.demo_mode:
                self.native_host.show_native_icons(not self.state.preferences.hide_native_icons)
                if not self.native_host.set_startup(bool(self.state.preferences.start_with_windows)):
                    QMessageBox.warning(None, '开机启动', '无法更新开机启动设置，请检查当前用户的权限。')
            self.queue_save()
        dialog.deleteLater()

    def export_layout(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(None, '导出布局', 'DeskIsle-layout.json', '布局文件 (*.json)')
        if path:
            self._capture_geometries()
            try:
                self.store.export_state(self.state, path)
            except (OSError, RuntimeError) as exc:
                QMessageBox.warning(None, '导出失败', str(exc))

    def import_layout(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(None, '导入布局', '', '布局文件 (*.json)')
        if not path:
            return
        try:
            state = self.store.import_state(path, persist=False)
            answer = QMessageBox.question(None, '导入布局', '替换当前布局？当前布局会自动备份，原文件不会移动或删除。',
                                          QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                                          QMessageBox.StandardButton.Cancel)
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._capture_geometries()
            self.store.save_snapshot(self.state, '导入前自动备份')
            self.state = state
            self._ensure_state()
            self._rule_engine.rules = state.rules
            self.rebuild_page()
            self.save_state()
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(None, '导入失败', str(exc))

    def show_rules(self) -> None:
        islands = [island for page in self.state.pages for island in page.islands if _is_file_island(island)]
        dialog = RulesDialog(copy.deepcopy(self.state.rules), islands, None)
        if hasattr(dialog, "apply_requested"):
            def apply_dialog_rules() -> None:
                self.state.rules = copy.deepcopy(dialog.rules)
                self._rule_engine.rules = self.state.rules
                self.apply_rules()

            dialog.apply_requested.connect(apply_dialog_rules)
        if dialog.exec():
            self.state.rules = dialog.rules
            self._rule_engine.rules = self.state.rules
            self.queue_save()

    def save_snapshot(self) -> None:
        name, ok = QInputDialog.getText(None, "保存布局快照", "快照名称", text="手动快照")
        if not ok or not name.strip():
            return
        self.save_state()
        self.store.save_snapshot(self.state, name.strip())
        self.tray.showMessage(APP_NAME, "布局快照已保存。", QSystemTrayIcon.MessageIcon.Information, 1800)

    def restore_snapshot(self) -> None:
        snapshots = self.store.list_snapshots()
        if not snapshots:
            QMessageBox.information(None, "布局快照", "还没有布局快照。")
            return
        labels = []
        for snapshot in snapshots:
            if isinstance(snapshot, dict):
                labels.append(str(snapshot.get("name") or snapshot.get("path")))
            else:
                labels.append(getattr(snapshot, "stem", str(snapshot)))
        label, ok = QInputDialog.getItem(None, "恢复布局快照", "选择快照", labels, 0, False)
        if not ok:
            return
        index = labels.index(label)
        answer = QMessageBox.question(
            None,
            "确认恢复",
            "恢复会替换当前布局。当前状态会先自动保存。继续吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.save_state()
        self.store.save_snapshot(self.state, "恢复前自动备份")
        restored = self.store.restore_snapshot(snapshots[index])
        if restored is not None:
            self.state = restored
            self._ensure_state()
            self._rule_engine.rules = self.state.rules
            self.rebuild_page()
            self.queue_save()

    def _setup_tray(self) -> None:
        self.tray = QSystemTrayIcon(self._make_icon(), self)
        self.tray.setToolTip(APP_NAME)
        menu = GlassMenu()
        self._tray_menu = menu
        show_action = menu.addAction("显示 / 隐藏收纳岛")
        focus_action = menu.addAction("聚焦层")
        menu.addSeparator()
        add_action = menu.addAction("新建收纳岛")
        portal_action = menu.addAction("新建文件视窗")
        html_action = menu.addAction("新建 HTML 动画")
        web_action = menu.addAction("新建固定网页")
        menu.addSeparator()
        rules_action = menu.addAction("归流规则")
        settings_action = menu.addAction("设置")
        save_action = menu.addAction('保存布局快照')
        restore_action = menu.addAction('恢复布局快照…')
        export_action = menu.addAction('导出布局…')
        import_action = menu.addAction('导入布局…')
        menu.addSeparator()
        home_action = menu.addAction('全部归位（移回屏幕内）')
        arrange_action = menu.addAction('智能排列收纳岛')
        home_action.triggered.connect(self.restore_positions)
        arrange_action.triggered.connect(self.auto_arrange)
        menu.addSeparator()
        update_action = menu.addAction("检查更新…")
        exit_action = menu.addAction("退出")
        show_action.triggered.connect(lambda _checked=False: self.toggle_hidden())
        focus_action.triggered.connect(lambda _checked=False: self.toggle_focus())
        add_action.triggered.connect(lambda: self.add_island(False))
        portal_action.triggered.connect(lambda: self.add_island(True))
        html_action.triggered.connect(lambda: self.add_island(kind="html"))
        web_action.triggered.connect(lambda: self.add_island(kind="web"))
        rules_action.triggered.connect(self.show_rules)
        settings_action.triggered.connect(lambda _checked=False: self.show_settings())
        save_action.triggered.connect(self.save_snapshot)
        restore_action.triggered.connect(self.restore_snapshot)
        export_action.triggered.connect(self.export_layout)
        import_action.triggered.connect(self.import_layout)
        update_action.triggered.connect(lambda _checked=False: self.show_update_dialog())
        exit_action.triggered.connect(self.exit_application)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_hidden()

    def _make_icon(self) -> QIcon:
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor("#1D2A3A"))
        painter.setPen(QColor("#55D6BE"))
        painter.drawRoundedRect(5, 8, 54, 47, 13, 13)
        painter.setBrush(QColor("#55D6BE"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(13, 17, 38, 8, 4, 4)
        painter.drawRoundedRect(13, 31, 17, 15, 5, 5)
        painter.drawRoundedRect(34, 31, 17, 15, 5, 5)
        painter.end()
        return QIcon(pixmap)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._closing_for_real or self.demo_mode:
            self.save_timer.stop()
            self.save_state()
            self._cleanup_native()
            event.accept()
            return
        event.ignore()
        self.toggle_hidden(True)
        self.tray.showMessage(APP_NAME, "桌屿仍在托盘运行。", QSystemTrayIcon.MessageIcon.Information, 1800)

    def exit_application(self) -> None:
        self._closing_for_real = True
        self.save_state()
        self._cleanup_native()
        self.tray.hide()
        QApplication.quit()

    def _cleanup_native(self) -> None:
        self._occlusion_timer.stop()
        if self.updater is not None:
            self.updater.shutdown()
        for widget in self.islands.values():
            widget.hide()
        self.search.hide()
        html_view.shutdown()
        if not self.demo_mode:
            self.native_host.cleanup(int(self.winId()))

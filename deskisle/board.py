from __future__ import annotations

import copy
import os
from pathlib import Path

from PySide6.QtCore import QEvent, QFileSystemWatcher, QPoint, QRect, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QKeyEvent, QLinearGradient, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QFrame,
    QFileDialog,
    QPushButton,
    QSystemTrayIcon,
    QToolButton,
    QWidget,
)

from .dialogs import NewIslandDialog, RulesDialog, SettingsDialog
from .island import IslandWidget
from .items import ItemListWidget, open_path
from .models import AppState, IslandState, ItemRef, PageState, TabState
from .native_win import (
    MOD_ALT,
    MOD_CONTROL,
    MOD_NOREPEAT,
    VK_H,
    VK_LEFT,
    VK_RIGHT,
    VK_SPACE,
    DesktopHost,
    set_window_overlay,
    set_window_no_activate,
)
from .rules import RuleEngine
from .theme import APP_NAME, ISLAND_COLORS


HOTKEY_FOCUS = 0x5151
HOTKEY_HIDE = 0x5152
HOTKEY_PREV = 0x5153
HOTKEY_NEXT = 0x5154
WM_HOTKEY = 0x0312
ICON_DIR = Path(__file__).resolve().parent / "assets" / "icons"


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
            gradient = QLinearGradient(0, 0, self.width(), self.height())
            gradient.setColorAt(0.0, QColor("#0E1724"))
            gradient.setColorAt(0.48, QColor("#18243A"))
            gradient.setColorAt(1.0, QColor("#123833"))
            painter.fillRect(self.rect(), gradient)
            painter.setPen(QColor(255, 255, 255, 10))
            step = 42
            for x in range(0, self.width(), step):
                painter.drawLine(x, 0, x, self.height())
            for y in range(0, self.height(), step):
                painter.drawLine(0, y, self.width(), y)
        if self.focus_mode:
            painter.fillRect(self.rect(), QColor(4, 8, 14, 128))


class FloatingToolbar(QFrame):
    move_started = Signal()
    move_requested = Signal(QPoint)
    move_finished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("floatingToolbar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "QWidget#floatingToolbar { background: rgba(20,27,38,225); border: 1px solid rgba(130,150,175,80);"
            " border-radius: 16px; }"
            "QToolButton { background: transparent; border: 0; border-radius: 10px; color: #EAF0F8;"
            " padding: 5px 9px; font-size: 10pt; }"
            "QToolButton:hover { background: rgba(85,214,190,45); color: #7CE8D5; }"
            "QPushButton { background: transparent; border: 0; color: #F4F7FB; font-weight: 600; padding: 5px 12px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
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
        if not demo_mode:
            for screen in QApplication.screens():
                self._watch_screen(screen)
            QApplication.instance().screenAdded.connect(self._screen_added)
            QApplication.instance().screenRemoved.connect(self._schedule_screen_restore)
        self._setup_tray()
        self._ensure_state()
        self.rebuild_page()
        self.import_new_desktop_items(initial=True)
        QTimer.singleShot(0, self._after_show)
        if not demo_mode:
            QTimer.singleShot(0, self.restore_positions)

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

    def rebuild_page(self) -> None:
        for widget in list(self.islands.values()):
            widget.hide()
            widget.deleteLater()
        self.islands.clear()
        page = self.current_page()
        self.toolbar.page_button.setText(page.title)
        for island_state in page.islands:
            widget = IslandWidget(island_state, self.state.preferences.panel_opacity, self.surface,
                                  desktop_window=not self.demo_mode)
            widget.set_snap_callback(self.snap_position)
            widget.state_changed.connect(self.queue_save)
            widget.delete_requested.connect(self.delete_island)
            widget.references_dropped.connect(self._move_references)
            widget.references_removed.connect(self._remove_references)
            widget.item_list.unavailable_remove_requested.connect(self._remove_unavailable_references)
            widget.item_list.shell_operation_finished.connect(self.import_new_desktop_items)
            self.islands[island_state.id] = widget
            widget.show()
            if widget.desktop_window:
                set_window_no_activate(int(widget.winId()), True)
                set_window_overlay(int(widget.winId()), self.focus_mode)
            else:
                widget.raise_()
        self._refresh_loose()
        if self.focus_mode:
            self.loose_view.show()
            for widget in self.islands.values():
                widget.show()
        else:
            self.loose_view.setVisible(not self.groups_hidden)
            for widget in self.islands.values():
                keep = bool(getattr(widget.state, "exclude_from_hide", False))
                widget.setVisible((not self.groups_hidden) or keep)
        if self.search.text():
            self._filter_items(self.search.text())
        self.toolbar.raise_()
        if self.search.isVisible():
            self.search.raise_()

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

    def add_island(self, portal: bool = False) -> None:
        data = NewIslandDialog.get_data(None, force_portal=portal)
        if not data:
            return
        title = str(data.get("title") or data.get("name") or "新收纳岛").strip()
        folder = data.get("folder") or data.get("folder_path") or data.get("path")
        page = self.current_page()
        index = len(page.islands)
        width, height = 340, 270
        x = 48 + (index % 4) * 365
        y = 90 + (index // 4) * 295
        tab = TabState(title="全部", portal_path=str(folder) if folder else None)
        state = IslandState(
            title=title,
            x=min(x, max(20, self.surface.width() - width - 20)),
            y=min(y, max(70, self.surface.height() - height - 20)),
            width=width,
            height=height,
            color=ISLAND_COLORS[index % len(ISLAND_COLORS)],
            tabs=[tab],
            active_tab_id=tab.id,
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
        detail = "其中 {0} 个引用会回到桌面散放区；原文件不会删除。".format(len(virtual_items))
        answer = QMessageBox.question(
            None,
            "删除收纳岛",
            "删除“{0}”？\n{1}\n文件视窗对应的真实文件夹也不会删除。".format(target.title, detail),
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
            target_island = next((item for item in all_islands if item.id == target_id), None)
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
                    if island.id == target_id:
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
                set_window_overlay(int(widget.winId()), wanted)
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
        self.rebuild_page()
        self.queue_save()

    def add_page(self) -> None:
        name, ok = QInputDialog.getText(None, "新建场景页", "场景页名称", text="新场景")
        if ok and name.strip():
            page = PageState(title=name.strip())
            self.state.pages.append(page)
            self.state.current_page_id = page.id
            self.rebuild_page()
            self.queue_save()

    def rename_page(self) -> None:
        page = self.current_page()
        name, ok = QInputDialog.getText(None, "重命名场景页", "名称", text=page.title)
        if ok and name.strip():
            page.title = name.strip()
            self.toolbar.page_button.setText(page.title)
            self.queue_save()

    def _show_page_menu(self) -> None:
        menu = QMenu()
        menu.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        menu.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
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
        # Preserve saved board coordinates; live windows still have their old
        # global origin until rebuilt after the monitor layout changes.
        self.rebuild_page()
        self.restore_positions()

    def show_board_menu(self, global_point: QPoint) -> None:
        menu = QMenu()
        menu.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        menu.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        add_action = menu.addAction("新建收纳岛…")
        portal_action = menu.addAction("新建文件视窗…")
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
        settings_action = menu.addAction("设置…")
        chosen = menu.exec(global_point)
        if chosen == add_action:
            self.add_island(False)
        elif chosen == portal_action:
            self.add_island(True)
        elif chosen == hide_action:
            self.toggle_hidden()
        elif chosen == focus_action:
            self.toggle_focus()
        elif chosen == arrange_action:
            self.auto_arrange()
        elif chosen == scan_action:
            self.import_new_desktop_items()
        elif chosen == rules_action:
            self.show_rules()
        elif chosen == snapshot_action:
            self.save_snapshot()
        elif chosen == restore_action:
            self.restore_snapshot()
        elif chosen == export_action:
            self.export_layout()
        elif chosen == import_action:
            self.import_layout()
        elif chosen == settings_action:
            self.show_settings()

    def show_settings(self) -> None:
        dialog = SettingsDialog(copy.deepcopy(self.state.preferences), None)
        if dialog.exec():
            self.state.preferences = dialog.preferences
            for island in self.islands.values():
                island.opacity = self.state.preferences.panel_opacity
                island.update()
            if not self.demo_mode:
                self.native_host.show_native_icons(not self.state.preferences.hide_native_icons)
                if not self.native_host.set_startup(bool(self.state.preferences.start_with_windows)):
                    QMessageBox.warning(None, '开机启动', '无法更新开机启动设置，请检查当前用户的权限。')
            self.queue_save()

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
        islands = [island for page in self.state.pages for island in page.islands]
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
        menu = QMenu()
        show_action = menu.addAction("显示 / 隐藏收纳岛")
        focus_action = menu.addAction("聚焦层")
        add_action = menu.addAction("新建收纳岛")
        portal_action = menu.addAction("新建文件视窗")
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
        exit_action = menu.addAction("退出")
        show_action.triggered.connect(lambda _checked=False: self.toggle_hidden())
        focus_action.triggered.connect(lambda _checked=False: self.toggle_focus())
        add_action.triggered.connect(lambda: self.add_island(False))
        portal_action.triggered.connect(lambda: self.add_island(True))
        rules_action.triggered.connect(self.show_rules)
        settings_action.triggered.connect(self.show_settings)
        save_action.triggered.connect(self.save_snapshot)
        restore_action.triggered.connect(self.restore_snapshot)
        export_action.triggered.connect(self.export_layout)
        import_action.triggered.connect(self.import_layout)
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
        for widget in self.islands.values():
            widget.hide()
        self.search.hide()
        if not self.demo_mode:
            self.native_host.cleanup(int(self.winId()))

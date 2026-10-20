from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import QEasingCurve, QFileSystemWatcher, QPoint, QRectF, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QColorDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTabBar,
    QToolButton,
    QWidget,
)

from .items import ItemListWidget, open_path
from .models import IslandState, TabState
from .theme import ACCENT


HEADER_HEIGHT = 42
TAB_HEIGHT = 36
TAB_TOP = HEADER_HEIGHT + 4
CONTENT_TOP = TAB_TOP + TAB_HEIGHT + 8
COLLAPSED_HEIGHT = 44
MINIMUM_WIDTH = 230
MINIMUM_HEIGHT = 150


class CollapseButton(QToolButton):
    """Draw a panel icon with an animated chevron, independent of font glyphs."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.progress = 0.0
        self._highlight = 0.0
        self._feedback = QVariantAnimation(self)
        self._feedback.setDuration(100)
        self._feedback.valueChanged.connect(self._set_highlight)
        self.setAccessibleName('收起收纳岛')

    def _set_highlight(self, value):
        self._highlight = float(value)
        self.update()

    def _animate_feedback(self, value):
        self._feedback.stop()
        self._feedback.setStartValue(self._highlight)
        self._feedback.setEndValue(value)
        self._feedback.start()

    def enterEvent(self, event):  # noqa: N802
        self._animate_feedback(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        self._animate_feedback(0.0)
        super().leaveEvent(event)

    def set_progress(self, value):
        self.progress = max(0.0, min(1.0, float(value)))
        self.update()

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QColor(85, 214, 190, 85 if self.isDown() else int(14 + 32 * self._highlight))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
        painter.translate(self.width() / 2, self.height() / 2)
        if self.isDown():
            painter.scale(0.88, 0.88)
        color = QColor('#8AF2DF' if self.isDown() or self._highlight > 0.5 else '#EAF0F8')
        painter.setPen(QPen(color, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(-8, -7, 16, 14), 2.5, 2.5)
        painter.drawLine(-7, -3, 7, -3)
        painter.translate(0, 2)
        painter.rotate(180 * self.progress)
        arrow = QPainterPath()
        arrow.moveTo(-3, 1.5)
        arrow.lineTo(0, -1.5)
        arrow.lineTo(3, 1.5)
        painter.drawPath(arrow)


class IslandHeader(QWidget):
    move_started = Signal()
    move_requested = Signal(QPoint)
    move_finished = Signal()
    collapse_requested = Signal()
    menu_requested = Signal(QPoint)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(HEADER_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_origin: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(13, 4, 7, 3)
        layout.setSpacing(6)
        self.title_label = QLabel("收纳岛")
        self.title_label.setStyleSheet("font-size: 10.5pt; font-weight: 650; color: #F4F7FB;")
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.count_label = QLabel("0")
        self.count_label.setStyleSheet(
            "color: #AAB4C4; background: rgba(255,255,255,16); border-radius: 9px; padding: 1px 7px;"
        )
        self.count_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.title_label)
        layout.addWidget(self.count_label)
        layout.addStretch(1)

        self.lock_label = QLabel("")
        self.lock_label.setStyleSheet("color: #AAB4C4;")
        self.lock_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        layout.addWidget(self.lock_label)

        self.collapse_button = CollapseButton()
        self.collapse_button.setToolTip("收拢 / 展开")
        self.collapse_button.clicked.connect(self.collapse_requested)
        self.menu_button = QToolButton()
        self.menu_button.setText("•••")
        self.menu_button.setToolTip("收纳岛菜单")
        self.menu_button.clicked.connect(lambda: self.menu_requested.emit(self.menu_button.mapToGlobal(QPoint(0, self.menu_button.height()))))
        for button in (self.collapse_button, self.menu_button):
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setFixedSize(32, 30)
            button.setStyleSheet(
                "QToolButton { color: #EAF0F8; background: transparent; border: 0; border-radius: 7px; }"
                "QToolButton:hover { background: rgba(255,255,255,30); }"
            )
            layout.addWidget(button)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self.grabMouse()
            self.move_started.emit()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            now = event.globalPosition().toPoint()
            delta = now - self._drag_origin
            self.move_requested.emit(delta)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._drag_origin is not None:
            self._drag_origin = None
            if self.mouseGrabber() is self:
                self.releaseMouse()
            self.move_finished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.collapse_requested.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ResizeGrip(QWidget):
    resize_started = Signal()
    resize_requested = Signal(QPoint)
    resize_finished = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(20, 20)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self._origin: QPoint | None = None

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 90), 1.4))
        painter.drawLine(9, 17, 17, 9)
        painter.drawLine(13, 17, 17, 13)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._origin = event.globalPosition().toPoint()
            self.resize_started.emit()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            now = event.globalPosition().toPoint()
            self.resize_requested.emit(now - self._origin)
            self._origin = now
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._origin is not None:
            self._origin = None
            self.resize_finished.emit()
            event.accept()


class IslandWidget(QWidget):
    state_changed = Signal()
    visual_geometry_changed = Signal()
    geometry_interaction_started = Signal()
    geometry_interaction_finished = Signal()
    delete_requested = Signal(str)
    references_dropped = Signal(list, str, str, str, str)
    references_removed = Signal(list, str, str)

    def __init__(self, state: IslandState, opacity: float = 0.88, parent=None, *, desktop_window=False) -> None:
        super().__init__(parent)
        self.desktop_window = desktop_window
        self._board = parent
        if desktop_window:
            # Each island gets a small backing store. Moving it is now a native
            # window move, not a blit inside a monitor-sized layered window.
            self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                                | Qt.WindowType.WindowStaysOnBottomHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.state = state
        self.opacity = max(0.35, min(1.0, opacity))
        self._portal_current: dict[str, str] = {}
        self._portal_history: dict[str, list[str]] = {}
        self._hovered = False
        self._snap_callback = None
        self._move_origin: QPoint | None = None
        self._pending_resize = QPoint()
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(16)
        self._resize_timer.timeout.connect(self._flush_resize)
        self._collapse_animation = QVariantAnimation(self)
        self._collapse_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._collapse_animation.valueChanged.connect(self._animate_height)
        self._collapse_animation.finished.connect(self._finish_collapse)
        self._collapse_animating = False
        self._collapse_snapshot = None
        self._visual_height = 0.0

        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setMinimumSize(MINIMUM_WIDTH, COLLAPSED_HEIGHT)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

        self.header = IslandHeader(self)
        self.header.move_started.connect(self._begin_move)
        self.header.move_requested.connect(self._move_by)
        self.header.move_finished.connect(self._commit_geometry)
        self.header.collapse_requested.connect(self.toggle_collapsed)
        self.header.menu_requested.connect(self.show_menu)

        self.tabs_row = QWidget(self)
        tabs_layout = QHBoxLayout(self.tabs_row)
        tabs_layout.setContentsMargins(8, 0, 8, 2)
        tabs_layout.setSpacing(4)
        self.tab_bar = QTabBar()
        self.tab_bar.setExpanding(False)
        self.tab_bar.setMovable(True)
        self.tab_bar.setTabsClosable(True)
        self.tab_bar.setElideMode(Qt.TextElideMode.ElideRight)
        self.tab_bar.setDocumentMode(True)
        self.tab_bar.setDrawBase(False)
        self.tab_bar.currentChanged.connect(self._tab_changed)
        self.tab_bar.tabCloseRequested.connect(self._close_tab)
        self.tab_bar.tabMoved.connect(self._tab_moved)
        self.tab_bar.tabBarDoubleClicked.connect(self._rename_tab)
        self.tab_bar.setStyleSheet(
            "QTabBar::tab { color: #AAB4C4; background: rgba(255,255,255,10); border: 0;"
            " border-radius: 7px; padding: 5px 12px; margin-right: 3px; min-width: 45px; }"
            "QTabBar::tab:selected { color: white; background: rgba(85,214,190,55); }"
            "QTabBar::close-button { image: none; width: 8px; }"
        )
        self.add_tab_button = QToolButton()
        self.add_tab_button.setText("＋")
        self.add_tab_button.setToolTip("添加标签页")
        self.add_tab_button.clicked.connect(self.add_tab)
        self.add_tab_button.setStyleSheet(
            "QToolButton { background: transparent; border: 0; color: #AAB4C4; font-size: 14pt; }"
            "QToolButton:hover { color: #55D6BE; }"
        )
        tabs_layout.addWidget(self.tab_bar, 1)
        tabs_layout.addWidget(self.add_tab_button)

        self.portal_bar = QFrame(self)
        portal_layout = QHBoxLayout(self.portal_bar)
        portal_layout.setContentsMargins(9, 1, 9, 4)
        portal_layout.setSpacing(5)
        self.back_button = self._small_button("‹", "返回")
        self.up_button = self._small_button("↑", "上一级")
        self.refresh_button = self._small_button("↻", "刷新")
        self.path_label = QLabel("")
        self.path_label.setStyleSheet("color: #AAB4C4; font-size: 8.5pt;")
        self.path_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        portal_layout.addWidget(self.back_button)
        portal_layout.addWidget(self.up_button)
        portal_layout.addWidget(self.path_label, 1)
        portal_layout.addWidget(self.refresh_button)
        self.back_button.clicked.connect(self.portal_back)
        self.up_button.clicked.connect(self.portal_up)
        self.refresh_button.clicked.connect(self.refresh_items)

        initial_tab_id = getattr(state, "active_tab_id", "") or ""
        self.item_list = ItemListWidget(state.id, initial_tab_id, self)
        self.item_list.files_dropped.connect(self._handle_files_dropped)
        self.item_list.remove_requested.connect(self.references_removed)
        self.item_list.reorder_requested.connect(self._reorder_items)
        self.item_list.activated_path.connect(self._activate_path)
        self.item_list.blank_context_requested.connect(self.show_menu)
        self.item_list.shell_operation_finished.connect(self.refresh_items)

        self.empty_label = QLabel("把文件拖到这里", self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: rgba(220,230,240,115); font-size: 10pt;")
        self.empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.grip = ResizeGrip(self)
        self.grip.resize_started.connect(self.geometry_interaction_started)
        self.grip.resize_requested.connect(self._resize_by)
        self.grip.resize_finished.connect(self._commit_geometry)

        self.watcher = QFileSystemWatcher(self)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(120)
        self.refresh_timer.timeout.connect(self.refresh_items)
        self.watcher.directoryChanged.connect(lambda _path: self.refresh_timer.start())
        self.watcher.fileChanged.connect(lambda _path: self.refresh_timer.start())

        self._rebuild_tabs()
        actual_height = COLLAPSED_HEIGHT if state.collapsed else max(MINIMUM_HEIGHT, state.height)
        self.setGeometry(state.x, state.y, max(MINIMUM_WIDTH, state.width), actual_height)
        self.move_on_board(QPoint(state.x, state.y))
        self.refresh_items()
        self._sync_collapsed_state()
        for context_widget in (
            self,
            self.header,
            self.tabs_row,
            self.tab_bar,
            self.portal_bar,
            self.path_label,
        ):
            self._bind_island_context_menu(context_widget)

    def _bind_island_context_menu(self, widget: QWidget) -> None:
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda point, owner=widget: self.show_menu(owner.mapToGlobal(point))
        )

    def _small_button(self, text: str, tooltip: str) -> QPushButton:
        button = QPushButton(text)
        button.setToolTip(tooltip)
        button.setFixedSize(25, 24)
        button.setStyleSheet(
            "QPushButton { background: rgba(255,255,255,12); border: 0; border-radius: 6px; padding: 0; }"
            "QPushButton:hover { background: rgba(255,255,255,28); color: #55D6BE; }"
        )
        return button

    def set_snap_callback(self, callback) -> None:
        self._snap_callback = callback

    def board_position(self) -> QPoint:
        if self.desktop_window and self._board is not None:
            return self._board.mapFromGlobal(self.pos())
        return self.pos()

    def move_on_board(self, point: QPoint) -> None:
        if self.desktop_window and self._board is not None:
            point = self._board.mapToGlobal(point)
        if point != self.pos():
            self.move(point)

    def active_tab(self) -> TabState:
        if not self.state.tabs:
            tab = TabState(title="全部")
            self.state.tabs.append(tab)
        wanted = getattr(self.state, "active_tab_id", "")
        for tab in self.state.tabs:
            if tab.id == wanted:
                return tab
        self.state.active_tab_id = self.state.tabs[0].id
        return self.state.tabs[0]

    def _rebuild_tabs(self) -> None:
        self.tab_bar.blockSignals(True)
        while self.tab_bar.count():
            self.tab_bar.removeTab(0)
        active_index = 0
        for index, tab in enumerate(self.state.tabs):
            self.tab_bar.addTab(tab.title)
            self.tab_bar.setTabData(index, tab.id)
            if tab.id == getattr(self.state, "active_tab_id", ""):
                active_index = index
        if self.state.tabs:
            self.tab_bar.setCurrentIndex(active_index)
            self.state.active_tab_id = self.state.tabs[active_index].id
        self.tab_bar.blockSignals(False)
        self.tab_bar.setTabsClosable(len(self.state.tabs) > 1)

    def refresh_items(self) -> None:
        tab = self.active_tab()
        portal_path = getattr(tab, "portal_path", None)
        records: list[tuple[str, str]] = []
        if portal_path:
            current = self._portal_current.get(tab.id, portal_path)
            self._portal_current[tab.id] = current
            path = Path(current)
            if path.is_dir():
                try:
                    children = [p for p in path.iterdir() if not p.name.startswith(".")]
                except OSError:
                    children = []
                children.sort(key=self._sort_key, reverse=tab.sort_descending)
                records = [(str(child), "") for child in children[:1000]]
            self.path_label.setText(self._short_path(current))
            self.path_label.setToolTip(current)
            self.portal_bar.show()
            self._watch_path(current)
        else:
            items = list(getattr(tab, "items", []))
            if getattr(tab, "sort_mode", "name") != "manual":
                items.sort(
                    key=lambda item: self._sort_key(Path(item.path)),
                    reverse=tab.sort_descending,
                )
            records = [(item.path, getattr(item, "title", "")) for item in items]
            self.portal_bar.hide()
            self._watch_path(None)
        self.item_list.configure(self.state.id, tab.id, int(self.state.icon_size), bool(portal_path))
        self.item_list.set_paths(records)
        self.header.title_label.setText(self.state.title)
        self.header.count_label.setText(str(len(records)))
        self.header.lock_label.setText("🔒" if self.state.locked else "")
        self.header.setCursor(
            Qt.CursorShape.ForbiddenCursor if self.state.locked else Qt.CursorShape.SizeAllCursor
        )
        self.empty_label.setText("文件夹不可用" if portal_path and not Path(self._portal_current.get(tab.id, portal_path)).is_dir() else "把文件拖到这里")
        self.empty_label.setVisible(not records and not self.state.collapsed)
        self._layout_children()
        self.update()

    def _sort_key(self, path: Path):
        tab = self.active_tab()
        mode = getattr(tab, "sort_mode", "name")
        try:
            if mode == "modified":
                return (0 if path.is_dir() else 1, path.stat().st_mtime, path.name.casefold())
            if mode == "type":
                return (0 if path.is_dir() else 1, path.suffix.casefold(), path.name.casefold())
        except OSError:
            pass
        return (0 if path.is_dir() else 1, path.name.casefold())

    def _short_path(self, value: str) -> str:
        if len(value) <= 42:
            return value
        return "…" + value[-41:]

    def _watch_path(self, path: str | None) -> None:
        old = self.watcher.directories()
        if old:
            self.watcher.removePaths(old)
        if path and os.path.isdir(path):
            self.watcher.addPath(path)

    def _activate_path(self, path: str) -> None:
        tab = self.active_tab()
        if getattr(tab, "portal_path", None) and os.path.isdir(path):
            current = self._portal_current.get(tab.id, tab.portal_path)
            self._portal_history.setdefault(tab.id, []).append(current)
            self._portal_current[tab.id] = path
            self.refresh_items()
            return
        if not open_path(path):
            QMessageBox.warning(None, "无法打开", "无法打开：\n" + path)

    def portal_back(self) -> None:
        tab = self.active_tab()
        history = self._portal_history.get(tab.id, [])
        if history:
            self._portal_current[tab.id] = history.pop()
            self.refresh_items()

    def portal_up(self) -> None:
        tab = self.active_tab()
        if not getattr(tab, "portal_path", None):
            return
        current = Path(self._portal_current.get(tab.id, tab.portal_path))
        root = Path(tab.portal_path)
        try:
            current.relative_to(root)
        except ValueError:
            self._portal_current[tab.id] = str(root)
            self.refresh_items()
            return
        if current != root:
            self._portal_history.setdefault(tab.id, []).append(str(current))
            self._portal_current[tab.id] = str(current.parent)
            self.refresh_items()

    def _handle_files_dropped(self, paths: list[str], source_island: str, source_tab: str) -> None:
        tab = self.active_tab()
        if getattr(tab, "portal_path", None):
            destination = Path(self._portal_current.get(tab.id, tab.portal_path))
            if not destination.is_dir():
                QMessageBox.warning(None, "文件夹不可用", "目标文件夹当前不可用。")
                return
            answer = QMessageBox.question(
                None,
                "复制到文件视窗",
                "将 {0} 个项目复制到：\n{1}\n\n这是实际文件操作。".format(len(paths), destination),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            failures: list[str] = []
            for value in paths:
                source = Path(value)
                try:
                    source_resolved = source.resolve()
                    destination_resolved = destination.resolve()
                except OSError:
                    failures.append(str(source))
                    continue
                if source.is_dir() and (
                    destination_resolved == source_resolved
                    or source_resolved in destination_resolved.parents
                ):
                    # Copying a directory into itself or one of its children
                    # recursively expands forever. Reject it before touching
                    # the filesystem.
                    failures.append(str(source) + "（目标位于源目录内部）")
                    continue
                target = self._unique_destination(destination / source.name)
                try:
                    if source.is_dir():
                        shutil.copytree(source, target)
                    else:
                        shutil.copy2(source, target)
                except OSError:
                    failures.append(str(source))
            self.refresh_items()
            if failures:
                QMessageBox.warning(None, "部分复制失败", "以下项目未复制：\n" + "\n".join(failures[:8]))
            return
        self.references_dropped.emit(paths, source_island, source_tab, self.state.id, tab.id)

    def _reorder_items(
        self,
        paths: list[str],
        island_id: str,
        tab_id: str,
        target_index: int,
    ) -> None:
        if island_id != self.state.id:
            return
        tab = next((item for item in self.state.tabs if item.id == tab_id), None)
        if tab is None or getattr(tab, "portal_path", None):
            return

        # The drop index refers to the currently displayed order. Convert that
        # order into the new persistent manual order before moving selections.
        displayed = list(tab.items)
        if getattr(tab, "sort_mode", "name") != "manual":
            displayed.sort(
                key=lambda item: self._sort_key(Path(item.path)),
                reverse=tab.sort_descending,
            )
        selected_keys = {os.path.normcase(path) for path in paths}
        moving = [
            item for item in displayed
            if os.path.normcase(item.path) in selected_keys
        ]
        if not moving:
            return
        selected_before_target = sum(
            1
            for index, item in enumerate(displayed)
            if index < target_index and os.path.normcase(item.path) in selected_keys
        )
        remaining = [
            item for item in displayed
            if os.path.normcase(item.path) not in selected_keys
        ]
        insert_at = max(
            0,
            min(len(remaining), target_index - selected_before_target),
        )
        tab.items = remaining[:insert_at] + moving + remaining[insert_at:]
        tab.sort_mode = "manual"
        self.refresh_items()
        self.state_changed.emit()

    def _unique_destination(self, path: Path) -> Path:
        if not path.exists():
            return path
        stem, suffix = path.stem, path.suffix
        for index in range(2, 10000):
            candidate = path.with_name("{0} ({1}){2}".format(stem, index, suffix))
            if not candidate.exists():
                return candidate
        raise OSError("无法生成不冲突的文件名")

    def _tab_changed(self, index: int) -> None:
        if index < 0:
            return
        tab_id = self.tab_bar.tabData(index)
        if tab_id:
            self.state.active_tab_id = str(tab_id)
            self.refresh_items()
            self.state_changed.emit()

    def _tab_moved(self, old_index: int, new_index: int) -> None:
        if old_index == new_index or old_index < 0 or new_index < 0:
            return
        tab = self.state.tabs.pop(old_index)
        self.state.tabs.insert(new_index, tab)
        self.state_changed.emit()

    def _rename_tab(self, index: int) -> None:
        if index < 0:
            return
        tab = self.state.tabs[index]
        name, ok = QInputDialog.getText(None, "重命名标签", "标签名称", text=tab.title)
        if ok and name.strip():
            tab.title = name.strip()
            self.tab_bar.setTabText(index, tab.title)
            self.state_changed.emit()

    def add_tab(self) -> None:
        name, ok = QInputDialog.getText(None, "添加标签", "标签名称", text="新标签")
        if not ok or not name.strip():
            return
        tab = TabState(title=name.strip())
        self.state.tabs.append(tab)
        self.state.active_tab_id = tab.id
        self._rebuild_tabs()
        self.refresh_items()
        self.state_changed.emit()

    def _close_tab(self, index: int) -> None:
        if len(self.state.tabs) <= 1 or index < 0:
            return
        tab = self.state.tabs[index]
        answer = QMessageBox.question(
            None,
            "移除标签",
            "移除标签“{0}”？\n普通标签中的文件不会被删除，文件视窗的目标文件夹也不会被删除。".format(tab.title),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if not getattr(tab, "portal_path", None) and tab.items:
            self.references_removed.emit(
                [item.path for item in list(tab.items)], self.state.id, tab.id
            )
        self.state.tabs.pop(index)
        self.state.active_tab_id = self.state.tabs[max(0, index - 1)].id
        self._rebuild_tabs()
        self.refresh_items()
        self.state_changed.emit()

    def _move_by(self, delta: QPoint) -> None:
        if self.state.locked:
            return
        target = (self._move_origin if self._move_origin is not None else self.board_position()) + delta
        if self._snap_callback is not None:
            # Keep live dragging pixel-smooth; apply grid/edge snapping only
            # when the mouse is released. This avoids the "won't move" feel
            # caused by repeatedly rounding small mouse deltas.
            target = self._snap_callback(self, target, False)
        self.move_on_board(target)
        self.visual_geometry_changed.emit()

    def _begin_move(self) -> None:
        self._move_origin = self.board_position()
        self.geometry_interaction_started.emit()

    def _resize_by(self, delta: QPoint) -> None:
        if self.state.locked or self.state.collapsed:
            return
        self._pending_resize += delta
        if not self._resize_timer.isActive():
            self._resize_timer.start()

    def _flush_resize(self) -> None:
        delta = self._pending_resize
        self._pending_resize = QPoint()
        if delta.isNull() or self.state.locked or self.state.collapsed:
            return
        self.resize(
            max(MINIMUM_WIDTH, self.width() + delta.x()),
            max(MINIMUM_HEIGHT, self.height() + delta.y()),
        )
        self.visual_geometry_changed.emit()

    def _commit_geometry(self) -> None:
        if self._resize_timer.isActive():
            self._resize_timer.stop()
        self._flush_resize()
        if self._move_origin is not None and self._snap_callback is not None:
            self.move_on_board(self._snap_callback(self, self.board_position(), True))
        self.state.x = self.board_position().x()
        self.state.y = self.board_position().y()
        self.state.width = self.width()
        if not self.state.collapsed and not self._collapse_animating:
            self.state.height = self.height()
        self._move_origin = None
        self.state_changed.emit()
        self.geometry_interaction_finished.emit()

    def toggle_collapsed(self) -> None:
        was_animating = self._collapse_animating
        start_height = self._visual_height if was_animating else float(self.height())
        if not was_animating and not self.state.collapsed:
            self.state.height = self.height()
        self._collapse_animation.stop()
        self.state.collapsed = not self.state.collapsed
        target = COLLAPSED_HEIGHT if self.state.collapsed else max(MINIMUM_HEIGHT, self.state.height)
        self._collapse_animating = True
        if not was_animating:
            # Allocate the layered backing store once. Repeated native resize
            # calls can stall Windows composition for hundreds of milliseconds.
            expanded = max(MINIMUM_HEIGHT, self.state.height)
            self._visual_height = float(expanded)
            self.resize(self.width(), expanded)
            self._set_content_visible(True)
            self.grip.hide()
            self._layout_children()
            self._collapse_snapshot = self.grab()
            self._set_content_visible(False)
        self._visual_height = start_height
        self._update_collapse_label()
        self._collapse_animation.setDuration(160)
        self._collapse_animation.setStartValue(start_height)
        self._collapse_animation.setEndValue(float(target))
        self._collapse_animation.start()
        self.update()
        self.state_changed.emit()

    def _animate_height(self, value):
        self._visual_height = float(value)
        expanded = max(MINIMUM_HEIGHT, self.state.height)
        self.header.collapse_button.set_progress((expanded - value) / (expanded - COLLAPSED_HEIGHT))
        self.update()

    def _finish_collapse(self):
        self._collapse_animating = False
        self._sync_collapsed_state()
        self.state_changed.emit()

    def _update_collapse_label(self):
        label = '展开收纳岛' if self.state.collapsed else '收起收纳岛'
        self.header.collapse_button.setToolTip(label)
        self.header.collapse_button.setAccessibleName(label)

    def _sync_collapsed_state(self) -> None:
        self._collapse_animation.stop()
        self._collapse_animating = False
        self._collapse_snapshot = None
        if self.state.collapsed:
            self.resize(self.width(), COLLAPSED_HEIGHT)
        else:
            self.resize(self.width(), max(MINIMUM_HEIGHT, self.state.height))
        self.header.collapse_button.set_progress(float(self.state.collapsed))
        self._update_collapse_label()
        self._set_content_visible(not self.state.collapsed)
        self.grip.setVisible(not self.state.collapsed and not self.state.locked)
        self._layout_children()
        self.update()
        self.visual_geometry_changed.emit()

    def _set_content_visible(self, visible):
        self.tabs_row.setVisible(visible)
        self.portal_bar.setVisible(visible and bool(getattr(self.active_tab(), 'portal_path', None)))
        self.item_list.setVisible(visible)
        self.empty_label.setVisible(visible and self.item_list.count() == 0)

    def _layout_children(self) -> None:
        margin = 5
        self.header.setGeometry(margin, 2, self.width() - margin * 2, HEADER_HEIGHT)
        if self.state.collapsed and not self._collapse_animating:
            return
        content_height = max(MINIMUM_HEIGHT, self.state.height) if self._collapse_animating else self.height()
        y = TAB_TOP
        self.tabs_row.setGeometry(margin, y, self.width() - margin * 2, TAB_HEIGHT)
        y += TAB_HEIGHT + 8
        if not self.portal_bar.isHidden():
            self.portal_bar.setGeometry(margin, y, self.width() - margin * 2, 31)
            y += 31
        self.item_list.setGeometry(7, y, self.width() - 14, max(20, content_height - y - 8))
        self.empty_label.setGeometry(14, y + 10, self.width() - 28, max(30, content_height - y - 30))
        self.grip.move(self.width() - self.grip.width() - 3, self.height() - self.grip.height() - 3)
        self.grip.raise_()

    def resizeEvent(self, event) -> None:  # noqa: N802
        self._layout_children()
        super().resizeEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        height = self._visual_height if self._collapse_animating else self.height()
        rect = QRectF(2.0, 2.0, self.width() - 4.0, height - 4.0)
        path = QPainterPath()
        path.addRoundedRect(rect, 13.0, 13.0)
        base = QColor(self.state.color)
        base.setAlphaF(min(1.0, self.opacity + (0.05 if self._hovered else 0.0)))
        painter.fillPath(path, base)
        if self._collapse_animating and self._collapse_snapshot is not None:
            painter.save()
            painter.setClipPath(path)
            painter.setClipRect(QRectF(0, HEADER_HEIGHT, self.width(), max(0, height - HEADER_HEIGHT)),
                                Qt.ClipOperation.IntersectClip)
            # The captured pixels already include their translucent background.
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            painter.drawPixmap(0, 0, self._collapse_snapshot)
            painter.restore()
        border = QColor(ACCENT if self._hovered else "#8290A3")
        border.setAlpha(130 if self._hovered else 58)
        painter.setPen(QPen(border, 1.2))
        painter.drawPath(path)
        if not self.state.collapsed or self._collapse_animating:
            painter.setPen(QPen(QColor(255, 255, 255, 24), 1))
            painter.drawLine(12, CONTENT_TOP - 4, self.width() - 12, CONTENT_TOP - 4)

    def show_menu(self, global_point: QPoint) -> None:
        menu = QMenu()
        menu.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        menu.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        rename_action = menu.addAction("重命名收纳岛")
        new_tab_action = menu.addAction("添加标签页")
        portal_action = menu.addAction("将当前标签设为文件视窗…")
        if getattr(self.active_tab(), "portal_path", None):
            portal_action.setText("更换文件视窗目录…")
            unbind_action = menu.addAction("取消文件视窗（不删除目录）")
        else:
            unbind_action = None
        menu.addSeparator()
        color_action = menu.addAction("更换颜色…")
        size_menu = menu.addMenu("图标大小")
        size_actions = {}
        for size, label in ((40, "小"), (56, "中"), (72, "大")):
            action = size_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(int(self.state.icon_size) == size)
            size_actions[action] = size
        sort_menu = menu.addMenu("排序")
        sort_actions = {}
        sort_options = [("name", "按名称"), ("type", "按类型"), ("modified", "按修改时间")]
        if not getattr(self.active_tab(), "portal_path", None):
            sort_options.insert(0, ("manual", "手动排序"))
        for mode, label in sort_options:
            action = sort_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(getattr(self.active_tab(), "sort_mode", "name") == mode)
            sort_actions[action] = mode
        reverse_action = sort_menu.addAction("降序")
        reverse_action.setCheckable(True)
        reverse_action.setChecked(self.active_tab().sort_descending)
        menu.addSeparator()
        lock_action = menu.addAction("锁定位置" if not self.state.locked else "解除锁定")
        exclude_action = menu.addAction("清屏时保持显示")
        exclude_action.setCheckable(True)
        exclude_action.setChecked(bool(getattr(self.state, "exclude_from_hide", False)))
        collapse_action = menu.addAction("展开" if self.state.collapsed else "收拢")
        menu.addSeparator()
        delete_action = menu.addAction("删除收纳岛…")
        chosen = menu.exec(global_point)
        if chosen is None:
            return
        if chosen == rename_action:
            name, ok = QInputDialog.getText(None, "重命名收纳岛", "名称", text=self.state.title)
            if ok and name.strip():
                self.state.title = name.strip()
                self.refresh_items()
                self.state_changed.emit()
        elif chosen == new_tab_action:
            self.add_tab()
        elif chosen == portal_action:
            folder = QFileDialog.getExistingDirectory(None, "选择文件夹", getattr(self.active_tab(), "portal_path", "") or "")
            if folder:
                tab = self.active_tab()
                if not getattr(tab, "portal_path", None) and tab.items:
                    answer = QMessageBox.question(
                        None,
                        "转换为文件视窗",
                        "当前标签中的 {0} 个引用会回到桌面散放区；原文件不会移动或删除。继续吗？".format(len(tab.items)),
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                        QMessageBox.StandardButton.Cancel,
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        return
                    self.references_removed.emit(
                        [item.path for item in list(tab.items)], self.state.id, tab.id
                    )
                tab.portal_path = folder
                self._portal_current[tab.id] = folder
                self.refresh_items()
                self.state_changed.emit()
        elif unbind_action is not None and chosen == unbind_action:
            tab = self.active_tab()
            tab.portal_path = None
            self._portal_current.pop(tab.id, None)
            self.refresh_items()
            self.state_changed.emit()
        elif chosen == color_action:
            color = QColorDialog.getColor(QColor(self.state.color), None, "收纳岛颜色")
            if color.isValid():
                self.state.color = color.name()
                self.update()
                self.state_changed.emit()
        elif chosen in size_actions:
            self.state.icon_size = size_actions[chosen]
            self.refresh_items()
            self.state_changed.emit()
        elif chosen in sort_actions:
            self.active_tab().sort_mode = sort_actions[chosen]
            self.refresh_items()
            self.state_changed.emit()
        elif chosen == reverse_action:
            self.active_tab().sort_descending = not self.active_tab().sort_descending
            self.refresh_items()
            self.state_changed.emit()
        elif chosen == lock_action:
            self.state.locked = not self.state.locked
            self._sync_collapsed_state()
            self.refresh_items()
            self.state_changed.emit()
        elif chosen == exclude_action:
            self.state.exclude_from_hide = exclude_action.isChecked()
            self.state_changed.emit()
        elif chosen == collapse_action:
            self.toggle_collapsed()
        elif chosen == delete_action:
            self.delete_requested.emit(self.state.id)

"""One floating island: glass + media background, header, tabs and icon grid.

Islands can also host live web content (``kind == "html"`` animations and
``kind == "web"`` pinned pages); those reuse the same glass shell, header,
collapse morph and menus.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QLinearGradient,
    QMouseEvent,
    QPainter,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QTabBar,
    QWidget,
)

from . import motion, theme
from .backdrop import GlassCache, GlassStyle, glass_path, paint_glass_base, paint_glass_rim, painter_ratio, provider
from .grid_layout import LEVEL_FULL, LEVEL_HALF, LEVEL_QUARTER, LEVEL_THIRD, normalise_level
from .items import ItemListWidget, open_path, reveal_path
from .media import MEDIA_FILTER, MediaLayer, import_media_file
from .models import MATERIALS, IslandState, TabState
from .widgets import GlassMenu, GlyphButton, draw_glyph


HEADER_HEIGHT = 42
TAB_HEIGHT = 36
TAB_TOP = HEADER_HEIGHT + 4
CONTENT_TOP = TAB_TOP + TAB_HEIGHT + 8
COLLAPSED_HEIGHT = 44
MINIMUM_WIDTH = 230
MINIMUM_HEIGHT = 150
EXPANDED_RADIUS = 18.0
PILL_RADIUS = (COLLAPSED_HEIGHT - 4) / 2.0
MIN_ICON_SIZE = 32
MAX_ICON_SIZE = 96
ICON_STEP = 8
WEB_KINDS = ("html", "web")

_default_material = "frosted"


def set_default_material(material: str) -> None:
    """Global “背景质感”; islands with an empty ``material`` follow it."""
    global _default_material
    _default_material = material if material in MATERIALS else "frosted"


def default_material() -> str:
    return _default_material


def effective_material(state: IslandState) -> str:
    value = getattr(state, "material", "") or ""
    return value if value in MATERIALS else _default_material


class CollapseButton(GlyphButton):
    """Chevron that rotates with the collapse morph."""

    def __init__(self, parent=None):
        super().__init__("chevron-up", parent, diameter=28, tooltip="收起收纳岛", glyph_size=17)
        self.progress = 0.0

    def set_progress(self, value):
        self.progress = max(0.0, min(1.0, float(value)))
        self.set_rotation(180.0 * self.progress)


class MenuButton(GlyphButton):
    def __init__(self, parent=None):
        super().__init__("dots", parent, diameter=28, tooltip="收纳岛菜单", glyph_size=17)


class IslandHeader(QWidget):
    """Custom-painted title row.

    The title and the count capsule are painted (not QLabels) so the capsule
    keeps a fixed 20 px pill height and both can scale smoothly while the
    island morphs into its collapsed pill.
    """

    move_started = Signal()
    move_requested = Signal(QPoint)
    move_finished = Signal()
    collapse_requested = Signal()
    menu_requested = Signal(QPoint)

    BADGE_HEIGHT = 20.0

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedHeight(HEADER_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._drag_origin: QPoint | None = None
        self.title = "收纳岛"
        self.badge_text = "0"
        self.badge_visible = True
        self.locked = False
        self.pinned = False
        self.progress = 0.0
        self.text_shadow = False

        self.collapse_button = CollapseButton(self)
        self.collapse_button.setToolTip("收拢 / 展开")
        self.collapse_button.clicked.connect(self.collapse_requested)
        self.menu_button = MenuButton(self)
        self.menu_button.clicked.connect(
            lambda: self.menu_requested.emit(self.menu_button.mapToGlobal(QPoint(0, self.menu_button.height())))
        )

    # State -------------------------------------------------------------
    def set_title(self, text: str) -> None:
        text = text or "收纳岛"
        if text != self.title:
            self.title = text
            self.setAccessibleName(text)
            self.update()

    def set_badge(self, text: str, visible: bool = True) -> None:
        if text != self.badge_text or visible != self.badge_visible:
            self.badge_text, self.badge_visible = text, visible
            self.update()

    def set_count(self, count: int) -> None:
        self.set_badge(str(int(count)), True)

    def set_locked(self, locked: bool, pinned: bool = False) -> None:
        if locked != self.locked or pinned != self.pinned:
            self.locked, self.pinned = locked, pinned
            self.update()

    def set_progress(self, value: float) -> None:
        self.progress = max(0.0, min(1.0, float(value)))
        self.collapse_button.set_progress(self.progress)
        self.update()

    def set_text_shadow(self, enabled: bool) -> None:
        if enabled != self.text_shadow:
            self.text_shadow = enabled
            self.update()

    # Geometry ----------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        y = (self.height() - self.menu_button.height()) // 2
        right = self.width() - 4
        self.menu_button.move(right - self.menu_button.width(), y)
        self.collapse_button.move(self.menu_button.x() - self.collapse_button.width(), y)
        super().resizeEvent(event)

    def title_font(self) -> QFont:
        return theme.ui_font(10.5, QFont.Weight.DemiBold)

    def badge_rect(self) -> QRectF:
        """Geometry of the count capsule (for tests and hit testing)."""
        return self._layout()[2]

    def _layout(self):
        p = self.progress
        scale = 1.0 + 0.07 * p
        font = self.title_font()
        metrics = QFontMetricsF(font)
        badge_font = theme.ui_font(8.5, QFont.Weight.DemiBold)
        badge_metrics = QFontMetricsF(badge_font)
        left = 13.0 + 4.0 * p
        limit = float(self.collapse_button.x()) - 6.0
        badge_w = max(self.BADGE_HEIGHT, badge_metrics.horizontalAdvance(self.badge_text) + 13.0) if self.badge_visible else 0.0
        glyphs = (14.0 if self.locked else 0.0) + (14.0 if self.pinned else 0.0)
        reserve = (badge_w + 7.0 if self.badge_visible else 0.0) + glyphs
        available = max(10.0, (limit - left - reserve) / scale)
        title = metrics.elidedText(self.title, Qt.TextElideMode.ElideRight, available)
        title_w = metrics.horizontalAdvance(title) * scale
        cy = self.height() / 2.0
        badge = QRectF(left + title_w + 7.0, cy - self.BADGE_HEIGHT / 2.0, badge_w, self.BADGE_HEIGHT)
        return font, title, badge, badge_font, scale, left, cy, metrics

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font, title, badge, badge_font, scale, left, cy, metrics = self._layout()
        painter.save()
        painter.translate(left, cy)
        painter.scale(scale, scale)
        painter.setFont(font)
        baseline = (metrics.ascent() - metrics.descent()) / 2.0
        if self.text_shadow:
            painter.setPen(QColor(0, 0, 0, 120))
            painter.drawText(QPointF(0, baseline + 1.0), title)
        painter.setPen(QColor(theme.TEXT))
        painter.drawText(QPointF(0, baseline), title)
        painter.restore()
        x = badge.right() + 5.0
        if self.badge_visible:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 40 if self.text_shadow else 30))
            painter.drawRoundedRect(badge, badge.height() / 2.0, badge.height() / 2.0)
            painter.setFont(badge_font)
            painter.setPen(QColor(theme.TEXT if self.text_shadow else theme.TEXT_MUTED))
            painter.drawText(badge, Qt.AlignmentFlag.AlignCenter, self.badge_text)
        else:
            x = left + metrics.horizontalAdvance(title) * scale + 7.0
        glyph_color = QColor(theme.TEXT_MUTED)
        if self.locked:
            draw_glyph(painter, "lock", QRectF(x, cy - 7.0, 13.0, 13.0), glyph_color)
            x += 15.0
        if self.pinned:
            draw_glyph(painter, "pin", QRectF(x, cy - 7.0, 13.0, 13.0), glyph_color)

    # Dragging ----------------------------------------------------------
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
        self._hover = 0.0
        self._tween = motion.Tween(self, self._set_hover, 0.0, motion.HOVER_MS)

    def _set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._tween.to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._tween.to(0.0)
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(255, 255, 255, int(70 + 90 * self._hover)), 1.6, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawLine(QPointF(8.5, 16.0), QPointF(16.0, 8.5))
        painter.drawLine(QPointF(12.5, 16.0), QPointF(16.0, 12.5))

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


TAB_STYLESHEET = (
    "QTabBar { background: transparent; }"
    "QTabBar::tab { color: #A1A1A8; background: rgba(255,255,255,14); border: 0;"
    " border-radius: 10px; padding: 4px 12px; margin: 3px 4px 3px 0; min-width: 40px; }"
    "QTabBar::tab:hover { color: #F5F5F7; background: rgba(255,255,255,26); }"
    "QTabBar::tab:selected { color: #FFFFFF; background: rgba(255,255,255,54); }"
    "QTabBar::close-button { image: none; width: 8px; }"
    "QTabBar QToolButton { background: rgba(28,28,30,200); border: 0; border-radius: 8px; color: #F5F5F7; }"
)


class IslandWidget(QWidget):
    state_changed = Signal()
    visual_geometry_changed = Signal()
    geometry_interaction_started = Signal()
    geometry_interaction_finished = Signal()
    delete_requested = Signal(str)
    references_dropped = Signal(list, str, str, str, str)
    references_removed = Signal(list, str, str)
    window_level_changed = Signal()
    level_requested = Signal(str, str)
    level_cycle_requested = Signal(str)

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
        self._hover = 0.0
        self._hover_tween = motion.Tween(self, self._set_hover, 0.0, motion.HOVER_MS)
        self._snap_callback = None
        self._move_origin: QPoint | None = None
        self._grid_locked = False
        self._pending_resize = QPoint()
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(16)
        self._resize_timer.timeout.connect(self._flush_resize)
        self._progress = 1.0 if state.collapsed else 0.0
        self._collapse_tween = motion.Tween(self, self._animate_progress, self._progress, motion.COLLAPSE_MS,
                                            motion.ios_curve())
        self._collapse_animating = False
        self._collapse_snapshot: QPixmap | None = None
        self._snapshot_pass = False
        self._visual_height = 0.0
        self._glass_cache = GlassCache()
        self.media = MediaLayer(self)
        self.media.frame_changed.connect(self._media_frame)
        self._snapshot_layer = MediaLayer(self)
        self._snapshot_layer.frame_changed.connect(self.update)
        self.web = None
        self._commit_timer = QTimer(self)
        self._commit_timer.setSingleShot(True)
        self._commit_timer.setInterval(450)
        self._commit_timer.timeout.connect(self.state_changed)

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
        tabs_layout.setContentsMargins(8, 0, 6, 2)
        tabs_layout.setSpacing(2)
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
        self.tab_bar.setStyleSheet(TAB_STYLESHEET)
        self.add_tab_button = GlyphButton("plus", diameter=24, tooltip="添加标签页", glyph_size=15)
        self.add_tab_button.clicked.connect(self.add_tab)
        tabs_layout.addWidget(self.tab_bar, 1)
        tabs_layout.addWidget(self.add_tab_button)

        self.portal_bar = QFrame(self)
        portal_layout = QHBoxLayout(self.portal_bar)
        portal_layout.setContentsMargins(7, 1, 7, 4)
        portal_layout.setSpacing(3)
        self.back_button = GlyphButton("chevron-left", diameter=24, tooltip="返回", glyph_size=15)
        self.up_button = GlyphButton("arrow-up", diameter=24, tooltip="上一级", glyph_size=14)
        self.refresh_button = GlyphButton("reload", diameter=24, tooltip="刷新", glyph_size=14)
        self.path_label = QLabel("")
        self.path_label.setStyleSheet("color: #A1A1A8; font-size: 8.5pt; background: transparent;")
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
        self.item_list.zoom_requested.connect(self.zoom_icons)

        self.empty_label = QLabel("把文件拖到这里", self)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: rgba(235,235,245,110); font-size: 10pt; background: transparent;")
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

        if self.is_web_content:
            self._create_web_content()
        self._rebuild_tabs()
        actual_height = COLLAPSED_HEIGHT if state.collapsed else max(MINIMUM_HEIGHT, state.height)
        self.setGeometry(state.x, state.y, max(MINIMUM_WIDTH, state.width), actual_height)
        self._visual_height = float(actual_height)
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
        self._apply_media()
        provider().changed.connect(self._backdrop_changed)

    # Kind helpers -------------------------------------------------------
    @property
    def is_web_content(self) -> bool:
        return getattr(self.state, "kind", "files") in WEB_KINDS

    def _create_web_content(self) -> None:
        from .html_view import WebContentView

        self.web = WebContentView(self.state.kind, self)
        self.web.menu_requested.connect(self.show_menu)
        self.web.title_changed.connect(lambda title: self.header.setToolTip(title))
        for widget in (self.tabs_row, self.portal_bar, self.item_list, self.empty_label):
            widget.hide()
        self._load_web_content()

    def _load_web_content(self) -> None:
        if self.web is None:
            return
        self.web.set_zoom(getattr(self.state, "web_zoom", 1.0))
        if self.state.kind == "html":
            self.web.set_html_file(self.state.html_path, self.state.html_allow_network)
        else:
            self.web.set_toolbar_visible(self.state.web_toolbar)
            self.web.set_refresh_minutes(self.state.web_refresh_minutes)
            self.web.load_url(self.state.web_url)

    def _bind_island_context_menu(self, widget: QWidget) -> None:
        widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda point, owner=widget: self.show_menu(owner.mapToGlobal(point))
        )

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

    def _refresh_header(self, count: int) -> None:
        self.header.set_title(self.state.title)
        kind = getattr(self.state, "kind", "files")
        if kind == "html":
            self.header.set_badge("HTML", True)
        elif kind == "web":
            self.header.set_badge("网页", True)
        else:
            self.header.set_count(count)
        self.header.set_locked(bool(self.state.locked), bool(getattr(self.state, "pin_on_top", False)))
        self.header.setCursor(
            Qt.CursorShape.ForbiddenCursor if self.state.locked else Qt.CursorShape.SizeAllCursor
        )

    def refresh_items(self) -> None:
        if self.web is not None:
            self._refresh_header(0)
            self._layout_children()
            self.update()
            return
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
        self._refresh_header(len(records))
        self.empty_label.setText("文件夹不可用" if portal_path and not Path(self._portal_current.get(tab.id, portal_path)).is_dir() else "把文件拖到这里")
        self.empty_label.setVisible(not records and not self.state.collapsed)
        if self.state.collapsed or self._collapse_animating:
            self.portal_bar.hide()
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
        if self.state.locked or self.state.collapsed or getattr(self, "_grid_locked", False):
            return
        self._pending_resize += delta
        if not self._resize_timer.isActive():
            self._resize_timer.start()

    def _flush_resize(self) -> None:
        delta = self._pending_resize
        self._pending_resize = QPoint()
        if delta.isNull() or self.state.locked or self.state.collapsed:
            return
        if getattr(self, "_grid_locked", False):
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
        if not was_animating and not self.state.collapsed:
            self.state.height = self.height()
        self.state.collapsed = not self.state.collapsed
        target = 1.0 if self.state.collapsed else 0.0
        self._collapse_animating = True
        if not was_animating:
            # Allocate the layered backing store once. Repeated native resize
            # calls can stall Windows composition for hundreds of milliseconds.
            expanded = max(MINIMUM_HEIGHT, self.state.height)
            if self.height() != expanded:
                self.resize(self.width(), expanded)
            self._capture_content_snapshot(expanded)
            self._set_content_visible(False)
            self.grip.hide()
            self._visual_height = motion.mix(float(expanded), float(COLLAPSED_HEIGHT), self._progress)
        self._update_collapse_label()
        self._collapse_tween.to(target, motion.COLLAPSE_MS, motion.ios_curve(), on_finished=self._finish_collapse)
        self.update()
        self.state_changed.emit()

    def _capture_content_snapshot(self, expanded: int) -> None:
        """Render the content (not the glass) once; the morph scales it."""
        ratio = self.devicePixelRatioF()
        pixmap = QPixmap(max(1, int(self.width() * ratio)), max(1, int(expanded * ratio)))
        pixmap.setDevicePixelRatio(ratio)
        pixmap.fill(Qt.GlobalColor.transparent)
        if self.web is not None:
            image = self.web.grab_snapshot() if self.web.isVisible() else self.web.snapshot()
            if image is not None and not image.isNull():
                self._snapshot_layer.set_static_image(image)
                painter = QPainter(pixmap)
                painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
                self._layout_web_geometry(expanded)
                painter.drawImage(QRectF(self.web.geometry()), image)
                painter.end()
            self._collapse_snapshot = pixmap
            return
        self._set_content_visible(True)
        self.grip.hide()
        self._layout_children()
        top = HEADER_HEIGHT + 1
        self._snapshot_pass = True
        try:
            from PySide6.QtGui import QRegion

            self.render(pixmap, QPoint(0, top), QRegion(0, top, self.width(), max(1, expanded - top)),
                        QWidget.RenderFlag.DrawChildren)
        finally:
            self._snapshot_pass = False
        self._collapse_snapshot = pixmap

    def _animate_progress(self, value: float) -> None:
        self._progress = float(value)
        expanded = max(MINIMUM_HEIGHT, self.state.height)
        self._visual_height = motion.mix(float(expanded), float(COLLAPSED_HEIGHT), self._progress)
        self.header.set_progress(self._progress)
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
        self._collapse_tween.stop()
        self._collapse_animating = False
        self._collapse_snapshot = None
        self._progress = 1.0 if self.state.collapsed else 0.0
        self._collapse_tween.value = self._collapse_tween.target = self._progress
        self.header.set_progress(self._progress)
        if self.state.collapsed:
            self.resize(self.width(), COLLAPSED_HEIGHT)
        else:
            self.resize(self.width(), max(MINIMUM_HEIGHT, self.state.height))
        self._visual_height = float(self.height())
        self._update_collapse_label()
        self._set_content_visible(not self.state.collapsed)
        self.grip.setVisible(not self.state.collapsed and not self.state.locked)
        self._layout_children()
        self.update()
        self.visual_geometry_changed.emit()

    def set_grid_size(self, width: int, height: int) -> None:
        """Apply a size dictated by the automatic arrangement mode.

        The grid owns width and height in this mode, so the interactive resize
        grip is hidden and the stored geometry is updated in place.
        """

        self._grid_locked = True
        self.state.width = max(MINIMUM_WIDTH, int(width))
        if not self.state.collapsed:
            self.state.height = max(MINIMUM_HEIGHT, int(height))
            self.resize(self.state.width, self.state.height)
        else:
            self.resize(self.state.width, self.height())
        self.grip.hide()
        self._layout_children()

    def grid_geometry(self) -> tuple[float, float, float, float]:
        """Current ``(x, y, w, h)`` in board coordinates, for animating."""

        point = self.board_position()
        return float(point.x()), float(point.y()), float(self.width()), float(self.height())

    def apply_grid_geometry(self, x: float, y: float, width: float, height: float) -> None:
        """Place and size the island directly; used by the move animation."""

        self._grid_locked = True
        width_i = max(MINIMUM_WIDTH, int(round(width)))
        height_i = max(MINIMUM_HEIGHT, int(round(height)))
        self.state.width = width_i
        if not self.state.collapsed:
            self.state.height = height_i
            if self.width() != width_i or self.height() != height_i:
                self.resize(width_i, height_i)
        elif self.width() != width_i:
            self.resize(width_i, self.height())
        self.move_on_board(QPoint(int(round(x)), int(round(y))))
        self._layout_children()

    def set_grid_unlocked(self) -> None:
        """Return to free layout and re-show the resize grip."""

        if not getattr(self, "_grid_locked", False):
            return
        self._grid_locked = False
        self.grip.setVisible(not self.state.collapsed and not self.state.locked)

    def _set_content_visible(self, visible):
        if self.web is not None:
            for widget in (self.tabs_row, self.portal_bar, self.item_list, self.empty_label):
                widget.setVisible(False)
            self.web.set_suspended("collapsed", not visible)
            self.web.setVisible(visible)
            return
        self.tabs_row.setVisible(visible)
        self.portal_bar.setVisible(visible and bool(getattr(self.active_tab(), 'portal_path', None)))
        self.item_list.setVisible(visible)
        self.empty_label.setVisible(visible and self.item_list.count() == 0)

    def _layout_web_geometry(self, content_height: int) -> None:
        if self.web is not None:
            self.web.setGeometry(8, HEADER_HEIGHT + 1, max(20, self.width() - 16),
                                 max(20, content_height - HEADER_HEIGHT - 9))

    def _layout_children(self) -> None:
        margin = 5
        self.header.setGeometry(margin, 1, self.width() - margin * 2, HEADER_HEIGHT)
        if self.state.collapsed and not self._collapse_animating:
            return
        content_height = max(MINIMUM_HEIGHT, self.state.height) if self._collapse_animating else self.height()
        if self.web is not None:
            self._layout_web_geometry(content_height)
        else:
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

    # Events -------------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        self._layout_children()
        if not self._collapse_animating and not self.state.collapsed:
            ratio = self.devicePixelRatioF()
            self.media.set_target_size(QSize(int(self.width() * ratio), int(self.height() * ratio)))
        super().resizeEvent(event)

    def moveEvent(self, event) -> None:  # noqa: N802
        # The glass samples whatever is behind the island, so it has to be
        # recomposed after a move (clear glass has nothing to resample).
        if effective_material(self.state) != "clear":
            self.update()
        super().moveEvent(event)

    def _backdrop_changed(self) -> None:
        self._glass_cache.clear()
        self.update()

    def _set_hover(self, value: float) -> None:
        self._hover = value
        self.update()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self._hover_tween.to(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self._hover_tween.to(0.0)
        super().leaveEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802
        self.set_suspended("hidden", False)
        super().showEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self.set_suspended("hidden", True)
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.media.clear()
        if self.web is not None:
            self.web.release()
        super().closeEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier and self.web is None:
            delta = event.angleDelta().y()
            if delta:
                self.zoom_icons(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)

    def set_suspended(self, reason: str, suspended: bool) -> None:
        """Pause video / web content while the island cannot be seen."""
        self.media.set_suspended(reason, suspended)
        if self.web is not None:
            self.web.set_suspended(reason, suspended)

    # Icon zoom ----------------------------------------------------------
    def zoom_icons(self, direction: int) -> None:
        if self.web is not None:
            return
        current = int(self.state.icon_size)
        size = max(MIN_ICON_SIZE, min(MAX_ICON_SIZE, current + ICON_STEP * (1 if direction > 0 else -1)))
        if size != current:
            self.set_icon_size(size)

    def set_icon_size(self, size: int, animate: bool = True) -> None:
        self.state.icon_size = int(size)
        if animate and self.item_list.isVisible():
            self.item_list.animate_icon_size(int(size))
        else:
            self.refresh_items()
        self._commit_timer.start()

    # Media ----------------------------------------------------------------
    def _media_frame(self) -> None:
        self._update_text_shadow()
        self.update()

    def _update_text_shadow(self) -> None:
        enabled = self.media.has_frame()
        self.header.set_text_shadow(enabled)
        self.item_list.set_text_shadow(enabled)

    def _apply_media(self) -> None:
        ratio = self.devicePixelRatioF()
        expanded = max(MINIMUM_HEIGHT, self.state.height)
        self.media.set_target_size(QSize(int(self.width() * ratio), int(expanded * ratio)))
        path = getattr(self.state, "media_path", "") or ""
        if path:
            self.media.set_source(path)
        else:
            self.media.clear()
        self._update_text_shadow()
        self._glass_cache.clear()
        self.update()

    def apply_appearance(self) -> None:
        """Re-read title, material, tint and media from ``self.state``."""
        self._apply_media()
        self.refresh_items()
        self.update()

    def _background_layer(self):
        if self.media.has_frame():
            return self.media, float(self.state.media_opacity)
        if (self.web is not None and self.state.kind == "html" and self._snapshot_layer.has_frame()
                and (self.state.collapsed or self._collapse_animating)):
            return self._snapshot_layer, 0.92 * self._progress
        return None

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._snapshot_pass:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        height = self._visual_height if self._collapse_animating else float(self.height())
        p = self._progress
        rect = QRectF(2.0, 2.0, self.width() - 4.0, max(8.0, height - 4.0))
        radius = min(motion.mix(EXPANDED_RADIUS, PILL_RADIUS, p), rect.height() / 2.0, rect.width() / 2.0)
        background = self._background_layer()
        style = GlassStyle(effective_material(self.state), QColor(self.state.color), self.opacity, radius,
                           self._hover, 0.0 if background is not None else p)
        origin = provider().canvas_point(self) if style.material != "clear" else None
        paint_glass_base(painter, rect, style, origin, self._glass_cache)
        if background is not None:
            layer, layer_opacity = background
            feather = min(float(self.state.media_feather), rect.height() * 0.32, rect.width() * 0.25)
            if layer.paint(painter, rect, radius, feather, layer_opacity, painter_ratio(painter)):
                self._paint_media_scrim(painter, rect, radius, p)
        if self._collapse_animating and self._collapse_snapshot is not None:
            content_alpha = motion.clamp01(1.0 - p * 1.3)
            if content_alpha > 0.01:
                painter.save()
                painter.setClipPath(glass_path(rect, radius))
                painter.setClipRect(QRectF(0, HEADER_HEIGHT, self.width(), max(0.0, height - HEADER_HEIGHT - 3)),
                                    Qt.ClipOperation.IntersectClip)
                painter.setOpacity(content_alpha)
                scale = motion.mix(1.0, 0.94, p)
                cx = self.width() / 2.0
                painter.translate(cx, HEADER_HEIGHT)
                painter.scale(scale, scale)
                painter.translate(-cx, -HEADER_HEIGHT - 10.0 * p)
                painter.drawPixmap(0, 0, self._collapse_snapshot)
                painter.restore()
        paint_glass_rim(painter, rect, style)
        if self.web is None and (not self.state.collapsed or self._collapse_animating):
            line_y = CONTENT_TOP - 4
            if line_y < rect.bottom() - 6:
                painter.setPen(QPen(QColor(255, 255, 255, int(20 * (1.0 - p))), 1))
                painter.drawLine(QPointF(14, line_y + 0.5), QPointF(self.width() - 14, line_y + 0.5))

    def _paint_media_scrim(self, painter: QPainter, rect: QRectF, radius: float, p: float) -> None:
        """Darken behind the title so it stays legible on bright media."""
        painter.save()
        painter.setClipPath(glass_path(rect, radius))
        depth = motion.mix(HEADER_HEIGHT + 16.0, rect.height(), p)
        gradient = QLinearGradient(QPointF(0, rect.top()), QPointF(0, rect.top() + depth))
        gradient.setColorAt(0.0, QColor(0, 0, 0, 74))
        gradient.setColorAt(1.0, QColor(0, 0, 0, int(36 * p)))
        painter.fillRect(rect, gradient)
        wash = QColor(self.state.color)
        wash.setAlpha(26)
        painter.fillRect(rect, wash)
        painter.restore()

    # Web drop targets -------------------------------------------------------
    def _web_drop_value(self, mime) -> str:
        if self.web is None or not mime.hasUrls() or not mime.urls():
            return ""
        url = mime.urls()[0]
        if self.state.kind == "html":
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in (".html", ".htm", ".xhtml"):
                return url.toLocalFile()
            return ""
        if url.scheme().lower() in ("http", "https"):
            return url.toString()
        return ""

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if self._web_drop_value(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if self._web_drop_value(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        value = self._web_drop_value(event.mimeData())
        if value:
            if self.state.kind == "html":
                self.state.html_path = value
            else:
                self.state.web_url = value
            self._load_web_content()
            self.state_changed.emit()
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    # Menu -------------------------------------------------------------------
    def show_menu(self, global_point: QPoint) -> None:
        menu = GlassMenu(passive=True)
        kind = getattr(self.state, "kind", "files")
        handlers: dict = {}

        def add(text: str, handler, *, checkable: bool = False, checked: bool = False, enabled: bool = True,
                target=None):
            action = (target or menu).addAction(text)
            if checkable:
                action.setCheckable(True)
                action.setChecked(checked)
            action.setEnabled(enabled)
            handlers[action] = handler
            return action

        add("外观与名称…", self.edit_appearance)
        media_menu = menu.addMenu("背景媒体")
        add("选择图片或视频…", self.choose_media, target=media_menu)
        add("移除背景媒体", self.clear_media, enabled=bool(self.state.media_path), target=media_menu)
        menu.addSeparator()

        if kind == "html":
            add("更换 HTML 文件…", self.choose_html_file)
            add("重新加载", self._reload_web)
            add("在资源管理器中显示", lambda: reveal_path(self.state.html_path), enabled=bool(self.state.html_path))
            add("允许页面联网", self._toggle_html_network, checkable=True, checked=bool(self.state.html_allow_network))
            zoom_menu = menu.addMenu("内容缩放")
            self._add_zoom_actions(zoom_menu, add)
        elif kind == "web":
            add("更改网址…", self.change_web_url)
            add("回到固定网址", self._load_web_content)
            add("重新加载", self._reload_web)
            add("在浏览器中打开", lambda: self.web is not None and self.web.open_in_browser())
            add("显示导航栏", self._toggle_web_toolbar, checkable=True, checked=bool(self.state.web_toolbar))
            refresh_menu = menu.addMenu("自动刷新")
            for minutes, label in ((0, "关闭"), (1, "每 1 分钟"), (5, "每 5 分钟"), (15, "每 15 分钟"),
                                   (30, "每 30 分钟"), (60, "每 60 分钟")):
                add(label, lambda m=minutes: self._set_web_refresh(m), checkable=True,
                    checked=int(self.state.web_refresh_minutes) == minutes, target=refresh_menu)
            zoom_menu = menu.addMenu("页面缩放")
            self._add_zoom_actions(zoom_menu, add)
        else:
            add("重命名收纳岛", self.rename_island)
            add("添加标签页", self.add_tab)
            portal_text = "更换文件视窗目录…" if getattr(self.active_tab(), "portal_path", None) else "将当前标签设为文件视窗…"
            add(portal_text, self.choose_portal_folder)
            if getattr(self.active_tab(), "portal_path", None):
                add("取消文件视窗（不删除目录）", self.unbind_portal)
            menu.addSeparator()
            size_menu = menu.addMenu("图标大小")
            for size, label in ((40, "小"), (56, "中"), (72, "大")):
                add(label, lambda s=size: self.set_icon_size(s), checkable=True,
                    checked=int(self.state.icon_size) == size, target=size_menu)
            size_menu.addSeparator()
            add("放大", lambda: self.zoom_icons(1), enabled=int(self.state.icon_size) < MAX_ICON_SIZE, target=size_menu)
            add("缩小", lambda: self.zoom_icons(-1), enabled=int(self.state.icon_size) > MIN_ICON_SIZE, target=size_menu)
            hint = size_menu.addAction("提示：按住 Ctrl 滚动滚轮可快速缩放")
            hint.setEnabled(False)
            sort_menu = menu.addMenu("排序")
            sort_options = [("name", "按名称"), ("type", "按类型"), ("modified", "按修改时间")]
            if not getattr(self.active_tab(), "portal_path", None):
                sort_options.insert(0, ("manual", "手动排序"))
            for mode, label in sort_options:
                add(label, lambda m=mode: self._set_sort_mode(m), checkable=True,
                    checked=getattr(self.active_tab(), "sort_mode", "name") == mode, target=sort_menu)
            add("降序", self._toggle_sort_direction, checkable=True, checked=self.active_tab().sort_descending,
                target=sort_menu)
        menu.addSeparator()
        if self._grid_locked:
            # In arrangement mode the free resize grip is gone, so the size
            # level submenu becomes the way to change an island's footprint.
            level_menu = menu.addMenu("大小级别")
            current_level = normalise_level(self.state.size_level)
            for level, label in (
                (LEVEL_QUARTER, "小 ¼"),
                (LEVEL_THIRD, "中 ⅓"),
                (LEVEL_HALF, "大 ½"),
                (LEVEL_FULL, "整行"),
            ):
                add(label, lambda lv=level: self.level_requested.emit(self.state.id, lv),
                    checkable=True, checked=current_level == level, target=level_menu)
            add("下一档", lambda: self.level_cycle_requested.emit(self.state.id))
        add("锁定位置" if not self.state.locked else "解除锁定", self._toggle_lock)
        add("窗口置顶", self._toggle_pin, checkable=True, checked=bool(getattr(self.state, "pin_on_top", False)))
        add("清屏时保持显示", self._toggle_exclude, checkable=True,
            checked=bool(getattr(self.state, "exclude_from_hide", False)))
        add("展开" if self.state.collapsed else "收拢", self.toggle_collapsed)
        menu.addSeparator()
        add("删除收纳岛…", lambda: self.delete_requested.emit(self.state.id))
        chosen = menu.exec(global_point)
        if chosen is None:
            return
        handler = handlers.get(chosen)
        if handler is not None:
            handler()

    def _add_zoom_actions(self, zoom_menu, add) -> None:
        current = float(getattr(self.state, "web_zoom", 1.0))
        for factor in (0.5, 0.67, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0):
            add("{0}%".format(round(factor * 100)), lambda f=factor: self._set_web_zoom(f), checkable=True,
                checked=abs(current - factor) < 0.01, target=zoom_menu)

    # Menu handlers ------------------------------------------------------------
    def rename_island(self) -> None:
        name, ok = QInputDialog.getText(None, "重命名收纳岛", "名称", text=self.state.title)
        if ok and name.strip():
            self.state.title = name.strip()
            self.refresh_items()
            self.state_changed.emit()

    def edit_appearance(self) -> None:
        from .dialogs import IslandAppearanceDialog

        original = self._appearance_values()
        dialog = IslandAppearanceDialog(self.state, default_material(), preview=self._preview_appearance)
        if dialog.exec():
            self._preview_appearance(dialog.values())
            self.state_changed.emit()
        else:
            self._preview_appearance(original)

    def _appearance_values(self) -> dict:
        return {
            "title": self.state.title,
            "material": getattr(self.state, "material", ""),
            "color": self.state.color,
            "media_path": getattr(self.state, "media_path", ""),
            "media_opacity": getattr(self.state, "media_opacity", 0.9),
            "media_feather": getattr(self.state, "media_feather", 26),
        }

    def _preview_appearance(self, values: dict) -> None:
        media_changed = values.get("media_path", self.state.media_path) != self.state.media_path
        title = (values.get("title") or "").strip()
        if title:
            self.state.title = title
        self.state.material = values.get("material", self.state.material) or ""
        self.state.color = values.get("color", self.state.color) or self.state.color
        self.state.media_path = values.get("media_path", self.state.media_path) or ""
        self.state.media_opacity = max(0.1, min(1.0, float(values.get("media_opacity", self.state.media_opacity))))
        self.state.media_feather = max(0, min(120, int(values.get("media_feather", self.state.media_feather))))
        if media_changed:
            self._apply_media()
        self._glass_cache.clear()
        self.refresh_items()
        self.update()

    def choose_media(self) -> None:
        start = os.path.dirname(self.state.media_path) if self.state.media_path else ""
        path, _ = QFileDialog.getOpenFileName(None, "选择背景图片或视频", start, MEDIA_FILTER)
        if not path:
            return
        self.state.media_path = import_media_file(path)
        self._apply_media()
        if self.media.error:
            QMessageBox.warning(None, "背景媒体", "无法使用这个文件作为背景：" + self.media.error)
        self.state_changed.emit()

    def clear_media(self) -> None:
        self.state.media_path = ""
        self._apply_media()
        self.state_changed.emit()

    def choose_html_file(self) -> None:
        from .html_view import HTML_FILTER

        start = os.path.dirname(self.state.html_path) if self.state.html_path else ""
        path, _ = QFileDialog.getOpenFileName(None, "选择 HTML 文件", start, HTML_FILTER)
        if path:
            self.state.html_path = path
            self._load_web_content()
            self.state_changed.emit()

    def change_web_url(self) -> None:
        from .html_view import normalize_url

        text, ok = QInputDialog.getText(None, "固定网页", "网址", text=self.state.web_url)
        if ok and text.strip():
            self.state.web_url = normalize_url(text)
            self._load_web_content()
            self.state_changed.emit()

    def _reload_web(self) -> None:
        if self.web is not None:
            self.web.reload()

    def _toggle_html_network(self) -> None:
        self.state.html_allow_network = not self.state.html_allow_network
        self._load_web_content()
        self.state_changed.emit()

    def _toggle_web_toolbar(self) -> None:
        self.state.web_toolbar = not self.state.web_toolbar
        if self.web is not None:
            self.web.set_toolbar_visible(self.state.web_toolbar)
        self.state_changed.emit()

    def _set_web_refresh(self, minutes: int) -> None:
        self.state.web_refresh_minutes = int(minutes)
        if self.web is not None:
            self.web.set_refresh_minutes(minutes)
        self.state_changed.emit()

    def _set_web_zoom(self, factor: float) -> None:
        self.state.web_zoom = float(factor)
        if self.web is not None:
            self.web.set_zoom(factor)
        self.state_changed.emit()

    def choose_portal_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(None, "选择文件夹", getattr(self.active_tab(), "portal_path", "") or "")
        if not folder:
            return
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

    def unbind_portal(self) -> None:
        tab = self.active_tab()
        tab.portal_path = None
        self._portal_current.pop(tab.id, None)
        self.refresh_items()
        self.state_changed.emit()

    def _set_sort_mode(self, mode: str) -> None:
        self.active_tab().sort_mode = mode
        self.refresh_items()
        self.state_changed.emit()

    def _toggle_sort_direction(self) -> None:
        self.active_tab().sort_descending = not self.active_tab().sort_descending
        self.refresh_items()
        self.state_changed.emit()

    def _toggle_lock(self) -> None:
        self.state.locked = not self.state.locked
        self._sync_collapsed_state()
        self.refresh_items()
        self.state_changed.emit()

    def _toggle_pin(self) -> None:
        self.state.pin_on_top = not bool(getattr(self.state, "pin_on_top", False))
        self.refresh_items()
        self.window_level_changed.emit()
        self.state_changed.emit()

    def _toggle_exclude(self) -> None:
        self.state.exclude_from_hide = not bool(getattr(self.state, "exclude_from_hide", False))
        self.state_changed.emit()

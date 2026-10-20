from __future__ import annotations

import json
import os
import subprocess
import sys
import weakref
from pathlib import Path

from collections import OrderedDict

from PySide6.QtCore import (
    QByteArray,
    QFileInfo,
    QMimeData,
    QPoint,
    QProcess,
    QRectF,
    QSize,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import (
    QColor,
    QDesktopServices,
    QDrag,
    QFontMetricsF,
    QIcon,
    QMouseEvent,
    QPainter,
    QPen,
    QTextLayout,
    QTextOption,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileIconProvider,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QStyle,
    QStyledItemDelegate,
)

from . import motion, theme
from .widgets import GlassMenu


MIME_TYPE = "application/x-deskisle-items"


def display_name(path: str, explicit: str = "") -> str:
    if explicit:
        return explicit
    p = Path(path)
    if p.suffix.lower() in {".lnk", ".url"}:
        return p.stem
    return p.name or str(p)


def open_path(path: str) -> bool:
    """Open a path with the Windows shell without invoking a command shell."""
    try:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        return True
    except (OSError, ValueError):
        return False


def reveal_path(path: str) -> bool:
    try:
        if os.name == "nt":
            subprocess.Popen(["explorer.exe", "/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(path).parent)))
        return True
    except OSError:
        return False


def grid_for_icon(icon_size: float) -> QSize:
    size = int(round(icon_size))
    return QSize(max(86, size + 30), size + 52)


class IconDelegate(QStyledItemDelegate):
    """iOS-style cell: soft rounded highlight, crisp icon, two-line label."""

    def __init__(self, view: "ItemListWidget") -> None:
        super().__init__(view)
        self._view = view
        self._lines: "OrderedDict[tuple, list[str]]" = OrderedDict()

    def sizeHint(self, option, index) -> QSize:  # noqa: N802 - Qt API
        grid = self._view.gridSize()
        return QSize(max(40, grid.width() - 4), max(40, grid.height() - 4))

    def _wrap(self, text: str, font, width: float) -> list[str]:
        key = (text, round(width), font.key())
        lines = self._lines.get(key)
        if lines is not None:
            self._lines.move_to_end(key)
            return lines
        metrics = QFontMetricsF(font)
        layout = QTextLayout(text, font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        spans: list[tuple[int, int]] = []
        while len(spans) < 2:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(width)
            spans.append((line.textStart(), line.textLength()))
        layout.endLayout()
        lines = []
        for number, (start, length) in enumerate(spans):
            if number == 1:
                lines.append(metrics.elidedText(text[start:], Qt.TextElideMode.ElideRight, width))
            else:
                lines.append(text[start:start + length].strip())
        if not lines:
            lines = [text]
        self._lines[key] = lines
        while len(self._lines) > 2048:
            self._lines.popitem(last=False)
        return lines

    def paint(self, painter: QPainter, option, index) -> None:
        view = self._view
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        state = option.state
        selected = bool(state & QStyle.StateFlag.State_Selected)
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        if selected:
            fill = QColor(theme.ACCENT)
            fill.setAlpha(70 if view.hasFocus() else 52)
            border = QColor(theme.ACCENT)
            border.setAlpha(150)
            painter.setPen(QPen(border, 1.0))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(255, 255, 255, 24))
            painter.drawRoundedRect(rect, 12, 12)

        size = float(view.iconSize().width())
        icon_rect = QRectF(rect.center().x() - size / 2, rect.top() + 7, size, size)
        available = view.is_available(index)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        scale = view.press_scale(index.row())
        painter.save()
        if scale != 1.0:
            center = icon_rect.center()
            painter.translate(center)
            painter.scale(scale, scale)
            painter.translate(-center)
        if isinstance(icon, QIcon) and not icon.isNull():
            ratio = view.devicePixelRatioF()
            wanted = int(round(size))
            pixmap = icon.pixmap(QSize(wanted, wanted), ratio)
            if not pixmap.isNull():
                if not available:
                    painter.setOpacity(0.42)
                # Pixmaps rastered for another size (during a zoom) are
                # simply scaled; the view re-rasters when the zoom settles.
                painter.drawPixmap(icon_rect, pixmap, QRectF(pixmap.rect()))
                painter.setOpacity(1.0)
        painter.restore()

        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        if text:
            font = option.font
            metrics = QFontMetricsF(font)
            width = rect.width() - 8
            lines = self._wrap(text, font, width)
            top = icon_rect.bottom() + 5
            color = QColor(theme.TEXT if available else theme.TEXT_TERTIARY)
            if selected:
                color = QColor("#FFFFFF")
            line_height = metrics.height()
            for number, line in enumerate(lines):
                line_rect = QRectF(rect.left() + 4, top + number * line_height, width, line_height)
                if line_rect.bottom() > rect.bottom() + 2:
                    break
                if view.text_shadow:
                    painter.setPen(QColor(0, 0, 0, 150))
                    painter.drawText(line_rect.translated(0, 1), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, line)
                painter.setPen(color)
                painter.drawText(line_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, line)
        painter.restore()


class ItemListWidget(QListWidget):
    """Icon grid shared by normal islands and live folder views."""

    files_dropped = Signal(list, str, str)
    remove_requested = Signal(list, str, str)
    reorder_requested = Signal(list, str, str, int)
    activated_path = Signal(str)
    shell_operation_finished = Signal()
    unavailable_remove_requested = Signal(list)
    blank_double_clicked = Signal()
    blank_context_requested = Signal(QPoint)
    zoom_requested = Signal(int)

    def __init__(self, island_id: str, tab_id: str, parent=None) -> None:
        super().__init__(parent)
        self.island_id = island_id
        self.tab_id = tab_id
        self.portal_mode = False
        self.text_shadow = False
        self._blank_press_active = False
        self._icon_provider = QFileIconProvider()
        self._icon_cache: dict[tuple[str, int, int, float], QIcon] = {}
        self._records: list[tuple[str, str]] = []
        self._shell_process = None
        self._missing: set[str] = set()
        self._zoom_target: int | None = None
        self._zoom_tween = motion.Tween(self, self._apply_zoom, 56.0, motion.ZOOM_MS, motion.ios_curve())
        self._press_row = -1
        self._press_scale = 1.0
        self._press_tween = motion.Tween(self, self._set_press_scale, 1.0, motion.PRESS_MS, span=0.1)
        self._wheel_accum = 0
        self._scroll_tween = motion.Tween(self, self._set_scroll, 0.0, 220, motion.ios_curve())
        self._scroll_target = 0.0
        self.setItemDelegate(IconDelegate(self))

        self.setViewMode(QListWidget.ViewMode.IconMode)
        self.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.setMovement(QListWidget.Movement.Snap)
        self.setWrapping(True)
        self.setWordWrap(True)
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setDropIndicatorShown(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemDoubleClicked.connect(self._activate_item)
        self.itemSelectionChanged.connect(self._paint_selection_feedback)
        self.viewport().setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setStyleSheet(
            "QListWidget { background: transparent; border: 0; outline: 0; }"
            "QScrollBar:vertical { width: 7px; background: transparent; margin: 4px 1px 4px 0; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,60); border-radius: 3px; min-height: 28px; }"
            "QScrollBar::handle:vertical:hover { background: rgba(255,255,255,110); }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )

    def configure(self, island_id: str, tab_id: str, icon_size: int, portal_mode: bool) -> None:
        self.island_id = island_id
        self.tab_id = tab_id
        self.portal_mode = portal_mode
        icon_size = int(icon_size)
        if self._zoom_target is not None:
            if icon_size != self._zoom_target:
                self.animate_icon_size(icon_size)
            return
        size_changed = self.iconSize() != QSize(icon_size, icon_size)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setGridSize(grid_for_icon(icon_size))
        self._zoom_tween.value = self._zoom_tween.target = float(icon_size)
        if size_changed:
            self._reraster_icons()

    def _reraster_icons(self) -> None:
        for index in range(self.count()):
            item = self.item(index)
            item.setIcon(self._file_icon(item.data(Qt.ItemDataRole.UserRole)))

    # Smooth icon zoom -------------------------------------------------
    def animate_icon_size(self, size: int) -> None:
        size = int(size)
        current = self.iconSize().width()
        if size == current and self._zoom_target is None:
            return
        if self._zoom_target is None:
            self._zoom_tween.value = float(current)
        self._zoom_target = size
        self._zoom_tween.to(float(size), motion.ZOOM_MS, motion.ios_curve(), on_finished=self._finish_zoom,
                            proportional=False)

    def _apply_zoom(self, value: float) -> None:
        size = max(16, int(round(value)))
        if self.iconSize().width() != size:
            self.setIconSize(QSize(size, size))
            self.setGridSize(grid_for_icon(size))

    def _finish_zoom(self) -> None:
        target = self._zoom_target
        self._zoom_target = None
        if target is None:
            return
        self.setIconSize(QSize(target, target))
        self.setGridSize(grid_for_icon(target))
        self._reraster_icons()
        self.viewport().update()

    def is_zooming(self) -> bool:
        return self._zoom_target is not None

    def set_text_shadow(self, enabled: bool) -> None:
        if self.text_shadow != bool(enabled):
            self.text_shadow = bool(enabled)
            self.viewport().update()

    def is_available(self, index) -> bool:
        return str(index.data(Qt.ItemDataRole.UserRole) or "") not in self._missing

    # Press feedback ---------------------------------------------------
    def press_scale(self, row: int) -> float:
        return self._press_scale if row == self._press_row else 1.0

    def _set_press_scale(self, value: float) -> None:
        self._press_scale = value
        item = self.item(self._press_row) if self._press_row >= 0 else None
        if item is not None:
            self.viewport().update(self.visualItemRect(item).adjusted(-4, -4, 4, 4))

    def _release_press(self) -> None:
        if self._press_row >= 0:
            self._press_tween.to(1.0, motion.RELEASE_MS, motion.spring_curve(1.7), proportional=False)

    # Smooth wheel scrolling -------------------------------------------
    def _set_scroll(self, value: float) -> None:
        self.verticalScrollBar().setValue(int(round(value)))

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self._wheel_accum += event.angleDelta().y()
            while abs(self._wheel_accum) >= 60:
                step = 1 if self._wheel_accum > 0 else -1
                self._wheel_accum -= 120 * step if abs(self._wheel_accum) >= 120 else 60 * step
                self.zoom_requested.emit(step)
            event.accept()
            return
        bar = self.verticalScrollBar()
        if not event.pixelDelta().isNull() or motion.reduce_motion() or bar.maximum() <= 0:
            self._scroll_tween.stop()
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
        if not delta:
            super().wheelEvent(event)
            return
        base = self._scroll_target if self._scroll_tween.is_running() else float(bar.value())
        step = max(40.0, self.gridSize().height() * 0.85)
        target = max(float(bar.minimum()), min(float(bar.maximum()), base - delta / 120.0 * step))
        self._scroll_target = target
        self._scroll_tween.value = float(bar.value())
        self._scroll_tween.to(target, 220, proportional=False)
        event.accept()

    def _file_icon(self, path: str) -> QIcon:
        size = self.iconSize()
        ratio = self.devicePixelRatioF()
        key = (path, size.width(), size.height(), ratio)
        if key not in self._icon_cache:
            # QFileIconProvider returns a lazy shell icon engine. Leaving that
            # engine on every row repeats expensive Shell extraction during
            # painting, scrolling and animation snapshots. Rasterize once.
            source = self._icon_provider.icon(QFileInfo(path))
            self._icon_cache[key] = QIcon(source.pixmap(size, ratio))
            if len(self._icon_cache) > 512:
                self._icon_cache.pop(next(iter(self._icon_cache)))
        return self._icon_cache[key]

    def set_paths(self, records: list[tuple[str, str]]) -> None:
        if records == self._records:
            return
        self._records = list(records)
        scroll = self.verticalScrollBar().value()
        selected = {self.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.count()) if self.item(i).isSelected()}
        old_items = {}
        self.setUpdatesEnabled(False)
        while self.count():
            item = self.takeItem(0)
            old_items[item.data(Qt.ItemDataRole.UserRole)] = item
        for path, title in records:
            item = old_items.pop(path, None)
            if item is None:
                item = QListWidgetItem(self._file_icon(path), '')
            item.setText(display_name(path, title))
            item.setData(Qt.ItemDataRole.UserRole, path)
            item.setToolTip(path)
            item.setTextAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
            if not os.path.exists(path):
                self._missing.add(path)
                item.setForeground(Qt.GlobalColor.gray)
                item.setToolTip(path + "\n位置暂不可用")
            else:
                self._missing.discard(path)
            self.addItem(item)
            item.setSelected(path in selected)
        self.verticalScrollBar().setValue(scroll)
        self.setUpdatesEnabled(True)

    def scrollContentsBy(self, dx: int, dy: int) -> None:  # noqa: N802
        super().scrollContentsBy(dx, dy)
        # Redraw this small viewport after scrolling: copying translucent
        # pixels can otherwise leave rectangles from the previous frame.
        self.viewport().update()

    def selected_paths(self) -> list[str]:
        return [
            str(self.item(index).data(Qt.ItemDataRole.UserRole))
            for index in range(self.count())
            if self.item(index).isSelected()
        ]

    def _paint_selection_feedback(self) -> None:
        # The stylesheet paints selected items. Rewriting every item's model
        # background caused a cascade of full layered-window repaints.
        self.viewport().update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        pressed = self.itemAt(event.position().toPoint())
        if event.button() == Qt.MouseButton.LeftButton and pressed is not None:
            self._press_tween.stop()
            self._press_row = self.row(pressed)
            self._press_tween.value = self._press_scale = 1.0
            self._press_tween.to(0.9, motion.PRESS_MS, motion.ios_curve(), proportional=False)
        if (
            event.button() == Qt.MouseButton.LeftButton
            and pressed is None
        ):
            self.clearSelection()
            self.setCurrentItem(None)
            self._blank_press_active = True
            self._paint_selection_feedback()
            event.accept()
            return
        self._blank_press_active = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._blank_press_active:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._release_press()
        if event.button() == Qt.MouseButton.LeftButton and self._blank_press_active:
            self._blank_press_active = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def startDrag(self, supported_actions: Qt.DropAction) -> None:  # noqa: N802 - Qt API
        self._release_press()
        paths = self.selected_paths()
        if not paths:
            return
        mime = QMimeData()
        payload = {
            "paths": paths,
            "source_island": self.island_id,
            "source_tab": self.tab_id,
            "portal": self.portal_mode,
        }
        mime.setData(MIME_TYPE, QByteArray(json.dumps(payload, ensure_ascii=False).encode("utf-8")))
        drag = QDrag(self)
        drag.setMimeData(mime)
        if self.currentItem() is not None:
            drag.setPixmap(self.currentItem().icon().pixmap(self.iconSize()))
        # This MIME type is private to DeskIsle, so MoveAction only rearranges
        # virtual references and can never move the real filesystem object.
        drag.exec(Qt.DropAction.MoveAction, Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasFormat(MIME_TYPE):
            action = (
                Qt.DropAction.MoveAction
                if event.mimeData().hasFormat(MIME_TYPE)
                else Qt.DropAction.CopyAction
            )
            event.setDropAction(action)
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasFormat(MIME_TYPE):
            action = (
                Qt.DropAction.MoveAction
                if event.mimeData().hasFormat(MIME_TYPE)
                else Qt.DropAction.CopyAction
            )
            event.setDropAction(action)
            event.accept()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # noqa: N802
        paths: list[str] = []
        source_island = ""
        source_tab = ""
        if event.mimeData().hasFormat(MIME_TYPE):
            try:
                payload = json.loads(bytes(event.mimeData().data(MIME_TYPE)).decode("utf-8"))
                paths = [str(p) for p in payload.get("paths", [])]
                source_island = str(payload.get("source_island", ""))
                source_tab = str(payload.get("source_tab", ""))
            except (ValueError, TypeError, UnicodeDecodeError):
                paths = []
        if not paths and event.mimeData().hasUrls():
            paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            if (
                not self.portal_mode
                and source_island == self.island_id
                and source_tab == self.tab_id
            ):
                target_item = self.itemAt(event.position().toPoint())
                target_index = self.row(target_item) if target_item is not None else self.count()
                self.reorder_requested.emit(
                    paths, self.island_id, self.tab_id, target_index
                )
                event.setDropAction(Qt.DropAction.MoveAction)
                event.accept()
                return
            self.files_dropped.emit(paths, source_island, source_tab)
            event.setDropAction(
                Qt.DropAction.MoveAction
                if source_island
                else Qt.DropAction.CopyAction
            )
            event.accept()
            return
        super().dropEvent(event)

    def _activate_item(self, item: QListWidgetItem) -> None:
        path = str(item.data(Qt.ItemDataRole.UserRole))
        self.activated_path.emit(path)

    def _show_context_menu(self, point: QPoint) -> None:
        item = self.itemAt(point)
        if item is not None and not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
        paths = self.selected_paths()
        if not paths:
            self.blank_context_requested.emit(self.viewport().mapToGlobal(point))
            return
        unavailable = [path for path in paths if not os.path.lexists(path)]
        if unavailable:
            menu = GlassMenu(passive=True)
            menu.addAction('所选项目的位置已不可用').setEnabled(False)
            remove = menu.addAction('移除失效引用（不删除文件）')
            if menu.exec(self.viewport().mapToGlobal(point)) == remove:
                self.unavailable_remove_requested.emit(unavailable)
            return
        if os.name == 'nt':
            self._show_windows_menu(paths)
            return
        # Keep the popup independent from the monitor-sized desktop HWND.
        # Wallpaper tools may classify a popup by its Win32 root-owner.
        menu = GlassMenu(passive=True)
        open_action = menu.addAction("打开")
        reveal_action = menu.addAction("在资源管理器中显示")
        copy_path_action = menu.addAction("复制路径")
        remove_action = None
        if not self.portal_mode:
            menu.addSeparator()
            remove_action = menu.addAction("从收纳岛移出（不删除文件）")
        chosen = menu.exec(self.viewport().mapToGlobal(point))
        if chosen == open_action:
            for path in paths:
                if not open_path(path):
                    QMessageBox.warning(None, "无法打开", "无法打开：\n" + path)
        elif chosen == reveal_action:
            reveal_path(paths[0])
        elif chosen == copy_path_action:
            QApplication.clipboard().setText("\n".join(paths))
        elif remove_action is not None and chosen == remove_action:
            self.remove_requested.emit(paths, self.island_id, self.tab_id)

    def _show_windows_menu(self, paths: list[str]) -> None:
        if self._shell_process is not None:
            return
        process = QProcess(QApplication.instance())
        self._shell_process = process
        process.setWorkingDirectory(str(Path(__file__).resolve().parents[1]))
        view_ref = weakref.ref(self)
        island_id, tab_id = self.island_id, self.tab_id

        def finished(*_args):
            from shiboken6 import isValid
            view = view_ref()
            output = bytes(process.readAllStandardOutput())
            try:
                result = json.loads(output.decode('utf-8')) if output else {'error': '无法启动 Windows 右键菜单。'}
            except (ValueError, UnicodeDecodeError):
                result = {'error': 'Windows 右键菜单返回异常。'}
            if view is not None and isValid(view):
                view._shell_process = None
                if result.get('error'):
                    QMessageBox.warning(None, 'Windows 右键菜单', result['error'])
                elif result.get('remove'):
                    view.remove_requested.emit(paths, island_id, tab_id)
                view.shell_operation_finished.emit()
            process.deleteLater()

        process.finished.connect(finished)
        process.errorOccurred.connect(
            lambda error: finished() if error == QProcess.ProcessError.FailedToStart else None
        )
        payload = json.dumps({'paths': paths, 'allow_remove': not self.portal_mode and island_id != '__loose__'},
                             ensure_ascii=False).encode('utf-8')

        def started():
            process.write(payload)
            process.closeWriteChannel()

        process.started.connect(started)
        if getattr(sys, 'frozen', False):
            process.start(str(Path(sys.executable).with_name('DeskIsleShellMenu.exe')), [])
        else:
            process.start(sys.executable, ['-B', '-m', 'deskisle.shell_menu'])

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self.itemAt(event.position().toPoint()) is None:
            self.blank_double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

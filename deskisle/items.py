from __future__ import annotations

import json
import os
import subprocess
import sys
import weakref
from pathlib import Path

from PySide6.QtCore import (
    QByteArray,
    QFileInfo,
    QMimeData,
    QPoint,
    QProcess,
    QSize,
    Qt,
    QUrl,
    Signal,
)
from PySide6.QtGui import QDesktopServices, QDrag, QIcon, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileIconProvider,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
)


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

    def __init__(self, island_id: str, tab_id: str, parent=None) -> None:
        super().__init__(parent)
        self.island_id = island_id
        self.tab_id = tab_id
        self.portal_mode = False
        self._blank_press_active = False
        self._icon_provider = QFileIconProvider()
        self._icon_cache: dict[tuple[str, int, int, float], QIcon] = {}
        self._records: list[tuple[str, str]] = []
        self._shell_process = None

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
        self.setStyleSheet(
            "QListWidget { background: transparent; border: 0; outline: 0; }"
            "QListWidget::item { color: #F4F7FB; border-radius: 8px; padding: 4px; }"
            "QListWidget::item:selected { background: rgba(85,214,190,135); border: 1px solid #67E2CB; }"
            "QListWidget::item:selected:active { background: rgba(85,214,190,165); border: 1px solid #8AF2DF; }"
            "QListWidget::item:hover { background: rgba(255,255,255,38); border: 1px solid rgba(255,255,255,32); }"
            "QListWidget::item:pressed { background: rgba(85,214,190,190); border: 1px solid #A2F8E8; }"
            "QScrollBar:vertical { width: 8px; background: transparent; }"
            "QScrollBar::handle:vertical { background: rgba(255,255,255,70); border-radius: 4px; min-height: 24px; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )

    def configure(self, island_id: str, tab_id: str, icon_size: int, portal_mode: bool) -> None:
        self.island_id = island_id
        self.tab_id = tab_id
        self.portal_mode = portal_mode
        size_changed = self.iconSize() != QSize(icon_size, icon_size)
        self.setIconSize(QSize(icon_size, icon_size))
        self.setGridSize(QSize(max(86, icon_size + 30), icon_size + 52))
        if size_changed:
            for index in range(self.count()):
                item = self.item(index)
                item.setIcon(self._file_icon(item.data(Qt.ItemDataRole.UserRole)))

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
                item.setForeground(Qt.GlobalColor.gray)
                item.setToolTip(path + "\n位置暂不可用")
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
        if (
            event.button() == Qt.MouseButton.LeftButton
            and self.itemAt(event.position().toPoint()) is None
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
        if event.button() == Qt.MouseButton.LeftButton and self._blank_press_active:
            self._blank_press_active = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def startDrag(self, supported_actions: Qt.DropAction) -> None:  # noqa: N802 - Qt API
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
            menu = QMenu()
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
        menu = QMenu()
        menu.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        menu.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
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

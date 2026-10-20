"""Dialogs: new island, appearance, settings, rules, snapshots, updates.

The look follows iOS “grouped” settings: dark rounded cards, switches,
segmented controls and short helper text below each group.
"""

from __future__ import annotations

import copy
import os
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontDatabase, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__, motion, theme
from .models import Preferences, Rule
from .theme import (
    ACCENT,
    APP_NAME,
    SURFACE,
    SURFACE_ALT,
    TEXT,
    TEXT_MUTED,
    TINT_SWATCHES,
    app_stylesheet,
)
from .widgets import SegmentedControl, ToggleSwitch


_DIALOG_STYLESHEET = f"""
QDialog {{
    background: {SURFACE};
}}
QLabel#dialogTitle {{
    color: {TEXT};
    font-size: 17pt;
    font-weight: 700;
}}
QLabel#dialogSubtitle, QLabel#helpText {{
    color: {TEXT_MUTED};
}}
QLabel#helpText {{
    font-size: 8.8pt;
}}
QLabel#sectionTitle {{
    color: {TEXT_MUTED};
    font-size: 8.8pt;
    font-weight: 600;
    padding-left: 14px;
}}
QLabel#rowLabel {{
    color: {TEXT};
}}
QLabel#valueLabel {{
    color: {TEXT_MUTED};
}}
QLabel#errorText {{
    color: #FF6961;
}}
QLabel#pageTitle {{
    color: {TEXT};
    font-size: 14pt;
    font-weight: 700;
}}
QFrame#typeCard, QFrame#summaryCard, QFrame#groupCard {{
    background: {SURFACE_ALT};
    border: 1px solid rgba(255,255,255,14);
    border-radius: 13px;
}}
QFrame#typeCard:hover {{
    background: #323236;
}}
QFrame#typeCard[selected="true"] {{
    background: #26332F;
    border: 1px solid {ACCENT};
}}
QFrame#rowSeparator {{
    background: rgba(255,255,255,20);
    border: 0;
    min-height: 1px;
    max-height: 1px;
}}
QGroupBox {{
    background: {SURFACE_ALT};
    border: 1px solid rgba(255,255,255,14);
    border-radius: 13px;
    margin-top: 16px;
    padding: 14px 12px 10px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    color: {TEXT_MUTED};
}}
QTreeWidget {{
    background: {SURFACE_ALT};
    alternate-background-color: #303034;
    border: 1px solid rgba(255,255,255,14);
    border-radius: 12px;
    outline: 0;
}}
QTreeWidget::item {{
    padding: 7px 5px;
}}
QTreeWidget::item:selected {{
    background: rgba(85,214,190,70);
    color: white;
}}
QHeaderView::section {{
    color: {TEXT_MUTED};
    background: transparent;
    border: 0;
    border-bottom: 1px solid rgba(255,255,255,20);
    padding: 7px;
}}
QListWidget#settingsNav {{
    background: transparent;
    border: 0;
    outline: 0;
    padding: 0;
}}
QListWidget#settingsNav::item {{
    padding: 9px 12px;
    margin: 1px 0;
    border-radius: 9px;
    color: {TEXT};
}}
QListWidget#settingsNav::item:selected {{
    background: rgba(255,255,255,32);
    color: white;
}}
QListWidget#settingsNav::item:hover:!selected {{
    background: rgba(255,255,255,14);
}}
QFrame#navPanel {{
    background: #232325;
    border-right: 1px solid rgba(255,255,255,14);
}}
QProgressBar {{
    background: rgba(255,255,255,28);
    border: 0;
    border-radius: 3px;
    max-height: 6px;
    min-height: 6px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 3px;
}}
QTextBrowser {{
    background: {SURFACE_ALT};
    border: 1px solid rgba(255,255,255,14);
    border-radius: 12px;
    padding: 8px 10px;
}}
QPushButton#linkButton {{
    background: transparent;
    color: {ACCENT};
    padding: 4px 6px;
}}
QScrollArea#pageScroll, QScrollArea#pageScroll > QWidget, QWidget#settingsPage {{
    background: transparent;
}}
QPushButton#linkButton:hover {{
    color: #8CF0DE;
}}
"""


_CONDITION_LABELS = {
    "extension": "扩展名属于",
    "name_contains": "名称包含",
    "name_starts": "名称开头是",
    "name_ends": "名称结尾是",
    "kind": "项目类型是",
}

_KIND_OPTIONS = (
    ("folder", "文件夹"),
    ("shortcut", "快捷方式"),
    ("image", "图片"),
    ("document", "文档"),
    ("media", "音频或视频"),
    ("archive", "压缩包"),
)

MATERIAL_CHOICES = (("clear", "简易透明"), ("frosted", "毛玻璃"), ("liquid", "液体玻璃"))
GRID_MOVE_CHOICES = (("swap", "交换位置"), ("reorder", "依次后移"))
FPS_CHOICES = (15, 24, 30, 60)


def _prepare_dialog(dialog: QDialog, width: int, height: int | None = None) -> None:
    dialog.setStyleSheet(app_stylesheet() + _DIALOG_STYLESHEET)
    dialog.setMinimumWidth(width)
    if height is not None:
        dialog.setMinimumHeight(height)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)


def _fit_to_contents(dialog: QDialog) -> None:
    """Resize *dialog* so word-wrapped labels get their full height.

    Top-level windows ignore height-for-width, so a plain ``adjustSize()``
    leaves wrapped help text (or the rows next to it) slightly squeezed.
    """
    layout = dialog.layout()
    if layout is None:
        return
    layout.activate()
    width = max(dialog.minimumWidth(), layout.totalMinimumSize().width())
    if layout.hasHeightForWidth():
        height = layout.totalHeightForWidth(width)
    else:
        height = layout.totalSizeHint().height()
    height = max(height, dialog.minimumHeight(), layout.totalMinimumSize().height())
    screen = dialog.screen()
    if screen is not None:
        height = min(height, max(320, screen.availableGeometry().height() - 48))
    dialog.resize(width, height)


def _heading(title: str, subtitle: str = "") -> QVBoxLayout:
    layout = QVBoxLayout()
    layout.setSpacing(4)
    title_label = QLabel(title)
    title_label.setObjectName("dialogTitle")
    layout.addWidget(title_label)
    if subtitle:
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("dialogSubtitle")
        subtitle_label.setWordWrap(True)
        layout.addWidget(subtitle_label)
    return layout


def _primary_button(button_box: QDialogButtonBox) -> None:
    button = button_box.button(QDialogButtonBox.StandardButton.Ok)
    if button is not None:
        button.setObjectName("primary")


def _help(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("helpText")
    label.setWordWrap(True)
    return label


def _section(title: str) -> QLabel:
    label = QLabel(title)
    label.setObjectName("sectionTitle")
    label.setContentsMargins(0, 6, 0, 0)
    return label


def _separator() -> QFrame:
    line = QFrame()
    line.setObjectName("rowSeparator")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


def _group(*rows: QWidget, margins: tuple[int, int, int, int] = (14, 6, 14, 6)) -> QFrame:
    """iOS grouped card: rows separated by hairlines."""
    frame = QFrame()
    frame.setObjectName("groupCard")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(*margins)
    layout.setSpacing(0)
    for index, row in enumerate(rows):
        if index:
            layout.addWidget(_separator())
        layout.addWidget(row)
    return frame


def _row(label: str, widget: QWidget | None = None, *, stretch_widget: bool = False) -> QWidget:
    row = QWidget()
    row.setMinimumHeight(42)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 6, 0, 6)
    layout.setSpacing(12)
    text = QLabel(label)
    text.setObjectName("rowLabel")
    layout.addWidget(text)
    if widget is not None:
        if stretch_widget:
            layout.addWidget(widget, 1)
        else:
            layout.addStretch(1)
            layout.addWidget(widget)
    else:
        layout.addStretch(1)
    return row


def _switch_row(switch: ToggleSwitch) -> QWidget:
    row = QWidget()
    row.setMinimumHeight(42)
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 4, 0, 4)
    layout.addWidget(switch)
    return row


def _island_id(island: Any) -> str:
    if isinstance(island, dict):
        return str(island.get("id", ""))
    return str(getattr(island, "id", ""))


def _island_title(island: Any) -> str:
    if isinstance(island, dict):
        return str(island.get("title") or island.get("name") or island.get("id") or "未命名收纳岛")
    return str(
        getattr(island, "title", "")
        or getattr(island, "name", "")
        or getattr(island, "id", "")
        or "未命名收纳岛"
    )


def _record_value(record: Any, key: str, default: Any = "") -> Any:
    if isinstance(record, dict):
        return record.get(key, default)
    return getattr(record, key, default)


def _replace_rule(rule: Rule, **changes: Any) -> Rule:
    """Update rules safely even if the model later becomes a frozen dataclass."""
    try:
        return replace(rule, **changes)
    except TypeError:
        updated = copy.deepcopy(rule)
        for key, value in changes.items():
            setattr(updated, key, value)
        return updated


class _FadeStack(QStackedWidget):
    """Stacked pages that cross-fade in quickly (no effect when idle)."""

    def set_page(self, index: int) -> None:
        if index == self.currentIndex():
            return
        self.setCurrentIndex(index)
        page = self.currentWidget()
        if page is None or motion.reduce_motion():
            return
        effect = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", page)
        animation.setDuration(motion.duration(motion.FADE_MS))
        animation.setStartValue(0.0)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.Type.OutCubic)

        def done(page=page) -> None:
            try:
                page.setGraphicsEffect(None)
            except RuntimeError:
                pass

        animation.finished.connect(done)
        animation.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


class _ChoiceCard(QFrame):
    """A selectable card; clicking anywhere selects its radio button."""

    def __init__(self, title: str, description: str, glyph: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("typeCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(86)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._glyph = glyph
        layout = QVBoxLayout(self)
        layout.setContentsMargins(52, 12, 14, 12)
        layout.setSpacing(4)
        self.radio = QRadioButton(title)
        self.radio.setStyleSheet("QRadioButton { font-size: 10.5pt; font-weight: 600; }")
        self.radio.toggled.connect(self._sync)
        help_label = _help(description)
        layout.addWidget(self.radio)
        layout.addWidget(help_label)
        layout.addStretch(1)
        self._sync(False)

    def _sync(self, checked: bool) -> None:
        self.setProperty("selected", "true" if checked else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.radio.setChecked(True)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        from .widgets import draw_glyph

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        tile = self.rect().adjusted(14, 14, 0, 0)
        tile.setSize(QSize(28, 28))
        color = QColor(ACCENT) if self.radio.isChecked() else QColor(255, 255, 255, 40)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(color)
        painter.drawRoundedRect(tile, 8, 8)
        glyph_color = QColor("#0E1F1C") if self.radio.isChecked() else QColor(245, 245, 247, 220)
        draw_glyph(painter, self._glyph, tile.toRectF().adjusted(6, 6, -6, -6), glyph_color, width=1.7)
        painter.end()


class NewIslandDialog(QDialog):
    """Create a reference island, a folder portal, an HTML animation or a pinned web page."""

    KINDS = ("normal", "portal", "html", "web")

    def __init__(
        self,
        parent: QWidget | None = None,
        force_portal: bool | None = None,
        kind: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建收纳岛")
        _prepare_dialog(self, 600)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)
        root.addLayout(_heading("新建收纳岛", "选择一种内容。普通收纳岛只保存引用，不会移动原文件。"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.type_group = QButtonGroup(self)
        self.normal_card = _ChoiceCard("普通收纳岛", "整理桌面上的文件、文件夹与快捷方式", "grid")
        self.portal_card = _ChoiceCard("文件视窗", "在桌面实时查看一个文件夹的内容", "folder")
        self.html_card = _ChoiceCard("HTML 动画", "打开本地 HTML 文件并持续播放其中的动画", "sparkle")
        self.web_card = _ChoiceCard("固定网页", "把一个网页固定在桌面，可登录、自动刷新", "globe")
        self.normal_radio = self.normal_card.radio
        self.portal_radio = self.portal_card.radio
        self.html_radio = self.html_card.radio
        self.web_radio = self.web_card.radio
        for index, card in enumerate((self.normal_card, self.portal_card, self.html_card, self.web_card)):
            self.type_group.addButton(card.radio, index)
            grid.addWidget(card, index // 2, index % 2)
        root.addLayout(grid)

        form_frame = QFrame()
        form_frame.setObjectName("summaryCard")
        form = QGridLayout(form_frame)
        form.setContentsMargins(16, 14, 16, 14)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)
        form.setColumnStretch(1, 1)

        form.addWidget(QLabel("名称"), 0, 0)
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("例如：进行中、参考资料、截图")
        self.name_edit.setClearButtonEnabled(True)
        form.addWidget(self.name_edit, 0, 1, 1, 2)

        self.folder_label = QLabel("文件夹")
        form.addWidget(self.folder_label, 1, 0)
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("选择要映射到桌面的文件夹")
        self.folder_edit.setClearButtonEnabled(True)
        form.addWidget(self.folder_edit, 1, 1)
        self.browse_button = QPushButton("选择…")
        self.browse_button.clicked.connect(self._choose_folder)
        form.addWidget(self.browse_button, 1, 2)

        self.html_label = QLabel("HTML 文件")
        form.addWidget(self.html_label, 2, 0)
        self.html_edit = QLineEdit()
        self.html_edit.setPlaceholderText("选择 .html / .htm 文件")
        self.html_edit.setClearButtonEnabled(True)
        form.addWidget(self.html_edit, 2, 1)
        self.html_browse_button = QPushButton("选择…")
        self.html_browse_button.clicked.connect(self._choose_html)
        form.addWidget(self.html_browse_button, 2, 2)
        self.html_network_check = QCheckBox("允许页面联网（默认离线，更安全）")
        form.addWidget(self.html_network_check, 3, 1, 1, 2)

        self.url_label = QLabel("网址")
        form.addWidget(self.url_label, 4, 0)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("例如：https://calendar.google.com 或输入关键词搜索")
        self.url_edit.setClearButtonEnabled(True)
        form.addWidget(self.url_edit, 4, 1, 1, 2)
        root.addWidget(form_frame)

        self.kind_hint = _help("")
        root.addWidget(self.kind_hint)

        self.error_label = QLabel()
        self.error_label.setObjectName("errorText")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("创建")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        _primary_button(buttons)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        wanted = kind if kind in self.KINDS else None
        if wanted is None and force_portal is not None:
            wanted = "portal" if force_portal else "normal"
        {"normal": self.normal_radio, "portal": self.portal_radio, "html": self.html_radio,
         "web": self.web_radio}.get(wanted or "normal").setChecked(True)

        self.type_group.idToggled.connect(lambda _id, _checked: self._sync_type())
        self.name_edit.returnPressed.connect(self._validate_and_accept)
        self.url_edit.returnPressed.connect(self._validate_and_accept)
        self._sync_type()
        self.name_edit.setFocus()

    def selected_kind(self) -> str:
        if self.portal_radio.isChecked():
            return "portal"
        if self.html_radio.isChecked():
            return "html"
        if self.web_radio.isChecked():
            return "web"
        return "normal"

    def _sync_type(self) -> None:
        kind = self.selected_kind()
        portal = kind == "portal"
        for widget in (self.folder_label, self.folder_edit, self.browse_button):
            widget.setVisible(portal)
            widget.setEnabled(portal)
        for widget in (self.html_label, self.html_edit, self.html_browse_button, self.html_network_check):
            widget.setVisible(kind == "html")
        for widget in (self.url_label, self.url_edit):
            widget.setVisible(kind == "web")
        hints = {
            "normal": "把文件拖进收纳岛即可整理；原文件保持在原处。",
            "portal": "文件视窗显示真实文件夹，在其中删除或重命名会作用于原文件。",
            "html": "适合放置 CSS / Canvas / WebGL 动画。页面默认离线运行，不会访问网络。",
            "web": "网页在独立的浏览器配置中运行，登录状态会保留；新窗口链接会用系统浏览器打开。",
        }
        self.kind_hint.setText(hints[kind])
        self.error_label.hide()
        _fit_to_contents(self)

    def _choose_folder(self) -> None:
        start = self.folder_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择文件视窗目录", start)
        if not folder:
            return
        self.folder_edit.setText(os.path.normpath(folder))
        if not self.name_edit.text().strip():
            self.name_edit.setText(Path(folder).name or "文件视窗")

    def _choose_html(self) -> None:
        from .html_view import HTML_FILTER

        start = os.path.dirname(self.html_edit.text().strip()) or str(Path.home())
        path, _filter = QFileDialog.getOpenFileName(self, "选择 HTML 文件", start, HTML_FILTER)
        if not path:
            return
        self.html_edit.setText(os.path.normpath(path))
        if not self.name_edit.text().strip():
            self.name_edit.setText(Path(path).stem or "HTML 动画")

    def _validate_and_accept(self) -> None:
        kind = self.selected_kind()
        name = self.name_edit.text().strip()
        if kind == "web" and not name and self.url_edit.text().strip():
            name = QUrl.fromUserInput(self.url_edit.text().strip()).host() or "固定网页"
            self.name_edit.setText(name)
        if kind == "html" and not name and self.html_edit.text().strip():
            name = Path(self.html_edit.text().strip()).stem or "HTML 动画"
            self.name_edit.setText(name)
        if not name:
            self._show_error("请输入收纳岛名称。")
            self.name_edit.setFocus()
            return
        if kind == "portal":
            folder = os.path.expandvars(os.path.expanduser(self.folder_edit.text().strip()))
            if not folder:
                self._show_error("请选择文件视窗要显示的文件夹。")
                self.folder_edit.setFocus()
                return
            if not os.path.isdir(folder):
                self._show_error("所选文件夹不存在或暂时不可访问。")
                self.folder_edit.setFocus()
                return
            self.folder_edit.setText(os.path.normpath(folder))
        elif kind == "html":
            path = os.path.expandvars(os.path.expanduser(self.html_edit.text().strip()))
            if not path or not os.path.isfile(path):
                self._show_error("请选择一个存在的 HTML 文件。")
                self.html_edit.setFocus()
                return
            self.html_edit.setText(os.path.normpath(path))
        elif kind == "web":
            from .html_view import normalize_url

            url = normalize_url(self.url_edit.text())
            if not url:
                self._show_error("请输入要固定的网址。")
                self.url_edit.setFocus()
                return
            self.url_edit.setText(url)
        self.error_label.hide()
        self.accept()

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def data(self) -> dict[str, Any]:
        kind = self.selected_kind()
        portal = kind == "portal"
        path = self.folder_edit.text().strip() if portal else ""
        title = self.name_edit.text().strip()
        island_kind = {"html": "html", "web": "web"}.get(kind, "files")
        return {
            "kind": kind,
            "type": kind,
            "island_kind": island_kind,
            "title": title,
            "name": title,
            "folder": path,
            "folder_path": path,
            "portal_path": path or None,
            "path": path,
            "is_portal": portal,
            "html_path": self.html_edit.text().strip() if kind == "html" else "",
            "html_allow_network": bool(self.html_network_check.isChecked()) if kind == "html" else False,
            "web_url": self.url_edit.text().strip() if kind == "web" else "",
        }

    @staticmethod
    def get_data(
        parent: QWidget | None = None,
        force_portal: bool | None = None,
        kind: str | None = None,
    ) -> dict[str, Any] | None:
        dialog = NewIslandDialog(parent, force_portal, kind)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.data()
        return None


class RenameDialog(QDialog):
    def __init__(self, current_name: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("重命名")
        _prepare_dialog(self, 420)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)
        root.addLayout(_heading("重命名", "输入一个简洁、容易辨认的名称。"))
        self.name_edit = QLineEdit(current_name)
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.selectAll()
        root.addWidget(self.name_edit)
        self.error_label = QLabel("名称不能为空。")
        self.error_label.setObjectName("errorText")
        self.error_label.hide()
        root.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        _primary_button(buttons)
        buttons.accepted.connect(self._accept_name)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.name_edit.returnPressed.connect(self._accept_name)
        self.name_edit.setFocus()

    def _accept_name(self) -> None:
        if not self.name_edit.text().strip():
            self.error_label.show()
            return
        self.accept()

    @staticmethod
    def get_name(current_name: str = "", parent: QWidget | None = None) -> str | None:
        dialog = RenameDialog(current_name, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.name_edit.text().strip()
        return None


class TabDialog(QDialog):
    """Collect the model-neutral data needed to create or edit a tab."""

    def __init__(self, existing: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建标签")
        _prepare_dialog(self, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 18)
        root.setSpacing(14)
        root.addLayout(_heading("标签设置", "普通标签保存文件引用；文件夹标签显示目录中的实时内容。"))

        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.setVerticalSpacing(12)
        self.title_edit = QLineEdit(str(_record_value(existing, "title", _record_value(existing, "name", ""))))
        self.title_edit.setPlaceholderText("例如：本周、素材、已完成")
        self.title_edit.setClearButtonEnabled(True)
        form.addRow("标签名称", self.title_edit)

        existing_path = str(
            _record_value(
                existing,
                "portal_path",
                _record_value(existing, "folder_path", _record_value(existing, "path", "")),
            )
            or ""
        )
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("普通标签", "normal")
        self.kind_combo.addItem("文件夹标签", "portal")
        existing_kind = str(
            _record_value(
                existing,
                "kind",
                _record_value(existing, "type", "portal" if existing_path else "normal"),
            )
        )
        self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(existing_kind)))
        form.addRow("内容来源", self.kind_combo)

        path_row = QWidget()
        path_layout = QHBoxLayout(path_row)
        path_layout.setContentsMargins(0, 0, 0, 0)
        path_layout.setSpacing(8)
        self.folder_edit = QLineEdit(existing_path)
        self.folder_edit.setPlaceholderText("选择文件夹")
        self.folder_edit.setClearButtonEnabled(True)
        self.browse_button = QPushButton("选择…")
        self.browse_button.clicked.connect(self._choose_folder)
        path_layout.addWidget(self.folder_edit, 1)
        path_layout.addWidget(self.browse_button)
        form.addRow("文件夹", path_row)
        root.addLayout(form)

        self.error_label = QLabel()
        self.error_label.setObjectName("errorText")
        self.error_label.hide()
        root.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        _primary_button(buttons)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.kind_combo.currentIndexChanged.connect(self._sync_kind)
        self.title_edit.returnPressed.connect(self._validate_and_accept)
        self._sync_kind()
        self.title_edit.setFocus()

    def _sync_kind(self) -> None:
        portal = self.kind_combo.currentData() == "portal"
        self.folder_edit.setEnabled(portal)
        self.browse_button.setEnabled(portal)

    def _choose_folder(self) -> None:
        start = self.folder_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择文件夹", start)
        if folder:
            self.folder_edit.setText(os.path.normpath(folder))
            if not self.title_edit.text().strip():
                self.title_edit.setText(Path(folder).name or "文件夹")

    def _validate_and_accept(self) -> None:
        if not self.title_edit.text().strip():
            self.error_label.setText("请输入标签名称。")
            self.error_label.show()
            self.title_edit.setFocus()
            return
        if self.kind_combo.currentData() == "portal":
            folder = os.path.expandvars(os.path.expanduser(self.folder_edit.text().strip()))
            if not os.path.isdir(folder):
                self.error_label.setText("请选择一个可访问的文件夹。")
                self.error_label.show()
                self.folder_edit.setFocus()
                return
            self.folder_edit.setText(os.path.normpath(folder))
        self.error_label.hide()
        self.accept()

    def data(self) -> dict[str, Any]:
        kind = str(self.kind_combo.currentData())
        path = self.folder_edit.text().strip() if kind == "portal" else ""
        title = self.title_edit.text().strip()
        return {
            "title": title,
            "name": title,
            "kind": kind,
            "type": kind,
            "folder_path": path,
            "portal_path": path or None,
            "path": path,
            "is_portal": kind == "portal",
        }

    @staticmethod
    def get_data(
        parent: QWidget | None = None,
        existing: Any = None,
    ) -> dict[str, Any] | None:
        dialog = TabDialog(existing, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.data()
        return None


class RuleEditDialog(QDialog):
    def __init__(
        self,
        existing: Rule | None,
        islands: Iterable[Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._existing = existing
        self._result: Rule | None = None
        self._islands = list(islands)
        self.setWindowTitle("编辑归流规则" if existing else "新建归流规则")
        _prepare_dialog(self, 580)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)
        root.addLayout(
            _heading(
                "编辑归流规则" if existing else "新建归流规则",
                "规则按优先级从上到下匹配。这里只改变项目归属，不移动原文件。",
            )
        )

        form = QFormLayout()
        form.setHorizontalSpacing(16)
        form.setVerticalSpacing(12)

        self.name_edit = QLineEdit(existing.name if existing else "")
        self.name_edit.setPlaceholderText("例如：自动收纳截图")
        self.name_edit.setClearButtonEnabled(True)
        form.addRow("规则名称", self.name_edit)

        self.condition_combo = QComboBox()
        for value, label in _CONDITION_LABELS.items():
            self.condition_combo.addItem(label, value)
        form.addRow("匹配条件", self.condition_combo)

        self.value_stack = QStackedWidget()
        self.value_edit = QLineEdit()
        self.value_edit.setClearButtonEnabled(True)
        self.value_stack.addWidget(self.value_edit)
        self.kind_combo = QComboBox()
        self.kind_combo.setEditable(True)
        for value, label in _KIND_OPTIONS:
            self.kind_combo.addItem(label, value)
        self.value_stack.addWidget(self.kind_combo)
        form.addRow("匹配内容", self.value_stack)

        self.target_combo = QComboBox()
        for island in self._islands:
            island_id = _island_id(island)
            if island_id:
                self.target_combo.addItem(_island_title(island), island_id)
        form.addRow("放入", self.target_combo)

        self.enabled_check = QCheckBox("启用此规则")
        self.enabled_check.setChecked(existing.enabled if existing else True)
        form.addRow("", self.enabled_check)
        root.addLayout(form)

        note = QLabel("多个值可用逗号分隔，例如扩展名可填写：.png, .jpg, .webp")
        note.setObjectName("helpText")
        note.setWordWrap(True)
        root.addWidget(note)
        self.error_label = QLabel()
        self.error_label.setObjectName("errorText")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        root.addWidget(self.error_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存规则")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        _primary_button(buttons)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.condition_combo.currentIndexChanged.connect(self._sync_condition)
        if existing:
            index = self.condition_combo.findData(existing.condition)
            if index >= 0:
                self.condition_combo.setCurrentIndex(index)
            target_index = self.target_combo.findData(existing.target_island_id)
            if target_index < 0 and existing.target_island_id:
                self.target_combo.addItem("原目标（当前不可用）", existing.target_island_id)
                target_index = self.target_combo.count() - 1
            if target_index >= 0:
                self.target_combo.setCurrentIndex(target_index)
        self._sync_condition()
        if existing:
            if existing.condition == "kind":
                kind_index = self.kind_combo.findData(existing.value)
                if kind_index >= 0:
                    self.kind_combo.setCurrentIndex(kind_index)
                else:
                    self.kind_combo.setEditText(existing.value)
            else:
                self.value_edit.setText(existing.value)
        self.name_edit.setFocus()

    def _sync_condition(self) -> None:
        condition = str(self.condition_combo.currentData())
        is_kind = condition == "kind"
        self.value_stack.setCurrentIndex(1 if is_kind else 0)
        placeholders = {
            "extension": ".png, .jpg",
            "name_contains": "名称中要包含的文字",
            "name_starts": "名称开头的文字",
            "name_ends": "名称结尾的文字",
        }
        self.value_edit.setPlaceholderText(placeholders.get(condition, "匹配值"))

    def _current_value(self) -> str:
        if self.condition_combo.currentData() == "kind":
            index = self.kind_combo.currentIndex()
            if index >= 0 and self.kind_combo.currentText() == self.kind_combo.itemText(index):
                data = self.kind_combo.itemData(index)
                if data is not None:
                    return str(data).strip()
            return self.kind_combo.currentText().strip()
        return self.value_edit.text().strip()

    def _validate_and_accept(self) -> None:
        name = self.name_edit.text().strip()
        value = self._current_value()
        target = self.target_combo.currentData()
        if not name:
            self._show_error("请输入规则名称。")
            self.name_edit.setFocus()
            return
        if not value:
            self._show_error("请输入或选择匹配内容。")
            return
        if not target:
            self._show_error("至少需要一个可作为目标的收纳岛。")
            return

        values = {
            "name": name,
            "condition": str(self.condition_combo.currentData()),
            "value": value,
            "target_island_id": str(target),
            "enabled": self.enabled_check.isChecked(),
        }
        if self._existing is None:
            self._result = Rule(id=uuid.uuid4().hex, priority=100, **values)
        else:
            self._result = _replace_rule(self._existing, **values)
        self.error_label.hide()
        self.accept()

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    @staticmethod
    def get_rule(
        existing: Rule | None,
        islands: Iterable[Any],
        parent: QWidget | None = None,
    ) -> Rule | None:
        dialog = RuleEditDialog(existing, islands, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog._result
        return None


class RulesDialog(QDialog):
    apply_requested = Signal()

    def __init__(
        self,
        rules: Iterable[Rule],
        islands: Iterable[Any],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        indexed_rules = list(enumerate(copy.deepcopy(list(rules))))
        indexed_rules.sort(key=lambda pair: (pair[1].priority, pair[0]))
        self.rules: list[Rule] = [rule for _, rule in indexed_rules]
        self.islands = list(islands)
        self._island_names = {_island_id(i): _island_title(i) for i in self.islands}
        self._refreshing = False

        self.setWindowTitle("归流规则")
        _prepare_dialog(self, 830, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)
        root.addLayout(_heading("归流规则", "启用的规则按优先级从上到下匹配；优先命中的规则生效。"))

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["启用", "规则", "条件", "目标", "优先级"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tree.setColumnWidth(0, 62)
        self.tree.setColumnWidth(1, 190)
        self.tree.setColumnWidth(2, 245)
        self.tree.setColumnWidth(3, 150)
        self.tree.itemDoubleClicked.connect(lambda *_: self._edit_rule())
        self.tree.itemChanged.connect(self._enabled_changed)
        root.addWidget(self.tree, 1)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(8)
        self.add_button = QPushButton("＋ 新建")
        self.edit_button = QPushButton("编辑")
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("danger")
        self.up_button = QPushButton("上移")
        self.down_button = QPushButton("下移")
        for button in (self.add_button, self.edit_button, self.delete_button, self.up_button, self.down_button):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.apply_button = QPushButton("立即应用规则")
        self.apply_button.setObjectName("primary")
        toolbar.addWidget(self.apply_button)
        root.addLayout(toolbar)

        hint = QLabel("“立即应用”只发出请求；具体文件扫描与归类由主程序执行。")
        hint.setObjectName("helpText")
        root.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("完成")
        buttons.rejected.connect(self.accept)
        root.addWidget(buttons)

        self.add_button.clicked.connect(self._add_rule)
        self.edit_button.clicked.connect(self._edit_rule)
        self.delete_button.clicked.connect(self._delete_rule)
        self.up_button.clicked.connect(lambda: self._move_rule(-1))
        self.down_button.clicked.connect(lambda: self._move_rule(1))
        self.apply_button.clicked.connect(self._request_apply)
        self.tree.itemSelectionChanged.connect(self._update_buttons)
        self._refresh()

    def _selected_index(self) -> int:
        items = self.tree.selectedItems()
        if not items:
            return -1
        return int(items[0].data(0, Qt.ItemDataRole.UserRole))

    def _condition_text(self, rule: Rule) -> str:
        label = _CONDITION_LABELS.get(rule.condition, rule.condition)
        value = rule.value
        if rule.condition == "kind":
            value = dict(_KIND_OPTIONS).get(rule.value, rule.value)
        return f"{label}  {value}"

    def _refresh(self, selected_index: int | None = None) -> None:
        if selected_index is None:
            selected_index = self._selected_index()
        self._refreshing = True
        self.tree.clear()
        for index, rule in enumerate(self.rules):
            target = self._island_names.get(rule.target_island_id, "目标不可用")
            item = QTreeWidgetItem(
                ["", rule.name, self._condition_text(rule), target, str(rule.priority)]
            )
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if rule.enabled else Qt.CheckState.Unchecked)
            if rule.target_island_id not in self._island_names:
                item.setToolTip(3, f"找不到目标收纳岛：{rule.target_island_id}")
            self.tree.addTopLevelItem(item)
            if index == selected_index:
                self.tree.setCurrentItem(item)
        self._refreshing = False
        self._update_buttons()

    def _enabled_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if self._refreshing or column != 0:
            return
        index = int(item.data(0, Qt.ItemDataRole.UserRole))
        if 0 <= index < len(self.rules):
            enabled = item.checkState(0) == Qt.CheckState.Checked
            self.rules[index] = _replace_rule(self.rules[index], enabled=enabled)

    def _update_buttons(self) -> None:
        index = self._selected_index()
        valid = 0 <= index < len(self.rules)
        self.edit_button.setEnabled(valid)
        self.delete_button.setEnabled(valid)
        self.up_button.setEnabled(valid and index > 0)
        self.down_button.setEnabled(valid and index < len(self.rules) - 1)

    def _add_rule(self) -> None:
        rule = RuleEditDialog.get_rule(None, self.islands, self)
        if rule is None:
            return
        priority = (max((item.priority for item in self.rules), default=0) // 100 + 1) * 100
        self.rules.append(_replace_rule(rule, priority=priority))
        self._refresh(len(self.rules) - 1)

    def _edit_rule(self) -> None:
        index = self._selected_index()
        if not 0 <= index < len(self.rules):
            return
        rule = RuleEditDialog.get_rule(self.rules[index], self.islands, self)
        if rule is not None:
            self.rules[index] = rule
            self._refresh(index)

    def _delete_rule(self) -> None:
        index = self._selected_index()
        if not 0 <= index < len(self.rules):
            return
        answer = QMessageBox.question(
            self,
            "删除规则",
            f"确定删除“{self.rules[index].name}”吗？\n这不会删除或移动任何文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.rules.pop(index)
        self._normalize_priorities()
        self._refresh(min(index, len(self.rules) - 1))

    def _move_rule(self, direction: int) -> None:
        index = self._selected_index()
        target = index + direction
        if not (0 <= index < len(self.rules) and 0 <= target < len(self.rules)):
            return
        self.rules[index], self.rules[target] = self.rules[target], self.rules[index]
        self._normalize_priorities()
        self._refresh(target)

    def _normalize_priorities(self) -> None:
        self.rules = [
            _replace_rule(rule, priority=(index + 1) * 100)
            for index, rule in enumerate(self.rules)
        ]

    def _request_apply(self) -> None:
        self._normalize_priorities()
        self._refresh(self._selected_index())
        self.apply_requested.emit()




class _Swatch(QAbstractButton):
    """Round colour chip used for island tints."""

    def __init__(self, color: str, parent: QWidget | None = None, *, custom: bool = False) -> None:
        super().__init__(parent)
        self.color = color
        self.custom = custom
        self.setCheckable(True)
        self.setFixedSize(32, 32)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("自定义颜色…" if custom else color)
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)

    def set_color(self, color: str) -> None:
        self.color = color
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtCore import QRectF

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        chip = QRectF(self.rect()).adjusted(5, 5, -5, -5)
        if self.custom and not self.isChecked():
            pen = QPen(QColor(255, 255, 255, 120), 1.4, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(chip)
            painter.setPen(QPen(QColor(255, 255, 255, 200), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            center = chip.center()
            painter.drawLine(center.x() - 4, center.y(), center.x() + 4, center.y())
            painter.drawLine(center.x(), center.y() - 4, center.x(), center.y() + 4)
        else:
            painter.setPen(QPen(QColor(255, 255, 255, 46), 1))
            painter.setBrush(QColor(self.color))
            painter.drawEllipse(chip)
        if self.isChecked():
            painter.setPen(QPen(QColor(ACCENT), 2.0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5))
        painter.end()


class IslandAppearanceDialog(QDialog):
    """Name, glass material, tint and background media of one island.

    Every change is previewed live through *preview*; the caller restores the
    original values when the dialog is cancelled.
    """

    MATERIAL_VALUES = ("", "clear", "frosted", "liquid")

    def __init__(self, state: Any, default_material: str = "frosted", preview: Callable[[dict], None] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._preview = preview
        self._media_path = str(_record_value(state, "media_path", "") or "")
        self._color = str(_record_value(state, "color", TINT_SWATCHES[0]) or TINT_SWATCHES[0])
        self.setWindowTitle("外观与名称")
        _prepare_dialog(self, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 18)
        root.setSpacing(8)
        root.addLayout(_heading("外观与名称", "修改会立即预览；点“完成”保存，点“取消”还原。"))

        self.name_edit = QLineEdit(str(_record_value(state, "title", "")))
        self.name_edit.setPlaceholderText("收纳岛名称")
        self.name_edit.setClearButtonEnabled(True)
        self.name_edit.setMaxLength(60)
        root.addWidget(_section("名称"))
        root.addWidget(_group(self.name_edit, margins=(10, 10, 10, 10)))

        global_label = dict(MATERIAL_CHOICES).get(default_material, "毛玻璃")
        self.material_control = SegmentedControl(["跟随全局", "简易透明", "毛玻璃", "液体玻璃"])
        current_material = str(_record_value(state, "material", "") or "")
        self.material_control.setCurrentIndex(
            self.MATERIAL_VALUES.index(current_material) if current_material in self.MATERIAL_VALUES else 0,
            animate=False)
        root.addWidget(_section("背景质感"))
        root.addWidget(_group(self.material_control, margins=(10, 10, 10, 10)))
        root.addWidget(_help("“跟随全局”当前为{0}。简易透明最省资源，液体玻璃更通透并带折射高光。".format(global_label)))

        swatch_row = QWidget()
        swatch_layout = QHBoxLayout(swatch_row)
        swatch_layout.setContentsMargins(0, 4, 0, 4)
        swatch_layout.setSpacing(2)
        self.swatch_group = QButtonGroup(self)
        self.swatch_group.setExclusive(True)
        self.swatches: list[_Swatch] = []
        for color in TINT_SWATCHES:
            swatch = _Swatch(color)
            swatch.clicked.connect(lambda _checked=False, c=color: self._pick_color(c))
            self.swatch_group.addButton(swatch)
            self.swatches.append(swatch)
            swatch_layout.addWidget(swatch)
        self.custom_swatch = _Swatch(self._color, custom=True)
        self.custom_swatch.clicked.connect(self._choose_custom_color)
        self.swatch_group.addButton(self.custom_swatch)
        swatch_layout.addWidget(self.custom_swatch)
        swatch_layout.addStretch(1)
        root.addWidget(_section("色调"))
        root.addWidget(_group(swatch_row))

        media_row = QWidget()
        media_layout = QHBoxLayout(media_row)
        media_layout.setContentsMargins(0, 6, 0, 6)
        media_layout.setSpacing(8)
        self.media_label = QLabel()
        self.media_label.setObjectName("valueLabel")
        self.media_label.setMinimumWidth(160)
        self.media_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.media_button = QPushButton("选择图片或视频…")
        self.clear_media_button = QPushButton("移除")
        self.clear_media_button.setObjectName("danger")
        media_layout.addWidget(self.media_label, 1)
        media_layout.addWidget(self.media_button)
        media_layout.addWidget(self.clear_media_button)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(round(float(_record_value(state, "media_opacity", 0.9) or 0.9) * 100))
        self.opacity_value = QLabel()
        self.opacity_value.setObjectName("valueLabel")
        self.opacity_value.setMinimumWidth(44)
        self.feather_slider = QSlider(Qt.Orientation.Horizontal)
        self.feather_slider.setRange(0, 100)
        self.feather_slider.setValue(int(_record_value(state, "media_feather", 26) or 0))
        self.feather_value = QLabel()
        self.feather_value.setObjectName("valueLabel")
        self.feather_value.setMinimumWidth(44)
        opacity_row = self._slider_row("融合度", self.opacity_slider, self.opacity_value)
        feather_row = self._slider_row("边缘虚化", self.feather_slider, self.feather_value)
        root.addWidget(_section("背景媒体"))
        root.addWidget(_group(media_row, opacity_row, feather_row))
        root.addWidget(_help("支持图片（PNG / JPG / GIF / WebP）和视频（MP4 / WebM 等，静音循环）。"
                             "媒体位于玻璃之上、图标之下，边缘向内虚化融入背景，收拢后也会显示。"))

        root.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("完成")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        _primary_button(buttons)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.error_label = QLabel()
        self.error_label.setObjectName("errorText")
        self.error_label.hide()
        root.addWidget(self.error_label)

        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(40)
        self._preview_timer.timeout.connect(self._emit_preview)

        self.name_edit.textChanged.connect(self._schedule_preview)
        self.material_control.currentChanged.connect(self._schedule_preview)
        self.opacity_slider.valueChanged.connect(self._sync_labels)
        self.feather_slider.valueChanged.connect(self._sync_labels)
        self.opacity_slider.valueChanged.connect(self._schedule_preview)
        self.feather_slider.valueChanged.connect(self._schedule_preview)
        self.media_button.clicked.connect(self._choose_media)
        self.clear_media_button.clicked.connect(self._clear_media)
        self._select_swatch(self._color)
        self._sync_labels()
        self._sync_media()
        self.name_edit.setFocus()
        self.name_edit.selectAll()
        _fit_to_contents(self)

    @staticmethod
    def _slider_row(label: str, slider: QSlider, value: QLabel) -> QWidget:
        row = QWidget()
        row.setMinimumHeight(42)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 6, 0, 6)
        layout.setSpacing(12)
        text = QLabel(label)
        text.setObjectName("rowLabel")
        text.setMinimumWidth(64)
        layout.addWidget(text)
        layout.addWidget(slider, 1)
        layout.addWidget(value)
        return row

    def _sync_labels(self) -> None:
        self.opacity_value.setText("{0}%".format(self.opacity_slider.value()))
        self.feather_value.setText("{0} px".format(self.feather_slider.value()))

    def _sync_media(self) -> None:
        has_media = bool(self._media_path)
        if has_media:
            name = Path(self._media_path).name
            metrics = self.media_label.fontMetrics()
            self.media_label.setText(metrics.elidedText(name, Qt.TextElideMode.ElideMiddle, 220))
            self.media_label.setToolTip(self._media_path)
        else:
            self.media_label.setText("未设置")
            self.media_label.setToolTip("")
        self.clear_media_button.setEnabled(has_media)
        self.opacity_slider.setEnabled(has_media)
        self.feather_slider.setEnabled(has_media)

    def _select_swatch(self, color: str) -> None:
        self._color = color
        for swatch in self.swatches:
            if swatch.color.lower() == color.lower():
                swatch.setChecked(True)
                return
        self.custom_swatch.set_color(color)
        self.custom_swatch.setChecked(True)

    def _pick_color(self, color: str) -> None:
        self._select_swatch(color)
        self._schedule_preview()

    def _choose_custom_color(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self, "自定义色调")
        if chosen.isValid():
            self._select_swatch(chosen.name().upper())
            self._schedule_preview()
        else:
            self._select_swatch(self._color)

    def _choose_media(self) -> None:
        from .media import MEDIA_FILTER, import_media_file

        start = os.path.dirname(self._media_path) if self._media_path else str(Path.home())
        path, _filter = QFileDialog.getOpenFileName(self, "选择背景图片或视频", start, MEDIA_FILTER)
        if not path:
            return
        self._media_path = import_media_file(path)
        self._sync_media()
        self._schedule_preview()

    def _clear_media(self) -> None:
        self._media_path = ""
        self._sync_media()
        self._schedule_preview()

    def _schedule_preview(self, *_args) -> None:
        if self._preview is not None:
            self._preview_timer.start()

    def _emit_preview(self) -> None:
        if self._preview is not None:
            self._preview(self.values())

    def _validate_and_accept(self) -> None:
        if not self.name_edit.text().strip():
            self.error_label.setText("名称不能为空。")
            self.error_label.show()
            self.name_edit.setFocus()
            return
        self._preview_timer.stop()
        self.accept()

    def values(self) -> dict[str, Any]:
        return {
            "title": self.name_edit.text().strip(),
            "material": self.MATERIAL_VALUES[self.material_control.currentIndex()],
            "color": self._color,
            "media_path": self._media_path,
            "media_opacity": self.opacity_slider.value() / 100.0,
            "media_feather": self.feather_slider.value(),
        }


class SettingsDialog(QDialog):
    """Grouped settings with a sidebar: 通用 / 外观 / 动态与性能 / 更新."""

    check_updates_requested = Signal()
    PAGES = ("通用", "外观", "动态与性能", "更新")

    def __init__(self, preferences: Preferences, parent: QWidget | None = None, *,
                 font_importer: Callable[[str], str] | None = None, update_status: str = "",
                 initial_page: int = 0) -> None:
        super().__init__(parent)
        self.preferences = copy.deepcopy(preferences)
        self._opacity_was_float = isinstance(preferences.panel_opacity, float)
        self._font_importer = font_importer
        self._font_file = str(getattr(preferences, "font_file", "") or "")
        self._font_file_family = theme.load_font_file(self._font_file) or "" if self._font_file else ""
        self._backdrop_image = str(getattr(preferences, "backdrop_image", "") or "")
        self.setWindowTitle("桌屿设置")
        _prepare_dialog(self, 760, 560)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        nav_panel = QFrame()
        nav_panel.setObjectName("navPanel")
        nav_panel.setFixedWidth(186)
        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(12, 20, 12, 16)
        nav_layout.setSpacing(10)
        nav_title = QLabel("设置")
        nav_title.setObjectName("dialogTitle")
        nav_layout.addWidget(nav_title)
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.addItems(list(self.PAGES))
        self.nav.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        nav_layout.addWidget(self.nav, 1)
        version = QLabel("{0}\n版本 {1}".format(APP_NAME, __version__))
        version.setObjectName("helpText")
        nav_layout.addWidget(version)
        outer.addWidget(nav_panel)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 22, 24, 18)
        content_layout.setSpacing(12)
        self.stack = _FadeStack()
        self.stack.addWidget(self._general_page(preferences))
        self.stack.addWidget(self._appearance_page(preferences))
        self.stack.addWidget(self._motion_page(preferences))
        self.stack.addWidget(self._update_page(preferences, update_status))
        content_layout.addWidget(self.stack, 1)

        button_row = QHBoxLayout()
        self.defaults_button = QPushButton("恢复默认")
        button_row.addWidget(self.defaults_button)
        button_row.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        _primary_button(buttons)
        button_row.addWidget(buttons)
        content_layout.addLayout(button_row)
        outer.addWidget(content, 1)

        self.nav.currentRowChanged.connect(self.stack.set_page)
        self.nav.setCurrentRow(max(0, min(len(self.PAGES) - 1, int(initial_page))))
        self.snap_check.toggled.connect(self.grid_spin.setEnabled)
        self.auto_layout_check.toggled.connect(self.move_mode_control.setEnabled)
        self.edge_switch_check.toggled.connect(self.edge_width_spin.setEnabled)
        self.edge_switch_check.toggled.connect(self.edge_delay_spin.setEnabled)
        self.opacity_slider.valueChanged.connect(self._update_opacity_label)
        self.font_combo.currentIndexChanged.connect(self._update_font_preview)
        self.font_size_spin.valueChanged.connect(self._update_font_preview)
        self.backdrop_control.currentChanged.connect(self._sync_backdrop)
        self.defaults_button.clicked.connect(self._restore_defaults)
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        self.grid_spin.setEnabled(self.snap_check.isChecked())
        self._update_opacity_label()
        self._update_font_preview()
        self._sync_backdrop()

    # Pages ----------------------------------------------------------------
    @staticmethod
    def _page(title: str) -> tuple[QWidget, QVBoxLayout]:
        """A scrollable settings page (content never gets squeezed)."""
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page = QWidget()
        page.setObjectName("settingsPage")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)
        heading = QLabel(title)
        heading.setObjectName("pageTitle")
        layout.addWidget(heading)
        layout.addSpacing(4)
        scroll.setWidget(page)
        return scroll, layout

    def _general_page(self, preferences: Preferences) -> QWidget:
        page, layout = self._page("通用")
        self.hide_native_check = ToggleSwitch("隐藏 Windows 原生桌面图标，由桌屿统一显示")
        self.hide_native_check.setChecked(bool(preferences.hide_native_icons))
        self.startup_check = ToggleSwitch("登录 Windows 后自动启动桌屿")
        self.startup_check.setChecked(bool(preferences.start_with_windows))
        layout.addWidget(_section("桌面"))
        layout.addWidget(_group(_switch_row(self.hide_native_check), _switch_row(self.startup_check)))
        layout.addWidget(_help("关闭桌屿或退出应用时，原生桌面图标会恢复显示。"))

        self.snap_check = ToggleSwitch("移动和缩放时吸附到网格")
        self.snap_check.setChecked(bool(preferences.snap_to_grid))
        self.grid_spin = QSpinBox()
        self.grid_spin.setRange(4, 64)
        self.grid_spin.setSingleStep(2)
        self.grid_spin.setSuffix(" px")
        self.grid_spin.setValue(int(preferences.grid_size))
        self.grid_spin.setFixedWidth(110)
        self.auto_check = ToggleSwitch("持续监听并自动应用已启用的归流规则")
        self.auto_check.setChecked(bool(preferences.auto_organize))
        layout.addWidget(_section("布局与自动整理"))
        layout.addWidget(_group(_switch_row(self.snap_check), _row("网格尺寸", self.grid_spin),
                                _switch_row(self.auto_check)))

        # Automatic arrangement mode
        self.auto_layout_check = ToggleSwitch("自动排列：岛屿按 ¼ / ⅓ / ½ / 整行 铺成网格")
        self.auto_layout_check.setChecked(bool(getattr(preferences, "auto_layout", False)))
        self.move_mode_control = SegmentedControl(["交换位置", "依次后移"])
        modes = [value for value, _label in GRID_MOVE_CHOICES]
        current_mode = str(getattr(preferences, "grid_move_mode", "swap") or "swap")
        self.move_mode_control.setCurrentIndex(
            modes.index(current_mode) if current_mode in modes else 0, animate=False
        )
        self.move_mode_control.setEnabled(self.auto_layout_check.isChecked())
        layout.addWidget(_section("自动排列"))
        layout.addWidget(_group(_switch_row(self.auto_layout_check),
                                _row("拖动时其他岛屿", self.move_mode_control)))
        layout.addWidget(_help("开启后岛屿可自由拖动，按四分之一屏幕吸附，空隙会自动补齐；"
                               "岛屿大小改用大小级别调整。"))

        # Edge page switching
        self.edge_switch_check = ToggleSwitch("鼠标停在屏幕左右边缘时切换场景页")
        self.edge_switch_check.setChecked(bool(getattr(preferences, "edge_switch_enabled", True)))
        self.edge_width_spin = QSpinBox()
        self.edge_width_spin.setRange(8, 120)
        self.edge_width_spin.setSingleStep(4)
        self.edge_width_spin.setSuffix(" px")
        self.edge_width_spin.setValue(int(getattr(preferences, "edge_switch_width", 28)))
        self.edge_width_spin.setFixedWidth(110)
        self.edge_delay_spin = QSpinBox()
        self.edge_delay_spin.setRange(120, 1500)
        self.edge_delay_spin.setSingleStep(60)
        self.edge_delay_spin.setSuffix(" ms")
        self.edge_delay_spin.setValue(int(getattr(preferences, "edge_switch_delay_ms", 420)))
        self.edge_delay_spin.setFixedWidth(110)
        self.edge_width_spin.setEnabled(self.edge_switch_check.isChecked())
        self.edge_delay_spin.setEnabled(self.edge_switch_check.isChecked())
        layout.addWidget(_section("场景页切换"))
        layout.addWidget(_group(_switch_row(self.edge_switch_check),
                                _row("触发边缘宽度", self.edge_width_spin),
                                _row("停留时间", self.edge_delay_spin)))
        layout.addWidget(_help("仅在存在多个场景页时生效；停留足够久才会切换，避免误触。"))

        layout.addStretch(1)
        return page

    def _appearance_page(self, preferences: Preferences) -> QWidget:
        page, layout = self._page("外观")
        material = str(getattr(preferences, "island_material", "frosted") or "frosted")
        values = [value for value, _label in MATERIAL_CHOICES]
        self.material_control = SegmentedControl([label for _value, label in MATERIAL_CHOICES])
        self.material_control.setCurrentIndex(values.index(material) if material in values else 1, animate=False)
        material_box = QWidget()
        material_layout = QVBoxLayout(material_box)
        material_layout.setContentsMargins(0, 8, 0, 8)
        material_layout.addWidget(self.material_control)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(35, 100)
        initial_opacity = (
            round(float(preferences.panel_opacity) * 100)
            if self._opacity_was_float and float(preferences.panel_opacity) <= 1.0
            else round(float(preferences.panel_opacity))
        )
        self.opacity_slider.setValue(max(35, min(100, initial_opacity)))
        self.opacity_label = QLabel()
        self.opacity_label.setObjectName("valueLabel")
        self.opacity_label.setMinimumWidth(44)
        opacity_row = IslandAppearanceDialog._slider_row("面板浓度", self.opacity_slider, self.opacity_label)
        layout.addWidget(_section("收纳岛背景"))
        layout.addWidget(_group(material_box, opacity_row))
        layout.addWidget(_help("这是所有收纳岛的默认质感；单个收纳岛可在右键菜单“外观与名称…”中另行选择。"))

        self.backdrop_control = SegmentedControl(["系统壁纸", "自定义图片"])
        self.backdrop_control.setCurrentIndex(
            1 if getattr(preferences, "backdrop_source", "wallpaper") == "image" else 0, animate=False)
        backdrop_box = QWidget()
        backdrop_layout = QVBoxLayout(backdrop_box)
        backdrop_layout.setContentsMargins(0, 8, 0, 8)
        backdrop_layout.addWidget(self.backdrop_control)
        image_row = QWidget()
        image_layout = QHBoxLayout(image_row)
        image_layout.setContentsMargins(0, 6, 0, 6)
        image_layout.setSpacing(8)
        self.backdrop_label = QLabel()
        self.backdrop_label.setObjectName("valueLabel")
        self.backdrop_button = QPushButton("选择图片…")
        image_layout.addWidget(self.backdrop_label, 1)
        image_layout.addWidget(self.backdrop_button)
        self.backdrop_button.clicked.connect(self._choose_backdrop_image)
        layout.addWidget(_section("玻璃取样来源"))
        layout.addWidget(_group(backdrop_box, image_row))
        layout.addWidget(_help("毛玻璃 / 液体玻璃会模糊身后的桌面壁纸。使用动态壁纸软件时，可选择一张相近的图片作为取样来源。"))

        self.font_combo = QComboBox()
        self.font_combo.setMaxVisibleItems(18)
        self.font_combo.setMinimumWidth(230)
        self.font_combo.addItem("系统默认", "")
        current_family = str(getattr(preferences, "font_family", "") or "")
        families = [name for name in QFontDatabase.families() if not name.startswith("@")]
        if self._font_file_family and self._font_file_family not in families:
            families.append(self._font_file_family)
        for name in sorted(set(families), key=str.casefold):
            self.font_combo.addItem(name, name)
        index = self.font_combo.findData(current_family) if current_family else 0
        self.font_combo.setCurrentIndex(max(0, index))
        self.font_import_button = QPushButton("导入字体文件…")
        self.font_import_button.clicked.connect(self._import_font)
        font_row = QWidget()
        font_layout = QHBoxLayout(font_row)
        font_layout.setContentsMargins(0, 6, 0, 6)
        font_layout.setSpacing(8)
        font_label = QLabel("字体")
        font_label.setObjectName("rowLabel")
        font_layout.addWidget(font_label)
        font_layout.addStretch(1)
        font_layout.addWidget(self.font_combo)
        font_layout.addWidget(self.font_import_button)
        self.font_size_spin = QDoubleSpinBox()
        self.font_size_spin.setRange(8.0, 16.0)
        self.font_size_spin.setSingleStep(0.5)
        self.font_size_spin.setDecimals(1)
        self.font_size_spin.setSuffix(" pt")
        self.font_size_spin.setValue(float(getattr(preferences, "font_size", 10.0) or 10.0))
        self.font_size_spin.setFixedWidth(110)
        self.font_preview = QLabel("桌屿 DeskIsle · 把凌乱桌面整理成你的工作岛 0123")
        self.font_preview.setObjectName("valueLabel")
        self.font_preview.setWordWrap(True)
        self.font_preview.setMinimumHeight(34)
        layout.addWidget(_section("字体（应用于整个桌屿）"))
        layout.addWidget(_group(font_row, _row("字号", self.font_size_spin), self.font_preview))
        layout.addStretch(1)
        return page

    def _motion_page(self, preferences: Preferences) -> QWidget:
        page, layout = self._page("动态与性能")
        self.reduce_motion_check = ToggleSwitch("减弱动态效果")
        self.reduce_motion_check.setChecked(bool(getattr(preferences, "reduce_motion", False)))
        layout.addWidget(_group(_switch_row(self.reduce_motion_check)))
        layout.addWidget(_help("开启后，展开 / 收拢、图标缩放与菜单将直接切换，不播放过渡动画。"))

        self.smart_pause_check = ToggleSwitch("被遮挡时暂停视频与动画")
        self.smart_pause_check.setChecked(bool(getattr(preferences, "smart_pause", True)))
        fps = int(getattr(preferences, "media_fps", 24) or 24)
        self.fps_control = SegmentedControl(["{0} 帧".format(value) for value in FPS_CHOICES])
        closest = min(range(len(FPS_CHOICES)), key=lambda i: abs(FPS_CHOICES[i] - fps))
        self.fps_control.setCurrentIndex(closest, animate=False)
        self.fps_control.setFixedWidth(260)
        layout.addSpacing(6)
        layout.addWidget(_section("背景视频与 HTML 动画"))
        layout.addWidget(_group(_switch_row(self.smart_pause_check), _row("视频帧率上限", self.fps_control)))
        layout.addWidget(_help("全屏或最大化窗口挡住收纳岛、收拢或清屏时，会自动暂停背景视频、HTML 动画与网页渲染。"
                               "帧率越低越省电，24 帧已足够流畅。"))
        layout.addStretch(1)
        return page

    def _update_page(self, preferences: Preferences, update_status: str) -> QWidget:
        page, layout = self._page("更新")
        self.auto_update_check = ToggleSwitch("自动检查更新")
        self.auto_update_check.setChecked(bool(getattr(preferences, "auto_check_updates", True)))
        self.check_now_button = QPushButton("立即检查更新")
        self.check_now_button.setObjectName("primary")
        self.check_now_button.clicked.connect(self.check_updates_requested)
        self.update_status_label = QLabel(update_status or "尚未检查")
        self.update_status_label.setObjectName("valueLabel")
        layout.addWidget(_group(_row("当前版本", QLabel(__version__)), _switch_row(self.auto_update_check),
                                _row("上次检查", self.update_status_label)))
        layout.addWidget(_help("从 GitHub 上的 narabias/DeskIsle 检查正式发布版本，每天最多自动检查一次，"
                               "发现新版本时只提醒、不会自动安装。"))
        button_row = QHBoxLayout()
        button_row.addWidget(self.check_now_button)
        button_row.addStretch(1)
        layout.addSpacing(4)
        layout.addLayout(button_row)
        layout.addSpacing(8)
        layout.addWidget(_section("你的配置会被保留"))
        layout.addWidget(_group(_help(
            "更新只替换程序文件。收纳岛布局、归流规则、背景媒体与设置保存在 %LOCALAPPDATA%\\DeskIsle，"
            "安装程序不会改动它们；开始安装前还会自动保存一份布局快照，可在“恢复布局快照”中找回。"),
            margins=(14, 12, 14, 12)))
        layout.addStretch(1)
        return page

    def set_update_status(self, text: str) -> None:
        self.update_status_label.setText(text)

    # Behaviour ------------------------------------------------------------
    def _update_opacity_label(self) -> None:
        self.opacity_label.setText(f"{self.opacity_slider.value()}%")

    def _selected_font_family(self) -> str:
        return str(self.font_combo.currentData() or "")

    def _update_font_preview(self, *_args) -> None:
        family = self._selected_font_family()
        font = QFont()
        if family:
            font.setFamilies([family] + theme.DEFAULT_FAMILIES)
        else:
            font.setFamilies(theme.DEFAULT_FAMILIES)
        font.setPointSizeF(self.font_size_spin.value())
        self.font_preview.setFont(font)

    def _import_font(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "导入字体文件", str(Path.home()),
                                                    "字体文件 (*.ttf *.otf *.ttc *.otc)")
        if not path:
            return
        stored = path
        if self._font_importer is not None:
            try:
                stored = self._font_importer(path) or path
            except OSError:
                stored = path
        family = theme.load_font_file(stored)
        if not family:
            QMessageBox.warning(self, "导入字体", "无法读取这个字体文件。请确认它是有效的 TTF / OTF 字体。")
            return
        self._font_file = stored
        self._font_file_family = family
        index = self.font_combo.findData(family)
        if index < 0:
            self.font_combo.addItem(family, family)
            index = self.font_combo.count() - 1
        self.font_combo.setCurrentIndex(index)

    def _sync_backdrop(self, *_args) -> None:
        custom = self.backdrop_control.currentIndex() == 1
        self.backdrop_button.setEnabled(custom)
        if self._backdrop_image:
            name = Path(self._backdrop_image).name
            self.backdrop_label.setText(self.backdrop_label.fontMetrics().elidedText(
                name, Qt.TextElideMode.ElideMiddle, 260))
            self.backdrop_label.setToolTip(self._backdrop_image)
        else:
            self.backdrop_label.setText("未选择图片" if custom else "使用当前 Windows 壁纸")
        self.backdrop_label.setEnabled(custom or not self._backdrop_image)

    def _choose_backdrop_image(self) -> None:
        start = os.path.dirname(self._backdrop_image) if self._backdrop_image else str(Path.home())
        path, _filter = QFileDialog.getOpenFileName(self, "选择玻璃取样图片", start,
                                                    "图片 (*.png *.jpg *.jpeg *.bmp *.webp *.gif)")
        if path:
            from .media import import_media_file

            self._backdrop_image = import_media_file(path)
            self._sync_backdrop()

    def _restore_defaults(self) -> None:
        defaults = Preferences()
        self.hide_native_check.setChecked(defaults.hide_native_icons)
        self.snap_check.setChecked(defaults.snap_to_grid)
        self.grid_spin.setValue(defaults.grid_size)
        self.auto_check.setChecked(defaults.auto_organize)
        self.startup_check.setChecked(defaults.start_with_windows)
        opacity = float(defaults.panel_opacity)
        self.opacity_slider.setValue(round(opacity * 100 if opacity <= 1.0 else opacity))
        values = [value for value, _label in MATERIAL_CHOICES]
        self.material_control.setCurrentIndex(values.index(defaults.island_material))
        self.backdrop_control.setCurrentIndex(0)
        self.font_combo.setCurrentIndex(0)
        self.font_size_spin.setValue(defaults.font_size)
        self.reduce_motion_check.setChecked(defaults.reduce_motion)
        self.smart_pause_check.setChecked(defaults.smart_pause)
        self.fps_control.setCurrentIndex(FPS_CHOICES.index(defaults.media_fps))
        self.auto_update_check.setChecked(defaults.auto_check_updates)
        self.auto_layout_check.setChecked(defaults.auto_layout)
        self.move_mode_control.setCurrentIndex(
            [value for value, _label in GRID_MOVE_CHOICES].index(defaults.grid_move_mode), animate=False
        )
        self.edge_switch_check.setChecked(defaults.edge_switch_enabled)
        self.edge_width_spin.setValue(defaults.edge_switch_width)
        self.edge_delay_spin.setValue(defaults.edge_switch_delay_ms)

    def _save_and_accept(self) -> None:
        opacity: float | int
        if self._opacity_was_float:
            opacity = self.opacity_slider.value() / 100.0
        else:
            opacity = self.opacity_slider.value()
        family = self._selected_font_family()
        font_file = self._font_file if family and family == self._font_file_family else ""
        backdrop_source = "image" if self.backdrop_control.currentIndex() == 1 and self._backdrop_image else "wallpaper"
        self.preferences = replace(
            self.preferences,
            hide_native_icons=self.hide_native_check.isChecked(),
            snap_to_grid=self.snap_check.isChecked(),
            grid_size=self.grid_spin.value(),
            auto_organize=self.auto_check.isChecked(),
            start_with_windows=self.startup_check.isChecked(),
            panel_opacity=opacity,
            island_material=MATERIAL_CHOICES[self.material_control.currentIndex()][0],
            backdrop_source=backdrop_source,
            backdrop_image=self._backdrop_image,
            font_family=family,
            font_file=font_file,
            font_size=float(self.font_size_spin.value()),
            reduce_motion=self.reduce_motion_check.isChecked(),
            smart_pause=self.smart_pause_check.isChecked(),
            media_fps=FPS_CHOICES[self.fps_control.currentIndex()],
            auto_check_updates=self.auto_update_check.isChecked(),
            auto_layout=self.auto_layout_check.isChecked(),
            grid_move_mode=GRID_MOVE_CHOICES[self.move_mode_control.currentIndex()][0],
            edge_switch_enabled=self.edge_switch_check.isChecked(),
            edge_switch_width=int(self.edge_width_spin.value()),
            edge_switch_delay_ms=int(self.edge_delay_spin.value()),
        )
        self.accept()


class UpdateDialog(QDialog):
    """Check → show release notes → download (SHA-256 verified) → install."""

    install_requested = Signal(str)

    def __init__(self, manager, parent: QWidget | None = None, release=None, newer: bool | None = None) -> None:
        super().__init__(parent)
        from .updater import RELEASES_PAGE, can_self_install

        self.manager = manager
        self.release = release
        self._installer_path = ""
        self._releases_page = RELEASES_PAGE
        self._self_install = can_self_install()
        self.setWindowTitle("软件更新")
        _prepare_dialog(self, 540)

        root = QVBoxLayout(self)
        root.setContentsMargins(26, 24, 26, 20)
        root.setSpacing(12)
        title = QLabel("软件更新")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        self.status_label = QLabel()
        self.status_label.setStyleSheet("font-size: 12pt; font-weight: 600;")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)
        self.detail_label = _help("")
        root.addWidget(self.detail_label)
        self.notes = QTextBrowser()
        self.notes.setOpenExternalLinks(True)
        self.notes.setMinimumHeight(150)
        self.notes.setMaximumHeight(260)
        self.notes.hide()
        root.addWidget(self.notes)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 1000)
        self.progress.hide()
        root.addWidget(self.progress)
        self.progress_label = _help("")
        self.progress_label.hide()
        root.addWidget(self.progress_label)
        self.keep_note = _help("更新只替换程序文件，你的布局、规则和设置会原样保留；安装前会自动保存一份布局快照。")
        root.addWidget(self.keep_note)
        root.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(8)
        self.skip_button = QPushButton("跳过此版本")
        self.browser_button = QPushButton("在浏览器中查看")
        row.addWidget(self.skip_button)
        row.addWidget(self.browser_button)
        row.addStretch(1)
        self.later_button = QPushButton("稍后")
        self.retry_button = QPushButton("重试")
        self.cancel_button = QPushButton("取消下载")
        self.install_button = QPushButton("下载并安装")
        self.install_button.setObjectName("primary")
        self.close_button = QPushButton("完成")
        for button in (self.later_button, self.retry_button, self.cancel_button, self.install_button,
                       self.close_button):
            row.addWidget(button)
        root.addLayout(row)

        self.skip_button.clicked.connect(self._skip)
        self.browser_button.clicked.connect(self._open_page)
        self.later_button.clicked.connect(self.reject)
        self.close_button.clicked.connect(self.accept)
        self.retry_button.clicked.connect(self.start_check)
        self.cancel_button.clicked.connect(self.manager.cancel_download)
        self.install_button.clicked.connect(self._install_clicked)

        self._connections = [
            (manager.check_finished, self._check_finished),
            (manager.check_failed, self._check_failed),
            (manager.download_progress, self._download_progress),
            (manager.download_finished, self._download_finished),
            (manager.download_failed, self._download_failed),
        ]
        for signal, slot in self._connections:
            signal.connect(slot)

        if release is not None:
            from .updater import is_newer

            self._show_release(release, is_newer(release.version, manager.current_version) if newer is None else newer)
        else:
            self.start_check()

    def _buttons(self, *visible: QPushButton) -> None:
        for button in (self.skip_button, self.browser_button, self.later_button, self.retry_button,
                       self.cancel_button, self.install_button, self.close_button):
            button.setVisible(button in visible)

    def start_check(self) -> None:
        self.status_label.setText("正在检查更新…")
        self.detail_label.setText("正在连接 GitHub（{0}）".format("narabias/DeskIsle"))
        self.notes.hide()
        self.progress.show()
        self.progress.setRange(0, 0)
        self.progress_label.hide()
        self._buttons(self.later_button)
        self.later_button.setText("取消")
        self.manager.check(manual=True)

    def _check_finished(self, release, newer: bool, _manual: bool) -> None:
        if self.manager.is_downloading:
            return
        self._show_release(release, newer)

    def _show_release(self, release, newer: bool) -> None:
        self.release = release
        self.progress.hide()
        self.progress.setRange(0, 1000)
        self.later_button.setText("稍后")
        if not newer:
            self.status_label.setText("桌屿已是最新版本")
            self.detail_label.setText("当前版本 {0}，GitHub 上的最新发布版本为 {1}。".format(
                self.manager.current_version, release.version))
            self.notes.hide()
            self._buttons(self.browser_button, self.close_button)
            return
        self.status_label.setText("发现新版本 {0}".format(release.version))
        details = ["当前版本 {0}".format(self.manager.current_version)]
        if release.published_text:
            details.append("发布于 {0}".format(release.published_text))
        if release.size_text:
            details.append("安装包 {0}".format(release.size_text))
        self.detail_label.setText(" · ".join(details))
        notes = release.notes or "这个版本没有附带更新说明。"
        self.notes.setMarkdown(notes)
        self.notes.show()
        if self._self_install and release.has_installer:
            self.install_button.setText("下载并安装")
        else:
            self.install_button.setText("前往下载页面")
        self._buttons(self.skip_button, self.browser_button, self.later_button, self.install_button)

    def _check_failed(self, message: str, _manual: bool) -> None:
        self.progress.hide()
        self.progress.setRange(0, 1000)
        self.status_label.setText("暂时无法检查更新")
        self.detail_label.setText(message)
        self.later_button.setText("关闭")
        self._buttons(self.browser_button, self.retry_button, self.later_button)

    def _install_clicked(self) -> None:
        if self._installer_path:
            self.install_requested.emit(self._installer_path)
            return
        release = self.release
        if release is None:
            return
        if not (self._self_install and release.has_installer):
            self._open_page()
            return
        self.status_label.setText("正在下载 {0}…".format(release.version))
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.show()
        self.progress_label.setText("准备下载…")
        self.progress_label.show()
        self._buttons(self.cancel_button)
        self.manager.download(release)

    def _download_progress(self, received, total) -> None:
        received = int(received)
        total = int(total or 0)
        if total > 0:
            self.progress.setRange(0, 1000)
            self.progress.setValue(int(1000 * min(1.0, received / total)))
            self.progress_label.setText("{0:.1f} / {1:.1f} MB".format(received / 1048576, total / 1048576))
        else:
            self.progress.setRange(0, 0)
            self.progress_label.setText("{0:.1f} MB".format(received / 1048576))

    def _download_finished(self, path: str) -> None:
        self._installer_path = path
        self.progress.setRange(0, 1000)
        self.progress.setValue(1000)
        self.status_label.setText("安装包已下载并通过校验")
        self.progress_label.setText("SHA-256 校验通过。点击“立即安装”后，桌屿会保存布局、退出，安装完成后自动重新打开。")
        self.install_button.setText("立即安装")
        self._buttons(self.later_button, self.install_button)

    def _download_failed(self, message: str) -> None:
        self.progress.hide()
        self.status_label.setText("下载未完成")
        self.progress_label.setText(message)
        self.progress_label.show()
        self.install_button.setText("重新下载")
        self._buttons(self.browser_button, self.later_button, self.install_button)

    def _skip(self) -> None:
        if self.release is not None:
            self.manager.skip_version(self.release.version)
        self.reject()

    def _open_page(self) -> None:
        url = getattr(self.release, "page_url", "") or self._releases_page
        QDesktopServices.openUrl(QUrl(url))

    def done(self, result: int) -> None:  # noqa: D401 - Qt API
        if self.manager.is_downloading:
            self.manager.cancel_download()
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._connections = []
        super().done(result)


class SnapshotDialog(QDialog):
    """Select a snapshot returned by StateStore.list_snapshots()."""

    def __init__(self, snapshots: Iterable[Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.snapshots = list(snapshots)
        self.selected_snapshot: Any | None = None
        self.selected_name = ""
        self.selected_path = ""
        self.setWindowTitle("布局时光机")
        _prepare_dialog(self, 720, 430)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)
        root.addLayout(_heading("布局时光机", "选择一个布局快照。恢复操作由主程序在确认后执行。"))

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["名称", "创建时间", "位置"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setColumnWidth(0, 190)
        self.tree.setColumnWidth(1, 150)
        self.tree.itemSelectionChanged.connect(self._selection_changed)
        self.tree.itemDoubleClicked.connect(lambda *_: self._validate_and_accept())
        root.addWidget(self.tree, 1)

        detail = QFrame()
        detail.setObjectName("summaryCard")
        detail_form = QFormLayout(detail)
        detail_form.setContentsMargins(14, 12, 14, 12)
        self.name_value = QLabel("尚未选择")
        self.path_value = QLineEdit()
        self.path_value.setReadOnly(True)
        self.path_value.setPlaceholderText("选择快照后显示文件位置")
        detail_form.addRow("快照", self.name_value)
        detail_form.addRow("路径", self.path_value)
        root.addWidget(detail)

        self.empty_label = QLabel("还没有布局快照。请先在主界面保存一个快照。")
        self.empty_label.setObjectName("helpText")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setVisible(not self.snapshots)
        root.addWidget(self.empty_label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.restore_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.restore_button.setText("选择")
        self.restore_button.setObjectName("primary")
        self.restore_button.setEnabled(False)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._populate()

    @staticmethod
    def _snapshot_data(snapshot: Any) -> tuple[str, str, Any]:
        if isinstance(snapshot, (str, os.PathLike, Path)):
            path = os.fspath(snapshot)
            return Path(path).stem, path, ""
        name = str(_record_value(snapshot, "name", "未命名快照"))
        path = str(_record_value(snapshot, "path", ""))
        created = _record_value(snapshot, "created_at", "")
        return name, path, created

    @staticmethod
    def _format_created(value: Any) -> str:
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%d %H:%M")
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M")
            except (ValueError, OSError, OverflowError):
                return str(value)
        text = str(value or "")
        if "T" in text:
            return text.replace("T", " ")[:16]
        return text

    def _populate(self) -> None:
        for index, snapshot in enumerate(self.snapshots):
            name, path, created = self._snapshot_data(snapshot)
            item = QTreeWidgetItem([name, self._format_created(created), path])
            item.setData(0, Qt.ItemDataRole.UserRole, index)
            item.setToolTip(2, path)
            self.tree.addTopLevelItem(item)
        if self.snapshots:
            self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _selection_changed(self) -> None:
        items = self.tree.selectedItems()
        if not items:
            self.selected_snapshot = None
            self.selected_name = ""
            self.selected_path = ""
            self.name_value.setText("尚未选择")
            self.path_value.clear()
            self.restore_button.setEnabled(False)
            return
        index = int(items[0].data(0, Qt.ItemDataRole.UserRole))
        self.selected_snapshot = self.snapshots[index]
        self.selected_name, self.selected_path, _ = self._snapshot_data(self.selected_snapshot)
        self.name_value.setText(self.selected_name)
        self.path_value.setText(self.selected_path)
        self.restore_button.setEnabled(True)

    @property
    def selection(self) -> dict[str, Any] | None:
        if self.selected_snapshot is None:
            return None
        return {
            "snapshot": self.selected_snapshot,
            "name": self.selected_name,
            "path": self.selected_path,
        }

    def _validate_and_accept(self) -> None:
        if self.selected_snapshot is not None:
            self.accept()

    @staticmethod
    def get_data(
        snapshots: Iterable[Any],
        parent: QWidget | None = None,
    ) -> dict[str, Any] | None:
        dialog = SnapshotDialog(snapshots, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.selection
        return None


class AboutDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"关于 {APP_NAME}")
        _prepare_dialog(self, 500)

        root = QVBoxLayout(self)
        root.setContentsMargins(28, 26, 28, 22)
        root.setSpacing(14)

        mark = QLabel("▦")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setStyleSheet(
            f"color: {ACCENT}; font-size: 34pt; font-weight: 700; background: transparent;"
        )
        root.addWidget(mark)
        title = QLabel(APP_NAME)
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)
        version = QLabel(f"版本 {__version__}")
        version.setObjectName("dialogSubtitle")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(version)

        summary = QLabel("把凌乱桌面整理成你的工作岛。")
        summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        summary.setStyleSheet("font-size: 11pt;")
        root.addWidget(summary)

        card = QFrame()
        card.setObjectName("summaryCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        privacy = QLabel(
            "桌屿采用本地优先设计。普通收纳岛只保存文件引用，"
            "不会因为整理或删除收纳岛而移动、重命名或删除原文件。"
        )
        privacy.setObjectName("helpText")
        privacy.setWordWrap(True)
        privacy.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(privacy)
        root.addWidget(card)

        copyright_label = QLabel("独立原创实现 · Python + PySide6")
        copyright_label.setObjectName("dialogSubtitle")
        copyright_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(copyright_label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.accept)
        root.addWidget(buttons)


class WelcomeDialog(QDialog):
    """First-run guide. Only asks about startup; every choice is reversible."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"欢迎使用 {APP_NAME}")
        _prepare_dialog(self, 420)
        # A guide is not a task dialog: there is no close button, and both
        # outcomes are positive choices rather than accept/reject.
        self.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(30, 28, 30, 24)
        root.setSpacing(14)

        mark = QLabel("▦")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setStyleSheet(
            f"color: {ACCENT}; font-size: 34pt; font-weight: 700; background: transparent;"
        )
        root.addWidget(mark)

        title = QLabel(f"欢迎使用 {APP_NAME}")
        title.setObjectName("dialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        subtitle = QLabel("把凌乱桌面整理成你的工作岛。")
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        card = QFrame()
        card.setObjectName("summaryCard")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(16, 14, 16, 14)
        card_layout.setSpacing(8)

        question = QLabel("开机自动启动")
        question.setStyleSheet("font-weight: 600;")
        card_layout.addWidget(question)

        explanation = QLabel(
            "桌屿平时停留在桌面底层，开机自动启动可以让收纳岛立即就位，"
            "不必每次手动打开。"
        )
        explanation.setObjectName("helpText")
        explanation.setWordWrap(True)
        card_layout.addWidget(explanation)

        self.startup_check = QCheckBox("登录 Windows 后自动启动桌屿（推荐）")
        self.startup_check.setChecked(True)
        card_layout.addWidget(self.startup_check)
        root.addWidget(card)

        note = QLabel("之后可随时在设置中开启或关闭，不影响其他功能。")
        note.setObjectName("helpText")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        root.addWidget(note)

        root.addStretch(1)

        button_row = QHBoxLayout()
        button_row.setSpacing(10)
        button_row.addStretch(1)
        self.skip_button = QPushButton("暂不设置")
        self.accept_button = QPushButton("开始使用")
        self.accept_button.setObjectName("primary")
        self.skip_button.setDefault(False)
        self.accept_button.setDefault(True)
        button_row.addWidget(self.skip_button)
        button_row.addWidget(self.accept_button)
        root.addLayout(button_row)

        self.skip_button.clicked.connect(self.reject)
        self.accept_button.clicked.connect(self.accept)

    def wants_startup(self) -> bool:
        """Return the startup preference chosen in this guide."""
        return bool(self.startup_check.isChecked())


__all__ = [
    "AboutDialog",
    "IslandAppearanceDialog",
    "NewIslandDialog",
    "RenameDialog",
    "RuleEditDialog",
    "RulesDialog",
    "SettingsDialog",
    "SnapshotDialog",
    "TabDialog",
    "UpdateDialog",
    "WelcomeDialog",
]

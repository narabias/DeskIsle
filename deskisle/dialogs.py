from __future__ import annotations

import copy
import os
import uuid
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import __version__
from .models import Preferences, Rule
from .theme import ACCENT, APP_NAME, TEXT_MUTED, app_stylesheet


_DIALOG_STYLESHEET = f"""
QDialog {{
    background: #151B25;
}}
QLabel#dialogTitle {{
    color: #F8FAFD;
    font-size: 18pt;
    font-weight: 650;
}}
QLabel#dialogSubtitle, QLabel#helpText {{
    color: {TEXT_MUTED};
}}
QLabel#errorText {{
    color: #FF9DA5;
}}
QFrame#typeCard, QFrame#summaryCard {{
    background: #1C2532;
    border: 1px solid #344256;
    border-radius: 11px;
}}
QFrame#typeCard:hover {{
    border-color: {ACCENT};
    background: #202D3A;
}}
QGroupBox {{
    border: 1px solid #344256;
    border-radius: 10px;
    margin-top: 13px;
    padding: 14px 12px 10px 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #DCE5F1;
}}
QTreeWidget {{
    background: #1B2431;
    alternate-background-color: #202B3A;
    border: 1px solid #344256;
    border-radius: 9px;
    outline: 0;
}}
QTreeWidget::item {{
    padding: 7px 5px;
}}
QTreeWidget::item:selected {{
    background: #31554F;
}}
QHeaderView::section {{
    color: #BFC9D7;
    background: #202938;
    border: 0;
    border-bottom: 1px solid #344256;
    padding: 7px;
}}
QSlider::groove:horizontal {{
    height: 5px;
    background: #344256;
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 16px;
    margin: -6px 0;
    background: {ACCENT};
    border-radius: 8px;
}}
QSlider::sub-page:horizontal {{
    background: #3E8F83;
    border-radius: 2px;
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


def _prepare_dialog(dialog: QDialog, width: int, height: int | None = None) -> None:
    dialog.setStyleSheet(app_stylesheet() + _DIALOG_STYLESHEET)
    dialog.setMinimumWidth(width)
    if height is not None:
        dialog.setMinimumHeight(height)
    dialog.setWindowModality(Qt.WindowModality.WindowModal)


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


class NewIslandDialog(QDialog):
    """Create either a reference-only island or a live folder portal."""

    def __init__(
        self,
        parent: QWidget | None = None,
        force_portal: bool | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("新建收纳岛")
        _prepare_dialog(self, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(17)
        root.addLayout(_heading("新建收纳岛", "选择一种内容来源。普通收纳岛只保存引用，不会移动原文件。"))

        choices = QHBoxLayout()
        choices.setSpacing(12)
        self.type_group = QButtonGroup(self)
        self.normal_radio = self._type_card(
            choices,
            "普通收纳岛",
            "整理桌面上的文件、文件夹与快捷方式",
            checked=True,
        )
        self.portal_radio = self._type_card(
            choices,
            "文件视窗",
            "在桌面实时查看一个文件夹的内容",
        )
        self.type_group.addButton(self.normal_radio, 0)
        self.type_group.addButton(self.portal_radio, 1)
        if force_portal is not None:
            self.portal_radio.setChecked(bool(force_portal))
            self.normal_radio.setChecked(not bool(force_portal))
        root.addLayout(choices)

        form_frame = QFrame()
        form_frame.setObjectName("summaryCard")
        form = QGridLayout(form_frame)
        form.setContentsMargins(16, 15, 16, 15)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(12)

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
        root.addWidget(form_frame)

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

        self.type_group.idToggled.connect(lambda _id, _checked: self._sync_type())
        self.name_edit.returnPressed.connect(self._validate_and_accept)
        self._sync_type()
        self.name_edit.setFocus()

    def _type_card(
        self,
        layout: QHBoxLayout,
        title: str,
        description: str,
        checked: bool = False,
    ) -> QRadioButton:
        frame = QFrame()
        frame.setObjectName("typeCard")
        card = QVBoxLayout(frame)
        card.setContentsMargins(15, 13, 15, 13)
        card.setSpacing(5)
        radio = QRadioButton(title)
        radio.setChecked(checked)
        radio.setStyleSheet("QRadioButton { font-size: 11pt; font-weight: 600; }")
        help_label = QLabel(description)
        help_label.setObjectName("helpText")
        help_label.setWordWrap(True)
        card.addWidget(radio)
        card.addWidget(help_label)
        layout.addWidget(frame, 1)
        return radio

    def _sync_type(self) -> None:
        portal = self.portal_radio.isChecked()
        self.folder_label.setEnabled(portal)
        self.folder_edit.setEnabled(portal)
        self.browse_button.setEnabled(portal)
        if not portal:
            self.error_label.hide()

    def _choose_folder(self) -> None:
        start = self.folder_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "选择文件视窗目录", start)
        if not folder:
            return
        self.folder_edit.setText(os.path.normpath(folder))
        if not self.name_edit.text().strip():
            self.name_edit.setText(Path(folder).name or "文件视窗")

    def _validate_and_accept(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            self._show_error("请输入收纳岛名称。")
            self.name_edit.setFocus()
            return
        if self.portal_radio.isChecked():
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
        self.error_label.hide()
        self.accept()

    def _show_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.show()

    def data(self) -> dict[str, Any]:
        portal = self.portal_radio.isChecked()
        kind = "portal" if portal else "normal"
        path = self.folder_edit.text().strip() if portal else ""
        title = self.name_edit.text().strip()
        return {
            "kind": kind,
            "type": kind,
            "title": title,
            "name": title,
            "folder": path,
            "folder_path": path,
            "portal_path": path or None,
            "path": path,
            "is_portal": portal,
        }

    @staticmethod
    def get_data(
        parent: QWidget | None = None,
        force_portal: bool | None = None,
    ) -> dict[str, Any] | None:
        dialog = NewIslandDialog(parent, force_portal)
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


class SettingsDialog(QDialog):
    def __init__(self, preferences: Preferences, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.preferences = copy.deepcopy(preferences)
        self._opacity_was_float = isinstance(preferences.panel_opacity, float)
        self.setWindowTitle("桌屿设置")
        _prepare_dialog(self, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(14)
        root.addLayout(_heading("桌屿设置", "调整桌面接管、自动整理与收纳岛显示方式。"))

        desktop_group = QGroupBox("桌面")
        desktop_layout = QVBoxLayout(desktop_group)
        desktop_layout.setSpacing(10)
        self.hide_native_check = QCheckBox("隐藏 Windows 原生桌面图标，由桌屿统一显示")
        self.hide_native_check.setChecked(bool(preferences.hide_native_icons))
        desktop_layout.addWidget(self.hide_native_check)
        safety_note = QLabel("关闭桌屿或退出应用时，原生桌面图标会恢复显示。")
        safety_note.setObjectName("helpText")
        safety_note.setWordWrap(True)
        desktop_layout.addWidget(safety_note)
        root.addWidget(desktop_group)

        layout_group = QGroupBox("布局与自动整理")
        layout_form = QFormLayout(layout_group)
        layout_form.setVerticalSpacing(11)
        self.snap_check = QCheckBox("移动和缩放时吸附到网格")
        self.snap_check.setChecked(bool(preferences.snap_to_grid))
        layout_form.addRow("吸附", self.snap_check)
        self.grid_spin = QSpinBox()
        self.grid_spin.setRange(4, 64)
        self.grid_spin.setSingleStep(2)
        self.grid_spin.setSuffix(" px")
        self.grid_spin.setValue(int(preferences.grid_size))
        layout_form.addRow("网格尺寸", self.grid_spin)
        self.auto_check = QCheckBox("持续监听并自动应用已启用的归流规则")
        self.auto_check.setChecked(bool(preferences.auto_organize))
        layout_form.addRow("自动归流", self.auto_check)
        root.addWidget(layout_group)

        appearance_group = QGroupBox("外观与启动")
        appearance_form = QFormLayout(appearance_group)
        appearance_form.setVerticalSpacing(12)
        opacity_row = QWidget()
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_layout.setSpacing(10)
        self.opacity_slider = QSlider(Qt.Orientation.Horizontal)
        self.opacity_slider.setRange(35, 100)
        initial_opacity = (
            round(float(preferences.panel_opacity) * 100)
            if self._opacity_was_float and float(preferences.panel_opacity) <= 1.0
            else round(float(preferences.panel_opacity))
        )
        self.opacity_slider.setValue(max(35, min(100, initial_opacity)))
        self.opacity_label = QLabel()
        self.opacity_label.setMinimumWidth(44)
        opacity_layout.addWidget(self.opacity_slider, 1)
        opacity_layout.addWidget(self.opacity_label)
        appearance_form.addRow("收纳岛透明度", opacity_row)
        self.startup_check = QCheckBox("登录 Windows 后自动启动桌屿")
        self.startup_check.setChecked(bool(preferences.start_with_windows))
        appearance_form.addRow("开机启动", self.startup_check)
        root.addWidget(appearance_group)

        root.addStretch(1)
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
        root.addLayout(button_row)

        self.snap_check.toggled.connect(self.grid_spin.setEnabled)
        self.opacity_slider.valueChanged.connect(self._update_opacity_label)
        self.defaults_button.clicked.connect(self._restore_defaults)
        buttons.accepted.connect(self._save_and_accept)
        buttons.rejected.connect(self.reject)
        self.grid_spin.setEnabled(self.snap_check.isChecked())
        self._update_opacity_label()

    def _update_opacity_label(self) -> None:
        self.opacity_label.setText(f"{self.opacity_slider.value()}%")

    def _restore_defaults(self) -> None:
        defaults = Preferences()
        self.hide_native_check.setChecked(defaults.hide_native_icons)
        self.snap_check.setChecked(defaults.snap_to_grid)
        self.grid_spin.setValue(defaults.grid_size)
        self.auto_check.setChecked(defaults.auto_organize)
        self.startup_check.setChecked(defaults.start_with_windows)
        opacity = float(defaults.panel_opacity)
        self.opacity_slider.setValue(round(opacity * 100 if opacity <= 1.0 else opacity))

    def _save_and_accept(self) -> None:
        opacity: float | int
        if self._opacity_was_float:
            opacity = self.opacity_slider.value() / 100.0
        else:
            opacity = self.opacity_slider.value()
        self.preferences = replace(
            self.preferences,
            hide_native_icons=self.hide_native_check.isChecked(),
            snap_to_grid=self.snap_check.isChecked(),
            grid_size=self.grid_spin.value(),
            auto_organize=self.auto_check.isChecked(),
            start_with_windows=self.startup_check.isChecked(),
            panel_opacity=opacity,
        )
        self.accept()


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


__all__ = [
    "AboutDialog",
    "NewIslandDialog",
    "RenameDialog",
    "RuleEditDialog",
    "RulesDialog",
    "SettingsDialog",
    "SnapshotDialog",
    "TabDialog",
]

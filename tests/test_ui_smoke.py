from __future__ import annotations

import os
import shutil
import unittest
import uuid
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import deskisle.board as board_module  # noqa: E402
from deskisle.board import DesktopWindow  # noqa: E402
from deskisle.items import ItemListWidget  # noqa: E402
from deskisle.models import AppState, IslandState, ItemRef, PageState, TabState  # noqa: E402
from deskisle.storage import StateStore  # noqa: E402


class UiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.temp_root = Path(__file__).parent / ".test-work" / uuid.uuid4().hex
        self.temp_root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_root, ignore_errors=True)

    def test_board_islands_portal_collapse_and_reference_move(self) -> None:
        file_path = self.temp_root / "note.txt"
        file_path.write_text("safe", encoding="utf-8")
        second_path = self.temp_root / "second.txt"
        third_path = self.temp_root / "third.txt"
        second_path.write_text("second", encoding="utf-8")
        third_path.write_text("third", encoding="utf-8")
        normal_tab = TabState(title="普通", items=[])
        second_tab = TabState(title="第二标签", items=[])
        portal_tab = TabState(title="门户", portal_path=str(self.temp_root))
        normal = IslandState(title="普通岛", tabs=[normal_tab, second_tab], active_tab_id=normal_tab.id)
        portal = IslandState(title="文件视窗", x=420, tabs=[portal_tab], active_tab_id=portal_tab.id)
        page = PageState(title="测试页", islands=[normal, portal])
        state = AppState(pages=[page], current_page_id=page.id, loose_items=[ItemRef(path=str(file_path))])

        original_desktop_directories = board_module._desktop_directories
        board_module._desktop_directories = lambda: []
        try:
            window = DesktopWindow(state, StateStore(self.temp_root / "data"), demo_mode=True)
            window.resize(1100, 720)
            window.show()
            self.app.processEvents()

            self.assertEqual(len(window.islands), 2)
            portal_widget = window.islands[portal.id]
            self.assertGreaterEqual(portal_widget.portal_bar.y(), 70)
            self.assertGreater(portal_widget.item_list.y(), portal_widget.portal_bar.y())

            normal_widget = window.islands[normal.id]
            start_position = normal_widget.pos()
            QTest.mousePress(
                normal_widget.header,
                Qt.MouseButton.LeftButton,
                pos=QPoint(80, 20),
            )
            QTest.mouseMove(normal_widget.header, QPoint(117, 43), 30)
            self.app.processEvents()
            self.assertNotEqual(normal_widget.pos(), start_position)
            QTest.mouseRelease(
                normal_widget.header,
                Qt.MouseButton.LeftButton,
                pos=QPoint(117, 43),
            )
            self.assertEqual(normal_widget.x() % state.preferences.grid_size, 0)

            normal_widget.toggle_collapsed()
            self.assertTrue(normal.collapsed)
            QTest.qWait(240)
            self.assertEqual(normal_widget.height(), 44)
            normal_widget.toggle_collapsed()
            self.assertFalse(normal.collapsed)
            QTest.qWait(240)

            window._move_references(
                [str(file_path)], "__loose__", "__loose__", normal.id, normal_tab.id
            )
            self.assertEqual([item.path for item in normal_tab.items], [str(file_path)])
            self.assertEqual(state.loose_items, [])
            self.assertEqual(file_path.read_text(encoding="utf-8"), "safe")

            window._move_references(
                [str(file_path)], normal.id, normal_tab.id, normal.id, second_tab.id
            )
            self.assertEqual(normal_tab.items, [])
            self.assertEqual([item.path for item in second_tab.items], [str(file_path)])

            normal_tab.items = [
                ItemRef(path=str(file_path)),
                ItemRef(path=str(second_path)),
                ItemRef(path=str(third_path)),
            ]
            normal_widget._reorder_items(
                [str(file_path)], normal.id, normal_tab.id, 3
            )
            self.assertEqual(
                [item.path for item in normal_tab.items],
                [str(second_path), str(third_path), str(file_path)],
            )
            self.assertEqual(normal_tab.sort_mode, "manual")

            self.assertFalse(
                window.search.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
            )
            window._move_toolbar_by(QPoint(90, 55))
            search_local = window.surface.mapFromGlobal(window.search.pos())
            self.assertEqual(
                search_local.y(),
                window.toolbar.y() + window.toolbar.height() + 10,
            )
            self.assertEqual(
                search_local.x(),
                window.toolbar.x()
                + (window.toolbar.width() - window.search.width()) // 2,
            )
            window._finish_toolbar_move()

            window.toolbar.hide_button.click()
            self.assertTrue(window.groups_hidden)
            window.toolbar.hide_button.click()
            self.assertFalse(window.groups_hidden)
            self.app.processEvents()
            self.assertTrue(all(widget.isVisible() for widget in window.islands.values()))
            self.assertTrue(window.loose_view.isVisible())
            window.toolbar.focus_button.click()
            self.assertTrue(window.focus_mode)
            self.assertIsNone(window.search.parentWidget())
            self.assertTrue(window.search.windowFlags() & Qt.WindowType.Tool)
            window.toolbar.focus_button.click()
            self.assertFalse(window.focus_mode)

            window._closing_for_real = True
            window.close()
            self.app.processEvents()
        finally:
            board_module._desktop_directories = original_desktop_directories

    def test_icon_selection_plain_ctrl_and_shift(self) -> None:
        paths = []
        for index in range(4):
            path = self.temp_root / f"item-{index}.txt"
            path.write_text(str(index), encoding="utf-8")
            paths.append(str(path))
        view = ItemListWidget("loose", "loose")
        view.configure("loose", "loose", 40, False)
        view.resize(430, 220)
        view.set_paths([(path, "") for path in paths])
        view.show()
        self.app.processEvents()

        def click(index: int, modifier=Qt.KeyboardModifier.NoModifier) -> None:
            point = view.visualItemRect(view.item(index)).center()
            QTest.mouseClick(
                view.viewport(), Qt.MouseButton.LeftButton, modifier, point
            )
            self.app.processEvents()

        click(0)
        self.assertEqual(view.selected_paths(), [paths[0]])
        click(1)
        self.assertEqual(view.selected_paths(), [paths[1]])
        click(2, Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(view.selected_paths(), [paths[1], paths[2]])
        click(3, Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(view.selected_paths(), [paths[1], paths[2], paths[3]])
        click(0)
        self.assertEqual(view.selected_paths(), [paths[0]])

        # Dragging transparent space in the desktop-wide loose view must not
        # invoke QListView's rubber-band selection or leave mouse capture set.
        blank = QPoint(view.viewport().width() - 8, view.viewport().height() - 8)
        QTest.mousePress(view.viewport(), Qt.MouseButton.LeftButton, pos=blank)
        QTest.mouseMove(view.viewport(), QPoint(4, 4), 20)
        QTest.mouseRelease(
            view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(4, 4)
        )
        self.app.processEvents()
        self.assertEqual(view.selected_paths(), [])
        view.close()


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QEvent, QObject, QRect  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from deskisle.board import DesktopWindow  # noqa: E402
from deskisle.island import IslandWidget, CONTENT_TOP  # noqa: E402
from deskisle.motion import COLLAPSE_MS  # noqa: E402
from deskisle.models import AppState, IslandState, ItemRef, PageState, Rule, TabState  # noqa: E402
from deskisle.storage import StateStore  # noqa: E402


class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.root = Path(__file__).parent / '.test-work' / uuid4().hex
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root)

    def test_animation_reversal_does_not_resize_every_frame_or_lose_height(self):
        state = IslandState(width=400, height=480, tabs=[TabState()])
        widget = IslandWidget(state, desktop_window=True)
        widget.show()
        self.app.processEvents()
        widget.toggle_collapsed()

        class Counter(QObject):
            resizes = 0

            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Resize:
                    self.resizes += 1
                return False

        counter = Counter()
        widget.installEventFilter(counter)
        # Drive the tween to a fixed mid-collapse point instead of racing a wall
        # clock: on a fast machine the whole animation can finish inside qWait,
        # which then indexes pixels outside the shrunken window.
        widget._collapse_tween.stop()
        widget._animate_progress(0.5)
        self.app.processEvents()
        self.assertEqual(counter.resizes, 0)
        self.assertGreaterEqual(widget._visual_height, 44)
        self.assertLessEqual(widget._visual_height, 480)
        self.assertEqual(widget.grab().toImage().pixelColor(20, 470).alpha(), 0)
        widget.toggle_collapsed()
        QTest.qWait(COLLAPSE_MS + 100)
        self.assertEqual(widget.height(), 480)
        self.assertEqual(state.height, 480)
        self.assertFalse(state.collapsed)
        self.assertLessEqual(counter.resizes, 1)
        self.assertLess(widget.tabs_row.geometry().bottom(), CONTENT_TOP - 4)
        widget.close()

    def test_refresh_reuses_raster_icons_and_sort_direction_roundtrips(self):
        file = self.root / 'test.txt'
        file.write_text('test')
        tab = TabState(items=[ItemRef(path=str(file))], sort_descending=True)
        widget = IslandWidget(IslandState(tabs=[tab]))
        icon = widget.item_list.item(0).icon().cacheKey()
        with patch.object(widget.item_list, '_file_icon', side_effect=AssertionError('re-extracted icon')):
            widget.refresh_items()
        self.assertEqual(widget.item_list.item(0).icon().cacheKey(), icon)
        self.assertTrue(TabState.from_dict(tab.to_dict()).sort_descending)
        widget.close()

    def test_search_window_has_transparent_outer_corners(self):
        window = DesktopWindow(AppState(pages=[PageState()]), StateStore(self.root / 'data'), demo_mode=True)
        window.search.show()
        self.app.processEvents()
        pixels = window.search.grab().toImage()
        self.assertEqual(pixels.pixelColor(0, 0).alpha(), 0)
        self.assertGreater(pixels.pixelColor(20, 20).alpha(), 0)
        window.close()

    def test_auto_rules_can_deliver_to_another_scene(self):
        file = self.root / 'note.txt'
        file.write_text('test')
        target = IslandState(tabs=[TabState()])
        first, second = PageState(), PageState(islands=[target])
        state = AppState(pages=[first, second], current_page_id=first.id,
                         rules=[Rule(condition='extension', value='.txt', target_island_id=target.id)])
        window = DesktopWindow(state, StateStore(self.root / 'data'), demo_mode=True)
        window._desktop_dirs = [self.root]
        window.import_new_desktop_items(initial=True)
        self.assertEqual([item.path for item in target.tabs[0].items], [str(file)])
        self.assertFalse(state.loose_items)
        window.close()

    @unittest.skipUnless(os.name == 'nt', 'Windows Shell integration')
    def test_native_menu_exposes_runas_and_extended_interface(self):
        from deskisle.shell_menu import probe_menu
        result = probe_menu([str(Path(os.environ['WINDIR']) / 'System32/notepad.exe')])
        self.assertIn('runas', result['verbs'])
        self.assertTrue(result['extended_menu'])

    def test_deleted_desktop_references_removed_across_scenes_and_saved(self):
        desktop = self.root / 'Desktop'
        desktop.mkdir()
        deleted = desktop / 'deleted.txt'
        kept = desktop / 'kept.txt'
        kept.write_text('keep')
        offline = self.root / 'offline' / 'document.txt'
        tab = TabState(items=[ItemRef(path=str(deleted)), ItemRef(path=str(kept)), ItemRef(path=str(offline))])
        state = AppState(pages=[PageState(), PageState(islands=[IslandState(tabs=[tab])])],
                         loose_items=[ItemRef(path=str(deleted))])
        window = DesktopWindow(state, StateStore(self.root / 'data'), demo_mode=True)
        window._desktop_dirs = [desktop, offline.parent]
        window.import_new_desktop_items()
        self.assertEqual([r.path for r in tab.items], [str(kept), str(offline)])
        self.assertEqual(state.loose_items, [])
        window.save_state()
        self.assertEqual(len(window.store.load().pages[1].islands[0].tabs[0].items), 2)
        window._remove_unavailable_references([str(kept), str(offline)])
        self.assertEqual([r.path for r in tab.items], [str(kept)])
        window.close()

    def test_restore_and_arrange_use_real_monitor_work_areas(self):
        islands = [IslandState(x=4000, y=-500, width=500, height=450, tabs=[TabState()]) for _ in range(4)]
        window = DesktopWindow(AppState(pages=[PageState(islands=islands)]), StateStore(self.root / 'data'), demo_mode=True)
        areas = [QRect(-1280, 100, 1280, 900), QRect(0, 0, 1920, 1040)]
        with patch.object(window, '_screen_areas', return_value=areas):
            window.state.preferences.toolbar_x = 6000
            window.restore_positions()
            for island in islands:
                self.assertTrue(any(a.contains(QRect(island.x, island.y, island.width, island.height)) for a in areas))
            self.assertTrue(any(a.contains(window.toolbar.geometry()) for a in areas))
            window.auto_arrange()
            rectangles = [QRect(i.x, i.y, i.width, i.height) for i in islands]
            for index, rect in enumerate(rectangles):
                self.assertTrue(any(a.contains(rect) for a in areas))
                self.assertFalse(any(rect.intersects(other) for other in rectangles[index + 1:]))
            with patch.object(window, '_screen_areas', return_value=[QRect(0, 0, 1024, 720)]):
                window.restore_positions()
                for island in islands:
                    self.assertTrue(QRect(0, 0, 1024, 720).contains(QRect(island.x, island.y, island.width, island.height)))
        window.close()

"""Arrangement mode, move animations and page transitions at window level."""

from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from deskisle import grid_layout  # noqa: E402
from deskisle.board import DesktopWindow  # noqa: E402
from deskisle.models import AppState, IslandState, PageState, Preferences  # noqa: E402
from deskisle.storage import StateStore  # noqa: E402


class _Workspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.root = Path(__file__).parent / ".test-work" / uuid4().hex
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _window(self, islands: list[IslandState], pages: int = 1, **prefs) -> DesktopWindow:
        page = PageState(title="页", islands=islands)
        extra = [PageState(title=f"页{i}", islands=[IslandState(title=f"岛{i}")])
                 for i in range(1, pages)]
        state = AppState(pages=[page, *extra], current_page_id=page.id)
        for key, value in prefs.items():
            setattr(state.preferences, key, value)
        window = DesktopWindow(state, StateStore(self.root / "data"), demo_mode=True)
        window.resize(1400, 900)
        window.show()
        self.app.processEvents()
        return window

    @staticmethod
    def _settle(window: DesktopWindow) -> None:
        """Let running tweens finish so assertions see final geometry."""

        for widget in window.islands.values():
            tween = getattr(widget, "_grid_tween", None)
            if tween is not None:
                tween.finish()
        window.apply_grid_layout(animate=False)
        QApplication.processEvents()


class AutoLayoutTests(_Workspace):
    def test_toggle_on_assigns_levels_and_places_islands(self) -> None:
        islands = [IslandState(title=f"岛{i}", width=380, height=300) for i in range(3)]
        window = self._window(islands)
        try:
            self.assertFalse(window.is_auto_layout())
            window.set_auto_layout(True)
            self.assertTrue(window.state.preferences.auto_layout)
            for island in islands:
                self.assertIn(island.size_level, grid_layout.SIZE_LEVELS)
            self._settle(window)
            rects = window.grid_rects()
            self.assertEqual(len(rects), len(islands))
            for island, rect in zip(islands, rects):
                self.assertEqual((island.x, island.y), (rect.x(), rect.y()))
        finally:
            window.close()

    def test_placement_is_persisted_so_the_board_survives_a_restart(self) -> None:
        islands = [IslandState(title="A", size_level=grid_layout.LEVEL_HALF),
                   IslandState(title="B", size_level=grid_layout.LEVEL_HALF)]
        window = self._window(islands, auto_layout=True)
        try:
            self._settle(window)
            window.save_state()
            positions = {(i.grid_col, i.grid_row) for i in islands}
            self.assertEqual(len(positions), 2)
            reloaded = window.store.load()
            saved = reloaded.pages[0].islands
            self.assertEqual({(i.grid_col, i.grid_row) for i in saved}, positions)
        finally:
            window.close()

    def test_gaps_are_filled_after_turning_the_mode_on(self) -> None:
        # Mixed sizes used to leave a void in the middle of the page.
        islands = [
            IslandState(title="小", size_level=grid_layout.LEVEL_QUARTER),
            IslandState(title="大", size_level=grid_layout.LEVEL_HALF),
            IslandState(title="中", size_level=grid_layout.LEVEL_THIRD),
        ]
        window = self._window(islands, auto_layout=True)
        try:
            self._settle(window)
            placements = window._grid_placements(window.current_page())
            for index, placement in enumerate(placements):
                others = placements[:index] + placements[index + 1:]
                if placement.row > 0:
                    up = grid_layout.Placement(placement.col, placement.row - 1,
                                               placement.cols, placement.rows)
                    self.assertTrue(grid_layout.collides(others, up),
                                    f"island {index} left a gap above it")
        finally:
            window.close()

    def test_drag_moves_an_island_to_the_dropped_slot(self) -> None:
        islands = [IslandState(title=n, size_level=grid_layout.LEVEL_QUARTER)
                   for n in ("A", "B", "C", "D")]
        window = self._window(islands, auto_layout=True)
        try:
            self._settle(window)
            page = window.current_page()
            before = list(window._grid_placements(page))
            widget = window.islands[islands[0].id]
            window._grid_interaction_started()
            # Drag A towards D's slot.
            rects = window.grid_rects()
            widget.move_on_board(rects[3].topLeft())
            window._grid_interaction_finished(widget)
            self._settle(window)
            after = window._grid_placements(page)
            self.assertNotEqual(before[0], after[0], "the dragged island did not move")
            # No island keeps overlapping another.
            for index, placement in enumerate(after):
                others = after[:index] + after[index + 1:]
                self.assertFalse(grid_layout.collides(others, placement))
        finally:
            window.close()

    def test_drop_never_stacks_two_islands(self) -> None:
        islands = [IslandState(title=n, size_level=grid_layout.LEVEL_HALF)
                   for n in ("A", "B")]
        window = self._window(islands, auto_layout=True)
        try:
            self._settle(window)
            page = window.current_page()
            widget = window.islands[islands[1].id]
            window._grid_interaction_started()
            # Drop B exactly on top of A.
            widget.move_on_board(window.grid_rects()[0].topLeft())
            window._grid_interaction_finished(widget)
            self._settle(window)
            placements = window._grid_placements(page)
            self.assertFalse(grid_layout.collides([placements[0]], placements[1]))
        finally:
            window.close()

    def test_swap_mode_trades_positions_with_the_covered_island(self) -> None:
        islands = [IslandState(title=n, size_level=grid_layout.LEVEL_QUARTER)
                   for n in ("A", "B")]
        window = self._window(islands, auto_layout=True, grid_move_mode="swap")
        try:
            self._settle(window)
            page = window.current_page()
            first = window.islands[islands[0].id]
            window._grid_interaction_started()
            first.move_on_board(window.grid_rects()[1].topLeft())
            window._grid_interaction_finished(first)
            self._settle(window)
            # A took B's slot and B took A's, so neither sits where it started.
            placements = window._grid_placements(page)
            self.assertNotEqual((placements[0].col, placements[0].row), (0, 0))
            self.assertFalse(grid_layout.collides([placements[0]], placements[1]))
        finally:
            window.close()

    def test_reorder_mode_lets_the_board_refill(self) -> None:
        islands = [IslandState(title=n, size_level=grid_layout.LEVEL_QUARTER)
                   for n in ("A", "B", "C")]
        window = self._window(islands, auto_layout=True, grid_move_mode="reorder")
        try:
            self._settle(window)
            page = window.current_page()
            widget = window.islands[islands[0].id]
            window._grid_interaction_started()
            widget.move_on_board(window.grid_rects()[2].topLeft())
            window._grid_interaction_finished(widget)
            self._settle(window)
            placements = window._grid_placements(page)
            for index, placement in enumerate(placements):
                others = placements[:index] + placements[index + 1:]
                self.assertFalse(grid_layout.collides(others, placement))
        finally:
            window.close()

    def test_cycle_level_grows_the_island(self) -> None:
        islands = [IslandState(title="岛", size_level=grid_layout.LEVEL_HALF)]
        window = self._window(islands, auto_layout=True)
        try:
            self._settle(window)
            before = (islands[0].width, islands[0].height)
            window.cycle_island_level(islands[0].id)
            self.assertEqual(islands[0].size_level, grid_layout.LEVEL_FULL)
            self._settle(window)
            self.assertNotEqual(before, (islands[0].width, islands[0].height))
        finally:
            window.close()

    def test_move_animation_runs_and_lands_on_target(self) -> None:
        islands = [IslandState(title=n, size_level=grid_layout.LEVEL_QUARTER)
                   for n in ("A", "B", "C", "D")]
        window = self._window(islands, auto_layout=True)
        try:
            self._settle(window)
            page = window.current_page()
            dragged = window.islands[islands[0].id]
            target = window.grid_rects()[3]
            window._grid_interaction_started()
            dragged.move_on_board(target.topLeft())
            window._grid_interaction_finished(dragged)
            # The dragged island is already under the pointer, so it settles
            # instantly; the island it displaced is the one that glides.
            displaced = [w for w in window.islands.values() if w is not dragged]
            self.assertTrue(
                any(getattr(w, "_grid_tween", None) is not None for w in displaced),
                "the displaced island should animate to its new slot",
            )
            self._settle(window)
            placements = window._grid_placements(page)
            self.assertEqual(len(placements), 4)
            for index, placement in enumerate(placements):
                others = placements[:index] + placements[index + 1:]
                self.assertFalse(grid_layout.collides(others, placement))
        finally:
            window.close()

    def test_dragged_island_settles_without_a_jump(self) -> None:
        """A drop must not animate the island the pointer is holding."""

        islands = [IslandState(title=n, size_level=grid_layout.LEVEL_QUARTER)
                   for n in ("A", "B")]
        window = self._window(islands, auto_layout=True)
        try:
            self._settle(window)
            dragged = window.islands[islands[0].id]
            window._grid_interaction_started()
            dragged.move_on_board(window.grid_rects()[1].topLeft())
            window._grid_interaction_finished(dragged)
            self.assertIsNone(
                getattr(dragged, "_grid_tween", None),
                "the island already under the pointer should not animate away",
            )
        finally:
            window.close()

    def test_geometry_tween_interpolates_and_finishes(self) -> None:
        from PySide6.QtCore import QEventLoop, QTimer

        from deskisle import motion

        seen: list[tuple[float, float, float, float]] = []
        tween = motion.GeometryTween(None, lambda *a: seen.append(a), 250)
        tween.to((0.0, 0.0, 100.0, 100.0), (400.0, 200.0, 150.0, 150.0))
        # QVariantAnimation is driven by the event loop's timers, so a real
        # loop is required here — processEvents() alone never advances it.
        loop = QEventLoop()
        QTimer.singleShot(500, loop.quit)
        loop.exec()
        self.assertGreater(len(seen), 2, "the tween must emit intermediate frames")
        self.assertEqual(tuple(round(v, 1) for v in seen[-1]), (400.0, 200.0, 150.0, 150.0))
        self.assertFalse(tween.is_running())

    def test_geometry_tween_moves_monotonically(self) -> None:
        from PySide6.QtCore import QEventLoop, QTimer

        from deskisle import motion

        xs: list[float] = []
        tween = motion.GeometryTween(None, lambda x, y, w, h: xs.append(x), 200)
        tween.to((0.0, 0.0, 100.0, 100.0), (300.0, 0.0, 100.0, 100.0))
        loop = QEventLoop()
        QTimer.singleShot(400, loop.quit)
        loop.exec()
        self.assertGreater(len(xs), 2)
        self.assertTrue(all(xs[i] <= xs[i + 1] + 0.01 for i in range(len(xs) - 1)),
                        f"motion should be monotonic, got {xs}")

    def test_geometry_tween_is_instant_when_motion_is_reduced(self) -> None:
        from deskisle import motion

        seen: list[tuple[float, float, float, float]] = []
        previous = motion.reduce_motion()
        motion.set_reduce_motion(True)
        try:
            tween = motion.GeometryTween(None, lambda *a: seen.append(a), 200)
            tween.to((0.0, 0.0, 100.0, 100.0), (300.0, 200.0, 100.0, 100.0))
            self.assertEqual(seen, [(300.0, 200.0, 100.0, 100.0)])
            self.assertFalse(tween.is_running())
        finally:
            motion.set_reduce_motion(previous)

    def test_turning_mode_off_releases_the_resize_grip(self) -> None:
        islands = [IslandState(title="岛")]
        window = self._window(islands, auto_layout=True)
        try:
            self._settle(window)
            widget = window.islands[islands[0].id]
            self.assertTrue(widget._grid_locked)
            window.set_auto_layout(False)
            self.assertFalse(window.state.preferences.auto_layout)
        finally:
            window.close()

    def test_grid_geometry_roundtrip(self) -> None:
        window = self._window([IslandState(title="岛")], auto_layout=True)
        try:
            widget = window.islands[window.current_page().islands[0].id]
            start = widget.grid_geometry()
            widget.apply_grid_geometry(start[0] + 20, start[1] + 10, start[2], start[3])
            moved = widget.grid_geometry()
            self.assertAlmostEqual(moved[0], start[0] + 20, delta=1)
        finally:
            window.close()


class PageSwitchTests(_Workspace):
    """Switching scene pages is a plain hard cut.

    Animating it was tried and removed: every island is its own native desktop
    window, so a cross-fade or slide has to be drawn on a separate overlay
    window, and the Windows compositor cannot keep the two in step.  The result
    was stray frames and flicker rather than motion, so the switch is instant.
    """

    def test_switch_page_changes_the_page(self) -> None:
        window = self._window([IslandState(title="岛")], pages=2)
        try:
            first = window.current_page().title
            window.switch_page(1)
            self.assertNotEqual(window.current_page().title, first)
            window.switch_page(-1)
            self.assertEqual(window.current_page().title, first)
        finally:
            window.close()

    def test_switch_page_rebuilds_the_islands(self) -> None:
        window = self._window([IslandState(title="甲")], pages=2)
        try:
            window.demo_mode = False
            window.surface.demo_mode = False
            self.app.processEvents()
            window.rebuild_page()
            self.app.processEvents()
            first = list(window.islands.values())[0].state.title
            window.switch_page(1)
            self.app.processEvents()
            second = list(window.islands.values())[0].state.title
            self.assertNotEqual(first, second)
        finally:
            window.close()

    def test_switch_page_needs_more_than_one_page(self) -> None:
        window = self._window([IslandState(title="岛")], pages=1)
        try:
            page_id = window.state.current_page_id
            window.switch_page(1)
            self.assertEqual(window.state.current_page_id, page_id)
        finally:
            window.close()

    def test_no_animation_overlay_is_created(self) -> None:
        window = self._window([IslandState(title="岛")], pages=2)
        try:
            window.demo_mode = False
            window.surface.demo_mode = False
            self.app.processEvents()
            window.rebuild_page()
            self.app.processEvents()
            window.switch_page(1)
            self.app.processEvents()
            self.assertIsNone(getattr(window, "_page_overlay", None))
            self.assertIsNone(getattr(window, "_page_animation", None))
        finally:
            window.close()

    def test_snapshot_uses_board_coordinates_not_screen_coordinates(self) -> None:
        """The snapshot helper is still used to detect an empty board."""

        from deskisle import motion

        original = motion.reduce_motion
        motion.reduce_motion = lambda: False
        window = self._window([IslandState(title="岛")], pages=2)
        try:
            window.demo_mode = False
            window.surface.demo_mode = False
            self.app.processEvents()
            window.rebuild_page()
            self.app.processEvents()
            window.apply_grid_layout(animate=False)
            self.app.processEvents()
            snapshot = window._snapshot_board()
            self.assertIsNotNone(snapshot)
            widget = next(iter(window.islands.values()))
            if widget.desktop_window:
                self.assertNotEqual(widget.geometry().topLeft(),
                                    widget.board_position(),
                                    "the test needs the two coordinate systems to differ")
        finally:
            motion.reduce_motion = original
            window.close()

    def test_board_snapshot_keeps_gaps_transparent(self) -> None:
        from deskisle import motion

        original = motion.reduce_motion
        motion.reduce_motion = lambda: False
        window = self._window([IslandState(title="岛")], pages=2)
        try:
            window.demo_mode = False
            window.surface.demo_mode = False
            self.app.processEvents()
            window.rebuild_page()
            self.app.processEvents()
            window.apply_grid_layout(animate=False)
            self.app.processEvents()
            snapshot = window._snapshot_board()
            self.assertIsNotNone(snapshot)
            image = snapshot.toImage()
            transparent = 0
            total = 0
            for y in range(0, image.height(), 6):
                for x in range(0, image.width(), 6):
                    total += 1
                    if ((image.pixel(x, y) >> 24) & 0xFF) == 0:
                        transparent += 1
            self.assertGreater(transparent / max(1, total), 0.2,
                               "the board paints nothing behind its islands")
        finally:
            motion.reduce_motion = original
            window.close()

    def test_snapshot_excludes_the_toolbar(self) -> None:
        from deskisle import motion

        original = motion.reduce_motion
        motion.reduce_motion = lambda: False
        window = self._window([IslandState(title="岛")], pages=2)
        try:
            window.demo_mode = False
            window.surface.demo_mode = False
            self.app.processEvents()
            window.rebuild_page()
            self.app.processEvents()
            window.apply_grid_layout(animate=False)
            self.app.processEvents()
            snapshot = window._snapshot_board()
            self.assertIsNotNone(snapshot)
            image = snapshot.toImage()
            box = window.toolbar.geometry()
            opaque = 0
            for y in range(box.top(), box.bottom() + 1, 3):
                for x in range(box.left(), box.right() + 1, 3):
                    if 0 <= x < image.width() and 0 <= y < image.height():
                        if ((image.pixel(x, y) >> 24) & 0xFF) > 250:
                            opaque += 1
            self.assertEqual(opaque, 0, "the toolbar must not be baked into the snapshot")
        finally:
            motion.reduce_motion = original
            window.close()


class PreferencesTests(_Workspace):
    def test_new_preferences_roundtrip(self) -> None:
        prefs = Preferences(
            auto_layout=True,
            grid_move_mode="reorder",
            edge_switch_enabled=False,
            edge_switch_width=40,
            edge_switch_delay_ms=600,
        )
        restored = Preferences.from_dict(prefs.to_dict())
        self.assertTrue(restored.auto_layout)
        self.assertEqual(restored.grid_move_mode, "reorder")
        self.assertFalse(restored.edge_switch_enabled)
        self.assertEqual(restored.edge_switch_width, 40)
        self.assertEqual(restored.edge_switch_delay_ms, 600)

    def test_legacy_state_without_new_fields_loads(self) -> None:
        raw = Preferences().to_dict()
        for key in ("auto_layout", "grid_move_mode", "edge_switch_enabled",
                    "edge_switch_width", "edge_switch_delay_ms"):
            raw.pop(key)
        restored = Preferences.from_dict(raw)
        self.assertFalse(restored.auto_layout)
        self.assertEqual(restored.grid_move_mode, "swap")
        self.assertTrue(restored.edge_switch_enabled)


    def test_unknown_values_fall_back(self) -> None:
        self.assertEqual(Preferences.from_dict({"grid_move_mode": "bogus"}).grid_move_mode, "swap")


    def test_island_board_position_survives_roundtrip(self) -> None:
        island = IslandState(title="岛", size_level="quarter", grid_col=6, grid_row=3)
        restored = IslandState.from_dict(island.to_dict())
        self.assertEqual((restored.grid_col, restored.grid_row), (6, 3))
        self.assertEqual(restored.size_level, "quarter")

    def test_island_without_board_position_defaults_to_unplaced(self) -> None:
        island = IslandState.from_dict({"title": "旧存档"})
        self.assertEqual((island.grid_col, island.grid_row), (-1, -1))
        self.assertEqual(island.size_level, grid_layout.DEFAULT_SIZE_LEVEL)


class EdgeSwitchTests(_Workspace):
    def test_edge_timer_off_for_a_single_page(self) -> None:
        window = self._window([IslandState(title="岛")], edge_switch_enabled=True)
        try:
            self.assertFalse(window._edge_timer.isActive())
        finally:
            window.close()

    def test_edge_timer_off_when_disabled(self) -> None:
        window = self._window([IslandState(title="岛")], pages=2, edge_switch_enabled=False)
        try:
            self.assertFalse(window._edge_timer.isActive())
        finally:
            window.close()

    def test_edge_switching_never_runs_in_demo_mode(self) -> None:
        window = self._window([IslandState(title="岛")], pages=2)
        try:
            window._update_edge_timer()
            self.assertFalse(window._edge_timer.isActive())
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()

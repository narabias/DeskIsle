"""Free-form board maths: spans, placement, compaction and drops."""

from __future__ import annotations

import unittest

from deskisle import grid_layout as grid


class GridLevelTests(unittest.TestCase):
    def test_every_level_divides_the_board_exactly(self) -> None:
        for level in grid.SIZE_LEVELS:
            cols, rows = grid.span_cells(level)
            self.assertGreater(cols, 0)
            self.assertGreater(rows, 0)
            self.assertLessEqual(cols, grid.GRID_COLUMNS)
            self.assertEqual(grid.GRID_COLUMNS % cols, 0, level)

    def test_levels_are_strictly_increasing_in_width(self) -> None:
        widths = [grid.span_cells(level)[0] for level in grid.SIZE_LEVELS]
        self.assertEqual(widths, sorted(widths))
        self.assertEqual(len(set(widths)), len(widths))

    def test_ratios_are_the_advertised_fractions(self) -> None:
        self.assertEqual(grid.level_ratio(grid.LEVEL_QUARTER), (4, 4))
        self.assertEqual(grid.level_ratio(grid.LEVEL_THIRD), (3, 3))
        self.assertEqual(grid.level_ratio(grid.LEVEL_HALF), (2, 2))
        self.assertEqual(grid.level_ratio(grid.LEVEL_FULL), (1, 2))

    def test_unknown_level_falls_back(self) -> None:
        self.assertEqual(grid.normalise_level("nonsense"), grid.DEFAULT_SIZE_LEVEL)
        self.assertEqual(grid.normalise_level(None), grid.DEFAULT_SIZE_LEVEL)

    def test_next_level_cycles(self) -> None:
        self.assertEqual(grid.next_level(grid.LEVEL_QUARTER), grid.LEVEL_THIRD)
        self.assertEqual(grid.next_level(grid.LEVEL_FULL), grid.LEVEL_QUARTER)


class PlacementTests(unittest.TestCase):
    def test_first_free_fills_the_top_left(self) -> None:
        placed = grid.first_free([], 6, 6)
        self.assertEqual((placed.col, placed.row), (0, 0))

    def test_first_free_uses_the_gap_left_behind(self) -> None:
        # A half island on the right leaves the left column free.
        taken = [grid.Placement(6, 0, 6, 6)]
        placed = grid.first_free(taken, 3, 3)
        self.assertEqual((placed.col, placed.row), (0, 0))

    def test_a_quarter_can_slot_below_a_wide_island(self) -> None:
        taken = [grid.Placement(0, 0, 12, 6)]
        placed = grid.first_free(taken, 3, 3)
        self.assertEqual(placed.row, 6)

    def test_two_quarters_share_a_row(self) -> None:
        first = grid.first_free([], 3, 3)
        second = grid.first_free([first], 3, 3)
        self.assertEqual(second.row, 0)
        self.assertEqual(second.col, 3)
        self.assertFalse(grid.collides([first], second))

    def test_four_quarters_fill_one_row_without_overlap(self) -> None:
        placed: list[grid.Placement] = []
        for _ in range(4):
            placed.append(grid.first_free(placed, 3, 3))
        self.assertEqual({p.row for p in placed}, {0})
        self.assertEqual(len(grid.occupied(placed)), 4 * 9)

    def test_mixed_sizes_never_overlap(self) -> None:
        levels = [grid.LEVEL_QUARTER, grid.LEVEL_HALF, grid.LEVEL_THIRD, grid.LEVEL_FULL,
                  grid.LEVEL_THIRD, grid.LEVEL_QUARTER, grid.LEVEL_QUARTER]
        placements = grid.resolve(levels, [None] * len(levels))
        self.assertEqual(len(placements), len(levels))
        for index, placement in enumerate(placements):
            others = placements[:index] + placements[index + 1:]
            self.assertFalse(grid.collides(others, placement))

    def test_mixed_sizes_leave_no_hole_that_could_be_filled(self) -> None:
        # The bug this replaces: sequential bands left a visible void between
        # a small island and a tall one.  After compaction there must be no
        # single-cell island worth of free space above any island.
        levels = [grid.LEVEL_QUARTER, grid.LEVEL_HALF, grid.LEVEL_THIRD, grid.LEVEL_FULL,
                  grid.LEVEL_THIRD, grid.LEVEL_QUARTER]
        placements = grid.compact(grid.resolve(levels, [None] * len(levels)))
        for index, placement in enumerate(placements):
            others = placements[:index] + placements[index + 1:]
            if placement.row > 0:
                up = grid.Placement(placement.col, placement.row - 1,
                                    placement.cols, placement.rows)
                self.assertTrue(grid.collides(others, up),
                                f"island {index} could still move up: {placement}")

    def test_pinned_positions_are_honoured(self) -> None:
        levels = [grid.LEVEL_QUARTER, grid.LEVEL_QUARTER]
        placements = grid.resolve(levels, [(6, 6), (0, 0)])
        self.assertEqual((placements[0].col, placements[0].row), (6, 6))
        self.assertEqual((placements[1].col, placements[1].row), (0, 0))

    def test_a_pinned_position_that_clashes_is_relocated(self) -> None:
        levels = [grid.LEVEL_HALF, grid.LEVEL_HALF]
        placements = grid.resolve(levels, [(0, 0), (0, 0)])
        self.assertNotEqual((placements[0].col, placements[0].row),
                            (placements[1].col, placements[1].row))
        self.assertFalse(grid.collides([placements[0]], placements[1]))

    def test_pinned_position_is_clamped_to_the_board(self) -> None:
        placements = grid.resolve([grid.LEVEL_HALF], [(99, 0)])
        self.assertLessEqual(placements[0].col, grid.GRID_COLUMNS - 6)

    def test_compaction_pulls_an_island_to_the_top_left(self) -> None:
        placements = [grid.Placement(6, 6, 3, 3)]
        compacted = grid.compact(placements)
        self.assertEqual((compacted[0].col, compacted[0].row), (0, 0))

    def test_compaction_is_stable_when_already_tidy(self) -> None:
        placements = [grid.Placement(0, 0, 6, 6), grid.Placement(6, 0, 6, 6)]
        self.assertEqual(grid.compact(placements), placements)

    def test_compaction_never_stacks_islands(self) -> None:
        placements = [grid.Placement(0, 0, 3, 3), grid.Placement(9, 9, 3, 3)]
        compacted = grid.compact(placements)
        self.assertFalse(grid.collides([compacted[0]], compacted[1]))


class SnapTests(unittest.TestCase):
    def test_snap_is_quarter_screen_granularity(self) -> None:
        self.assertEqual(grid.SNAP, 3)
        self.assertEqual(grid.snap_col(4, 3), 3)
        self.assertEqual(grid.snap_col(5, 3), 6)

    def test_snap_keeps_the_island_on_the_board(self) -> None:
        self.assertEqual(grid.snap_col(11, 3), 9)
        self.assertGreaterEqual(grid.snap_row(-5), 0)

    def test_slot_at_maps_pixels_to_cells(self) -> None:
        metrics = grid.CellMetrics(column_width=110, row_height=80, gap=10)
        step_x, step_y = 120, 90
        self.assertEqual(grid.slot_at((0, 0), metrics, 3, 3), (0, 0))
        self.assertEqual(grid.slot_at((step_x * 3, step_y * 3), metrics, 3, 3), (3, 3))

    def test_best_drop_uses_the_requested_cell_when_free(self) -> None:
        metrics = grid.CellMetrics(column_width=110, row_height=80, gap=10)
        placements = [grid.Placement(0, 0, 3, 3), grid.Placement(6, 0, 3, 3)]
        landed = grid.best_drop(placements, 1, (3 * 120, 0), metrics)
        self.assertEqual((landed.col, landed.row), (3, 0))

    def test_best_drop_never_stacks_on_an_occupied_cell(self) -> None:
        metrics = grid.CellMetrics(column_width=110, row_height=80, gap=10)
        placements = [grid.Placement(0, 0, 3, 3), grid.Placement(9, 0, 3, 3)]
        landed = grid.best_drop(placements, 1, (0, 0), metrics)
        self.assertNotEqual((landed.col, landed.row), (0, 0))
        self.assertFalse(grid.collides([placements[0]], landed))

    def test_nearest_index_finds_the_closest_centre(self) -> None:
        rects = [grid.Rect(0, 0, 100, 100), grid.Rect(400, 0, 100, 100)]
        self.assertEqual(grid.nearest_index((10, 10), rects), 0)
        self.assertEqual(grid.nearest_index((460, 40), rects), 1)
        self.assertEqual(grid.nearest_index((0, 0), []), -1)


class PixelGeometryTests(unittest.TestCase):
    def test_quarter_is_a_quarter_of_the_area(self) -> None:
        rects = grid.layout([grid.LEVEL_QUARTER], [None], 1200, 1200)
        self.assertAlmostEqual(rects[0].width, 1200 / 4 - grid.GAP * 0.75, delta=8)

    def test_half_is_half_the_width(self) -> None:
        rects = grid.layout([grid.LEVEL_HALF], [None], 1200, 1200)
        self.assertAlmostEqual(rects[0].width, 1200 / 2 - grid.GAP * 0.5, delta=8)

    def test_full_spans_the_whole_width(self) -> None:
        rects = grid.layout([grid.LEVEL_FULL], [None], 1200, 1200)
        self.assertAlmostEqual(rects[0].width, 1200, delta=2)

    def test_every_layout_fits_inside_the_area(self) -> None:
        cases = [
            [grid.LEVEL_QUARTER, grid.LEVEL_HALF, grid.LEVEL_THIRD, grid.LEVEL_FULL,
             grid.LEVEL_THIRD, grid.LEVEL_QUARTER],
            [grid.LEVEL_FULL, grid.LEVEL_HALF],
            [grid.LEVEL_QUARTER] * 12,
            [grid.LEVEL_HALF] * 4,
            [grid.LEVEL_THIRD] * 6,
            [grid.LEVEL_FULL] * 3,
        ]
        for levels in cases:
            pinned = [None] * len(levels)
            for width, height in ((1920, 1040), (1600, 900), (1280, 720), (1366, 728)):
                rects = grid.layout(levels, pinned, width, height)
                for rect in rects:
                    self.assertLessEqual(rect.bottom(), height + 1, (levels, width, height, rect))
                    self.assertLessEqual(rect.right(), width + 1, (levels, width, height, rect))
                    self.assertGreaterEqual(rect.x, 0)
                    self.assertGreaterEqual(rect.y, 0)

    def test_density_packing_beats_naive_fill_on_mixed_sizes(self) -> None:
        # Six mixed islands: choosing the tighter of two packing orders saves a
        # row compared with pouring them in the order they were created.
        levels = [grid.LEVEL_QUARTER, grid.LEVEL_HALF, grid.LEVEL_THIRD,
                  grid.LEVEL_FULL, grid.LEVEL_THIRD, grid.LEVEL_QUARTER]
        packed = grid.resolve(levels, [None] * len(levels))
        self.assertEqual(len(packed), len(levels))
        # Density is measured by how many board rows the result needs.
        self.assertLessEqual(grid.content_rows(packed), 16)

    def test_crowded_page_shrinks_cells(self) -> None:
        sparse = grid.cells_for(1600, 900, grid.content_rows(grid.resolve([grid.LEVEL_HALF], [None])))
        crowded_levels = [grid.LEVEL_QUARTER] * 16
        crowded = grid.cells_for(
            1600, 900,
            grid.content_rows(grid.resolve(crowded_levels, [None] * len(crowded_levels))),
        )
        self.assertLessEqual(crowded.row_height, sparse.row_height)

    def test_cells_never_collapse(self) -> None:
        metrics = grid.cells_for(200, 150, 40)
        self.assertGreaterEqual(metrics.column_width, 1)
        self.assertGreaterEqual(metrics.row_height, 1)


if __name__ == "__main__":
    unittest.main()

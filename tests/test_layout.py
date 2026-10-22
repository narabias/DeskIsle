"""Invariants of the pure layout engine (deskisle.layout) and monitor presets."""

from __future__ import annotations

import random
import unittest

from deskisle import layout as L
from deskisle.layout import Box, Rect
from deskisle.models import STATE_VERSION, AppState, IslandState, PageState
from deskisle.monitors import MonitorSpec, guest_pages, migrate_state, ensure_current_pages

GAP = 12
WORK = Rect(16, 72, 1888, 992)


def random_layout(rng: random.Random, count: int, work: Rect = WORK, gap: int = GAP,
                  min_w: int = L.MIN_W, min_h: int = L.MIN_H) -> list[Box]:
    boxes: list[Box] = []
    for index in range(count * 4):
        if len(boxes) >= count:
            break
        w = rng.randint(min_w, min_w + 260)
        h = rng.randint(min_h, min_h + 200)
        if rng.random() < 0.15:
            h = L.COLLAPSED_H
        found = L.nearest_position(w, h, rng.randint(work.x, work.right), rng.randint(work.y, work.bottom),
                                   [box.rect for box in boxes], work, gap)
        if found is None:
            continue
        mh = h if h == L.COLLAPSED_H else min_h
        boxes.append(Box("b{0}".format(index), Rect(found[0], found[1], w, h), min_w, mh,
                         fixed=rng.random() < 0.08))
    return boxes


def assert_valid(case: unittest.TestCase, rects: dict[str, Rect], work: Rect, gap: int = GAP,
                 boxes: list[Box] | None = None) -> None:
    items = list(rects.items())
    for index, (key, rect) in enumerate(items):
        case.assertTrue(work.contains(rect), "{0} {1} outside {2}".format(key, rect, work))
        for other_key, other in items[index + 1:]:
            case.assertFalse(L.too_close(rect, other, gap), "{0} {1} too close to {2} {3}".format(
                key, rect, other_key, other))
    if boxes:
        for box in boxes:
            rect = rects[box.id]
            case.assertGreaterEqual(rect.w, min(box.min_w, box.rect.w))
            case.assertGreaterEqual(rect.h, min(box.min_h, box.rect.h))


class GeometryTests(unittest.TestCase):
    def test_too_close_uses_gap_on_either_axis(self) -> None:
        a = Rect(0, 0, 100, 100)
        self.assertFalse(L.too_close(a, Rect(112, 0, 50, 50), 12))
        self.assertTrue(L.too_close(a, Rect(111, 0, 50, 50), 12))
        self.assertFalse(L.too_close(a, Rect(105, 112, 50, 50), 12))
        self.assertTrue(L.too_close(a, Rect(105, 105, 50, 50), 12))

    def test_nearest_position_is_exact_against_brute_force(self) -> None:
        rng = random.Random(7)
        work = Rect(0, 0, 90, 70)
        for _case in range(40):
            obstacles = []
            for _ in range(rng.randint(0, 5)):
                w, h = rng.randint(6, 30), rng.randint(6, 25)
                found = L.nearest_position(w, h, rng.randint(0, 90), rng.randint(0, 70), obstacles, work, 3)
                if found:
                    obstacles.append(Rect(found[0], found[1], w, h))
            w, h = rng.randint(5, 40), rng.randint(5, 30)
            tx, ty = rng.randint(-10, 100), rng.randint(-10, 80)
            result = L.nearest_position(w, h, tx, ty, obstacles, work, 3)
            best = None
            for x in range(work.x, work.right - w + 1):
                for y in range(work.y, work.bottom - h + 1):
                    if L.fits(Rect(x, y, w, h), obstacles, work, 3):
                        distance = (x - tx) ** 2 + (y - ty) ** 2
                        if best is None or distance < best:
                            best = distance
            if best is None:
                self.assertIsNone(result)
            else:
                self.assertIsNotNone(result)
                self.assertTrue(L.fits(Rect(result[0], result[1], w, h), obstacles, work, 3))
                self.assertEqual((result[0] - tx) ** 2 + (result[1] - ty) ** 2, best)

    def test_nearest_grid_position_snaps_inside_free_space(self) -> None:
        rng = random.Random(11)
        for _round in range(40):
            boxes = random_layout(rng, rng.randint(2, 9))
            obstacles = [box.rect for box in boxes]
            w, h = rng.randint(L.MIN_W, 420), rng.randint(L.MIN_H, 360)
            tx, ty = rng.randint(WORK.x, WORK.right), rng.randint(WORK.y, WORK.bottom)
            found = L.nearest_grid_position(w, h, tx, ty, obstacles, WORK, GAP, 8)
            plain = L.nearest_position(w, h, tx, ty, obstacles, WORK, GAP)
            self.assertEqual(found is None, plain is None)
            if found is None:
                continue
            self.assertTrue(L.fits(Rect(found[0], found[1], w, h), obstacles, WORK, GAP))
        # A free work area always yields a grid point near the target.
        self.assertEqual(L.nearest_grid_position(300, 200, 101, 203, [], WORK, GAP, 8), (104, 200))

    def test_largest_fit_respects_bounds(self) -> None:
        rng = random.Random(11)
        for _case in range(30):
            boxes = random_layout(rng, rng.randint(3, 12))
            obstacles = [box.rect for box in boxes]
            rect = L.largest_fit(L.MIN_W, L.MIN_H, 600, 500, obstacles, WORK, GAP)
            if rect is not None:
                self.assertTrue(L.fits(rect, obstacles, WORK, GAP))
                self.assertGreaterEqual(rect.w, L.MIN_W)
                self.assertLessEqual(rect.w, 600)


class PushTests(unittest.TestCase):
    def test_simple_push_moves_neighbour(self) -> None:
        a = Box("a", Rect(16, 72, 300, 200))
        b = Box("b", Rect(328, 72, 300, 200))
        result = L.resize_with_push([a, b], "a", Rect(16, 72, 400, 200), WORK, GAP)
        self.assertEqual(result.active, Rect(16, 72, 400, 200))
        self.assertEqual(result.rects["b"], Rect(428, 72, 300, 200))

    def test_push_shrinks_at_screen_edge_then_clamps(self) -> None:
        work = Rect(0, 0, 1000, 600)
        a = Box("a", Rect(0, 0, 400, 300))
        b = Box("b", Rect(412, 0, 400, 300))
        result = L.resize_with_push([a, b], "a", Rect(0, 0, 600, 300), work, GAP)
        self.assertEqual(result.active.w, 600)
        self.assertEqual(result.rects["b"].x, 612)
        self.assertEqual(result.rects["b"].right, 1000)
        result = L.resize_with_push([a, b], "a", Rect(0, 0, 950, 300), work, GAP)
        self.assertTrue(result.clamped)
        self.assertEqual(result.rects["b"].w, L.MIN_W)
        self.assertEqual(result.rects["b"].right, 1000)
        self.assertEqual(result.active.right + GAP, result.rects["b"].x)

    def test_random_resizes_keep_layout_valid(self) -> None:
        rng = random.Random(3)
        for _case in range(250):
            boxes = random_layout(rng, rng.randint(2, 14))
            if not boxes:
                continue
            active = rng.choice(boxes)
            if active.fixed:
                continue
            old = active.rect
            dl = rng.choice([0, 0, rng.randint(0, 500)])
            dr = rng.choice([0, rng.randint(0, 700)])
            dt = rng.choice([0, 0, rng.randint(0, 300)])
            db = rng.choice([0, rng.randint(0, 500)])
            if dl and dr:
                dl = 0
            if dt and db:
                dt = 0
            target = Rect(old.x - dl, old.y - dt, old.w + dl + dr, old.h + dt + db)
            result = L.resize_with_push(boxes, active.id, target, WORK, GAP)
            assert_valid(self, result.rects, WORK, GAP, boxes)
            for box in boxes:
                if box.fixed:
                    self.assertEqual(result.rects[box.id], box.rect)
            self.assertGreaterEqual(result.active.w, old.w)
            self.assertGreaterEqual(result.active.h, old.h)
            self.assertLessEqual(result.active.w, max(old.w, target.w))

    def test_free_extent_stops_at_gap(self) -> None:
        a = Box("a", Rect(16, 72, 300, 200))
        b = Box("b", Rect(500, 100, 300, 200))
        self.assertEqual(L.free_extent([a, b], "a", a.rect, "right", WORK, GAP), 488)
        self.assertEqual(L.free_extent([a, b], "a", a.rect, "bottom", WORK, GAP), WORK.bottom)

    def test_expand_pushes_down_or_relocates(self) -> None:
        rng = random.Random(5)
        for _case in range(150):
            boxes = random_layout(rng, rng.randint(2, 12))
            collapsed = [box for box in boxes if box.rect.h == L.COLLAPSED_H and not box.fixed]
            if not collapsed:
                continue
            box = collapsed[0]
            result = L.expand_with_push(boxes, box.id, 320, L.MIN_H, WORK, GAP)
            if result is None:
                continue
            assert_valid(self, result.rects, WORK, GAP)
            self.assertGreaterEqual(result.active.h, L.MIN_H)


class WholeLayoutTests(unittest.TestCase):
    def test_auto_arrange_is_valid_and_ordered(self) -> None:
        rng = random.Random(9)
        for _case in range(120):
            boxes = random_layout(rng, rng.randint(1, 16))
            arranged = L.auto_arrange(boxes, WORK, GAP)
            if arranged is None:
                continue
            assert_valid(self, arranged, WORK, GAP)
            for box in boxes:
                rect = arranged[box.id]
                self.assertLessEqual(rect.w, box.preferred[0])
                self.assertGreaterEqual(rect.w, box.min_w)

    def test_place_new_never_overlaps(self) -> None:
        rng = random.Random(13)
        for _case in range(120):
            boxes = random_layout(rng, rng.randint(0, 22))
            placed = L.place_new(boxes, L.DEFAULT_W, L.DEFAULT_H, L.MIN_W, L.MIN_H, WORK, GAP)
            if placed is None:
                arranged = L.auto_arrange(boxes + [Box("n", Rect(0, 0, L.MIN_W, L.MIN_H))], WORK, GAP)
                self.assertIsNone(arranged)
                continue
            rects = dict(placed.rects)
            rects["__new__"] = placed.rect
            assert_valid(self, rects, WORK, GAP)
            self.assertGreaterEqual(placed.rect.w, L.MIN_W)
            self.assertGreaterEqual(placed.rect.h, L.MIN_H)

    def test_full_screen_reports_no_room(self) -> None:
        work = Rect(0, 0, 500, 330)
        boxes = [Box("a", Rect(0, 0, 240, 330), 230, 300), Box("b", Rect(252, 0, 248, 330), 230, 300)]
        self.assertIsNone(L.place_new(boxes, 340, 270, 220, 150, work, GAP))

    def test_repair_fixes_overlaps(self) -> None:
        rng = random.Random(17)
        for _case in range(120):
            boxes = []
            for index in range(rng.randint(1, 8)):
                w, h = rng.randint(220, 420), rng.randint(150, 330)
                boxes.append(Box(str(index), Rect(rng.randint(-200, 1900), rng.randint(0, 1100), w, h)))
            repaired = L.repair(boxes, WORK, GAP)
            assert_valid(self, repaired, WORK, GAP)

    def test_repair_keeps_valid_layout(self) -> None:
        rng = random.Random(19)
        boxes = random_layout(rng, 10)
        repaired = L.repair(boxes, WORK, GAP)
        self.assertEqual(repaired, {box.id: box.rect for box in boxes})

    def test_relax_regrows_towards_preference(self) -> None:
        a = Box("a", Rect(16, 72, 300, 200), pref_w=500, pref_h=260)
        relaxed = L.relax([a], WORK, GAP)
        self.assertEqual(relaxed["a"], Rect(16, 72, 500, 260))
        b = Box("b", Rect(420, 72, 300, 200))
        relaxed = L.relax([a, b], WORK, GAP)
        self.assertEqual(relaxed["a"].right + GAP, 420)

    def test_swap_targets(self) -> None:
        a = Box("a", Rect(16, 72, 300, 200))
        b = Box("b", Rect(340, 72, 300, 200))
        moved_a = a.with_rect(Rect(360, 90, 300, 200))
        result = L.swap_targets([moved_a, b], "a", "b", a.rect, WORK, GAP)
        self.assertEqual(result, (Rect(340, 72, 300, 200), Rect(16, 72, 300, 200)))

    def test_plan_transition_fades_crossing_islands(self) -> None:
        old = {"a": Rect(0, 0, 100, 100), "b": Rect(400, 0, 100, 100), "c": Rect(200, 0, 100, 100)}
        new = {"a": Rect(400, 0, 100, 100), "b": Rect(0, 0, 100, 100), "c": Rect(200, 0, 100, 100)}
        modes = L.plan_transition(old, new)
        self.assertEqual(modes["c"], "still")
        self.assertIn("fade", (modes["a"], modes["b"]))
        modes = L.plan_transition({"a": Rect(0, 0, 10, 10)}, {"a": Rect(50, 0, 10, 10)})
        self.assertEqual(modes["a"], "slide")


def spec(key: str, number: int, x: int, primary: bool = False) -> MonitorSpec:
    rect = Rect(x, 0, 1920, 1080)
    return MonitorSpec(key, number, rect, Rect(x, 0, 1920, 1040), primary)


class MonitorTests(unittest.TestCase):
    def test_migration_splits_pages_by_monitor(self) -> None:
        left = IslandState(title="左", x=40, y=100)
        right = IslandState(title="右", x=2100, y=100)
        page = PageState(title="主页", islands=[left, right])
        other = PageState(title="娱乐")
        state = AppState(pages=[page, other], current_page_id=page.id)
        monitors = [spec("A", 1, 0, True), spec("B", 2, 1920)]
        self.assertTrue(migrate_state(state, monitors))
        self.assertEqual(state.version, STATE_VERSION)
        self.assertEqual(page.monitor_key, "A")
        self.assertEqual([island.title for island in page.islands], ["左"])
        split = [p for p in state.pages if p.monitor_key == "B"]
        self.assertEqual([p.title for p in split], ["主页"])
        self.assertEqual(split[0].islands[0].title, "右")
        self.assertEqual(state.current_pages, {"A": page.id, "B": split[0].id})
        self.assertEqual(state.current_page_id, page.id)
        self.assertFalse(migrate_state(state, monitors))

    def test_disconnected_monitor_pages_become_guests_and_return(self) -> None:
        page_a = PageState(title="工作", monitor_key="A", monitor_label="显示器 1")
        page_b = PageState(title="副屏", monitor_key="B", monitor_label="显示器 2")
        state = AppState(version=2, pages=[page_a, page_b], current_page_id=page_a.id,
                         current_pages={"A": page_a.id, "B": page_b.id})
        only_a = [spec("A", 1, 0, True)]
        ensure_current_pages(state, only_a)
        self.assertEqual([p.id for p in guest_pages(state, only_a)], [page_b.id])
        state.current_pages["A"] = page_b.id  # the user opened the guest preset
        ensure_current_pages(state, only_a)
        self.assertEqual(state.current_pages["A"], page_b.id)
        self.assertEqual(state.current_page_id, page_b.id)
        both = [spec("A", 1, 0, True), spec("B", 2, 1920)]
        ensure_current_pages(state, both)
        self.assertEqual(state.current_pages["A"], page_a.id)
        self.assertEqual(state.current_pages["B"], page_b.id)

    def test_new_monitor_gets_default_page(self) -> None:
        page_a = PageState(title="工作", monitor_key="A")
        state = AppState(version=2, pages=[page_a], current_pages={"A": page_a.id})
        ensure_current_pages(state, [spec("A", 1, 0, True), spec("C", 2, 1920)])
        created = state.page(state.current_pages["C"])
        self.assertEqual(created.title, "工作台")
        self.assertEqual(created.monitor_key, "C")

    def test_replaced_primary_keeps_showing_previous_preset(self) -> None:
        page_a = PageState(title="工作", monitor_key="A", monitor_label="显示器 1")
        state = AppState(version=2, pages=[page_a], current_page_id=page_a.id, current_pages={"A": page_a.id})
        ensure_current_pages(state, [spec("N", 1, 0, True)])
        self.assertEqual(state.current_pages["N"], page_a.id)
        self.assertEqual(len(state.pages), 1)
        ensure_current_pages(state, [spec("N", 1, 0, True), spec("A", 2, 1920)])
        self.assertEqual(state.current_pages["A"], page_a.id)
        self.assertNotEqual(state.current_pages["N"], page_a.id)
        self.assertEqual(state.page(state.current_pages["N"]).monitor_key, "N")

    def test_models_round_trip_new_fields(self) -> None:
        island = IslandState(pref_width=400, pref_height=300, norm=[0.1, 0.2, 0.3, 0.4])
        page = PageState(islands=[island], monitor_key="A", monitor_label="显示器 1")
        state = AppState(pages=[page], current_pages={"A": page.id})
        restored = AppState.from_dict(state.to_dict())
        self.assertEqual(restored.to_dict(), state.to_dict())
        legacy = AppState.from_dict({"preferences": {"toolbar_x": 5, "theme_mode": "bogus",
                                                      "day_bg": "abc", "night_start": "25:00"}})
        self.assertEqual(legacy.preferences.theme_mode, "auto_time")
        self.assertEqual(legacy.preferences.day_bg, "#AABBCC")
        self.assertEqual(legacy.preferences.night_start, "19:00")
        self.assertEqual(legacy.preferences.to_dict()["toolbar_x"], 5)


if __name__ == "__main__":
    unittest.main()

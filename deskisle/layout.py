"""Pure layout geometry for DeskIsle islands.

Nothing in this module imports Qt, so the rules that keep islands apart can be
unit tested quickly and exhaustively.

Coordinates are integers in board space.  A :class:`Rect` is half-open, i.e. it
covers ``x <= px < x + w``.  Two islands are *too close* when they are not
separated by at least ``gap`` pixels horizontally **or** vertically.  A layout
is *valid* when every island lies inside the work area of its monitor and no
two islands are too close.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Mapping, Sequence

GAP = 12
MIN_W, MIN_H = 220, 150
WEB_MIN_W, WEB_MIN_H = 260, 180
DEFAULT_W, DEFAULT_H = 340, 270
WEB_DEFAULT_W, WEB_DEFAULT_H = 420, 320
COLLAPSED_H = 44
# Distance (px) a resize has to be pulled past a neighbour before DeskIsle
# offers to push that neighbour away.
PUSH_THRESHOLD = 24
# How long a dragged island has to hover over another one before they swap.
SWAP_HOVER_MS = 250
# Free border kept around the work area of every monitor.
MARGIN = 16
# Height reserved at the top of the primary monitor for the dynamic bar.
TOP_BAND = 56

_SEARCH_STEPS = 14


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0

    @property
    def cy(self) -> float:
        return self.y + self.h / 2.0

    @property
    def area(self) -> int:
        return max(0, self.w) * max(0, self.h)

    def moved_to(self, x: float, y: float) -> "Rect":
        return Rect(int(round(x)), int(round(y)), self.w, self.h)

    def translated(self, dx: float, dy: float) -> "Rect":
        return Rect(int(round(self.x + dx)), int(round(self.y + dy)), self.w, self.h)

    def resized(self, w: float, h: float) -> "Rect":
        return Rect(self.x, self.y, int(round(w)), int(round(h)))

    def intersects(self, other: "Rect") -> bool:
        return (self.x < other.right and other.x < self.right
                and self.y < other.bottom and other.y < self.bottom)

    def intersection_area(self, other: "Rect") -> int:
        w = min(self.right, other.right) - max(self.x, other.x)
        h = min(self.bottom, other.bottom) - max(self.y, other.y)
        return w * h if w > 0 and h > 0 else 0

    def contains(self, other: "Rect") -> bool:
        return (other.x >= self.x and other.y >= self.y
                and other.right <= self.right and other.bottom <= self.bottom)

    def contains_point(self, px: float, py: float) -> bool:
        return self.x <= px < self.right and self.y <= py < self.bottom

    def united(self, other: "Rect") -> "Rect":
        x, y = min(self.x, other.x), min(self.y, other.y)
        return Rect(x, y, max(self.right, other.right) - x, max(self.bottom, other.bottom) - y)

    def inset(self, left: int, top: int, right: int, bottom: int) -> "Rect":
        return Rect(self.x + left, self.y + top, max(0, self.w - left - right),
                    max(0, self.h - top - bottom))

    def distance_to_point(self, px: float, py: float) -> float:
        dx = max(self.x - px, 0.0, px - self.right)
        dy = max(self.y - py, 0.0, py - self.bottom)
        return (dx * dx + dy * dy) ** 0.5

    def as_tuple(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.w, self.h)


@dataclass(frozen=True)
class Box:
    """One island as seen by the layout engine.

    ``rect`` is the island's *footprint*: collapsed islands only occupy their
    header row, so callers pass ``COLLAPSED_H`` as height (and as ``min_h`` and
    ``pref_h``) for them.
    """

    id: str
    rect: Rect
    min_w: int = MIN_W
    min_h: int = MIN_H
    pref_w: int = 0
    pref_h: int = 0
    fixed: bool = False

    @property
    def preferred(self) -> tuple[int, int]:
        return (max(self.min_w, self.pref_w or self.rect.w), max(self.min_h, self.pref_h or self.rect.h))

    def with_rect(self, rect: Rect) -> "Box":
        return replace(self, rect=rect)


# ---------------------------------------------------------------------------
# Basic predicates
# ---------------------------------------------------------------------------

def too_close(a: Rect, b: Rect, gap: int = GAP) -> bool:
    """True when ``a`` and ``b`` are not separated by ``gap`` on either axis."""

    return (a.x < b.right + gap and b.x < a.right + gap
            and a.y < b.bottom + gap and b.y < a.bottom + gap)


def fits(rect: Rect, obstacles: Iterable[Rect], work: Rect, gap: int = GAP) -> bool:
    return work.contains(rect) and not any(too_close(rect, other, gap) for other in obstacles)


def conflicts(boxes: Sequence[Box], work: Rect, gap: int = GAP) -> set[str]:
    """Ids of islands that are outside ``work`` or too close to another one."""

    bad: set[str] = set()
    for index, box in enumerate(boxes):
        if not work.contains(box.rect):
            bad.add(box.id)
        for other in boxes[index + 1:]:
            if too_close(box.rect, other.rect, gap):
                bad.add(box.id)
                bad.add(other.id)
    return bad


def layout_valid(boxes: Sequence[Box], work: Rect, gap: int = GAP) -> bool:
    return not conflicts(boxes, work, gap)


# ---------------------------------------------------------------------------
# Free space
# ---------------------------------------------------------------------------

Region = tuple[int, int, int, int]  # closed box of valid top-left points: x0, y0, x1, y1


def _prune(regions: list[Region]) -> list[Region]:
    unique = list(dict.fromkeys(regions))
    result: list[Region] = []
    for index, region in enumerate(unique):
        x0, y0, x1, y1 = region
        contained = False
        for other_index, other in enumerate(unique):
            if other_index == index:
                continue
            if other[0] <= x0 and other[1] <= y0 and other[2] >= x1 and other[3] >= y1:
                # Identical boxes were removed above, so ``other`` is strictly bigger.
                contained = True
                break
        if not contained:
            result.append(region)
    return result


def valid_regions(w: int, h: int, obstacles: Iterable[Rect], work: Rect, gap: int = GAP) -> list[Region]:
    """All top-left positions where a ``w`` x ``h`` island fits.

    The result is a list of closed integer boxes ``(x0, y0, x1, y1)``.  For
    each obstacle the forbidden top-left positions form an *open* rectangle,
    so positions exactly ``gap`` away from a neighbour stay valid.
    """

    x0, y0 = work.x, work.y
    x1, y1 = work.right - w, work.bottom - h
    if w <= 0 or h <= 0 or x1 < x0 or y1 < y0:
        return []
    regions: list[Region] = [(x0, y0, x1, y1)]
    for other in obstacles:
        fx0, fx1 = other.x - gap - w, other.right + gap
        fy0, fy1 = other.y - gap - h, other.bottom + gap
        changed = False
        result: list[Region] = []
        for region in regions:
            bx0, by0, bx1, by1 = region
            if bx0 >= fx1 or bx1 <= fx0 or by0 >= fy1 or by1 <= fy0:
                result.append(region)
                continue
            changed = True
            if fx0 >= bx0:
                result.append((bx0, by0, fx0, by1))
            if fx1 <= bx1:
                result.append((fx1, by0, bx1, by1))
            if fy0 >= by0:
                result.append((bx0, by0, bx1, fy0))
            if fy1 <= by1:
                result.append((bx0, fy1, bx1, by1))
        regions = _prune(result) if changed else result
        if not regions:
            break
    return regions


def nearest_position(w: int, h: int, target_x: float, target_y: float, obstacles: Iterable[Rect],
                     work: Rect, gap: int = GAP) -> tuple[int, int] | None:
    """Valid top-left position closest (euclidean) to ``target``."""

    tx, ty = int(round(target_x)), int(round(target_y))
    best: tuple[int, int, int] | None = None
    for x0, y0, x1, y1 in valid_regions(w, h, list(obstacles), work, gap):
        px = min(max(tx, x0), x1)
        py = min(max(ty, y0), y1)
        distance = (px - tx) ** 2 + (py - ty) ** 2
        if best is None or distance < best[0]:
            best = (distance, px, py)
    return None if best is None else (best[1], best[2])


def nearest_grid_position(w: int, h: int, target_x: float, target_y: float, obstacles: Iterable[Rect],
                          work: Rect, gap: int = GAP, grid: int = 0) -> tuple[int, int] | None:
    """Like :func:`nearest_position`, but prefers top-left corners on a ``grid``.

    Falls back to the nearest valid (off-grid) position when no grid point is
    available, so a free spot is never rejected just because of snapping.
    """

    if grid <= 1:
        return nearest_position(w, h, target_x, target_y, obstacles, work, gap)
    regions = valid_regions(w, h, list(obstacles), work, gap)
    best: tuple[float, int, int] | None = None
    for x0, y0, x1, y1 in regions:
        gx0, gx1 = -(-x0 // grid) * grid, (x1 // grid) * grid
        gy0, gy1 = -(-y0 // grid) * grid, (y1 // grid) * grid
        if gx0 > gx1 or gy0 > gy1:
            continue
        px = min(max(int(round(target_x / grid)) * grid, gx0), gx1)
        py = min(max(int(round(target_y / grid)) * grid, gy0), gy1)
        distance = (px - target_x) ** 2 + (py - target_y) ** 2
        if best is None or distance < best[0]:
            best = (distance, px, py)
    if best is not None:
        return (best[1], best[2])
    tx, ty = int(round(target_x)), int(round(target_y))
    fallback: tuple[int, int, int] | None = None
    for x0, y0, x1, y1 in regions:
        px = min(max(tx, x0), x1)
        py = min(max(ty, y0), y1)
        distance = (px - tx) ** 2 + (py - ty) ** 2
        if fallback is None or distance < fallback[0]:
            fallback = (distance, px, py)
    return None if fallback is None else (fallback[1], fallback[2])


def first_position(w: int, h: int, obstacles: Iterable[Rect], work: Rect,
                   gap: int = GAP) -> tuple[int, int] | None:
    """Top-most, then left-most valid position (reading order)."""

    regions = valid_regions(w, h, list(obstacles), work, gap)
    if not regions:
        return None
    x0, y0, _x1, _y1 = min(regions, key=lambda region: (region[1], region[0]))
    return (x0, y0)


def _lerp_size(low: int, high: int, factor: float) -> int:
    if high <= low:
        return high
    return int(low + (high - low) * factor)


def largest_fit(min_w: int, min_h: int, max_w: int, max_h: int, obstacles: Iterable[Rect], work: Rect,
                gap: int = GAP, target: tuple[float, float] | None = None) -> Rect | None:
    """Biggest island between the minimum and maximum size that still fits.

    Width and height shrink by the same factor.  The island is placed nearest
    to ``target`` or, without a target, in reading order.
    """

    obstacles = list(obstacles)
    max_w, max_h = max(min_w, max_w), max(min_h, max_h)

    def position(factor: float) -> Rect | None:
        w, h = _lerp_size(min_w, max_w, factor), _lerp_size(min_h, max_h, factor)
        if target is None:
            found = first_position(w, h, obstacles, work, gap)
        else:
            found = nearest_position(w, h, target[0], target[1], obstacles, work, gap)
        return None if found is None else Rect(found[0], found[1], w, h)

    best = position(1.0)
    if best is not None:
        return best
    best = position(0.0)
    if best is None:
        return None
    low, high = 0.0, 1.0
    for _step in range(_SEARCH_STEPS):
        middle = (low + high) / 2.0
        candidate = position(middle)
        if candidate is None:
            high = middle
        else:
            low, best = middle, candidate
    return best


# ---------------------------------------------------------------------------
# Pushing neighbours away
# ---------------------------------------------------------------------------

def _transform(rect: Rect, axis: str, sign: int) -> Rect:
    """Map ``rect`` into the canonical frame where the push goes towards +x."""

    if axis == "y":
        rect = Rect(rect.y, rect.x, rect.h, rect.w)
    if sign < 0:
        rect = Rect(-rect.right, rect.y, rect.w, rect.h)
    return rect


def _untransform(rect: Rect, axis: str, sign: int) -> Rect:
    if sign < 0:
        rect = Rect(-rect.right, rect.y, rect.w, rect.h)
    if axis == "y":
        rect = Rect(rect.y, rect.x, rect.h, rect.w)
    return rect


@dataclass(frozen=True)
class _Item:
    id: str
    rect: Rect
    min_w: int
    fixed: bool


def _band_close(a0: int, a1: int, b0: int, b1: int, gap: int) -> bool:
    return a0 < b1 + gap and b0 < a1 + gap


def _push_canonical(active_new: Rect, active_old: Rect, items: Sequence[_Item], limit: int,
                    gap: int, factor: float) -> dict[str, Rect] | None:
    """Push islands right of the active one towards +x.

    Pushed islands shrink to ``min + (width - min) * factor``.  Returns the
    new rectangles of all items, or ``None`` when they do not fit before
    ``limit`` (or a fixed island would have to move).
    """

    if active_new.right > limit:
        return None
    placed: list[tuple[_Item, Rect]] = []
    result: dict[str, Rect] = {}
    for item in sorted(items, key=lambda entry: (entry.rect.x, entry.rect.y)):
        rect = item.rect
        bound = None
        if rect.x > active_old.x and _band_close(active_new.y, active_new.bottom, rect.y, rect.bottom, gap):
            bound = active_new.right + gap
        for other, other_rect in placed:
            if other.rect.x < rect.x and _band_close(other_rect.y, other_rect.bottom, rect.y, rect.bottom, gap):
                edge = other_rect.right + gap
                bound = edge if bound is None else max(bound, edge)
        if bound is not None and bound > rect.x:
            if item.fixed:
                return None
            width = rect.w if rect.w <= item.min_w else max(item.min_w, _lerp_size(item.min_w, rect.w, factor))
            rect = Rect(bound, rect.y, width, rect.h)
            if rect.right > limit:
                return None
        placed.append((item, rect))
        result[item.id] = rect
    return result


@dataclass(frozen=True)
class PushResult:
    active: Rect
    rects: dict[str, Rect]
    clamped: bool = False
    factor: float = 1.0


def push_axis(boxes: Sequence[Box], active_id: str, new_rect: Rect, axis: str, sign: int,
              work: Rect, gap: int = GAP) -> PushResult:
    """Grow the active island along one axis, pushing/shrinking neighbours.

    Neighbours first move away; when they reach the edge of the work area
    they all shrink by a common factor (never below their minimum).  When even
    minimum sizes do not make enough room the active island is clamped to the
    largest size that works.
    """

    by_id = {box.id: box for box in boxes}
    active_box = by_id[active_id]
    old = active_box.rect
    rects = {box.id: box.rect for box in boxes}
    canon_old = _transform(old, axis, sign)
    canon_new = _transform(new_rect, axis, sign)
    canon_work = _transform(work, axis, sign)
    limit = canon_work.right
    items = []
    for box in boxes:
        if box.id == active_id:
            continue
        minimum = box.min_w if axis == "x" else box.min_h
        items.append(_Item(box.id, _transform(box.rect, axis, sign), minimum, box.fixed))

    def solve(active: Rect, factor: float) -> dict[str, Rect] | None:
        return _push_canonical(active, canon_old, items, limit, gap, factor)

    def finish(active: Rect, solved: dict[str, Rect], factor: float, clamped: bool) -> PushResult:
        out = dict(rects)
        for key, rect in solved.items():
            out[key] = _untransform(rect, axis, sign)
        result_active = _untransform(active, axis, sign)
        out[active_id] = result_active
        return PushResult(result_active, out, clamped, factor)

    solved = solve(canon_new, 1.0)
    if solved is not None:
        return finish(canon_new, solved, 1.0, False)
    solved = solve(canon_new, 0.0)
    if solved is not None:
        low, high, best = 0.0, 1.0, solved
        for _step in range(_SEARCH_STEPS):
            middle = (low + high) / 2.0
            candidate = solve(canon_new, middle)
            if candidate is None:
                high = middle
            else:
                low, best = middle, candidate
        return finish(canon_new, best, low, False)
    # Not even minimum sizes make enough room: clamp the active island.
    low_w = min(canon_old.w, canon_new.w)
    base = Rect(canon_new.x, canon_new.y, low_w, canon_new.h)
    best_solution = solve(base, 0.0)
    if best_solution is None:
        return PushResult(old, rects, True, 0.0)
    low, high = low_w, canon_new.w
    best_active = base
    while high - low > 1:
        middle = (low + high) // 2
        candidate_rect = Rect(canon_new.x, canon_new.y, middle, canon_new.h)
        candidate = solve(candidate_rect, 0.0)
        if candidate is None:
            high = middle
        else:
            low, best_active, best_solution = middle, candidate_rect, candidate
    return finish(best_active, best_solution, 0.0, True)


def free_extent(boxes: Sequence[Box], active_id: str, rect: Rect, edge: str, work: Rect,
                gap: int = GAP) -> int:
    """How far ``edge`` of ``rect`` can move outwards without pushing anyone.

    Returns the extreme coordinate for that edge (e.g. the largest possible
    right edge for ``edge == "right"``).
    """

    others = [box.rect for box in boxes if box.id != active_id]
    if edge == "right":
        limit = work.right
        for other in others:
            if other.x >= rect.x and _band_close(rect.y, rect.bottom, other.y, other.bottom, gap):
                limit = min(limit, other.x - gap)
        return max(limit, rect.x)
    if edge == "left":
        limit = work.x
        for other in others:
            if other.right <= rect.right and _band_close(rect.y, rect.bottom, other.y, other.bottom, gap):
                limit = max(limit, other.right + gap)
        return min(limit, rect.right)
    if edge == "bottom":
        limit = work.bottom
        for other in others:
            if other.y >= rect.y and _band_close(rect.x, rect.right, other.x, other.right, gap):
                limit = min(limit, other.y - gap)
        return max(limit, rect.y)
    if edge == "top":
        limit = work.y
        for other in others:
            if other.bottom <= rect.bottom and _band_close(rect.x, rect.right, other.x, other.right, gap):
                limit = max(limit, other.bottom + gap)
        return min(limit, rect.bottom)
    raise ValueError(edge)


def resize_with_push(boxes: Sequence[Box], active_id: str, new_rect: Rect, work: Rect,
                     gap: int = GAP) -> PushResult:
    """Resize the active island (any edges), pushing neighbours as needed."""

    by_id = {box.id: box for box in boxes}
    active = by_id[active_id]
    old = active.rect
    min_w, min_h = active.min_w, active.min_h
    # Keep the requested rect inside the work area and above the minimum.
    left, right = new_rect.x, new_rect.right
    top, bottom = new_rect.y, new_rect.bottom
    if left != old.x:
        left = max(work.x, min(left, right - min_w))
    if right != old.right:
        right = min(work.right, max(right, left + min_w))
    if top != old.y:
        top = max(work.y, min(top, bottom - min_h))
    if bottom != old.bottom:
        bottom = min(work.bottom, max(bottom, top + min_h))
    target = Rect(left, top, right - left, bottom - top)

    current = list(boxes)
    clamped = False
    factor = 1.0
    rects = {box.id: box.rect for box in boxes}
    # Horizontal pass with the old vertical extent.
    if target.x != old.x or target.right != old.right:
        stage = Rect(target.x, old.y, target.w, old.h)
        sign = -1 if target.x < old.x else 1
        if target.x < old.x and target.right > old.right:
            sign = 1  # both edges cannot move at once from one handle
        result = push_axis(current, active_id, stage, "x", sign, work, gap)
        clamped, factor, rects = result.clamped, result.factor, result.rects
        current = [box.with_rect(rects[box.id]) for box in boxes]
    after_x = rects[active_id]
    if target.y != old.y or target.bottom != old.bottom:
        stage = Rect(after_x.x, target.y, after_x.w, target.h)
        sign = -1 if target.y < old.y else 1
        result = push_axis(current, active_id, stage, "y", sign, work, gap)
        clamped = clamped or result.clamped
        factor = min(factor, result.factor)
        rects = result.rects
    return PushResult(rects[active_id], rects, clamped, factor)


@dataclass(frozen=True)
class ExpandResult:
    active: Rect
    rects: dict[str, Rect]
    mode: str  # "push" | "shrunk" | "relocated"


def expand_with_push(boxes: Sequence[Box], active_id: str, height: int, min_h: int, work: Rect,
                     gap: int = GAP) -> ExpandResult | None:
    """Expand a collapsed island to ``height``.

    Neighbours below are pushed down (and shrink if needed).  When even
    ``min_h`` cannot be reached in place, the island moves to the nearest spot
    where it fits.  ``None`` means there is no room anywhere.
    """

    by_id = {box.id: box for box in boxes}
    active = by_id[active_id]
    old = active.rect
    target = Rect(old.x, old.y, old.w, height)
    result = push_axis(boxes, active_id, target, "y", 1, work, gap)
    if result.active.h >= height:
        return ExpandResult(result.active, result.rects, "push")
    if result.active.h >= min_h:
        return ExpandResult(result.active, result.rects, "shrunk")
    others = [box.rect for box in boxes if box.id != active_id]
    rects = {box.id: box.rect for box in boxes}
    found = largest_fit(active.min_w, min_h, old.w, height, others, work, gap, target=(old.x, old.y))
    if found is None:
        return None
    rects[active_id] = found
    return ExpandResult(found, rects, "relocated")


# ---------------------------------------------------------------------------
# Whole-layout operations
# ---------------------------------------------------------------------------

def reading_order(boxes: Sequence[Box]) -> list[Box]:
    """Rows top to bottom, each row left to right."""

    remaining = sorted(boxes, key=lambda box: (box.rect.y, box.rect.x))
    rows: list[list[Box]] = []
    for box in remaining:
        if rows:
            head = rows[-1][0].rect
            if box.rect.y < head.y + max(1, head.h) / 2.0:
                rows[-1].append(box)
                continue
        rows.append([box])
    ordered: list[Box] = []
    for row in rows:
        ordered.extend(sorted(row, key=lambda box: box.rect.x))
    return ordered


def _shelf(sizes: Sequence[tuple[int, int]], work: Rect, gap: int) -> list[Rect] | None:
    x, y, row_h = work.x, work.y, 0
    result: list[Rect] = []
    for w, h in sizes:
        if w > work.w:
            return None
        if x > work.x and x + w > work.right:
            x, y, row_h = work.x, y + row_h + gap, 0
        result.append(Rect(x, y, w, h))
        x += w + gap
        row_h = max(row_h, h)
    if result and y + row_h > work.bottom:
        return None
    return result


def auto_arrange(boxes: Sequence[Box], work: Rect, gap: int = GAP) -> dict[str, Rect] | None:
    """Tidy rows in reading order at preferred size, shrinking uniformly if needed."""

    if not boxes:
        return {}
    fixed = [box for box in boxes if box.fixed]
    movable = reading_order([box for box in boxes if not box.fixed])
    if fixed:
        # Locked islands stay where they are; the others flow around them.
        return _arrange_around(fixed, movable, work, gap)

    def sizes(factor: float) -> list[tuple[int, int]]:
        result = []
        for box in movable:
            pref_w, pref_h = box.preferred
            result.append((_lerp_size(box.min_w, pref_w, factor), _lerp_size(box.min_h, pref_h, factor)))
        return result

    packed = _shelf(sizes(1.0), work, gap)
    if packed is None:
        packed = _shelf(sizes(0.0), work, gap)
        if packed is None:
            return None
        low, high = 0.0, 1.0
        for _step in range(_SEARCH_STEPS):
            middle = (low + high) / 2.0
            candidate = _shelf(sizes(middle), work, gap)
            if candidate is None:
                high = middle
            else:
                low, packed = middle, candidate
    return {box.id: rect for box, rect in zip(movable, packed)}


def _arrange_around(fixed: Sequence[Box], movable: Sequence[Box], work: Rect, gap: int) -> dict[str, Rect] | None:
    def attempt(factor: float) -> dict[str, Rect] | None:
        placed = [box.rect for box in fixed]
        result = {box.id: box.rect for box in fixed}
        for box in movable:
            pref_w, pref_h = box.preferred
            w, h = _lerp_size(box.min_w, pref_w, factor), _lerp_size(box.min_h, pref_h, factor)
            found = first_position(w, h, placed, work, gap)
            if found is None:
                return None
            rect = Rect(found[0], found[1], w, h)
            placed.append(rect)
            result[box.id] = rect
        return result

    best = attempt(1.0)
    if best is not None:
        return best
    best = attempt(0.0)
    if best is None:
        return None
    low, high = 0.0, 1.0
    for _step in range(_SEARCH_STEPS):
        middle = (low + high) / 2.0
        candidate = attempt(middle)
        if candidate is None:
            high = middle
        else:
            low, best = middle, candidate
    return best


@dataclass(frozen=True)
class PlaceResult:
    rect: Rect
    rects: dict[str, Rect]  # new rectangles of the existing islands
    mode: str  # "free" | "shrunk" | "squeeze" | "arrange"


def place_new(boxes: Sequence[Box], width: int, height: int, min_w: int, min_h: int, work: Rect,
              gap: int = GAP, target: tuple[float, float] | None = None,
              new_id: str = "__new__") -> PlaceResult | None:
    """Find room for a new island; ``None`` means "尺寸不足"."""

    rects = {box.id: box.rect for box in boxes}
    obstacles = list(rects.values())
    width, height = max(width, min_w), max(height, min_h)
    if target is None:
        found = first_position(width, height, obstacles, work, gap)
    else:
        found = nearest_position(width, height, target[0], target[1], obstacles, work, gap)
    if found is not None:
        return PlaceResult(Rect(found[0], found[1], width, height), rects, "free")
    smaller = largest_fit(min_w, min_h, width, height, obstacles, work, gap, target)
    if smaller is not None:
        return PlaceResult(smaller, rects, "shrunk")

    # Squeeze: shrink everybody in place (top-left corners stay) until the
    # new island fits at least at its minimum size.
    movable = [box for box in boxes if not box.fixed]

    def squeezed(factor: float) -> dict[str, Rect]:
        result = dict(rects)
        for box in movable:
            rect = box.rect
            result[box.id] = Rect(rect.x, rect.y, _lerp_size(box.min_w, rect.w, factor) if rect.w > box.min_w else rect.w,
                                  _lerp_size(box.min_h, rect.h, factor) if rect.h > box.min_h else rect.h)
        return result

    def fit_with(factor: float) -> Rect | None:
        layout = squeezed(factor)
        found_rect = largest_fit(min_w, min_h, width, height, list(layout.values()), work, gap, target)
        return found_rect

    if fit_with(0.0) is not None:
        low, high = 0.0, 1.0
        for _step in range(10):
            middle = (low + high) / 2.0
            if fit_with(middle) is None:
                high = middle
            else:
                low = middle
        layout = squeezed(low)
        rect = fit_with(low)
        if rect is not None:
            return PlaceResult(rect, layout, "squeeze")

    # Last resort: rearrange everything, the new island at the end.
    new_box = Box(new_id, Rect(work.right, work.bottom, width, height), min_w, min_h, width, height)
    arranged = auto_arrange(list(boxes) + [new_box], work, gap)
    if arranged is None:
        return None
    new_rect = arranged.pop(new_id)
    return PlaceResult(new_rect, arranged, "arrange")


def repair(boxes: Sequence[Box], work: Rect, gap: int = GAP) -> dict[str, Rect]:
    """Make a layout valid while moving as little as possible.

    Islands are visited in reading order (locked ones first); an island that
    already fits next to the earlier ones stays, otherwise it moves to the
    nearest free spot, shrinking only when nothing else works.
    """

    ordered = [box for box in boxes if box.fixed] + reading_order([box for box in boxes if not box.fixed])
    placed: list[Rect] = []
    result: dict[str, Rect] = {}
    for box in ordered:
        rect = box.rect
        w = max(min(rect.w, work.w), min(box.min_w, work.w))
        h = max(min(rect.h, work.h), min(box.min_h, work.h))
        rect = Rect(rect.x, rect.y, w, h)
        if not fits(rect, placed, work, gap):
            found = nearest_position(w, h, rect.x, rect.y, placed, work, gap)
            if found is not None:
                rect = Rect(found[0], found[1], w, h)
            else:
                smaller = largest_fit(min(box.min_w, w), min(box.min_h, h), w, h, placed, work, gap,
                                      target=(rect.x, rect.y))
                if smaller is not None:
                    rect = smaller
                else:
                    # Nothing fits any more: keep it inside the work area at least.
                    x = min(max(rect.x, work.x), max(work.x, work.right - w))
                    y = min(max(rect.y, work.y), max(work.y, work.bottom - h))
                    rect = Rect(x, y, w, h)
        placed.append(rect)
        result[box.id] = rect
    return result


def relax(boxes: Sequence[Box], work: Rect, gap: int = GAP, ids: Iterable[str] | None = None) -> dict[str, Rect]:
    """Let islands that were shrunk to make room grow back towards their preferred size."""

    wanted = set(ids) if ids is not None else None
    rects = {box.id: box.rect for box in boxes}
    for box in reading_order(boxes):
        if wanted is not None and box.id not in wanted:
            continue
        pref_w, pref_h = box.preferred
        rect = rects[box.id]
        if rect.w >= pref_w and rect.h >= pref_h:
            continue
        others = [other for key, other in rects.items() if key != box.id]

        def grow(current: Rect, target_w: int, target_h: int) -> Rect:
            candidate = Rect(current.x, current.y, target_w, target_h)
            if fits(candidate, others, work, gap):
                return candidate
            low_w, high_w = current.w, target_w
            low_h, high_h = current.h, target_h
            best = current
            for _step in range(_SEARCH_STEPS):
                mid_w = (low_w + high_w) // 2 if high_w > low_w else low_w
                mid_h = (low_h + high_h) // 2 if high_h > low_h else low_h
                candidate = Rect(current.x, current.y, mid_w, mid_h)
                if fits(candidate, others, work, gap):
                    best = candidate
                    low_w, low_h = mid_w, mid_h
                else:
                    high_w, high_h = mid_w, mid_h
                if high_w - low_w <= 1 and high_h - low_h <= 1:
                    break
            return best

        grown = grow(rect, max(rect.w, pref_w), rect.h)
        grown = grow(grown, grown.w, max(grown.h, pref_h))
        rects[box.id] = grown
    return rects


def swap_targets(boxes: Sequence[Box], a_id: str, b_id: str, a_home: Rect, work: Rect,
                 gap: int = GAP, tolerance: int = 160) -> tuple[Rect, Rect] | None:
    """Where A and B land when the dragged island A swaps with B.

    A takes B's place and B moves into A's former spot (both keep their sizes
    and are nudged to the nearest valid position).  ``None`` when that would
    move either island further than ``tolerance`` pixels.
    """

    by_id = {box.id: box for box in boxes}
    a, b = by_id[a_id], by_id[b_id]
    others = [box.rect for box in boxes if box.id not in (a_id, b_id)]
    a_pos = nearest_position(a.rect.w, a.rect.h, b.rect.x, b.rect.y, others, work, gap)
    if a_pos is None:
        return None
    a_rect = Rect(a_pos[0], a_pos[1], a.rect.w, a.rect.h)
    b_pos = nearest_position(b.rect.w, b.rect.h, a_home.x, a_home.y, others + [a_rect], work, gap)
    if b_pos is None:
        return None
    b_rect = Rect(b_pos[0], b_pos[1], b.rect.w, b.rect.h)
    if (abs(a_rect.x - b.rect.x) + abs(a_rect.y - b.rect.y) > tolerance
            or abs(b_rect.x - a_home.x) + abs(b_rect.y - a_home.y) > tolerance):
        return None
    return a_rect, b_rect


def interpolate(a: Rect, b: Rect, t: float) -> Rect:
    return Rect(int(round(a.x + (b.x - a.x) * t)), int(round(a.y + (b.y - a.y) * t)),
                int(round(a.w + (b.w - a.w) * t)), int(round(a.h + (b.h - a.h) * t)))


def plan_transition(old: Mapping[str, Rect], new: Mapping[str, Rect], steps: int = 12) -> dict[str, str]:
    """Decide how every island animates from ``old`` to ``new``.

    ``"slide"`` islands move/resize on a shared timeline, ``"fade"`` islands
    would cross another island on the way and instead fade out, jump and fade
    back in, ``"still"`` islands do not change.
    """

    modes: dict[str, str] = {}
    keys = [key for key in new if key in old]
    movers = [key for key in keys if old[key] != new[key]]
    for key in keys:
        modes[key] = "still"
    movers.sort(key=lambda key: -(abs(new[key].cx - old[key].cx) + abs(new[key].cy - old[key].cy)))
    fading: set[str] = set()
    for key in movers:
        modes[key] = "slide"
    for key in movers:
        collides = False
        for step in range(1, steps):
            t = step / steps
            rect = interpolate(old[key], new[key], t)
            for other in keys:
                if other == key or other in fading:
                    continue
                other_rect = interpolate(old[other], new[other], t)
                if rect.intersects(other_rect):
                    collides = True
                    break
            if collides:
                break
        if collides:
            fading.add(key)
            modes[key] = "fade"
    return modes


def work_area(available: Rect, primary: bool, margin: int = MARGIN, band: int = TOP_BAND) -> Rect:
    """Area islands may use on a monitor (the bar band only exists on the primary one)."""

    top = margin + (band if primary else 0)
    return available.inset(margin, top, margin, margin)


__all__ = [
    "COLLAPSED_H", "DEFAULT_H", "DEFAULT_W", "GAP", "MARGIN", "MIN_H", "MIN_W", "PUSH_THRESHOLD",
    "SWAP_HOVER_MS", "TOP_BAND", "WEB_DEFAULT_H", "WEB_DEFAULT_W", "WEB_MIN_H", "WEB_MIN_W",
    "Box", "ExpandResult", "PlaceResult", "PushResult", "Rect",
    "auto_arrange", "conflicts", "expand_with_push", "first_position", "fits", "free_extent",
    "interpolate", "largest_fit", "layout_valid", "nearest_grid_position", "nearest_position", "place_new", "plan_transition",
    "push_axis", "reading_order", "relax", "repair", "resize_with_push", "swap_targets", "too_close",
    "valid_regions", "work_area",
]

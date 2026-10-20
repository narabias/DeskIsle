"""Free-form grid layout engine for the automatic arrangement mode.

The desktop is a :data:`GRID_COLUMNS` × :data:`GRID_ROWS` board of micro cells.
An island owns a rectangle of cells and remembers *where* it sits, so islands can
be dropped anywhere instead of being poured into a single sequential stream.
That is what lets a page pack tightly even when the levels are mixed.

Size levels are expressed as a fraction of the board:

===========  ==========  ===============================
level        cells       occupies
===========  ==========  ===============================
``quarter``  3 × 3       ¼ width, ¼ height
``third``    4 × 4       ⅓ width, ⅓ height
``half``     6 × 6       ½ width, ½ height
``full``     12 × 6      full width, ½ height
===========  ==========  ===============================

Dragging snaps to :data:`SNAP` cells — a quarter of the screen — which gives the
chunky, unmistakably "phone home screen" feel the mode is modelled on.

This module deliberately avoids Qt imports so the placement maths can be tested
on its own.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

LEVEL_QUARTER = "quarter"
LEVEL_THIRD = "third"
LEVEL_HALF = "half"
LEVEL_FULL = "full"

SIZE_LEVELS: tuple[str, ...] = (LEVEL_QUARTER, LEVEL_THIRD, LEVEL_HALF, LEVEL_FULL)
DEFAULT_SIZE_LEVEL = LEVEL_HALF

# 12 divides evenly by 4, 3 and 2, so every level lands on an exact boundary.
GRID_COLUMNS = 12
GRID_ROWS = 12

# Dragging snaps to this many micro cells (= one quarter of the screen).
SNAP = 3

GAP = 12

_SPANS = {
    LEVEL_QUARTER: (3, 3),
    LEVEL_THIRD: (4, 4),
    LEVEL_HALF: (6, 6),
    LEVEL_FULL: (12, 6),
}


def normalise_level(level: str | None) -> str:
    """Coerce an unknown level to a valid one."""

    return level if level in SIZE_LEVELS else DEFAULT_SIZE_LEVEL


def span_cells(level: str) -> tuple[int, int]:
    """How many micro cells this level occupies: ``(columns, rows)``."""

    return _SPANS[normalise_level(level)]


def level_span(level: str) -> int:
    """Column span of a level (for callers that only care about width)."""

    return span_cells(level)[0]


def level_ratio(level: str) -> tuple[int, int]:
    """Width/height fraction of the screen the level covers."""

    columns, rows = span_cells(level)
    return GRID_COLUMNS // math.gcd(columns, GRID_COLUMNS), GRID_ROWS // math.gcd(rows, GRID_ROWS)


def next_level(level: str) -> str:
    """Cycle a size level upward, wrapping around to the smallest."""

    return SIZE_LEVELS[(SIZE_LEVELS.index(normalise_level(level)) + 1) % len(SIZE_LEVELS)]


@dataclass(frozen=True)
class Rect:
    """Plain rectangle so callers can convert to QRect at the edge."""

    x: int
    y: int
    width: int
    height: int

    def right(self) -> int:
        return self.x + self.width

    def bottom(self) -> int:
        return self.y + self.height

    def intersects(self, other: "Rect") -> bool:
        return not (
            self.right() <= other.x
            or other.right() <= self.x
            or self.bottom() <= other.y
            or other.bottom() <= self.y
        )

    def contains_point(self, x: float, y: float) -> bool:
        return self.x <= x < self.right() and self.y <= y < self.bottom()

    def center(self) -> tuple[float, float]:
        return self.x + self.width / 2, self.y + self.height / 2


@dataclass(frozen=True)
class Placement:
    """Where one island sits on the board, in micro cells."""

    col: int
    row: int
    cols: int
    rows: int

    def cells(self) -> set[tuple[int, int]]:
        return {
            (self.col + column, self.row + row)
            for column in range(max(1, self.cols))
            for row in range(max(1, self.rows))
        }

    def bottom(self) -> int:
        return self.row + self.rows


@dataclass(frozen=True)
class CellMetrics:
    """Pixel geometry of one micro cell."""

    column_width: int
    row_height: int
    gap: int


def occupied(placements: list[Placement]) -> set[tuple[int, int]]:
    """Every micro cell already taken."""

    taken: set[tuple[int, int]] = set()
    for placement in placements:
        taken |= placement.cells()
    return taken


def collides(placements: list[Placement], candidate: Placement) -> bool:
    return bool(candidate.cells() & occupied(placements))


def content_rows(placements: list[Placement]) -> int:
    """How many board rows the page actually needs."""

    if not placements:
        return 1
    return max(1, max(placement.bottom() for placement in placements))


def clamp_col(col: int, cols: int) -> int:
    """Keep a placement inside the board horizontally."""

    return max(0, min(int(col), max(0, GRID_COLUMNS - max(1, cols))))


def snap_col(col: int, cols: int) -> int:
    """Snap a column to the quarter-screen granularity, staying on the board."""

    snapped = int(round(int(col) / SNAP)) * SNAP
    return clamp_col(snapped, cols)


def snap_row(row: int) -> int:
    return max(0, int(round(int(row) / SNAP)) * SNAP)


def first_free(placements: list[Placement], cols: int, rows: int) -> Placement:
    """Lowest, then left-most free slot that fits *cols* × *rows*.

    Scanning every micro column (not just snapped ones) is what lets a later,
    differently sized island drop into a gap an earlier island left behind.
    """

    taken = occupied(placements)
    max_col = max(0, GRID_COLUMNS - cols)
    limit_row = max(GRID_ROWS, content_rows(placements) + rows)
    for row in range(0, limit_row + 1):
        for col in range(0, max_col + 1):
            candidate = Placement(col, row, cols, rows)
            if not (candidate.cells() & taken):
                return candidate
    return Placement(0, content_rows(placements), cols, rows)


def _pack_order(levels: list[str], order: list[int]) -> list[Placement | None]:
    """Place islands in *order*, returning placements indexed like *levels*."""

    placed: dict[int, Placement] = {}
    existing: list[Placement] = []
    for index in order:
        columns, rows = span_cells(levels[index])
        chosen = first_free(existing, columns, rows)
        placed[index] = chosen
        existing.append(chosen)
    return [placed.get(index) for index in range(len(levels))]


def resolve(levels: list[str], pinned: list[tuple[int, int] | None]) -> list[Placement]:
    """Turn size levels plus optional saved positions into a full placement list.

    Islands that already have a board position keep it when it does not clash;
    everything else is poured into the first gap that fits, so a page never
    carries a hole that could have been filled.

    When no island is pinned yet, two packing orders are tried and the one that
    needs fewer board rows wins.  Larger islands first usually packs tighter,
    but not always, so the choice is measured rather than assumed.
    """

    pinned = list(pinned) + [None] * max(0, len(levels) - len(pinned))
    result: list[Placement] = []
    for index, level in enumerate(levels):
        columns, rows = span_cells(level)
        want = pinned[index]
        chosen: Placement | None = None
        if want is not None:
            candidate = Placement(clamp_col(want[0], columns), max(0, int(want[1])), columns, rows)
            if not collides(result, candidate):
                chosen = candidate
        if chosen is None:
            chosen = first_free(result, columns, rows)
        result.append(chosen)

    if any(want is None for want in pinned) and len(levels) > 1:
        # Nobody pinned everything, so the layout is still ours to choose.
        in_order = [index for index in range(len(levels))]
        by_area = sorted(in_order, key=lambda i: -span_cells(levels[i])[0] * span_cells(levels[i])[1])
        candidates = []
        for order in (in_order, by_area):
            packed = _pack_order(levels, order)
            if all(placement is not None for placement in packed):
                candidates.append([placement for placement in packed if placement is not None])
        candidates.append(result)
        result = min(candidates, key=content_rows)
    return result


def compact(placements: list[Placement], pinned: set[int] | None = None) -> list[Placement]:
    """Pull every island up and to the left into any gap above it.

    Applying this repeatedly until nothing moves reproduces the "Tetris settles"
    behaviour people expect: removing an island never leaves a scar behind.

    Indices in *pinned* stay exactly where they are.  A drop is a deliberate
    placement, so the island the user just moved must never be dragged back to
    the top-left by the tidy-up pass.
    """

    keep = set(pinned or ())
    result = list(placements)
    changed = True
    while changed:
        changed = False
        for index in range(len(result)):
            if index in keep:
                continue
            current = result[index]
            others = result[:index] + result[index + 1:]
            moved = current
            # Slide up as far as the gap allows, then left, then up again.
            for _ in range(GRID_ROWS * 2):
                if moved.row > 0:
                    up = Placement(moved.col, moved.row - 1, moved.cols, moved.rows)
                    if not collides(others, up):
                        moved = up
                        continue
                if moved.col > 0:
                    left = Placement(moved.col - 1, moved.row, moved.cols, moved.rows)
                    if not collides(others, left):
                        moved = left
                        continue
                break
            if moved != current:
                result[index] = moved
                changed = True
    return result


def cells_for(area_width: int, area_height: int, rows: int) -> CellMetrics:
    """Pixel size of one micro cell on a board that needs *rows* rows.

    The board keeps :data:`GRID_ROWS` as its reference so a level really does
    cover the fraction it advertises.  Only a page taller than the reference
    shrinks the cells, and only by as much as it must.
    """

    total = max(GRID_ROWS, int(rows))
    column_width = max(1, (max(1, int(area_width)) - GAP * (GRID_COLUMNS - 1)) // GRID_COLUMNS)
    available = max(1, int(area_height)) - GAP * (total - 1)
    return CellMetrics(column_width=column_width, row_height=max(1, available // total), gap=GAP)


def to_rect(placement: Placement, metrics: CellMetrics) -> Rect:
    """Pixel rectangle for a placement."""

    width = placement.cols * metrics.column_width + (placement.cols - 1) * metrics.gap
    height = placement.rows * metrics.row_height + (placement.rows - 1) * metrics.gap
    return Rect(
        x=placement.col * (metrics.column_width + metrics.gap),
        y=placement.row * (metrics.row_height + metrics.gap),
        width=max(1, width),
        height=max(1, height),
    )


def layout(levels: list[str], pinned: list[tuple[int, int] | None],
           area_width: int, area_height: int) -> list[Rect]:
    """Placements resolved and converted to pixels in one call."""

    placements = resolve(levels, pinned)
    metrics = cells_for(area_width, area_height, content_rows(placements))
    return [to_rect(placement, metrics) for placement in placements]


def slot_at(point: tuple[int, int], metrics: CellMetrics,
            cols: int, rows: int) -> tuple[int, int]:
    """Nearest snapped board cell for a dragged island's top-left corner."""

    step_x = metrics.column_width + metrics.gap
    step_y = metrics.row_height + metrics.gap
    col = snap_col(int(round(point[0] / max(1, step_x))), cols)
    row = snap_row(int(round(point[1] / max(1, step_y))))
    return col, row


def nearest_index(point: tuple[int, int], rects: list[Rect]) -> int:
    """Index of the rectangle whose centre is closest to *point*."""

    if not rects:
        return -1
    px, py = point
    best_index = 0
    best_distance: float | None = None
    for index, rect in enumerate(rects):
        center_x, center_y = rect.center()
        distance = (center_x - px) ** 2 + (center_y - py) ** 2
        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_index = index
    return best_index


def best_drop(placements: list[Placement], moving: int, point: tuple[int, int],
              metrics: CellMetrics) -> Placement:
    """Where the island being dragged should land.

    The wanted cell is honoured when it is free.  When it is not, the dragged
    island takes the closest free slot instead, so a drop can never silently
    stack two islands on top of each other.
    """

    current = placements[moving]
    others = placements[:moving] + placements[moving + 1:]
    wanted = Placement(*slot_at(point, metrics, current.cols, current.rows),
                       current.cols, current.rows)
    if not collides(others, wanted):
        return wanted
    # Spiral outwards from the requested cell looking for the nearest fit.
    best: Placement | None = None
    best_distance: float | None = None
    for radius in range(1, GRID_ROWS + 1):
        for delta_row in range(-radius, radius + 1):
            for delta_col in range(-radius, radius + 1):
                if max(abs(delta_col), abs(delta_row)) != radius:
                    continue
                candidate = Placement(
                    clamp_col(wanted.col + delta_col * SNAP, current.cols),
                    max(0, wanted.row + delta_row * SNAP),
                    current.cols, current.rows,
                )
                if collides(others, candidate):
                    continue
                distance = (candidate.col - wanted.col) ** 2 + (candidate.row - wanted.row) ** 2
                if best_distance is None or distance < best_distance:
                    best, best_distance = candidate, distance
        if best is not None:
            return best
    return first_free(others, current.cols, current.rows)


__all__ = [
    "DEFAULT_SIZE_LEVEL",
    "GAP",
    "GRID_COLUMNS",
    "GRID_ROWS",
    "LEVEL_FULL",
    "LEVEL_HALF",
    "LEVEL_QUARTER",
    "LEVEL_THIRD",
    "SIZE_LEVELS",
    "SNAP",
    "CellMetrics",
    "Placement",
    "Rect",
    "best_drop",
    "cells_for",
    "clamp_col",
    "collides",
    "compact",
    "content_rows",
    "first_free",
    "layout",
    "level_ratio",
    "level_span",
    "nearest_index",
    "next_level",
    "normalise_level",
    "occupied",
    "resolve",
    "slot_at",
    "snap_col",
    "snap_row",
    "span_cells",
    "to_rect",
]

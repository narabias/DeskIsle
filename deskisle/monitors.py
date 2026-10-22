"""Which preset belongs to which monitor (pure Python, no Qt).

Since 1.3 every preset ("页面") belongs to one monitor and every monitor shows
its own current preset.  Layouts written by 1.2 have one shared page list;
:func:`migrate_state` splits each of those pages by the monitor that contains
the island, keeping the page titles, so nothing visibly moves.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .layout import Rect, work_area
from .models import STATE_VERSION, AppState, IslandState, PageState

DEFAULT_PAGE_TITLE = "工作台"


@dataclass(frozen=True)
class MonitorSpec:
    key: str
    number: int
    geometry: Rect
    available: Rect
    primary: bool = False
    scale: float = 1.0
    pixel_width: int = 0
    pixel_height: int = 0

    @property
    def label(self) -> str:
        return "显示器 {0}".format(self.number)

    @property
    def work(self) -> Rect:
        return work_area(self.available, self.primary)

    @property
    def description(self) -> str:
        width = self.pixel_width or int(round(self.geometry.w * self.scale))
        height = self.pixel_height or int(round(self.geometry.h * self.scale))
        return "{0} · {1}×{2} · {3}%".format(self.label, width, height, int(round(self.scale * 100)))


def island_rect(island: IslandState) -> Rect:
    return Rect(int(island.x), int(island.y), int(island.width), int(island.height))


def primary_of(monitors: Sequence[MonitorSpec]) -> MonitorSpec:
    return next((monitor for monitor in monitors if monitor.primary), monitors[0])


def monitor_for_rect(rect: Rect, monitors: Sequence[MonitorSpec]) -> MonitorSpec:
    """Monitor containing the centre of ``rect`` (or the closest one)."""

    for monitor in monitors:
        if monitor.geometry.contains_point(rect.cx, rect.cy):
            return monitor
    best = max(monitors, key=lambda monitor: monitor.geometry.intersection_area(rect))
    if best.geometry.intersection_area(rect) > 0:
        return best
    return min(monitors, key=lambda monitor: monitor.geometry.distance_to_point(rect.cx, rect.cy))


def monitor_at(x: float, y: float, monitors: Sequence[MonitorSpec]) -> MonitorSpec:
    for monitor in monitors:
        if monitor.geometry.contains_point(x, y):
            return monitor
    return min(monitors, key=lambda monitor: monitor.geometry.distance_to_point(x, y))


def norm_of(rect: Rect, work: Rect) -> list[float]:
    if work.w <= 0 or work.h <= 0:
        return []
    return [round((rect.x - work.x) / work.w, 5), round((rect.y - work.y) / work.h, 5),
            round(rect.w / work.w, 5), round(rect.h / work.h, 5)]


def from_norm(norm: Sequence[float], work: Rect, min_w: int = 1, min_h: int = 1) -> Rect:
    x, y, w, h = norm
    width = max(min_w, int(round(w * work.w)))
    height = max(min_h, int(round(h * work.h)))
    return Rect(int(round(work.x + x * work.w)), int(round(work.y + y * work.h)), width, height)


def pages_of(state: AppState, key: str) -> list[PageState]:
    return [page for page in state.pages if page.monitor_key == key]


def guest_pages(state: AppState, monitors: Sequence[MonitorSpec]) -> list[PageState]:
    """Presets of monitors that are not connected right now."""

    connected = {monitor.key for monitor in monitors}
    return [page for page in state.pages if page.monitor_key not in connected]


def guest_label(page: PageState) -> str:
    return "来自 {0}".format(page.monitor_label or "其他显示器")


def migrate_state(state: AppState, monitors: Sequence[MonitorSpec]) -> bool:
    """Assign 1.2 pages to monitors and make sure every monitor has a preset.

    Returns ``True`` when ``state`` changed.
    """

    if not monitors:
        return False
    primary = primary_of(monitors)
    ordered = sorted(monitors, key=lambda monitor: monitor.number)
    changed = False
    pages: list[PageState] = []
    origin: dict[str, dict[str, str]] = {}
    for page in state.pages:
        if page.monitor_key:
            pages.append(page)
            continue
        changed = True
        buckets: dict[str, list[IslandState]] = {}
        for island in page.islands:
            buckets.setdefault(monitor_for_rect(island_rect(island), monitors).key, []).append(island)
        page.monitor_key = primary.key
        page.monitor_label = primary.label
        page.islands = buckets.pop(primary.key, [])
        pages.append(page)
        origin[page.id] = {primary.key: page.id}
        for monitor in ordered:
            islands = buckets.get(monitor.key)
            if not islands:
                continue
            split = PageState(title=page.title, islands=islands, monitor_key=monitor.key,
                              monitor_label=monitor.label)
            pages.append(split)
            origin[page.id][monitor.key] = split.id
    state.pages = pages
    if ensure_current_pages(state, monitors, origin):
        changed = True
    if state.version < STATE_VERSION:
        state.version = STATE_VERSION
        changed = True
    return changed


def ensure_current_pages(state: AppState, monitors: Sequence[MonitorSpec],
                         origin: dict[str, dict[str, str]] | None = None) -> bool:
    """Every connected monitor shows one of its presets (primary may show a guest)."""

    if not monitors:
        return False
    changed = False
    connected = {monitor.key: monitor for monitor in monitors}
    primary = primary_of(monitors)
    for page in state.pages:
        monitor = connected.get(page.monitor_key)
        if monitor is not None and page.monitor_label != monitor.label:
            page.monitor_label = monitor.label
            changed = True
    legacy_current = state.current_page_id
    for monitor in sorted(monitors, key=lambda item: item.number):
        page = state.page(state.current_pages.get(monitor.key, ""))
        if page is not None and (page.monitor_key == monitor.key
                                 or (monitor.primary and page.monitor_key not in connected)):
            continue
        chosen = ""
        if origin and legacy_current in origin:
            chosen = origin[legacy_current].get(monitor.key, "")
        if not chosen:
            own = pages_of(state, monitor.key)
            if own:
                chosen = own[0].id
        if not chosen and monitor.primary:
            # A replaced / renamed primary monitor keeps showing the preset the
            # previous primary showed, so the islands do not seem to vanish.
            inherited = state.page(legacy_current)
            if inherited is not None and inherited.monitor_key not in connected:
                chosen = inherited.id
        if not chosen:
            created = PageState(title=DEFAULT_PAGE_TITLE, monitor_key=monitor.key, monitor_label=monitor.label)
            state.pages.append(created)
            chosen = created.id
        state.current_pages[monitor.key] = chosen
        changed = True
    primary_page = state.current_pages.get(primary.key, "")
    if state.current_page_id != primary_page:
        state.current_page_id = primary_page
        changed = True
    return changed


def pages_for_menu(state: AppState, monitor: MonitorSpec,
                   monitors: Sequence[MonitorSpec]) -> list[tuple[PageState, bool]]:
    """Presets listed for ``monitor``: its own ones plus, on the primary
    monitor, those of disconnected monitors (flag ``True``)."""

    result = [(page, False) for page in pages_of(state, monitor.key)]
    if monitor.primary:
        result.extend((page, True) for page in guest_pages(state, monitors))
    return result


__all__ = [
    "DEFAULT_PAGE_TITLE", "MonitorSpec", "ensure_current_pages", "from_norm", "guest_label",
    "guest_pages", "island_rect", "migrate_state", "monitor_at", "monitor_for_rect", "norm_of",
    "pages_for_menu", "pages_of", "primary_of",
]

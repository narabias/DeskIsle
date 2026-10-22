"""Live layout operations on the displayed islands (port of 1.3 ``arranger``).

Every geometry change goes through the arranger: dragging (ghost target and
swapping), resizing (live clamp + push preview), expanding (pushes
neighbours), placing new islands, automatic arrangement, repairing a layout
after a monitor change and a small undo history.

The island *states* are the source of truth.  The arranger writes them and
tells the island proxies where to animate; QML only animates.  Coordinates
are board coordinates (logical pixels, origin = top-left of all monitors).

``host`` is the :class:`~deskisle.engine.controller.DeskController` and must
provide: ``monitors()``, ``displayed_page(key)``, ``proxy(id)``,
``board_bounds()``, ``queue_save()``, ``show_notice(title, text)``,
``set_ghosts(list)``, ``reassign(proxy, key)``, ``expand_now(proxy)`` and
``preferences``.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal

from .. import layout
from ..layout import Box, Rect
from ..monitors import MonitorSpec, from_norm, monitor_at, norm_of

UNDO_LIMIT = 30
WEB_KINDS = ("html", "web")
# Widget islands (clock, weather...) may be smaller than file islands.
WIDGET_MIN_W, WIDGET_MIN_H = 180, 120


def min_size(state) -> tuple[int, int]:
    kind = getattr(state, "kind", "files")
    if kind in WEB_KINDS:
        return layout.WEB_MIN_W, layout.WEB_MIN_H
    if kind == "widget":
        return WIDGET_MIN_W, WIDGET_MIN_H
    return layout.MIN_W, layout.MIN_H


def footprint(state) -> Rect:
    """The space an island occupies (collapsed: only its header pill)."""
    height = layout.COLLAPSED_H if state.collapsed else int(state.height)
    return Rect(int(state.x), int(state.y), int(state.width), height)


def expanded_rect(state) -> Rect:
    return Rect(int(state.x), int(state.y), int(state.width), int(state.height))


def box_of(state, rect: Rect | None = None) -> Box:
    rect = rect or footprint(state)
    min_w, min_h = min_size(state)
    pref_w = int(getattr(state, "pref_width", 0) or 0) or rect.w
    if state.collapsed:
        return Box(state.id, rect, min_w, layout.COLLAPSED_H, pref_w, layout.COLLAPSED_H, bool(state.locked))
    pref_h = int(getattr(state, "pref_height", 0) or 0) or rect.h
    return Box(state.id, rect, min_w, min_h, pref_w, pref_h, bool(state.locked))


@dataclass
class _Drag:
    proxy: object
    home: Rect
    home_key: str
    origin: tuple
    snapshot: dict
    moved: bool = False
    position: tuple = (0, 0)
    cursor: tuple | None = None
    target_key: str = ""
    ghost: Rect | None = None
    hover_id: str = ""
    ignore_id: str = ""
    swapped: bool = False


@dataclass
class _Resize:
    proxy: object
    edge: str
    key: str
    start: Rect
    snapshot: dict
    total: tuple = (0, 0)
    live: Rect | None = None
    preview: layout.PushResult | None = None
    moved: dict = field(default_factory=dict)


class Arranger(QObject):
    """Owns the layout of every displayed preset."""

    changed = Signal()          # undo availability changed

    def __init__(self, host) -> None:
        super().__init__(host if isinstance(host, QObject) else None)
        self.host = host
        self._undo: list[dict] = []
        self._undo_suppressed = 0
        self._quiet_collapse: set[str] = set()
        self._drag: _Drag | None = None
        self._resize: _Resize | None = None
        self._drag_timer = self._timer(16, self._drag_update)
        self._swap_timer = self._timer(layout.SWAP_HOVER_MS, self._swap_fire)
        self._resize_timer = self._timer(16, self._resize_update)

    def _timer(self, interval: int, slot) -> QTimer:
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(interval)
        timer.timeout.connect(slot)
        return timer

    # Accessors ------------------------------------------------------------------
    def monitors(self) -> list[MonitorSpec]:
        return list(self.host.monitors())

    def spec(self, key: str) -> MonitorSpec | None:
        return next((monitor for monitor in self.monitors() if monitor.key == key), None)

    def page(self, key: str):
        return self.host.displayed_page(key)

    def work(self, key: str) -> Rect:
        monitor = self.spec(key)
        return monitor.work if monitor is not None else Rect(0, 0, 0, 0)

    @property
    def gap(self) -> int:
        prefs = self.host.preferences
        return max(4, min(48, int(getattr(prefs, "layout_gap", layout.GAP) or layout.GAP)))

    @property
    def grid(self) -> int:
        prefs = self.host.preferences
        if not getattr(prefs, "snap_to_grid", False):
            return 0
        return max(0, int(getattr(prefs, "grid_size", 0) or 0))

    def proxy(self, island_id: str):
        return self.host.proxy(island_id)

    def islands(self, key: str) -> list:
        page = self.page(key)
        return list(page.islands) if page is not None else []

    def state_of(self, island_id: str):
        for monitor in self.monitors():
            for state in self.islands(monitor.key):
                if state.id == island_id:
                    return monitor.key, state
        return "", None

    def boxes(self, key: str, exclude=(), overrides: dict | None = None) -> list[Box]:
        overrides = overrides or {}
        return [box_of(state, overrides.get(state.id)) for state in self.islands(key) if state.id not in exclude]

    @staticmethod
    def _norm(state, work: Rect) -> list[float]:
        return norm_of(expanded_rect(state), work)

    # Applying layouts -------------------------------------------------------------
    def apply(self, key: str, rects: dict, animate: bool = True, allow_fade: bool = True) -> None:
        """Write footprints to the island states and move their proxies."""
        page = self.page(key)
        if page is None or not rects:
            return
        work = self.work(key)
        old = {state.id: footprint(state) for state in page.islands if state.id in rects}
        modes = layout.plan_transition(old, {k: rects[k] for k in old}) if animate and allow_fade else {}
        for state in page.islands:
            rect = rects.get(state.id)
            if rect is None:
                continue
            state.x, state.y, state.width = int(rect.x), int(rect.y), int(rect.w)
            if not state.collapsed:
                state.height = int(rect.h)
            state.norm = self._norm(state, work)
            proxy = self.proxy(state.id)
            if proxy is None:
                continue
            if proxy.monitor_key != key:
                self.host.reassign(proxy, key)
            if animate:
                proxy.animate_to(rect, "fade" if modes.get(state.id) == "fade" else "slide")
            else:
                proxy.set_geometry(rect)
        self.host.queue_save()

    def _changed(self, key: str, rects: dict) -> dict:
        current = {state.id: footprint(state) for state in self.islands(key)}
        return {k: v for k, v in rects.items() if k in current and current[k] != v}

    def fit_page(self, page, monitor: MonitorSpec) -> bool:
        """Make a stored preset valid on ``monitor`` (before proxies exist).

        Islands keep their absolute position unless the monitor's work area
        changed since the layout was saved (resolution, scaling, taskbar,
        arrangement); then the monitor-relative position is used.
        """
        work = monitor.work
        changed = False
        for state in page.islands:
            min_w, min_h = min_size(state)
            rect = Rect(int(state.x), int(state.y), max(min_w, int(state.width)), max(min_h, int(state.height)))
            norm = list(getattr(state, "norm", []) or [])
            if len(norm) == 4 and work.w > 0 and work.h > 0:
                mapped = from_norm(norm, work, min_w, min_h)
                off = max(abs(mapped.x - rect.x), abs(mapped.y - rect.y), abs(mapped.w - rect.w),
                          abs(mapped.h - rect.h))
                if off > 3:
                    rect = mapped
                    grid = self.grid
                    if grid > 1:
                        rect = Rect(int(round(rect.x / grid)) * grid, int(round(rect.y / grid)) * grid,
                                    rect.w, rect.h)
            if (rect.x, rect.y, rect.w, rect.h) != (state.x, state.y, state.width, state.height):
                changed = True
            state.x, state.y, state.width, state.height = rect.x, rect.y, rect.w, rect.h
            if not state.pref_width:
                state.pref_width = rect.w
            if not state.pref_height:
                state.pref_height = rect.h
        boxes = [box_of(state) for state in page.islands]
        rects = layout.repair(boxes, work, self.gap)
        for state in page.islands:
            rect = rects.get(state.id)
            if rect is None:
                continue
            if rect != footprint(state):
                changed = True
            state.x, state.y, state.width = rect.x, rect.y, rect.w
            if not state.collapsed:
                state.height = rect.h
            state.norm = self._norm(state, work)
        return changed

    def sync_norms(self) -> None:
        for monitor in self.monitors():
            work = monitor.work
            for state in self.islands(monitor.key):
                state.norm = self._norm(state, work)

    def repair_all(self, animate: bool = True) -> bool:
        changed = False
        for monitor in self.monitors():
            boxes = self.boxes(monitor.key)
            if not boxes:
                continue
            rects = self._changed(monitor.key, layout.repair(boxes, monitor.work, self.gap))
            if rects:
                changed = True
                self.apply(monitor.key, rects, animate)
        return changed

    def arrange(self, key: str) -> bool:
        """自动排布: tidy rows at preferred sizes.  ``False`` = not enough room."""
        boxes = self.boxes(key)
        if not boxes:
            return True
        result = layout.auto_arrange(boxes, self.work(key), self.gap)
        if result is None:
            return False
        rects = self._changed(key, result)
        if rects:
            self.push_undo()
            self.apply(key, rects)
        return True

    def place_new(self, key: str, state, target=None) -> bool:
        """Find room for a new island and add it to the displayed preset."""
        page = self.page(key)
        if page is None:
            return False
        work = self.work(key)
        min_w, min_h = min_size(state)
        wanted_w, wanted_h = max(min_w, int(state.width)), max(min_h, int(state.height))
        result = layout.place_new(self.boxes(key), wanted_w, wanted_h, min_w, min_h, work, self.gap,
                                  target, state.id)
        if result is None:
            return False
        moved = self._changed(key, result.rects)
        self.push_undo()
        if moved:
            self.apply(key, moved)
        rect = result.rect
        state.x, state.y, state.width, state.height = rect.x, rect.y, rect.w, rect.h
        state.pref_width, state.pref_height = wanted_w, wanted_h
        state.collapsed = False
        state.norm = self._norm(state, work)
        page.islands.append(state)
        return True

    def move_to(self, island_id: str, x=None, y=None, w=None, h=None) -> tuple[bool, str]:
        """Programmatic move / resize (agent ``island.update``).

        A new size pushes neighbours like an edge drag; a new position takes
        the nearest free spot like a title-bar drag.  Returns ``(ok, why)``.
        """
        _key, state = self.state_of(island_id)
        proxy = self.proxy(island_id)
        if state is None or proxy is None:
            return False, "island is not on a displayed preset"
        if state.locked:
            return False, "island is locked (island.update locked=false first)"
        key = proxy.monitor_key
        work = self.work(key)
        gap = self.gap
        before = self.snapshot()
        start = footprint(state)
        min_w, min_h = min_size(state)
        changed: dict = {}
        current = start
        if w is not None or h is not None:
            want_w = max(min_w, min(work.w, int(w if w is not None else start.w)))
            want_h = start.h if state.collapsed else max(min_h, min(work.h, int(h if h is not None else start.h)))
            requested = Rect(start.x, start.y, want_w, want_h)
            if requested.right > work.right:
                requested = Rect(max(work.x, work.right - want_w), requested.y, want_w, want_h)
            if requested.bottom > work.bottom:
                requested = Rect(requested.x, max(work.y, work.bottom - want_h), want_w, want_h)
            boxes = self.boxes(key, exclude={state.id}) + [box_of(state, start)]
            result = layout.resize_with_push(boxes, state.id, requested, work, gap)
            changed = dict(result.rects)
            current = result.active
            changed[state.id] = current
            state.pref_width, state.pref_height = current.w, (current.h if not state.collapsed else state.pref_height)
        if x is not None or y is not None:
            tx = int(x) if x is not None else current.x
            ty = int(y) if y is not None else current.y
            obstacles = [changed.get(b.id, b.rect) for b in self.boxes(key, exclude={state.id})]
            found = layout.nearest_grid_position(current.w, current.h, tx, ty, obstacles, work, gap, self.grid)
            if found is None:
                return False, "no free spot of that size on this monitor"
            current = Rect(found[0], found[1], current.w, current.h)
            changed[state.id] = current
        changed = {k: v for k, v in changed.items() if k == state.id or self._changed(key, {k: v})}
        if not changed or (len(changed) == 1 and changed.get(state.id) == start):
            return True, ""
        self.push_undo(before)
        self.apply(key, changed)
        self.relax(key, exclude=(state.id,))
        return True, ""

    def relax(self, key: str, exclude=()) -> None:
        boxes = self.boxes(key)
        if not boxes:
            return
        ids = [box.id for box in boxes if box.id not in exclude]
        rects = self._changed(key, layout.relax(boxes, self.work(key), self.gap, ids))
        if rects:
            self.apply(key, rects)

    # Expand / collapse ----------------------------------------------------------
    def request_expand(self, proxy) -> bool:
        """Make room before an island expands; ``False`` cancels the expand."""
        key = proxy.monitor_key
        state = proxy.state
        _min_w, min_h = min_size(state)
        height = max(min_h, int(state.pref_height or state.height or min_h))
        result = layout.expand_with_push(self.boxes(key), state.id, height, min_h, self.work(key), self.gap)
        if result is None:
            self.host.show_notice(
                "空间不足",
                "当前显示器没有足够空间展开“{0}”。可以先收起、缩小或移走其他收纳岛。".format(state.title),
            )
            return False
        snapshot = self.snapshot()
        neighbours = {k: v for k, v in self._changed(key, result.rects).items() if k != state.id}
        if result.mode == "relocated":
            self.push_undo(snapshot)
            target = result.active
            state.height = int(target.h)
            if neighbours:
                self.apply(key, neighbours)
            pill = Rect(target.x, target.y, target.w, layout.COLLAPSED_H)
            state.x, state.y, state.width = pill.x, pill.y, pill.w
            state.norm = self._norm(state, self.work(key))
            self.host.queue_save()
            proxy.animate_to(pill, "slide")
            QTimer.singleShot(300, lambda: self.host.expand_now(proxy))
            return False
        if neighbours:
            self.push_undo(snapshot)
            self.apply(key, neighbours)
        state.height = int(result.active.h)
        state.norm = self._norm(state, self.work(key))
        return True

    def after_collapse(self, proxy) -> None:
        if proxy.state.id in self._quiet_collapse:
            self._quiet_collapse.discard(proxy.state.id)
            return
        self.relax(proxy.monitor_key, exclude=(proxy.state.id,))

    # Dragging -------------------------------------------------------------------
    def drag_active(self) -> bool:
        return self._drag is not None

    def dragged_id(self) -> str:
        return self._drag.proxy.state.id if self._drag is not None else ""

    def drag_begin(self, proxy) -> None:
        self.cancel_gestures()
        state = proxy.state
        rect = footprint(state)
        self._drag = _Drag(proxy, rect, proxy.monitor_key, (rect.x, rect.y), self.snapshot(),
                           position=(rect.x, rect.y))
        proxy.raise_()

    def drag_move(self, proxy, x: float, y: float, cursor: tuple | None = None) -> None:
        drag = self._drag
        if drag is None or drag.proxy is not proxy:
            return
        bounds = self.host.board_bounds()
        rect = footprint(proxy.state)
        x = min(max(int(x), bounds.x), max(bounds.x, bounds.right - rect.w))
        y = min(max(int(y), bounds.y), max(bounds.y, bounds.bottom - rect.h))
        if not drag.moved and abs(x - drag.origin[0]) + abs(y - drag.origin[1]) > 3:
            drag.moved = True
        drag.position = (x, y)
        drag.cursor = (int(cursor[0]), int(cursor[1])) if cursor is not None else None
        proxy.set_geometry(Rect(x, y, rect.w, rect.h), live=True)
        self.host.drag_shadow(proxy, Rect(x, y, rect.w, rect.h))
        if drag.moved and not self._drag_timer.isActive():
            self._drag_timer.start()

    def _drag_update(self) -> None:
        drag = self._drag
        if drag is None or not drag.moved:
            return
        state = drag.proxy.state
        size = footprint(state)
        x, y = drag.position
        monitors = self.monitors()
        if not monitors:
            return
        point = drag.cursor if drag.cursor is not None else (int(x + size.w / 2), int(y + size.h / 2))
        monitor = monitor_at(point[0], point[1], monitors)
        obstacles = [box.rect for box in self.boxes(monitor.key, exclude={state.id})]
        found = layout.nearest_grid_position(size.w, size.h, x, y, obstacles, monitor.work, self.gap, self.grid)
        drag.target_key = monitor.key
        drag.ghost = Rect(found[0], found[1], size.w, size.h) if found is not None else None
        self.host.set_ghosts([(drag.ghost, "target")] if drag.ghost is not None else [])
        self._update_hover(drag, monitor.key, point)

    def _update_hover(self, drag: _Drag, key: str, point: tuple) -> None:
        hovered = ""
        if key == drag.home_key:
            for state in self.islands(key):
                if state.id == drag.proxy.state.id or state.locked:
                    continue
                if footprint(state).contains_point(point[0], point[1]):
                    hovered = state.id
                    break
        if drag.ignore_id and hovered != drag.ignore_id:
            drag.ignore_id = ""
        if hovered == drag.ignore_id:
            hovered = ""
        if hovered == drag.hover_id:
            return
        previous = self.proxy(drag.hover_id) if drag.hover_id else None
        if previous is not None:
            previous.set_hint("")
        drag.hover_id = hovered
        self._swap_timer.stop()
        if hovered:
            proxy = self.proxy(hovered)
            if proxy is not None:
                proxy.set_hint("swap")
            self._swap_timer.start()

    def _swap_fire(self) -> None:
        drag = self._drag
        if drag is None or not drag.hover_id:
            return
        key = drag.home_key
        a_id, b_id = drag.proxy.state.id, drag.hover_id
        boxes = self.boxes(key, overrides={a_id: drag.home})
        result = layout.swap_targets(boxes, a_id, b_id, drag.home, self.work(key), self.gap)
        partner = self.proxy(b_id)
        if partner is not None:
            partner.set_hint("")
        if result is None:
            drag.ignore_id, drag.hover_id = b_id, ""
            return
        a_rect, b_rect = result
        self.apply(key, {b_id: b_rect}, allow_fade=False)
        drag.home = a_rect
        drag.swapped = True
        drag.ignore_id, drag.hover_id = b_id, ""
        self._drag_update()

    def drag_end(self, proxy) -> None:
        drag = self._drag
        if drag is None or drag.proxy is not proxy:
            return
        if drag.moved:
            self._drag_update()
        self._drag = None
        self._drag_timer.stop()
        self._swap_timer.stop()
        self._clear_hints()
        self.host.set_ghosts([])
        self.host.drag_shadow(None, None)
        state = proxy.state
        if not drag.moved and not drag.swapped:
            proxy.animate_to(footprint(state), "slide")
            return
        key, rect = drag.target_key or drag.home_key, drag.ghost
        if rect is None:
            key, rect = drag.home_key, drag.home
        if key != drag.home_key:
            source, target = self.page(drag.home_key), self.page(key)
            if source is not None and target is not None and state in source.islands:
                source.islands.remove(state)
                target.islands.append(state)
                self.host.reassign(proxy, key)
        before = drag.snapshot["islands"].get(state.id)
        unchanged = before is not None and (before[1], before[2], before[3]) == (rect.x, rect.y, rect.w)
        if not unchanged or key != drag.home_key or drag.swapped:
            self.push_undo(drag.snapshot)
        self.apply(key, {state.id: rect}, allow_fade=False)
        if key != drag.home_key:
            self.relax(drag.home_key)

    # Resizing -------------------------------------------------------------------
    def resize_active(self) -> bool:
        return self._resize is not None

    def resize_begin(self, proxy, edge: str) -> None:
        self.cancel_gestures()
        self._resize = _Resize(proxy, edge, proxy.monitor_key, footprint(proxy.state), self.snapshot())

    def resize_move(self, proxy, dx: float, dy: float) -> None:
        resize = self._resize
        if resize is None or resize.proxy is not proxy:
            return
        resize.total = (int(dx), int(dy))
        if not self._resize_timer.isActive():
            self._resize_timer.start()

    def _requested_rect(self, resize: _Resize) -> Rect:
        state = resize.proxy.state
        work = self.work(resize.key)
        grid = self.grid
        min_w, min_h = min_size(state)
        start = resize.start
        edges = set(resize.edge.split("-"))
        left, top, right, bottom = start.x, start.y, start.right, start.bottom
        dx, dy = resize.total

        def snap(value: int, origin: int) -> int:
            return origin + int(round((value - origin) / grid)) * grid if grid > 1 else value

        if "right" in edges:
            right = max(left + min_w, snap(start.right + dx, work.x))
        if "left" in edges:
            left = min(right - min_w, snap(start.x + dx, work.x))
        if "bottom" in edges:
            bottom = max(top + min_h, snap(start.bottom + dy, work.y))
        left = max(left, min(work.x, start.x))
        right = min(right, max(work.right, start.right))
        bottom = min(bottom, max(work.bottom, start.bottom))
        return Rect(left, top, right - left, bottom - top)

    def _resize_update(self) -> None:
        resize = self._resize
        if resize is None:
            return
        proxy = resize.proxy
        state = proxy.state
        key = resize.key
        work = self.work(key)
        gap = self.gap
        start = resize.start
        requested = self._requested_rect(resize)
        others = self.boxes(key, exclude={state.id})
        boxes = others + [box_of(state, start)]
        edges = set(resize.edge.split("-"))
        live_left, live_right, live_bottom = requested.x, requested.right, requested.bottom
        push = False
        if "right" in edges and requested.right > start.right:
            limit = layout.free_extent(boxes, state.id, start, "right", work, gap)
            live_right = min(requested.right, limit)
            push = push or (limit < work.right and requested.right - limit > layout.PUSH_THRESHOLD)
        if "left" in edges and requested.x < start.x:
            limit = layout.free_extent(boxes, state.id, start, "left", work, gap)
            live_left = max(requested.x, limit)
            push = push or (limit > work.x and limit - requested.x > layout.PUSH_THRESHOLD)
        if "bottom" in edges and requested.bottom > start.bottom:
            band = Rect(live_left, start.y, live_right - live_left, start.h)
            limit = layout.free_extent(boxes, state.id, band, "bottom", work, gap)
            live_bottom = min(requested.bottom, limit)
            push = push or (limit < work.bottom and requested.bottom - limit > layout.PUSH_THRESHOLD)
        live = Rect(live_left, start.y, max(1, live_right - live_left), max(1, live_bottom - start.y))
        resize.live = live
        proxy.set_geometry(live, live=True)
        if push:
            result = layout.resize_with_push(boxes, state.id, requested, work, gap)
            current = {box.id: box.rect for box in others}
            moved = {k: v for k, v in result.rects.items() if k in current and current[k] != v}
            resize.preview = result
            ghosts = [(result.active, "target")] + [(rect, "moved") for rect in moved.values()]
            self._show_preview(key, ghosts, set(moved), state.id)
        else:
            resize.preview = None
            self._show_preview(key, [], set(), state.id)

    def _show_preview(self, key: str, ghosts: list, hatched: set, active_id: str) -> None:
        self.host.set_ghosts(ghosts)
        for state in self.islands(key):
            proxy = self.proxy(state.id)
            if proxy is not None and state.id != active_id:
                proxy.set_hint("hatch" if state.id in hatched else "")

    def resize_end(self, proxy) -> None:
        resize = self._resize
        if resize is None or resize.proxy is not proxy:
            return
        self._resize_timer.stop()
        self._resize_update()
        self._resize = None
        self._clear_hints()
        self.host.set_ghosts([])
        state = proxy.state
        key = resize.key
        if resize.preview is not None:
            rects = dict(resize.preview.rects)
            active = rects[state.id]
            state.pref_width, state.pref_height = active.w, active.h
            changed = self._changed(key, rects)
            changed[state.id] = active
            self.push_undo(resize.snapshot)
            self.apply(key, changed, allow_fade=False)
        else:
            live = resize.live or resize.start
            state.pref_width, state.pref_height = live.w, live.h
            if live != resize.start:
                self.push_undo(resize.snapshot)
            self.apply(key, {state.id: live}, animate=False)
        self.relax(key, exclude=(state.id,))
        self.host.queue_save()

    def cancel_gestures(self) -> None:
        """Abort a running drag / resize; the island returns to its slot."""
        drag, resize = self._drag, self._resize
        self._drag = None
        self._resize = None
        self._drag_timer.stop()
        self._swap_timer.stop()
        self._resize_timer.stop()
        if drag is None and resize is None:
            return
        self._clear_hints()
        self.host.set_ghosts([])
        self.host.drag_shadow(None, None)
        if drag is not None and drag.proxy.state in self.islands(drag.home_key):
            self.apply(drag.home_key, {drag.proxy.state.id: drag.home}, allow_fade=False)
        if resize is not None and resize.proxy.state in self.islands(resize.key):
            self.apply(resize.key, {resize.proxy.state.id: footprint(resize.proxy.state)}, allow_fade=False)

    def _clear_hints(self) -> None:
        for monitor in self.monitors():
            for state in self.islands(monitor.key):
                proxy = self.proxy(state.id)
                if proxy is not None:
                    proxy.set_hint("")

    # Undo -----------------------------------------------------------------------
    def snapshot(self) -> dict:
        keys: dict[str, str] = {}
        pages: dict[str, list[str]] = {}
        islands: dict[str, tuple] = {}
        for monitor in self.monitors():
            page = self.page(monitor.key)
            if page is None:
                continue
            keys[monitor.key] = page.id
            pages[page.id] = [state.id for state in page.islands]
            for state in page.islands:
                islands[state.id] = (page.id, int(state.x), int(state.y), int(state.width), int(state.height),
                                     bool(state.collapsed), int(state.pref_width), int(state.pref_height))
        return {"keys": keys, "pages": pages, "islands": islands}

    def push_undo(self, snapshot: dict | None = None) -> None:
        if self._undo_suppressed:
            return
        snapshot = snapshot or self.snapshot()
        if self._undo and self._undo[-1] == snapshot:
            return
        self._undo.append(snapshot)
        del self._undo[:-UNDO_LIMIT]
        self.changed.emit()

    @contextmanager
    def batch(self):
        """Group several layout operations into a single undo step."""
        before = None if self._undo_suppressed else self.snapshot()
        self._undo_suppressed += 1
        try:
            yield
        finally:
            self._undo_suppressed -= 1
        if before is not None and before != self.snapshot():
            self.push_undo(before)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def clear_undo(self) -> None:
        if self._undo:
            self._undo.clear()
            self.changed.emit()

    def undo(self) -> bool:
        """撤销排布: restore the layout before the last layout operation."""
        self.cancel_gestures()
        restored = False
        while self._undo and not restored:
            restored = self._restore(self._undo.pop())
        self.changed.emit()
        return restored

    def restore_snapshot(self, snapshot: dict) -> bool:
        """Put the islands back where ``snapshot`` says (capsule folded back to its pill)."""
        self.cancel_gestures()
        restored = self._restore(snapshot)
        if restored:
            self.changed.emit()
        return restored

    def _restore(self, snapshot: dict) -> bool:
        current = {monitor.key: self.page(monitor.key) for monitor in self.monitors()}
        for key, page_id in snapshot["keys"].items():
            page = current.get(key)
            if page is None or page.id != page_id:
                return False
        if self.snapshot() == snapshot:
            return False
        by_page = {page.id: (key, page) for key, page in current.items() if page is not None}
        located: dict[str, tuple[str, object]] = {}
        for key, page in current.items():
            if page is None:
                continue
            for state in page.islands:
                located[state.id] = (key, state)
        for island_id, values in snapshot["islands"].items():
            if island_id not in located or values[0] not in by_page:
                continue
            key, state = located[island_id]
            home_key, home_page = by_page[values[0]]
            if key != home_key:
                self.page(key).islands.remove(state)
                home_page.islands.append(state)
                proxy = self.proxy(island_id)
                if proxy is not None:
                    self.host.reassign(proxy, home_key)
                located[island_id] = (home_key, state)
        for page_id, order in snapshot["pages"].items():
            if page_id not in by_page:
                continue
            page = by_page[page_id][1]
            rank = {island_id: index for index, island_id in enumerate(order)}
            page.islands.sort(key=lambda state: rank.get(state.id, len(rank)))
        for island_id, values in snapshot["islands"].items():
            if island_id not in located:
                continue
            _key, state = located[island_id]
            _page, _x, _y, _width, height, collapsed, pref_w, pref_h = values
            if collapsed != bool(state.collapsed):
                state.collapsed = collapsed
                proxy = self.proxy(island_id)
                if proxy is not None:
                    proxy.refresh()
            state.height = height
            state.pref_width, state.pref_height = pref_w, pref_h
        for key, page in current.items():
            if page is None:
                continue
            boxes = []
            for state in page.islands:
                values = snapshot["islands"].get(state.id)
                if values is None:
                    boxes.append(box_of(state))
                    continue
                _page, x, y, width, height, _collapsed, _pw, _ph = values
                rect = Rect(x, y, width, layout.COLLAPSED_H if state.collapsed else height)
                boxes.append(Box(state.id, rect, rect.w, rect.h, rect.w, rect.h, True))
            rects = layout.repair(boxes, self.work(key), self.gap)
            self.apply(key, rects)
        self.host.queue_save()
        return True


__all__ = ["Arranger", "box_of", "expanded_rect", "footprint", "min_size"]

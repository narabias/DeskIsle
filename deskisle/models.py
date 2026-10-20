"""Serializable application state models for DeskIsle.

The models intentionally contain only JSON-friendly state.  In particular,
``ItemRef`` is a reference to a file system item; putting it in an island does
not move or otherwise mutate the referenced file.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from os import PathLike, fspath
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .grid_layout import SIZE_LEVELS


def _new_id() -> str:
    return str(uuid4())


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (str, PathLike)):
        try:
            return fspath(value)
        except TypeError:
            return default
    if isinstance(value, (int, float, bool)):
        return str(value)
    return default


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    result = _as_str(value).strip()
    return result or None


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"1", "true", "yes", "on", "enabled"}:
            return True
        if normalized in {"0", "false", "no", "off", "disabled", ""}:
            return False
    return default


def _as_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_float(value: Any, default: float) -> float:
    if isinstance(value, bool):
        return default
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _choice(value: Any, allowed: Iterable[str], default: str) -> str:
    text = _as_str(value, default).strip().casefold()
    return text if text in set(allowed) else default


def _extras(raw: Mapping[str, Any], known: Iterable[str]) -> dict[str, Any]:
    """Keep keys written by newer DeskIsle versions.

    Updating (or temporarily downgrading) must never silently drop settings the
    running version does not understand; they are written back unchanged.
    """

    known_keys = set(known)
    return {
        str(key): copy.deepcopy(value)
        for key, value in raw.items()
        if isinstance(key, str) and key not in known_keys
    }


def _with_extras(extra: Mapping[str, Any], known: dict[str, Any]) -> dict[str, Any]:
    if not extra:
        return known
    merged = copy.deepcopy(dict(extra))
    merged.update(known)
    return merged


ISLAND_KINDS = ("files", "html", "web")
MATERIALS = ("clear", "frosted", "liquid")
GRID_MOVE_MODES = ("swap", "reorder")


@dataclass
class ItemRef:
    path: str = ""
    title: str = ""
    pinned: bool = False
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return _with_extras(self.extra, {
            "path": self.path,
            "title": self.title,
            "pinned": self.pinned,
        })

    @classmethod
    def from_dict(cls, data: Any) -> "ItemRef":
        if isinstance(data, cls):
            data = data.to_dict()
        if isinstance(data, (str, PathLike)):
            return cls(path=_as_str(data))
        raw = _mapping(data)
        return cls(
            path=_as_str(raw.get("path")),
            title=_as_str(raw.get("title")),
            pinned=_as_bool(raw.get("pinned"), False),
            extra=_extras(raw, ("path", "title", "pinned")),
        )


@dataclass
class TabState:
    id: str = field(default_factory=_new_id)
    title: str = "全部"
    portal_path: str | None = None
    items: list[ItemRef] = field(default_factory=list)
    sort_mode: str = "name"
    sort_descending: bool = False
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    _KNOWN = ("id", "title", "portal_path", "items", "sort_mode", "sort_descending")

    def to_dict(self) -> dict[str, Any]:
        return _with_extras(self.extra, {
            "id": self.id,
            "title": self.title,
            "portal_path": self.portal_path,
            "items": [item.to_dict() for item in self.items],
            "sort_mode": self.sort_mode,
            "sort_descending": self.sort_descending,
        })

    @classmethod
    def from_dict(cls, data: Any) -> "TabState":
        if isinstance(data, cls):
            data = data.to_dict()
        raw = _mapping(data)
        items: list[ItemRef] = []
        for item in _as_list(raw.get("items")):
            if isinstance(item, (ItemRef, Mapping, str, PathLike)):
                parsed = ItemRef.from_dict(item)
                if parsed.path:
                    items.append(parsed)
        return cls(
            id=_as_str(raw.get("id")) or _new_id(),
            title=_as_str(raw.get("title"), "全部"),
            portal_path=_as_optional_str(raw.get("portal_path")),
            items=items,
            sort_mode=_as_str(raw.get("sort_mode"), "name") or "name",
            sort_descending=_as_bool(raw.get("sort_descending"), False),
            extra=_extras(raw, cls._KNOWN),
        )


@dataclass
class IslandState:
    id: str = field(default_factory=_new_id)
    title: str = "收纳岛"
    x: int = 32
    y: int = 32
    width: int = 360
    height: int = 260
    color: str = "#4F7CAC"
    collapsed: bool = False
    locked: bool = False
    icon_size: int = 48
    active_tab_id: str = ""
    tabs: list[TabState] = field(default_factory=list)
    exclude_from_hide: bool = False
    # "files" = normal/portal island, "html" = local HTML animation,
    # "web" = pinned browser window.
    kind: str = "files"
    html_path: str = ""
    html_allow_network: bool = False
    web_url: str = ""
    web_toolbar: bool = True
    web_zoom: float = 1.0
    web_refresh_minutes: int = 0
    pin_on_top: bool = False
    # "" follows Preferences.island_material.
    material: str = ""
    media_path: str = ""
    media_opacity: float = 0.9
    media_feather: int = 26
    # Size level used by the automatic arrangement mode ("quarter"/"third"/
    # "half"/"full"); ignored while a page is in free layout.
    size_level: str = "half"
    # Board position in micro cells for the arrangement mode; -1 means "not
    # placed yet" and lets the layout engine pick the first free slot.
    grid_col: int = -1
    grid_row: int = -1
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    _KNOWN = (
        "id", "title", "x", "y", "width", "height", "color", "collapsed", "locked",
        "icon_size", "active_tab_id", "tabs", "exclude_from_hide", "kind", "html_path",
        "html_allow_network", "web_url", "web_toolbar", "web_zoom", "web_refresh_minutes",
        "pin_on_top", "material", "media_path", "media_opacity", "media_feather",
        "size_level", "grid_col", "grid_row",
    )

    def __post_init__(self) -> None:
        if self.tabs and not self.active_tab_id:
            self.active_tab_id = self.tabs[0].id

    @property
    def is_web_content(self) -> bool:
        return self.kind in ("html", "web")

    def to_dict(self) -> dict[str, Any]:
        return _with_extras(self.extra, {
            "id": self.id,
            "title": self.title,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "color": self.color,
            "collapsed": self.collapsed,
            "locked": self.locked,
            "icon_size": self.icon_size,
            "active_tab_id": self.active_tab_id,
            "tabs": [tab.to_dict() for tab in self.tabs],
            "exclude_from_hide": self.exclude_from_hide,
            "kind": self.kind,
            "html_path": self.html_path,
            "html_allow_network": self.html_allow_network,
            "web_url": self.web_url,
            "web_toolbar": self.web_toolbar,
            "web_zoom": self.web_zoom,
            "web_refresh_minutes": self.web_refresh_minutes,
            "pin_on_top": self.pin_on_top,
            "material": self.material,
            "media_path": self.media_path,
            "media_opacity": self.media_opacity,
            "media_feather": self.media_feather,
            "size_level": self.size_level,
            "grid_col": self.grid_col,
            "grid_row": self.grid_row,
        })

    @classmethod
    def from_dict(cls, data: Any) -> "IslandState":
        if isinstance(data, cls):
            data = data.to_dict()
        raw = _mapping(data)
        tabs = [
            TabState.from_dict(tab)
            for tab in _as_list(raw.get("tabs"))
            if isinstance(tab, (TabState, Mapping))
        ]
        active_tab_id = _as_str(raw.get("active_tab_id"))
        tab_ids = {tab.id for tab in tabs}
        if tabs and active_tab_id not in tab_ids:
            active_tab_id = tabs[0].id
        material = _as_str(raw.get("material")).strip().casefold()
        return cls(
            id=_as_str(raw.get("id")) or _new_id(),
            title=_as_str(raw.get("title"), "收纳岛"),
            x=_as_int(raw.get("x"), 32),
            y=_as_int(raw.get("y"), 32),
            width=max(1, _as_int(raw.get("width"), 360)),
            height=max(1, _as_int(raw.get("height"), 260)),
            color=_as_str(raw.get("color"), "#4F7CAC") or "#4F7CAC",
            collapsed=_as_bool(raw.get("collapsed"), False),
            locked=_as_bool(raw.get("locked"), False),
            icon_size=max(1, _as_int(raw.get("icon_size"), 48)),
            active_tab_id=active_tab_id,
            tabs=tabs,
            exclude_from_hide=_as_bool(raw.get("exclude_from_hide"), False),
            kind=_choice(raw.get("kind"), ISLAND_KINDS, "files"),
            html_path=_as_str(raw.get("html_path")),
            html_allow_network=_as_bool(raw.get("html_allow_network"), False),
            web_url=_as_str(raw.get("web_url")).strip(),
            web_toolbar=_as_bool(raw.get("web_toolbar"), True),
            web_zoom=_clamp(_as_float(raw.get("web_zoom"), 1.0), 0.25, 5.0),
            web_refresh_minutes=int(_clamp(_as_int(raw.get("web_refresh_minutes"), 0), 0, 1440)),
            pin_on_top=_as_bool(raw.get("pin_on_top"), False),
            material=material if material in MATERIALS else "",
            media_path=_as_str(raw.get("media_path")),
            media_opacity=_clamp(_as_float(raw.get("media_opacity"), 0.9), 0.1, 1.0),
            media_feather=int(_clamp(_as_int(raw.get("media_feather"), 26), 0, 120)),
            size_level=_choice(raw.get("size_level"), SIZE_LEVELS, "half"),
            grid_col=_as_int(raw.get("grid_col"), -1),
            grid_row=_as_int(raw.get("grid_row"), -1),
            extra=_extras(raw, cls._KNOWN),
        )


@dataclass
class PageState:
    id: str = field(default_factory=_new_id)
    title: str = "主页"
    islands: list[IslandState] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return _with_extras(self.extra, {
            "id": self.id,
            "title": self.title,
            "islands": [island.to_dict() for island in self.islands],
        })

    @classmethod
    def from_dict(cls, data: Any) -> "PageState":
        if isinstance(data, cls):
            data = data.to_dict()
        raw = _mapping(data)
        islands = [
            IslandState.from_dict(island)
            for island in _as_list(raw.get("islands"))
            if isinstance(island, (IslandState, Mapping))
        ]
        return cls(
            id=_as_str(raw.get("id")) or _new_id(),
            title=_as_str(raw.get("title"), "主页"),
            islands=islands,
            extra=_extras(raw, ("id", "title", "islands")),
        )


@dataclass
class Rule:
    id: str = field(default_factory=_new_id)
    name: str = "新规则"
    condition: str = "extension"
    value: str = ""
    target_island_id: str = ""
    enabled: bool = True
    priority: int = 100
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return _with_extras(self.extra, {
            "id": self.id,
            "name": self.name,
            "condition": self.condition,
            "value": self.value,
            "target_island_id": self.target_island_id,
            "enabled": self.enabled,
            "priority": self.priority,
        })

    @classmethod
    def from_dict(cls, data: Any) -> "Rule":
        if isinstance(data, cls):
            data = data.to_dict()
        raw = _mapping(data)
        return cls(
            id=_as_str(raw.get("id")) or _new_id(),
            name=_as_str(raw.get("name"), "未命名规则"),
            condition=_as_str(raw.get("condition")).strip().casefold(),
            value=_as_str(raw.get("value")),
            target_island_id=_as_str(raw.get("target_island_id")),
            enabled=_as_bool(raw.get("enabled"), True),
            priority=_as_int(raw.get("priority"), 100),
            extra=_extras(raw, ("id", "name", "condition", "value", "target_island_id", "enabled", "priority")),
        )


@dataclass
class Preferences:
    hide_native_icons: bool = True
    snap_to_grid: bool = True
    grid_size: int = 8
    auto_organize: bool = True
    start_with_windows: bool = False
    panel_opacity: float = 0.88
    toolbar_x: int = -1
    toolbar_y: int = 14
    onboarding_done: bool = False
    # Appearance
    island_material: str = "frosted"
    backdrop_source: str = "wallpaper"
    backdrop_image: str = ""
    font_family: str = ""
    font_file: str = ""
    font_size: float = 10.0
    # Motion and performance
    reduce_motion: bool = False
    smart_pause: bool = True
    media_fps: int = 24
    # Updates (only the switch lives here; bookkeeping is kept in update.json)
    auto_check_updates: bool = True
    # Automatic arrangement mode
    auto_layout: bool = False
    # "swap" = exchange two positions, "reorder" = insert and shift the rest.
    grid_move_mode: str = "swap"
    edge_switch_enabled: bool = True
    edge_switch_width: int = 28
    edge_switch_delay_ms: int = 420
    # "slide" / "fade" / "pinwheel" / "cube"
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    _KNOWN = (
        "hide_native_icons", "snap_to_grid", "grid_size", "auto_organize",
        "start_with_windows", "panel_opacity", "toolbar_x", "toolbar_y", "onboarding_done",
        "island_material", "backdrop_source", "backdrop_image", "font_family", "font_file",
        "font_size", "reduce_motion", "smart_pause", "media_fps", "auto_check_updates",
        "auto_layout", "grid_move_mode", "edge_switch_enabled", "edge_switch_width",
        "edge_switch_delay_ms",
    )

    def to_dict(self) -> dict[str, Any]:
        return _with_extras(self.extra, {
            "hide_native_icons": self.hide_native_icons,
            "snap_to_grid": self.snap_to_grid,
            "grid_size": self.grid_size,
            "auto_organize": self.auto_organize,
            "start_with_windows": self.start_with_windows,
            "panel_opacity": self.panel_opacity,
            "toolbar_x": self.toolbar_x,
            "toolbar_y": self.toolbar_y,
            "onboarding_done": self.onboarding_done,
            "island_material": self.island_material,
            "backdrop_source": self.backdrop_source,
            "backdrop_image": self.backdrop_image,
            "font_family": self.font_family,
            "font_file": self.font_file,
            "font_size": self.font_size,
            "reduce_motion": self.reduce_motion,
            "smart_pause": self.smart_pause,
            "media_fps": self.media_fps,
            "auto_check_updates": self.auto_check_updates,
            "auto_layout": self.auto_layout,
            "grid_move_mode": self.grid_move_mode,
            "edge_switch_enabled": self.edge_switch_enabled,
            "edge_switch_width": self.edge_switch_width,
            "edge_switch_delay_ms": self.edge_switch_delay_ms,
        })

    @classmethod
    def from_dict(cls, data: Any) -> "Preferences":
        if isinstance(data, cls):
            data = data.to_dict()
        raw = _mapping(data)
        opacity = min(1.0, max(0.0, _as_float(raw.get("panel_opacity"), 0.88)))
        return cls(
            hide_native_icons=_as_bool(raw.get("hide_native_icons"), True),
            snap_to_grid=_as_bool(raw.get("snap_to_grid"), True),
            grid_size=max(1, _as_int(raw.get("grid_size"), 8)),
            auto_organize=_as_bool(raw.get("auto_organize"), True),
            start_with_windows=_as_bool(raw.get("start_with_windows"), False),
            panel_opacity=opacity,
            toolbar_x=_as_int(raw.get("toolbar_x"), -1),
            toolbar_y=_as_int(raw.get("toolbar_y"), 14),
            onboarding_done=_as_bool(raw.get("onboarding_done"), False),
            island_material=_choice(raw.get("island_material"), MATERIALS, "frosted"),
            backdrop_source=_choice(raw.get("backdrop_source"), ("wallpaper", "image"), "wallpaper"),
            backdrop_image=_as_str(raw.get("backdrop_image")),
            font_family=_as_str(raw.get("font_family")).strip(),
            font_file=_as_str(raw.get("font_file")).strip(),
            font_size=_clamp(_as_float(raw.get("font_size"), 10.0), 7.0, 20.0),
            reduce_motion=_as_bool(raw.get("reduce_motion"), False),
            smart_pause=_as_bool(raw.get("smart_pause"), True),
            media_fps=int(_clamp(_as_int(raw.get("media_fps"), 24), 5, 60)),
            auto_check_updates=_as_bool(raw.get("auto_check_updates"), True),
            auto_layout=_as_bool(raw.get("auto_layout"), False),
            grid_move_mode=_choice(raw.get("grid_move_mode"), GRID_MOVE_MODES, "swap"),
            edge_switch_enabled=_as_bool(raw.get("edge_switch_enabled"), True),
            edge_switch_width=int(_clamp(_as_int(raw.get("edge_switch_width"), 28), 8, 120)),
            edge_switch_delay_ms=int(_clamp(_as_int(raw.get("edge_switch_delay_ms"), 420), 120, 1500)),
            extra=_extras(raw, cls._KNOWN),
        )


@dataclass
class AppState:
    version: int = 1
    current_page_id: str = ""
    pages: list[PageState] = field(default_factory=list)
    loose_items: list[ItemRef] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    preferences: Preferences = field(default_factory=Preferences)
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.pages and not self.current_page_id:
            self.current_page_id = self.pages[0].id

    def to_dict(self) -> dict[str, Any]:
        return _with_extras(self.extra, {
            "version": self.version,
            "current_page_id": self.current_page_id,
            "pages": [page.to_dict() for page in self.pages],
            "loose_items": [item.to_dict() for item in self.loose_items],
            "rules": [rule.to_dict() for rule in self.rules],
            "preferences": self.preferences.to_dict(),
        })

    @classmethod
    def from_dict(cls, data: Any) -> "AppState":
        if isinstance(data, cls):
            data = data.to_dict()
        raw = _mapping(data)
        pages = [
            PageState.from_dict(page)
            for page in _as_list(raw.get("pages"))
            if isinstance(page, (PageState, Mapping))
        ]
        rules = [
            Rule.from_dict(rule)
            for rule in _as_list(raw.get("rules"))
            if isinstance(rule, (Rule, Mapping))
        ]
        loose_items: list[ItemRef] = []
        for item in _as_list(raw.get("loose_items")):
            if isinstance(item, (ItemRef, Mapping, str, PathLike)):
                parsed = ItemRef.from_dict(item)
                if parsed.path:
                    loose_items.append(parsed)
        current_page_id = _as_str(raw.get("current_page_id"))
        page_ids = {page.id for page in pages}
        if pages and current_page_id not in page_ids:
            current_page_id = pages[0].id
        return cls(
            version=max(1, _as_int(raw.get("version"), 1)),
            current_page_id=current_page_id,
            pages=pages,
            loose_items=loose_items,
            rules=rules,
            preferences=Preferences.from_dict(raw.get("preferences")),
            extra=_extras(raw, ("version", "current_page_id", "pages", "loose_items", "rules", "preferences")),
        )


__all__ = [
    "ISLAND_KINDS",
    "MATERIALS",
    "AppState",
    "IslandState",
    "ItemRef",
    "PageState",
    "Preferences",
    "Rule",
    "TabState",
]

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


def _as_color(value: Any, default: str) -> str:
    """Return ``#RRGGBB`` (upper case) or ``default`` for anything else."""

    text = _as_str(value).strip()
    if text.startswith("#"):
        text = text[1:]
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) == 6 and all(ch in "0123456789abcdefABCDEF" for ch in text):
        return "#" + text.upper()
    return default


def _as_hhmm(value: Any, default: str) -> str:
    text = _as_str(value).strip().replace("：", ":")
    parts = text.split(":")
    if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
        hour, minute = int(parts[0]), int(parts[1])
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return "{0:02d}:{1:02d}".format(hour, minute)
    return default


def _as_norm_rect(value: Any) -> list[float]:
    """A rectangle relative to a monitor work area: ``[x, y, w, h]`` in 0..1."""

    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return []
    result: list[float] = []
    for number in value:
        parsed = _as_float(number, float("nan"))
        if parsed != parsed:  # NaN
            return []
        result.append(round(_clamp(parsed, -1.0, 2.0), 5))
    if result[2] <= 0 or result[3] <= 0:
        return []
    return result


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


ISLAND_KINDS = ("files", "web", "widget")
# 1.x stored local HTML animations as their own kind; 2.0 folds them into "web".
LEGACY_KINDS = {"html": "web"}
WIDGET_TYPES = ("clock", "weather", "media", "todo")
# live = sample the (possibly animated) wallpaper continuously, static = wallpaper
# file, image = custom picture, solid = neutral backdrop.
WALLPAPER_MODES = ("live", "static", "image", "solid")
CLOCK_STYLES = ("digital", "analog", "split")
MATERIALS = ("clear", "frosted", "liquid")
BACKDROP_SOURCES = ("wallpaper", "image", "black", "white", "daynight")
SORT_MODES = ("manual", "name", "type", "modified")
AUTO_SORTS = ("name", "type", "modified")
# Bounds of the remembered file-view orders.
PORTAL_ORDER_FOLDERS = 64
PORTAL_ORDER_NAMES = 2000
THEME_MODES = ("auto_time", "wallpaper", "system", "light", "dark")
TEXT_COLOR_MODES = ("auto", "light", "dark", "custom")
# Default colours of DeskIsle's own windows (settings, dialogs, menus).
DAY_BG = "#ABB2A9"
DAY_SURFACE = "#FFFFFF"
NIGHT_BG = "#758BBB"
NIGHT_SURFACE = "#000000"


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
    # 1.3: automatic order restored by “重新自动排列” after a manual drag.
    auto_sort: str = "name"
    # 1.3: manual order of file-view folders (folder -> child names).  It is
    # only remembered by DeskIsle; the real folder is never touched.
    portal_order: dict[str, list[str]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    _KNOWN = ("id", "title", "portal_path", "items", "sort_mode", "sort_descending", "auto_sort", "portal_order")

    def to_dict(self) -> dict[str, Any]:
        return _with_extras(self.extra, {
            "id": self.id,
            "title": self.title,
            "portal_path": self.portal_path,
            "items": [item.to_dict() for item in self.items],
            "sort_mode": self.sort_mode,
            "sort_descending": self.sort_descending,
            "auto_sort": self.auto_sort,
            "portal_order": {folder: list(names) for folder, names in self.portal_order.items()},
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
            sort_mode=_choice(raw.get("sort_mode"), SORT_MODES, "name"),
            sort_descending=_as_bool(raw.get("sort_descending"), False),
            auto_sort=_choice(raw.get("auto_sort"), AUTO_SORTS, "name"),
            portal_order=_portal_order(raw.get("portal_order")),
            extra=_extras(raw, cls._KNOWN),
        )


def _portal_order(value: Any) -> dict[str, list[str]]:
    order: dict[str, list[str]] = {}
    if not isinstance(value, Mapping):
        return order
    for folder, names in value.items():
        if len(order) >= PORTAL_ORDER_FOLDERS:
            break
        if not isinstance(folder, str) or not folder:
            continue
        cleaned = [name for name in _as_list(names) if isinstance(name, str) and name][:PORTAL_ORDER_NAMES]
        if cleaned:
            order[folder] = cleaned
    return order


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
    # kind == "widget": built-in widget type (clock/weather/media/todo) or
    # "custom:<folder>" for widgets from the custom folder.
    widget: str = ""
    widget_config: dict[str, Any] = field(default_factory=dict)
    # Capsule mode: shrink to a pill and peek open on hover.
    capsule: bool = False
    # Size the user asked for.  Automatic layout may shrink an island to make
    # room for a neighbour; it grows back towards this size when space frees
    # up.  ``0`` means "same as width/height".
    pref_width: int = 0
    pref_height: int = 0
    # Position relative to the monitor work area ([x, y, w, h], 0..1).  Used to
    # map a layout when a monitor changes resolution or is shown elsewhere.
    norm: list[float] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    _KNOWN = (
        "id", "title", "x", "y", "width", "height", "color", "collapsed", "locked",
        "icon_size", "active_tab_id", "tabs", "exclude_from_hide", "kind", "html_path",
        "html_allow_network", "web_url", "web_toolbar", "web_zoom", "web_refresh_minutes",
        "pin_on_top", "material", "media_path", "media_opacity", "media_feather",
        "pref_width", "pref_height", "norm", "widget", "widget_config", "capsule",
    )

    def __post_init__(self) -> None:
        if self.tabs and not self.active_tab_id:
            self.active_tab_id = self.tabs[0].id

    @property
    def is_web_content(self) -> bool:
        return self.kind == "web"

    @property
    def is_widget(self) -> bool:
        return self.kind == "widget"

    @property
    def preferred_size(self) -> tuple[int, int]:
        return (self.pref_width or self.width, self.pref_height or self.height)

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
            "pref_width": self.pref_width,
            "pref_height": self.pref_height,
            "norm": list(self.norm),
            "widget": self.widget,
            "widget_config": copy.deepcopy(self.widget_config),
            "capsule": self.capsule,
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
        raw_kind = _as_str(raw.get("kind")).strip().casefold()
        kind = _choice(LEGACY_KINDS.get(raw_kind, raw_kind), ISLAND_KINDS, "files")
        html_path = _as_str(raw.get("html_path"))
        web_url = _as_str(raw.get("web_url")).strip()
        if raw_kind == "html" and html_path and not web_url:
            # 2.0: a local HTML animation is simply a web island showing a file URL.
            web_url = _file_url(html_path)
        widget = _as_str(raw.get("widget")).strip()
        if kind == "widget" and not widget:
            widget = "clock"
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
            kind=kind,
            html_path=html_path,
            html_allow_network=_as_bool(raw.get("html_allow_network"), raw_kind != "html"),
            web_url=web_url,
            web_toolbar=_as_bool(raw.get("web_toolbar"), True),
            web_zoom=_clamp(_as_float(raw.get("web_zoom"), 1.0), 0.25, 5.0),
            web_refresh_minutes=int(_clamp(_as_int(raw.get("web_refresh_minutes"), 0), 0, 1440)),
            pin_on_top=_as_bool(raw.get("pin_on_top"), False),
            material=material if material in MATERIALS else "",
            media_path=_as_str(raw.get("media_path")),
            media_opacity=_clamp(_as_float(raw.get("media_opacity"), 0.9), 0.1, 1.0),
            media_feather=int(_clamp(_as_int(raw.get("media_feather"), 26), 0, 120)),
            pref_width=max(0, _as_int(raw.get("pref_width"), 0)),
            pref_height=max(0, _as_int(raw.get("pref_height"), 0)),
            norm=_as_norm_rect(raw.get("norm")),
            widget=widget if kind == "widget" else "",
            widget_config=copy.deepcopy(dict(_mapping(raw.get("widget_config")))),
            capsule=_as_bool(raw.get("capsule"), False),
            extra=_extras(raw, cls._KNOWN),
        )


def _file_url(path: str) -> str:
    try:
        from pathlib import Path

        return Path(path).resolve().as_uri()
    except (OSError, ValueError):
        return ""


@dataclass
class PageState:
    """A layout preset.  Since 1.3 every preset belongs to one monitor."""

    id: str = field(default_factory=_new_id)
    title: str = "主页"
    islands: list[IslandState] = field(default_factory=list)
    # Stable key of the monitor this preset belongs to ("" = not assigned yet,
    # i.e. a layout written by DeskIsle 1.2 or older).
    monitor_key: str = ""
    # Human readable name of that monitor ("显示器 2"), remembered so presets
    # of a disconnected monitor can still be labelled.
    monitor_label: str = ""
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    _KNOWN = ("id", "title", "islands", "monitor_key", "monitor_label")

    def to_dict(self) -> dict[str, Any]:
        return _with_extras(self.extra, {
            "id": self.id,
            "title": self.title,
            "islands": [island.to_dict() for island in self.islands],
            "monitor_key": self.monitor_key,
            "monitor_label": self.monitor_label,
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
            monitor_key=_as_str(raw.get("monitor_key")).strip(),
            monitor_label=_as_str(raw.get("monitor_label")).strip(),
            extra=_extras(raw, cls._KNOWN),
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
    onboarding_done: bool = False
    # Appearance
    island_material: str = "frosted"
    # wallpaper | image | black | white | daynight (black at night, white by day)
    backdrop_source: str = "wallpaper"
    backdrop_image: str = ""
    # Opacity of the solid black/white/day-night island background.
    solid_opacity: float = 0.88
    # Width (px) of the soft fade along island edges; 0 = crisp edge.
    edge_fade: int = 14
    font_family: str = ""
    font_file: str = ""
    font_size: float = 10.0
    # 2.0.1: text colour of every DeskIsle surface: auto (follows the theme) | light | dark | custom.
    text_color_mode: str = "auto"
    text_color: str = "#FFFFFF"
    # Theme of DeskIsle's own windows (settings, menus, dialogs).
    theme_mode: str = "auto_time"
    day_start: str = "07:00"
    night_start: str = "19:00"
    day_bg: str = DAY_BG
    day_surface: str = DAY_SURFACE
    night_bg: str = NIGHT_BG
    night_surface: str = NIGHT_SURFACE
    # Layout
    layout_gap: int = 12
    first_arrange_done: bool = False
    # Dynamic bar
    bar_hover_zoom: bool = True
    # Motion and performance
    reduce_motion: bool = False
    smart_pause: bool = True
    media_fps: int = 24
    # 2.0.1: hand idle memory back to Windows (working-set trim after startup / settings close).
    idle_trim: bool = True
    # Updates (only the switch lives here; bookkeeping is kept in update.json)
    auto_check_updates: bool = True
    # --- 2.0 -------------------------------------------------------------
    # Wallpaper sampling for the glass (accent colour always comes from it).
    wallpaper_mode: str = "live"
    wallpaper_image: str = ""
    live_fps: int = 12
    glass_strength: float = 1.0
    # A: remember one layout per monitor combination and restore on replug.
    layout_memory: bool = True
    replug_grace_s: int = 6
    # B: capsule islands open after hovering this long.
    capsule_peek_ms: int = 260
    # C: wake / watchdog.
    wake_double_click: bool = True
    hotkeys_enabled: bool = True
    watchdog: bool = True
    # D: Everything powered search in the bar.
    everything_search: bool = True
    # Widgets.
    clock_24h: bool = True
    clock_seconds: bool = False
    clock_lunar: bool = True
    clock_style: str = "digital"
    weather_auto_location: bool = True
    weather_city: str = ""
    weather_lat: float = 0.0
    weather_lon: float = 0.0
    weather_fahrenheit: bool = False
    # Agent interfaces (local named pipe / MCP / CLI).
    agent_enabled: bool = True
    custom_folder: str = ""
    # Web islands: "auto" (windowed, composition only where it can sit below the glass),
    # "composition" (experimental, always DirectComposition), "windowed".
    web_hosting: str = "auto"
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    _KNOWN = (
        "hide_native_icons", "snap_to_grid", "grid_size", "auto_organize",
        "start_with_windows", "panel_opacity", "onboarding_done",
        "island_material", "backdrop_source", "backdrop_image", "solid_opacity", "edge_fade",
        "font_family", "font_file", "font_size", "text_color_mode", "text_color",
        "theme_mode", "day_start", "night_start",
        "day_bg", "day_surface", "night_bg", "night_surface", "layout_gap",
        "first_arrange_done", "bar_hover_zoom",
        "reduce_motion", "smart_pause", "media_fps", "idle_trim", "auto_check_updates",
        "wallpaper_mode", "wallpaper_image", "live_fps", "glass_strength", "layout_memory",
        "replug_grace_s", "capsule_peek_ms", "wake_double_click", "hotkeys_enabled", "watchdog",
        "everything_search", "clock_24h", "clock_seconds", "clock_lunar", "clock_style",
        "weather_auto_location", "weather_city", "weather_lat", "weather_lon",
        "weather_fahrenheit", "agent_enabled", "custom_folder", "web_hosting",
    )
    # 1.x settings that 2.0 replaced: read once for the migration and still written back
    # (unused) so that downgrading to 1.x keeps the old look.
    _RETIRED = ("panel_opacity", "backdrop_source", "backdrop_image", "solid_opacity",
                "edge_fade", "day_bg", "day_surface", "night_bg", "night_surface")

    def to_dict(self) -> dict[str, Any]:
        return _with_extras(self.extra, {
            "hide_native_icons": self.hide_native_icons,
            "snap_to_grid": self.snap_to_grid,
            "grid_size": self.grid_size,
            "auto_organize": self.auto_organize,
            "start_with_windows": self.start_with_windows,
            "panel_opacity": self.panel_opacity,
            "onboarding_done": self.onboarding_done,
            "island_material": self.island_material,
            "backdrop_source": self.backdrop_source,
            "backdrop_image": self.backdrop_image,
            "solid_opacity": self.solid_opacity,
            "edge_fade": self.edge_fade,
            "font_family": self.font_family,
            "font_file": self.font_file,
            "font_size": self.font_size,
            "text_color_mode": self.text_color_mode,
            "text_color": self.text_color,
            "theme_mode": self.theme_mode,
            "day_start": self.day_start,
            "night_start": self.night_start,
            "day_bg": self.day_bg,
            "day_surface": self.day_surface,
            "night_bg": self.night_bg,
            "night_surface": self.night_surface,
            "layout_gap": self.layout_gap,
            "first_arrange_done": self.first_arrange_done,
            "bar_hover_zoom": self.bar_hover_zoom,
            "reduce_motion": self.reduce_motion,
            "smart_pause": self.smart_pause,
            "media_fps": self.media_fps,
            "idle_trim": self.idle_trim,
            "auto_check_updates": self.auto_check_updates,
            "wallpaper_mode": self.wallpaper_mode,
            "wallpaper_image": self.wallpaper_image,
            "live_fps": self.live_fps,
            "glass_strength": self.glass_strength,
            "layout_memory": self.layout_memory,
            "replug_grace_s": self.replug_grace_s,
            "capsule_peek_ms": self.capsule_peek_ms,
            "wake_double_click": self.wake_double_click,
            "hotkeys_enabled": self.hotkeys_enabled,
            "watchdog": self.watchdog,
            "everything_search": self.everything_search,
            "clock_24h": self.clock_24h,
            "clock_seconds": self.clock_seconds,
            "clock_lunar": self.clock_lunar,
            "clock_style": self.clock_style,
            "weather_auto_location": self.weather_auto_location,
            "weather_city": self.weather_city,
            "weather_lat": self.weather_lat,
            "weather_lon": self.weather_lon,
            "weather_fahrenheit": self.weather_fahrenheit,
            "agent_enabled": self.agent_enabled,
            "custom_folder": self.custom_folder,
            "web_hosting": self.web_hosting,
        })

    @classmethod
    def from_dict(cls, data: Any) -> "Preferences":
        if isinstance(data, cls):
            data = data.to_dict()
        raw = _mapping(data)
        opacity = min(1.0, max(0.0, _as_float(raw.get("panel_opacity"), 0.88)))
        # 1.x backdrop choice -> 2.0 wallpaper mode (dynamic sampling by default).
        legacy_source = _as_str(raw.get("backdrop_source")).strip().casefold()
        legacy_mode = {"image": "image", "black": "solid", "white": "solid",
                       "daynight": "solid"}.get(legacy_source, "live")
        legacy_image = _as_str(raw.get("backdrop_image")) if legacy_source == "image" else ""
        return cls(
            hide_native_icons=_as_bool(raw.get("hide_native_icons"), True),
            snap_to_grid=_as_bool(raw.get("snap_to_grid"), True),
            grid_size=max(1, _as_int(raw.get("grid_size"), 8)),
            auto_organize=_as_bool(raw.get("auto_organize"), True),
            start_with_windows=_as_bool(raw.get("start_with_windows"), False),
            panel_opacity=opacity,
            onboarding_done=_as_bool(raw.get("onboarding_done"), False),
            island_material=_choice(raw.get("island_material"), MATERIALS, "frosted"),
            backdrop_source=_choice(raw.get("backdrop_source"), BACKDROP_SOURCES, "wallpaper"),
            backdrop_image=_as_str(raw.get("backdrop_image")),
            solid_opacity=_clamp(_as_float(raw.get("solid_opacity"), 0.88), 0.2, 1.0),
            edge_fade=int(_clamp(_as_int(raw.get("edge_fade"), 14), 0, 24)),
            font_family=_as_str(raw.get("font_family")).strip(),
            font_file=_as_str(raw.get("font_file")).strip(),
            font_size=_clamp(_as_float(raw.get("font_size"), 10.0), 7.0, 20.0),
            text_color_mode=_choice(raw.get("text_color_mode"), TEXT_COLOR_MODES, "auto"),
            text_color=_as_color(raw.get("text_color"), "#FFFFFF"),
            theme_mode=_choice(raw.get("theme_mode"), THEME_MODES, "auto_time"),
            day_start=_as_hhmm(raw.get("day_start"), "07:00"),
            night_start=_as_hhmm(raw.get("night_start"), "19:00"),
            day_bg=_as_color(raw.get("day_bg"), DAY_BG),
            day_surface=_as_color(raw.get("day_surface"), DAY_SURFACE),
            night_bg=_as_color(raw.get("night_bg"), NIGHT_BG),
            night_surface=_as_color(raw.get("night_surface"), NIGHT_SURFACE),
            layout_gap=int(_clamp(_as_int(raw.get("layout_gap"), 12), 4, 48)),
            first_arrange_done=_as_bool(raw.get("first_arrange_done"), False),
            bar_hover_zoom=_as_bool(raw.get("bar_hover_zoom"), True),
            reduce_motion=_as_bool(raw.get("reduce_motion"), False),
            smart_pause=_as_bool(raw.get("smart_pause"), True),
            media_fps=int(_clamp(_as_int(raw.get("media_fps"), 24), 5, 60)),
            idle_trim=_as_bool(raw.get("idle_trim"), True),
            auto_check_updates=_as_bool(raw.get("auto_check_updates"), True),
            wallpaper_mode=_choice(raw.get("wallpaper_mode"), WALLPAPER_MODES, legacy_mode),
            wallpaper_image=_as_str(raw.get("wallpaper_image") or legacy_image).strip(),
            live_fps=int(_clamp(_as_int(raw.get("live_fps"), 12), 1, 30)),
            glass_strength=_clamp(_as_float(raw.get("glass_strength"), 1.0), 0.3, 1.6),
            layout_memory=_as_bool(raw.get("layout_memory"), True),
            replug_grace_s=int(_clamp(_as_int(raw.get("replug_grace_s"), 6), 0, 60)),
            capsule_peek_ms=int(_clamp(_as_int(raw.get("capsule_peek_ms"), 260), 0, 2000)),
            wake_double_click=_as_bool(raw.get("wake_double_click"), True),
            hotkeys_enabled=_as_bool(raw.get("hotkeys_enabled"), True),
            watchdog=_as_bool(raw.get("watchdog"), True),
            everything_search=_as_bool(raw.get("everything_search"), True),
            clock_24h=_as_bool(raw.get("clock_24h"), True),
            clock_seconds=_as_bool(raw.get("clock_seconds"), False),
            clock_lunar=_as_bool(raw.get("clock_lunar"), True),
            clock_style=_choice(raw.get("clock_style"), CLOCK_STYLES, "digital"),
            weather_auto_location=_as_bool(raw.get("weather_auto_location"), True),
            weather_city=_as_str(raw.get("weather_city")).strip(),
            weather_lat=_clamp(_as_float(raw.get("weather_lat"), 0.0), -90.0, 90.0),
            weather_lon=_clamp(_as_float(raw.get("weather_lon"), 0.0), -180.0, 180.0),
            weather_fahrenheit=_as_bool(raw.get("weather_fahrenheit"), False),
            agent_enabled=_as_bool(raw.get("agent_enabled"), True),
            custom_folder=_as_str(raw.get("custom_folder")).strip(),
            web_hosting=_choice(raw.get("web_hosting"), ("auto", "composition", "windowed"), "auto"),
            extra=_extras(raw, cls._KNOWN + cls._RETIRED),
        )


# 1 = <= 1.2, 2 = presets per monitor (1.3), 3 = 2.0 (web/widget kinds, new prefs).
STATE_VERSION = 3


@dataclass
class AppState:
    # 1 = DeskIsle <= 1.2 (one shared page list); 2 = presets per monitor.
    version: int = 1
    # Preset shown on the primary monitor (kept for older versions).
    current_page_id: str = ""
    pages: list[PageState] = field(default_factory=list)
    loose_items: list[ItemRef] = field(default_factory=list)
    rules: list[Rule] = field(default_factory=list)
    preferences: Preferences = field(default_factory=Preferences)
    # monitor key -> id of the preset currently shown on that monitor.
    current_pages: dict[str, str] = field(default_factory=dict)
    # 2.0 (A): layout memory per monitor combination.  combination signature ->
    # {"current_pages": {...}, "islands": {id: [x, y, w, h, collapsed]}, "saved": epoch}
    combos: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    _KNOWN = ("version", "current_page_id", "pages", "loose_items", "rules", "preferences",
              "current_pages", "combos")

    def __post_init__(self) -> None:
        if self.pages and not self.current_page_id:
            self.current_page_id = self.pages[0].id

    def page(self, page_id: str) -> PageState | None:
        return next((page for page in self.pages if page.id == page_id), None)

    def to_dict(self) -> dict[str, Any]:
        return _with_extras(self.extra, {
            "version": self.version,
            "current_page_id": self.current_page_id,
            "pages": [page.to_dict() for page in self.pages],
            "loose_items": [item.to_dict() for item in self.loose_items],
            "rules": [rule.to_dict() for rule in self.rules],
            "preferences": self.preferences.to_dict(),
            "current_pages": dict(self.current_pages),
            "combos": copy.deepcopy(self.combos),
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
        current_pages: dict[str, str] = {}
        for key, value in _mapping(raw.get("current_pages")).items():
            page_id = _as_str(value)
            if isinstance(key, str) and key and page_id in page_ids:
                current_pages[key] = page_id
        return cls(
            version=max(1, _as_int(raw.get("version"), 1)),
            current_page_id=current_page_id,
            pages=pages,
            loose_items=loose_items,
            rules=rules,
            preferences=Preferences.from_dict(raw.get("preferences")),
            current_pages=current_pages,
            combos={str(k): copy.deepcopy(v) for k, v in _mapping(raw.get("combos")).items()
                    if isinstance(v, Mapping)},
            extra=_extras(raw, cls._KNOWN),
        )


__all__ = [
    "AUTO_SORTS",
    "BACKDROP_SOURCES",
    "CLOCK_STYLES",
    "ISLAND_KINDS",
    "LEGACY_KINDS",
    "WALLPAPER_MODES",
    "WIDGET_TYPES",
    "MATERIALS",
    "STATE_VERSION",
    "THEME_MODES",
    "AppState",
    "IslandState",
    "ItemRef",
    "PageState",
    "Preferences",
    "Rule",
    "SORT_MODES",
    "TabState",
]

"""Qt Quick facing view-models.

The controller owns the :class:`~deskisle.models.AppState`; these objects only
*present* it to QML:

* :class:`ObjectListModel` - list of QObjects (role ``object``).
* :class:`ItemsModel` - icons of one tab / folder / the loose desktop area,
  with diff based updates so GridView can animate add/move/remove and
  placeholder rows for the "make way" drop preview.
* :class:`IslandProxy` - one displayed island.  Geometry is window local.
* :class:`MonitorScene` - everything one layer window shows.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import quote

from PySide6.QtCore import (
    Property,
    QAbstractListModel,
    QByteArray,
    QModelIndex,
    QObject,
    Qt,
    Signal,
    Slot,
)

from .. import layout
from ..layout import Rect


def norm_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(path)) if path else ""


def icon_url(path: str, size: int = 48) -> str:
    return "image://icon/{0}?s={1}".format(quote(path, safe=""), int(size))


# --------------------------------------------------------------------------------------
class ObjectListModel(QAbstractListModel):
    ObjectRole = Qt.ItemDataRole.UserRole + 1
    countChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._items: list[QObject] = []

    def roleNames(self):  # noqa: N802 - Qt API
        return {self.ObjectRole: QByteArray(b"object")}

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        if role == self.ObjectRole:
            return self._items[index.row()]
        return None

    def items(self) -> list[QObject]:
        return list(self._items)

    def __iter__(self):
        return iter(list(self._items))

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, obj) -> bool:
        return obj in self._items

    def append(self, obj: QObject) -> None:
        if obj in self._items:
            return
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append(obj)
        self.endInsertRows()
        self.countChanged.emit()

    def remove(self, obj: QObject) -> None:
        if obj not in self._items:
            return
        row = self._items.index(obj)
        self.beginRemoveRows(QModelIndex(), row, row)
        self._items.pop(row)
        self.endRemoveRows()
        self.countChanged.emit()

    def reset(self, objects) -> None:
        self.beginResetModel()
        self._items = list(objects)
        self.endResetModel()
        self.countChanged.emit()

    @Slot(int, result=QObject)
    def at(self, row: int):
        return self._items[row] if 0 <= row < len(self._items) else None

    count = Property(int, lambda self: len(self._items), notify=countChanged)


# --------------------------------------------------------------------------------------
@dataclass
class ItemRecord:
    path: str
    name: str
    is_dir: bool = False
    available: bool = True
    pinned: bool = False
    ext: str = ""
    placeholder: bool = False
    x: float = 0.0
    y: float = 0.0
    match: bool = True

    @property
    def key(self) -> str:
        return self.path if self.placeholder else norm_key(self.path)


class ItemsModel(QAbstractListModel):
    """Icons of one container ("island:tab", "loose", "search" ...)."""

    Roles = ("path", "name", "icon", "isDir", "available", "pinned", "selected", "ext",
             "placeholder", "itemKey", "px", "py", "match")
    countChanged = Signal()
    selectionChanged = Signal()
    iconSizeChanged = Signal()
    DPR = 1.0   # largest screen scale (set by the app) - icons are fetched at physical size

    def __init__(self, container: str = "", parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.container = container
        self._rows: list[ItemRecord] = []
        self._selected: set[str] = set()
        self._icon_size = 48
        self._gap = (-1, 0)
        self._roles = {Qt.ItemDataRole.UserRole + 1 + i: QByteArray(name.encode()) for i, name in
                       enumerate(self.Roles)}
        self._role_index = {name: Qt.ItemDataRole.UserRole + 1 + i for i, name in enumerate(self.Roles)}
        self._role_name = {role: name for name, role in self._role_index.items()}

    # Qt API ------------------------------------------------------------------------
    def roleNames(self):  # noqa: N802
        return self._roles

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        name = self._role_name.get(role)
        if name is None:
            return row.name if role == Qt.ItemDataRole.DisplayRole else None
        if name == "path":
            return "" if row.placeholder else row.path
        if name == "name":
            return row.name
        if name == "icon":
            return "" if row.placeholder else icon_url(row.path, self._icon_px())
        if name == "isDir":
            return row.is_dir
        if name == "available":
            return row.available
        if name == "pinned":
            return row.pinned
        if name == "selected":
            return row.key in self._selected
        if name == "ext":
            return row.ext
        if name == "placeholder":
            return row.placeholder
        if name == "itemKey":
            return row.key
        if name == "px":
            return row.x
        if name == "py":
            return row.y
        if name == "match":
            return row.match
        return None

    def _icon_px(self) -> int:
        # Request icons in steps so zooming does not refetch every pixel size.
        size = self._icon_size * ItemsModel.DPR
        for step in (32, 48, 64, 96, 128, 256):
            if size <= step:
                return step
        return 256

    # Records -----------------------------------------------------------------------
    def records(self) -> list[ItemRecord]:
        return [row for row in self._rows if not row.placeholder]

    def paths(self) -> list[str]:
        return [row.path for row in self._rows if not row.placeholder]

    def set_icon_size(self, size: int) -> None:
        size = int(size)
        if size == self._icon_size:
            return
        old = self._icon_px()
        self._icon_size = size
        self.iconSizeChanged.emit()
        if old != self._icon_px() and self._rows:
            self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1),
                                  [self._role_index["icon"]])

    def set_records(self, records: list[ItemRecord]) -> None:
        """Diff ``records`` into the model (keeps delegates alive for animation)."""
        self._clear_gap()
        new = list(records)
        new_keys = [record.key for record in new]
        if len(set(new_keys)) != len(new_keys):
            seen: set[str] = set()
            unique = []
            for record in new:
                if record.key not in seen:
                    seen.add(record.key)
                    unique.append(record)
            new, new_keys = unique, [record.key for record in unique]
        wanted = set(new_keys)
        if not self._rows or len(new) > 400 and abs(len(new) - len(self._rows)) > 200:
            self.beginResetModel()
            self._rows = new
            self.endResetModel()
            self._prune_selection()
            self.countChanged.emit()
            return
        # 1. removals
        for row in range(len(self._rows) - 1, -1, -1):
            if self._rows[row].key not in wanted:
                self.beginRemoveRows(QModelIndex(), row, row)
                self._rows.pop(row)
                self.endRemoveRows()
        # 2. moves / inserts
        for target, record in enumerate(new):
            current = self._rows[target].key if target < len(self._rows) else None
            if current == record.key:
                old = self._rows[target]
                self._rows[target] = record
                if old != record:
                    index = self.index(target)
                    self.dataChanged.emit(index, index)
                continue
            source = next((i for i in range(target + 1, len(self._rows)) if self._rows[i].key == record.key), -1)
            if source >= 0:
                self.beginMoveRows(QModelIndex(), source, source, QModelIndex(), target)
                self._rows.insert(target, self._rows.pop(source))
                self.endMoveRows()
                old = self._rows[target]
                self._rows[target] = record
                if old != record:
                    index = self.index(target)
                    self.dataChanged.emit(index, index)
            else:
                self.beginInsertRows(QModelIndex(), target, target)
                self._rows.insert(target, record)
                self.endInsertRows()
        if len(self._rows) > len(new):
            self.beginRemoveRows(QModelIndex(), len(new), len(self._rows) - 1)
            del self._rows[len(new):]
            self.endRemoveRows()
        self._prune_selection()
        self.countChanged.emit()

    def set_positions(self, positions: dict[str, tuple[float, float]]) -> None:
        roles = [self._role_index["px"], self._role_index["py"]]
        for row, record in enumerate(self._rows):
            pos = positions.get(record.key)
            if pos is None or (record.x, record.y) == pos:
                continue
            record.x, record.y = pos
            index = self.index(row)
            self.dataChanged.emit(index, index, roles)

    def set_matches(self, predicate) -> None:
        role = [self._role_index["match"]]
        for row, record in enumerate(self._rows):
            match = bool(predicate(record)) if predicate is not None else True
            if match != record.match:
                record.match = match
                index = self.index(row)
                self.dataChanged.emit(index, index, role)

    # Drop gap ------------------------------------------------------------------------
    def _clear_gap(self) -> None:
        rows = [i for i, row in enumerate(self._rows) if row.placeholder]
        for row in reversed(rows):
            self.beginRemoveRows(QModelIndex(), row, row)
            self._rows.pop(row)
            self.endRemoveRows()
        self._gap = (-1, 0)

    @Slot(int, int)
    def setGap(self, index: int, count: int) -> None:  # noqa: N802 - QML API
        count = max(0, min(int(count), 64))
        index = int(index)
        if (index, count) == self._gap:
            return
        self._clear_gap()
        if index < 0 or count <= 0:
            return
        index = max(0, min(index, len(self._rows)))
        self.beginInsertRows(QModelIndex(), index, index + count - 1)
        for i in range(count):
            self._rows.insert(index + i, ItemRecord(path="__gap__{0}".format(i), name="", placeholder=True))
        self.endInsertRows()
        self._gap = (index, count)

    @Slot()
    def clearGap(self) -> None:  # noqa: N802
        self._clear_gap()

    @Slot(result=int)
    def gapIndex(self) -> int:  # noqa: N802
        return self._gap[0]

    @Slot(int, result=int)
    def realIndex(self, row: int) -> int:  # noqa: N802
        """Model row (may include placeholders) -> index among real items."""
        return sum(1 for record in self._rows[:max(0, row)] if not record.placeholder)

    # Selection -----------------------------------------------------------------------
    def _prune_selection(self) -> None:
        keys = {row.key for row in self._rows}
        if self._selected - keys:
            self._selected &= keys
            self.selectionChanged.emit()

    def _emit_selected(self) -> None:
        if self._rows:
            self.dataChanged.emit(self.index(0), self.index(len(self._rows) - 1),
                                  [self._role_index["selected"]])
        self.selectionChanged.emit()

    @Slot(int, bool, bool)
    def select(self, row: int, toggle: bool = False, extend: bool = False) -> None:
        if not 0 <= row < len(self._rows) or self._rows[row].placeholder:
            return
        key = self._rows[row].key
        if extend and self._selected:
            anchor = next((i for i, r in enumerate(self._rows) if r.key in self._selected), row)
            low, high = sorted((anchor, row))
            self._selected = {r.key for r in self._rows[low:high + 1] if not r.placeholder}
        elif toggle:
            self._selected ^= {key}
        else:
            self._selected = {key}
        self._emit_selected()

    @Slot(int, result=bool)
    def isSelected(self, row: int) -> bool:  # noqa: N802
        return 0 <= row < len(self._rows) and self._rows[row].key in self._selected

    @Slot("QVariantList")
    def selectRows(self, rows) -> None:  # noqa: N802
        self._selected = {self._rows[int(r)].key for r in rows
                          if 0 <= int(r) < len(self._rows) and not self._rows[int(r)].placeholder}
        self._emit_selected()

    @Slot()
    def clearSelection(self) -> None:  # noqa: N802
        if self._selected:
            self._selected.clear()
            self._emit_selected()

    @Slot(result="QStringList")
    def selectedPaths(self) -> list[str]:  # noqa: N802
        return [row.path for row in self._rows if row.key in self._selected and not row.placeholder]

    @Slot(int, result="QStringList")
    def dragPaths(self, row: int) -> list[str]:  # noqa: N802
        """Paths a drag starting on ``row`` carries (selection if row is in it)."""
        if not 0 <= row < len(self._rows):
            return []
        if self._rows[row].key not in self._selected:
            self._selected = {self._rows[row].key}
            self._emit_selected()
        return self.selectedPaths()

    @Slot(int, result=str)
    def pathAt(self, row: int) -> str:  # noqa: N802
        return self._rows[row].path if 0 <= row < len(self._rows) and not self._rows[row].placeholder else ""

    @Slot(str, result=int)
    def rowOf(self, path: str) -> int:  # noqa: N802
        key = norm_key(path)
        return next((i for i, row in enumerate(self._rows) if row.key == key), -1)

    count = Property(int, lambda self: len(self.records()), notify=countChanged)
    iconSize = Property(int, lambda self: self._icon_size, notify=iconSizeChanged)
    selectedCount = Property(int, lambda self: len(self._selected), notify=selectionChanged)


# --------------------------------------------------------------------------------------
class IslandProxy(QObject):
    """One island as QML sees it.  ``state`` is the IslandState (source of truth)."""

    changed = Signal()
    geometryChanged = Signal()
    hintChanged = Signal()
    webChanged = Signal()
    flash = Signal(str)

    def __init__(self, state, scene: "MonitorScene", controller, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.state = state
        self.scene = scene
        self.controller = controller
        self.items = ItemsModel("island:" + state.id, self)
        self._rect = Rect(0, 0, 0, 0)  # board coords
        self._motion = ""
        self._hint = ""
        self._z = 0
        self._portal = ""
        self._portal_missing = False
        self._web = {"title": "", "url": "", "loading": False, "canBack": False, "canForward": False,
                     "status": "", "zoom": 1.0}
        self._peek = False
        self.sync_rect(animate=False)

    # Arranger proxy interface ---------------------------------------------------------
    @property
    def monitor_key(self) -> str:
        return self.scene.key if self.scene is not None else ""

    def animate_to(self, rect: Rect, mode: str = "slide") -> None:
        self._set_rect(rect, "fade" if mode == "fade" else "slide")

    def set_geometry(self, rect: Rect, live: bool = False) -> None:
        self._set_rect(rect, "live" if live else "")

    def set_hint(self, hint: str) -> None:
        if hint != self._hint:
            self._hint = hint
            self.hintChanged.emit()

    def raise_(self) -> None:
        if self.scene is not None:
            self._z = self.scene.next_z()
            self.changed.emit()

    def refresh(self) -> None:
        self.sync_rect(animate=True)
        self.changed.emit()

    # Helpers ---------------------------------------------------------------------------
    def sync_rect(self, animate: bool = True) -> None:
        state = self.state
        height = layout.COLLAPSED_H if state.collapsed else int(state.height)
        self._set_rect(Rect(int(state.x), int(state.y), int(state.width), height), "slide" if animate else "")

    def _set_rect(self, rect: Rect, motion: str) -> None:
        rect = Rect(int(rect.x), int(rect.y), max(1, int(rect.w)), max(1, int(rect.h)))
        if rect == self._rect and motion == self._motion:
            return
        self._rect = rect
        self._motion = motion
        self.geometryChanged.emit()

    def board_rect(self) -> Rect:
        return self._rect

    def set_scene(self, scene: "MonitorScene") -> None:
        self.scene = scene
        self.geometryChanged.emit()

    def notify(self) -> None:
        self.changed.emit()

    def set_portal(self, path: str) -> None:
        if path != self._portal:
            self._portal = path
            self.changed.emit()

    def set_portal_missing(self, value: bool) -> None:
        if bool(value) != self._portal_missing:
            self._portal_missing = bool(value)
            self.changed.emit()

    def update_web(self, **values) -> None:
        changed = False
        for key, value in values.items():
            if self._web.get(key) != value:
                self._web[key] = value
                changed = True
        if changed:
            self.webChanged.emit()

    def set_peek(self, value: bool) -> None:
        if value != self._peek:
            self._peek = value
            self.changed.emit()

    # Local geometry ---------------------------------------------------------------------
    def _ox(self) -> int:
        return self.scene.local_x if self.scene is not None else 0

    def _oy(self) -> int:
        return self.scene.local_y if self.scene is not None else 0

    def _tabs(self) -> list:
        return [{"id": tab.id, "title": tab.title, "portal": bool(tab.portal_path),
                 "count": len(tab.items)} for tab in self.state.tabs]

    def _active_tab(self):
        state = self.state
        return next((tab for tab in state.tabs if tab.id == state.active_tab_id),
                    state.tabs[0] if state.tabs else None)

    def _portal_root(self) -> str:
        tab = self._active_tab()
        return tab.portal_path if tab is not None else ""

    def _material(self) -> str:
        prefs = self.controller.preferences
        return self.state.material or getattr(prefs, "island_material", "frosted") or "frosted"

    uid = Property(str, lambda self: self.state.id, constant=True)
    title = Property(str, lambda self: self.state.title, notify=changed)
    kind = Property(str, lambda self: self.state.kind, notify=changed)
    widget = Property(str, lambda self: self.state.widget, notify=changed)
    widgetConfig = Property("QVariantMap", lambda self: dict(self.state.widget_config), notify=changed)
    collapsed = Property(bool, lambda self: bool(self.state.collapsed), notify=changed)
    locked = Property(bool, lambda self: bool(self.state.locked), notify=changed)
    pinned = Property(bool, lambda self: bool(self.state.pin_on_top), notify=changed)
    capsule = Property(bool, lambda self: bool(self.state.capsule), notify=changed)
    peek = Property(bool, lambda self: self._peek, notify=changed)
    excludeFromHide = Property(bool, lambda self: bool(self.state.exclude_from_hide), notify=changed)
    material = Property(str, _material, notify=changed)
    iconSize = Property(int, lambda self: int(self.state.icon_size), notify=changed)
    tabs = Property("QVariantList", _tabs, notify=changed)
    activeTab = Property(str, lambda self: self.state.active_tab_id, notify=changed)
    portalRoot = Property(str, _portal_root, notify=changed)
    portalPath = Property(str, lambda self: self._portal or self._portal_root(), notify=changed)
    portalMissing = Property(bool, lambda self: self._portal_missing, notify=changed)
    portalCanUp = Property(bool, lambda self: bool(self._portal) and norm_key(self._portal) != norm_key(
        self._portal_root()), notify=changed)
    mediaPath = Property(str, lambda self: self.state.media_path, notify=changed)
    mediaOpacity = Property(float, lambda self: float(self.state.media_opacity), notify=changed)
    mediaFeather = Property(int, lambda self: int(self.state.media_feather), notify=changed)
    webUrl = Property(str, lambda self: self.state.web_url, notify=changed)
    webToolbar = Property(bool, lambda self: bool(self.state.web_toolbar), notify=changed)
    web = Property("QVariantMap", lambda self: dict(self._web), notify=webChanged)
    z = Property(int, lambda self: self._z, notify=changed)
    hint = Property(str, lambda self: self._hint, notify=hintChanged)
    itemsModel = Property(QObject, lambda self: self.items, constant=True)
    x = Property(int, lambda self: self._rect.x - self._ox(), notify=geometryChanged)
    y = Property(int, lambda self: self._rect.y - self._oy(), notify=geometryChanged)
    width = Property(int, lambda self: self._rect.w, notify=geometryChanged)
    height = Property(int, lambda self: self._rect.h, notify=geometryChanged)
    fullHeight = Property(int, lambda self: int(self.state.height), notify=geometryChanged)
    motion = Property(str, lambda self: self._motion, notify=geometryChanged)


# --------------------------------------------------------------------------------------
class MonitorScene(QObject):
    """Model of one layer window (one monitor)."""

    changed = Signal()
    ghostsChanged = Signal()
    shadowChanged = Signal()
    wallChanged = Signal()
    stateChanged = Signal()

    INSET = 2

    def __init__(self, spec, controller, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.spec = spec
        self.controller = controller
        self.islands = ObjectListModel(self)
        self.loose = ItemsModel("loose", self)
        self.loose.set_icon_size(48)
        self._ghosts: list = []
        self._shadow: dict = {"visible": False}
        self._wall = ""
        self._z = 1
        self._page_id = ""

    # Geometry ---------------------------------------------------------------------------
    @property
    def key(self) -> str:
        return self.spec.key

    @property
    def local_x(self) -> int:
        """Board x of the window's (0, 0)."""
        return int(self.spec.geometry.x) + self.INSET

    @property
    def local_y(self) -> int:
        return int(self.spec.geometry.y) + self.INSET

    def set_spec(self, spec) -> None:
        self.spec = spec
        self.changed.emit()
        for proxy in self.islands:
            proxy.geometryChanged.emit()

    def next_z(self) -> int:
        self._z += 1
        return self._z

    def window_rect(self) -> Rect:
        g = self.spec.geometry
        return Rect(g.x + self.INSET, g.y + self.INSET, max(1, g.w - 2 * self.INSET),
                    max(1, g.h - 2 * self.INSET))

    # Overlays -----------------------------------------------------------------------------
    def set_ghosts(self, ghosts: list) -> None:
        local = []
        for rect, style in ghosts:
            if rect is None:
                continue
            local.append({"x": rect.x - self.local_x, "y": rect.y - self.local_y, "w": rect.w, "h": rect.h,
                          "style": style})
        if local != self._ghosts:
            self._ghosts = local
            self.ghostsChanged.emit()

    def set_shadow(self, info: dict | None) -> None:
        info = dict(info or {"visible": False})
        if info.get("visible"):
            info["x"] = info["x"] - self.local_x
            info["y"] = info["y"] - self.local_y
        if info != self._shadow:
            self._shadow = info
            self.shadowChanged.emit()

    def set_wall_source(self, url: str) -> None:
        if url != self._wall:
            self._wall = url
            self.wallChanged.emit()

    def set_page(self, page_id: str) -> None:
        if page_id != self._page_id:
            self._page_id = page_id
            self.changed.emit()

    def _page(self):
        return self.controller.displayed_page(self.key)

    def _pages(self) -> list:
        return self.controller.pages_info(self.key)

    def _work(self) -> dict:
        work = self.spec.work
        return {"x": work.x - self.local_x, "y": work.y - self.local_y, "w": work.w, "h": work.h}

    def _area(self) -> dict:
        area = self.spec.available
        return {"x": area.x - self.local_x, "y": area.y - self.local_y, "w": area.w, "h": area.h}

    key_ = Property(str, lambda self: self.spec.key, notify=changed)
    label = Property(str, lambda self: self.spec.label, notify=changed)
    primary = Property(bool, lambda self: bool(self.spec.primary), notify=changed)
    originX = Property(int, lambda self: self.local_x, notify=changed)
    originY = Property(int, lambda self: self.local_y, notify=changed)
    inset = Property(int, lambda self: self.INSET, constant=True)
    monitorWidth = Property(int, lambda self: int(self.spec.geometry.w), notify=changed)
    monitorHeight = Property(int, lambda self: int(self.spec.geometry.h), notify=changed)
    work = Property("QVariantMap", _work, notify=changed)
    area = Property("QVariantMap", _area, notify=changed)          # monitor minus taskbar (bar band lives here)
    islandsModel = Property(QObject, lambda self: self.islands, constant=True)
    looseModel = Property(QObject, lambda self: self.loose, constant=True)
    ghosts = Property("QVariantList", lambda self: list(self._ghosts), notify=ghostsChanged)
    dragShadow = Property("QVariantMap", lambda self: dict(self._shadow), notify=shadowChanged)
    wallSource = Property(str, lambda self: self._wall, notify=wallChanged)
    pageId = Property(str, lambda self: self._page_id, notify=changed)
    pageTitle = Property(str, lambda self: (self._page().title if self._page() is not None else ""),
                         notify=changed)
    pages = Property("QVariantList", _pages, notify=changed)


__all__ = ["ItemRecord", "ItemsModel", "IslandProxy", "MonitorScene", "ObjectListModel", "icon_url", "norm_key"]

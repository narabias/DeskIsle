"""Item (icon) logic of the controller: records, sorting, portals, drag & drop,
loose desktop icons and desktop scanning.  Mixed into DeskController."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QUrl, Slot
from PySide6.QtGui import QColor, QDrag, QGuiApplication, QImage, QPainter, QPixmap

from .. import layout
from ..layout import Rect
from ..models import ItemRef, TabState
from .arrange import footprint
from .icons import display_name, provider as icon_provider
from .scene import ItemRecord, norm_key

MIME = "application/x-deskisle-items"
PORTAL_LIMIT = 1000
LOOSE = "loose"
SHORTCUT_EXT = {".lnk", ".url", ".website", ".appref-ms"}


def desktop_directories() -> list[Path]:
    candidates = [Path.home() / "Desktop"]
    public = os.environ.get("PUBLIC")
    if public:
        candidates.append(Path(public) / "Desktop")
    one_drive = os.environ.get("OneDrive")
    if one_drive:
        candidates.extend([Path(one_drive) / "Desktop", Path(one_drive) / "桌面"])
    result: list[Path] = []
    for path in candidates:
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path
        if resolved.is_dir() and resolved not in result:
            result.append(resolved)
    return result


def _is_dir(path: str) -> bool:
    try:
        return os.path.isdir(path)
    except OSError:
        return False


def _exists(path: str) -> bool:
    try:
        return os.path.exists(path)
    except OSError:
        return False


def _mtime(path: str) -> float:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return 0.0


def make_record(path: str, title: str = "", pinned: bool = False) -> ItemRecord:
    is_dir = _is_dir(path)
    return ItemRecord(path=path, name=display_name(path, title), is_dir=is_dir,
                      available=is_dir or _exists(path), pinned=pinned,
                      ext="" if is_dir else os.path.splitext(path)[1].casefold())


def sort_records(records: list[ItemRecord], mode: str, descending: bool = False) -> list[ItemRecord]:
    if mode == "manual":
        return list(records)

    def key(record: ItemRecord):
        if mode == "type":
            return (record.ext, record.name.casefold())
        if mode == "modified":
            return (_mtime(record.path), record.name.casefold())
        return (record.name.casefold(),)

    dirs = sorted((r for r in records if r.is_dir), key=key, reverse=descending)
    files = sorted((r for r in records if not r.is_dir), key=key, reverse=descending)
    return dirs + files


def open_path(path: str) -> bool:
    if not path:
        return False
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606 - user action
        else:
            subprocess.Popen(["xdg-open", path])  # noqa: S603,S607
        return True
    except OSError:
        return False


def reveal_path(path: str) -> bool:
    if not path:
        return False
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])  # noqa: S603,S607
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or "."])  # noqa: S603,S607
        return True
    except OSError:
        return False


class ItemsMixin:
    """Requires: state, scenes, proxy(), queue_save(), show_notice(), preferences."""

    # Lookup ------------------------------------------------------------------------
    def find_tab(self, island_id: str, tab_id: str = ""):
        _page, island = self.find_island(island_id)
        if island is None:
            return None
        if not tab_id:
            tab_id = island.active_tab_id
        return next((tab for tab in island.tabs if tab.id == tab_id), island.tabs[0] if island.tabs else None)

    @staticmethod
    def parse_container(container: str) -> tuple[str, str, str]:
        """"island:<id>:<tab>" -> ("island", id, tab); "loose" -> ("loose", "", "")."""
        parts = str(container or "").split(":")
        if parts[0] == "island" and len(parts) >= 2:
            return "island", parts[1], parts[2] if len(parts) > 2 else ""
        return parts[0], "", ""

    def container_of(self, island_id: str) -> str:
        tab = self.find_tab(island_id)
        return "island:{0}:{1}".format(island_id, tab.id if tab is not None else "")

    # Records ------------------------------------------------------------------------
    def portal_listing(self, folder: str, tab: TabState | None = None) -> list[ItemRecord]:
        try:
            with os.scandir(folder) as entries:
                children = []
                for entry in entries:
                    if entry.name.startswith("."):
                        continue
                    children.append(entry.path)
                    if len(children) >= PORTAL_LIMIT:
                        break
        except OSError:
            return []
        records = [make_record(path) for path in children]
        order = (tab.portal_order or {}).get(norm_key(folder)) if tab is not None else None
        if tab is not None and tab.sort_mode == "manual" and order:
            rank = {name.casefold(): i for i, name in enumerate(order)}
            records.sort(key=lambda r: (rank.get(os.path.basename(r.path).casefold(), len(rank)),
                                        not r.is_dir, r.name.casefold()))
            return records
        return sort_records(records, tab.sort_mode if tab is not None else "name",
                            bool(tab.sort_descending) if tab is not None else False)

    def records_for(self, island, tab: TabState | None, portal_current: str = "") -> list[ItemRecord]:
        if tab is None:
            return []
        if tab.portal_path:
            return self.portal_listing(portal_current or tab.portal_path, tab)
        records = [make_record(item.path, item.title, item.pinned) for item in tab.items if item.path]
        return sort_records(records, tab.sort_mode or "manual", bool(tab.sort_descending))

    def refresh_items(self, proxy) -> None:
        if proxy is None:
            return
        island = proxy.state
        tab = self.find_tab(island.id)
        if island.kind != "files" or tab is None:
            proxy.items.set_records([])
            return
        if not tab.portal_path:
            proxy.set_portal("")
        current = proxy.portalPath if tab.portal_path else ""
        if tab.portal_path and current and not _is_dir(current):
            current = tab.portal_path
            proxy.set_portal("")
        proxy.set_portal_missing(bool(tab.portal_path) and not _is_dir(tab.portal_path))
        proxy.items.set_icon_size(island.icon_size)
        proxy.items.set_records(self.records_for(island, tab, current))
        if tab.portal_path:
            self.watch_portals()

    # File views follow their folder ----------------------------------------------------------
    def _portal_proxies(self) -> list:
        return [proxy for proxy in list(self._proxies.values())
                if proxy.state.kind == "files" and proxy.portalRoot]

    def watch_portals(self) -> None:
        """Watch exactly the folders the file views show right now."""
        watcher = getattr(self, "_portal_watcher", None)
        if watcher is None:
            return
        wanted: dict[str, str] = {}
        for proxy in self._portal_proxies():
            path = proxy.portalPath
            if path and _is_dir(path):
                wanted[norm_key(path)] = os.path.normpath(path)
        current = {norm_key(path): path for path in watcher.directories()}
        stale = [path for key, path in current.items() if key not in wanted]
        if stale:
            watcher.removePaths(stale)
        fresh = [path for key, path in wanted.items() if key not in current]
        if fresh:
            watcher.addPaths(fresh)

    def _portal_folder_changed(self, path: str) -> None:
        self._portal_dirty.add(norm_key(path))
        self._portal_timer.start()

    def _refresh_dirty_portals(self) -> None:
        if self._dragging_items:
            self._portal_timer.start()
            return
        dirty, self._portal_dirty = self._portal_dirty, set()
        for proxy in self._portal_proxies():
            if norm_key(proxy.portalPath) in dirty:
                self.refresh_items(proxy)
        self.watch_portals()

    def refresh_portals(self) -> None:
        """Periodic safety net: a drive that came back, a missed change notification."""
        if self._dragging_items:
            return
        for proxy in self._portal_proxies():
            self.refresh_items(proxy)
        self.watch_portals()

    def refresh_all_items(self) -> None:
        for proxy in list(self._proxies.values()):
            self.refresh_items(proxy)
        self.refresh_loose()

    # Loose desktop icons -----------------------------------------------------------------
    def loose_scene(self):
        for scene in self.scenes.values():
            if scene.spec.primary:
                return scene
        return next(iter(self.scenes.values()), None)

    def refresh_loose(self) -> None:
        scene = self.loose_scene()
        for other in self.scenes.values():
            if other is not scene:
                other.loose.set_records([])
        if scene is None:
            return
        records = [make_record(item.path, item.title, item.pinned) for item in self.state.loose_items if item.path]
        scene.loose.set_records(records)
        self.layout_loose()

    def loose_cell(self) -> tuple[int, int]:
        size = 48
        return size + 44, size + 50

    def layout_loose(self) -> None:
        scene = self.loose_scene()
        if scene is None:
            return
        cell_w, cell_h = self.loose_cell()
        work = scene.spec.work
        top = work.y + (layout.TOP_BAND if scene.spec.primary else 0) + 4
        left = work.x + 10
        obstacles = []
        page = self.displayed_page(scene.key)
        if page is not None and not self._hidden:
            for island in page.islands:
                r = footprint(island)
                obstacles.append(Rect(r.x - 6, r.y - 6, r.w + 12, r.h + 12))
        rows = max(1, (work.bottom - top - 8) // cell_h)
        cols = max(1, (work.right - left - 8) // cell_w)
        positions: dict[str, tuple[float, float]] = {}
        slot = 0
        total = rows * cols
        for record in scene.loose.records():
            placed = False
            while slot < total * 2:
                col, row = divmod(slot, rows)
                slot += 1
                x = left + col * cell_w
                y = top + row * cell_h
                cell = Rect(x, y, cell_w, cell_h)
                if col >= cols:
                    # Out of space: stack over the last column rather than vanish.
                    x = left + (cols - 1) * cell_w
                if any(cell.intersects(o) for o in obstacles) and col < cols:
                    continue
                positions[record.key] = (float(x - scene.local_x), float(y - scene.local_y))
                placed = True
                break
            if not placed:
                positions[record.key] = (float(left - scene.local_x), float(top - scene.local_y))
        scene.loose.set_positions(positions)

    # Item actions ---------------------------------------------------------------------
    @Slot(str)
    def openItem(self, path: str) -> None:  # noqa: N802 - QML API
        if not open_path(path):
            self.show_notice("无法打开", path, "warning")

    @Slot(str, str)
    def openInIsland(self, container: str, path: str) -> None:  # noqa: N802
        """Double click: folders inside a file view navigate, everything else opens."""
        kind, island_id, _tab = self.parse_container(container)
        if kind == "island":
            proxy = self.proxy(island_id)
            tab = self.find_tab(island_id)
            if proxy is not None and tab is not None and tab.portal_path and _is_dir(path):
                proxy.set_portal(path)
                self.refresh_items(proxy)
                return
        self.openItem(path)

    @Slot(str)
    def revealItem(self, path: str) -> None:  # noqa: N802
        reveal_path(path)

    @Slot("QStringList")
    def copyPaths(self, paths) -> None:  # noqa: N802
        QGuiApplication.clipboard().setText("\n".join(paths))

    @Slot(str)
    @Slot(str, str)
    def copyText(self, text: str, note: str = "已复制到剪贴板") -> None:  # noqa: N802
        QGuiApplication.clipboard().setText(text)
        if note:
            self.show_notice(note, "", "success", [], 1800)

    def remove_references(self, container: str, paths: list[str]) -> int:
        """Island -> loose (never touches files)."""
        kind, island_id, tab_id = self.parse_container(container)
        if kind != "island":
            return 0
        tab = self.find_tab(island_id, tab_id)
        if tab is None or tab.portal_path:
            return 0
        keys = {norm_key(p) for p in paths}
        refs = [item for item in tab.items if norm_key(item.path) in keys]
        tab.items = [item for item in tab.items if norm_key(item.path) not in keys]
        existing = {norm_key(item.path) for item in self.state.loose_items}
        for ref in refs:
            if norm_key(ref.path) not in existing and _exists(ref.path):
                self.state.loose_items.append(ItemRef(path=ref.path, title=ref.title))
        self.refresh_all_items()
        self.queue_save()
        return len(refs)

    def remove_missing(self, container: str = "") -> int:
        removed = 0
        lists = [("loose", self.state.loose_items)]
        for page in self.state.pages:
            for island in page.islands:
                for tab in island.tabs:
                    if not tab.portal_path:
                        lists.append(("island:{0}:{1}".format(island.id, tab.id), tab.items))
        for name, items in lists:
            if container and name != container:
                continue
            keep = [item for item in items if _exists(item.path)]
            removed += len(items) - len(keep)
            items[:] = keep
        if removed:
            self.refresh_all_items()
            self.queue_save()
        return removed

    @Slot("QStringList", result=bool)
    def shellMenu(self, paths) -> bool:  # noqa: N802
        """Native Explorer context menu (Windows)."""
        if sys.platform != "win32" or not paths:
            return False
        try:
            from ..shell_menu import track_menu

            track_menu(list(paths))
        except Exception:  # noqa: BLE001 - shell extensions may fail arbitrarily
            return False
        self._scan_timer.start(600)
        return True

    # Drag out -----------------------------------------------------------------------------
    @Slot(str, "QStringList", int)
    def startDrag(self, container: str, paths, icon_size: int = 48) -> None:  # noqa: N802
        """Native drag: private payload for DeskIsle + file URLs (CF_HDROP) for Explorer."""
        paths = [p for p in paths if p]
        if not paths:
            return
        mime = QMimeData()
        payload = {"paths": paths, "source": container}
        mime.setData(MIME, json.dumps(payload).encode("utf-8"))
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths if _exists(p)])
        source = self._drag_source()
        drag = QDrag(source)
        drag.setMimeData(mime)
        pixmap = self._drag_pixmap(paths, max(32, min(96, int(icon_size or 48))))
        if pixmap is not None:
            drag.setPixmap(pixmap)
            drag.setHotSpot(QPoint(pixmap.width() // 2, pixmap.height() // 2))
        self._dragging_items = True
        try:
            result = drag.exec(Qt.DropAction.MoveAction | Qt.DropAction.CopyAction | Qt.DropAction.LinkAction,
                               Qt.DropAction.MoveAction)
        finally:
            self._dragging_items = False
            for scene in self.scenes.values():
                scene.loose.clearGap()
            for proxy in self._proxies.values():
                proxy.items.clearGap()
        if result == Qt.DropAction.MoveAction and not self._drop_handled:
            # Explorer moved the file away: forget references that vanished.
            self._scan_timer.start(500)
        self._drop_handled = False

    def _drag_source(self):
        return self

    def _drag_pixmap(self, paths: list[str], size: int):
        image = icon_provider().requestImage("{0}?s={1}".format(
            QUrl.toPercentEncoding(paths[0]).data().decode(), size), QSize(), QSize(size, size))
        if image is None or image.isNull():
            return None
        canvas = QImage(size + 24, size + 24, QImage.Format.Format_ARGB32_Premultiplied)
        canvas.fill(Qt.GlobalColor.transparent)
        p = QPainter(canvas)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(0.92)
        p.drawImage(12, 12, image.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation))
        if len(paths) > 1:
            p.setOpacity(1.0)
            p.setBrush(QColor(self.theme.accent if self.theme is not None else "#4C8DF6"))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(size, 0, 24, 24)
            p.setPen(QColor("white"))
            font = p.font()
            font.setBold(True)
            font.setPixelSize(12)
            p.setFont(font)
            p.drawText(size, 0, 24, 24, Qt.AlignmentFlag.AlignCenter, str(len(paths)))
        p.end()
        return QPixmap.fromImage(canvas)

    # Drop in --------------------------------------------------------------------------------
    @Slot(str, int, str, "QStringList", result=bool)
    def dropItems(self, container: str, index: int, payload_text: str, urls) -> bool:  # noqa: N802
        """QML DropArea -> move/reorder references, or add external files."""
        payload = {}
        if payload_text:
            try:
                payload = json.loads(payload_text)
            except (TypeError, ValueError):
                payload = {}
        paths = [str(p) for p in payload.get("paths", []) if p]
        source = str(payload.get("source") or "")
        if not paths:
            paths = [QUrl(u).toLocalFile() if "://" in str(u) else str(u) for u in urls]
            paths = [p for p in paths if p]
            source = ""
        if not paths:
            return False
        self._drop_handled = True
        kind, island_id, tab_id = self.parse_container(container)
        if kind == "loose":
            self.drop_to_loose(paths, source, index)
            return True
        if kind != "island":
            return False
        tab = self.find_tab(island_id, tab_id)
        if tab is None:
            return False
        if tab.portal_path:
            proxy = self.proxy(island_id)
            folder = proxy.portalPath if proxy is not None else tab.portal_path
            if source.startswith("island:") or source == LOOSE or not source:
                self.move_into_folder(paths, folder, source)
            return True
        if source == "island:{0}:{1}".format(island_id, tab.id):
            self.reorder(tab, paths, index)
        else:
            self.move_references(paths, source, tab, index)
        return True

    def reorder(self, tab: TabState, paths: list[str], index: int) -> None:
        keys = {norm_key(p) for p in paths}
        shown = self.records_for(None, tab)
        if tab.sort_mode != "manual":
            # Dragging inside a sorted tab switches it to manual order (as Explorer does).
            order = {norm_key(r.path): i for i, r in enumerate(shown)}
            tab.items.sort(key=lambda item: order.get(norm_key(item.path), 1 << 30))
            tab.sort_mode = "manual"
        moving = [item for item in tab.items if norm_key(item.path) in keys]
        remaining = [item for item in tab.items if norm_key(item.path) not in keys]
        if index >= 0:
            # ``index`` counts every shown item (the dragged ones included); convert it.
            index -= sum(1 for item in tab.items[:index] if norm_key(item.path) in keys)
        at = max(0, min(len(remaining), index if index >= 0 else len(remaining)))
        tab.items = remaining[:at] + moving + remaining[at:]
        self.refresh_all_items()
        self.queue_save()

    def move_references(self, paths: list[str], source: str, tab: TabState, index: int = -1) -> None:
        existing = {norm_key(item.path) for item in tab.items}
        added = []
        for path in paths:
            if norm_key(path) not in existing:
                added.append(ItemRef(path=path))
                existing.add(norm_key(path))
        if index >= 0 and tab.sort_mode == "manual":
            at = min(len(tab.items), index)
            tab.items[at:at] = added
        else:
            tab.items.extend(added)
        keys = {norm_key(p) for p in paths}
        if source == LOOSE:
            self.state.loose_items = [i for i in self.state.loose_items if norm_key(i.path) not in keys]
        elif source.startswith("island:"):
            _k, sid, stab = self.parse_container(source)
            src = self.find_tab(sid, stab)
            if src is not None and src is not tab and not src.portal_path:
                src.items = [i for i in src.items if norm_key(i.path) not in keys]
        self.refresh_all_items()
        self.queue_save()

    def drop_to_loose(self, paths: list[str], source: str, index: int = -1) -> None:
        keys = {norm_key(p) for p in paths}
        if source == LOOSE:
            moving = [i for i in self.state.loose_items if norm_key(i.path) in keys]
            remaining = [i for i in self.state.loose_items if norm_key(i.path) not in keys]
            if index >= 0:
                index -= sum(1 for i in self.state.loose_items[:index] if norm_key(i.path) in keys)
            at = len(remaining) if index < 0 else max(0, min(len(remaining), index))
            self.state.loose_items = remaining[:at] + moving + remaining[at:]
        else:
            existing = {norm_key(i.path) for i in self.state.loose_items}
            added = [ItemRef(path=p) for p in paths if norm_key(p) not in existing]
            at = len(self.state.loose_items) if index < 0 else min(len(self.state.loose_items), index)
            self.state.loose_items[at:at] = added
            if source.startswith("island:"):
                _k, sid, stab = self.parse_container(source)
                src = self.find_tab(sid, stab)
                if src is not None and not src.portal_path:
                    src.items = [i for i in src.items if norm_key(i.path) not in keys]
        self.refresh_all_items()
        self.queue_save()

    def move_into_folder(self, paths: list[str], folder: str, source: str, confirmed: bool = False) -> None:
        """Dropping onto a file view moves the files into that folder (undoable in Explorer).

        This is the only place where DeskIsle changes files on disk, so it asks first.
        """
        if not folder or not _is_dir(folder):
            return
        paths = [p for p in paths if _exists(p) and norm_key(os.path.dirname(p)) != norm_key(folder)
                 and norm_key(p) != norm_key(folder)]
        if not paths:
            return
        if not confirmed:
            first = os.path.basename(paths[0].rstrip("\\/")) or paths[0]
            what = "“{0}”".format(first) if len(paths) == 1 else "{0} 个项目".format(len(paths))
            target = os.path.basename(folder.rstrip("\\/")) or folder
            self.confirm("把{0}移动到“{1}”？".format(what, target),
                         "文件视窗显示的是真实文件夹，文件会真正移动过去（可在资源管理器中按 Ctrl+Z 撤销）。",
                         "移动", lambda: self.move_into_folder(paths, folder, source, confirmed=True),
                         danger=False)
            return
        moved = False
        if sys.platform == "win32":
            try:
                from ..native_win import shell_move

                moved = shell_move(paths, folder)
            except (ImportError, OSError, AttributeError):
                moved = False
        if not moved and sys.platform != "win32":
            for path in paths:
                try:
                    shutil.move(path, os.path.join(folder, os.path.basename(path)))
                    moved = True
                except OSError as exc:
                    self.show_notice("移动失败", str(exc), "warning")
        if moved:
            self._scan_timer.start(400)
            for proxy in self._proxies.values():
                if proxy.portalPath and norm_key(proxy.portalPath) == norm_key(folder):
                    self.refresh_items(proxy)

    # Desktop scanning ------------------------------------------------------------------------
    def import_new_desktop_items(self, initial: bool = False) -> int:
        disk_paths: list[str] = []
        scanned: dict[str, set[str]] = {}
        for folder in self._desktop_dirs:
            try:
                children = list(folder.iterdir())
            except OSError:
                continue
            scanned[norm_key(str(folder))] = {norm_key(str(p)) for p in children}
            disk_paths.extend(str(p) for p in children if not p.name.startswith(".")
                              and p.name.casefold() != "desktop.ini")

        def deleted(ref) -> bool:
            key = norm_key(os.path.abspath(ref.path))
            parent = os.path.dirname(key)
            return parent in scanned and key not in scanned[parent]

        removed = 0
        lists = [self.state.loose_items]
        lists.extend(tab.items for page in self.state.pages for island in page.islands
                     for tab in island.tabs if not tab.portal_path)
        for items in lists:
            keep = [item for item in items if not deleted(item)]
            removed += len(items) - len(keep)
            items[:] = keep
        assigned = {norm_key(i.path) for i in self.state.loose_items}
        for page in self.state.pages:
            for island in page.islands:
                for tab in island.tabs:
                    if not tab.portal_path:
                        assigned.update(norm_key(i.path) for i in tab.items)
        new_paths = [p for p in disk_paths if norm_key(p) not in assigned]
        islands = {island.id: island for page in self.state.pages for island in page.islands}
        for path in new_paths:
            target_id = None
            if self.state.preferences.auto_organize:
                self._rules.rules = self.state.rules
                try:
                    target_id = self._rules.choose_target(path)
                except Exception:  # noqa: BLE001 - user rules must never break scanning
                    target_id = None
                target_id = getattr(target_id, "target_island_id", target_id)
            target = islands.get(target_id) if target_id else None
            tab = None
            if target is not None and target.kind == "files":
                tab = next((t for t in target.tabs if not t.portal_path), None)
            if tab is not None:
                tab.items.append(ItemRef(path=path))
            else:
                self.state.loose_items.append(ItemRef(path=path))
        if new_paths or removed:
            self.refresh_all_items()
            self.queue_save()
        if new_paths and not initial:
            self.show_notice("发现新项目", "已整理 {0} 个新桌面项目。".format(len(new_paths)), "info")
        return len(new_paths)

    def apply_rules_now(self) -> int:
        """Re-run the rules over loose items (manual "立即归流")."""
        moved = 0
        islands = {island.id: island for page in self.state.pages for island in page.islands}
        self._rules.rules = self.state.rules
        keep = []
        for item in self.state.loose_items:
            try:
                target_id = self._rules.choose_target(item.path)
            except Exception:  # noqa: BLE001
                target_id = None
            target_id = getattr(target_id, "target_island_id", target_id)
            target = islands.get(target_id) if target_id else None
            tab = next((t for t in target.tabs if not t.portal_path), None) if target is not None else None
            if tab is not None and target.kind == "files":
                if norm_key(item.path) not in {norm_key(i.path) for i in tab.items}:
                    tab.items.append(item)
                moved += 1
            else:
                keep.append(item)
        self.state.loose_items = keep
        if moved:
            self.refresh_all_items()
            self.queue_save()
        return moved

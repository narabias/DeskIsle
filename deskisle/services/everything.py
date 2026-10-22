"""Search for the dynamic bar: DeskIsle's own items + Everything (voidtools).

Everything
----------
When Everything (https://www.voidtools.com) is running we talk to it through
its documented IPC: a ``WM_COPYDATA`` message with an
``EVERYTHING_IPC_QUERY2W`` block is sent to the window of class
``EVERYTHING_TASKBAR_NOTIFICATION``; Everything answers with another
``WM_COPYDATA`` (``EVERYTHING_IPC_LIST2``) to a hidden window of ours.  No DLL
is needed and nothing is installed.  The reply arrives through the app's
native event filter (:meth:`SearchService.handle_copydata`).

Without Everything a small built-in index (desktop folders, Start menu,
user folders, island folders) is searched on a worker thread.
"""

from __future__ import annotations

import ctypes
import logging
import os
import struct
import sys
import threading
import time
from pathlib import Path

from PySide6.QtCore import Property, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QGuiApplication, QWindow

from ..engine.scene import icon_url, norm_key

log = logging.getLogger("deskisle.search")
IS_WINDOWS = sys.platform == "win32"

WM_COPYDATA = 0x004A
EVERYTHING_IPC_COPYDATA_QUERY2W = 18
EVERYTHING_WINDOW_CLASSES = ("EVERYTHING_TASKBAR_NOTIFICATION", "EVERYTHING_TASKBAR_NOTIFICATION_(1.5a)")
REQUEST_NAME = 0x00000001
REQUEST_PATH = 0x00000002
SORT_NAME_ASCENDING = 1
SORT_DATE_RUN_DESCENDING = 26
ITEM_FOLDER = 0x1
ITEM_DRIVE = 0x2
REPLY_BASE = 0x0D150000
MAX_RESULTS = 40
SMTO_ABORTIFHUNG = 0x0002


def pack_query(text: str, reply_hwnd: int, reply_id: int, max_results: int = MAX_RESULTS,
               sort: int = SORT_NAME_ASCENDING, search_flags: int = 0) -> bytes:
    """EVERYTHING_IPC_QUERY2 header + UTF-16 search string (null terminated)."""
    header = struct.pack("<7I", int(reply_hwnd) & 0xFFFFFFFF, int(reply_id) & 0xFFFFFFFF, int(search_flags), 0,
                         int(max_results), REQUEST_NAME | REQUEST_PATH, int(sort))
    return header + (text + "\0").encode("utf-16-le")


def parse_list2(data: bytes) -> tuple[int, list[dict]]:
    """EVERYTHING_IPC_LIST2 (NAME | PATH requested) -> (total, [{name, folder, path, isDir}])."""
    if len(data) < 20:
        return 0, []
    total, count, _offset, flags, _sort = struct.unpack_from("<5I", data, 0)
    results = []
    for i in range(count):
        base = 20 + i * 8
        if base + 8 > len(data):
            break
        item_flags, offset = struct.unpack_from("<2I", data, base)
        fields = {}
        for bit, name in ((REQUEST_NAME, "name"), (REQUEST_PATH, "folder")):
            if not flags & bit:
                continue
            if offset + 4 > len(data):
                break
            (length,) = struct.unpack_from("<I", data, offset)
            offset += 4
            raw = data[offset:offset + length * 2]
            fields[name] = raw.decode("utf-16-le", "replace")
            offset += (length + 1) * 2
        name = fields.get("name", "")
        folder = fields.get("folder", "")
        if not name:
            continue
        if folder and "\\" in folder:
            path = folder.rstrip("\\") + "\\" + name
        else:
            path = os.path.join(folder, name) if folder else name
        results.append({"name": name, "folder": folder, "path": path,
                        "isDir": bool(item_flags & (ITEM_FOLDER | ITEM_DRIVE))})
    return int(total), results


def split_terms(text: str) -> list[str]:
    return [t for t in (text or "").casefold().split() if t]


def score(name: str, terms: list[str]) -> int:
    """Lower is better; -1 = no match."""
    low = name.casefold()
    best = 0
    for term in terms:
        index = low.find(term)
        if index < 0:
            return -1
        if index == 0:
            rank = 0
        elif not low[index - 1].isalnum():
            rank = 1
        else:
            rank = 3
        best += rank
    return best * 100 + min(99, len(name))


# ---------------------------------------------------------------------------------------------
class LocalIndex:
    """Small file index used when Everything is not available."""

    MAX_ENTRIES = 60_000
    REBUILD_S = 600

    def __init__(self) -> None:
        self.entries: list[tuple[str, str, bool]] = []   # (name, path, is_dir)
        self.built = 0.0
        self.building = False
        self.extra_roots: list[str] = []
        self._lock = threading.Lock()

    def roots(self) -> list[tuple[Path, int]]:
        home = Path.home()
        roots: list[tuple[Path, int]] = []
        if IS_WINDOWS:
            appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
            program_data = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
            public = Path(os.environ.get("PUBLIC", r"C:\Users\Public"))
            roots += [(appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs", 4),
                      (program_data / "Microsoft" / "Windows" / "Start Menu" / "Programs", 4),
                      (public / "Desktop", 2)]
        for name, depth in (("Desktop", 3), ("Documents", 3), ("Downloads", 2), ("Pictures", 2), ("Music", 2),
                            ("Videos", 2)):
            roots.append((home / name, depth))
        roots += [(Path(p), 3) for p in self.extra_roots]
        seen, unique = set(), []
        for path, depth in roots:
            key = norm_key(str(path))
            if key not in seen and path.is_dir():
                seen.add(key)
                unique.append((path, depth))
        return unique

    def ensure(self) -> None:
        if self.building or (self.entries and time.time() - self.built < self.REBUILD_S):
            return
        self.building = True
        threading.Thread(target=self._build, name="deskisle-index", daemon=True).start()

    def _build(self) -> None:
        entries: list[tuple[str, str, bool]] = []
        try:
            for root, depth in self.roots():
                self._walk(str(root), depth, entries)
                if len(entries) >= self.MAX_ENTRIES:
                    break
        finally:
            with self._lock:
                self.entries = entries
                self.built = time.time()
                self.building = False

    def _walk(self, folder: str, depth: int, out: list) -> None:
        try:
            with os.scandir(folder) as it:
                for entry in it:
                    if entry.name.startswith(".") or entry.name.casefold() in ("desktop.ini", "thumbs.db"):
                        continue
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    out.append((entry.name, entry.path, is_dir))
                    if len(out) >= self.MAX_ENTRIES:
                        return
                    if is_dir and depth > 1 and entry.name.casefold() not in ("node_modules", "$recycle.bin",
                                                                               "appdata", "__pycache__"):
                        self._walk(entry.path, depth - 1, out)
        except OSError:
            return

    def search(self, terms: list[str], limit: int = MAX_RESULTS) -> list[dict]:
        with self._lock:
            entries = list(self.entries)
        ranked = []
        for name, path, is_dir in entries:
            shown = name[:-4] if name.casefold().endswith(".lnk") else name
            s = score(shown, terms)
            if s >= 0:
                bonus = -40 if name.casefold().endswith((".lnk", ".exe", ".url")) else 0
                ranked.append((s + bonus, shown, path, is_dir))
        ranked.sort(key=lambda r: (r[0], r[1].casefold()))
        seen, results = set(), []
        for _s, shown, path, is_dir in ranked:
            key = norm_key(path)
            if key in seen:
                continue
            seen.add(key)
            results.append({"name": shown, "folder": os.path.dirname(path), "path": path, "isDir": is_dir})
            if len(results) >= limit:
                break
        return results


# ---------------------------------------------------------------------------------------------
class SearchService(QObject):
    """Exposed to QML as ``Search``."""

    changed = Signal()
    _local_done = Signal(int, object)

    def __init__(self, desk=None, demo: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.desk = desk
        self.demo = demo
        self._query = ""
        self._desk_results: list[dict] = []
        self._file_results: list[dict] = []
        self._total = 0
        self._status = ""
        self._engine = "none"
        self._busy = False
        self._seq = 0
        self._reply_window = None
        self.index = LocalIndex()
        if demo:
            root = os.environ.get("DESKISLE_DEMO_FILES", "")
            self.index.extra_roots = [root] if root else []
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(110)
        self._debounce.timeout.connect(self._run)
        self._timeout = QTimer(self)
        self._timeout.setSingleShot(True)
        self._timeout.setInterval(1800)
        self._timeout.timeout.connect(self._everything_timeout)
        self._local_done.connect(self._local_finished)

    # Everything ---------------------------------------------------------------------------------
    def everything_window(self) -> int:
        if not IS_WINDOWS or self.demo:
            return 0
        prefs = getattr(self.desk, "preferences", None)
        if prefs is not None and not getattr(prefs, "everything_search", True):
            return 0
        user32 = ctypes.windll.user32
        user32.FindWindowW.restype = ctypes.c_void_p
        for cls in EVERYTHING_WINDOW_CLASSES:
            hwnd = user32.FindWindowW(cls, None)
            if hwnd:
                return int(hwnd)
        return 0

    def _reply_hwnd(self) -> int:
        if self._reply_window is None:
            window = QWindow()
            window.setTitle("DeskIsle search reply")
            window.create()
            self._reply_window = window
            try:
                # Allow replies from a non-elevated Everything if DeskIsle runs elevated.
                ctypes.windll.user32.ChangeWindowMessageFilterEx(ctypes.c_void_p(int(window.winId())),
                                                                 WM_COPYDATA, 1, None)
            except (AttributeError, OSError):
                pass
        return int(self._reply_window.winId())

    def _query_everything(self, text: str) -> bool:
        hwnd = self.everything_window()
        if not hwnd:
            return False
        from ctypes import wintypes

        class COPYDATASTRUCT(ctypes.Structure):
            _fields_ = [("dwData", ctypes.c_size_t), ("cbData", wintypes.DWORD), ("lpData", ctypes.c_void_p)]

        self._seq = (self._seq + 1) & 0xFFFF
        payload = pack_query(text, self._reply_hwnd(), REPLY_BASE + self._seq)
        buffer = ctypes.create_string_buffer(payload, len(payload))
        cds = COPYDATASTRUCT(EVERYTHING_IPC_COPYDATA_QUERY2W, len(payload), ctypes.cast(buffer, ctypes.c_void_p))
        result = ctypes.c_size_t(0)
        user32 = ctypes.windll.user32
        user32.SendMessageTimeoutW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p,
                                               ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_size_t)]
        ok = user32.SendMessageTimeoutW(ctypes.c_void_p(hwnd), WM_COPYDATA, ctypes.c_void_p(self._reply_hwnd()),
                                        ctypes.byref(cds), SMTO_ABORTIFHUNG, 1500, ctypes.byref(result))
        if not ok or not result.value:
            return False
        self._engine = "everything"
        self._busy = True
        self._timeout.start()
        return True

    def handle_copydata(self, hwnd: int, wparam: int, lparam: int) -> bool:
        """Called by the native event filter for WM_COPYDATA (must copy synchronously)."""
        if not lparam or self._reply_window is None or int(hwnd) != int(self._reply_window.winId()):
            return False
        from ctypes import wintypes

        class COPYDATASTRUCT(ctypes.Structure):
            _fields_ = [("dwData", ctypes.c_size_t), ("cbData", wintypes.DWORD), ("lpData", ctypes.c_void_p)]

        cds = COPYDATASTRUCT.from_address(int(lparam))
        reply = int(cds.dwData)
        if reply & 0xFFFF0000 != REPLY_BASE:
            return False
        data = ctypes.string_at(cds.lpData, int(cds.cbData)) if cds.lpData and cds.cbData else b""
        if (reply & 0xFFFF) != self._seq:
            return True                 # stale answer to an older query
        total, results = parse_list2(data)
        QTimer.singleShot(0, lambda: self._everything_finished(total, results))
        return True

    def _everything_finished(self, total: int, results: list[dict]) -> None:
        self._timeout.stop()
        self._busy = False
        self._total = total
        self._file_results = [self._decorate(r, "files") for r in results]
        self._status = "Everything · 共 {0} 个结果".format(total) if total else "Everything 中没有找到"
        self.changed.emit()

    def _everything_timeout(self) -> None:
        if self._busy and self._engine == "everything":
            self._busy = False
            self._status = "Everything 没有响应，已改用内置索引"
            self._search_local(self._query)

    # Local ----------------------------------------------------------------------------------------
    def _search_local(self, text: str) -> None:
        self._engine = "local"
        terms = split_terms(text)
        roots = []
        if self.desk is not None:
            for page in self.desk.state.pages:
                for island in page.islands:
                    roots += [t.portal_path for t in island.tabs if t.portal_path]
        self.index.extra_roots = list(dict.fromkeys(roots + (self.index.extra_roots if self.demo else [])))
        self.index.ensure()
        seq = self._seq = (self._seq + 1) & 0xFFFF
        self._busy = True

        def work() -> None:
            deadline = time.time() + 8
            while self.index.building and time.time() < deadline:
                time.sleep(0.05)
            self._local_done.emit(seq, self.index.search(terms))

        threading.Thread(target=work, name="deskisle-local-search", daemon=True).start()

    def _local_finished(self, seq: int, results) -> None:
        if seq != self._seq:
            return
        self._busy = False
        self._total = len(results)
        self._file_results = [self._decorate(r, "files") for r in results]
        hint = "" if not IS_WINDOWS or self.demo else " · 安装 Everything 可搜索整台电脑"
        self._status = ("内置索引 · {0} 个结果".format(len(results)) if results else "没有找到文件") + hint
        self.changed.emit()

    # Desk items ------------------------------------------------------------------------------------
    def _search_desk(self, terms: list[str]) -> list[dict]:
        desk = self.desk
        if desk is None:
            return []
        results = []
        current = set(desk.state.current_pages.values())
        for page in desk.state.pages:
            for island in page.islands:
                where = island.title + ("" if page.id in current else " · 预设“{0}”".format(page.title))
                if score(island.title, terms) >= 0:
                    results.append({"name": island.title, "folder": where, "path": "", "isDir": False,
                                    "uid": island.id, "pageId": page.id, "kind": "island",
                                    "glyph": {"files": "box", "web": "world"}.get(island.kind, "layout")})
                for tab in island.tabs:
                    for item in tab.items:
                        name = item.title or os.path.basename(item.path.rstrip("\\/"))
                        shown = name[:-4] if name.casefold().endswith(".lnk") else name
                        s = score(shown, terms)
                        if s >= 0:
                            results.append({"name": shown, "folder": where, "path": item.path,
                                            "isDir": os.path.isdir(item.path), "uid": island.id,
                                            "pageId": page.id, "kind": "item", "score": s})
        for item in desk.state.loose_items:
            name = item.title or os.path.basename(item.path.rstrip("\\/"))
            shown = name[:-4] if name.casefold().endswith(".lnk") else name
            s = score(shown, terms)
            if s >= 0:
                results.append({"name": shown, "folder": "桌面散放区", "path": item.path,
                                "isDir": os.path.isdir(item.path), "uid": "", "pageId": "", "kind": "item",
                                "score": s})
        results.sort(key=lambda r: (r.get("kind") != "island", r.get("score", 0), r["name"].casefold()))
        return [self._decorate(r, "desk") for r in results[:12]]

    def _decorate(self, result: dict, section: str) -> dict:
        result = dict(result)
        result["section"] = section
        result.setdefault("kind", "file")
        result.setdefault("uid", "")
        result.setdefault("glyph", "")
        result["icon"] = icon_url(result["path"], 64) if result.get("path") else ""
        return result

    # QML API ----------------------------------------------------------------------------------------
    @Slot(str)
    def search(self, text: str) -> None:
        self._query = text or ""
        if not self._query.strip():
            self.clear()
            return
        self._debounce.start()

    def _run(self) -> None:
        text = self._query.strip()
        terms = split_terms(text)
        self._desk_results = self._search_desk(terms)
        self._file_results = []
        self._status = "正在搜索…"
        self.changed.emit()
        if not self._query_everything(text):
            self._search_local(text)

    @Slot()
    def clear(self) -> None:
        self._query = ""
        self._desk_results = []
        self._file_results = []
        self._status = ""
        self._busy = False
        self._total = 0
        self.changed.emit()

    @Slot()
    def warmUp(self) -> None:  # noqa: N802 - start the local index before the first key press
        if not self.everything_window():
            self.index.ensure()
        self._engine = "everything" if self.everything_window() else "local"
        self.changed.emit()

    @Slot(str)
    def open(self, path: str) -> None:
        if self.desk is not None:
            self.desk.openItem(path)
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @Slot(str)
    def reveal(self, path: str) -> None:
        if self.desk is not None:
            self.desk.revealItem(path)

    @Slot(str)
    def copyPath(self, path: str) -> None:  # noqa: N802
        QGuiApplication.clipboard().setText(path)

    @Slot(str, str, str)
    def locate(self, uid: str, page_id: str, path: str) -> None:
        """Show where a desk result lives: switch preset if needed, raise and highlight."""
        desk = self.desk
        if desk is None or not uid:
            return
        key = desk.monitor_of_page(page_id)
        if not key:
            page = desk.state.page(page_id)
            key = page.monitor_key if page is not None and desk.spec_for(page.monitor_key) else \
                desk.primary_spec().key
            desk.switch_page(key, page_id)
        proxy = desk.proxy(uid)
        if proxy is None:
            return
        if proxy.state.collapsed:
            desk.island_action(uid, "collapse", {"value": False})
        if path:
            for tab in proxy.state.tabs:
                if any(norm_key(i.path) == norm_key(path) for i in tab.items):
                    if proxy.state.active_tab_id != tab.id:
                        desk.island_action(uid, "tab", {"id": tab.id})
                    break
        proxy.raise_()
        proxy.flash.emit("locate:" + path if path else "locate")
        desk.closePanel()

    def idle(self) -> bool:
        """True once the last query has finished (desk part and file part)."""
        return not self._debounce.isActive() and not self._busy and self._status != "正在搜索…"

    def snapshot(self) -> dict:
        return {"query": self._query, "engine": self._engine, "status": self._status,
                "desk": self._desk_results, "files": self._file_results}

    def shutdown(self) -> None:
        if self._reply_window is not None:
            self._reply_window.destroy()

    query = Property(str, lambda self: self._query, notify=changed)
    deskResults = Property("QVariantList", lambda self: list(self._desk_results), notify=changed)
    fileResults = Property("QVariantList", lambda self: list(self._file_results), notify=changed)
    total = Property(int, lambda self: self._total, notify=changed)
    status = Property(str, lambda self: self._status, notify=changed)
    busy = Property(bool, lambda self: self._busy, notify=changed)
    engine = Property(str, lambda self: self._engine, notify=changed)
    available = Property(bool, lambda self: True, constant=True)


__all__ = ["LocalIndex", "SearchService", "pack_query", "parse_list2", "score"]

"""Qt-side implementation of every agent command (catalogue: ``schema.py``).

``Commands.handle(name, args, respond)`` validates the arguments against the
schema, runs the handler on the Qt thread and calls ``respond(ok, payload)``
exactly once.  ``payload`` is the result (``ok=True``) or
``{"code", "message"}`` (``ok=False``).

Destructive commands never act on their own: their handler returns a
:class:`Plan` and the user is asked with the desk's confirm card (labelled
“来自 AI 助手”).  The response waits for the answer up to ``wait`` seconds;
after that the agent gets ``status=pending`` plus a ``confirm_id`` to poll with
``confirm.status``.  ``dry_run=true`` only describes the plan.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QTimer

from .. import __version__
from . import PROTOCOL_VERSION
from .schema import BY_NAME, COMMANDS, input_schema, validate

log = logging.getLogger("deskisle.agent")

WAIT_DEFAULT, WAIT_MAX = 90.0, 300.0
SEARCH_WAIT_MS = 3000
CONFIRM_KEEP = 64
LOOSE = "loose"
ISLAND_ACTIONS = {
    "collapse", "lock", "pin", "keepVisible", "capsule", "rename", "material", "raise", "tab", "addTab",
    "renameTab", "iconSize", "sort", "autoSort", "portal", "portalOpen", "portalUp", "portalHome", "media",
    "widgetConfig", "web.url", "web.home", "web.reload", "web.back", "web.forward", "web.external",
    "web.toolbar", "web.refresh", "web.zoom", "web.network",
}
WIDGET_CONFIG_DOCS = {
    "clock": {"style": "digital | analog | split", "h24": "bool", "seconds": "bool", "lunar": "bool"},
    "weather": {"city": "name shown", "lat": "number", "lon": "number"},
    "media": {"compact": "bool"},
    "todo": {"items": "managed by todo.* commands", "hideDone": "bool"},
}
TOKEN_KEYS = ("radius", "smallRadius", "glassStrength", "shadow", "motion", "fontScale", "headerHeight",
              "barHeight", "iconLabelLines")
SAFE_FILE = re.compile(r"^[A-Za-z0-9_.\- /]+$")
MAX_WIDGET_FILE = 2 * 1024 * 1024


class AgentError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def fail(code: str, message: str):
    raise AgentError(code, message)


class Plan:
    """What a destructive command would do; ``run()`` does it after the user agreed."""

    def __init__(self, title: str, text: str, accept: str, run, summary: str = "") -> None:
        self.title, self.text, self.accept, self.run = title, text, accept, run
        self.summary = summary or title


class Later:
    """A result that arrives after the handler returned (search, ...)."""

    def __init__(self) -> None:
        self._respond = None
        self._done = None

    def attach(self, respond) -> None:
        self._respond = respond
        if self._done is not None:
            respond(*self._done)

    def finish(self, ok: bool, payload) -> None:
        if self._done is not None:
            return
        self._done = (ok, payload)
        if self._respond is not None:
            self._respond(ok, payload)


def rect_info(x, y, w, h) -> dict:
    return {"x": int(x), "y": int(y), "width": int(w), "height": int(h)}


def island_info(desk, page, s, include_items: bool = False) -> dict:
    proxy = desk.proxy(s.id)
    info = {
        "uid": s.id, "kind": s.kind, "title": s.title,
        "page": page.id if page is not None else "", "page_title": page.title if page is not None else "",
        "monitor": desk.monitor_of_page(page.id) if page is not None else "",
        "shown": proxy is not None,
        **rect_info(s.x, s.y, s.width, s.height),
        "collapsed": bool(s.collapsed), "locked": bool(s.locked), "pinned": bool(s.pin_on_top),
        "capsule": bool(s.capsule), "keep_visible": bool(s.exclude_from_hide),
        "material": s.material or "default", "icon_size": int(s.icon_size),
    }
    if s.kind == "files":
        tabs = []
        for tab in s.tabs:
            entry = {"id": tab.id, "title": tab.title, "active": tab.id == s.active_tab_id,
                     "folder": tab.portal_path or "", "sort": tab.sort_mode,
                     "descending": bool(tab.sort_descending), "count": len(tab.items)}
            if include_items:
                entry["items"] = [r.path for r in desk.records_for(s, tab)]
            tabs.append(entry)
        info["tabs"] = tabs
    elif s.kind == "web":
        host = getattr(desk.layers, "webhost", None) if desk.layers is not None else None
        view = host.views.get(s.id) if host is not None else None
        info["web"] = {"url": s.web_url, "html_path": s.html_path, "network": bool(s.html_allow_network),
                       "toolbar": bool(s.web_toolbar), "zoom": float(s.web_zoom),
                       "refresh_minutes": int(s.web_refresh_minutes),
                       "mode": getattr(view, "mode", "") if view is not None else "not loaded",
                       "current_url": proxy.web.get("url", "") if proxy is not None else ""}
    else:
        config = {k: v for k, v in s.widget_config.items() if k != "items"}
        info["widget"] = s.widget
        info["config"] = config
        if s.widget == "todo":
            info["todo_count"] = len(s.widget_config.get("items") or [])
    if s.media_path:
        info["media"] = {"path": s.media_path, "opacity": s.media_opacity, "feather": s.media_feather}
    return info


class Commands(QObject):
    def __init__(self, app, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.app = app
        self._confirms: dict[str, dict] = {}
        self._search = None

    @property
    def desk(self):
        return self.app.desk

    # Dispatch ------------------------------------------------------------------------------------
    def handle(self, name: str, args, respond) -> None:
        if args is None:
            args = {}
        problems = validate(name, args)
        if problems:
            respond(False, {"code": "invalid_args" if name in BY_NAME else "unknown_command",
                            "message": "; ".join(problems)})
            return
        spec = BY_NAME[name]
        handler = getattr(self, "c_" + name.replace(".", "_"), None)
        if handler is None:
            respond(False, {"code": "not_implemented", "message": name})
            return
        try:
            if spec["destructive"]:
                self._destructive(name, args, handler, respond)
                return
            result = handler(args)
        except AgentError as exc:
            respond(False, {"code": exc.code, "message": exc.message})
            return
        except Exception as exc:  # noqa: BLE001 - reported to the agent, logged here
            log.exception("agent command %s failed", name)
            respond(False, {"code": "internal", "message": "{0}: {1}".format(type(exc).__name__, exc)})
            return
        if isinstance(result, Later):
            result.attach(respond)
        else:
            respond(True, result)

    def run(self, name: str, args=None, timeout: float = 5.0):
        """Synchronous helper for tests: returns ``(ok, payload)`` (spins the event loop)."""
        from PySide6.QtCore import QCoreApplication, QEventLoop

        box: list = []
        self.handle(name, args or {}, lambda ok, payload: box.append((ok, payload)))
        deadline = time.time() + timeout
        while not box and time.time() < deadline:
            QCoreApplication.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            time.sleep(0.005)
        return box[0] if box else (False, {"code": "timeout", "message": "no answer"})

    def _destructive(self, name: str, args: dict, handler, respond) -> None:
        plan = handler(args)
        if args.get("dry_run"):
            respond(True, {"status": "dry_run", "would": plan.summary, "title": plan.title, "text": plan.text})
            return
        pending = self.desk.pending_confirm()
        if pending:
            fail("busy", "a confirmation is already waiting on the desk ({0}); poll confirm.status or try "
                         "again later".format(pending.get("title", "")))
        wait = args.get("wait")
        wait = WAIT_DEFAULT if wait is None else max(0.0, min(WAIT_MAX, float(wait)))
        record = {"id": "", "command": name, "title": plan.title, "status": "pending", "result": None,
                  "error": None, "created": time.time()}
        sent = {"done": False}

        def answer(ok: bool, payload) -> None:
            if not sent["done"]:
                sent["done"] = True
                respond(ok, payload)

        def accepted() -> None:
            try:
                result = plan.run()
            except AgentError as exc:
                record.update(status="failed", error={"code": exc.code, "message": exc.message})
                answer(False, dict(record["error"], confirm_id=record["id"]))
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("confirmed agent command %s failed", name)
                record.update(status="failed", error={"code": "internal", "message": str(exc)})
                answer(False, dict(record["error"], confirm_id=record["id"]))
                return
            record.update(status="accepted", result=result)
            answer(True, {"status": "accepted", "confirm_id": record["id"], "result": result})

        def rejected() -> None:
            record["status"] = "rejected"
            answer(False, {"code": "rejected", "confirm_id": record["id"],
                           "message": "The user declined this action (用户拒绝了这个操作)."})

        cid = self.desk.confirm(plan.title, plan.text, plan.accept, accepted, danger=True,
                                cancel_callback=rejected, source="agent")
        record["id"] = cid
        self._confirms[cid] = record
        while len(self._confirms) > CONFIRM_KEEP:
            self._confirms.pop(next(iter(self._confirms)))
        waiting = {"status": "pending", "confirm_id": cid,
                   "message": "Waiting for the user to answer on the desk; poll confirm.status."}
        if wait <= 0:
            answer(True, waiting)
        else:
            QTimer.singleShot(int(wait * 1000), lambda: answer(True, waiting) if record["status"] == "pending"
                              else None)

    # Lookups ----------------------------------------------------------------------------------------
    def _island(self, uid: str):
        page, island = self.desk.find_island(uid)
        if island is None:
            fail("not_found", "no island with uid {0!r}; see island.list".format(uid))
        return page, island

    def _key(self, monitor: str | None) -> str:
        desk = self.desk
        if monitor:
            spec = desk.spec_for(monitor)
            if spec is None:
                fail("not_found", "no monitor {0!r}; see monitor.list".format(monitor))
            return spec.key
        return desk.primary_spec().key

    def _service(self, name: str):
        service = self.app.services.get(name)
        if service is None or not bool(service.property("available")):
            reason = str(service.property("error") or "") if service is not None else ""
            fail("unavailable", "the {0} service is not available here{1}".format(
                name, ": " + reason if reason else ""))
        return service

    def _widget_island(self, uid: str, widget: str):
        page, s = self._island(uid)
        if s.kind != "widget" or s.widget != widget:
            fail("wrong_kind", "island {0} is not a {1} widget".format(uid, widget))
        return page, s

    def _monitor_list(self) -> list:
        desk = self.desk
        result = []
        for spec in desk.monitors():
            page = desk.displayed_page(spec.key)
            g, w = spec.geometry, spec.work
            result.append({"key": spec.key, "label": spec.label, "primary": bool(spec.primary),
                           "geometry": rect_info(g.x, g.y, g.w, g.h), "work": rect_info(w.x, w.y, w.w, w.h),
                           "scale": float(spec.scale), "description": spec.description,
                           "page": {"id": page.id, "title": page.title} if page is not None else None})
        return result

    def _page_info(self, page) -> dict:
        desk = self.desk
        return {"id": page.id, "title": page.title, "monitor": page.monitor_key,
                "monitor_label": page.monitor_label, "shown_on": desk.monitor_of_page(page.id),
                "islands": len(page.islands)}

    # App ------------------------------------------------------------------------------------------------
    def c_app_info(self, _args):
        app, desk = self.app, self.desk
        services = {}
        for name, service in app.services.items():
            if name == "media" or service is None:
                continue
            services[name] = {"available": bool(service.property("available")),
                              "error": str(service.property("error") or "")}
        prefs = desk.preferences
        return {"name": "DeskIsle 桌屿", "version": __version__, "protocol": PROTOCOL_VERSION,
                "platform": sys.platform, "pid": os.getpid(), "demo": bool(app.demo), "data_dir": str(app.root),
                "monitors": len(desk.monitors()), "hidden": bool(desk.property("hidden")),
                "focus_mode": bool(desk.property("focusMode")),
                "agent_pipe": app.agent.full_name() if app.agent is not None else "",
                "custom_folder": str(app.custom.folder) if app.custom is not None else "",
                "web": app.webhost.status() if app.webhost is not None else {"preferred": "unavailable"},
                "wallpaper": {"mode": prefs.wallpaper_mode, "live": app.liveStatus()},
                "services": services}

    def c_app_activate(self, _args):
        desk = self.desk
        desk.set_hidden(False)
        desk.show_notice("桌屿正在运行", "双击桌面空白处可以隐藏 / 显示收纳岛，托盘图标里有更多选项。", "info", [], 3500)
        return {"hidden": False}

    def c_app_screenshot(self, args):
        app = self.app
        folder = Path(args.get("folder") or (Path(app.root) / "screenshots")).expanduser()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            fail("io", "cannot create {0}: {1}".format(folder, exc))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        windows = [("desk-" + key, window) for key, window in (app.layers.windows.items() if app.layers else [])]
        windows += [("pinned-" + uid[:8], window) for uid, window in (app.layers.pinned.items() if app.layers else [])]
        if app.settings_window is not None:
            windows.append(("settings", app.settings_window))
        paths = []
        for label, window in windows:
            try:
                image = window.grabWindow()
            except Exception:  # noqa: BLE001
                continue
            name = re.sub(r"[^A-Za-z0-9_-]+", "_", label)[:48] or "window"
            path = folder / "{0}-{1}.png".format(name, stamp)
            if not image.isNull() and image.save(str(path)):
                paths.append(str(path))
        return {"paths": paths, "note": "Web pages composed by WebView2 below the Qt layer are not included."}

    def c_app_quit(self, _args):
        def run():
            QTimer.singleShot(500, self.app.quit)
            return {"quitting": True}

        return Plan("退出桌屿？", "AI 助手请求退出桌屿。收纳岛会消失，桌面图标恢复显示；以后可以从开始菜单重新打开。",
                    "退出", run, "quit DeskIsle")

    def c_schema(self, _args):
        return {"protocol": PROTOCOL_VERSION, "version": __version__,
                "commands": [{"name": s["name"], "title": s["title"], "description": s["description"],
                              "category": s["category"], "destructive": s["destructive"],
                              "input_schema": input_schema(s)} for s in COMMANDS]}

    def c_confirm_status(self, args):
        record = self._confirms.get(args["id"])
        if record is None:
            return {"id": args["id"], "status": "unknown"}
        return {k: v for k, v in record.items() if k != "created"}

    # Desk -------------------------------------------------------------------------------------------------
    def c_desk_state(self, args):
        desk = self.desk
        include = bool(args.get("include_items"))
        pages = []
        for page in desk.state.pages:
            info = self._page_info(page)
            info["islands"] = [island_info(desk, page, s, include) for s in page.islands]
            pages.append(info)
        return {"hidden": bool(desk.property("hidden")), "focus_mode": bool(desk.property("focusMode")),
                "can_undo": bool(desk.arranger.can_undo()), "monitors": self._monitor_list(), "pages": pages,
                "loose_items": [item.path for item in desk.state.loose_items]}

    def c_desk_visibility(self, args):
        desk = self.desk
        action = args["action"]
        hidden = bool(desk.property("hidden"))
        desk.set_hidden(not hidden if action == "toggle" else action == "hide")
        return {"hidden": bool(desk.property("hidden"))}

    def c_desk_focus(self, args):
        desk = self.desk
        on = args.get("on")
        desk.set_focus_mode(not bool(desk.property("focusMode")) if on is None else bool(on))
        return {"focus_mode": bool(desk.property("focusMode"))}

    def c_desk_notice(self, args):
        timeout = args.get("timeout_ms")
        nid = self.desk.show_notice(args["title"][:80], (args.get("text") or "")[:600], args.get("kind") or "info",
                                    [], 5000 if timeout is None else max(0, int(timeout)))
        return {"id": nid}

    def c_desk_undo(self, _args):
        desk = self.desk
        if not desk.arranger.can_undo():
            return {"undone": False, "message": "nothing to undo"}
        return {"undone": bool(desk.arranger.undo())}

    def c_desk_arrange(self, args):
        key = self._key(args.get("monitor"))
        if not self.desk.arranger.arrange(key):
            fail("no_room", "not enough room to arrange the islands at their preferred sizes")
        return {"arranged": True, "monitor": key}

    # Monitors / presets ---------------------------------------------------------------------------------------
    def c_monitor_list(self, _args):
        return {"monitors": self._monitor_list()}

    def c_page_list(self, args):
        desk = self.desk
        key = self._key(args["monitor"]) if args.get("monitor") else ""
        pages = [self._page_info(p) for p in desk.state.pages if not key or p.monitor_key == key
                 or desk.monitor_of_page(p.id) == key]
        return {"pages": pages}

    def c_page_switch(self, args):
        desk = self.desk
        page = desk.state.page(args["page"])
        if page is None:
            fail("not_found", "no preset {0!r}; see page.list".format(args["page"]))
        if args.get("monitor"):
            key = self._key(args["monitor"])
        else:
            key = page.monitor_key if desk.spec_for(page.monitor_key) is not None else desk.primary_spec().key
        if not desk.switch_page(key, page.id):
            fail("conflict", "the preset is shown on another monitor; switch that monitor first")
        return {"monitor": key, "page": page.id}

    def c_page_create(self, args):
        desk = self.desk
        key = self._key(args.get("monitor"))
        source = args.get("duplicate_of") or ""
        if source and desk.state.page(source) is None:
            fail("not_found", "no preset {0!r} to duplicate".format(source))
        page = desk.new_page(key, (args.get("title") or "").strip()[:40], source)
        if page is None:
            fail("failed", "could not create the preset")
        return self._page_info(page)

    def c_page_rename(self, args):
        if self.desk.state.page(args["page"]) is None:
            fail("not_found", "no preset {0!r}".format(args["page"]))
        if not self.desk.rename_page(args["page"], args["title"]):
            fail("invalid_args", "empty title")
        return self._page_info(self.desk.state.page(args["page"]))

    def c_page_delete(self, args):
        desk = self.desk
        page = desk.state.page(args["page"])
        if page is None:
            fail("not_found", "no preset {0!r}".format(args["page"]))
        own = [p for p in desk.state.pages if p.monitor_key == page.monitor_key]
        if len(own) <= 1 and desk.spec_for(page.monitor_key) is not None:
            fail("last_preset", "every monitor keeps at least one preset")
        pid = page.id
        text = "AI 助手请求删除这个预设。其中的 {0} 个收纳岛会一起删除，图标回到桌面散放区，文件不受影响。".format(
            len(page.islands))
        return Plan("删除预设“{0}”？".format(page.title), text, "删除预设",
                    lambda: {"deleted": bool(desk.delete_page(pid))},
                    "delete preset {0!r} with {1} islands".format(page.title, len(page.islands)))

    # Islands ---------------------------------------------------------------------------------------------------
    def c_island_list(self, args):
        desk = self.desk
        key = self._key(args["monitor"]) if args.get("monitor") else ""
        result = []
        for page in desk.state.pages:
            if args.get("page") and page.id != args["page"]:
                continue
            if key and desk.monitor_of_page(page.id) != key and page.monitor_key != key:
                continue
            for s in page.islands:
                if args.get("kind") and s.kind != args["kind"]:
                    continue
                result.append(island_info(desk, page, s))
        return {"islands": result}

    def c_island_get(self, args):
        page, s = self._island(args["uid"])
        return island_info(self.desk, page, s, bool(args.get("include_items")))

    def c_island_create(self, args):
        from ..engine.controller import WIDGET_SIZES
        from ..engine.webhost import normalize_url

        desk = self.desk
        kind = args["kind"]
        folder = (args.get("folder") or "").strip()
        html = (args.get("html_path") or "").strip()
        url = (args.get("url") or "").strip()
        widget = (args.get("widget") or "").strip()
        if kind == "files" and folder and not os.path.isdir(folder):
            fail("not_found", "folder does not exist: {0}".format(folder))
        if kind == "web":
            if html:
                if not os.path.isfile(html):
                    fail("not_found", "file does not exist: {0}".format(html))
                if not html.lower().endswith((".html", ".htm")):
                    fail("invalid_args", "html_path must be an .html file")
                html = str(Path(html).resolve())
            elif url:
                url = normalize_url(url)
            else:
                fail("invalid_args", "web islands need url or html_path")
        if kind == "widget":
            if not widget:
                fail("invalid_args", "widget is required (clock | weather | media | todo | custom:<id>)")
            if widget.startswith("custom:"):
                info = self.app.custom.widget(widget) if self.app.custom is not None else None
                if info is None:
                    fail("not_found", "no custom widget {0!r}; see widget.types".format(widget))
                if info.get("error"):
                    fail("invalid_widget", info["error"])
                widget = "custom:" + info["id"]
            elif widget not in WIDGET_SIZES:
                fail("invalid_args", "unknown widget {0!r}".format(widget))
        key = self._key(args.get("monitor"))
        size = None
        if args.get("width") or args.get("height"):
            size = (int(args.get("width") or 360), int(args.get("height") or 260))
        position = None
        if args.get("x") is not None or args.get("y") is not None:
            work = desk.spec_for(key).work
            position = (int(args["x"]) if args.get("x") is not None else work.x,
                        int(args["y"]) if args.get("y") is not None else work.y)
        state = desk.add_island(kind, monitor_key=key, title=(args.get("title") or "").strip()[:60], folder=folder,
                                url=url, widget=widget, html_path=html, config=args.get("config") or None,
                                size=size, position=position)
        if state is None:
            fail("no_room", "no free space for the island on that monitor; collapse or shrink islands first")
        page, s = desk.find_island(state.id)
        return island_info(desk, page, s)

    def c_island_update(self, args):
        desk = self.desk
        uid = args["uid"]
        page, s = self._island(uid)
        if args.get("locked") is False:
            desk.island_action(uid, "lock", {"value": False})
        if args.get("title"):
            desk.island_action(uid, "rename", {"title": args["title"]})
        for key, action in (("collapsed", "collapse"), ("pinned", "pin"), ("capsule", "capsule"),
                            ("keep_visible", "keepVisible")):
            if args.get(key) is not None:
                desk.island_action(uid, action, {"value": bool(args[key])})
        if args.get("material"):
            desk.island_action(uid, "material", {"material": args["material"]})
        if args.get("icon_size") is not None:
            desk.island_action(uid, "iconSize", {"size": max(32, min(128, int(args["icon_size"])))})
        geometry = [args.get(k) for k in ("x", "y", "width", "height")]
        if any(v is not None for v in geometry):
            ok, why = desk.arranger.move_to(uid, *geometry)
            if not ok:
                fail("layout", why)
        if args.get("locked") is True:
            desk.island_action(uid, "lock", {"value": True})
        page, s = self._island(uid)
        return island_info(desk, page, s)

    def c_island_delete(self, args):
        desk = self.desk
        uid = args["uid"]
        _page, s = self._island(uid)
        count = sum(len(t.items) for t in s.tabs if not t.portal_path)
        if s.kind == "files":
            text = "AI 助手请求删除这个收纳岛。里面的 {0} 个图标会回到桌面散放区，文件不会被删除。".format(count)
        else:
            text = "AI 助手请求删除这个{0}。不会影响任何文件。".format("网页岛" if s.kind == "web" else "小组件")
        return Plan("删除“{0}”？".format(s.title), text, "删除", lambda: {"deleted": bool(desk.delete_island(uid))},
                    "delete island {0!r} ({1}, {2} items go back to the desktop)".format(s.title, s.kind, count))

    def c_island_action(self, args):
        desk = self.desk
        uid, name = args["uid"], args["name"]
        if name in ("delete", "closeTab"):
            fail("use_command", "use island.delete / island.tab_close: they ask the user first")
        if name not in ISLAND_ACTIONS:
            fail("unknown_action", "unknown action {0!r}; see the island.action description".format(name))
        page, s = self._island(uid)
        if name.startswith("web.") and s.kind != "web":
            fail("wrong_kind", "web actions need a web island")
        payload = dict(args.get("args") or {})
        payload.pop("confirmed", None)
        if name == "media" and payload.get("path") and not os.path.isfile(str(payload["path"])):
            fail("not_found", "media file does not exist")
        if name in ("portal", "portalOpen") and payload.get("path") and not os.path.isdir(str(payload["path"])):
            fail("not_found", "folder does not exist")
        desk.island_action(uid, name, payload)
        page, s = self._island(uid)
        return island_info(desk, page, s)

    def c_island_items(self, args):
        desk = self.desk
        page, s = self._island(args["uid"])
        if s.kind != "files":
            fail("wrong_kind", "only file islands have items")
        tab_id = args.get("tab") or s.active_tab_id
        tab = next((t for t in s.tabs if t.id == tab_id), None)
        if tab is None:
            fail("not_found", "no tab {0!r} in this island".format(tab_id))
        records = desk.records_for(s, tab)
        return {"tab": tab.id, "folder": tab.portal_path or "",
                "items": [{"path": r.path, "name": r.name, "folder": bool(r.is_dir), "exists": bool(r.available)}
                          for r in records]}

    def c_island_tab_close(self, args):
        desk = self.desk
        uid, tab_id = args["uid"], args["tab"]
        _page, s = self._island(uid)
        tab = next((t for t in s.tabs if t.id == tab_id), None)
        if tab is None:
            fail("not_found", "no tab {0!r} in this island".format(tab_id))
        if len(s.tabs) <= 1:
            fail("last_tab", "an island keeps at least one tab; delete the island instead")
        if tab.portal_path:
            text = "AI 助手请求关闭这个文件视图标签页，文件夹本身不受影响。"
        else:
            text = "AI 助手请求关闭这个标签页。其中的 {0} 个图标会并入其他标签页，文件不受影响。".format(len(tab.items))
        return Plan("关闭标签页“{0}”？".format(tab.title), text, "关闭",
                    lambda: {"closed": bool(desk.island_action(uid, "closeTab", {"id": tab_id}))},
                    "close tab {0!r} of {1!r}".format(tab.title, s.title))

    def c_island_locate(self, args):
        desk = self.desk
        uid = args["uid"]
        page, s = self._island(uid)
        key = desk.monitor_of_page(page.id)
        if not key:
            key = page.monitor_key if desk.spec_for(page.monitor_key) is not None else desk.primary_spec().key
            if not desk.switch_page(key, page.id):
                fail("conflict", "the preset cannot be shown right now")
        if bool(desk.property("hidden")):
            desk.set_hidden(False)
        if s.collapsed:
            desk.island_action(uid, "collapse", {"value": False})
        proxy = desk.proxy(uid)
        if proxy is not None:
            proxy.raise_()
            proxy.flash.emit("locate")
        return {"monitor": key, "page": page.id}

    # Items ------------------------------------------------------------------------------------------------------
    def _container_of_path(self, path: str) -> str:
        from ..engine.scene import norm_key

        key = norm_key(path)
        if any(norm_key(i.path) == key for i in self.desk.state.loose_items):
            return LOOSE
        for page in self.desk.state.pages:
            for island in page.islands:
                for tab in island.tabs:
                    if not tab.portal_path and any(norm_key(i.path) == key for i in tab.items):
                        return "island:{0}:{1}".format(island.id, tab.id)
        return ""

    def c_item_loose(self, _args):
        return {"items": [{"path": i.path, "name": i.title or os.path.basename(i.path.rstrip("\\/")),
                           "exists": os.path.exists(i.path)} for i in self.desk.state.loose_items]}

    def c_item_move(self, args):
        desk = self.desk
        paths = [str(p) for p in args["paths"] if p]
        if not paths:
            fail("invalid_args", "paths is empty")
        groups: dict[str, list[str]] = {}
        for path in paths:
            source = self._container_of_path(path)
            if not source and not os.path.exists(path):
                fail("not_found", "path does not exist: {0}".format(path))
            groups.setdefault(source, []).append(path)
        index = int(args["index"]) if args.get("index") is not None else -1
        target = args["to"]
        if target == LOOSE:
            for source, group in groups.items():
                desk.drop_to_loose(group, source, index)
            return {"moved": len(paths), "to": LOOSE}
        _page, s = self._island(target)
        if s.kind != "files":
            fail("wrong_kind", "items can only move into file islands")
        tab_id = args.get("tab") or s.active_tab_id
        tab = next((t for t in s.tabs if t.id == tab_id), None)
        if tab is None:
            fail("not_found", "no tab {0!r}".format(tab_id))
        if tab.portal_path:
            fail("file_view", "that tab is a live folder view; references cannot be added to it")
        for source, group in groups.items():
            desk.move_references(group, source, tab, index)
        return {"moved": len(paths), "to": "island:{0}:{1}".format(s.id, tab.id)}

    def c_item_open(self, args):
        path = args["path"]
        if not os.path.exists(path):
            fail("not_found", "path does not exist: {0}".format(path))
        self.desk.openItem(path)
        return {"opened": path}

    def c_item_reveal(self, args):
        path = args["path"]
        if not os.path.exists(path):
            fail("not_found", "path does not exist: {0}".format(path))
        self.desk.revealItem(path)
        return {"revealed": path}

    # Web --------------------------------------------------------------------------------------------------------
    def _web_island(self, uid: str):
        page, s = self._island(uid)
        if s.kind != "web":
            fail("wrong_kind", "island {0} is not a web island".format(uid))
        return page, s

    def c_web_navigate(self, args):
        from ..engine.webhost import normalize_url

        uid = args["uid"]
        self._web_island(uid)
        url = normalize_url(args["url"])
        if not url:
            fail("invalid_args", "empty url")
        self.desk.island_action(uid, "web.url", {"url": url})
        page, s = self._web_island(uid)
        return island_info(self.desk, page, s)

    def c_web_control(self, args):
        uid = args["uid"]
        self._web_island(uid)
        self.desk.island_action(uid, "web." + args["action"], {})
        page, s = self._web_island(uid)
        return island_info(self.desk, page, s)

    def c_web_status(self, _args):
        host = self.app.webhost
        status = host.status() if host is not None else {"preferred": "unavailable", "views": {}}
        titles = {}
        for page in self.desk.state.pages:
            for s in page.islands:
                if s.kind == "web" or s.widget.startswith("custom:"):
                    titles[s.id] = s.title
        status["islands"] = [{"uid": uid, "title": title, "mode": status.get("views", {}).get(uid, "not loaded")}
                             for uid, title in titles.items()]
        return status

    # Widgets ------------------------------------------------------------------------------------------------------
    def c_widget_types(self, _args):
        from ..engine.controller import WIDGET_SIZES, WIDGET_TITLES

        builtin = [{"id": wid, "name": WIDGET_TITLES.get(wid, wid), "size": list(size),
                    "config": WIDGET_CONFIG_DOCS.get(wid, {}), "builtin": True}
                   for wid, size in WIDGET_SIZES.items()]
        custom = []
        if self.app.custom is not None:
            for info in self.app.custom.widgets():
                custom.append({"id": "custom:" + info["id"], "name": info["name"], "type": info.get("type"),
                               "size": list(info.get("size") or []), "description": info.get("description", ""),
                               "network": bool(info.get("network")), "error": info.get("error", ""),
                               "path": info.get("path", ""), "builtin": False})
        return {"builtin": builtin, "custom": custom}

    def c_widget_config(self, args):
        uid = args["uid"]
        page, s = self._island(uid)
        if s.kind != "widget":
            fail("wrong_kind", "island {0} is not a widget".format(uid))
        values = dict(args["values"])
        if s.widget == "todo" and "items" in values:
            fail("invalid_args", "todo items are changed with todo.add / todo.toggle / todo.remove")
        self.desk.island_action(uid, "widgetConfig", values)
        page, s = self._island(uid)
        return island_info(self.desk, page, s)

    def c_todo_list(self, args):
        self._widget_island(args["uid"], "todo")
        return {"items": self._service("todo").list(args["uid"])}

    def _todo_item(self, uid: str, item_id: str) -> dict:
        item = next((i for i in self._service("todo").items(uid) if i.get("id") == item_id), None)
        if item is None:
            fail("not_found", "no todo item {0!r}; see todo.list".format(item_id))
        return item

    def c_todo_add(self, args):
        uid = args["uid"]
        self._widget_island(uid, "todo")
        item_id = self._service("todo").add(uid, args["text"])
        if not item_id:
            fail("invalid_args", "empty text")
        return {"item": self._todo_item(uid, item_id)}

    def c_todo_toggle(self, args):
        uid = args["uid"]
        self._widget_island(uid, "todo")
        self._todo_item(uid, args["id"])
        self._service("todo").toggle(uid, args["id"])
        return {"item": self._todo_item(uid, args["id"])}

    def c_todo_remove(self, args):
        uid, item_id = args["uid"], args["id"]
        self._widget_island(uid, "todo")
        item = self._todo_item(uid, item_id)
        service = self._service("todo")

        def run():
            service.remove(uid, item_id)
            return {"removed": item_id}

        return Plan("删除待办“{0}”？".format(item.get("text", "")[:30]), "AI 助手请求删除这条待办事项。", "删除", run,
                    "delete todo item {0!r}".format(item.get("text", "")))

    def c_media_status(self, _args):
        return self._service("player").snapshot()

    def c_media_control(self, args):
        player = self._service("player")
        action = args["action"]
        if action == "seek":
            if args.get("position") is None:
                fail("invalid_args", "seek needs position (seconds)")
            player.seek(float(args["position"]))
        else:
            {"play_pause": player.playPause, "next": player.next, "previous": player.previous}[action]()
        return {"done": action}

    def c_weather_status(self, _args):
        weather = self._service("weather")
        return {"data": weather.property("data"), "status": weather.property("status"),
                "loading": bool(weather.property("loading")), "location_note": weather.property("locationNote")}

    def c_weather_refresh(self, _args):
        self._service("weather").refresh(True)
        return {"refreshing": True}

    def c_clock_info(self, _args):
        now = datetime.now().astimezone()
        prefs = self.desk.preferences
        clock = self.app.services.get("clock")
        lunar = {}
        if clock is not None and bool(clock.property("lunarAvailable")):
            try:
                lunar = clock.lunarFor(now.year, now.month, now.day)
            except Exception:  # noqa: BLE001
                lunar = {}
        return {"iso": now.isoformat(timespec="seconds"), "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M:%S"), "weekday": "一二三四五六日"[now.weekday()],
                "timezone": str(now.tzinfo), "h24": bool(prefs.clock_24h), "lunar": lunar}

    def _agent_search(self):
        if self._search is None:
            from ..services.everything import SearchService

            self._search = SearchService(self.desk, demo=bool(self.app.demo), parent=self)
        return self._search

    def c_search_query(self, args):
        text = args["text"].strip()
        if not text:
            fail("invalid_args", "empty text")
        limit = max(1, min(200, int(args.get("limit") or 20)))
        service = self._agent_search()
        service.search(text)
        later = Later()
        started = time.monotonic()

        def clean(result: dict) -> dict:
            return {k: v for k, v in result.items() if k not in ("icon", "glyph", "section", "score")}

        def poll() -> None:
            done = service.idle()
            if not done and (time.monotonic() - started) * 1000 < SEARCH_WAIT_MS:
                QTimer.singleShot(50, poll)
                return
            snap = service.snapshot()
            later.finish(True, {"query": text, "engine": snap["engine"], "status": snap["status"],
                                "complete": bool(done), "desk": [clean(r) for r in snap["desk"]],
                                "files": [clean(r) for r in snap["files"][:limit]]})

        QTimer.singleShot(150, poll)
        return later

    # Preferences / theme / custom ----------------------------------------------------------------------------------
    def c_prefs_get(self, _args):
        return {"prefs": self.desk.preferences.to_dict()}

    def c_prefs_set(self, args):
        values = dict(args["values"])
        if values.get("agent_enabled") is False:
            fail("refused", "the agent interface cannot be switched off by an agent; the user can do it in 设置")
        result = self.desk.set_preferences(values)
        unknown = list(result.get("unknown") or [])
        return {"applied": [k for k in values if k not in unknown], "unknown": unknown,
                "prefs": self.desk.preferences.to_dict()}

    def c_theme_get(self, _args):
        from ..custom import theme_snapshot

        theme = self.app.theme
        data = theme_snapshot(theme)
        data["tokens"] = dict(theme.property("tokens") or {})
        data["material"] = str(theme.property("material") or "")
        data["wallLuminance"] = float(theme.property("wallLuminance") or 0)
        data["note"] = "The accent colour always comes from the wallpaper and cannot be set."
        return data

    def c_theme_tokens(self, args):
        custom = self.app.custom
        if custom is None:
            fail("unavailable", "custom folder unavailable")
        tokens = dict(args["tokens"])
        unknown = [k for k in tokens if k not in TOKEN_KEYS]
        if unknown:
            fail("invalid_args", "unknown token(s) {0}; allowed: {1}".format(", ".join(unknown), ", ".join(TOKEN_KEYS)))
        bad = [k for k, v in tokens.items() if isinstance(v, bool) or not isinstance(v, (int, float))]
        if bad:
            fail("invalid_args", "token values must be numbers: {0}".format(", ".join(bad)))
        path = Path(custom.folder) / "theme.json"
        current = {}
        if not args.get("replace") and path.is_file():
            try:
                current = json.loads(path.read_text(encoding="utf-8"))
                current = current if isinstance(current, dict) else {}
            except (OSError, ValueError):
                current = {}
        current.update(tokens)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            fail("io", str(exc))
        custom.reload()
        return {"path": str(path), "tokens": current,
                "problems": [p for p in custom.problems if p.startswith("theme.json")]}

    def c_custom_status(self, _args):
        if self.app.custom is None:
            fail("unavailable", "custom folder unavailable")
        return self.app.custom.status()

    def _widget_dir(self, wid: str, must_exist: bool = True) -> Path:
        from ..custom import WIDGET_ID

        custom = self.app.custom
        if custom is None:
            fail("unavailable", "custom folder unavailable")
        wid = wid[7:] if wid.startswith("custom:") else wid
        if not WIDGET_ID.match(wid or ""):
            fail("invalid_args", "widget id may only use letters, digits, '.', '_' and '-' (max 48)")
        folder = Path(custom.folder) / "widgets" / wid
        if must_exist and not folder.is_dir():
            fail("not_found", "no custom widget {0!r}; see custom.status".format(wid))
        return folder

    def _widget_file(self, folder: Path, name: str) -> Path:
        name = (name or "").replace("\\", "/").strip()
        if not name or not SAFE_FILE.match(name) or name.startswith("/") or ".." in name.split("/"):
            fail("invalid_args", "file must be a relative name inside the widget folder")
        path = (folder / name).resolve()
        if folder.resolve() not in path.parents:
            fail("invalid_args", "file must stay inside the widget folder")
        return path

    def c_custom_widget_create(self, args):
        from .. import custom as custom_module

        folder = self._widget_dir(args["id"], must_exist=False)
        if folder.exists():
            fail("exists", "widget {0!r} already exists; use custom.widget_write".format(folder.name))
        kind = args.get("type") or "html"
        size = args.get("size") or [320, 220]
        if len(size) != 2:
            fail("invalid_args", "size is [width, height]")
        size = [max(custom_module.MIN_SIZE, min(custom_module.MAX_SIZE, int(v))) for v in size]
        entry = "index.html" if kind == "html" else "Widget.qml"
        content = args.get("content")
        if content is None:
            content = custom_module.HELLO_HTML if kind == "html" else custom_module.QML_SAMPLE
        if len(content.encode("utf-8")) > MAX_WIDGET_FILE:
            fail("too_large", "entry file is larger than 2 MB")
        manifest = {"name": (args.get("name") or folder.name)[:40], "type": kind, "entry": entry, "size": size,
                    "description": (args.get("description") or "")[:200], "version": "1.0"}
        if kind == "html":
            manifest["network"] = bool(args.get("network"))
        try:
            folder.mkdir(parents=True)
            (folder / "widget.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                                encoding="utf-8")
            (folder / entry).write_text(content, encoding="utf-8")
        except OSError as exc:
            fail("io", str(exc))
        custom = self.app.custom
        custom.reload()
        info = custom.widget(folder.name) or {}
        result = {"widget": "custom:" + folder.name, "path": str(folder), "error": info.get("error", "")}
        if args.get("add_to_desk") and not info.get("error"):
            state = self.desk.add_island("widget", widget="custom:" + folder.name, title=manifest["name"],
                                         size=tuple(size))
            result["island"] = state.id if state is not None else ""
        return result

    def c_custom_widget_write(self, args):
        folder = self._widget_dir(args["id"])
        path = self._widget_file(folder, args["file"])
        content = args["content"]
        if len(content.encode("utf-8")) > MAX_WIDGET_FILE:
            fail("too_large", "file is larger than 2 MB")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as exc:
            fail("io", str(exc))
        self.app.custom.reload()
        info = self.app.custom.widget(folder.name) or {}
        return {"path": str(path), "bytes": len(content.encode("utf-8")), "error": info.get("error", "")}

    def c_custom_widget_read(self, args):
        folder = self._widget_dir(args["id"])
        name = args.get("file")
        if not name:
            info = self.app.custom.widget(folder.name) or {}
            name = info.get("entry") or "index.html"
        path = self._widget_file(folder, name)
        if not path.is_file():
            fail("not_found", "no file {0!r}; files: {1}".format(name, ", ".join(
                sorted(str(p.relative_to(folder)).replace("\\", "/") for p in folder.rglob("*") if p.is_file()))))
        try:
            data = path.read_bytes()
        except OSError as exc:
            fail("io", str(exc))
        if len(data) > MAX_WIDGET_FILE:
            fail("too_large", "file is larger than 2 MB")
        return {"path": str(path), "content": data.decode("utf-8", errors="replace")}

    def c_custom_widget_delete(self, args):
        folder = self._widget_dir(args["id"])
        wid = folder.name
        desk = self.desk
        islands = [s.id for p in desk.state.pages for s in p.islands if s.widget == "custom:" + wid]

        def run():
            for uid in islands:
                desk.delete_island(uid)
            if not self.app.custom.remove_widget_files(wid):
                fail("io", "could not delete {0}".format(folder))
            return {"deleted": wid, "islands_removed": len(islands)}

        text = "AI 助手请求删除自制小组件文件夹“{0}”{1}。此操作会删除文件夹里的文件。".format(
            wid, "以及显示它的 {0} 个小组件".format(len(islands)) if islands else "")
        return Plan("删除小组件“{0}”？".format(wid), text, "删除", run,
                    "delete folder {0} and {1} islands".format(folder, len(islands)))

    # Layout files / snapshots ----------------------------------------------------------------------------------------
    def c_snapshot_list(self, _args):
        return {"snapshots": self.desk.snapshots()}

    def c_snapshot_save(self, args):
        path = self.desk.save_snapshot((args.get("name") or "").strip()[:60])
        return {"path": path}

    def c_snapshot_restore(self, args):
        desk = self.desk
        path = args["path"]
        known = {os.path.normcase(os.path.abspath(s["path"])): s for s in desk.snapshots()}
        snap = known.get(os.path.normcase(os.path.abspath(path)))
        if snap is None:
            fail("not_found", "not a snapshot of this desk; see snapshot.list")
        return Plan("恢复布局快照“{0}”？".format(snap["name"]),
                    "AI 助手请求用这个快照（{0}）替换当前布局。当前布局会先自动备份为快照。".format(snap["time"]),
                    "恢复", lambda: {"restored": bool(desk.restore_snapshot(snap["path"]))},
                    "replace the layout with snapshot {0!r}".format(snap["name"]))

    def c_layout_export(self, args):
        path = Path(args["path"]).expanduser()
        if path.suffix.lower() != ".json":
            fail("invalid_args", "the file name must end with .json")
        if path.exists():
            fail("exists", "{0} already exists; choose a new file name".format(path))
        self.desk.arranger.sync_norms()
        try:
            written = self.desk.store.export_state(self.desk.state, path)
        except Exception as exc:  # noqa: BLE001
            fail("io", str(exc))
        return {"path": str(written)}

    def c_layout_import(self, args):
        desk = self.desk
        path = Path(args["path"]).expanduser()
        if not path.is_file():
            fail("not_found", "no file {0}".format(path))
        try:
            state = desk.store.import_state(path, persist=False)
        except Exception as exc:  # noqa: BLE001
            fail("invalid_file", str(exc))
        islands = sum(len(p.islands) for p in state.pages)

        def run():
            desk.store.save_snapshot(desk.state, "导入前自动备份")
            desk.replace_state(state)
            desk.show_notice("已导入布局", path.name)
            return {"imported": str(path), "pages": len(state.pages), "islands": islands}

        return Plan("导入布局“{0}”？".format(path.name),
                    "AI 助手请求用这个文件替换当前布局（{0} 个预设、{1} 个收纳岛）。当前布局会先自动备份为快照。".format(
                        len(state.pages), islands), "导入", run,
                    "replace the layout with {0} ({1} presets, {2} islands)".format(path, len(state.pages), islands))

    def c_rules_list(self, _args):
        return {"rules": [rule.to_dict() if hasattr(rule, "to_dict") else dict(vars(rule))
                          for rule in self.desk.state.rules]}

    def c_rules_apply(self, _args):
        return {"moved": int(self.desk.apply_rules_now())}


__all__ = ["AgentError", "Commands", "Later", "Plan", "island_info"]

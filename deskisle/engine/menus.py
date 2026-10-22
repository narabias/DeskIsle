"""Context menus as data (rendered by GlassMenu.qml) and the action dispatcher.

Menu entries: ``{"id", "text", "icon", "checked", "enabled", "danger",
"shortcut", "children", "separator"}``.  Selecting an entry calls
``Desk.menuAction(context, target, id, extra)`` -> :func:`dispatch`.
"""

from __future__ import annotations

import os

from .desk_items import LOOSE


def item(id_: str, text: str, icon: str = "", *, checked=None, enabled: bool = True, danger: bool = False,
         shortcut: str = "", children=None) -> dict:
    entry = {"id": id_, "text": text, "icon": icon, "enabled": bool(enabled), "danger": bool(danger),
             "shortcut": shortcut}
    if checked is not None:
        entry["checked"] = bool(checked)
    if children is not None:
        entry["children"] = children
    return entry


SEP = {"separator": True}


def _widget_entries(desk) -> list:
    entries = [item("new.widget.clock", "时钟", "clock"), item("new.widget.weather", "天气", "cloud"),
               item("new.widget.media", "正在播放", "music"), item("new.widget.todo", "待办", "checklist")]
    custom = getattr(desk, "custom", None)
    if custom is not None:
        widgets = custom.widgets()
        if widgets:
            entries.append(SEP)
            entries.extend(item("new.widget.custom:" + w["id"], w["name"], "puzzle") for w in widgets)
    return entries


def new_entries(desk) -> list:
    return [
        item("new.files", "收纳岛", "box"),
        item("new.portal", "文件视窗…", "folder"),
        item("new.web", "网页…", "world"),
        item("new.html", "本地 HTML 动画…", "code"),
        item("new.widget", "小组件", "layout", children=_widget_entries(desk)),
    ]


def build(desk, context: str, target: str = "", extra: dict | None = None) -> list:
    extra = extra or {}
    if context == "desktop":
        return desktop_menu(desk, target)
    if context == "island":
        return island_menu(desk, target)
    if context == "item":
        return item_menu(desk, target, list(extra.get("paths") or []), bool(extra.get("available", True)))
    if context == "tray":
        return tray_menu(desk)
    if context == "preset":
        return preset_menu(desk, target)
    if context == "new":
        return new_entries(desk)
    return []


def desktop_menu(desk, key: str) -> list:
    pages = [item("page.switch:" + p["id"], p["title"] + ("  · " + p["label"] if p["label"] else ""),
                  "layout-board", checked=p["current"]) for p in desk.pages_info(key)]
    pages += [SEP, item("page.new", "新建预设", "plus"), item("page.duplicate", "复制当前预设", "copy")]
    snapshots = [item("snapshot.restore:" + s["path"], "{0}  {1}".format(s["name"], s["time"]), "history")
                 for s in desk.snapshots()[:12]]
    return [
        item("new", "新建", "plus", children=new_entries(desk)),
        SEP,
        item("view.hide", "恢复显示" if desk.hidden else "清屏", "eye" if desk.hidden else "eye-off",
             shortcut="Ctrl+Alt+H"),
        item("view.focus", "退出聚焦层" if desk.focusMode else "聚焦层", "focus", shortcut="Ctrl+Alt+Space"),
        item("layout.arrange", "自动排布", "layout-grid"),
        item("layout.undo", "撤销排布", "undo", enabled=desk.canUndo, shortcut="Ctrl+Alt+Z"),
        SEP,
        item("pages", "预设", "layout-board", children=pages),
        item("scan", "扫描桌面新项目", "refresh"),
        item("rules.apply", "立即按规则归流", "filter"),
        item("snapshots", "布局快照", "history", children=[
            item("snapshot.save", "保存当前布局快照", "device-floppy"),
            item("snapshot.list", "恢复快照", "history", children=snapshots or [item("", "暂无快照", enabled=False)]),
            SEP,
            item("layout.export", "导出布局…", "upload"),
            item("layout.import", "导入布局…", "download"),
        ]),
        SEP,
        item("search", "搜索", "search", shortcut="Ctrl+Alt+F"),
        item("settings", "设置", "settings"),
    ]


def island_menu(desk, uid: str) -> list:
    proxy = desk.proxy(uid)
    _page, s = desk.find_island(uid)
    if s is None:
        return []
    entries: list = []
    if s.kind == "files":
        tab = desk.find_tab(uid)
        portal = bool(tab and tab.portal_path)
        mode = tab.sort_mode if tab is not None else "manual"
        sizes = [item("island.iconSize:{0}".format(v), label, checked=s.icon_size == v)
                 for v, label in ((40, "小"), (56, "中"), (72, "大"))]
        sizes += [SEP, item("island.iconBigger", "放大", "zoom-in", shortcut="Ctrl+滚轮"),
                  item("island.iconSmaller", "缩小", "zoom-out")]
        sort = [item("island.sort:" + m, label, checked=mode == m)
                for m, label in (("manual", "手动"), ("name", "名称"), ("type", "类型"), ("modified", "修改时间"))]
        sort += [SEP, item("island.descending", "降序", checked=bool(tab and tab.sort_descending),
                           enabled=mode != "manual")]
        if not portal:
            sort.append(item("island.autoSort", "按名称重新排列一次", "sort-ascending"))
        entries += [
            item("island.rename", "重命名", "pencil"),
            item("island.addTab", "添加标签页", "plus"),
            item("island.portalMenu", "文件视窗", "folder", children=[
                item("island.portalSet", "显示文件夹…" if not portal else "更换文件夹…", "folder"),
                item("island.portalHome", "回到根目录", "home", enabled=portal and bool(proxy and proxy.portalCanUp)),
                item("island.portalClear", "改回普通收纳岛", "box", enabled=portal),
            ]),
            item("island.icons", "图标大小", "photo", children=sizes),
            item("island.sortMenu", "排序", "sort-ascending", children=sort),
        ]
    elif s.kind == "web":
        refresh = [item("island.webRefresh:{0}".format(m), "关闭" if m == 0 else "每 {0} 分钟".format(m),
                        checked=s.web_refresh_minutes == m) for m in (0, 1, 5, 15, 30, 60)]
        zoom = [item("island.webZoom:{0}".format(z), "{0}%".format(int(z * 100)), checked=abs(s.web_zoom - z) < .01)
                for z in (0.5, 0.75, 0.9, 1.0, 1.1, 1.25, 1.5, 2.0)]
        entries += [
            item("island.rename", "重命名", "pencil"),
            item("island.webUrl", "更改网址…", "link"),
            item("island.webHome", "回到固定网址", "home"),
            item("island.webReload", "重新加载", "refresh"),
            item("island.webExternal", "在浏览器中打开", "external-link"),
            item("island.webToolbar", "导航栏", "layout-navbar", checked=s.web_toolbar),
            item("island.webRefreshMenu", "自动刷新", "clock", children=refresh),
            item("island.webZoomMenu", "页面缩放", "zoom-in", children=zoom),
        ]
        if s.web_url.startswith("file:"):
            entries.append(item("island.webNetwork", "允许本地页面联网", "world", checked=s.html_allow_network))
    else:
        entries += [item("island.rename", "重命名", "pencil")]
        entries += widget_entries(desk, s)
    materials = [item("island.material:", "跟随全局", checked=not s.material)]
    materials += [item("island.material:" + m, label, checked=s.material == m)
                  for m, label in (("liquid", "液态玻璃"), ("frosted", "毛玻璃"), ("clear", "清透"))]
    entries += [
        item("island.materialMenu", "材质", "droplet", children=materials),
        item("island.mediaMenu", "背景媒体", "photo", children=[
            item("island.mediaPick", "选择图片 / GIF / 视频…", "photo"),
            item("island.mediaClear", "清除背景媒体", "x", enabled=bool(s.media_path)),
        ]),
        SEP,
        item("island.capsule", "胶囊模式（悬停展开）", "pill", checked=s.capsule),
        item("island.lock", "锁定位置", "lock", checked=s.locked),
        item("island.pin", "窗口置顶", "pin", checked=s.pin_on_top),
        item("island.keepVisible", "清屏时保持显示", "eye", checked=s.exclude_from_hide),
        item("island.collapse", "展开" if s.collapsed else "收拢", "chevron-up" if not s.collapsed else "chevron-down"),
        SEP,
        item("island.delete", "删除", "trash", danger=True),
    ]
    return entries


def widget_entries(desk, s) -> list:
    cfg = s.widget_config or {}
    prefs = desk.preferences
    if s.widget == "clock":
        style = cfg.get("style", prefs.clock_style)
        seconds = [] if style == "split" else [  # flip cards have no seconds
            item("widget.clockSeconds", "显示秒", checked=bool(cfg.get("seconds", prefs.clock_seconds)))]
        return [
            item("widget.clock24", "24 小时制", "clock", checked=bool(cfg.get("h24", prefs.clock_24h))),
            *seconds,
            item("widget.clockLunar", "显示农历与节气", checked=bool(cfg.get("lunar", prefs.clock_lunar))),
            item("widget.clockStyle", "样式", "palette", children=[
                item("widget.clockStyle:" + k, label, checked=style == k)
                for k, label in (("digital", "数字"), ("analog", "指针"), ("split", "翻页"))]),
        ]
    if s.widget == "weather":
        return [item("widget.weatherRefresh", "立即刷新", "refresh"),
                item("widget.weatherSettings", "位置与单位…", "map-pin")]
    if s.widget == "todo":
        return [item("widget.todoClear", "清除已完成", "checklist")]
    if s.widget == "media":
        return [item("widget.mediaOpen", "打开播放器", "music")]
    return [item("widget.reload", "重新加载小组件", "refresh")]


def item_menu(desk, container: str, paths: list, available: bool = True) -> list:
    kind, island_id, _tab = desk.parse_container(container)
    in_island = kind == "island"
    tab = desk.find_tab(island_id) if in_island else None
    portal = bool(tab and tab.portal_path)
    single = len(paths) == 1
    entries = [
        item("item.open", "打开" if single else "打开 {0} 项".format(len(paths)), "external-link", enabled=available),
        item("item.reveal", "在资源管理器中显示", "folder", enabled=single),
        item("item.copy", "复制路径", "copy"),
    ]
    if desk.isWindows:
        entries.append(item("item.shell", "更多（Windows 菜单）…", "dots"))
    if in_island and not portal:
        entries += [SEP, item("item.unref", "从收纳岛移出（不删除文件）", "arrow-back-up")]
    if not available:
        entries.append(item("item.prune", "移除失效引用", "unlink", danger=True))
    return entries


def tray_menu(desk) -> list:
    return [
        item("view.hide", "恢复显示" if desk.hidden else "清屏", "eye"),
        item("view.focus", "聚焦层", "focus"),
        item("layout.arrangeAll", "全部归位", "layout-grid"),
        item("new", "新建", "plus", children=new_entries(desk)),
        SEP,
        item("settings", "设置", "settings"),
        item("update.check", "检查更新", "download"),
        SEP,
        item("quit", "退出桌屿", "power", danger=True),
    ]


def preset_menu(desk, page_id: str) -> list:
    return [
        item("page.rename:" + page_id, "重命名", "pencil"),
        item("page.duplicate:" + page_id, "复制", "copy"),
        item("page.delete:" + page_id, "删除", "trash", danger=True),
    ]


# --------------------------------------------------------------------------------------
def _key(desk, args: dict) -> str:
    key = str(args.get("monitor") or "")
    if args.get("context") == "desktop" and args.get("target"):
        key = str(args["target"])
    if not key or desk.spec_for(key) is None:
        key = desk._monitor_under_cursor() or desk.primary_spec().key
    return key


def dispatch(desk, action: str, args: dict) -> None:  # noqa: C901 - flat dispatcher
    action = str(action or "")
    name, _sep, param = action.partition(":")
    target = str(args.get("target") or "")
    if name.startswith("island.") or name.startswith("widget."):
        return _island(desk, name, param, target, args)
    if name.startswith("item."):
        return _items(desk, name, target, list(args.get("paths") or []))
    if name == "new":
        desk.togglePanel("new", _key(desk, args))
    elif name == "new.files":
        desk.add_island("files", monitor_key=_key(desk, args))
    elif name == "new.portal":
        folder = desk.pickFolder()
        if folder:
            desk.add_island("files", monitor_key=_key(desk, args), folder=folder)
    elif name == "new.web":
        desk.togglePanel("new:web", _key(desk, args))
    elif name == "new.webUrl":
        url = str(args.get("url") or "").strip()
        if url:
            desk.add_island("web", monitor_key=_key(desk, args), url=url, title=str(args.get("title") or ""))
            desk.closePanel()
    elif name == "new.html":
        path = desk.pickFile("选择 HTML 文件", "HTML (*.html *.htm)")
        if path:
            desk.add_island("web", monitor_key=_key(desk, args), html_path=path,
                            title=os.path.splitext(os.path.basename(path))[0])
    elif name.startswith("new.widget"):
        widget = name[len("new.widget."):] if name != "new.widget" else "clock"
        if widget == "custom":
            widget = "custom:" + param
        desk.add_island("widget", monitor_key=_key(desk, args), widget=widget,
                        title=desk.custom.widget_name(param) if widget.startswith("custom:") and getattr(
                            desk, "custom", None) else "")
    elif name == "view.hide":
        desk.toggleHidden()
    elif name == "view.focus":
        desk.toggleFocus()
    elif name == "layout.arrange":
        desk.arrange(_key(desk, args))
    elif name == "layout.arrangeAll":
        desk.arrange("")
    elif name == "layout.undo":
        desk.undo()
    elif name == "page.switch":
        key = _key(desk, args)
        if not desk.switch_page(key, param):
            desk.show_notice("无法切换", "这个预设正显示在另一台显示器上。", "warning")
    elif name == "page.new":
        desk.new_page(_key(desk, args))
    elif name == "page.duplicate":
        key = _key(desk, args)
        desk.new_page(key, duplicate_of=param or desk.state.current_pages.get(key, ""))
    elif name == "page.rename":
        if args.get("title"):
            desk.rename_page(param, str(args["title"]))
        else:
            desk.openPanel("presets", _key(desk, args), "rename:" + param)
    elif name == "page.delete":
        desk.ask_delete_page(param)
    elif name == "scan":
        count = desk.import_new_desktop_items(initial=True)
        desk.show_notice("扫描完成", "发现 {0} 个新项目。".format(count) if count else "没有发现新的桌面项目。")
    elif name == "rules.apply":
        moved = desk.apply_rules_now()
        desk.show_notice("归流规则", "已归流 {0} 个散放项目。".format(moved) if moved else "没有符合规则的散放项目。")
    elif name == "snapshot.save":
        desk.save_snapshot()
        desk.show_notice("已保存布局快照", "可在右键菜单“布局快照”中恢复。")
    elif name == "snapshot.restore":
        desk.confirm("恢复布局快照？", "当前布局会先自动备份。", "恢复",
                     lambda p=param: desk.restore_snapshot(p), danger=False)
    elif name == "snapshot.delete":
        label = next((s["name"] + "  " + s["time"] for s in desk.snapshots() if s["path"] == param),
                     os.path.basename(param))
        desk.confirm("删除布局快照？", label + "\n删除后无法恢复。", "删除",
                     lambda p=param: desk.delete_snapshot(p), danger=True)
    elif name in ("todo.done", "todo.snooze"):
        uid, _slash, item_id = param.partition("/")
        todo = getattr(desk, "services", {}).get("todo")
        if todo is not None and hasattr(todo, "complete"):
            (todo.complete if name == "todo.done" else todo.snooze)(uid, item_id)
    elif name == "layout.export":
        export_layout(desk)
    elif name == "layout.import":
        import_layout(desk)
    elif name == "search":
        desk.togglePanel("search", desk.primary_spec().key)
    elif name == "settings":
        desk.openSettings(param)
    elif name == "update.check":
        desk.openSettings("about")
        updater = getattr(desk, "updater", None)
        if updater is not None:
            updater.check(manual=True)
    elif name == "quit":
        desk.requestQuit()
    elif name == "noop" or not name:
        return None
    else:
        # Notice buttons such as "open-log" / "update-open" are handled by the application object.
        app = getattr(desk, "app", None)
        handler = getattr(app, "noticeAction", None) if app is not None else None
        if handler is not None:
            handler(action)
    return None


def _island(desk, name: str, param: str, uid: str, args: dict) -> None:
    proxy = desk.proxy(uid)
    _page, s = desk.find_island(uid)
    if s is None:
        return
    act = desk.island_action
    simple = {"island.capsule": "capsule", "island.lock": "lock", "island.pin": "pin",
              "island.keepVisible": "keepVisible", "island.collapse": "collapse", "island.delete": "delete",
              "island.webHome": "web.home", "island.webReload": "web.reload", "island.webExternal": "web.external",
              "island.webToolbar": "web.toolbar", "island.webNetwork": "web.network",
              "island.portalHome": "portalHome"}
    if name in simple:
        act(uid, simple[name], {})
    elif name in ("island.rename", "island.webUrl", "island.addTab"):
        if proxy is not None:
            proxy.flash.emit(name.split(".")[1])
    elif name == "island.iconSize":
        act(uid, "iconSize", {"size": int(param or 48)})
    elif name == "island.iconBigger":
        act(uid, "iconSize", {"delta": 1})
    elif name == "island.iconSmaller":
        act(uid, "iconSize", {"delta": -1})
    elif name == "island.sort":
        act(uid, "sort", {"mode": param, "descending": False})
    elif name == "island.descending":
        tab = desk.find_tab(uid)
        act(uid, "sort", {"descending": not (tab.sort_descending if tab else False)})
    elif name == "island.autoSort":
        act(uid, "autoSort", {"mode": "name"})
    elif name == "island.portalSet":
        folder = desk.pickFolder()
        if folder:
            act(uid, "portal", {"path": folder})
    elif name == "island.portalClear":
        act(uid, "portal", {"path": ""})
    elif name == "island.material":
        act(uid, "material", {"material": param})
    elif name == "island.mediaPick":
        path = desk.pickFile("选择背景媒体", "媒体 (*.png *.jpg *.jpeg *.gif *.webp *.bmp *.mp4 *.webm *.mov *.mkv)")
        if path:
            act(uid, "media", {"path": path})
    elif name == "island.mediaClear":
        act(uid, "media", {"path": ""})
    elif name == "island.webRefresh":
        act(uid, "web.refresh", {"minutes": int(param or 0)})
    elif name == "island.webZoom":
        act(uid, "web.zoom", {"zoom": float(param or 1.0)})
    elif name.startswith("widget."):
        cfg = s.widget_config or {}
        prefs = desk.preferences
        if name == "widget.clock24":
            act(uid, "widgetConfig", {"h24": not bool(cfg.get("h24", prefs.clock_24h))})
        elif name == "widget.clockSeconds":
            act(uid, "widgetConfig", {"seconds": not bool(cfg.get("seconds", prefs.clock_seconds))})
        elif name == "widget.clockLunar":
            act(uid, "widgetConfig", {"lunar": not bool(cfg.get("lunar", prefs.clock_lunar))})
        elif name == "widget.clockStyle" and param:
            act(uid, "widgetConfig", {"style": param})
        elif name == "widget.weatherRefresh":
            service = getattr(desk, "services", {}).get("weather") if hasattr(desk, "services") else None
            if service is not None:
                service.refresh(force=True)
        elif name == "widget.weatherSettings":
            desk.openSettings("widgets:自动定位")
        elif name == "widget.todoClear":
            items = [t for t in cfg.get("items", []) if not t.get("done")]
            act(uid, "widgetConfig", {"items": items})
        elif name == "widget.mediaOpen":
            desk.togglePanel("media", proxy.monitor_key if proxy is not None else "")
        elif name == "widget.reload":
            if proxy is not None:
                proxy.flash.emit("reload")


def _items(desk, name: str, container: str, paths: list) -> None:
    if name == "item.open":
        for path in paths[:12]:
            desk.openItem(path)
    elif name == "item.reveal" and paths:
        desk.revealItem(paths[0])
    elif name == "item.copy":
        desk.copyPaths(paths)
    elif name == "item.shell":
        desk.shellMenu(paths)
    elif name == "item.unref":
        desk.remove_references(container, paths)
    elif name == "item.prune":
        desk.remove_missing(container if container != LOOSE else "loose")


def export_layout(desk) -> None:
    from PySide6.QtWidgets import QFileDialog

    path, _f = QFileDialog.getSaveFileName(None, "导出布局", "DeskIsle-layout.json", "布局文件 (*.json)")
    if not path:
        return
    desk.arranger.sync_norms()
    try:
        desk.store.export_state(desk.state, path)
        desk.show_notice("已导出布局", os.path.basename(path))
    except (OSError, RuntimeError) as exc:
        desk.show_notice("导出失败", str(exc), "warning")


def import_layout(desk) -> None:
    from PySide6.QtWidgets import QFileDialog

    path, _f = QFileDialog.getOpenFileName(None, "导入布局", "", "布局文件 (*.json)")
    if not path:
        return
    try:
        state = desk.store.import_state(path, persist=False)
    except (OSError, RuntimeError, ValueError) as exc:
        desk.show_notice("导入失败", str(exc), "warning")
        return

    def apply() -> None:
        desk.save_snapshot("导入前自动备份")
        desk.replace_state(state)

    desk.confirm("替换当前布局？", "当前布局会自动备份，原文件不会移动或删除。", "导入", apply, danger=False)


__all__ = ["build", "dispatch", "item"]

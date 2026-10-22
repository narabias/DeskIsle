"""Command catalogue shared by the pipe server, the CLI and the MCP bridge.

Pure Python on purpose: ``deskisle-cli`` and ``--mcp`` list the commands
without importing Qt.  Every command is ``{name, title, description, params,
required, destructive, category}``; ``params`` are JSON-schema properties.
"""

from __future__ import annotations

import re


def _s(kind: str, description: str, **extra) -> dict:
    value = {"type": kind, "description": description}
    value.update(extra)
    return value


UID = _s("string", "Island id (see island.list).")
PAGE = _s("string", "Preset (page) id (see page.list).")
MONITOR = _s("string", "Monitor key (see monitor.list); empty = primary monitor.")
WAIT = _s("number", "Seconds to wait for the user's confirmation (default 90, max 300). "
                    "On timeout the result is status=pending with confirm_id; poll confirm.status.")
DRY = _s("boolean", "Only describe what would happen; nothing is changed and nothing is asked.")

COMMANDS: list[dict] = []


def command(name: str, title: str, description: str, params: dict | None = None, required=(),
            destructive: bool = False, category: str = "") -> None:
    params = dict(params or {})
    if destructive:
        params.setdefault("wait", WAIT)
        params.setdefault("dry_run", DRY)
    COMMANDS.append({"name": name, "title": title, "description": description, "params": params,
                     "required": list(required), "destructive": destructive,
                     "category": category or name.split(".", 1)[0]})


# App --------------------------------------------------------------------------------------------
command("app.info", "桌屿信息", "Version, data folder, demo flag, monitors, agent pipe, custom folder, web "
        "hosting mode and the state of the widget services.")
command("app.activate", "显示桌屿", "Bring the desk back (un-hide islands) and show a short notice.")
command("app.screenshot", "截图", "Save a PNG of every layer window (one per monitor) and return the paths. "
        "Use it to verify visual changes.", {"folder": _s("string", "Target folder (default: <data>/screenshots).")})
command("app.quit", "退出桌屿", "Quit DeskIsle (the desktop icons come back).", destructive=True)
command("schema", "命令列表", "All commands with JSON schemas (same as `deskisle-cli list --json`).")
command("confirm.status", "确认状态", "State of a confirmation requested by a destructive command: "
        "pending | accepted | rejected | unknown, plus the command result once accepted.",
        {"id": _s("string", "confirm_id returned by the destructive command.")}, ["id"])

# Desk ---------------------------------------------------------------------------------------------
command("desk.state", "桌面状态", "Presets with their islands (geometry in board pixels), loose desktop "
        "items and global flags (hidden, focus mode).",
        {"include_items": _s("boolean", "Also list the item paths of every island tab.")})
command("desk.visibility", "隐藏/显示", "Hide or show all islands (like double-clicking the desktop).",
        {"action": _s("string", "show | hide | toggle", enum=["show", "hide", "toggle"])}, ["action"])
command("desk.focus", "专注模式", "Focus mode: islands above other windows, everything else dimmed.",
        {"on": _s("boolean", "true = enter, false = leave, omitted = toggle.")})
command("desk.notice", "显示通知", "Show a notice card on the desk.",
        {"title": _s("string", "Title."), "text": _s("string", "Body text."),
         "kind": _s("string", "info | success | warning | error", enum=["info", "success", "warning", "error"]),
         "timeout_ms": _s("integer", "0 = stays until closed; default 5000.")}, ["title"])
command("desk.undo", "撤销", "Undo the last layout change (move/resize/arrange/delete).")
command("desk.arrange", "整理布局", "Tidy the islands of a monitor into a gap-free layout.",
        {"monitor": MONITOR})

# Monitors / presets --------------------------------------------------------------------------------
command("monitor.list", "显示器", "Connected monitors: key, label, primary, geometry, work area, scale, "
        "and the preset shown on each.")
command("page.list", "预设列表", "Presets (pages) of a monitor or of all monitors.", {"monitor": MONITOR})
command("page.switch", "切换预设", "Show a preset on a monitor.", {"page": PAGE, "monitor": MONITOR}, ["page"])
command("page.create", "新建预设", "Create a preset on a monitor (optionally duplicating another).",
        {"title": _s("string", "Name."), "monitor": MONITOR,
         "duplicate_of": _s("string", "Preset id to copy.")})
command("page.rename", "重命名预设", "Rename a preset.", {"page": PAGE, "title": _s("string", "New name.")},
        ["page", "title"])
command("page.delete", "删除预设", "Delete a preset and its islands (files stay where they are).",
        {"page": PAGE}, ["page"], destructive=True)

# Islands --------------------------------------------------------------------------------------------
command("island.list", "收纳岛列表", "Islands with kind, title, geometry and flags.",
        {"page": _s("string", "Only this preset."), "monitor": MONITOR,
         "kind": _s("string", "files | web | widget", enum=["files", "web", "widget"])})
command("island.get", "收纳岛详情", "One island with tabs, settings and (optionally) items.",
        {"uid": UID, "include_items": _s("boolean", "List the items of every tab.")}, ["uid"])
command("island.create", "新建收纳岛", "Create an island on the preset shown on a monitor. kind=files: icon "
        "island (folder = live view of that folder); kind=web: web page (url) or local HTML animation "
        "(html_path); kind=widget: widget = clock | weather | media | todo | custom:<id>.",
        {"kind": _s("string", "files | web | widget", enum=["files", "web", "widget"]),
         "title": _s("string", "Title (defaults per kind)."),
         "folder": _s("string", "files: folder to show live (a 'file view')."),
         "url": _s("string", "web: address."),
         "html_path": _s("string", "web: local .html file (runs offline, transparent background)."),
         "widget": _s("string", "widget: clock | weather | media | todo | custom:<folder name>."),
         "config": _s("object", "widget: initial widget_config, e.g. {\"style\": \"analog\"}."),
         "monitor": MONITOR,
         "x": _s("integer", "Left in board px (optional; otherwise the first free spot)."),
         "y": _s("integer", "Top in board px."),
         "width": _s("integer", "Width px."), "height": _s("integer", "Height px.")}, ["kind"])
command("island.update", "修改收纳岛", "Change title, flags, material, icon size or geometry. Other islands "
        "make way like when dragging.",
        {"uid": UID, "title": _s("string", "Title."), "collapsed": _s("boolean", "Fold to the header."),
         "locked": _s("boolean", "Lock position/size."), "pinned": _s("boolean", "Keep above all windows."),
         "capsule": _s("boolean", "Capsule mode: a small pill that opens on hover."),
         "keep_visible": _s("boolean", "Stay visible when the desk is hidden."),
         "material": _s("string", "liquid | frosted | clear", enum=["liquid", "frosted", "clear"]),
         "icon_size": _s("integer", "Icon size 32-128."),
         "x": _s("integer", "Left (board px)."), "y": _s("integer", "Top (board px)."),
         "width": _s("integer", "Width."), "height": _s("integer", "Height.")}, ["uid"])
command("island.delete", "删除收纳岛", "Remove an island. Its icons go back to the loose desktop area; "
        "no file is deleted.", {"uid": UID}, ["uid"], destructive=True)
command("island.action", "收纳岛操作", "Low-level island action (same as the island menu). name: collapse, "
        "lock, pin, keepVisible, capsule, rename{title}, material{material}, raise, tab{id}, addTab{title}, "
        "renameTab{id,title}, iconSize{size|delta}, sort{mode,descending}, autoSort{value}, portal{path}, "
        "portalOpen{path}, portalUp, portalHome, media{path,opacity,feather}, widgetConfig{...}, "
        "web.url{url}, web.home, web.reload, web.back, web.forward, web.toolbar, web.refresh{minutes}, "
        "web.zoom{zoom}, web.network. Deleting islands/tabs uses island.delete / island.tab.",
        {"uid": UID, "name": _s("string", "Action name."), "args": _s("object", "Action arguments.")},
        ["uid", "name"])
command("island.items", "收纳岛图标", "Items shown by an island tab (path, name, folder flag, exists).",
        {"uid": UID, "tab": _s("string", "Tab id (default: active tab).")}, ["uid"])
command("island.tab_close", "关闭标签页", "Close a tab; its icons go back to the desktop area.",
        {"uid": UID, "tab": _s("string", "Tab id.")}, ["uid", "tab"], destructive=True)
command("island.locate", "定位收纳岛", "Switch to the island's preset, expand and highlight it.", {"uid": UID},
        ["uid"])

# Items ------------------------------------------------------------------------------------------------
command("item.loose", "散放图标", "Desktop items not inside any island.")
command("item.move", "移动图标", "Move desktop item references into an island tab or back to the loose "
        "area. Files are not moved on disk.",
        {"paths": _s("array", "Item paths.", items={"type": "string"}),
         "to": _s("string", "Island id, or \"loose\"."), "tab": _s("string", "Tab id (default active)."),
         "index": _s("integer", "Position (default: end).")}, ["paths", "to"])
command("item.open", "打开", "Open a file/folder with its default application.",
        {"path": _s("string", "Path.")}, ["path"])
command("item.reveal", "在资源管理器中显示", "Show a file in Explorer.", {"path": _s("string", "Path.")},
        ["path"])

# Web ------------------------------------------------------------------------------------------------------
command("web.navigate", "打开网址", "Load an address in a web island (also becomes its home page).",
        {"uid": UID, "url": _s("string", "Address or search words.")}, ["uid", "url"])
command("web.control", "网页控制", "reload | back | forward | home | external (open in browser) | toolbar.",
        {"uid": UID, "action": _s("string", "Action.", enum=["reload", "back", "forward", "home", "external",
                                                             "toolbar"])}, ["uid", "action"])
command("web.status", "网页状态", "Hosting mode of every web page (composition / windowed / ...).")

# Widgets ----------------------------------------------------------------------------------------------------
command("widget.types", "小组件类型", "Built-in widgets and the widgets found in the custom folder.")
command("widget.config", "小组件设置", "Merge values into a widget island's widget_config. clock: "
        "{style: digital|analog|split, h24: bool, seconds: bool, lunar: bool}; weather: {city, lat, lon}; "
        "media: {compact: bool}; custom widgets: anything (window.deskisle.config).",
        {"uid": UID, "values": _s("object", "Keys to set.")}, ["uid", "values"])
command("todo.list", "待办列表", "Items of a todo widget.", {"uid": UID}, ["uid"])
command("todo.add", "添加待办", "Add an item; text may end with a due time like '@明天 18:00' or "
        "'@2025-05-01 9:30'.", {"uid": UID, "text": _s("string", "Text.")}, ["uid", "text"])
command("todo.toggle", "完成待办", "Mark an item done / not done.",
        {"uid": UID, "id": _s("string", "Item id.")}, ["uid", "id"])
command("todo.remove", "删除待办", "Delete a todo item.", {"uid": UID, "id": _s("string", "Item id.")},
        ["uid", "id"], destructive=True)
command("media.status", "正在播放", "Current media session (title, artist, app, playing, position).")
command("media.control", "播放控制", "Control the current media session.",
        {"action": _s("string", "play_pause | next | previous | seek",
                      enum=["play_pause", "next", "previous", "seek"]),
         "position": _s("number", "seek: seconds.")}, ["action"])
command("weather.status", "天气", "Current weather and forecast shown by the weather widget.")
command("weather.refresh", "刷新天气", "Fetch the weather again.")
command("clock.info", "时间与农历", "Current time, date and Chinese lunar calendar information.")
command("search.query", "搜索", "Search islands, desk items and files (Everything when installed).",
        {"text": _s("string", "Search text."), "limit": _s("integer", "Max file results (default 20).")},
        ["text"])

# Preferences / theme / custom folder ------------------------------------------------------------------------
command("prefs.get", "设置", "All preferences (see AGENTS.md for meanings).")
command("prefs.set", "修改设置", "Change preferences, e.g. {\"island_material\": \"liquid\", "
        "\"clock_24h\": false}. Unknown keys are reported, not stored.",
        {"values": _s("object", "Preference names and values.")}, ["values"])
command("theme.get", "主题", "Theme colours (accent from the wallpaper), light/dark state and tokens.")
command("theme.tokens", "主题参数", "Write visual tokens to custom/theme.json (merged unless replace=true); "
        "hot-reloaded. Keys: radius, smallRadius, glassStrength, shadow, motion, fontScale, headerHeight.",
        {"tokens": _s("object", "Token values."), "replace": _s("boolean", "Replace the whole file.")},
        ["tokens"])
command("custom.status", "自定义文件夹", "Custom folder path, widgets found and problems.")
command("custom.widget_create", "创建自制小组件", "Create a widget folder in custom/widgets (html or qml). "
        "content = the entry file (index.html / Widget.qml); omitted = a sample to edit.",
        {"id": _s("string", "Folder name: letters, digits, . _ -"), "name": _s("string", "Display name."),
         "type": _s("string", "html | qml", enum=["html", "qml"]),
         "content": _s("string", "Entry file content."),
         "size": _s("array", "[width, height] px.", items={"type": "integer"}),
         "description": _s("string", "Description."),
         "network": _s("boolean", "html: allow network access."),
         "add_to_desk": _s("boolean", "Also create an island showing it.")}, ["id"])
command("custom.widget_write", "写入小组件文件", "Create or replace one file inside a custom widget folder "
        "(hot-reloaded).", {"id": _s("string", "Widget id."), "file": _s("string", "Relative file name."),
                            "content": _s("string", "UTF-8 text.")}, ["id", "file", "content"])
command("custom.widget_read", "读取小组件文件", "Read a file of a custom widget (default: its entry file).",
        {"id": _s("string", "Widget id."), "file": _s("string", "Relative file name.")}, ["id"])
command("custom.widget_delete", "删除自制小组件", "Delete a custom widget folder and the islands showing it.",
        {"id": _s("string", "Widget id.")}, ["id"], destructive=True)

# Layout files / snapshots -------------------------------------------------------------------------------------
command("snapshot.list", "布局快照", "Saved layout snapshots.")
command("snapshot.save", "保存快照", "Save the current layout as a snapshot.", {"name": _s("string", "Name.")})
command("snapshot.restore", "恢复快照", "Replace the current layout with a snapshot (the current one is "
        "backed up first).", {"path": _s("string", "Snapshot path (snapshot.list).")}, ["path"],
        destructive=True)
command("layout.export", "导出布局", "Write the layout to a JSON file (never overwrites).",
        {"path": _s("string", "Target .json path.")}, ["path"])
command("layout.import", "导入布局", "Replace the layout with a JSON file (current layout backed up first).",
        {"path": _s("string", "Layout .json path.")}, ["path"], destructive=True)
command("rules.list", "整理规则", "Auto-sort rules for new desktop items.")
command("rules.apply", "应用规则", "Sort the loose desktop items into islands using the rules now.")

BY_NAME = {spec["name"]: spec for spec in COMMANDS}
_MCP_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def input_schema(spec: dict) -> dict:
    return {"type": "object", "properties": spec["params"], "required": list(spec["required"]),
            "additionalProperties": False}


def mcp_name(name: str) -> str:
    """MCP tool names may not contain dots: ``island.create`` -> ``island_create``."""
    return _MCP_SAFE.sub("_", name)


def from_mcp_name(tool: str) -> str:
    for spec in COMMANDS:
        if mcp_name(spec["name"]) == tool:
            return spec["name"]
    return tool


_TYPES = {"string": str, "boolean": bool, "object": dict, "array": list}


def validate(name: str, args) -> list[str]:
    """Light JSON-schema check with messages an agent can act on."""
    spec = BY_NAME.get(name)
    if spec is None:
        return ["unknown command {0!r}; call 'schema' for the list".format(name)]
    if args is None:
        args = {}
    if not isinstance(args, dict):
        return ["args must be an object"]
    problems = []
    for key in spec["required"]:
        if key not in args or args[key] in (None, ""):
            problems.append("missing required argument {0!r}".format(key))
    for key, value in args.items():
        prop = spec["params"].get(key)
        if prop is None:
            problems.append("unknown argument {0!r} (allowed: {1})".format(key, ", ".join(spec["params"]) or "none"))
            continue
        if value is None:
            continue
        kind = prop.get("type")
        if kind == "integer":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif kind == "number":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = isinstance(value, _TYPES.get(kind, object))
        if not ok:
            problems.append("argument {0!r} must be {1}".format(key, kind))
        elif "enum" in prop and value not in prop["enum"]:
            problems.append("argument {0!r} must be one of {1}".format(key, ", ".join(prop["enum"])))
    return problems


__all__ = ["COMMANDS", "BY_NAME", "input_schema", "mcp_name", "from_mcp_name", "validate"]

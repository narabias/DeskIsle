# DeskIsle (桌屿) — guide for AI agents

DeskIsle turns the Windows desktop into glass **islands** (收纳岛) laid out on per‑monitor **presets**
(预设, also called pages). You control it through the same commands everywhere:

| Way in | How |
|---|---|
| MCP (stdio) | `deskisle-cli mcp` — `deskisle-cli.exe` is the console program next to `DeskIsle.exe` (from source: `python main.py --mcp`). 设置 → AI 与扩展 shows the exact JSON for your install. Tool names use `_` instead of `.` (`island_create`). |
| CLI | `deskisle-cli <command> --key value …` or `deskisle-cli <command> --json '{"key": "value"}'` |
| Named pipe | `\\.\pipe\deskisle-<user>` (demo: `deskisle-demo-<user>`), one JSON object per line: `{"id": 1, "cmd": "island.list", "args": {}}` → `{"id": 1, "ok": true, "result": …}` or `{"id": 1, "ok": false, "error": {"code", "message"}}`. `<data>/agent.json` names the pipe of the running instance. |

`schema` (or `deskisle-cli list --json`) returns every command with its JSON schema; `deskisle-cli help <command>`
explains one. The interfaces can be switched off by the user (设置 → AI 与扩展 → 允许 AI 助手控制桌屿); an agent cannot switch them off.

## Start here
1. `app.info` — version, data folder, monitors, web hosting mode, custom folder, service states.
2. `desk.state` — presets → islands (kind, title, geometry, flags) and loose desktop items.
3. After a visual change, `app.screenshot` and look at the PNGs (MCP returns them as images).

## Concepts
* **Board coordinates**: logical pixels; the origin is the top‑left corner of the union of all monitors
  (`monitor.list` gives each monitor's `geometry` and `work` area in board pixels). Island `x/y/width/height`
  are board pixels. Leave the geometry out and DeskIsle finds a free spot.
* **Make way**: islands never overlap. Moving/resizing an island (`island.update` with x/y/width/height)
  pushes the neighbours away exactly like a drag; a locked island does not move.
* **Island kinds**
  * `files` — icons of desktop items. Items are *references*: moving them between islands never moves files on
    disk. With `folder` the island is a live view of that folder (文件夹视图, browse into sub folders).
  * `web` — a web page (`url`) or a local HTML animation (`html_path`, transparent, offline by default).
  * `widget` — `clock`, `weather`, `media` (now playing), `todo`, or `custom:<id>` from the custom folder.
* **Presets**: every monitor shows one preset; `page.switch` changes it. A monitor combination (A) remembers its
  own layout; unplugging and re‑plugging restores it after a short grace period.
* **Flags**: `collapsed` (fold to the header), `locked`, `pinned` (above all windows), `capsule` (a small pill
  that opens on hover), `keep_visible` (stays when the desk is hidden), `material` liquid | frosted | clear.
* **Accent colour** always comes from the wallpaper. There is deliberately no way to set it.

## Destructive commands need the user
`app.quit`, `page.delete`, `island.delete`, `island.tab_close`, `todo.remove`, `custom.widget_delete`,
`snapshot.restore`, `layout.import` show a confirmation card on the desktop marked “来自 AI 助手”.
* The call waits for the answer (`wait`, default 90 s, max 300 s). Accepted → `{"status": "accepted", "result"}`.
  Declined → error code `rejected` (do not retry unless the user asks). Timeout → `{"status": "pending",
  "confirm_id"}`; poll `confirm.status {"id": confirm_id}`.
* Only one confirmation can be open; another one returns error `busy`.
* `dry_run: true` describes what would happen without asking or changing anything — use it to explain plans.
* Deleting an island never deletes files; its icons return to the desktop area. `desk.undo` reverts the last
  layout change (move/resize/arrange/delete).

## Errors
`{"code", "message"}`; the message says what to change. Codes: `invalid_args` (lists the problems),
`unknown_command`, `unknown_action`, `use_command` (use the dedicated command named in the message),
`not_found` (bad uid / page / path / item), `wrong_kind` (e.g. web command on a files island), `refused`,
`exists`, `conflict`, `no_room` (no free spot on that monitor), `last_preset`, `last_tab`, `file_view`
(items of a folder view cannot be moved), `too_large`, `invalid_file`, `invalid_widget`, `io`, `layout`,
`busy` (another confirmation is open), `rejected` (the user declined — do not retry unless asked), `timeout`,
`unavailable` (service missing on this machine, e.g. no media session or no Everything), `internal`.
CLI exit codes: 0 ok, 1 command error, 2 usage error, 3 DeskIsle not running / pipe unavailable.

## Recipes
* Island for a project folder: `island.create {"kind": "files", "folder": "D:\\Work\\Report", "title": "报告"}`.
* Move desktop items into an island: `item.loose` → `item.move {"paths": [...], "to": "<uid>"}`.
* Web page: `island.create {"kind": "web", "url": "https://example.com", "width": 480, "height": 360}`;
  later `web.navigate`, `web.control {"action": "reload"}`. `web.status` shows composition/windowed hosting.
* Clock with lunar calendar, 12‑hour: `island.create {"kind": "widget", "widget": "clock",
  "config": {"h24": false, "lunar": true, "style": "analog"}}`. Styles: digital | analog | split.
* Weather for a fixed city: `widget.config {"uid", "values": {"city": "杭州", "lat": 30.27, "lon": 120.15}}`
  (omit to use Windows location). `weather.status` / `weather.refresh`.
* Todo: `todo.add {"uid", "text": "交周报 @明天 18:00"}` (due time after `@`), `todo.toggle`, `todo.list`.
* Media: `media.status`, `media.control {"action": "play_pause" | "next" | "previous" | "seek", "position"}`.
* Tidy a monitor: `desk.arrange {"monitor": "<key>"}`; save first with `snapshot.save {"name": "…"}`.
* Look & feel tokens (hot‑reloaded): `theme.tokens {"tokens": {"radius": 26, "motion": 0.8}}` → keys radius,
  smallRadius, glassStrength, shadow, motion (0 = no animation), fontScale, headerHeight, barHeight,
  iconLabelLines. Preferences: `prefs.get` / `prefs.set {"values": {"island_material": "liquid"}}`.

## Custom widgets (widget SDK)
`custom.widget_create {"id": "pomodoro", "name": "番茄钟", "type": "html", "size": [300, 200],
"content": "<!doctype html>…", "add_to_desk": true}` creates `custom/widgets/pomodoro/` with `widget.json`
and the entry file. Edit with `custom.widget_write {"id", "file", "content"}` — every island showing the widget
reloads at once. Problems (bad JSON, missing entry, QML errors) appear in `custom.status`.

**HTML widgets** run in WebView2 with a transparent background; no network unless `"network": true`.
`window.deskisle` offers `theme` (colours, font, `dark`), `config` (this island's settings),
`setConfig(key, value)` (persisted), `on("theme" | "config", cb)`, `openUrl(url)` (http/https/mailto in the
browser), `notify(title, text)`, `menu()` (the island menu). CSS variables: `--deskisle-accent`,
`--deskisle-text`, `--deskisle-textDim`, `--deskisle-onAccent`, `--deskisle-fontFamily`, …;
`<html data-deskisle-theme="dark|light">`. Keep the page background transparent: the glass is drawn behind it.

**QML widgets** (`"type": "qml"`, entry `Widget.qml`, root item fills the island body) may use `Theme`
(colours, `fontFamily`, `radius`, `ms(duration)`), `Desk`, `Clock`, `Weather`, `Player`, `Todo` and `widget`
(the island: `widget.uid`, `widget.widgetConfig`; save with `Desk.act(widget.uid, "widgetConfig", {...})`).
Only `import QtQuick`, `QtQuick.Shapes`, `QtQuick.Layouts` and `QtQuick.Effects` are guaranteed.

Design rules that keep widgets at home on the desk: transparent background, text in `Theme.text` /
`Theme.textDim`, a single accent (`Theme.accent`), 12–14 px body text, generous padding (≥ 14 px), no hard
borders, respect `Theme.reduceMotion`.

<!-- commands:begin (generated by tools/gen_guide.py) -->
## Command reference

`*` = required argument, ⚠ = asks the user first (`wait`, `dry_run` accepted). `deskisle-cli help <command>` shows types and descriptions.

**app**

* `app.info` — 桌屿信息. Version, data folder, demo flag, monitors, agent pipe, custom folder, web hosting mode and the state of the widget services.
* `app.activate` — 显示桌屿. Bring the desk back (un-hide islands) and show a short notice.
* `app.screenshot` — 截图 (folder). Save a PNG of every layer window (one per monitor) and return the paths. Use it to verify visual changes.
* `app.quit` ⚠ — 退出桌屿. Quit DeskIsle (the desktop icons come back).

**schema**

* `schema` — 命令列表. All commands with JSON schemas (same as `deskisle-cli list --json`).

**confirm**

* `confirm.status` — 确认状态 (id*). State of a confirmation requested by a destructive command: pending | accepted | rejected | unknown, plus the command result once accepted.

**desk**

* `desk.state` — 桌面状态 (include_items). Presets with their islands (geometry in board pixels), loose desktop items and global flags (hidden, focus mode).
* `desk.visibility` — 隐藏/显示 (action*). Hide or show all islands (like double-clicking the desktop).
* `desk.focus` — 专注模式 (on). Focus mode: islands above other windows, everything else dimmed.
* `desk.notice` — 显示通知 (title*, text, kind, timeout_ms). Show a notice card on the desk.
* `desk.undo` — 撤销. Undo the last layout change (move/resize/arrange/delete).
* `desk.arrange` — 整理布局 (monitor). Tidy the islands of a monitor into a gap-free layout.

**monitor**

* `monitor.list` — 显示器. Connected monitors: key, label, primary, geometry, work area, scale, and the preset shown on each.

**page**

* `page.list` — 预设列表 (monitor). Presets (pages) of a monitor or of all monitors.
* `page.switch` — 切换预设 (page*, monitor). Show a preset on a monitor.
* `page.create` — 新建预设 (title, monitor, duplicate_of). Create a preset on a monitor (optionally duplicating another).
* `page.rename` — 重命名预设 (page*, title*). Rename a preset.
* `page.delete` ⚠ — 删除预设 (page*). Delete a preset and its islands (files stay where they are).

**island**

* `island.list` — 收纳岛列表 (page, monitor, kind). Islands with kind, title, geometry and flags.
* `island.get` — 收纳岛详情 (uid*, include_items). One island with tabs, settings and (optionally) items.
* `island.create` — 新建收纳岛 (kind*, title, folder, url, html_path, widget, config, monitor, x, y, width, height). Create an island on the preset shown on a monitor. kind=files: icon island (folder = live view of that folder); kind=web: web page (url) or local HTML animation (html_path); kind=widget: widget = clock | weather | media | todo | custom:<id>.
* `island.update` — 修改收纳岛 (uid*, title, collapsed, locked, pinned, capsule, keep_visible, material, icon_size, x, y, width, height). Change title, flags, material, icon size or geometry. Other islands make way like when dragging.
* `island.delete` ⚠ — 删除收纳岛 (uid*). Remove an island. Its icons go back to the loose desktop area; no file is deleted.
* `island.action` — 收纳岛操作 (uid*, name*, args). Low-level island action (same as the island menu). name: collapse, lock, pin, keepVisible, capsule, rename{title}, material{material}, raise, tab{id}, addTab{title}, renameTab{id,title}, iconSize{size|delta}, sort{mode,descending}, autoSort{value}, portal{path}, portalOpen{path}, portalUp, portalHome, media{path,opacity,feather}, widgetConfig{...}, web.url{url}, web.home, web.reload, web.back, web.forward, web.toolbar, web.refresh{minutes}, web.zoom{zoom}, web.network. Deleting islands/tabs uses island.delete / island.tab.
* `island.items` — 收纳岛图标 (uid*, tab). Items shown by an island tab (path, name, folder flag, exists).
* `island.tab_close` ⚠ — 关闭标签页 (uid*, tab*). Close a tab; its icons go back to the desktop area.
* `island.locate` — 定位收纳岛 (uid*). Switch to the island's preset, expand and highlight it.

**item**

* `item.loose` — 散放图标. Desktop items not inside any island.
* `item.move` — 移动图标 (paths*, to*, tab, index). Move desktop item references into an island tab or back to the loose area. Files are not moved on disk.
* `item.open` — 打开 (path*). Open a file/folder with its default application.
* `item.reveal` — 在资源管理器中显示 (path*). Show a file in Explorer.

**web**

* `web.navigate` — 打开网址 (uid*, url*). Load an address in a web island (also becomes its home page).
* `web.control` — 网页控制 (uid*, action*). reload | back | forward | home | external (open in browser) | toolbar.
* `web.status` — 网页状态. Hosting mode of every web page (composition / windowed / ...).

**widget**

* `widget.types` — 小组件类型. Built-in widgets and the widgets found in the custom folder.
* `widget.config` — 小组件设置 (uid*, values*). Merge values into a widget island's widget_config. clock: {style: digital|analog|split, h24: bool, seconds: bool, lunar: bool}; weather: {city, lat, lon}; media: {compact: bool}; custom widgets: anything (window.deskisle.config).

**todo**

* `todo.list` — 待办列表 (uid*). Items of a todo widget.
* `todo.add` — 添加待办 (uid*, text*). Add an item; text may end with a due time like '@明天 18:00' or '@2025-05-01 9:30'.
* `todo.toggle` — 完成待办 (uid*, id*). Mark an item done / not done.
* `todo.remove` ⚠ — 删除待办 (uid*, id*). Delete a todo item.

**media**

* `media.status` — 正在播放. Current media session (title, artist, app, playing, position).
* `media.control` — 播放控制 (action*, position). Control the current media session.

**weather**

* `weather.status` — 天气. Current weather and forecast shown by the weather widget.
* `weather.refresh` — 刷新天气. Fetch the weather again.

**clock**

* `clock.info` — 时间与农历. Current time, date and Chinese lunar calendar information.

**search**

* `search.query` — 搜索 (text*, limit). Search islands, desk items and files (Everything when installed).

**prefs**

* `prefs.get` — 设置. All preferences (see AGENTS.md for meanings).
* `prefs.set` — 修改设置 (values*). Change preferences, e.g. {"island_material": "liquid", "clock_24h": false}. Unknown keys are reported, not stored.

**theme**

* `theme.get` — 主题. Theme colours (accent from the wallpaper), light/dark state and tokens.
* `theme.tokens` — 主题参数 (tokens*, replace). Write visual tokens to custom/theme.json (merged unless replace=true); hot-reloaded. Keys: radius, smallRadius, glassStrength, shadow, motion, fontScale, headerHeight.

**custom**

* `custom.status` — 自定义文件夹. Custom folder path, widgets found and problems.
* `custom.widget_create` — 创建自制小组件 (id*, name, type, content, size, description, network, add_to_desk). Create a widget folder in custom/widgets (html or qml). content = the entry file (index.html / Widget.qml); omitted = a sample to edit.
* `custom.widget_write` — 写入小组件文件 (id*, file*, content*). Create or replace one file inside a custom widget folder (hot-reloaded).
* `custom.widget_read` — 读取小组件文件 (id*, file). Read a file of a custom widget (default: its entry file).
* `custom.widget_delete` ⚠ — 删除自制小组件 (id*). Delete a custom widget folder and the islands showing it.

**snapshot**

* `snapshot.list` — 布局快照. Saved layout snapshots.
* `snapshot.save` — 保存快照 (name). Save the current layout as a snapshot.
* `snapshot.restore` ⚠ — 恢复快照 (path*). Replace the current layout with a snapshot (the current one is backed up first).

**layout**

* `layout.export` — 导出布局 (path*). Write the layout to a JSON file (never overwrites).
* `layout.import` ⚠ — 导入布局 (path*). Replace the layout with a JSON file (current layout backed up first).

**rules**

* `rules.list` — 整理规则. Auto-sort rules for new desktop items.
* `rules.apply` — 应用规则. Sort the loose desktop items into islands using the rules now.

<!-- commands:end -->

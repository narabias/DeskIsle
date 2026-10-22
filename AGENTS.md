# AGENTS.md — working on DeskIsle (桌屿) 2.0

This file is for AI coding agents (and humans) who change the **code**. An agent that only wants to *drive* a
running DeskIsle should read [deskisle/agent/GUIDE.md](deskisle/agent/GUIDE.md) instead (MCP / CLI / pipe).

## Ground rules

- **Never touch user files.** Islands hold *references* (paths). The only code that changes files on disk is the
  folder‑view drop (`desk_items.move_into_folder`), and it asks first. Deleting an island returns its icons to the
  loose desktop area. Keep it that way.
- **Destructive agent commands need the user** (`destructive=True` in `agent/schema.py` → confirm card
  “来自 AI 助手”). Do not add bypasses, environment switches or “trusted” modes.
- **The accent colour comes only from the wallpaper** (`engine/wallpaper.py` → `ThemeBridge.set_wallpaper_accent`).
  No colour pickers, hex fields or RGB wheels for it — this was an explicit product decision. Two deliberate
  exceptions (2.0.1, user requests): the **text colour** preference (`text_color_mode` auto / light / dark /
  custom + `text_color`, applied by `ThemeBridge._text_rgb` to every surface incl. the settings window), and the
  now‑playing widget, which tints itself with the cover colour (`Player.accent`) without touching `Theme.accent`.
- UI text is **Simplified Chinese**; code, comments, logs and agent messages are English. Reuse the established
  terms: 收纳岛, 文件视窗, 网页岛, 小组件, 预设, 灵动岛, 胶囊, 液态玻璃 / 毛玻璃 / 清透, 数字 / 指针 / 翻页.
- One mutation path: QML, menus, tray and agent all call the same `DeskController` methods. Don't mutate
  `AppState` from QML/JS and don't duplicate logic in `agent/commands.py`.
- Everything Windows‑specific lives behind `sys.platform == "win32"` checks (`native_win.py`, `webview2.py`,
  services). The app must still start with `--demo` on macOS/Linux, and the test suite must pass there.

## Quick commands

```bash
python -m pip install -r requirements.txt          # PySide6 6.12, lunar_python, pywin32/winrt on Windows
python main.py --demo                              # demo window, data in %TEMP%/DeskIsleDemo
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests
python tools/gen_guide.py                          # after editing agent/schema.py (CI: --check)
python tools/cli_entry.py list                     # deskisle-cli from source
python tools/probe.py --out shots wait:3000 grab:desk panel:new wait:800 grab:new   # screenshots
```

Windows release: `powershell -File tools/build_release.ps1 -NoOpen` (see docs/打包说明.md).

## Map of the code

| Path | What it is |
| --- | --- |
| `main.py` | argument parsing; `--mcp` / `--cli` never import Qt; `--watchdog`, `--self-test` |
| `deskisle/models.py` | dataclasses (`AppState`, `PageState`, `IslandState`, `TabState`, `Preferences`), JSON (de)serialisation, 1.x → 2.0 migration (`STATE_VERSION = 3`, `LEGACY_KINDS`) |
| `deskisle/storage.py` | `StateStore`: atomic writes, `.bak`, snapshots, import/export |
| `deskisle/layout.py`, `monitors.py`, `rules.py` | Qt‑free geometry (no overlap, gaps, make‑way), monitor/preset mapping and combos, auto‑sort rules |
| `deskisle/engine/app.py` | `DeskIsleApp`: builds everything, owns the QML engine, image providers, settings/menu windows, shutdown |
| `deskisle/engine/controller.py` | `DeskController` (QML `Desk`): gestures, island actions, presets, prefs, notices, confirmations, A/B features |
| `deskisle/engine/desk_items.py` | icon records, sorting, folder views, drag & drop, drag‑out (`QDrag` with file URLs → CF_HDROP) |
| `deskisle/engine/scene.py` | per‑monitor scene models, `IslandProxy`, `ItemsModel` (what QML binds to) |
| `deskisle/engine/arrange.py` | live make‑way / swap during drags, `move_to`, undo stack |
| `deskisle/engine/layer.py` | `LayerManager`: one transparent `Layer.qml` window per monitor (+ `PinnedIsland.qml` windows) |
| `deskisle/engine/wallpaper.py` | backdrop sources (live / static / image / solid), accent extraction, `image://wall` |
| `deskisle/engine/style.py` | `ThemeBridge` (QML `Theme`): palette, day/night, tokens from `custom/theme.json` |
| `deskisle/engine/icons.py` | `image://icon` provider (shell icons, generated file‑type icons), provider warm‑up |
| `deskisle/engine/menus.py` | every context menu (`build_*`) and its dispatcher; menus are QML windows (`MenuWindow.qml`) |
| `deskisle/engine/webhost.py`, `deskisle/webview2.py` | WebView2 composition / windowed hosting, `window.deskisle` bridge |
| `deskisle/engine/system.py` | tray, global hotkeys (`HOTKEYS`), foreground / desktop double‑click hooks, guardian |
| `deskisle/services/` | widget back‑ends: `clock` (lunar), `weather`, `nowplaying` (GSMTC), `everything`, `todo`, `base` (`Http`, `NullService`) |
| `deskisle/custom.py` | custom folder (QML `Custom`): `theme.json`, `widgets/<id>/`, hot reload, problems list |
| `deskisle/agent/` | `schema.py` (catalogue, pure Python), `commands.py` (Qt side), `server.py` (QLocalServer), `client.py`, `mcp.py`, `cli.py`, `GUIDE.md` |
| `deskisle/qml/` | all UI. `Layer.qml` (desk of one monitor), `Island.qml` + bodies, `DynamicBar.qml` + panels, `Settings*.qml`, widgets, `Glass.qml` + `shaders/` |
| `deskisle/watchdog.py` | crash watchdog process (no Qt imports) |
| `deskisle/selftest.py` | `--self-test` for frozen builds |
| `packaging/`, `tools/` | PyInstaller spec, Inno Setup script, build script, generators, probe |

## Runtime architecture

`DeskIsleApp.build()` (engine/app.py) runs in this order — keep it:

1. `load_state()` — a 1.x file is copied to `snapshots/<stamp>--升级到2.0之前的布局.json`, then migrated.
2. `WallpaperService`, `QQmlEngine`, image providers `icon`, `wall`, plus every service's `image_providers()`
   (`cover`). Then **`icons.prime_image_providers(...)`** — see “Threads and the GIL”.
3. `DeskController` (`Desk`), services (`Clock`, `Weather`, `Player` = `Media`, `Search`, `Todo`), `CustomFolder`
   (`Custom`), context properties, `LayerManager`, `WebHost`.
4. `start()`: layer windows, desktop attach (Windows: above the icon list view, below normal windows), tray,
   hotkeys, hooks, agent pipe, watchdog marker, update check.

Context objects available to every QML file: `Desk`, `Theme`, `App`, `Clock`, `Weather`, `Player`, `Media`,
`Search`, `Todo`, `WebHost`, `Custom`.

How a change flows: QML calls a slot (`Desk.act(uid, "collapse", {})`, `Desk.menuAction(...)`,
`Desk.setPref(name, value)`) → controller mutates `AppState` → emits (`changed`, `islandsChanged`,
`prefsChanged`, …) → proxies/models update → QML re‑binds; `queue_save()` writes `state.json` (debounced,
atomic, `.bak`). Agent commands call the same controller methods and return JSON.

### Coordinates and layout invariants

- Island `x/y/width/height` are **board coordinates**: logical pixels, origin = top‑left of the union of all
  screen geometries (same as 1.x, so layouts stay compatible). Window‑local = board − monitor geometry.
- Islands on one monitor never overlap and keep `Preferences.layout_gap`; use `arrange.Arranger` (`move_to`, drag/resize
  gestures) instead of writing geometry directly, so neighbours make way and undo works.
- Every monitor shows one preset (`state.current_pages[monitor_key]`); `state.combos` stores layouts per monitor
  combination (feature A).

### Threads and the GIL (read before touching Qt from Python)

Two real deadlocks shaped these rules:

- **No Python Qt message handler by default.** `qInstallMessageHandler` with a Python callback deadlocks when Qt's
  QML type‑loader thread logs while the GUI thread (holding the GIL) waits for it. QML warnings reach the log
  via `QQmlEngine.warnings`. `DESKISLE_QT_LOG=1` enables the handler for debugging only.
- **Image providers must be primed.** Qt's pixmap reader thread calls the *virtual* `imageType()` of a provider
  while holding its job mutex; for a Python provider the first call needs the GIL. If the GUI thread holds the
  GIL and queues another async image at that moment, both wait forever (frozen start‑up). `prime_image_providers`
  loads one tiny image from every provider before any QML exists, after which PySide caches the lookup.
  A new provider must be registered before that call and must answer ids starting with `icons.WARMUP_ID`
  immediately with `icons.warmup_image(size)`.
- Worker threads (weather, location, now playing, Everything index, icon extraction) never touch QObjects; they
  hand results to the GUI thread through signals (`Signal(object)` + queued connection).
- PySide cannot convert some QML enum properties (e.g. `Image.status`): expose a `bool`/`int` helper property
  in QML instead of calling `item.property("status")` from Python.

### QML conventions

- Don't declare properties named like `Item` members (`layer`, `left`, `top`, `state`, …) — they are FINAL and
  break silently; existing code uses `deskLayer`, `remaining`, `baseY`.
- `font.pixelSize` must be an integer; text uses `Theme.fontFamily`; durations go through `Theme.ms(…)` so
  “减弱动态效果” and the `motion` token work.
- Icons are `Glyph { name: "…" }` using Tabler outline paths from `qml/glyphs.js`. To add one, copy the path
  data of the Tabler icon into `paths` (MIT, see `qml/LICENSE-TABLER.txt`); a test checks that every glyph name
  used in QML and Python exists.
- Shaders: edit `qml/shaders/*.frag`, then bake with
  `pyside6-qsb --glsl "100 es,120,150" --hlsl 50 --msl 12 -o x.frag.qsb x.frag` and commit the `.qsb`.
- Panels (`PanelHost.qml`) and the settings window are **non‑modal**; the settings window is a single instance
  (`App.open_settings`). Keep new dialogs inline (cards, popovers) instead of modal windows.
- Since 2.0.1 bar panels, confirmation cards and notices are shown in **`PopupWindow.qml`** — one frameless,
  always‑on‑top tool window per role (`panel` / `confirm` / `notice`), created lazily by `App._popup(role)` and
  hidden + `releaseResources()` after the card faded out. This keeps them above web islands (native child windows)
  and pinned islands; the card background calls `beginMove()` (system move); `Layer.qml` no longer draws them.
  Notices never take focus; a confirmation asked while the settings window is active is shown inside the settings
  window instead.
- Window children are QObject children of the window, not of `contentItem` (matters for `findChildren` in tests).
- Settings rows: `SettingRow { title; description; pref: "<Preferences field>"; kind: "switch" | … }`. Add every
  new row to the search index in `Settings.qml` (a test checks that each index entry has a row).

## Recipes

### Add an agent command
1. `agent/schema.py`: `command("area.verb", "中文标题", "English description for the agent.", {params…},
   required=(…), destructive=…)`. Params are JSON‑schema properties; the input schema is closed.
2. `agent/commands.py`: `def c_area_verb(self, args):` → return JSON‑able data or raise
   `AgentError(code, message)` (codes listed in GUIDE.md). Destructive commands return a `Plan` (the user decides).
3. `python tools/gen_guide.py` regenerates the command reference in `GUIDE.md`; tests check handler/schema/guide
   parity, and `tools/build_release.ps1` runs `--check`.
4. If it is read‑only, add it to `READ_ONLY` in `agent/mcp.py`.

### Add a preference
`models.Preferences` field + `to_dict` + `from_dict` (validate there with `_as_bool`, `_as_int`, `_clamp`, …) →
react to it in `controller.apply_preferences` / `app._prefs_changed` → a `SettingRow` with `pref:` → the
`Settings.qml` search index. `Desk.setPref` and the agent's `prefs.set` both go through
`controller.set_preferences`, i.e. through `Preferences.from_dict`, so invalid values are clamped, never stored.

### Add a built‑in widget
1. Back‑end `services/<name>.py`: `class XService(QObject)` with `__init__(self, desk, demo=False, parent=None)`,
   Qt properties/slots for QML, `shutdown()`, optional `set_paused()` / `image_providers()`.
2. Register it in `engine/app.py::_build_services` **and** in `SERVICES` of `packaging/DeskIsle.spec`
   (a test compares them; a missing module silently becomes a `NullService` in the frozen build).
3. QML `XWidget.qml`, mapped in `WidgetBody.qml`; a tile in `NewPanel.qml`; menu entries in
   `menus.widget_entries`; config docs in `WIDGET_CONFIG_DOCS` (agent) and `widget.types`.
4. Demo data when `demo=True` (the demo and the tests never touch the network).

## 自定义文件夹与小组件 SDK

`<data>/custom` (preference `custom_folder` may point elsewhere), hot‑reloaded by `custom.py`:

```
custom/
  README.md             created once, never overwritten
  theme.json            tokens: radius, smallRadius, barHeight, glassStrength, shadow, motion (0 = no animation),
                        fontScale, headerHeight, iconLabelLines — see engine/style.py DEFAULT_TOKENS
  widgets/<id>/
    widget.json         {"name", "type": "html" | "qml", "entry", "size": [w, h], "description",
                         "network": false, "version"}
    index.html | Widget.qml
```

- **HTML widgets** run in WebView2 with a transparent background and no network unless `"network": true`.
  `window.deskisle`: `version`, `uid`, `theme` (colours, `fontFamily`, `dark`), `config`, `setConfig(key, value)`
  (persisted in the island), `on("theme" | "config", cb)`, `openUrl(url)`, `notify(title, text)`, `menu()`.
  CSS variables `--deskisle-<token>` and `<html data-deskisle-theme="dark|light">` are kept up to date.
- **QML widgets** (`Widget.qml`, root fills the island body) may use `Theme`, `Desk`, `Clock`, `Weather`,
  `Player`, `Todo` and `widget` (the island proxy: `widget.uid`, `widget.widgetConfig`; save with
  `Desk.act(widget.uid, "widgetConfig", {...})`). Only `QtQuick`, `QtQuick.Shapes`, `QtQuick.Layouts` and
  `QtQuick.Effects` are guaranteed in the packaged build (other Qt modules are stripped by the spec).
- Problems (bad JSON, missing entry, QML errors) go to `CustomFolder.problems` → settings page and
  `custom.status`; never raise into the UI.
- Design rules: transparent background, `Theme.text` / `Theme.textDim`, one accent (`Theme.accent`), 12–14 px body
  text, ≥ 14 px padding, no hard borders, respect `Theme.reduceMotion`.

## Testing

- `tests/test_layout.py`, `test_models_storage_rules.py`, `test_v12_features.py`: geometry, models, storage,
  rules, migrations. `test_v13_webview2.py`: WebView2 COM bindings with fakes. `test_v2_services.py`: clock /
  lunar, weather parsing and gating, todo quick dates, Everything IPC, now playing. `test_v2_agent.py`: schema,
  CLI, MCP, pipe round trip. `test_v2_app.py`: a real demo app (QML loaded offscreen) — islands, arrange/undo,
  presets, panels, menus, confirmations, desktop scan, settings single instance. `test_v2_static.py`: glyphs,
  settings search index, QML compilation, shaders, migration, theme, custom folder, packaging. `test_v201.py`:
  2.0.1 fixes without an app — todo calendar marks / reminders / snooze (fake desk, patched `todo._now`),
  snapshot deletion, text colour, theme signal de‑duplication, flip‑clock menu, drag‑icon guard, memory helpers.
- `tests/support.py` sets `DESKISLE_DISABLE_WEBVIEW2=1` and a temporary data folder; tests never use the network.
- The offscreen platform uses the software scene graph: `ShaderEffect`/`MultiEffect` (glass, rounded covers) are
  not drawn there. For visual checks use a GL context, e.g. Linux `Xvfb :99` + `QT_QPA_PLATFORM=xcb
  QSG_RHI_BACKEND=opengl`, and `tools/probe.py` (steps: `wait:<ms> grab:<name> panel:<new|presets|search|media>
  close settings:<appearance|desktop|widgets|ai|about> menu:<context> action:<id> pref:<name>=<json> hide focus
  eval:<python>`). Kill stale probe processes before a new run.
- Frozen builds: `DeskIsle.exe --self-test report.json` checks QML compilation, services, layer windows, actions,
  all settings pages, the agent pipe, storage, `deskisle-cli.exe` and (Windows) the native shell menu.

## Packaging notes

- `packaging/DeskIsle.spec` builds three programs into one folder: `DeskIsle.exe` (windowed), `deskisle-cli.exe`
  (console; MCP clients need real stdio; it excludes Qt) and `DeskIsleShellMenu.exe`.
- The spec bundles `deskisle/qml`, `deskisle/assets`, `agent/GUIDE.md`, `docs`, README/CHANGELOG/notices, and
  filters unused Qt modules (`UNUSED_QML`, `UNUSED_LIBS`). If you import a new Qt module from QML, check the
  filter (a test verifies the modules the QML imports survive it).
- `installer.iss`: `AppVersion` must equal `VERSION` and `deskisle.__version__` (tested); optional task
  `addtopath` adds the install folder to the user's PATH (removed on uninstall); `[InstallDelete]` clears the old
  `_internal` folder so 1.x Qt files don't linger.
- Version bump: `VERSION`, `deskisle/__init__.py`, `packaging/installer.iss`, `CHANGELOG.md`.

## Only testable on real Windows

Desktop attach and icon hiding, live wallpaper capture (`PrintWindow` of the wallpaper `WorkerW`), WebView2
composition hosting, GSMTC now playing, the Windows location service, Everything IPC, global hotkeys, the
desktop double‑click hook, drag‑out to Explorer, the native shell menu, the watchdog restart, the installer and
its PATH task. The demo and the tests exercise the platform‑independent logic around them.

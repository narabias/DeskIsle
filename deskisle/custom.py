"""The custom folder: user / agent supplied theme tokens and widgets.

Layout (``<data>/custom`` unless the preference ``custom_folder`` points
elsewhere)::

    custom/
      README.md                 how it works (created once, never overwritten)
      theme.json                visual tokens, see engine/style.py DEFAULT_TOKENS
      widgets/
        <id>/
          widget.json           {"name", "type": "html"|"qml", "entry", "size": [w, h],
                                 "description", "network": false, "version"}
          index.html | Widget.qml

Everything is hot-reloaded: saving ``theme.json`` restyles the desk at once,
saving a widget file reloads every island showing that widget.  Problems are
collected in :attr:`CustomFolder.problems` (shown in the settings and returned
by the agent command ``custom.status``) instead of raising.

HTML widgets run in WebView2 like web islands and get ``window.deskisle``
(theme, config, ``setConfig``, ``openUrl``, ``notify``; see AGENTS.md).  QML
widgets are loaded into the island with the context objects ``Desk``,
``Theme``, ``Clock``, ``Weather``, ``Player``, ``Todo`` and ``widget`` (the
island proxy, read ``widget.widgetConfig``; write through
``Desk.act(widget.uid, "widgetConfig", {...})``).
"""

from __future__ import annotations

import json
import logging
import re
import shutil
from pathlib import Path

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QTimer, QUrl, Signal, Slot

log = logging.getLogger("deskisle.custom")

WIDGET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,47}$")
MIN_SIZE, MAX_SIZE = 140, 1600

README = """# 桌屿自定义文件夹

这个文件夹里的内容会被桌屿实时读取，保存后立即生效（无需重启）。

## theme.json —— 视觉参数
```json
{
  "radius": 22,          // 收纳岛圆角（像素）
  "smallRadius": 12,     // 按钮、菜单圆角
  "glassStrength": 1.0,  // 玻璃折射强度倍数
  "shadow": 1.0,         // 阴影倍数
  "motion": 1.0,         // 动画时长倍数，2 = 慢一倍，0 = 关闭动画
  "fontScale": 1.0,      // 字号倍数
  "headerHeight": 44     // 标题栏高度
}
```
（实际文件里不能写注释。）强调色只来自壁纸，这里不能修改。

## widgets/ —— 自制小组件
每个子文件夹是一个小组件，需要一个 `widget.json`：
```json
{"name": "你好", "type": "html", "entry": "index.html", "size": [300, 200],
 "description": "示例", "network": false}
```
* `type: "html"`：网页小组件，页面里可以使用 `window.deskisle`：
  `deskisle.theme`（颜色、字体、深浅色）、`deskisle.config`（这个岛自己的设置）、
  `deskisle.setConfig(key, value)`、`deskisle.openUrl(url)`、`deskisle.notify(title, text)`、
  `deskisle.on("theme" | "config", callback)`；CSS 变量 `--deskisle-accent`、`--deskisle-text` 等。
  `network` 为 false 时页面不能访问网络。
* `type: "qml"`：Qt Quick 小组件（`entry` 指向 .qml 文件），可直接使用 `Theme`、`Desk`、
  `Clock`、`Weather`、`Player`、`Todo` 和 `widget`（当前小组件岛）。

放到桌面上：点灵动岛的 ＋（新建），在“小组件”中选择它；或在“设置 → 小组件 → 自定义小组件”中点“添加到桌面”；
也可以让 AI 助手调用 `island.create`（kind=widget，widget=custom:<文件夹名>）。
完整说明见“设置 → 关于 → 使用说明”中的“自定义小组件”一节，以及“设置 → AI 与扩展 → 说明文档”（GUIDE.md）。
"""

THEME_SAMPLE = {
    "radius": 22,
    "smallRadius": 12,
    "glassStrength": 1.0,
    "shadow": 1.0,
    "motion": 1.0,
    "fontScale": 1.0,
}

HELLO_JSON = {
    "name": "你好，桌屿",
    "type": "html",
    "entry": "index.html",
    "size": [300, 190],
    "description": "示例网页小组件：显示问候语并记住点击次数。",
    "network": False,
    "version": "1.0",
}

HELLO_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  html, body { margin: 0; height: 100%; background: transparent; overflow: hidden;
               font-family: var(--deskisle-fontFamily, "Microsoft YaHei UI"), sans-serif;
               color: var(--deskisle-text, #fff); }
  .wrap { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; }
  h1 { margin: 0; font-size: 22px; font-weight: 600; }
  button { border: 0; border-radius: 999px; padding: 7px 16px; font: inherit; cursor: pointer;
           background: var(--deskisle-accent, #5aa9ff); color: var(--deskisle-onAccent, #fff); }
  small { opacity: .65; }
</style>
</head>
<body>
<div class="wrap">
  <h1 id="greet">你好</h1>
  <button id="btn">点我</button>
  <small id="count"></small>
</div>
<script>
  function hello() {
    var h = new Date().getHours();
    document.getElementById("greet").textContent = h < 6 ? "夜深了" : h < 12 ? "早上好" : h < 18 ? "下午好" : "晚上好";
  }
  function show() {
    var n = (window.deskisle && deskisle.config.clicks) || 0;
    document.getElementById("count").textContent = "已点击 " + n + " 次";
  }
  document.getElementById("btn").onclick = function () {
    if (!window.deskisle) { return; }
    deskisle.setConfig("clicks", (deskisle.config.clicks || 0) + 1);
    show();
  };
  hello(); show();
  if (window.deskisle) { deskisle.on("config", show); }
</script>
</body>
</html>
"""

QML_JSON = {
    "name": "QML 示例",
    "type": "qml",
    "entry": "Widget.qml",
    "size": [280, 170],
    "description": "示例 Qt Quick 小组件：跟随主题色的进度环，显示今天过去了多少。",
    "version": "1.0",
}

QML_SAMPLE = """import QtQuick

// Context objects available here: Theme, Desk, Clock, Weather, Player, Todo, widget.
Item {
    id: root
    property real dayProgress: 0

    function update() {
        var d = new Date()
        root.dayProgress = (d.getHours() * 3600 + d.getMinutes() * 60 + d.getSeconds()) / 86400
    }
    Timer { interval: 30000; running: true; repeat: true; triggeredOnStart: true; onTriggered: root.update() }

    Canvas {
        id: ring
        width: Math.min(root.width, root.height) - 24
        height: width
        anchors.centerIn: parent
        property real p: root.dayProgress
        property color accent: Theme.accent
        property color track: Theme.hairline
        onPChanged: requestPaint()
        onAccentChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            var c = width / 2, r = c - 8
            ctx.lineWidth = 9
            ctx.lineCap = "round"
            ctx.strokeStyle = track
            ctx.beginPath(); ctx.arc(c, c, r, 0, Math.PI * 2); ctx.stroke()
            ctx.strokeStyle = accent
            ctx.beginPath(); ctx.arc(c, c, r, -Math.PI / 2, -Math.PI / 2 + Math.PI * 2 * p); ctx.stroke()
        }
    }
    Column {
        anchors.centerIn: parent
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Math.round(root.dayProgress * 100) + "%"
            color: Theme.text
            font.pixelSize: 26
            font.family: Theme.fontFamily
            font.weight: Font.DemiBold
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "今天已过去"
            color: Theme.textDim
            font.pixelSize: 12
            font.family: Theme.fontFamily
        }
    }
}
"""


def color_hex(value) -> str:
    try:
        return value.name()
    except AttributeError:
        return str(value)


def theme_snapshot(theme) -> dict:
    """Plain JSON view of the theme for HTML widgets (``deskisle.theme``)."""
    if theme is None:
        return {"dark": True, "accent": "#5aa9ff", "text": "#ffffff"}
    data = {"dark": bool(theme.property("dark"))}
    for name in ("accent", "accentSoft", "onAccent", "text", "textDim", "textFaint", "hairline", "danger"):
        data[name] = color_hex(theme.property(name))
    data["fontFamily"] = str(theme.property("fontFamily") or "")
    data["radius"] = float(theme.property("radius") or 22)
    data["fontSize"] = float(theme.property("fontSize") or 13)
    return data


class CustomFolder(QObject):
    changed = Signal()
    widgetChanged = Signal(str)  # widget id whose files changed ("" = all)

    def __init__(self, desk, theme, root: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.desk = desk
        self.theme = theme
        self.data_root = Path(root)
        self._folder = Path()
        self._widgets: dict[str, dict] = {}
        self._problems: list[str] = []
        self._revision = 0
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule)
        self._watcher.fileChanged.connect(self._schedule)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.reload)
        prefs = getattr(desk, "preferences", None)
        self._folder = self._resolve(getattr(prefs, "custom_folder", "") if prefs is not None else "")

    # Setup -----------------------------------------------------------------------------------
    def _resolve(self, value: str) -> Path:
        value = (value or "").strip()
        return Path(value).expanduser() if value else self.data_root / "custom"

    def start(self) -> None:
        self.scaffold()
        self.reload()

    def set_folder(self, value: str) -> None:
        folder = self._resolve(value)
        if folder == self._folder:
            return
        self._folder = folder
        self.scaffold()
        self.reload()

    def scaffold(self) -> None:
        """Create the folder with a README and two sample widgets (never overwrites)."""
        folder = self._folder
        try:
            fresh = not folder.exists()
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "widgets").mkdir(exist_ok=True)
            readme = folder / "README.md"
            if not readme.exists():
                readme.write_text(README, encoding="utf-8")
            theme_file = folder / "theme.json"
            if not theme_file.exists():
                theme_file.write_text(json.dumps(THEME_SAMPLE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if fresh or not any((folder / "widgets").iterdir()):
                self._write_sample("hello", HELLO_JSON, {"index.html": HELLO_HTML})
                self._write_sample("qml-sample", QML_JSON, {"Widget.qml": QML_SAMPLE})
        except OSError:
            log.exception("could not prepare the custom folder %s", folder)

    def _write_sample(self, wid: str, manifest: dict, files: dict) -> None:
        target = self._folder / "widgets" / wid
        if target.exists():
            return
        target.mkdir(parents=True)
        (target / "widget.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                                            encoding="utf-8")
        for name, text in files.items():
            (target / name).write_text(text, encoding="utf-8")

    # Reloading ----------------------------------------------------------------------------------
    def _schedule(self, *_args) -> None:
        self._timer.start()

    @Slot()
    def reload(self) -> None:
        problems: list[str] = []
        if self.theme is not None:
            problems += ["theme.json：" + p for p in self.theme.load_custom(self._folder / "theme.json")]
        old = self._widgets
        widgets: dict[str, dict] = {}
        base = self._folder / "widgets"
        try:
            entries = sorted(p for p in base.iterdir() if p.is_dir()) if base.is_dir() else []
        except OSError:
            entries = []
        for path in entries:
            info = self._read_widget(path)
            if info.get("error"):
                problems.append("{0}：{1}".format(path.name, info["error"]))
            widgets[info["id"]] = info
        self._widgets = widgets
        self._problems = problems
        self._revision += 1
        self._rewatch()
        changed = [wid for wid in set(old) | set(widgets) if old.get(wid) != widgets.get(wid)]
        self.changed.emit()
        for wid in changed or [""]:
            self.widgetChanged.emit(wid)
        if self.desk is not None:
            for proxy in self.desk.proxies():
                if proxy.state.kind == "widget" and proxy.state.widget.startswith("custom:"):
                    proxy.notify()

    def _read_widget(self, path: Path) -> dict:
        wid = path.name
        info = {"id": wid, "name": wid, "type": "", "entry": "", "url": "", "path": str(path),
                "size": [300, 200], "description": "", "network": False, "version": "", "error": "",
                "stamp": 0.0}
        if not WIDGET_ID.match(wid):
            info["error"] = "文件夹名只能包含字母、数字、点、下划线和连字符"
            return info
        manifest = path / "widget.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8-sig"))
            if not isinstance(data, dict):
                raise ValueError("widget.json 顶层必须是对象")
        except FileNotFoundError:
            data = {}
            for candidate, kind in (("index.html", "html"), ("Widget.qml", "qml")):
                if (path / candidate).is_file():
                    data = {"type": kind, "entry": candidate}
                    break
            if not data:
                info["error"] = "缺少 widget.json"
                return info
        except (OSError, ValueError) as exc:
            info["error"] = "widget.json 无法解析：{0}".format(exc)
            return info
        kind = str(data.get("type") or "").lower()
        entry = str(data.get("entry") or ("Widget.qml" if kind == "qml" else "index.html"))
        if kind not in ("html", "qml"):
            kind = "qml" if entry.lower().endswith(".qml") else "html"
        target = (path / entry).resolve()
        try:
            target.relative_to(path.resolve())
        except ValueError:
            info["error"] = "entry 必须位于小组件文件夹内"
            return info
        if not target.is_file():
            info["error"] = "找不到入口文件 {0}".format(entry)
        size = data.get("size") or [300, 200]
        try:
            w, h = int(size[0]), int(size[1])
        except (TypeError, ValueError, IndexError):
            w, h = 300, 200
        try:
            stamp = max((p.stat().st_mtime for p in path.rglob("*") if p.is_file()), default=0.0)
        except OSError:
            stamp = 0.0
        info.update({
            "name": str(data.get("name") or wid)[:40],
            "type": kind,
            "entry": entry,
            "url": QUrl.fromLocalFile(str(target)).toString(),
            "size": [max(MIN_SIZE, min(MAX_SIZE, w)), max(MIN_SIZE // 2, min(MAX_SIZE, h))],
            "description": str(data.get("description") or "")[:200],
            "network": bool(data.get("network", False)),
            "version": str(data.get("version") or ""),
            "stamp": stamp,
        })
        return info

    def _rewatch(self) -> None:
        watched = self._watcher.directories() + self._watcher.files()
        if watched:
            self._watcher.removePaths(watched)
        paths = [self._folder, self._folder / "widgets", self._folder / "theme.json"]
        for info in self._widgets.values():
            base = Path(info["path"])
            paths.append(base)
            try:
                paths += [p for p in base.rglob("*") if p.is_file() and p.suffix.lower() in (
                    ".json", ".html", ".htm", ".js", ".css", ".qml", ".svg", ".png")][:64]
            except OSError:
                pass
        existing = [str(p) for p in paths if p.exists()]
        if existing:
            self._watcher.addPaths(existing)

    # Python API ----------------------------------------------------------------------------------
    @property
    def folder(self) -> Path:
        return self._folder

    @property
    def problems(self) -> list[str]:
        return list(self._problems)

    def widgets(self) -> list[dict]:
        return [dict(info) for info in self._widgets.values()]

    def widget(self, wid: str) -> dict | None:
        wid = wid[7:] if wid.startswith("custom:") else wid
        info = self._widgets.get(wid)
        return dict(info) if info is not None else None

    def widget_name(self, wid: str) -> str:
        info = self.widget(wid)
        return info["name"] if info else wid

    def status(self) -> dict:
        return {"folder": str(self._folder), "widgets": self.widgets(), "problems": self.problems,
                "revision": self._revision}

    # QML API -----------------------------------------------------------------------------------------
    def _get_folder(self) -> str:
        return str(self._folder)

    def _get_widgets(self) -> list:
        return self.widgets()

    def _get_problems(self) -> list:
        return self.problems

    def _get_revision(self) -> int:
        return self._revision

    folderPath = Property(str, _get_folder, notify=changed)
    widgetList = Property("QVariantList", _get_widgets, notify=changed)
    problemList = Property("QVariantList", _get_problems, notify=changed)
    revision = Property(int, _get_revision, notify=changed)

    @Slot(str, result="QVariantMap")
    def widgetInfo(self, wid: str):  # noqa: N802
        return self.widget(wid) or {}

    @Slot(str, result=str)
    def widgetUrl(self, wid: str) -> str:  # noqa: N802
        info = self.widget(wid)
        if not info or info.get("error"):
            return ""
        # The revision makes QML Loaders reload after a file change.
        return "{0}?rev={1}".format(info["url"], int(info.get("stamp", 0) * 1000) % 10_000_000)

    @Slot()
    def openFolder(self) -> None:  # noqa: N802
        if self.desk is not None:
            self.desk.openItem(str(self._folder))

    @Slot(str, result=bool)
    def addWidget(self, wid: str) -> bool:  # noqa: N802
        info = self.widget(wid)
        if info is None or self.desk is None:
            return False
        w, h = info["size"]
        return self.desk.add_island("widget", widget="custom:" + info["id"], title=info["name"],
                                    size=(w, h)) is not None

    @Slot(str, result=str)
    def createWidget(self, name: str) -> str:  # noqa: N802
        """Copy the HTML sample into a new widget folder; returns its id."""
        base = re.sub(r"[^A-Za-z0-9_.-]+", "-", (name or "my-widget").strip()).strip("-.") or "my-widget"
        wid, n = base[:40], 2
        while (self._folder / "widgets" / wid).exists():
            wid, n = "{0}-{1}".format(base[:36], n), n + 1
        manifest = dict(HELLO_JSON, name=name or wid, description="")
        try:
            self._write_sample(wid, manifest, {"index.html": HELLO_HTML})
        except OSError:
            log.exception("could not create widget %s", wid)
            return ""
        self.reload()
        return wid

    def remove_widget_files(self, wid: str) -> bool:
        """Delete a widget folder (agent command; asks for confirmation first)."""
        info = self.widget(wid)
        if info is None:
            return False
        try:
            shutil.rmtree(info["path"])
        except OSError:
            log.exception("could not delete widget %s", wid)
            return False
        self.reload()
        return True


__all__ = ["CustomFolder", "theme_snapshot", "color_hex"]

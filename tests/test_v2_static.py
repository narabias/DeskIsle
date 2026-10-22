"""Static checks of the 2.0 sources: icon names, settings search, QML compile,
shaders, 1.x -> 2.0 migration, theme rules and the custom widget folder."""

from __future__ import annotations

import ast
import json
import re
import shutil
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from tests import support

ROOT = support.ROOT
QML = support.QML_DIR
GLYPHS = set(re.findall(r'^"([a-z0-9-]+)":', (QML / "glyphs.js").read_text(encoding="utf-8"), re.M))
# Weather ids are drawn by WeatherIcon.qml from several glyphs ("cloud-sun" = cloud + sun).
WEATHER_IDS = {"sun", "moon", "cloud", "cloud-sun", "cloud-moon", "cloud-rain", "cloud-drizzle", "cloud-storm",
               "cloud-snow", "snowflake", "mist", "wind"}
# String literals on icon/name lines that are not glyphs (comparisons, licence names, actions).
NOT_GLYPHS = {"error", "warning", "success", "info", "qml", "html", "hide", "quit", "lunar-python", "pywin32",
              "pywinrt", "voidtools"}


def qml_files():
    return sorted(p for p in QML.glob("*.qml") if not p.name.startswith("_"))


class GlyphTests(unittest.TestCase):
    def test_table_is_well_formed(self) -> None:
        self.assertGreater(len(GLYPHS), 60)
        text = (QML / "glyphs.js").read_text(encoding="utf-8")
        self.assertIn(".pragma library", text)
        self.assertTrue((QML / "LICENSE-TABLER.txt").is_file(), "Tabler icons are MIT: keep the licence")
        names = re.findall(r'^"([a-z0-9-]+)":', text, re.M)
        self.assertEqual(len(names), len(set(names)), "duplicate glyph names")

    def test_qml_glyph_names_exist(self) -> None:
        prop = re.compile(r'\b(icon|glyph|iconName|name)\s*:\s*(.+)$')
        literal = re.compile(r'"([a-z][a-z0-9-]*)"')
        missing = []
        for path in qml_files():
            if path.name == "WeatherIcon.qml":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                match = prop.search(line.split("//")[0])
                if match is None:
                    continue
                for name in literal.findall(match.group(2)):
                    if name not in GLYPHS and name not in NOT_GLYPHS:
                        missing.append("{0}:{1} {2}".format(path.name, number, name))
        self.assertEqual(missing, [])

    def test_python_glyph_names_exist(self) -> None:
        missing = []
        for path in sorted((ROOT / "deskisle").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                values = []
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "item" and len(node.args) >= 3:
                    arg = node.args[2]
                    branches = [arg.body, arg.orelse] if isinstance(arg, ast.IfExp) else [arg]
                    values = [b.value for b in branches if isinstance(b, ast.Constant)]
                elif isinstance(node, ast.Dict):
                    values = [v.value for k, v in zip(node.keys, node.values)
                              if isinstance(k, ast.Constant) and k.value == "icon" and isinstance(v, ast.Constant)]
                for value in values:
                    allowed = GLYPHS | (WEATHER_IDS if path.name == "weather.py" else set())
                    if value and value not in allowed:
                        missing.append("{0}:{1} {2}".format(path.relative_to(ROOT), node.lineno, value))
        self.assertEqual(missing, [])

    def test_weather_ids_are_drawable(self) -> None:
        import inspect

        from deskisle.services import weather

        ids = {icon for _text, icon in weather.WMO.values()}
        ids |= set(re.findall(r'"([a-z-]+)"', inspect.getsource(weather.glyph_for)))
        self.assertLessEqual(ids, WEATHER_IDS)
        source = (QML / "WeatherIcon.qml").read_text(encoding="utf-8")
        for glyph in re.findall(r'name:\s*"([a-z-]+)"', source):
            self.assertIn(glyph, GLYPHS)


class SettingsSearchTests(unittest.TestCase):
    def test_every_search_entry_has_a_row(self) -> None:
        source = (QML / "Settings.qml").read_text(encoding="utf-8")
        pages = dict(re.findall(r'\{ id: "([a-z]+)", title: "[^"]+", icon: "[^"]+", file: "([A-Za-z]+\.qml)"', source))
        self.assertEqual(set(pages), {"appearance", "desktop", "widgets", "ai", "about"})
        block = source[source.index("searchIndex:"):source.index("readonly property var results")]
        entries = re.findall(r'\["([a-z]+)", "([^"]+)", "[^"]*"\]', block)
        self.assertGreater(len(entries), 40)
        for section, title in entries:
            self.assertIn(section, pages)
            text = (QML / pages[section]).read_text(encoding="utf-8")
            if section == "desktop":
                text += (QML / "RulesEditor.qml").read_text(encoding="utf-8")
            self.assertRegex(text, r'\btitle\s*:\s*"' + re.escape(title) + '"', "{0}: {1}".format(section, title))
        for name in pages.values():
            self.assertTrue((QML / name).is_file(), name)


class QmlCompileTests(unittest.TestCase):
    def test_all_components_compile(self) -> None:
        from PySide6.QtCore import QUrl
        from PySide6.QtQml import QQmlComponent, QQmlEngine

        support.qapp()
        engine = QQmlEngine()
        engine.addImportPath(str(QML))
        errors = []
        for path in qml_files():
            if path.name == "WebEngineSurface.qml":  # needs the optional QtWebEngine module
                continue
            component = QQmlComponent(engine, QUrl.fromLocalFile(str(path)))
            support.spin(1, until=lambda c=component: not c.isLoading())
            if component.isError():
                errors += [e.toString() for e in component.errors()]
        engine.deleteLater()
        self.assertEqual(errors, [])

    def test_shaders_are_baked(self) -> None:
        shaders = QML / "shaders"
        sources = sorted(p for p in shaders.iterdir() if p.suffix in (".frag", ".vert"))
        self.assertTrue(sources)
        for source in sources:
            baked = source.with_name(source.name + ".qsb")
            self.assertTrue(baked.is_file() and baked.stat().st_size > 100, baked.name)
        for path in qml_files():
            for ref in re.findall(r'shaders/([A-Za-z0-9_.-]+\.qsb)', path.read_text(encoding="utf-8")):
                self.assertTrue((shaders / ref).is_file(), "{0} -> {1}".format(path.name, ref))


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp(prefix="deskisle-migrate-"))

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, store, data: dict) -> None:
        store.state_path.parent.mkdir(parents=True, exist_ok=True)
        store.state_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def legacy(self) -> dict:
        return {
            "version": 2, "current_page_id": "p1",
            "pages": [{"id": "p1", "title": "主页", "islands": [
                {"id": "i1", "title": "动画", "kind": "html", "html_path": str(self.root / "a.html"),
                 "x": 10, "y": 10, "width": 300, "height": 200},
                {"id": "i2", "title": "文件", "x": 330, "y": 10, "width": 300, "height": 200,
                 "tabs": [{"id": "t1", "title": "全部", "items": [{"path": "C:/x.txt"}]}]}]}],
            "preferences": {"backdrop_source": "image", "backdrop_image": "C:/wall.png", "onboarding_done": True,
                            "theme_mode": "dark", "some_future_key": 42},
        }

    def test_1x_layout_is_backed_up_and_migrated(self) -> None:
        from deskisle.engine.app import load_state
        from deskisle.models import STATE_VERSION
        from deskisle.monitors import MonitorSpec, migrate_state
        from deskisle.layout import Rect
        from deskisle.storage import StateStore

        store = StateStore(self.root)
        self.write(store, self.legacy())
        state, note = load_state(store)
        self.assertIn("2.0", note)
        backups = list(store.snapshots_dir.glob("*升级到2.0之前的布局.json"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads(backups[0].read_text(encoding="utf-8"))["version"], 2)
        web, files = state.pages[0].islands
        self.assertEqual(web.kind, "web", "1.x html islands became web islands")
        self.assertTrue(web.web_url.startswith("file:"))
        self.assertFalse(web.html_allow_network, "local HTML stays offline")
        self.assertEqual(files.kind, "files")
        self.assertEqual(files.tabs[0].items[0].path, "C:/x.txt")
        prefs = state.preferences
        self.assertEqual((prefs.wallpaper_mode, prefs.wallpaper_image), ("image", "C:/wall.png"))
        self.assertTrue(prefs.onboarding_done)
        self.assertEqual(prefs.theme_mode, "dark")
        self.assertEqual(prefs.to_dict()["some_future_key"], 42, "unknown keys survive a round trip")
        monitor = MonitorSpec("m1", 1, Rect(0, 0, 1920, 1080), Rect(0, 0, 1920, 1040), True, 1.0, 1920, 1080)
        migrate_state(state, [monitor])
        self.assertEqual(state.version, STATE_VERSION)
        store.save(state)
        _again, note = load_state(store)
        self.assertEqual(note, "", "a migrated layout is not migrated (or backed up) again")
        self.assertEqual(len(list(store.snapshots_dir.glob("*升级到2.0之前的布局.json"))), 1)

    def test_backdrop_sources_map_to_wallpaper_modes(self) -> None:
        from deskisle.models import Preferences

        expected = {"wallpaper": "live", "image": "image", "black": "solid", "white": "solid",
                    "daynight": "solid", "": "live"}
        for source, mode in expected.items():
            self.assertEqual(Preferences.from_dict({"backdrop_source": source}).wallpaper_mode, mode, source)
        self.assertEqual(Preferences.from_dict({"backdrop_source": "black", "wallpaper_mode": "static"}).wallpaper_mode,
                         "static", "an explicit 2.0 value wins")

    def test_onboarding_flag(self) -> None:
        from deskisle.models import Preferences

        self.assertFalse(Preferences.from_dict({}).onboarding_done)
        self.assertTrue(Preferences.from_dict(Preferences(onboarding_done=True).to_dict()).onboarding_done)
        self.assertTrue(Preferences().wallpaper_mode in ("live", "static"), "dynamic wallpaper reading on")

    def test_broken_file_falls_back(self) -> None:
        from deskisle.engine.app import load_state
        from deskisle.storage import StateStore

        store = StateStore(self.root)
        store.state_path.parent.mkdir(parents=True, exist_ok=True)
        store.state_path.write_text("{not json", encoding="utf-8")
        state, note = load_state(store)
        self.assertEqual(note, "")
        self.assertIsNotNone(state)


class ThemeTests(unittest.TestCase):
    class Prefs:
        def __init__(self, mode: str, day: str = "07:00", night: str = "19:00") -> None:
            self.theme_mode, self.day_start, self.night_start = mode, day, night

    def test_fixed_and_time_modes(self) -> None:
        from deskisle.engine.style import is_daytime, theme_is_day

        noon, night = datetime(2025, 6, 1, 12, 0), datetime(2025, 6, 1, 23, 0)
        self.assertTrue(theme_is_day(self.Prefs("light"), night))
        self.assertFalse(theme_is_day(self.Prefs("dark"), noon))
        self.assertTrue(theme_is_day(self.Prefs("auto_time"), noon))
        self.assertFalse(theme_is_day(self.Prefs("auto_time"), night))
        # A day that wraps midnight (night shift): 20:00 -> 06:00 is "day".
        self.assertTrue(is_daytime("20:00", "06:00", datetime(2025, 6, 1, 23, 30)))
        self.assertTrue(is_daytime("20:00", "06:00", datetime(2025, 6, 2, 5, 59)))
        self.assertFalse(is_daytime("20:00", "06:00", datetime(2025, 6, 2, 12, 0)))
        self.assertTrue(is_daytime("08:00", "08:00", noon), "equal times = always day")
        self.assertTrue(is_daytime("bad", "19:00", noon), "bad input falls back to 07:00")

    def test_wallpaper_mode_has_hysteresis(self) -> None:
        from deskisle.engine.style import WALL_LIGHT_OFF, WALL_LIGHT_ON, theme_is_day

        prefs = self.Prefs("wallpaper")
        middle = (WALL_LIGHT_ON + WALL_LIGHT_OFF) / 2
        self.assertTrue(theme_is_day(prefs, wall_luminance=0.9))
        self.assertFalse(theme_is_day(prefs, wall_luminance=0.1))
        self.assertTrue(theme_is_day(prefs, wall_luminance=middle, was_day=True), "stays light")
        self.assertFalse(theme_is_day(prefs, wall_luminance=middle, was_day=False), "stays dark")
        noon = datetime(2025, 6, 1, 12, 0)
        self.assertTrue(theme_is_day(prefs, noon, wall_luminance=None), "unknown wallpaper: by time")

    def test_accent_comes_from_the_wallpaper(self) -> None:
        from PySide6.QtGui import QColor

        from deskisle.engine.style import ThemeBridge
        from deskisle.models import Preferences

        support.qapp()
        theme = ThemeBridge()
        theme.set_preferences(Preferences(theme_mode="dark"))
        theme.set_wallpaper_accent(QColor("#d02020"), 0.2)
        red = QColor(theme.property("accent"))
        theme.set_wallpaper_accent(QColor("#2040d0"), 0.2)
        blue = QColor(theme.property("accent"))
        self.assertGreater(red.redF(), red.blueF())
        self.assertGreater(blue.blueF(), blue.redF())
        self.assertEqual(QColor(theme.property("wallAccent")).name(), "#2040d0")
        theme.set_wallpaper_accent(QColor("#808080"), 0.2)  # grey wallpaper: still a usable accent
        grey = QColor(theme.property("accent"))
        self.assertGreaterEqual(grey.hslSaturationF(), 0.4)
        meta = theme.metaObject()
        names = [str(meta.property(i).name()) for i in range(meta.propertyCount())]
        self.assertNotIn("accentOverride", names)

    def test_theme_json_tokens(self) -> None:
        from deskisle.engine.style import DEFAULT_TOKENS, ThemeBridge

        support.qapp()
        folder = Path(tempfile.mkdtemp(prefix="deskisle-theme-"))
        try:
            theme = ThemeBridge()
            path = folder / "theme.json"
            path.write_text(json.dumps({"radius": 30, "motion": "fast", "accentName": "x", "$schema": "y"}),
                            encoding="utf-8")
            problems = theme.load_custom(path)
            self.assertEqual(len(problems), 1, problems)
            self.assertEqual(theme.tok("radius", 0), 30)
            self.assertEqual(theme.tok("motion", 0), DEFAULT_TOKENS["motion"], "bad values keep the default")
            self.assertEqual(theme.tok("accentName", ""), "x")
            path.write_text("[1, 2]", encoding="utf-8")
            self.assertTrue(theme.load_custom(path))
            self.assertEqual(theme.tok("radius", 0), DEFAULT_TOKENS["radius"])
            self.assertEqual(theme.load_custom(None), [])
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class CustomFolderTests(unittest.TestCase):
    def setUp(self) -> None:
        support.qapp()
        from deskisle.custom import CustomFolder

        self.root = Path(tempfile.mkdtemp(prefix="deskisle-custom-"))
        self.folder = CustomFolder(None, None, self.root)
        self.folder.start()
        self.widgets = self.folder.folder / "widgets"

    def tearDown(self) -> None:
        self.folder.deleteLater()
        shutil.rmtree(self.root, ignore_errors=True)

    def add(self, name: str, files: dict) -> None:
        target = self.widgets / name
        target.mkdir(parents=True, exist_ok=True)
        for file, text in files.items():
            (target / file).write_text(text, encoding="utf-8")

    def test_scaffold(self) -> None:
        self.assertEqual(self.folder.folder, self.root / "custom")
        self.assertTrue((self.folder.folder / "README.md").is_file())
        self.assertTrue((self.folder.folder / "theme.json").is_file())
        ids = {w["id"] for w in self.folder.widgets()}
        self.assertLessEqual({"hello", "qml-sample"}, ids)
        hello = self.folder.widget("custom:hello")
        self.assertEqual(hello["type"], "html")
        self.assertEqual(hello["error"], "")
        self.assertTrue(hello["url"].startswith("file:"))
        self.assertEqual(self.folder.widget("qml-sample")["type"], "qml")
        self.assertEqual(self.folder.problems, [])
        # A second start never overwrites the user's edits.
        (self.widgets / "hello" / "index.html").write_text("mine", encoding="utf-8")
        self.folder.start()
        self.assertEqual((self.widgets / "hello" / "index.html").read_text(encoding="utf-8"), "mine")

    def test_manifest_problems(self) -> None:
        self.add("no-manifest", {"index.html": "<p>hi</p>"})
        self.add("bad-json", {"widget.json": "{nope", "index.html": ""})
        self.add("escape", {"widget.json": json.dumps({"type": "html", "entry": "../../x.html"})})
        self.add("missing-entry", {"widget.json": json.dumps({"type": "html", "entry": "gone.html"})})
        self.add("huge", {"widget.json": json.dumps({"type": "qml", "entry": "Widget.qml", "size": [99999, 1]}),
                          "Widget.qml": "import QtQuick\nItem {}\n"})
        self.add("bad name!", {"index.html": ""})
        self.add("empty", {})
        self.folder.reload()
        info = {w["id"]: w for w in self.folder.widgets()}
        self.assertEqual(info["no-manifest"]["error"], "")
        self.assertEqual(info["no-manifest"]["type"], "html")
        self.assertIn("无法解析", info["bad-json"]["error"])
        self.assertIn("文件夹内", info["escape"]["error"])
        self.assertIn("gone.html", info["missing-entry"]["error"])
        self.assertIn("只能包含", info["bad name!"]["error"])
        self.assertIn("缺少 widget.json", info["empty"]["error"])
        w, h = info["huge"]["size"]
        self.assertLess(w, 99999)
        self.assertGreater(h, 1)
        self.assertGreaterEqual(len(self.folder.problems), 5)
        self.assertEqual(self.folder.status()["folder"], str(self.folder.folder))


if __name__ == "__main__":
    unittest.main()


class PackagingTests(unittest.TestCase):
    """The PyInstaller spec must keep what the app loads by name or imports in QML."""

    spec = (ROOT / "packaging" / "DeskIsle.spec").read_text(encoding="utf-8")

    def _spec_names(self, start: str, end: str) -> dict:
        source = self.spec[self.spec.index(start):self.spec.index(end)]
        namespace: dict = {}
        exec(compile(source, "DeskIsle.spec", "exec"), namespace)  # noqa: S102 - our own file
        return namespace

    def test_every_service_module_is_listed(self) -> None:
        app = (ROOT / "deskisle" / "engine" / "app.py").read_text(encoding="utf-8")
        loaded = set(re.findall(r'"(deskisle\.services\.\w+)"', app))
        self.assertGreaterEqual(len(loaded), 5)
        line = next(line for line in self.spec.splitlines() if line.startswith("SERVICES ="))
        namespace: dict = {}
        exec(line, namespace)  # noqa: S102
        self.assertLessEqual(loaded, set(namespace["SERVICES"]))
        for module in namespace["SERVICES"]:
            self.assertTrue((ROOT / (module.replace(".", "/") + ".py")).is_file(), module)

    def test_qml_imports_survive_the_filter(self) -> None:
        unused = self._spec_names("UNUSED_QML = (", "app.binaries = [")["_unused"]
        imports = set()
        for path in (ROOT / "deskisle" / "qml").glob("*.qml"):
            if path.name == "WebEngineSurface.qml":
                continue
            imports.update(re.findall(r"^import (Qt[\w.]*)", path.read_text(encoding="utf-8"), re.M))
        self.assertIn("QtQuick", imports)
        for module in sorted(imports):
            dest = "PySide6/qml/" + module.replace(".", "/") + "/qmldir"
            self.assertFalse(unused(dest), module)
        for library in ("Qt6Core.dll", "Qt6Gui.dll", "Qt6Qml.dll", "Qt6Quick.dll", "Qt6QuickEffects.dll",
                        "Qt6QuickShapes.dll", "Qt6Multimedia.dll", "Qt6MultimediaQuick.dll", "Qt6Network.dll",
                        "Qt6Svg.dll", "Qt6Widgets.dll", "deskisle/qml/Layer.qml"):
            self.assertFalse(unused("PySide6\\" + library), library)
        for library in ("Qt6WebEngineCore.dll", "Qt63DCore.dll", "Qt6Quick3D.dll", "libQt6Pdf.so.6"):
            self.assertTrue(unused("PySide6/" + library), library)

    def test_bundled_files_exist(self) -> None:
        for relative in ("deskisle/qml", "deskisle/assets", "deskisle/agent/GUIDE.md", "docs", "tools/cli_entry.py",
                         "tools/shell_menu_entry.py", "packaging/DeskIsle.ico", "README.md", "CHANGELOG.md",
                         "THIRD-PARTY-NOTICES.md", "LICENSE"):
            self.assertTrue((ROOT / relative).exists(), relative)
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        from deskisle import __version__

        self.assertEqual(version, __version__)
        iss = (ROOT / "packaging" / "installer.iss").read_text(encoding="utf-8")
        self.assertIn('#define AppVersion "{0}"'.format(version), iss)


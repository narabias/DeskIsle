"""2.0.1 fixes: todo dates / reminders, snapshot deletion, text colour, idle memory trim,
flip-clock menu, drag pixmap guard and the now-playing hint (pure Python, no app)."""

from __future__ import annotations

import datetime as dt
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from tests import support  # noqa: F401 - offscreen platform before Qt loads

from deskisle import models
from deskisle.services import nowplaying, todo

WED = dt.datetime(2026, 10, 21, 13, 48)          # a Wednesday afternoon


class _Island:
    def __init__(self, uid: str, title: str, items: list[dict]) -> None:
        self.id, self.title, self.kind, self.widget = uid, title, "widget", "todo"
        self.widget_config = {"items": items}


class _Desk:
    """The parts of the controller the todo service uses."""

    def __init__(self, *islands: _Island) -> None:
        self.state = SimpleNamespace(pages=[SimpleNamespace(islands=list(islands))])
        self.notices: list[tuple] = []

    def find_island(self, uid):
        for island in self.state.pages[0].islands:
            if island.id == uid:
                return self.state.pages[0], island
        return None, None

    def island_action(self, uid, name, args):
        assert name == "widgetConfig"
        self.find_island(uid)[1].widget_config.update(args)

    def show_notice(self, title, text="", kind="info", actions=None, timeout=4200):
        self.notices.append((title, text, kind, list(actions or []), timeout))
        return "n%d" % len(self.notices)


def _service(desk) -> todo.TodoService:
    support.qapp()
    service = todo.TodoService(desk)
    service._timer.stop()           # driven by hand below
    return service


class TodoDateTests(unittest.TestCase):
    def test_remind_at(self) -> None:
        self.assertEqual(todo.remind_at("2026-10-22"), dt.datetime(2026, 10, 22, 9, 0))   # date only: 09:00
        self.assertEqual(todo.remind_at("2026-10-22T18:30"), dt.datetime(2026, 10, 22, 18, 30))
        self.assertEqual(todo.remind_at("2026-10-22 07:05"), dt.datetime(2026, 10, 22, 7, 5))
        self.assertIsNone(todo.remind_at(""))
        self.assertIsNone(todo.remind_at("明天"))

    def test_calendar_marks_and_day_list(self) -> None:
        week = _Island("w", "工作", [
            {"id": "a", "text": "周报", "done": False, "due": "2026-10-22T18:00"},
            {"id": "b", "text": "买花", "done": False, "due": "2026-10-22"},
            {"id": "c", "text": "已交", "done": True, "due": "2026-10-22T08:00"},
            {"id": "d", "text": "昨天的", "done": False, "due": "2026-10-20T10:00"},
            {"id": "e", "text": "无日期", "done": False, "due": ""},
        ])
        home = _Island("h", "家", [{"id": "f", "text": "交电费", "done": False, "due": "2026-10-22T09:30"}])
        service = _service(_Desk(week, home))
        with mock.patch.object(todo, "_now", return_value=WED):
            marks = service.due_map()
            self.assertEqual(marks["2026-10-22"], {"count": 3, "overdue": False})    # done items do not count
            self.assertEqual(marks["2026-10-20"], {"count": 1, "overdue": True})
            self.assertEqual(set(marks), {"2026-10-20", "2026-10-22"})
            day = service.itemsOn("2026-10-22")
        self.assertEqual([i["text"] for i in day], ["交电费", "周报", "买花", "已交"])  # timed, all-day, done
        self.assertEqual(day[0]["list"], "家")
        self.assertEqual((day[0]["uid"], day[0]["id"], day[0]["time"]), ("h", "f", "09:30"))
        self.assertEqual(day[2]["time"], "")
        self.assertEqual(service.itemsOn("2026-10-23"), [])
        self.assertEqual(todo.TodoService(None).due_map(), {})

    def test_dates_in_the_past_do_not_remind(self) -> None:
        island = _Island("t", "待办", [])
        desk = _Desk(island)
        service = _service(desk)
        with mock.patch.object(todo, "_now", return_value=WED):
            past = service.add("t", "交周报 @今天 9")              # 09:00 already passed at 13:48
            future = service.add("t", "开会 @今天 15:00")
            service.setDue("t", future, "2026-10-21T10:00")         # moved into the past
            service.setDue("t", past, "2026-10-21T16:00")           # moved into the future
            service.check_reminders()
        items = {i["id"]: i for i in island.widget_config["items"]}
        self.assertTrue(items[future]["notified"])
        self.assertFalse(items[past]["notified"])
        self.assertEqual(desk.notices, [])


class TodoReminderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.island = _Island("t", "工作", [
            {"id": "soon", "text": "开会", "done": False, "due": "2026-10-21T14:00"},
            {"id": "missed", "text": "交周报", "done": False, "due": "2026-10-20T18:00"},
            {"id": "done", "text": "已完成", "done": True, "due": "2026-10-20T08:00"},
            {"id": "later", "text": "买菜", "done": False, "due": "2026-10-22"},
        ])
        self.desk = _Desk(self.island)
        self.service = _service(self.desk)
        self.changes: list[int] = []
        self.reminders: list[tuple] = []
        self.service.changed.connect(lambda: self.changes.append(1))
        self.service.reminder.connect(lambda title, text: self.reminders.append((title, text)))

    def check(self, when: dt.datetime) -> None:
        with mock.patch.object(todo, "_now", return_value=when):
            self.service.check_reminders()

    def item(self, item_id: str) -> dict:
        return next(i for i in self.island.widget_config["items"] if i["id"] == item_id)

    def test_missed_ones_are_summarised_once(self) -> None:
        self.check(WED)                                            # first pass after start-up
        self.assertEqual(len(self.desk.notices), 1)
        title, text, kind, actions, _timeout = self.desk.notices[0]
        self.assertEqual(title, "有 1 项待办已到期")
        self.assertIn("交周报", text)
        self.assertEqual(kind, "warning")
        self.assertTrue(self.item("missed")["notified"])
        self.assertNotIn("notified", self.item("done"))
        self.assertEqual(self.reminders, [("有 1 项待办已到期", "交周报")])
        self.check(WED + dt.timedelta(seconds=15))
        self.assertEqual(len(self.desk.notices), 1, "no repeat")

    def test_reminder_at_due_time_with_actions(self) -> None:
        self.check(WED)
        self.desk.notices.clear()
        self.check(dt.datetime(2026, 10, 21, 13, 59))
        self.assertEqual(self.desk.notices, [], "not yet")
        self.check(dt.datetime(2026, 10, 21, 14, 0, 10))
        self.assertEqual(len(self.desk.notices), 1)
        title, text, kind, actions, timeout = self.desk.notices[0]
        self.assertEqual(title, "待办提醒 · 工作")
        self.assertTrue(text.startswith("开会"))
        self.assertEqual(timeout, 0, "stays until answered")
        self.assertEqual([a["id"] for a in actions], ["todo.done:t/soon", "todo.snooze:t/soon"])
        self.assertTrue(self.item("soon")["notified"])
        # Remind again ten minutes after "10 分钟后".
        with mock.patch.object(todo, "_now", return_value=dt.datetime(2026, 10, 21, 14, 1)):
            self.service.snooze("t", "soon")
        self.assertFalse(self.item("soon")["notified"])
        self.assertEqual(self.item("soon")["snooze"], "2026-10-21T14:11")
        self.check(dt.datetime(2026, 10, 21, 14, 5))
        self.assertEqual(len(self.desk.notices), 1)
        self.check(dt.datetime(2026, 10, 21, 14, 11, 5))
        self.assertEqual(len(self.desk.notices), 2)
        self.assertNotIn("snooze", self.item("soon"))
        self.service.complete("t", "soon")
        self.assertTrue(self.item("soon")["done"])
        # Date-only items remind at 09:00 of their day.
        self.check(dt.datetime(2026, 10, 22, 8, 59))
        self.assertEqual(len(self.desk.notices), 2)
        self.check(dt.datetime(2026, 10, 22, 9, 0, 3))
        self.assertEqual(self.desk.notices[-1][0], "待办提醒 · 工作")
        self.assertTrue(self.desk.notices[-1][1].startswith("买菜"))

    def test_changed_only_when_something_changes(self) -> None:
        self.check(WED)
        first = len(self.changes)
        self.assertGreaterEqual(first, 1)
        self.check(WED + dt.timedelta(seconds=15))
        self.check(WED + dt.timedelta(seconds=30))
        self.assertEqual(len(self.changes), first, "a quiet tick repaints nothing")
        self.check(dt.datetime(2026, 10, 21, 14, 0, 30))            # "开会" became overdue
        self.assertEqual(len(self.changes), first + 1)

    def test_menu_actions_reach_the_service(self) -> None:
        from deskisle.engine import menus

        self.desk.services = {"todo": self.service}
        with mock.patch.object(todo, "_now", return_value=WED):
            menus.dispatch(self.desk, "todo.snooze:t/soon", {})
        self.assertEqual(self.item("soon")["snooze"], "2026-10-21T13:58")
        menus.dispatch(self.desk, "todo.done:t/soon", {})
        self.assertTrue(self.item("soon")["done"])
        menus.dispatch(self.desk, "todo.done:t/unknown", {})    # harmless
        del self.desk.services
        menus.dispatch(self.desk, "todo.done:t/later", {})       # no service: ignored
        self.assertFalse(self.item("later")["done"])


class SnapshotDeleteTests(unittest.TestCase):
    def setUp(self) -> None:
        from deskisle.storage import StateStore

        self.root = Path(tempfile.mkdtemp(prefix="deskisle-snap-"))
        self.store = StateStore(self.root / "data")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_only_snapshot_files_can_be_deleted(self) -> None:
        state = self.store.load()
        keep = self.store.save_snapshot(state, "保留")
        gone = self.store.save_snapshot(state, "删除")
        self.assertTrue(self.store.delete_snapshot(str(gone)))
        self.assertFalse(gone.exists())
        self.assertEqual(self.store.list_snapshots(), [keep])
        self.assertTrue(self.store.delete_snapshot(keep.name))          # a bare file name works too
        self.assertEqual(self.store.list_snapshots(), [])
        outside = self.root / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        sneaky = self.store.snapshots_dir / ".." / "outside.json"
        other = self.store.snapshots_dir / "notes.txt"
        other.write_text("x", encoding="utf-8")
        for target in (outside, sneaky, other, self.store.snapshots_dir / "missing.json", self.store.snapshots_dir):
            self.assertFalse(self.store.delete_snapshot(str(target)), target)
        self.assertTrue(outside.exists() and other.exists())


class PreferenceTests(unittest.TestCase):
    def test_new_preferences_round_trip(self) -> None:
        prefs = models.Preferences()
        self.assertEqual((prefs.text_color_mode, prefs.text_color, prefs.idle_trim), ("auto", "#FFFFFF", True))
        data = prefs.to_dict()
        data.update(text_color_mode="custom", text_color="#FFE8A3", idle_trim=False)
        loaded = models.Preferences.from_dict(data)
        self.assertEqual((loaded.text_color_mode, loaded.text_color.upper(), loaded.idle_trim),
                         ("custom", "#FFE8A3", False))
        self.assertEqual(models.Preferences.from_dict(loaded.to_dict()).to_dict(), loaded.to_dict())
        bad = models.Preferences.from_dict({"text_color_mode": "rainbow", "text_color": "not a colour"})
        self.assertEqual((bad.text_color_mode, bad.text_color), ("auto", "#FFFFFF"))
        self.assertEqual(bad.idle_trim, True)

    def test_text_colour_modes(self) -> None:
        from PySide6.QtGui import QColor

        from deskisle.engine.style import ThemeBridge

        support.qapp()
        theme = ThemeBridge()
        theme._timer.stop()
        prefs = models.Preferences.from_dict({"theme_mode": "dark"})
        theme.set_preferences(prefs)
        auto = theme._get_text().name()
        cases = {"light": "#f4f7fb", "dark": "#11161d"}
        for mode, expected in cases.items():
            theme.set_preferences(models.Preferences.from_dict({"theme_mode": "dark", "text_color_mode": mode}))
            self.assertEqual(theme._get_text().name(), expected, mode)
        self.assertEqual(auto, "#f4f7fb", "auto follows the dark theme")
        theme.set_preferences(models.Preferences.from_dict(
            {"theme_mode": "dark", "text_color_mode": "custom", "text_color": "#FFE8A3"}))
        self.assertEqual(theme._get_text().name(), "#ffe8a3")
        dim, faint = theme._get_text_dim(), theme._get_text_faint()
        self.assertEqual((dim.red(), dim.green(), dim.blue()), (0xFF, 0xE8, 0xA3))
        self.assertGreater(theme._get_text().alpha(), dim.alpha())
        self.assertGreater(dim.alpha(), faint.alpha())
        self.assertIsInstance(theme._get_accent(), QColor)

    def test_theme_signal_only_on_real_changes(self) -> None:
        from PySide6.QtGui import QColor

        from deskisle.engine.style import ThemeBridge

        support.qapp()
        theme = ThemeBridge()
        theme._timer.stop()
        theme.set_preferences(models.Preferences.from_dict({"theme_mode": "dark"}))
        seen: list[int] = []
        theme.changed.connect(lambda: seen.append(1))
        for _ in range(5):                                   # a live wallpaper repeating itself
            theme.set_wallpaper_accent(QColor("#5AA9FF"), 0.351)
            theme.reevaluate()
        self.assertLessEqual(len(seen), 1)
        before = len(seen)
        theme.set_wallpaper_accent(QColor("#FF8800"), 0.351)
        self.assertEqual(len(seen), before + 1)
        theme.set_preferences(models.Preferences.from_dict({"theme_mode": "dark", "text_color_mode": "dark"}))
        self.assertEqual(len(seen), before + 2)


class ClockMenuTests(unittest.TestCase):
    def test_flip_clock_has_no_seconds_switch(self) -> None:
        from deskisle.engine import menus

        desk = SimpleNamespace(preferences=models.Preferences())
        for style, has_seconds in (("split", False), ("digital", True), ("analog", True)):
            island = SimpleNamespace(widget="clock", widget_config={"style": style})
            ids = [e.get("id") for e in menus.widget_entries(desk, island)]
            self.assertEqual("widget.clockSeconds" in ids, has_seconds, style)
            self.assertIn("widget.clockStyle", ids)


class PlatformFallbackTests(unittest.TestCase):
    def test_drag_icon_without_sizes(self) -> None:
        from PySide6.QtCore import QSize

        from deskisle.engine.icons import IconProvider

        support.qapp()
        provider = IconProvider()
        path = str(Path(__file__))
        for args in ((None, None), (QSize(), QSize(48, 48)), (QSize(), QSize())):
            image = provider.requestImage(path + "?s=48", *args)
            self.assertFalse(image.isNull(), args)

    def test_memory_helpers_are_safe_everywhere(self) -> None:
        from deskisle import native_win

        usage = native_win.memory_usage()
        self.assertIsInstance(usage, dict)
        for key in ("self", "web", "web_count"):
            self.assertIsInstance(usage.get(key, 0), int)
        self.assertIn(native_win.trim_working_set(), (True, False))

    def test_now_playing_hint(self) -> None:
        support.qapp()
        self.assertIn("SMTC", nowplaying.NETEASE_HINT)
        service = nowplaying.NowPlayingService(demo=True)
        try:
            self.assertEqual(service.hint, "")
        finally:
            service.shutdown()


if __name__ == "__main__":
    unittest.main()

"""2.0 widget services: clock (农历), weather parsing, todo quick syntax, Everything IPC, now playing."""

from __future__ import annotations

import datetime as dt
import struct
import unittest

from tests import support  # noqa: F401 - offscreen platform before Qt loads

from deskisle.services import clock, everything, nowplaying, todo, weather

WED = dt.datetime(2026, 10, 21, 13, 48)          # a Wednesday afternoon


class ClockTests(unittest.TestCase):
    @unittest.skipIf(clock.Solar is None, "lunar_python is not installed")
    def test_lunar_calendar(self) -> None:
        info = clock.lunar_info(dt.date(2024, 2, 10))
        self.assertEqual(info["text"], "正月初一")
        self.assertEqual(info["year"], "甲辰龙年")
        self.assertIn("春节", info["festivals"])
        self.assertEqual(clock.lunar_info(dt.date(2024, 12, 21))["term"], "冬至")
        self.assertLessEqual(len(info["yi"]), 4)

    def test_month_grid_is_six_weeks_from_monday(self) -> None:
        support.qapp()
        service = clock.ClockService(demo=True)
        cells = service.monthGrid(2024, 2)
        self.assertEqual(len(cells), 42)
        self.assertEqual(cells[0]["day"], 29)            # Monday 29 January 2024
        self.assertFalse(cells[0]["inMonth"])
        self.assertTrue(cells[3]["inMonth"] and cells[3]["day"] == 1)
        self.assertTrue(cells[5]["weekend"] and cells[6]["weekend"])
        if clock.Solar is not None:
            spring = next(c for c in cells if c["inMonth"] and c["day"] == 10)
            self.assertEqual(spring["lunar"], "春节")
            self.assertTrue(spring["special"])
        self.assertEqual(service.lunarFor(2024, 2, 30), {})      # invalid dates are harmless


class WeatherTests(unittest.TestCase):
    def test_wind_in_beaufort_levels(self) -> None:
        self.assertEqual(weather.wind_text(45, 10), "东北风 2级")
        self.assertEqual(weather.wind_text(200, 130), "南风 12级")
        self.assertEqual(weather.wind_text(None, 0), "0级")
        self.assertEqual(weather.wind_text("x", "y"), "")

    def test_caption_glyphs(self) -> None:
        cases = {"雷阵雨": "cloud-storm", "小雪": "snowflake", "毛毛雨": "cloud-drizzle", "中雨": "cloud-rain",
                 "雾霾": "mist", "阴": "cloud", "局部多云": "cloud-sun", "晴": "sun", "大风": "wind", "": "cloud"}
        for caption, glyph in cases.items():
            self.assertEqual(weather.glyph_for(caption), glyph, caption)
        self.assertEqual(weather.glyph_for("晴", night=True), "moon")
        self.assertEqual(weather.glyph_for("多云", night=True), "cloud-moon")

    def test_every_wmo_code_has_text_and_icon(self) -> None:
        for code, (text, icon) in weather.WMO.items():
            self.assertTrue(text and icon, code)

    def test_parse_open_meteo(self) -> None:
        payload = {
            "current": {"temperature_2m": 21.6, "apparent_temperature": 20.2, "relative_humidity_2m": 55,
                        "weather_code": 2, "is_day": 0, "wind_speed_10m": 14.0, "wind_direction_10m": 270},
            "daily": {"time": ["2026-10-21", "2026-10-22"], "weather_code": [61, 0],
                      "temperature_2m_max": [24.4, 26.0], "temperature_2m_min": [15.5, 14.2],
                      "precipitation_probability_max": [80, 0]},
        }
        data = weather.parse_open_meteo(payload, now=WED)
        self.assertEqual((data["temp"], data["feels"], data["humidity"]), (22, 20, 55))
        self.assertEqual((data["text"], data["icon"], data["night"]), ("多云", "cloud-moon", True))
        self.assertEqual(data["wind"], "西风 3级")
        self.assertEqual([d["label"] for d in data["days"]], ["今天", "周四"])
        self.assertEqual(data["days"][0]["icon"], "cloud-rain")
        self.assertEqual((data["high"], data["low"]), (24, 16))

    def test_parse_msn(self) -> None:
        payload = {"value": [{"responses": [{
            "source": {"location": {"Name": "hangzhou"}, "coordinates": {"lat": 30.3, "lon": 120.2}},
            "weather": [{
                "current": {"temp": 23.4, "feels": 24, "cap": "局部多云", "daytime": "d", "rh": 62, "windDir": 45,
                            "windSpd": 12, "uvDesc": "中等", "aqi": 38, "aqiSeverity": "空气优", "baro": 1016, "vis": 14},
                "forecast": {"days": [
                    {"daily": {"valid": "2026-10-21T00:00:00", "day": {"cap": "多云"}, "tempHi": 26, "tempLo": 17,
                               "precip": 10}},
                    {"daily": {"valid": "2026-10-22T00:00:00", "pvdrCap": "小雨", "tempHi": 22, "tempLo": 16}},
                ]},
            }],
        }]}]}
        data = weather.parse_msn(payload, now=WED)
        self.assertEqual(data["city"], "Hangzhou")
        self.assertEqual((data["temp"], data["icon"], data["wind"]), (23, "cloud-sun", "东北风 3级"))
        self.assertEqual([d["label"] for d in data["days"]], ["今天", "周四"])
        self.assertEqual(data["days"][1]["icon"], "cloud-rain")
        self.assertEqual((data["lat"], data["lon"]), (30.3, 120.2))

    def test_demo_forecast_uses_real_weekdays(self) -> None:
        data = weather.demo_data()
        self.assertEqual(data["days"][0]["label"], "今天")
        tomorrow = dt.date.today() + dt.timedelta(days=1)
        self.assertEqual(data["days"][1]["label"], weather.WEEKDAYS[tomorrow.weekday()])

    def test_position_is_coarse(self) -> None:
        self.assertEqual(weather.coarse((30.274089, 120.155070)), (30.27, 120.16))
        self.assertIsNone(weather.coarse(None))
        self.assertIsNone(weather.coarse(("x", 1)))

    def test_nothing_is_requested_without_a_weather_island(self) -> None:
        from types import SimpleNamespace

        from PySide6.QtWidgets import QApplication

        QApplication.instance() or QApplication([])
        island = SimpleNamespace(kind="widget", widget="clock")
        desk = SimpleNamespace(state=SimpleNamespace(pages=[SimpleNamespace(islands=[island])]),
                               preferences=None)
        service = weather.WeatherService(desk)
        calls: list = []
        service._fetch = lambda *args: calls.append(args)
        service._locator.locate = lambda done: calls.append("locate")
        try:
            service.refresh(False)
            self.assertEqual(calls, [], "no location / network without a weather island")
            self.assertFalse(service.loading)
            self.assertIn("没有天气小组件", service.status)
            island.widget = "weather"
            service._islands_changed()
            self.assertTrue(calls, "the first weather island starts a refresh")
        finally:
            service.shutdown()       # kept alive: its start-up timer may still fire later (harmless)


class TodoTests(unittest.TestCase):
    def test_quick_due_syntax(self) -> None:
        cases = {
            "明天 18:00": "2026-10-22T18:00", "明天18": "2026-10-22T18:00", "今天 9": "2026-10-21T09:00",
            "今晚八点半": "2026-10-21T20:30", "明早七点二十分": "2026-10-22T07:20", "后天": "2026-10-23",
            "周五 下午3点半": "2026-10-23T15:30", "周三": "2026-10-21", "下周一": "2026-10-26",
            "周六十点": "2026-10-24T10:00", "星期天": "2026-10-25", "2025-01-31": "2025-01-31",
            "1-31": "2027-01-31", "10/25": "2026-10-25", "2026年11月3日 8:30": "2026-11-03T08:30",
            "20:00": "2026-10-21T20:00", "9:00": "2026-10-22T09:00", "中午1点": "2026-10-22T13:00",
            "明天 25:00": "2026-10-22", "买菜": "", "": "", "13-45": "",
        }
        for text, expected in cases.items():
            self.assertEqual(todo.quick_due(text, WED), expected, text)

    def test_due_labels(self) -> None:
        self.assertEqual(todo.due_label("2026-10-21T18:00", WED), "今天 18:00")
        self.assertEqual(todo.due_label("2026-10-22", WED), "明天")
        self.assertEqual(todo.due_label("2026-10-20", WED), "昨天")
        self.assertEqual(todo.due_label("2026-10-24", WED), "周六")
        self.assertEqual(todo.due_label("2026-12-01T08:00", WED), "12-01 08:00")
        self.assertEqual(todo.due_label("garbage", WED), "")

    def test_service_add_toggle_and_store(self) -> None:
        support.qapp()

        class Island:
            id, kind, widget = "t1", "widget", "todo"

            def __init__(self) -> None:
                self.widget_config = {}

        class Desk:
            def __init__(self) -> None:
                self.island = Island()

            def find_island(self, uid):
                return (None, self.island) if uid == "t1" else (None, None)

            def island_action(self, uid, name, args):
                assert name == "widgetConfig"
                self.island.widget_config.update(args)

        desk = Desk()
        service = todo.TodoService(desk)
        self.assertEqual(service.add("t1", "   "), "")
        first = service.add("t1", "交周报 @明天 18:00")
        service.add("t1", "@明天")                       # only a date: keep the text
        items = service.list("t1")
        self.assertEqual([i["text"] for i in items], ["交周报", "@明天"])
        self.assertTrue(items[0]["due"].endswith("T18:00"))
        service.toggle("t1", first)
        self.assertTrue(service.list("t1")[0]["done"])
        service.clearDone("t1")
        self.assertEqual([i["text"] for i in service.list("t1")], ["@明天"])
        self.assertEqual(service.list("missing"), [])


class EverythingTests(unittest.TestCase):
    def test_query_packet(self) -> None:
        packet = everything.pack_query("报告 docx", 0x1234, everything.REPLY_BASE + 7, max_results=20)
        header = struct.unpack_from("<7I", packet, 0)
        self.assertEqual(header[0], 0x1234)
        self.assertEqual(header[1], everything.REPLY_BASE + 7)
        self.assertEqual(header[4], 20)
        self.assertEqual(header[5], everything.REQUEST_NAME | everything.REQUEST_PATH)
        self.assertEqual(packet[28:].decode("utf-16-le"), "报告 docx\0")

    def test_parse_list2(self) -> None:
        entries = [("季度报告.docx", "C:\\Users\\me\\Desktop", 0), ("工作", "D:\\", everything.ITEM_FOLDER)]
        flags = everything.REQUEST_NAME | everything.REQUEST_PATH
        head = struct.pack("<5I", 99, len(entries), 0, flags, 1)
        table = b""
        blob = b""
        base = 20 + 8 * len(entries)
        for name, folder, item_flags in entries:
            table += struct.pack("<2I", item_flags, base + len(blob))
            for text in (name, folder):
                blob += struct.pack("<I", len(text)) + (text + "\0").encode("utf-16-le")
        total, results = everything.parse_list2(head + table + blob)
        self.assertEqual(total, 99)
        self.assertEqual(results[0]["path"], "C:\\Users\\me\\Desktop\\季度报告.docx")
        self.assertFalse(results[0]["isDir"])
        self.assertEqual(results[1]["path"], "D:\\工作")
        self.assertTrue(results[1]["isDir"])
        self.assertEqual(everything.parse_list2(b"short"), (0, []))
        self.assertEqual(everything.parse_list2(head + table[:4]), (99, []))    # truncated: no crash

    def test_ranking(self) -> None:
        terms = everything.split_terms("  Report  2025 ")
        self.assertEqual(terms, ["report", "2025"])
        self.assertEqual(everything.score("notes.txt", terms), -1)
        self.assertLess(everything.score("report-2025.pdf", terms), everything.score("myreport2025.pdf", terms))
        self.assertLess(everything.score("report 2025.pdf", terms),
                        everything.score("report 2025 final version.pdf", terms))


class NowPlayingTests(unittest.TestCase):
    def test_friendly_app_names(self) -> None:
        self.assertEqual(nowplaying.friendly_app("Spotify.exe"), "Spotify")
        self.assertEqual(nowplaying.friendly_app("C:\\Program Files\\foo\\Player.exe"), "Player")
        self.assertEqual(nowplaying.friendly_app("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic"), "媒体播放器")
        self.assertEqual(nowplaying.friendly_app("com.squirrel.someapp"), "Someapp")
        self.assertEqual(nowplaying.friendly_app(""), "")

    def test_timespans(self) -> None:
        self.assertEqual(nowplaying._seconds(None), 0.0)
        self.assertEqual(nowplaying._seconds(dt.timedelta(minutes=2, seconds=3)), 123.0)
        self.assertEqual(nowplaying._seconds(30_000_000), 3.0)
        self.assertEqual(nowplaying._seconds("x"), 0.0)

    def test_cover_accent_is_readable(self) -> None:
        from PySide6.QtGui import QColor, QImage

        self.assertEqual(nowplaying.dominant_color(QImage()).name(), "#5aa9ff")
        image = QImage(32, 32, QImage.Format.Format_RGB32)
        image.fill(QColor("#101060"))
        color = nowplaying.dominant_color(image)
        self.assertGreaterEqual(color.valueF(), 0.44)
        self.assertGreater(color.blueF(), color.redF())

    def test_demo_session(self) -> None:
        support.qapp()
        service = nowplaying.NowPlayingService(demo=True)
        try:
            support.spin(300)
            snap = service.snapshot()
            self.assertTrue(snap.get("title"))
            self.assertEqual(snap.get("status"), "playing")
            self.assertTrue(service.playing)
            first = service.currentPosition()
            service.playPause()
            support.spin(100)
            self.assertEqual(service.snapshot().get("status"), "paused")
            self.assertFalse(service.playing)
            self.assertGreaterEqual(service.currentPosition(), first)
            service.next()
            self.assertEqual(service.title, "Paper Planes")
            self.assertTrue(service.playing)
            service.seek(30.0)
            self.assertAlmostEqual(service.currentPosition(), 30.0, delta=1.0)
            service.selectSession("demo2")
            self.assertEqual(service.app, "Chrome")
        finally:
            service.shutdown()


if __name__ == "__main__":
    unittest.main()

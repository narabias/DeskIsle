"""Weather widget back-end.

Same source as the Windows weather flyout (MSN Weather) - including its IP based
location when no position is known - with Open-Meteo (CC BY 4.0) as fallback.
Location: the Windows location service (pywinrt Geolocator) when allowed,
otherwise a city chosen in the settings (Open-Meteo geocoding search).

Privacy: nothing is requested (no location, no network) while no weather island
exists on any preset - only an explicit refresh (settings, agent) does.  The
position leaves the machine rounded to two decimals (about 1 km).
"""

from __future__ import annotations

import datetime as _dt
import logging
import sys
import threading
import time
from urllib.parse import quote, urlencode

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

from .base import Http

log = logging.getLogger("deskisle.weather")
MSN_URL = "https://api.msn.com/weather/overview"
MSN_KEY = "UhJ4G66OjyLbn9mXARgajXLiLw6V75sHnfpU60aJBB"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
REFRESH_MS = 20 * 60 * 1000
WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

# WMO weather codes (Open-Meteo) -> (text, glyph)
WMO = {
    0: ("晴", "sun"), 1: ("晴间多云", "cloud-sun"), 2: ("多云", "cloud-sun"), 3: ("阴", "cloud"),
    45: ("雾", "mist"), 48: ("冻雾", "mist"), 51: ("毛毛雨", "cloud-drizzle"), 53: ("毛毛雨", "cloud-drizzle"),
    55: ("毛毛雨", "cloud-drizzle"), 56: ("冻毛毛雨", "cloud-drizzle"), 57: ("冻毛毛雨", "cloud-drizzle"),
    61: ("小雨", "cloud-rain"), 63: ("中雨", "cloud-rain"), 65: ("大雨", "cloud-rain"),
    66: ("冻雨", "cloud-rain"), 67: ("冻雨", "cloud-rain"), 71: ("小雪", "snowflake"), 73: ("中雪", "snowflake"),
    75: ("大雪", "snowflake"), 77: ("米雪", "snowflake"), 80: ("阵雨", "cloud-rain"), 81: ("阵雨", "cloud-rain"),
    82: ("强阵雨", "cloud-rain"), 85: ("阵雪", "snowflake"), 86: ("强阵雪", "snowflake"),
    95: ("雷阵雨", "cloud-storm"), 96: ("雷阵雨伴冰雹", "cloud-storm"), 99: ("雷阵雨伴冰雹", "cloud-storm"),
}
DIRECTIONS = ("北风", "东北风", "东风", "东南风", "南风", "西南风", "西风", "西北风")


def glyph_for(caption: str, night: bool = False) -> str:
    """Our icon for an MSN caption such as “局部多云” / “小雨”."""
    text = caption or ""
    if "雷" in text:
        return "cloud-storm"
    if "雪" in text or "冰" in text:
        return "snowflake"
    if "毛毛雨" in text:
        return "cloud-drizzle"
    if "雨" in text:
        return "cloud-rain"
    if "雾" in text or "霾" in text or "沙" in text or "尘" in text:
        return "mist"
    if "阴" in text:
        return "cloud"
    if "云" in text:
        return "cloud-moon" if night else "cloud-sun"
    if "风" in text:
        return "wind"
    if "晴" in text:
        return "moon" if night else "sun"
    return "cloud"


def wind_text(direction_deg, speed_kmh) -> str:
    try:
        speed = float(speed_kmh)
    except (TypeError, ValueError):
        return ""
    name = ""
    try:
        name = DIRECTIONS[int((float(direction_deg) % 360 + 22.5) // 45) % 8]
    except (TypeError, ValueError):
        pass
    # Beaufort scale (级) as Chinese forecasts use it.
    limits = (1, 6, 12, 20, 29, 39, 50, 62, 75, 89, 103, 118)
    level = next((i for i, limit in enumerate(limits) if speed < limit), 12)
    return "{0} {1}级".format(name, level).strip()


def _num(value, digits: int = 0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return round(number, digits) if digits else int(round(number))


def parse_msn(payload: dict, now: _dt.datetime | None = None) -> dict:
    """Normalise an MSN ``weather/overview`` response."""
    response = payload["value"][0]["responses"][0]
    weather = response["weather"][0]
    current = weather["current"]
    source = response.get("source", {}) or {}
    location = source.get("location", {}) or {}
    night = str(current.get("daytime", "d")) == "n" or str(current.get("symbol", "d")).startswith("n")
    caption = current.get("cap") or current.get("pvdrCap") or ""
    days = []
    for entry in (weather.get("forecast", {}) or {}).get("days", [])[:7]:
        daily = entry.get("daily", {}) or {}
        valid = str(daily.get("valid", ""))[:10]
        try:
            date = _dt.date.fromisoformat(valid)
            label = WEEKDAYS[date.weekday()]
        except ValueError:
            date, label = None, ""
        cap = (daily.get("day") or {}).get("cap") or daily.get("pvdrCap") or ""
        days.append({"date": valid, "label": label, "text": cap, "icon": glyph_for(cap),
                     "high": _num(daily.get("tempHi")), "low": _num(daily.get("tempLo")),
                     "precip": _num(daily.get("precip"))})
    today = (now or _dt.datetime.now()).date().isoformat()
    if days and days[0]["date"] == today:
        days[0]["label"] = "今天"
    name = str(location.get("Name") or "")
    return {
        "ok": True, "source": "MSN 天气",
        "city": name[:1].upper() + name[1:] if name.isascii() else name,
        "temp": _num(current.get("temp")), "feels": _num(current.get("feels")),
        "text": caption, "icon": glyph_for(caption, night), "night": night,
        "humidity": _num(current.get("rh")), "wind": wind_text(current.get("windDir"), current.get("windSpd")),
        "uv": current.get("uvDesc") or "", "aqi": _num(current.get("aqi")), "aqiText": current.get("aqiSeverity") or "",
        "pressure": _num(current.get("baro")), "visibility": _num(current.get("vis")),
        "high": days[0]["high"] if days else None, "low": days[0]["low"] if days else None,
        "days": days,
        "lat": (source.get("coordinates") or {}).get("lat"), "lon": (source.get("coordinates") or {}).get("lon"),
    }


def parse_open_meteo(payload: dict, now: _dt.datetime | None = None) -> dict:
    current = payload.get("current", {}) or {}
    daily = payload.get("daily", {}) or {}
    code = int(current.get("weather_code", 3) or 0)
    night = not bool(current.get("is_day", 1))
    text, icon = WMO.get(code, ("多云", "cloud"))
    if night and icon == "sun":
        icon = "moon"
    elif night and icon == "cloud-sun":
        icon = "cloud-moon"
    days = []
    times = daily.get("time", []) or []
    for i, valid in enumerate(times[:7]):
        try:
            label = WEEKDAYS[_dt.date.fromisoformat(valid).weekday()]
        except ValueError:
            label = ""
        dcode = int((daily.get("weather_code") or [3])[i] or 0)
        dtext, dicon = WMO.get(dcode, ("多云", "cloud"))
        days.append({"date": valid, "label": label, "text": dtext, "icon": dicon,
                     "high": _num((daily.get("temperature_2m_max") or [None])[i]),
                     "low": _num((daily.get("temperature_2m_min") or [None])[i]),
                     "precip": _num((daily.get("precipitation_probability_max") or [None])[i])})
    today = (now or _dt.datetime.now()).date().isoformat()
    if days and days[0]["date"] == today:
        days[0]["label"] = "今天"
    return {
        "ok": True, "source": "Open-Meteo",
        "city": "", "temp": _num(current.get("temperature_2m")), "feels": _num(current.get("apparent_temperature")),
        "text": text, "icon": icon, "night": night, "humidity": _num(current.get("relative_humidity_2m")),
        "wind": wind_text(current.get("wind_direction_10m"), current.get("wind_speed_10m")),
        "uv": "", "aqi": None, "aqiText": "", "pressure": None, "visibility": None,
        "high": days[0]["high"] if days else None, "low": days[0]["low"] if days else None, "days": days,
    }


DEMO = {
    "ok": True, "source": "演示数据", "city": "杭州", "temp": 23, "feels": 24, "text": "局部多云", "icon": "cloud-sun",
    "night": False, "humidity": 62, "wind": "东北风 3级", "uv": "中等", "aqi": 38, "aqiText": "空气优",
    "pressure": 1016, "visibility": 14, "high": 26, "low": 17,
    "days": [{"date": "", "label": "今天", "text": "局部多云", "icon": "cloud-sun", "high": 26, "low": 17, "precip": 10},
             {"date": "", "label": "周三", "text": "小雨", "icon": "cloud-rain", "high": 22, "low": 16, "precip": 70},
             {"date": "", "label": "周四", "text": "阴", "icon": "cloud", "high": 21, "low": 15, "precip": 30},
             {"date": "", "label": "周五", "text": "晴", "icon": "sun", "high": 25, "low": 14, "precip": 0},
             {"date": "", "label": "周六", "text": "晴", "icon": "sun", "high": 27, "low": 16, "precip": 0}],
}


def demo_data() -> dict:
    """Demo forecast with real dates (labels follow today's weekday)."""
    data = dict(DEMO)
    today = _dt.date.today()
    days = []
    for index, day in enumerate(DEMO["days"]):
        date = today + _dt.timedelta(days=index)
        days.append(dict(day, date=date.isoformat(), label="今天" if index == 0 else WEEKDAYS[date.weekday()]))
    data["days"] = days
    return data


class _Locator:
    """Windows location service (pywinrt).  Runs its async call on a thread."""

    def __init__(self) -> None:
        self.available = False
        if sys.platform == "win32":
            try:
                import winrt.windows.devices.geolocation  # noqa: F401
                import winrt.windows.foundation  # noqa: F401  (async operations)

                self.available = True
            except Exception:
                self.available = False

    def locate(self, done) -> None:
        if not self.available:
            done(None, "定位组件不可用")
            return

        def work() -> None:
            import asyncio

            async def run():
                from winrt.windows.devices.geolocation import GeolocationAccessStatus, Geolocator

                status = await Geolocator.request_access_async()
                if status != GeolocationAccessStatus.ALLOWED:
                    return None, "Windows 定位未开启"
                locator = Geolocator()
                position = await locator.get_geoposition_async()
                point = position.coordinate.point.position
                return (float(point.latitude), float(point.longitude)), ""

            try:
                result, error = asyncio.run(run())
            except Exception as exc:  # pragma: no cover - Windows only
                result, error = None, "定位失败：{0}".format(exc)
            done(result, error)

        threading.Thread(target=work, name="deskisle-locate", daemon=True).start()


def coarse(position):
    """(lat, lon) rounded to two decimals (~1 km): enough for weather, kinder to privacy."""
    if not position:
        return position
    try:
        return round(float(position[0]), 2), round(float(position[1]), 2)
    except (TypeError, ValueError, IndexError):
        return None


class WeatherService(QObject):
    changed = Signal()
    searchFinished = Signal("QVariantList")
    _located = Signal(object, str)

    def __init__(self, desk=None, demo: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.desk = desk
        self.demo = demo
        self._http = Http(self)
        self._data: dict = demo_data() if demo else {"ok": False}
        self._status = "演示数据" if demo else "正在获取天气…"
        self._loading = False
        self._updated = 0.0
        self._position: tuple | None = None
        self._position_error = ""
        self._located.connect(self._on_located)
        self._locator = _Locator()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(lambda: self.refresh(False))
        self._paused = False
        if not demo:
            for name in ("islandsChanged", "stateReplaced"):
                signal = getattr(desk, name, None)
                if signal is not None:
                    signal.connect(self._islands_changed)
        if not demo:
            QTimer.singleShot(1500, lambda: self.refresh(False))

    # Preferences -------------------------------------------------------------------------------
    def _prefs(self):
        return self.desk.preferences if self.desk is not None else None

    def in_use(self) -> bool:
        """A weather island exists on some preset (custom widgets refresh explicitly)."""
        state = getattr(self.desk, "state", None)
        if self.demo or state is None:
            return True
        return any(island.kind == "widget" and island.widget == "weather"
                   for page in state.pages for island in page.islands)

    def _islands_changed(self) -> None:
        if self._loading or not self.in_use():
            return
        if not self._data.get("ok") or time.time() - self._updated > REFRESH_MS / 1000:
            self.refresh(False)

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        if not paused and time.time() - self._updated > REFRESH_MS / 1000:
            self.refresh(False)

    # Refresh ------------------------------------------------------------------------------------
    @Slot()
    @Slot(bool)
    def refresh(self, force: bool = True) -> None:
        if self.demo:
            self._data = demo_data()
            self.changed.emit()
            return
        if self._loading:
            return
        if self._paused and not force:
            self._timer.start(REFRESH_MS)
            return
        if not force and not self.in_use():
            self._timer.stop()           # _islands_changed() starts again with the first weather island
            if not self._data.get("ok"):
                self._status = "桌面上还没有天气小组件"
                self.changed.emit()
            return
        prefs = self._prefs()
        self._loading = True
        self._status = "正在更新…"
        self.changed.emit()
        if prefs is not None and not prefs.weather_auto_location and (prefs.weather_lat or prefs.weather_lon):
            self._fetch((float(prefs.weather_lat), float(prefs.weather_lon)), prefs.weather_city)
        elif prefs is None or prefs.weather_auto_location:
            if self._locator.available and (self._position is None or force):
                self._locator.locate(lambda pos, err: self._located.emit(pos, err))
            else:
                self._fetch(self._position, "")
        else:
            self._fetch(None, "")

    def _on_located(self, position, error: str) -> None:
        self._position = position
        self._position_error = error
        self._fetch(position, "")

    def _units(self) -> str:
        prefs = self._prefs()
        return "F" if prefs is not None and prefs.weather_fahrenheit else "C"

    def _fetch(self, position, city: str) -> None:
        params = {"apikey": MSN_KEY, "units": self._units(), "locale": "zh-cn"}
        position = coarse(position)
        if position:
            params["lat"], params["lon"] = "{0:.2f}".format(position[0]), "{0:.2f}".format(position[1])
        url = MSN_URL + "?" + urlencode(params)
        self._http.get_json(url, lambda data, err: self._msn_done(data, err, position, city))

    def _msn_done(self, data, error: str, position, city: str) -> None:
        parsed = None
        if not error and data:
            try:
                parsed = parse_msn(data)
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                error = "天气数据格式变化：{0}".format(exc)
        if parsed is not None:
            if city:
                parsed["city"] = city
            self._finish(parsed)
            return
        log.info("MSN weather failed (%s) - trying Open-Meteo", error)
        if not position:
            self._finish(None, error or "无法获取天气")
            return
        params = {"latitude": position[0], "longitude": position[1], "timezone": "auto", "forecast_days": 6,
                  "current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,"
                             "wind_speed_10m,wind_direction_10m,is_day",
                  "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"}
        if self._units() == "F":
            params["temperature_unit"] = "fahrenheit"
        self._http.get_json(OPEN_METEO + "?" + urlencode(params),
                            lambda d, e: self._meteo_done(d, e, city))

    def _meteo_done(self, data, error: str, city: str) -> None:
        if error or not data:
            self._finish(None, error or "无法获取天气")
            return
        try:
            parsed = parse_open_meteo(data)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            self._finish(None, str(exc))
            return
        parsed["city"] = city or self._data.get("city", "")
        self._finish(parsed)

    def _finish(self, data: dict | None, error: str = "") -> None:
        self._loading = False
        if data is not None:
            data["updated"] = _dt.datetime.now().strftime("%H:%M")
            data["unit"] = "°F" if self._units() == "F" else "°C"
            self._data = data
            self._updated = time.time()
            self._status = ""
            self._timer.start(REFRESH_MS)
        else:
            self._status = error
            if not self._data.get("ok"):
                self._data = {"ok": False}
            self._timer.start(2 * 60 * 1000)
        self.changed.emit()

    # City search (settings) ---------------------------------------------------------------------
    @Slot(str)
    def searchCity(self, text: str) -> None:  # noqa: N802
        text = (text or "").strip()
        if not text:
            self.searchFinished.emit([])
            return
        url = "{0}?name={1}&count=8&language=zh&format=json".format(GEOCODE, quote(text))

        def done(data, error) -> None:
            results = []
            for entry in (data or {}).get("results", []) or []:
                parts = [entry.get("admin1") or "", entry.get("country") or ""]
                results.append({"name": entry.get("name", ""), "detail": " · ".join(p for p in parts if p),
                                "lat": float(entry.get("latitude", 0.0)), "lon": float(entry.get("longitude", 0.0))})
            self.searchFinished.emit(results)

        self._http.get_json(url, done)

    @Slot(str, float, float)
    def useCity(self, name: str, lat: float, lon: float) -> None:  # noqa: N802
        if self.desk is None:
            return
        self.desk.set_preferences({"weather_auto_location": False, "weather_city": name,
                                   "weather_lat": float(lat), "weather_lon": float(lon)})
        self.refresh(True)

    @Slot()
    def useAutoLocation(self) -> None:  # noqa: N802
        if self.desk is not None:
            self.desk.set_preferences({"weather_auto_location": True})
        self._position = None
        self.refresh(True)

    def shutdown(self) -> None:
        self._timer.stop()
        self._http.abort_all()

    available = Property(bool, lambda self: True, constant=True)
    data = Property("QVariantMap", lambda self: dict(self._data), notify=changed)
    status = Property(str, lambda self: self._status, notify=changed)
    loading = Property(bool, lambda self: self._loading, notify=changed)
    locationNote = Property(str, lambda self: self._position_error, notify=changed)


__all__ = ["WeatherService", "coarse", "glyph_for", "parse_msn", "parse_open_meteo", "wind_text"]

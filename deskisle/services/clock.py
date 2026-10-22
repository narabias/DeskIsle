"""Clock widget back-end: lunar calendar (农历), solar terms and festivals.

Uses lunar-python (MIT, 6tail) when installed; the widget simply hides the
lunar line otherwise.
"""

from __future__ import annotations

import datetime as _dt

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

try:  # pragma: no cover - optional dependency
    from lunar_python import Solar
except Exception:  # pragma: no cover
    Solar = None

WEEKDAYS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def lunar_info(day: _dt.date) -> dict:
    """农历 details for ``day`` ({} when lunar-python is missing)."""
    if Solar is None:
        return {}
    solar = Solar.fromYmd(day.year, day.month, day.day)
    lunar = solar.getLunar()
    festivals = list(lunar.getFestivals()) + list(solar.getFestivals())
    term = lunar.getJieQi() or ""
    return {
        "month": "{0}月".format(lunar.getMonthInChinese()),
        "day": lunar.getDayInChinese(),
        "text": "{0}月{1}".format(lunar.getMonthInChinese(), lunar.getDayInChinese()),
        "year": "{0}{1}年".format(lunar.getYearInGanZhi(), lunar.getYearShengXiao()),
        "ganzhi": lunar.getYearInGanZhi(),
        "zodiac": lunar.getYearShengXiao(),
        "term": term,
        "festival": festivals[0] if festivals else "",
        "festivals": festivals,
        "yi": list(lunar.getDayYi())[:4],
        "ji": list(lunar.getDayJi())[:4],
    }


class ClockService(QObject):
    dayChanged = Signal()

    def __init__(self, desk=None, demo: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._today = _dt.date.today()
        self._info = lunar_info(self._today)
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self._check_day)
        self._timer.start()

    def _check_day(self) -> None:
        today = _dt.date.today()
        if today != self._today:
            self._today = today
            self._info = lunar_info(today)
            self.dayChanged.emit()

    @Slot(int, int, int, result="QVariantMap")
    def lunarFor(self, year: int, month: int, day: int) -> dict:  # noqa: N802 - QML API
        try:
            return lunar_info(_dt.date(int(year), int(month), int(day)))
        except ValueError:
            return {}

    @Slot(int, int, result="QVariantList")
    def monthGrid(self, year: int, month: int) -> list:  # noqa: N802
        """6x7 cells for a month calendar (Monday first) with lunar day names."""
        first = _dt.date(int(year), int(month), 1)
        start = first - _dt.timedelta(days=first.weekday())
        cells = []
        for i in range(42):
            day = start + _dt.timedelta(days=i)
            info = lunar_info(day) if Solar is not None else {}
            label = info.get("term") or info.get("festival") or (
                info.get("month") if info.get("day") == "初一" else info.get("day", ""))
            cells.append({"day": day.day, "date": day.isoformat(),
                          "inMonth": day.month == first.month, "today": day == self._today,
                          "lunar": label, "special": bool(info.get("term") or info.get("festival")),
                          "weekend": day.weekday() >= 5})
        return cells

    available = Property(bool, lambda self: True, constant=True)
    lunarAvailable = Property(bool, lambda self: Solar is not None, constant=True)
    lunar = Property("QVariantMap", lambda self: dict(self._info), notify=dayChanged)
    weekday = Property(str, lambda self: WEEKDAYS[self._today.weekday()], notify=dayChanged)


__all__ = ["ClockService", "lunar_info"]

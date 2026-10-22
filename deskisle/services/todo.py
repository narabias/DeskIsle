"""Todo widget back-end.

Items live in the island's ``widget_config["items"]`` (so they travel with
layout snapshots/exports): ``{"id", "text", "done", "due", "created",
"notified"}``.  ``due`` is ``YYYY-MM-DD`` or ``YYYY-MM-DDTHH:MM``.  Reminders (2.0.1): a timed item
reminds at its time, a date-only item at 09:00 that day; reminders missed while
DeskIsle was not running are summarised once at the next start.  Each reminder
is a notice (完成 / 10 分钟后) plus a Windows notification (``reminder``).
"""

from __future__ import annotations

import datetime as _dt
import re
import uuid

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

DEMO_ITEMS = [
    {"text": "整理本周的设计稿", "done": False, "due": ""},
    {"text": "给天气小组件换个城市试试", "done": False, "due": ""},
    {"text": "把下载文件夹拖进收纳岛", "done": True, "due": ""},
]


def _now() -> _dt.datetime:
    return _dt.datetime.now()


def parse_due(text: str):
    text = (text or "").strip()
    if not text:
        return None
    try:
        if "T" in text or " " in text:
            return _dt.datetime.fromisoformat(text.replace(" ", "T"))
        return _dt.datetime.combine(_dt.date.fromisoformat(text), _dt.time(23, 59))
    except ValueError:
        return None


DATE_ONLY_REMIND = _dt.time(9, 0)
SNOOZE_MINUTES = 10


def remind_at(text: str):
    """When an item with this ``due`` should remind (None = no valid date)."""
    due = parse_due(text)
    if due is None:
        return None
    if "T" in text or " " in text:
        return due
    return _dt.datetime.combine(due.date(), DATE_ONLY_REMIND)


def _already_due(text: str) -> bool:
    """The reminder time of ``text`` passed a while ago (a date picked in the past on purpose,
    not "now" picked a few seconds late): such an item does not remind."""
    when = remind_at(text)
    return when is not None and when < _now() - _dt.timedelta(minutes=2)


def due_label(text: str, now: _dt.datetime | None = None) -> str:
    due = parse_due(text)
    if due is None:
        return ""
    now = now or _now()
    days = (due.date() - now.date()).days
    timed = "T" in text or " " in text
    clock = due.strftime(" %H:%M") if timed else ""
    if days == 0:
        return "今天" + clock
    if days == 1:
        return "明天" + clock
    if days == -1:
        return "昨天" + clock
    if 1 < days < 7:
        return "周" + "一二三四五六日"[due.weekday()] + clock
    return due.strftime("%m-%d") + clock


_DAY_WORDS = {"大后天": 3, "后天": 2, "明晚": 1, "明早": 1, "明天": 1, "今晚": 0, "今早": 0, "今天": 0}
_WEEKDAY = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_WEEK_RE = re.compile(r"^(?P<next>下个?|这个?|本)?(?:周|星期|礼拜)(?P<w>[一二三四五六日天])")
_DATE_RE = re.compile(r"^(?:(?P<y>\d{4})[-/.年])?(?P<m>\d{1,2})[-/.月](?P<d>\d{1,2})日?")
_TIME_RE = re.compile(r"^(?P<ampm>凌晨|早上|上午|中午|下午|晚上)?(?P<h>\d{1,2})"
                      r"(?:[:：](?P<m>\d{2})|[点时](?P<half>半)?(?:(?P<m2>\d{1,2})分?)?)?$")


_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


def _cn_number(word: str) -> str:
    """十二 -> 12, 二十三 -> 23, 八 -> 8 (hours and minutes only)."""
    if "十" in word:
        tens, _sep, ones = word.partition("十")
        value = (_CN_DIGITS.get(tens, 0) if tens else 1) * 10 + (_CN_DIGITS.get(ones, 0) if ones else 0)
    else:
        value = 0
        for ch in word:
            value = value * 10 + _CN_DIGITS.get(ch, 0)
    return str(value)


def quick_due(text: str, now: _dt.datetime | None = None) -> str:
    """“明天 18:00”, “今天 9”, “周五 下午三点半”, “下周一”, “1-31”, “2025-01-31 8:30”, “20:00”."""
    rest = re.sub(r"\s+", "", text or "")
    if not rest:
        return ""
    now = now or _now()
    today = now.date()
    day = None
    evening = False
    for word, offset in _DAY_WORDS.items():
        if rest.startswith(word):
            day = today + _dt.timedelta(days=offset)
            evening = word.endswith("晚")
            rest = rest[len(word):]
            break
    else:
        week = _WEEK_RE.match(rest)
        date = _DATE_RE.match(rest)
        if week:
            target = _WEEKDAY[week.group("w")]
            if (week.group("next") or "").startswith("下"):
                day = today - _dt.timedelta(days=today.weekday()) + _dt.timedelta(days=7 + target)
            else:
                day = today + _dt.timedelta(days=(target - today.weekday()) % 7)
            rest = rest[week.end():]
        elif date:
            try:
                year = int(date.group("y") or today.year)
                day = _dt.date(year, int(date.group("m")), int(date.group("d")))
            except ValueError:
                return ""
            if not date.group("y") and day < today:
                day = day.replace(year=today.year + 1)
            rest = rest[date.end():]
    clock = ""
    # Chinese numerals only after the day part, so that “周六十点” stays 周六 + 10 点.
    rest = re.sub(r"([零一二两三四五六七八九十]+)(?=[点时分])", lambda m: _cn_number(m.group(1)), rest)
    if rest:
        match = _TIME_RE.match(rest)
        if not match:
            return day.isoformat() if day is not None and not rest.strip("的") else ""
        hour = int(match.group("h"))
        minute = 30 if match.group("half") else int(match.group("m") or match.group("m2") or 0)
        ampm = match.group("ampm") or ""
        if hour < 12 and (ampm in ("下午", "晚上") or (evening and not ampm) or (ampm == "中午" and hour < 11)):
            hour += 12
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return day.isoformat() if day is not None else ""
        clock = "{0:02d}:{1:02d}".format(hour, minute)
        if day is None:   # only a time: today, or tomorrow when it has passed
            day = today if (hour, minute) > (now.hour, now.minute) else today + _dt.timedelta(days=1)
    if day is None:
        return ""
    return day.isoformat() + ("T" + clock if clock else "")


class TodoService(QObject):
    """Exposed to QML as ``Todo``; every call names the island (``uid``)."""

    changed = Signal()
    reminder = Signal(str, str)     # title, text -> Windows notification (app.py)

    def __init__(self, desk=None, demo: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.desk = desk
        self.demo = demo
        self._seeded: dict[str, list] = {}
        self._signature = None
        self._started = False
        self._timer = QTimer(self)
        self._timer.setInterval(15_000)
        self._timer.timeout.connect(self.check_reminders)
        self._timer.start()
        # First pass a little after start-up: summarise what was missed while not running.
        QTimer.singleShot(4000, self.check_reminders)

    # Helpers ---------------------------------------------------------------------------------
    def _state(self, uid: str):
        if self.desk is None:
            return None
        _page, island = self.desk.find_island(uid)
        return island if island is not None and island.kind == "widget" and island.widget == "todo" else None

    def items(self, uid: str) -> list[dict]:
        island = self._state(uid)
        if island is None:
            return []
        items = island.widget_config.get("items")
        if items is None and self.demo:
            # Seed the demo list once; store it later (storing emits change signals, which must not
            # happen while QML is still evaluating the binding that asked for the list).
            items = self._seeded.get(uid)
            if items is None:
                items = [dict(i, id=uuid.uuid4().hex[:8], created="") for i in DEMO_ITEMS]
                self._seeded[uid] = items
                QTimer.singleShot(0, lambda: self._store(uid, [dict(i) for i in items]))
        return [dict(i) for i in (items or []) if isinstance(i, dict)]

    def _store(self, uid: str, items: list[dict]) -> None:
        if self.desk is not None:
            self.desk.island_action(uid, "widgetConfig", {"items": items})
        self.changed.emit()

    # QML API ---------------------------------------------------------------------------------
    @Slot(str, result="QVariantList")
    def list(self, uid: str) -> list:
        now = _now()
        result = []
        for item in self.items(uid):
            due = parse_due(item.get("due", ""))
            item["dueText"] = due_label(item.get("due", ""), now)
            item["overdue"] = bool(due is not None and due < now and not item.get("done"))
            result.append(item)
        return result

    @Slot(str, str, result=str)
    def add(self, uid: str, text: str) -> str:
        text = (text or "").strip()
        if not text:
            return ""
        due = ""
        # Quick syntax: “买牛奶 @明天 18:00” / “@今天” / “@2025-01-31”.
        if " @" in " " + text:
            head, _sep, tail = (" " + text).rpartition(" @")
            due = self.parse_quick_due(tail.strip())
            if due and head.strip():
                text = head.strip()
        items = self.items(uid)
        item_id = uuid.uuid4().hex[:8]
        item = {"id": item_id, "text": text[:200], "done": False, "due": due,
                "created": _now().isoformat(timespec="minutes")}
        if _already_due(due):
            item["notified"] = True      # set in the past on purpose: no reminder for it
        items.append(item)
        self._store(uid, items)
        return item_id

    @staticmethod
    def parse_quick_due(text: str, now: _dt.datetime | None = None) -> str:
        """``@`` suffix of a new item -> ``YYYY-MM-DD[THH:MM]`` ("" = not a date)."""
        return quick_due(text, now)

    @Slot(str, str)
    def toggle(self, uid: str, item_id: str) -> None:
        items = self.items(uid)
        for item in items:
            if item.get("id") == item_id:
                item["done"] = not item.get("done")
        self._store(uid, items)

    @Slot(str, str, str)
    def edit(self, uid: str, item_id: str, text: str) -> None:
        text = (text or "").strip()
        items = self.items(uid)
        for item in items:
            if item.get("id") == item_id:
                if text:
                    item["text"] = text[:200]
        self._store(uid, [i for i in items if i.get("text")])

    @Slot(str, str, str)
    def setDue(self, uid: str, item_id: str, due: str) -> None:  # noqa: N802
        items = self.items(uid)
        for item in items:
            if item.get("id") == item_id:
                item["due"] = due if parse_due(due) is not None else ""
                item["notified"] = _already_due(item["due"])
                item.pop("snooze", None)
        self._store(uid, items)

    @Slot(str, str)
    def remove(self, uid: str, item_id: str) -> None:
        self._store(uid, [i for i in self.items(uid) if i.get("id") != item_id])

    @Slot(str)
    def clearDone(self, uid: str) -> None:  # noqa: N802
        self._store(uid, [i for i in self.items(uid) if not i.get("done")])

    @Slot(str, int, int)
    def move(self, uid: str, source: int, target: int) -> None:
        items = self.items(uid)
        if not 0 <= source < len(items):
            return
        item = items.pop(source)
        items.insert(max(0, min(len(items), target)), item)
        self._store(uid, items)

    # Calendar (clock widget) -----------------------------------------------------------------
    def _todo_islands(self):
        desk = self.desk
        if desk is None:
            return
        for page in desk.state.pages:
            for island in page.islands:
                if island.kind == "widget" and island.widget == "todo":
                    yield island

    def due_map(self) -> dict:
        """``{"YYYY-MM-DD": {"count": n, "overdue": bool}}`` of open items (all todo widgets)."""
        now = _now()
        marks: dict = {}
        for island in self._todo_islands():
            for item in island.widget_config.get("items", []) or []:
                if not isinstance(item, dict) or item.get("done"):
                    continue
                due = parse_due(item.get("due", ""))
                if due is None:
                    continue
                mark = marks.setdefault(due.date().isoformat(), {"count": 0, "overdue": False})
                mark["count"] += 1
                mark["overdue"] = mark["overdue"] or due < now
        return marks

    @Slot(str, result="QVariantList")
    def itemsOn(self, date: str) -> list:  # noqa: N802
        """Items due on ``YYYY-MM-DD`` (all todo widgets), timed ones first by time."""
        result = []
        for island in self._todo_islands():
            for item in island.widget_config.get("items", []) or []:
                if not isinstance(item, dict):
                    continue
                text = item.get("due", "") or ""
                due = parse_due(text)
                if due is None or due.date().isoformat() != date:
                    continue
                timed = "T" in text or " " in text
                result.append({"text": item.get("text", ""), "done": bool(item.get("done")),
                               "time": due.strftime("%H:%M") if timed else "", "list": island.title,
                               "uid": island.id, "id": item.get("id", "")})
        result.sort(key=lambda i: (i["done"], i["time"] == "", i["time"]))
        return result

    # Reminders --------------------------------------------------------------------------------
    def complete(self, uid: str, item_id: str) -> None:
        items = self.items(uid)
        for item in items:
            if item.get("id") == item_id:
                item["done"] = True
        self._store(uid, items)

    def snooze(self, uid: str, item_id: str, minutes: int = SNOOZE_MINUTES) -> None:
        """Remind again in a few minutes (keeps the original due date)."""
        items = self.items(uid)
        until = (_now() + _dt.timedelta(minutes=minutes)).isoformat(timespec="minutes")
        for item in items:
            if item.get("id") == item_id:
                item["notified"] = False
                item["snooze"] = until
        self._store(uid, items)

    def _remind(self, island, item) -> None:
        desk = self.desk
        text = item.get("text", "")
        label = due_label(item.get("due", ""))
        actions = [{"id": "todo.done:{0}/{1}".format(island.id, item.get("id", "")), "text": "完成"},
                   {"id": "todo.snooze:{0}/{1}".format(island.id, item.get("id", "")), "text": "10 分钟后"}]
        desk.show_notice("待办提醒 · " + island.title, text + ("（" + label + "）" if label else ""), "info", actions, 0)
        self.reminder.emit("待办提醒 · " + island.title, text)

    def check_reminders(self) -> None:
        desk = self.desk
        if desk is None:
            return
        now = _now()
        first = not self._started
        self._started = True
        missed: list[str] = []
        overdue: list[str] = []
        for island in list(self._todo_islands()):
            items = [dict(i) for i in island.widget_config.get("items", []) or [] if isinstance(i, dict)]
            fired = False
            for item in items:
                if item.get("done"):
                    continue
                due_text = item.get("due", "") or ""
                when = remind_at(due_text)
                due = parse_due(due_text)
                if due is not None and due < now:
                    overdue.append(item.get("id", ""))
                snooze = parse_due(item.get("snooze", "") or "")
                if snooze is not None:
                    when = snooze
                if when is None or item.get("notified") or when > now:
                    continue
                item["notified"] = True
                item.pop("snooze", None)
                fired = True
                if first and snooze is None and (now - when) > _dt.timedelta(minutes=10):
                    missed.append(item.get("text", ""))  # due while DeskIsle was not running
                else:
                    self._remind(island, item)
            if fired:
                desk.island_action(island.id, "widgetConfig", {"items": items})
        if missed:
            shown = "、".join(t for t in missed[:3] if t) + (" 等" if len(missed) > 3 else "")
            desk.show_notice("有 {0} 项待办已到期".format(len(missed)), shown, "warning", [], 0)
            self.reminder.emit("有 {0} 项待办已到期".format(len(missed)), shown)
        # Repaint (overdue colours, "今天/明天" labels) only when something actually changed.
        signature = (now.date(), tuple(sorted(overdue)))
        if signature != self._signature:
            self._signature = signature
            self.changed.emit()

    dueMap = Property("QVariantMap", lambda self: self.due_map(), notify=changed)
    revision = Property(int, lambda self: 0, notify=changed)
    available = Property(bool, lambda self: True, constant=True)


__all__ = ["TodoService", "due_label", "parse_due", "remind_at"]

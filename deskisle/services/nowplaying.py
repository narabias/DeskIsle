"""“正在播放” back-end: Windows Global System Media Transport Controls.

Every player that shows up in the Windows volume flyout (Spotify, QQ 音乐,
网易云音乐, 酷狗, foobar2000, the browsers, Media Player ...) publishes a
GSMTC session.  We read it through pywinrt (MIT,
``winrt-Windows.Media.Control``) on a private asyncio thread and hand plain
values to QML.  2.0.1: the GSMTC events (sessions / current session / media
properties / playback / timeline changed) wake the reader at once; polling
(1 s while playing, 4 s otherwise) stays as the safety net because some players
do not raise every event.  Position updates that only confirm the local
extrapolation are swallowed, so the UI is not re-bound every second.  The
player UI itself is ours (``MediaWidget.qml`` / ``MediaPanel.qml``).

网易云音乐 only publishes a session after its "SMTC" option is switched on
(the same advice as WinIsland's FAQ); when its window is found without a
session, ``hint`` says so.

Without pywinrt (or off Windows) the service reports ``available = False``;
the demo mode simulates a track so the UI can be explored anywhere.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QRadialGradient
from PySide6.QtQuick import QQuickImageProvider

log = logging.getLogger("deskisle.nowplaying")
IS_WINDOWS = sys.platform == "win32"
POLL_S = 1.0
IDLE_POLL_S = 4.0
COVER_RETRY_S = (0.3, 1.0, 3.0)    # a thumbnail often arrives after the title
DRIFT_S = 1.5                      # re-anchor the progress only beyond this drift
NETEASE_HINT = ("检测到网易云音乐正在运行，但它没有向系统报告播放信息：请在网易云音乐的设置里打开"
                "「SMTC」（系统媒体控制）选项。进度条与歌词需要 BetterNCM 插件。")

# Friendly names for common AppUserModelIDs / executables.
APP_NAMES = {
    "spotify": "Spotify", "qqmusic": "QQ 音乐", "cloudmusic": "网易云音乐", "kugou": "酷狗音乐",
    "kuwo": "酷我音乐", "foobar2000": "foobar2000", "potplayer": "PotPlayer", "vlc": "VLC",
    "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "zunemusic": "媒体播放器",
    "zunevideo": "电影和电视", "applemusic": "Apple Music", "itunes": "iTunes", "aimp": "AIMP",
    "musicbee": "MusicBee", "bilibili": "哔哩哔哩", "neteasemusic": "网易云音乐", "lx-music": "洛雪音乐",
    "listen1": "Listen 1", "youtube": "YouTube Music", "opera": "Opera", "brave": "Brave",
}
STATUS = {0: "closed", 1: "opened", 2: "changing", 3: "stopped", 4: "playing", 5: "paused"}


def friendly_app(app_id: str) -> str:
    text = (app_id or "").strip()
    if not text:
        return ""
    low = text.casefold()
    for key, name in APP_NAMES.items():
        if key in low:
            return name
    base = text.split("!")[0].split("_")[0]
    base = base.rsplit("\\", 1)[-1]
    if base.casefold().endswith(".exe"):
        base = base[:-4]
    if "." in base:
        base = base.rsplit(".", 1)[-1]
    return base[:1].upper() + base[1:]


def _seconds(value) -> float:
    """pywinrt TimeSpan -> seconds (timedelta, int ticks or None)."""
    if value is None:
        return 0.0
    if hasattr(value, "total_seconds"):
        return float(value.total_seconds())
    try:
        return float(value) / 10_000_000.0
    except (TypeError, ValueError):
        return 0.0


def dominant_color(image: QImage) -> QColor:
    """Average of a small, saturation weighted thumbnail (player accent)."""
    if image.isNull():
        return QColor("#5AA9FF")
    small = image.scaled(24, 24).convertToFormat(QImage.Format.Format_RGB32)
    total_w = r = g = b = 0.0
    for y in range(small.height()):
        for x in range(small.width()):
            c = QColor(small.pixel(x, y))
            weight = 0.15 + c.hsvSaturationF() * c.valueF()
            r += c.redF() * weight
            g += c.greenF() * weight
            b += c.blueF() * weight
            total_w += weight
    if total_w <= 0:
        return QColor("#5AA9FF")
    color = QColor.fromRgbF(r / total_w, g / total_w, b / total_w)
    h, s, v, _a = color.getHsvF()
    return QColor.fromHsvF(max(0.0, h), min(1.0, s * 1.25 + 0.05), max(0.45, min(0.92, v)))


class CoverProvider(QQuickImageProvider):
    """``image://cover/<revision>`` -> album art of the current session."""

    def __init__(self, service: "NowPlayingService") -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)
        self._service = service

    def requestImage(self, image_id, size, requested_size):  # noqa: N802 - Qt API
        from ..engine.icons import WARMUP_ID, warmup_image

        if str(image_id).startswith(WARMUP_ID):
            return warmup_image(size)
        image = self._service.cover_image()
        if image.isNull():
            image = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0)
        if requested_size is not None and requested_size.isValid() and requested_size.width() > 0:
            image = image.scaled(requested_size.width(), requested_size.height(),
                                 Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                 Qt.TransformationMode.SmoothTransformation)
        try:
            size.setWidth(image.width())
            size.setHeight(image.height())
        except Exception:
            pass
        return image


def demo_cover() -> QImage:
    image = QImage(320, 320, QImage.Format.Format_ARGB32_Premultiplied)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 320, 320)
    grad.setColorAt(0, QColor("#FF8A5B"))
    grad.setColorAt(0.55, QColor("#C2417A"))
    grad.setColorAt(1, QColor("#3A2C7A"))
    p.fillRect(image.rect(), grad)
    glow = QRadialGradient(220, 100, 150)
    glow.setColorAt(0, QColor(255, 236, 190, 200))
    glow.setColorAt(1, QColor(255, 236, 190, 0))
    p.setBrush(glow)
    p.setPen(QColor(0, 0, 0, 0))
    p.drawEllipse(70, -50, 300, 300)
    p.setBrush(QColor(20, 16, 40, 120))
    for i, h in enumerate((60, 110, 80, 140, 96, 120, 70)):
        p.drawRoundedRect(46 + i * 34, 270 - h, 20, h, 8, 8)
    p.end()
    return image


# ---------------------------------------------------------------------------------------------
class _Worker:
    """Owns the asyncio loop + GSMTC manager (Windows only)."""

    def __init__(self, service: "NowPlayingService") -> None:
        self.service = service
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self._run, name="deskisle-gsmtc", daemon=True)
        self.manager = None
        self.stop = False
        self.wake = None
        self.last_cover_key = None
        self.selected = ""
        self.cover_pending = False
        self.cover_tries = 0
        self.cover_next = 0.0
        self.cover_digest = None
        self.anchor = None             # (id, title, status, position, stamp) last reported
        self.tokens = []               # (source, remover name, token) of event subscriptions
        self.watched = None            # session whose events we listen to
        self.netease_check = 0.0
        self.netease = False

    def start(self) -> None:
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        except Exception:  # pragma: no cover - Windows only
            log.exception("GSMTC worker stopped")
            self.service._report.emit({"available": False, "error": "无法读取系统媒体信息"})

    async def _main(self) -> None:  # pragma: no cover - Windows only
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as Manager

        self.manager = await Manager.request_async()
        self.wake = asyncio.Event()
        self._subscribe(self.manager, ("sessions_changed", "current_session_changed"))
        while not self.stop:
            try:
                await self._poll()
            except Exception:
                log.debug("poll failed", exc_info=True)
            playing = bool(self.anchor and self.anchor[2] == "playing")
            interval = IDLE_POLL_S if (self.service.paused or not playing) else POLL_S
            if self.cover_pending:
                interval = min(interval, max(0.05, self.cover_next - time.monotonic()))
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            self.wake.clear()
        self._unsubscribe_all()

    # Events (wake-ups only; the poll reads the actual values) --------------------------------
    def _poke(self, refetch_cover: bool = False) -> None:
        """Called from WinRT threads: wake the reader loop."""
        if self.loop.is_closed():
            return

        def wake():
            if refetch_cover:
                self.last_cover_key = None
            if self.wake is not None:
                self.wake.set()
        try:
            self.loop.call_soon_threadsafe(wake)
        except RuntimeError:
            pass

    def _subscribe(self, source, events, session: bool = False) -> None:  # pragma: no cover - Windows only
        for event in events:
            adder = getattr(source, "add_" + event, None)
            if adder is None:
                continue
            refetch = event == "media_properties_changed"
            handler = (lambda *_args, r=refetch: self._poke(r))
            try:
                token = adder(handler)
                self.tokens.append((source, "remove_" + event, token, handler, session))
            except Exception:
                log.debug("subscribe %s failed", event, exc_info=True)

    def _unsubscribe(self, session_only: bool) -> None:  # pragma: no cover - Windows only
        keep = []
        for entry in self.tokens:
            source, remover, token, _handler, is_session = entry
            if session_only and not is_session:
                keep.append(entry)
                continue
            try:
                getattr(source, remover)(token)
            except Exception:
                pass
        self.tokens = keep

    def _unsubscribe_all(self) -> None:  # pragma: no cover - Windows only
        self._unsubscribe(False)

    def _watch(self, session) -> None:  # pragma: no cover - Windows only
        """Listen to the events of the session we show (re-subscribed when it changes)."""
        sid = session.source_app_user_model_id if session is not None else None
        if sid == self.watched:
            return
        self._unsubscribe(True)
        self.watched = sid
        if session is not None:
            self._subscribe(session, ("media_properties_changed", "playback_info_changed",
                                      "timeline_properties_changed"), session=True)

    @staticmethod
    def _status_of(session) -> int:  # pragma: no cover - Windows only
        try:
            info = session.get_playback_info()
            return int(info.playback_status) if info is not None else 0
        except Exception:
            return 0

    def _session(self):  # pragma: no cover - Windows only
        """Priority: picked by the user > current if playing > any playing > current > first."""
        manager = self.manager
        if manager is None:
            return None, []
        sessions = list(manager.get_sessions() or [])
        if self.selected:
            picked = next((s for s in sessions if s.source_app_user_model_id == self.selected), None)
            if picked is not None:
                return picked, sessions
        current = manager.get_current_session()
        if current is not None and self._status_of(current) == 4:
            return current, sessions
        playing = next((s for s in sessions if self._status_of(s) == 4), None)
        if playing is not None:
            return playing, sessions
        if current is not None:
            return current, sessions
        return (sessions[0] if sessions else None), sessions

    def _netease_running(self) -> bool:  # pragma: no cover - Windows only
        now = time.monotonic()
        if now - self.netease_check > 5.0:
            self.netease_check = now
            try:
                import ctypes

                self.netease = bool(ctypes.windll.user32.FindWindowW("OrpheusBrowserHost", None))
            except Exception:
                self.netease = False
        return self.netease

    async def _poll(self) -> None:  # pragma: no cover - Windows only
        session, sessions = self._session()
        self._watch(session)
        listing = [{"id": s.source_app_user_model_id, "app": friendly_app(s.source_app_user_model_id)}
                   for s in sessions]
        has_netease = any("cloudmusic" in (i["id"] or "").casefold() or "netease" in (i["id"] or "").casefold()
                          for i in listing)
        hint = NETEASE_HINT if (not has_netease and self._netease_running()) else ""
        if session is None:
            self.anchor = None
            self.service._report.emit({"available": True, "hasSession": False, "sessions": listing, "hint": hint})
            return
        props = await session.try_get_media_properties_async()
        info = session.get_playback_info()
        timeline = session.get_timeline_properties()
        controls = info.controls if info is not None else None
        status = STATUS.get(int(info.playback_status), "closed") if info is not None else "closed"
        position = _seconds(getattr(timeline, "position", None))
        start = _seconds(getattr(timeline, "start_time", None))
        end = _seconds(getattr(timeline, "end_time", None))
        updated = getattr(timeline, "last_updated_time", None)
        stamp = time.time()
        if updated is not None and hasattr(updated, "timestamp") and status == "playing":
            try:
                # The position was sampled at last_updated_time; advance it to "now".
                age = max(0.0, stamp - updated.timestamp())
                if age < 3600:
                    position += age * float(getattr(info, "playback_rate", None) or 1.0)
            except (OverflowError, OSError, ValueError):
                pass
        sid = session.source_app_user_model_id
        title = props.title or ""
        position = max(0.0, position - start)
        # Keep the previous anchor while it still predicts the position well: the UI
        # extrapolates locally, so re-sending the same timeline would only cause churn.
        anchor = self.anchor
        if anchor is not None and anchor[0] == sid and anchor[1] == title and anchor[2] == status:
            predicted = anchor[3] + ((stamp - anchor[4]) if status == "playing" else 0.0)
            if abs(predicted - position) < DRIFT_S:
                position, stamp = anchor[3], anchor[4]
        self.anchor = (sid, title, status, position, stamp)
        report = {
            "available": True, "hasSession": True, "sessions": listing, "hint": hint,
            "id": sid,
            "app": friendly_app(sid),
            "title": title, "artist": props.artist or props.album_artist or "",
            "album": props.album_title or "", "status": status,
            "position": position, "duration": max(0.0, end - start), "stamp": stamp,
            "canPlay": bool(controls and controls.is_play_enabled),
            "canPause": bool(controls and controls.is_pause_enabled),
            "canNext": bool(controls and controls.is_next_enabled),
            "canPrevious": bool(controls and controls.is_previous_enabled),
            "canSeek": bool(controls and controls.is_playback_position_enabled),
            "shuffle": bool(getattr(info, "is_shuffle_active", None) or False),
            "repeat": int(getattr(info, "auto_repeat_mode", None) or 0),
        }
        cover = await self._cover_step((sid, title, report["album"]), props)
        if cover is not None:
            report["cover"] = cover
        self.service._report.emit(report)

    async def _cover_step(self, key, props):  # pragma: no cover - Windows only
        """New cover bytes, b"" for "no cover", or None for "keep the current one"."""
        now = time.monotonic()
        if key != self.last_cover_key:
            self.last_cover_key = key
            self.cover_pending = True
            self.cover_tries = 0
            self.cover_next = now
        if not self.cover_pending or now < self.cover_next:
            return None
        data = await self._thumbnail(props)
        if data:
            self.cover_pending = False
            digest = hash(data)
            if digest == self.cover_digest:
                return None
            self.cover_digest = digest
            return data
        # Not there yet: keep the last cover and try again a little later.
        if self.cover_tries < len(COVER_RETRY_S):
            self.cover_next = now + COVER_RETRY_S[self.cover_tries]
            self.cover_tries += 1
            return None
        self.cover_pending = False
        if self.cover_digest is None:
            return None
        self.cover_digest = None
        return b""

    async def _thumbnail(self, props) -> bytes:  # pragma: no cover - Windows only
        ref = getattr(props, "thumbnail", None)
        if ref is None:
            return b""
        try:
            from winrt.windows.storage.streams import DataReader, InputStreamOptions

            stream = await ref.open_read_async()
            size = int(stream.size)
            if size <= 0 or size > 16 * 1024 * 1024:
                return b""
            reader = DataReader(stream)
            reader.input_stream_options = InputStreamOptions.READ_AHEAD
            await reader.load_async(size)
            try:
                return bytes(reader.read_buffer(size))
            except TypeError:
                data = bytearray(size)
                reader.read_bytes(data)
                return bytes(data)
        except Exception:
            log.debug("thumbnail failed", exc_info=True)
            return b""

    # Commands (thread safe) ---------------------------------------------------------------
    def command(self, name: str, value=None) -> None:
        if self.loop.is_closed():
            return
        asyncio.run_coroutine_threadsafe(self._command(name, value), self.loop)

    async def _command(self, name: str, value) -> None:  # pragma: no cover - Windows only
        if name == "select":
            self.selected = str(value or "")
            self.last_cover_key = None
            self.anchor = None
        else:
            session, _sessions = self._session()
            if session is None:
                return
            if name == "toggle":
                await session.try_toggle_play_pause_async()
            elif name == "next":
                await session.try_skip_next_async()
            elif name == "previous":
                await session.try_skip_previous_async()
            elif name == "seek":
                timeline = session.get_timeline_properties()
                start = _seconds(getattr(timeline, "start_time", None))
                await session.try_change_playback_position_async(int((start + float(value)) * 10_000_000))
            elif name == "shuffle":
                await session.try_change_shuffle_active_async(bool(value))
            elif name == "repeat":
                from winrt.windows.media import MediaPlaybackAutoRepeatMode

                await session.try_change_auto_repeat_mode_async(MediaPlaybackAutoRepeatMode(int(value)))
        self.anchor = None             # a command moves the timeline: take the next reading as is
        await asyncio.sleep(0.15)
        if self.wake is not None:
            self.wake.set()

    def shutdown(self) -> None:
        self.stop = True
        if self.wake is not None and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.wake.set)


# ---------------------------------------------------------------------------------------------
class NowPlayingService(QObject):
    """Exposed to QML as ``Player``."""

    changed = Signal()
    coverChanged = Signal()
    _report = Signal(object)

    def __init__(self, desk=None, demo: bool = False, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.desk = desk
        self.demo = demo
        self.paused = False
        self._state: dict = {"available": False, "hasSession": False, "sessions": []}
        self._cover = QImage()
        self._cover_rev = 0
        self._accent = QColor("#5AA9FF")
        self._error = ""
        self._worker = None
        self._report.connect(self._apply)
        self._provider = CoverProvider(self)
        if demo:
            self._start_demo()
        elif IS_WINDOWS:
            try:
                # The namespaces whose types GSMTC hands back (async operations,
                # session vectors, thumbnail streams) must be importable too,
                # otherwise pywinrt cannot wrap the results.
                import winrt.windows.foundation  # noqa: F401
                import winrt.windows.foundation.collections  # noqa: F401
                import winrt.windows.media.control  # noqa: F401
                import winrt.windows.storage.streams  # noqa: F401

                self._worker = _Worker(self)
                self._worker.start()
                self._state["available"] = True
            except Exception as exc:  # pragma: no cover - depends on installed wheels
                self._error = "缺少 pywinrt 组件（winrt-Windows.Media.Control 等，见 requirements.txt）：{0}".format(exc)
                log.info("now playing unavailable: %s", exc)
        else:
            self._error = "“正在播放”需要 Windows 10/11 的系统媒体控制。"

    # Image providers registered by the app ------------------------------------------------------
    def image_providers(self) -> dict:
        return {"cover": self._provider}

    def cover_image(self) -> QImage:
        return self._cover

    # Updates -------------------------------------------------------------------------------------
    def _apply(self, report: dict) -> None:
        cover = report.pop("cover", None)
        if cover is not None:
            image = QImage()
            if cover:
                image.loadFromData(cover)
            self._cover = image
            self._cover_rev += 1
            self._accent = dominant_color(image) if not image.isNull() else QColor("#5AA9FF")
            self.coverChanged.emit()
        if report.get("error"):
            self._error = str(report.pop("error"))
        state = dict(self._state)
        state.update(report)
        if not state.get("hasSession"):
            for key in ("title", "artist", "album", "app", "id"):
                state[key] = ""
            state["status"] = "closed"
        if state != self._state:
            self._state = state
            self.changed.emit()

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)

    # Demo ----------------------------------------------------------------------------------------
    def _start_demo(self) -> None:
        self._cover = demo_cover()
        self._cover_rev = 1
        self._accent = dominant_color(self._cover)
        self._demo_pos = 47.0
        self._state = {"available": True, "hasSession": True, "id": "demo", "app": "演示播放器",
                       "title": "Sunset Drive", "artist": "Lumen Waves", "album": "Night City Tapes",
                       "status": "playing", "position": self._demo_pos, "duration": 214.0, "stamp": time.time(),
                       "canPlay": True, "canPause": True, "canNext": True, "canPrevious": True, "canSeek": True,
                       "shuffle": False, "repeat": 0,
                       "sessions": [{"id": "demo", "app": "演示播放器"}, {"id": "demo2", "app": "Chrome"}]}
        self._demo_timer = QTimer(self)
        self._demo_timer.setInterval(1000)
        self._demo_timer.timeout.connect(self._demo_tick)
        self._demo_timer.start()

    def _demo_tick(self) -> None:
        if self._state.get("status") == "playing":
            pos = float(self._state.get("position", 0)) + (time.time() - float(self._state.get("stamp", time.time())))
            if pos >= float(self._state.get("duration", 0)):
                pos = 0.0
            self._apply({"position": pos, "stamp": time.time()})

    def _demo_command(self, name: str, value=None) -> None:
        tracks = [("Sunset Drive", "Lumen Waves", 214.0), ("Paper Planes", "Kite Theory", 188.0),
                  ("北岛以北", "雾港乐队", 241.0)]
        state = dict(self._state)
        now = time.time()
        position = float(state.get("position", 0)) + ((now - float(state.get("stamp", now)))
                                                        if state.get("status") == "playing" else 0)
        if name == "toggle":
            self._apply({"status": "paused" if state.get("status") == "playing" else "playing",
                         "position": position, "stamp": now})
        elif name in ("next", "previous"):
            titles = [t[0] for t in tracks]
            index = titles.index(state.get("title")) if state.get("title") in titles else 0
            index = (index + (1 if name == "next" else -1)) % len(tracks)
            title, artist, duration = tracks[index]
            self._apply({"title": title, "artist": artist, "duration": duration, "position": 0.0, "stamp": now,
                         "status": "playing"})
        elif name == "seek":
            self._apply({"position": max(0.0, float(value)), "stamp": now})
        elif name == "shuffle":
            self._apply({"shuffle": bool(value)})
        elif name == "repeat":
            self._apply({"repeat": int(value)})

    # QML API -------------------------------------------------------------------------------------
    def _command(self, name: str, value=None) -> None:
        if self.demo:
            self._demo_command(name, value)
        elif self._worker is not None:
            self._worker.command(name, value)

    @Slot()
    def playPause(self) -> None:  # noqa: N802
        self._command("toggle")

    @Slot()
    def next(self) -> None:
        self._command("next")

    @Slot()
    def previous(self) -> None:
        self._command("previous")

    @Slot(float)
    def seek(self, seconds: float) -> None:
        self._command("seek", max(0.0, float(seconds)))

    @Slot(bool)
    def setShuffle(self, on: bool) -> None:  # noqa: N802
        self._command("shuffle", bool(on))

    @Slot(int)
    def setRepeat(self, mode: int) -> None:  # noqa: N802
        self._command("repeat", int(mode) % 3)

    @Slot(str)
    def selectSession(self, session_id: str) -> None:  # noqa: N802
        if self.demo:
            app = next((s["app"] for s in self._state.get("sessions", []) if s["id"] == session_id), "")
            self._apply({"id": session_id, "app": app})
            return
        self._command("select", session_id)

    @Slot(result=float)
    def currentPosition(self) -> float:  # noqa: N802
        state = self._state
        position = float(state.get("position", 0) or 0)
        if state.get("status") == "playing":
            position += max(0.0, time.time() - float(state.get("stamp", time.time())))
        duration = float(state.get("duration", 0) or 0)
        return min(position, duration) if duration > 0 else position

    def snapshot(self) -> dict:
        """Plain state for the agent API."""
        state = {k: v for k, v in self._state.items()}
        state["position"] = self.currentPosition()
        state["error"] = self._error
        return state

    def shutdown(self) -> None:
        if self._worker is not None:
            self._worker.shutdown()

    def _get(self, key: str, default=None):
        return self._state.get(key, default)

    available = Property(bool, lambda self: bool(self._state.get("available")), notify=changed)
    hasSession = Property(bool, lambda self: bool(self._state.get("hasSession")), notify=changed)
    title = Property(str, lambda self: str(self._get("title", "") or ""), notify=changed)
    artist = Property(str, lambda self: str(self._get("artist", "") or ""), notify=changed)
    album = Property(str, lambda self: str(self._get("album", "") or ""), notify=changed)
    app = Property(str, lambda self: str(self._get("app", "") or ""), notify=changed)
    playing = Property(bool, lambda self: self._get("status") == "playing", notify=changed)
    status = Property(str, lambda self: str(self._get("status", "closed")), notify=changed)
    position = Property(float, lambda self: float(self._get("position", 0) or 0), notify=changed)
    stamp = Property(float, lambda self: float(self._get("stamp", 0) or 0), notify=changed)
    duration = Property(float, lambda self: float(self._get("duration", 0) or 0), notify=changed)
    canPlay = Property(bool, lambda self: bool(self._get("canPlay")), notify=changed)
    canPause = Property(bool, lambda self: bool(self._get("canPause")), notify=changed)
    canNext = Property(bool, lambda self: bool(self._get("canNext")), notify=changed)
    canPrevious = Property(bool, lambda self: bool(self._get("canPrevious")), notify=changed)
    canSeek = Property(bool, lambda self: bool(self._get("canSeek")), notify=changed)
    shuffle = Property(bool, lambda self: bool(self._get("shuffle")), notify=changed)
    repeat = Property(int, lambda self: int(self._get("repeat", 0) or 0), notify=changed)
    sessions = Property("QVariantList", lambda self: list(self._get("sessions", []) or []), notify=changed)
    sessionId = Property(str, lambda self: str(self._get("id", "") or ""), notify=changed)
    cover = Property(str, lambda self: "image://cover/{0}".format(self._cover_rev) if not self._cover.isNull()
                     else "", notify=coverChanged)
    accent = Property(QColor, lambda self: QColor(self._accent), notify=coverChanged)
    error = Property(str, lambda self: self._error, notify=changed)
    hint = Property(str, lambda self: str(self._get("hint", "") or ""), notify=changed)


__all__ = ["NowPlayingService", "dominant_color", "friendly_app"]

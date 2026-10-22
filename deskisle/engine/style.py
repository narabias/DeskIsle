"""Theme tokens for QML (``Theme`` context property).

Light/dark follows the preference (time of day, system or fixed); the accent
colour comes *only* from the wallpaper (see :mod:`.wallpaper`).  Agents and
power users can override visual tokens in ``custom/theme.json`` (see
AGENTS.md); unknown keys are kept and readable from QML via ``Theme.tok()``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Property, QObject, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication

from .wallpaper import tune_accent

# Default tokens; theme.json may override any of them.
DEFAULT_TOKENS: dict = {
    "radius": 22,            # island corner radius (px)
    "smallRadius": 12,       # buttons, tiles, menus
    "barHeight": 40,         # dynamic bar pill height
    "glassStrength": 1.0,    # refraction/tone intensity multiplier
    "shadow": 1.0,           # drop shadow multiplier
    "motion": 1.0,           # animation speed multiplier (2 = twice as slow)
    "fontScale": 1.0,
    "headerHeight": 44,
    "iconLabelLines": 2,
}


def _color(value: QColor, alpha: float) -> QColor:
    c = QColor(value)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


# Day / night ------------------------------------------------------------------------------------
def luminance(color) -> float:
    """WCAG relative luminance (0 = black, 1 = white)."""
    value = QColor(color)

    def channel(component: float) -> float:
        return component / 12.92 if component <= 0.03928 else ((component + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(value.redF()) + 0.7152 * channel(value.greenF()) + 0.0722 * channel(value.blueF())


def _minutes(text: str, default: int) -> int:
    try:
        hours, minutes = str(text).split(":", 1)
        return max(0, min(23, int(hours))) * 60 + max(0, min(59, int(minutes)))
    except (ValueError, AttributeError):
        return default


def is_daytime(day_start: str = "07:00", night_start: str = "19:00", now: datetime | None = None) -> bool:
    now = now or datetime.now()
    current = now.hour * 60 + now.minute
    day, night = _minutes(day_start, 7 * 60), _minutes(night_start, 19 * 60)
    if day == night:
        return True
    if day < night:
        return day <= current < night
    return current >= day or current < night


def system_prefers_dark() -> bool | None:
    """Windows app theme (AppsUseLightTheme); ``None`` when unknown."""
    try:
        import winreg  # type: ignore[import-not-found]

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(value) == 0
    except (ImportError, OSError, ValueError):
        pass
    try:
        app = QGuiApplication.instance()
        if app is not None:
            scheme = app.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return True
            if scheme == Qt.ColorScheme.Light:
                return False
    except (AttributeError, RuntimeError):
        pass
    return None


# Wallpaper mode: light islands on bright wallpapers.  Hysteresis keeps a
# wallpaper near the threshold (or a live one) from flipping back and forth.
WALL_LIGHT_ON = 0.56
WALL_LIGHT_OFF = 0.46


def theme_is_day(preferences, now: datetime | None = None, wall_luminance: float | None = None,
                 was_day: bool | None = None) -> bool:
    """True = light islands.  Modes: auto_time | wallpaper | system | light | dark."""
    mode = str(getattr(preferences, "theme_mode", "auto_time") or "auto_time")
    if mode == "light":
        return True
    if mode == "dark":
        return False
    if mode == "system":
        dark = system_prefers_dark()
        if dark is not None:
            return not dark
    if mode == "wallpaper" and wall_luminance is not None:
        threshold = WALL_LIGHT_OFF if was_day else WALL_LIGHT_ON
        return float(wall_luminance) >= threshold
    return is_daytime(str(getattr(preferences, "day_start", "07:00")),
                      str(getattr(preferences, "night_start", "19:00")), now)


_DEFAULT_FONT: str | None = None
FONT_CANDIDATES = ("Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans SC", "Noto Sans CJK SC",
                   "Source Han Sans SC", "WenQuanYi Micro Hei", "Segoe UI", "Noto Sans")


def default_font_family() -> str:
    """UI font when the user has not chosen one: the first installed CJK-capable sans family."""
    global _DEFAULT_FONT
    if _DEFAULT_FONT is None:
        try:
            from PySide6.QtGui import QFontDatabase

            families = set(QFontDatabase.families())
        except Exception:  # noqa: BLE001 - before QGuiApplication
            return "Microsoft YaHei UI" if sys.platform == "win32" else ""
        _DEFAULT_FONT = next((f for f in FONT_CANDIDATES if f in families), "")
    return _DEFAULT_FONT


_LOADED_FONT_FILES: dict[str, str] = {}


def load_font_file(path: str) -> str:
    """Register a .ttf/.otf/.ttc file for this process; returns its family ("" on failure)."""
    if not path:
        return ""
    key = str(Path(path))
    if key in _LOADED_FONT_FILES:
        return _LOADED_FONT_FILES[key]
    if not Path(key).is_file():
        return ""
    try:
        from PySide6.QtGui import QFontDatabase

        font_id = QFontDatabase.addApplicationFont(key)
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    except Exception:  # noqa: BLE001
        families = []
    family = str(families[0]) if families else ""
    if family:
        _LOADED_FONT_FILES[key] = family
    return family


class ThemeBridge(QObject):
    changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._prefs = None
        self._dark = True
        self._raw_accent = QColor("#5AA9FF")
        self._wall_lum = 0.35
        self._tokens = dict(DEFAULT_TOKENS)
        self._custom_path: Path | None = None
        self._font_family = ""
        self._timer = QTimer(self)
        self._timer.setInterval(30_000)
        self._timer.timeout.connect(self.reevaluate)
        self._timer.start()
        app = QGuiApplication.instance()
        if app is not None:
            try:
                app.styleHints().colorSchemeChanged.connect(lambda *_: self.reevaluate())
            except (AttributeError, RuntimeError):
                pass

    # Inputs -----------------------------------------------------------------
    def set_preferences(self, prefs) -> None:
        self._prefs = prefs
        family = str(getattr(prefs, "font_family", "") or "")
        font_file = str(getattr(prefs, "font_file", "") or "")
        if font_file:
            loaded = load_font_file(font_file)
            if loaded and not family:
                family = loaded
        self._font_family = family
        self.reevaluate(force=True)

    def set_wallpaper_accent(self, color: QColor, wall_luminance: float) -> None:
        self._raw_accent = QColor(color)
        self._wall_lum = round(float(wall_luminance), 2)
        if self._prefs is not None and getattr(self._prefs, "theme_mode", "") == "wallpaper":
            self.reevaluate()
        self._emit_if_changed()

    def _signature(self) -> tuple:
        """Every value QML can read; ``changed`` is only emitted when this differs (a live
        wallpaper reports the same accent over and over - re-evaluating every binding of every
        window for nothing made the settings window flicker)."""
        values = []
        for getter in (self._get_dark, self._get_accent, self._get_wall_accent, self._get_text,
                       self._get_text_dim, self._get_text_faint, self._get_material, self._get_strength,
                       self._get_font_family, self._get_font_size, self._get_reduce_motion,
                       self._get_wall_luminance):
            value = getter()
            values.append(value.rgba() if isinstance(value, QColor) else value)
        values.append(tuple(sorted((str(k), repr(v)) for k, v in self._tokens.items())))
        return tuple(values)

    def _emit_if_changed(self) -> None:
        signature = self._signature()
        if signature != getattr(self, "_last_signature", None):
            self._last_signature = signature
            self.changed.emit()

    def load_custom(self, path: Path | None) -> list[str]:
        """Read ``theme.json``; returns problems (shown in the settings)."""
        self._custom_path = path
        tokens = dict(DEFAULT_TOKENS)
        problems: list[str] = []
        if path is not None and path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError("theme.json 顶层必须是对象")
                for key, value in data.items():
                    if key.startswith("$") or key == "comment":
                        continue
                    if key in DEFAULT_TOKENS and not isinstance(value, (int, float)):
                        problems.append("{0} 应为数字".format(key))
                        continue
                    tokens[key] = value
            except (OSError, ValueError) as exc:
                problems.append(str(exc))
        self._tokens = tokens
        self._emit_if_changed()
        return problems

    @Slot()
    def reevaluate(self, force: bool = False) -> None:
        prefs = self._prefs
        dark = (not theme_is_day(prefs, wall_luminance=self._wall_lum, was_day=not self._dark)
                if prefs is not None else True)
        self._dark = dark
        self._emit_if_changed()

    # Helpers ------------------------------------------------------------------
    def _tok(self, name: str) -> float:
        try:
            return float(self._tokens.get(name, DEFAULT_TOKENS.get(name, 0)))
        except (TypeError, ValueError):
            return float(DEFAULT_TOKENS.get(name, 0))

    @Slot(str, "QVariant", result="QVariant")
    def tok(self, name: str, fallback=None):
        return self._tokens.get(name, fallback)

    @Slot(result="QVariantList")
    def fontFamilies(self):  # noqa: N802
        """Settings font picker: [{name, cjk}] - Chinese-capable families first."""
        try:
            from PySide6.QtGui import QFontDatabase

            result = []
            for family in QFontDatabase.families():
                if not family or family.startswith("@") or QFontDatabase.isPrivateFamily(family):
                    continue
                systems = QFontDatabase.writingSystems(family)
                cjk = QFontDatabase.WritingSystem.SimplifiedChinese in systems
                result.append({"name": family, "cjk": bool(cjk)})
        except Exception:  # noqa: BLE001
            return []
        result.sort(key=lambda f: (not f["cjk"], f["name"].casefold()))
        return result

    @Slot(int, result=int)
    def ms(self, duration: int) -> int:
        """Animation duration honouring “减少动态效果” and the motion token."""
        if self._prefs is not None and getattr(self._prefs, "reduce_motion", False):
            return 0
        return int(max(0.0, duration * self._tok("motion")))

    # Properties ---------------------------------------------------------------
    def _get_dark(self) -> bool:
        return self._dark

    def _get_accent(self) -> QColor:
        return tune_accent(self._raw_accent, self._dark)

    def _get_accent_soft(self) -> QColor:
        return _color(self._get_accent(), 0.22 if self._dark else 0.18)

    def _get_on_accent(self) -> QColor:
        accent = self._get_accent()
        return QColor("#0B0F14") if luminance(accent) > 0.45 else QColor("#FFFFFF")

    def _get_wall_accent(self) -> QColor:
        return QColor(self._raw_accent)

    def _text_rgb(self) -> tuple:
        """Base text colour: the theme's, or the 文字颜色 preference."""
        mode = str(getattr(self._prefs, "text_color_mode", "auto") or "auto") if self._prefs is not None else "auto"
        if mode == "custom":
            color = QColor(str(getattr(self._prefs, "text_color", "") or ""))
            if color.isValid():
                return color.red(), color.green(), color.blue(), luminance(color) > 0.4
        light = mode == "light" or (mode not in ("dark", "custom") and self._dark)
        return (244, 247, 251, True) if light else (17, 22, 29, False)

    def _get_text(self) -> QColor:
        r, g, b, _light = self._text_rgb()
        return QColor(r, g, b)

    def _get_text_dim(self) -> QColor:
        r, g, b, light = self._text_rgb()
        return QColor(r, g, b, 178 if light else 168)

    def _get_text_faint(self) -> QColor:
        r, g, b, light = self._text_rgb()
        return QColor(r, g, b, 112 if light else 110)

    def _get_hairline(self) -> QColor:
        return QColor(255, 255, 255, 34) if self._dark else QColor(0, 0, 0, 26)

    def _get_hover(self) -> QColor:
        return QColor(255, 255, 255, 26) if self._dark else QColor(0, 0, 0, 16)

    def _get_pressed(self) -> QColor:
        return QColor(255, 255, 255, 44) if self._dark else QColor(0, 0, 0, 28)

    def _get_danger(self) -> QColor:
        return QColor("#FF6B6B") if self._dark else QColor("#D63B3B")

    def _get_material(self) -> str:
        return str(getattr(self._prefs, "island_material", "liquid") or "liquid")

    def _get_strength(self) -> float:
        base = float(getattr(self._prefs, "glass_strength", 1.0) or 1.0) if self._prefs is not None else 1.0
        return base * self._tok("glassStrength")

    def _get_radius(self) -> float:
        return self._tok("radius")

    def _get_small_radius(self) -> float:
        return self._tok("smallRadius")

    def _get_bar_height(self) -> float:
        return self._tok("barHeight")

    def _get_header_height(self) -> float:
        return self._tok("headerHeight")

    def _get_shadow(self) -> float:
        return self._tok("shadow")

    def _get_font_family(self) -> str:
        return self._font_family or default_font_family()

    def _get_font_size(self) -> float:
        size = float(getattr(self._prefs, "font_size", 10.0) or 10.0) if self._prefs is not None else 10.0
        # Preferences store points (1.x); QML wants pixels at 96 dpi.
        return round(size * 96.0 / 72.0 * self._tok("fontScale"), 1)

    def _get_reduce_motion(self) -> bool:
        return bool(getattr(self._prefs, "reduce_motion", False)) if self._prefs is not None else False

    def _get_wall_luminance(self) -> float:
        return self._wall_lum

    def _get_tokens(self) -> dict:
        return dict(self._tokens)

    dark = Property(bool, _get_dark, notify=changed)
    accent = Property(QColor, _get_accent, notify=changed)
    accentSoft = Property(QColor, _get_accent_soft, notify=changed)
    onAccent = Property(QColor, _get_on_accent, notify=changed)
    wallAccent = Property(QColor, _get_wall_accent, notify=changed)
    text = Property(QColor, _get_text, notify=changed)
    textDim = Property(QColor, _get_text_dim, notify=changed)
    textFaint = Property(QColor, _get_text_faint, notify=changed)
    hairline = Property(QColor, _get_hairline, notify=changed)
    hover = Property(QColor, _get_hover, notify=changed)
    pressed = Property(QColor, _get_pressed, notify=changed)
    danger = Property(QColor, _get_danger, notify=changed)
    material = Property(str, _get_material, notify=changed)
    strength = Property(float, _get_strength, notify=changed)
    radius = Property(float, _get_radius, notify=changed)
    smallRadius = Property(float, _get_small_radius, notify=changed)
    barHeight = Property(float, _get_bar_height, notify=changed)
    headerHeight = Property(float, _get_header_height, notify=changed)
    shadow = Property(float, _get_shadow, notify=changed)
    fontFamily = Property(str, _get_font_family, notify=changed)
    fontSize = Property(float, _get_font_size, notify=changed)
    reduceMotion = Property(bool, _get_reduce_motion, notify=changed)
    wallLuminance = Property(float, _get_wall_luminance, notify=changed)
    tokens = Property("QVariantMap", _get_tokens, notify=changed)


__all__ = ["DEFAULT_TOKENS", "ThemeBridge"]

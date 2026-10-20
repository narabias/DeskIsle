from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir
from PySide6.QtGui import QColor, QFont, QFontDatabase


APP_NAME = "桌屿 DeskIsle"
DATA_VERSION = 1
TRANSPARENT_KEY = QColor(1, 2, 3)

# iOS-like dark palette.  The brand accent stays DeskIsle's teal, but it is
# used sparingly (switches, primary buttons, focus rings) like iOS tint colour.
ACCENT = "#55D6BE"
ACCENT_HOVER = "#70E5D0"
ACCENT_TEXT = "#0E1F1C"
TEXT = "#F5F5F7"
TEXT_MUTED = "#A1A1A8"
TEXT_TERTIARY = "#6C6C70"
SURFACE = "#1C1C1E"
SURFACE_ALT = "#2C2C2E"
SURFACE_RAISED = "#3A3A3C"
SEPARATOR = "rgba(255,255,255,22)"
DANGER = "#FF453A"

ISLAND_COLORS = [
    "#243245",
    "#263A3B",
    "#3A3048",
    "#44342F",
    "#26384A",
    "#343843",
]

# Extra tints offered by the appearance dialog (kept separate so the default
# palette used for new islands does not change for existing users).
TINT_SWATCHES = ISLAND_COLORS + ["#1C1C1E", "#2B2F3A", "#1F3A5F", "#3B2A4D", "#4A2F3A", "#2F4A3A"]

UI_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "ui"
QDir.addSearchPath("deskisle", str(UI_ASSET_DIR))

DEFAULT_FAMILIES = [
    "Segoe UI Variable Text",
    "Segoe UI",
    "Microsoft YaHei UI",
    "PingFang SC",
    "Noto Sans SC",
    "Noto Sans CJK SC",
]
_ui_family = ""
_ui_size = 10.0
_loaded_font_files: dict[str, str] = {}


def ui_families() -> list[str]:
    families = list(DEFAULT_FAMILIES)
    if _ui_family:
        families = [_ui_family] + [name for name in families if name != _ui_family]
    return families


def ui_font_size() -> float:
    return _ui_size


def font_stack() -> str:
    return ", ".join("'{0}'".format(name.replace("'", "")) for name in ui_families())


def set_ui_font(family: str = "", size: float = 10.0) -> None:
    global _ui_family, _ui_size
    _ui_family = (family or "").strip()
    try:
        _ui_size = max(7.0, min(20.0, float(size)))
    except (TypeError, ValueError):
        _ui_size = 10.0


def ui_font(point_size: float | None = None, weight: QFont.Weight | None = None) -> QFont:
    font = QFont()
    font.setFamilies(ui_families())
    font.setPointSizeF(point_size if point_size else _ui_size)
    if weight is not None:
        font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def load_font_file(path: str) -> str | None:
    """Register a .ttf/.otf/.ttc file for this process and return its family."""
    if not path:
        return None
    key = str(Path(path))
    if key in _loaded_font_files:
        return _loaded_font_files[key]
    if not Path(key).is_file():
        return None
    font_id = QFontDatabase.addApplicationFont(key)
    if font_id < 0:
        return None
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        return None
    _loaded_font_files[key] = families[0]
    return families[0]


def apply_app_font(app, family: str = "", size: float = 10.0, font_file: str = "") -> str:
    """Apply the user's font everywhere; returns the family actually used."""
    chosen = (family or "").strip()
    if font_file:
        loaded = load_font_file(font_file)
        if loaded and (not chosen or chosen == loaded or chosen not in QFontDatabase.families()):
            chosen = loaded
    if chosen and chosen not in QFontDatabase.families():
        chosen = ""
    set_ui_font(chosen, size)
    if app is not None:
        app.setFont(ui_font())
        app.setStyleSheet(app_stylesheet())
    return chosen


def app_stylesheet() -> str:
    size = "{0:.1f}pt".format(_ui_size)
    return f"""
    QDialog, QMainWindow {{ background: {SURFACE}; color: {TEXT}; }}
    QWidget {{ color: {TEXT}; font-family: {font_stack()}; font-size: {size}; }}
    QLabel#muted {{ color: {TEXT_MUTED}; }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget, QTableWidget, QFontComboBox {{
        background: {SURFACE_ALT}; border: 1px solid rgba(255,255,255,20); border-radius: 9px;
        padding: 6px 10px; selection-background-color: rgba(85,214,190,110);
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{ border-color: {ACCENT}; }}
    QComboBox::drop-down {{ border: 0; width: 24px; }}
    QComboBox::down-arrow {{ image: url(deskisle:chevron-down.svg); width: 12px; height: 12px; }}
    QComboBox QAbstractItemView {{
        background: #2C2C2E; border: 1px solid rgba(255,255,255,26); border-radius: 10px; padding: 4px;
        selection-background-color: rgba(255,255,255,30); outline: 0;
    }}
    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        border: 0; width: 18px; background: transparent;
    }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{ image: url(deskisle:chevron-up.svg); width: 10px; height: 10px; }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{ image: url(deskisle:chevron-down.svg); width: 10px; height: 10px; }}
    QPushButton {{
        background: rgba(255,255,255,26); border: 0; border-radius: 10px;
        padding: 7px 16px; color: {TEXT};
    }}
    QPushButton:hover {{ background: rgba(255,255,255,38); }}
    QPushButton:pressed {{ background: rgba(255,255,255,16); }}
    QPushButton:disabled {{ color: rgba(235,235,245,80); background: rgba(255,255,255,12); }}
    QPushButton#primary {{ background: {ACCENT}; color: {ACCENT_TEXT}; font-weight: 600; }}
    QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
    QPushButton#primary:pressed {{ background: #46B7A3; }}
    QPushButton#danger {{ color: #FF6961; }}
    QCheckBox, QRadioButton {{ spacing: 9px; }}
    QCheckBox::indicator {{
        width: 18px; height: 18px; border-radius: 9px; border: 2px solid #636366; background: transparent;
    }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url(deskisle:check-dark.svg); }}
    QRadioButton::indicator {{
        width: 18px; height: 18px; border-radius: 9px; border: 2px solid #636366; background: transparent;
    }}
    QRadioButton::indicator:checked {{
        border-color: {ACCENT};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0 {ACCENT}, stop:0.45 {ACCENT}, stop:0.5 transparent, stop:1 transparent);
    }}
    QSlider::groove:horizontal {{ height: 4px; background: rgba(255,255,255,40); border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
    QSlider::handle:horizontal {{
        width: 20px; height: 20px; margin: -8px 0; border-radius: 10px;
        background: #FFFFFF; border: 1px solid rgba(0,0,0,40);
    }}
    QTabWidget::pane {{ border: 1px solid rgba(255,255,255,20); border-radius: 10px; }}
    QTabBar::tab {{ background: {SURFACE_ALT}; padding: 8px 14px; margin-right: 2px; border-radius: 8px; }}
    QTabBar::tab:selected {{ background: {SURFACE_RAISED}; color: white; }}
    QMenu {{
        background: rgba(40,40,44,240); border: 1px solid rgba(255,255,255,30);
        border-radius: 12px; padding: 6px;
    }}
    QMenu::item {{ padding: 7px 28px 7px 14px; border-radius: 7px; color: {TEXT}; background: transparent; }}
    QMenu::item:selected {{ background: rgba(255,255,255,34); }}
    QMenu::item:disabled {{ color: rgba(235,235,245,90); }}
    QMenu::separator {{ height: 1px; background: rgba(255,255,255,24); margin: 5px 10px; }}
    QMenu::indicator {{ width: 16px; height: 16px; left: 6px; }}
    QMenu::indicator:checked {{ image: url(deskisle:check.svg); }}
    QMenu::right-arrow {{ image: url(deskisle:chevron-right.svg); width: 12px; height: 12px; right: 8px; }}
    QToolTip {{
        background: rgba(44,44,46,248); color: {TEXT}; border: 1px solid rgba(255,255,255,30);
        border-radius: 8px; padding: 5px 8px;
    }}
    QScrollBar:vertical {{ width: 8px; background: transparent; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: rgba(255,255,255,64); border-radius: 3px; min-height: 28px; }}
    QScrollBar::handle:vertical:hover {{ background: rgba(255,255,255,96); }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
    QScrollBar:horizontal {{ height: 8px; background: transparent; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: rgba(255,255,255,64); border-radius: 3px; min-width: 28px; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    """

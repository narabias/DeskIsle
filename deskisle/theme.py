from __future__ import annotations

from PySide6.QtGui import QColor


APP_NAME = "桌屿 DeskIsle"
DATA_VERSION = 1
TRANSPARENT_KEY = QColor(1, 2, 3)

ACCENT = "#55D6BE"
ACCENT_HOVER = "#70E5D0"
TEXT = "#F4F7FB"
TEXT_MUTED = "#AAB4C4"
SURFACE = "#202938"
SURFACE_ALT = "#2A3547"
DANGER = "#FF6B78"

ISLAND_COLORS = [
    "#243245",
    "#263A3B",
    "#3A3048",
    "#44342F",
    "#26384A",
    "#343843",
]


def app_stylesheet() -> str:
    return """
    QDialog, QMainWindow { background: #151B25; color: #F4F7FB; }
    QWidget { color: #F4F7FB; font-family: 'Segoe UI', 'Microsoft YaHei UI'; font-size: 10pt; }
    QLabel#muted { color: #AAB4C4; }
    QLineEdit, QComboBox, QSpinBox, QListWidget, QTableWidget {
        background: #202938; border: 1px solid #36445A; border-radius: 7px;
        padding: 6px; selection-background-color: #3E7E78;
    }
    QPushButton {
        background: #2A3547; border: 1px solid #3B4A61; border-radius: 7px;
        padding: 7px 13px;
    }
    QPushButton:hover { background: #35445A; border-color: #55D6BE; }
    QPushButton:pressed { background: #1E2938; }
    QPushButton#primary { background: #3E8F83; border-color: #55D6BE; font-weight: 600; }
    QPushButton#danger { color: #FF9DA5; }
    QCheckBox { spacing: 8px; }
    QTabWidget::pane { border: 1px solid #344256; border-radius: 8px; }
    QTabBar::tab { background: #202938; padding: 8px 14px; margin-right: 2px; }
    QTabBar::tab:selected { background: #31554F; color: white; }
    QMenu { background: #202938; border: 1px solid #3B4A61; padding: 5px; }
    QMenu::item { padding: 7px 24px 7px 10px; border-radius: 5px; }
    QMenu::item:selected { background: #31554F; }
    QToolTip { background: #202938; color: white; border: 1px solid #55D6BE; padding: 4px; }
    """

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import traceback
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QLockFile, Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from deskisle import html_view, theme
from deskisle.board import DesktopWindow
from deskisle.models import AppState, IslandState, ItemRef, PageState, Rule, TabState
from deskisle.native_win import restore_native_desktop_icons
from deskisle.storage import StateStore
from deskisle.theme import APP_NAME, ISLAND_COLORS

DEMO_ANIMATION = Path(__file__).resolve().parent / "deskisle" / "assets" / "demo" / "aurora.html"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="桌屿 DeskIsle Windows 桌面整理器")
    parser.add_argument("--demo", action="store_true", help="以普通窗口运行，不挂接 Windows 桌面")
    parser.add_argument("--data-dir", type=Path, help="覆盖数据目录")
    parser.add_argument("--reset", action="store_true", help="备份并重建默认布局")
    parser.add_argument('--self-test', type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def demo_state() -> AppState:
    windows = Path(os.environ.get("WINDIR", r"C:\Windows"))
    home = Path.home()
    applications = TabState(
        title="常用",
        items=[
            ItemRef(path=str(windows / "System32" / "notepad.exe"), title="记事本"),
            ItemRef(path=str(windows / "explorer.exe"), title="文件资源管理器"),
            ItemRef(path=str(windows / "System32" / "calc.exe"), title="计算器"),
        ],
    )
    docs = TabState(
        title="文档",
        items=[
            ItemRef(path=str(home / "Documents"), title="文档"),
            ItemRef(path=str(home / "Downloads"), title="下载"),
            ItemRef(path=str(home / "Pictures"), title="图片"),
        ],
    )
    portal = TabState(title="下载", portal_path=str(home / "Downloads"))
    page = PageState(
        title="工作台",
        islands=[
            IslandState(
                title="今日常用",
                x=54,
                y=105,
                width=360,
                height=275,
                color=ISLAND_COLORS[0],
                tabs=[applications, docs],
                active_tab_id=applications.id,
            ),
            IslandState(
                title="文件视窗",
                x=440,
                y=105,
                width=410,
                height=380,
                color=ISLAND_COLORS[1],
                tabs=[portal],
                active_tab_id=portal.id,
            ),
            IslandState(
                title="稍后处理",
                x=875,
                y=105,
                width=330,
                height=260,
                color=ISLAND_COLORS[2],
                tabs=[TabState(title="收集箱")],
                material="liquid",
            ),
            IslandState(
                title="HTML 动画",
                x=875,
                y=390,
                width=330,
                height=230,
                color=ISLAND_COLORS[3],
                tabs=[TabState(title="全部")],
                kind="html",
                html_path=str(DEMO_ANIMATION) if DEMO_ANIMATION.is_file() else "",
            ),
        ],
    )
    state = AppState(pages=[page], current_page_id=page.id)
    state.rules = [
        Rule(name="图片", condition="extension", value=".png;.jpg;.jpeg", target_island_id=page.islands[2].id, priority=10),
    ]
    state.loose_items = []
    return state


def install_exception_guard(app: QApplication) -> None:
    def handle_exception(exc_type, exc_value, exc_traceback) -> None:
        restore_native_desktop_icons()
        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        data_root = Path(os.environ.get("LOCALAPPDATA", tempfile.gettempdir())) / "DeskIsle"
        try:
            data_root.mkdir(parents=True, exist_ok=True)
            (data_root / "crash.log").write_text(details, encoding="utf-8")
        except OSError:
            pass
        QMessageBox.critical(None, "桌屿发生错误", "应用遇到错误，原生桌面图标已恢复。\n\n" + str(exc_value))

    sys.excepthook = handle_exception


def apply_saved_font(app: QApplication, state: AppState) -> None:
    prefs = state.preferences
    try:
        size = float(getattr(prefs, "font_size", 10.0) or 10.0)
    except (TypeError, ValueError):
        size = 10.0
    theme.apply_app_font(app, str(getattr(prefs, "font_family", "") or ""), size,
                         str(getattr(prefs, "font_file", "") or ""))


def main() -> int:
    args = parse_args()
    if args.self_test:
        from deskisle.selftest import run
        return run(args.self_test)
    QCoreApplication.setOrganizationName("DeskIsle")
    QCoreApplication.setApplicationName("DeskIsle")
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    # HTML / web islands: WebEngine must be configured before QApplication.
    html_view.prepare_application()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(bool(args.demo))
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    theme.apply_app_font(app)
    install_exception_guard(app)

    if args.demo:
        root = args.data_dir or (Path(tempfile.gettempdir()) / "DeskIsleDemo")
        store = StateStore(root)
        state = demo_state()
    else:
        root = args.data_dir or (Path(os.environ.get("DESKISLE_DATA_DIR")) if os.environ.get("DESKISLE_DATA_DIR") else None)
        store = StateStore(root)
        store.root.mkdir(parents=True, exist_ok=True)
        instance_lock = QLockFile(str(store.root / 'instance.lock'))
        instance_lock.setStaleLockTime(0)
        if not instance_lock.tryLock(0):
            QMessageBox.information(None, APP_NAME, '桌屿已经在运行，请使用系统托盘中的桌屿图标。')
            return 0
        if args.reset:
            try:
                existing = store.load()
                store.save_snapshot(existing, "重置前自动备份")
            except Exception:
                pass
            desktop = Path.home() / "Desktop"
            try:
                desktop_items = list(desktop.iterdir()) if desktop.is_dir() else []
            except OSError:
                desktop_items = []
            state = store.create_default_state(desktop_items)
            store.save(state)
        else:
            state = store.load()
        try:
            # Drop copied background media no layout or snapshot refers to.
            store.prune_media(state)
        except Exception:
            pass

    apply_saved_font(app, state)
    window = DesktopWindow(state, store, demo_mode=args.demo)
    window.show()
    exit_code = app.exec()
    if not args.demo:
        instance_lock.unlock()
    restore_native_desktop_icons()
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())

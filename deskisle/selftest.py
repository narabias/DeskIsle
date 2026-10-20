"""Opt-in packaged-app smoke test. Uses isolated data, never the live desktop."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import shutil
from contextlib import contextmanager
from uuid import uuid4
import traceback


@contextmanager
def _workspace(parent):
    parent = parent.resolve()
    root = parent / ('.selftest-' + uuid4().hex)
    root.mkdir(parents=True)
    try:
        yield root
    finally:
        if root.resolve().is_relative_to(parent):
            shutil.rmtree(root)


def run(report_path: Path) -> int:
    os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication
    from .board import DesktopWindow, _tabler_icon
    from .island import CONTENT_TOP
    from .models import AppState, IslandState, ItemRef, PageState, TabState
    from .storage import StateStore
    from .theme import app_stylesheet
    app = QApplication.instance() or QApplication([])
    app.setStyle('Fusion')
    font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts/msyh.ttc'
    if font_path.exists():
        QFontDatabase.addApplicationFont(str(font_path))
    app.setFont(QFont('Microsoft YaHei', 10))
    app.setStyleSheet(app_stylesheet())
    report = {}
    window = None
    try:
        with _workspace(report_path.parent) as folder:
            root = Path(folder)
            items = []
            for i in range(40):
                path = root / f'item-{i}.txt'
                path.write_text('test', encoding='utf-8')
                items.append(ItemRef(path=str(path)))
            tab = TabState(title='常用', items=items)
            island = IslandState(title='界面验证', width=440, height=480, tabs=[tab, TabState(title='全部')])
            page = PageState(islands=[island])
            state = AppState(pages=[page], current_page_id=page.id)
            window = DesktopWindow(state, StateStore(root / 'data'), demo_mode=True)
            window.show()
            app.processEvents()
            widget = window.islands[island.id]
            window.search.show()
            app.processEvents()
            search_image = window.search.grab().toImage()
            assert search_image.pixelColor(0, 0).alpha() == 0
            assert search_image.pixelColor(20, 20).alpha() > 0
            window.search.hide()
            assert not _tabler_icon('settings').pixmap(40, 40).isNull()
            assert widget.tabs_row.geometry().bottom() < CONTENT_TOP - 4
            widget.item_list.verticalScrollBar().setValue(100)
            scroll = widget.item_list.verticalScrollBar().value()
            widget.toggle_collapsed()
            QTest.qWait(50)
            assert widget._collapse_animating
            assert 44 < widget._visual_height < island.height
            widget.toggle_collapsed()
            QTest.qWait(210)
            assert widget.height() == 480 and not island.collapsed
            assert widget.item_list.verticalScrollBar().value() == scroll
            widget.toggle_collapsed()
            QTest.qWait(210)
            assert widget.height() == 44 and island.height == 480
            widget.toggle_collapsed()
            QTest.qWait(210)
            widget._begin_move()
            widget._move_by(QPoint(20, 30))
            widget._commit_geometry()
            window.save_state()
            assert window.store.load().pages[0].islands[0].height == 480
            report_path.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(report_path.with_suffix('.png')))
            report['ui'] = 'passed'
            if os.name == 'nt':
                if getattr(sys, 'frozen', False):
                    command = [str(Path(sys.executable).with_name('DeskIsleShellMenu.exe'))]
                else:
                    command = [sys.executable, '-B', '-m', 'deskisle.shell_menu']
                result = subprocess.run(command, input=json.dumps({'paths': [r'C:\Windows\System32\notepad.exe'], 'probe': True}).encode(),
                                        capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW)
                menu = json.loads(result.stdout.decode('utf-8'))
                assert 'runas' in menu.get('verbs', []), menu
                assert menu['extended_menu']
                report['native_menu'] = 'passed'
            window._closing_for_real = True
            window.close()
            report['status'] = 'passed'
    except Exception:
        report['status'] = 'failed'
        report['error'] = traceback.format_exc()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if report['status'] == 'passed' else 1

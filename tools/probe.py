"""Developer probe: run the demo, execute a few UI steps and grab screenshots.

    python tools/probe.py --out shots step step ...

Steps: wait:<ms>  grab:<name>  panel:<name>  close  settings:<page>  menu:<context>
       notice  confirm  action:<name>  pref:<name>=<json>  hide  focus  eval:<python>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    import faulthandler

    faulthandler.enable()
    if os.environ.get("PROBE_HANG"):
        faulthandler.dump_traceback_later(int(os.environ["PROBE_HANG"]), repeat=True)
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "deskisle-shots"))
    parser.add_argument("--size", default="1440x900")
    parser.add_argument("--layer", default="", help="use another QML file for the layer windows")
    parser.add_argument("steps", nargs="*")
    args = parser.parse_args()
    width, height = (int(v) for v in args.size.split("x"))
    os.environ["DESKISLE_DEMO_W"] = str(width)
    os.environ["DESKISLE_DEMO_H"] = str(height)

    from PySide6.QtCore import QPoint, QTimer
    from PySide6.QtWidgets import QApplication

    from deskisle.demo import demo_state
    from deskisle.engine import app as appmod
    from deskisle.storage import StateStore

    appmod.prepare_environment()
    root = Path(tempfile.mkdtemp(prefix="deskisle-probe-"))
    appmod.setup_logging(root, verbose=True)
    appmod.init_web_engine()
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    store = StateStore(root)
    state = demo_state(root)
    app = appmod.DeskIsleApp(qapp, store, state, demo=True, root=root, notes=[], recovered=False)
    if args.layer:
        from deskisle.engine.layer import LayerManager

        original = LayerManager.create_window

        def create_window(self, name, props):
            return original(self, args.layer if name == "Layer.qml" else name, props)

        LayerManager.create_window = create_window
    app.build()
    app.start()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    steps = list(args.steps) or ["wait:2500", "grab:desk"]
    holder: list = []

    def grab(name: str) -> None:
        for key, window in app.layers.windows.items():
            path = out / "{0}.png".format(name if len(app.layers.windows) == 1 else name + "-" + key[:6])
            window.grabWindow().save(str(path))
            print("grab", path, flush=True)
        for key, window in getattr(app.layers, "pinned", {}).items():
            path = out / "{0}-pin-{1}.png".format(name, str(key)[:6])
            window.grabWindow().save(str(path))
            print("grab", path, flush=True)
        if app.settings_window is not None and app.settings_window.isVisible():
            path = out / "{0}-settings.png".format(name)
            app.settings_window.grabWindow().save(str(path))
            print("grab", path, flush=True)
        if app.menu_window is not None and app.menu_window.isVisible():
            path = out / "{0}-menu.png".format(name)
            app.menu_window.grabWindow().save(str(path))
            print("grab", path, flush=True)
        # Popup windows (panels / confirmation / notices), also composed onto the first layer.
        popups = [(role, w) for role, w in getattr(app, "popups", {}).items() if w.isVisible()]
        if popups and app.layers.windows:
            from PySide6.QtGui import QPainter

            layer = next(iter(app.layers.windows.values()))
            canvas = layer.grabWindow()
            painter = QPainter(canvas)
            for role, window in popups:
                image = window.grabWindow()
                image.save(str(out / "{0}-{1}.png".format(name, role)))
                painter.drawImage(window.x() - layer.x(), window.y() - layer.y(), image)
            painter.end()
            path = out / "{0}-all.png".format(name)
            canvas.save(str(path))
            print("grab", path, flush=True)

    def key0() -> str:
        return next(iter(app.desk.scenes))

    def run(index: int) -> None:
        if index >= len(steps):
            QTimer.singleShot(200, qapp.quit)
            return
        step = steps[index]
        kind, _, arg = step.partition(":")
        delay = 350
        print("step", step, flush=True)
        try:
            if kind == "wait":
                delay = int(arg or 500)
            elif kind == "grab":
                grab(arg or "shot{0}".format(index))
            elif kind == "panel":
                app.desk.openPanel(arg, key0(), "")
                delay = 700
            elif kind == "close":
                app.desk.closePanel()
                app.close_menu()
            elif kind == "settings":
                app.open_settings(arg)
                delay = 1200
            elif kind == "menu":
                app.show_menu(arg or "desktop", QPoint(400, 300))
                delay = 600
            elif kind == "notice":
                app.desk.show_notice("测试通知", arg or "这是一条测试通知，用来检查布局。", "info",
                                     [{"id": "ok", "text": "知道了"}], 20000)
            elif kind == "confirm":
                app.desk.confirm("删除小岛？", "将删除“工作”小岛，里面的图标会回到桌面。", "删除",
                                 lambda: print("confirm accepted"), source=arg or "agent")
                delay = 700
            elif kind == "action":
                name, _, rest = arg.partition("=")
                app.desk.action(name, json.loads(rest) if rest else {})
            elif kind == "pref":
                name, _, rest = arg.partition("=")
                app.desk.setPref(name, json.loads(rest))
            elif kind == "hide":
                app.desk.toggleHidden()
                delay = 900
            elif kind == "focus":
                app.desk.toggleFocus()
                delay = 900
            elif kind == "snippet":
                # snippet:<qml body> -> created as a child item of the first layer window
                from PySide6.QtCore import QUrl
                from PySide6.QtQml import QQmlComponent

                window = next(iter(app.layers.windows.values()))
                component = QQmlComponent(app.engine)
                component.setData(("import QtQuick\nimport QtQuick.Effects\nimport QtQuick.Shapes\n" + arg).encode(),
                                  QUrl.fromLocalFile(str(ROOT / "deskisle" / "qml" / "_snippet.qml")))
                if component.isError():
                    print("snippet errors", [e.toString() for e in component.errors()], flush=True)
                else:
                    print("creating snippet", flush=True)
                    obj = component.createWithInitialProperties({})
                    print("created snippet", obj, flush=True)
                    if obj is not None:
                        obj.setParentItem(window.contentItem())
                        obj.setProperty("deskLayer", window)
                        holder.append(obj)
            elif kind == "eval":
                exec(arg, {"app": app, "desk": app.desk, "qapp": qapp})
        except Exception as exc:  # noqa: BLE001
            import traceback

            traceback.print_exc()
            print("step failed", step, exc, flush=True)
        QTimer.singleShot(delay, lambda: run(index + 1))

    QTimer.singleShot(1500, lambda: run(0))
    QTimer.singleShot(120000, qapp.quit)
    code = qapp.exec()
    app.shutdown()
    return int(code)


if __name__ == "__main__":
    sys.exit(main())

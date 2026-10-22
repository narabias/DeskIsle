"""End-to-end checks of the 2.0 app: the real ``DeskIsleApp`` in demo mode (offscreen,
software Qt Quick), driven through the same APIs the QML, the menus and the agent use."""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from tests import support

APP: support.DemoApp | None = None


def setUpModule() -> None:  # noqa: N802 - unittest hook
    global APP
    APP = support.DemoApp()


def tearDownModule() -> None:  # noqa: N802 - unittest hook
    global APP
    if APP is not None:
        APP.close()
        APP = None


def desk():
    return APP.desk


def key() -> str:
    return desk().primary_spec().key


def valid(monitor: str = "") -> bool:
    from deskisle import layout

    arranger = desk().arranger
    monitor = monitor or key()
    return layout.layout_valid(arranger.boxes(monitor), arranger.work(monitor), arranger.gap)


def geometry() -> dict:
    page = desk().displayed_page(key())
    return {s.id: (s.x, s.y, s.width, s.height) for s in page.islands}


def commands():
    from deskisle.agent.commands import Commands

    if not hasattr(APP, "commands"):
        APP.commands = Commands(APP.app)
    return APP.commands


def run(name: str, args: dict | None = None, timeout: float = 5.0):
    return commands().run(name, args or {}, timeout)


def files_island(title: str):
    state = desk().add_island("files", monitor_key=key(), title=title, size=(300, 200))
    assert state is not None, "no room for a test island"
    support.spin(50)
    return state


class AppStartTests(unittest.TestCase):
    def test_layers_and_scene(self) -> None:
        self.assertTrue(APP.app.layers.windows)
        page = desk().displayed_page(key())
        self.assertIsNotNone(page)
        self.assertTrue(page.islands)
        self.assertEqual({p.state.id for p in desk().proxies()} >= {s.id for s in page.islands}, True)

    def test_demo_layout_is_valid(self) -> None:
        for spec in desk().monitors():
            self.assertTrue(valid(spec.key), spec.key)

    def test_every_island_inside_work_area(self) -> None:
        work = desk().arranger.work(key())
        for s in desk().displayed_page(key()).islands:
            self.assertGreaterEqual(s.x, work.x, s.title)
            self.assertGreaterEqual(s.y, work.y, s.title)
            self.assertLessEqual(s.x + s.width, work.x + work.w, s.title)

    def test_image_providers_answer_the_warm_up(self) -> None:
        # The warm-up runs in build(); a second round must answer at once (no hung provider).
        from deskisle.engine import icons

        names = ["icon", "wall", "cover"]
        self.assertEqual(icons.prime_image_providers(APP.app.engine, names, timeout_s=3), [])
        self.assertEqual(icons.warmup_image().size().width(), 1)

    def test_a_snapshot_is_saved_before_an_update_installs(self) -> None:
        from unittest import mock

        before = len(desk().store.list_snapshots())
        with mock.patch("deskisle.updater.launch_installer", return_value=False) as launch:
            APP.app._update_downloaded("DeskIsle-Setup-9.9.9-x64.exe")
        launch.assert_called_once()
        names = [p.name for p in desk().store.list_snapshots()]
        self.assertEqual(len(names), before + 1)
        self.assertTrue(any("更新前自动备份" in n for n in names), names)


class IslandTests(unittest.TestCase):
    def test_add_each_kind_keeps_layout_valid(self) -> None:
        made = []
        try:
            for kind, extra in (("files", {}), ("widget", {"widget": "clock"}), ("widget", {"widget": "todo"}),
                                ("web", {"url": "https://example.com"})):
                state = desk().add_island(kind, monitor_key=key(), **extra)
                if state is None:  # the demo desk can be full: that must be reported, not overlap
                    self.assertTrue(valid())
                    continue
                made.append(state.id)
                support.spin(30)
                self.assertTrue(valid(), kind)
                page, found = desk().find_island(state.id)
                self.assertIs(found, state)
                self.assertIs(page, desk().displayed_page(key()))
                self.assertIsNotNone(desk().proxy(state.id))
            self.assertTrue(made)
        finally:
            for uid in made:
                desk().delete_island(uid)
            support.spin(50)
        for uid in made:
            self.assertIsNone(desk().find_island(uid)[1])
        self.assertTrue(valid())

    def test_add_at_requested_position(self) -> None:
        work = desk().arranger.work(key())
        target = (work.x + work.w // 2, work.y + work.h // 2)
        state = desk().add_island("widget", monitor_key=key(), widget="clock", position=target)
        try:
            if state is not None:
                self.assertTrue(valid())
        finally:
            if state is not None:
                desk().delete_island(state.id)

    def test_delete_returns_items_to_loose(self) -> None:
        state = files_island("测试收纳")
        path = str(APP.root / "demo" / "示例桌面" / "随手记.txt")
        loose_before = [i.path for i in desk().state.loose_items]
        state.tabs[0].items.append(__import__("deskisle.models", fromlist=["ItemRef"]).ItemRef(path=path + ".x"))
        self.assertTrue(desk().delete_island(state.id))
        loose = [i.path for i in desk().state.loose_items]
        self.assertIn(path + ".x", loose)
        desk().state.loose_items[:] = [i for i in desk().state.loose_items if i.path in loose_before]

    def test_arrange_then_undo_restores_geometry(self) -> None:
        before = geometry()
        desk().arrange(key())
        support.spin(80)
        self.assertTrue(valid())
        arranged = geometry()
        if arranged != before:
            self.assertTrue(desk().canUndo)
            desk().undo()
            support.spin(80)
            self.assertEqual(geometry(), before)
        self.assertTrue(valid())

    def test_island_actions(self) -> None:
        state = files_island("动作测试")
        uid = state.id
        try:
            desk().island_action(uid, "rename", {"title": "改名了"})
            self.assertEqual(state.title, "改名了")
            desk().island_action(uid, "lock", {"value": True})
            self.assertTrue(state.locked)
            desk().island_action(uid, "lock", {"value": False})
            self.assertFalse(state.locked)
            desk().island_action(uid, "collapse", {"value": True})
            support.spin(50)
            self.assertTrue(state.collapsed)
            desk().island_action(uid, "collapse", {"value": False})
            support.spin(50)
            self.assertFalse(state.collapsed)
            self.assertTrue(valid())
            desk().island_action(uid, "capsule", {"value": True})
            self.assertTrue(state.capsule)
            desk().hoverIsland(uid, True)
            desk().hoverIsland(uid, False)
            desk().island_action(uid, "capsule", {"value": False})
            self.assertFalse(state.capsule)
            desk().island_action(uid, "addTab", {"title": "第二页"})
            self.assertEqual(len(state.tabs), 2)
        finally:
            desk().delete_island(uid)


class AgentCommandTests(unittest.TestCase):
    def test_read_commands(self) -> None:
        for name in ("app.info", "desk.state", "monitor.list", "page.list", "island.list", "item.loose",
                     "widget.types", "prefs.get", "theme.get", "rules.list", "snapshot.list", "clock.info",
                     "media.status", "weather.status", "custom.status", "schema"):
            ok, payload = run(name)
            self.assertTrue(ok, (name, payload))

    def test_island_update_and_make_way(self) -> None:
        ok, created = run("island.create", {"kind": "widget", "widget": "clock", "title": "代理时钟"})
        self.assertTrue(ok, created)
        uid = created["uid"]
        try:
            ok, info = run("island.update", {"uid": uid, "title": "AI 时钟", "material": "clear"})
            self.assertTrue(ok, info)
            self.assertEqual(info["title"], "AI 时钟")
            self.assertEqual(info["material"], "clear")
            # A bigger size pushes the neighbours out of the way instead of overlapping them.
            ok, info = run("island.update", {"uid": uid, "width": info["width"] + 120, "height": info["height"] + 80})
            self.assertTrue(ok, info)
            support.spin(60)
            self.assertTrue(valid())
            # A position takes the nearest free spot.
            work = desk().arranger.work(key())
            ok, info = run("island.update", {"uid": uid, "x": work.x, "y": work.y})
            self.assertTrue(ok, info)
            support.spin(60)
            self.assertTrue(valid())
            ok, info = run("island.update", {"uid": uid, "locked": True})
            self.assertTrue(ok and info["locked"], info)
            ok, info = run("island.update", {"uid": uid, "x": work.x + 40})
            self.assertFalse(ok)
            self.assertEqual(info["code"], "layout")
            ok, info = run("island.update", {"uid": uid, "locked": False, "x": work.x + 40})
            self.assertTrue(ok, info)
            self.assertFalse(info["locked"])
        finally:
            desk().delete_island(uid)
        self.assertTrue(valid())

    def test_invalid_arguments(self) -> None:
        ok, payload = run("island.update", {"uid": 5})
        self.assertFalse(ok)
        self.assertEqual(payload["code"], "invalid_args")
        ok, payload = run("island.get", {"uid": "nope"})
        self.assertFalse(ok)
        self.assertEqual(payload["code"], "not_found")
        ok, payload = run("no.such.command")
        self.assertFalse(ok)
        self.assertEqual(payload["code"], "unknown_command")
        ok, payload = run("island.action", {"uid": "x", "name": "delete"})
        self.assertFalse(ok)
        self.assertEqual(payload["code"], "use_command")

    def test_destructive_commands_wait_for_the_user(self) -> None:
        state = files_island("待删除")
        uid = state.id
        ok, plan = run("island.delete", {"uid": uid, "dry_run": True})
        self.assertTrue(ok, plan)
        self.assertEqual(plan["status"], "dry_run")
        self.assertIsNotNone(desk().find_island(uid)[1])
        self.assertFalse(desk().pending_confirm())

        ok, waiting = run("island.delete", {"uid": uid, "wait": 0})
        self.assertTrue(ok, waiting)
        self.assertEqual(waiting["status"], "pending")
        cid = waiting["confirm_id"]
        pending = desk().pending_confirm()
        self.assertEqual(pending["id"], cid)
        self.assertEqual(pending["source"], "agent")
        self.assertIsNotNone(desk().find_island(uid)[1], "nothing happens before the user answers")
        ok, busy = run("island.delete", {"uid": uid, "wait": 0})
        self.assertFalse(ok)
        self.assertEqual(busy["code"], "busy")

        desk().resolveConfirm(cid, True)
        support.spin(30)
        self.assertIsNone(desk().find_island(uid)[1])
        ok, status = run("confirm.status", {"id": cid})
        self.assertTrue(ok)
        self.assertEqual(status["status"], "accepted")

    def test_rejected_and_blocked_deletes(self) -> None:
        page_count = len(desk().state.pages)
        ok, created = run("page.create", {"title": "临时预设"})
        self.assertTrue(ok, created)
        pid = created["id"]
        ok, waiting = run("page.delete", {"page": pid, "wait": 0})
        self.assertTrue(ok, waiting)
        desk().resolveConfirm(waiting["confirm_id"], False)
        ok, status = run("confirm.status", {"id": waiting["confirm_id"]})
        self.assertEqual(status["status"], "rejected")
        self.assertIsNotNone(desk().state.page(pid))
        # An answer that arrives inside ``wait`` is returned directly.
        from PySide6.QtCore import QTimer

        QTimer.singleShot(150, lambda: desk().resolveConfirm(desk().pending_confirm().get("id", ""), True))
        ok, done = run("page.delete", {"page": pid, "wait": 3}, timeout=5)
        self.assertTrue(ok, done)
        self.assertEqual(done["status"], "accepted")
        self.assertIsNone(desk().state.page(pid))
        self.assertEqual(len(desk().state.pages), page_count)
        main = desk().displayed_page(key())
        self.assertIsNotNone(main)

    def test_todo_through_agent(self) -> None:
        ok, created = run("island.create", {"kind": "widget", "widget": "todo"})
        self.assertTrue(ok, created)
        uid = created["uid"]
        try:
            ok, added = run("todo.add", {"uid": uid, "text": "明天 9点 交周报"})
            self.assertTrue(ok, added)
            ok, listing = run("todo.list", {"uid": uid})
            self.assertTrue(ok, listing)
            self.assertTrue(any("周报" in str(t) for t in listing.get("items", listing.get("todos", []))))
        finally:
            desk().delete_island(uid)


class RuleTests(unittest.TestCase):
    def test_rule_editor_slots(self) -> None:
        target = files_island("规则目标")
        try:
            rid = desk().saveRule({"name": "PDF", "condition": "extension", "value": "pdf", "target": target.id})
            self.assertTrue(rid)
            rules = {r["id"]: r for r in desk().ruleList()}
            self.assertTrue(rules[rid]["valid"])
            self.assertEqual(rules[rid]["targetTitle"], "规则目标")
            other = desk().saveRule({"name": "", "condition": "bogus", "value": " ", "target": target.id})
            rules = {r["id"]: r for r in desk().ruleList()}
            self.assertEqual(rules[other]["condition"], "extension")
            self.assertEqual(rules[other]["name"], "未命名规则")
            self.assertFalse(rules[other]["valid"], "an empty value is flagged")
            desk().moveRule(other, -1)
            order = [r["id"] for r in desk().ruleList()]
            self.assertLess(order.index(other), order.index(rid))
            desk().setRuleEnabled(rid, False)
            self.assertFalse({r["id"]: r for r in desk().ruleList()}[rid]["enabled"])
            desk().saveRule({"id": rid, "name": "PDF 文件", "condition": "extension", "value": "pdf",
                             "target": target.id, "enabled": True})
            self.assertEqual({r["id"]: r for r in desk().ruleList()}[rid]["name"], "PDF 文件")
            priorities = [r["priority"] for r in desk().ruleList()]
            self.assertEqual(priorities, sorted(set(priorities)))
            desk().deleteRule(other)
            self.assertNotIn(other, {r["id"] for r in desk().ruleList()})
        finally:
            desk().delete_island(target.id)
        self.assertNotIn(rid, {r["id"] for r in desk().ruleList()}, "rules of a deleted island go too")

    def test_deleting_a_preset_drops_its_rules(self) -> None:
        main = desk().displayed_page(key())
        page = desk().new_page(key(), "规则预设")
        try:
            target = files_island("预设里的岛")
            rid = desk().saveRule({"name": "zip", "condition": "extension", "value": "zip", "target": target.id})
        finally:
            self.assertTrue(desk().switch_page(key(), main.id))
        self.assertTrue(desk().delete_page(page.id))
        self.assertNotIn(rid, {r.id for r in desk().state.rules})


class PageTests(unittest.TestCase):
    def test_create_rename_duplicate_delete(self) -> None:
        main = desk().displayed_page(key())
        count = len(desk().state.pages)
        page = desk().new_page(key(), "新的预设")
        self.assertIsNotNone(page)
        self.assertEqual(desk().displayed_page(key()).id, page.id)
        self.assertTrue(desk().rename_page(page.id, "  改名预设  "))
        self.assertEqual(page.title, "改名预设")
        self.assertFalse(desk().rename_page(page.id, "   "))
        copy = desk().new_page(key(), duplicate_of=main.id)
        self.assertEqual(len(copy.islands), len(main.islands))
        self.assertFalse({s.id for s in copy.islands} & {s.id for s in main.islands})
        self.assertTrue(valid())
        self.assertTrue(desk().switch_page(key(), main.id))
        for pid in (page.id, copy.id):
            self.assertTrue(desk().delete_page(pid))
        self.assertEqual(len(desk().state.pages), count)
        self.assertEqual(desk().displayed_page(key()).id, main.id)

    def test_last_preset_cannot_be_deleted(self) -> None:
        main = desk().displayed_page(key())
        others = [p for p in desk().state.pages if p.monitor_key == main.monitor_key and p.id != main.id]
        removed = []
        for page in others:
            removed.append(page.title)
            self.assertTrue(desk().delete_page(page.id))
        self.assertFalse(desk().delete_page(main.id))
        self.assertIsNotNone(desk().state.page(main.id))
        for title in removed:  # put the other presets back (empty) for the remaining tests
            desk().new_page(key(), title)
        self.assertTrue(desk().switch_page(key(), main.id))

    def test_cycle_pages(self) -> None:
        main = desk().displayed_page(key())
        desk().cyclePage(key(), 1)
        support.spin(30)
        desk().cyclePage(key(), -1)
        support.spin(30)
        self.assertEqual(desk().displayed_page(key()).id, main.id)


class V201AppTests(unittest.TestCase):
    """2.0.1: popups in their own windows, snapshot deletion, todo reminders, drag pixmaps, memory."""

    def test_popups_live_in_their_own_windows(self) -> None:
        app = APP.app
        nid = desk().show_notice("测试通知", "置顶窗口")
        support.spin(200)
        notice = app.popups.get("notice")
        self.assertIsNotNone(notice)
        self.assertTrue(notice.isVisible())
        desk().dismissNotice(nid)
        cid = desk().confirm("测试确认", "", "好", lambda: None, danger=False)
        support.spin(200)
        confirm = app.popups.get("confirm")
        self.assertIsNotNone(confirm)
        self.assertTrue(confirm.isVisible())
        desk().resolveConfirm(cid, False)
        self.assertTrue(support.spin(2000, lambda: not confirm.isVisible()), "hides after fading out")

    def test_snapshot_delete_asks_first(self) -> None:
        path = APP.store.save_snapshot(desk().state, "待删快照")
        self.assertIn(str(path), [s["path"] for s in desk().snapshots()])
        desk().run_action("snapshot.delete:" + str(path))
        pending = desk().pending_confirm()
        self.assertEqual(pending.get("title"), "删除布局快照？")
        self.assertTrue(path.exists(), "nothing happens before the user answers")
        desk().resolveConfirm(pending["id"], True)
        support.spin(50)
        self.assertFalse(path.exists())
        self.assertNotIn(str(path), [s["path"] for s in desk().snapshots()])
        outside = APP.root / "not-a-snapshot.json"
        outside.write_text("{}", encoding="utf-8")
        self.assertFalse(desk().delete_snapshot(str(outside)))
        self.assertTrue(outside.exists())

    def test_todo_reminder_and_notice_actions(self) -> None:
        import datetime as dt
        from unittest import mock

        from deskisle.services import todo

        service = desk().services["todo"]
        state = desk().add_island("widget", monitor_key=key(), widget="todo", size=(300, 260))
        self.assertIsNotNone(state)
        uid = state.id
        try:
            support.spin(100)
            soon = (dt.datetime.now() + dt.timedelta(minutes=3)).replace(second=0, microsecond=0)
            item_id = service.add(uid, "测试提醒")
            service.setDue(uid, item_id, soon.isoformat(timespec="minutes"))
            self.assertIn(soon.date().isoformat(), service.due_map())
            self.assertEqual([i["text"] for i in service.itemsOn(soon.date().isoformat())
                              if i["uid"] == uid], ["测试提醒"])
            before = len(desk().notices)
            with mock.patch.object(todo, "_now", return_value=soon + dt.timedelta(seconds=20)):
                service.check_reminders()
            support.spin(100)
            self.assertEqual(len(desk().notices), min(4, before + 1))
            notice = desk().notices.at(len(desk().notices) - 1)
            self.assertIn("测试提醒", notice.text)
            done = [a for a in notice.actions if str(a.get("id", "")).startswith("todo.done:")]
            self.assertTrue(done)
            desk().noticeAction(notice.nid, done[0]["id"])
            support.spin(50)
            self.assertTrue(next(i for i in service.list(uid) if i["id"] == item_id)["done"])
        finally:
            desk().delete_island(uid)
            support.spin(50)

    def test_drag_pixmap_and_memory_slots(self) -> None:
        pixmap = desk()._drag_pixmap([str(APP.root)], 48)
        self.assertIsNotNone(pixmap)
        self.assertFalse(pixmap.isNull())
        self.assertIsInstance(APP.app.memoryText(), str)
        APP.app.trimMemoryNow()                 # no-op off Windows, must not raise
        APP.app.schedule_trim(10)
        support.spin(100)


class ViewStateTests(unittest.TestCase):
    def test_hide_and_focus(self) -> None:
        self.assertFalse(desk().hidden)
        desk().toggleHidden()
        support.spin(30)
        self.assertTrue(desk().hidden)
        desk().toggleHidden()
        self.assertFalse(desk().hidden)
        desk().toggleHidden()
        desk().toggleFocus()
        support.spin(30)
        self.assertTrue(desk().focusMode)
        self.assertFalse(desk().hidden, "focus mode brings the islands back")
        desk().toggleFocus()
        self.assertFalse(desk().focusMode)

    def test_panels_are_non_modal(self) -> None:
        desk().togglePanel("new", key())
        support.spin(40)
        self.assertEqual(desk().panel, "new")
        # The desk stays usable while the "+" panel is open.
        state = desk().add_island("widget", monitor_key=key(), widget="clock")
        if state is not None:
            desk().delete_island(state.id)
        self.assertEqual(desk().panel, "new")
        desk().togglePanel("new", key())
        self.assertEqual(desk().panel, "")
        desk().openPanel("presets", key(), "")
        self.assertEqual(desk().panel, "presets")
        desk().closePanel()
        self.assertEqual(desk().panel, "")


class DesktopScanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="deskisle-desktop-"))
        self.saved_dirs = desk()._desktop_dirs  # noqa: SLF001 - test hook
        desk()._desktop_dirs = [self.folder]  # noqa: SLF001
        self.saved_auto = desk().state.preferences.auto_organize
        desk().state.preferences.auto_organize = True

    def tearDown(self) -> None:
        desk()._desktop_dirs = self.saved_dirs  # noqa: SLF001
        desk().state.preferences.auto_organize = self.saved_auto
        prefix = os.path.normcase(str(self.folder))
        desk().state.loose_items[:] = [i for i in desk().state.loose_items
                                       if not os.path.normcase(i.path).startswith(prefix)]
        shutil.rmtree(self.folder, ignore_errors=True)

    def loose(self) -> set:
        return {os.path.normcase(i.path) for i in desk().state.loose_items}

    def test_moving_real_files_into_a_folder_view_asks_first(self) -> None:
        target = self.folder / "目标"
        target.mkdir()
        doc = self.folder / "报告.txt"
        doc.write_text("x", encoding="utf-8")
        desk().move_into_folder([str(doc)], str(target), "loose")
        info = desk().pending_confirm()
        self.assertTrue(info.get("id"), "a confirmation card is shown")
        self.assertIn("目标", info["title"])
        self.assertTrue(doc.exists(), "nothing moves before the user agrees")
        desk().resolveConfirm(info["id"], False)
        self.assertTrue(doc.exists(), "declined: the file stays")
        desk().move_into_folder([str(doc)], str(target), "loose")
        desk().resolveConfirm(desk().pending_confirm()["id"], True)
        self.assertFalse(doc.exists())
        self.assertTrue((target / "报告.txt").exists())

    def test_a_folder_view_follows_its_folder(self) -> None:
        shown = self.folder / "视窗"
        shown.mkdir()
        (shown / "一.txt").write_text("1", encoding="utf-8")
        state = desk().add_island("files", monitor_key=key(), folder=str(shown), title="视窗", size=(300, 200))
        self.assertIsNotNone(state, "no room for a test island")
        try:
            proxy = desk().proxy(state.id)
            support.spin(50)
            self.assertEqual(proxy.items.rowCount(), 1)
            self.assertFalse(proxy.portalMissing)
            (shown / "二.txt").write_text("2", encoding="utf-8")
            self.assertTrue(support.spin(4000, lambda: proxy.items.rowCount() == 2),
                            "a new file shows up without any user action")
            shutil.rmtree(shown)
            desk().refresh_portals()
            self.assertTrue(proxy.portalMissing, "a vanished folder is reported, not shown as empty")
            self.assertEqual(proxy.items.rowCount(), 0)
            shown.mkdir()
            (shown / "三.txt").write_text("3", encoding="utf-8")
            desk().refresh_portals()
            self.assertFalse(proxy.portalMissing, "the view recovers when the folder is back")
            self.assertEqual(proxy.items.rowCount(), 1)
        finally:
            desk().delete_island(state.id)
            support.spin(50)

    def test_new_and_deleted_items(self) -> None:
        a = self.folder / "笔记.txt"
        a.write_text("x", encoding="utf-8")
        (self.folder / "desktop.ini").write_text("", encoding="utf-8")
        (self.folder / ".hidden").write_text("", encoding="utf-8")
        self.assertEqual(desk().import_new_desktop_items(initial=True), 1)
        self.assertIn(os.path.normcase(str(a)), self.loose())
        self.assertEqual(desk().import_new_desktop_items(initial=True), 0, "known items are not imported twice")
        a.unlink()
        desk().import_new_desktop_items(initial=True)
        self.assertNotIn(os.path.normcase(str(a)), self.loose())

    def test_rules_file_into_an_island_on_another_preset(self) -> None:
        main = desk().displayed_page(key())
        other = desk().new_page(key(), "归档预设")
        try:
            target = files_island("PDF 归档")
            self.assertTrue(desk().switch_page(key(), main.id))
            rid = desk().saveRule({"name": "pdf", "condition": "extension", "value": "pdf", "target": target.id})
            pdf = self.folder / "合同.pdf"
            pdf.write_text("x", encoding="utf-8")
            self.assertEqual(desk().import_new_desktop_items(), 1)
            paths = [os.path.normcase(i.path) for i in target.tabs[0].items]
            self.assertIn(os.path.normcase(str(pdf)), paths)
            self.assertNotIn(os.path.normcase(str(pdf)), self.loose())
            pdf.unlink()
            desk().import_new_desktop_items(initial=True)
            self.assertFalse(target.tabs[0].items, "deleted files leave islands on every preset")
            desk().deleteRule(rid)
        finally:
            if desk().displayed_page(key()).id != main.id:
                desk().switch_page(key(), main.id)
            desk().delete_page(other.id)


class WindowTests(unittest.TestCase):
    def test_settings_is_single_instance(self) -> None:
        app = APP.app
        app.open_settings("appearance")
        support.spin(300)
        first = app.settings_window
        self.assertIsNotNone(first)
        app.open_settings("rules")
        support.spin(100)
        self.assertIs(app.settings_window, first)
        self.assertEqual(first.property("page"), "rules")
        for page in ("widgets", "agent", "about"):
            first.setProperty("page", page)
            support.spin(120)
        first.close()
        support.spin(100)
        self.assertIsNone(app.settings_window)
        app.open_settings("")
        support.spin(200)
        self.assertIsNotNone(app.settings_window)
        app.settings_window.close()
        support.spin(100)

    def test_menus_build_for_every_context(self) -> None:
        from PySide6.QtCore import QPoint

        page = desk().displayed_page(key())
        island = next(s for s in page.islands if s.kind == "files")
        container = desk().container_of(island.id)
        path = island.tabs[0].items[0].path if island.tabs[0].items else str(APP.root)
        contexts = [("desktop", key(), {}), ("tray", "", {}), ("preset", page.id, {}), ("new", "", {}),
                    ("item", container, {"paths": [path]}), ("item", "loose", {"paths": [path], "available": False})]
        contexts += [("island", s.id, {}) for s in page.islands]
        for context, target, extra in contexts:
            entries = desk().menu(context, target, extra)
            self.assertTrue(entries, (context, target))
            for entry in entries:
                self.assertIsInstance(entry, dict)
                if entry.get("separator"):
                    continue
                self.assertTrue(entry.get("id") and entry.get("text"), entry)
        APP.app.show_menu("tray", QPoint(40, 40))
        support.spin(150)
        self.assertIsNotNone(APP.app.menu_window)
        desk().dismissMenus()
        support.spin(50)

    def test_save_and_reload(self) -> None:
        desk().save_now()
        loaded = APP.store.load()
        self.assertEqual(len(loaded.pages), len(desk().state.pages))
        ids = {s.id for p in desk().state.pages for s in p.islands}
        self.assertEqual({s.id for p in loaded.pages for s in p.islands}, ids)
        self.assertEqual(loaded.preferences.theme_mode, desk().state.preferences.theme_mode)


class ZWarningsTest(unittest.TestCase):
    """Runs last (classes load alphabetically): nothing above produced a QML error."""

    def test_no_fatal_qml_warnings(self) -> None:
        support.spin(200)
        self.assertEqual(support.fatal(APP.warnings), [])


if __name__ == "__main__":
    unittest.main()

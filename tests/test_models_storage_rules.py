from __future__ import annotations

import json
import shutil
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID, uuid4

from deskisle.models import (
    AppState,
    IslandState,
    ItemRef,
    PageState,
    Preferences,
    Rule,
    TabState,
)
from deskisle.rules import RuleEngine
from deskisle.storage import StateStore


@contextmanager
def _test_workspace():
    """Create a Windows-sandbox-friendly temporary test directory."""

    base = Path(__file__).resolve().parent / ".test-work"
    work = base / uuid4().hex
    work.mkdir(parents=True)
    try:
        yield work
    finally:
        shutil.rmtree(work, ignore_errors=False)
        try:
            base.rmdir()
        except OSError:
            # Another concurrent test may still own a sibling workspace.
            pass


class ModelTests(unittest.TestCase):
    def test_json_roundtrip_and_uuid_defaults(self) -> None:
        regular = TabState(
            title="常用",
            items=[ItemRef(path=r"C:\Desktop\notes.txt", title="笔记", pinned=True)],
            sort_mode="name",
        )
        portal = TabState(title="下载", portal_path=r"C:\Users\me\Downloads")
        island = IslandState(
            title="工作",
            x=20,
            y=30,
            width=500,
            height=320,
            color="#336699",
            collapsed=True,
            locked=True,
            icon_size=56,
            active_tab_id=portal.id,
            tabs=[regular, portal],
            exclude_from_hide=True,
        )
        page = PageState(title="项目", islands=[island])
        state = AppState(
            current_page_id=page.id,
            pages=[page],
            loose_items=[ItemRef(path=r"C:\Desktop\loose.url")],
            rules=[
                Rule(
                    name="文档",
                    condition="kind",
                    value="document",
                    target_island_id=island.id,
                    priority=10,
                )
            ],
            preferences=Preferences(
                hide_native_icons=False,
                snap_to_grid=True,
                grid_size=12,
                auto_organize=True,
                start_with_windows=True,
                panel_opacity=0.75,
            ),
        )

        serialized = json.loads(json.dumps(state.to_dict(), ensure_ascii=False))
        restored = AppState.from_dict(serialized)

        self.assertEqual(restored.to_dict(), state.to_dict())
        for value in (regular.id, portal.id, island.id, page.id, state.rules[0].id):
            self.assertEqual(str(UUID(value)), value)

    def test_from_dict_tolerates_missing_and_bad_values(self) -> None:
        state = AppState.from_dict(
            {
                "version": "bad",
                "pages": [
                    {
                        "title": "恢复页",
                        "islands": [
                            {
                                "title": "恢复岛",
                                "width": "420",
                                "tabs": [{"title": "全部", "items": [None, "a.txt"]}],
                            }
                        ],
                    },
                    None,
                ],
                "loose_items": ["loose.txt", None],
                "preferences": {"panel_opacity": 99, "grid_size": 0},
            }
        )

        self.assertEqual(state.version, 1)
        self.assertEqual(state.current_page_id, state.pages[0].id)
        self.assertEqual(state.pages[0].islands[0].width, 420)
        self.assertEqual(state.pages[0].islands[0].active_tab_id, state.pages[0].islands[0].tabs[0].id)
        self.assertEqual(state.pages[0].islands[0].tabs[0].items[0].path, "a.txt")
        self.assertEqual(state.loose_items[0].path, "loose.txt")
        self.assertEqual(state.preferences.panel_opacity, 1.0)
        self.assertEqual(state.preferences.grid_size, 1)


class StorageTests(unittest.TestCase):
    def test_default_layout_smartly_groups_references_without_moving_files(self) -> None:
        with _test_workspace() as temp_dir:
            shortcut = temp_dir / "Tool.lnk"
            document = temp_dir / "Report.docx"
            image = temp_dir / "Photo.png"
            archive = temp_dir / "Bundle.zip"
            folder = temp_dir / "Project"
            for path in (shortcut, document, image, archive):
                path.write_bytes(b"unchanged")
            folder.mkdir()

            state = StateStore(temp_dir / "data").create_default_state(
                [shortcut, document, image, archive, folder]
            )

            grouped = {
                island.title: {item.path for tab in island.tabs for item in tab.items}
                for island in state.pages[0].islands
            }
            self.assertIn(str(shortcut), grouped["常用应用"])
            self.assertIn(str(document), grouped["文档"])
            self.assertIn(str(image), grouped["图片与媒体"])
            self.assertIn(str(archive), grouped["文件夹与归档"])
            self.assertIn(str(folder), grouped["文件夹与归档"])
            self.assertEqual(shortcut.read_bytes(), b"unchanged")
            self.assertTrue(folder.is_dir())

    def test_corrupt_primary_recovers_from_backup_and_repairs_it(self) -> None:
        with _test_workspace() as temp_dir:
            store = StateStore(temp_dir)
            state = store.create_default_state([r"C:\Desktop\alpha.txt"])
            state.pages[0].title = "可恢复"
            store.save(state)

            self.assertTrue(store.backup_path.exists())
            store.state_path.write_text("{ definitely broken", encoding="utf-8")

            recovered = store.load()

            self.assertEqual(recovered.pages[0].title, "可恢复")
            repaired_payload = json.loads(store.state_path.read_text(encoding="utf-8"))
            self.assertEqual(repaired_payload["pages"][0]["title"], "可恢复")

    def test_snapshot_restore_export_and_import(self) -> None:
        with _test_workspace() as temp_dir:
            store = StateStore(Path(temp_dir) / "main")
            state = store.create_default_state([r"C:\Desktop\one.txt"])
            state.pages[0].title = "快照版本"
            store.save(state)
            snapshot = store.save_snapshot(state, "发布前")

            state.pages[0].title = "修改后"
            store.save(state)
            self.assertEqual(store.list_snapshots(), [snapshot])

            restored = store.restore_snapshot(snapshot)
            self.assertEqual(restored.pages[0].title, "快照版本")
            self.assertEqual(store.load().pages[0].title, "快照版本")

            export_path = Path(temp_dir) / "exports" / "layout.json"
            self.assertEqual(store.export(restored, export_path), export_path)
            imported_store = StateStore(Path(temp_dir) / "imported")
            imported = imported_store.import_state(export_path)
            self.assertEqual(imported.to_dict(), restored.to_dict())
            self.assertEqual(imported_store.load().to_dict(), restored.to_dict())


class RuleEngineTests(unittest.TestCase):
    def test_matching_priority_and_kinds(self) -> None:
        with _test_workspace() as temp_dir:
            folder = Path(temp_dir) / "Folder"
            folder.mkdir()
            generic = Rule(
                name="所有图片",
                condition="kind",
                value="image",
                target_island_id="images",
                priority=100,
            )
            specific = Rule(
                name="旅行图片",
                condition="name_contains",
                value="Holiday",
                target_island_id="travel",
                priority=10,
            )
            disabled = Rule(
                name="禁用",
                condition="extension",
                value=".jpg",
                target_island_id="disabled",
                enabled=False,
                priority=1,
            )
            engine = RuleEngine([generic, disabled, specific])

            self.assertEqual(engine.choose_target("Holiday.JPG"), "travel")
            self.assertEqual(engine.choose_target("portrait.png"), "images")
            self.assertTrue(engine.match(Rule(condition="extension", value="pdf", target_island_id="x"), "BOOK.PDF"))
            self.assertTrue(engine.match(Rule(condition="name_starts", value="book", target_island_id="x"), "BOOK.PDF"))
            self.assertTrue(engine.match(Rule(condition="name_ends", value=".pdf", target_island_id="x"), "BOOK.PDF"))
            self.assertTrue(engine.match(Rule(condition="kind", value="folder", target_island_id="x"), folder))
            self.assertTrue(engine.match(Rule(condition="kind", value="shortcut", target_island_id="x"), "site.URL"))
            self.assertTrue(engine.match(Rule(condition="kind", value="document", target_island_id="x"), "notes.docx"))
            self.assertTrue(engine.match(Rule(condition="kind", value="media", target_island_id="x"), "clip.MP4"))
            self.assertTrue(engine.match(Rule(condition="kind", value="archive", target_island_id="x"), "files.7z"))

    def test_apply_path_records_reference_only_and_skips_known_paths(self) -> None:
        with _test_workspace() as temp_dir:
            source = Path(temp_dir) / "Holiday.jpg"
            source.write_bytes(b"not moved")
            loose = Path(temp_dir) / "keep-loose.txt"
            loose.write_text("loose", encoding="utf-8")

            portal = TabState(title="门户", portal_path=str(temp_dir))
            island = IslandState(title="图片", active_tab_id=portal.id, tabs=[portal])
            page = PageState(title="主页", islands=[island])
            rule = Rule(
                name="图片",
                condition="kind",
                value="image",
                target_island_id=island.id,
                priority=5,
            )
            state = AppState(
                pages=[page],
                rules=[rule],
                loose_items=[ItemRef(path=str(loose))],
            )
            engine = RuleEngine()

            target = engine.apply_path(source, state)

            self.assertEqual(target, island.id)
            self.assertTrue(source.exists())
            self.assertEqual(source.read_bytes(), b"not moved")
            ordinary_tabs = [tab for tab in island.tabs if tab.portal_path is None]
            self.assertEqual(len(ordinary_tabs), 1)
            self.assertEqual(ordinary_tabs[0].items[0].path, str(source))
            self.assertIsNone(engine.apply_path(source, state))
            self.assertIsNone(engine.apply_path(loose, state))
            self.assertEqual(engine.preview([source, loose], state=state), {})


if __name__ == "__main__":
    unittest.main()

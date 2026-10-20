"""Regression tests for the 1.2 features (materials, media, HTML/web islands, updates)."""

from __future__ import annotations

import os
import shutil
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Never start Chromium in unit tests: HTML / web islands show their placeholder.
os.environ.setdefault("DESKISLE_DISABLE_WEBENGINE", "1")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

import deskisle  # noqa: E402
import deskisle.board as board_module  # noqa: E402
from deskisle.board import DesktopWindow  # noqa: E402
from deskisle.dialogs import (  # noqa: E402
    FPS_CHOICES,
    IslandAppearanceDialog,
    NewIslandDialog,
    SettingsDialog,
)
from deskisle.html_view import normalize_url  # noqa: E402
from deskisle.island import MAX_ICON_SIZE, IslandWidget  # noqa: E402
from deskisle.models import AppState, IslandState, PageState, Preferences, TabState  # noqa: E402
from deskisle.motion import COLLAPSE_MS, ZOOM_MS  # noqa: E402
from deskisle.storage import StateStore  # noqa: E402
from deskisle.updater import (  # noqa: E402
    RELEASES_PAGE,
    ReleaseInfo,
    UpdateManager,
    is_newer,
    parse_release,
    parse_sha256_file,
)

DOWNLOAD = "https://github.com/narabias/DeskIsle/releases/download/v1.2.0/"
DIGEST = "A1" * 32


def _release_payload() -> dict:
    return {
        "tag_name": "v1.2.0",
        "name": "桌屿 1.2.0",
        "body": "更新说明",
        "html_url": "https://github.com/narabias/DeskIsle/releases/tag/v1.2.0",
        "published_at": "2025-01-02T03:04:05Z",
        "assets": [
            {"name": "DeskIsle-Portable.zip", "browser_download_url": DOWNLOAD + "DeskIsle-Portable.zip", "size": 1},
            {
                "name": "DeskIsle-Setup-1.2.0-x64.exe",
                "browser_download_url": DOWNLOAD + "DeskIsle-Setup-1.2.0-x64.exe",
                "size": 50 * 1024 * 1024,
                "digest": "sha256:" + DIGEST,
            },
            {
                "name": "DeskIsle-Setup-1.2.0-x64.exe.sha256",
                "browser_download_url": DOWNLOAD + "DeskIsle-Setup-1.2.0-x64.exe.sha256",
                "size": 96,
            },
        ],
    }


class _Workspace(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".test-work" / uuid4().hex
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def html_file(self) -> Path:
        path = self.root / "动画.html"
        path.write_text("<html><body style='background:transparent'>hi</body></html>", encoding="utf-8")
        return path


class ModelTests(unittest.TestCase):
    def test_new_island_fields_roundtrip_and_keep_unknown_keys(self) -> None:
        island = IslandState(
            title="动画",
            kind="html",
            html_path=r"C:\anim\index.html",
            html_allow_network=True,
            material="liquid",
            media_path=r"C:\media\loop.mp4",
            media_opacity=0.5,
            media_feather=40,
            pin_on_top=True,
            web_zoom=1.25,
            web_refresh_minutes=15,
        )
        data = island.to_dict()
        data["future_field"] = {"keep": True}
        restored = IslandState.from_dict(data)
        for name in ("kind", "html_path", "html_allow_network", "material", "media_path", "media_opacity",
                     "media_feather", "pin_on_top", "web_zoom", "web_refresh_minutes"):
            self.assertEqual(getattr(restored, name), getattr(island, name), name)
        self.assertTrue(restored.is_web_content)
        self.assertEqual(restored.to_dict()["future_field"], {"keep": True})

    def test_invalid_and_old_island_values_are_sanitized(self) -> None:
        bad = IslandState.from_dict({
            "kind": "evil", "material": "Metal", "media_opacity": 9, "media_feather": -5,
            "web_zoom": 99, "web_refresh_minutes": 99999,
        })
        self.assertEqual(bad.kind, "files")
        self.assertEqual(bad.material, "")
        self.assertEqual(bad.media_opacity, 1.0)
        self.assertEqual(bad.media_feather, 0)
        self.assertEqual(bad.web_zoom, 5.0)
        self.assertEqual(bad.web_refresh_minutes, 1440)
        old = IslandState.from_dict({"title": "旧版收纳岛", "width": 300})
        self.assertEqual((old.kind, old.material, old.media_path), ("files", "", ""))
        self.assertFalse(old.is_web_content)
        self.assertEqual(IslandState.from_dict({"material": " LIQUID "}).material, "liquid")

    def test_preferences_roundtrip_defaults_and_clamping(self) -> None:
        prefs = Preferences(
            island_material="liquid", backdrop_source="image", backdrop_image=r"C:\bg.png",
            font_family="思源黑体", font_file=r"C:\fonts\a.ttf", font_size=12.5, reduce_motion=True,
            smart_pause=False, media_fps=30, auto_check_updates=False,
        )
        data = prefs.to_dict()
        data["future_pref"] = 3
        restored = Preferences.from_dict(data)
        for name in ("island_material", "backdrop_source", "backdrop_image", "font_family", "font_file",
                     "font_size", "reduce_motion", "smart_pause", "media_fps", "auto_check_updates"):
            self.assertEqual(getattr(restored, name), getattr(prefs, name), name)
        self.assertEqual(restored.to_dict()["future_pref"], 3)

        defaults = Preferences.from_dict({"panel_opacity": 0.8})
        self.assertEqual(defaults.island_material, "frosted")
        self.assertEqual(defaults.backdrop_source, "wallpaper")
        self.assertEqual(defaults.font_family, "")
        self.assertEqual(defaults.font_size, 10.0)
        self.assertTrue(defaults.smart_pause)
        self.assertEqual(defaults.media_fps, 24)
        self.assertTrue(defaults.auto_check_updates)

        clamped = Preferences.from_dict({"font_size": 99, "media_fps": 1000, "island_material": "x",
                                         "backdrop_source": "video"})
        self.assertEqual(clamped.font_size, 20.0)
        self.assertEqual(clamped.media_fps, 60)
        self.assertEqual(clamped.island_material, "frosted")
        self.assertEqual(clamped.backdrop_source, "wallpaper")


class UpdaterTests(_Workspace):
    def test_parse_release_finds_installer_digest_and_checksum(self) -> None:
        release = parse_release(_release_payload())
        self.assertEqual(release.version, "1.2.0")
        self.assertEqual(release.tag, "v1.2.0")
        self.assertTrue(release.has_installer)
        self.assertEqual(release.asset_name, "DeskIsle-Setup-1.2.0-x64.exe")
        self.assertEqual(release.sha256, DIGEST.lower())
        self.assertTrue(release.sha256_url.endswith(".exe.sha256"))
        self.assertEqual(release.size_text, "50.0 MB")
        self.assertEqual(release.published_text, "2025-01-02 03:04")

    def test_parse_release_rejects_untrusted_hosts(self) -> None:
        payload = _release_payload()
        payload["html_url"] = "https://evil.example/release"
        payload["assets"] = [{"name": "DeskIsle-Setup-1.2.0-x64.exe",
                              "browser_download_url": "https://evil.example/DeskIsle-Setup-1.2.0-x64.exe"}]
        release = parse_release(payload)
        self.assertFalse(release.has_installer)
        self.assertEqual(release.page_url, RELEASES_PAGE)
        payload["assets"] = [{"name": "DeskIsle-Setup-1.2.0-x64.exe",
                              "browser_download_url": "http://github.com/x/DeskIsle-Setup-1.2.0-x64.exe"}]
        self.assertFalse(parse_release(payload).has_installer)
        with self.assertRaises(ValueError):
            parse_release({"name": "缺少版本号"})

    def test_parse_release_ignores_installer_of_another_version(self) -> None:
        payload = _release_payload()
        payload["tag_name"] = "v1.2.1"
        self.assertFalse(parse_release(payload).has_installer)
        payload["tag_name"] = "1.2"  # same version written differently
        self.assertTrue(parse_release(payload).has_installer)

    def test_version_comparison_and_checksum_files(self) -> None:
        self.assertTrue(is_newer("v1.2.0", "1.1.3"))
        self.assertTrue(is_newer("1.10.0", "1.9.9"))
        self.assertTrue(is_newer("1.2.0", "1.2.0-beta.1"))
        self.assertFalse(is_newer("1.2.0-beta.1", "1.2.0"))
        self.assertFalse(is_newer("1.1.3", "v1.1.3"))
        self.assertFalse(is_newer("", "1.0.0"))
        line = DIGEST + " *DeskIsle-Setup-1.2.0-x64.exe\r\n"
        self.assertEqual(parse_sha256_file(line), DIGEST.lower())
        self.assertEqual(parse_sha256_file("not a checksum"), "")

    def test_download_requires_trusted_host_and_checksum(self) -> None:
        manager = UpdateManager(None, None, "1.1.3")
        failures: list[str] = []
        manager.download_failed.connect(failures.append)
        name = "DeskIsle-Setup-1.2.0-x64.exe"
        manager.download(ReleaseInfo(version="1.2.0", tag="v1.2.0", asset_name=name, asset_url=DOWNLOAD + name))
        self.assertIn("SHA-256", failures[-1])
        manager.download(ReleaseInfo(version="1.2.0", tag="v1.2.0", asset_name=name,
                                     asset_url="https://evil.example/" + name, sha256=DIGEST.lower()))
        self.assertIn("不受信任", failures[-1])
        manager.download(ReleaseInfo(version="1.2.0", tag="v1.2.0"))
        self.assertIn("没有提供", failures[-1])
        self.assertFalse(manager.is_downloading)

    def test_error_message_reads_rate_limit_header_without_wrong_argument_types(self) -> None:
        """rawHeader takes the header name as str; passing bytes used to crash.

        The crash surfaced as a global exception dialog while the app was
        merely being dragged, because the update check runs in the background.
        """
        manager = UpdateManager(None, None, "1.1.3")
        from PySide6.QtCore import QByteArray

        class _FakeReply:
            def __init__(self, status: int, headers: dict[str, bytes]) -> None:
                self._status = status
                self._headers = headers

            def attribute(self, _which):
                return self._status

            def rawHeader(self, name):
                # Mirror the strict binding: only str is accepted.
                if not isinstance(name, str):
                    raise TypeError(
                        "QNetworkReply.rawHeader called with wrong argument types"
                    )
                return QByteArray(self._headers.get(name, b""))

            def error(self):
                return 0  # NoError; the 403/429 branches never read it.

            def errorString(self) -> str:
                return ""

        # 429 must be reported as rate limiting, not as a crash.
        reply = _FakeReply(429, {"X-RateLimit-Remaining": b"0"})
        self.assertIn("次数", manager._error_message(reply))

        # 403 with a non-zero remaining count is a plain rejection.
        reply = _FakeReply(403, {"X-RateLimit-Remaining": b"42"})
        self.assertIn("403", manager._error_message(reply))

        # Missing header must not raise either.
        reply = _FakeReply(403, {})
        self.assertIn("403", manager._error_message(reply))

    def test_version_file_matches_package_version(self) -> None:
        version_file = Path(__file__).resolve().parents[1] / "VERSION"
        self.assertEqual(version_file.read_text(encoding="utf-8").strip(), deskisle.__version__)

    def test_update_state_is_separate_from_user_layout(self) -> None:
        store = StateStore(self.root / "data")
        page = PageState(title="主页", islands=[IslandState(title="工作")])
        store.save(AppState(pages=[page], current_page_id=page.id))
        layout_before = store.state_path.read_bytes()

        release = parse_release(_release_payload())
        manager = UpdateManager(store.root, None, "1.1.3")
        self.assertTrue(manager.should_notify(release))
        manager.mark_notified(release)
        self.assertFalse(manager.should_notify(release))

        newer = ReleaseInfo(version="1.2.1", tag="v1.2.1")
        self.assertTrue(manager.should_notify(newer))
        manager.skip_version("v1.2.1")
        self.assertFalse(manager.should_notify(newer))

        reloaded = UpdateManager(store.root, None, "1.1.3")
        self.assertEqual(reloaded.skipped_version, "1.2.1")
        self.assertTrue((store.root / "update.json").is_file())
        self.assertEqual(store.state_path.read_bytes(), layout_before)
        self.assertFalse(UpdateManager(None, None, "1.2.0").should_notify(release))

        reloaded.state["last_check"] = time.time()
        self.assertFalse(reloaded.auto_check_due())
        reloaded.state["last_check"] = time.time() - 21 * 3600
        self.assertTrue(reloaded.auto_check_due())
        reloaded.state["last_check"] = time.time() + 7 * 24 * 3600  # clock moved backwards
        self.assertTrue(reloaded.auto_check_due())


class StorageTests(_Workspace):
    def test_import_media_copies_once_and_prune_keeps_referenced_files(self) -> None:
        store = StateStore(self.root / "data")
        image = self.root / "背景 图.png"
        image.write_bytes(b"image-bytes")
        other = self.root / "unused.mp4"
        other.write_bytes(b"video-bytes")

        managed = store.import_media(image)
        self.assertEqual(Path(managed).resolve().parent, store.media_dir.resolve())
        self.assertEqual(Path(managed).read_bytes(), b"image-bytes")
        self.assertTrue(image.is_file(), "the original file must never be moved")
        self.assertEqual(store.import_media(image), managed)
        self.assertEqual(Path(store.import_media(managed)).resolve(), Path(managed).resolve())
        missing = str(self.root / "missing.webm")
        self.assertEqual(store.import_media(missing), missing)

        orphan = store.import_media(other)
        page = PageState(islands=[IslandState(media_path=managed)])
        state = AppState(pages=[page], current_page_id=page.id)
        store.save(state)
        self.assertEqual(store.prune_media(state), 1)
        self.assertTrue(Path(managed).is_file())
        self.assertFalse(Path(orphan).exists())
        self.assertTrue(other.is_file())

    def test_import_font_keeps_a_readable_name(self) -> None:
        store = StateStore(self.root / "data")
        font = self.root / "My Font.ttf"
        font.write_bytes(b"\x00\x01\x00\x00fake")
        managed = Path(store.import_font(font))
        self.assertEqual(managed.resolve().parent, store.fonts_dir.resolve())
        self.assertTrue(managed.name.startswith("My-Font-"))
        self.assertEqual(managed.suffix, ".ttf")


class IslandWidgetTests(_Workspace):
    def test_count_badge_keeps_pill_height_when_collapsed(self) -> None:
        state = IslandState(title="一个很长很长的收纳岛名称用来测试省略显示", width=360, height=300, tabs=[TabState()])
        widget = IslandWidget(state, desktop_window=True)
        widget.show()
        self.app.processEvents()
        header = widget.header
        badge = header.badge_rect()
        self.assertEqual(badge.height(), 20.0)
        self.assertLessEqual(badge.right(), header.collapse_button.x())

        widget.toggle_collapsed()
        QTest.qWait(COLLAPSE_MS + 160)
        self.assertTrue(state.collapsed)
        self.assertEqual(widget.height(), 44)
        badge = header.badge_rect()
        self.assertEqual(badge.height(), 20.0)
        self.assertGreaterEqual(badge.top(), 0)
        self.assertLessEqual(badge.bottom(), header.height())
        self.assertLessEqual(badge.right(), header.collapse_button.x())
        header.set_badge("128")
        wide = header.badge_rect()
        self.assertEqual(wide.height(), 20.0)
        self.assertGreater(wide.width(), 20.0)
        widget.toggle_collapsed()
        QTest.qWait(COLLAPSE_MS + 160)
        self.assertFalse(state.collapsed)
        self.assertEqual(widget.height(), 300)
        widget.close()

    def test_icon_zoom_animates_to_target_and_is_clamped(self) -> None:
        state = IslandState(icon_size=48, tabs=[TabState()])
        widget = IslandWidget(state, desktop_window=True)
        widget.show()
        self.app.processEvents()
        widget.zoom_icons(1)
        self.assertEqual(state.icon_size, 56)
        self.assertTrue(widget.item_list.is_zooming())
        QTest.qWait(ZOOM_MS + 160)
        self.assertFalse(widget.item_list.is_zooming())
        self.assertEqual(widget.item_list.iconSize().width(), 56)

        widget.zoom_icons(-1)
        QTest.qWait(ZOOM_MS // 3)
        widget.zoom_icons(-1)  # re-target while the first zoom is still running
        QTest.qWait(ZOOM_MS + 160)
        self.assertEqual(state.icon_size, 40)
        self.assertEqual(widget.item_list.iconSize().width(), 40)

        for _ in range(20):
            widget.zoom_icons(1)
        QTest.qWait(ZOOM_MS + 160)
        self.assertEqual(state.icon_size, MAX_ICON_SIZE)
        self.assertEqual(widget.item_list.iconSize().width(), MAX_ICON_SIZE)
        widget.close()

    def test_html_and_web_islands_show_placeholder_and_ignore_icon_zoom(self) -> None:
        cases = (
            IslandState(kind="html", html_path=str(self.html_file()), width=420, height=320, tabs=[TabState()]),
            IslandState(kind="web", web_url="https://example.com", width=420, height=320, tabs=[TabState()]),
        )
        for state in cases:
            with self.subTest(kind=state.kind):
                widget = IslandWidget(state, desktop_window=True)
                widget.show()
                self.app.processEvents()
                self.assertTrue(widget.is_web_content)
                self.assertIsNotNone(widget.web)
                self.assertIsNotNone(widget.web.placeholder)
                self.assertFalse(widget.item_list.isVisible())
                widget.zoom_icons(1)
                self.assertEqual(state.icon_size, 48)
                widget.toggle_collapsed()
                QTest.qWait(COLLAPSE_MS + 160)
                self.assertEqual(widget.height(), 44)
                widget.toggle_collapsed()
                QTest.qWait(COLLAPSE_MS + 160)
                self.assertEqual(widget.height(), 320)
                widget.close()

    def test_normalize_url(self) -> None:
        self.assertEqual(normalize_url("example.com"), "https://example.com")
        self.assertEqual(normalize_url("https://github.com/narabias"), "https://github.com/narabias")
        self.assertEqual(normalize_url("  "), "")
        self.assertTrue(normalize_url("北京 天气").startswith("https://www.bing.com/search?q="))


class DialogTests(_Workspace):
    def test_new_island_dialog_kinds(self) -> None:
        for kind, island_kind in (("normal", "files"), ("portal", "files"), ("html", "html"), ("web", "web")):
            with self.subTest(kind=kind):
                dialog = NewIslandDialog(None, None, kind)
                self.assertEqual(dialog.selected_kind(), kind)
                self.assertEqual(dialog.data()["island_kind"], island_kind)
                dialog.close()

        dialog = NewIslandDialog(None, None, "html")
        dialog._validate_and_accept()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted, "a missing HTML file must be rejected")
        dialog.html_edit.setText(str(self.html_file()))
        dialog.name_edit.setText("极光")
        dialog._validate_and_accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        data = dialog.data()
        self.assertEqual((data["title"], data["html_allow_network"]), ("极光", False))
        self.assertTrue(data["html_path"].endswith("动画.html"))

        dialog = NewIslandDialog(None, None, "web")
        dialog.url_edit.setText("example.com")
        dialog._validate_and_accept()
        self.assertEqual(dialog.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.data()["web_url"], "https://example.com")

    def test_settings_dialog_saves_new_preferences(self) -> None:
        original = Preferences()
        dialog = SettingsDialog(original)
        dialog.material_control.setCurrentIndex(2)
        dialog.reduce_motion_check.setChecked(True)
        dialog.smart_pause_check.setChecked(False)
        dialog.fps_control.setCurrentIndex(FPS_CHOICES.index(30))
        dialog.auto_update_check.setChecked(False)
        dialog.font_size_spin.setValue(12.0)
        dialog._save_and_accept()
        saved = dialog.preferences
        self.assertEqual(saved.island_material, "liquid")
        self.assertTrue(saved.reduce_motion)
        self.assertFalse(saved.smart_pause)
        self.assertEqual(saved.media_fps, 30)
        self.assertFalse(saved.auto_check_updates)
        self.assertEqual(saved.font_size, 12.0)
        self.assertEqual(saved.backdrop_source, "wallpaper", "no image chosen -> keep the wallpaper")
        self.assertEqual(original.island_material, "frosted", "the input preferences must not be mutated")

        dialog = SettingsDialog(saved)
        dialog._restore_defaults()
        dialog._save_and_accept()
        self.assertEqual(dialog.preferences.island_material, "frosted")
        self.assertEqual(dialog.preferences.media_fps, 24)
        self.assertTrue(dialog.preferences.auto_check_updates)

    def test_appearance_dialog_values_and_preview(self) -> None:
        state = IslandState(title="工作", color="#4F7CAC")
        previews: list[dict] = []
        dialog = IslandAppearanceDialog(state, "frosted", previews.append)
        dialog.name_edit.setText("我的收纳岛")
        dialog.material_control.setCurrentIndex(3)
        values = dialog.values()
        self.assertEqual(values["title"], "我的收纳岛")
        self.assertEqual(values["material"], "liquid")
        self.assertEqual(values["color"], "#4F7CAC")
        self.assertEqual(values["media_path"], "")
        self.assertAlmostEqual(values["media_opacity"], 0.9)
        self.assertEqual(values["media_feather"], 26)
        QTest.qWait(120)
        self.assertTrue(previews)
        self.assertEqual(previews[-1]["title"], "我的收纳岛")

        dialog.name_edit.setText("   ")
        dialog._validate_and_accept()
        self.assertNotEqual(dialog.result(), QDialog.DialogCode.Accepted, "an empty name must be rejected")
        dialog.material_control.setCurrentIndex(0)
        self.assertEqual(dialog.values()["material"], "")


class BoardTests(_Workspace):
    def test_board_creates_html_and_web_islands(self) -> None:
        normal = IslandState(title="普通", tabs=[TabState()])
        page = PageState(title="主页", islands=[normal])
        state = AppState(pages=[page], current_page_id=page.id)
        original_dirs = board_module._desktop_directories
        board_module._desktop_directories = lambda: []
        try:
            window = DesktopWindow(state, StateStore(self.root / "data"), demo_mode=True)
            window.resize(1200, 760)
            window.show()
            self.app.processEvents()

            html_data = {"island_kind": "html", "title": "", "html_path": str(self.html_file()),
                         "html_allow_network": False}
            with patch.object(board_module.NewIslandDialog, "get_data", return_value=html_data):
                window.add_island(kind="html")
            html_state = page.islands[-1]
            self.assertEqual(html_state.kind, "html")
            self.assertEqual(html_state.title, "HTML 动画")
            self.assertEqual((html_state.width, html_state.height), (420, 320))
            self.assertTrue(window.islands[html_state.id].is_web_content)

            web_data = {"island_kind": "web", "title": "看板", "web_url": "https://example.com"}
            with patch.object(board_module.NewIslandDialog, "get_data", return_value=web_data):
                window.add_island(kind="web")
            web_state = page.islands[-1]
            self.assertEqual((web_state.kind, web_state.title, web_state.web_url),
                             ("web", "看板", "https://example.com"))
            self.assertIsNone(web_state.tabs[0].portal_path)

            with patch.object(board_module.NewIslandDialog, "get_data", return_value=None):
                window.add_island()
            self.assertEqual(len(page.islands), 3)

            self.assertTrue(board_module._is_file_island(normal))
            self.assertFalse(board_module._is_file_island(html_state))
            self.assertFalse(board_module._is_file_island(web_state))

            window._closing_for_real = True
            window.close()
            self.app.processEvents()
        finally:
            board_module._desktop_directories = original_dirs


if __name__ == "__main__":
    unittest.main()

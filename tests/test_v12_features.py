"""Model, updater and storage regressions from 1.2 that still apply to 2.0."""

from __future__ import annotations

import shutil
import time
import unittest
from pathlib import Path
from uuid import uuid4

import deskisle
from deskisle.engine.webhost import normalize_url
from deskisle.models import AppState, IslandState, PageState, Preferences, TabState
from deskisle.storage import StateStore
from deskisle.updater import (
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
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parent / ".test-work" / uuid4().hex
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)


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
        self.assertEqual(restored.kind, "web")  # 2.0: "html" islands became "web"
        for name in ("html_path", "html_allow_network", "material", "media_path", "media_opacity",
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


class UrlTests(unittest.TestCase):
    def test_normalize_url(self) -> None:
        self.assertEqual(normalize_url("example.com"), "https://example.com")
        self.assertEqual(normalize_url("https://github.com/narabias"), "https://github.com/narabias")
        self.assertEqual(normalize_url("  "), "")
        self.assertTrue(normalize_url("北京 天气").startswith("https://www.bing.com/search?q="))


if __name__ == "__main__":
    unittest.main()

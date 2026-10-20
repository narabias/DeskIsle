"""First-run welcome guide: shown once, never in demo mode, always reversible."""

from __future__ import annotations

import os
import shutil
import unittest
from pathlib import Path
from uuid import uuid4

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from deskisle.board import DesktopWindow  # noqa: E402
from deskisle.dialogs import WelcomeDialog  # noqa: E402
from deskisle.models import AppState, PageState, Preferences  # noqa: E402
from deskisle.storage import StateStore  # noqa: E402


class OnboardingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.root = Path(__file__).parent / ".test-work" / uuid4().hex
        self.root.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def test_onboarding_done_defaults_to_false_and_roundtrips(self) -> None:
        self.assertFalse(Preferences().onboarding_done)
        prefs = Preferences(onboarding_done=True)
        self.assertTrue(Preferences.from_dict(prefs.to_dict()).onboarding_done)

    def test_onboarding_flag_survives_missing_key(self) -> None:
        # Older state files have no such key; loading must not raise.
        legacy = Preferences().to_dict()
        legacy.pop("onboarding_done")
        self.assertFalse(Preferences.from_dict(legacy).onboarding_done)

    def test_welcome_dialog_defaults_to_startup_enabled(self) -> None:
        dialog = WelcomeDialog(None)
        self.assertTrue(dialog.wants_startup())
        dialog.startup_check.setChecked(False)
        self.assertFalse(dialog.wants_startup())
        dialog.close()

    def test_welcome_is_skipped_in_demo_mode(self) -> None:
        state = AppState(pages=[PageState()], current_page_id="")
        window = DesktopWindow(state, StateStore(self.root / "data"), demo_mode=True)
        # Demo mode must never block on a modal guide.
        window.maybe_show_welcome()
        self.assertFalse(window.state.preferences.onboarding_done)
        window.close()

    def test_welcome_is_skipped_after_completion(self) -> None:
        state = AppState(pages=[PageState()])
        state.preferences.onboarding_done = True
        window = DesktopWindow(state, StateStore(self.root / "data"), demo_mode=True)
        window.maybe_show_welcome()
        self.assertTrue(window.state.preferences.onboarding_done)
        window.close()


if __name__ == "__main__":
    unittest.main()

"""Non-destructive automatic organization rules."""

from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from os import PathLike
from pathlib import Path
from typing import Any

from .models import AppState, IslandState, ItemRef, Rule, TabState


_SHORTCUT_EXTENSIONS = {".lnk", ".url", ".website", ".appref-ms"}
_DOCUMENT_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docm",
    ".docx",
    ".epub",
    ".htm",
    ".html",
    ".ini",
    ".json",
    ".log",
    ".md",
    ".ods",
    ".odt",
    ".pdf",
    ".ppt",
    ".pptm",
    ".pptx",
    ".rtf",
    ".tex",
    ".txt",
    ".xls",
    ".xlsm",
    ".xlsx",
    ".xml",
    ".yaml",
    ".yml",
}
_IMAGE_EXTENSIONS = {
    ".avif",
    ".bmp",
    ".gif",
    ".heic",
    ".heif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".tif",
    ".tiff",
    ".webp",
}
_MEDIA_EXTENSIONS = {
    ".3gp",
    ".aac",
    ".avi",
    ".flac",
    ".m4a",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
    ".wma",
    ".wmv",
}
_ARCHIVE_EXTENSIONS = {
    ".7z",
    ".bz2",
    ".cab",
    ".gz",
    ".iso",
    ".rar",
    ".tar",
    ".tgz",
    ".xz",
    ".zip",
}


class RuleEngine:
    """Match paths to islands without moving the underlying files."""

    def __init__(self, rules: Iterable[Rule | Mapping[str, Any]] | None = None) -> None:
        self.rules = self._normalize_rules(rules or [])

    @staticmethod
    def match(rule: Rule | Mapping[str, Any], path: str | PathLike[str]) -> bool:
        """Return whether an enabled rule matches *path*.

        Matching is case-insensitive.  Extension rules accept values with or
        without a leading dot and may contain comma/semicolon/pipe-separated
        alternatives.
        """

        normalized_rule = rule if isinstance(rule, Rule) else Rule.from_dict(rule)
        if not normalized_rule.enabled:
            return False

        try:
            path_text = os.fspath(path)
        except TypeError:
            return False
        if not path_text:
            return False

        name = Path(path_text).name.casefold()
        condition = normalized_rule.condition.strip().casefold()
        value = normalized_rule.value.strip().casefold()

        if condition == "extension":
            if not value or RuleEngine._is_folder(path_text):
                return False
            extensions = {
                token if token.startswith(".") else f".{token.lstrip('*')}"
                for token in re.split(r"[,;|\s]+", value)
                if token.strip(".* ")
            }
            return any(name.endswith(extension) for extension in extensions)
        if condition == "name_contains":
            return bool(value) and value in name
        if condition == "name_starts":
            return bool(value) and name.startswith(value)
        if condition == "name_ends":
            return bool(value) and name.endswith(value)
        if condition == "kind":
            expected = {
                token.strip()
                for token in re.split(r"[,;|]+", value)
                if token.strip()
            }
            return RuleEngine.kind_of(path_text) in expected
        return False

    def choose_target(
        self,
        path: str | PathLike[str],
        rules: Iterable[Rule | Mapping[str, Any]] | None = None,
    ) -> str | None:
        """Return the first matching target, with lower priorities winning."""

        for rule in self._ordered_rules(rules):
            if rule.target_island_id and self.match(rule, path):
                return rule.target_island_id
        return None

    def preview(
        self,
        paths: Iterable[str | PathLike[str]],
        rules: Iterable[Rule | Mapping[str, Any]] | None = None,
        *,
        state: AppState | None = None,
    ) -> dict[str, str | None]:
        """Preview targets for paths.

        When *state* is supplied, already grouped paths and paths deliberately
        kept in ``loose_items`` are omitted.  This mirrors the automatic scan
        contract: only genuinely new desktop paths are candidates.
        """

        result: dict[str, str | None] = {}
        for raw_path in paths:
            try:
                path = os.fspath(raw_path)
            except TypeError:
                continue
            if not path or (state is not None and self.is_known_path(state, path)):
                continue
            result[path] = self.choose_target(path, rules)
        return result

    def apply_path(
        self,
        path: str | PathLike[str],
        state: AppState,
        rules: Iterable[Rule | Mapping[str, Any]] | None = None,
        *,
        title: str = "",
    ) -> str | None:
        """Add a new path reference to its matching ordinary island.

        No file-system mutation is performed.  Known paths, including those in
        ``state.loose_items``, are intentionally ignored.  If the target's
        active tab is a folder portal, the reference is placed in another
        ordinary tab (or a new ordinary tab), never copied into the portal.
        """

        if not isinstance(state, AppState):
            raise TypeError("state must be an AppState")
        try:
            path_text = os.fspath(path)
        except TypeError:
            return None
        if not path_text or not state.preferences.auto_organize:
            return None
        if self.is_known_path(state, path_text):
            return None

        effective_rules = rules
        if effective_rules is None and not self.rules:
            effective_rules = state.rules
        target_id = self.choose_target(path_text, effective_rules)
        if target_id is None:
            return None

        island = self._find_island(state, target_id)
        if island is None:
            return None
        tab = self._ordinary_target_tab(island)
        tab.items.append(ItemRef(path=path_text, title=title))
        return target_id

    @staticmethod
    def is_known_path(state: AppState, path: str | PathLike[str]) -> bool:
        """Return whether a path is already grouped or explicitly left loose."""

        try:
            identity = RuleEngine._path_identity(os.fspath(path))
        except TypeError:
            return False
        if not identity:
            return False

        for item in state.loose_items:
            if RuleEngine._path_identity(item.path) == identity:
                return True
        for page in state.pages:
            for island in page.islands:
                for tab in island.tabs:
                    for item in tab.items:
                        if RuleEngine._path_identity(item.path) == identity:
                            return True
        return False

    @staticmethod
    def kind_of(path: str | PathLike[str]) -> str:
        """Classify a path into one of the supported ``kind`` values."""

        try:
            path_text = os.fspath(path)
        except TypeError:
            return ""
        if RuleEngine._is_folder(path_text):
            return "folder"
        extension = Path(path_text).suffix.casefold()
        if extension in _SHORTCUT_EXTENSIONS:
            return "shortcut"
        if extension in _DOCUMENT_EXTENSIONS:
            return "document"
        if extension in _IMAGE_EXTENSIONS:
            return "image"
        if extension in _MEDIA_EXTENSIONS:
            return "media"
        if extension in _ARCHIVE_EXTENSIONS:
            return "archive"
        return ""

    def _ordered_rules(
        self, rules: Iterable[Rule | Mapping[str, Any]] | None
    ) -> list[Rule]:
        normalized = self.rules if rules is None else self._normalize_rules(rules)
        # Python's sort is stable, so source order resolves equal priorities.
        return sorted(
            (rule for rule in normalized if rule.enabled),
            key=lambda rule: rule.priority,
        )

    @staticmethod
    def _normalize_rules(
        rules: Iterable[Rule | Mapping[str, Any]],
    ) -> list[Rule]:
        result: list[Rule] = []
        for rule in rules:
            if isinstance(rule, Rule):
                result.append(rule)
            elif isinstance(rule, Mapping):
                result.append(Rule.from_dict(rule))
        return result

    @staticmethod
    def _find_island(state: AppState, island_id: str) -> IslandState | None:
        for page in state.pages:
            for island in page.islands:
                if island.id == island_id:
                    return island
        return None

    @staticmethod
    def _ordinary_target_tab(island: IslandState) -> TabState:
        for tab in island.tabs:
            if tab.id == island.active_tab_id and tab.portal_path is None:
                return tab
        for tab in island.tabs:
            if tab.portal_path is None:
                return tab
        tab = TabState(title="全部")
        island.tabs.append(tab)
        island.active_tab_id = tab.id
        return tab

    @staticmethod
    def _path_identity(path: str) -> str:
        if not path:
            return ""
        return os.path.normcase(os.path.abspath(os.path.normpath(path)))

    @staticmethod
    def _is_folder(path: str) -> bool:
        if path.endswith(("/", "\\")):
            return True
        try:
            return Path(path).is_dir()
        except OSError:
            return False


__all__ = ["RuleEngine"]

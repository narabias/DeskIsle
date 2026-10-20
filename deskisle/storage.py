"""Durable JSON persistence for DeskIsle state."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from os import PathLike
from pathlib import Path
from typing import Any

from .models import AppState, IslandState, ItemRef, PageState, Rule, TabState


class StateStoreError(RuntimeError):
    """Raised when an explicit import or snapshot operation cannot complete."""


class StateStore:
    """Store application state under one local data directory.

    ``save`` replaces the main JSON file atomically and maintains a known-good
    ``.bak`` file.  ``load`` falls back to that backup and repairs the primary
    file when the primary JSON is missing or damaged.
    """

    STATE_FILENAME = "state.json"
    BACKUP_FILENAME = "state.json.bak"
    SNAPSHOT_DIRECTORY = "snapshots"
    MEDIA_DIRECTORY = "media"
    FONT_DIRECTORY = "fonts"
    # Background media up to this size is copied next to the layout so it keeps
    # working when the original file is moved; larger videos are referenced.
    MAX_MEDIA_COPY_BYTES = 200 * 1024 * 1024
    MAX_FONT_COPY_BYTES = 64 * 1024 * 1024

    def __init__(self, root: str | PathLike[str] | None = None) -> None:
        if root is None:
            configured = os.environ.get("DESKISLE_DATA_DIR")
            local_app_data = os.environ.get("LOCALAPPDATA")
            if configured:
                root = configured
            elif local_app_data:
                root = Path(local_app_data) / "DeskIsle"
            else:
                root = Path.home() / "AppData" / "Local" / "DeskIsle"

        self.root = Path(root).expanduser()
        self.state_path = self.root / self.STATE_FILENAME
        self.backup_path = self.root / self.BACKUP_FILENAME
        self.snapshots_dir = self.root / self.SNAPSHOT_DIRECTORY
        self.media_dir = self.root / self.MEDIA_DIRECTORY
        self.fonts_dir = self.root / self.FONT_DIRECTORY

    def load(self) -> AppState:
        """Load state, recovering from the backup when necessary.

        Missing or unusable primary and backup files result in a fresh default
        state.  This makes startup resilient while explicit import operations
        still report malformed input to the caller.
        """

        try:
            return self._load_state_file(self.state_path)
        except (OSError, StateStoreError):
            pass

        try:
            recovered = self._load_state_file(self.backup_path)
        except (OSError, StateStoreError):
            return self.create_default_state([])

        # Repair the primary without rotating the known-good backup away.
        try:
            self._atomic_write_json(self.state_path, recovered.to_dict())
        except OSError:
            # A read-only data directory should not prevent use of the backup.
            pass
        return recovered

    def save(self, state: AppState | Mapping[str, Any]) -> Path:
        """Atomically persist *state* and maintain a recoverable backup."""

        normalized = self._coerce_state(state)
        payload = normalized.to_dict()
        self.root.mkdir(parents=True, exist_ok=True)

        previous_payload: Mapping[str, Any] | None = None
        if self.state_path.exists():
            try:
                previous_payload = self._read_mapping(self.state_path)
                # Parse through the model before considering it known-good.
                AppState.from_dict(previous_payload)
            except (OSError, StateStoreError):
                previous_payload = None

        if previous_payload is not None:
            self._atomic_write_json(self.backup_path, previous_payload)

        self._atomic_write_json(self.state_path, payload)

        # A first save needs a backup too; otherwise one damaged write after the
        # first successful run would leave no recovery point.
        if not self.backup_path.exists():
            self._atomic_write_json(self.backup_path, payload)
        return self.state_path

    def create_default_state(
        self, desktop_paths: Iterable[str | PathLike[str]] | None
    ) -> AppState:
        """Create a useful first-run layout from desktop item references.

        The supplied paths are only recorded as ``ItemRef`` objects.  This
        method never creates, moves, renames, or deletes the referenced items.
        """

        items: list[ItemRef] = []
        seen: set[str] = set()
        for raw_path in desktop_paths or []:
            try:
                path = os.fspath(raw_path)
            except TypeError:
                continue
            if not path:
                continue
            identity = os.path.normcase(os.path.normpath(path))
            if identity in seen:
                continue
            seen.add(identity)
            items.append(ItemRef(path=path))

        shortcut_tab = TabState(title="常用")
        document_tab = TabState(title="文档")
        media_tab = TabState(title="图片与媒体")
        other_tab = TabState(title="文件夹与归档")
        islands = [
            IslandState(
                title="常用应用",
                x=30,
                y=86,
                width=300,
                height=265,
                color="#243245",
                icon_size=48,
                active_tab_id=shortcut_tab.id,
                tabs=[shortcut_tab],
            ),
            IslandState(
                title="文档",
                x=348,
                y=86,
                width=300,
                height=265,
                color="#263A3B",
                icon_size=48,
                active_tab_id=document_tab.id,
                tabs=[document_tab],
            ),
            IslandState(
                title="图片与媒体",
                x=666,
                y=86,
                width=300,
                height=265,
                color="#3A3048",
                icon_size=48,
                active_tab_id=media_tab.id,
                tabs=[media_tab],
            ),
            IslandState(
                title="文件夹与归档",
                x=30,
                y=369,
                width=300,
                height=250,
                color="#44342F",
                icon_size=48,
                active_tab_id=other_tab.id,
                tabs=[other_tab],
            ),
        ]
        page = PageState(title="工作台", islands=islands)
        rules = [
            Rule(name="快捷方式", condition="kind", value="shortcut", target_island_id=islands[0].id, priority=10),
            Rule(name="文档", condition="kind", value="document", target_island_id=islands[1].id, priority=20),
            Rule(name="图片", condition="kind", value="image", target_island_id=islands[2].id, priority=30),
            Rule(name="音视频", condition="kind", value="media", target_island_id=islands[2].id, priority=40),
            Rule(name="文件夹", condition="kind", value="folder", target_island_id=islands[3].id, priority=50),
            Rule(name="压缩包", condition="kind", value="archive", target_island_id=islands[3].id, priority=60),
        ]
        state = AppState(current_page_id=page.id, pages=[page], rules=rules)

        # Apply the default rules to references only. No filesystem item is
        # moved, renamed or deleted during first-run setup.
        from .rules import RuleEngine

        engine = RuleEngine(rules)
        for item in items:
            if engine.apply_path(item.path, state, title=item.title) is None:
                state.loose_items.append(item)
        return state

    def save_snapshot(self, state: AppState, name: str | None = None) -> Path:
        """Save a named, timestamped layout snapshot and return its path."""

        normalized = self._coerce_state(state)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        safe_name = self._safe_snapshot_name(name or "layout")
        destination = self.snapshots_dir / f"{stamp}--{safe_name}.json"
        self._atomic_write_json(destination, normalized.to_dict())
        return destination

    def list_snapshots(self) -> list[Path]:
        """Return snapshot paths newest first."""

        if not self.snapshots_dir.exists():
            return []
        snapshots = [
            path
            for path in self.snapshots_dir.iterdir()
            if path.is_file() and path.suffix.casefold() == ".json"
        ]
        return sorted(
            snapshots,
            key=lambda path: (path.stat().st_mtime_ns, path.name),
            reverse=True,
        )

    def restore_snapshot(self, snapshot: str | PathLike[str]) -> AppState:
        """Restore a snapshot as current state and return the restored model."""

        source = self._resolve_snapshot(snapshot)
        try:
            state = self._load_state_file(source)
        except (OSError, StateStoreError) as exc:
            raise StateStoreError(f"无法恢复快照：{source}") from exc
        self.save(state)
        return state

    def export(
        self,
        state_or_destination: AppState | Mapping[str, Any] | str | PathLike[str],
        destination: str | PathLike[str] | None = None,
    ) -> Path:
        """Export state to a standalone JSON file.

        Both ``export(state, destination)`` and ``export(destination)`` are
        supported; the latter exports the currently stored state.
        """

        if destination is None:
            state = self.load()
            destination = os.fspath(state_or_destination)
        else:
            state = self._coerce_state(state_or_destination)

        target = Path(destination).expanduser()
        if target.exists() and target.is_dir():
            target = target / "deskisle-layout.json"
        self._atomic_write_json(target, state.to_dict())
        return target

    def export_state(
        self, state: AppState | Mapping[str, Any], destination: str | PathLike[str]
    ) -> Path:
        """Explicit alias for :meth:`export`."""

        return self.export(state, destination)

    def import_state(
        self, source: str | PathLike[str], *, persist: bool = True
    ) -> AppState:
        """Import a standalone JSON file, optionally making it current."""

        path = Path(source).expanduser()
        try:
            state = self._load_state_file(path)
        except (OSError, StateStoreError) as exc:
            raise StateStoreError(f"无法导入布局：{path}") from exc
        if persist:
            self.save(state)
        return state

    # ``import`` is a Python keyword, so public callers get conventional and
    # concise spellings without sacrificing a descriptive implementation name.
    import_ = import_state
    import_file = import_state

    # Managed copies of background media and fonts ---------------------------
    def import_media(self, path: str | PathLike[str]) -> str:
        """Copy a background image/video into ``media/`` and return the path.

        The original file is never modified.  Files that cannot be read or are
        larger than :attr:`MAX_MEDIA_COPY_BYTES` are referenced in place.
        """

        return self._import_managed(path, self.media_dir, self.MAX_MEDIA_COPY_BYTES, keep_name=False)

    def import_font(self, path: str | PathLike[str]) -> str:
        """Copy a user font into ``fonts/`` so it survives moving the original."""

        return self._import_managed(path, self.fonts_dir, self.MAX_FONT_COPY_BYTES, keep_name=True)

    def _import_managed(self, path: str | PathLike[str], folder: Path, limit: int, *, keep_name: bool) -> str:
        source = Path(os.fspath(path)).expanduser()
        try:
            if not source.is_file():
                return os.fspath(path)
            resolved = source.resolve()
            try:
                if resolved.parent == folder.resolve():
                    return str(resolved)
            except OSError:
                pass
            size = source.stat().st_size
            if size <= 0 or size > limit:
                return str(source)
            digest = hashlib.sha256()
            with source.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            suffix = source.suffix.lower()[:12]
            if keep_name:
                stem = re.sub(r"[^\w.-]+", "-", source.stem, flags=re.UNICODE).strip(".-_")[:60] or "font"
                name = "{0}-{1}{2}".format(stem, digest.hexdigest()[:8], suffix)
            else:
                name = digest.hexdigest()[:20] + suffix
            target = folder / name
            if not target.is_file() or target.stat().st_size != size:
                folder.mkdir(parents=True, exist_ok=True)
                temp = target.with_name("." + target.name + ".tmp")
                shutil.copyfile(source, temp)
                os.replace(temp, target)
            return str(target)
        except OSError:
            return str(source)

    def prune_media(self, state: AppState | None = None) -> int:
        """Delete managed media files that no layout references any more.

        References in the current state, the ``.bak`` file and every layout
        snapshot are kept, so restoring an old snapshot never loses its
        background.  Returns the number of removed files.
        """

        if not self.media_dir.is_dir():
            return 0
        keep: set[str] = set()

        def collect(value: Any) -> None:
            if isinstance(value, Mapping):
                for item in value.values():
                    collect(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    collect(item)
            elif isinstance(value, str) and value:
                keep.add(os.path.normcase(os.path.basename(value)))

        if state is not None:
            collect(state.to_dict())
        sources = [self.state_path, self.backup_path]
        if self.snapshots_dir.is_dir():
            sources.extend(path for path in self.snapshots_dir.iterdir() if path.suffix.casefold() == ".json")
        for source in sources:
            try:
                collect(self._read_mapping(source))
            except (OSError, StateStoreError):
                # When any layout cannot be read, keep every file to be safe.
                if source.exists():
                    return 0
        removed = 0
        for path in self.media_dir.iterdir():
            if not path.is_file() or os.path.normcase(path.name) in keep:
                continue
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
        return removed

    @staticmethod
    def _coerce_state(state: AppState | Mapping[str, Any] | Any) -> AppState:
        if isinstance(state, AppState):
            return AppState.from_dict(state.to_dict())
        if isinstance(state, Mapping):
            return AppState.from_dict(state)
        raise TypeError("state must be an AppState or mapping")

    @staticmethod
    def _safe_snapshot_name(name: str) -> str:
        safe = re.sub(r"[^\w.-]+", "-", name.strip(), flags=re.UNICODE)
        safe = safe.strip(".-_")
        return safe[:80] or "layout"

    def _resolve_snapshot(self, snapshot: str | PathLike[str]) -> Path:
        source = Path(snapshot).expanduser()
        if source.is_absolute():
            return source
        if source.suffix.casefold() != ".json":
            source = source.with_suffix(".json")
        return self.snapshots_dir / source

    def _load_state_file(self, path: Path) -> AppState:
        return AppState.from_dict(self._read_mapping(path))

    @staticmethod
    def _read_mapping(path: Path) -> Mapping[str, Any]:
        try:
            with path.open("r", encoding="utf-8-sig") as stream:
                payload = json.load(stream)
        except (json.JSONDecodeError, UnicodeError) as exc:
            raise StateStoreError(f"状态文件不是有效 JSON：{path}") from exc
        if not isinstance(payload, Mapping):
            raise StateStoreError(f"状态文件顶层必须是对象：{path}")
        return payload

    @staticmethod
    def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{path.name}.",
                suffix=".tmp",
                dir=path.parent,
                delete=False,
            ) as stream:
                temp_path = Path(stream.name)
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
            temp_path = None
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass


__all__ = ["StateStore", "StateStoreError"]

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config.settings import STATE_FILE, Settings
from ..state import write_state_file


@dataclass(frozen=True, slots=True)
class StaleStatePlan:
    state_file: Path
    music_dir: Path
    stale_keys: tuple[str, ...]
    source_digest: str
    state: dict[str, Any]

    @property
    def stale_count(self) -> int:
        return len(self.stale_keys)


@dataclass(frozen=True, slots=True)
class StateCleanupResult:
    removed_count: int
    backup_path: Path | None


def _is_outside(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return True
    return False


def _is_pytest_temp_path(path: Path) -> bool:
    if not path.is_absolute():
        return False
    parts = path.parts
    return (
        len(parts) >= 3
        and parts[1] == "tmp"
        and any(part.startswith("pytest-") for part in parts[2:])
    )


def _absolute_media_paths(key: str, entry: object) -> tuple[Path, ...]:
    paths: list[Path] = []
    key_path = Path(key)
    if key_path.is_absolute():
        paths.append(key_path)
    if isinstance(entry, Mapping):
        for field in ("audio_path", "media_path", "file", "path"):
            raw = entry.get(field)
            if isinstance(raw, str) and Path(raw).is_absolute():
                paths.append(Path(raw))
    return tuple(paths)


def _is_stale_record(key: str, entry: object, music_dir: Path) -> bool:
    media_paths = _absolute_media_paths(key, entry)
    if any(not path.exists() and _is_outside(path, music_dir) for path in media_paths):
        return True

    # Preserve ordinary missing relative records because they may represent a
    # track moved within the library. A missing pytest-temporary LRC is useful
    # corroboration only when that relative media record is also absent.
    if isinstance(entry, Mapping) and not Path(key).is_absolute():
        raw_lrc = entry.get("lrc")
        lrc_path = Path(raw_lrc) if isinstance(raw_lrc, str) else None
        media_path = music_dir / key
        if (
            lrc_path is not None
            and _is_pytest_temp_path(lrc_path)
            and not lrc_path.exists()
            and not media_path.exists()
        ):
            return True
    return False


def plan_stale_state_cleanup(
    settings: Settings,
    *,
    state_file: Path = STATE_FILE,
) -> StaleStatePlan:
    source = Path(state_file)
    raw = source.read_bytes() if source.exists() else b""
    try:
        value = json.loads(raw.decode("utf-8")) if raw else {"files": {}, "updated": None}
    except (UnicodeError, json.JSONDecodeError):
        value = {"files": {}, "updated": None}
    state = value if isinstance(value, dict) else {"files": {}, "updated": None}
    files = state.get("files", {})
    stale_keys = (
        tuple(
            key
            for key, entry in files.items()
            if isinstance(key, str)
            and _is_stale_record(key, entry, Path(settings.music_dir))
        )
        if isinstance(files, dict)
        else ()
    )
    return StaleStatePlan(
        source,
        Path(settings.music_dir),
        tuple(stale_keys),
        hashlib.sha256(raw).hexdigest(),
        state,
    )


def execute_stale_state_cleanup(
    plan: StaleStatePlan,
    *,
    copier: Callable[[Path, Path], Any] = shutil.copy2,
    writer: Callable[[Path, Mapping[str, Any]], None] = write_state_file,
) -> StateCleanupResult:
    if not plan.stale_keys:
        return StateCleanupResult(0, None)

    current = plan.state_file.read_bytes()
    if hashlib.sha256(current).hexdigest() != plan.source_digest:
        raise RuntimeError("State changed after the cleanup preview; run the preview again.")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    backup = plan.state_file.with_name(f"{plan.state_file.name}.pre-clean-{stamp}.bak")
    copier(plan.state_file, backup)

    updated = dict(plan.state)
    files = dict(updated.get("files", {}))
    for key in plan.stale_keys:
        files.pop(key, None)
    updated["files"] = files
    writer(plan.state_file, updated)
    return StateCleanupResult(len(plan.stale_keys), backup)

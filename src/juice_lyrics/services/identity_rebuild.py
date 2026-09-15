from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..api.client import search_song_names
from ..config.settings import STATE_FILE, Settings
from ..library.matching import choose_candidate, search_title_for
from ..state import read_state_file, resolve_state_entry, write_state_file
from .library_status import LibrarySnapshot, LibraryTrack, get_library_snapshot
from .library_status import LibraryStateStatus
from .manual_identity import (
    IDENTITY_LOCK_FIELD,
    IDENTITY_SOURCE_FIELD,
    is_identity_locked,
)
from .state_maintenance import plan_stale_state_cleanup


IDENTITY_FIELDS = ("song_id", "api_name", IDENTITY_SOURCE_FIELD, IDENTITY_LOCK_FIELD)


def _valid_track_lock(entry: Mapping[str, Any] | None, track: LibraryTrack) -> bool:
    return bool(
        is_identity_locked(entry)
        and track.state_status is LibraryStateStatus.CURRENT
        and track.content_sha256
        and entry.get("sha256") == track.content_sha256
    )


@dataclass(frozen=True, slots=True)
class IdentityRebuildPlan:
    settings: Settings
    state_file: Path
    source_digest: str
    state: dict[str, Any]
    tracks: tuple[LibraryTrack, ...]
    stale_keys: tuple[str, ...]
    existing_identities: int

    @property
    def current_tracks(self) -> int:
        return len(self.tracks)

    @property
    def currently_unknown(self) -> int:
        return self.current_tracks - self.existing_identities

    @property
    def locked_identities(self) -> int:
        files = self.state.get("files", {})
        state_files = files if isinstance(files, Mapping) else {}
        relative_paths = tuple(track.relative_path for track in self.tracks)
        return sum(
            _valid_track_lock(
                resolve_state_entry(state_files, track.relative_path, relative_paths)[1],
                track,
            )
            for track in self.tracks
        )


@dataclass(frozen=True, slots=True)
class IdentityChange:
    path: Path
    old_song_id: Any
    old_api_name: str | None
    new_song_id: Any
    new_api_name: str | None


@dataclass(frozen=True, slots=True)
class IdentityRebuildProgress:
    completed: int
    total: int
    path: Path
    status: str


@dataclass(frozen=True, slots=True)
class IdentityRebuildResult:
    inspected: int
    matched: int
    unknown: int
    changed_identities: int
    unchanged_identities: int
    failed_preserved: int
    stale_ignored: int
    changes: tuple[IdentityChange, ...]
    errors: tuple[str, ...]
    backup_path: Path | None
    aborted: bool = False
    abort_reason: str | None = None


@dataclass(slots=True)
class IdentityRebuildDependencies:
    state_reader: Callable[[Path], dict[str, Any]] = read_state_file
    state_writer: Callable[[Path, Mapping[str, Any]], None] = write_state_file
    searcher: Callable[..., list[dict[str, Any]]] = search_song_names
    matcher: Callable[..., Any] = choose_candidate
    search_title: Callable[[Path], str] = search_title_for
    copier: Callable[[Path, Path], Any] = shutil.copy2


def _source_bytes(path: Path) -> bytes:
    return path.read_bytes() if path.exists() else b""


def _digest(path: Path) -> str:
    return hashlib.sha256(_source_bytes(path)).hexdigest()


def _identity(entry: Mapping[str, Any] | None) -> tuple[Any, str | None]:
    if not isinstance(entry, Mapping):
        return None, None
    name = str(entry.get("api_name") or "").strip() or None
    return entry.get("song_id"), name


def _has_identity(entry: Mapping[str, Any] | None) -> bool:
    song_id, name = _identity(entry)
    return song_id is not None and name is not None


def plan_catalogue_identity_rebuild(
    settings: Settings,
    *,
    state_file: Path = STATE_FILE,
    snapshot_provider: Callable[..., LibrarySnapshot] = get_library_snapshot,
) -> IdentityRebuildPlan:
    """Create a read-only rebuild preview for the current local library."""

    state_path = Path(state_file)
    maintenance = plan_stale_state_cleanup(settings, state_file=state_path)
    snapshot = snapshot_provider(settings, state_file=state_path)
    state = maintenance.state
    files = state.get("files", {})
    state_files = files if isinstance(files, Mapping) else {}
    relative_paths = tuple(track.relative_path for track in snapshot.tracks)
    existing = sum(
        _has_identity(resolve_state_entry(state_files, track.relative_path, relative_paths)[1])
        for track in snapshot.tracks
    )
    return IdentityRebuildPlan(
        settings=settings,
        state_file=state_path,
        source_digest=maintenance.source_digest,
        state=state,
        tracks=snapshot.tracks,
        stale_keys=maintenance.stale_keys,
        existing_identities=existing,
    )


def _validate_candidate_state(state: Mapping[str, Any], tracks: Sequence[LibraryTrack]) -> None:
    files = state.get("files")
    if not isinstance(files, Mapping):
        raise RuntimeError("Rebuilt state has an invalid files collection.")
    relative_paths = tuple(track.relative_path for track in tracks)
    for track in tracks:
        _, entry = resolve_state_entry(files, track.relative_path, relative_paths)
        if entry is None:
            continue
        song_id, api_name = _identity(entry)
        if (song_id is None) != (api_name is None):
            raise RuntimeError(f"Rebuilt identity is incomplete for {track.relative_path}.")


def execute_catalogue_identity_rebuild(
    plan: IdentityRebuildPlan,
    *,
    refresh: bool = False,
    dependencies: IdentityRebuildDependencies | None = None,
    progress: Callable[[IdentityRebuildProgress], None] | None = None,
    include_locked: bool = False,
) -> IdentityRebuildResult:
    """Re-match current tracks and atomically replace identity fields only."""

    dependencies = dependencies or IdentityRebuildDependencies()
    if _digest(plan.state_file) != plan.source_digest:
        raise RuntimeError("State changed after the rebuild preview; run the preview again.")

    original_files = plan.state.get("files", {})
    source_files = original_files if isinstance(original_files, Mapping) else {}
    rebuilt_files = dict(source_files)
    rebuilt_state = dict(plan.state)
    relative_paths = tuple(track.relative_path for track in plan.tracks)
    changes: list[IdentityChange] = []
    errors: list[str] = []
    successful_queries = failures = 0

    for completed, track in enumerate(plan.tracks, start=1):
        _, resolved = resolve_state_entry(source_files, track.relative_path, relative_paths)
        old_song_id, old_api_name = _identity(resolved)
        reference = str(track.relative_path)
        exact = source_files.get(reference)
        had_entry = isinstance(exact, Mapping) or isinstance(resolved, Mapping)
        base = dict(exact) if isinstance(exact, Mapping) else dict(resolved or {})
        if _valid_track_lock(resolved, track) and not include_locked:
            if progress is not None:
                progress(
                    IdentityRebuildProgress(
                        completed, len(plan.tracks), track.path, "manual match preserved"
                    )
                )
            continue
        try:
            query = dependencies.search_title(track.path)
            results = dependencies.searcher(plan.settings, query, refresh=refresh)
            successful_queries += 1
            candidate, _, _, _ = dependencies.matcher(
                plan.settings, track.path, results, query
            )
            for field in IDENTITY_FIELDS:
                base.pop(field, None)
            if isinstance(candidate, Mapping):
                song_id = candidate.get("id")
                api_name = str(candidate.get("name") or "").strip() or None
                if song_id is not None and api_name is not None:
                    base["song_id"] = song_id
                    base["api_name"] = api_name
            new_song_id, new_api_name = _identity(base)
            if had_entry or base:
                rebuilt_files[reference] = base
            if (old_song_id, old_api_name) != (new_song_id, new_api_name):
                changes.append(
                    IdentityChange(
                        track.relative_path,
                        old_song_id,
                        old_api_name,
                        new_song_id,
                        new_api_name,
                    )
                )
            status = "matched" if new_song_id is not None else "unknown"
        except Exception as exc:
            failures += 1
            errors.append(f"{track.filename}: {str(exc) or type(exc).__name__}")
            status = "preserved after failure"
        if progress is not None:
            progress(IdentityRebuildProgress(completed, len(plan.tracks), track.path, status))

    if failures and successful_queries == 0:
        return IdentityRebuildResult(
            inspected=len(plan.tracks),
            matched=plan.existing_identities,
            unknown=plan.currently_unknown,
            changed_identities=0,
            unchanged_identities=len(plan.tracks),
            failed_preserved=failures,
            stale_ignored=len(plan.stale_keys),
            changes=(),
            errors=tuple(errors),
            backup_path=None,
            aborted=True,
            abort_reason="Catalogue provider was unavailable; original identities were preserved.",
        )

    rebuilt_state["files"] = rebuilt_files
    _validate_candidate_state(rebuilt_state, plan.tracks)
    if _digest(plan.state_file) != plan.source_digest:
        raise RuntimeError("State changed during the rebuild; no changes were written.")

    matched = unknown = 0
    for track in plan.tracks:
        _, entry = resolve_state_entry(rebuilt_files, track.relative_path, relative_paths)
        if _has_identity(entry):
            matched += 1
        else:
            unknown += 1
    changed = len(changes)
    unchanged = len(plan.tracks) - changed

    backup: Path | None = None
    if rebuilt_state != plan.state:
        if plan.state_file.exists():
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            backup = plan.state_file.with_name(
                f"{plan.state_file.name}.pre-identity-rebuild-{stamp}.bak"
            )
            dependencies.copier(plan.state_file, backup)
        dependencies.state_writer(plan.state_file, rebuilt_state)

    return IdentityRebuildResult(
        inspected=len(plan.tracks),
        matched=matched,
        unknown=unknown,
        changed_identities=changed,
        unchanged_identities=unchanged,
        failed_preserved=failures,
        stale_ignored=len(plan.stale_keys),
        changes=tuple(changes),
        errors=tuple(errors),
        backup_path=backup,
    )

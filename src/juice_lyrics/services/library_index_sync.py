"""Routine, state-only Library Sync for local discovery and catalogue identity."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config.settings import STATE_FILE, Settings
from ..state import file_fingerprint, read_state_file, sha256_file, write_state_file
from .library_identity import (
    IdentityBackfillDependencies,
    backfill_catalogue_identities,
)
from .library_status import (
    LibraryMatchStatus,
    LibrarySnapshot,
    LibraryStateStatus,
    LibraryTrack,
    get_library_snapshot,
)


@dataclass(frozen=True, slots=True)
class LibraryIndexSyncResult:
    snapshot: LibrarySnapshot
    new: int = 0
    changed: int = 0
    removed: int = 0
    identified: int = 0
    unknown: int = 0
    failed: int = 0
    error: str | None = None

    @property
    def summary(self) -> str:
        if self.error:
            return f"Library scan complete · {self.error}"
        if not (self.new or self.changed or self.removed or self.identified or self.failed):
            return "Library is up to date"
        parts = [f"Library synced · {self.snapshot.total_track_count} tracks"]
        for count, label in (
            (self.new, "new"), (self.changed, "changed"),
            (self.removed, "removed"), (self.identified, "newly matched"),
            (self.failed, "could not be checked"),
        ):
            if count:
                parts.append(f"{count} {label}")
        return " · ".join(parts)


@dataclass(slots=True)
class LibraryIndexSyncDependencies:
    snapshot_provider: Callable[..., LibrarySnapshot] = get_library_snapshot
    identity: IdentityBackfillDependencies | None = None
    state_reader: Callable[[Path], dict[str, Any]] = read_state_file
    state_writer: Callable[[Path, Mapping[str, Any]], None] = write_state_file
    hasher: Callable[[Path], str] = sha256_file


def _source_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _current_hash(track: LibraryTrack, hasher: Callable[[Path], str]) -> str:
    if (
        track.content_sha256 is not None
        and track.content_fingerprint is not None
        and file_fingerprint(track.path) == track.content_fingerprint
    ):
        return track.content_sha256
    return hasher(track.path)


def _unknown_check_due(entry: object, track: LibraryTrack, settings: Settings) -> bool:
    if not isinstance(entry, dict) or entry.get("sha256") != track.content_sha256:
        return True
    checked = entry.get("catalogue_checked_at")
    if not isinstance(checked, str):
        return True
    try:
        when = datetime.fromisoformat(checked)
        if when.tzinfo is None:
            return True
        age = (datetime.now(timezone.utc) - when).total_seconds()
    except ValueError:
        return True
    return age < 0 or age >= settings.cache_ttl_hours * 3600


def sync_library_index(
    settings: Settings,
    *,
    previous_snapshot: LibrarySnapshot | None = None,
    state_file: Path = STATE_FILE,
    dependencies: LibraryIndexSyncDependencies | None = None,
) -> LibraryIndexSyncResult:
    """Discover, identify, and retire only known active records; never edit media."""

    deps = dependencies or LibraryIndexSyncDependencies()
    state_path = Path(state_file)
    original_bytes = _source_bytes(state_path)
    if original_bytes is not None:
        try:
            raw_state = json.loads(original_bytes)
        except (UnicodeError, ValueError) as exc:
            raise RuntimeError("Library state is malformed; Sync will not overwrite it.") from exc
        if not isinstance(raw_state, dict) or not isinstance(raw_state.get("files", {}), dict):
            raise RuntimeError("Library state is malformed; Sync will not overwrite it.")
    original = deps.state_reader(state_path)
    if original_bytes is not None and (
        not isinstance(original, dict) or not isinstance(original.get("files", {}), dict)
    ):
        raise RuntimeError("Library state is malformed; Sync will not overwrite it.")
    if _source_bytes(state_path) != original_bytes:
        raise RuntimeError("Library state changed while Sync started; try again.")

    snapshot = deps.snapshot_provider(
        settings, state_file=state_path, previous_snapshot=previous_snapshot
    )
    if not snapshot.directory_exists:
        return LibraryIndexSyncResult(snapshot, error="Music directory is unavailable")
    current = {str(track.relative_path): track for track in snapshot.tracks}
    prior = (
        {str(track.relative_path): track for track in previous_snapshot.tracks}
        if previous_snapshot is not None and previous_snapshot.library_path == snapshot.library_path
        else {}
    )
    new = changed = 0
    for reference, track in current.items():
        earlier = prior.get(reference)
        if earlier is None:
            if track.state_status is LibraryStateStatus.NEW:
                new += 1
            elif track.state_status is LibraryStateStatus.CHANGED:
                changed += 1
        elif earlier.content_fingerprint != track.content_fingerprint:
            changed += 1

    managed_paths = original.get("library_sync_paths", ())
    previously_active = {
        reference for reference in (managed_paths if isinstance(managed_paths, list) else ())
        if isinstance(reference, str)
        and reference
        and not Path(reference).is_absolute()
        and ".." not in Path(reference).parts
    }
    previously_active.update(prior)
    removed_paths = previously_active - current.keys()
    candidate_state = copy.deepcopy(original)
    files = candidate_state.setdefault("files", {})
    if not isinstance(files, dict):
        raise RuntimeError("Library state records are malformed; Sync will not overwrite them.")
    for reference in removed_paths:
        # Retire exact active records without destroying their custom history.
        # Historical basename aliases and unrelated records are untouched.
        entry = files.get(reference)
        if isinstance(entry, dict):
            entry["library_removed_at"] = datetime.now(timezone.utc).isoformat()
    for reference in current:
        entry = files.get(reference)
        if isinstance(entry, dict):
            entry.pop("library_removed_at", None)

    targets = tuple(
        track for track in snapshot.tracks
        if track.match_status is LibraryMatchStatus.UNMATCHED
        and (track.media_format == "MP3" or (track.title and track.artist))
        and _unknown_check_due(files.get(str(track.relative_path)), track, settings)
    )
    identity_deps = replace(
        deps.identity or IdentityBackfillDependencies(),
        state_reader=lambda path: candidate_state,
        state_writer=lambda path, state: None,
    )
    try:
        identity = backfill_catalogue_identities(
            settings, targets, state_file=state_path, dependencies=identity_deps
        ) if targets else None
    except RuntimeError:
        return LibraryIndexSyncResult(snapshot, new, changed, len(removed_paths), error="State changed during Sync; retry safely")
    failed_paths = set(identity.failed_paths) if identity is not None else set()
    attempted_paths = {str(track.relative_path) for track in targets}
    if identity is not None and identity.failed == len(targets) and not identity.identified:
        return LibraryIndexSyncResult(
            snapshot, new, changed, len(removed_paths),
            unknown=snapshot.unmatched_count, failed=identity.failed,
            error="Catalogue identification unavailable; existing state was kept",
        )

    calculated_hashes: dict[str, str] = {}
    for reference, track in current.items():
        if reference in failed_paths:
            continue
        entry = files.get(reference)
        if (
            track.state_status is LibraryStateStatus.CHANGED
            and isinstance(entry, dict)
            and entry.get("sha256") == track.content_sha256
        ):
            # A newly identified replacement must not inherit lyric claims
            # derived from the previous audio bytes at this same path.
            entry.pop("lyric_type", None)
            entry.pop("lrc", None)
        if isinstance(entry, dict) and entry.get("sha256") == track.content_sha256 and entry.get("song_id") is not None:
            continue
        if track.state_status not in {LibraryStateStatus.NEW, LibraryStateStatus.CHANGED}:
            continue
        try:
            audio_hash = _current_hash(track, deps.hasher)
        except OSError:
            failed_paths.add(reference)
            continue
        calculated_hashes[reference] = audio_hash
        updated = dict(entry) if isinstance(entry, dict) else {}
        if updated.get("sha256") != audio_hash:
            updated.pop("song_id", None)
            updated.pop("api_name", None)
            updated.pop("lyric_type", None)
            updated.pop("lrc", None)
            updated.pop("catalogue_checked_at", None)
        updated["sha256"] = audio_hash
        if reference in attempted_paths and not updated.get("song_id"):
            updated["catalogue_checked_at"] = datetime.now(timezone.utc).isoformat()
        files[reference] = updated

    candidate_state["library_sync_paths"] = sorted(current)
    if _source_bytes(state_path) != original_bytes:
        return LibraryIndexSyncResult(snapshot, new, changed, len(removed_paths), error="State changed during Sync; retry safely")
    effective_change = candidate_state != original
    if effective_change:
        deps.state_writer(state_path, candidate_state)

    refreshed_tracks: list[LibraryTrack] = []
    for track in snapshot.tracks:
        reference = str(track.relative_path)
        entry = files.get(reference)
        if not isinstance(entry, dict) or not entry.get("sha256"):
            refreshed_tracks.append(track)
            continue
        try:
            audio_hash = calculated_hashes.get(reference) or _current_hash(track, deps.hasher)
        except OSError:
            refreshed_tracks.append(track)
            continue
        if entry.get("sha256") != audio_hash:
            refreshed_tracks.append(track)
            continue
        updated_track = replace(
            track,
            state_status=LibraryStateStatus.CURRENT,
            content_sha256=audio_hash,
        )
        if (
            entry.get("song_id") is not None
            and entry.get("api_name")
            and (track.media_format == "MP3" or (track.title and track.artist))
        ):
            updated_track = replace(
                updated_track,
                match_status=LibraryMatchStatus.MATCHED,
                matched_title=str(entry["api_name"]),
            )
        refreshed_tracks.append(updated_track)
    final_signature = (
        hashlib.sha256(_source_bytes(state_path) or b"").hexdigest()
        if state_path.is_file() else None
    )
    final_snapshot = replace(
        snapshot, tracks=tuple(refreshed_tracks), state_signature=final_signature
    )
    return LibraryIndexSyncResult(
        final_snapshot, new, changed, len(removed_paths),
        identified=identity.identified if identity else 0,
        unknown=final_snapshot.unmatched_count,
        failed=len(failed_paths),
    )

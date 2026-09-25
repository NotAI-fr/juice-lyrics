"""Explicit user-selected catalogue identities with file-bound locking."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..backup.manager import now_iso
from ..config.settings import STATE_FILE, Settings
from ..state import (
    file_fingerprint,
    read_state_file,
    resolve_state_entry,
    sha256_file,
    write_state_file,
)
if TYPE_CHECKING:
    from .library_status import LibraryTrack

IDENTITY_SOURCE_FIELD = "identity_source"
IDENTITY_LOCK_FIELD = "identity_locked"
MANUAL_IDENTITY_SOURCE = "manual"


def is_identity_locked(entry: Mapping[str, Any] | None) -> bool:
    """Return whether an entry contains a complete, explicit manual lock."""

    return bool(
        isinstance(entry, Mapping)
        and entry.get(IDENTITY_LOCK_FIELD) is True
        and entry.get(IDENTITY_SOURCE_FIELD) == MANUAL_IDENTITY_SOURCE
        and entry.get("song_id") is not None
        and str(entry.get("api_name") or "").strip()
    )


@dataclass(frozen=True, slots=True)
class ManualIdentityResult:
    reference: str
    song_id: Any | None
    api_name: str | None
    locked: bool
    changed: bool


@dataclass(slots=True)
class ManualIdentityDependencies:
    state_reader: Callable[[Path], dict[str, Any]] = read_state_file
    state_writer: Callable[[Path, Mapping[str, Any]], None] = write_state_file
    hasher: Callable[[Path], str] = sha256_file


def _source_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _current_file_hash(
    track: LibraryTrack,
    hasher: Callable[[Path], str],
) -> tuple[str, tuple[int, int, int, int, int]]:
    try:
        before = file_fingerprint(track.path)
    except OSError as exc:
        raise RuntimeError("The selected audio file is no longer available.") from exc
    if track.content_fingerprint is not None and before != track.content_fingerprint:
        raise RuntimeError("The selected audio file changed; refresh Library and choose again.")
    try:
        digest = hasher(track.path)
        after = file_fingerprint(track.path)
    except OSError as exc:
        raise RuntimeError("The selected audio file could not be read.") from exc
    if before != after:
        raise RuntimeError("The selected audio file changed; refresh Library and choose again.")
    if track.content_sha256 is not None and digest != track.content_sha256:
        raise RuntimeError("The selected audio file changed; refresh Library and choose again.")
    return digest, after


def _validate_track_scope(settings: Settings, track: LibraryTrack) -> None:
    try:
        root = Path(settings.music_dir).resolve()
        audio = track.path.resolve(strict=True)
        actual_relative = audio.relative_to(root)
    except (OSError, ValueError) as exc:
        raise RuntimeError("The selected track is outside the configured music library.") from exc
    if (
        Path(track.reference).is_absolute()
        or ".." in Path(track.reference).parts
        or actual_relative != track.relative_path
        or track.reference != str(track.relative_path)
    ):
        raise RuntimeError("The selected track path is no longer valid; refresh Library.")


def set_manual_identity(
    settings: Settings,
    track: LibraryTrack,
    *,
    song_id: Any,
    api_name: str,
    state_file: Path = STATE_FILE,
    dependencies: ManualIdentityDependencies | None = None,
) -> ManualIdentityResult:
    """Atomically bind a user-selected identity to the exact scanned audio."""

    _validate_track_scope(settings, track)
    name = str(api_name or "").strip()
    if song_id is None or not name:
        raise RuntimeError("The selected catalogue result has no usable identity.")
    deps = dependencies or ManualIdentityDependencies()
    state_path = Path(state_file)
    original_bytes = _source_bytes(state_path)
    state = deps.state_reader(state_path)
    if _source_bytes(state_path) != original_bytes:
        raise RuntimeError("Library state changed; refresh Library and choose again.")
    files = state.setdefault("files", {})
    if not isinstance(files, dict):
        raise RuntimeError("Library state records are malformed.")

    audio_hash, fingerprint = _current_file_hash(track, deps.hasher)
    relative_paths = (track.relative_path,)
    _, resolved = resolve_state_entry(files, track.relative_path, relative_paths)
    exact = files.get(track.reference)
    entry = dict(exact) if isinstance(exact, Mapping) else dict(resolved or {})
    before_identity = (
        entry.get("song_id"),
        str(entry.get("api_name") or "").strip() or None,
        is_identity_locked(entry),
    )
    entry.update(
        {
            "sha256": audio_hash,
            "song_id": song_id,
            "api_name": name,
            IDENTITY_SOURCE_FIELD: MANUAL_IDENTITY_SOURCE,
            IDENTITY_LOCK_FIELD: True,
            "updated": now_iso(),
        }
    )
    files[track.reference] = entry

    if _source_bytes(state_path) != original_bytes:
        raise RuntimeError("Library state changed; no catalogue match was saved.")
    try:
        if file_fingerprint(track.path) != fingerprint:
            raise RuntimeError
    except (OSError, RuntimeError) as exc:
        raise RuntimeError("The selected audio file changed; no catalogue match was saved.") from exc

    changed = before_identity != (song_id, name, True)
    if changed:
        deps.state_writer(state_path, state)
    return ManualIdentityResult(track.reference, song_id, name, True, changed)


def unlock_manual_identity(
    settings: Settings,
    track: LibraryTrack,
    *,
    state_file: Path = STATE_FILE,
    dependencies: ManualIdentityDependencies | None = None,
) -> ManualIdentityResult:
    """Clear a manual identity so a later normal Sync may reconsider the track."""

    _validate_track_scope(settings, track)
    deps = dependencies or ManualIdentityDependencies()
    state_path = Path(state_file)
    original_bytes = _source_bytes(state_path)
    state = deps.state_reader(state_path)
    if _source_bytes(state_path) != original_bytes:
        raise RuntimeError("Library state changed; refresh Library and try again.")
    files = state.get("files", {})
    if not isinstance(files, dict):
        raise RuntimeError("Library state records are malformed.")
    _current_file_hash(track, deps.hasher)
    relative_paths = (track.relative_path,)
    _, resolved = resolve_state_entry(files, track.relative_path, relative_paths)
    exact = files.get(track.reference)
    entry = dict(exact) if isinstance(exact, Mapping) else dict(resolved or {})
    if not is_identity_locked(entry):
        return ManualIdentityResult(
            track.reference,
            entry.get("song_id"),
            str(entry.get("api_name") or "").strip() or None,
            False,
            False,
        )
    for field in ("song_id", "api_name", IDENTITY_SOURCE_FIELD, IDENTITY_LOCK_FIELD):
        entry.pop(field, None)
    entry.pop("catalogue_checked_at", None)
    entry["updated"] = now_iso()
    files[track.reference] = entry
    if _source_bytes(state_path) != original_bytes:
        raise RuntimeError("Library state changed; the catalogue match was not unlocked.")
    deps.state_writer(state_path, state)
    return ManualIdentityResult(track.reference, None, None, False, True)

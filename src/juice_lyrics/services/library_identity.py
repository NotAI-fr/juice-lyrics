from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..api.client import search_song_names
from ..backup.manager import now_iso
from ..config.settings import STATE_FILE, Settings
from ..library.matching import choose_candidate, search_title_for
from ..state import file_fingerprint, read_state_file, resolve_state_entry, sha256_file, write_state_file
from .library_status import LibraryTrack
from .manual_identity import IDENTITY_LOCK_FIELD, IDENTITY_SOURCE_FIELD


@dataclass(frozen=True, slots=True)
class IdentityBackfillResult:
    inspected: int
    reused: int
    identified: int
    unknown: int
    failed: int
    errors: tuple[str, ...] = ()
    failed_paths: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        return self.identified > 0


@dataclass(slots=True)
class IdentityBackfillDependencies:
    state_reader: Callable[[Path], dict[str, Any]] = read_state_file
    state_writer: Callable[[Path, Mapping[str, Any]], None] = write_state_file
    searcher: Callable[..., list[dict[str, Any]]] = search_song_names
    matcher: Callable[..., Any] = choose_candidate
    search_title: Callable[[Path], str] = search_title_for
    hasher: Callable[[Path], str] = sha256_file


def _has_identity(entry: Mapping[str, Any] | None) -> bool:
    if not isinstance(entry, Mapping):
        return False
    name = str(entry.get("api_name") or "").strip()
    return entry.get("song_id") is not None and bool(name)


def _state_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def backfill_catalogue_identities(
    settings: Settings,
    tracks: Sequence[LibraryTrack],
    *,
    state_file: Path = STATE_FILE,
    dependencies: IdentityBackfillDependencies | None = None,
) -> IdentityBackfillResult:
    """Persist confident catalogue identities without changing any media files."""

    dependencies = dependencies or IdentityBackfillDependencies()
    state_path = Path(state_file)
    original_state = _state_bytes(state_path)
    state = dependencies.state_reader(state_path)
    if _state_bytes(state_path) != original_state:
        raise RuntimeError("Library state changed during catalogue identification; refresh again.")
    files = state.setdefault("files", {})
    if not isinstance(files, dict):
        files = {}
        state["files"] = files

    relative_paths = tuple(track.relative_path for track in tracks)
    reused = identified = unknown = failed = 0
    errors: list[str] = []
    failed_paths: list[str] = []

    for track in tracks:
        _, existing = resolve_state_entry(files, track.relative_path, relative_paths)
        try:
            if (
                track.content_sha256 is not None
                and track.content_fingerprint is not None
                and file_fingerprint(track.path) == track.content_fingerprint
            ):
                audio_hash = track.content_sha256
            else:
                audio_hash = dependencies.hasher(track.path)
            if _has_identity(existing) and existing.get("sha256") == audio_hash:
                reused += 1
                continue
            query = dependencies.search_title(track.path)
            results = dependencies.searcher(settings, query, refresh=False)
            candidate, _, _, _ = dependencies.matcher(settings, track.path, results, query)
            if not isinstance(candidate, Mapping):
                unknown += 1
                continue
            song_id = candidate.get("id")
            api_name = str(candidate.get("name") or "").strip()
            if song_id is None or not api_name:
                unknown += 1
                continue

            if dependencies.hasher(track.path) != audio_hash:
                raise RuntimeError("Audio changed during catalogue identification; refresh again.")

            reference = str(track.relative_path)
            current = files.get(reference)
            entry = dict(current) if isinstance(current, Mapping) else {}
            # A match recalculated for different audio must not inherit a
            # user lock that belonged to the previous file at this path.
            entry.pop(IDENTITY_SOURCE_FIELD, None)
            entry.pop(IDENTITY_LOCK_FIELD, None)
            entry.update(
                {
                    "sha256": audio_hash,
                    "song_id": song_id,
                    "api_name": api_name,
                    "updated": now_iso(),
                }
            )
            files[reference] = entry
            identified += 1
        except Exception as exc:
            failed += 1
            errors.append(f"{track.filename}: {str(exc) or type(exc).__name__}")
            failed_paths.append(str(track.relative_path))

    if identified:
        if _state_bytes(state_path) != original_state:
            raise RuntimeError("Library state changed during catalogue identification; refresh again.")
        dependencies.state_writer(state_path, state)
    return IdentityBackfillResult(
        inspected=len(tracks),
        reused=reused,
        identified=identified,
        unknown=unknown,
        failed=failed,
        errors=tuple(errors),
        failed_paths=tuple(failed_paths),
    )

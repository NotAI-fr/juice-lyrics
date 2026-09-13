from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..api.client import search_song_names
from ..backup.manager import now_iso
from ..config.settings import STATE_FILE, Settings
from ..library.matching import choose_candidate, search_title_for
from ..state import read_state_file, resolve_state_entry, sha256_file, write_state_file
from .library_status import LibraryTrack


@dataclass(frozen=True, slots=True)
class IdentityBackfillResult:
    inspected: int
    reused: int
    identified: int
    unknown: int
    failed: int
    errors: tuple[str, ...] = ()

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
    state = dependencies.state_reader(state_path)
    files = state.setdefault("files", {})
    if not isinstance(files, dict):
        files = {}
        state["files"] = files

    relative_paths = tuple(track.relative_path for track in tracks)
    reused = identified = unknown = failed = 0
    errors: list[str] = []

    for track in tracks:
        _, existing = resolve_state_entry(files, track.relative_path, relative_paths)
        if _has_identity(existing):
            reused += 1
            continue
        try:
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

            reference = str(track.relative_path)
            current = files.get(reference)
            entry = dict(current) if isinstance(current, Mapping) else {}
            entry.update(
                {
                    "sha256": dependencies.hasher(track.path),
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

    if identified:
        dependencies.state_writer(state_path, state)
    return IdentityBackfillResult(
        inspected=len(tracks),
        reused=reused,
        identified=identified,
        unknown=unknown,
        failed=failed,
        errors=tuple(errors),
    )

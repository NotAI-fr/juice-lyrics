from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..config.settings import BACKUP_DIR, STATE_FILE, Settings, resolve_lyrics_dir
from ..library.scanner import find_mp3s
from ..library.matching import local_duration
from ..lyrics.engine import verify_file
from ..state import sha256_file

LyricsVerifier = Callable[[Path], tuple[bool, str]]
DurationReader = Callable[[Path], float | None]


class LibraryLyricStatus(str, Enum):
    SYNCED = "synced"
    PLAIN = "plain"
    NONE = "none"


class LibraryMatchStatus(str, Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"


class LibraryLrcStatus(str, Enum):
    PRESENT = "present"
    MISSING = "missing"
    NONE = "none"


class LibraryStateStatus(str, Enum):
    CURRENT = "current"
    NEW = "new"
    CHANGED = "changed"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class LibraryTrack:
    """Presentation-neutral read-only information about one local MP3."""

    reference: str
    path: Path
    relative_path: Path
    filename: str
    title: str
    duration_seconds: float | None
    match_status: LibraryMatchStatus
    matched_title: str | None
    lyric_status: LibraryLyricStatus
    lrc_status: LibraryLrcStatus
    lrc_path: Path | None
    state_status: LibraryStateStatus
    warning: str | None = None

    @property
    def needs_attention(self) -> bool:
        return (
            self.match_status is LibraryMatchStatus.UNMATCHED
            or self.lyric_status is LibraryLyricStatus.NONE
            or self.lrc_status is LibraryLrcStatus.MISSING
            or self.state_status is not LibraryStateStatus.CURRENT
            or self.warning is not None
        )


@dataclass(frozen=True, slots=True)
class LibrarySnapshot:
    """Read-only track-level snapshot for frontend library browsing."""

    library_path: Path
    directory_exists: bool
    tracks: tuple[LibraryTrack, ...]
    warnings: tuple[str, ...] = ()

    @property
    def total_track_count(self) -> int:
        return len(self.tracks)

    @property
    def matched_count(self) -> int:
        return sum(track.match_status is LibraryMatchStatus.MATCHED for track in self.tracks)

    @property
    def unmatched_count(self) -> int:
        return self.total_track_count - self.matched_count

    @property
    def synced_count(self) -> int:
        return sum(track.lyric_status is LibraryLyricStatus.SYNCED for track in self.tracks)

    @property
    def plain_count(self) -> int:
        return sum(track.lyric_status is LibraryLyricStatus.PLAIN for track in self.tracks)

    @property
    def no_lyrics_count(self) -> int:
        return sum(track.lyric_status is LibraryLyricStatus.NONE for track in self.tracks)

    @property
    def external_lrc_count(self) -> int:
        return sum(track.lrc_status is LibraryLrcStatus.PRESENT for track in self.tracks)

    @property
    def needs_attention_count(self) -> int:
        return sum(track.needs_attention for track in self.tracks)


@dataclass(frozen=True, slots=True)
class LibraryStatus:
    """Read-only snapshot of the application's MP3 library status."""

    library_path: Path
    track_count: int
    embedded_synced_count: int
    embedded_plain_count: int
    missing_or_invalid_count: int
    rmpc_lrc_count: int
    new_or_changed_count: int
    backup_count: int
    warnings: tuple[str, ...] = ()


def _read_state(path: Path) -> dict[str, Any]:
    """Read state without creating or modifying application data directories."""

    if not path.exists():
        return {"files": {}, "updated": None}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"files": {}, "updated": None}
    return value if isinstance(value, dict) else {"files": {}, "updated": None}


def _read_state_snapshot(path: Path) -> tuple[dict[str, Any], tuple[str, ...]]:
    if not path.exists():
        return {"files": {}, "updated": None}, ()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"files": {}, "updated": None}, (f"Library state could not be read: {exc}",)
    if not isinstance(value, dict):
        return {"files": {}, "updated": None}, ("Library state has an unsupported format.",)
    if not isinstance(value.get("files", {}), dict):
        return {"files": {}, "updated": value.get("updated")}, ("Library state file records are malformed.",)
    return value, ()


def get_library_snapshot(
    settings: Settings,
    *,
    state_file: Path = STATE_FILE,
    verifier: LyricsVerifier = verify_file,
    duration_reader: DurationReader = local_duration,
    hasher: Callable[[Path], str] = sha256_file,
) -> LibrarySnapshot:
    """Inspect local MP3s and state without contacting APIs or writing files."""

    library_path = Path(settings.music_dir)
    if not library_path.is_dir():
        return LibrarySnapshot(
            library_path,
            False,
            (),
            (f"Music directory does not exist: {library_path}",),
        )

    state, warnings = _read_state_snapshot(Path(state_file))
    state_files = state.get("files", {})
    tracks: list[LibraryTrack] = []
    for path in find_mp3s(settings):
        relative_path = path.relative_to(library_path)
        reference = str(relative_path)
        raw_entry = state_files.get(reference)
        entry = raw_entry if isinstance(raw_entry, dict) else None
        track_warnings: list[str] = []

        try:
            valid, verification = verifier(path)
        except Exception as exc:
            valid, verification = False, str(exc) or type(exc).__name__
        if valid and verification.startswith("SYLT"):
            lyric_status = LibraryLyricStatus.SYNCED
        elif valid:
            lyric_status = LibraryLyricStatus.PLAIN
        else:
            lyric_status = LibraryLyricStatus.NONE
            if verification:
                track_warnings.append(verification)

        if raw_entry is None:
            state_status = LibraryStateStatus.NEW
        elif entry is None:
            state_status = LibraryStateStatus.INVALID
            track_warnings.append("Stored library state is malformed.")
        else:
            try:
                state_status = (
                    LibraryStateStatus.CURRENT
                    if entry.get("sha256") == hasher(path)
                    else LibraryStateStatus.CHANGED
                )
            except OSError as exc:
                state_status = LibraryStateStatus.INVALID
                track_warnings.append(f"Could not hash file: {exc}")

        matched_title = None
        if entry is not None:
            candidate_title = entry.get("api_name")
            if candidate_title is not None and str(candidate_title).strip():
                matched_title = str(candidate_title).strip()
        matched = bool(matched_title or (entry is not None and entry.get("song_id") is not None))

        recorded_lrc = (
            Path(str(entry["lrc"]))
            if entry is not None and entry.get("lrc")
            else None
        )
        lrc_path = (
            resolve_lyrics_dir(settings) / f"{path.stem}.lrc"
            if lyric_status is LibraryLyricStatus.SYNCED
            else None
        )
        if lrc_path is None:
            lrc_status = LibraryLrcStatus.NONE
        elif lrc_path.is_file():
            lrc_status = LibraryLrcStatus.PRESENT
        else:
            lrc_status = LibraryLrcStatus.MISSING
            track_warnings.append("External LRC file is missing from the configured directory.")
        if recorded_lrc is not None and lrc_path is not None and recorded_lrc != lrc_path:
            track_warnings.append(
                f"Library state records an LRC outside the configured directory: {recorded_lrc}"
            )

        try:
            duration = duration_reader(path)
        except Exception as exc:
            duration = None
            track_warnings.append(f"Duration unavailable: {exc}")

        tracks.append(
            LibraryTrack(
                reference=reference,
                path=path,
                relative_path=relative_path,
                filename=path.name,
                title=path.stem,
                duration_seconds=duration,
                match_status=(
                    LibraryMatchStatus.MATCHED if matched else LibraryMatchStatus.UNMATCHED
                ),
                matched_title=matched_title,
                lyric_status=lyric_status,
                lrc_status=lrc_status,
                lrc_path=lrc_path,
                state_status=state_status,
                warning=" ".join(track_warnings) or None,
            )
        )
    return LibrarySnapshot(library_path, True, tuple(tracks), warnings)


def get_library_status(
    settings: Settings,
    *,
    state_file: Path = STATE_FILE,
    backup_dir: Path = BACKUP_DIR,
    verifier: LyricsVerifier = verify_file,
) -> LibraryStatus:
    """Calculate a status snapshot without contacting APIs or changing local state."""

    library_path = Path(settings.music_dir)
    files = find_mp3s(settings)
    state = _read_state(Path(state_file))
    state_files = state.get("files", {})
    if not isinstance(state_files, dict):
        state_files = {}

    synced = plain = missing = new_or_changed = lrc = 0
    for path in files:
        valid, message = verifier(path)
        if valid:
            if message.startswith("SYLT"):
                synced += 1
            else:
                plain += 1
        else:
            missing += 1

        relative = str(path.relative_to(library_path))
        entry = state_files.get(relative)
        if not isinstance(entry, dict) or entry.get("sha256") != sha256_file(path):
            new_or_changed += 1
        if (
            valid
            and message.startswith("SYLT")
            and (resolve_lyrics_dir(settings) / f"{path.stem}.lrc").is_file()
        ):
            lrc += 1

    backup_path = Path(backup_dir)
    backup_count = (
        len([path for path in backup_path.iterdir() if path.is_dir()])
        if backup_path.exists()
        else 0
    )
    return LibraryStatus(
        library_path=library_path,
        track_count=len(files),
        embedded_synced_count=synced,
        embedded_plain_count=plain,
        missing_or_invalid_count=missing,
        rmpc_lrc_count=lrc,
        new_or_changed_count=new_or_changed,
        backup_count=backup_count,
    )

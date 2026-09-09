from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..backup.manager import list_backups
from ..config.settings import BACKUP_DIR, STATE_FILE, Settings
from ..library.scanner import find_mp3s
from ..library.matching import local_duration
from ..library.media import (
    AudioMetadata,
    is_tagged_container,
    media_format,
    read_tagged_metadata,
)
from ..lyrics.engine import verify_file
from ..lyrics.sidecar import sidecar_lrc_path
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
    """Presentation-neutral read-only information about one local audio file."""

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
    artist: str | None = None
    album: str | None = None
    media_format: str = "MP3"
    synchronized_source: bool = False

    @property
    def needs_attention(self) -> bool:
        return (
            self.match_status is LibraryMatchStatus.UNMATCHED
            or self.lyric_status is LibraryLyricStatus.NONE
            or self.lrc_status is LibraryLrcStatus.MISSING
            or self.state_status is not LibraryStateStatus.CURRENT
            or self.warning is not None
        )

    @property
    def fully_covered(self) -> bool:
        """Whether format-appropriate embedded lyrics and a synced sidecar are healthy."""

        return (
            self.match_status is LibraryMatchStatus.MATCHED
            and self.state_status is LibraryStateStatus.CURRENT
            and self.synchronized_source
            and self.lrc_status is LibraryLrcStatus.PRESENT
            and self.lyric_status is not LibraryLyricStatus.NONE
            and self.warning is None
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

    @property
    def fully_covered_count(self) -> int:
        return sum(track.fully_covered for track in self.tracks)

    @property
    def plain_only_count(self) -> int:
        return sum(
            track.match_status is LibraryMatchStatus.MATCHED
            and track.lyric_status is LibraryLyricStatus.PLAIN
            and not track.fully_covered
            for track in self.tracks
        )

    @property
    def missing_lyrics_count(self) -> int:
        return sum(
            track.match_status is LibraryMatchStatus.MATCHED
            and track.lyric_status is LibraryLyricStatus.NONE
            for track in self.tracks
        )

    def format_count(self, name: str) -> int:
        return sum(track.media_format.casefold() == name.casefold() for track in self.tracks)


@dataclass(frozen=True, slots=True)
class LibraryStatus:
    """Read-only snapshot of the application's local audio library status."""

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
    metadata_reader: Callable[[Path], AudioMetadata] = read_tagged_metadata,
) -> LibrarySnapshot:
    """Inspect local MP3, FLAC, and M4A files without APIs or writes."""

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
        metadata: AudioMetadata | None = None
        metadata_safe_for_matching = True

        if is_tagged_container(path):
            try:
                metadata = metadata_reader(path)
                missing_metadata = [
                    label
                    for label, value in (("title", metadata.title), ("artist", metadata.artist))
                    if not value
                ]
                if missing_metadata:
                    metadata_safe_for_matching = False
                    track_warnings.append(
                        f"{media_format(path)} metadata is missing {', '.join(missing_metadata)}; track cannot be matched safely."
                    )
            except Exception as exc:
                metadata_safe_for_matching = False
                track_warnings.append(f"{media_format(path)} metadata could not be read: {exc}")

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
        matched = metadata_safe_for_matching and bool(
            matched_title or (entry is not None and entry.get("song_id") is not None)
        )

        expected_synced = bool(
            entry is not None
            and entry.get("lyric_type") in {
                "SYLT",
                "FLAC_LYRICS_SYNCED",
                "M4A_LYRICS_SYNCED",
            }
        )
        adjacent_lrc = sidecar_lrc_path(path)
        lrc_path = (
            adjacent_lrc
            if lyric_status is LibraryLyricStatus.SYNCED
            or expected_synced
            or (is_tagged_container(path) and adjacent_lrc.is_file())
            else None
        )
        if lrc_path is None:
            lrc_status = LibraryLrcStatus.NONE
        elif lrc_path.is_file():
            lrc_status = LibraryLrcStatus.PRESENT
        else:
            lrc_status = LibraryLrcStatus.MISSING
            track_warnings.append("Adjacent external LRC file is missing.")

        try:
            duration = (
                metadata.duration_seconds
                if metadata is not None
                else duration_reader(path)
            )
        except Exception as exc:
            duration = None
            track_warnings.append(f"Duration unavailable: {exc}")

        tracks.append(
            LibraryTrack(
                reference=reference,
                path=path,
                relative_path=relative_path,
                filename=path.name,
                title=metadata.title if metadata is not None and metadata.title else path.stem,
                duration_seconds=duration,
                match_status=(
                    LibraryMatchStatus.MATCHED if matched else LibraryMatchStatus.UNMATCHED
                ),
                matched_title=matched_title,
                lyric_status=lyric_status,
                lrc_status=lrc_status,
                lrc_path=lrc_path,
                state_status=state_status,
                artist=metadata.artist if metadata is not None else None,
                album=metadata.album if metadata is not None else None,
                media_format=media_format(path),
                synchronized_source=expected_synced,
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
        if sidecar_lrc_path(path).is_file() and (
            (valid and message.startswith("SYLT")) or is_tagged_container(path)
        ):
            lrc += 1

    backup_count = len(list_backups(Path(backup_dir)))
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

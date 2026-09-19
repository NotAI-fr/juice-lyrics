from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen.flac import FLAC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4


SUPPORTED_LIBRARY_SUFFIXES = frozenset({".mp3", ".flac", ".m4a"})


class MediaMetadataError(ValueError):
    """Raised when a supported local file lacks safe matching metadata."""


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    title: str | None
    artist: str | None
    album: str | None
    duration_seconds: float | None
    track_number: str | None = None


def is_flac(path: Path) -> bool:
    return Path(path).suffix.casefold() == ".flac"


def is_m4a(path: Path) -> bool:
    return Path(path).suffix.casefold() == ".m4a"


def is_tagged_container(path: Path) -> bool:
    return is_flac(path) or is_m4a(path)


def is_supported_audio(path: Path) -> bool:
    return Path(path).suffix.casefold() in SUPPORTED_LIBRARY_SUFFIXES


def _first(values: object) -> str | None:
    if not isinstance(values, (list, tuple)) or not values:
        return None
    value = str(values[0]).strip()
    return value or None


def _mp3_text(audio: MP3, frame_name: str) -> str | None:
    frame = audio.tags.get(frame_name) if audio.tags is not None else None
    values = getattr(frame, "text", None)
    return _first(values)


def read_mp3_metadata(path: Path) -> AudioMetadata:
    """Read common ID3 metadata without modifying the file."""

    audio = MP3(path)
    return AudioMetadata(
        title=_mp3_text(audio, "TIT2"),
        artist=_mp3_text(audio, "TPE1"),
        album=_mp3_text(audio, "TALB"),
        duration_seconds=float(audio.info.length) if audio.info is not None else None,
        track_number=_mp3_text(audio, "TRCK"),
    )


def read_flac_metadata(path: Path) -> AudioMetadata:
    """Read standard FLAC/Vorbis metadata without modifying the file."""

    audio = FLAC(path)
    return AudioMetadata(
        title=_first(audio.get("title")),
        artist=_first(audio.get("artist")),
        album=_first(audio.get("album")),
        duration_seconds=float(audio.info.length) if audio.info is not None else None,
        track_number=_first(audio.get("tracknumber")),
    )


def read_m4a_metadata(path: Path) -> AudioMetadata:
    """Read standard MP4/M4A atoms without modifying the file."""

    audio = MP4(path)
    track = None
    raw_track = audio.get("trkn")
    if isinstance(raw_track, (list, tuple)) and raw_track:
        pair = raw_track[0]
        if isinstance(pair, (list, tuple)) and pair:
            number = pair[0]
            total = pair[1] if len(pair) > 1 else 0
            if isinstance(number, int) and number > 0:
                track = f"{number}/{total}" if isinstance(total, int) and total > 0 else str(number)
    return AudioMetadata(
        title=_first(audio.get("\xa9nam")),
        artist=_first(audio.get("\xa9ART")),
        album=_first(audio.get("\xa9alb")),
        duration_seconds=float(audio.info.length) if audio.info is not None else None,
        track_number=track,
    )


def read_audio_metadata(path: Path) -> AudioMetadata:
    """Read common metadata from every supported local-library format."""

    if is_flac(path):
        return read_flac_metadata(path)
    if is_m4a(path):
        return read_m4a_metadata(path)
    if Path(path).suffix.casefold() == ".mp3":
        return read_mp3_metadata(path)
    raise MediaMetadataError(f"Unsupported audio format: {path.suffix or '(none)'}")


def read_tagged_metadata(path: Path) -> AudioMetadata:
    if is_flac(path):
        return read_flac_metadata(path)
    if is_m4a(path):
        return read_m4a_metadata(path)
    raise MediaMetadataError(f"Unsupported tagged audio format: {path.suffix or '(none)'}")


def media_format(path: Path) -> str:
    if is_flac(path):
        return "FLAC"
    if is_m4a(path):
        return "M4A"
    return "MP3"


def tagged_matching_title(path: Path) -> str:
    """Return trustworthy native metadata or refuse filename-only guessing."""

    format_name = media_format(path)
    try:
        metadata = read_tagged_metadata(path)
    except Exception as exc:
        raise MediaMetadataError(
            f"{format_name} metadata could not be read; track left unmatched: {exc}"
        ) from exc
    missing = [
        label
        for label, value in (("title", metadata.title), ("artist", metadata.artist))
        if not value
    ]
    if missing:
        raise MediaMetadataError(
            f"{format_name} metadata is missing {', '.join(missing)}; track left unmatched"
        )
    return metadata.title or ""


def flac_matching_title(path: Path) -> str:
    """Backward-compatible FLAC-specific matching helper."""

    return tagged_matching_title(path)

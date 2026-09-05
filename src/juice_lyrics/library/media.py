from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mutagen.flac import FLAC
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


def read_flac_metadata(path: Path) -> AudioMetadata:
    """Read standard FLAC/Vorbis metadata without modifying the file."""

    audio = FLAC(path)
    return AudioMetadata(
        title=_first(audio.get("title")),
        artist=_first(audio.get("artist")),
        album=_first(audio.get("album")),
        duration_seconds=float(audio.info.length) if audio.info is not None else None,
    )


def read_m4a_metadata(path: Path) -> AudioMetadata:
    """Read standard MP4/M4A atoms without modifying the file."""

    audio = MP4(path)
    return AudioMetadata(
        title=_first(audio.get("\xa9nam")),
        artist=_first(audio.get("\xa9ART")),
        album=_first(audio.get("\xa9alb")),
        duration_seconds=float(audio.info.length) if audio.info is not None else None,
    )


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

from __future__ import annotations
from pathlib import Path
from typing import Any

from .media import is_supported_audio


def find_audio_files(target: Path | Any) -> list[Path]:
    """Find supported local audio recursively beneath the configured root."""

    if hasattr(target, "music_dir"):
        music_dir = Path(target.music_dir)
    else:
        music_dir = Path(target)
    if not music_dir.is_dir():
        raise RuntimeError(f"Music directory does not exist: {music_dir}")
    return sorted(
        (path for path in music_dir.rglob("*") if path.is_file() and is_supported_audio(path)),
        key=lambda path: str(path).casefold(),
    )


def find_mp3s(target: Path | Any) -> list[Path]:
    """Backward-compatible name for the MP3, FLAC, and M4A library scanner."""

    return find_audio_files(target)

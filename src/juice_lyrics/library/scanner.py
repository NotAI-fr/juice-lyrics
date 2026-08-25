from __future__ import annotations
from pathlib import Path
from typing import Any
from .matching import local_duration

def find_mp3s(target: Path | Any) -> list[Path]:
    if hasattr(target, "music_dir"):
        music_dir = Path(target.music_dir)
    else:
        music_dir = Path(target)
    if not music_dir.is_dir():
        raise RuntimeError(f"Music directory does not exist: {music_dir}")
    return sorted(music_dir.rglob("*.mp3"), key=lambda p: str(p).lower())

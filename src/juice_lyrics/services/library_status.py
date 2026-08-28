from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..config.settings import BACKUP_DIR, STATE_FILE, Settings
from ..library.scanner import find_mp3s
from ..lyrics.engine import verify_file
from ..state import sha256_file

LyricsVerifier = Callable[[Path], tuple[bool, str]]


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
        if isinstance(entry, dict) and entry.get("lrc") and Path(entry["lrc"]).is_file():
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

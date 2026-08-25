from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..backup.manager import now_iso
from ..lyrics.engine import embed_lyrics, parse_synced_lyrics, verify_file, write_lrc
from ..rmpc.integration import notify_rmpc_index
from ..state import load_state, save_state, sha256_file
from .models import AcquisitionItem


@dataclass(frozen=True, slots=True)
class IntegrationResult:
    """Outcome of integrating an acquired file into the existing media workflow."""

    path: Path
    lyric_type: str = "NONE"
    lrc_path: Path | None = None
    rmpc_notified: int = 0
    message: str = ""


def integrate_downloaded_mp3(
    item: AcquisitionItem,
    *,
    song_fetcher: Callable[[int], dict[str, Any]],
    lyrics_dir: Path | None = None,
    settings: Any | None = None,
    state: dict[str, Any] | None = None,
    notify_rmpc: bool = True,
) -> IntegrationResult:
    """Apply the existing lyrics pipeline to a newly acquired MP3.

    Acquisition remains responsible for obtaining the file. This layer handles
    the project's established lyrics embedding, rmpc LRC generation, rmpc notification,
    and library state.json synchronization after a successful MP3 download.
    Non-MP3 resources are deliberately left untouched.
    """

    path = item.destination
    if path.suffix.lower() != ".mp3":
        return IntegrationResult(path=path, message="not an MP3; lyrics integration skipped")

    try:
        song_id = int(item.identifier)
    except (TypeError, ValueError):
        raise RuntimeError(f"Cannot integrate {path.name}: API song id is unavailable")

    song = song_fetcher(song_id)
    synced = parse_synced_lyrics(str(song.get("synced_lyrics") or ""))
    plain = str(song.get("lyrics") or "")

    lrc_path: Path | None = None
    rmpc_notified = 0

    if not synced and not plain.strip():
        lyric_type = "NONE"
        verification = "no lyrics available"
    else:
        lyric_type = embed_lyrics(path, synced, plain)
        valid, verification = verify_file(path)
        if not valid:
            raise RuntimeError(f"Lyrics were embedded but verification failed: {verification}")

        if synced and lyrics_dir is not None:
            lrc_path = write_lrc(path, synced, song, Path(lyrics_dir))
            if notify_rmpc:
                try:
                    rmpc_notified = notify_rmpc_index([lrc_path])
                except Exception:
                    rmpc_notified = 0

    # Synchronize library state.json so future `sync` operations recognize this file
    try:
        current_state = load_state() if state is None else state
        music_dir = getattr(settings, "music_dir", None) if settings is not None else None
        if music_dir is not None:
            try:
                relative = str(path.relative_to(Path(music_dir)))
            except ValueError:
                relative = str(path)
        else:
            relative = str(path)

        current_state.setdefault("files", {})[relative] = {
            "sha256": sha256_file(path),
            "song_id": song_id,
            "api_name": song.get("name"),
            "lyric_type": lyric_type,
            "lrc": str(lrc_path) if lrc_path else None,
            "updated": now_iso(),
        }
        if state is None:
            save_state(current_state)
    except Exception as exc:
        raise RuntimeError(f"Failed to synchronize library state: {exc}") from exc

    detail = f"{lyric_type}; {verification}"
    if lrc_path:
        detail += f"; LRC: {lrc_path}"
    if rmpc_notified:
        detail += f"; rmpc notified: {rmpc_notified}"
    return IntegrationResult(
        path=path,
        lyric_type=lyric_type,
        lrc_path=lrc_path,
        rmpc_notified=rmpc_notified,
        message=detail,
    )


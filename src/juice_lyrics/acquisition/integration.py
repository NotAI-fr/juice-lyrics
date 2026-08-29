from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..backup.manager import (
    backup_file,
    make_backup_root,
    now_iso,
    restore_file,
    write_manifest,
)
from ..lyrics.engine import embed_lyrics, parse_synced_lyrics, verify_file, write_lrc
from ..rmpc.integration import notify_rmpc_index
from ..state import load_state, save_state, sha256_file
from .models import AcquisitionFailureStage, AcquisitionItem, AcquisitionPostProcessingError


@dataclass(frozen=True, slots=True)
class IntegrationResult:
    """Outcome of integrating an acquired file into the existing media workflow."""

    path: Path
    lyric_type: str = "NONE"
    lrc_path: Path | None = None
    rmpc_notified: int = 0
    message: str = ""
    backup_path: Path | None = None


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
    backup_path: Path | None = None
    rmpc_notified = 0
    rmpc_warning: str | None = None

    if not synced and not plain.strip():
        lyric_type = "NONE"
        verification = "no lyrics available"
    else:
        music_dir = getattr(settings, "music_dir", None) if settings is not None else None
        backup_base = Path(music_dir) if music_dir is not None else path.parent
        try:
            path.relative_to(backup_base)
        except ValueError:
            backup_base = path.parent

        try:
            original_hash = sha256_file(path)
            backup_root = make_backup_root()
            backup_path = backup_file(path, backup_root, backup_base)
            write_manifest(
                backup_root,
                [{
                    "file": str(path),
                    "sha256_before": original_hash,
                    "purpose": "acquisition lyric post-processing",
                }],
            )
        except Exception as exc:
            raise AcquisitionPostProcessingError(
                AcquisitionFailureStage.LYRICS,
                f"Audio download completed, but lyric backup failed before metadata modification: {exc}. "
                "The downloaded file was not modified."
            ) from exc

        try:
            lyric_type = embed_lyrics(path, synced, plain)
            valid, verification = verify_file(path)
            if not valid:
                raise RuntimeError(f"verification failed: {verification}")
        except Exception as exc:
            try:
                restore_file(backup_path, path)
            except Exception as restore_exc:
                raise AcquisitionPostProcessingError(
                    AcquisitionFailureStage.LYRICS,
                    f"Audio download completed, but lyric post-processing failed: {exc}. "
                    f"Automatic restore also failed: {restore_exc}. "
                    f"The pristine backup remains at {backup_path}; the downloaded file may be partially modified.",
                    reuse_finalized_file=False,
                ) from restore_exc
            raise AcquisitionPostProcessingError(
                AcquisitionFailureStage.LYRICS,
                f"Audio download completed, but lyric post-processing failed: {exc}. "
                "The original downloaded file was restored from backup; the failed item remains retryable."
            ) from exc

        if synced and lyrics_dir is not None:
            try:
                lrc_path = write_lrc(path, synced, song, Path(lyrics_dir))
            except Exception as exc:
                raise AcquisitionPostProcessingError(
                    AcquisitionFailureStage.LRC,
                    f"Audio download and lyric processing succeeded, but LRC integration failed: {exc}. "
                    "The verified MP3 and pristine backup were retained; the failed item remains retryable."
                ) from exc
            if notify_rmpc:
                try:
                    rmpc_notified = notify_rmpc_index([lrc_path])
                except Exception as exc:
                    rmpc_notified = 0
                    rmpc_warning = str(exc)

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
        processed = " and lyric processing succeeded" if lyric_type != "NONE" else ""
        raise AcquisitionPostProcessingError(
            AcquisitionFailureStage.STATE,
            f"Audio download{processed}, but state update failed "
            f"(Failed to synchronize library state): {exc}. "
            "The finalized MP3 was retained; the failed item remains retryable."
        ) from exc

    detail = f"{lyric_type}; {verification}"
    if lrc_path:
        detail += f"; LRC: {lrc_path}"
    if rmpc_notified:
        detail += f"; rmpc notified: {rmpc_notified}"
    if rmpc_warning:
        detail += f"; rmpc notification failed: {rmpc_warning}"
    return IntegrationResult(
        path=path,
        lyric_type=lyric_type,
        backup_path=backup_path,
        lrc_path=lrc_path,
        rmpc_notified=rmpc_notified,
        message=detail,
    )

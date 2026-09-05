from __future__ import annotations

import json
import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config.settings import BACKUP_DIR, DATA_DIR

BACKUP_RETENTION_COUNT = 10
BACKUP_AUDIO_SUFFIXES = frozenset({".mp3", ".flac", ".m4a"})

logger = logging.getLogger(__name__)


def _backup_audio_files(root: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in BACKUP_AUDIO_SUFFIXES
    )


@dataclass(frozen=True, slots=True)
class BackupRecord:
    """A completed backup with an authoritative manifest timestamp."""

    path: Path
    created_at: datetime


@dataclass(frozen=True, slots=True)
class BackupPruneResult:
    """Conservative result of applying rolling backup retention."""

    removed: tuple[Path, ...] = ()
    error: str | None = None


def ensure_data_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_backup_root() -> Path:
    ensure_data_dirs()
    root = BACKUP_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    root.mkdir(parents=True, exist_ok=True)
    return root


def backup_file(path: Path, root: Path, base: Path) -> Path:
    destination = root / path.relative_to(base)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return destination


def restore_file(backup: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(backup, destination)


def _manifest_created_at(root: Path) -> datetime | None:
    """Return a completed backup's timestamp without trusting its filename."""

    if not root.is_dir() or root.is_symlink():
        return None
    try:
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        raw_created = manifest.get("created") if isinstance(manifest, dict) else None
        if not isinstance(raw_created, str):
            return None
        files = manifest.get("files")
        if not (isinstance(files, list) and files) and not _backup_audio_files(root):
            return None
        created_at = datetime.fromisoformat(raw_created.replace("Z", "+00:00"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(timezone.utc)


def list_backups(backup_dir: Path = BACKUP_DIR) -> tuple[BackupRecord, ...]:
    """List completed backups oldest-first without modifying the directory."""

    directory = Path(backup_dir)
    if not directory.is_dir():
        return ()
    try:
        children = tuple(directory.iterdir())
    except OSError:
        return ()
    records: list[BackupRecord] = []
    for child in children:
        created_at = _manifest_created_at(child)
        if created_at is not None:
            records.append(BackupRecord(child, created_at))
    return tuple(sorted(records, key=lambda record: (record.created_at, record.path.name)))


def prune_backup_history(
    backup_dir: Path = BACKUP_DIR,
    *,
    keep: int = BACKUP_RETENTION_COUNT,
    protected: Path | None = None,
    remover: Callable[[Path], None] = shutil.rmtree,
) -> BackupPruneResult:
    """Keep the newest completed backups and stop on the first prune failure."""

    if keep < 0:
        raise ValueError("keep must not be negative")
    records = list_backups(Path(backup_dir))
    newest = {record.path for record in records[-keep:]} if keep else set()
    if protected is not None:
        newest.add(Path(protected))
    candidates = [record.path for record in records if record.path not in newest]

    removed: list[Path] = []
    for candidate in candidates:
        try:
            remover(candidate)
        except Exception as exc:
            return BackupPruneResult(
                tuple(removed),
                f"could not remove old backup {candidate}: {exc}",
            )
        removed.append(candidate)
    return BackupPruneResult(tuple(removed))


def write_manifest(root: Path, entries: list[dict[str, Any]]) -> None:
    """Finalize a backup, then apply retention without invalidating that backup."""

    (root / "manifest.json").write_text(
        json.dumps(
            {"created": now_iso(), "files": entries},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    # Some batch failures occur after the pristine audio was copied but before
    # its manifest entry was assembled.  That copy is still a recoverable
    # backup.  Conversely, an empty root after every copy failed must not
    # trigger deletion of older backups.
    try:
        has_backup_file = bool(entries) or bool(_backup_audio_files(root))
    except OSError as exc:
        logger.warning("Backup created, but retention cleanup could not inspect it: %s", exc)
        return
    if not has_backup_file:
        return
    result = prune_backup_history(root.parent, protected=root)
    if result.error:
        logger.warning("Backup created, but retention cleanup failed: %s", result.error)


def restore_backup(root: Path, base: Path) -> int:
    restored = 0
    for source in _backup_audio_files(root):
        destination = base / source.relative_to(root)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        restored += 1
    return restored

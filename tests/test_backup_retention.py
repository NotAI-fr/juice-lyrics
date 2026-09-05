import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.backup import manager
from juice_lyrics.config.settings import Settings
from juice_lyrics.services.library_status import get_library_status


def _completed_backup(
    backup_dir: Path,
    name: str,
    created_at: datetime,
    *,
    audio: bytes = b"original audio",
) -> Path:
    root = backup_dir / name
    root.mkdir(parents=True)
    (root / "Track.mp3").write_bytes(audio)
    (root / "manifest.json").write_text(
        json.dumps({"created": created_at.isoformat(), "files": [{"file": "Track.mp3"}]}),
        encoding="utf-8",
    )
    return root


def _backup_set(backup_dir: Path, count: int) -> list[Path]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return [
        _completed_backup(
            backup_dir,
            f"backup-{index:02d}",
            start + timedelta(days=index),
        )
        for index in range(count)
    ]


@pytest.mark.parametrize("count", [9, 10])
def test_retention_does_nothing_at_or_below_limit(tmp_path, count):
    backup_dir = tmp_path / "backups"
    roots = _backup_set(backup_dir, count)

    result = manager.prune_backup_history(backup_dir)

    assert result.removed == ()
    assert result.error is None
    assert all(root.is_dir() for root in roots)


def test_successful_eleventh_backup_removes_only_oldest(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    roots = _backup_set(backup_dir, 10)
    newest = backup_dir / "newly-created"
    newest.mkdir()
    monkeypatch.setattr(
        manager,
        "now_iso",
        lambda: datetime(2026, 2, 1, tzinfo=timezone.utc).isoformat(),
    )

    manager.write_manifest(newest, [{"file": "new.mp3"}])

    assert not roots[0].exists()
    assert all(root.exists() for root in roots[1:])
    assert newest.exists()
    assert len(manager.list_backups(backup_dir)) == 10


def test_repeated_successful_backups_never_retain_more_than_ten(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    created: list[Path] = []
    for index in range(15):
        root = backup_dir / f"run-{index:02d}"
        root.mkdir(parents=True)
        created.append(root)
        monkeypatch.setattr(
            manager,
            "now_iso",
            lambda index=index: (start + timedelta(days=index)).isoformat(),
        )
        manager.write_manifest(root, [{"file": f"{index}.mp3"}])
        assert len(manager.list_backups(backup_dir)) <= 10

    assert all(not root.exists() for root in created[:5])
    assert all(root.exists() for root in created[5:])
    assert created[-1].exists()


def test_manifest_timestamp_controls_order_and_unrelated_entries_are_ignored(tmp_path):
    backup_dir = tmp_path / "backups"
    newer = _completed_backup(
        backup_dir,
        "0000-lexically-first",
        datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    oldest = _completed_backup(
        backup_dir,
        "9999-lexically-last",
        datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    (backup_dir / "notes.txt").write_text("leave me", encoding="utf-8")
    (backup_dir / "unrelated-directory").mkdir()
    (backup_dir / "broken-backup").mkdir()
    (backup_dir / "broken-backup" / "manifest.json").write_text("not json", encoding="utf-8")

    result = manager.prune_backup_history(backup_dir, keep=1)

    assert result.removed == (oldest,)
    assert newer.exists()
    assert (backup_dir / "notes.txt").exists()
    assert (backup_dir / "unrelated-directory").exists()
    assert (backup_dir / "broken-backup").exists()


def test_manifest_failure_does_not_start_pruning(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    roots = _backup_set(backup_dir, 11)
    prune_called = False

    def unexpected_prune(*args, **kwargs):
        nonlocal prune_called
        prune_called = True
        raise AssertionError("pruning started")

    monkeypatch.setattr(manager, "prune_backup_history", unexpected_prune)
    missing_root = backup_dir / "backup-that-was-not-created"

    with pytest.raises(OSError):
        manager.write_manifest(missing_root, [])

    assert not prune_called
    assert all(root.exists() for root in roots)


def test_empty_backup_after_copy_failure_does_not_start_pruning(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    roots = _backup_set(backup_dir, 11)
    empty_root = backup_dir / "empty-failed-run"
    empty_root.mkdir()
    prune_called = False

    def unexpected_prune(*args, **kwargs):
        nonlocal prune_called
        prune_called = True
        raise AssertionError("pruning started")

    monkeypatch.setattr(manager, "prune_backup_history", unexpected_prune)

    manager.write_manifest(empty_root, [])

    assert not prune_called
    assert all(root.exists() for root in roots)


def test_prune_failure_stops_cleanup_and_preserves_new_backup(tmp_path):
    backup_dir = tmp_path / "backups"
    roots = _backup_set(backup_dir, 11)
    attempted: list[Path] = []

    def fail(candidate: Path) -> None:
        attempted.append(candidate)
        raise PermissionError("read only")

    result = manager.prune_backup_history(
        backup_dir,
        keep=10,
        protected=roots[-1],
        remover=fail,
    )

    assert attempted == [roots[0]]
    assert result.removed == ()
    assert "read only" in (result.error or "")
    assert all(root.exists() for root in roots)
    assert roots[-1].exists()


def test_cleanup_failure_is_logged_without_failing_completed_backup(tmp_path, monkeypatch, caplog):
    root = tmp_path / "backups" / "new"
    root.mkdir(parents=True)
    monkeypatch.setattr(
        manager,
        "prune_backup_history",
        lambda *args, **kwargs: manager.BackupPruneResult(error="permission denied"),
    )

    manager.write_manifest(root, [{"file": "Track.mp3"}])

    assert (root / "manifest.json").is_file()
    assert "Backup created, but retention cleanup failed" in caplog.text


def test_read_only_status_counts_backups_without_pruning(tmp_path):
    backup_dir = tmp_path / "backups"
    roots = _backup_set(backup_dir, 11)
    music_dir = tmp_path / "music"
    music_dir.mkdir()

    status = get_library_status(
        Settings(music_dir=music_dir),
        state_file=tmp_path / "missing-state.json",
        backup_dir=backup_dir,
    )

    assert status.backup_count == 11
    assert all(root.exists() for root in roots)


def test_retained_backup_can_still_be_restored(tmp_path):
    backup_dir = tmp_path / "backups"
    roots = _backup_set(backup_dir, 11)
    result = manager.prune_backup_history(backup_dir)
    target = tmp_path / "restored"

    restored = manager.restore_backup(roots[-1], target)

    assert result.removed == (roots[0],)
    assert restored == 1
    assert (target / "Track.mp3").read_bytes() == b"original audio"


def test_completed_flac_backup_is_valid_for_retention_and_restore(tmp_path):
    backup_dir = tmp_path / "backups"
    roots = _backup_set(backup_dir, 10)
    newest = backup_dir / "flac-backup"
    (newest / "Nested").mkdir(parents=True)
    (newest / "Nested" / "Track.FLAC").write_bytes(b"flac backup")
    (newest / "manifest.json").write_text(
        json.dumps({"created": "2026-02-01T00:00:00+00:00", "files": []}),
        encoding="utf-8",
    )

    result = manager.prune_backup_history(backup_dir)
    target = tmp_path / "restored"

    assert result.removed == (roots[0],)
    assert len(manager.list_backups(backup_dir)) == 10
    assert manager.restore_backup(newest, target) == 1
    assert (target / "Nested" / "Track.FLAC").read_bytes() == b"flac backup"


def test_completed_m4a_backup_uses_existing_retention_policy(tmp_path):
    backup_dir = tmp_path / "backups"
    roots = _backup_set(backup_dir, 10)
    newest = backup_dir / "m4a-backup"
    newest.mkdir(parents=True)
    (newest / "Track.M4A").write_bytes(b"m4a backup")
    (newest / "manifest.json").write_text(
        json.dumps({"created": "2026-02-01T00:00:00+00:00", "files": []}),
        encoding="utf-8",
    )

    result = manager.prune_backup_history(backup_dir)

    assert result.removed == (roots[0],)
    assert len(manager.list_backups(backup_dir)) == 10
    assert newest.is_dir()

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.services.library_status import LibraryStatus, get_library_status
from juice_lyrics.state import sha256_file


def test_empty_library_status_is_read_only(tmp_path):
    library = tmp_path / "music"
    library.mkdir()
    state_file = tmp_path / "missing" / "state.json"
    backup_dir = tmp_path / "missing" / "backups"

    status = get_library_status(
        Settings(music_dir=library),
        state_file=state_file,
        backup_dir=backup_dir,
    )

    assert status == LibraryStatus(
        library_path=library,
        track_count=0,
        embedded_synced_count=0,
        embedded_plain_count=0,
        missing_or_invalid_count=0,
        rmpc_lrc_count=0,
        new_or_changed_count=0,
        backup_count=0,
    )
    assert not state_file.parent.exists()


def test_library_status_counts_lyrics_changes_lrc_and_backups(tmp_path):
    library = tmp_path / "music"
    library.mkdir()
    synced = library / "synced.mp3"
    plain = library / "plain.mp3"
    missing = library / "missing.mp3"
    changed = library / "changed.mp3"
    for path in (synced, plain, missing, changed):
        path.write_bytes(path.stem.encode())

    lrc = tmp_path / "lyrics" / "synced.lrc"
    lrc.parent.mkdir()
    lrc.write_text("[00:01.00] line\n", encoding="utf-8")
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "files": {
                    "synced.mp3": {"sha256": sha256_file(synced), "lrc": str(lrc)},
                    "plain.mp3": {"sha256": sha256_file(plain), "lrc": None},
                    "missing.mp3": {"sha256": sha256_file(missing), "lrc": None},
                    "changed.mp3": {"sha256": "old-hash", "lrc": None},
                }
            }
        ),
        encoding="utf-8",
    )
    backup_dir = tmp_path / "backups"
    (backup_dir / "one").mkdir(parents=True)
    (backup_dir / "two").mkdir()
    (backup_dir / "not-a-backup.txt").write_text("ignored", encoding="utf-8")

    results = {
        synced: (True, "SYLT (2 synced lines)"),
        plain: (True, "USLT (ordinary lyrics)"),
        missing: (False, "no managed lyrics frame"),
        changed: (True, "USLT (ordinary lyrics)"),
    }
    status = get_library_status(
        Settings(music_dir=library),
        state_file=state_file,
        backup_dir=backup_dir,
        verifier=results.__getitem__,
    )

    assert status.library_path == library
    assert status.track_count == 4
    assert status.embedded_synced_count == 1
    assert status.embedded_plain_count == 2
    assert status.missing_or_invalid_count == 1
    assert status.rmpc_lrc_count == 1
    assert status.new_or_changed_count == 1
    assert status.backup_count == 2
    assert status.warnings == ()


def test_library_status_marks_new_file_for_sync_and_ignores_non_mp3(tmp_path):
    mp3 = tmp_path / "new.mp3"
    mp3.write_bytes(b"audio")
    (tmp_path / "future.flac").write_bytes(b"audio")

    status = get_library_status(
        Settings(music_dir=tmp_path),
        state_file=tmp_path / "absent.json",
        backup_dir=tmp_path / "absent-backups",
        verifier=lambda path: (False, "invalid"),
    )

    assert status.track_count == 1
    assert status.missing_or_invalid_count == 1
    assert status.new_or_changed_count == 1


def test_library_status_does_not_contact_api(tmp_path, monkeypatch):
    import juice_lyrics.api.client as api_client

    monkeypatch.setattr(
        api_client,
        "api_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API called")),
    )

    status = get_library_status(
        Settings(music_dir=tmp_path),
        state_file=tmp_path / "state.json",
        backup_dir=tmp_path / "backups",
    )

    assert status.track_count == 0

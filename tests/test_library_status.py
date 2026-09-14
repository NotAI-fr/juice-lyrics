import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.library.media import AudioMetadata
from juice_lyrics.services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibraryStateStatus,
    LibraryStatus,
    get_library_snapshot,
    get_library_status,
)
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

    lrc = synced.with_suffix(".lrc")
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
    for index, name in enumerate(("one", "two"), start=1):
        root = backup_dir / name
        root.mkdir(parents=True)
        (root / "Track.mp3").write_bytes(b"backup")
        (root / "manifest.json").write_text(
            json.dumps({"created": f"2026-01-0{index}T00:00:00+00:00", "files": []}),
            encoding="utf-8",
        )
    (backup_dir / "not-a-backup.txt").write_text("ignored", encoding="utf-8")

    results = {
        synced: (True, "SYLT (2 synced lines)"),
        plain: (True, "USLT (ordinary lyrics)"),
        missing: (False, "no managed lyrics frame"),
        changed: (True, "USLT (ordinary lyrics)"),
    }
    status = get_library_status(
        Settings(music_dir=library, lyrics_dir=tmp_path / "ignored-central"),
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


def test_library_status_marks_new_supported_audio_files_for_sync(tmp_path):
    mp3 = tmp_path / "new.mp3"
    mp3.write_bytes(b"audio")
    (tmp_path / "future.flac").write_bytes(b"audio")

    status = get_library_status(
        Settings(music_dir=tmp_path),
        state_file=tmp_path / "absent.json",
        backup_dir=tmp_path / "absent-backups",
        verifier=lambda path: (False, "invalid"),
    )

    assert status.track_count == 2
    assert status.missing_or_invalid_count == 2
    assert status.new_or_changed_count == 2


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


def test_track_snapshot_exposes_typed_local_state_without_api(tmp_path, monkeypatch):
    import juice_lyrics.api.client as api_client

    library = tmp_path / "music"
    library.mkdir()
    synced = library / "A Synced.mp3"
    plain = library / "B Plain.mp3"
    missing = library / "C Missing.mp3"
    for path in (synced, plain, missing):
        path.write_bytes(path.name.encode())
    lrc = synced.with_suffix(".lrc")
    lrc.write_text("[00:01.00] line\n", encoding="utf-8")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({
        "files": {
            "A Synced.mp3": {
                "sha256": sha256_file(synced),
                "song_id": 1,
                "api_name": "A Synced (v1)",
                "lrc": str(lrc),
            },
            "B Plain.mp3": {
                "sha256": "old",
                "song_id": 2,
                "api_name": "B Plain",
                "lrc": None,
            },
        }
    }), encoding="utf-8")
    verification = {
        synced: (True, "SYLT (2 synced lines)"),
        plain: (True, "USLT (ordinary lyrics)"),
        missing: (False, "no managed lyrics frame"),
    }
    monkeypatch.setattr(
        api_client,
        "api_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API called")),
    )

    snapshot = get_library_snapshot(
        Settings(music_dir=library, lyrics_dir=tmp_path / "ignored-central"),
        state_file=state_file,
        verifier=verification.__getitem__,
        duration_reader=lambda path: {synced: 180.0, plain: 181.5, missing: None}[path],
    )

    assert [track.filename for track in snapshot.tracks] == [
        "A Synced.mp3", "B Plain.mp3", "C Missing.mp3"
    ]
    assert snapshot.total_track_count == 3
    assert snapshot.matched_count == 1
    assert snapshot.unmatched_count == 2
    assert snapshot.synced_count == 1
    assert snapshot.plain_count == 1
    assert snapshot.no_lyrics_count == 1
    assert snapshot.external_lrc_count == 1
    assert snapshot.needs_attention_count == 1
    assert snapshot.tracks[0].match_status is LibraryMatchStatus.MATCHED
    assert snapshot.tracks[0].lyric_status is LibraryLyricStatus.SYNCED
    assert snapshot.tracks[0].lrc_status is LibraryLrcStatus.PRESENT
    assert snapshot.tracks[0].state_status is LibraryStateStatus.CURRENT
    assert snapshot.tracks[1].state_status is LibraryStateStatus.CHANGED
    assert snapshot.tracks[1].match_status is LibraryMatchStatus.UNMATCHED
    assert snapshot.tracks[1].matched_title is None
    assert snapshot.tracks[2].match_status is LibraryMatchStatus.UNMATCHED
    assert snapshot.tracks[2].lyric_status is LibraryLyricStatus.NONE
    assert snapshot.tracks[2].needs_attention is True


@pytest.mark.parametrize(
    ("suffix", "verification", "format_name", "lyric_status"),
    [
        (".mp3", "SYLT (61 synced lines)", "MP3", LibraryLyricStatus.SYNCED),
        (".flac", "FLAC LYRICS (500 characters)", "FLAC", LibraryLyricStatus.PLAIN),
        (".m4a", "M4A LYRICS (500 characters)", "M4A", LibraryLyricStatus.PLAIN),
    ],
)
def test_unmatched_track_with_format_appropriate_lyrics_is_fully_covered(
    tmp_path, suffix, verification, format_name, lyric_status
):
    track = tmp_path / f"Bandit{suffix}"
    track.write_bytes(b"audio")
    track.with_suffix(".lrc").write_text(
        "[ar:Juice WRLD]\n[00:05.77] Oh-oh\n[00:10.45] Yeah\n",
        encoding="utf-8",
    )

    snapshot = get_library_snapshot(
        Settings(music_dir=tmp_path),
        state_file=tmp_path / "missing-state.json",
        verifier=lambda path: (True, verification),
        duration_reader=lambda path: 189.32,
        metadata_reader=lambda path: AudioMetadata(
            "Bandit (with YoungBoy Never Broke Again)",
            "Juice WRLD, YoungBoy Never Broke Again",
            "Death Race For Love (Bonus Track Version)",
            189.32,
        ),
    )

    item = snapshot.tracks[0]
    assert item.media_format == format_name
    assert item.match_status is LibraryMatchStatus.UNMATCHED
    assert item.lyric_status is lyric_status
    assert item.lrc_status is LibraryLrcStatus.PRESENT
    assert item.fully_covered is True
    assert item.needs_attention is False
    assert snapshot.fully_covered_count == 1
    assert snapshot.needs_attention_count == 0


def test_existing_untimed_sidecar_is_invalid_and_needs_attention(tmp_path):
    track = tmp_path / "Bandit.flac"
    track.write_bytes(b"audio")
    track.with_suffix(".lrc").write_text(
        "[ar:Juice WRLD]\nThese are only plain lyrics.\n",
        encoding="utf-8",
    )
    snapshot = get_library_snapshot(
        Settings(music_dir=tmp_path),
        state_file=tmp_path / "missing-state.json",
        verifier=lambda path: (True, "FLAC LYRICS (30 characters)"),
        metadata_reader=lambda path: AudioMetadata("Bandit", "Juice WRLD", None, 189.32),
    )

    item = snapshot.tracks[0]
    assert item.lrc_status is LibraryLrcStatus.INVALID
    assert item.fully_covered is False
    assert item.needs_attention is True
    assert "no timestamped lyric lines" in (item.warning or "")


def test_matched_track_with_expected_synced_lyrics_and_missing_sidecar_needs_attention(tmp_path):
    track = tmp_path / "Bandit.flac"
    track.write_bytes(b"audio")
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "files": {
                    "Bandit.flac": {
                        "sha256": sha256_file(track),
                        "song_id": 1,
                        "api_name": "Bandit",
                        "lyric_type": "FLAC_LYRICS_SYNCED",
                        "lrc": str(track.with_suffix(".lrc")),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    snapshot = get_library_snapshot(
        Settings(music_dir=tmp_path),
        state_file=state_file,
        verifier=lambda path: (True, "FLAC LYRICS (500 characters)"),
        metadata_reader=lambda path: AudioMetadata("Bandit", "Juice WRLD", None, 189.32),
    )

    item = snapshot.tracks[0]
    assert item.match_status is LibraryMatchStatus.MATCHED
    assert item.lyric_status is LibraryLyricStatus.PLAIN
    assert item.lrc_status is LibraryLrcStatus.MISSING
    assert item.fully_covered is False
    assert item.needs_attention is True


def test_library_snapshot_uses_adjacent_sidecar_not_config_or_historical_state_path(tmp_path):
    library = tmp_path / "Music" / "Juice WRLD" / "Unreleased"
    library.mkdir(parents=True)
    track = library / "Rental.mp3"
    track.write_bytes(b"audio")
    legacy = tmp_path / "Music" / "Juice WRLD" / "lyrics" / "Rental.lrc"
    configured = tmp_path / "Music" / "lyrics"
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({
        "files": {
            "Rental.mp3": {
                "sha256": sha256_file(track),
                "song_id": 1,
                "api_name": "Rental",
                "lrc": str(legacy),
            }
        }
    }), encoding="utf-8")

    snapshot = get_library_snapshot(
        Settings(music_dir=library, lyrics_dir=configured),
        state_file=state_file,
        verifier=lambda path: (True, "SYLT (1 synced line)"),
        duration_reader=lambda path: 180.0,
    )

    item = snapshot.tracks[0]
    assert item.lrc_path == track.with_suffix(".lrc")
    assert item.lrc_status is LibraryLrcStatus.MISSING
    assert "Adjacent external LRC file is missing" in (item.warning or "")
    assert not legacy.parent.exists()
    assert not configured.exists()


def test_library_status_ignores_unrelated_centralized_lrc(tmp_path):
    library = tmp_path / "music"
    library.mkdir()
    track = library / "Rental.mp3"
    track.write_bytes(b"audio")
    central = tmp_path / "lyrics"
    central.mkdir()
    (central / "Rental.lrc").write_text("[00:01.00] old\n", encoding="utf-8")

    status = get_library_status(
        Settings(music_dir=library, lyrics_dir=central, lyrics_dir_explicit=True),
        state_file=tmp_path / "missing-state.json",
        backup_dir=tmp_path / "missing-backups",
        verifier=lambda path: (True, "SYLT (1 synced line)"),
    )

    assert status.rmpc_lrc_count == 0
    assert not track.with_suffix(".lrc").exists()


def test_unambiguous_historical_basename_identity_remains_readable(tmp_path):
    library = tmp_path / "music"
    track = library / "Unreleased" / "24 Hours.mp3"
    track.parent.mkdir(parents=True)
    track.write_bytes(b"audio")
    state_file = tmp_path / "state.json"
    state_file.write_text(
        json.dumps(
            {
                "files": {
                    "24 Hours.mp3": {
                        "sha256": sha256_file(track),
                        "song_id": 94760,
                        "api_name": "24 Hours",
                        "lyric_type": "USLT",
                        "lrc": None,
                    },
                    "/tmp/pytest-of-someone/pytest-2/test_case/Ghost.flac": {
                        "song_id": 1,
                        "api_name": "Ghost",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    snapshot = get_library_snapshot(
        Settings(music_dir=library),
        state_file=state_file,
        verifier=lambda path: (True, "USLT (ordinary lyrics)"),
        duration_reader=lambda path: 180.0,
    )

    item = snapshot.tracks[0]
    assert item.reference == "Unreleased/24 Hours.mp3"
    assert item.match_status is LibraryMatchStatus.MATCHED
    assert item.matched_title == "24 Hours"
    assert snapshot.unmatched_count == 0


def test_track_snapshot_handles_missing_library_and_malformed_state(tmp_path):
    missing = tmp_path / "missing"
    snapshot = get_library_snapshot(Settings(music_dir=missing), state_file=tmp_path / "state.json")
    assert snapshot.directory_exists is False
    assert snapshot.tracks == ()
    assert "does not exist" in snapshot.warnings[0]

    library = tmp_path / "music"
    library.mkdir()
    track = library / "Track.mp3"
    track.write_bytes(b"audio")
    state_file = tmp_path / "bad-state.json"
    state_file.write_text("not-json", encoding="utf-8")
    snapshot = get_library_snapshot(
        Settings(music_dir=library),
        state_file=state_file,
        verifier=lambda path: (False, "unreadable tags"),
        duration_reader=lambda path: None,
    )
    assert snapshot.directory_exists is True
    assert snapshot.warnings
    assert snapshot.tracks[0].state_status is LibraryStateStatus.NEW
    assert snapshot.tracks[0].warning == "unreadable tags"


def test_track_snapshot_is_read_only(tmp_path, monkeypatch):
    library = tmp_path / "music"
    library.mkdir()
    track = library / "Track.mp3"
    track.write_bytes(b"original")
    state_file = tmp_path / "absent" / "state.json"
    before = track.read_bytes()

    snapshot = get_library_snapshot(
        Settings(music_dir=library),
        state_file=state_file,
        verifier=lambda path: (False, "no managed lyrics frame"),
        duration_reader=lambda path: 100.0,
    )

    assert snapshot.total_track_count == 1
    assert track.read_bytes() == before
    assert not state_file.parent.exists()

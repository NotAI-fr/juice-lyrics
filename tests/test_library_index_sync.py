from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.library.media import AudioMetadata
from juice_lyrics.services.library_identity import IdentityBackfillDependencies
from juice_lyrics.services.library_index_sync import LibraryIndexSyncDependencies, sync_library_index
from juice_lyrics.services.library_status import LibraryLrcStatus, LibraryMatchStatus, get_library_snapshot
from juice_lyrics.state import sha256_file


def _dependencies(state_file, *, searcher, counts):
    def snapshot(settings, *, previous_snapshot=None, state_file=state_file):
        return get_library_snapshot(
            settings, state_file=state_file, previous_snapshot=previous_snapshot,
            verifier=lambda path: (False, "no lyrics"),
            duration_reader=lambda path: 180.0,
            metadata_reader=lambda path: _metadata(path, counts),
            hasher=lambda path: _hash(path, counts),
        )

    def writer(path, state):
        from juice_lyrics.state import write_state_file
        counts["writes"] += 1
        write_state_file(path, state)

    return LibraryIndexSyncDependencies(
        snapshot_provider=snapshot,
        identity=IdentityBackfillDependencies(
            searcher=searcher,
            search_title=lambda path: path.stem,
            matcher=lambda settings, path, results, query: (
                results[0] if len(results) == 1 else None, 100.0, [], []
            ),
            hasher=lambda path: _hash(path, counts),
        ),
        state_writer=writer,
        hasher=lambda path: _hash(path, counts),
    )


def _metadata(path, counts):
    counts["metadata"] += 1
    return AudioMetadata(path.stem, "Juice WRLD", "Album", 180.0)


def _hash(path, counts):
    counts["hashes"] += 1
    return sha256_file(path)


def _counts():
    return {"metadata": 0, "hashes": 0, "writes": 0, "searches": 0}


@pytest.mark.parametrize("suffix", [".mp3", ".FLAC", ".M4A"])
def test_new_audio_is_discovered_identified_and_unchanged_repeat_skips_work(tmp_path, suffix):
    music = tmp_path / "music"
    path = music / "Nested" / f"Song{suffix}"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"audio")
    state_file = tmp_path / "state.json"
    counts = _counts()

    def searcher(settings, query, refresh=False):
        counts["searches"] += 1
        return [{"id": 101, "name": "Song"}]

    deps = _dependencies(state_file, searcher=searcher, counts=counts)
    settings = Settings(music_dir=music)
    first = sync_library_index(settings, state_file=state_file, dependencies=deps)
    assert first.new == 1 and first.identified == 1
    assert first.snapshot.tracks[0].match_status is LibraryMatchStatus.MATCHED
    assert json.loads(state_file.read_text(encoding="utf-8"))["files"][f"Nested/Song{suffix}"]["song_id"] == 101
    before = counts.copy()

    second = sync_library_index(
        settings, previous_snapshot=first.snapshot, state_file=state_file, dependencies=deps
    )

    assert second.summary == "Library is up to date"
    assert counts == before


def test_changed_audio_replaces_stale_identity_and_ambiguous_stays_unknown(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    path = music / "Song.mp3"
    path.write_bytes(b"old audio")
    state_file = tmp_path / "state.json"
    counts = _counts()
    candidates = [{"id": 1, "name": "Old"}]
    deps = _dependencies(state_file, searcher=lambda *args, **kwargs: candidates, counts=counts)
    settings = Settings(music_dir=music)
    first = sync_library_index(settings, state_file=state_file, dependencies=deps)
    old_state = json.loads(state_file.read_text(encoding="utf-8"))
    old_state["files"]["Song.mp3"].update({"lyric_type": "USLT", "lrc": "old.lrc"})
    state_file.write_text(json.dumps(old_state), encoding="utf-8")
    path.write_bytes(b"new audio")
    candidates[:] = [{"id": 2, "name": "New"}]

    changed = sync_library_index(settings, previous_snapshot=first.snapshot, state_file=state_file, dependencies=deps)
    assert changed.changed == 1 and changed.identified == 1
    changed_entry = json.loads(state_file.read_text(encoding="utf-8"))["files"]["Song.mp3"]
    assert changed_entry["song_id"] == 2
    assert "lyric_type" not in changed_entry and "lrc" not in changed_entry
    path.write_bytes(b"third audio")
    candidates[:] = [{"id": 3, "name": "A"}, {"id": 4, "name": "B"}]

    ambiguous = sync_library_index(settings, previous_snapshot=changed.snapshot, state_file=state_file, dependencies=deps)
    entry = json.loads(state_file.read_text(encoding="utf-8"))["files"]["Song.mp3"]
    assert ambiguous.changed == 1 and ambiguous.unknown == 1
    assert ambiguous.snapshot.tracks[0].match_status is LibraryMatchStatus.UNMATCHED
    assert "song_id" not in entry and "api_name" not in entry


@pytest.mark.parametrize("after_restart", [False, True])
def test_removed_active_entry_is_retired_but_historical_custom_state_survives(tmp_path, after_restart):
    music = tmp_path / "music"
    music.mkdir()
    path = music / "Song.mp3"
    path.write_bytes(b"audio")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": {"Old Historical.mp3": {"song_id": 9}}, "custom": 42}), encoding="utf-8")
    deps = _dependencies(state_file, searcher=lambda *args, **kwargs: [{"id": 1, "name": "Song"}], counts=_counts())
    settings = Settings(music_dir=music)
    first = sync_library_index(settings, state_file=state_file, dependencies=deps)
    path.unlink()

    second = sync_library_index(
        settings,
        previous_snapshot=None if after_restart else first.snapshot,
        state_file=state_file,
        dependencies=deps,
    )
    saved = json.loads(state_file.read_text(encoding="utf-8"))
    assert second.removed == 1 and second.snapshot.total_track_count == 0
    assert saved["files"]["Song.mp3"]["library_removed_at"]
    assert saved["files"]["Song.mp3"]["song_id"] == 1
    assert saved["library_sync_paths"] == []
    assert saved["files"]["Old Historical.mp3"] == {"song_id": 9}
    assert saved["custom"] == 42


def test_offline_sync_preserves_state_and_local_health(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    path = music / "Song.mp3"
    path.write_bytes(b"audio")
    state_file = tmp_path / "state.json"
    original = {"files": {"Song.mp3": {"sha256": "old", "song_id": 7, "api_name": "Old"}}, "custom": 42}
    state_file.write_text(json.dumps(original), encoding="utf-8")
    before = state_file.read_bytes()
    deps = _dependencies(
        state_file,
        searcher=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
        counts=_counts(),
    )

    result = sync_library_index(Settings(music_dir=music), state_file=state_file, dependencies=deps)

    assert result.error is not None and result.snapshot.total_track_count == 1
    assert result.snapshot.tracks[0].match_status is LibraryMatchStatus.UNMATCHED
    assert state_file.read_bytes() == before
    assert path.read_bytes() == b"audio"


def test_malformed_state_is_not_overwritten(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    (music / "Song.mp3").write_bytes(b"audio")
    state_file = tmp_path / "state.json"
    state_file.write_text("{broken", encoding="utf-8")
    before = state_file.read_bytes()

    with pytest.raises(RuntimeError, match="malformed"):
        sync_library_index(Settings(music_dir=music), state_file=state_file)
    assert state_file.read_bytes() == before


def test_empty_search_stays_unknown_and_is_not_repeated_within_cache_ttl(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    path = music / "Unknown.flac"
    path.write_bytes(b"audio")
    state_file = tmp_path / "state.json"
    counts = _counts()

    def searcher(*args, **kwargs):
        counts["searches"] += 1
        return []

    deps = _dependencies(state_file, searcher=searcher, counts=counts)
    settings = Settings(music_dir=music)
    first = sync_library_index(settings, state_file=state_file, dependencies=deps)
    saved = json.loads(state_file.read_text(encoding="utf-8"))["files"]["Unknown.flac"]
    assert first.unknown == 1 and "song_id" not in saved
    assert saved["catalogue_checked_at"]
    before = counts.copy()

    second = sync_library_index(settings, previous_snapshot=first.snapshot, state_file=state_file, dependencies=deps)

    assert second.unknown == 1 and second.summary == "Library is up to date"
    assert counts == before
    assert path.read_bytes() == b"audio"


def test_existing_unknown_is_backfilled_without_changing_audio_or_sidecar(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    path = music / "Bandit.flac"
    path.write_bytes(b"untouched audio")
    sidecar = music / "Bandit.lrc"
    sidecar.write_text("[00:01.00]Lyric\n", encoding="utf-8")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": {"Bandit.flac": {
        "sha256": sha256_file(path), "lyric_type": "FLAC_LYRICS_PLAIN",
    }}}), encoding="utf-8")
    rmpc = tmp_path / "rmpc.ron"
    rmpc.write_text("keep", encoding="utf-8")
    counts = _counts()
    deps = _dependencies(
        state_file,
        searcher=lambda *args, **kwargs: [{"id": 94107, "name": "Bandit"}],
        counts=counts,
    )

    result = sync_library_index(Settings(music_dir=music), state_file=state_file, dependencies=deps)

    entry = json.loads(state_file.read_text(encoding="utf-8"))["files"]["Bandit.flac"]
    assert result.identified == 1 and result.new == 0
    assert entry["song_id"] == 94107 and entry["lyric_type"] == "FLAC_LYRICS_PLAIN"
    assert path.read_bytes() == b"untouched audio"
    assert sidecar.read_text(encoding="utf-8") == "[00:01.00]Lyric\n"
    assert rmpc.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "backups").exists()


def test_concurrent_state_update_is_preserved(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    (music / "Song.mp3").write_bytes(b"audio")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": {}, "custom": "before"}), encoding="utf-8")

    def searcher(*args, **kwargs):
        state_file.write_text(json.dumps({"files": {}, "custom": "newer"}), encoding="utf-8")
        return [{"id": 1, "name": "Song"}]

    deps = _dependencies(state_file, searcher=searcher, counts=_counts())
    result = sync_library_index(Settings(music_dir=music), state_file=state_file, dependencies=deps)

    assert result.error and "State changed" in result.error
    assert result.snapshot.total_track_count == 1
    assert json.loads(state_file.read_text(encoding="utf-8"))["custom"] == "newer"


def test_sidecar_change_rechecks_health_without_rehashing_unchanged_audio(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    (music / "Song.mp3").write_bytes(b"audio")
    sidecar = music / "Song.lrc"
    sidecar.write_text("[00:01.00]Line\n", encoding="utf-8")
    state_file = tmp_path / "state.json"
    counts = _counts()
    deps = _dependencies(
        state_file, searcher=lambda *args, **kwargs: [{"id": 1, "name": "Song"}],
        counts=counts,
    )
    settings = Settings(music_dir=music)
    first = sync_library_index(settings, state_file=state_file, dependencies=deps)
    assert first.snapshot.tracks[0].lrc_status is LibraryLrcStatus.PRESENT
    hashes_before = counts["hashes"]
    sidecar.write_text("Untimed words\n", encoding="utf-8")

    second = sync_library_index(settings, previous_snapshot=first.snapshot, state_file=state_file, dependencies=deps)

    assert second.snapshot.tracks[0].lrc_status is LibraryLrcStatus.INVALID
    assert counts["hashes"] == hashes_before + 1
    assert sidecar.read_text(encoding="utf-8") == "Untimed words\n"


def test_one_catalogue_failure_does_not_lose_other_safe_matches(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    old = music / "Old.mp3"
    old.write_bytes(b"changed audio")
    (music / "New.mp3").write_bytes(b"new audio")
    state_file = tmp_path / "state.json"
    original_old = {"sha256": "old hash", "song_id": 7, "api_name": "Old match", "custom": 42}
    state_file.write_text(json.dumps({"files": {"Old.mp3": original_old}}), encoding="utf-8")

    def searcher(settings, query, refresh=False):
        if query == "Old":
            raise OSError("one request failed")
        return [{"id": 8, "name": "New"}]

    deps = _dependencies(state_file, searcher=searcher, counts=_counts())
    result = sync_library_index(Settings(music_dir=music), state_file=state_file, dependencies=deps)
    saved = json.loads(state_file.read_text(encoding="utf-8"))["files"]

    assert result.identified == 1 and result.failed == 1
    assert saved["New.mp3"]["song_id"] == 8
    assert saved["Old.mp3"] == original_old
    assert {track.filename: track.match_status for track in result.snapshot.tracks} == {
        "New.mp3": LibraryMatchStatus.MATCHED,
        "Old.mp3": LibraryMatchStatus.UNMATCHED,
    }

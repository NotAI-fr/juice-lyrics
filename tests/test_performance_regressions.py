"""Deterministic work-count checks; timing output is diagnostic, not an assertion."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.services.library_identity import IdentityBackfillDependencies, backfill_catalogue_identities
from juice_lyrics.services.library_status import get_library_snapshot
from juice_lyrics.state import sha256_file
from juice_lyrics.library.media import AudioMetadata


def test_unchanged_snapshot_backfill_does_not_hash_audio_twice(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    files = {}
    for index in range(16):
        path = music / f"Track {index:02}.mp3"
        path.write_bytes(bytes([index]) * (1024 * 1024))
        files[path.name] = {
            "sha256": sha256_file(path), "song_id": index + 1,
            "api_name": f"Track {index:02}",
        }
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": files}), encoding="utf-8")
    hashes = 0

    def counted_hash(path):
        nonlocal hashes
        hashes += 1
        return sha256_file(path)

    start = perf_counter()
    snapshot = get_library_snapshot(
        Settings(music_dir=music), state_file=state_file,
        verifier=lambda path: (False, "no lyrics"),
        duration_reader=lambda path: 180.0, hasher=counted_hash,
    )
    scan_seconds = perf_counter() - start
    assert hashes == len(files)
    dependencies = IdentityBackfillDependencies(
        hasher=counted_hash,
        searcher=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("known song searched")),
    )

    start = perf_counter()
    result = backfill_catalogue_identities(
        Settings(music_dir=music), snapshot.tracks,
        state_file=state_file, dependencies=dependencies,
    )
    backfill_seconds = perf_counter() - start
    print(f"snapshot={scan_seconds:.4f}s backfill={backfill_seconds:.4f}s hashes={hashes}")
    assert result.reused == len(files)
    assert hashes == len(files)


def test_cached_hash_is_not_reused_after_same_size_replacement(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    path = music / "Song.mp3"
    path.write_bytes(b"old audio")
    original_stat = path.stat()
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": {"Song.mp3": {
        "sha256": sha256_file(path), "song_id": 1, "api_name": "Old song",
    }}}), encoding="utf-8")
    snapshot = get_library_snapshot(
        Settings(music_dir=music), state_file=state_file,
        verifier=lambda path: (False, "no lyrics"), duration_reader=lambda path: 180.0,
    )
    replacement = music / "replacement.tmp"
    replacement.write_bytes(b"new audio")
    os.replace(replacement, path)
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    searches = []
    candidate = {"id": 2, "name": "New song"}
    dependencies = IdentityBackfillDependencies(
        searcher=lambda *args, **kwargs: searches.append(1) or [candidate],
        matcher=lambda *args: (candidate, 100.0, [], []),
        search_title=lambda path: "Song",
    )

    result = backfill_catalogue_identities(
        Settings(music_dir=music), snapshot.tracks,
        state_file=state_file, dependencies=dependencies,
    )

    assert result.reused == 0
    assert result.identified == 1
    assert searches == [1]
    assert json.loads(state_file.read_text(encoding="utf-8"))["files"]["Song.mp3"]["song_id"] == 2


def test_one_state_entry_change_only_rechecks_that_track(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    files = {}
    for index in range(8):
        path = music / f"Track {index:02}.flac"
        path.write_bytes(bytes([index]) * 4096)
        files[path.name] = {
            "sha256": sha256_file(path),
            "song_id": index + 1,
            "api_name": f"Track {index:02}",
        }
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": files}), encoding="utf-8")
    counts = {"hashes": 0, "metadata": 0, "verification": 0}

    def counted_hash(path):
        counts["hashes"] += 1
        return sha256_file(path)

    def metadata(path):
        counts["metadata"] += 1
        return AudioMetadata(path.stem, "Juice WRLD", "Album", 180.0)

    def verify(path):
        counts["verification"] += 1
        return False, "no lyrics"

    first = get_library_snapshot(
        Settings(music_dir=music),
        state_file=state_file,
        verifier=verify,
        metadata_reader=metadata,
        hasher=counted_hash,
    )
    baseline = counts.copy()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    state["files"]["Track 00.flac"]["api_name"] = "Corrected title"
    state_file.write_text(json.dumps(state), encoding="utf-8")

    second = get_library_snapshot(
        Settings(music_dir=music),
        state_file=state_file,
        verifier=verify,
        metadata_reader=metadata,
        hasher=counted_hash,
        previous_snapshot=first,
    )

    assert second.tracks[0].matched_title == "Corrected title"
    assert counts["hashes"] - baseline["hashes"] == 1
    assert counts["metadata"] - baseline["metadata"] == 1
    assert counts["verification"] - baseline["verification"] == 1

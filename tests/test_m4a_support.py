from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from mutagen.mp4 import MP4

from juice_lyrics.backup.manager import backup_file, restore_backup, write_manifest
from juice_lyrics.config.settings import Settings
from juice_lyrics.library.matching import choose_candidate, local_duration, search_title_for
from juice_lyrics.library.media import MediaMetadataError, read_m4a_metadata
from juice_lyrics.library.scanner import find_audio_files, find_mp3s
from juice_lyrics.lyrics.engine import embed_lyrics, verify_file
from juice_lyrics.services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    get_library_snapshot,
    get_library_status,
)
from juice_lyrics.services.library_sync import (
    LibrarySyncDependencies,
    LibrarySyncOptions,
    MatchOutcome,
    execute_library_sync,
    plan_library_sync,
)
from juice_lyrics.state import sha256_file


_MEDIA_PAYLOAD = b"synthetic AAC payload remains untouched"


def _atom(name: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, name) + payload


def _make_m4a(
    path: Path,
    *,
    title: str | None = "All Life Long",
    artist: str | None = "Juice WRLD",
    album: str | None = "Unreleased",
    duration: float = 2.0,
) -> Path:
    """Create a tiny metadata-capable M4A container without external tools."""

    path.parent.mkdir(parents=True, exist_ok=True)
    timescale = 44_100
    movie_header = _atom(
        b"mvhd",
        b"\0\0\0\0"
        + struct.pack(">IIII", 0, 0, timescale, int(timescale * duration)),
    )
    path.write_bytes(
        _atom(b"ftyp", b"M4A \0\0\0\0M4A mp42")
        + _atom(b"moov", movie_header)
        + _atom(b"mdat", _MEDIA_PAYLOAD)
    )
    tags = MP4(path)
    if any(value is not None for value in (title, artist, album)):
        tags.add_tags()
        for key, value in (("\xa9nam", title), ("\xa9ART", artist), ("\xa9alb", album)):
            if value is not None:
                tags[key] = [value]
        tags.save()
    return path


def _candidate(*, synced: bool = True) -> dict[str, object]:
    return {
        "id": 202,
        "name": "All Life Long",
        "credited_artists": "Juice WRLD",
        "album": "Unreleased",
        "length": "0:02",
        "category": "unreleased",
        "synced_lyrics": "[00:00.50] first\n[00:01.20] second" if synced else "",
        "lyrics": "first\nsecond",
    }


def test_recursive_m4a_discovery_is_case_insensitive_and_narrowly_scoped(tmp_path):
    root = tmp_path / "Juice WRLD"
    lower = _make_m4a(root / "Album (v2)" / "Légend's [Mix].m4a")
    upper = _make_m4a(root / "Nested" / "Song.final.v2.M4A")
    outside = _make_m4a(tmp_path / "outside.m4a")
    (root / "ignore.mp4").write_bytes(b"video")
    (root / "ignore.aac").write_bytes(b"audio")

    assert find_audio_files(root) == sorted([lower, upper], key=lambda path: str(path).casefold())
    assert find_mp3s(Settings(music_dir=root)) == find_audio_files(root)
    assert outside not in find_audio_files(root)


def test_m4a_metadata_atoms_and_duration_are_read_natively(tmp_path):
    path = _make_m4a(
        tmp_path / "metadata.m4a",
        title="All Life Long (v2)",
        artist="Juice WRLD",
        album="Test Album",
        duration=3.25,
    )

    metadata = read_m4a_metadata(path)

    assert metadata.title == "All Life Long (v2)"
    assert metadata.artist == "Juice WRLD"
    assert metadata.album == "Test Album"
    assert metadata.duration_seconds == pytest.approx(3.25)
    assert local_duration(path) == pytest.approx(3.25)
    assert search_title_for(path) == "All Life Long"

    no_album = _make_m4a(tmp_path / "no album.m4a", album=None)
    assert read_m4a_metadata(no_album).album is None
    assert search_title_for(no_album) == "All Life Long"


def test_missing_m4a_matching_metadata_is_left_unresolved(tmp_path):
    path = _make_m4a(tmp_path / "Do Not Guess.m4a", title=None, artist=None, album=None)
    options = LibrarySyncOptions.from_settings(
        Settings(music_dir=tmp_path),
        dry_run=True,
        state_file=tmp_path / "missing-state.json",
    )
    dependencies = LibrarySyncDependencies(
        searcher=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API called")),
    )

    with pytest.raises(MediaMetadataError, match="missing title, artist"):
        search_title_for(path)
    assert verify_file(path) == (False, "no embedded M4A lyrics")
    plan = plan_library_sync(options, dependencies=dependencies)

    assert plan.tracks[0].outcome is MatchOutcome.UNRESOLVED
    assert "left unmatched" in (plan.tracks[0].error or "")


def test_malformed_m4a_is_left_unresolved_instead_of_guessed(tmp_path):
    path = tmp_path / "Looks Like A Song.m4a"
    path.write_bytes(b"not an MP4 container")
    options = LibrarySyncOptions.from_settings(
        Settings(music_dir=tmp_path),
        dry_run=True,
        state_file=tmp_path / "missing-state.json",
    )

    plan = plan_library_sync(options, dependencies=LibrarySyncDependencies())

    assert plan.tracks[0].path == path
    assert plan.tracks[0].outcome is MatchOutcome.UNRESOLVED
    assert "could not be read" in (plan.tracks[0].error or "")


def test_m4a_matching_reuses_normal_version_title_and_duration_scoring(tmp_path):
    path = _make_m4a(
        tmp_path / "opaque filename.m4a",
        title="All Life Long (v2)",
        duration=2.0,
    )
    right = {**_candidate(), "name": "All Life Long (v2)"}
    wrong = {**_candidate(), "name": "All Life Long (v1)"}

    chosen, score, reasons, _ = choose_candidate(
        Settings(music_dir=tmp_path),
        path,
        [wrong, right],
        search_title_for(path),
    )

    assert chosen is right
    assert score >= 70
    assert "exact version v2" in reasons
    assert any(reason.startswith("duration match") for reason in reasons)


def test_m4a_plain_embedding_preserves_unrelated_atoms_and_media_payload(tmp_path):
    path = _make_m4a(tmp_path / "All Life Long.m4a")
    audio = MP4(path)
    audio["\xa9cmt"] = ["keep me"]
    audio.save()

    result = embed_lyrics(path, [], "ordinary lyrics")
    valid, message = verify_file(path)
    updated = MP4(path)

    assert result == "M4A_LYRICS"
    assert updated["\xa9lyr"] == ["ordinary lyrics"]
    assert updated["\xa9cmt"] == ["keep me"]
    assert _MEDIA_PAYLOAD in path.read_bytes()
    assert valid is True
    assert message.startswith("M4A LYRICS")


def test_synced_m4a_embeds_plain_text_without_nonstandard_timing(tmp_path):
    path = _make_m4a(tmp_path / "All Life Long.m4a")

    embed_lyrics(path, [("first", 500), ("second", 1200)], "")

    assert MP4(path)["\xa9lyr"] == ["first\nsecond"]
    assert not any("500" in value or "1200" in value for value in MP4(path)["\xa9lyr"])


def test_m4a_sync_dry_run_writes_nothing(tmp_path):
    path = _make_m4a(tmp_path / "Album" / "All Life Long.m4a")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": {}}), encoding="utf-8")
    before = path.read_bytes()
    dependencies = LibrarySyncDependencies(
        searcher=lambda settings, title, refresh=False: [_candidate()],
    )
    options = LibrarySyncOptions.from_settings(
        Settings(music_dir=tmp_path, lyrics_dir=tmp_path / "central"),
        dry_run=True,
        rmpc_enabled=True,
        state_file=state_file,
    )

    plan = plan_library_sync(options, dependencies=dependencies)
    result = execute_library_sync(plan, dependencies=dependencies)

    assert plan.ready_files == 1
    assert plan.tracks[0].lrc_path == path.with_suffix(".lrc")
    assert result.updated_files == 0
    assert path.read_bytes() == before
    assert not path.with_suffix(".lrc").exists()
    assert not (tmp_path / "central").exists()
    assert state_file.read_text(encoding="utf-8") == json.dumps({"files": {}})


def test_m4a_sync_backs_up_before_mutation_writes_state_sidecar_and_notifies(tmp_path):
    music = tmp_path / "music"
    path = _make_m4a(music / "Album" / "All Life Long.m4a")
    pristine = path.read_bytes()
    backup_root = tmp_path / "backups" / "run"
    state = {"files": {}}
    saved: list[dict[str, object]] = []
    notified: list[list[Path]] = []

    def make_backup_root() -> Path:
        backup_root.mkdir(parents=True, exist_ok=True)
        return backup_root

    def checked_embed(target: Path, synced, plain) -> str:
        assert (backup_root / target.relative_to(music)).read_bytes() == pristine
        return embed_lyrics(target, synced, plain)

    dependencies = LibrarySyncDependencies(
        searcher=lambda settings, title, refresh=False: [_candidate()],
        backup_root_factory=make_backup_root,
        embedder=checked_embed,
        state_loader=lambda: state,
        state_saver=lambda value: saved.append(json.loads(json.dumps(value))),
        rmpc_notifier=lambda paths: notified.append(list(paths)) or len(paths),
    )
    options = LibrarySyncOptions.from_settings(
        Settings(music_dir=music, lyrics_dir=tmp_path / "central"),
        rmpc_enabled=True,
    )

    result = execute_library_sync(
        plan_library_sync(options, dependencies=dependencies),
        dependencies=dependencies,
    )

    sidecar = path.with_suffix(".lrc")
    entry = saved[0]["files"]["Album/All Life Long.m4a"]
    assert result.updated_files == 1
    assert result.lrc_files_generated == 1
    assert sidecar.is_file()
    assert notified == [[sidecar]]
    assert entry["lyric_type"] == "M4A_LYRICS_SYNCED"
    assert entry["lrc"] == str(sidecar)
    assert entry["sha256"] == sha256_file(path)
    assert not (tmp_path / "central").exists()
    assert (backup_root / "Album" / "All Life Long.m4a").read_bytes() == pristine


def test_m4a_status_distinguishes_embedded_lyrics_and_external_lrc(tmp_path):
    music = tmp_path / "music"
    path = _make_m4a(music / "All Life Long.m4a")
    embed_lyrics(path, [("line", 500)], "plain representation")
    sidecar = path.with_suffix(".lrc")
    sidecar.write_text("[00:00.50] line\n", encoding="utf-8")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": {"All Life Long.m4a": {
        "sha256": sha256_file(path),
        "song_id": 202,
        "api_name": "All Life Long",
        "lyric_type": "M4A_LYRICS_SYNCED",
        "lrc": str(sidecar),
    }}}), encoding="utf-8")

    snapshot = get_library_snapshot(Settings(music_dir=music), state_file=state_file)
    track = snapshot.tracks[0]

    assert track.media_format == "M4A"
    assert track.title == "All Life Long"
    assert track.artist == "Juice WRLD"
    assert track.album == "Unreleased"
    assert track.match_status is LibraryMatchStatus.MATCHED
    assert track.lyric_status is LibraryLyricStatus.PLAIN
    assert track.lrc_status is LibraryLrcStatus.PRESENT
    assert track.lrc_path == sidecar
    assert track.warning is None

    status = get_library_status(
        Settings(music_dir=music),
        state_file=state_file,
        backup_dir=tmp_path / "missing-backups",
    )
    assert status.track_count == 1
    assert status.embedded_plain_count == 1
    assert status.embedded_synced_count == 0
    assert status.rmpc_lrc_count == 1


def test_m4a_and_historical_mp3_flac_backups_restore_together(tmp_path):
    music = tmp_path / "music"
    m4a = _make_m4a(music / "Nested" / "Song.M4A")
    mp3 = music / "Old.mp3"
    flac = music / "Old.flac"
    mp3.write_bytes(b"historical mp3")
    flac.write_bytes(b"historical flac")
    backup_root = tmp_path / "backups" / "historical"
    for path in (m4a, mp3, flac):
        backup_file(path, backup_root, music)
        path.unlink()
    write_manifest(backup_root, [{"file": str(mp3)}])

    restored = restore_backup(backup_root, music)

    assert restored == 3
    assert MP4(m4a).get("\xa9nam") == ["All Life Long"]
    assert mp3.read_bytes() == b"historical mp3"
    assert flac.read_bytes() == b"historical flac"

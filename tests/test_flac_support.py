from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest
from mutagen.flac import FLAC

from juice_lyrics.backup.manager import backup_file, restore_backup, write_manifest
from juice_lyrics.config.settings import Settings
from juice_lyrics.library.matching import choose_candidate, local_duration, search_title_for
from juice_lyrics.library.media import MediaMetadataError, read_flac_metadata
from juice_lyrics.library.scanner import find_audio_files, find_mp3s
from juice_lyrics.lyrics.engine import embed_lyrics, verify_file
from juice_lyrics.services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    get_library_snapshot,
)
from juice_lyrics.services.library_sync import (
    LibrarySyncDependencies,
    LibrarySyncOptions,
    MatchOutcome,
    execute_library_sync,
    plan_library_sync,
)
from juice_lyrics.state import sha256_file


def _make_flac(
    path: Path,
    *,
    title: str | None = "Rental",
    artist: str | None = "Juice WRLD",
    album: str | None = "Unreleased",
    track_number: str | None = None,
    duration: float = 2.0,
) -> Path:
    """Create a tiny metadata-capable FLAC container without audio samples."""

    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44_100
    total_samples = int(sample_rate * duration)
    packed = (
        (sample_rate << 44)
        | ((2 - 1) << 41)
        | ((16 - 1) << 36)
        | total_samples
    )
    stream_info = (
        struct.pack(">HH", 4096, 4096)
        + b"\0" * 6
        + packed.to_bytes(8, "big")
        + b"\0" * 16
    )
    path.write_bytes(b"fLaC" + b"\x80" + len(stream_info).to_bytes(3, "big") + stream_info)
    tags = FLAC(path)
    for key, value in (("TITLE", title), ("ARTIST", artist), ("ALBUM", album), ("TRACKNUMBER", track_number)):
        if value is not None:
            tags[key] = [value]
    if any(value is not None for value in (title, artist, album, track_number)):
        tags.save()
    return path


def _candidate(*, synced: bool = True) -> dict[str, object]:
    return {
        "id": 101,
        "name": "Rental",
        "credited_artists": "Juice WRLD",
        "album": "Unreleased",
        "length": "0:02",
        "category": "unreleased",
        "synced_lyrics": "[00:00.50] first\n[00:01.20] second" if synced else "",
        "lyrics": "first\nsecond",
    }


def test_recursive_flac_discovery_is_case_insensitive_and_stays_in_root(tmp_path):
    root = tmp_path / "Juice WRLD"
    lower = _make_flac(root / "Album (v2)" / "Légend's [Mix].flac")
    upper = _make_flac(root / "Nested" / "Song.final.v2.FLAC")
    mp3 = root / "Still MP3.MP3"
    mp3.write_bytes(b"audio")
    outside = _make_flac(tmp_path / "outside.flac")
    (root / "ignore.aac").write_bytes(b"audio")

    assert find_audio_files(root) == sorted([lower, upper, mp3], key=lambda path: str(path).casefold())
    assert find_mp3s(Settings(music_dir=root)) == find_audio_files(root)
    assert outside not in find_audio_files(root)


def test_flac_metadata_and_duration_are_read_natively(tmp_path):
    path = _make_flac(
        tmp_path / "metadata.flac",
        title="Rental (v2)",
        artist="Juice WRLD",
        album="Test Album",
        track_number="7/20",
        duration=3.25,
    )

    metadata = read_flac_metadata(path)

    assert metadata.title == "Rental (v2)"
    assert metadata.artist == "Juice WRLD"
    assert metadata.album == "Test Album"
    assert metadata.track_number == "7/20"
    assert metadata.duration_seconds == pytest.approx(3.25)
    assert local_duration(path) == pytest.approx(3.25)
    assert search_title_for(path) == "Rental"


def test_missing_flac_matching_metadata_is_left_unresolved(tmp_path):
    path = _make_flac(tmp_path / "Do Not Guess.flac", title=None, artist=None, album=None)
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
    plan = plan_library_sync(options, dependencies=dependencies)

    assert plan.tracks[0].outcome is MatchOutcome.UNRESOLVED
    assert "left unmatched" in (plan.tracks[0].error or "")


def test_malformed_flac_is_left_unresolved_instead_of_guessed(tmp_path):
    path = tmp_path / "Looks Like Rental.flac"
    path.write_bytes(b"not a FLAC stream")
    options = LibrarySyncOptions.from_settings(
        Settings(music_dir=tmp_path),
        dry_run=True,
        state_file=tmp_path / "missing-state.json",
    )

    plan = plan_library_sync(options, dependencies=LibrarySyncDependencies())

    assert plan.tracks[0].path == path
    assert plan.tracks[0].outcome is MatchOutcome.UNRESOLVED
    assert "could not be read" in (plan.tracks[0].error or "")


def test_flac_matching_reuses_normal_version_title_and_duration_scoring(tmp_path):
    path = _make_flac(tmp_path / "opaque filename.flac", title="Rental (v2)", duration=2.0)
    right = {**_candidate(), "name": "Rental (v2)"}
    wrong = {**_candidate(), "name": "Rental (v1)"}

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


def test_bandit_collaboration_credit_searches_base_title_and_matches_by_duration(tmp_path):
    path = _make_flac(
        tmp_path / "opaque.flac",
        title="Bandit (with YoungBoy Never Broke Again)",
        artist="Juice WRLD, YoungBoy Never Broke Again",
        album="Death Race For Love (Bonus Track Version)",
        duration=189.322562,
    )
    candidate = {
        **_candidate(),
        "name": "Bandit (feat. YoungBoy Never Broke Again)",
        "credited_artists": "Juice WRLD",
        "album": "Death Race For Love",
        "length": "3:09",
        "category": "released",
    }

    search_title = search_title_for(path)
    chosen, score, reasons, _ = choose_candidate(
        Settings(music_dir=tmp_path), path, [candidate], search_title
    )

    assert search_title == "Bandit"
    assert chosen is candidate
    assert score >= 70
    assert any(reason.startswith("duration match") for reason in reasons)


def test_real_flac_with_embedded_plain_and_timed_sidecar_is_healthy_without_state(tmp_path):
    path = _make_flac(
        tmp_path / "Bandit (with YoungBoy Never Broke Again).flac",
        title="Bandit (with YoungBoy Never Broke Again)",
        artist="Juice WRLD, YoungBoy Never Broke Again",
        album="Death Race For Love (Bonus Track Version)",
        duration=189.322562,
    )
    embed_lyrics(path, [], "Oh-oh\nYeah")
    path.with_suffix(".lrc").write_text(
        "[00:05.77]Oh-oh\n[00:10.45]Yeah\n",
        encoding="utf-8",
    )

    snapshot = get_library_snapshot(
        Settings(music_dir=tmp_path),
        state_file=tmp_path / "missing-state.json",
    )

    track = snapshot.tracks[0]
    assert track.match_status is LibraryMatchStatus.UNMATCHED
    assert track.lyric_status is LibraryLyricStatus.PLAIN
    assert track.lrc_status is LibraryLrcStatus.PRESENT
    assert track.fully_covered is True
    assert track.needs_attention is False


def test_flac_plain_embedding_preserves_unrelated_metadata_and_verifies(tmp_path):
    path = _make_flac(tmp_path / "Rental.flac")
    before_samples = FLAC(path).info.total_samples
    audio = FLAC(path)
    audio["COMMENT"] = ["keep me"]
    audio.save()

    result = embed_lyrics(path, [], "ordinary lyrics")
    valid, message = verify_file(path)
    updated = FLAC(path)

    assert result == "FLAC_LYRICS"
    assert updated["lyrics"] == ["ordinary lyrics"]
    assert updated["comment"] == ["keep me"]
    assert updated.info.total_samples == before_samples
    assert valid is True
    assert message.startswith("FLAC LYRICS")


def test_synced_flac_embeds_plain_text_without_inventing_embedded_timing(tmp_path):
    path = _make_flac(tmp_path / "Rental.flac")

    embed_lyrics(path, [("first", 500), ("second", 1200)], "")

    assert FLAC(path)["lyrics"] == ["first\nsecond"]
    assert not any("500" in value or "1200" in value for value in FLAC(path)["lyrics"])


def test_flac_sync_dry_run_writes_nothing(tmp_path):
    path = _make_flac(tmp_path / "Album" / "Rental.flac")
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


def test_flac_sync_backs_up_before_mutation_writes_state_sidecar_and_notifies(tmp_path):
    music = tmp_path / "music"
    path = _make_flac(music / "Album" / "Rental.flac")
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
    entry = saved[0]["files"]["Album/Rental.flac"]
    assert result.updated_files == 1
    assert result.lrc_files_generated == 1
    assert sidecar.is_file()
    assert notified == [[sidecar]]
    assert entry["lyric_type"] == "FLAC_LYRICS_SYNCED"
    assert entry["lrc"] == str(sidecar)
    assert entry["sha256"] == sha256_file(path)
    assert not (tmp_path / "central").exists()
    assert (backup_root / "Album" / "Rental.flac").read_bytes() == pristine


def test_flac_status_distinguishes_embedded_lyrics_and_external_lrc(tmp_path):
    music = tmp_path / "music"
    path = _make_flac(music / "Rental.flac")
    embed_lyrics(path, [("line", 500)], "plain representation")
    sidecar = path.with_suffix(".lrc")
    sidecar.write_text("[00:00.50] line\n", encoding="utf-8")
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({"files": {"Rental.flac": {
        "sha256": sha256_file(path),
        "song_id": 101,
        "api_name": "Rental",
        "lyric_type": "FLAC_LYRICS_SYNCED",
        "lrc": str(sidecar),
    }}}), encoding="utf-8")

    snapshot = get_library_snapshot(Settings(music_dir=music), state_file=state_file)
    track = snapshot.tracks[0]

    assert track.media_format == "FLAC"
    assert track.title == "Rental"
    assert track.artist == "Juice WRLD"
    assert track.album == "Unreleased"
    assert track.match_status is LibraryMatchStatus.MATCHED
    assert track.lyric_status is LibraryLyricStatus.PLAIN
    assert track.lrc_status is LibraryLrcStatus.PRESENT
    assert track.lrc_path == sidecar
    assert track.warning is None


def test_flac_and_historical_mp3_backups_restore_together(tmp_path):
    music = tmp_path / "music"
    flac = _make_flac(music / "Nested" / "Song.FLAC")
    mp3 = music / "Old.mp3"
    mp3.write_bytes(b"historical mp3")
    backup_root = tmp_path / "backups" / "historical"
    backup_file(flac, backup_root, music)
    backup_file(mp3, backup_root, music)
    write_manifest(backup_root, [{"file": str(mp3)}])
    flac.unlink()
    mp3.unlink()

    restored = restore_backup(backup_root, music)

    assert restored == 2
    assert FLAC(flac).get("title") == ["Rental"]
    assert mp3.read_bytes() == b"historical mp3"

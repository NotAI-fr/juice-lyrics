from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.library.matching import choose_candidate
from juice_lyrics.services.library_identity import (
    IdentityBackfillDependencies,
    backfill_catalogue_identities,
)
from juice_lyrics.services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibraryStateStatus,
    LibraryTrack,
)


def _track(root: Path, relative: str, *, healthy: bool = False) -> LibraryTrack:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"audio:{relative}".encode())
    if healthy:
        path.with_suffix(".lrc").write_text("[00:05.77]Oh-oh\n", encoding="utf-8")
    suffix = path.suffix.casefold()
    lyric = (
        LibraryLyricStatus.SYNCED
        if suffix == ".mp3" and healthy
        else LibraryLyricStatus.PLAIN if healthy else LibraryLyricStatus.NONE
    )
    return LibraryTrack(
        reference=relative,
        path=path,
        relative_path=Path(relative),
        filename=path.name,
        title=path.stem,
        duration_seconds=189.0,
        match_status=LibraryMatchStatus.UNMATCHED,
        matched_title=None,
        lyric_status=lyric,
        lrc_status=LibraryLrcStatus.PRESENT if healthy else LibraryLrcStatus.NONE,
        lrc_path=path.with_suffix(".lrc") if healthy else None,
        state_status=LibraryStateStatus.NEW,
        media_format=suffix.removeprefix(".").upper(),
    )


def _candidate(title: str, *, song_id: int = 101, length: str = "3:09") -> dict:
    return {
        "id": song_id,
        "name": title,
        "length": length,
        "category": "unreleased",
    }


@pytest.mark.parametrize("relative", ["New.mp3", "Album/New.FLAC", "Album/New.M4A"])
def test_new_supported_format_without_state_is_identified_and_persisted(
    tmp_path, monkeypatch, relative
):
    track = _track(tmp_path, relative)
    state_file = tmp_path / "state.json"
    calls = []
    monkeypatch.setattr("juice_lyrics.library.matching.local_duration", lambda path: 189.0)
    monkeypatch.setattr("juice_lyrics.library.matching.local_album", lambda path: None)
    monkeypatch.setattr("juice_lyrics.library.matching.tagged_matching_title", lambda path: "New")
    dependencies = IdentityBackfillDependencies(
        searcher=lambda settings, query, refresh=False: calls.append(query) or [_candidate("New")],
        search_title=lambda path: "New",
    )

    result = backfill_catalogue_identities(
        Settings(music_dir=tmp_path),
        (track,),
        state_file=state_file,
        dependencies=dependencies,
    )
    saved = json.loads(state_file.read_text(encoding="utf-8"))["files"][relative]

    assert result.identified == 1
    assert calls == ["New"]
    assert saved["song_id"] == 101
    assert saved["api_name"] == "New"
    assert saved["sha256"]
    assert "lyric_type" not in saved
    assert "lrc" not in saved


@pytest.mark.parametrize(
    ("local_title", "query", "candidate_title", "length"),
    [
        (
            "Bandit (with YoungBoy Never Broke Again)",
            "Bandit",
            "Bandit (feat. YoungBoy Never Broke Again)",
            "3:09",
        ),
        ("10 Feet", "10 Feet", "10 Feet", "3:09"),
    ],
)
def test_released_mainstream_fixture_is_identified_conservatively(
    tmp_path, monkeypatch, local_title, query, candidate_title, length
):
    track = _track(tmp_path, f"{local_title}.flac")
    track = replace(track, title=local_title)
    candidate = _candidate(candidate_title, length=length)
    candidate["category"] = "released"
    monkeypatch.setattr("juice_lyrics.library.matching.local_duration", lambda path: 189.32)
    monkeypatch.setattr(
        "juice_lyrics.library.matching.tagged_matching_title",
        lambda path: local_title,
    )
    dependencies = IdentityBackfillDependencies(
        searcher=lambda settings, value, refresh=False: [candidate],
        search_title=lambda path: query,
        matcher=choose_candidate,
    )

    result = backfill_catalogue_identities(
        Settings(music_dir=tmp_path),
        (track,),
        state_file=tmp_path / "state.json",
        dependencies=dependencies,
    )

    assert result.identified == 1


def test_persisted_identity_is_reused_without_search(tmp_path):
    track = _track(tmp_path, "Nested/Song.m4a")
    state_file = tmp_path / "state.json"
    dependencies = IdentityBackfillDependencies(
        searcher=lambda settings, query, refresh=False: [_candidate("Song")],
        search_title=lambda path: "Song",
        matcher=lambda *args: (_candidate("Song"), 100.0, [], []),
    )
    first = backfill_catalogue_identities(
        Settings(music_dir=tmp_path), (track,), state_file=state_file, dependencies=dependencies
    )
    dependencies.searcher = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("catalogue searched again")
    )
    second = backfill_catalogue_identities(
        Settings(music_dir=tmp_path), (track,), state_file=state_file, dependencies=dependencies
    )

    assert first.identified == 1
    assert second.reused == 1
    assert second.identified == 0


@pytest.mark.parametrize("ambiguous", [True, False])
def test_ambiguous_or_duration_incompatible_candidate_remains_unknown(
    tmp_path, monkeypatch, ambiguous
):
    track = _track(tmp_path, "Song.flac")
    monkeypatch.setattr("juice_lyrics.library.matching.local_duration", lambda path: 189.0)
    monkeypatch.setattr("juice_lyrics.library.matching.tagged_matching_title", lambda path: "Song")
    candidates = (
        [_candidate("Song", song_id=1), _candidate("Song", song_id=2)]
        if ambiguous
        else [_candidate("Song", length="4:30")]
    )
    dependencies = IdentityBackfillDependencies(
        searcher=lambda settings, query, refresh=False: candidates,
        search_title=lambda path: "Song",
    )
    state_file = tmp_path / "state.json"

    result = backfill_catalogue_identities(
        Settings(music_dir=tmp_path), (track,), state_file=state_file, dependencies=dependencies
    )

    assert result.unknown == 1
    assert result.identified == 0
    assert not state_file.exists()


def test_api_failure_preserves_healthy_audio_lrc_and_other_configuration(tmp_path):
    track = _track(tmp_path / "music", "Bandit.flac", healthy=True)
    audio_before = track.path.read_bytes()
    lrc_before = track.path.with_suffix(".lrc").read_bytes()
    rmpc = tmp_path / "rmpc.ron"
    rmpc.write_text("keep", encoding="utf-8")
    dependencies = IdentityBackfillDependencies(
        searcher=lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline")),
        search_title=lambda path: "Bandit",
    )

    result = backfill_catalogue_identities(
        Settings(music_dir=tmp_path / "music"),
        (track,),
        state_file=tmp_path / "state.json",
        dependencies=dependencies,
    )

    assert result.failed == 1
    assert track.fully_covered is True
    assert track.needs_attention is False
    assert track.path.read_bytes() == audio_before
    assert track.path.with_suffix(".lrc").read_bytes() == lrc_before
    assert rmpc.read_text(encoding="utf-8") == "keep"
    assert not (tmp_path / "backups").exists()

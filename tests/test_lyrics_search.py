from __future__ import annotations

import json
import struct
from dataclasses import replace
from pathlib import Path

from mutagen.flac import FLAC
from mutagen.id3 import ID3, SYLT, USLT
from mutagen.mp4 import MP4

from juice_lyrics.config.settings import LYRICS_SEARCH_INDEX, Settings
from juice_lyrics.lyrics.engine import DESCRIPTION, LocalLyricLine, read_local_lyrics
from juice_lyrics.services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibrarySnapshot,
    LibraryStateStatus,
    LibraryTrack,
)
from juice_lyrics.services.lyrics_search import (
    build_lyrics_search_index,
    normalize_lyric_text,
)


def _atom(name: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, name) + payload


def _make_mp3(path: Path, lyrics: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")
    tags = ID3()
    tags.add(USLT(encoding=3, lang="eng", desc=DESCRIPTION, text=lyrics))
    tags.save(path)
    return path


def _make_flac(path: Path, lyrics: str) -> Path:
    sample_rate = 44_100
    packed = (sample_rate << 44) | ((2 - 1) << 41) | ((16 - 1) << 36) | sample_rate
    stream_info = struct.pack(">HH", 4096, 4096) + b"\0" * 6 + packed.to_bytes(8, "big") + b"\0" * 16
    path.write_bytes(b"fLaC" + b"\x80" + len(stream_info).to_bytes(3, "big") + stream_info)
    audio = FLAC(path)
    audio["TITLE"] = [path.stem]
    audio["ARTIST"] = ["Juice WRLD"]
    audio["LYRICS"] = [lyrics]
    audio.save()
    return path


def _make_m4a(path: Path, lyrics: str) -> Path:
    timescale = 44_100
    movie_header = _atom(
        b"mvhd", b"\0\0\0\0" + struct.pack(">IIII", 0, 0, timescale, timescale)
    )
    path.write_bytes(
        _atom(b"ftyp", b"M4A \0\0\0\0M4A mp42")
        + _atom(b"moov", movie_header)
        + _atom(b"mdat", b"synthetic payload")
    )
    audio = MP4(path)
    audio.add_tags()
    audio["\xa9nam"] = [path.stem]
    audio["\xa9ART"] = ["Juice WRLD"]
    audio["\xa9lyr"] = [lyrics]
    audio.save()
    return path


def _track(path: Path, root: Path) -> LibraryTrack:
    return LibraryTrack(
        reference=str(path.relative_to(root)),
        path=path,
        relative_path=path.relative_to(root),
        filename=path.name,
        title=path.stem,
        duration_seconds=1.0,
        match_status=LibraryMatchStatus.UNMATCHED,
        matched_title=None,
        lyric_status=LibraryLyricStatus.PLAIN,
        lrc_status=LibraryLrcStatus.PRESENT if path.with_suffix(".lrc").is_file() else LibraryLrcStatus.NONE,
        lrc_path=path.with_suffix(".lrc") if path.with_suffix(".lrc").is_file() else None,
        state_status=LibraryStateStatus.NEW,
    )


def _snapshot(root: Path, *paths: Path) -> LibrarySnapshot:
    return LibrarySnapshot(root, True, tuple(_track(path, root) for path in paths))


def test_native_reader_covers_mp3_flac_m4a_plain_and_timed_lrc(tmp_path):
    mp3 = _make_mp3(tmp_path / "Lucid Dreams.mp3", "I still see your shadows\nin my room")
    flac = _make_flac(tmp_path / "Rental.flac", "I don't know why\nplain FLAC line")
    m4a = _make_m4a(tmp_path / "All Life Long.m4a", "M4A embedded lyric")
    mp3.with_suffix(".lrc").write_text(
        "[ar:Juice WRLD]\n[01:42.25] I still see your shadows\nplain sidecar line\n",
        encoding="utf-8",
    )

    mp3_lines = read_local_lyrics(mp3)
    assert LocalLyricLine("I still see your shadows", 102250, "lrc") in mp3_lines
    assert LocalLyricLine("plain sidecar line", None, "lrc") in mp3_lines
    assert any(line.text == "in my room" and line.source == "embedded" for line in mp3_lines)
    assert [line.text for line in read_local_lyrics(flac)] == ["I don't know why", "plain FLAC line"]
    assert [line.text for line in read_local_lyrics(m4a)] == ["M4A embedded lyric"]


def test_mp3_synced_embedded_lyrics_remain_searchable(tmp_path):
    path = tmp_path / "Synced.mp3"
    path.write_bytes(b"")
    tags = ID3()
    tags.add(SYLT(encoding=3, lang="eng", format=2, type=1, desc=DESCRIPTION, text=[("timed embedded line", 1200)]))
    tags.save(path)

    assert read_local_lyrics(path) == (LocalLyricLine("timed embedded line", 1200, "embedded"),)


def test_normalization_and_phrase_matching_are_predictable(tmp_path):
    assert normalize_lyric_text("  DON'T   know?! ") == "dont know"
    path = _make_mp3(tmp_path / "Song.mp3", "Baby, I DON'T   know why\nnext line")
    index = build_lyrics_search_index(
        Settings(music_dir=tmp_path), _snapshot(tmp_path, path), cache_file=tmp_path / "index.json"
    )

    for query in ("dont know", "don't know", "DON'T   KNOW", "i dont"):
        result = index.search(query)
        assert len(result) == 1
        assert result[0].matching_line == "Baby, I DON'T   know why"
    assert index.search("not present") == ()


def test_one_result_per_track_preserves_lrc_timestamp_and_hit_count(tmp_path):
    path = _make_mp3(tmp_path / "Lucid Dreams.mp3", "I still see your shadows!\nI still see your shadows!")
    path.with_suffix(".lrc").write_text(
        "[01:42.00] I still see your shadows\n[02:10.00] I still see your shadows\n",
        encoding="utf-8",
    )
    index = build_lyrics_search_index(
        Settings(music_dir=tmp_path), _snapshot(tmp_path, path), cache_file=tmp_path / "index.json"
    )

    results = index.search("still see your shadows")
    assert len(results) == 1
    assert results[0].timestamp_ms == 102000
    assert results[0].source == "lrc"
    assert results[0].hit_count == 2


def test_default_index_path_uses_isolated_xdg_cache():
    assert LYRICS_SEARCH_INDEX == Path.home() / ".cache" / "juice-lyrics" / "lyrics-search-index-v1.json"


def test_incremental_index_new_changed_removed_and_repeated_queries(tmp_path):
    first = _make_mp3(tmp_path / "First.mp3", "first lyric")
    second = _make_mp3(tmp_path / "Second.mp3", "second lyric")
    cache = tmp_path / "cache" / "index.json"
    reads: list[Path] = []

    def reader(path: Path):
        reads.append(path)
        return read_local_lyrics(path)

    initial = build_lyrics_search_index(
        Settings(music_dir=tmp_path), _snapshot(tmp_path, first), cache_file=cache, lyrics_reader=reader
    )
    assert initial.indexed_count == 1 and reads == [first]
    reads.clear()
    added = build_lyrics_search_index(
        Settings(music_dir=tmp_path), _snapshot(tmp_path, first, second), cache_file=cache, lyrics_reader=reader
    )
    assert added.indexed_count == 1 and added.reused_count == 1 and reads == [second]

    _make_mp3(first, "changed embedded lyric")
    reads.clear()
    changed = build_lyrics_search_index(
        Settings(music_dir=tmp_path), _snapshot(tmp_path, first, second), cache_file=cache, lyrics_reader=reader
    )
    assert changed.indexed_count == 1 and changed.reused_count == 1 and reads == [first]
    reads.clear()
    for query in ("changed", "changed e", "changed embedded", "missing"):
        changed.search(query)
    assert reads == []

    removed = build_lyrics_search_index(
        Settings(music_dir=tmp_path), _snapshot(tmp_path, first), cache_file=cache, lyrics_reader=reader
    )
    assert removed.removed_count == 1
    assert removed.search("second lyric") == ()


def test_changed_lrc_reindexes_only_its_track(tmp_path):
    first = _make_mp3(tmp_path / "First.mp3", "embedded one")
    second = _make_mp3(tmp_path / "Second.mp3", "embedded two")
    first.with_suffix(".lrc").write_text("[00:01.00] old sidecar\n", encoding="utf-8")
    cache = tmp_path / "index.json"
    snapshot = _snapshot(tmp_path, first, second)
    build_lyrics_search_index(Settings(music_dir=tmp_path), snapshot, cache_file=cache)
    first.with_suffix(".lrc").write_text("[00:02.00] replacement sidecar text\n", encoding="utf-8")
    reads: list[Path] = []
    index = build_lyrics_search_index(
        Settings(music_dir=tmp_path), snapshot, cache_file=cache,
        lyrics_reader=lambda path: reads.append(path) or read_local_lyrics(path),
    )

    assert reads == [first]
    assert index.search("replacement sidecar")[0].timestamp_ms == 2000


def test_corrupt_index_rebuilds_offline_without_mutating_media_or_state(tmp_path, monkeypatch):
    import juice_lyrics.api.client as api_client

    path = _make_mp3(tmp_path / "Offline.mp3", "works with no catalogue")
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"files": {"keep": {"custom": True}}}), encoding="utf-8")
    before_audio = path.read_bytes()
    before_state = state.read_bytes()
    cache = tmp_path / "cache" / "index.json"
    cache.parent.mkdir()
    cache.write_text("not json", encoding="utf-8")
    monkeypatch.setattr(
        api_client, "api_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API called")),
    )

    index = build_lyrics_search_index(
        Settings(music_dir=tmp_path), _snapshot(tmp_path, path), cache_file=cache
    )

    assert index.rebuilt is True
    assert index.search("no catalogue")
    assert path.read_bytes() == before_audio
    assert state.read_bytes() == before_state
    assert json.loads(cache.read_text(encoding="utf-8"))["version"] == 1

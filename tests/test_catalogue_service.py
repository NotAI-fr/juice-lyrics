from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pytest

from juice_lyrics.config.settings import Settings
from juice_lyrics.services.catalogue import (
    LyricAvailability,
    get_song_details,
    search_catalogue,
)


def test_empty_catalogue_search_preserves_filters():
    calls = []

    def searcher(settings, query, **kwargs):
        calls.append((query, kwargs))
        return {"results": []}

    results = search_catalogue(
        Settings(),
        "rental",
        category="unreleased",
        era="DRFL",
        refresh=True,
        searcher=searcher,
    )

    assert results == ()
    assert calls == [("rental", {"category": "unreleased", "era": "DRFL", "refresh": True})]


def test_search_normalizes_shapes_lyrics_and_downloadability(tmp_path):
    records = [
        {
            "id": 1,
            "name": "Synced Song",
            "category": "unreleased",
            "era": "DRFL",
            "length": "3:00",
            "credited_artists": "Juice WRLD",
            "producers": [{"name": "Producer One"}, "Producer Two"],
            "path": "Tracks/Synced Song.mp3",
            "synced_lyrics": "[00:01.00] line",
            "lyrics": "line",
        },
        {
            "id": "2",
            "title": "Plain Song",
            "era": {"id": 4, "name": "JW3"},
            "artist": [{"name": "Juice WRLD"}],
            "producer": {"name": "Producer Three"},
            "download_url": "https://example.invalid/plain.mp3",
            "lyrics": "plain lyrics",
        },
        {"id": 3, "name": "Unavailable", "era": None},
    ]

    results = search_catalogue(
        Settings(music_dir=tmp_path),
        "song",
        searcher=lambda *args, **kwargs: {"results": records},
    )

    assert [result.selection_index for result in results] == [1, 2, 3]
    assert [result.title for result in results] == ["Synced Song", "Plain Song", "Unavailable"]
    assert results[0].era == "DRFL"
    assert results[1].era == "JW3"
    assert results[0].artists == ("Juice WRLD",)
    assert results[0].producers == ("Producer One", "Producer Two")
    assert results[1].producers == ("Producer Three",)
    assert results[0].lyrics is LyricAvailability.SYNCED
    assert results[1].lyrics is LyricAvailability.PLAIN
    assert results[2].lyrics is LyricAvailability.NONE
    assert results[0].downloadable is True
    assert results[1].downloadable is True
    assert results[2].downloadable is False


def test_search_handles_malformed_optional_metadata_without_writes(tmp_path):
    settings = Settings(music_dir=tmp_path / "does-not-exist")
    record = {
        "id": True,
        "name": {"unexpected": "shape"},
        "era": {"unexpected": "shape"},
        "length": ["3:00"],
        "credited_artists": [{"unexpected": "shape"}, None],
        "producers": 42,
    }

    result = search_catalogue(
        settings,
        "bad",
        searcher=lambda *args, **kwargs: {"results": [record]},
    )[0]

    assert result.song_id is None
    assert result.title is None
    assert result.era is None
    assert result.length is None
    assert result.artists == ()
    assert result.producers == ()
    assert result.media_path is None
    assert result.downloadable is False
    assert not settings.music_dir.exists()


def test_details_selects_index_fetches_and_normalizes_content(tmp_path):
    search_records = [
        {"id": 10, "name": "First"},
        {"id": 20, "name": "Second"},
    ]
    fetched_ids = []

    def fetcher(settings, song_id):
        fetched_ids.append(song_id)
        return {
            "id": song_id,
            "name": "Second Details",
            "category": "unreleased",
            "era": {"name": "WOD"},
            "length": "2:19",
            "credited_artists": ["Juice WRLD", {"name": "Guest"}],
            "producers": "Producer",
            "path": "Tracks/Second.mp3",
            "synced_lyrics": "[00:01.00] synced",
            "lyrics": "plain fallback",
        }

    details = get_song_details(
        Settings(music_dir=tmp_path),
        "second",
        selection_index=2,
        refresh=True,
        searcher=lambda settings, query, refresh=False: search_records,
        details_fetcher=fetcher,
    )

    assert details is not None
    assert details.selection_index == 2
    assert details.song_id == 20
    assert details.title == "Second Details"
    assert details.era == "WOD"
    assert details.artists == ("Juice WRLD", "Guest")
    assert details.producers == ("Producer",)
    assert details.lyrics is LyricAvailability.SYNCED
    assert details.synced_lyrics == "[00:01.00] synced"
    assert details.plain_lyrics == "plain fallback"
    assert details.downloadable is True
    assert fetched_ids == [20]


def test_details_empty_invalid_index_and_fetch_fallback(tmp_path):
    settings = Settings(music_dir=tmp_path)
    assert get_song_details(
        settings,
        "none",
        searcher=lambda *args, **kwargs: [],
    ) is None

    searcher = lambda *args, **kwargs: [{"id": 1, "name": "Fallback", "lyrics": "plain"}]
    with pytest.raises(RuntimeError, match="--index is outside the result list"):
        get_song_details(settings, "song", selection_index=2, searcher=searcher)

    details = get_song_details(
        settings,
        "song",
        searcher=searcher,
        details_fetcher=lambda *args: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    assert details is not None
    assert details.title == "Fallback"
    assert details.lyrics is LyricAvailability.PLAIN

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..acquisition.resolver import ResourceResolutionError, resolve_resource
from ..api.client import get_song, search_song_names, search_songs
from ..config.settings import Settings

SearchResponse = Mapping[str, Any]
SearchFunction = Callable[..., SearchResponse]
NameSearchFunction = Callable[..., Sequence[Any]]
DetailsFunction = Callable[[Settings, int], Mapping[str, Any]]
SongId = int | str


class LyricAvailability(str, Enum):
    SYNCED = "synced"
    PLAIN = "plain"
    NONE = "none"


@dataclass(frozen=True, slots=True)
class CatalogueSearchResult:
    selection_index: int
    song_id: SongId | None
    title: str | None
    category: str | None
    era: str | None
    length: str | None
    artists: tuple[str, ...]
    producers: tuple[str, ...]
    media_path: str | None
    lyrics: LyricAvailability
    downloadable: bool


@dataclass(frozen=True, slots=True)
class SongDetails:
    selection_index: int
    song_id: SongId | None
    title: str | None
    category: str | None
    era: str | None
    length: str | None
    artists: tuple[str, ...]
    producers: tuple[str, ...]
    media_path: str | None
    lyrics: LyricAvailability
    synced_lyrics: str | None
    plain_lyrics: str | None
    downloadable: bool


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None


def _named_values(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, Mapping):
        for key in ("name", "title"):
            text = _text(value.get(key))
            if text:
                return (text,)
        return ()
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values: list[str] = []
        for item in value:
            values.extend(_named_values(item))
        return tuple(values)
    return ()


def _era(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _text(value.get("name"))
    return _text(value)


def _song_id(value: Any) -> SongId | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    return _text(value)


def _lyrics(record: Mapping[str, Any]) -> tuple[LyricAvailability, str | None, str | None]:
    synced = _text(record.get("synced_lyrics"))
    plain = _text(record.get("lyrics"))
    if synced:
        return LyricAvailability.SYNCED, synced, plain
    if plain:
        return LyricAvailability.PLAIN, None, plain
    return LyricAvailability.NONE, None, None


def _is_downloadable(settings: Settings, record: Mapping[str, Any]) -> bool:
    try:
        resolve_resource(
            dict(record),
            destination_dir=Path(settings.music_dir),
            api_base=settings.api_base,
        )
    except (ResourceResolutionError, TypeError, ValueError):
        return False
    return True


def _common_fields(settings: Settings, record: Mapping[str, Any]) -> dict[str, Any]:
    lyric_status, synced, plain = _lyrics(record)
    return {
        "song_id": _song_id(record.get("id")),
        "title": _text(record.get("title")) or _text(record.get("name")),
        "category": _text(record.get("category")),
        "era": _era(record.get("era")),
        "length": _text(record.get("length")),
        "artists": _named_values(record.get("credited_artists") or record.get("artist")),
        "producers": _named_values(record.get("producers") or record.get("producer")),
        "media_path": _text(record.get("path") or record.get("file_path")),
        "lyrics": lyric_status,
        "synced_lyrics": synced,
        "plain_lyrics": plain,
        "downloadable": _is_downloadable(settings, record),
    }


def search_catalogue(
    settings: Settings,
    query: str,
    *,
    category: str | None = None,
    era: str | None = None,
    refresh: bool = False,
    searcher: SearchFunction = search_songs,
) -> tuple[CatalogueSearchResult, ...]:
    """Search and normalize catalogue records without changing application state."""

    response = searcher(
        settings,
        query,
        category=category,
        era=era,
        refresh=refresh,
    )
    raw_results = response.get("results", []) if isinstance(response, Mapping) else []
    if not isinstance(raw_results, Sequence) or isinstance(raw_results, (str, bytes, bytearray)):
        return ()

    results: list[CatalogueSearchResult] = []
    for index, record in enumerate(raw_results, start=1):
        if not isinstance(record, Mapping):
            continue
        fields = _common_fields(settings, record)
        fields.pop("synced_lyrics")
        fields.pop("plain_lyrics")
        results.append(CatalogueSearchResult(selection_index=index, **fields))
    return tuple(results)


def get_song_details(
    settings: Settings,
    query: str,
    *,
    selection_index: int | None = None,
    refresh: bool = False,
    searcher: NameSearchFunction = search_song_names,
    details_fetcher: DetailsFunction = get_song,
) -> SongDetails | None:
    """Select a search result and return normalized song details."""

    raw_results = searcher(settings, query, refresh=refresh)
    results = list(raw_results) if isinstance(raw_results, Sequence) else []
    if not results:
        return None

    selected = selection_index or 1
    if selected < 1 or selected > len(results):
        raise RuntimeError("--index is outside the result list")
    candidate = results[selected - 1]
    if not isinstance(candidate, Mapping):
        return None

    record: Mapping[str, Any] = candidate
    candidate_id = _song_id(candidate.get("id"))
    if candidate_id is not None:
        try:
            numeric_id = int(candidate_id)
            fetched = details_fetcher(settings, numeric_id)
            if isinstance(fetched, Mapping):
                record = fetched
        except Exception:
            pass

    fields = _common_fields(settings, record)
    return SongDetails(selection_index=selected, **fields)

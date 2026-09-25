from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .. import __version__
from ..config.settings import CACHE_DIR, Settings


def ensure_cache() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def cache_key(value: str) -> str:
    import re
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value.lower()).strip("_") or "empty"


def build_download_url(api_base: str, path: str) -> str:
    path_str = str(path).strip()
    if path_str.startswith(("http://", "https://")):
        return path_str
    return f"{api_base.rstrip('/')}/files/download/?path={quote(path_str)}"


def api_get(url: str, timeout: int) -> Any:
    request = Request(url, headers={"User-Agent": f"juice-lyrics/{__version__}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"API returned HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach the Juice WRLD API: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("The API returned invalid JSON") from exc


def _cached_get(settings: Settings, url: str, cache_name: str, refresh: bool) -> Any:
    cache_file = CACHE_DIR / cache_name
    ensure_cache()
    ttl = settings.cache_ttl_hours * 3600
    if not refresh and cache_file.exists() and time.time() - cache_file.stat().st_mtime <= ttl:
        try:
            return json.loads(cache_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    data = api_get(url, settings.timeout)
    cache_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    time.sleep(settings.delay)
    return data


def search_songs(
    settings: Settings,
    query: str,
    *,
    category: str | None = None,
    era: str | None = None,
    page: int = 1,
    page_size: int = 50,
    refresh: bool = False,
) -> dict[str, Any]:
    params: list[tuple[str, str | int]] = [
        ("search", query),
        ("page_size", page_size),
        ("page", page),
    ]
    if category:
        params.append(("category", category))
    if era:
        params.append(("era", era))
    query_string = urlencode(params)
    # API filter values are case-sensitive (for example, ``DRFL`` works while
    # ``drfl`` does not), so the cache identity must preserve the exact query.
    query_digest = hashlib.sha256(query_string.encode("utf-8")).hexdigest()[:24]
    cache_name = f"catalogue_v3_{query_digest}.json"
    data = _cached_get(
        settings,
        f"{settings.songs_endpoint}?{query_string}",
        cache_name,
        refresh,
    )
    result = data if isinstance(data, dict) else {"results": []}
    return result


def get_categories(settings: Settings, *, refresh: bool = False) -> dict[str, Any]:
    """Return the API's canonical category values and display labels."""

    data = _cached_get(
        settings,
        settings.api_base.rstrip("/") + "/categories/",
        "catalogue_categories_v1.json",
        refresh,
    )
    return data if isinstance(data, dict) else {"categories": []}


def get_eras(settings: Settings, *, refresh: bool = False) -> list[dict[str, Any]]:
    """Read every small era-metadata page without using the song catalogue."""

    eras: list[dict[str, Any]] = []
    page = 1
    while True:
        query_string = urlencode({"page": page, "page_size": 100})
        data = _cached_get(
            settings,
            settings.api_base.rstrip("/") + f"/eras/?{query_string}",
            f"catalogue_eras_v1_page_{page}.json",
            refresh,
        )
        if not isinstance(data, dict):
            break
        values = data.get("results", [])
        if isinstance(values, list):
            eras.extend(value for value in values if isinstance(value, dict))
        if not data.get("next"):
            break
        page += 1
        if page > 20:
            raise RuntimeError("Era metadata pagination exceeded the safety limit")
    return eras


def search_song_names(settings: Settings, title: str, *, refresh: bool = False) -> list[dict[str, Any]]:
    data = search_songs(settings, title, refresh=refresh)
    results = data.get("results", []) if isinstance(data, dict) else []
    return results if isinstance(results, list) else []


def get_song(settings: Settings, song_id: int) -> dict[str, Any]:
    data = api_get(f"{settings.songs_endpoint}{song_id}/", settings.timeout)
    if not isinstance(data, dict):
        raise RuntimeError("API returned an invalid song object")
    return data

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
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


def search_songs(settings: Settings, query: str, *, category: str | None = None, era: str | None = None, refresh: bool = False) -> dict[str, Any]:
    params = [f"search={quote(query)}", "page_size=50"]
    if category:
        params.append(f"category={quote(category)}")
    if era:
        params.append(f"era={quote(era)}")
    cache_name = "advanced_" + cache_key("|".join(params)) + ".json"
    cache_file = CACHE_DIR / cache_name
    ensure_cache()
    ttl = settings.cache_ttl_hours * 3600
    if not refresh and cache_file.exists() and time.time() - cache_file.stat().st_mtime <= ttl:
        try:
            cached = json.loads(cache_file.read_text(encoding="utf-8"))
            if isinstance(cached, dict):
                return cached
        except Exception:
            pass
    data = api_get(f"{settings.songs_endpoint}?{'&'.join(params)}", settings.timeout)
    result = data if isinstance(data, dict) else {"results": []}
    cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    time.sleep(settings.delay)
    return result


def search_song_names(settings: Settings, title: str, *, refresh: bool = False) -> list[dict[str, Any]]:
    data = search_songs(settings, title, refresh=refresh)
    results = data.get("results", []) if isinstance(data, dict) else []
    return results if isinstance(results, list) else []


def get_song(settings: Settings, song_id: int) -> dict[str, Any]:
    data = api_get(f"{settings.songs_endpoint}{song_id}/", settings.timeout)
    if not isinstance(data, dict):
        raise RuntimeError("API returned an invalid song object")
    return data

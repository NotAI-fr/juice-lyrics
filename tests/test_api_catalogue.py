import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import juice_lyrics.api.client as client
from juice_lyrics.config.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures" / "catalogue"


def _fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_song_request_uses_canonical_filters_page_and_page_size(tmp_path, monkeypatch):
    urls = []
    monkeypatch.setattr(client, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(client, "api_get", lambda url, timeout: urls.append(url) or {"count": 0, "results": []})

    client.search_songs(
        Settings(cache_ttl_hours=0, delay=0),
        "Rental",
        category="unreleased",
        era="DRFL",
        page=2,
        page_size=50,
        refresh=True,
    )

    parsed = urlparse(urls[0])
    assert parsed.path == "/juicewrld/songs/"
    assert parse_qs(parsed.query) == {
        "search": ["Rental"],
        "category": ["unreleased"],
        "era": ["DRFL"],
        "page": ["2"],
        "page_size": ["50"],
    }


def test_filter_only_request_preserves_blank_search_and_server_filters(tmp_path, monkeypatch):
    urls = []
    monkeypatch.setattr(client, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(client, "api_get", lambda url, timeout: urls.append(url) or {"count": 0, "results": []})

    client.search_songs(
        Settings(cache_ttl_hours=0, delay=0),
        "",
        category="unreleased",
        era="DRFL",
        refresh=True,
    )

    assert "search=" in urlparse(urls[0]).query
    assert "category=unreleased" in urls[0]
    assert "era=DRFL" in urls[0]


def test_case_sensitive_filter_values_have_distinct_cache_entries(tmp_path, monkeypatch):
    urls = []
    monkeypatch.setattr(client, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(client, "api_get", lambda url, timeout: urls.append(url) or {"count": 0, "results": []})
    settings = Settings(cache_ttl_hours=24, delay=0)

    client.search_songs(settings, "", era="drfl")
    client.search_songs(settings, "", era="DRFL")

    assert len(urls) == 2
    assert len(list(tmp_path.glob("catalogue_v3_*.json"))) == 2


def test_api_metadata_shapes_and_era_pagination(tmp_path, monkeypatch):
    urls = []
    monkeypatch.setattr(client, "CACHE_DIR", tmp_path)

    def api_get(url, timeout):
        urls.append(url)
        if "/categories/" in url:
            return _fixture("categories.json")
        if "page=1" in url:
            return _fixture("eras_page_1.json")
        return _fixture("eras_page_2.json")

    monkeypatch.setattr(client, "api_get", api_get)
    settings = Settings(cache_ttl_hours=0, delay=0)

    categories = client.get_categories(settings, refresh=True)
    eras = client.get_eras(settings, refresh=True)

    assert categories["categories"][1] == {"value": "unreleased", "label": "Unreleased"}
    assert [(era["id"], era["name"]) for era in eras] == [(109, "WOD"), (110, "DRFL"), (130, "DRFL (TV)")]
    assert len([url for url in urls if "/eras/" in url]) == 2

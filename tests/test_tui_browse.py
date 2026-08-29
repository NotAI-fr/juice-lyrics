import asyncio
from pathlib import Path
import sys
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from textual.widgets import Input

from juice_lyrics.config.settings import Settings
from juice_lyrics.services import LibraryStatus, QueueSnapshot
from juice_lyrics.services.catalogue import (
    CatalogueSearchResult,
    LyricAvailability,
    SongDetails,
)
from juice_lyrics.tui import JuiceLyricsApp


def _result(
    index: int,
    title: str,
    *,
    lyrics: LyricAvailability = LyricAvailability.SYNCED,
    downloadable: bool = True,
) -> CatalogueSearchResult:
    return CatalogueSearchResult(
        selection_index=index,
        song_id=index,
        title=title,
        category="unreleased",
        era="DRFL",
        length="3:21",
        artists=("Juice WRLD",),
        producers=(f"Producer {index}",),
        media_path=f"Tracks/{title}.mp3" if downloadable else None,
        lyrics=lyrics,
        downloadable=downloadable,
    )


def _details(
    result: CatalogueSearchResult,
    *,
    synced: str | None = None,
    plain: str | None = None,
) -> SongDetails:
    return SongDetails(
        selection_index=result.selection_index,
        song_id=result.song_id,
        title=result.title,
        category=result.category,
        era=result.era,
        length=result.length,
        artists=result.artists,
        producers=result.producers,
        media_path=result.media_path,
        lyrics=result.lyrics,
        synced_lyrics=synced,
        plain_lyrics=plain,
        downloadable=result.downloadable,
    )


def _app(tmp_path: Path, *, search, details=None) -> JuiceLyricsApp:
    return JuiceLyricsApp(
        Settings(music_dir=tmp_path / "music"),
        library_status_provider=lambda settings: LibraryStatus(
            tmp_path / "music", 0, 0, 0, 0, 0, 0, 0
        ),
        queue_snapshot_provider=lambda: QueueSnapshot((), 0, 0, 0, 0, 0),
        catalogue_search_provider=search,
        catalogue_details_provider=details or (lambda *args, **kwargs: None),
    )


def _text(app: JuiceLyricsApp, selector: str) -> str:
    return str(app.query_one(selector).render())


async def _open_browse(app: JuiceLyricsApp, pilot):
    await pilot.press("2")
    await pilot.pause()
    return app.screen


async def _submit(app: JuiceLyricsApp, pilot, query: str):
    field = app.query_one("#browse-query", Input)
    field.value = query
    field.focus()
    await pilot.press("enter")
    await pilot.pause()
    worker = app.screen._search_worker
    if worker is not None:
        await worker.wait()
        await pilot.pause()


def test_browse_is_functional_slash_focuses_and_empty_query_does_not_search(tmp_path):
    calls = []

    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: calls.append((args, kwargs)) or ())
        async with app.run_test() as pilot:
            screen = await _open_browse(app, pilot)
            assert screen.__class__.__name__ == "BrowseScreen"
            assert app.query_one("#browse-results") is not None
            await pilot.press("/")
            assert app.focused is app.query_one("#browse-query")
            await pilot.press("enter")
            await pilot.pause()
            assert calls == []
            assert "Enter a song title" in _text(app, "#browse-status")

    asyncio.run(scenario())


def test_search_forwards_filters_and_preserves_service_order(tmp_path):
    calls = []
    expected = (_result(1, "First"), _result(2, "Second"), _result(3, "Third"))

    def search(settings, query, **kwargs):
        calls.append((query, kwargs))
        return expected

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test(size=(120, 30)) as pilot:
            await _open_browse(app, pilot)
            app.query_one("#browse-category", Input).value = "unreleased"
            app.query_one("#browse-era", Input).value = "DRFL"
            await _submit(app, pilot, "rental")

            assert calls == [("rental", {"category": "unreleased", "era": "DRFL", "refresh": False})]
            rendered = _text(app, "#browse-results")
            assert rendered.index("First") < rendered.index("Second") < rendered.index("Third")
            assert "Filters: category=unreleased, era=DRFL" in _text(app, "#browse-status")

    asyncio.run(scenario())


def test_slow_search_shows_loading_and_navigation_remains_responsive(tmp_path):
    started = Event()
    release = Event()

    def search(*args, **kwargs):
        started.set()
        assert release.wait(timeout=5)
        return (_result(1, "Rental"),)

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            field = app.query_one("#browse-query", Input)
            field.value = "rental"
            field.focus()
            await pilot.press("enter")
            await asyncio.to_thread(started.wait, 2)
            assert "Searching" in _text(app, "#browse-status")
            assert "Searching" in _text(app, "#browse-results")
            await pilot.press("3")
            await pilot.pause()
            assert app.screen.id == "screen-library"
            await pilot.press("2")
            await pilot.pause()
            assert app.screen.id == "screen-browse"
            release.set()
            worker = app.screen._search_worker
            assert worker is not None
            await worker.wait()
            await pilot.pause()
            assert "Rental" in _text(app, "#browse-results")

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_q_exits_during_slow_search(tmp_path):
    started = Event()
    release = Event()

    def search(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        return ()

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            field = app.query_one("#browse-query", Input)
            field.value = "slow"
            field.focus()
            await pilot.press("enter")
            await asyncio.to_thread(started.wait, 2)
            await pilot.press("q")
            assert not app.is_running
            release.set()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_empty_results_and_provider_errors_are_safe(tmp_path):
    calls = 0

    def search(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return ()
        raise RuntimeError("catalogue is unavailable")

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "missing")
            assert "No catalogue results found" in _text(app, "#browse-results")
            await _submit(app, pilot, "broken")
            assert "Search unavailable" in _text(app, "#browse-results")
            assert "catalogue is unavailable" in _text(app, "#browse-status")
            assert app.is_running

    asyncio.run(scenario())


def test_new_search_supersedes_stale_worker_result(tmp_path):
    first_started = Event()
    release_first = Event()

    def search(settings, query, **kwargs):
        if query == "first":
            first_started.set()
            release_first.wait(timeout=5)
            return (_result(1, "Stale Result"),)
        return (_result(1, "Fresh Result"),)

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            field = app.query_one("#browse-query", Input)
            field.value = "first"
            field.focus()
            await pilot.press("enter")
            await asyncio.to_thread(first_started.wait, 2)

            field.value = "second"
            field.focus()
            await pilot.press("enter")
            current = app.screen._search_worker
            assert current is not None
            await current.wait()
            await pilot.pause()
            assert "Fresh Result" in _text(app, "#browse-results")

            release_first.set()
            await pilot.pause()
            assert "Stale Result" not in _text(app, "#browse-results")

    try:
        asyncio.run(scenario())
    finally:
        release_first.set()


def test_arrow_jk_selection_updates_basic_details_and_enter_loads_full_details(tmp_path):
    results = (_result(1, "One"), _result(2, "Two"), _result(3, "Three"))
    detail_calls = []

    def details(settings, query, **kwargs):
        detail_calls.append((query, kwargs))
        selected = results[kwargs["selection_index"] - 1]
        return _details(selected, synced="[00:01.00] selected lyric")

    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: results, details=details)
        async with app.run_test(size=(120, 30)) as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "songs")
            assert "> One" in _text(app, "#browse-results")
            await pilot.press("down")
            await pilot.pause()
            assert "> Two" in _text(app, "#browse-results")
            assert "Producer 2" in _text(app, "#browse-details")
            await pilot.press("j")
            await pilot.pause()
            assert "> Three" in _text(app, "#browse-results")
            await pilot.press("k")
            await pilot.pause()
            assert "> Two" in _text(app, "#browse-results")
            await pilot.press("enter")
            worker = app.screen._details_worker
            assert worker is not None
            await worker.wait()
            await pilot.pause()
            assert detail_calls == [("songs", {"selection_index": 2, "refresh": False})]
            assert "[00:01.00] selected lyric" in _text(app, "#browse-details")

    asyncio.run(scenario())


def test_details_use_frontend_lyrics_terms_preview_limits_and_download_labels(tmp_path):
    results = (
        _result(1, "Synced", lyrics=LyricAvailability.SYNCED),
        _result(2, "Plain", lyrics=LyricAvailability.PLAIN),
        _result(3, "Missing", lyrics=LyricAvailability.NONE, downloadable=False),
    )
    synced = "\n".join(f"[00:0{i}.00] line {i}" for i in range(8))

    def details(settings, query, **kwargs):
        result = results[kwargs["selection_index"] - 1]
        return _details(
            result,
            synced=synced if result.lyrics is LyricAvailability.SYNCED else None,
            plain="ordinary plain lyrics" if result.lyrics is LyricAvailability.PLAIN else None,
        )

    async def load_current(app, pilot):
        await pilot.press("enter")
        await app.screen._details_worker.wait()
        await pilot.pause()
        return _text(app, "#browse-details")

    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: results, details=details)
        async with app.run_test(size=(120, 32)) as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "lyrics")
            text = await load_current(app, pilot)
            assert "Lyrics         Synced" in text
            assert "[00:05.00] line 5" in text
            assert "[00:06.00] line 6" not in text
            assert "…" in text
            assert "Download       Available" in text

            await pilot.press("down")
            text = await load_current(app, pilot)
            assert "Lyrics         Plain" in text
            assert "ordinary plain lyrics" in text

            await pilot.press("down")
            text = await load_current(app, pilot)
            assert "Lyrics         None" in text
            assert "No lyrics available" in text
            assert "Download       Unavailable" in text
            assert "SYLT" not in text and "USLT" not in text

    asyncio.run(scenario())


def test_refresh_forwards_refresh_and_state_survives_section_switch(tmp_path):
    calls = []
    results = (_result(1, "One"), _result(2, "Two"))

    def search(settings, query, **kwargs):
        calls.append((query, kwargs))
        return results

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "persist")
            await pilot.press("down")
            await pilot.press("3", "2")
            await pilot.pause()
            assert app.query_one("#browse-query", Input).value == "persist"
            assert "> Two" in _text(app, "#browse-results")
            await pilot.press("r")
            worker = app.screen._search_worker
            assert worker is not None
            await worker.wait()
            await pilot.pause()
            assert calls[-1] == ("persist", {"category": None, "era": None, "refresh": True})

    asyncio.run(scenario())


def test_narrow_browse_stacks_layout_and_remains_usable(tmp_path):
    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: (_result(1, "Narrow Song"),))
        async with app.run_test(size=(50, 24)) as pilot:
            await _open_browse(app, pilot)
            assert "-narrow" in app.screen.classes
            await _submit(app, pilot, "narrow")
            rendered = _text(app, "#browse-results")
            assert "> Narrow Song" in rendered
            assert "DRFL · unreleased · Synced · Available" in rendered

    asyncio.run(scenario())


def test_browse_is_read_only_and_has_no_live_api_dependency(tmp_path, monkeypatch):
    import juice_lyrics.api.client as api_client

    monkeypatch.setattr(
        api_client,
        "api_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("live API called")),
    )
    calls = []

    async def scenario():
        app = _app(
            tmp_path,
            search=lambda *args, **kwargs: calls.append("search") or (_result(1, "Offline"),),
            details=lambda *args, **kwargs: calls.append("details") or _details(_result(1, "Offline")),
        )
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "offline")
            await pilot.press("enter")
            await app.screen._details_worker.wait()
            await pilot.pause()

    asyncio.run(scenario())
    assert calls == ["search", "details"]
    assert not list(tmp_path.rglob("*.mp3"))
    assert not list(tmp_path.rglob("*.flac"))
    assert not list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.rglob("*.lrc"))
    assert not list(tmp_path.rglob("*.toml"))

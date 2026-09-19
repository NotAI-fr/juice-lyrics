import asyncio
from pathlib import Path
import sys
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from textual.containers import VerticalScroll
from textual.widgets import Input, Select

from juice_lyrics.config.settings import Settings
from juice_lyrics.services import LibraryStatus, QueueSnapshot
from juice_lyrics.services.catalogue import (
    CatalogueSearchResult,
    CatalogueFilterMetadata,
    CatalogueFilterOption,
    CataloguePage,
    LyricAvailability,
    SongDetails,
)
from juice_lyrics.services.download_queue import (
    DownloadQueueItem,
    DownloadQueueItemStatus,
    DownloadQueueSnapshot,
    PlannedQueueItem,
    QueueAddPlan,
    QueueAddResult,
    QueueAddStatus,
    QueueBatchAddItem,
    QueueBatchAddItemStatus,
    QueueBatchAddPlan,
    QueueBatchAddResult,
    QueueBatchAddStatus,
)
from juice_lyrics.acquisition.models import AcquisitionItem
from juice_lyrics.tui import JuiceLyricsApp
from juice_lyrics.tui.help import guide_text


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


def _app(
    tmp_path: Path,
    *,
    search,
    details=None,
    filters=None,
    queue_plan=None,
    queue_add=None,
    downloads=None,
) -> JuiceLyricsApp:
    return JuiceLyricsApp(
        Settings(music_dir=tmp_path / "music"),
        library_status_provider=lambda settings: LibraryStatus(
            tmp_path / "music", 0, 0, 0, 0, 0, 0, 0
        ),
        queue_snapshot_provider=lambda: QueueSnapshot((), 0, 0, 0, 0, 0),
        catalogue_search_provider=search,
        catalogue_details_provider=details or (lambda *args, **kwargs: None),
        catalogue_filters_provider=filters or (lambda *args, **kwargs: CatalogueFilterMetadata(
            categories=(
                CatalogueFilterOption("Released", "released"),
                CatalogueFilterOption("Unreleased", "unreleased"),
            ),
            eras=(
                CatalogueFilterOption("DRFL", "DRFL", 110),
                CatalogueFilterOption("JW3", "JW3", 111),
            ),
        )),
        queue_plan_provider=queue_plan or (lambda *args, **kwargs: QueueAddResult(
            QueueAddStatus.INVALID_SELECTION, "Queue planning is not configured for this test."
        )),
        queue_add_provider=queue_add or (lambda plan: QueueAddResult(
            QueueAddStatus.SAVE_FAILED, "Queue writing is not configured for this test."
        )),
        downloads_queue_provider=downloads or (lambda: DownloadQueueSnapshot((), 0, 0, 0, 0, 0)),
    )


def _text(app: JuiceLyricsApp, selector: str) -> str:
    return str(app.query_one(selector).render())


def _queue_plan(tmp_path: Path, result: CatalogueSearchResult) -> QueueAddPlan:
    item = AcquisitionItem(
        identifier=str(result.song_id),
        title=result.title or "Unknown",
        url="https://example.invalid/song.mp3",
        destination=tmp_path / "music" / f"{result.title}.mp3",
        metadata={"artist": "Juice WRLD", "category": result.category or "", "era": result.era or ""},
    )
    return QueueAddPlan((PlannedQueueItem(
        item=item,
        song_id=str(result.song_id),
        artist="Juice WRLD",
        category=result.category,
        era=result.era,
    ),))


def _batch_plan(
    tmp_path: Path,
    results: tuple[CatalogueSearchResult, ...],
    *,
    extra: tuple[QueueBatchAddItem, ...] = (),
) -> QueueBatchAddPlan:
    items = []
    for result in results:
        single = _queue_plan(tmp_path, result).items[0]
        items.append(QueueBatchAddItem(
            str(result.song_id),
            result.title or "Unknown",
            QueueBatchAddItemStatus.ELIGIBLE,
            "Ready to add.",
            single,
        ))
    return QueueBatchAddPlan(tuple(items) + extra)


async def _open_browse(app: JuiceLyricsApp, pilot):
    await pilot.press("2")
    await pilot.pause()
    return app.screen


async def _wait_queue_add(browse, pilot):
    worker = browse._queue_add_worker
    if worker is not None:
        await worker.wait()
    await pilot.pause(0.2)


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
            assert "Enter a title or choose at least one filter" in _text(app, "#browse-status")

    asyncio.run(scenario())


def test_filter_only_searches_forward_category_era_and_both_from_filter_fields(tmp_path):
    calls = []

    def search(settings, query, **kwargs):
        calls.append((query, kwargs))
        return (_result(1, "Filtered Song"),)

    async def submit_from(app, pilot, selector):
        field = app.query_one(selector, Select)
        field.focus()
        await pilot.pause()
        worker = app.screen._search_worker
        assert worker is not None
        await worker.wait()
        await pilot.pause()

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)

            app.query_one("#browse-category", Select).value = "unreleased"
            await submit_from(app, pilot, "#browse-category")
            assert calls[-1] == ("", {"category": "unreleased", "era": None, "page": 1, "page_size": 50, "refresh": False})

            app.query_one("#browse-category", Select).value = ""
            app.query_one("#browse-era", Select).value = "DRFL"
            await submit_from(app, pilot, "#browse-era")
            assert calls[-1] == ("", {"category": None, "era": "DRFL", "page": 1, "page_size": 50, "refresh": False})

            app.query_one("#browse-category", Select).value = "unreleased"
            await submit_from(app, pilot, "#browse-category")
            assert calls[-1] == ("", {"category": "unreleased", "era": "DRFL", "page": 1, "page_size": 50, "refresh": False})
            assert "Filtered Song" in _text(app, "#browse-results")
            assert "Filters: category=unreleased, era=DRFL" in _text(app, "#browse-status")

    asyncio.run(scenario())


def test_filter_only_loading_empty_and_error_states(tmp_path):
    started = Event()
    release = Event()
    mode = "slow"

    def search(settings, query, **kwargs):
        if mode == "slow":
            started.set()
            release.wait(timeout=5)
            return (_result(1, "Era Song"),)
        if mode == "empty":
            return ()
        raise RuntimeError("filtered catalogue failed")

    async def submit_era(app, pilot):
        field = app.query_one("#browse-era", Select)
        field.value = "DRFL"
        field.focus()
        app.screen.submit_search(refresh=False)
        await pilot.pause()

    async def scenario():
        nonlocal mode
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            await submit_era(app, pilot)
            await asyncio.to_thread(started.wait, 2)
            assert "Searching: era=DRFL" in _text(app, "#browse-status")
            release.set()
            await app.screen._search_worker.wait()
            await pilot.pause()
            assert "Era Song" in _text(app, "#browse-results")

            mode = "empty"
            await submit_era(app, pilot)
            await app.screen._search_worker.wait()
            await pilot.pause()
            assert "No catalogue results found" in _text(app, "#browse-results")
            assert "No results for filters: era=DRFL" in _text(app, "#browse-status")

            mode = "error"
            await submit_era(app, pilot)
            await app.screen._search_worker.wait()
            await pilot.pause()
            assert "filtered catalogue failed" in _text(app, "#browse-status")

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_filter_only_refresh_and_screen_switch_preserve_blank_title_and_state(tmp_path):
    calls = []
    results = (_result(1, "One"), _result(2, "Two"))

    def search(settings, query, **kwargs):
        calls.append((query, kwargs))
        return results

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            app.query_one("#browse-category", Select).value = "unreleased"
            app.query_one("#browse-era", Select).value = "DRFL"
            await pilot.pause()
            await app.screen._search_worker.wait()
            await pilot.pause()
            await pilot.press("down", "3", "2")
            await pilot.pause()
            assert app.query_one("#browse-query", Input).value == ""
            assert app.query_one("#browse-category", Select).value == "unreleased"
            assert app.query_one("#browse-era", Select).value == "DRFL"
            assert "> Two" in _text(app, "#browse-results")

            await pilot.press("r")
            await app.screen._search_worker.wait()
            await pilot.pause()
            assert calls[-1] == ("", {"category": "unreleased", "era": "DRFL", "page": 1, "page_size": 50, "refresh": True})

    asyncio.run(scenario())


def test_new_filter_only_search_supersedes_stale_filter_results(tmp_path):
    first_started = Event()
    release_first = Event()

    def search(settings, query, **kwargs):
        if kwargs["era"] == "DRFL":
            first_started.set()
            release_first.wait(timeout=5)
            return (_result(1, "Stale Era"),)
        return (_result(1, "Fresh Era"),)

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            era = app.query_one("#browse-era", Select)
            era.value = "DRFL"
            era.focus()
            await pilot.pause()
            await asyncio.to_thread(first_started.wait, 2)

            era.value = "JW3"
            era.focus()
            await pilot.pause()
            current = app.screen._search_worker
            assert current is not None
            await current.wait()
            await pilot.pause()
            assert "Fresh Era" in _text(app, "#browse-results")

            release_first.set()
            await pilot.pause()
            assert "Stale Era" not in _text(app, "#browse-results")

    try:
        asyncio.run(scenario())
    finally:
        release_first.set()


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
            app.query_one("#browse-category", Select).value = "unreleased"
            app.query_one("#browse-era", Select).value = "DRFL"
            await _submit(app, pilot, "rental")

            assert calls[-1] == ("rental", {"category": "unreleased", "era": "DRFL", "page": 1, "page_size": 50, "refresh": False})
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
            assert detail_calls == [(2, {"selection_index": 2})]
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
            assert calls[-1] == ("persist", {"category": None, "era": None, "page": 1, "page_size": 50, "refresh": True})

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


def test_pagination_next_previous_home_refresh_and_later_page_details(tmp_path):
    calls = []
    detail_ids = []

    def search(settings, query, **kwargs):
        calls.append((query, kwargs))
        page = kwargs["page"]
        if page == 1:
            results = tuple(_result(index, f"Page One {index}") for index in range(1, 51))
            return CataloguePage(results, 1, 50, 75, 2, None)
        results = tuple(_result(index, f"Page Two {index}") for index in range(51, 76))
        return CataloguePage(results, 2, 50, 75, None, 1)

    def details(settings, song_id, **kwargs):
        detail_ids.append(song_id)
        result = _result(song_id, f"Page Two {song_id}")
        return _details(result, synced="[00:01.00] later page")

    async def scenario():
        app = _app(tmp_path, search=search, details=details)
        async with app.run_test(size=(120, 32)) as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "page")
            assert "Result 1 of 50 loaded" in _text(app, "#browse-status")
            assert "Page 1 of 2 · Results 1–50 of 75" in _text(app, "#browse-page-position")
            initial_calls = len(calls)
            await pilot.press("p")
            await pilot.pause()
            assert len(calls) == initial_calls

            await pilot.press("n")
            await app.screen._search_worker.wait()
            await pilot.pause()
            assert "Page 2 of 2 · Results 51–75 of 75" in _text(app, "#browse-page-position")
            assert not app.query_one("#browse-next").available
            assert "> Page Two 51" in _text(app, "#browse-results")
            await pilot.press("enter")
            await app.screen._details_worker.wait()
            await pilot.pause()
            assert detail_ids == [51]
            assert "later page" in _text(app, "#browse-details")

            await pilot.press("r")
            await app.screen._search_worker.wait()
            assert calls[-1][1]["page"] == 2 and calls[-1][1]["refresh"] is True

            await pilot.press("p")
            await app.screen._search_worker.wait()
            await pilot.press("n")
            await app.screen._search_worker.wait()
            await pilot.press("home")
            await pilot.pause()
            assert app.screen.selected_index == 0
            assert "Page 2 of 2 · Results 51–75 of 75" in _text(app, "#browse-page-position")

    asyncio.run(scenario())


def test_loaded_page_scrolls_all_fifty_results_and_supports_list_navigation(tmp_path):
    calls = []

    def search(settings, query, **kwargs):
        calls.append(kwargs.copy())
        page = kwargs["page"]
        start = (page - 1) * 50 + 1
        results = tuple(_result(index, f"Song {index}") for index in range(start, start + 50))
        return CataloguePage(results, page, 50, 1485, page + 1, page - 1 if page > 1 else None)

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test(size=(80, 24)) as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "songs")
            scroll = app.query_one("#browse-results-scroll", VerticalScroll)
            rendered = _text(app, "#browse-results")

            assert len(app.screen.results) == 50
            assert "Song 1" in rendered and "Song 50" in rendered
            assert scroll.max_scroll_y > 0
            assert app.query_one("#browse-pagination").region.height > 0
            assert app.query_one("#browse-pagination").region.bottom <= app.screen.region.bottom
            assert "Page 1 of 30 · Results 1–50 of 1,485" in _text(app, "#browse-page-position")
            assert not app.query_one("#browse-previous").available
            assert "[p Previous]" in _text(app, "#browse-previous")
            assert "[n Next]" in _text(app, "#browse-next")
            assert "a add" in _text(app, "#browse-shortcuts").lower()

            for _ in range(34):
                await pilot.press("down")
            await pilot.pause()
            assert app.screen.selected_index == 34
            assert "> Song 35" in _text(app, "#browse-results")
            assert "Song 35" in _text(app, "#browse-details")
            assert scroll.scroll_y <= 34 < scroll.scroll_y + scroll.size.height

            await pilot.press("end")
            await pilot.pause()
            assert app.screen.selected_index == 49
            assert "> Song 50" in _text(app, "#browse-results")
            assert scroll.scroll_y <= 49 < scroll.scroll_y + scroll.size.height

            await pilot.press("home", "pagedown")
            await pilot.pause()
            page_step_index = app.screen.selected_index
            assert 0 < page_step_index < 49
            assert len(calls) == 1
            await pilot.press("pageup")
            await pilot.pause()
            assert app.screen.selected_index == 0

            await pilot.press("end")
            await pilot.pause()
            assert scroll.scroll_y > 0
            clicked = await pilot.click("#browse-next")
            assert clicked, (
                app.query_one("#browse-next").region,
                app.query_one("#browse-pagination").region,
            )
            await pilot.pause()
            await app.screen._search_worker.wait()
            await pilot.pause()
            assert calls[-1]["page"] == 2
            assert app.screen.selected_index == 0
            assert scroll.scroll_y == 0
            assert "Page 2 of 30 · Results 51–100 of 1,485" in _text(app, "#browse-page-position")
            assert app.query_one("#browse-previous").available

            await pilot.click("#browse-previous")
            await pilot.pause()
            await app.screen._search_worker.wait()
            await pilot.pause()
            assert calls[-1]["page"] == 1

    asyncio.run(scenario())


def test_browse_help_distinguishes_loaded_result_scrolling_from_api_pages(tmp_path):
    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: ())
        async with app.run_test(size=(80, 24)) as pilot:
            await _open_browse(app, pilot)
            await pilot.press("question_mark")
            assert app.screen.__class__.__name__ == "HelpScreen"
            help_text = _text(app, "#help-content")
            assert "Next / previous catalogue page" in help_text
            assert "Scroll loaded results" in help_text
            assert "First / last result" in help_text
            await pilot.press("escape")
            assert app.screen.id == "screen-browse"

    asyncio.run(scenario())


def test_global_help_covers_sections_scrolls_and_traps_navigation(tmp_path):
    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: ())
        async with app.run_test(size=(70, 22)) as pilot:
            for section in ("dashboard", "browse", "library", "downloads", "settings"):
                if app.focused is not None and isinstance(app.focused, Input):
                    await pilot.press("escape")
                await pilot.press(str(("dashboard", "browse", "library", "downloads", "settings").index(section) + 1))
                await pilot.press("question_mark")
                assert app.screen.__class__.__name__ == "HelpScreen"
                guide = _text(app, "#help-content")
                for heading in ("Global", "Browse", "Library", "Downloads", "Settings", "Confirmations"):
                    assert heading in guide
                scroll = app.query_one("#help-scroll", VerticalScroll)
                assert scroll.max_scroll_y > 0
                await pilot.press("pagedown")
                assert scroll.scroll_y > 0
                await pilot.press("2")
                assert app.screen.__class__.__name__ == "HelpScreen"
                await pilot.press("escape")
                assert app.screen.id == f"screen-{section}"

    asyncio.run(scenario())


def test_search_input_accepts_q_and_help_can_open_while_focused(tmp_path):
    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: ())
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            field = app.query_one("#browse-query", Input)
            field.focus()
            await pilot.press("q", "1", "0")
            assert field.value == "q10"
            assert app.screen.id == "screen-browse"
            await pilot.press("question_mark")
            assert app.screen.__class__.__name__ == "HelpScreen"
            await pilot.press("escape")
            assert app.screen.id == "screen-browse"
            await pilot.press("escape", "3")
            assert app.screen.id == "screen-library"

    asyncio.run(scenario())


def test_help_inventories_app_bindings_and_focus_palette():
    guide = guide_text()
    for label in ("Switch sections", "Refresh current section", "Open Help", "Quit",
                  "Mark or unmark", "Download entire queue", "Preview and maintain",
                  "Open Library Issues",
                  "Review duplicate recordings",
                  "Preview metadata repairs",
                  "Choose and lock a catalogue match", "Unlock and clear a manual match",
                  "Inspect setting", "Confirm immediately"):
        assert label in guide
    assert "#browse-controls Input:focus" in JuiceLyricsApp.CSS
    assert "#library-controls Input:focus" in JuiceLyricsApp.CSS
    assert "SelectOverlay:focus" in JuiceLyricsApp.CSS
    assert "background-tint: transparent" in JuiceLyricsApp.CSS
    assert "#browse-controls Input > .input--cursor" in JuiceLyricsApp.CSS


def test_fifty_result_page_remains_scrollable_at_realistic_terminal_sizes(tmp_path):
    results = tuple(_result(index, f"Visible Song {index}") for index in range(1, 51))

    async def scenario(size):
        app = _app(
            tmp_path,
            search=lambda settings, query, **kwargs: CataloguePage(results, 1, 50, 1485, 2, None),
        )
        async with app.run_test(size=size) as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "visible")
            scroll = app.query_one("#browse-results-scroll", VerticalScroll)
            pagination = app.query_one("#browse-pagination")
            assert len(app.screen.results) == 50
            assert 5 <= scroll.size.height < 50
            assert scroll.max_scroll_y > 0
            assert pagination.region.height > 0
            assert pagination.region.bottom <= app.screen.region.bottom

    for size in ((80, 24), (100, 30), (120, 40)):
        asyncio.run(scenario(size))


def test_filter_change_resets_pagination_to_first_page(tmp_path):
    calls = []

    def search(settings, query, **kwargs):
        calls.append(kwargs.copy())
        result = (_result(1, "Result"),)
        return CataloguePage(result, kwargs["page"], 50, 60, 2 if kwargs["page"] == 1 else None, 1 if kwargs["page"] > 1 else None)

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "filter reset")
            await pilot.press("n")
            await app.screen._search_worker.wait()
            assert calls[-1]["page"] == 2

            app.query_one("#browse-era", Select).value = "DRFL"
            await pilot.pause()
            await app.screen._search_worker.wait()
            assert calls[-1]["page"] == 1
            assert calls[-1]["era"] == "DRFL"

    asyncio.run(scenario())


def test_stale_page_response_cannot_replace_new_first_page(tmp_path):
    page_two_started = Event()
    release_page_two = Event()

    def search(settings, query, **kwargs):
        if kwargs["page"] == 2:
            page_two_started.set()
            release_page_two.wait(timeout=5)
            return CataloguePage((_result(51, "Stale Page Two"),), 2, 50, 60, None, 1)
        return CataloguePage((_result(1, f"Fresh {query}"),), 1, 50, 60, 2, None)

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "old")
            await pilot.press("n")
            await asyncio.to_thread(page_two_started.wait, 2)

            field = app.query_one("#browse-query", Input)
            field.value = "new"
            field.focus()
            await pilot.press("enter")
            current = app.screen._search_worker
            assert current is not None
            await current.wait()
            await pilot.pause()
            assert "Fresh new" in _text(app, "#browse-results")

            release_page_two.set()
            await pilot.pause()
            assert "Stale Page Two" not in _text(app, "#browse-results")

    try:
        asyncio.run(scenario())
    finally:
        release_page_two.set()


def test_selector_keyboard_confirmation_uses_canonical_value(tmp_path):
    calls = []

    async def scenario():
        app = _app(tmp_path, search=lambda settings, query, **kwargs: calls.append(kwargs) or ())
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            category = app.query_one("#browse-category", Select)
            category.focus()
            await pilot.press("enter", "down", "down", "enter")
            await pilot.pause()
            worker = app.screen._search_worker
            assert worker is not None
            await worker.wait()
            assert category.value == "unreleased"
            assert calls[-1]["category"] == "unreleased"

    asyncio.run(scenario())


def test_filter_metadata_failure_disables_selectors_but_title_search_survives(tmp_path):
    calls = []

    def broken_filters(*args, **kwargs):
        raise RuntimeError("metadata endpoint unavailable")

    async def scenario():
        app = _app(
            tmp_path,
            search=lambda settings, query, **kwargs: calls.append(query) or (),
            filters=broken_filters,
        )
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            worker = app.screen._filters_worker
            assert worker is not None
            await worker.wait()
            await pilot.pause()
            assert app.query_one("#browse-category", Select).disabled
            assert app.query_one("#browse-era", Select).disabled
            assert "Filter metadata unavailable" in _text(app, "#browse-status")
            await _submit(app, pilot, "Rental")
            assert calls == ["Rental"]

    asyncio.run(scenario())


def test_add_to_queue_is_immediate_and_does_not_download(tmp_path):
    calls = []
    song = _result(1, "Rental")

    def planner(settings, selections):
        calls.append(selections)
        return QueueAddResult(QueueAddStatus.READY, "Ready", plan=_queue_plan(tmp_path, selections[0]))

    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: (song,), queue_plan=planner)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "rental")
            browse = app.screen
            await pilot.press("a")
            await browse._queue_plan_worker.wait()
            await _wait_queue_add(browse, pilot)
            assert app.screen.id == "screen-browse"
            assert len(calls) == 1
            assert "not configured" in _text(app, "#browse-status")

    asyncio.run(scenario())


def test_confirm_adds_once_preserves_browse_and_can_open_refreshed_downloads(tmp_path):
    created = []
    song = _result(1, "Rental")
    queued = DownloadQueueItem(
        reference="internal:0", song_id="1", title="Rental", artist="Juice WRLD",
        category="unreleased", era="DRFL", destination=tmp_path / "music" / "Rental.mp3",
        status=DownloadQueueItemStatus.QUEUED, bytes_written=0, expected_bytes=None,
        failure_stage=None, error=None, retryable=True,
        queued_at="2026-08-30T12:00:00+00:00",
    )

    def planner(settings, selections):
        return QueueAddResult(QueueAddStatus.READY, "Ready", plan=_queue_plan(tmp_path, selections[0]))

    def creator(plan):
        created.append(plan)
        return QueueAddResult(QueueAddStatus.ADDED, "Added 1 song to the download queue.", added_count=1)

    def downloads():
        items = (queued,) if created else ()
        return DownloadQueueSnapshot(items, len(items), 0, 0, 0, 0)

    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: (song,), queue_plan=planner,
                   queue_add=creator, downloads=downloads)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "rental")
            browse = app.screen
            await pilot.press("a")
            await browse._queue_plan_worker.wait()
            await _wait_queue_add(browse, pilot)
            assert len(created) == 1
            assert "not started" in _text(app, "#browse-status")
            await pilot.press("4")
            await pilot.pause()
            if app.screen._refresh_worker is not None:
                await app.screen._refresh_worker.wait()
                await pilot.pause()
            assert app.screen.id == "screen-downloads"
            assert "Rental" in _text(app, "#download-queue")
            await pilot.press("2")
            await pilot.pause()
            assert app.query_one("#browse-query", Input).value == "rental"
            assert "> Rental" in _text(app, "#browse-results")

    asyncio.run(scenario())


def test_add_to_queue_rejections_and_input_guard(tmp_path):
    plan_calls = []
    available = _result(1, "Available")
    unavailable = _result(2, "Unavailable", downloadable=False)

    def planner(settings, selections):
        plan_calls.append(selections[0].title)
        return QueueAddResult(QueueAddStatus.ALREADY_QUEUED, "Available is already in the queue.")

    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: (available, unavailable), queue_plan=planner)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "songs")
            field = app.query_one("#browse-query", Input)
            field.focus()
            await pilot.press("a")
            assert plan_calls == []
            category = app.query_one("#browse-category", Select)
            category.focus()
            await pilot.press("enter")
            assert category.expanded
            await pilot.press("a")
            assert plan_calls == []
            await pilot.press("escape")
            app.screen.set_focus(None)
            await pilot.press("a")
            await app.screen._queue_plan_worker.wait()
            await pilot.pause()
            assert "already in the queue" in _text(app, "#browse-status")
            await pilot.press("down", "a")
            assert plan_calls == ["Available"]
            assert "Media unavailable" in _text(app, "#browse-status")

    asyncio.run(scenario())


def test_add_to_queue_store_failure_is_safe_and_slow_planning_does_not_block_navigation(tmp_path):
    started = Event()
    release = Event()
    song = _result(1, "Rental")

    def slow_planner(settings, selections):
        started.set()
        release.wait(timeout=5)
        return QueueAddResult(QueueAddStatus.READY, "Ready", plan=_queue_plan(tmp_path, selections[0]))

    async def navigation_scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: (song,), queue_plan=slow_planner)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "rental")
            browse = app.screen
            await pilot.press("a")
            await asyncio.to_thread(started.wait, 2)
            assert "Checking destination" in _text(app, "#browse-status")
            await pilot.press("4")
            assert app.screen.id == "screen-downloads"
            release.set()
            await browse._queue_plan_worker.wait()
            await pilot.pause()
            assert app.screen.id == "screen-downloads"

    async def failure_scenario():
        planner = lambda settings, selections: QueueAddResult(
            QueueAddStatus.READY, "Ready", plan=_queue_plan(tmp_path, selections[0])
        )
        creator = lambda plan: QueueAddResult(
            QueueAddStatus.SAVE_FAILED, "Unable to save the queue: permission denied."
        )
        app = _app(tmp_path, search=lambda *args, **kwargs: (song,), queue_plan=planner, queue_add=creator)
        async with app.run_test() as pilot:
            await _open_browse(app, pilot)
            await _submit(app, pilot, "rental")
            browse = app.screen
            await pilot.press("a")
            await browse._queue_plan_worker.wait()
            await _wait_queue_add(browse, pilot)
            assert "permission denied" in _text(app, "#browse-status")
            assert app.screen.id == "screen-browse"

    try:
        asyncio.run(navigation_scenario())
        asyncio.run(failure_scenario())
    finally:
        release.set()


def test_browse_marks_cursor_and_page_selection_are_independent(tmp_path):
    songs = (_result(1, "First"), _result(2, "Second"), _result(3, "Unavailable", downloadable=False))

    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: songs)
        async with app.run_test(size=(100, 30)) as pilot:
            browse = await _open_browse(app, pilot)
            await _submit(app, pilot, "songs")
            assert "[ ]" not in _text(app, "#browse-results")
            assert "a Add" in _text(app, "#browse-shortcuts")
            await pilot.press("space")
            assert set(browse.marked) == {"1"}
            assert "First" in _text(app, "#browse-results") and "[x]" in _text(app, "#browse-results")
            assert "1 song marked" in _text(app, "#browse-results-title")
            assert "a Add selected" in _text(app, "#browse-shortcuts")
            await pilot.press("down")
            assert set(browse.marked) == {"1"}
            await pilot.press("space")
            assert set(browse.marked) == {"1", "2"}
            assert "2 songs marked" in _text(app, "#browse-results-title")
            await pilot.press("M")
            assert browse.marked == {}
            await pilot.press("M")
            assert set(browse.marked) == {"1", "2"}
            await pilot.press("u")
            assert browse.marked == {}
            assert "Selection cleared" in _text(app, "#browse-status")
            assert "[ ]" not in _text(app, "#browse-results")
            assert "a Add" in _text(app, "#browse-shortcuts")

    asyncio.run(scenario())


def test_marks_span_pages_but_search_and_filter_changes_clear_them(tmp_path):
    first = _result(1, "Page One")
    second = _result(51, "Page Two")

    def search(settings, query, **kwargs):
        page = kwargs["page"]
        return CataloguePage(
            (first,) if page == 1 else (second,),
            page,
            50,
            100,
            page + 1 if page < 2 else None,
            page - 1 if page > 1 else None,
        )

    async def scenario():
        app = _app(tmp_path, search=search)
        async with app.run_test() as pilot:
            browse = await _open_browse(app, pilot)
            await _submit(app, pilot, "songs")
            await pilot.press("space")
            await pilot.pause()
            assert set(browse.marked) == {"1"}
            await pilot.press("n")
            await browse._search_worker.wait()
            await pilot.pause()
            await pilot.press("space")
            assert set(browse.marked) == {"1", "51"}
            await pilot.press("p")
            await browse._search_worker.wait()
            await pilot.pause()
            assert set(browse.marked) == {"1", "51"}
            query = app.query_one("#browse-query", Input)
            query.value = "changed"
            query.focus()
            await pilot.press("enter")
            await browse._search_worker.wait()
            await pilot.pause()
            assert browse.marked == {}
            assert "Selection cleared because the search changed" in _text(app, "#browse-status")

            browse.set_focus(None)
            await pilot.press("space")
            assert browse.marked
            category = app.query_one("#browse-category", Select)
            category.value = "unreleased"
            await pilot.pause()
            await browse._search_worker.wait()
            await pilot.pause()
            assert browse.marked == {}

    asyncio.run(scenario())


def test_batch_add_is_immediate_and_captures_stable_targets(tmp_path):
    songs = (_result(1, "First"), _result(2, "Second"), _result(9, "Already there"))
    created = []

    def planner(settings, selections):
        plan = _batch_plan(tmp_path, tuple(selections[:2]), extra=(
            QueueBatchAddItem("9", "Already there", QueueBatchAddItemStatus.ALREADY_QUEUED, "Already queued."),
        ))
        return QueueBatchAddResult(QueueBatchAddStatus.READY, "Ready", plan=plan)

    def creator(plan):
        created.append(plan)
        return QueueBatchAddResult(
            QueueBatchAddStatus.ADDED,
            "Added 2 songs · 1 already queued",
            plan=plan,
            added_count=2,
            added_song_ids=("1", "2"),
        )

    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: songs, queue_plan=planner, queue_add=creator)
        async with app.run_test(size=(80, 24)) as pilot:
            browse = await _open_browse(app, pilot)
            await _submit(app, pilot, "songs")
            await pilot.press("M", "a")
            await browse._queue_plan_worker.wait()
            await _wait_queue_add(browse, pilot)
            assert app.screen is browse
            assert len(created) == 1
            assert [item.song_id for item in created[0].eligible] == ["1", "2"]
            assert "Added 2 songs" in _text(app, "#browse-status")
            assert "1" not in browse.marked and "2" not in browse.marked

    asyncio.run(scenario())


def test_browse_batch_help_shortcuts_and_unavailable_mark_guard(tmp_path):
    songs = (_result(1, "Available"), _result(2, "Unavailable", downloadable=False))

    async def scenario():
        app = _app(tmp_path, search=lambda *args, **kwargs: songs)
        async with app.run_test(size=(80, 24)) as pilot:
            browse = await _open_browse(app, pilot)
            await _submit(app, pilot, "songs")
            shortcuts = app.query_one("#browse-shortcuts")
            assert shortcuts.region.height == 1
            shortcuts_text = _text(app, "#browse-shortcuts")
            assert "a add" in shortcuts_text.lower()
            assert "enter details" in shortcuts_text.lower()
            assert "M" not in shortcuts_text and "u clear" not in shortcuts_text.lower()
            results_scroll = app.query_one("#browse-results-scroll", VerticalScroll)
            assert results_scroll.region.height >= 5
            await pilot.press("down", "space")
            assert browse.marked == {}
            assert "cannot be marked" in _text(app, "#browse-status")
            await pilot.press("question_mark")
            help_text = _text(app, "#help-content")
            assert "Mark or unmark song" in help_text
            assert "Toggle marks on this page" in help_text
            assert "Add current or marked songs" in help_text
            assert "Switch sections" in help_text

    asyncio.run(scenario())


def test_disappeared_mark_is_revalidated_as_unavailable_not_replaced_by_row_index(tmp_path):
    original = _result(1, "Original")
    replacement = _result(2, "Replacement")
    planned = []

    def search(settings, query, **kwargs):
        return (replacement,) if kwargs.get("refresh") else (original,)

    def planner(settings, selections):
        planned.extend(selections)
        plan = QueueBatchAddPlan((QueueBatchAddItem(
            "1", "Original", QueueBatchAddItemStatus.UNAVAILABLE, "No longer available."
        ),))
        return QueueBatchAddResult(QueueBatchAddStatus.NOTHING_TO_ADD, "No songs added · 1 unavailable", plan=plan)

    async def scenario():
        app = _app(tmp_path, search=search, queue_plan=planner)
        async with app.run_test() as pilot:
            browse = await _open_browse(app, pilot)
            await _submit(app, pilot, "song")
            await pilot.press("space")
            await pilot.pause()
            await pilot.press("r")
            await browse._search_worker.wait()
            await pilot.pause()
            assert set(browse.marked) == {"1"}
            assert browse.results[0].song_id == 2
            await pilot.press("a")
            await browse._queue_plan_worker.wait()
            await pilot.pause()
            assert [item.song_id for item in planned] == [1]
            assert not planned[0].downloadable
            assert app.screen is browse
            assert "unavailable" in _text(app, "#browse-status")

    asyncio.run(scenario())

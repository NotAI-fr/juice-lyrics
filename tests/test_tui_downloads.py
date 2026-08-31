import asyncio
from pathlib import Path
import sys
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from textual.containers import VerticalScroll

from juice_lyrics.config.settings import Settings
from juice_lyrics.services import (
    CatalogueFilterMetadata,
    LibraryStatus,
    QueueFailureStage,
    QueueItem,
    QueueJob,
    QueueSnapshot,
    QueueStatus,
)
from juice_lyrics.tui import JuiceLyricsApp


_ACTIVE = {
    QueueStatus.CHECKING_EXISTING,
    QueueStatus.DOWNLOADING,
    QueueStatus.VALIDATING,
    QueueStatus.POST_PROCESSING,
}


def _item(
    tmp_path: Path,
    title: str,
    status: QueueStatus,
    *,
    failure_stage: QueueFailureStage | None = None,
    error: str | None = None,
    postprocessing_retryable: bool = False,
) -> QueueItem:
    return QueueItem(
        title=title,
        destination=tmp_path / f"{title}.mp3",
        status=status,
        stored_state=status.value,
        bytes_written=100 if status in {QueueStatus.COMPLETED, QueueStatus.FAILED} else 25,
        expected_bytes=100,
        resumed=False,
        error=error,
        retryable=status not in {QueueStatus.COMPLETED, QueueStatus.SKIPPED, QueueStatus.UNKNOWN},
        failure_stage=failure_stage,
        postprocessing_retryable=postprocessing_retryable,
    )


def _job(
    number: int,
    job_id: str,
    items: tuple[QueueItem, ...],
    *,
    created_at: str = "2026-08-30T12:00:00+00:00",
) -> QueueJob:
    statuses = tuple(item.status for item in items)
    if QueueStatus.FAILED in statuses:
        status = QueueStatus.FAILED
    elif statuses and all(value in {QueueStatus.COMPLETED, QueueStatus.SKIPPED} for value in statuses):
        status = QueueStatus.COMPLETED
    elif any(value in _ACTIVE for value in statuses):
        status = next(value for value in statuses if value in _ACTIVE)
    elif not statuses:
        status = QueueStatus.COMPLETED
    else:
        status = QueueStatus.PENDING
    completed = sum(value in {QueueStatus.COMPLETED, QueueStatus.SKIPPED} for value in statuses)
    return QueueJob(
        display_number=number,
        job_id=job_id,
        label=items[0].title if len(items) == 1 else f"{items[0].title} + {len(items) - 1} more" if items else "Untitled job",
        created_at=created_at,
        destination=items[0].destination if len(items) == 1 else None,
        total_item_count=len(items),
        pending_item_count=sum(value in {QueueStatus.PENDING, QueueStatus.UNKNOWN} for value in statuses),
        active_item_count=sum(value in _ACTIVE for value in statuses),
        completed_item_count=completed,
        failed_item_count=sum(value is QueueStatus.FAILED for value in statuses),
        status=status,
        stored_state=status.value,
        retryable=any(item.retryable for item in items),
        deletion_allowed=not any(value in _ACTIVE for value in statuses),
        items=items,
        updated_at="2026-08-30T12:05:00+00:00",
    )


def _snapshot(*jobs: QueueJob) -> QueueSnapshot:
    return QueueSnapshot(
        jobs=jobs,
        total_job_count=len(jobs),
        active_job_count=sum(job.status in _ACTIVE for job in jobs),
        pending_job_count=sum(job.status in {QueueStatus.PENDING, QueueStatus.UNKNOWN} for job in jobs),
        completed_job_count=sum(job.status is QueueStatus.COMPLETED for job in jobs),
        failed_job_count=sum(job.status is QueueStatus.FAILED for job in jobs),
    )


def _app(tmp_path: Path, provider) -> JuiceLyricsApp:
    empty = _snapshot()
    return JuiceLyricsApp(
        Settings(music_dir=tmp_path / "music"),
        library_status_provider=lambda settings: LibraryStatus(
            settings.music_dir, 0, 0, 0, 0, 0, 0, 0, ()
        ),
        queue_snapshot_provider=lambda: empty,
        downloads_queue_provider=provider,
        catalogue_filters_provider=lambda *args, **kwargs: CatalogueFilterMetadata((), ()),
    )


def _text(app: JuiceLyricsApp, selector: str) -> str:
    return str(app.query_one(selector).render())


async def _open_downloads(app: JuiceLyricsApp, pilot):
    await pilot.press("4")
    await pilot.pause()
    worker = app.screen._refresh_worker
    if worker is not None:
        await worker.wait()
        await pilot.pause()
    return app.screen


def test_downloads_replaces_placeholder_and_renders_empty_and_error_states(tmp_path):
    async def empty_scenario():
        app = _app(tmp_path, _snapshot)
        async with app.run_test() as pilot:
            screen = await _open_downloads(app, pilot)
            assert screen.__class__.__name__ == "DownloadsScreen"
            assert "No queued or failed songs" in _text(app, "#download-queue")
            assert "Queued 0 · Downloading 0 · Processing 0 · Failed 0 · Completed 0" in _text(
                app, "#downloads-summary"
            )

    async def error_scenario():
        app = _app(
            tmp_path,
            lambda: (_ for _ in ()).throw(RuntimeError("job store is malformed")),
        )
        async with app.run_test() as pilot:
            await _open_downloads(app, pilot)
            assert "Queue unavailable: job store is malformed" in _text(app, "#downloads-status")
            assert app.screen.id == "screen-downloads"

    async def empty_job_scenario():
        empty_job = _job(1, "empty-job", ())
        app = _app(tmp_path, lambda: _snapshot(empty_job))
        async with app.run_test() as pilot:
            await _open_downloads(app, pilot)
            assert "No active queue item selected" in _text(app, "#download-details")
            assert "Completed 0" in _text(app, "#downloads-summary")

    asyncio.run(empty_scenario())
    asyncio.run(error_scenario())
    asyncio.run(empty_job_scenario())


def test_slow_queue_loading_does_not_block_navigation_or_quit(tmp_path):
    started = Event()
    release = Event()

    def provider():
        started.set()
        release.wait(timeout=5)
        return _snapshot()

    async def navigation_scenario():
        app = _app(tmp_path, provider)
        async with app.run_test() as pilot:
            await pilot.press("4")
            await asyncio.to_thread(started.wait, 2)
            assert "Loading queue" in _text(app, "#download-queue")
            downloads = app.screen
            worker = downloads._refresh_worker
            await pilot.press("2")
            await pilot.pause()
            assert app.screen.id == "screen-browse"
            release.set()
            await worker.wait()
            await pilot.pause()
            assert downloads._refresh_worker is None
            await pilot.press("4")
            await pilot.pause()
            assert app.screen.id == "screen-downloads"
            assert downloads._refresh_worker is not None
            await downloads._refresh_worker.wait()

    async def quit_scenario():
        quit_started = Event()
        quit_release = Event()

        def quit_provider():
            quit_started.set()
            quit_release.wait(timeout=5)
            return _snapshot()

        app = _app(tmp_path, quit_provider)
        async with app.run_test() as pilot:
            await pilot.press("4")
            await asyncio.to_thread(quit_started.wait, 2)
            await pilot.press("q")
            assert not app.is_running
            quit_release.set()

    try:
        asyncio.run(navigation_scenario())
        asyncio.run(quit_scenario())
    finally:
        release.set()


def test_queue_totals_order_navigation_details_failures_and_retry_information(tmp_path):
    queued = _job(1, "queued-id", (_item(tmp_path, "Queued Song", QueueStatus.PENDING),))
    active = _job(2, "active-id", (_item(tmp_path, "Active Song", QueueStatus.DOWNLOADING),))
    completed = _job(3, "complete-id", (_item(tmp_path, "Done Song", QueueStatus.COMPLETED),))
    failed = _job(
        4,
        "failed-id",
        (
            _item(tmp_path, "Finished Track", QueueStatus.COMPLETED),
            _item(
                tmp_path,
                "Lyrics Track",
                QueueStatus.FAILED,
                failure_stage=QueueFailureStage.LYRICS,
                error="Audio downloaded\nlyrics verification failed",
                postprocessing_retryable=True,
            ),
            _item(
                tmp_path,
                "Transport Track",
                QueueStatus.FAILED,
                failure_stage=QueueFailureStage.TRANSPORT,
                error="connection reset",
            ),
            _item(
                tmp_path,
                "Validation Track",
                QueueStatus.FAILED,
                failure_stage=QueueFailureStage.VALIDATION,
                error="size mismatch",
            ),
            _item(
                tmp_path,
                "LRC Track",
                QueueStatus.FAILED,
                failure_stage=QueueFailureStage.LRC,
                error="lyrics directory unavailable",
            ),
            _item(
                tmp_path,
                "State Track",
                QueueStatus.FAILED,
                failure_stage=QueueFailureStage.STATE,
                error="state file unavailable",
            ),
        ),
    )

    async def scenario():
        app = _app(tmp_path, lambda: _snapshot(queued, active, completed, failed))
        async with app.run_test(size=(100, 30)) as pilot:
            await _open_downloads(app, pilot)
            assert "Queued 1 · Downloading 1 · Processing 0 · Failed 5 · Completed 2" in _text(
                app, "#downloads-summary"
            )
            rendered = _text(app, "#download-queue")
            assert rendered.index("Queued Song") < rendered.index("Active Song") < rendered.index("Lyrics Track")
            assert "Done Song" not in rendered
            assert "> Queued" in rendered
            assert "queued-id" not in rendered and "failed-id" not in rendered

            await pilot.press("down", "j")
            await pilot.pause()
            assert app.screen.selected_item.title == "Lyrics Track"
            assert "Lyrics Track" in _text(app, "#download-details")
            await pilot.press("up", "k")
            assert app.screen.selected_item.title == "Queued Song"

            await pilot.press("end")
            await pilot.pause()
            details = _text(app, "#download-details")
            assert app.screen.selected_item.title == "State Track"
            assert "Job ID" not in details
            assert "Library update failed" in details
            assert "Internal ref" in details

            await pilot.press("home")
            assert app.screen.selected_item.title == "Queued Song"

    asyncio.run(scenario())


def test_many_jobs_and_tracks_scroll_with_details_mode_at_80x24(tmp_path):
    jobs = tuple(
        _job(index, f"job-{index}", (_item(tmp_path, f"Song {index}", QueueStatus.PENDING),))
        for index in range(1, 21)
    )
    track_job = _job(
        20,
        "job-20",
        tuple(_item(tmp_path, f"Track {index}", QueueStatus.PENDING) for index in range(1, 21)),
    )
    jobs = (*jobs[:-1], track_job)

    async def scenario():
        app = _app(tmp_path, lambda: _snapshot(*jobs))
        async with app.run_test(size=(80, 24)) as pilot:
            await _open_downloads(app, pilot)
            job_scroll = app.query_one("#download-queue-scroll", VerticalScroll)
            assert "-downloads-narrow" in app.screen.classes
            assert job_scroll.size.height >= 5
            assert job_scroll.max_scroll_y > 0
            assert "r refresh" in _text(app, "#downloads-position")

            await pilot.press("end")
            await pilot.pause()
            assert app.screen.selected_item.title == "Track 20"
            assert job_scroll.scroll_y > 0
            assert job_scroll.scroll_y <= 38 < job_scroll.scroll_y + job_scroll.size.height

            await pilot.press("enter")
            await pilot.pause()
            assert app.screen.has_class("-details-mode")
            details_scroll = app.query_one("#download-details-scroll", VerticalScroll)
            await pilot.press("pagedown")
            await pilot.pause()
            assert details_scroll.scroll_y >= 0
            await pilot.press("escape")
            assert not app.screen.has_class("-details-mode")

            await pilot.press("pageup")
            await pilot.pause()
            assert app.screen.selected_index < 38

    asyncio.run(scenario())


def test_refresh_preserves_or_safely_replaces_selection(tmp_path):
    first = _job(1, "first", (_item(tmp_path, "First", QueueStatus.PENDING),))
    keep = _job(2, "keep", (_item(tmp_path, "Keep", QueueStatus.PENDING),))
    replacement = _job(1, "replacement", (_item(tmp_path, "Replacement", QueueStatus.COMPLETED),))
    responses = [_snapshot(first, keep), _snapshot(keep, replacement), _snapshot(replacement)]

    def provider():
        return responses.pop(0)

    async def scenario():
        app = _app(tmp_path, provider)
        async with app.run_test() as pilot:
            await _open_downloads(app, pilot)
            await pilot.press("down")
            assert app.screen.selected_item.title == "Keep"

            await pilot.press("r")
            await app.screen._refresh_worker.wait()
            await pilot.pause()
            assert app.screen.selected_item.title == "Keep"

            await pilot.press("r")
            await app.screen._refresh_worker.wait()
            await pilot.pause()
            assert app.screen.selected_item is None

    asyncio.run(scenario())


def test_newer_refresh_supersedes_stale_queue_result(tmp_path):
    stale_started = Event()
    release_stale = Event()
    calls = 0
    initial = _job(1, "initial", (_item(tmp_path, "Initial", QueueStatus.PENDING),))
    stale = _job(1, "stale", (_item(tmp_path, "Stale", QueueStatus.FAILED),))
    fresh = _job(1, "fresh", (_item(tmp_path, "Fresh", QueueStatus.COMPLETED),))

    def provider():
        nonlocal calls
        calls += 1
        if calls == 1:
            return _snapshot(initial)
        if calls == 2:
            stale_started.set()
            release_stale.wait(timeout=5)
            return _snapshot(stale)
        return _snapshot(fresh)

    async def scenario():
        app = _app(tmp_path, provider)
        async with app.run_test() as pilot:
            await _open_downloads(app, pilot)
            await pilot.press("r")
            await asyncio.to_thread(stale_started.wait, 2)
            await pilot.press("r")
            current = app.screen._refresh_worker
            await current.wait()
            await pilot.pause()
            assert app.screen.selected_item is None
            release_stale.set()
            await pilot.pause()
            assert "Stale" not in _text(app, "#download-queue")

    try:
        asyncio.run(scenario())
    finally:
        release_stale.set()


def test_downloads_screen_is_read_only_and_uses_no_live_dependencies(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.downloader as downloader
    import juice_lyrics.acquisition.jobs as jobs_module
    import juice_lyrics.acquisition.runner as runner

    def mutation(*args, **kwargs):
        raise AssertionError("queue mutation attempted")

    monkeypatch.setattr(downloader, "download_to", mutation)
    monkeypatch.setattr(runner, "run_job", mutation)
    monkeypatch.setattr(jobs_module.JobStore, "save", mutation)
    monkeypatch.setattr(jobs_module.JobStore, "create", mutation)
    monkeypatch.setattr(jobs_module.JobStore, "delete", mutation)
    view = _job(1, "read-only", (_item(tmp_path, "Read Only", QueueStatus.PENDING),))

    async def scenario():
        app = _app(tmp_path, lambda: _snapshot(view))
        async with app.run_test() as pilot:
            await _open_downloads(app, pilot)
            await pilot.press("down", "up", "enter", "pagedown", "escape", "r")
            await app.screen._refresh_worker.wait()
            await pilot.pause()

    asyncio.run(scenario())
    assert not list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.rglob("*.part"))
    assert not list(tmp_path.rglob("*.lrc"))
    assert not list(tmp_path.rglob("*.mp3"))

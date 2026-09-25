import asyncio
from pathlib import Path
import sys
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from textual.containers import VerticalScroll

from juice_lyrics.config.settings import Settings
from juice_lyrics.services import (
    CatalogueFilterMetadata,
    DownloadExecutionAction,
    DownloadExecutionPlan,
    DownloadExecutionResult,
    DownloadExecutionStatus,
    DownloadAllPlan,
    DownloadAllResult,
    DownloadBatchStatus,
    DownloadProgress,
    DownloadQueueItemStatus,
    LibraryStatus,
    QueueFailureStage,
    QueueItem,
    QueueJob,
    QueueSnapshot,
    QueueStatus,
    QueueMutationResult,
    QueueMutationStatus,
)
from juice_lyrics.services.download_queue import DownloadRetryAction, DownloadRetryPlan, DownloadRetryResult, DownloadRetryStatus
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


def _app(tmp_path: Path, provider, *, plan=None, execute=None, batch_plan=None, batch_execute=None, history=None) -> JuiceLyricsApp:
    empty = _snapshot()
    plan = plan or (lambda settings, reference: DownloadExecutionResult(
        DownloadExecutionStatus.NOT_ELIGIBLE,
        "Not eligible",
    ))
    execute = execute or (lambda settings, plan, **kwargs: DownloadExecutionResult(
        DownloadExecutionStatus.FAILED,
        "Execution provider was not configured",
        plan=plan,
    ))
    return JuiceLyricsApp(
        Settings(music_dir=tmp_path / "music"),
        library_status_provider=lambda settings: LibraryStatus(
            settings.music_dir, 0, 0, 0, 0, 0, 0, 0, ()
        ),
        queue_snapshot_provider=lambda: empty,
        downloads_queue_provider=provider,
        download_plan_provider=plan,
        download_execution_provider=execute,
        download_all_plan_provider=batch_plan or (lambda settings: DownloadAllPlan((), 0, 0, 0, 0)),
        download_all_execution_provider=batch_execute or (lambda settings, plan, **kwargs: DownloadAllResult(DownloadBatchStatus.COMPLETED, "Download all finished")),
        queue_history_provider=history or (lambda: None),
        catalogue_filters_provider=lambda *args, **kwargs: CatalogueFilterMetadata((), ()),
    )


def _text(app: JuiceLyricsApp, selector: str) -> str:
    return str(app.query_one(selector).render())


def _execution_plan(tmp_path: Path, reference: str, title: str = "Queued Song"):
    return DownloadExecutionPlan(
        reference=reference,
        job_id=reference.rpartition(":")[0],
        item_index=int(reference.rpartition(":")[2]),
        song_id="94902",
        title=title,
        artist="Juice WRLD",
        destination=tmp_path / f"{title}.mp3",
        current_status=DownloadQueueItemStatus.QUEUED,
        action=DownloadExecutionAction.START,
    )


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
            assert "Nothing waiting to download" in _text(app, "#download-queue")
            assert "Waiting 0 · Downloading 0 · Adding lyrics 0 · Failed 0 · Complete 0" in _text(
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
            assert "Complete 0" in _text(app, "#downloads-summary")

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
            assert "Waiting 1 · Downloading 1 · Adding lyrics 0 · Failed 5 · Complete 2" in _text(
                app, "#downloads-summary"
            )
            rendered = _text(app, "#download-queue")
            assert rendered.index("Queued Song") < rendered.index("Active Song") < rendered.index("Lyrics Track")
            assert "Done Song" not in rendered
            assert "> Waiting" in rendered
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
            assert app.query_one("#downloads-position").region.height == 1

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


def test_downloads_shortcuts_and_context_guidance_are_visible(tmp_path):
    queued = _job(1, "queued", (_item(tmp_path, "Queued", QueueStatus.PENDING),))
    failed = _job(2, "failed", (_item(tmp_path, "Failed", QueueStatus.FAILED, failure_stage=QueueFailureStage.TRANSPORT),))
    async def scenario():
        app = _app(tmp_path, lambda: _snapshot(queued, failed))
        async with app.run_test(size=(120, 40)) as pilot:
            await _open_downloads(app, pilot)
            bar = _text(app, "#downloads-position")
            assert "A Queue" in bar and "d Download" in bar and "Enter Details" in bar
            assert "x Remove" not in bar and "c Clear" not in bar and "H Clear" not in bar
            assert "Ready to download" in _text(app, "#downloads-status")
            await pilot.press("down"); await pilot.pause()
            assert "t Retry" in _text(app, "#downloads-position")
            assert "Download failed" in _text(app, "#downloads-status")
            await pilot.press("question_mark")
            help_text = _text(app, "#help-content")
            assert "Download entire queue" in help_text and "Clear completed history" in help_text
            await pilot.press("escape")
            await pilot.press("home", "x"); await pilot.pause()
            assert app.screen.id == "screen-downloads"
    asyncio.run(scenario())


def test_one_song_download_all_cancel_then_confirm_runs_once(tmp_path):
    queued = _job(1, "one-song", (_item(tmp_path, "Only Song", QueueStatus.PENDING),))
    execution_plan = _execution_plan(tmp_path, "one-song:0", "Only Song")
    batch = DownloadAllPlan((execution_plan,), 0, 0, 0, 0)
    calls = []
    snapshots = [_snapshot(queued), _snapshot(_job(1, "done", (_item(tmp_path, "Only Song", QueueStatus.COMPLETED),)))]

    def provider():
        return snapshots[0] if len(snapshots) == 1 else snapshots.pop(0)

    def execute_batch(settings, plan, **kwargs):
        calls.append(len(plan.eligible))
        return DownloadAllResult(DownloadBatchStatus.COMPLETED, "Download all finished · 1 completed · 0 failed · 0 skipped", 1)

    async def scenario():
        app = _app(tmp_path, provider, batch_plan=lambda settings: batch, batch_execute=execute_batch)
        async with app.run_test() as pilot:
            downloads = await _open_downloads(app, pilot)
            await pilot.press("shift+a"); await pilot.pause()
            if downloads._batch_plan_worker is not None:
                await downloads._batch_plan_worker.wait(); await pilot.pause()
            assert app.screen.__class__.__name__ == "DownloadAllDialog", (_text(app, "#downloads-status"), downloads._batch_plan_worker)
            assert "Download 1 song?" in _text(app, "#download-confirm-body")
            assert "Lyrics will be added automatically." in _text(app, "#download-confirm-body")
            assert app.focused is not None and app.focused.id == "download-confirm-cancel"
            await pilot.press("enter"); await pilot.pause()
            assert calls == []
            await pilot.press("shift+a"); await pilot.pause()
            if downloads._batch_plan_worker is not None:
                await downloads._batch_plan_worker.wait(); await pilot.pause()
            await pilot.press("2"); await pilot.pause()
            assert app.screen.__class__.__name__ == "DownloadAllDialog"
            await pilot.press("tab"); await pilot.pause()
            assert app.focused is not None and app.focused.id == "download-confirm-download"
            await pilot.press("shift+tab"); await pilot.pause()
            assert app.focused is not None and app.focused.id == "download-confirm-cancel"
            await pilot.press("tab"); await pilot.pause()
            await pilot.press("enter"); await pilot.pause(0.2)
            assert calls == [1]
            assert "1 completed" in _text(app, "#downloads-status")

    asyncio.run(scenario())


def test_download_all_y_confirms_once_without_enter(tmp_path):
    queued = _job(1, "one-song", (_item(tmp_path, "Only Song", QueueStatus.PENDING),))
    plan = DownloadAllPlan((_execution_plan(tmp_path, "one-song:0", "Only Song"),), 0, 0, 0, 0)
    calls = []

    def execute(settings, batch, **kwargs):
        calls.append(batch)
        return DownloadAllResult(DownloadBatchStatus.COMPLETED, "Downloaded 1 song", 1)

    async def scenario():
        app = _app(tmp_path, lambda: _snapshot(queued), batch_plan=lambda settings: plan, batch_execute=execute)
        async with app.run_test() as pilot:
            downloads = await _open_downloads(app, pilot)
            await pilot.press("shift+a")
            if downloads._batch_plan_worker is not None:
                await downloads._batch_plan_worker.wait()
            await pilot.pause()
            assert app.screen.__class__.__name__ == "DownloadAllDialog"
            await pilot.press("2")
            assert app.screen.__class__.__name__ == "DownloadAllDialog"
            await pilot.press("y", "enter")
            await pilot.pause(0.2)
            assert len(calls) == 1

    asyncio.run(scenario())


def test_clear_history_is_immediate_and_preserves_downloaded_files(tmp_path):
    completed = _job(1, "history", (_item(tmp_path, "Finished", QueueStatus.COMPLETED),))
    snapshots = [_snapshot(completed), _snapshot()]
    calls = []
    audio = tmp_path / "Finished.mp3"
    lrc = tmp_path / "Finished.lrc"
    audio.write_bytes(b"audio")
    lrc.write_text("lyrics", encoding="utf-8")

    def provider():
        return snapshots[0] if len(snapshots) == 1 else snapshots.pop(0)

    def clear_history():
        calls.append("clear")
        return QueueMutationResult(QueueMutationStatus.COMPLETED, "Cleared 1 completed history entry.", removed_count=1)

    async def scenario():
        app = _app(tmp_path, provider, history=clear_history)
        async with app.run_test(size=(80, 24)) as pilot:
            downloads = await _open_downloads(app, pilot)
            await pilot.press("shift+h"); await pilot.pause()
            await pilot.pause(0.2)
            assert app.screen.id == "screen-downloads"
            assert calls == ["clear"]
            assert audio.read_bytes() == b"audio"
            assert lrc.read_text(encoding="utf-8") == "lyrics"

    asyncio.run(scenario())


def test_clear_history_does_not_need_confirmation_keys(tmp_path):
    completed = _job(1, "history", (_item(tmp_path, "Finished", QueueStatus.COMPLETED),))

    async def confirm_scenario():
        calls = []
        def clear():
            calls.append("clear")
            return QueueMutationResult(QueueMutationStatus.COMPLETED, "Cleared history", removed_count=1)
        app = _app(tmp_path, lambda: _snapshot(completed), history=clear)
        async with app.run_test(size=(80, 24)) as pilot:
            await _open_downloads(app, pilot)
            await pilot.press("shift+h"); await pilot.pause(0.2)
            await pilot.press("y", "enter"); await pilot.pause()
            assert calls == ["clear"]

    asyncio.run(confirm_scenario())


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


def test_download_selected_starts_without_confirmation(tmp_path):
    queued = _job(1, "queue-record", (_item(tmp_path, "Queued Song", QueueStatus.PENDING),))
    plan_calls = []
    execution_calls = []

    def planner(settings, reference):
        plan_calls.append(reference)
        plan = _execution_plan(tmp_path, reference)
        return DownloadExecutionResult(DownloadExecutionStatus.READY, "Ready", plan=plan)

    def execute(*args, **kwargs):
        execution_calls.append(args)
        return DownloadExecutionResult(DownloadExecutionStatus.COMPLETED, "finished")

    async def scenario():
        app = _app(tmp_path, lambda: _snapshot(queued), plan=planner, execute=execute)
        async with app.run_test() as pilot:
            downloads = await _open_downloads(app, pilot)
            await pilot.press("d")
            await pilot.pause(0.2)
            assert app.screen.id == "screen-downloads"
            assert len(execution_calls) == 1
            assert len(plan_calls) == 1

    asyncio.run(scenario())


def test_retry_failed_song_runs_once_without_confirmation(tmp_path):
    failed = _job(1, "retry-job", (_item(tmp_path, "Broken Song", QueueStatus.FAILED, failure_stage=QueueFailureStage.TRANSPORT, error="network"),))
    calls = []
    plan = DownloadRetryPlan("retry-job:0", "retry-job", 0, "id", "Broken Song", tmp_path / "Broken Song.mp3", "Download failed", DownloadRetryAction.DOWNLOAD_AGAIN)
    def planner(settings, reference):
        return DownloadRetryResult(DownloadRetryStatus.READY, "Ready", plan=plan)
    def executor(settings, retry_plan, **kwargs):
        calls.append(retry_plan.reference)
        return DownloadRetryResult(DownloadRetryStatus.COMPLETED, "Broken Song finished", plan=retry_plan)
    async def scenario():
        app = _app(tmp_path, lambda: _snapshot(failed))
        app.download_retry_plan_provider = planner
        app.download_retry_execution_provider = executor
        async with app.run_test() as pilot:
            await _open_downloads(app, pilot)
            await pilot.press("t"); await pilot.pause(0.2)
            assert app.screen.id == "screen-downloads"
            assert calls == ["retry-job:0"]
    asyncio.run(scenario())


def test_confirm_download_once_shows_progress_then_removes_completed_track(tmp_path):
    started = Event()
    continue_to_processing = Event()
    processing = Event()
    finish = Event()
    completed = False
    calls = []
    queued = _job(1, "queue-record", (_item(tmp_path, "Queued Song", QueueStatus.PENDING),))
    done = _job(1, "queue-record", (_item(tmp_path, "Queued Song", QueueStatus.COMPLETED),))

    def provider():
        return _snapshot(done if completed else queued)

    def planner(settings, reference):
        return DownloadExecutionResult(
            DownloadExecutionStatus.READY,
            "Ready",
            plan=_execution_plan(tmp_path, reference),
        )

    def execute(settings, plan, *, progress):
        nonlocal completed
        calls.append(plan.reference)
        progress(DownloadProgress(plan.reference, DownloadExecutionStatus.DOWNLOADING, 25, 100, "Downloading…"))
        started.set()
        continue_to_processing.wait(timeout=5)
        progress(DownloadProgress(plan.reference, DownloadExecutionStatus.PROCESSING, 100, 100, "Processing lyrics and library metadata…"))
        processing.set()
        finish.wait(timeout=5)
        completed = True
        return DownloadExecutionResult(
            DownloadExecutionStatus.COMPLETED,
            "Queued Song finished downloading.",
            plan=plan,
        )

    async def scenario():
        app = _app(tmp_path, provider, plan=planner, execute=execute)
        async with app.run_test() as pilot:
            downloads = await _open_downloads(app, pilot)
            await pilot.press("d")
            await pilot.pause()
            await pilot.press("y", "y")
            await asyncio.to_thread(started.wait, 2)
            await pilot.pause()
            assert calls == ["queue-record:0"]
            assert "Downloading" in _text(app, "#download-queue")
            assert "25%" in _text(app, "#download-details")

            continue_to_processing.set()
            await asyncio.to_thread(processing.wait, 2)
            await pilot.pause()
            assert "Adding lyrics" in _text(app, "#download-queue")

            execution_worker = downloads._execution_worker
            assert execution_worker is not None
            finish.set()
            await execution_worker.wait()
            await pilot.pause()
            refresh = downloads._refresh_worker
            if refresh is not None:
                await refresh.wait()
                await pilot.pause()
            assert "Nothing waiting to download" in _text(app, "#download-queue")
            assert "Complete 1" in _text(app, "#downloads-summary")
            assert "finished downloading" in _text(app, "#downloads-status")
            assert app.get_screen("dashboard")._invalidated
            assert app.get_screen("library").snapshot is None

    try:
        asyncio.run(scenario())
    finally:
        continue_to_processing.set()
        finish.set()


def test_download_failure_stays_visible_and_ineligible_states_do_not_start(tmp_path):
    failed_now = False
    plan_calls = []
    execution_calls = []
    queued = _job(1, "queued", (_item(tmp_path, "Queued Song", QueueStatus.PENDING),))
    failed = _job(
        1,
        "queued",
        (_item(
            tmp_path,
            "Queued Song",
            QueueStatus.FAILED,
            failure_stage=QueueFailureStage.VALIDATION,
            error="checksum mismatch",
        ),),
    )

    def provider():
        return _snapshot(failed if failed_now else queued)

    def planner(settings, reference):
        plan_calls.append(reference)
        return DownloadExecutionResult(
            DownloadExecutionStatus.READY,
            "Ready",
            plan=_execution_plan(tmp_path, reference),
        )

    def execute(settings, plan, *, progress):
        nonlocal failed_now
        execution_calls.append(plan.reference)
        failed_now = True
        return DownloadExecutionResult(
            DownloadExecutionStatus.FAILED,
            "File validation failed",
            plan=plan,
            failure_stage="File validation failed",
            error="checksum mismatch",
        )

    async def failure_scenario():
        app = _app(tmp_path, provider, plan=planner, execute=execute)
        async with app.run_test() as pilot:
            downloads = await _open_downloads(app, pilot)
            await pilot.press("d")
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            if downloads._refresh_worker is not None:
                await downloads._refresh_worker.wait()
                await pilot.pause()
            assert "Queued Song" in _text(app, "#download-queue")
            assert "File validation failed: checksum mismatch" in _text(app, "#downloads-status")
            await pilot.press("d")
            assert "Press t to try again" in _text(app, "#downloads-status")
            assert len(plan_calls) == 1
            assert execution_calls == ["queued:0"]

    async def active_scenario():
        active = _job(1, "active", (_item(tmp_path, "Moving", QueueStatus.DOWNLOADING),))
        app = _app(tmp_path, lambda: _snapshot(active), plan=planner, execute=execute)
        async with app.run_test() as pilot:
            await _open_downloads(app, pilot)
            await pilot.press("d")
            assert "already downloading or processing" in _text(app, "#downloads-status")

    asyncio.run(failure_scenario())
    asyncio.run(active_scenario())


def test_confirmed_download_survives_screen_switch_and_reloads_authoritative_queue(tmp_path):
    started = Event()
    release = Event()
    completed = False
    queued = _job(1, "queue-record", (_item(tmp_path, "Queued Song", QueueStatus.PENDING),))
    done = _job(1, "queue-record", (_item(tmp_path, "Queued Song", QueueStatus.COMPLETED),))

    def provider():
        return _snapshot(done if completed else queued)

    def planner(settings, reference):
        return DownloadExecutionResult(
            DownloadExecutionStatus.READY,
            "Ready",
            plan=_execution_plan(tmp_path, reference),
        )

    def execute(settings, plan, *, progress):
        nonlocal completed
        started.set()
        release.wait(timeout=5)
        completed = True
        return DownloadExecutionResult(
            DownloadExecutionStatus.COMPLETED,
            "Queued Song finished downloading.",
            plan=plan,
        )

    async def scenario():
        app = _app(tmp_path, provider, plan=planner, execute=execute)
        async with app.run_test() as pilot:
            downloads = await _open_downloads(app, pilot)
            await pilot.press("d")
            await pilot.pause()
            await pilot.press("y")
            await asyncio.to_thread(started.wait, 2)
            execution_worker = downloads._execution_worker
            assert execution_worker is not None
            await pilot.press("2")
            assert app.screen.id == "screen-browse"
            release.set()
            await execution_worker.wait()
            await pilot.pause()
            assert app.screen.id == "screen-browse"
            await pilot.press("4")
            await pilot.pause()
            refresh = downloads._refresh_worker
            if refresh is not None:
                await refresh.wait()
                await pilot.pause()
            assert "Complete 1" in _text(app, "#downloads-summary")
            assert "Nothing waiting to download" in _text(app, "#download-queue")

    try:
        asyncio.run(scenario())
    finally:
        release.set()

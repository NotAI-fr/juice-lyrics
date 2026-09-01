from pathlib import Path

from juice_lyrics.acquisition.jobs import JobStore
from juice_lyrics.acquisition.integration import IntegrationResult
from juice_lyrics.acquisition.models import (
    AcquisitionFailureStage,
    AcquisitionItem,
    AcquisitionResult,
    AcquisitionState,
)
from juice_lyrics.acquisition.runner import AcquisitionRunSummary
from juice_lyrics.acquisition.resolver import ResourceResolutionError
from juice_lyrics.config.settings import Settings
from juice_lyrics.services.acquisition_queue import (
    QueueFailureStage,
    QueueItem,
    QueueJob,
    QueueSnapshot,
    QueueStatus,
)
from juice_lyrics.services.catalogue import CatalogueSearchResult, LyricAvailability
from juice_lyrics.services.download_queue import (
    DownloadExecutionAction,
    DownloadExecutionStatus,
    DownloadAllResult,
    DownloadRetryAction,
    DownloadRetryStatus,
    DownloadQueueItemStatus,
    QueueAddStatus,
    add_to_download_queue,
    execute_selected_download,
    get_download_queue_snapshot,
    plan_download_execution,
    plan_download_retry,
    plan_download_all,
    remove_queue_item,
    clear_download_queue,
    clear_completed_history,
    plan_queue_additions,
    project_download_queue,
)


def _queue_item(tmp_path: Path, title: str, status: QueueStatus, **kwargs) -> QueueItem:
    return QueueItem(
        title=title,
        destination=tmp_path / f"{title}.mp3",
        status=status,
        stored_state=status.value,
        bytes_written=kwargs.get("bytes_written", 0),
        expected_bytes=kwargs.get("expected_bytes", 100),
        resumed=False,
        error=kwargs.get("error"),
        retryable=kwargs.get("retryable", status is QueueStatus.FAILED),
        failure_stage=kwargs.get("failure_stage"),
        identifier=kwargs.get("identifier", title.lower()),
        metadata=(("artist", "Juice WRLD"), ("category", "unreleased"), ("era", "DRFL")),
    )


def _job(number: int, job_id: str, items: tuple[QueueItem, ...]) -> QueueJob:
    return QueueJob(
        display_number=number,
        job_id=job_id,
        label=items[0].title or "Untitled",
        created_at=f"2026-08-30T12:0{number}:00+00:00",
        destination=items[0].destination,
        total_item_count=len(items),
        pending_item_count=sum(item.status is QueueStatus.PENDING for item in items),
        active_item_count=sum(item.status is QueueStatus.DOWNLOADING for item in items),
        completed_item_count=sum(item.status is QueueStatus.COMPLETED for item in items),
        failed_item_count=sum(item.status is QueueStatus.FAILED for item in items),
        status=QueueStatus.FAILED if any(item.status is QueueStatus.FAILED for item in items) else items[0].status,
        stored_state="failed" if any(item.status is QueueStatus.FAILED for item in items) else "pending",
        retryable=any(item.retryable for item in items),
        deletion_allowed=True,
        items=items,
    )


def _selection(*, downloadable: bool = True) -> CatalogueSearchResult:
    return CatalogueSearchResult(
        selection_index=1,
        song_id=94902,
        title="Lemon Glow",
        category="unreleased",
        era="DRFL",
        length="3:12",
        artists=("Juice WRLD",),
        producers=(),
        media_path="Compilation/DRFL/Lemon Glow.mp3" if downloadable else None,
        lyrics=LyricAvailability.SYNCED,
        downloadable=downloadable,
    )


def test_internal_jobs_flatten_into_tracks_and_completed_stays_out_of_active_queue(tmp_path):
    queued = _queue_item(tmp_path, "Queued", QueueStatus.PENDING)
    downloading = _queue_item(tmp_path, "Moving", QueueStatus.DOWNLOADING, bytes_written=50)
    complete = _queue_item(tmp_path, "Done", QueueStatus.COMPLETED, bytes_written=100)
    failed = _queue_item(
        tmp_path,
        "Broken",
        QueueStatus.FAILED,
        failure_stage=QueueFailureStage.LYRICS,
        error="verification failed",
    )
    snapshot = QueueSnapshot(
        (_job(1, "first-job", (queued, downloading)), _job(2, "second-job", (complete, failed))),
        2, 1, 1, 0, 1,
    )

    projected = project_download_queue(snapshot)

    assert [item.title for item in projected.items] == ["Queued", "Moving", "Broken"]
    assert projected.queued_count == 1
    assert projected.downloading_count == 1
    assert projected.failed_count == 1
    assert projected.completed_count == 1
    broken = projected.items[-1]
    assert broken.failure_stage == "Lyrics processing failed"
    assert broken.retryable
    assert broken.artist == "Juice WRLD"
    assert broken.status is DownloadQueueItemStatus.FAILED


def test_retry_plan_uses_verified_finalized_file_for_processing_only(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    destination = tmp_path / "Lemon Glow.mp3"
    destination.write_bytes(b"pristine")
    item = AcquisitionItem("94902", "Lemon Glow", "https://example.test/song", destination)
    job = JobStore(jobs_path).create([item], job_id="retry-job")
    entry = job.items[0]
    entry.state = AcquisitionState.FAILED
    entry.failure_stage = AcquisitionFailureStage.LYRICS
    entry.error = "lyrics verification failed"
    import hashlib
    entry.retry_file_size = destination.stat().st_size
    entry.retry_file_sha256 = hashlib.sha256(destination.read_bytes()).hexdigest()
    JobStore(jobs_path).save(job)

    result = plan_download_retry(Settings(music_dir=tmp_path / "music"), "retry-job:0", jobs_path=jobs_path)
    assert result.status is DownloadRetryStatus.READY
    assert result.plan is not None
    assert result.plan.action is DownloadRetryAction.PROCESS_ONLY
    assert result.plan.song_id == "94902"


def test_retry_plan_chooses_resume_or_download_again_for_transport_failure(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    destination = tmp_path / "song.mp3"
    item = AcquisitionItem("1", "Song", "https://example.test/song", destination)
    job = JobStore(jobs_path).create([item], job_id="transport-job")
    entry = job.items[0]; entry.state = AcquisitionState.FAILED; entry.failure_stage = AcquisitionFailureStage.TRANSPORT
    JobStore(jobs_path).save(job)
    settings = Settings(music_dir=tmp_path / "music")
    result = plan_download_retry(settings, "transport-job:0", jobs_path=jobs_path)
    assert result.plan is not None and result.plan.action is DownloadRetryAction.DOWNLOAD_AGAIN
    destination.with_name("song.mp3.part").write_bytes(b"partial")
    result = plan_download_retry(settings, "transport-job:0", jobs_path=jobs_path)
    assert result.plan is not None and result.plan.action is DownloadRetryAction.RESUME_DOWNLOAD


def test_queue_cleanup_is_record_only_and_preserves_files(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    queued_path = tmp_path / "queued.mp3"; queued_path.write_bytes(b"audio")
    done_path = tmp_path / "done.mp3"; done_path.write_bytes(b"audio")
    store = JobStore(jobs_path)
    job = store.create([AcquisitionItem("q", "Queued", "url", queued_path), AcquisitionItem("d", "Done", "url", done_path)], job_id="cleanup")
    job.items[1].state = AcquisitionState.COMPLETE; store.save(job)
    removed = remove_queue_item("cleanup:0", jobs_path=jobs_path)
    assert removed.removed_count == 1 and queued_path.exists() and done_path.exists()
    history = clear_completed_history(jobs_path=jobs_path)
    assert history.removed_count == 1 and done_path.exists()


def test_clear_queue_keeps_active_and_completed_history(tmp_path):
    jobs_path = tmp_path / "jobs.json"; store = JobStore(jobs_path)
    job = store.create([AcquisitionItem("q", "Queued", "url", tmp_path / "q.mp3"), AcquisitionItem("a", "Active", "url", tmp_path / "a.mp3")], job_id="clear")
    job.items[1].state = AcquisitionState.DOWNLOADING; store.save(job)
    result = clear_download_queue(jobs_path=jobs_path)
    assert result.removed_count == 1 and result.retained_active_count == 1
    remaining = JobStore(jobs_path).get("clear"); assert remaining is not None and len(remaining.items) == 1


def test_download_all_plan_includes_only_waiting_songs(tmp_path):
    jobs_path = tmp_path / "jobs.json"; store = JobStore(jobs_path)
    job = store.create([
        AcquisitionItem("q", "Queued", "url", tmp_path / "q.mp3"),
        AcquisitionItem("f", "Failed", "url", tmp_path / "f.mp3"),
        AcquisitionItem("a", "Active", "url", tmp_path / "a.mp3"),
        AcquisitionItem("d", "Done", "url", tmp_path / "d.mp3"),
    ], job_id="batch")
    job.items[1].state = AcquisitionState.FAILED
    job.items[2].state = AcquisitionState.DOWNLOADING
    job.items[3].state = AcquisitionState.COMPLETE
    store.save(job)
    planned = plan_download_all(Settings(music_dir=tmp_path / "music"), jobs_path=jobs_path)
    assert not isinstance(planned, DownloadAllResult)
    assert [item.title for item in planned.eligible] == ["Queued"]
    assert (planned.failed_count, planned.active_count, planned.completed_count) == (1, 1, 1)


def test_plan_and_confirm_adds_exactly_one_song_without_running_it(tmp_path, monkeypatch):
    import juice_lyrics.acquisition.downloader as downloader
    import juice_lyrics.acquisition.runner as runner

    jobs_path = tmp_path / "jobs.json"
    music = tmp_path / "music"
    settings = Settings(music_dir=music)
    monkeypatch.setattr(downloader, "download_to", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("download ran")))
    monkeypatch.setattr(runner, "run_job", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("runner ran")))

    planned = plan_queue_additions(settings, (_selection(),), jobs_path=jobs_path)
    assert planned.status is QueueAddStatus.READY
    assert not jobs_path.exists()

    added = add_to_download_queue(planned.plan, jobs_path=jobs_path)  # type: ignore[arg-type]
    assert added.status is QueueAddStatus.ADDED
    assert added.added_count == 1
    jobs = JobStore(jobs_path).list()
    assert len(jobs) == 1
    assert jobs[0].items[0].state is AcquisitionState.PENDING
    assert jobs[0].items[0].item.identifier == "94902"
    assert jobs[0].items[0].item.destination == music / "Lemon Glow.mp3"
    queue = get_download_queue_snapshot(jobs_path)
    assert [item.title for item in queue.items] == ["Lemon Glow"]


def test_queue_plan_reports_unavailable_queued_downloaded_and_store_failures(tmp_path):
    jobs_path = tmp_path / "jobs.json"
    music = tmp_path / "music"
    settings = Settings(music_dir=music)

    unavailable = plan_queue_additions(settings, (_selection(downloadable=False),), jobs_path=jobs_path)
    assert unavailable.status is QueueAddStatus.MEDIA_UNAVAILABLE

    unresolved = plan_queue_additions(
        settings,
        (_selection(),),
        jobs_path=jobs_path,
        resolver=lambda *args, **kwargs: (_ for _ in ()).throw(
            ResourceResolutionError("missing safe media path")
        ),
    )
    assert unresolved.status is QueueAddStatus.RESOLUTION_FAILED
    assert unresolved.message == "Unable to resolve download: missing safe media path"

    first = plan_queue_additions(settings, (_selection(),), jobs_path=jobs_path)
    assert first.plan is not None
    assert add_to_download_queue(first.plan, jobs_path=jobs_path).status is QueueAddStatus.ADDED
    queued = plan_queue_additions(settings, (_selection(),), jobs_path=jobs_path)
    assert queued.status is QueueAddStatus.ALREADY_QUEUED

    other_jobs = tmp_path / "other.json"
    music.mkdir(parents=True)
    (music / "Lemon Glow.mp3").write_bytes(b"downloaded")
    downloaded = plan_queue_additions(settings, (_selection(),), jobs_path=other_jobs)
    assert downloaded.status is QueueAddStatus.ALREADY_DOWNLOADED

    class BrokenStore:
        def create(self, items):
            raise PermissionError

    failed = add_to_download_queue(
        first.plan,
        jobs_path=tmp_path / "failure.json",
        duplicate_finder=lambda *args, **kwargs: None,
        store_factory=lambda path: BrokenStore(),
    )
    assert failed.status is QueueAddStatus.SAVE_FAILED
    assert "permission denied" in failed.message


def _stored_downloads(tmp_path: Path):
    jobs_path = tmp_path / "jobs.json"
    items = (
        AcquisitionItem(
            "101",
            "First Song",
            "https://example.test/first.mp3",
            tmp_path / "music" / "First Song.mp3",
            metadata={"artist": "Juice WRLD"},
        ),
        AcquisitionItem(
            "202",
            "Selected Song",
            "https://example.test/selected.mp3",
            tmp_path / "music" / "Selected Song.mp3",
            expected_size=100,
            metadata={"artist": "Juice WRLD"},
        ),
    )
    job = JobStore(jobs_path).create(items, job_id="durable-job")
    return jobs_path, job


def test_download_execution_plan_maps_exact_item_and_detects_resume(tmp_path):
    jobs_path, job = _stored_downloads(tmp_path)
    settings = Settings(music_dir=tmp_path / "music")

    ready = plan_download_execution(settings, f"{job.job_id}:1", jobs_path=jobs_path)

    assert ready.status is DownloadExecutionStatus.READY
    assert ready.plan is not None
    assert ready.plan.item_index == 1
    assert ready.plan.song_id == "202"
    assert ready.plan.destination == tmp_path / "music" / "Selected Song.mp3"
    assert ready.plan.action is DownloadExecutionAction.START

    ready.plan.destination.parent.mkdir(parents=True)
    ready.plan.destination.with_name("Selected Song.mp3.part").write_bytes(b"partial")
    resumed = plan_download_execution(settings, ready.plan.reference, jobs_path=jobs_path)
    assert resumed.plan is not None
    assert resumed.plan.action is DownloadExecutionAction.RESUME

    missing = plan_download_execution(settings, "durable-job:99", jobs_path=jobs_path)
    assert missing.status is DownloadExecutionStatus.NOT_FOUND


def test_execute_selected_download_delegates_exactly_one_item_and_reports_progress(tmp_path):
    jobs_path, job = _stored_downloads(tmp_path)
    settings = Settings(music_dir=tmp_path / "music")
    planned = plan_download_execution(settings, f"{job.job_id}:1", jobs_path=jobs_path)
    assert planned.plan is not None
    progress = []
    integrated = []

    def integration(item, **kwargs):
        integrated.append(item.identifier)
        return IntegrationResult(item.destination, message="processed")

    def runner(job, store, *, progress, postprocess, item_indexes, **kwargs):
        assert item_indexes == {1}
        assert job.items[0].state is AcquisitionState.PENDING
        assert job.items[1].state is AcquisitionState.CHECKING_EXISTING
        progress(1, 2, 50, 100)
        result = AcquisitionResult(
            job.items[1].item,
            AcquisitionState.COMPLETE,
            destination=job.items[1].item.destination,
            bytes_written=100,
        )
        postprocess(result)
        job.record_result(1, result)
        store.save(job)
        return AcquisitionRunSummary(job.job_id, 1, 0, 0, 1)

    result = execute_selected_download(
        settings,
        planned.plan,
        jobs_path=jobs_path,
        runner=runner,
        integration=integration,
        progress=progress.append,
    )

    assert result.status is DownloadExecutionStatus.COMPLETED
    assert integrated == ["202"]
    assert [event.status for event in progress] == [
        DownloadExecutionStatus.DOWNLOADING,
        DownloadExecutionStatus.DOWNLOADING,
        DownloadExecutionStatus.PROCESSING,
    ]
    assert progress[1].percent == 50
    authoritative = JobStore(jobs_path).get(job.job_id)
    assert authoritative is not None
    assert authoritative.items[0].state is AcquisitionState.PENDING
    assert authoritative.items[1].state is AcquisitionState.COMPLETE


def test_execute_selected_download_preserves_structured_failure_and_rejects_second_start(tmp_path):
    jobs_path, job = _stored_downloads(tmp_path)
    settings = Settings(music_dir=tmp_path / "music")
    planned = plan_download_execution(settings, f"{job.job_id}:1", jobs_path=jobs_path)
    assert planned.plan is not None
    calls = 0

    def failing_runner(job, store, *, item_indexes, **kwargs):
        nonlocal calls
        calls += 1
        entry = job.items[1]
        entry.state = AcquisitionState.FAILED
        entry.failure_stage = AcquisitionFailureStage.VALIDATION
        entry.error = "checksum mismatch"
        store.save(job)
        return AcquisitionRunSummary(job.job_id, 0, 0, 1, 1)

    failed = execute_selected_download(
        settings,
        planned.plan,
        jobs_path=jobs_path,
        runner=failing_runner,
    )
    second = execute_selected_download(
        settings,
        planned.plan,
        jobs_path=jobs_path,
        runner=failing_runner,
    )

    assert failed.status is DownloadExecutionStatus.FAILED
    assert failed.message == "File validation failed"
    assert failed.error == "checksum mismatch"
    assert second.status is DownloadExecutionStatus.RETRY_REQUIRED
    assert calls == 1


def test_unexpected_runner_failure_is_persisted_and_exact_destination_is_rechecked(tmp_path):
    jobs_path, job = _stored_downloads(tmp_path)
    settings = Settings(music_dir=tmp_path / "music")
    planned = plan_download_execution(settings, f"{job.job_id}:1", jobs_path=jobs_path)
    assert planned.plan is not None

    changed = JobStore(jobs_path).get(job.job_id)
    assert changed is not None
    changed.items[1].item.destination = tmp_path / "other" / "Unrelated.mp3"
    JobStore(jobs_path).save(changed)
    wrong_target = execute_selected_download(
        settings,
        planned.plan,
        jobs_path=jobs_path,
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("runner called")),
    )
    assert wrong_target.status is DownloadExecutionStatus.NOT_FOUND

    changed.items[1].item.destination = planned.plan.destination
    changed.items[1].state = AcquisitionState.PENDING
    JobStore(jobs_path).save(changed)
    failed = execute_selected_download(
        settings,
        planned.plan,
        jobs_path=jobs_path,
        runner=lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("runner stopped")),
    )
    assert failed.status is DownloadExecutionStatus.FAILED
    assert failed.error == "runner stopped"
    authoritative = JobStore(jobs_path).get(job.job_id)
    assert authoritative is not None
    assert authoritative.items[1].state is AcquisitionState.FAILED
    assert authoritative.items[1].failure_stage is AcquisitionFailureStage.TRANSPORT

from pathlib import Path

from juice_lyrics.acquisition.jobs import JobStore
from juice_lyrics.acquisition.models import AcquisitionItem, AcquisitionState
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
    DownloadQueueItemStatus,
    QueueAddStatus,
    add_to_download_queue,
    get_download_queue_snapshot,
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

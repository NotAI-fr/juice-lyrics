from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ..acquisition.duplicates import DuplicateMatch, find_duplicate
from ..acquisition.jobs import DEFAULT_JOBS_FILE, AcquisitionJob, JobStore, JobStoreError
from ..acquisition.models import AcquisitionItem
from ..acquisition.resolver import ResourceResolutionError, resolve_resource
from ..config.settings import Settings
from .acquisition_queue import (
    QueueFailureStage,
    QueueItem,
    QueueSnapshot,
    QueueStatus,
    get_queue_snapshot,
)
from .catalogue import CatalogueSearchResult


class DownloadQueueItemStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NEEDS_ATTENTION = "needs_attention"


class QueueDuplicateReason(str, Enum):
    ALREADY_QUEUED = "already_queued"
    ALREADY_DOWNLOADED = "already_downloaded"


class QueueAddStatus(str, Enum):
    READY = "ready"
    ADDED = "added"
    ALREADY_QUEUED = "already_queued"
    ALREADY_DOWNLOADED = "already_downloaded"
    MEDIA_UNAVAILABLE = "media_unavailable"
    INVALID_SELECTION = "invalid_selection"
    RESOLUTION_FAILED = "resolution_failed"
    SAVE_FAILED = "save_failed"


@dataclass(frozen=True, slots=True)
class DownloadQueueItem:
    reference: str
    song_id: str | None
    title: str
    artist: str | None
    category: str | None
    era: str | None
    destination: Path | None
    status: DownloadQueueItemStatus
    bytes_written: int
    expected_bytes: int | None
    failure_stage: str | None
    error: str | None
    retryable: bool
    queued_at: str | None
    internal_reference: str | None = None

    @property
    def progress_percent(self) -> int | None:
        if self.expected_bytes is None or self.expected_bytes <= 0:
            return None
        return min(100, int(self.bytes_written * 100 / self.expected_bytes))


@dataclass(frozen=True, slots=True)
class DownloadQueueSnapshot:
    items: tuple[DownloadQueueItem, ...]
    queued_count: int
    downloading_count: int
    processing_count: int
    failed_count: int
    completed_count: int

    @property
    def active_count(self) -> int:
        return len(self.items)


@dataclass(frozen=True, slots=True)
class PlannedQueueItem:
    item: AcquisitionItem
    song_id: str
    artist: str | None
    category: str | None
    era: str | None


@dataclass(frozen=True, slots=True)
class QueueAddPlan:
    items: tuple[PlannedQueueItem, ...]


@dataclass(frozen=True, slots=True)
class QueueAddResult:
    status: QueueAddStatus
    message: str
    plan: QueueAddPlan | None = None
    added_count: int = 0
    queue_references: tuple[str, ...] = ()
    duplicate_reason: QueueDuplicateReason | None = None

    @property
    def ok(self) -> bool:
        return self.status in {QueueAddStatus.READY, QueueAddStatus.ADDED}


QueueReader = Callable[[Path], QueueSnapshot]
Resolver = Callable[..., AcquisitionItem]
DuplicateFinder = Callable[..., DuplicateMatch | None]
StoreFactory = Callable[[Path], JobStore]


def _metadata(item: QueueItem) -> dict[str, str]:
    return dict(item.metadata)


def _status(status: QueueStatus) -> DownloadQueueItemStatus:
    if status is QueueStatus.PENDING:
        return DownloadQueueItemStatus.QUEUED
    if status in {QueueStatus.CHECKING_EXISTING, QueueStatus.DOWNLOADING}:
        return DownloadQueueItemStatus.DOWNLOADING
    if status in {QueueStatus.VALIDATING, QueueStatus.POST_PROCESSING}:
        return DownloadQueueItemStatus.PROCESSING
    if status in {QueueStatus.COMPLETED, QueueStatus.SKIPPED}:
        return DownloadQueueItemStatus.COMPLETED
    if status is QueueStatus.FAILED:
        return DownloadQueueItemStatus.FAILED
    return DownloadQueueItemStatus.NEEDS_ATTENTION


def _failure_label(stage: QueueFailureStage | None) -> str | None:
    return {
        QueueFailureStage.TRANSPORT: "Download failed",
        QueueFailureStage.VALIDATION: "File validation failed",
        QueueFailureStage.LYRICS: "Lyrics processing failed",
        QueueFailureStage.LRC: "LRC creation failed",
        QueueFailureStage.STATE: "Library update failed",
        QueueFailureStage.UNKNOWN: "Queue processing failed",
        None: None,
    }[stage]


def project_download_queue(snapshot: QueueSnapshot) -> DownloadQueueSnapshot:
    """Flatten durable jobs into the track-oriented queue used by frontends."""

    projected: list[DownloadQueueItem] = []
    completed_count = 0
    for job in snapshot.jobs:
        for item_index, item in enumerate(job.items):
            status = _status(item.status)
            if status is DownloadQueueItemStatus.COMPLETED:
                completed_count += 1
                continue
            metadata = _metadata(item)
            projected.append(DownloadQueueItem(
                reference=f"{job.job_id}:{item_index}",
                song_id=item.identifier,
                title=item.title or "Unknown song",
                artist=metadata.get("artist"),
                category=metadata.get("category"),
                era=metadata.get("era"),
                destination=item.destination,
                status=status,
                bytes_written=item.bytes_written,
                expected_bytes=item.expected_bytes,
                failure_stage=_failure_label(item.failure_stage),
                error=item.error,
                retryable=item.retryable,
                queued_at=job.created_at,
                internal_reference=f"{job.job_id}:{item_index}",
            ))
    items = tuple(projected)
    return DownloadQueueSnapshot(
        items=items,
        queued_count=sum(item.status is DownloadQueueItemStatus.QUEUED for item in items),
        downloading_count=sum(item.status is DownloadQueueItemStatus.DOWNLOADING for item in items),
        processing_count=sum(item.status is DownloadQueueItemStatus.PROCESSING for item in items),
        failed_count=sum(item.status in {DownloadQueueItemStatus.FAILED, DownloadQueueItemStatus.NEEDS_ATTENTION} for item in items),
        completed_count=completed_count,
    )


def get_download_queue_snapshot(path: Path = DEFAULT_JOBS_FILE) -> DownloadQueueSnapshot:
    return project_download_queue(get_queue_snapshot(path))


def _selection_resource(selection: CatalogueSearchResult) -> dict[str, object]:
    return {
        "id": selection.song_id,
        "title": selection.title,
        "path": selection.media_path,
        "artist": ", ".join(selection.artists) or None,
        "category": selection.category,
        "era": selection.era,
    }


def _existing_queue_duplicate(
    item: AcquisitionItem,
    snapshot: QueueSnapshot,
) -> QueueItem | None:
    for job in snapshot.jobs:
        for queued in job.items:
            if queued.status in {QueueStatus.COMPLETED, QueueStatus.SKIPPED}:
                continue
            if item.identifier and queued.identifier == item.identifier:
                return queued
            if queued.destination == item.destination:
                return queued
    return None


def plan_queue_additions(
    settings: Settings,
    selections: Sequence[CatalogueSearchResult],
    *,
    destination_dir: Path | None = None,
    jobs_path: Path = DEFAULT_JOBS_FILE,
    queue_reader: QueueReader = get_queue_snapshot,
    resolver: Resolver = resolve_resource,
    duplicate_finder: DuplicateFinder = find_duplicate,
) -> QueueAddResult:
    """Validate one or more explicit catalogue selections without writing anything."""

    if not selections:
        return QueueAddResult(QueueAddStatus.INVALID_SELECTION, "Select a song first.")
    target_dir = Path(destination_dir or settings.music_dir).expanduser()
    try:
        snapshot = queue_reader(Path(jobs_path))
    except PermissionError:
        return QueueAddResult(QueueAddStatus.SAVE_FAILED, "Unable to inspect the queue: permission denied.")
    except (JobStoreError, OSError) as exc:
        return QueueAddResult(QueueAddStatus.SAVE_FAILED, f"Unable to inspect the queue: {exc}")
    planned: list[PlannedQueueItem] = []
    seen_ids: set[str] = set()
    seen_destinations: set[Path] = set()
    for selection in selections:
        if not selection.downloadable or not selection.media_path:
            return QueueAddResult(QueueAddStatus.MEDIA_UNAVAILABLE, "Media is unavailable for this song.")
        if selection.song_id is None or not selection.title:
            return QueueAddResult(QueueAddStatus.INVALID_SELECTION, "This song lacks a stable catalogue ID or title.")
        try:
            item = resolver(
                _selection_resource(selection),
                destination_dir=target_dir,
                api_base=settings.api_base,
            )
        except (ResourceResolutionError, TypeError, ValueError) as exc:
            return QueueAddResult(QueueAddStatus.RESOLUTION_FAILED, f"Unable to resolve download: {exc}")
        if item.identifier in seen_ids or item.destination in seen_destinations:
            return QueueAddResult(QueueAddStatus.ALREADY_QUEUED, f"{item.title} is already selected.", duplicate_reason=QueueDuplicateReason.ALREADY_QUEUED)
        if _existing_queue_duplicate(item, snapshot) is not None:
            return QueueAddResult(QueueAddStatus.ALREADY_QUEUED, f"{item.title} is already in the queue.", duplicate_reason=QueueDuplicateReason.ALREADY_QUEUED)
        duplicate = duplicate_finder(item, search_dir=target_dir)
        if duplicate is not None:
            return QueueAddResult(
                QueueAddStatus.ALREADY_DOWNLOADED,
                f"{item.title} is already downloaded at {duplicate.path}.",
                duplicate_reason=QueueDuplicateReason.ALREADY_DOWNLOADED,
            )
        seen_ids.add(item.identifier)
        seen_destinations.add(item.destination)
        planned.append(PlannedQueueItem(
            item=item,
            song_id=str(selection.song_id),
            artist=", ".join(selection.artists) or None,
            category=selection.category,
            era=selection.era,
        ))
    plan = QueueAddPlan(tuple(planned))
    return QueueAddResult(QueueAddStatus.READY, "Ready to add to the download queue.", plan=plan)


def add_to_download_queue(
    plan: QueueAddPlan,
    *,
    jobs_path: Path = DEFAULT_JOBS_FILE,
    queue_reader: QueueReader = get_queue_snapshot,
    duplicate_finder: DuplicateFinder = find_duplicate,
    store_factory: StoreFactory = JobStore,
) -> QueueAddResult:
    """Persist a validated queue addition exactly once as one durable backend job."""

    if not plan.items:
        return QueueAddResult(QueueAddStatus.INVALID_SELECTION, "Nothing was selected for the queue.")
    try:
        snapshot = queue_reader(Path(jobs_path))
        for planned in plan.items:
            if _existing_queue_duplicate(planned.item, snapshot) is not None:
                return QueueAddResult(QueueAddStatus.ALREADY_QUEUED, f"{planned.item.title} is already in the queue.", duplicate_reason=QueueDuplicateReason.ALREADY_QUEUED)
            duplicate = duplicate_finder(planned.item, search_dir=planned.item.destination.parent)
            if duplicate is not None:
                return QueueAddResult(QueueAddStatus.ALREADY_DOWNLOADED, f"{planned.item.title} is already downloaded at {duplicate.path}.", duplicate_reason=QueueDuplicateReason.ALREADY_DOWNLOADED)
        store = store_factory(Path(jobs_path))
        job: AcquisitionJob = store.create(planned.item for planned in plan.items)
    except PermissionError:
        return QueueAddResult(QueueAddStatus.SAVE_FAILED, "Unable to save the queue: permission denied.")
    except (JobStoreError, OSError) as exc:
        return QueueAddResult(QueueAddStatus.SAVE_FAILED, f"Unable to save the queue: {exc}")
    references = tuple(f"{job.job_id}:{index}" for index in range(len(plan.items)))
    return QueueAddResult(
        QueueAddStatus.ADDED,
        f"Added {len(plan.items)} song{'s' if len(plan.items) != 1 else ''} to the download queue.",
        added_count=len(plan.items),
        queue_references=references,
    )

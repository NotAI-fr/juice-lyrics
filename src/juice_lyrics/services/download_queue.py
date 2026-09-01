from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
import hashlib
from pathlib import Path
from threading import Lock

from ..acquisition.duplicates import DuplicateMatch, find_duplicate
from ..acquisition.jobs import DEFAULT_JOBS_FILE, AcquisitionJob, JobStore, JobStoreError
from ..acquisition.downloader import DownloadPolicy
from ..acquisition.integration import IntegrationResult, integrate_downloaded_mp3
from ..acquisition.models import (
    AcquisitionFailureStage,
    AcquisitionItem,
    AcquisitionResult,
    AcquisitionState,
)
from ..acquisition.resolver import ResourceResolutionError, resolve_resource
from ..acquisition.runner import AcquisitionRunSummary, run_job
from ..api.client import get_song
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


class DownloadExecutionAction(str, Enum):
    START = "start"
    RESUME = "resume"


class DownloadExecutionStatus(str, Enum):
    READY = "ready"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_FOUND = "not_found"
    NOT_ELIGIBLE = "not_eligible"
    ALREADY_RUNNING = "already_running"
    RETRY_REQUIRED = "retry_required"
    STORE_FAILED = "store_failed"


class DownloadRetryAction(str, Enum):
    RESUME_DOWNLOAD = "resume_download"
    DOWNLOAD_AGAIN = "download_again"
    PROCESS_ONLY = "process_only"


class DownloadRetryStatus(str, Enum):
    READY = "ready"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_FOUND = "not_found"
    NOT_ELIGIBLE = "not_eligible"
    ALREADY_RUNNING = "already_running"
    STORE_FAILED = "store_failed"


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


@dataclass(frozen=True, slots=True)
class DownloadExecutionPlan:
    reference: str
    job_id: str
    item_index: int
    song_id: str
    title: str
    artist: str | None
    destination: Path
    current_status: DownloadQueueItemStatus
    action: DownloadExecutionAction


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    reference: str
    status: DownloadExecutionStatus
    bytes_written: int = 0
    total_bytes: int | None = None
    message: str = ""

    @property
    def percent(self) -> int | None:
        if self.total_bytes is None or self.total_bytes <= 0:
            return None
        return min(100, int(self.bytes_written * 100 / self.total_bytes))


@dataclass(frozen=True, slots=True)
class DownloadExecutionResult:
    status: DownloadExecutionStatus
    message: str
    plan: DownloadExecutionPlan | None = None
    failure_stage: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {DownloadExecutionStatus.READY, DownloadExecutionStatus.COMPLETED}


@dataclass(frozen=True, slots=True)
class DownloadRetryPlan:
    reference: str
    job_id: str
    item_index: int
    song_id: str
    title: str
    destination: Path
    previous_failure: str
    action: DownloadRetryAction


@dataclass(frozen=True, slots=True)
class DownloadRetryResult:
    status: DownloadRetryStatus
    message: str
    plan: DownloadRetryPlan | None = None
    failure_stage: str | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status in {DownloadRetryStatus.READY, DownloadRetryStatus.COMPLETED}


class QueueMutationStatus(str, Enum):
    READY = "ready"
    COMPLETED = "completed"
    NOT_FOUND = "not_found"
    NOT_ELIGIBLE = "not_eligible"
    ACTIVE = "active"
    STORE_FAILED = "store_failed"


@dataclass(frozen=True, slots=True)
class QueueMutationPlan:
    action: str
    reference: str | None = None
    count: int = 0


@dataclass(frozen=True, slots=True)
class QueueMutationResult:
    status: QueueMutationStatus
    message: str
    removed_count: int = 0
    retained_active_count: int = 0


@dataclass(frozen=True, slots=True)
class DownloadAllPlan:
    eligible: tuple[DownloadExecutionPlan, ...]
    failed_count: int
    active_count: int
    completed_count: int
    skipped_count: int


class DownloadBatchStatus(str, Enum):
    READY = "ready"
    COMPLETED = "completed"
    FAILED = "failed"
    STORE_FAILED = "store_failed"


@dataclass(frozen=True, slots=True)
class DownloadBatchItemResult:
    reference: str
    title: str
    status: DownloadBatchStatus
    message: str


@dataclass(frozen=True, slots=True)
class DownloadBatchProgress:
    completed: int
    total: int
    reference: str
    title: str
    status: DownloadExecutionStatus


@dataclass(frozen=True, slots=True)
class DownloadAllResult:
    status: DownloadBatchStatus
    message: str
    completed_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0
    items: tuple[DownloadBatchItemResult, ...] = ()


QueueReader = Callable[[Path], QueueSnapshot]
Resolver = Callable[..., AcquisitionItem]
DuplicateFinder = Callable[..., DuplicateMatch | None]
StoreFactory = Callable[[Path], JobStore]
ExecutionProgressCallback = Callable[[DownloadProgress], None]
Runner = Callable[..., AcquisitionRunSummary]
Integration = Callable[..., IntegrationResult]
SongFetcher = Callable[[Settings, int], dict[str, object]]


_EXECUTION_CLAIM_LOCK = Lock()
_ACTIVE_EXECUTIONS: set[str] = set()


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


def _parse_queue_reference(reference: str) -> tuple[str, int] | None:
    job_id, separator, index_text = str(reference).rpartition(":")
    if not separator or not job_id or not index_text.isdigit():
        return None
    return job_id, int(index_text)


def _mutation_error(exc: Exception) -> QueueMutationResult:
    return QueueMutationResult(QueueMutationStatus.STORE_FAILED, f"Unable to update the download queue: {exc}")


def remove_queue_item(
    reference: str,
    *,
    jobs_path: Path = DEFAULT_JOBS_FILE,
    store_factory: StoreFactory = JobStore,
) -> QueueMutationResult:
    parsed = _parse_queue_reference(reference)
    if parsed is None:
        return QueueMutationResult(QueueMutationStatus.NOT_FOUND, "This queued song no longer exists.")
    job_id, index = parsed
    with _EXECUTION_CLAIM_LOCK:
        if reference in _ACTIVE_EXECUTIONS:
            return QueueMutationResult(QueueMutationStatus.ACTIVE, "This song is currently being processed and cannot be removed.")
        try:
            store = store_factory(Path(jobs_path)); job = store.get(job_id)
            if job is None or index < 0 or index >= len(job.items):
                return QueueMutationResult(QueueMutationStatus.NOT_FOUND, "This queued song no longer exists.")
            entry = job.items[index]
            if entry.state in {AcquisitionState.CHECKING_EXISTING, AcquisitionState.DOWNLOADING, AcquisitionState.DOWNLOADED, AcquisitionState.VALIDATING, AcquisitionState.IMPORTED}:
                return QueueMutationResult(QueueMutationStatus.ACTIVE, "This song is currently being processed and cannot be removed.")
            if entry.state in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED}:
                return QueueMutationResult(QueueMutationStatus.NOT_ELIGIBLE, "Completed songs are managed as history.")
            title = entry.item.title
            job.items.pop(index)
            if job.items:
                store.save(job)
            else:
                store.delete(job_id)
            return QueueMutationResult(QueueMutationStatus.COMPLETED, f"Removed {title} from the download queue.", removed_count=1)
        except PermissionError:
            return QueueMutationResult(QueueMutationStatus.STORE_FAILED, "Unable to update the download queue: permission denied.")
        except (JobStoreError, OSError) as exc:
            return _mutation_error(exc)


def clear_download_queue(*, jobs_path: Path = DEFAULT_JOBS_FILE, store_factory: StoreFactory = JobStore) -> QueueMutationResult:
    removed = retained = 0
    with _EXECUTION_CLAIM_LOCK:
        try:
            store = store_factory(Path(jobs_path))
            for job in list(store.list()):
                kept = []
                for index, entry in enumerate(job.items):
                    ref = f"{job.job_id}:{index}"
                    if entry.state in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED}:
                        kept.append(entry); continue
                    if entry.state in {AcquisitionState.CHECKING_EXISTING, AcquisitionState.DOWNLOADING, AcquisitionState.DOWNLOADED, AcquisitionState.VALIDATING, AcquisitionState.IMPORTED} or ref in _ACTIVE_EXECUTIONS:
                        kept.append(entry); retained += 1
                    else:
                        removed += 1
                if len(kept) != len(job.items):
                    if kept:
                        job.items = kept; store.save(job)
                    else:
                        store.delete(job.job_id)
            message = f"Cleared {removed} waiting or failed song(s)."
            if retained: message += f" Retained {retained} active song(s)."
            return QueueMutationResult(QueueMutationStatus.COMPLETED, message, removed_count=removed, retained_active_count=retained)
        except PermissionError:
            return QueueMutationResult(QueueMutationStatus.STORE_FAILED, "Unable to update the download queue: permission denied.")
        except (JobStoreError, OSError) as exc:
            return _mutation_error(exc)


def clear_completed_history(*, jobs_path: Path = DEFAULT_JOBS_FILE, store_factory: StoreFactory = JobStore) -> QueueMutationResult:
    removed = 0
    with _EXECUTION_CLAIM_LOCK:
        try:
            store = store_factory(Path(jobs_path))
            for job in list(store.list()):
                kept = [entry for entry in job.items if entry.state not in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED}]
                removed += len(job.items) - len(kept)
                if len(kept) != len(job.items):
                    if kept:
                        job.items = kept; store.save(job)
                    else:
                        store.delete(job.job_id)
            return QueueMutationResult(QueueMutationStatus.COMPLETED, f"Cleared {removed} completed history entr{'y' if removed == 1 else 'ies'}.", removed_count=removed)
        except PermissionError:
            return QueueMutationResult(QueueMutationStatus.STORE_FAILED, "Unable to update the download queue: permission denied.")
        except (JobStoreError, OSError) as exc:
            return _mutation_error(exc)


def _execution_failure(
    status: DownloadExecutionStatus,
    message: str,
) -> DownloadExecutionResult:
    return DownloadExecutionResult(status, message)


def plan_download_execution(
    settings: Settings,
    reference: str,
    *,
    jobs_path: Path = DEFAULT_JOBS_FILE,
    store_factory: StoreFactory = JobStore,
) -> DownloadExecutionResult:
    """Resolve one frontend queue reference and validate download eligibility."""

    parsed = _parse_queue_reference(reference)
    if parsed is None:
        return _execution_failure(DownloadExecutionStatus.NOT_FOUND, "This queue item no longer exists.")
    job_id, item_index = parsed
    try:
        job = store_factory(Path(jobs_path)).get(job_id)
    except PermissionError:
        return _execution_failure(DownloadExecutionStatus.STORE_FAILED, "Unable to read the download queue: permission denied.")
    except (JobStoreError, OSError) as exc:
        return _execution_failure(DownloadExecutionStatus.STORE_FAILED, f"Unable to read the download queue: {exc}")
    if job is None or item_index < 0 or item_index >= len(job.items):
        return _execution_failure(DownloadExecutionStatus.NOT_FOUND, "This queue item no longer exists.")
    entry = job.items[item_index]
    if entry.state is AcquisitionState.FAILED:
        return _execution_failure(
            DownloadExecutionStatus.RETRY_REQUIRED,
            "This download failed previously. Retry will be available in a future action.",
        )
    if entry.state in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED}:
        return _execution_failure(DownloadExecutionStatus.NOT_ELIGIBLE, "This song is already completed.")
    if entry.state in {
        AcquisitionState.CHECKING_EXISTING,
        AcquisitionState.DOWNLOADING,
        AcquisitionState.DOWNLOADED,
        AcquisitionState.VALIDATING,
        AcquisitionState.IMPORTED,
    }:
        return _execution_failure(DownloadExecutionStatus.ALREADY_RUNNING, "This song is already downloading or processing.")
    item = entry.item
    if not item.destination.name:
        return _execution_failure(DownloadExecutionStatus.NOT_ELIGIBLE, "This queue item has no valid destination.")
    if not item.url or not item.identifier:
        return _execution_failure(DownloadExecutionStatus.NOT_ELIGIBLE, "This queue item has no valid downloadable resource.")
    partial = item.destination.with_name(item.destination.name + ".part")
    action = DownloadExecutionAction.RESUME if partial.is_file() else DownloadExecutionAction.START
    return DownloadExecutionResult(
        DownloadExecutionStatus.READY,
        "Ready to resume download." if action is DownloadExecutionAction.RESUME else "Ready to start download.",
        plan=DownloadExecutionPlan(
            reference=reference,
            job_id=job_id,
            item_index=item_index,
            song_id=item.identifier,
            title=item.title,
            artist=item.metadata.get("artist"),
            destination=item.destination,
            current_status=DownloadQueueItemStatus.QUEUED,
            action=action,
        ),
    )


def plan_download_all(
    settings: Settings,
    *,
    jobs_path: Path = DEFAULT_JOBS_FILE,
    store_factory: StoreFactory = JobStore,
) -> DownloadAllPlan | DownloadAllResult:
    """Plan eligible queued songs from the authoritative persistent queue."""
    try:
        snapshot = get_queue_snapshot(jobs_path)
    except (JobStoreError, OSError) as exc:
        return DownloadAllResult(DownloadBatchStatus.STORE_FAILED, f"Unable to read the download queue: {exc}")
    eligible: list[DownloadExecutionPlan] = []
    failed = active = completed = skipped = 0
    for job in snapshot.jobs:
        for index, item in enumerate(job.items):
            status = _status(item.status)
            reference = f"{job.job_id}:{index}"
            if status in {DownloadQueueItemStatus.COMPLETED}: completed += 1; continue
            if status is DownloadQueueItemStatus.FAILED: failed += 1; continue
            if status in {DownloadQueueItemStatus.DOWNLOADING, DownloadQueueItemStatus.PROCESSING}: active += 1; continue
            if item.destination is None or not item.identifier:
                skipped += 1; continue
            if reference in _ACTIVE_EXECUTIONS:
                active += 1; continue
            metadata = dict(item.metadata)
            eligible.append(DownloadExecutionPlan(reference, job.job_id, index, item.identifier, item.title or "Unknown song", metadata.get("artist"), item.destination, DownloadQueueItemStatus.QUEUED, DownloadExecutionAction.RESUME if item.destination.with_name(item.destination.name + ".part").is_file() else DownloadExecutionAction.START))
    return DownloadAllPlan(tuple(eligible), failed, active, completed, skipped)


def execute_download_all(
    settings: Settings,
    plan: DownloadAllPlan,
    *,
    jobs_path: Path = DEFAULT_JOBS_FILE,
    runner: Runner = run_job,
    integration: Integration = integrate_downloaded_mp3,
    song_fetcher: SongFetcher = get_song,
    lyrics_dir: Path | None = None,
    progress: Callable[[DownloadBatchProgress], None] | None = None,
) -> DownloadAllResult:
    results: list[DownloadBatchItemResult] = []
    completed = failed = skipped = 0
    for position, execution_plan in enumerate(plan.eligible, 1):
        if progress:
            progress(DownloadBatchProgress(position - 1, len(plan.eligible), execution_plan.reference, execution_plan.title, DownloadExecutionStatus.READY))
        current = plan_download_execution(settings, execution_plan.reference, jobs_path=jobs_path)
        if current.plan is None:
            skipped += 1
            results.append(DownloadBatchItemResult(execution_plan.reference, execution_plan.title, DownloadBatchStatus.FAILED, current.message))
            continue
        result = execute_selected_download(settings, current.plan, jobs_path=jobs_path, runner=runner, integration=integration, song_fetcher=song_fetcher, lyrics_dir=lyrics_dir, progress=(lambda update, pos=position: progress(DownloadBatchProgress(pos, len(plan.eligible), execution_plan.reference, execution_plan.title, update.status)) if progress else None))
        if result.status is DownloadExecutionStatus.COMPLETED:
            completed += 1; batch_status = DownloadBatchStatus.COMPLETED
        else:
            failed += 1; batch_status = DownloadBatchStatus.FAILED
        results.append(DownloadBatchItemResult(execution_plan.reference, execution_plan.title, batch_status, result.message))
    return DownloadAllResult(DownloadBatchStatus.COMPLETED if failed == 0 else DownloadBatchStatus.FAILED, f"Download all finished · {completed} completed · {failed} failed · {skipped} skipped", completed, failed, skipped, tuple(results))


def _verified_retry_file(entry: Any) -> bool:
    destination = entry.item.destination
    if not destination.is_file() or entry.retry_file_size is None or not entry.retry_file_sha256:
        return False
    try:
        digest = hashlib.sha256(destination.read_bytes()).hexdigest()
        return destination.stat().st_size == entry.retry_file_size and digest == entry.retry_file_sha256.lower()
    except OSError:
        return False


def plan_download_retry(
    settings: Settings,
    reference: str,
    *,
    jobs_path: Path = DEFAULT_JOBS_FILE,
    store_factory: StoreFactory = JobStore,
) -> DownloadRetryResult:
    parsed = _parse_queue_reference(reference)
    if parsed is None:
        return DownloadRetryResult(DownloadRetryStatus.NOT_FOUND, "This queue item no longer exists.")
    job_id, item_index = parsed
    try:
        job = store_factory(Path(jobs_path)).get(job_id)
    except PermissionError:
        return DownloadRetryResult(DownloadRetryStatus.STORE_FAILED, "Unable to read the download queue: permission denied.")
    except (JobStoreError, OSError) as exc:
        return DownloadRetryResult(DownloadRetryStatus.STORE_FAILED, f"Unable to read the download queue: {exc}")
    if job is None or item_index < 0 or item_index >= len(job.items):
        return DownloadRetryResult(DownloadRetryStatus.NOT_FOUND, "This queue item no longer exists.")
    entry = job.items[item_index]
    if entry.state is not AcquisitionState.FAILED:
        if entry.state in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED}:
            return DownloadRetryResult(DownloadRetryStatus.NOT_ELIGIBLE, "This song is already completed.")
        return DownloadRetryResult(DownloadRetryStatus.ALREADY_RUNNING, "This song is already downloading or processing.")
    if not entry.item.url or not entry.item.identifier or not entry.item.destination.name:
        return DownloadRetryResult(DownloadRetryStatus.NOT_ELIGIBLE, "This song cannot be retried because its download resource is incomplete.")
    if entry.failure_stage is not None and entry.failure_stage.is_post_processing and _verified_retry_file(entry):
        action = DownloadRetryAction.PROCESS_ONLY
    elif entry.item.destination.with_name(entry.item.destination.name + ".part").is_file():
        action = DownloadRetryAction.RESUME_DOWNLOAD
    else:
        action = DownloadRetryAction.DOWNLOAD_AGAIN
    return DownloadRetryResult(
        DownloadRetryStatus.READY,
        "Ready to retry processing only." if action is DownloadRetryAction.PROCESS_ONLY else ("Ready to resume download." if action is DownloadRetryAction.RESUME_DOWNLOAD else "Ready to download again."),
        plan=DownloadRetryPlan(reference, job_id, item_index, entry.item.identifier, entry.item.title, entry.item.destination, entry.error or "Previous attempt failed.", action),
    )


def execute_selected_download(
    settings: Settings,
    plan: DownloadExecutionPlan,
    *,
    jobs_path: Path = DEFAULT_JOBS_FILE,
    store_factory: StoreFactory = JobStore,
    runner: Runner = run_job,
    integration: Integration = integrate_downloaded_mp3,
    song_fetcher: SongFetcher = get_song,
    lyrics_dir: Path | None = None,
    progress: ExecutionProgressCallback | None = None,
    _allow_failed: bool = False,
) -> DownloadExecutionResult:
    """Execute exactly one confirmed queue item through the existing runner."""

    try:
        store = store_factory(Path(jobs_path))
        # Claim the exact persisted item before starting the long-running worker.
        # This closes the same-process double-submit race without changing the
        # durable job schema or runner semantics.
        with _EXECUTION_CLAIM_LOCK:
            if plan.reference in _ACTIVE_EXECUTIONS:
                return _execution_failure(DownloadExecutionStatus.ALREADY_RUNNING, "This song is already downloading or processing.")
            job = store.get(plan.job_id)
            if job is None or plan.item_index < 0 or plan.item_index >= len(job.items):
                return _execution_failure(DownloadExecutionStatus.NOT_FOUND, "This queue item no longer exists.")
            entry = job.items[plan.item_index]
            if (
                entry.item.identifier != plan.song_id
                or entry.item.destination != plan.destination
            ):
                return _execution_failure(DownloadExecutionStatus.NOT_FOUND, "The selected queue item changed before download could start.")
            if entry.state is AcquisitionState.FAILED and not _allow_failed:
                return _execution_failure(DownloadExecutionStatus.RETRY_REQUIRED, "This failed song requires the future Retry action.")
            if entry.state in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED}:
                return _execution_failure(DownloadExecutionStatus.NOT_ELIGIBLE, "This song is already completed.")
            if entry.state not in {AcquisitionState.PENDING, AcquisitionState.RESOLVED}:
                return _execution_failure(DownloadExecutionStatus.ALREADY_RUNNING, "This song is already downloading or processing.")
            if not entry.item.destination.name:
                return _execution_failure(DownloadExecutionStatus.NOT_ELIGIBLE, "This queue item has no valid destination.")

            entry.state = AcquisitionState.CHECKING_EXISTING
            entry.error = None
            entry.failure_stage = None
            job.touch()
            store.save(job)
            _ACTIVE_EXECUTIONS.add(plan.reference)
        if progress:
            progress(DownloadProgress(plan.reference, DownloadExecutionStatus.DOWNLOADING, message="Downloading…"))

        def report(_index: int, _total: int, written: int, remote_total: int | None) -> None:
            if progress:
                progress(DownloadProgress(
                    plan.reference,
                    DownloadExecutionStatus.DOWNLOADING,
                    written,
                    remote_total,
                    "Downloading…",
                ))

        def postprocess(result: AcquisitionResult) -> IntegrationResult:
            if progress:
                progress(DownloadProgress(
                    plan.reference,
                    DownloadExecutionStatus.PROCESSING,
                    entry.bytes_written,
                    entry.item.expected_size,
                    "Processing lyrics and library metadata…",
                ))
            return integration(
                entry.item,
                song_fetcher=lambda song_id: song_fetcher(settings, song_id),
                lyrics_dir=Path(lyrics_dir) if lyrics_dir is not None else settings.lyrics_dir,
                settings=settings,
            )

        runner(
            job,
            store,
            policy=DownloadPolicy(),
            progress=report,
            postprocess=postprocess,
            item_indexes={plan.item_index},
        )
        authoritative = store.get(plan.job_id)
    except PermissionError:
        with _EXECUTION_CLAIM_LOCK: _ACTIVE_EXECUTIONS.discard(plan.reference)
        return _execution_failure(DownloadExecutionStatus.STORE_FAILED, "Unable to update the download queue: permission denied.")
    except (JobStoreError, OSError) as exc:
        with _EXECUTION_CLAIM_LOCK: _ACTIVE_EXECUTIONS.discard(plan.reference)
        return _execution_failure(DownloadExecutionStatus.STORE_FAILED, f"Unable to update the download queue: {exc}")
    except Exception as exc:
        with _EXECUTION_CLAIM_LOCK: _ACTIVE_EXECUTIONS.discard(plan.reference)
        error = str(exc) or type(exc).__name__
        try:
            interrupted = store.get(plan.job_id)
            if interrupted is not None and plan.item_index < len(interrupted.items):
                failed_entry = interrupted.items[plan.item_index]
                if failed_entry.state not in {
                    AcquisitionState.COMPLETE,
                    AcquisitionState.SKIPPED,
                    AcquisitionState.FAILED,
                }:
                    failed_entry.state = AcquisitionState.FAILED
                    failed_entry.error = error
                    failed_entry.failure_stage = AcquisitionFailureStage.TRANSPORT
                    interrupted.touch()
                    store.save(interrupted)
        except Exception:
            pass
        return DownloadExecutionResult(
            DownloadExecutionStatus.FAILED,
            "Download execution failed safely.",
            plan=plan,
            error=error,
        )

    try:
        if authoritative is None or plan.item_index >= len(authoritative.items):
            return _execution_failure(DownloadExecutionStatus.NOT_FOUND, "The queue record disappeared after execution.")
        final_entry = authoritative.items[plan.item_index]
        if final_entry.state in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED}:
            message = (f"{plan.title} was already present and left the active queue." if final_entry.state is AcquisitionState.SKIPPED else f"{plan.title} finished downloading.")
            return DownloadExecutionResult(DownloadExecutionStatus.COMPLETED, message, plan=plan)
        stage = {
            AcquisitionFailureStage.TRANSPORT: "Download failed",
            AcquisitionFailureStage.VALIDATION: "File validation failed",
            AcquisitionFailureStage.LYRICS: "Lyrics processing failed",
            AcquisitionFailureStage.LRC: "LRC creation failed",
            AcquisitionFailureStage.STATE: "Library update failed",
            None: "Download failed",
        }[final_entry.failure_stage]
        return DownloadExecutionResult(DownloadExecutionStatus.FAILED, stage, plan=plan, failure_stage=stage, error=final_entry.error or "The selected download did not complete.")
    finally:
        with _EXECUTION_CLAIM_LOCK:
            _ACTIVE_EXECUTIONS.discard(plan.reference)


def execute_selected_retry(
    settings: Settings,
    plan: DownloadRetryPlan,
    *,
    jobs_path: Path = DEFAULT_JOBS_FILE,
    store_factory: StoreFactory = JobStore,
    runner: Runner = run_job,
    integration: Integration = integrate_downloaded_mp3,
    song_fetcher: SongFetcher = get_song,
    lyrics_dir: Path | None = None,
    progress: ExecutionProgressCallback | None = None,
) -> DownloadRetryResult:
    with _EXECUTION_CLAIM_LOCK:
        if plan.reference in _ACTIVE_EXECUTIONS:
            return DownloadRetryResult(DownloadRetryStatus.ALREADY_RUNNING, "This song is already downloading or processing.", plan=plan)
        try:
            store = store_factory(Path(jobs_path)); job = store.get(plan.job_id)
        except PermissionError:
            return DownloadRetryResult(DownloadRetryStatus.STORE_FAILED, "Unable to update the download queue: permission denied.", plan=plan)
        except (JobStoreError, OSError) as exc:
            return DownloadRetryResult(DownloadRetryStatus.STORE_FAILED, f"Unable to update the download queue: {exc}", plan=plan)
        if job is None or plan.item_index >= len(job.items):
            return DownloadRetryResult(DownloadRetryStatus.NOT_FOUND, "This queue item no longer exists.", plan=plan)
        entry = job.items[plan.item_index]
        if entry.item.identifier != plan.song_id or entry.item.destination != plan.destination:
            return DownloadRetryResult(DownloadRetryStatus.NOT_FOUND, "The selected queue item changed before retry could start.", plan=plan)
        if entry.state is not AcquisitionState.FAILED:
            return DownloadRetryResult(DownloadRetryStatus.ALREADY_RUNNING, "This song is no longer failed and cannot be retried here.", plan=plan)
        _ACTIVE_EXECUTIONS.add(plan.reference)
    try:
        def report(index: int, total: int, written: int, remote_total: int | None) -> None:
            if progress:
                progress(DownloadProgress(plan.reference, DownloadExecutionStatus.DOWNLOADING, written, remote_total, "Downloading…"))
        def postprocess(result: AcquisitionResult) -> IntegrationResult:
            if progress:
                progress(DownloadProgress(plan.reference, DownloadExecutionStatus.PROCESSING, result.bytes_written, entry.item.expected_size, "Processing lyrics and library metadata…"))
            return integration(entry.item, song_fetcher=lambda song_id: song_fetcher(settings, song_id), lyrics_dir=Path(lyrics_dir) if lyrics_dir is not None else settings.lyrics_dir, settings=settings)
        runner(job, store, policy=DownloadPolicy(), progress=report, postprocess=postprocess, item_indexes={plan.item_index})
        authoritative = store.get(plan.job_id)
        final = authoritative.items[plan.item_index] if authoritative is not None and plan.item_index < len(authoritative.items) else None
        if final is not None and final.state in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED}:
            return DownloadRetryResult(DownloadRetryStatus.COMPLETED, f"{plan.title} finished successfully.", plan=plan)
        error = final.error if final is not None else "The queue record disappeared after retry."
        return DownloadRetryResult(DownloadRetryStatus.FAILED, "Retry failed", plan=plan, error=error)
    except Exception as exc:
        return DownloadRetryResult(DownloadRetryStatus.FAILED, "Retry failed", plan=plan, error=str(exc) or type(exc).__name__)
    finally:
        with _EXECUTION_CLAIM_LOCK: _ACTIVE_EXECUTIONS.discard(plan.reference)

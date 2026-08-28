from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from ..acquisition.jobs import DEFAULT_JOBS_FILE, JobStoreError
from ..acquisition.models import AcquisitionState


class QueueStatus(str, Enum):
    PENDING = "pending"
    CHECKING_EXISTING = "checking_existing"
    DOWNLOADING = "downloading"
    VALIDATING = "validating"
    POST_PROCESSING = "post_processing"
    COMPLETED = "complete"
    SKIPPED = "skipped"
    FAILED = "failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class QueueItem:
    title: str | None
    destination: Path | None
    status: QueueStatus
    stored_state: str
    bytes_written: int
    expected_bytes: int | None
    resumed: bool
    error: str | None
    retryable: bool


@dataclass(frozen=True, slots=True)
class QueueJob:
    display_number: int
    job_id: str
    label: str
    created_at: str | None
    destination: Path | None
    total_item_count: int
    pending_item_count: int
    active_item_count: int
    completed_item_count: int
    failed_item_count: int
    status: QueueStatus
    stored_state: str
    retryable: bool
    deletion_allowed: bool
    items: tuple[QueueItem, ...]


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    jobs: tuple[QueueJob, ...]
    total_job_count: int
    active_job_count: int
    pending_job_count: int
    completed_job_count: int
    failed_job_count: int


class QueueReferenceError(ValueError):
    """A friendly queue reference does not identify a displayed job."""


_ACTIVE = {
    QueueStatus.CHECKING_EXISTING,
    QueueStatus.DOWNLOADING,
    QueueStatus.VALIDATING,
    QueueStatus.POST_PROCESSING,
}
_TERMINAL = {QueueStatus.COMPLETED, QueueStatus.SKIPPED}
_DELETE_BLOCKING_STORED_STATES = {
    AcquisitionState.CHECKING_EXISTING.value,
    AcquisitionState.DOWNLOADING.value,
    AcquisitionState.VALIDATING.value,
}


def _text(value: Any) -> str | None:
    if value is None or isinstance(value, (Mapping, list, tuple, set)):
        return None
    text = str(value).strip()
    return text or None


def _nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(0, parsed)


def _optional_nonnegative_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _item_status(value: Any) -> tuple[QueueStatus, str]:
    stored = _text(value) or AcquisitionState.PENDING.value
    normalized = {
        AcquisitionState.PENDING.value: QueueStatus.PENDING,
        AcquisitionState.RESOLVED.value: QueueStatus.PENDING,
        AcquisitionState.CHECKING_EXISTING.value: QueueStatus.CHECKING_EXISTING,
        AcquisitionState.DOWNLOADING.value: QueueStatus.DOWNLOADING,
        AcquisitionState.DOWNLOADED.value: QueueStatus.POST_PROCESSING,
        AcquisitionState.VALIDATING.value: QueueStatus.VALIDATING,
        AcquisitionState.IMPORTED.value: QueueStatus.POST_PROCESSING,
        AcquisitionState.COMPLETE.value: QueueStatus.COMPLETED,
        AcquisitionState.SKIPPED.value: QueueStatus.SKIPPED,
        AcquisitionState.FAILED.value: QueueStatus.FAILED,
    }.get(stored, QueueStatus.UNKNOWN)
    return normalized, stored


def _queue_item(raw: Any) -> QueueItem:
    record = raw if isinstance(raw, Mapping) else {}
    item = record.get("item")
    item_record = item if isinstance(item, Mapping) else {}
    status, stored_state = _item_status(record.get("state"))
    destination_text = _text(item_record.get("destination"))
    expected = _optional_nonnegative_int(item_record.get("expected_size"))
    error = _text(record.get("error"))
    return QueueItem(
        title=_text(item_record.get("title")),
        destination=Path(destination_text) if destination_text else None,
        status=status,
        stored_state=stored_state,
        bytes_written=_nonnegative_int(record.get("bytes_written")),
        expected_bytes=expected,
        resumed=bool(record.get("resumed", False)),
        error=error,
        retryable=status not in _TERMINAL and status is not QueueStatus.UNKNOWN,
    )


def _job_status(items: tuple[QueueItem, ...]) -> tuple[QueueStatus, str]:
    statuses = [item.status for item in items]
    if not statuses:
        return QueueStatus.COMPLETED, AcquisitionState.COMPLETE.value
    if QueueStatus.FAILED in statuses:
        return QueueStatus.FAILED, AcquisitionState.FAILED.value
    if all(status in _TERMINAL for status in statuses):
        return QueueStatus.COMPLETED, AcquisitionState.COMPLETE.value
    if any(status in _ACTIVE for status in statuses):
        normalized = next(status for status in statuses if status in _ACTIVE)
        legacy = (
            AcquisitionState.DOWNLOADING.value
            if any(item.stored_state in {
                AcquisitionState.DOWNLOADING.value,
                AcquisitionState.VALIDATING.value,
            } for item in items)
            else AcquisitionState.PENDING.value
        )
        return normalized, legacy
    if all(status is QueueStatus.UNKNOWN for status in statuses):
        return QueueStatus.UNKNOWN, QueueStatus.UNKNOWN.value
    return QueueStatus.PENDING, AcquisitionState.PENDING.value


def _job_label(items: tuple[QueueItem, ...]) -> str:
    titles = [item.title for item in items if item.title]
    if not titles:
        return "Untitled job"
    if len(items) == 1:
        return titles[0]
    return f"{titles[0]} + {len(items) - 1} more"


def _read_jobs(path: Path) -> list[tuple[int, str, Mapping[str, Any]]]:
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise JobStoreError(f"Could not read acquisition job store: {path}") from exc
    jobs = raw.get("jobs", {}) if isinstance(raw, Mapping) else None
    if not isinstance(jobs, Mapping):
        raise JobStoreError(f"Invalid acquisition job store format: {path}")
    records: list[tuple[int, str, Mapping[str, Any]]] = []
    for position, (stored_id, payload) in enumerate(jobs.items()):
        if isinstance(payload, Mapping):
            records.append((position, str(stored_id), payload))
    records.sort(
        key=lambda record: (_text(record[2].get("created_at")) or ""),
        reverse=True,
    )
    return records


def get_queue_snapshot(path: Path = DEFAULT_JOBS_FILE) -> QueueSnapshot:
    """Read and normalize the persistent queue without mutating or recovering it."""

    jobs: list[QueueJob] = []
    for display_number, (_, stored_id, raw) in enumerate(_read_jobs(Path(path)), start=1):
        raw_items = raw.get("items", [])
        source_items = (
            raw_items
            if isinstance(raw_items, Sequence) and not isinstance(raw_items, (str, bytes, bytearray))
            else []
        )
        items = tuple(_queue_item(item) for item in source_items)
        status, stored_state = _job_status(items)
        destinations = [item.destination for item in items if item.destination is not None]
        job_id = _text(raw.get("job_id")) or stored_id
        jobs.append(
            QueueJob(
                display_number=display_number,
                job_id=job_id,
                label=_job_label(items),
                created_at=_text(raw.get("created_at")),
                destination=destinations[0] if len(destinations) == 1 else None,
                total_item_count=len(items),
                pending_item_count=sum(item.status in {QueueStatus.PENDING, QueueStatus.UNKNOWN} for item in items),
                active_item_count=sum(item.status in _ACTIVE for item in items),
                completed_item_count=sum(item.status in _TERMINAL for item in items),
                failed_item_count=sum(item.status is QueueStatus.FAILED for item in items),
                status=status,
                stored_state=stored_state,
                retryable=any(item.retryable for item in items),
                deletion_allowed=not any(
                    item.stored_state in _DELETE_BLOCKING_STORED_STATES for item in items
                ),
                items=items,
            )
        )

    snapshot_jobs = tuple(jobs)
    return QueueSnapshot(
        jobs=snapshot_jobs,
        total_job_count=len(snapshot_jobs),
        active_job_count=sum(job.status in _ACTIVE for job in snapshot_jobs),
        pending_job_count=sum(job.status in {QueueStatus.PENDING, QueueStatus.UNKNOWN} for job in snapshot_jobs),
        completed_job_count=sum(job.status is QueueStatus.COMPLETED for job in snapshot_jobs),
        failed_job_count=sum(job.status is QueueStatus.FAILED for job in snapshot_jobs),
    )


def resolve_queue_reference(snapshot: QueueSnapshot, reference: str | int) -> QueueJob:
    """Resolve a display number, ``latest``, or exact persistent job ID."""

    text = str(reference).strip()
    if text.lower() == "latest":
        if snapshot.jobs:
            return snapshot.jobs[0]
        raise QueueReferenceError("The acquisition queue is empty")
    if text.isdigit():
        number = int(text)
        if 1 <= number <= len(snapshot.jobs):
            return snapshot.jobs[number - 1]
        raise QueueReferenceError(f"Queue number is out of range: {text}")
    for job in snapshot.jobs:
        if job.job_id == text:
            return job
    raise QueueReferenceError(f"Acquisition job not found: {text}")

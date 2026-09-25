from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
from typing import Callable, Any

from .downloader import DownloadPolicy, download_to
from .duplicates import find_duplicate
from .jobs import AcquisitionJob, JobStore
from .models import (
    AcquisitionFailureStage,
    AcquisitionPostProcessingError,
    AcquisitionResult,
    AcquisitionState,
)


@dataclass(frozen=True, slots=True)
class AcquisitionRunSummary:
    """High-level outcome of running a persistent acquisition job."""

    job_id: str
    completed: int
    skipped: int
    failed: int
    pending: int

    @property
    def ok(self) -> bool:
        return self.failed == 0 and self.pending == 0


ItemProgressCallback = Callable[[int, int, int, int | None], None]
PostprocessCallback = Callable[[AcquisitionResult], Any]


def _sha256(path: Path, chunk_size: int = 1024 * 128) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _can_retry_postprocessing(entry: Any) -> bool:
    stage = entry.failure_stage
    if entry.state is not AcquisitionState.FAILED or stage is None or not stage.is_post_processing:
        return False
    destination = entry.item.destination
    if not destination.is_file():
        return False
    if entry.retry_file_size is None or not entry.retry_file_sha256:
        return False
    try:
        actual_size = destination.stat().st_size
        return (
            actual_size == entry.retry_file_size
            and _sha256(destination) == entry.retry_file_sha256.lower()
        )
    except OSError:
        return False


def _record_postprocessing_failure(entry: Any, exc: AcquisitionPostProcessingError) -> None:
    entry.state = AcquisitionState.FAILED
    entry.error = str(exc)
    entry.failure_stage = exc.stage
    entry.retry_file_size = None
    entry.retry_file_sha256 = None
    destination = entry.item.destination
    if exc.reuse_finalized_file and destination.is_file():
        try:
            entry.retry_file_size = destination.stat().st_size
            entry.retry_file_sha256 = _sha256(destination)
        except OSError:
            entry.retry_file_size = None
            entry.retry_file_sha256 = None


def run_job(
    job: AcquisitionJob,
    store: JobStore,
    *,
    policy: DownloadPolicy | None = None,
    progress: ItemProgressCallback | None = None,
    postprocess: PostprocessCallback | None = None,
    item_indexes: set[int] | None = None,
) -> AcquisitionRunSummary:
    """Run a persistent acquisition job one item at a time.

    The runner is intentionally sequential and conservative for now. It owns
    job-level state, duplicate checks, persistence, and retry/recovery policy;
    the downloader remains responsible for HTTP transport and file validation.
    """

    policy = policy or DownloadPolicy()
    total = len(job.items)

    def report(index: int, written: int, remote_total: int | None) -> None:
        if progress:
            progress(index, total, written, remote_total)

    for index, entry in enumerate(job.items):
        if item_indexes is not None and index not in item_indexes:
            continue
        if entry.state in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED}:
            continue

        retry_postprocessing = postprocess is not None and _can_retry_postprocessing(entry)

        if retry_postprocessing:
            result = AcquisitionResult(
                item=entry.item,
                state=AcquisitionState.COMPLETE,
                destination=entry.item.destination,
                bytes_written=entry.bytes_written,
                resumed=entry.resumed,
                postprocessing_retry=True,
            )
            try:
                if postprocess is not None:
                    postprocess(result)
                job.record_result(index, result)
                store.save(job)
            except AcquisitionPostProcessingError as exc:
                _record_postprocessing_failure(entry, exc)
                entry.error = f"Post-processing retry from existing finalized file failed: {entry.error}"
                job.touch()
                store.save(job)
            except Exception as exc:
                entry.state = AcquisitionState.FAILED
                entry.error = f"Post-processing retry from existing finalized file failed: {exc}"
                entry.failure_stage = AcquisitionFailureStage.LYRICS
                entry.retry_file_size = None
                entry.retry_file_sha256 = None
                job.touch()
                store.save(job)
            continue

        entry.error = None
        entry.failure_stage = None
        entry.retry_file_size = None
        entry.retry_file_sha256 = None
        entry.state = AcquisitionState.CHECKING_EXISTING
        entry.resumed = False
        job.touch()
        store.save(job)

        try:
            duplicate = find_duplicate(entry.item)
            if duplicate is not None:
                entry.state = AcquisitionState.SKIPPED
                entry.bytes_written = duplicate.path.stat().st_size
                entry.error = None
                entry.failure_stage = None
                job.touch()
                store.save(job)
                continue

            entry.state = AcquisitionState.RESOLVED
            job.touch()
            store.save(job)

            def item_progress(written: int, remote_total: int | None) -> None:
                entry.bytes_written = written
                job.touch()
                store.save(job)
                report(index, written, remote_total)

            result: AcquisitionResult = download_to(
                entry.item,
                policy,
                progress=item_progress,
            )
            if result.state is AcquisitionState.COMPLETE and postprocess is not None:
                try:
                    postprocess(result)
                except AcquisitionPostProcessingError as exc:
                    entry.bytes_written = result.bytes_written
                    entry.resumed = result.resumed
                    _record_postprocessing_failure(entry, exc)
                    job.touch()
                    store.save(job)
                    continue
                except Exception as exc:
                    entry.state = AcquisitionState.FAILED
                    entry.bytes_written = result.bytes_written
                    entry.resumed = result.resumed
                    entry.error = f"Audio download completed, but post-processing failed: {exc}"
                    entry.failure_stage = AcquisitionFailureStage.LYRICS
                    entry.retry_file_size = None
                    entry.retry_file_sha256 = None
                    job.touch()
                    store.save(job)
                    continue
            job.record_result(index, result)
            store.save(job)
        except Exception as exc:  # keep one bad item from killing the whole job
            entry.state = AcquisitionState.FAILED
            entry.error = str(exc)
            entry.failure_stage = AcquisitionFailureStage.TRANSPORT
            entry.retry_file_size = None
            entry.retry_file_sha256 = None
            job.touch()
            store.save(job)

    return _summary(job)


def _summary(job: AcquisitionJob) -> AcquisitionRunSummary:
    completed = sum(entry.state is AcquisitionState.COMPLETE for entry in job.items)
    skipped = sum(entry.state is AcquisitionState.SKIPPED for entry in job.items)
    failed = sum(entry.state is AcquisitionState.FAILED for entry in job.items)
    pending = sum(
        entry.state
        not in {
            AcquisitionState.COMPLETE,
            AcquisitionState.SKIPPED,
            AcquisitionState.FAILED,
        }
        for entry in job.items
    )
    return AcquisitionRunSummary(
        job_id=job.job_id,
        completed=completed,
        skipped=skipped,
        failed=failed,
        pending=pending,
    )

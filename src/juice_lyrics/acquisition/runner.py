from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Any

from .downloader import DownloadPolicy, download_to
from .duplicates import find_duplicate
from .jobs import AcquisitionJob, JobStore
from .models import AcquisitionResult, AcquisitionState


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


def run_job(
    job: AcquisitionJob,
    store: JobStore,
    *,
    policy: DownloadPolicy | None = None,
    progress: ItemProgressCallback | None = None,
    postprocess: PostprocessCallback | None = None,
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
        if entry.state in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED}:
            continue

        entry.error = None
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
                postprocess(result)
            job.record_result(index, result)
            store.save(job)
        except Exception as exc:  # keep one bad item from killing the whole job
            entry.state = AcquisitionState.FAILED
            entry.error = str(exc)
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

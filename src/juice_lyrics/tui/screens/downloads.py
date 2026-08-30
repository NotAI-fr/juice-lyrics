from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from rich.text import Text
from textual import work
from textual.containers import Container, Grid, VerticalScroll
from textual.events import Key, Resize, ScreenResume
from textual.geometry import Region
from textual.widget import Widget
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from ...services.acquisition_queue import (
    QueueFailureStage,
    QueueItem,
    QueueJob,
    QueueSnapshot,
    QueueStatus,
)
from .base import HubScreen

QueueProvider = Callable[[], QueueSnapshot]


@dataclass(frozen=True, slots=True)
class QueueLoadOutcome:
    snapshot: QueueSnapshot | None = None
    error: str | None = None


class DownloadsScreen(HubScreen):
    """Read-only persistent acquisition queue browser."""

    def __init__(self, *, queue_provider: QueueProvider) -> None:
        super().__init__("downloads", "Downloads")
        self._queue_provider = queue_provider
        self.snapshot: QueueSnapshot | None = None
        self.jobs: tuple[QueueJob, ...] = ()
        self.selected_index = 0
        self._details_mode = False
        self._refresh_worker: Worker[QueueLoadOutcome] | None = None

    def compose_content(self) -> Iterable[Widget]:
        yield Static(
            "Jobs 0 · Pending 0 · Active 0 · Completed 0 · Failed 0",
            id="downloads-summary",
            markup=False,
        )
        yield Static("Loading acquisition queue…", id="downloads-status", markup=False)
        with Grid(id="downloads-main"):
            with Container(classes="downloads-panel", id="download-jobs-panel"):
                yield Static("Jobs · loading", classes="panel-title", id="download-jobs-title")
                with VerticalScroll(id="download-jobs-scroll"):
                    yield Static("Loading queue…", id="download-jobs", markup=False)
            with Container(classes="downloads-panel", id="download-details-panel"):
                yield Static("Job details", classes="panel-title")
                with VerticalScroll(id="download-details-scroll"):
                    yield Static("Select a job to inspect its tracks.", id="download-details", markup=False)
        yield Static("r refresh · Enter details", id="downloads-position", markup=False)

    def on_screen_resume(self, event: ScreenResume) -> None:
        if self.snapshot is None and self._refresh_worker is None:
            self.refresh_snapshot()

    def refresh_snapshot(self) -> None:
        if self.snapshot is None:
            self.query_one("#download-jobs", Static).update("Loading queue…")
            self.query_one("#download-details", Static).update("Waiting for queue data…")
        self.query_one("#downloads-status", Static).update("Refreshing queue…")
        self.query_one("#downloads-status", Static).remove_class("-error")
        self._refresh_worker = self._load_queue()

    @work(thread=True, exclusive=True, group="downloads-queue", exit_on_error=False)
    def _load_queue(self) -> QueueLoadOutcome:
        try:
            return QueueLoadOutcome(snapshot=self._queue_provider())
        except Exception as exc:
            return QueueLoadOutcome(error=str(exc) or type(exc).__name__)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._refresh_worker:
            return
        if event.state is WorkerState.SUCCESS:
            self._apply_queue(event.worker.result)
        elif event.state is WorkerState.ERROR:
            message = str(event.worker.error) if event.worker.error else "Unknown worker error"
            self._apply_queue(QueueLoadOutcome(error=message))

    def _apply_queue(self, outcome: QueueLoadOutcome) -> None:
        status = self.query_one("#downloads-status", Static)
        if outcome.error or outcome.snapshot is None:
            status.update(f"Queue unavailable: {outcome.error or 'Unknown queue error'}")
            status.add_class("-error")
            if self.snapshot is None:
                self.jobs = ()
                self.query_one("#download-jobs-title", Static).update("Jobs · unavailable")
                self.query_one("#download-jobs", Static).update("Unable to load acquisition jobs.")
                self.query_one("#download-details", Static).update("Queue details are unavailable.")
                self.query_one("#downloads-position", Static).update("r retry refresh")
            return

        previous_id = self.selected_job.job_id if self.selected_job is not None else None
        self.snapshot = outcome.snapshot
        self.jobs = outcome.snapshot.jobs
        if previous_id is not None:
            self.selected_index = next(
                (index for index, job in enumerate(self.jobs) if job.job_id == previous_id),
                0,
            )
        else:
            self.selected_index = 0
        self._details_mode = False
        self.remove_class("-details-mode")
        self._render_summary()
        self._render_jobs()
        self._render_selected_details()
        if self.jobs:
            status.update("Read-only queue · no Run, Retry, or Delete actions")
            self._update_position()
            self.call_after_refresh(self._scroll_selected_job_into_view)
        else:
            status.update("No acquisition jobs yet.")
            self.query_one("#downloads-position", Static).update("r refresh · Queue is empty")

    @property
    def selected_job(self) -> QueueJob | None:
        if not self.jobs:
            return None
        return self.jobs[self.selected_index]

    def _render_summary(self) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        self.query_one("#downloads-summary", Static).update(
            f"Jobs {snapshot.total_job_count} · Pending {snapshot.pending_job_count} · "
            f"Active {snapshot.active_job_count} · Completed {snapshot.completed_job_count} · "
            f"Failed {snapshot.failed_job_count}"
        )

    def _render_jobs(self) -> None:
        self.query_one("#download-jobs-title", Static).update(f"Jobs · {len(self.jobs)}")
        if not self.jobs:
            self.query_one("#download-jobs", Static).update("No acquisition jobs.")
            return
        lines = []
        for index, job in enumerate(self.jobs):
            marker = ">" if index == self.selected_index else " "
            status = _status_label(job.status)
            summary = f"{job.completed_item_count} done"
            if job.failed_item_count:
                summary += f" · {job.failed_item_count} failed"
            lines.append(
                f"{marker} {job.display_number:>2}  {status:<18} "
                f"{job.label[:28]:28} · {job.total_item_count} tracks · {summary}"
            )
        self.query_one("#download-jobs", Static).update(
            Text("\n".join(lines), no_wrap=True, overflow="ellipsis")
        )

    def _render_selected_details(self) -> None:
        job = self.selected_job
        details = self.query_one("#download-details", Static)
        scroll = self.query_one("#download-details-scroll", VerticalScroll)
        scroll.scroll_home(animate=False, immediate=True)
        if job is None:
            details.update("No job selected.")
            return
        destination = str(job.destination) if job.destination is not None else "See track destinations"
        lines = [
            job.label,
            "",
            f"Reference      {job.display_number}",
            f"Job ID         {job.job_id}",
            f"Status         {_status_label(job.status)}",
            f"Destination    {destination}",
            f"Created        {_timestamp(job.created_at)}",
            f"Updated        {_timestamp(job.updated_at)}",
            f"Tracks         {job.total_item_count}",
            f"Progress       {job.completed_item_count} completed · {job.failed_item_count} failed · "
            f"{job.pending_item_count} pending · {job.active_item_count} active",
            f"Retry          {_job_retry_label(job)}",
            "",
            "Tracks",
        ]
        if not job.items:
            lines.append("  No tracks stored in this job.")
        for index, item in enumerate(job.items, start=1):
            lines.extend(_item_lines(index, item))
        details.update(Text("\n".join(lines), overflow="ellipsis"))

    def _update_position(self) -> None:
        if not self.jobs:
            return
        suffix = "Esc job list · PgUp/PgDn details" if self._details_mode else "Enter details · r refresh"
        self.query_one("#downloads-position", Static).update(
            f"Job {self.selected_index + 1} of {len(self.jobs)} · {suffix}"
        )

    def on_key(self, event: Key) -> None:
        if event.key == "escape" and self._details_mode:
            self._details_mode = False
            self.remove_class("-details-mode")
            self._update_position()
        elif event.key == "enter" and self.selected_job is not None:
            self._details_mode = True
            self.add_class("-details-mode")
            self.query_one("#download-details-scroll", VerticalScroll).scroll_home(
                animate=False,
                immediate=True,
            )
            self._update_position()
        elif event.key in ("pagedown", "pageup") and self._details_mode:
            scroll = self.query_one("#download-details-scroll", VerticalScroll)
            if event.key == "pagedown":
                scroll.scroll_page_down(animate=False)
            else:
                scroll.scroll_page_up(animate=False)
        elif event.key in ("down", "j"):
            self._select_job(self.selected_index + 1)
        elif event.key in ("up", "k"):
            self._select_job(self.selected_index - 1)
        elif event.key == "home":
            self._select_job(0)
        elif event.key == "end":
            self._select_job(len(self.jobs) - 1)
        elif event.key in ("pagedown", "pageup"):
            scroll = self.query_one("#download-jobs-scroll", VerticalScroll)
            step = max(1, scroll.size.height - 1)
            self._select_job(self.selected_index + (step if event.key == "pagedown" else -step))
        else:
            return
        event.prevent_default()
        event.stop()

    def _select_job(self, index: int) -> None:
        if not self.jobs:
            return
        self.selected_index = max(0, min(len(self.jobs) - 1, index))
        self._render_jobs()
        self._render_selected_details()
        self._update_position()
        self.call_after_refresh(self._scroll_selected_job_into_view)

    def _scroll_selected_job_into_view(self) -> None:
        if not self.jobs:
            return
        scroll = self.query_one("#download-jobs-scroll", VerticalScroll)
        scroll.scroll_to_region(
            Region(0, self.selected_index, max(1, scroll.virtual_size.width), 1),
            animate=False,
            immediate=True,
            x_axis=False,
        )

    def on_resize(self, event: Resize) -> None:
        super().on_resize(event)
        self.set_class(event.size.width < 90, "-downloads-narrow")
        if self.jobs:
            self.call_after_refresh(self._scroll_selected_job_into_view)


def _status_label(status: QueueStatus) -> str:
    return {
        QueueStatus.PENDING: "Queued",
        QueueStatus.CHECKING_EXISTING: "Checking existing",
        QueueStatus.DOWNLOADING: "Downloading",
        QueueStatus.VALIDATING: "Validating",
        QueueStatus.POST_PROCESSING: "Processing lyrics",
        QueueStatus.COMPLETED: "Completed",
        QueueStatus.SKIPPED: "Skipped",
        QueueStatus.FAILED: "Failed",
        QueueStatus.UNKNOWN: "Unknown",
    }[status]


def _failure_label(stage: QueueFailureStage | None) -> str:
    return {
        QueueFailureStage.TRANSPORT: "Download failed",
        QueueFailureStage.VALIDATION: "Validation failed",
        QueueFailureStage.LYRICS: "Lyrics processing failed",
        QueueFailureStage.LRC: "LRC creation failed",
        QueueFailureStage.STATE: "Library-state update failed",
        QueueFailureStage.UNKNOWN: "Processing failed (unknown stage)",
        None: "Failure stage unavailable",
    }[stage]


def _item_retry_label(item: QueueItem) -> str:
    if item.postprocessing_retryable:
        return "Retry available from verified downloaded file"
    if item.status is QueueStatus.FAILED and item.retryable:
        return "Full download retry required"
    return "Not retryable"


def _job_retry_label(job: QueueJob) -> str:
    if job.status is not QueueStatus.FAILED:
        return "Not applicable"
    if any(item.postprocessing_retryable for item in job.items):
        return "Safe post-processing retry available"
    if job.retryable:
        return "Full download retry may be required"
    return "Not retryable"


def _item_lines(index: int, item: QueueItem) -> list[str]:
    title = item.title or "Untitled track"
    destination = str(item.destination) if item.destination is not None else "Unavailable"
    lines = [
        "",
        f"  {index}. {title}",
        f"     Status       {_status_label(item.status)}",
        f"     Destination  {destination}",
    ]
    if item.expected_bytes is not None or item.bytes_written:
        expected = str(item.expected_bytes) if item.expected_bytes is not None else "unknown"
        lines.append(f"     Progress     {item.bytes_written} / {expected} bytes")
    if item.status is QueueStatus.FAILED:
        lines.append(f"     Failure      {_failure_label(item.failure_stage)}")
        if item.error:
            lines.append(f"     Error        {_concise_error(item.error)}")
        lines.append(f"     Retry        {_item_retry_label(item)}")
    return lines


def _concise_error(error: str, limit: int = 240) -> str:
    text = " ".join(error.splitlines()).strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _timestamp(value: str | None) -> str:
    if not value:
        return "Unavailable"
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    zone = f" {parsed.tzname()}" if parsed.tzinfo and parsed.tzname() else ""
    return parsed.strftime("%Y-%m-%d %H:%M:%S") + zone

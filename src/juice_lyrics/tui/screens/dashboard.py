from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from textual import work
from textual.containers import Container, Grid
from textual.widget import Widget
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from ...services import LibraryStatus, QueueSnapshot
from .base import HubScreen


@dataclass(frozen=True, slots=True)
class DashboardSnapshot:
    library: LibraryStatus | None
    queue: QueueSnapshot | None
    library_error: str | None = None
    queue_error: str | None = None


class DashboardScreen(HubScreen):
    """Read-only summary assembled exclusively from application services."""

    def __init__(
        self,
        settings: Any,
        *,
        library_status_provider: Callable[[Any], LibraryStatus],
        queue_snapshot_provider: Callable[[], QueueSnapshot],
    ) -> None:
        super().__init__("dashboard", "Dashboard")
        self.settings = settings
        self._library_status_provider = library_status_provider
        self._queue_snapshot_provider = queue_snapshot_provider
        self._refresh_worker: Worker[DashboardSnapshot] | None = None

    def compose_content(self) -> Iterable[Widget]:
        with Grid(id="dashboard-panels"):
            with Container(classes="dashboard-panel", id="library-panel"):
                yield Static("Library", classes="panel-title")
                yield Static("Loading…", id="library-data", markup=False)
                yield Static("", id="library-error", classes="panel-error", markup=False)
            with Container(classes="dashboard-panel", id="downloads-panel"):
                yield Static("Downloads", classes="panel-title")
                yield Static("Loading…", id="queue-data", markup=False)
                yield Static("", id="queue-error", classes="panel-error", markup=False)

    def on_mount(self) -> None:
        self.refresh_snapshot()

    def refresh_snapshot(self) -> None:
        self.query_one("#library-data", Static).update("Loading library status…")
        self.query_one("#queue-data", Static).update("Loading queue status…")
        self.query_one("#library-error", Static).update("")
        self.query_one("#queue-error", Static).update("")
        self._refresh_worker = self._load_snapshot()

    @work(
        thread=True,
        exclusive=True,
        group="dashboard-snapshot",
        exit_on_error=False,
    )
    def _load_snapshot(self) -> DashboardSnapshot:
        library = queue = None
        library_error = queue_error = None
        try:
            library = self._library_status_provider(self.settings)
        except Exception as exc:
            library_error = str(exc) or type(exc).__name__
        try:
            queue = self._queue_snapshot_provider()
        except Exception as exc:
            queue_error = str(exc) or type(exc).__name__
        return DashboardSnapshot(library, queue, library_error, queue_error)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._refresh_worker:
            return
        if event.state is WorkerState.SUCCESS:
            self._apply_snapshot(event.worker.result)
        elif event.state is WorkerState.ERROR:
            message = str(event.worker.error) if event.worker.error else "Unknown worker error"
            self._apply_snapshot(DashboardSnapshot(None, None, message, message))

    def _apply_snapshot(self, snapshot: DashboardSnapshot) -> None:
        self._render_library(snapshot.library, snapshot.library_error)
        self._render_queue(snapshot.queue, snapshot.queue_error)

    def _render_library(self, status: LibraryStatus | None, failure: str | None) -> None:
        error = self.query_one("#library-error", Static)
        if status is None:
            self.query_one("#library-data", Static).update("Library data unavailable")
            error.update(f"Warning: {failure or 'Unknown library status error'}")
            return

        lines = (
            f"Path                 {status.library_path}",
            f"MP3 tracks           {status.track_count}",
            f"Synced lyrics        {status.embedded_synced_count}",
            f"Plain lyrics         {status.embedded_plain_count}",
            f"Missing / invalid    {status.missing_or_invalid_count}",
            f"New / changed        {status.new_or_changed_count}",
            f"Backups              {status.backup_count}",
            f"rmpc LRC files       {status.rmpc_lrc_count}",
        )
        self.query_one("#library-data", Static).update("\n".join(lines))
        error.update("\n".join(status.warnings))

    def _render_queue(self, snapshot: QueueSnapshot | None, failure: str | None) -> None:
        error = self.query_one("#queue-error", Static)
        if snapshot is None:
            self.query_one("#queue-data", Static).update("Queue data unavailable")
            error.update(f"Warning: {failure or 'Unknown queue status error'}")
            return

        lines = (
            f"Total jobs           {snapshot.total_job_count}",
            f"Pending              {snapshot.pending_job_count}",
            f"Active               {snapshot.active_job_count}",
            f"Completed            {snapshot.completed_job_count}",
            f"Failed               {snapshot.failed_job_count}",
        )
        self.query_one("#queue-data", Static).update("\n".join(lines))
        error.update("")

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from textual import work
from textual.containers import Container, Grid
from textual.events import ScreenResume
from textual.widget import Widget
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from ...services import LibraryStatus, QueueSnapshot
from .base import HubScreen


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
        self._refresh_worker: Worker[tuple[LibraryStatus | None, str | None]] | None = None
        self._queue_worker: Worker[tuple[QueueSnapshot | None, str | None]] | None = None
        self._invalidated = False

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

    def on_screen_resume(self, event: ScreenResume) -> None:
        if self._invalidated:
            self.refresh_snapshot()

    def refresh_snapshot(self) -> None:
        self._invalidated = False
        self.query_one("#library-data", Static).update("Loading library status…")
        self.query_one("#queue-data", Static).update("Loading queue status…")
        self.query_one("#library-error", Static).update("")
        self.query_one("#queue-error", Static).update("")
        self._refresh_worker = self._load_library()
        self._queue_worker = self._load_queue()

    def invalidate_snapshot(self) -> None:
        self._invalidated = True

    @work(
        thread=True,
        exclusive=True,
        group="dashboard-library",
        exit_on_error=False,
    )
    def _load_library(self) -> tuple[LibraryStatus | None, str | None]:
        try:
            return self._library_status_provider(self.settings), None
        except Exception as exc:
            return None, str(exc) or type(exc).__name__

    @work(thread=True, exclusive=True, group="dashboard-queue", exit_on_error=False)
    def _load_queue(self) -> tuple[QueueSnapshot | None, str | None]:
        try:
            return self._queue_snapshot_provider(), None
        except Exception as exc:
            return None, str(exc) or type(exc).__name__

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._refresh_worker:
            if event.state is WorkerState.SUCCESS:
                self._render_library(*event.worker.result)
            elif event.state is WorkerState.ERROR:
                message = str(event.worker.error) if event.worker.error else "Unable to load library data"
                self._render_library(None, message)
        elif event.worker is self._queue_worker:
            if event.state is WorkerState.SUCCESS:
                self._render_queue(*event.worker.result)
            elif event.state is WorkerState.ERROR:
                message = str(event.worker.error) if event.worker.error else "Unable to load queue data"
                self._render_queue(None, message)

    def _render_library(self, status: LibraryStatus | None, failure: str | None) -> None:
        error = self.query_one("#library-error", Static)
        if status is None:
            self.query_one("#library-data", Static).update(
                "Library data unavailable\n\nPress 5 for Settings"
            )
            error.update(f"Warning: {failure or 'Unknown library status error'}")
            return

        lines = (
            f"Path                 {status.library_path}",
            f"Audio tracks         {status.track_count}",
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

        waiting = sum(job.pending_item_count for job in snapshot.jobs)
        active = sum(job.active_item_count for job in snapshot.jobs)
        failed = sum(job.failed_item_count for job in snapshot.jobs)
        if not snapshot.jobs:
            waiting = snapshot.pending_job_count
            active = snapshot.active_job_count
            failed = snapshot.failed_job_count
        if waiting:
            lines = (
                f"{waiting} song{'s' if waiting != 1 else ''} ready to download",
                "",
                "Press 4 to Downloads",
            )
        elif active:
            lines = ("Downloading now", "", "Press 4 to Downloads")
        elif failed:
            label = "1 song needs attention" if failed == 1 else f"{failed} songs need attention"
            lines = (label, "", "Press 4 to Downloads")
        else:
            lines = ("Search for songs in Browse", "", "Press 2 to Browse")
        self.query_one("#queue-data", Static).update("\n".join(lines))
        error.update("")

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from textual.containers import Container, Grid
from textual.widget import Widget
from textual.widgets import Static

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
        self._refresh_library()
        self._refresh_queue()

    def _refresh_library(self) -> None:
        error = self.query_one("#library-error", Static)
        try:
            status = self._library_status_provider(self.settings)
        except Exception as exc:
            self.query_one("#library-data", Static).update("Library data unavailable")
            error.update(f"Warning: {exc}")
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

    def _refresh_queue(self) -> None:
        error = self.query_one("#queue-error", Static)
        try:
            snapshot = self._queue_snapshot_provider()
        except Exception as exc:
            self.query_one("#queue-data", Static).update("Queue data unavailable")
            error.update(f"Warning: {exc}")
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

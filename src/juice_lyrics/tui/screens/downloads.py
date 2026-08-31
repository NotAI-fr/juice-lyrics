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

from ...services.download_queue import DownloadQueueItem, DownloadQueueItemStatus, DownloadQueueSnapshot
from .base import HubScreen

QueueProvider = Callable[[], DownloadQueueSnapshot]


@dataclass(frozen=True, slots=True)
class QueueLoadOutcome:
    snapshot: DownloadQueueSnapshot | None = None
    error: str | None = None


class DownloadsScreen(HubScreen):
    """Track-oriented view over the durable acquisition queue."""

    def __init__(self, *, queue_provider: QueueProvider) -> None:
        super().__init__("downloads", "Downloads")
        self._queue_provider = queue_provider
        self.snapshot: DownloadQueueSnapshot | None = None
        self.items: tuple[DownloadQueueItem, ...] = ()
        self.selected_index = 0
        self._details_mode = False
        self._refresh_worker: Worker[QueueLoadOutcome] | None = None

    def compose_content(self) -> Iterable[Widget]:
        yield Static("Queued 0 · Downloading 0 · Processing 0 · Failed 0 · Completed 0", id="downloads-summary", markup=False)
        yield Static("Loading download queue…", id="downloads-status", markup=False)
        with Grid(id="downloads-main"):
            with Container(classes="downloads-panel", id="download-queue-panel"):
                yield Static("Queue · loading", classes="panel-title", id="download-queue-title")
                with VerticalScroll(id="download-queue-scroll"):
                    yield Static("Loading queue…", id="download-queue", markup=False)
            with Container(classes="downloads-panel", id="download-details-panel"):
                yield Static("Track details", classes="panel-title")
                with VerticalScroll(id="download-details-scroll"):
                    yield Static("Select a queued song to inspect it.", id="download-details", markup=False)
        yield Static("r refresh · Enter details", id="downloads-position", markup=False)

    def on_screen_resume(self, event: ScreenResume) -> None:
        if self.snapshot is None and self._refresh_worker is None:
            self.refresh_snapshot()

    def invalidate_snapshot(self) -> None:
        self.snapshot = None
        self._refresh_worker = None

    def refresh_snapshot(self) -> None:
        if self.snapshot is None:
            self.query_one("#download-queue", Static).update("Loading queue…")
            self.query_one("#download-details", Static).update("Waiting for queue data…")
        status = self.query_one("#downloads-status", Static)
        status.update("Refreshing download queue…")
        status.remove_class("-error")
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
        if self.app.screen is not self:
            # Textual unmounts the screen's widgets after section navigation.
            # Discard this now-stale read and load a fresh snapshot on resume.
            self._refresh_worker = None
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
                self.items = ()
                self.query_one("#download-queue-title", Static).update("Queue · unavailable")
                self.query_one("#download-queue", Static).update("Unable to load the download queue.")
                self.query_one("#download-details", Static).update("Queue details are unavailable.")
                self.query_one("#downloads-position", Static).update("r retry refresh")
            return

        previous = self.selected_item.reference if self.selected_item is not None else None
        self.snapshot = outcome.snapshot
        self.items = outcome.snapshot.items
        self.selected_index = next((index for index, item in enumerate(self.items) if item.reference == previous), 0)
        self._details_mode = False
        self.remove_class("-details-mode")
        self._render_summary()
        self._render_items()
        self._render_selected_details()
        if self.items:
            status.update("Download queue · actions coming next")
            self._update_position()
            self.call_after_refresh(self._scroll_selected_into_view)
        else:
            status.update("The active download queue is empty.")
            self.query_one("#downloads-position", Static).update("r refresh · Completed items stay in history")

    @property
    def selected_item(self) -> DownloadQueueItem | None:
        return self.items[self.selected_index] if self.items else None

    def _render_summary(self) -> None:
        if self.snapshot is None:
            return
        snapshot = self.snapshot
        self.query_one("#downloads-summary", Static).update(
            f"Queued {snapshot.queued_count} · Downloading {snapshot.downloading_count} · Processing {snapshot.processing_count} · Failed {snapshot.failed_count} · Completed {snapshot.completed_count}"
        )

    def _render_items(self) -> None:
        self.query_one("#download-queue-title", Static).update(f"Queue · {len(self.items)} active")
        if not self.items:
            self.query_one("#download-queue", Static).update("No queued or failed songs.")
            return
        lines = []
        for index, item in enumerate(self.items):
            marker = ">" if index == self.selected_index else " "
            error = " · error" if item.status in {DownloadQueueItemStatus.FAILED, DownloadQueueItemStatus.NEEDS_ATTENTION} else ""
            lines.append(f"{marker} {_status_label(item.status):<15} {item.title[:32]:32} {_progress_label(item)}{error}")
        self.query_one("#download-queue", Static).update(Text("\n".join(lines), no_wrap=True, overflow="ellipsis"))

    def _render_selected_details(self) -> None:
        item = self.selected_item
        details = self.query_one("#download-details", Static)
        self.query_one("#download-details-scroll", VerticalScroll).scroll_home(animate=False, immediate=True)
        if item is None:
            details.update("No active queue item selected.")
            return
        lines = [
            item.title, "",
            f"Artist         {item.artist or 'Unknown'}",
            f"Category       {item.category or 'Unknown'}",
            f"Era            {item.era or 'Unknown'}",
            f"Destination    {item.destination or 'Unavailable'}",
            f"Status         {_status_label(item.status)}",
            f"Progress       {_progress_label(item)}",
            f"Queued         {_timestamp(item.queued_at)}",
            f"Retry          {'Available' if item.retryable else 'Not available'}",
        ]
        if item.failure_stage:
            lines.append(f"Failure        {item.failure_stage}")
        if item.error:
            lines.append(f"Error          {_concise_error(item.error)}")
        if item.internal_reference:
            lines.extend(("", "Troubleshooting", f"Internal ref   {item.internal_reference}"))
        details.update(Text("\n".join(lines), overflow="ellipsis"))

    def _update_position(self) -> None:
        if self.items:
            suffix = "Esc queue · PgUp/PgDn details" if self._details_mode else "Enter details · r refresh"
            self.query_one("#downloads-position", Static).update(f"Track {self.selected_index + 1} of {len(self.items)} · {suffix}")

    def on_key(self, event: Key) -> None:
        if event.key == "escape" and self._details_mode:
            self._details_mode = False
            self.remove_class("-details-mode")
            self._update_position()
        elif event.key == "enter" and self.selected_item is not None:
            self._details_mode = True
            self.add_class("-details-mode")
            self.query_one("#download-details-scroll", VerticalScroll).scroll_home(animate=False, immediate=True)
            self._update_position()
        elif event.key in ("pagedown", "pageup") and self._details_mode:
            scroll = self.query_one("#download-details-scroll", VerticalScroll)
            (scroll.scroll_page_down if event.key == "pagedown" else scroll.scroll_page_up)(animate=False)
        elif event.key in ("down", "j"):
            self._select_item(self.selected_index + 1)
        elif event.key in ("up", "k"):
            self._select_item(self.selected_index - 1)
        elif event.key == "home":
            self._select_item(0)
        elif event.key == "end":
            self._select_item(len(self.items) - 1)
        elif event.key in ("pagedown", "pageup"):
            scroll = self.query_one("#download-queue-scroll", VerticalScroll)
            step = max(1, scroll.size.height - 1)
            self._select_item(self.selected_index + (step if event.key == "pagedown" else -step))
        else:
            return
        event.prevent_default()
        event.stop()

    def _select_item(self, index: int) -> None:
        if not self.items:
            return
        self.selected_index = max(0, min(len(self.items) - 1, index))
        self._render_items()
        self._render_selected_details()
        self._update_position()
        self.call_after_refresh(self._scroll_selected_into_view)

    def _scroll_selected_into_view(self) -> None:
        if self.items:
            scroll = self.query_one("#download-queue-scroll", VerticalScroll)
            scroll.scroll_to_region(Region(0, self.selected_index, max(1, scroll.virtual_size.width), 1), animate=False, immediate=True, x_axis=False)

    def on_resize(self, event: Resize) -> None:
        super().on_resize(event)
        self.set_class(event.size.width < 90, "-downloads-narrow")
        if self.items:
            self.call_after_refresh(self._scroll_selected_into_view)


def _status_label(status: DownloadQueueItemStatus) -> str:
    return {
        DownloadQueueItemStatus.QUEUED: "Queued",
        DownloadQueueItemStatus.DOWNLOADING: "Downloading",
        DownloadQueueItemStatus.PROCESSING: "Processing",
        DownloadQueueItemStatus.COMPLETED: "Completed",
        DownloadQueueItemStatus.FAILED: "Failed",
        DownloadQueueItemStatus.NEEDS_ATTENTION: "Needs attention",
    }[status]


def _progress_label(item: DownloadQueueItem) -> str:
    percent = item.progress_percent
    if percent is not None:
        return f"{percent}% ({item.bytes_written}/{item.expected_bytes} bytes)"
    return f"{item.bytes_written} bytes" if item.bytes_written else "Not started"


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

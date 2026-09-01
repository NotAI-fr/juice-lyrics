from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.containers import Container, Grid, VerticalScroll
from textual.events import Click, Key, Resize, ScreenResume
from textual.geometry import Region
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from ...services.download_queue import (
    DownloadExecutionAction,
    DownloadExecutionPlan,
    DownloadExecutionResult,
    DownloadExecutionStatus,
    DownloadProgress,
    DownloadRetryPlan,
    DownloadRetryResult,
    DownloadRetryStatus,
    DownloadQueueItem,
    DownloadQueueItemStatus,
    DownloadQueueSnapshot,
)
from .base import HubScreen

QueueProvider = Callable[[], DownloadQueueSnapshot]
PlanProvider = Callable[..., DownloadExecutionResult]
ExecutionProvider = Callable[..., DownloadExecutionResult]
RetryPlanProvider = Callable[..., DownloadRetryResult]
RetryExecutionProvider = Callable[..., DownloadRetryResult]


@dataclass(frozen=True, slots=True)
class QueueLoadOutcome:
    snapshot: DownloadQueueSnapshot | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionPlanOutcome:
    reference: str
    result: DownloadExecutionResult | None = None
    error: str | None = None


class DownloadDialogAction(Static):
    can_focus = False

    class Activated(Message):
        def __init__(self, action: str) -> None:
            self.action = action
            super().__init__()

    def __init__(self, label: str, action: str, *, id: str) -> None:
        super().__init__(label, id=id, markup=False)
        self.action = action

    def on_click(self, event: Click) -> None:
        self.post_message(self.Activated(self.action))


class DownloadSelectedDialog(ModalScreen[DownloadExecutionPlan | None]):
    """Cancel-first confirmation for executing one selected queue track."""

    def __init__(self, plan: DownloadExecutionPlan) -> None:
        super().__init__()
        self.plan = plan
        self._choice = "cancel"
        self._confirmed = False

    def compose(self) -> ComposeResult:
        action = "Resume download" if self.plan.action is DownloadExecutionAction.RESUME else "Start download"
        with Container(id="download-confirm-dialog"):
            yield Static("Download selected", id="download-confirm-title")
            yield Static(
                "\n".join((
                    f"Song         {self.plan.title}",
                    f"Artist       {self.plan.artist or 'Unknown'}",
                    f"Destination  {self.plan.destination}",
                    f"Status       {_status_label(self.plan.current_status)}",
                    f"Action       {action}",
                    "",
                    "This will write the media file and may embed lyrics, create an LRC file, "
                    "update library state, and notify rmpc according to your configuration.",
                )),
                id="download-confirm-body",
                markup=False,
            )
            with Grid(id="download-confirm-actions"):
                yield DownloadDialogAction("Download", "confirm", id="download-confirm-download")
                yield DownloadDialogAction("Cancel", "cancel", id="download-confirm-cancel")

    def on_mount(self) -> None:
        self._render_choice()

    def _render_choice(self) -> None:
        download = "[Download]" if self._choice == "confirm" else "Download"
        cancel = "[Cancel]" if self._choice == "cancel" else "Cancel"
        self.query_one("#download-confirm-download", Static).update(download)
        self.query_one("#download-confirm-cancel", Static).update(cancel)

    def on_download_dialog_action_activated(self, event: DownloadDialogAction.Activated) -> None:
        if self._confirmed:
            return
        self._choice = event.action
        self._render_choice()
        self._activate()

    def on_key(self, event: Key) -> None:
        if self._confirmed:
            event.prevent_default()
            event.stop()
            return
        if event.key in {"escape", "n"}:
            self.dismiss(None)
        elif event.key == "y":
            self._choice = "confirm"
            self._render_choice()
            self._activate()
        elif event.key in {"left", "right", "tab", "shift+tab"}:
            self._choice = "confirm" if self._choice == "cancel" else "cancel"
            self._render_choice()
        elif event.key == "enter":
            self._activate()
        else:
            return
        event.prevent_default()
        event.stop()

    def _activate(self) -> None:
        if self._choice == "cancel":
            self.dismiss(None)
            return
        if not self._confirmed:
            self._confirmed = True
            self.dismiss(self.plan)


class RetryFailedDialog(ModalScreen[DownloadRetryPlan | None]):
    def __init__(self, plan: DownloadRetryPlan) -> None:
        super().__init__(); self.plan = plan; self._confirmed = False
    def compose(self) -> ComposeResult:
        action = {"process_only": "Retry processing only", "resume_download": "Resume download", "download_again": "Download again"}[self.plan.action.value]
        with Container(id="download-confirm-dialog"):
            yield Static("Retry failed song", id="download-confirm-title")
            yield Static("\n".join((f"Song         {self.plan.title}", f"Destination  {self.plan.destination}", f"Previous     {self.plan.previous_failure}", f"Action       {action}", "", "This may write media and metadata. Retry is explicit and will not affect other songs.")), id="download-confirm-body", markup=False)
            with Grid(id="download-confirm-actions"):
                yield DownloadDialogAction("Retry", "confirm", id="download-confirm-download")
                yield DownloadDialogAction("Cancel", "cancel", id="download-confirm-cancel")
    def on_mount(self) -> None:
        self.query_one("#download-confirm-download", Static).update("Retry")
        self.query_one("#download-confirm-cancel", Static).update("[Cancel]")
    def on_download_dialog_action_activated(self, event: DownloadDialogAction.Activated) -> None:
        if event.action == "cancel": self.dismiss(None)
        elif not self._confirmed: self._confirmed = True; self.dismiss(self.plan)
    def on_key(self, event: Key) -> None:
        if event.key in {"escape", "n"}: self.dismiss(None)
        elif event.key == "y": self._confirmed = True; self.dismiss(self.plan)
        elif event.key == "enter":
            if not self._confirmed:
                self.dismiss(None)
            else:
                return
        else: return
        event.prevent_default(); event.stop()


class DownloadsScreen(HubScreen):
    """Track-oriented view over the durable acquisition queue."""

    def __init__(
        self,
        settings: object,
        *,
        queue_provider: QueueProvider,
        plan_provider: PlanProvider,
        execution_provider: ExecutionProvider,
        retry_plan_provider: RetryPlanProvider,
        retry_execution_provider: RetryExecutionProvider,
    ) -> None:
        super().__init__("downloads", "Downloads")
        self.settings = settings
        self._queue_provider = queue_provider
        self._plan_provider = plan_provider
        self._execution_provider = execution_provider
        self._retry_plan_provider = retry_plan_provider
        self._retry_execution_provider = retry_execution_provider
        self.snapshot: DownloadQueueSnapshot | None = None
        self.items: tuple[DownloadQueueItem, ...] = ()
        self.selected_index = 0
        self._details_mode = False
        self._refresh_worker: Worker[QueueLoadOutcome] | None = None
        self._plan_worker: Worker[ExecutionPlanOutcome] | None = None
        self._execution_worker: Worker[DownloadExecutionResult] | None = None
        self._retry_plan_worker: Worker[DownloadRetryResult] | None = None
        self._retry_execution_worker: Worker[DownloadRetryResult] | None = None
        self._active_reference: str | None = None
        self._live_progress: DownloadProgress | None = None
        self._completion_message: tuple[str, bool] | None = None

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
        yield Static("d Download selected · r refresh · Enter details", id="downloads-position", markup=False)

    def on_screen_resume(self, event: ScreenResume) -> None:
        if self.snapshot is None and self._refresh_worker is None:
            self.refresh_snapshot()

    def invalidate_snapshot(self) -> None:
        self.snapshot = None
        self._refresh_worker = None

    def refresh_snapshot(self) -> None:
        if self._execution_worker is not None:
            self.notify("The selected download is still running.")
            return
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
        if event.worker is self._plan_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_execution_plan(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._set_status("Unable to prepare the selected download.", error=True)
            return
        if event.worker is self._retry_plan_worker:
            if event.state is WorkerState.SUCCESS: self._apply_retry_plan(event.worker.result)
            elif event.state is WorkerState.ERROR: self._set_status("Unable to prepare retry.", error=True)
            return
        if event.worker is self._retry_execution_worker:
            if event.state is WorkerState.SUCCESS: self._apply_retry_result(event.worker.result)
            elif event.state is WorkerState.ERROR: self._apply_retry_result(DownloadRetryResult(DownloadRetryStatus.FAILED, "Retry failed safely.", error=str(event.worker.error)))
            return
        if event.worker is self._execution_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_execution_result(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._apply_execution_result(DownloadExecutionResult(
                    DownloadExecutionStatus.FAILED,
                    "Download failed safely.",
                    error=str(event.worker.error) if event.worker.error else "Unknown execution error",
                ))
            return
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
            status.update("Download queue · d Download selected")
            self._update_position()
            self.call_after_refresh(self._scroll_selected_into_view)
        else:
            status.update("The active download queue is empty.")
            self.query_one("#downloads-position", Static).update("r refresh · Completed items stay in history")
        if self._completion_message is not None:
            message, error = self._completion_message
            self._set_status(message, error=error)
            self._completion_message = None

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
            live = self._live_progress if item.reference == self._active_reference else None
            display_status = _progress_status(live) if live else item.status
            error = " · error" if display_status in {DownloadQueueItemStatus.FAILED, DownloadQueueItemStatus.NEEDS_ATTENTION} else ""
            lines.append(f"{marker} {_status_label(display_status):<15} {item.title[:32]:32} {_progress_label(item, live)}{error}")
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
            f"Status         {_status_label(_progress_status(self._live_progress) if item.reference == self._active_reference and self._live_progress else item.status)}",
            f"Progress       {_progress_label(item, self._live_progress if item.reference == self._active_reference else None)}",
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
            suffix = "Esc queue · PgUp/PgDn details" if self._details_mode else "d Download selected · Enter details · r refresh"
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
        elif event.key == "d":
            self._download_selected()
        elif event.key == "t":
            self._retry_selected()
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

    def _retry_selected(self) -> None:
        if self._execution_worker or self._plan_worker or self._retry_plan_worker or self._retry_execution_worker:
            self._set_status("Another download is already in progress.", error=True); return
        item = self.selected_item
        if item is None or item.status is not DownloadQueueItemStatus.FAILED:
            self._set_status("Select a failed song to retry.", error=True); return
        self._retry_plan_worker = self._prepare_retry(item.reference)

    @work(thread=True, exclusive=True, group="retry-plan", exit_on_error=False)
    def _prepare_retry(self, reference: str) -> DownloadRetryResult:
        return self._retry_plan_provider(self.settings, reference)

    def _apply_retry_plan(self, result: DownloadRetryResult) -> None:
        self._retry_plan_worker = None
        if self.app.screen is not self: return
        if result.status is not DownloadRetryStatus.READY or result.plan is None:
            self._set_status(result.message, error=True); return
        self.app.push_screen(RetryFailedDialog(result.plan), self._retry_dialog_closed)

    def _retry_dialog_closed(self, plan: DownloadRetryPlan | None) -> None:
        if plan is None or self._retry_execution_worker is not None: return
        self._active_reference = plan.reference
        self._live_progress = DownloadProgress(plan.reference, DownloadExecutionStatus.DOWNLOADING, message="Preparing retry…")
        self._render_items(); self._render_selected_details()
        self._retry_execution_worker = self._execute_retry(plan)

    @work(thread=True, exclusive=True, group="selected-retry", exit_on_error=False)
    def _execute_retry(self, plan: DownloadRetryPlan) -> DownloadRetryResult:
        return self._retry_execution_provider(self.settings, plan, progress=self._thread_progress)

    def _apply_retry_result(self, result: DownloadRetryResult) -> None:
        self._retry_execution_worker = None; self._retry_plan_worker = None; self._active_reference = None; self._live_progress = None; self.snapshot = None
        if result.status is DownloadRetryStatus.COMPLETED:
            invalidate = getattr(self.app, "invalidate_library_views", None)
            if callable(invalidate): invalidate()
        self._completion_message = (result.message if result.status is DownloadRetryStatus.COMPLETED else f"{result.message}{': ' + result.error if result.error else ''}", result.status is not DownloadRetryStatus.COMPLETED)
        if self.app.screen is self: self.refresh_snapshot()

    def _download_selected(self) -> None:
        if self._execution_worker is not None or self._plan_worker is not None:
            self._set_status("Another selected download is already being prepared or downloaded.", error=True)
            return
        item = self.selected_item
        if item is None:
            self._set_status("Select a queued song first.", error=True)
            return
        if item.status is DownloadQueueItemStatus.FAILED:
            self._set_status("This failed song requires the future Retry action.", error=True)
            return
        if item.status in {DownloadQueueItemStatus.DOWNLOADING, DownloadQueueItemStatus.PROCESSING}:
            self._set_status("This song is already downloading or processing.", error=True)
            return
        if item.status is not DownloadQueueItemStatus.QUEUED:
            self._set_status("This song is not eligible for Download selected.", error=True)
            return
        self._set_status("Checking the selected download…")
        self._plan_worker = self._prepare_execution(item.reference)

    @work(thread=True, exclusive=True, group="download-plan", exit_on_error=False)
    def _prepare_execution(self, reference: str) -> ExecutionPlanOutcome:
        try:
            return ExecutionPlanOutcome(reference, self._plan_provider(self.settings, reference))
        except Exception as exc:
            return ExecutionPlanOutcome(reference, error=str(exc) or type(exc).__name__)

    def _apply_execution_plan(self, outcome: ExecutionPlanOutcome) -> None:
        self._plan_worker = None
        if self.app.screen is not self:
            return
        if self.selected_item is None or self.selected_item.reference != outcome.reference:
            self._set_status("Selection changed; press d again for the current song.", error=True)
            return
        if outcome.error or outcome.result is None:
            self._set_status(f"Unable to prepare download: {outcome.error or 'Unknown error'}", error=True)
            return
        if outcome.result.status is not DownloadExecutionStatus.READY or outcome.result.plan is None:
            self._set_status(outcome.result.message, error=True)
            return
        self.app.push_screen(DownloadSelectedDialog(outcome.result.plan), self._download_dialog_closed)

    def _download_dialog_closed(self, plan: DownloadExecutionPlan | None) -> None:
        if plan is None:
            return
        if self._execution_worker is not None:
            self._set_status("This song is already downloading.", error=True)
            return
        self._active_reference = plan.reference
        self._live_progress = DownloadProgress(
            plan.reference,
            DownloadExecutionStatus.DOWNLOADING,
            message="Starting download…",
        )
        self._render_items()
        self._render_selected_details()
        self._set_status(f"Starting {plan.title}…")
        self._execution_worker = self._execute_selected(plan)

    @work(thread=True, exclusive=True, group="selected-download", exit_on_error=False)
    def _execute_selected(self, plan: DownloadExecutionPlan) -> DownloadExecutionResult:
        try:
            return self._execution_provider(
                self.settings,
                plan,
                progress=self._thread_progress,
            )
        except Exception as exc:
            return DownloadExecutionResult(
                DownloadExecutionStatus.FAILED,
                "Download failed safely.",
                plan=plan,
                error=str(exc) or type(exc).__name__,
            )

    def _thread_progress(self, progress: DownloadProgress) -> None:
        try:
            self.app.call_from_thread(self._apply_progress, progress)
        except RuntimeError:
            pass

    def _apply_progress(self, progress: DownloadProgress) -> None:
        if progress.reference != self._active_reference or self.app.screen is not self:
            return
        self._live_progress = progress
        self._render_items()
        self._render_selected_details()
        self._set_status(progress.message or _execution_status_label(progress.status))

    def _apply_execution_result(self, result: DownloadExecutionResult) -> None:
        self._execution_worker = None
        self._plan_worker = None
        self._active_reference = None
        self._live_progress = None
        self.snapshot = None
        if result.status is DownloadExecutionStatus.COMPLETED:
            invalidate = getattr(self.app, "invalidate_library_views", None)
            if callable(invalidate):
                invalidate()
            message = result.message
            error = False
        else:
            detail = f": {result.error}" if result.error else ""
            message = f"{result.message}{detail}"
            error = True
        self._completion_message = (message, error)
        if self.app.screen is self:
            self.refresh_snapshot()
        else:
            self._refresh_worker = None

    def _set_status(self, message: str, *, error: bool = False) -> None:
        status = self.query_one("#downloads-status", Static)
        status.update(message)
        status.set_class(error, "-error")

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


def _progress_label(item: DownloadQueueItem, live: DownloadProgress | None = None) -> str:
    if live is not None:
        if live.percent is not None:
            return f"{live.percent}% ({live.bytes_written}/{live.total_bytes} bytes)"
        if live.bytes_written:
            return f"{live.bytes_written} bytes"
        return _execution_status_label(live.status)
    percent = item.progress_percent
    if percent is not None:
        return f"{percent}% ({item.bytes_written}/{item.expected_bytes} bytes)"
    return f"{item.bytes_written} bytes" if item.bytes_written else "Not started"


def _progress_status(progress: DownloadProgress) -> DownloadQueueItemStatus:
    if progress.status is DownloadExecutionStatus.PROCESSING:
        return DownloadQueueItemStatus.PROCESSING
    if progress.status is DownloadExecutionStatus.FAILED:
        return DownloadQueueItemStatus.FAILED
    if progress.status is DownloadExecutionStatus.COMPLETED:
        return DownloadQueueItemStatus.COMPLETED
    return DownloadQueueItemStatus.DOWNLOADING


def _execution_status_label(status: DownloadExecutionStatus) -> str:
    return {
        DownloadExecutionStatus.READY: "Ready",
        DownloadExecutionStatus.DOWNLOADING: "Downloading",
        DownloadExecutionStatus.PROCESSING: "Processing",
        DownloadExecutionStatus.COMPLETED: "Completed",
        DownloadExecutionStatus.FAILED: "Failed",
        DownloadExecutionStatus.NOT_FOUND: "Not found",
        DownloadExecutionStatus.NOT_ELIGIBLE: "Not eligible",
        DownloadExecutionStatus.ALREADY_RUNNING: "Already running",
        DownloadExecutionStatus.RETRY_REQUIRED: "Retry required",
        DownloadExecutionStatus.STORE_FAILED: "Queue unavailable",
    }[status]


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

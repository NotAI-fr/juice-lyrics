from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from math import ceil
from typing import Any

from rich.text import Text
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Grid, Vertical, VerticalScroll
from textual.events import Click, Key, Resize, ScreenResume
from textual.geometry import Region
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Select, Static
from textual.worker import Worker, WorkerState

from ...services.catalogue import (
    CatalogueFilterMetadata,
    CataloguePage,
    CatalogueSearchResult,
    LyricAvailability,
    SongDetails,
)
from ...services.download_queue import QueueAddPlan, QueueAddResult, QueueAddStatus
from .base import HubScreen

SearchProvider = Callable[..., CataloguePage | tuple[CatalogueSearchResult, ...]]
DetailsProvider = Callable[..., SongDetails | None]
FiltersProvider = Callable[..., CatalogueFilterMetadata]
QueuePlanProvider = Callable[..., QueueAddResult]
QueueAddProvider = Callable[[QueueAddPlan], QueueAddResult]
_PREVIEW_LINES = 6
_PAGE_SIZE = 50


class BrowseInput(Input):
    """Filter input that preserves the shell's global numeric navigation."""

    def on_key(self, event: Key) -> None:
        if event.key == "slash":
            self.screen.action_focus_search()
            event.prevent_default()
            event.stop()
            return
        if event.key in "12345":
            sections = ("dashboard", "browse", "library", "downloads", "settings")
            self.app.action_show_section(sections[int(event.key) - 1])
            event.prevent_default()
            event.stop()


class BrowseSelect(Select[str]):
    """Catalogue selector that preserves global section shortcuts."""

    def on_key(self, event: Key) -> None:
        if event.key == "slash":
            self.screen.action_focus_search()
            event.prevent_default()
            event.stop()
            return
        if event.key in "12345":
            sections = ("dashboard", "browse", "library", "downloads", "settings")
            self.app.action_show_section(sections[int(event.key) - 1])
            event.prevent_default()
            event.stop()


class PaginationControl(Static):
    """Non-focusable terminal-native previous/next page control."""

    can_focus = False

    class Activated(Message):
        def __init__(self, item: PaginationControl) -> None:
            self.item = item
            super().__init__()

    def __init__(self, label: str, direction: int, *, id: str) -> None:
        super().__init__(label, id=id, markup=False)
        self.label = label
        self.direction = direction
        self.available = False

    def set_available(self, available: bool) -> None:
        self.available = available
        self.set_class(available, "-available")
        self.set_class(not available, "-unavailable")
        self.update(Text(f"[{self.label}]"))

    def on_click(self, event: Click) -> None:
        if self.available:
            self.post_message(self.Activated(self))


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    category: str | None
    era: str | None
    page: int
    refresh: bool


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    request: SearchRequest
    page: CataloguePage | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DetailsOutcome:
    result: CatalogueSearchResult
    details: SongDetails | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class FiltersOutcome:
    metadata: CatalogueFilterMetadata | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class QueuePlanOutcome:
    selection: CatalogueSearchResult
    result: QueueAddResult | None = None
    error: str | None = None


class QueueDialogAction(Static):
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


class AddToQueueDialog(ModalScreen[QueueAddResult | None]):
    """Explicit, cancel-first confirmation for one durable queue addition."""

    def __init__(self, plan: QueueAddPlan, creator: QueueAddProvider) -> None:
        super().__init__()
        self.plan = plan
        self._creator = creator
        self._choice = "cancel"
        self._creating = False
        self._created_result: QueueAddResult | None = None
        self._worker: Worker[QueueAddResult] | None = None

    def compose(self) -> ComposeResult:
        planned = self.plan.items[0]
        item = planned.item
        with Container(id="queue-confirm-dialog"):
            yield Static("Add to download queue", id="queue-confirm-title")
            yield Static(
                "\n".join((
                    f"Song         {item.title}",
                    f"Artist       {planned.artist or 'Unknown'}",
                    f"Category     {planned.category or 'Unknown'}",
                    f"Era          {planned.era or 'Unknown'}",
                    f"Destination  {item.destination}",
                    "Availability Available",
                    "",
                    "This adds the song to your download queue. It will not start downloading yet.",
                )),
                id="queue-confirm-body",
                markup=False,
            )
            yield Static("Choose an action.", id="queue-confirm-status", markup=False)
            with Grid(id="queue-confirm-actions"):
                yield QueueDialogAction("Add to queue", "confirm", id="queue-confirm-add")
                yield QueueDialogAction("Cancel", "cancel", id="queue-confirm-cancel")

    def on_mount(self) -> None:
        self._render_choice()

    def _render_choice(self) -> None:
        if self._created_result is not None:
            self.query_one("#queue-confirm-add", Static).update("[v View Downloads]")
            self.query_one("#queue-confirm-cancel", Static).update("[Enter Close]")
            return
        add = "[Add to queue]" if self._choice == "confirm" else "Add to queue"
        cancel = "[Cancel]" if self._choice == "cancel" else "Cancel"
        self.query_one("#queue-confirm-add", Static).update(add)
        self.query_one("#queue-confirm-cancel", Static).update(cancel)

    def on_queue_dialog_action_activated(self, event: QueueDialogAction.Activated) -> None:
        if self._created_result is not None:
            if event.action == "confirm":
                self._view_downloads()
            else:
                self.dismiss(self._created_result)
            return
        self._choice = event.action
        self._render_choice()
        self._activate_choice()

    def on_key(self, event: Key) -> None:
        if self._creating:
            event.prevent_default()
            event.stop()
            return
        if self._created_result is not None:
            if event.key == "v":
                self._view_downloads()
            elif event.key in {"enter", "escape"}:
                self.dismiss(self._created_result)
            else:
                return
        elif event.key in {"escape", "n"}:
            self.dismiss(None)
        elif event.key == "y":
            self._choice = "confirm"
            self._render_choice()
            self._activate_choice()
        elif event.key in {"left", "right", "tab", "shift+tab"}:
            self._choice = "confirm" if self._choice == "cancel" else "cancel"
            self._render_choice()
        elif event.key == "enter":
            self._activate_choice()
        else:
            return
        event.prevent_default()
        event.stop()

    def _activate_choice(self) -> None:
        if self._choice == "cancel":
            self.dismiss(None)
            return
        if self._creating:
            return
        self._creating = True
        self.query_one("#queue-confirm-status", Static).update("Adding to queue…")
        self._worker = self._create_queue_item()

    @work(thread=True, exclusive=True, group="queue-add", exit_on_error=False)
    def _create_queue_item(self) -> QueueAddResult:
        try:
            return self._creator(self.plan)
        except Exception as exc:
            return QueueAddResult(QueueAddStatus.SAVE_FAILED, f"Unable to save the queue: {exc}")

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        if event.state is WorkerState.SUCCESS:
            result = event.worker.result
        elif event.state is WorkerState.ERROR:
            result = QueueAddResult(QueueAddStatus.SAVE_FAILED, "Unable to save the queue.")
        else:
            return
        self._creating = False
        if result.status is QueueAddStatus.ADDED:
            self._created_result = result
            invalidate = getattr(self.app, "invalidate_download_queue", None)
            if callable(invalidate):
                invalidate()
            self.query_one("#queue-confirm-status", Static).update(
                f"{result.message} Nothing has started."
            )
            self._render_choice()
        else:
            self._choice = "cancel"
            self.query_one("#queue-confirm-status", Static).update(result.message)
            self._render_choice()

    def _view_downloads(self) -> None:
        result = self._created_result
        self.dismiss(result)
        if result is not None:
            self.app.call_after_refresh(self.app.action_show_section, "downloads")


class BrowseScreen(HubScreen):
    """Interactive, read-only catalogue search and song-details screen."""

    BINDINGS = [Binding("/", "focus_search", "Search", show=False)]

    def __init__(
        self,
        settings: Any,
        *,
        search_provider: SearchProvider,
        details_provider: DetailsProvider,
        filters_provider: FiltersProvider,
        queue_plan_provider: QueuePlanProvider,
        queue_add_provider: QueueAddProvider,
    ) -> None:
        super().__init__("browse", "Browse")
        self.settings = settings
        self._search_provider = search_provider
        self._details_provider = details_provider
        self._filters_provider = filters_provider
        self._queue_plan_provider = queue_plan_provider
        self._queue_add_provider = queue_add_provider
        self.results: tuple[CatalogueSearchResult, ...] = ()
        self.current_page: CataloguePage | None = None
        self.selected_index = 0
        self.last_request: SearchRequest | None = None
        self._search_worker: Worker[SearchOutcome] | None = None
        self._details_worker: Worker[DetailsOutcome] | None = None
        self._filters_worker: Worker[FiltersOutcome] | None = None
        self._queue_plan_worker: Worker[QueuePlanOutcome] | None = None
        self._applying_filters = False

    def compose_content(self) -> Iterable[Widget]:
        with Grid(id="browse-controls"):
            with Vertical(classes="browse-filter"):
                yield Static("Search", classes="filter-label")
                yield BrowseInput(placeholder="Optional song title", id="browse-query")
            with Vertical(classes="browse-filter"):
                yield Static("Category", classes="filter-label")
                yield BrowseSelect([("Loading…", "")], allow_blank=False, id="browse-category", disabled=True)
            with Vertical(classes="browse-filter"):
                yield Static("Era", classes="filter-label")
                yield BrowseSelect([("Loading…", "")], allow_blank=False, id="browse-era", disabled=True)
        yield Static("Enter a title or choose at least one filter.", id="browse-status", markup=False)
        with Grid(id="browse-main"):
            with Container(classes="browse-panel", id="browse-results-panel"):
                yield Static("Results · 0 loaded", classes="panel-title", id="browse-results-title")
                with VerticalScroll(id="browse-results-scroll"):
                    yield Static("No search yet.", id="browse-results", markup=False)
            with Container(classes="browse-panel", id="browse-details-panel"):
                yield Static("Details", classes="panel-title")
                with VerticalScroll(id="browse-details-scroll"):
                    yield Static("Select a result to inspect it.", id="browse-details", markup=False)
        with Grid(id="browse-pagination"):
            yield PaginationControl("p Previous", -1, id="browse-previous")
            yield Static("No catalogue page loaded", id="browse-page-position", markup=False)
            yield PaginationControl("n Next", 1, id="browse-next")

    def action_focus_search(self) -> None:
        self.query_one("#browse-query", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.submit_search(refresh=False)

    def on_select_changed(self, event: Select.Changed) -> None:
        if not self._applying_filters and not event.select.disabled:
            self.submit_search(refresh=False)

    def on_screen_resume(self, event: ScreenResume) -> None:
        if self._filters_worker is None:
            self._filters_worker = self._load_filters()
        if self.results:
            self.call_after_refresh(self.set_focus, None)

    def submit_search(self, *, refresh: bool) -> None:
        query = self.query_one("#browse-query", Input).value.strip()
        category = _select_value(self.query_one("#browse-category", Select))
        era = _select_value(self.query_one("#browse-era", Select))
        if not query and not category and not era:
            self._set_status("Enter a title or choose at least one filter.", error=True)
            return

        request = SearchRequest(query, category, era, 1, refresh)
        self._start_search(request)

    def _start_search(self, request: SearchRequest) -> None:
        self.last_request = request
        self.set_focus(None)
        self.results = ()
        self.current_page = None
        self.selected_index = 0
        self.query_one("#browse-results", Static).update("Searching…")
        self.query_one("#browse-results-title", Static).update("Results · loading")
        self.query_one("#browse-details", Static).update("Waiting for results…")
        self.query_one("#browse-results-scroll", VerticalScroll).scroll_home(animate=False, immediate=True)
        self._update_pagination(None, loading_page=request.page)
        self._set_status(self._loading_status(request))
        self._search_worker = self._run_search(request)

    def refresh_snapshot(self) -> None:
        if self.last_request is None:
            self.submit_search(refresh=True)
            return
        self.query_one("#browse-query", Input).value = self.last_request.query
        self.query_one("#browse-category", Select).value = self.last_request.category or ""
        self.query_one("#browse-era", Select).value = self.last_request.era or ""
        self._start_search(SearchRequest(
            self.last_request.query,
            self.last_request.category,
            self.last_request.era,
            self.last_request.page,
            True,
        ))

    @work(thread=True, exclusive=True, group="catalogue-filters", exit_on_error=False)
    def _load_filters(self) -> FiltersOutcome:
        try:
            return FiltersOutcome(self._filters_provider(self.settings, refresh=False))
        except Exception as exc:
            return FiltersOutcome(error=str(exc) or type(exc).__name__)

    @work(thread=True, exclusive=True, group="catalogue-search", exit_on_error=False)
    def _run_search(self, request: SearchRequest) -> SearchOutcome:
        try:
            results = self._search_provider(
                self.settings,
                request.query,
                category=request.category,
                era=request.era,
                page=request.page,
                page_size=_PAGE_SIZE,
                refresh=request.refresh,
            )
            if isinstance(results, CataloguePage):
                page = results
            else:
                normalized = tuple(results)
                page = CataloguePage(normalized, request.page, _PAGE_SIZE, len(normalized), None, None)
            return SearchOutcome(request, page)
        except Exception as exc:
            return SearchOutcome(request, error=str(exc) or type(exc).__name__)

    @work(thread=True, exclusive=True, group="catalogue-details", exit_on_error=False)
    def _run_details(self, result: CatalogueSearchResult) -> DetailsOutcome:
        request = self.last_request
        if request is None:
            return DetailsOutcome(result, error="Search context is unavailable")
        if result.song_id is None:
            return DetailsOutcome(result, error="This result has no stable song ID")
        try:
            details = self._details_provider(
                self.settings,
                result.song_id,
                selection_index=result.selection_index,
            )
            return DetailsOutcome(result, details)
        except Exception as exc:
            return DetailsOutcome(result, error=str(exc) or type(exc).__name__)

    @work(thread=True, exclusive=True, group="queue-plan", exit_on_error=False)
    def _plan_queue_add(self, selection: CatalogueSearchResult) -> QueuePlanOutcome:
        try:
            result = self._queue_plan_provider(self.settings, (selection,))
            return QueuePlanOutcome(selection, result)
        except Exception as exc:
            return QueuePlanOutcome(selection, error=str(exc) or type(exc).__name__)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._filters_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_filters(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._apply_filters(FiltersOutcome(error="Filter metadata worker failed"))
        elif event.worker is self._search_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_search(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._apply_search(SearchOutcome(
                    self.last_request or SearchRequest("", None, None, 1, False),
                    error="Search worker failed",
                ))
        elif event.worker is self._details_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_details(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self.query_one("#browse-details", Static).update("Unable to load song details.")
        elif event.worker is self._queue_plan_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_queue_plan(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._set_status("Unable to check the download queue.", error=True)

    def _apply_queue_plan(self, outcome: QueuePlanOutcome) -> None:
        if self.app.screen is not self:
            return
        if not self.results or self.results[self.selected_index] != outcome.selection:
            self._set_status("Selection changed; press a again to add the current song.", error=True)
            return
        if outcome.error or outcome.result is None:
            self._set_status(f"Unable to check the queue: {outcome.error or 'Unknown error'}", error=True)
            return
        if outcome.result.status is not QueueAddStatus.READY or outcome.result.plan is None:
            self._set_status(outcome.result.message, error=True)
            return
        self.app.push_screen(
            AddToQueueDialog(outcome.result.plan, self._queue_add_provider),
            self._queue_dialog_closed,
        )

    def _queue_dialog_closed(self, result: QueueAddResult | None) -> None:
        if result is not None and result.status is QueueAddStatus.ADDED:
            self._set_status(f"{result.message} It has not started. Press 4 to view Downloads.")

    def _apply_search(self, outcome: SearchOutcome) -> None:
        if outcome.error:
            self.results = ()
            self.current_page = None
            self.query_one("#browse-results", Static).update("Search unavailable.")
            self.query_one("#browse-results-title", Static).update("Results · unavailable")
            self.query_one("#browse-details", Static).update("No song selected.")
            self._update_pagination(None)
            self._set_status(f"Search failed: {outcome.error}", error=True)
            return

        page = outcome.page or CataloguePage((), outcome.request.page, _PAGE_SIZE, 0, None, None)
        self.current_page = page
        self.results = page.results
        self.selected_index = 0
        self.query_one("#browse-results-title", Static).update(f"Results · {len(self.results)} loaded")
        self._update_pagination(page)
        if not self.results:
            self.query_one("#browse-results", Static).update("No catalogue results found.")
            if outcome.request.page > 1:
                self.query_one("#browse-details", Static).update("Return to the previous or first page.")
                self._set_status(f"Page {outcome.request.page} is no longer available.", error=True)
            else:
                self.query_one("#browse-details", Static).update("Try another title or filter.")
                self._set_status(_empty_result_status(outcome.request))
            return

        self._render_results()
        self._render_summary(self.results[0])
        self._set_status(self._result_status(outcome.request, page))
        self.call_after_refresh(self._scroll_selection_into_view)

    def _apply_filters(self, outcome: FiltersOutcome) -> None:
        category = self.query_one("#browse-category", Select)
        era = self.query_one("#browse-era", Select)
        if outcome.error or outcome.metadata is None:
            category.set_options([("Unavailable", "")])
            era.set_options([("Unavailable", "")])
            category.disabled = era.disabled = True
            self._set_status(f"Filter metadata unavailable: {outcome.error or 'Unknown error'}. Title search remains available.", error=True)
            return
        self._applying_filters = True
        category.set_options([("All", ""), *((item.label, item.value) for item in outcome.metadata.categories)])
        era.set_options([("All", ""), *((item.label, item.value) for item in outcome.metadata.eras)])
        category.value = era.value = ""
        self._applying_filters = False
        category.disabled = era.disabled = False
        if self.last_request is None:
            self._set_status("Enter an optional title or choose filters, then press / and Enter.")

    def _apply_details(self, outcome: DetailsOutcome) -> None:
        if not self.results or self.results[self.selected_index] != outcome.result:
            return
        if outcome.error:
            self.query_one("#browse-details", Static).update(f"Unable to load details: {outcome.error}")
        elif outcome.details is None:
            self.query_one("#browse-details", Static).update("No additional details are available.")
        else:
            self.query_one("#browse-details", Static).update(self._details_text(outcome.details))

    def on_key(self, event: Key) -> None:
        if any(select.expanded for select in self.query(Select)):
            return
        if isinstance(self.app.focused, (Input, Select)):
            return
        if event.key in ("down", "j"):
            self._move_selection(1)
        elif event.key in ("up", "k"):
            self._move_selection(-1)
        elif event.key == "enter":
            self._load_selected_details()
        elif event.key == "a":
            self._add_selected_to_queue()
        elif event.key == "n":
            self._change_page(next_page=True)
        elif event.key == "p":
            self._change_page(next_page=False)
        elif event.key == "pagedown":
            self._move_viewport(1)
        elif event.key == "pageup":
            self._move_viewport(-1)
        elif event.key == "home":
            self._select_index(0)
        elif event.key == "end":
            self._select_index(len(self.results) - 1)
        else:
            return
        event.prevent_default()
        event.stop()

    def _add_selected_to_queue(self) -> None:
        if not self.results:
            self._set_status("Select a downloadable song first.", error=True)
            return
        selection = self.results[self.selected_index]
        if not selection.downloadable:
            self._set_status("Media unavailable; this song cannot be added to the queue.", error=True)
            return
        self._set_status("Checking destination and download queue…")
        self._queue_plan_worker = self._plan_queue_add(selection)

    def _change_page(self, *, next_page: bool) -> None:
        if self.current_page is None or self.last_request is None:
            return
        page = self.current_page.next_page if next_page else self.current_page.previous_page
        if page is None:
            self.notify("No next page." if next_page else "Already on the first page.")
            return
        self._start_search(SearchRequest(
            self.last_request.query,
            self.last_request.category,
            self.last_request.era,
            page,
            False,
        ))

    def on_pagination_control_activated(self, event: PaginationControl.Activated) -> None:
        self._change_page(next_page=event.item.direction > 0)

    def _move_selection(self, amount: int) -> None:
        if not self.results:
            return
        self._select_index(self.selected_index + amount)

    def _move_viewport(self, direction: int) -> None:
        scroll = self.query_one("#browse-results-scroll", VerticalScroll)
        row_height = 2 if "-narrow" in self.classes else 1
        visible_rows = max(1, scroll.size.height // row_height)
        self._select_index(self.selected_index + direction * max(1, visible_rows - 1))

    def _select_index(self, index: int) -> None:
        if not self.results:
            return
        self.selected_index = max(0, min(len(self.results) - 1, index))
        self._render_results()
        self._render_summary(self.results[self.selected_index])
        if self.last_request is not None and self.current_page is not None:
            self._set_status(self._result_status(self.last_request, self.current_page))
        self.call_after_refresh(self._scroll_selection_into_view)

    def _scroll_selection_into_view(self) -> None:
        if not self.results:
            return
        scroll = self.query_one("#browse-results-scroll", VerticalScroll)
        row_height = 2 if "-narrow" in self.classes else 1
        row_y = self.selected_index * row_height
        scroll.scroll_to_region(
            Region(0, row_y, max(1, scroll.virtual_size.width), row_height),
            animate=False,
            immediate=True,
            x_axis=False,
        )

    def _load_selected_details(self) -> None:
        if not self.results:
            return
        result = self.results[self.selected_index]
        self.query_one("#browse-details", Static).update("Loading full details…")
        self._details_worker = self._run_details(result)

    def _render_results(self) -> None:
        narrow = "-narrow" in self.classes
        lines: list[str] = []
        for index, result in enumerate(self.results):
            marker = ">" if index == self.selected_index else " "
            title = result.title or "Unknown title"
            era = result.era or "Unknown era"
            category = result.category or "Unknown category"
            lyrics = _lyrics_label(result.lyrics)
            available = "Available" if result.downloadable else "Unavailable"
            if narrow:
                lines.extend((f"{marker} {title}", f"  {era} · {category} · {lyrics} · {available}"))
            else:
                length = result.length or "?"
                lines.append(
                    f"{marker} {title[:26]:26} {era[:10]:10} {category[:12]:12} "
                    f"{length[:7]:7} {lyrics:6} {available}"
                )
        self.query_one("#browse-results", Static).update(
            Text("\n".join(lines), no_wrap=True, overflow="ellipsis")
        )

    def _update_pagination(self, page: CataloguePage | None, *, loading_page: int | None = None) -> None:
        previous = self.query_one("#browse-previous", PaginationControl)
        next_control = self.query_one("#browse-next", PaginationControl)
        position = self.query_one("#browse-page-position", Static)
        if page is None:
            previous.set_available(False)
            next_control.set_available(False)
            position.update(
                f"Page {loading_page} · Loading…"
                if loading_page
                else "No catalogue page loaded"
            )
            return
        previous.set_available(page.previous_page is not None)
        next_control.set_available(page.next_page is not None)
        page_count = max(1, ceil(page.total_count / page.page_size))
        if page.results:
            position.update(
                f"Page {page.page} of {page_count} · "
                f"Results {page.range_start}–{page.range_end} of {page.total_count:,}"
            )
        else:
            position.update(f"Page {page.page} of {page_count} · No results")

    def _render_summary(self, result: CatalogueSearchResult) -> None:
        artists = ", ".join(result.artists) or "Unknown"
        producers = ", ".join(result.producers) or "Unknown"
        path = result.media_path or "Unavailable"
        lyrics = _lyrics_label(result.lyrics)
        download = "Available" if result.downloadable else "Unavailable"
        lines = (
            result.title or "Unknown title",
            "",
            f"ID             {result.song_id if result.song_id is not None else 'Unknown'}",
            f"Era            {result.era or 'Unknown'}",
            f"Category       {result.category or 'Unknown'}",
            f"Length         {result.length or 'Unknown'}",
            f"Artists        {artists}",
            f"Producers      {producers}",
            f"Lyrics         {lyrics}",
            f"Download       {download}",
            f"Path           {path}",
            "",
            "Press Enter for full details and lyric preview.",
            "Press a to add this song to the download queue." if result.downloadable else "Media unavailable.",
        )
        self.query_one("#browse-details", Static).update("\n".join(lines))

    def _details_text(self, details: SongDetails) -> str:
        lyrics = _lyrics_label(details.lyrics)
        preview = _lyric_preview(details)
        return "\n".join((
            details.title or "Unknown title",
            "",
            f"ID             {details.song_id if details.song_id is not None else 'Unknown'}",
            f"Era            {details.era or 'Unknown'}",
            f"Category       {details.category or 'Unknown'}",
            f"Length         {details.length or 'Unknown'}",
            f"Artists        {', '.join(details.artists) or 'Unknown'}",
            f"Producers      {', '.join(details.producers) or 'Unknown'}",
            f"Lyrics         {lyrics}",
            f"Download       {'Available' if details.downloadable else 'Unavailable'}",
            f"Path           {details.media_path or 'Unavailable'}",
            "",
            "Lyrics preview",
            preview,
        ))

    def _set_status(self, message: str, *, error: bool = False) -> None:
        status = self.query_one("#browse-status", Static)
        status.update(message)
        status.set_class(error, "-error")

    @staticmethod
    def _loading_status(request: SearchRequest) -> str:
        if request.query:
            return f'Searching for "{request.query}"…{_filter_text(request.category, request.era)}'
        return f"Searching: {_filter_values(request.category, request.era)}…"

    def _result_status(self, request: SearchRequest, page: CataloguePage) -> str:
        filters = _filter_text(request.category, request.era)
        selected = min(len(page.results), self.selected_index + 1)
        return (
            f"Result {selected} of {len(page.results)} loaded · n/p pages · "
            f"j/k select · PgUp/PgDn scroll · Enter details"
            f"{' · a Add to queue' if self.results and self.results[self.selected_index].downloadable else ''}.{filters}"
        )

    def on_resize(self, event: Resize) -> None:
        super().on_resize(event)
        if self.results:
            self._render_results()
            self.call_after_refresh(self._scroll_selection_into_view)


def _lyrics_label(value: LyricAvailability) -> str:
    return {
        LyricAvailability.SYNCED: "Synced",
        LyricAvailability.PLAIN: "Plain",
        LyricAvailability.NONE: "None",
    }[value]


def _filter_text(category: str | None, era: str | None) -> str:
    values = _filter_values(category, era)
    return f"  Filters: {values}." if values else "  Filters: All."


def _filter_values(category: str | None, era: str | None) -> str:
    values = []
    if category:
        values.append(f"category={category}")
    if era:
        values.append(f"era={era}")
    return ", ".join(values)


def _empty_result_status(request: SearchRequest) -> str:
    if request.query:
        return f'No results for "{request.query}".{_filter_text(request.category, request.era)}'
    return f"No results for filters: {_filter_values(request.category, request.era)}."


def _select_value(select: Select) -> str | None:
    value = select.value
    return value if isinstance(value, str) and value else None


def _lyric_preview(details: SongDetails) -> str:
    if details.lyrics is LyricAvailability.SYNCED:
        text = details.synced_lyrics or ""
    elif details.lyrics is LyricAvailability.PLAIN:
        text = details.plain_lyrics or ""
    else:
        return "No lyrics available."
    lines = text.splitlines()
    preview = lines[:_PREVIEW_LINES]
    if len(lines) > _PREVIEW_LINES:
        preview.append("…")
    return "\n".join(preview) if preview else "No lyrics available."

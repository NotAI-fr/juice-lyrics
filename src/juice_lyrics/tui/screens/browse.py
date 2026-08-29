from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Grid, Vertical, VerticalScroll
from textual.events import Key, Resize, ScreenResume
from textual.widget import Widget
from textual.widgets import Input, Static
from textual.worker import Worker, WorkerState

from ...services.catalogue import CatalogueSearchResult, LyricAvailability, SongDetails
from .base import HubScreen

SearchProvider = Callable[..., tuple[CatalogueSearchResult, ...]]
DetailsProvider = Callable[..., SongDetails | None]
_PREVIEW_LINES = 6


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


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    category: str | None
    era: str | None
    refresh: bool


@dataclass(frozen=True, slots=True)
class SearchOutcome:
    request: SearchRequest
    results: tuple[CatalogueSearchResult, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class DetailsOutcome:
    result: CatalogueSearchResult
    details: SongDetails | None = None
    error: str | None = None


class BrowseScreen(HubScreen):
    """Interactive, read-only catalogue search and song-details screen."""

    BINDINGS = [Binding("/", "focus_search", "Search", show=False)]

    def __init__(
        self,
        settings: Any,
        *,
        search_provider: SearchProvider,
        details_provider: DetailsProvider,
    ) -> None:
        super().__init__("browse", "Browse")
        self.settings = settings
        self._search_provider = search_provider
        self._details_provider = details_provider
        self.results: tuple[CatalogueSearchResult, ...] = ()
        self.selected_index = 0
        self.last_request: SearchRequest | None = None
        self._search_worker: Worker[SearchOutcome] | None = None
        self._details_worker: Worker[DetailsOutcome] | None = None

    def compose_content(self) -> Iterable[Widget]:
        with Grid(id="browse-controls"):
            with Vertical(classes="browse-filter"):
                yield Static("Search", classes="filter-label")
                yield BrowseInput(placeholder="Song title", id="browse-query")
            with Vertical(classes="browse-filter"):
                yield Static("Category (All when blank)", classes="filter-label")
                yield BrowseInput(placeholder="All", id="browse-category")
            with Vertical(classes="browse-filter"):
                yield Static("Era (All when blank)", classes="filter-label")
                yield BrowseInput(placeholder="All", id="browse-era")
        yield Static("Enter a song title and press Enter.", id="browse-status", markup=False)
        with Grid(id="browse-main"):
            with Container(classes="browse-panel", id="browse-results-panel"):
                yield Static("Results", classes="panel-title")
                with VerticalScroll(id="browse-results-scroll"):
                    yield Static("No search yet.", id="browse-results", markup=False)
            with Container(classes="browse-panel", id="browse-details-panel"):
                yield Static("Details", classes="panel-title")
                with VerticalScroll(id="browse-details-scroll"):
                    yield Static("Select a result to inspect it.", id="browse-details", markup=False)

    def action_focus_search(self) -> None:
        self.query_one("#browse-query", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.submit_search(refresh=False)

    def on_screen_resume(self, event: ScreenResume) -> None:
        if self.results:
            self.call_after_refresh(self.set_focus, None)

    def submit_search(self, *, refresh: bool) -> None:
        query = self.query_one("#browse-query", Input).value.strip()
        category = self.query_one("#browse-category", Input).value.strip() or None
        era = self.query_one("#browse-era", Input).value.strip() or None
        if not query:
            self._set_status("Enter a song title before searching.", error=True)
            return

        request = SearchRequest(query, category, era, refresh)
        self.last_request = request
        self.set_focus(None)
        self.results = ()
        self.selected_index = 0
        self.query_one("#browse-results", Static).update("Searching…")
        self.query_one("#browse-details", Static).update("Waiting for results…")
        self._set_status(self._loading_status(request))
        self._search_worker = self._run_search(request)

    def refresh_snapshot(self) -> None:
        if self.last_request is None:
            self.submit_search(refresh=True)
            return
        self.query_one("#browse-query", Input).value = self.last_request.query
        self.query_one("#browse-category", Input).value = self.last_request.category or ""
        self.query_one("#browse-era", Input).value = self.last_request.era or ""
        self.submit_search(refresh=True)

    @work(thread=True, exclusive=True, group="catalogue-search", exit_on_error=False)
    def _run_search(self, request: SearchRequest) -> SearchOutcome:
        try:
            results = self._search_provider(
                self.settings,
                request.query,
                category=request.category,
                era=request.era,
                refresh=request.refresh,
            )
            return SearchOutcome(request, tuple(results))
        except Exception as exc:
            return SearchOutcome(request, error=str(exc) or type(exc).__name__)

    @work(thread=True, exclusive=True, group="catalogue-details", exit_on_error=False)
    def _run_details(self, result: CatalogueSearchResult) -> DetailsOutcome:
        request = self.last_request
        if request is None:
            return DetailsOutcome(result, error="Search context is unavailable")
        try:
            details = self._details_provider(
                self.settings,
                request.query,
                selection_index=result.selection_index,
                refresh=False,
            )
            return DetailsOutcome(result, details)
        except Exception as exc:
            return DetailsOutcome(result, error=str(exc) or type(exc).__name__)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._search_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_search(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._apply_search(SearchOutcome(self.last_request or SearchRequest("", None, None, False), error="Search worker failed"))
        elif event.worker is self._details_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_details(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self.query_one("#browse-details", Static).update("Unable to load song details.")

    def _apply_search(self, outcome: SearchOutcome) -> None:
        if outcome.error:
            self.results = ()
            self.query_one("#browse-results", Static).update("Search unavailable.")
            self.query_one("#browse-details", Static).update("No song selected.")
            self._set_status(f"Search failed: {outcome.error}", error=True)
            return

        self.results = outcome.results
        self.selected_index = 0
        if not self.results:
            self.query_one("#browse-results", Static).update("No catalogue results found.")
            self.query_one("#browse-details", Static).update("Try another title or filter.")
            self._set_status(f'No results for "{outcome.request.query}".')
            return

        self._render_results()
        self._render_summary(self.results[0])
        self._set_status(self._result_status(outcome.request, len(self.results)))

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
        if isinstance(self.app.focused, Input):
            return
        if event.key in ("down", "j"):
            self._move_selection(1)
        elif event.key in ("up", "k"):
            self._move_selection(-1)
        elif event.key == "enter":
            self._load_selected_details()
        else:
            return
        event.prevent_default()
        event.stop()

    def _move_selection(self, amount: int) -> None:
        if not self.results:
            return
        self.selected_index = max(0, min(len(self.results) - 1, self.selected_index + amount))
        self._render_results()
        self._render_summary(self.results[self.selected_index])

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
        self.query_one("#browse-results", Static).update("\n".join(lines))

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
        filters = _filter_text(request.category, request.era)
        return f'Searching for "{request.query}"…{filters}'

    @staticmethod
    def _result_status(request: SearchRequest, count: int) -> str:
        filters = _filter_text(request.category, request.era)
        return f"{count} result(s).{filters}  ↑/↓ or j/k select · Enter details"

    def on_resize(self, event: Resize) -> None:
        super().on_resize(event)
        if self.results:
            self._render_results()


def _lyrics_label(value: LyricAvailability) -> str:
    return {
        LyricAvailability.SYNCED: "Synced",
        LyricAvailability.PLAIN: "Plain",
        LyricAvailability.NONE: "None",
    }[value]


def _filter_text(category: str | None, era: str | None) -> str:
    values = []
    if category:
        values.append(f"category={category}")
    if era:
        values.append(f"era={era}")
    return f"  Filters: {', '.join(values)}." if values else "  Filters: All."


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

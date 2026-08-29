from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.app import App
from textual.binding import Binding

from ..services.acquisition_queue import QueueSnapshot, get_queue_snapshot
from ..services.catalogue import (
    CatalogueFilterMetadata,
    CataloguePage,
    SongDetails,
    get_catalogue_filters,
    get_song_details_by_id,
    search_catalogue_page,
)
from ..services.library_status import LibraryStatus, get_library_status
from .screens.base import NavigationItem
from .screens.browse import BrowseScreen
from .screens.dashboard import DashboardScreen
from .screens.placeholder import PlaceholderScreen

LibraryStatusProvider = Callable[[Any], LibraryStatus]
QueueSnapshotProvider = Callable[[], QueueSnapshot]
CatalogueSearchProvider = Callable[..., CataloguePage]
CatalogueDetailsProvider = Callable[..., SongDetails | None]
CatalogueFiltersProvider = Callable[..., CatalogueFilterMetadata]


class JuiceLyricsApp(App[None]):
    """The first read-only application shell for the planned 999 interface."""

    TITLE = "999"
    SUB_TITLE = "Juice WRLD Music Hub"

    BINDINGS = [
        Binding("1", "show_section('dashboard')", "Dashboard", show=False, priority=True),
        Binding("2", "show_section('browse')", "Browse", show=False, priority=True),
        Binding("3", "show_section('library')", "Library", show=False, priority=True),
        Binding("4", "show_section('downloads')", "Downloads", show=False, priority=True),
        Binding("5", "show_section('settings')", "Settings", show=False, priority=True),
        Binding("r", "refresh_active", "Refresh", show=False),
        Binding("question_mark", "show_help", "Help", show=False),
        Binding("q", "quit", "Quit", show=False, priority=True),
    ]

    CSS = """
    Screen {
        background: transparent;
    }

    #brand {
        height: 2;
        padding: 0 1;
        text-style: bold;
        border-bottom: solid ansi_cyan;
    }

    #primary-navigation {
        height: 3;
        padding: 0;
        align-horizontal: center;
    }

    #primary-navigation NavigationItem {
        width: auto;
        min-width: 12;
        height: 3;
        margin: 0 1;
        background: transparent;
        color: ansi_default;
        border: none;
        text-align: center;
        content-align: center middle;
    }

    #primary-navigation NavigationItem:hover {
        color: ansi_default;
        text-style: bold;
    }

    #primary-navigation NavigationItem.-current,
    #primary-navigation NavigationItem.-current:hover {
        color: ansi_blue;
        text-style: bold;
    }

    #screen-content {
        height: 1fr;
        padding: 0 2 1 2;
    }

    #screen-title {
        height: 2;
        text-style: bold;
    }

    #dashboard-panels {
        layout: grid;
        grid-size: 2 1;
        grid-gutter: 1 2;
        height: 1fr;
    }

    .dashboard-panel {
        border: round ansi_cyan;
        padding: 1 2;
        height: auto;
        min-height: 12;
    }

    .panel-title {
        text-style: bold;
        height: 2;
    }

    .panel-error {
        color: ansi_red;
        height: auto;
    }

    #browse-controls {
        height: auto;
        layout: grid;
        grid-size: 3 1;
        grid-columns: 2fr 1fr 1fr;
        grid-rows: 4;
        grid-gutter: 0 1;
    }

    .browse-filter {
        height: 4;
    }

    #browse-controls Input,
    #browse-controls SelectCurrent {
        background: transparent;
        color: ansi_default;
        border: tall ansi_default;
        background-tint: transparent;
        padding: 0 1;
    }

    #browse-controls Input:focus,
    #browse-controls Select:focus > SelectCurrent {
        background: transparent;
        border: tall ansi_blue;
        background-tint: transparent;
    }

    #browse-controls Select,
    #browse-controls SelectOverlay {
        background: transparent;
        color: ansi_default;
    }

    #browse-controls SelectOverlay {
        border: tall ansi_blue;
    }

    #browse-controls .option-list--option-highlighted {
        background: transparent;
        color: ansi_blue;
        text-style: bold;
    }

    .filter-label {
        height: 1;
        text-style: dim;
    }

    #browse-status {
        height: 2;
        padding: 0 1;
    }

    #browse-status.-error {
        color: ansi_red;
    }

    #browse-main {
        height: 1fr;
        layout: grid;
        grid-size: 2 1;
        grid-columns: 3fr 2fr;
        grid-gutter: 0 1;
    }

    .browse-panel {
        height: 1fr;
        border: round ansi_cyan;
        padding: 0 1;
    }

    #browse-results-scroll,
    #browse-details-scroll {
        height: 1fr;
        background: transparent;
    }

    #browse-results,
    #browse-details {
        height: auto;
        background: transparent;
    }

    #placeholder-panel {
        border: round ansi_cyan;
        padding: 2 3;
        height: auto;
        max-width: 72;
    }

    #status-footer {
        height: 2;
        padding: 0 2;
        border-top: solid ansi_cyan;
        text-style: dim;
    }

    Screen.-narrow #primary-navigation NavigationItem {
        min-width: 7;
        margin: 0;
    }

    Screen.-narrow #dashboard-panels {
        grid-size: 1 2;
        overflow-y: auto;
    }

    Screen.-narrow #screen-content {
        padding: 1;
    }

    Screen.-narrow #browse-controls {
        grid-size: 1 3;
        grid-columns: 1fr;
        grid-rows: 4 4 4;
        overflow-y: auto;
    }

    Screen.-narrow #browse-main {
        grid-size: 1 2;
        grid-columns: 1fr;
        grid-rows: 1fr 1fr;
    }
    """

    def __init__(
        self,
        settings: Any,
        *,
        library_status_provider: LibraryStatusProvider = get_library_status,
        queue_snapshot_provider: QueueSnapshotProvider = get_queue_snapshot,
        catalogue_search_provider: CatalogueSearchProvider = search_catalogue_page,
        catalogue_details_provider: CatalogueDetailsProvider = get_song_details_by_id,
        catalogue_filters_provider: CatalogueFiltersProvider = get_catalogue_filters,
    ) -> None:
        super().__init__(ansi_color=True)
        self.settings = settings
        self.library_status_provider = library_status_provider
        self.queue_snapshot_provider = queue_snapshot_provider
        self.catalogue_search_provider = catalogue_search_provider
        self.catalogue_details_provider = catalogue_details_provider
        self.catalogue_filters_provider = catalogue_filters_provider

    def on_mount(self) -> None:
        self.install_screen(
            DashboardScreen(
                self.settings,
                library_status_provider=self.library_status_provider,
                queue_snapshot_provider=self.queue_snapshot_provider,
            ),
            "dashboard",
        )
        self.install_screen(
            BrowseScreen(
                self.settings,
                search_provider=self.catalogue_search_provider,
                details_provider=self.catalogue_details_provider,
                filters_provider=self.catalogue_filters_provider,
            ),
            "browse",
        )
        self.install_screen(
            PlaceholderScreen("Library", "Local track browsing and sync actions are planned for a later milestone."),
            "library",
        )
        self.install_screen(
            PlaceholderScreen("Downloads", "Queue details and acquisition actions are planned for a later milestone."),
            "downloads",
        )
        self.install_screen(
            PlaceholderScreen("Settings", "Configuration viewing and editing are planned for a later milestone."),
            "settings",
        )
        self.push_screen("dashboard")

    def action_show_section(self, section: str) -> None:
        if self.screen.name == section:
            return
        self.switch_screen(section)

    def action_refresh_active(self) -> None:
        refresh = getattr(self.screen, "refresh_snapshot", None)
        if callable(refresh):
            refresh()
        else:
            self.notify(f"{self.screen.title or 'This section'} has no data to refresh yet.")

    def action_show_help(self) -> None:
        if self.screen.name == "browse":
            message = "/ search  •  ↑/↓ select  •  Enter details  •  n/p pages  •  r refresh  •  1–5 sections  •  q quit"
        else:
            message = "1–5 switch sections  •  r refreshes Dashboard  •  q quits"
        self.notify(message, timeout=5)

    def on_navigation_item_activated(self, event: NavigationItem.Activated) -> None:
        self.action_show_section(event.item.section)


def run_tui(settings: Any) -> int:
    """Run the interactive application and return a CLI-compatible exit code."""

    JuiceLyricsApp(settings).run()
    return 0

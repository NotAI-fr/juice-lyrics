from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.app import App
from textual.binding import Binding
from textual.widgets import Button

from ..services import LibraryStatus, QueueSnapshot, get_library_status, get_queue_snapshot
from .screens.dashboard import DashboardScreen
from .screens.placeholder import PlaceholderScreen

LibraryStatusProvider = Callable[[Any], LibraryStatus]
QueueSnapshotProvider = Callable[[], QueueSnapshot]


class JuiceLyricsApp(App[None]):
    """The first read-only application shell for the planned 999 interface."""

    TITLE = "999"
    SUB_TITLE = "Juice WRLD Music Hub"

    BINDINGS = [
        Binding("1", "show_section('dashboard')", "Dashboard", show=False),
        Binding("2", "show_section('browse')", "Browse", show=False),
        Binding("3", "show_section('library')", "Library", show=False),
        Binding("4", "show_section('downloads')", "Downloads", show=False),
        Binding("5", "show_section('settings')", "Settings", show=False),
        Binding("r", "refresh_active", "Refresh", show=False),
        Binding("question_mark", "show_help", "Help", show=False),
        Binding("q", "quit", "Quit", show=False, priority=True),
    ]

    CSS = """
    Screen {
        background: transparent;
    }

    #brand {
        height: 3;
        padding: 0 2;
        text-style: bold;
        border-bottom: solid ansi_blue;
    }

    #primary-navigation {
        height: 3;
        padding: 0 1;
        align-horizontal: center;
    }

    #primary-navigation Button {
        min-width: 12;
        height: 3;
        margin: 0 1;
        background: transparent;
        border: none;
    }

    #primary-navigation Button:hover,
    #primary-navigation Button:focus,
    #primary-navigation Button.-active {
        background: ansi_blue;
        color: ansi_bright_white;
        text-style: bold;
    }

    #screen-content {
        height: 1fr;
        padding: 1 2;
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
        border: round ansi_blue;
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

    #placeholder-panel {
        border: round ansi_blue;
        padding: 2 3;
        height: auto;
        max-width: 72;
    }

    #status-footer {
        height: 2;
        padding: 0 2;
        border-top: solid ansi_blue;
    }

    Screen.-narrow #primary-navigation Button {
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
    """

    def __init__(
        self,
        settings: Any,
        *,
        library_status_provider: LibraryStatusProvider = get_library_status,
        queue_snapshot_provider: QueueSnapshotProvider = get_queue_snapshot,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.library_status_provider = library_status_provider
        self.queue_snapshot_provider = queue_snapshot_provider

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
            PlaceholderScreen("Browse", "Catalogue search and song details are planned for a later milestone."),
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
        self.notify("1–5 navigate  •  Tab changes focus  •  r refreshes Dashboard  •  q quits", timeout=5)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id and event.button.id.startswith("nav-"):
            self.action_show_section(event.button.id.removeprefix("nav-"))


def run_tui(settings: Any) -> int:
    """Run the interactive application and return a CLI-compatible exit code."""

    JuiceLyricsApp(settings).run()
    return 0

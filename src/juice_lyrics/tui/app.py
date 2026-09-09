from __future__ import annotations

from collections.abc import Callable
from typing import Any

from textual.app import App
from textual.binding import Binding
from textual.screen import ModalScreen

from ..backup.manager import BackupRecord, list_backups, restore_backup
from ..rmpc.integration import patch_rmpc_config
from ..services.acquisition_queue import QueueSnapshot, get_queue_snapshot
from ..services.catalogue import (
    CatalogueFilterMetadata,
    CataloguePage,
    SongDetails,
    get_catalogue_filters,
    get_song_details_by_id,
    search_catalogue_page,
)
from ..services.download_queue import (
    DownloadExecutionResult,
    DownloadQueueSnapshot,
    QueueAddResult,
    QueueBatchAddResult,
    add_batch_to_download_queue,
    execute_selected_download,
    execute_selected_retry,
    remove_queue_item,
    clear_download_queue,
    clear_completed_history,
    plan_download_all,
    execute_download_all,
    plan_download_execution,
    plan_download_retry,
    plan_queue_batch_additions,
    project_download_queue,
)
from ..services.library_status import LibrarySnapshot, LibraryStatus, get_library_snapshot, get_library_status
from ..services.library_sync import (
    LibrarySyncPlan,
    LibrarySyncResult,
    execute_library_sync_preview,
    get_library_sync_preview,
)
from ..services.settings_snapshot import SettingsSnapshot, get_settings_snapshot
from .screens.base import NavigationItem
from .screens.browse import BrowseScreen
from .screens.dashboard import DashboardScreen
from .screens.downloads import DownloadsScreen
from .screens.library import LibraryScreen
from .screens.settings import SettingsScreen

LibraryStatusProvider = Callable[[Any], LibraryStatus]
QueueSnapshotProvider = Callable[[], QueueSnapshot]
DownloadQueueProvider = Callable[[], DownloadQueueSnapshot]
QueuePlanProvider = Callable[..., QueueAddResult | QueueBatchAddResult]
QueueAddProvider = Callable[..., QueueAddResult | QueueBatchAddResult]
DownloadPlanProvider = Callable[..., DownloadExecutionResult]
DownloadExecutionProvider = Callable[..., DownloadExecutionResult]
CatalogueSearchProvider = Callable[..., CataloguePage]
CatalogueDetailsProvider = Callable[..., SongDetails | None]
CatalogueFiltersProvider = Callable[..., CatalogueFilterMetadata]
LibrarySnapshotProvider = Callable[[Any], LibrarySnapshot]
LibraryPreviewProvider = Callable[[Any], LibrarySyncPlan]
LibraryExecutionProvider = Callable[..., LibrarySyncResult]
SettingsSnapshotProvider = Callable[[Any], SettingsSnapshot]


class JuiceLyricsApp(App[None]):
    """The 999 terminal application."""

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

    def _get_dom_base(self):
        """Keep application-level queries scoped to the visible section."""

        return self.screen

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

    #browse-results-scroll {
        overflow-y: scroll;
        overflow-x: hidden;
        scrollbar-size-vertical: 1;
        scrollbar-color: ansi_blue;
        scrollbar-background: transparent;
        scrollbar-corner-color: transparent;
    }

    #browse-results,
    #browse-details {
        height: auto;
        background: transparent;
    }

    #browse-pagination {
        height: 2;
        layout: grid;
        grid-size: 3 1;
        grid-columns: 14 1fr 10;
        padding: 0 1;
    }

    #browse-shortcuts {
        height: 1;
        padding: 0 1;
        color: ansi_default;
        text-style: dim;
        overflow: hidden;
        background: transparent;
    }

    #browse-pagination PaginationControl {
        width: 100%;
        height: 1;
        background: transparent;
        border: none;
        color: ansi_default;
        text-align: center;
    }

    #browse-pagination PaginationControl.-available {
        color: ansi_blue;
        text-style: bold;
    }

    #browse-pagination PaginationControl.-available:hover {
        background: transparent;
        text-style: bold;
    }

    #browse-pagination PaginationControl.-unavailable {
        color: ansi_default;
        text-style: dim;
    }

    #browse-page-position {
        height: 1;
        text-align: center;
        color: ansi_default;
    }

    AddToQueueDialog {
        align: center middle;
        background: transparent;
    }

    #queue-confirm-dialog {
        width: 72;
        max-width: 92%;
        height: auto;
        max-height: 92%;
        padding: 1 2;
        border: round ansi_cyan;
        background: transparent;
    }

    #queue-confirm-title {
        height: 2;
        text-style: bold;
        color: ansi_blue;
    }

    #queue-confirm-body {
        height: auto;
    }

    #queue-confirm-status {
        height: 2;
        padding-top: 1;
    }

    #queue-confirm-actions {
        height: 2;
        layout: grid;
        grid-size: 2 1;
        grid-columns: 1fr 1fr;
    }

    #queue-confirm-actions QueueDialogAction {
        background: transparent;
        border: none;
        color: ansi_blue;
        text-style: bold;
        text-align: center;
    }

    #queue-confirm-actions QueueDialogAction:hover {
        background: transparent;
        text-style: bold;
    }

    DownloadSelectedDialog,
    RetryFailedDialog,
    QueueCleanupDialog,
    DownloadAllDialog {
        align: center middle;
        background: transparent;
    }

    MaintenanceDialog,
    BackupBrowser,
    RestoreDialog,
    RmpcDialog {
        align: center middle;
        background: transparent;
    }

    #library-dialog {
        width: 76;
        max-width: 92%;
        max-height: 88%;
        height: auto;
        padding: 1 2;
        border: round ansi_cyan;
        background: transparent;
    }

    #library-dialog-title {
        height: 2;
        text-style: bold;
        color: ansi_blue;
    }

    #library-dialog-body {
        height: auto;
    }

    #library-dialog-help {
        height: 2;
        text-style: dim;
    }

    #library-dialog-actions {
        height: 2;
        grid-size: 2 1;
        grid-columns: 1fr 1fr;
    }

    #library-dialog-actions LibraryDialogAction {
        background: transparent;
        border: none;
        color: ansi_blue;
        text-style: bold;
        text-align: center;
    }

    #download-confirm-dialog {
        width: 76;
        max-width: 92%;
        max-height: 88%;
        height: auto;
        padding: 1 2;
        border: round ansi_cyan;
        background: transparent;
    }

    #download-confirm-title {
        height: 2;
        text-style: bold;
        color: ansi_blue;
    }

    #download-confirm-body {
        height: auto;
    }

    #download-confirm-actions {
        height: 2;
        layout: grid;
        grid-size: 2 1;
        grid-columns: 1fr 1fr;
    }

    #download-confirm-actions DownloadDialogAction {
        background: transparent;
        border: none;
        color: ansi_blue;
        text-style: bold;
        text-align: center;
    }

    #download-confirm-actions DownloadDialogAction:hover {
        background: transparent;
        text-style: bold;
    }

    #downloads-summary {
        height: 2;
        padding: 0 1;
        text-style: bold;
    }

    #downloads-status,
    #downloads-position {
        height: 2;
        padding: 0 1;
        overflow: hidden;
    }

    #downloads-status.-error {
        color: ansi_red;
    }

    #downloads-main {
        height: 1fr;
        layout: grid;
        grid-size: 2 1;
        grid-columns: 2fr 3fr;
        grid-gutter: 0 1;
    }

    .downloads-panel {
        height: 1fr;
        border: round ansi_cyan;
        padding: 0 1;
    }

    #download-queue-scroll,
    #download-details-scroll {
        height: 1fr;
        overflow-y: scroll;
        overflow-x: hidden;
        background: transparent;
        scrollbar-size-vertical: 1;
        scrollbar-color: ansi_blue;
        scrollbar-background: transparent;
        scrollbar-corner-color: transparent;
    }

    #download-queue,
    #download-details {
        height: auto;
        background: transparent;
    }

    #library-summary {
        height: 2;
        padding: 0 1;
        text-style: bold;
    }

    #library-status,
    #library-preview,
    #library-position {
        height: 2;
        padding: 0 1;
    }

    #library-status.-error {
        color: ansi_red;
    }

    #library-controls {
        height: 4;
        layout: grid;
        grid-size: 2 1;
        grid-columns: 2fr 1fr;
        grid-gutter: 0 1;
    }

    .library-filter {
        height: 4;
    }

    #library-controls Input,
    #library-controls SelectCurrent {
        background: transparent;
        color: ansi_default;
        border: tall ansi_default;
        background-tint: transparent;
        padding: 0 1;
    }

    #library-controls Input:focus,
    #library-controls Select:focus > SelectCurrent {
        background: transparent;
        border: tall ansi_blue;
        background-tint: transparent;
    }

    #library-controls Select,
    #library-controls SelectOverlay {
        background: transparent;
        color: ansi_default;
    }

    #library-controls SelectOverlay {
        border: tall ansi_blue;
    }

    #library-controls .option-list--option-highlighted {
        background: transparent;
        color: ansi_blue;
        text-style: bold;
    }

    #library-main {
        height: 1fr;
        layout: grid;
        grid-size: 2 1;
        grid-columns: 3fr 2fr;
        grid-gutter: 0 1;
    }

    .library-panel {
        height: 1fr;
        border: round ansi_cyan;
        padding: 0 1;
    }

    #library-tracks-scroll,
    #library-details-scroll {
        height: 1fr;
        overflow-y: scroll;
        overflow-x: hidden;
        background: transparent;
        scrollbar-size-vertical: 1;
        scrollbar-color: ansi_blue;
        scrollbar-background: transparent;
        scrollbar-corner-color: transparent;
    }

    #library-tracks,
    #library-details {
        height: auto;
        background: transparent;
    }

    #settings-warning {
        height: 2;
        padding: 0 1;
        color: ansi_blue;
        text-style: bold;
    }

    #settings-status,
    #settings-position {
        height: 2;
        padding: 0 1;
    }

    #settings-status.-error {
        color: ansi_red;
    }

    #settings-scroll {
        height: 1fr;
        overflow-y: scroll;
        overflow-x: hidden;
        background: transparent;
        scrollbar-size-vertical: 1;
        scrollbar-color: ansi_blue;
        scrollbar-background: transparent;
        scrollbar-corner-color: transparent;
    }

    #settings-main {
        height: auto;
        layout: grid;
        grid-size: 2 2;
        grid-columns: 1fr 1fr;
        grid-gutter: 1 1;
    }

    .settings-panel {
        height: auto;
        min-height: 8;
        border: round ansi_cyan;
        padding: 0 1;
    }

    #settings-configuration,
    #settings-paths,
    #settings-integrations,
    #settings-capabilities {
        height: auto;
        background: transparent;
    }

    #settings-detail {
        height: auto;
        min-height: 3;
        margin-top: 1;
        border-top: solid ansi_cyan;
        padding: 0 1;
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
        grid-size: 3 1;
        grid-columns: 2fr 1fr 1fr;
        grid-rows: 4;
    }

    Screen.-narrow #browse-main {
        grid-size: 1 2;
        grid-columns: 1fr;
        grid-rows: 2fr 1fr;
    }

    Screen.-narrow #browse-pagination {
        padding: 0;
    }

    Screen.-short #screen-title {
        display: none;
    }

    Screen.-short #browse-status,
    Screen.-short #browse-pagination,
    Screen.-short .browse-panel .panel-title {
        height: 1;
    }

    Screen.-downloads-narrow #downloads-main {
        grid-size: 1 2;
        grid-columns: 1fr;
        grid-rows: 2fr 1fr;
    }

    Screen.-downloads-narrow.-details-mode #downloads-main {
        grid-size: 1 1;
        grid-rows: 1fr;
    }

    Screen.-downloads-narrow.-details-mode #download-queue-panel {
        display: none;
    }

    Screen.-short #downloads-summary,
    Screen.-short #downloads-status,
    Screen.-short #downloads-position,
    Screen.-short .downloads-panel .panel-title {
        height: 1;
    }

    Screen.-library-narrow #library-main {
        grid-size: 1 1;
        grid-columns: 1fr;
        grid-rows: 1fr;
    }

    Screen.-library-narrow #library-details-panel {
        display: none;
    }

    Screen.-library-narrow.-details-mode #library-tracks-panel {
        display: none;
    }

    Screen.-library-narrow.-details-mode #library-details-panel {
        display: block;
    }

    Screen.-short #library-summary,
    Screen.-short #library-status,
    Screen.-short #library-preview,
    Screen.-short #library-position,
    Screen.-short .library-panel .panel-title {
        height: 1;
    }

    Screen.-library-compact #screen-title {
        display: none;
    }

    Screen.-library-compact #library-summary,
    Screen.-library-compact #library-status,
    Screen.-library-compact #library-preview,
    Screen.-library-compact #library-position,
    Screen.-library-compact .library-panel .panel-title {
        height: 1;
    }

    Screen.-settings-narrow #settings-main {
        grid-size: 1 4;
        grid-columns: 1fr;
    }

    Screen.-settings-compact #screen-title {
        display: none;
    }

    Screen.-settings-compact #settings-warning,
    Screen.-settings-compact #settings-status,
    Screen.-settings-compact #settings-position,
    Screen.-settings-compact .settings-panel .panel-title {
        height: 1;
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
        downloads_queue_provider: DownloadQueueProvider | None = None,
        queue_plan_provider: QueuePlanProvider = plan_queue_batch_additions,
        queue_add_provider: QueueAddProvider = add_batch_to_download_queue,
        download_plan_provider: DownloadPlanProvider = plan_download_execution,
        download_execution_provider: DownloadExecutionProvider = execute_selected_download,
        download_retry_plan_provider: Callable[..., Any] = plan_download_retry,
        download_retry_execution_provider: Callable[..., Any] = execute_selected_retry,
        queue_remove_provider: Callable[..., Any] = remove_queue_item,
        queue_clear_provider: Callable[..., Any] = clear_download_queue,
        queue_history_provider: Callable[..., Any] = clear_completed_history,
        download_all_plan_provider: Callable[..., Any] = plan_download_all,
        download_all_execution_provider: Callable[..., Any] = execute_download_all,
        library_snapshot_provider: LibrarySnapshotProvider = get_library_snapshot,
        library_preview_provider: LibraryPreviewProvider = get_library_sync_preview,
        library_execution_provider: LibraryExecutionProvider = execute_library_sync_preview,
        backup_provider: Callable[[], tuple[BackupRecord, ...]] = list_backups,
        restore_provider: Callable[[Any, Any], int] = restore_backup,
        rmpc_setup_provider: Callable[[Any, Any], Any] = patch_rmpc_config,
        settings_snapshot_provider: SettingsSnapshotProvider = get_settings_snapshot,
    ) -> None:
        super().__init__(ansi_color=True)
        self.settings = settings
        self.library_status_provider = library_status_provider
        self.queue_snapshot_provider = queue_snapshot_provider
        self.catalogue_search_provider = catalogue_search_provider
        self.catalogue_details_provider = catalogue_details_provider
        self.catalogue_filters_provider = catalogue_filters_provider
        source_downloads_provider = downloads_queue_provider or queue_snapshot_provider

        def normalized_downloads_provider() -> DownloadQueueSnapshot:
            snapshot = source_downloads_provider()
            if isinstance(snapshot, QueueSnapshot):
                return project_download_queue(snapshot)
            return snapshot

        self.downloads_queue_provider = normalized_downloads_provider
        self.queue_plan_provider = queue_plan_provider
        self.queue_add_provider = queue_add_provider
        self.download_plan_provider = download_plan_provider
        self.download_execution_provider = download_execution_provider
        self.download_retry_plan_provider = download_retry_plan_provider
        self.download_retry_execution_provider = download_retry_execution_provider
        self.queue_remove_provider = queue_remove_provider
        self.queue_clear_provider = queue_clear_provider
        self.queue_history_provider = queue_history_provider
        self.download_all_plan_provider = download_all_plan_provider
        self.download_all_execution_provider = download_all_execution_provider
        self.library_snapshot_provider = library_snapshot_provider
        self.library_preview_provider = library_preview_provider
        self.library_execution_provider = library_execution_provider
        self.backup_provider = backup_provider
        self.restore_provider = restore_provider
        self.rmpc_setup_provider = rmpc_setup_provider
        self.settings_snapshot_provider = settings_snapshot_provider

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
                queue_plan_provider=self.queue_plan_provider,
                queue_add_provider=self.queue_add_provider,
            ),
            "browse",
        )
        self.install_screen(
            LibraryScreen(
                self.settings,
                snapshot_provider=self.library_snapshot_provider,
                preview_provider=self.library_preview_provider,
                execution_provider=self.library_execution_provider,
                backup_provider=self.backup_provider,
                restore_provider=self.restore_provider,
                rmpc_status_provider=self.settings_snapshot_provider,
                rmpc_setup_provider=self.rmpc_setup_provider,
            ),
            "library",
        )
        self.install_screen(
            DownloadsScreen(
                self.settings,
                queue_provider=self.downloads_queue_provider,
                plan_provider=self.download_plan_provider,
                execution_provider=self.download_execution_provider,
                retry_plan_provider=self.download_retry_plan_provider,
                retry_execution_provider=self.download_retry_execution_provider,
                remove_provider=self.queue_remove_provider,
                clear_provider=self.queue_clear_provider,
                history_provider=self.queue_history_provider,
                batch_plan_provider=self.download_all_plan_provider,
                batch_execution_provider=self.download_all_execution_provider,
            ),
            "downloads",
        )
        self.install_screen(
            SettingsScreen(
                self.settings,
                snapshot_provider=self.settings_snapshot_provider,
            ),
            "settings",
        )
        self.push_screen("dashboard")

    def action_show_section(self, section: str) -> None:
        if isinstance(self.screen, ModalScreen):
            return
        if self.screen.name == section:
            return
        self.switch_screen(section)

    def invalidate_download_queue(self) -> None:
        downloads = self.get_screen("downloads")
        invalidate = getattr(downloads, "invalidate_snapshot", None)
        if callable(invalidate):
            invalidate()

    def invalidate_library_views(self) -> None:
        for name in ("dashboard", "library"):
            screen = self.get_screen(name)
            invalidate = getattr(screen, "invalidate_snapshot", None)
            if callable(invalidate):
                invalidate()

    def action_refresh_active(self) -> None:
        refresh = getattr(self.screen, "refresh_snapshot", None)
        if callable(refresh):
            refresh()
        else:
            self.notify(f"{self.screen.title or 'This section'} has no data to refresh yet.")

    def action_show_help(self) -> None:
        section = getattr(self.screen, "section", None)
        if section == "browse":
            message = (
                "Main: a Add to Downloads · 4 Open Downloads\n"
                "Selection actions: Space mark current · M toggle this page · u clear marks. "
                "Marks may span pages; changing search or filters clears them.\n"
                "Navigation: ↑/↓ or j/k move · n next catalogue page · p previous catalogue page · "
                "PageDown/PageUp scroll the loaded results · Home/End first/last loaded result · Enter details. "
                "Adding does not start downloading; Downloads handles the actual download."
            )
        elif section == "downloads":
            message = (
                "Main: A Download queue · d Download selected\n"
                "Queue actions: x Remove selected · c Clear waiting songs · H Clear completed history · r Refresh\n"
                "Troubleshooting: t Try failed song again\n"
                "Navigation: ↑/↓ or j/k select · PageUp/PageDown scroll · Home/End first/last · Enter details · Escape return/cancel. "
                "Complete songs are hidden; cleanup never deletes downloaded music or lyrics."
            )
        elif section == "library":
            message = (
                "Main: r Refresh · m Maintain lyrics · v Verify · b Backups · p Player integration\n"
                "Tracks: ↑/↓ or j/k select · / search · Enter details · l refresh selected lyrics. "
                "Maintenance, restore, and player setup always show a cancel-first confirmation."
            )
        elif section == "settings":
            message = (
                "↑/↓ or j/k inspect settings  •  Home/End first/last  •  "
                "PgUp/PgDn scroll  •  r refresh  •  read-only; configuration changes remain CLI-only"
            )
        else:
            message = "1–5 switch sections  •  r refreshes Dashboard  •  q quits"
        self.notify(message, timeout=5)

    def on_navigation_item_activated(self, event: NavigationItem.Activated) -> None:
        self.action_show_section(event.item.section)


def run_tui(settings: Any) -> int:
    """Run the interactive application and return a CLI-compatible exit code."""

    JuiceLyricsApp(settings).run()
    return 0

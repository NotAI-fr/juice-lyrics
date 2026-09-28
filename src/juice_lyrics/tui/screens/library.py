from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Any

from rich.text import Text
from textual import work
from textual.binding import Binding
from textual.containers import Container, Grid, Vertical, VerticalScroll
from textual.events import Click, Key, Resize, ScreenResume
from textual.geometry import Region
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Input, Select, Static
from textual.worker import Worker, WorkerState

from ...services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibrarySnapshot,
    LibraryStateStatus,
    LibraryTrack,
)
from ...services.library_identity import IdentityBackfillResult
from ...services.library_index_sync import LibraryIndexSyncResult
from ...services.lyrics_search import (
    LyricsSearchIndex,
    LyricsSearchResult,
    build_lyrics_search_index,
)
from ...services.library_issues import (
    LibraryHealth,
    LibraryIssue,
    LibraryIssueAction,
    LibraryIssueCategory,
    LibraryIssueSeverity,
    get_library_health,
)
from ...services.library_duplicates import (
    DuplicateConfidence,
    DuplicateGroup,
    DuplicateReport,
    detect_library_duplicates,
)
from ...services.missing_library import (
    CatalogueCoverage,
    MissingLibraryReport,
    get_missing_library,
)
from ...services.download_queue import (
    QueueAddResult,
    QueueBatchAddResult,
    add_batch_to_download_queue,
    plan_queue_batch_additions,
)
from ...services.metadata_audit import (
    MetadataAudit,
    MetadataProposalConfidence,
    audit_track_metadata,
)
from ...services.metadata_repair import (
    MetadataRepairPlan,
    MetadataRepairResult,
    execute_metadata_repair,
    plan_metadata_repair,
)
from ...services.catalogue import (
    CataloguePage,
    CatalogueSearchResult,
    SongDetails,
    get_song_details_by_id,
)
from ...services.identity_rebuild import (
    IdentityRebuildPlan,
    IdentityRebuildProgress,
    IdentityRebuildResult,
)
from ...services.manual_identity import (
    ManualIdentityResult,
    set_manual_identity,
    unlock_manual_identity,
)
from ...services.library_sync import LibrarySyncPlan, MatchOutcome, SyncLyricType
from ...services.library_sync import LibrarySyncResult, SyncEvent, SyncEventKind
from ...backup.manager import BackupRecord
from ...services.settings_snapshot import IntegrationStatus, SettingsSnapshot
from .base import HubScreen

SnapshotProvider = Callable[[Any], LibrarySnapshot]
IdentityProvider = Callable[..., IdentityBackfillResult]
IndexSyncProvider = Callable[..., LibraryIndexSyncResult]
LyricsSearchProvider = Callable[..., LyricsSearchIndex]
IdentityRebuildPlanProvider = Callable[..., IdentityRebuildPlan]
IdentityRebuildExecutionProvider = Callable[..., IdentityRebuildResult]
ManualSearchProvider = Callable[..., CataloguePage]
ManualIdentityProvider = Callable[..., ManualIdentityResult]
MetadataAuditProvider = Callable[..., MetadataAudit]
MetadataRepairPlanProvider = Callable[..., MetadataRepairPlan]
MetadataRepairExecutionProvider = Callable[..., MetadataRepairResult]
MissingLibraryProvider = Callable[..., MissingLibraryReport]
QueuePlanProvider = Callable[..., QueueAddResult | QueueBatchAddResult]
QueueAddProvider = Callable[..., QueueAddResult | QueueBatchAddResult]
CatalogueDetailsProvider = Callable[..., SongDetails | None]
PreviewProvider = Callable[[Any], LibrarySyncPlan]
ExecutionProvider = Callable[..., LibrarySyncResult]
BackupProvider = Callable[[], tuple[BackupRecord, ...]]
RestoreProvider = Callable[[Path, Path], int]
RmpcStatusProvider = Callable[[Any], SettingsSnapshot]
RmpcSetupProvider = Callable[[Path, Path], Path]


class LibraryFilter(str, Enum):
    ALL = "all"
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    SYNCED = "synced"
    PLAIN = "plain"
    NO_LYRICS = "no_lyrics"
    ATTENTION = "attention"


_FILTER_OPTIONS = (
    ("All", LibraryFilter.ALL.value),
    ("Matched", LibraryFilter.MATCHED.value),
    ("Unmatched", LibraryFilter.UNMATCHED.value),
    ("Synced lyrics", LibraryFilter.SYNCED.value),
    ("Plain lyrics", LibraryFilter.PLAIN.value),
    ("No lyrics", LibraryFilter.NO_LYRICS.value),
    ("Lyrics to improve", LibraryFilter.ATTENTION.value),
)


class LibraryInput(Input):
    """Local search input that preserves global section shortcuts."""

    def on_key(self, event: Key) -> None:
        if not self.value and event.key in {"m", "f", "x"}:
            action = {
                "m": self.screen._open_maintenance,
                "f": self.screen._open_lyrics_search,
                "x": self.screen._open_more,
            }[event.key]
            action()
            event.prevent_default()
            event.stop()
            return
        if event.key == "escape":
            self.screen.set_focus(None)
            event.prevent_default()
            event.stop()
            return
        if event.key == "question_mark":
            self.app.action_show_help()
            event.prevent_default()
            event.stop()
            return
        if event.key == "slash":
            self.screen.action_focus_search()
            event.prevent_default()
            event.stop()
            return


class LyricsSearchInput(Input):
    """Query entry that keeps result navigation available while typing."""

    def on_key(self, event: Key) -> None:
        dialog = self.screen
        if not isinstance(dialog, LyricsSearchDialog):
            return
        if event.key == "escape":
            dialog.dismiss(None)
        elif event.key == "down":
            dialog.move_selection(1)
        elif event.key == "up":
            dialog.move_selection(-1)
        elif event.key == "enter":
            dialog.select_result()
        else:
            return
        event.prevent_default()
        event.stop()


class LibrarySelect(Select[str]):
    """Local status selector that preserves global section shortcuts."""

    def on_key(self, event: Key) -> None:
        if not self.expanded and event.key in {"m", "f", "x"}:
            action = {
                "m": self.screen._open_maintenance,
                "f": self.screen._open_lyrics_search,
                "x": self.screen._open_more,
            }[event.key]
            action()
            event.prevent_default()
            event.stop()
            return
        if event.key == "question_mark":
            self.app.action_show_help()
            event.prevent_default()
            event.stop()
            return
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
class SnapshotOutcome:
    snapshot: LibrarySnapshot | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityOutcome:
    result: IdentityBackfillResult | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PreviewOutcome:
    plan: LibrarySyncPlan | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    result: LibrarySyncResult | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class BackupOutcome:
    records: tuple[BackupRecord, ...] = ()
    error: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityRebuildPlanOutcome:
    plan: IdentityRebuildPlan | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class IdentityRebuildOutcome:
    result: IdentityRebuildResult | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ManualMatchChoice:
    song_id: Any
    api_name: str


@dataclass(frozen=True, slots=True)
class MaintenanceWizardChoice:
    action: str
    issue: LibraryIssue | None = None


@dataclass(frozen=True, slots=True)
class ManualIdentityOutcome:
    result: ManualIdentityResult | None = None
    error: str | None = None
    action: str = "match"


@dataclass(frozen=True, slots=True)
class MetadataAuditOutcome:
    reference: str
    audit: MetadataAudit | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataRepairPlanOutcome:
    plan: MetadataRepairPlan | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataRepairOutcome:
    result: MetadataRepairResult | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class LibraryIssueChoice:
    reference: str
    action: LibraryIssueAction


class LibraryDialogAction(Static):
    can_focus = True

    class Activated(Message):
        def __init__(self, action: str) -> None:
            self.action = action
            super().__init__()

    def __init__(self, label: str, action: str, *, id: str) -> None:
        super().__init__(label, id=id, markup=False)
        self.action = action

    def on_click(self, event: Click) -> None:
        self.post_message(self.Activated(self.action))


class LyricsSearchDialog(ModalScreen[str | None]):
    """Offline, incrementally indexed lyric phrase search."""

    def __init__(
        self,
        settings: Any,
        snapshot: LibrarySnapshot,
        *,
        index_provider: LyricsSearchProvider = build_lyrics_search_index,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.snapshot = snapshot
        self._index_provider = index_provider
        self.index: LyricsSearchIndex | None = None
        self.results: tuple[LyricsSearchResult, ...] = ()
        self.selected_index = 0
        self._worker: Worker[LyricsSearchIndex] | None = None

    def compose(self) -> Iterable[Widget]:
        with Container(id="lyrics-search-dialog"):
            yield Static("Search Lyrics", id="lyrics-search-title")
            yield Static("Building local lyrics index…", id="lyrics-search-status", markup=False)
            yield LyricsSearchInput(
                placeholder="Type remembered words or a phrase",
                id="lyrics-search-query",
            )
            with Grid(id="lyrics-search-main"):
                with VerticalScroll(id="lyrics-search-results-scroll"):
                    yield Static("Indexing local lyrics…", id="lyrics-search-results", markup=False)
                with VerticalScroll(id="lyrics-search-detail-scroll"):
                    yield Static("Matches stay entirely on this device.", id="lyrics-search-detail", markup=False)
            yield Static(
                "Type to search · ↑/↓ navigate · Enter open track · Esc return",
                id="lyrics-search-help",
                markup=False,
            )

    def on_mount(self) -> None:
        self.query_one("#lyrics-search-query", Input).focus()
        self._worker = self._build_index()

    @work(thread=True, exclusive=True, group="lyrics-search-index", exit_on_error=False)
    def _build_index(self) -> LyricsSearchIndex:
        return self._index_provider(self.settings, self.snapshot)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._worker:
            return
        if event.state is WorkerState.SUCCESS:
            self.index = event.worker.result
            index = self.index
            message = (
                f"Ready · {len(index.entries)} tracks · {index.indexed_count} indexed · "
                f"{index.reused_count} reused"
            )
            if index.removed_count:
                message += f" · {index.removed_count} removed"
            if index.rebuilt:
                message += " · cache rebuilt"
            if index.persistence_warning:
                message += " · cache could not be saved"
            self.query_one("#lyrics-search-status", Static).update(message)
            self._update_results()
        elif event.state is WorkerState.ERROR:
            self.query_one("#lyrics-search-status", Static).update(
                "Lyrics index could not be loaded. No files were changed."
            )
            self.query_one("#lyrics-search-results", Static).update("Search unavailable.")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "lyrics-search-query":
            self._update_results()

    def _update_results(self) -> None:
        query = self.query_one("#lyrics-search-query", Input).value
        self.results = self.index.search(query) if self.index is not None else ()
        self.selected_index = 0
        self._render_results()

    def _render_results(self) -> None:
        query = self.query_one("#lyrics-search-query", Input).value.strip()
        listing = self.query_one("#lyrics-search-results", Static)
        detail = self.query_one("#lyrics-search-detail", Static)
        if self.index is None:
            return
        if not query:
            listing.update("Type words from a lyric to search your local library.")
            detail.update("Case, ordinary punctuation, and repeated whitespace are ignored.")
            return
        if not self.results:
            listing.update("No local lyric matches.")
            detail.update("Try a shorter exact phrase.")
            return
        lines = []
        for index, result in enumerate(self.results):
            marker = ">" if index == self.selected_index else " "
            timestamp = _lyrics_timestamp(result.timestamp_ms)
            count = f" · {result.hit_count} hits" if result.hit_count > 1 else ""
            lines.append(
                f"{marker} {result.title[:28]:28} · {timestamp:5} · “{result.matching_line}”{count}"
            )
        listing.update(Text("\n".join(lines), no_wrap=True, overflow="ellipsis"))
        selected = self.results[self.selected_index]
        context = []
        if selected.context_before:
            context.append(f"  {selected.context_before}")
        context.append(f"> {_lyrics_timestamp(selected.timestamp_ms)}  {selected.matching_line}")
        if selected.context_after:
            context.append(f"  {selected.context_after}")
        detail.update(
            "\n".join(
                [
                    selected.title,
                    str(selected.path),
                    f"Source: {'adjacent LRC' if selected.source == 'lrc' else 'embedded lyrics'}",
                    f"Matches in track: {selected.hit_count}",
                    "",
                    *context,
                ]
            )
        )

    def move_selection(self, amount: int) -> None:
        if not self.results:
            return
        self.selected_index = max(0, min(len(self.results) - 1, self.selected_index + amount))
        self._render_results()

    def select_result(self) -> None:
        if self.results:
            self.dismiss(self.results[self.selected_index].reference)

    def on_key(self, event: Key) -> None:
        if isinstance(self.app.focused, Input):
            return
        if event.key == "escape":
            self.dismiss(None)
        elif event.key in {"down", "j"}:
            self.move_selection(1)
        elif event.key in {"up", "k"}:
            self.move_selection(-1)
        elif event.key == "enter":
            self.select_result()
        else:
            return
        event.prevent_default()
        event.stop()


class ManualMatchInput(Input):
    """Search field for the state-only manual catalogue chooser."""

    def on_key(self, event: Key) -> None:
        if event.key == "question_mark":
            self.app.action_show_help()
            event.prevent_default()
            event.stop()


class ManualMatchDialog(ModalScreen[ManualMatchChoice | None]):
    """Search and choose one catalogue identity without touching media."""

    def __init__(
        self,
        settings: Any,
        track: LibraryTrack,
        search_provider: ManualSearchProvider,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.track = track
        self._search_provider = search_provider
        self.results: tuple[CatalogueSearchResult, ...] = ()
        self.index = 0
        self._search_worker: Worker[tuple[CataloguePage | None, str | None]] | None = None

    def compose(self) -> Iterable[Widget]:
        with Container(id="manual-match-dialog"):
            yield Static("Match manually", id="library-dialog-title")
            yield Static(
                f"{self.track.title}\nChoose the catalogue recording for this local file.",
                id="manual-match-context",
                markup=False,
            )
            yield ManualMatchInput(
                value=self.track.title,
                placeholder="Catalogue search",
                id="manual-match-query",
            )
            with VerticalScroll(id="manual-match-scroll"):
                yield Static("Searching catalogue…", id="manual-match-results", markup=False)
            yield Static(
                "↑/↓ Choose · Enter Save locked match · / Refine search · Esc Cancel",
                id="library-dialog-help",
                markup=False,
            )

    def on_mount(self) -> None:
        self.query_one("#manual-match-query", Input).focus()
        self._start_search(self.track.title)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if query:
            self._start_search(query)

    def _start_search(self, query: str) -> None:
        self.results = ()
        self.index = 0
        self.query_one("#manual-match-results", Static).update("Searching catalogue…")
        self._search_worker = self._search(query)

    @work(thread=True, exclusive=True, group="manual-match-search", exit_on_error=False)
    def _search(self, query: str) -> tuple[CataloguePage | None, str | None]:
        try:
            return self._search_provider(
                self.settings,
                query,
                page=1,
                page_size=50,
                refresh=False,
            ), None
        except Exception as exc:
            return None, str(exc) or type(exc).__name__

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._search_worker:
            return
        if event.state is WorkerState.SUCCESS:
            page, error = event.worker.result
            self._search_worker = None
            if error or page is None:
                self.query_one("#manual-match-results", Static).update(
                    f"Catalogue search unavailable: {error or 'Unknown error'}\nNo changes were made."
                )
                return
            self.results = tuple(
                result
                for result in page.results
                if result.song_id is not None and result.title
            )
            self.index = 0
            self.set_focus(None)
            self._render_results()
        elif event.state is WorkerState.ERROR:
            self._search_worker = None
            self.query_one("#manual-match-results", Static).update(
                "Catalogue search stopped safely. No changes were made."
            )

    def _render_results(self) -> None:
        if not self.results:
            self.query_one("#manual-match-results", Static).update(
                "No usable catalogue candidates found. Press / to refine the search."
            )
            return
        lines: list[str] = []
        for index, result in enumerate(self.results):
            marker = ">" if index == self.index else " "
            category = result.category or "category unknown"
            era = result.era or "era unknown"
            length = result.length or "duration unknown"
            lines.append(
                f"{marker} {result.title}\n"
                f"    {category} · {era} · {length} · ID {result.song_id}"
            )
        self.query_one("#manual-match-results", Static).update(
            Text("\n".join(lines), no_wrap=False, overflow="ellipsis")
        )
        self.call_after_refresh(self._scroll_selection_into_view)

    def _scroll_selection_into_view(self) -> None:
        if not self.results:
            return
        scroll = self.query_one("#manual-match-scroll", VerticalScroll)
        scroll.scroll_to(y=self.index * 2, animate=False, immediate=True)

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "question_mark":
            self.app.action_show_help()
        elif event.key == "slash":
            self.query_one("#manual-match-query", Input).focus()
        elif isinstance(self.app.focused, Input):
            return
        elif event.key in {"down", "j"} and self.results:
            self.index = min(len(self.results) - 1, self.index + 1)
            self._render_results()
        elif event.key in {"up", "k"} and self.results:
            self.index = max(0, self.index - 1)
            self._render_results()
        elif event.key == "enter" and self.results:
            selected = self.results[self.index]
            self.dismiss(ManualMatchChoice(selected.song_id, selected.title or ""))
        elif event.key in {"1", "2", "3", "4", "5"}:
            pass
        else:
            return
        event.prevent_default()
        event.stop()


class LibraryIssuesDialog(ModalScreen[LibraryIssueChoice | None]):
    """Cheap snapshot-backed list of tracks that still need user attention."""

    def __init__(self, health: LibraryHealth, *, maintenance: bool = False) -> None:
        super().__init__()
        self.health = health
        self.index = 0
        self.maintenance = maintenance
        self.skipped: set[int] = set()

    @property
    def selected_issue(self) -> LibraryIssue | None:
        if not self.health.issues:
            return None
        return self.health.issues[self.index]

    def compose(self) -> Iterable[Widget]:
        with Container(id="library-issues-dialog"):
            yield Static("Library Issues", id="library-dialog-title")
            yield Static("", id="library-issues-summary", markup=False)
            with Grid(id="library-issues-main"):
                with VerticalScroll(id="library-issues-list-scroll"):
                    yield Static("", id="library-issues-list", markup=False)
                with VerticalScroll(id="library-issues-detail-scroll"):
                    yield Static("", id="library-issues-detail", markup=False)
            yield Static("", id="library-issues-help", markup=False)

    def on_mount(self) -> None:
        self._render_issues()

    def _render_issues(self) -> None:
        issues = self.health.issues
        if self.maintenance:
            needs_input = sum(
                issue.severity is LibraryIssueSeverity.ERROR
                or LibraryIssueCategory.CATALOGUE in issue.categories
                for issue in issues
            )
            optional = len(issues) - needs_input
            self.query_one("#library-dialog-title", Static).update("Maintenance")
        self.query_one("#library-issues-summary", Static).update(
            (
                f"{self.health.snapshot.total_track_count} songs · "
                f"{max(0, self.health.snapshot.total_track_count - needs_input)} ready · "
                f"{needs_input} need your input · {optional} optional improvements"
                if self.maintenance else
                f"{self.health.snapshot.total_track_count} tracks · "
                f"{self.health.healthy_count} issue-free · {self.health.issue_count} follow-ups"
            )
        )
        if not issues:
            self.query_one("#library-issues-list", Static).update(
                "Everything looks ready" if self.maintenance else "No follow-ups"
            )
            self.query_one("#library-issues-detail", Static).update(
                "No items need your attention right now.\n\nYour songs and files are unchanged."
                if self.maintenance else
                "No library issues found.\n\nSync Library will keep this view current."
            )
            self.query_one("#library-issues-help", Static).update(
                "Enter / Esc Done" if self.maintenance else "Esc Close · ? Help"
            )
            return
        lines = []
        for index, issue in enumerate(issues):
            marker = ">" if index == self.index else " "
            lines.append(
                f"{marker} {issue.track.title[:27]:27} · "
                f"{issue.category_label:15} · {issue.severity.value.title()}"
            )
        self.query_one("#library-issues-list", Static).update(
            Text("\n".join(lines), no_wrap=True, overflow="ellipsis")
        )
        issue = issues[self.index]
        if self.maintenance:
            self.query_one("#library-issues-detail", Static).update(
                Text(
                    f"Maintenance · {self.index + 1} of {len(issues)}\n\n"
                    f"{issue.track.title}\n\n{_maintenance_issue_label(issue)}\n\n"
                    f"{chr(10).join(issue.details)}\n\n"
                    "Choose to open the safe next step. Skipping leaves it for later.",
                    overflow="ellipsis",
                )
            )
            self.query_one("#library-issues-help", Static).update(
                "↑/↓ Choose · Enter Start · s Skip · Esc Stop"
            )
            return
        detail_lines = [
            issue.track.title,
            "",
            f"Issue          {issue.summary}",
            f"Category       {issue.category_label}",
            f"Severity       {issue.severity.value.title()}",
            f"Format         {issue.track.media_format}",
            f"Artist         {issue.track.artist or 'Not available'}",
            f"Album          {issue.track.album or 'Not available'}",
            f"Path           {issue.track.relative_path}",
            "",
            *issue.details,
        ]
        if issue.action is LibraryIssueAction.MANUAL_MATCH:
            detail_lines.extend(("", "Next step: press c to choose a catalogue match."))
        elif issue.action is LibraryIssueAction.REFRESH_LYRICS:
            detail_lines.extend(("", "Next step: press l to preview a lyric refresh."))
        elif issue.action is LibraryIssueAction.SYNC:
            detail_lines.extend(("", "Next step: press s to Sync Library."))
        else:
            detail_lines.extend(("", "Next step: press v to verify the library again."))
        if LibraryIssueCategory.METADATA in issue.categories:
            detail_lines.extend(("", "Press e to review and select metadata repairs."))
        self.query_one("#library-issues-detail", Static).update(
            Text("\n".join(detail_lines), overflow="ellipsis")
        )
        available = ["↑/↓ Select"]
        if LibraryIssueCategory.CATALOGUE in issue.categories:
            available.append("c Match manually")
        if LibraryIssueCategory.METADATA in issue.categories:
            available.append("e Metadata repair")
        if LibraryIssueCategory.LYRICS in issue.categories:
            available.append("l Refresh lyrics")
        available.extend(("v Verify", "s Sync Library", "Esc Close", "? Help"))
        self.query_one("#library-issues-help", Static).update(" · ".join(available))
        self.call_after_refresh(self._scroll_selection_into_view)

    def _scroll_selection_into_view(self) -> None:
        if not self.health.issues:
            return
        scroll = self.query_one("#library-issues-list-scroll", VerticalScroll)
        scroll.scroll_to(y=self.index, animate=False, immediate=True)

    def on_key(self, event: Key) -> None:
        issue = self.selected_issue
        if self.maintenance:
            if event.key in {"escape", "q"}:
                self.dismiss(None)
            elif event.key in {"down", "j"} and issue is not None:
                self.index = min(len(self.health.issues) - 1, self.index + 1)
                self._render_issues()
            elif event.key in {"up", "k"} and issue is not None:
                self.index = max(0, self.index - 1)
                self._render_issues()
            elif event.key == "s" and issue is not None:
                self.skipped.add(self.index)
                next_index = next(
                    (position for position in range(self.index + 1, len(self.health.issues))
                     if position not in self.skipped),
                    None,
                )
                if next_index is None:
                    self.dismiss(None)
                else:
                    self.index = next_index
                    self._render_issues()
            elif event.key in {"enter", "space"} and issue is not None:
                self._dismiss_issue(issue)
            else:
                return
            event.prevent_default()
            event.stop()
            return
        if event.key in {"escape", "a"}:
            self.dismiss(None)
        elif event.key == "question_mark":
            self.app.action_show_help()
        elif event.key in {"down", "j"} and issue is not None:
            self.index = min(len(self.health.issues) - 1, self.index + 1)
            self._render_issues()
        elif event.key in {"up", "k"} and issue is not None:
            self.index = max(0, self.index - 1)
            self._render_issues()
        elif event.key == "home" and issue is not None:
            self.index = 0
            self._render_issues()
        elif event.key == "end" and issue is not None:
            self.index = len(self.health.issues) - 1
            self._render_issues()
        elif (
            event.key == "c"
            and issue is not None
            and LibraryIssueCategory.CATALOGUE in issue.categories
        ):
            self.dismiss(LibraryIssueChoice(issue.track.reference, LibraryIssueAction.MANUAL_MATCH))
        elif event.key == "l" and issue is not None and LibraryIssueCategory.LYRICS in issue.categories:
            self.dismiss(LibraryIssueChoice(issue.track.reference, LibraryIssueAction.REFRESH_LYRICS))
        elif event.key == "e" and issue is not None and LibraryIssueCategory.METADATA in issue.categories:
            self.dismiss(LibraryIssueChoice(issue.track.reference, LibraryIssueAction.METADATA_AUDIT))
        elif event.key == "v":
            self.dismiss(
                LibraryIssueChoice(issue.track.reference if issue else "", LibraryIssueAction.VERIFY)
            )
        elif event.key == "s":
            self.dismiss(
                LibraryIssueChoice(issue.track.reference if issue else "", LibraryIssueAction.SYNC)
            )
        elif event.key in {"1", "2", "3", "4", "5"}:
            pass
        else:
            return
        event.prevent_default()
        event.stop()

    def _dismiss_issue(self, issue: LibraryIssue) -> None:
        self.dismiss(LibraryIssueChoice(issue.track.reference, issue.action))


def _maintenance_issue_label(issue: LibraryIssue) -> str:
    if LibraryIssueCategory.CATALOGUE in issue.categories:
        return "Catalogue match needs your choice."
    if LibraryIssueCategory.METADATA in issue.categories:
        return "Metadata can be reviewed; nothing is changed until you approve it."
    if LibraryIssueCategory.LYRICS in issue.categories:
        return "Lyrics are missing or could be refreshed. This is optional, not file damage."
    if issue.severity is LibraryIssueSeverity.ERROR:
        return "This needs a safety check before it can be marked ready."
    return "This song may need a review."


class MaintenanceWizardDialog(ModalScreen[MaintenanceWizardChoice | None]):
    """One-step-at-a-time Library maintenance workflow."""

    def __init__(
        self,
        health: LibraryHealth,
        *,
        phase: str,
        issue: LibraryIssue | None = None,
        position: int = 0,
        total: int = 0,
        skipped: int = 0,
        matched: int = 0,
        lyrics_resolved: int = 0,
        message: str | None = None,
    ) -> None:
        super().__init__()
        self.health = health
        self.phase = phase
        self.issue = issue
        self.position = position
        self.total = total
        self.skipped = skipped
        self.matched = matched
        self.lyrics_resolved = lyrics_resolved
        self.message = message

    def compose(self) -> Iterable[Widget]:
        with Container(id="library-dialog"):
            yield Static("", id="library-dialog-title")
            yield Static("", id="library-dialog-body", markup=False)
            yield Static("", id="library-more-help", markup=False)

    def on_mount(self) -> None:
        health = self.health
        errors = sum(
            item.severity is LibraryIssueSeverity.ERROR for item in health.issues
        )
        optional = sum(_maintenance_optional(item) for item in health.issues)
        required = len(health.issues) - optional
        title = self.query_one("#library-dialog-title", Static)
        body = self.query_one("#library-dialog-body", Static)
        help_text = self.query_one("#library-more-help", Static)
        if self.phase == "summary":
            title.update("Maintenance")
            notice = f"{self.message}\n\n" if self.message else ""
            body.update(
                f"{notice}✓ {health.healthy_count} ready\n"
                f"? {required} need your input\n"
                f"~ {optional} optional improvements\n"
                f"! {errors} errors\n\n"
                "Maintenance refreshes safely first, then walks through one item at a time."
            )
            help_text.update("Enter Start Maintenance · Esc Stop for now")
        elif self.phase == "item" and self.issue is not None:
            title.update(f"Maintenance — {self.position} of {self.total}")
            prefix = f"{self.message}\n\n" if self.message else ""
            body.update(
                f"{prefix}{self.issue.track.title}\n\n"
                f"{_maintenance_issue_label(self.issue)}\n\n"
                f"{chr(10).join(self.issue.details)}"
            )
            verb = {
                LibraryIssueAction.MANUAL_MATCH: "Choose Match",
                LibraryIssueAction.REFRESH_LYRICS: "Add Lyrics",
                LibraryIssueAction.METADATA_AUDIT: "Review Metadata",
                LibraryIssueAction.VERIFY: "Verify",
                LibraryIssueAction.SYNC: "Refresh",
            }[self.issue.action]
            help_text.update(f"Enter {verb} · s Skip · Esc Stop for now")
        else:
            ready = max(
                0, health.snapshot.total_track_count - len(health.issues) - self.skipped
            )
            title.update("Maintenance complete")
            notice = f"{self.message}\n\n" if self.message else ""
            body.update(
                f"{notice}{health.snapshot.total_track_count} tracks\n\n"
                f"✓ {ready} ready\n"
                f"? {self.skipped} skipped for later\n"
                f"~ {optional} optional improvements\n"
                f"! {errors} errors\n\n"
                "This run:\n"
                f"{self.matched} {'song' if self.matched == 1 else 'songs'} matched\n"
                f"{self.lyrics_resolved} lyric {'issue' if self.lyrics_resolved == 1 else 'issues'} resolved"
            )
            help_text.update(
                "o Review optional improvements · Enter Done"
                if optional else "Enter Done"
            )

    def on_key(self, event: Key) -> None:
        if event.key in {"escape", "q"}:
            self.dismiss(None)
        elif self.phase == "summary" and event.key in {"enter", "space"}:
            self.dismiss(MaintenanceWizardChoice("start"))
        elif self.phase == "item" and self.issue is not None:
            if event.key in {"enter", "space"}:
                self.dismiss(MaintenanceWizardChoice("act", self.issue))
            elif event.key == "s":
                self.dismiss(MaintenanceWizardChoice("skip", self.issue))
            else:
                return
        elif self.phase == "complete":
            if event.key in {"enter", "space"}:
                self.dismiss(MaintenanceWizardChoice("done"))
            elif event.key == "o":
                self.dismiss(MaintenanceWizardChoice("optional"))
            else:
                return
        else:
            return
        event.prevent_default()
        event.stop()


def _maintenance_optional(issue: LibraryIssue) -> bool:
    return (
        issue.severity is not LibraryIssueSeverity.ERROR
        and LibraryIssueCategory.CATALOGUE not in issue.categories
        and LibraryIssueCategory.LYRICS not in issue.categories
    )


class LibraryDuplicatesDialog(ModalScreen[None]):
    """Read-only duplicate groups derived from the current Library snapshot."""

    def __init__(self, report: DuplicateReport) -> None:
        super().__init__()
        self.report = report
        self.index = 0

    def compose(self) -> Iterable[Widget]:
        with Container(id="library-duplicates-dialog"):
            yield Static("Duplicate recordings", id="library-dialog-title")
            yield Static("", id="library-duplicates-summary", markup=False)
            with Grid(id="library-duplicates-main"):
                with VerticalScroll(id="library-duplicates-list-scroll"):
                    yield Static("", id="library-duplicates-list", markup=False)
                with VerticalScroll(id="library-duplicates-detail-scroll"):
                    yield Static("", id="library-duplicates-detail", markup=False)
            yield Static("↑/↓ Select · Esc Close · ? Help", id="library-duplicates-help", markup=False)

    def on_mount(self) -> None:
        self._render_duplicates()

    def _render_duplicates(self) -> None:
        groups = self.report.groups
        self.query_one("#library-duplicates-summary", Static).update(
            f"{len(groups)} duplicate group{'s' if len(groups) != 1 else ''} · "
            f"{self.report.file_count} file{'s' if self.report.file_count != 1 else ''}"
        )
        if not groups:
            self.query_one("#library-duplicates-list", Static).update(
                "No duplicate recordings found"
            )
            self.query_one("#library-duplicates-detail", Static).update(
                "No exact or probable duplicate groups are present in the current Library snapshot."
            )
            return
        lines = []
        for index, group in enumerate(groups):
            marker = ">" if index == self.index else " "
            label = "Exact" if group.confidence is DuplicateConfidence.EXACT else "Probable"
            lines.append(
                f"{marker} {group.title[:27]:27} · {label:8} · {len(group.tracks)} files"
            )
        self.query_one("#library-duplicates-list", Static).update(
            Text("\n".join(lines), no_wrap=True, overflow="ellipsis")
        )
        self._render_duplicate_detail(groups[self.index])
        self.call_after_refresh(self._scroll_duplicate_selection_into_view)

    def _render_duplicate_detail(self, group: DuplicateGroup) -> None:
        label = "Exact duplicate audio" if group.confidence is DuplicateConfidence.EXACT else "Probable duplicate recording"
        lines = [group.title, "", f"Assessment     {label}", "", "Evidence"]
        lines.extend(f"- {item}" for item in group.evidence)
        lines.extend(("", "Files"))
        for track in group.tracks:
            duration = _duration(track.duration_seconds)
            catalogue = (
                f" · catalogue {track.catalogue_id}"
                if track.catalogue_id is not None
                else ""
            )
            lines.extend(
                (
                    f"- {track.relative_path}",
                    f"  {track.media_format} · {duration}{catalogue}",
                )
            )
        lines.extend(("", "Review only — no files will be changed."))
        self.query_one("#library-duplicates-detail", Static).update(
            Text("\n".join(lines), overflow="ellipsis")
        )

    def _scroll_duplicate_selection_into_view(self) -> None:
        if not self.report.groups:
            return
        self.query_one("#library-duplicates-list-scroll", VerticalScroll).scroll_to(
            y=self.index, animate=False, immediate=True
        )

    def on_key(self, event: Key) -> None:
        groups = self.report.groups
        if event.key in {"escape", "d"}:
            self.dismiss(None)
        elif event.key == "question_mark":
            self.app.action_show_help()
        elif event.key in {"down", "j"} and groups:
            self.index = min(len(groups) - 1, self.index + 1)
            self._render_duplicates()
        elif event.key in {"up", "k"} and groups:
            self.index = max(0, self.index - 1)
            self._render_duplicates()
        elif event.key == "home" and groups:
            self.index = 0
            self._render_duplicates()
        elif event.key == "end" and groups:
            self.index = len(groups) - 1
            self._render_duplicates()
        elif event.key in {"1", "2", "3", "4", "5"}:
            pass
        else:
            return
        event.prevent_default()
        event.stop()


class MissingLibraryInput(Input):
    """Local filter input for the Missing Library modal."""

    def on_key(self, event: Key) -> None:
        if event.key == "escape":
            self.screen.set_focus(None)
            event.prevent_default()
            event.stop()
        elif event.key == "question_mark":
            self.app.action_show_help()
            event.prevent_default()
            event.stop()


class MissingLibraryDialog(ModalScreen[None]):
    """Identity-based, read-only catalogue gap view with explicit queue add."""

    def __init__(
        self,
        settings: Any,
        snapshot: LibrarySnapshot,
        *,
        report_provider: MissingLibraryProvider = get_missing_library,
        queue_plan_provider: QueuePlanProvider = plan_queue_batch_additions,
        queue_add_provider: QueueAddProvider = add_batch_to_download_queue,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.snapshot = snapshot
        self._report_provider = report_provider
        self._queue_plan_provider = queue_plan_provider
        self._queue_add_provider = queue_add_provider
        self.report: MissingLibraryReport | None = None
        self.results: tuple[CatalogueSearchResult, ...] = ()
        self.index = 0
        self._load_worker: Worker[MissingLibraryReport] | None = None
        self._queue_worker: Worker[QueueAddResult | QueueBatchAddResult] | None = None
        self._adding = False

    def compose(self) -> Iterable[Widget]:
        with Container(id="missing-library-dialog"):
            yield Static("Missing Library", id="library-dialog-title")
            yield Static("Loading catalogue coverage…", id="missing-library-summary", markup=False)
            yield MissingLibraryInput(placeholder="Filter loaded recordings", id="missing-library-query")
            with Grid(id="missing-library-main"):
                with VerticalScroll(id="missing-library-list-scroll"):
                    yield Static("Loading…", id="missing-library-list", markup=False)
                with VerticalScroll(id="missing-library-detail-scroll"):
                    yield Static("The catalogue is loading in the background.", id="missing-library-detail", markup=False)
            yield Static("/ Filter · ↑/↓ Select · a Add to Downloads · Esc Close · ? Help", id="missing-library-help", markup=False)

    def on_mount(self) -> None:
        self.call_after_refresh(self.set_focus, None)
        self._load_worker = self._load_report()

    @work(thread=True, exclusive=True, group="missing-library-load", exit_on_error=False)
    def _load_report(self) -> MissingLibraryReport:
        return self._report_provider(self.settings, self.snapshot)

    @work(thread=True, exclusive=True, group="missing-library-queue", exit_on_error=False)
    def _queue_selected(self, selection: CatalogueSearchResult) -> QueueAddResult | QueueBatchAddResult:
        planned = self._queue_plan_provider(self.settings, (selection,))
        plan = getattr(planned, "plan", None)
        if plan is None:
            return planned
        return self._queue_add_provider(plan)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._load_worker:
            if event.state is WorkerState.SUCCESS:
                self.report = event.worker.result
                self._filter_results()
            elif event.state is WorkerState.ERROR:
                self.query_one("#missing-library-summary", Static).update("Catalogue coverage unavailable")
                self.query_one("#missing-library-list", Static).update("Unable to load the catalogue.")
                self.query_one("#missing-library-detail", Static).update("Your local Library was not changed.")
        elif event.worker is self._queue_worker:
            if event.state is WorkerState.SUCCESS:
                result = event.worker.result
                self._adding = False
                self.query_one("#missing-library-summary", Static).update(result.message)
                if result.ok:
                    invalidate = getattr(self.app, "invalidate_download_queue", None)
                    if callable(invalidate):
                        invalidate()
            elif event.state is WorkerState.ERROR:
                self._adding = False
                self.query_one("#missing-library-summary", Static).update("Unable to add this recording to Downloads.")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "missing-library-query" and self.report is not None:
            self._filter_results()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "missing-library-query":
            self.set_focus(None)

    def _filter_results(self) -> None:
        if self.report is None:
            return
        query = self.query_one("#missing-library-query", Input).value.strip().casefold()
        self.results = tuple(
            item for item in self.report.recordings
            if not query or query in " ".join(
                filter(None, (item.title, item.category, item.era, item.album, " ".join(item.artists)))
            ).casefold()
        )
        self.index = min(self.index, max(0, len(self.results) - 1))
        self._render_report()

    def _render_report(self) -> None:
        report = self.report
        if report is None:
            return
        coverage = {
            CatalogueCoverage.COMPLETE: "Complete catalogue coverage",
            CatalogueCoverage.PARTIAL: "Partial catalogue coverage",
            CatalogueCoverage.UNAVAILABLE: "Catalogue unavailable",
        }[report.coverage]
        summary = (
            f"{report.missing_count} confirmed missing · {report.local_unknown_count} local Unknown · "
            f"{report.loaded_recording_count} catalogue recordings loaded · {coverage}"
        )
        if report.error:
            summary += f" · {report.error}"
        self.query_one("#missing-library-summary", Static).update(summary)
        if not self.results:
            message = "No missing recordings match this filter." if report.recordings else (
                "No confirmed missing recordings in the loaded catalogue."
                if report.complete else "No missing recordings can be confirmed from the loaded catalogue data."
            )
            self.query_one("#missing-library-list", Static).update(message)
            self.query_one("#missing-library-detail", Static).update(
                "Local Unknown tracks are not assumed to own any catalogue recording. Run Sync or match them manually."
            )
            return
        lines = []
        for index, item in enumerate(self.results):
            marker = ">" if index == self.index else " "
            category = item.category or "unknown category"
            lines.append(f"{marker} {(item.title or 'Untitled')[:32]:32} · {category}")
        self.query_one("#missing-library-list", Static).update(Text("\n".join(lines), no_wrap=True, overflow="ellipsis"))
        item = self.results[self.index]
        artists = ", ".join(item.artists) or "Unknown"
        fields = (
            item.title or "Untitled",
            "",
            f"Catalogue ID   {item.song_id}",
            f"Category       {item.category or 'Unknown'}",
            f"Artists        {artists}",
            f"Album / era    {item.album or item.era or 'Unknown'}",
            f"Duration       {item.length or 'Unknown'}",
            f"Download       {'Available' if item.downloadable else 'Unavailable'}",
            "",
            "This exact catalogue recording ID is not present among confirmed local identities.",
        )
        self.query_one("#missing-library-detail", Static).update(Text("\n".join(fields), overflow="ellipsis"))
        self.call_after_refresh(
            self.query_one("#missing-library-list-scroll", VerticalScroll).scroll_to,
            y=self.index, animate=False, immediate=True,
        )

    def on_key(self, event: Key) -> None:
        if isinstance(self.app.focused, Input):
            return
        if event.key in {"escape", "g"}:
            self.dismiss(None)
        elif event.key == "question_mark":
            self.app.action_show_help()
        elif event.key == "slash":
            self.query_one("#missing-library-query", Input).focus()
        elif event.key in {"down", "j"} and self.results:
            self.index = min(len(self.results) - 1, self.index + 1)
            self._render_report()
        elif event.key in {"up", "k"} and self.results:
            self.index = max(0, self.index - 1)
            self._render_report()
        elif event.key == "home" and self.results:
            self.index = 0
            self._render_report()
        elif event.key == "end" and self.results:
            self.index = len(self.results) - 1
            self._render_report()
        elif event.key == "a" and self.results and not self._adding:
            selected = self.results[self.index]
            if not selected.downloadable:
                self.query_one("#missing-library-summary", Static).update("This recording is not available to download.")
            else:
                self._adding = True
                self.query_one("#missing-library-summary", Static).update("Adding to Downloads…")
                self._queue_worker = self._queue_selected(selected)
        elif event.key in {"1", "2", "3", "4", "5"}:
            pass
        else:
            return
        event.prevent_default()
        event.stop()


class MetadataAuditDialog(ModalScreen[tuple[str, ...] | None]):
    """Select explicit fields from a before/after metadata preview."""

    def __init__(self, audit: MetadataAudit) -> None:
        super().__init__()
        self.audit = audit
        self.index = 0
        self.selected: set[str] = set()
        self._submitted = False

    def compose(self) -> Iterable[Widget]:
        with Container(id="metadata-audit-dialog"):
            yield Static("Metadata repair preview", id="library-dialog-title")
            with VerticalScroll(id="metadata-audit-scroll"):
                yield Static(self._text(), id="metadata-audit-content", markup=False)
            yield Static(self._help_text(), id="metadata-audit-help", markup=False)

    def on_mount(self) -> None:
        self.query_one("#metadata-audit-scroll", VerticalScroll).focus()

    def _help_text(self) -> str:
        if not self.audit.proposals:
            return "No repairable fields · Esc Close"
        return "↑↓ Choose · Space/Enter Select · a Review apply · Esc Cancel"

    @property
    def _ordered_proposals(self) -> tuple[Any, ...]:
        return tuple(
            proposal
            for confidence in (
                MetadataProposalConfidence.CONFIDENT,
                MetadataProposalConfidence.REVIEW,
            )
            for proposal in self.audit.proposals
            if proposal.confidence is confidence
        )

    def _text(self) -> Text:
        audit = self.audit
        track = audit.track
        lines = [
            track.title,
            "",
            f"Format         {track.media_format}",
            f"Path           {track.relative_path}",
            f"Catalogue ID   {track.catalogue_id or 'Unknown'}",
            f"Identity       {'Manual lock' if track.identity_locked else 'Automatic' if track.catalogue_id is not None else 'Unknown'}",
        ]
        if audit.error:
            lines.extend(("", f"Preview unavailable: {audit.error}"))
        if audit.catalogue is not None:
            lines.extend(
                (
                    f"Catalogue      {audit.catalogue.title or 'Not available'}",
                    f"Category       {audit.catalogue.category or 'Not available'}",
                    f"Era            {audit.catalogue.era or 'Not available'}",
                    f"Duration       {audit.catalogue.length or 'Not available'}",
                )
            )
        lines.extend(("", "Proposed metadata · nothing is selected by default"))
        if not audit.proposals:
            lines.append("No metadata changes proposed")
        for confidence, heading in (
            (MetadataProposalConfidence.CONFIDENT, "Confident recommendations"),
            (MetadataProposalConfidence.REVIEW, "Review carefully"),
        ):
            proposals = tuple(
                (index, proposal)
                for index, proposal in enumerate(self._ordered_proposals)
                if proposal.confidence is confidence
            )
            if not proposals:
                continue
            lines.extend(("", heading))
            for index, proposal in proposals:
                cursor = ">" if index == self.index else " "
                checked = "x" if proposal.field in self.selected else " "
                lines.extend(
                    (
                        f"{cursor} [{checked}] {proposal.label}",
                        f"      {proposal.before or '(missing)'} → {proposal.after}",
                        f"      {proposal.reason}",
                    )
                )
        if audit.notes:
            lines.extend(("", "Notes", *(f"- {note}" for note in audit.notes)))
        return Text("\n".join(lines), overflow="ellipsis")

    def _render_content(self) -> None:
        self.query_one("#metadata-audit-content", Static).update(self._text())

    def _toggle(self) -> None:
        if not self.audit.proposals:
            return
        field = self._ordered_proposals[self.index].field
        if field in self.selected:
            self.selected.remove(field)
        else:
            self.selected.add(field)
        self._render_content()

    def on_key(self, event: Key) -> None:
        if self._submitted:
            event.prevent_default()
            event.stop()
            return
        if event.key in {"escape", "e"}:
            self._submitted = True
            self.dismiss(None)
        elif event.key in {"down", "j"} and self.audit.proposals:
            self.index = min(len(self._ordered_proposals) - 1, self.index + 1)
            self._render_content()
        elif event.key in {"up", "k"} and self.audit.proposals:
            self.index = max(0, self.index - 1)
            self._render_content()
        elif event.key in {"space", "enter"}:
            self._toggle()
        elif event.key == "a":
            if not self.selected:
                self.query_one("#metadata-audit-help", Static).update(
                    "Select at least one field · No changes have been made"
                )
            else:
                self._submitted = True
                fields = tuple(
                    proposal.field
                    for proposal in self._ordered_proposals
                    if proposal.field in self.selected
                )
                self.dismiss(fields)
        elif event.key == "question_mark":
            self.app.action_show_help()
        elif event.key in {"1", "2", "3", "4", "5"}:
            pass
        else:
            return
        event.prevent_default()
        event.stop()


class MetadataRepairConfirmationDialog(ModalScreen[bool]):
    """Cancel-first confirmation for one pinned metadata repair plan."""

    def __init__(self, plan: MetadataRepairPlan) -> None:
        super().__init__()
        self.plan = plan
        self._choice = "cancel"
        self._submitted = False

    def compose(self) -> Iterable[Widget]:
        changes = "\n".join(
            f"{proposal.label}: {proposal.before or '(missing)'} → {proposal.after}"
            for proposal in self.plan.selected
        )
        body = (
            f"{self.plan.reference}\n\n{changes}\n\n"
            "A complete audio backup will be created first. Only the selected "
            "metadata fields will change; audio, artwork, lyrics, and other tags "
            "will be verified."
        )
        with Container(id="library-dialog"):
            yield Static("Apply metadata repair?", id="library-dialog-title")
            yield Static(body, id="library-dialog-body", markup=False)
            with Grid(id="library-dialog-actions"):
                yield LibraryDialogAction("Apply", "confirm", id="library-dialog-confirm")
                yield LibraryDialogAction("Cancel", "cancel", id="library-dialog-cancel")

    def on_mount(self) -> None:
        self._render_choice()
        self.call_after_refresh(
            self.query_one("#library-dialog-cancel", LibraryDialogAction).focus
        )

    def _render_choice(self) -> None:
        self.query_one("#library-dialog-confirm", Static).update(
            "[Apply]" if self._choice == "confirm" else "Apply"
        )
        self.query_one("#library-dialog-cancel", Static).update(
            "[Cancel]" if self._choice == "cancel" else "Cancel"
        )

    def _activate(self) -> None:
        if self._submitted:
            return
        self._submitted = True
        self.dismiss(self._choice == "confirm")

    def on_library_dialog_action_activated(
        self, event: LibraryDialogAction.Activated
    ) -> None:
        if self._submitted:
            return
        self._choice = event.action
        self._render_choice()
        self._activate()

    def on_key(self, event: Key) -> None:
        if self._submitted:
            event.prevent_default()
            event.stop()
            return
        if event.key in {"escape", "n"}:
            self._choice = "cancel"
            self._activate()
        elif event.key == "y":
            self._choice = "confirm"
            self._activate()
        elif event.key in {"left", "right", "tab", "shift+tab"}:
            self._choice = "confirm" if self._choice == "cancel" else "cancel"
            self._render_choice()
            target = (
                "#library-dialog-confirm"
                if self._choice == "confirm"
                else "#library-dialog-cancel"
            )
            self.query_one(target, LibraryDialogAction).focus()
        elif event.key == "enter":
            self._activate()
        elif event.key in {"1", "2", "3", "4", "5"}:
            pass
        else:
            return
        event.prevent_default()
        event.stop()


class MaintenanceDialog(ModalScreen[LibrarySyncPlan | None]):
    """Cancel-first confirmation for an already non-mutating maintenance preview."""

    def __init__(
        self,
        plan: LibrarySyncPlan,
        *,
        lyrics_offer: bool = False,
        message: str | None = None,
    ) -> None:
        super().__init__()
        self.plan = plan
        self.lyrics_offer = lyrics_offer
        self.message = message
        self._choice = "cancel"
        self._confirmed = False

    def compose(self) -> Iterable[Widget]:
        problems = self.plan.unresolved_files + self.plan.no_lyrics_files + self.plan.analysis_failures
        count = self.plan.ready_files
        notice = f"{self.message}\n\n" if self.message else ""
        offer = "Lyrics are available for this song.\n\n" if self.lyrics_offer and count else ""
        body = (
            f"{notice}{offer}{count} song{'s' if count != 1 else ''} can be updated · "
            f"{problems} cannot be updated now\n\n"
            f"{self.plan.synced_files:2}  Synced lyrics available\n"
            f"{self.plan.plain_files:2}  Plain lyrics available\n"
            f"{self.plan.unresolved_files:2}  Could not be matched\n"
            f"{self.plan.no_lyrics_files:2}  Lyrics unavailable\n"
            f"{self.plan.analysis_failures:2}  Could not be checked\n\n"
            "No changes have been made."
        )
        with Container(id="library-dialog"):
            yield Static("Library maintenance", id="library-dialog-title")
            yield Static(body, id="library-dialog-body", markup=False)
            with Grid(id="library-dialog-actions"):
                yield LibraryDialogAction(
                    f"Update {count} song{'s' if count != 1 else ''}", "confirm", id="library-dialog-confirm"
                )
                yield LibraryDialogAction("Cancel", "cancel", id="library-dialog-cancel")

    def on_mount(self) -> None:
        self._render_choice()
        self.call_after_refresh(self.query_one("#library-dialog-cancel", LibraryDialogAction).focus)

    def _render_choice(self) -> None:
        confirm = self.query_one("#library-dialog-confirm", Static)
        cancel = self.query_one("#library-dialog-cancel", Static)
        confirm.update(f"[Update {self.plan.ready_files} song{'s' if self.plan.ready_files != 1 else ''}]" if self._choice == "confirm" else f"Update {self.plan.ready_files} song{'s' if self.plan.ready_files != 1 else ''}")
        cancel.update("[Cancel]" if self._choice == "cancel" else "Cancel")

    def on_library_dialog_action_activated(self, event: LibraryDialogAction.Activated) -> None:
        if not self._confirmed:
            self._choice = event.action
            self._render_choice()
            self._activate()

    def on_key(self, event: Key) -> None:
        if self._confirmed:
            event.prevent_default(); event.stop(); return
        if event.key in {"escape", "n"}:
            self._confirmed = True
            self.dismiss(None)
        elif event.key == "y" and self.plan.ready_files:
            self._choice = "confirm"; self._render_choice(); self._activate()
        elif event.key in {"left", "right", "tab", "shift+tab"} and self.plan.ready_files:
            self._choice = "confirm" if self._choice == "cancel" else "cancel"
            self._render_choice()
            target = "#library-dialog-confirm" if self._choice == "confirm" else "#library-dialog-cancel"
            self.query_one(target, LibraryDialogAction).focus()
        elif event.key == "enter":
            self._activate()
        elif event.key in {"1", "2", "3", "4", "5"}:
            pass
        else:
            return
        event.prevent_default(); event.stop()

    def _activate(self) -> None:
        if self._choice == "cancel" or not self.plan.ready_files:
            self._confirmed = True
            self.dismiss(None)
        elif not self._confirmed:
            self._confirmed = True
            self.dismiss(self.plan)


class IdentityRebuildDialog(ModalScreen[IdentityRebuildPlan | None]):
    """Cancel-first confirmation for rebuilding catalogue identity state."""

    def __init__(self, plan: IdentityRebuildPlan) -> None:
        super().__init__()
        self.plan = plan
        self._choice = "cancel"
        self._confirmed = False

    def compose(self) -> Iterable[Widget]:
        body = (
            "This will re-identify your current library using the latest matcher.\n"
            "Audio and lyrics will not be modified.\n\n"
            f"Current tracks       {self.plan.current_tracks}\n"
            f"Existing identities {self.plan.existing_identities}\n"
            f"Manual locks kept   {self.plan.locked_identities}\n"
            f"Currently unknown   {self.plan.currently_unknown}\n"
            f"Stale records ignored {len(self.plan.stale_keys)}"
        )
        with Container(id="library-dialog"):
            yield Static("Rebuild catalogue matches?", id="library-dialog-title")
            yield Static(body, id="library-dialog-body", markup=False)
            with Grid(id="library-dialog-actions"):
                yield LibraryDialogAction("Rebuild matches", "confirm", id="library-dialog-confirm")
                yield LibraryDialogAction("Cancel", "cancel", id="library-dialog-cancel")

    def on_mount(self) -> None:
        self._render_choice()
        self.call_after_refresh(
            self.query_one("#library-dialog-cancel", LibraryDialogAction).focus
        )

    def _render_choice(self) -> None:
        self.query_one("#library-dialog-confirm", Static).update(
            "[Rebuild matches]" if self._choice == "confirm" else "Rebuild matches"
        )
        self.query_one("#library-dialog-cancel", Static).update(
            "[Cancel]" if self._choice == "cancel" else "Cancel"
        )

    def on_library_dialog_action_activated(self, event: LibraryDialogAction.Activated) -> None:
        if not self._confirmed:
            self._choice = event.action
            self._render_choice()
            self._activate()

    def on_key(self, event: Key) -> None:
        if self._confirmed:
            event.prevent_default(); event.stop(); return
        if event.key in {"escape", "n"}:
            self._confirmed = True
            self.dismiss(None)
        elif event.key == "y":
            self._choice = "confirm"; self._render_choice(); self._activate()
        elif event.key in {"left", "right", "tab", "shift+tab"}:
            self._choice = "confirm" if self._choice == "cancel" else "cancel"
            self._render_choice()
            target = "#library-dialog-confirm" if self._choice == "confirm" else "#library-dialog-cancel"
            self.query_one(target, LibraryDialogAction).focus()
        elif event.key == "enter":
            self._activate()
        elif event.key in {"1", "2", "3", "4", "5"}:
            pass
        else:
            return
        event.prevent_default(); event.stop()

    def _activate(self) -> None:
        if self._choice == "cancel":
            self._confirmed = True
            self.dismiss(None)
        elif not self._confirmed:
            self._confirmed = True
            self.dismiss(self.plan)


class BackupBrowser(ModalScreen[BackupRecord | None]):
    """Read-only valid backup browser; choosing Restore returns a record."""

    def __init__(self, records: tuple[BackupRecord, ...]) -> None:
        super().__init__()
        self.records = tuple(reversed(records))
        self.index = 0

    def compose(self) -> Iterable[Widget]:
        with Container(id="library-dialog"):
            yield Static("Backups", id="library-dialog-title")
            yield Static("", id="library-dialog-body", markup=False)
            yield Static("↑/↓ select · r restore · Escape close", id="library-dialog-help", markup=False)

    def on_mount(self) -> None:
        self._render_records()

    def _render_records(self) -> None:
        if not self.records:
            self.query_one("#library-dialog-body", Static).update("No backups available")
            return
        lines = [f"{len(self.records)} valid backup{'s' if len(self.records) != 1 else ''}\n"]
        for index, record in enumerate(self.records):
            marker = ">" if index == self.index else " "
            stamp = record.created_at.astimezone().strftime("%Y-%m-%d %H:%M")
            lines.append(f"{marker} {stamp} · {record.file_count} file{'s' if record.file_count != 1 else ''}")
        self.query_one("#library-dialog-body", Static).update("\n".join(lines))

    def on_key(self, event: Key) -> None:
        if event.key == "escape": self.dismiss(None)
        elif event.key in {"down", "j"} and self.records: self.index = min(len(self.records) - 1, self.index + 1); self._render_records()
        elif event.key in {"up", "k"} and self.records: self.index = max(0, self.index - 1); self._render_records()
        elif event.key == "r" and self.records: self.dismiss(self.records[self.index])
        elif event.key in {"1", "2", "3", "4", "5"}: pass
        else: return
        event.prevent_default(); event.stop()


class RestoreDialog(ModalScreen[BackupRecord | None]):
    """Cancel-first destructive restore confirmation."""

    def __init__(self, record: BackupRecord) -> None:
        super().__init__(); self.record = record; self._choice = "cancel"; self._confirmed = False

    def compose(self) -> Iterable[Widget]:
        with Container(id="library-dialog"):
            yield Static("Restore backup?", id="library-dialog-title")
            yield Static(
                f"This will replace {self.record.file_count} current audio file{'s' if self.record.file_count != 1 else ''}\nwith copies from the selected backup.",
                id="library-dialog-body", markup=False,
            )
            with Grid(id="library-dialog-actions"):
                yield LibraryDialogAction("Restore", "confirm", id="library-dialog-confirm")
                yield LibraryDialogAction("Cancel", "cancel", id="library-dialog-cancel")

    def on_mount(self) -> None:
        self._render_choice(); self.call_after_refresh(self.query_one("#library-dialog-cancel", LibraryDialogAction).focus)

    def _render_choice(self) -> None:
        self.query_one("#library-dialog-confirm", Static).update("[Restore]" if self._choice == "confirm" else "Restore")
        self.query_one("#library-dialog-cancel", Static).update("[Cancel]" if self._choice == "cancel" else "Cancel")

    def on_library_dialog_action_activated(self, event: LibraryDialogAction.Activated) -> None:
        if not self._confirmed: self._choice = event.action; self._render_choice(); self._activate()

    def on_key(self, event: Key) -> None:
        if self._confirmed: event.prevent_default(); event.stop(); return
        if event.key in {"escape", "n"}: self._confirmed = True; self.dismiss(None)
        elif event.key == "y": self._choice = "confirm"; self._render_choice(); self._activate()
        elif event.key in {"left", "right", "tab", "shift+tab"}:
            self._choice = "confirm" if self._choice == "cancel" else "cancel"; self._render_choice()
            self.query_one("#library-dialog-confirm" if self._choice == "confirm" else "#library-dialog-cancel", LibraryDialogAction).focus()
        elif event.key == "enter": self._activate()
        elif event.key in {"1", "2", "3", "4", "5"}: pass
        else: return
        event.prevent_default(); event.stop()

    def _activate(self) -> None:
        if self._choice == "cancel": self._confirmed = True; self.dismiss(None)
        elif not self._confirmed: self._confirmed = True; self.dismiss(self.record)


class RmpcDialog(ModalScreen[SettingsSnapshot | None]):
    """Read-only rmpc check with an explicit, cancel-first setup option."""

    def __init__(self, snapshot: SettingsSnapshot) -> None:
        super().__init__(); self.snapshot = snapshot; self._choice = "cancel"; self._confirmed = False

    @property
    def can_setup(self) -> bool:
        return (
            self.snapshot.rmpc.status is IntegrationStatus.DETECTED_NOT_CONFIGURED
            and self.snapshot.rmpc.config_exists
        )

    def compose(self) -> Iterable[Widget]:
        body = self.snapshot.rmpc.detail
        if self.can_setup:
            body += "\n\nSet up rmpc? This may update its configuration."
        elif (
            self.snapshot.rmpc.status is IntegrationStatus.DETECTED_NOT_CONFIGURED
            and not self.snapshot.rmpc.config_exists
        ):
            body += "\n\nOpen rmpc once to create its configuration, then check again."
        with Container(id="library-dialog"):
            yield Static("rmpc integration", id="library-dialog-title")
            yield Static(body, id="library-dialog-body", markup=False)
            with Grid(id="library-dialog-actions"):
                yield LibraryDialogAction("Set up rmpc", "confirm", id="library-dialog-confirm")
                yield LibraryDialogAction("Close", "cancel", id="library-dialog-cancel")

    def on_mount(self) -> None:
        self.query_one("#library-dialog-confirm", LibraryDialogAction).disabled = not self.can_setup
        self._render_choice(); self.call_after_refresh(self.query_one("#library-dialog-cancel", LibraryDialogAction).focus)

    def _render_choice(self) -> None:
        self.query_one("#library-dialog-confirm", Static).update("[Set up rmpc]" if self._choice == "confirm" else "Set up rmpc")
        self.query_one("#library-dialog-cancel", Static).update("[Close]" if self._choice == "cancel" else "Close")

    def on_library_dialog_action_activated(self, event: LibraryDialogAction.Activated) -> None:
        if event.action == "confirm" and not self.can_setup: return
        if not self._confirmed: self._choice = event.action; self._render_choice(); self._activate()

    def on_key(self, event: Key) -> None:
        if self._confirmed: event.prevent_default(); event.stop(); return
        if event.key in {"escape", "n"}: self._confirmed = True; self.dismiss(None)
        elif event.key == "y" and self.can_setup: self._choice = "confirm"; self._render_choice(); self._activate()
        elif event.key in {"left", "right", "tab", "shift+tab"} and self.can_setup:
            self._choice = "confirm" if self._choice == "cancel" else "cancel"; self._render_choice()
            self.query_one("#library-dialog-confirm" if self._choice == "confirm" else "#library-dialog-cancel", LibraryDialogAction).focus()
        elif event.key == "enter": self._activate()
        elif event.key in {"1", "2", "3", "4", "5"}: pass
        else: return
        event.prevent_default(); event.stop()

    def _activate(self) -> None:
        if self._choice == "cancel": self._confirmed = True; self.dismiss(None)
        elif self.can_setup and not self._confirmed: self._confirmed = True; self.dismiss(self.snapshot)


class LibraryMoreDialog(ModalScreen[str | None]):
    """Secondary tools stay available without crowding normal Library use."""

    _OPTIONS = (
        ("a", "Issues"), ("d", "Duplicates"), ("g", "Missing Library"),
        ("e", "Metadata Repair"), ("v", "Verify Library"), ("b", "Backups"),
        ("p", "Player integration"), ("i", "Rebuild catalogue matches"),
        ("l", "Maintain lyrics"), ("u", "Unlock a manual catalogue choice"),
    )

    def __init__(self) -> None:
        super().__init__()
        self.index = 0

    def compose(self) -> Iterable[Widget]:
        with Container(id="library-dialog"):
            yield Static("More / Advanced", id="library-dialog-title")
            yield Static("Choose an occasional or recovery tool. These do not run automatically.", id="library-dialog-body", markup=False)
            yield Static("", id="library-more-options", markup=False)
            yield Static("↑/↓ Choose · Enter Open · Esc Close", id="library-more-help", markup=False)

    def on_mount(self) -> None:
        self._render_options()

    def _render_options(self) -> None:
        self.query_one("#library-more-options", Static).update(
            "\n".join(
                f"{'>' if position == self.index else ' '} {label}  ({key})"
                for position, (key, label) in enumerate(self._OPTIONS)
            )
        )

    def on_key(self, event: Key) -> None:
        if event.key in {"escape", "q"}:
            self.dismiss(None)
        elif event.key in {"down", "j"}:
            self.index = min(len(self._OPTIONS) - 1, self.index + 1)
            self._render_options()
        elif event.key in {"up", "k"}:
            self.index = max(0, self.index - 1)
            self._render_options()
        elif event.key == "enter":
            self.dismiss(self._OPTIONS[self.index][0])
        elif event.key in {key for key, _ in self._OPTIONS}:
            self.dismiss(event.key)
        else:
            return
        event.prevent_default()
        event.stop()


class ChangeMatchConfirmation(ModalScreen[bool]):
    """Explain replacement of an existing manual catalogue choice."""

    def __init__(self, title: str) -> None:
        super().__init__()
        self.track_title = title

    def compose(self) -> Iterable[Widget]:
        with Container(id="library-dialog"):
            yield Static("Change catalogue match?", id="library-dialog-title")
            yield Static(
                f"This will replace the saved catalogue choice for {self.track_title}. "
                "The new choice is saved only after you select a recording.",
                id="library-dialog-body", markup=False,
            )
            yield Static("Enter / y Continue · Esc Cancel", id="library-more-help", markup=False)

    def on_key(self, event: Key) -> None:
        if event.key in {"enter", "y"}:
            self.dismiss(True)
        elif event.key in {"escape", "n"}:
            self.dismiss(False)
        else:
            return
        event.prevent_default()
        event.stop()


class LibraryScreen(HubScreen):
    """Local library browser and safe maintenance centre."""

    BINDINGS = [Binding("/", "focus_search", "Search", show=False)]

    def action_refresh_library(self) -> None:
        self.sync_library()

    def __init__(
        self,
        settings: Any,
        *,
        snapshot_provider: SnapshotProvider,
        index_sync_provider: IndexSyncProvider,
        identity_provider: IdentityProvider,
        identity_rebuild_plan_provider: IdentityRebuildPlanProvider,
        identity_rebuild_execution_provider: IdentityRebuildExecutionProvider,
        preview_provider: PreviewProvider,
        execution_provider: ExecutionProvider,
        backup_provider: BackupProvider,
        restore_provider: RestoreProvider,
        rmpc_status_provider: RmpcStatusProvider,
        rmpc_setup_provider: RmpcSetupProvider,
        manual_search_provider: ManualSearchProvider,
        catalogue_details_provider: CatalogueDetailsProvider = get_song_details_by_id,
        metadata_audit_provider: MetadataAuditProvider = audit_track_metadata,
        metadata_repair_plan_provider: MetadataRepairPlanProvider = plan_metadata_repair,
        metadata_repair_execution_provider: MetadataRepairExecutionProvider = execute_metadata_repair,
        manual_identity_provider: ManualIdentityProvider = set_manual_identity,
        manual_unlock_provider: ManualIdentityProvider = unlock_manual_identity,
        missing_library_provider: MissingLibraryProvider = get_missing_library,
        queue_plan_provider: QueuePlanProvider = plan_queue_batch_additions,
        queue_add_provider: QueueAddProvider = add_batch_to_download_queue,
        lyrics_search_provider: LyricsSearchProvider = build_lyrics_search_index,
    ) -> None:
        super().__init__("library", "Library")
        self.settings = settings
        self._snapshot_provider = snapshot_provider
        self._index_sync_provider = index_sync_provider
        self._identity_provider = identity_provider
        self._identity_rebuild_plan_provider = identity_rebuild_plan_provider
        self._identity_rebuild_execution_provider = identity_rebuild_execution_provider
        self._preview_provider = preview_provider
        self._execution_provider = execution_provider
        self._backup_provider = backup_provider
        self._restore_provider = restore_provider
        self._rmpc_status_provider = rmpc_status_provider
        self._rmpc_setup_provider = rmpc_setup_provider
        self._manual_search_provider = manual_search_provider
        self._catalogue_details_provider = catalogue_details_provider
        self._metadata_audit_provider = metadata_audit_provider
        self._metadata_repair_plan_provider = metadata_repair_plan_provider
        self._metadata_repair_execution_provider = metadata_repair_execution_provider
        self._manual_identity_provider = manual_identity_provider
        self._manual_unlock_provider = manual_unlock_provider
        self._missing_library_provider = missing_library_provider
        self._queue_plan_provider = queue_plan_provider
        self._queue_add_provider = queue_add_provider
        self._lyrics_search_provider = lyrics_search_provider
        self.snapshot: LibrarySnapshot | None = None
        self.filtered_tracks: tuple[LibraryTrack, ...] = ()
        self.selected_index = 0
        self.preview: LibrarySyncPlan | None = None
        self._details_mode = False
        self._details_action_index = 0
        self._snapshot_worker: Worker[SnapshotOutcome] | None = None
        self._identity_worker: Worker[IdentityOutcome] | None = None
        self._index_sync_worker: Worker[LibraryIndexSyncResult] | None = None
        self._pending_index_sync: LibraryIndexSyncResult | None = None
        self._identity_rebuild_plan_worker: Worker[IdentityRebuildPlanOutcome] | None = None
        self._identity_rebuild_worker: Worker[IdentityRebuildOutcome] | None = None
        self._preview_worker: Worker[PreviewOutcome] | None = None
        self._pending_snapshot: SnapshotOutcome | None = None
        self._pending_identity: IdentityOutcome | None = None
        self._pending_preview: PreviewOutcome | None = None
        self._preview_action: str | None = None
        self._execution_worker: Worker[ExecutionOutcome] | None = None
        self._backup_worker: Worker[BackupOutcome] | None = None
        self._restore_worker: Worker[tuple[int | None, str | None]] | None = None
        self._rmpc_worker: Worker[tuple[SettingsSnapshot | None, str | None]] | None = None
        self._rmpc_setup_worker: Worker[tuple[Path | None, str | None]] | None = None
        self._snapshot_action = "scan"
        self._maintenance_completed = 0
        self._maintenance_total = 0
        self._completion_message: tuple[str, bool] | None = None
        self._identify_requested = False
        self._identity_rebuild_completed = 0
        self._manual_identity_worker: Worker[ManualIdentityOutcome] | None = None
        self._manual_track: LibraryTrack | None = None
        self._metadata_audit_worker: Worker[MetadataAuditOutcome] | None = None
        self._pending_metadata_audit: MetadataAuditOutcome | None = None
        self._metadata_audit_cache: dict[tuple[str, str | None, str], MetadataAudit] = {}
        self._metadata_repair_plan_worker: Worker[MetadataRepairPlanOutcome] | None = None
        self._metadata_repair_worker: Worker[MetadataRepairOutcome] | None = None
        self._maintenance_requested = False
        self._maintenance_active = False
        self._maintenance_started = False
        self._maintenance_skipped: set[str] = set()
        self._maintenance_initial_total = 0
        self._maintenance_matched = 0
        self._maintenance_lyrics_resolved = 0
        self._maintenance_last_message: str | None = None
        self._maintenance_current_reference: str | None = None
        self._maintenance_lyrics_offer_reference: str | None = None

    def compose_content(self) -> Iterable[Widget]:
        yield Static(
            "0 tracks · 0 follow-ups · 0 errors\n"
            "Lyrics to improve 0 · Fully covered 0 · Catalogue unknown 0 · "
            "MP3 0 · FLAC 0 · M4A 0",
            id="library-summary",
            markup=False,
        )
        yield Static("Loading local audio library…", id="library-status", markup=False)
        with Grid(id="library-controls"):
            with Vertical(classes="library-filter"):
                yield Static("Local search", classes="filter-label")
                yield LibraryInput(placeholder="Optional title or filename", id="library-query")
            with Vertical(classes="library-filter"):
                yield Static("Status", classes="filter-label")
                yield LibrarySelect(_FILTER_OPTIONS, value=LibraryFilter.ALL.value, allow_blank=False, id="library-filter")
        with Grid(id="library-main"):
            with Container(classes="library-panel", id="library-tracks-panel"):
                yield Static("Tracks · loading", classes="panel-title", id="library-tracks-title")
                with VerticalScroll(id="library-tracks-scroll"):
                    yield Static("Loading tracks…", id="library-tracks", markup=False)
            with Container(classes="library-panel", id="library-details-panel"):
                yield Static("Track details", classes="panel-title")
                with VerticalScroll(id="library-details-scroll"):
                    yield Static("Select a track to inspect it.", id="library-details", markup=False)
        yield Static("Refresh and Maintenance never silently change audio, tags, or lyrics.", id="library-preview", markup=False)
        yield Static("/ Search · f Search Lyrics · r Refresh Library · m Maintenance · ↑↓ Move · Enter Open Song · ? Help", id="library-position", markup=False)

    def action_focus_search(self) -> None:
        self.query_one("#library-query", Input).focus()

    def on_screen_resume(self, event: ScreenResume) -> None:
        self.call_after_refresh(self.set_focus, None)
        if self._pending_index_sync is not None:
            outcome, self._pending_index_sync = self._pending_index_sync, None
            self._apply_index_sync(outcome)
        if self._pending_snapshot is not None:
            outcome, self._pending_snapshot = self._pending_snapshot, None
            self._apply_snapshot(outcome)
        elif self.snapshot is None and self._snapshot_worker is None:
            self.refresh_snapshot(identify=False)
        if self._pending_preview is not None:
            outcome, self._pending_preview = self._pending_preview, None
            self._apply_preview(outcome)
        if self._pending_identity is not None:
            outcome, self._pending_identity = self._pending_identity, None
            self._apply_identity(outcome)
        if self._pending_metadata_audit is not None:
            outcome, self._pending_metadata_audit = self._pending_metadata_audit, None
            self._apply_metadata_audit(outcome)

    def refresh_snapshot(self, *, identify: bool = True) -> None:
        if self._index_sync_worker is not None and not self._index_sync_worker.is_finished:
            self._set_status("Library Sync is running; the view will update when it finishes.")
            return
        if self.snapshot is None:
            self.query_one("#library-tracks", Static).update("Loading tracks…")
            self.query_one("#library-details", Static).update("Waiting for library data…")
        self.preview = None
        self.query_one("#library-preview", Static).update("Sync Library updates the catalogue view without changing audio or lyrics.")
        self._identify_requested = identify and self._snapshot_action != "verify"
        self._set_status("Verifying library…" if self._snapshot_action == "verify" else "Scanning library…")
        self._snapshot_worker = self._load_snapshot()

    def invalidate_snapshot(self) -> None:
        self.snapshot = None
        self.preview = None
        self._snapshot_worker = None
        self._identity_worker = None
        self._identity_rebuild_plan_worker = None
        self._identity_rebuild_worker = None
        self._manual_identity_worker = None
        self._manual_track = None
        self._metadata_audit_worker = None
        self._pending_metadata_audit = None
        self._metadata_audit_cache.clear()
        self._metadata_repair_plan_worker = None
        self._metadata_repair_worker = None
        self._preview_worker = None
        self._pending_snapshot = None
        self._pending_identity = None
        self._pending_preview = None

    def sync_library(self) -> None:
        if self._index_sync_worker is not None and not self._index_sync_worker.is_finished:
            self._set_status("Library Sync is already running.")
            return
        self._snapshot_worker = None
        self._identity_worker = None
        self._set_status("Syncing library…")
        self._index_sync_worker = self._run_index_sync(self.snapshot)

    @work(thread=True, exclusive=True, group="library-index-sync", exit_on_error=False)
    def _run_index_sync(self, previous: LibrarySnapshot | None) -> LibraryIndexSyncResult:
        return self._index_sync_provider(self.settings, previous_snapshot=previous)

    def _apply_index_sync(self, result: LibraryIndexSyncResult) -> None:
        self._index_sync_worker = None
        self._identify_requested = False
        if self._maintenance_requested:
            self._maintenance_requested = False
            self._maintenance_active = True
            if result.error or result.failed:
                self._maintenance_last_message = (
                    "Catalogue is temporarily unavailable. Existing matches are safe. "
                    "Online matching was skipped."
                )
                self._maintenance_skipped.update(
                    track.reference
                    for track in result.snapshot.tracks
                    if track.match_status is LibraryMatchStatus.UNMATCHED
                )
        self._apply_snapshot(SnapshotOutcome(result.snapshot))
        self._set_status(result.summary, error=bool(result.error or result.failed))

    def _open_maintenance(self) -> None:
        if self.snapshot is None:
            self._set_status("Load the Library before starting Maintenance.", error=True)
            return
        self._maintenance_requested = True
        self._maintenance_active = False
        self._maintenance_started = False
        self._maintenance_skipped.clear()
        self._maintenance_initial_total = 0
        self._maintenance_matched = 0
        self._maintenance_lyrics_resolved = 0
        self._maintenance_last_message = None
        self._maintenance_current_reference = None
        self._maintenance_lyrics_offer_reference = None
        self._set_status("Refreshing changed songs before Maintenance…")
        self.sync_library()

    def _show_maintenance(self) -> None:
        if self.snapshot is None:
            return
        self._maintenance_active = True
        full_health = get_library_health(self.snapshot)
        health = LibraryHealth(
            full_health.snapshot,
            tuple(
                issue for issue in full_health.issues
                if issue.track.reference not in self._maintenance_skipped
            ),
        )
        required = tuple(
            issue for issue in health.issues
            if not _maintenance_optional(issue)
        )
        if not self._maintenance_started:
            self._maintenance_initial_total = len(required)
            phase = "summary"
            issue = None
        elif required:
            phase = "item"
            issue = required[0]
            self._maintenance_current_reference = issue.track.reference
        else:
            phase = "complete"
            issue = None
        self.app.push_screen(
            MaintenanceWizardDialog(
                health,
                phase=phase,
                issue=issue,
                position=(
                    self._maintenance_initial_total - len(required) + 1
                    if issue is not None else 0
                ),
                total=self._maintenance_initial_total,
                skipped=len(self._maintenance_skipped),
                matched=self._maintenance_matched,
                lyrics_resolved=self._maintenance_lyrics_resolved,
                message=self._maintenance_last_message,
            ),
            self._maintenance_wizard_closed,
        )
        self._maintenance_last_message = None

    def _offer_lyrics_after_match(self) -> None:
        reference, self._maintenance_lyrics_offer_reference = (
            self._maintenance_lyrics_offer_reference,
            None,
        )
        track = next(
            (
                item for item in self.snapshot.tracks
                if item.reference == reference
            ),
            None,
        ) if self.snapshot is not None else None
        if track is not None and track.lyric_status is LibraryLyricStatus.NONE:
            self._maintenance_current_reference = track.reference
            self.generate_preview(action="selected", selected_path=track.path)
            return
        self._show_maintenance()

    def _maintenance_wizard_closed(
        self, choice: MaintenanceWizardChoice | None
    ) -> None:
        if choice is None or choice.action == "done":
            self._maintenance_active = False
            self._maintenance_started = False
            self._set_status(
                "Maintenance complete."
                if choice is not None and choice.action == "done"
                else "Maintenance stopped. Completed work is saved."
            )
            return
        if choice.action == "start":
            self._maintenance_started = True
            self._show_maintenance()
            return
        if choice.action == "optional":
            self._maintenance_active = False
            self._maintenance_started = False
            self._open_issues()
            return
        issue = choice.issue
        if issue is None:
            return
        if choice.action == "skip":
            self._maintenance_skipped.add(issue.track.reference)
            self._maintenance_last_message = f"Skipped {issue.track.title} for later."
            self._show_maintenance()
            return
        self._issue_action_selected(
            LibraryIssueChoice(issue.track.reference, issue.action)
        )

    def _open_more(self) -> None:
        self.app.push_screen(LibraryMoreDialog(), self._more_selected)

    def _more_selected(self, key: str | None) -> None:
        if key is None:
            return
        if key == "a": self._open_issues()
        elif key == "d": self._open_duplicates()
        elif key == "g": self._open_missing_library()
        elif key == "e" and self.selected_track is not None: self._open_metadata_audit(self.selected_track)
        elif key == "v":
            self._snapshot_action = "verify"
            self.refresh_snapshot(identify=False)
        elif key == "b": self._open_backups()
        elif key == "p": self._check_rmpc()
        elif key == "i": self._preview_identity_rebuild()
        elif key == "l": self.generate_preview(action="maintain")
        elif key == "u": self._unlock_manual_match()

    @work(thread=True, exclusive=True, group="library-snapshot", exit_on_error=False)
    def _load_snapshot(self) -> SnapshotOutcome:
        try:
            return SnapshotOutcome(self._snapshot_provider(self.settings))
        except Exception as exc:
            return SnapshotOutcome(error=str(exc) or type(exc).__name__)

    def generate_preview(self, *, action: str = "preview", selected_path: Path | None = None) -> None:
        if self.snapshot is None:
            self._set_status("Load the library before generating a sync preview.", error=True)
            return
        self._preview_action = action
        self.query_one("#library-preview", Static).update("Checking library needs… · No files are being changed")
        self._preview_worker = self._load_preview(selected_path)

    @work(thread=True, exclusive=True, group="library-preview", exit_on_error=False)
    def _load_preview(self, selected_path: Path | None = None) -> PreviewOutcome:
        try:
            if selected_path is None:
                if self._preview_action != "maintain" or self.snapshot is None:
                    return PreviewOutcome(self._preview_provider(self.settings))
                protected_paths = tuple(
                    track.path
                    for track in self.snapshot.tracks
                    if track.fully_covered
                    and track.match_status is LibraryMatchStatus.UNMATCHED
                )
                return PreviewOutcome(
                    self._preview_provider(
                        self.settings,
                        protected_paths=protected_paths,
                    )
                )
            return PreviewOutcome(
                self._preview_provider(
                    self.settings,
                    refresh=True,
                    selected_paths=(selected_path,),
                )
            )
        except Exception as exc:
            return PreviewOutcome(error=str(exc) or type(exc).__name__)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._index_sync_worker:
            if event.state is WorkerState.SUCCESS:
                if self._can_render():
                    self._apply_index_sync(event.worker.result)
                else:
                    self._pending_index_sync = event.worker.result
            elif event.state is WorkerState.ERROR:
                self._index_sync_worker = None
                self._set_status("Library Sync stopped safely. Please try again.", error=True)
        elif event.worker is self._snapshot_worker:
            if event.state is WorkerState.SUCCESS:
                outcome = event.worker.result
                if self._can_render():
                    self._apply_snapshot(outcome)
                else:
                    self._pending_snapshot = outcome
            elif event.state is WorkerState.ERROR:
                outcome = SnapshotOutcome(error="Library scan stopped unexpectedly")
                if self._can_render():
                    self._apply_snapshot(outcome)
                else:
                    self._pending_snapshot = outcome
        elif event.worker is self._identity_worker:
            if event.state is WorkerState.SUCCESS:
                outcome = event.worker.result
                if self._can_render():
                    self._apply_identity(outcome)
                else:
                    self._pending_identity = outcome
            elif event.state is WorkerState.ERROR:
                outcome = IdentityOutcome(error="Catalogue identification stopped unexpectedly")
                if self._can_render():
                    self._apply_identity(outcome)
                else:
                    self._pending_identity = outcome
        elif event.worker is self._identity_rebuild_plan_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_identity_rebuild_plan(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._apply_identity_rebuild_plan(
                    IdentityRebuildPlanOutcome(error="Catalogue rebuild preview stopped unexpectedly")
                )
        elif event.worker is self._identity_rebuild_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_identity_rebuild(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._apply_identity_rebuild(
                    IdentityRebuildOutcome(error="Catalogue rebuild stopped unexpectedly")
                )
        elif event.worker is self._manual_identity_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_manual_identity(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._apply_manual_identity(
                    ManualIdentityOutcome(error="Catalogue match update stopped safely.")
                )
        elif event.worker is self._metadata_audit_worker:
            if event.state is WorkerState.SUCCESS:
                outcome = event.worker.result
                if self._can_render():
                    self._apply_metadata_audit(outcome)
                else:
                    self._pending_metadata_audit = outcome
            elif event.state is WorkerState.ERROR:
                self._apply_metadata_audit(
                    MetadataAuditOutcome("", error="Metadata preview stopped safely.")
                )
        elif event.worker is self._metadata_repair_plan_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_metadata_repair_plan(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._apply_metadata_repair_plan(
                    MetadataRepairPlanOutcome(error="Metadata repair planning stopped safely.")
                )
        elif event.worker is self._metadata_repair_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_metadata_repair(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._apply_metadata_repair(
                    MetadataRepairOutcome(error="Metadata repair stopped safely.")
                )
        elif event.worker is self._preview_worker:
            if event.state is WorkerState.SUCCESS:
                outcome = event.worker.result
                if self._can_render():
                    self._apply_preview(outcome)
                else:
                    self._pending_preview = outcome
            elif event.state is WorkerState.ERROR:
                outcome = PreviewOutcome(error="Maintenance preview stopped unexpectedly")
                if self._can_render():
                    self._apply_preview(outcome)
                else:
                    self._pending_preview = outcome
        elif event.worker is self._execution_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_execution(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._apply_execution(ExecutionOutcome(error="Library maintenance stopped unexpectedly."))
        elif event.worker is self._backup_worker:
            if event.state is WorkerState.SUCCESS:
                self._apply_backups(event.worker.result)
            elif event.state is WorkerState.ERROR:
                self._apply_backups(BackupOutcome(error="Backups could not be inspected."))
        elif event.worker is self._restore_worker:
            if event.state is WorkerState.SUCCESS:
                count, error = event.worker.result
                self._apply_restore(count, error)
            elif event.state is WorkerState.ERROR:
                self._apply_restore(None, "Restore stopped unexpectedly.")
        elif event.worker is self._rmpc_worker and event.state is WorkerState.SUCCESS:
            snapshot, error = event.worker.result
            self._rmpc_worker = None
            if error or snapshot is None: self._set_status(f"rmpc check failed: {error or 'Unknown error'}", error=True)
            else: self.app.push_screen(RmpcDialog(snapshot), self._rmpc_dialog_closed)
        elif event.worker is self._rmpc_worker and event.state is WorkerState.ERROR:
            self._rmpc_worker = None
            self._set_status("rmpc check stopped unexpectedly.", error=True)
        elif event.worker is self._rmpc_setup_worker and event.state is WorkerState.SUCCESS:
            path, error = event.worker.result
            self._rmpc_setup_worker = None
            self._set_status(f"rmpc setup failed safely: {error}", error=True) if error else self._set_status(f"rmpc setup complete · previous config backed up at {path}")
        elif event.worker is self._rmpc_setup_worker and event.state is WorkerState.ERROR:
            self._rmpc_setup_worker = None
            self._set_status("rmpc setup stopped safely.", error=True)

    def _can_render(self) -> bool:
        if not self.is_mounted or not list(self.query("#library-summary")):
            return False
        try:
            return self.app.screen is self
        except Exception:
            return False

    def _apply_snapshot(self, outcome: SnapshotOutcome) -> None:
        if outcome.error or outcome.snapshot is None:
            self._set_status(f"Library unavailable: {outcome.error or 'Unknown library error'}", error=True)
            if self.snapshot is None:
                self.filtered_tracks = ()
                self.query_one("#library-tracks-title", Static).update("Tracks · unavailable")
                self.query_one("#library-tracks", Static).update("Unable to load local tracks.")
                self.query_one("#library-details", Static).update("Track details are unavailable.")
            return

        previous_reference = self.selected_track.reference if self.selected_track else None
        self.snapshot = outcome.snapshot
        self.set_focus(None)
        self.preview = None
        self._details_mode = False
        self._details_action_index = 0
        self.remove_class("-details-mode")
        self._render_summary()
        self._apply_local_filter(preferred_reference=previous_reference)
        action, self._snapshot_action = self._snapshot_action, "scan"
        completion, self._completion_message = self._completion_message, None
        if not outcome.snapshot.directory_exists:
            self._set_status(outcome.snapshot.warnings[0], error=True)
        elif not outcome.snapshot.tracks:
            self._set_status("No supported MP3, FLAC, or M4A tracks found.")
        elif outcome.snapshot.warnings:
            self._set_status(" ".join(outcome.snapshot.warnings), error=True)
        elif completion is not None:
            self._set_status(completion[0], error=completion[1])
        elif action == "verify":
            health = get_library_health(outcome.snapshot)
            errors = sum(
                issue.severity is LibraryIssueSeverity.ERROR
                for issue in health.issues
            )
            self._set_status(
                f"Verification complete · {health.issue_count} follow-ups · "
                f"{errors} errors"
            )
            if outcome.snapshot.needs_attention_count:
                self.query_one("#library-filter", Select).value = LibraryFilter.ATTENTION.value
        else:
            self._set_status(
                f"Library refreshed · {outcome.snapshot.total_track_count} "
                f"song{'s' if outcome.snapshot.total_track_count != 1 else ''} found"
            )
        identify = self._identify_requested
        self._identify_requested = False
        if identify and outcome.snapshot.unmatched_count:
            unknown = tuple(
                track
                for track in outcome.snapshot.tracks
                if track.match_status is LibraryMatchStatus.UNMATCHED
            )
            self._set_status(
                f"Library refreshed · {outcome.snapshot.total_track_count} "
                f"song{'s' if outcome.snapshot.total_track_count != 1 else ''} found · "
                f"Identifying {len(unknown)} catalogue entr{'y' if len(unknown) == 1 else 'ies'}…"
            )
            self._identity_worker = self._identify_unknown(unknown)
        elif self._maintenance_active:
            callback = (
                self._offer_lyrics_after_match
                if self._maintenance_lyrics_offer_reference is not None
                else self._show_maintenance
            )
            self.call_after_refresh(callback)

    @work(thread=True, exclusive=True, group="library-identity", exit_on_error=False)
    def _identify_unknown(self, tracks: tuple[LibraryTrack, ...]) -> IdentityOutcome:
        try:
            return IdentityOutcome(self._identity_provider(self.settings, tracks))
        except Exception as exc:
            return IdentityOutcome(error=str(exc) or type(exc).__name__)

    def _apply_identity(self, outcome: IdentityOutcome) -> None:
        self._identity_worker = None
        snapshot = self.snapshot
        if outcome.error or outcome.result is None:
            self._set_status(
                "Catalogue identification unavailable · Local library health is still available",
                error=True,
            )
            if self._maintenance_active:
                self.call_after_refresh(self._show_maintenance)
            return
        result = outcome.result
        if result.identified:
            message = (
                f"Catalogue identification complete · {result.identified} "
                f"song{'s' if result.identified != 1 else ''} identified"
            )
            remaining = result.unknown + result.failed
            if remaining:
                message += f" · {remaining} remain unknown"
            self._completion_message = (message, bool(result.failed))
            self.refresh_snapshot(identify=False)
            return
        count = snapshot.total_track_count if snapshot is not None else result.inspected
        if result.failed:
            self._set_status(
                f"Library refreshed · {count} song{'s' if count != 1 else ''} found · "
                "Catalogue identification unavailable",
                error=True,
            )
        else:
            self._set_status(
                f"Library refreshed · {count} song{'s' if count != 1 else ''} found · "
                f"{result.unknown} catalogue match{'es' if result.unknown != 1 else ''} remain unknown"
            )
        if self._maintenance_active:
            self.call_after_refresh(self._show_maintenance)

    def _apply_preview(self, outcome: PreviewOutcome) -> None:
        if outcome.error or outcome.plan is None:
            self.preview = None
            self.query_one("#library-preview", Static).update(
                f"Preview failed: {outcome.error or 'Unknown preview error'} · Preview only — no files changed"
            )
            self._set_status("Maintenance preview unavailable.", error=True)
            self._render_details()
            if self._maintenance_active:
                self._maintenance_last_message = "Lyrics could not be checked. No files were changed."
                self.call_after_refresh(self._show_maintenance)
            return
        self.preview = outcome.plan
        plan = outcome.plan
        unavailable_locks = {
            item.path
            for item in plan.tracks
            if item.identity_locked
            and item.error
            and "manually selected catalogue recording is unavailable"
            in item.error.casefold()
        }
        if unavailable_locks and self.snapshot is not None:
            marker = "The manually selected catalogue recording is unavailable."
            self.snapshot = replace(
                self.snapshot,
                tracks=tuple(
                    replace(
                        track,
                        warning=(
                            f"{track.warning} {marker}" if track.warning else marker
                        ),
                    )
                    if track.path in unavailable_locks
                    and marker.casefold() not in (track.warning or "").casefold()
                    else track
                    for track in self.snapshot.tracks
                ),
            )
            self._render_summary()
            self._apply_local_filter(preferred_reference=self.selected_track.reference if self.selected_track else None)
        lrc = plan.synced_files if plan.options.rmpc_enabled else 0
        lrc_destination = " · LRC beside each song" if lrc else ""
        self.query_one("#library-preview", Static).update(
            f"Preview only — no files changed · Current {plan.unchanged_files} · Update {plan.ready_files} "
            f"(Synced {plan.synced_files}, Plain {plan.plain_files}) · LRC {lrc} · "
            f"Unresolved {plan.unresolved_files} · No lyrics {plan.no_lyrics_files} · Errors {plan.analysis_failures}"
            f"{lrc_destination}"
        )
        self._set_status("Maintenance preview ready. No files were changed.")
        self._render_details()
        action, self._preview_action = self._preview_action, None
        if action in {"maintain", "selected"} and self.app.screen is self:
            if self._maintenance_active and action == "selected" and not plan.ready_files:
                if self._maintenance_current_reference:
                    self._maintenance_skipped.add(self._maintenance_current_reference)
                result_message = (
                    "No lyrics were found. The song was left unchanged."
                    if plan.no_lyrics_files or plan.unresolved_files else
                    "This song is already up to date."
                )
                self._maintenance_last_message = "\n".join(
                    message for message in (self._maintenance_last_message, result_message)
                    if message
                )
                self.call_after_refresh(self._show_maintenance)
                return
            if plan.ready_files or plan.unresolved_files or plan.no_lyrics_files or plan.analysis_failures:
                message = self._maintenance_last_message if self._maintenance_active else None
                if self._maintenance_active:
                    self._maintenance_last_message = None
                self.app.push_screen(
                    MaintenanceDialog(
                        plan,
                        lyrics_offer=self._maintenance_active and action == "selected",
                        message=message,
                    ),
                    self._maintenance_dialog_closed,
                )
            else:
                self._set_status("Your library is up to date." if action == "maintain" else "This song is up to date.")

    @property
    def selected_track(self) -> LibraryTrack | None:
        if not self.filtered_tracks:
            return None
        return self.filtered_tracks[self.selected_index]

    def _render_summary(self) -> None:
        snapshot = self.snapshot
        if snapshot is None:
            return
        health = get_library_health(snapshot)
        errors = sum(
            issue.severity is LibraryIssueSeverity.ERROR for issue in health.issues
        )
        needs_input = sum(
            issue.severity is LibraryIssueSeverity.ERROR
            or LibraryIssueCategory.CATALOGUE in issue.categories
            for issue in health.issues
        )
        optional = max(0, health.issue_count - needs_input)
        ready = max(0, snapshot.total_track_count - health.issue_count)
        song_word = "song" if snapshot.total_track_count == 1 else "songs"
        self.query_one("#library-summary", Static).update(
            f"{snapshot.total_track_count} {song_word} · {ready} ready · "
            f"{needs_input} need your input · {optional} optional · {errors} errors\n"
            f"MP3 {snapshot.format_count('MP3')} · "
            f"FLAC {snapshot.format_count('FLAC')} · M4A {snapshot.format_count('M4A')}"
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.set_focus(None)
        self._apply_local_filter()

    def on_select_changed(self, event: Select.Changed) -> None:
        self._apply_local_filter()

    def _apply_local_filter(self, *, preferred_reference: str | None = None) -> None:
        if self.snapshot is None:
            return
        current_reference = preferred_reference or (self.selected_track.reference if self.selected_track else None)
        query = self.query_one("#library-query", Input).value.strip().casefold()
        raw_filter = self.query_one("#library-filter", Select).value
        selected_filter = LibraryFilter(str(raw_filter)) if raw_filter is not Select.BLANK else LibraryFilter.ALL
        tracks = tuple(
            track for track in self.snapshot.tracks
            if _matches_filter(track, selected_filter)
            and (not query or query in track.title.casefold() or query in track.filename.casefold())
        )
        self.filtered_tracks = tracks
        self.selected_index = next(
            (index for index, track in enumerate(tracks) if track.reference == current_reference),
            0,
        )
        self._render_tracks()
        self._render_details()
        self._update_position()
        self.query_one("#library-tracks-scroll", VerticalScroll).scroll_home(animate=False, immediate=True)
        if tracks:
            self.call_after_refresh(self._scroll_selection_into_view)

    def _render_tracks(self) -> None:
        self.query_one("#library-tracks-title", Static).update(
            f"Tracks · {len(self.filtered_tracks)} of "
            f"{self.snapshot.total_track_count if self.snapshot else 0} · ! error · ~ follow-up"
        )
        if not self.filtered_tracks:
            message = "No tracks match the local search or filter." if self.snapshot and self.snapshot.tracks else "No supported audio tracks found."
            self.query_one("#library-tracks", Static).update(message)
            return
        lines = []
        issues_by_reference = {
            issue.track.reference: issue
            for issue in get_library_health(self.snapshot).issues
        } if self.snapshot is not None else {}
        for index, track in enumerate(self.filtered_tracks):
            marker = ">" if index == self.selected_index else " "
            issue = issues_by_reference.get(track.reference)
            attention = (
                "!"
                if issue is not None and issue.severity is LibraryIssueSeverity.ERROR
                else "~" if issue is not None else " "
            )
            lines.append(
                f"{marker}{attention} {track.title[:30]:30} · {_match_label(track):9} · "
                f"{_lyric_label(track.lyric_status):13} · LRC {_lrc_label(track.lrc_status)}"
            )
        self.query_one("#library-tracks", Static).update(
            Text("\n".join(lines), no_wrap=True, overflow="ellipsis")
        )

    def _render_details(self) -> None:
        track = self.selected_track
        details = self.query_one("#library-details", Static)
        self.query_one("#library-details-scroll", VerticalScroll).scroll_home(animate=False, immediate=True)
        if track is None:
            details.update("No track selected.")
            return
        issue = next(
            (
                item
                for item in get_library_health(self.snapshot).issues
                if item.track.reference == track.reference
            ),
            None,
        ) if self.snapshot is not None else None
        lines = [
            track.title,
            "",
            f"Filename       {track.filename}",
            f"Format         {track.media_format}",
            f"Artist         {track.artist or 'Not available'}",
            f"Album          {track.album or 'Not available'}",
            f"Relative path  {track.relative_path}",
            f"Full path      {track.path}",
            f"Duration       {_duration(track.duration_seconds)}",
            f"Coverage       {'Fully covered' if track.fully_covered else _coverage_label(track)}",
            "",
            "Catalogue",
            f"  {'✓ Matched · ' + (track.matched_title or _match_label(track)) if track.match_status is LibraryMatchStatus.MATCHED else '? Needs your choice'}",
            f"  {'>' if self._details_mode and self._details_action_index == 0 else ' '} [Change Match]",
            "",
            "Lyrics",
            f"  {'✓ ' + _lyric_label(track.lyric_status) if track.lyric_status is not LibraryLyricStatus.NONE else '✗ Missing lyrics'}",
            (
                f"  {'>' if self._details_mode and self._details_action_index == 1 else ' '} "
                + ("[View / Replace Lyrics]" if track.lyric_status is not LibraryLyricStatus.NONE else "[Add Lyrics]")
            ),
            "",
            "Metadata",
            f"  {'~ Review available' if issue is not None and LibraryIssueCategory.METADATA in issue.categories else '✓ Good'}",
            f"  {'>' if self._details_mode and self._details_action_index == 2 else ' '} [Review Metadata]",
        ]
        if track.lrc_status is not LibraryLrcStatus.MISSING or track.lrc_path:
            lines.append(f"Lyrics source  {_lrc_label(track.lrc_status)} · {track.lrc_path or 'embedded'}")
        if track.warning:
            lines.extend(("", f"Warning        {track.warning}"))
        if track.match_status is LibraryMatchStatus.UNMATCHED:
            lines.extend(("", "Use Change Match to choose the correct recording, or leave it unresolved."))
        lines.extend((
            "",
            f"  {'>' if self._details_mode and self._details_action_index == 3 else ' '} [More / Advanced]",
        ))
        if self.preview is not None:
            lines.extend(("", "Preview · no changes until confirmed", _track_preview_text(self.preview, track.path)))
        details.update(Text("\n".join(lines), overflow="ellipsis"))

    def _update_position(self) -> None:
        if not self.filtered_tracks:
            self.query_one("#library-position", Static).update("/ Search · f Search Lyrics · r Refresh Library · m Maintenance · x More · ? Help")
            return
        suffix = "↑↓ Choose · Enter Open · Esc Back · ? Help" if self._details_mode else "/ Search · f Search Lyrics · r Refresh Library · m Maintenance · x More · ↑↓ Move · Enter Open Song · ? Help"
        self.query_one("#library-position", Static).update(
            f"Track {self.selected_index + 1} of {len(self.filtered_tracks)} · {suffix}"
        )

    def on_key(self, event: Key) -> None:
        if any(select.expanded for select in self.query(Select)):
            return
        if isinstance(self.app.focused, Select) or (
            isinstance(self.app.focused, Input)
            and not (isinstance(self.app.focused, LibraryInput) and not self.app.focused.value)
        ):
            return
        if event.key in {"r", "s"}:
            self.sync_library()
        elif event.key == "m" and not self._details_mode:
            self._open_maintenance()
        elif event.key == "x":
            self._open_more()
        elif event.key == "f":
            self._open_lyrics_search()
        elif event.key == "a" and self._details_mode and self.selected_track is not None:
            self.generate_preview(action="selected", selected_path=self.selected_track.path)
        elif event.key == "a":
            self._open_issues()
        elif event.key == "d":
            self._open_duplicates()
        elif event.key == "g":
            self._open_missing_library()
        elif event.key == "e" and self.selected_track is not None:
            self._open_metadata_audit(self.selected_track)
        elif event.key == "m":
            self.generate_preview(action="maintain")
        elif event.key == "v":
            self._snapshot_action = "verify"
            self.refresh_snapshot()
        elif event.key == "b":
            self._open_backups()
        elif event.key == "p":
            self._check_rmpc()
        elif event.key == "i":
            self._preview_identity_rebuild()
        elif event.key == "c" and self.selected_track is not None:
            self._change_match()
        elif event.key == "u" and self.selected_track is not None:
            self._unlock_manual_match()
        elif event.key == "l" and self.selected_track is not None:
            self.generate_preview(action="selected", selected_path=self.selected_track.path)
        elif event.key == "escape" and self._details_mode:
            self._details_mode = False
            self.remove_class("-details-mode")
            self._render_details()
            self._update_position()
        elif event.key in ("down", "j") and self._details_mode:
            self._details_action_index = min(3, self._details_action_index + 1)
            self._render_details()
        elif event.key in ("up", "k") and self._details_mode:
            self._details_action_index = max(0, self._details_action_index - 1)
            self._render_details()
        elif event.key == "enter" and self._details_mode and self.selected_track is not None:
            if self._details_action_index == 0:
                self._change_match()
            elif self._details_action_index == 1:
                self.generate_preview(action="selected", selected_path=self.selected_track.path)
            elif self._details_action_index == 2:
                self._open_metadata_audit(self.selected_track)
            else:
                self._open_more()
        elif event.key == "enter" and self.selected_track is not None:
            self._details_mode = True
            self._details_action_index = 0
            self.add_class("-details-mode")
            self.query_one("#library-details-scroll", VerticalScroll).scroll_home(animate=False, immediate=True)
            self._render_details()
            self._update_position()
        elif event.key in ("down", "j"):
            self._select_track(self.selected_index + 1)
        elif event.key in ("up", "k"):
            self._select_track(self.selected_index - 1)
        elif event.key == "home":
            self._select_track(0)
        elif event.key == "end":
            self._select_track(len(self.filtered_tracks) - 1)
        elif event.key in ("pagedown", "pageup") and self._details_mode:
            scroll = self.query_one("#library-details-scroll", VerticalScroll)
            (scroll.scroll_page_down if event.key == "pagedown" else scroll.scroll_page_up)(animate=False)
        elif event.key in ("pagedown", "pageup"):
            scroll = self.query_one("#library-tracks-scroll", VerticalScroll)
            step = max(1, scroll.size.height - 1)
            self._select_track(self.selected_index + (step if event.key == "pagedown" else -step))
        else:
            return
        event.prevent_default()
        event.stop()

    def _open_lyrics_search(self) -> None:
        if self.snapshot is None:
            self._set_status("Load the library before searching lyrics.", error=True)
            return
        self.app.push_screen(
            LyricsSearchDialog(
                self.settings,
                self.snapshot,
                index_provider=self._lyrics_search_provider,
            ),
            self._lyrics_search_closed,
        )

    def _lyrics_search_closed(self, reference: str | None) -> None:
        if reference is None:
            self._set_status("Lyrics Search closed. No files were changed.")
            return
        self.query_one("#library-query", Input).value = ""
        self.query_one("#library-filter", Select).value = LibraryFilter.ALL.value
        self._apply_local_filter(preferred_reference=reference)
        if self.selected_track is None or self.selected_track.reference != reference:
            self._set_status("That track is no longer in the current Library view.", error=True)
            return
        self._details_mode = True
        self.add_class("-details-mode")
        self._render_details()
        self._update_position()
        self._set_status(f"Opened {self.selected_track.title} from Lyrics Search.")

    def _open_issues(self) -> None:
        if self.snapshot is None:
            self._set_status("Load the library before viewing Issues.", error=True)
            return
        self.app.push_screen(
            LibraryIssuesDialog(get_library_health(self.snapshot)),
            self._issue_action_selected,
        )

    def _open_duplicates(self) -> None:
        if self.snapshot is None:
            self._set_status("Load the library before viewing duplicates.", error=True)
            return
        self.app.push_screen(
            LibraryDuplicatesDialog(
                detect_library_duplicates(
                    self.snapshot,
                    duration_tolerance=self.settings.duration_tolerance,
                )
            )
        )

    def _open_missing_library(self) -> None:
        if self.snapshot is None:
            self._set_status("Load the library before checking Missing Library.", error=True)
            return
        self.app.push_screen(
            MissingLibraryDialog(
                self.settings,
                self.snapshot,
                report_provider=self._missing_library_provider,
                queue_plan_provider=self._queue_plan_provider,
                queue_add_provider=self._queue_add_provider,
            )
        )

    def _issue_action_selected(self, choice: LibraryIssueChoice | None) -> None:
        if choice is None:
            if self._maintenance_active:
                self._maintenance_active = False
                self._set_status("Maintenance stopped. Completed work is saved.")
            else:
                self._set_status("Issues closed. No files were changed.")
            return
        track = next(
            (
                item
                for item in self.snapshot.tracks
                if item.reference == choice.reference
            ),
            None,
        ) if self.snapshot is not None else None
        if choice.action is LibraryIssueAction.SYNC:
            self.sync_library()
        elif choice.action is LibraryIssueAction.VERIFY:
            self._snapshot_action = "verify"
            self.refresh_snapshot(identify=False)
        elif track is None:
            self._set_status("That track is no longer in the current Library view.", error=True)
        elif choice.action is LibraryIssueAction.MANUAL_MATCH:
            self._change_match(track)
        elif choice.action is LibraryIssueAction.REFRESH_LYRICS:
            self.generate_preview(action="selected", selected_path=track.path)
        elif choice.action is LibraryIssueAction.METADATA_AUDIT:
            self._open_metadata_audit(track)

    def _metadata_cache_key(self, track: LibraryTrack) -> tuple[str, str | None, str]:
        return track.reference, track.content_sha256, str(track.catalogue_id)

    def _open_metadata_audit(self, track: LibraryTrack) -> None:
        if (
            self._metadata_repair_plan_worker is not None
            and not self._metadata_repair_plan_worker.is_finished
        ) or (
            self._metadata_repair_worker is not None
            and not self._metadata_repair_worker.is_finished
        ):
            self._set_status("A metadata repair is already running.")
            return
        if self._metadata_audit_worker is not None and not self._metadata_audit_worker.is_finished:
            self._set_status("A metadata preview is already being prepared.")
            return
        cached = self._metadata_audit_cache.get(self._metadata_cache_key(track))
        if cached is not None:
            self._show_metadata_audit(cached)
            return
        self._set_status("Preparing metadata repair preview… · No files are being changed")
        self._metadata_audit_worker = self._load_metadata_audit(track)

    @work(thread=True, exclusive=True, group="metadata-audit", exit_on_error=False)
    def _load_metadata_audit(self, track: LibraryTrack) -> MetadataAuditOutcome:
        try:
            return MetadataAuditOutcome(
                track.reference,
                self._metadata_audit_provider(
                    self.settings,
                    track,
                    details_provider=self._catalogue_details_provider,
                ),
            )
        except Exception as exc:
            return MetadataAuditOutcome(
                track.reference,
                error=str(exc) or type(exc).__name__,
            )

    def _apply_metadata_audit(self, outcome: MetadataAuditOutcome) -> None:
        self._metadata_audit_worker = None
        track = next(
            (item for item in self.snapshot.tracks if item.reference == outcome.reference),
            None,
        ) if self.snapshot is not None else None
        if outcome.error or outcome.audit is None:
            self._set_status(
                f"Metadata preview unavailable: {outcome.error or 'Unknown error'}",
                error=True,
            )
            return
        if track is None or self._metadata_cache_key(track) != self._metadata_cache_key(outcome.audit.track):
            self._set_status("The selected track changed; refresh and preview it again.", error=True)
            return
        self._metadata_audit_cache[self._metadata_cache_key(track)] = outcome.audit
        self._set_status("Metadata repair preview ready · No files were changed")
        self._show_metadata_audit(outcome.audit)

    def _show_metadata_audit(self, audit: MetadataAudit) -> None:
        self.app.push_screen(
            MetadataAuditDialog(audit),
            lambda fields: self._metadata_selection_closed(audit, fields),
        )

    def _metadata_selection_closed(
        self, audit: MetadataAudit, fields: tuple[str, ...] | None
    ) -> None:
        if fields is None:
            self._set_status("Metadata repair cancelled. No files were changed.")
            return
        if not fields:
            self._set_status("Select at least one metadata field.", error=True)
            return
        if (
            self._metadata_repair_plan_worker is not None
            and not self._metadata_repair_plan_worker.is_finished
        ) or (
            self._metadata_repair_worker is not None
            and not self._metadata_repair_worker.is_finished
        ):
            self._set_status("A metadata repair is already running.")
            return
        self._set_status("Checking selected metadata fields… · No files are being changed")
        self._metadata_repair_plan_worker = self._plan_metadata_repair(audit, fields)

    @work(thread=True, exclusive=True, group="metadata-repair-plan", exit_on_error=False)
    def _plan_metadata_repair(
        self, audit: MetadataAudit, fields: tuple[str, ...]
    ) -> MetadataRepairPlanOutcome:
        try:
            return MetadataRepairPlanOutcome(
                self._metadata_repair_plan_provider(self.settings, audit, fields)
            )
        except Exception as exc:
            return MetadataRepairPlanOutcome(error=str(exc) or type(exc).__name__)

    def _apply_metadata_repair_plan(self, outcome: MetadataRepairPlanOutcome) -> None:
        self._metadata_repair_plan_worker = None
        if outcome.error or outcome.plan is None:
            self._set_status(
                f"Metadata repair unavailable: {outcome.error or 'Unknown error'}",
                error=True,
            )
            return
        self._set_status("Metadata repair ready for confirmation · No files were changed")
        self.app.push_screen(
            MetadataRepairConfirmationDialog(outcome.plan),
            lambda confirmed: self._metadata_repair_confirmation_closed(
                outcome.plan, confirmed
            ),
        )

    def _metadata_repair_confirmation_closed(
        self, plan: MetadataRepairPlan, confirmed: bool
    ) -> None:
        if not confirmed:
            self._set_status("Metadata repair cancelled. No files were changed.")
            return
        if self._metadata_repair_worker is not None and not self._metadata_repair_worker.is_finished:
            self._set_status("A metadata repair is already running.")
            return
        self._set_status("Applying metadata repair… · 0 / 1 · Creating a backup first")
        self._metadata_repair_worker = self._execute_metadata_repair(plan)

    @work(thread=True, exclusive=True, group="metadata-repair-apply", exit_on_error=False)
    def _execute_metadata_repair(
        self, plan: MetadataRepairPlan
    ) -> MetadataRepairOutcome:
        try:
            return MetadataRepairOutcome(
                self._metadata_repair_execution_provider(plan, confirmed=True)
            )
        except BaseException as exc:
            return MetadataRepairOutcome(error=str(exc) or type(exc).__name__)

    def _apply_metadata_repair(self, outcome: MetadataRepairOutcome) -> None:
        self._metadata_repair_worker = None
        if outcome.error or outcome.result is None:
            message = outcome.error or "Unknown error"
            if "rollback failed" in message.casefold():
                self._set_status(
                    f"Metadata repair needs recovery: {message} · The backup was retained",
                    error=True,
                )
            else:
                self._set_status(
                    f"Metadata repair failed safely: {message} · Existing data was preserved or restored",
                    error=True,
                )
            return
        result = outcome.result
        fields = ", ".join(result.fields)
        self._metadata_audit_cache.clear()
        self._completion_message = (
            f"Metadata repaired · {fields} · Backup: {result.backup_path}",
            False,
        )
        self._set_status("Metadata repair complete · Refreshing Library health…")
        self.refresh_snapshot(identify=False)

    def _open_manual_match(self, track: LibraryTrack | None = None) -> None:
        track = track or self.selected_track
        if track is None or (
            self._manual_identity_worker is not None
            and not self._manual_identity_worker.is_finished
        ):
            return
        self._manual_track = track
        self.app.push_screen(
            ManualMatchDialog(self.settings, track, self._manual_search_provider),
            self._manual_match_closed,
        )

    def _change_match(self, track: LibraryTrack | None = None) -> None:
        track = track or self.selected_track
        if track is None:
            return
        if track.identity_locked:
            self.app.push_screen(
                ChangeMatchConfirmation(track.title),
                lambda confirmed: self._open_manual_match(track) if confirmed else None,
            )
        else:
            self._open_manual_match(track)

    def _manual_match_closed(self, choice: ManualMatchChoice | None) -> None:
        track, self._manual_track = self._manual_track, None
        if choice is None:
            self._set_status("Manual catalogue matching cancelled. No changes were made.")
            if self._maintenance_active:
                self.call_after_refresh(self._show_maintenance)
            return
        if track is None:
            self._set_status("The selected track is no longer available.", error=True)
            return
        self._set_status("Saving manual catalogue match…")
        self._manual_identity_worker = self._save_manual_identity(track, choice)

    def _unlock_manual_match(self) -> None:
        track = self.selected_track
        if track is None:
            return
        if not track.identity_locked:
            self._set_status("This track does not have a manual catalogue lock.")
            return
        if self._manual_identity_worker is not None and not self._manual_identity_worker.is_finished:
            return
        self._set_status("Unlocking catalogue match…")
        self._manual_identity_worker = self._unlock_identity(track)

    @work(thread=True, exclusive=True, group="manual-identity-write", exit_on_error=False)
    def _save_manual_identity(
        self,
        track: LibraryTrack,
        choice: ManualMatchChoice,
    ) -> ManualIdentityOutcome:
        try:
            return ManualIdentityOutcome(
                self._manual_identity_provider(
                    self.settings,
                    track,
                    song_id=choice.song_id,
                    api_name=choice.api_name,
                ),
                action="match",
            )
        except Exception as exc:
            return ManualIdentityOutcome(error=str(exc) or type(exc).__name__, action="match")

    @work(thread=True, exclusive=True, group="manual-identity-write", exit_on_error=False)
    def _unlock_identity(self, track: LibraryTrack) -> ManualIdentityOutcome:
        try:
            return ManualIdentityOutcome(
                self._manual_unlock_provider(self.settings, track),
                action="unlock",
            )
        except Exception as exc:
            return ManualIdentityOutcome(error=str(exc) or type(exc).__name__, action="unlock")

    def _apply_manual_identity(self, outcome: ManualIdentityOutcome) -> None:
        self._manual_identity_worker = None
        if outcome.error or outcome.result is None:
            self._set_status(
                f"Catalogue match was not changed: {outcome.error or 'Unknown error'}",
                error=True,
            )
            return
        if outcome.action == "unlock":
            message = "Manual catalogue match unlocked and cleared · Sync Library may identify it again"
        else:
            message = f"Manual catalogue match saved and locked · {outcome.result.api_name}"
            if self._maintenance_active:
                self._maintenance_matched += 1
                self._maintenance_last_message = "✓ Match saved"
                self._maintenance_lyrics_offer_reference = outcome.result.reference
        self._completion_message = (message, False)
        self.refresh_snapshot(identify=False)

    def _select_track(self, index: int) -> None:
        if not self.filtered_tracks:
            return
        self.selected_index = max(0, min(len(self.filtered_tracks) - 1, index))
        self._render_tracks()
        self._render_details()
        self._update_position()
        self.call_after_refresh(self._scroll_selection_into_view)

    def _scroll_selection_into_view(self) -> None:
        if not self.filtered_tracks:
            return
        scroll = self.query_one("#library-tracks-scroll", VerticalScroll)
        scroll.scroll_to_region(
            Region(0, self.selected_index, max(1, scroll.virtual_size.width), 1),
            animate=False,
            immediate=True,
            x_axis=False,
        )

    def _set_status(self, message: str, *, error: bool = False) -> None:
        status = self.query_one("#library-status", Static)
        status.update(message)
        status.set_class(error, "-error")

    def _maintenance_dialog_closed(self, plan: LibrarySyncPlan | None) -> None:
        if plan is None:
            self._set_status("Library maintenance cancelled. No files were changed.")
            if self._maintenance_active:
                self.call_after_refresh(self._show_maintenance)
            return
        if self._execution_worker is not None:
            return
        self._maintenance_completed = 0
        self._maintenance_total = plan.ready_files
        self._set_status(f"Maintaining library… 0 / {plan.ready_files} songs")
        self._execution_worker = self._execute_maintenance(plan)

    def _preview_identity_rebuild(self) -> None:
        if self._identity_rebuild_plan_worker is not None or self._identity_rebuild_worker is not None:
            return
        self._set_status("Preparing catalogue rebuild preview…")
        self._identity_rebuild_plan_worker = self._load_identity_rebuild_plan()

    @work(thread=True, exclusive=True, group="library-identity-rebuild-plan", exit_on_error=False)
    def _load_identity_rebuild_plan(self) -> IdentityRebuildPlanOutcome:
        try:
            return IdentityRebuildPlanOutcome(self._identity_rebuild_plan_provider(self.settings))
        except Exception as exc:
            return IdentityRebuildPlanOutcome(error=str(exc) or type(exc).__name__)

    def _apply_identity_rebuild_plan(self, outcome: IdentityRebuildPlanOutcome) -> None:
        self._identity_rebuild_plan_worker = None
        if outcome.error or outcome.plan is None:
            self._set_status(
                f"Catalogue rebuild preview unavailable: {outcome.error or 'Unknown error'}",
                error=True,
            )
            return
        self.app.push_screen(IdentityRebuildDialog(outcome.plan), self._identity_rebuild_confirmed)

    def _identity_rebuild_confirmed(self, plan: IdentityRebuildPlan | None) -> None:
        if plan is None:
            self._set_status("Catalogue rebuild cancelled. No state was changed.")
            return
        if self._identity_rebuild_worker is not None:
            return
        self._identity_rebuild_completed = 0
        self._set_status(f"Rebuilding catalogue matches… 0 / {plan.current_tracks}")
        self._identity_rebuild_worker = self._execute_identity_rebuild(plan)

    @work(thread=True, exclusive=True, group="library-identity-rebuild", exit_on_error=False)
    def _execute_identity_rebuild(self, plan: IdentityRebuildPlan) -> IdentityRebuildOutcome:
        try:
            return IdentityRebuildOutcome(
                self._identity_rebuild_execution_provider(
                    plan,
                    progress=self._identity_rebuild_progress,
                )
            )
        except Exception as exc:
            return IdentityRebuildOutcome(error=str(exc) or type(exc).__name__)

    def _identity_rebuild_progress(self, event: IdentityRebuildProgress) -> None:
        self._identity_rebuild_completed = event.completed
        try:
            self.app.call_from_thread(
                self._set_status,
                f"Rebuilding catalogue matches… {event.completed} / {event.total} · {event.path.stem}",
            )
        except RuntimeError:
            pass

    def _apply_identity_rebuild(self, outcome: IdentityRebuildOutcome) -> None:
        self._identity_rebuild_worker = None
        if outcome.error or outcome.result is None:
            self._set_status(
                f"Catalogue rebuild failed safely: {outcome.error or 'Unknown error'}",
                error=True,
            )
            return
        result = outcome.result
        if result.aborted:
            self._set_status(
                f"Catalogue rebuild aborted safely · {result.abort_reason}",
                error=True,
            )
            return
        message = (
            f"Catalogue rebuild complete · {result.matched} matched · "
            f"{result.unknown} unknown · {result.changed_identities} changed"
        )
        if result.failed_preserved:
            message += f" · {result.failed_preserved} preserved after errors"
        self._completion_message = (message, bool(result.failed_preserved))
        self.snapshot = None
        self._snapshot_action = "scan"
        self.refresh_snapshot(identify=False)

    @work(thread=True, exclusive=True, group="library-maintenance", exit_on_error=False)
    def _execute_maintenance(self, plan: LibrarySyncPlan) -> ExecutionOutcome:
        try:
            return ExecutionOutcome(self._execution_provider(plan, progress=self._maintenance_progress))
        except Exception as exc:
            return ExecutionOutcome(error=str(exc) or type(exc).__name__)

    def _maintenance_progress(self, event: SyncEvent) -> None:
        if event.kind not in {SyncEventKind.TRACK_COMPLETED, SyncEventKind.TRACK_FAILED}:
            return
        self._maintenance_completed += 1
        title = event.path.stem if event.path is not None else ""
        try:
            self.app.call_from_thread(
                self._set_status,
                f"Maintaining library… {self._maintenance_completed} / {self._maintenance_total} songs · {title}",
            )
        except RuntimeError:
            pass

    def _apply_execution(self, outcome: ExecutionOutcome) -> None:
        self._execution_worker = None
        if outcome.error or outcome.result is None:
            self._set_status(f"Library maintenance failed safely: {outcome.error or 'Unknown error'}", error=True)
            return
        result = outcome.result
        remaining = result.failed_files + result.plan.unresolved_files + result.plan.no_lyrics_files
        updated_word = "song" if result.updated_files == 1 else "songs"
        message = f"Library updated · {result.updated_files} {updated_word} updated"
        if remaining:
            message += f" · {remaining} could not be updated"
        if result.warnings:
            message += f" · {result.warnings[0]}"
        self._completion_message = (message, bool(result.failed_files))
        if self._maintenance_active and result.updated_files:
            self._maintenance_lyrics_resolved += result.updated_files
            self._maintenance_last_message = "✓ Lyrics added"
        self.snapshot = None
        self.preview = None
        self._snapshot_action = "scan"
        self.refresh_snapshot(identify=False)

    def _open_backups(self) -> None:
        if self._backup_worker is None:
            self._set_status("Loading backups…")
            self._backup_worker = self._load_backups()

    @work(thread=True, exclusive=True, group="library-backups", exit_on_error=False)
    def _load_backups(self) -> BackupOutcome:
        try:
            return BackupOutcome(self._backup_provider())
        except Exception as exc:
            return BackupOutcome(error=str(exc) or type(exc).__name__)

    def _apply_backups(self, outcome: BackupOutcome) -> None:
        self._backup_worker = None
        if outcome.error:
            self._set_status(f"Backups unavailable: {outcome.error}", error=True)
            return
        self.app.push_screen(BackupBrowser(outcome.records), self._backup_selected)

    def _backup_selected(self, record: BackupRecord | None) -> None:
        self._backup_worker = None
        if record is not None:
            self.app.push_screen(RestoreDialog(record), self._restore_confirmed)

    def _restore_confirmed(self, record: BackupRecord | None) -> None:
        if record is None:
            self._set_status("Restore cancelled. No files were changed.")
            return
        self._set_status("Restoring backup…")
        self._restore_worker = self._restore(record)

    @work(thread=True, exclusive=True, group="library-restore", exit_on_error=False)
    def _restore(self, record: BackupRecord) -> tuple[int | None, str | None]:
        try:
            return self._restore_provider(record.path, Path(self.settings.music_dir)), None
        except Exception as exc:
            return None, str(exc) or type(exc).__name__

    def _apply_restore(self, count: int | None, error: str | None) -> None:
        self._restore_worker = None
        if error is not None or count is None:
            self._set_status(f"Restore failed safely: {error or 'Unknown error'}", error=True)
            return
        self._completion_message = (
            f"Restored {count} audio file{'s' if count != 1 else ''}.",
            False,
        )
        self.snapshot = None
        self._snapshot_action = "scan"
        self.refresh_snapshot(identify=False)

    def _check_rmpc(self) -> None:
        if self._rmpc_worker is None:
            self._set_status("Checking rmpc integration…")
            self._rmpc_worker = self._load_rmpc()

    @work(thread=True, exclusive=True, group="library-rmpc", exit_on_error=False)
    def _load_rmpc(self) -> tuple[SettingsSnapshot | None, str | None]:
        try: return self._rmpc_status_provider(self.settings), None
        except Exception as exc: return None, str(exc) or type(exc).__name__

    def _rmpc_dialog_closed(self, snapshot: SettingsSnapshot | None) -> None:
        self._rmpc_worker = None
        if snapshot is None:
            self._set_status("rmpc check complete. No configuration was changed.")
            return
        self._set_status("Setting up rmpc…")
        self._rmpc_setup_worker = self._setup_rmpc(snapshot)

    @work(thread=True, exclusive=True, group="library-rmpc-setup", exit_on_error=False)
    def _setup_rmpc(self, snapshot: SettingsSnapshot) -> tuple[Path | None, str | None]:
        try: return self._rmpc_setup_provider(snapshot.rmpc.config_path, Path(self.settings.music_dir)), None
        except Exception as exc: return None, str(exc) or type(exc).__name__

    def on_resize(self, event: Resize) -> None:
        super().on_resize(event)
        self.set_class(event.size.width < 110, "-library-narrow")
        self.set_class(event.size.height <= 30, "-library-compact")
        if self.filtered_tracks:
            self.call_after_refresh(self._scroll_selection_into_view)


def _matches_filter(track: LibraryTrack, selected: LibraryFilter) -> bool:
    return {
        LibraryFilter.ALL: True,
        LibraryFilter.MATCHED: track.match_status is LibraryMatchStatus.MATCHED,
        LibraryFilter.UNMATCHED: track.match_status is LibraryMatchStatus.UNMATCHED,
        LibraryFilter.SYNCED: track.lyric_status is LibraryLyricStatus.SYNCED,
        LibraryFilter.PLAIN: track.lyric_status is LibraryLyricStatus.PLAIN,
        LibraryFilter.NO_LYRICS: track.lyric_status is LibraryLyricStatus.NONE,
        LibraryFilter.ATTENTION: track.needs_attention,
    }[selected]


def _match_label(track: LibraryTrack) -> str:
    return "Matched" if track.match_status is LibraryMatchStatus.MATCHED else "Needs choice"


def _lyric_label(status: LibraryLyricStatus) -> str:
    return {
        LibraryLyricStatus.SYNCED: "Synced lyrics",
        LibraryLyricStatus.PLAIN: "Plain lyrics",
        LibraryLyricStatus.NONE: "Missing lyrics",
    }[status]


def _lrc_label(status: LibraryLrcStatus) -> str:
    return {
        LibraryLrcStatus.PRESENT: "Present",
        LibraryLrcStatus.MISSING: "Missing",
        LibraryLrcStatus.INVALID: "Invalid",
        LibraryLrcStatus.NONE: "None",
    }[status]


def _state_label(status: LibraryStateStatus) -> str:
    return {
        LibraryStateStatus.CURRENT: "Current",
        LibraryStateStatus.NEW: "New",
        LibraryStateStatus.CHANGED: "Changed",
        LibraryStateStatus.INVALID: "Invalid",
    }[status]


def _coverage_label(track: LibraryTrack) -> str:
    if track.fully_covered:
        return "Fully covered"
    if track.lyric_status is LibraryLyricStatus.NONE:
        return "No managed lyrics"
    if track.lrc_status in {LibraryLrcStatus.MISSING, LibraryLrcStatus.INVALID}:
        return "Synced LRC needs attention"
    if track.lyric_status is LibraryLyricStatus.PLAIN:
        return "Plain lyrics only"
    return "Needs attention" if track.needs_attention else "Lyrics present"


def _duration(seconds: float | None) -> str:
    if seconds is None:
        return "Unavailable"
    minutes, remainder = divmod(max(0, int(round(seconds))), 60)
    return f"{minutes}:{remainder:02d}"


def _lyrics_timestamp(milliseconds: int | None) -> str:
    if milliseconds is None:
        return ""
    minutes, remainder = divmod(max(0, milliseconds), 60_000)
    seconds = remainder // 1_000
    return f"{minutes:02d}:{seconds:02d}"


def _track_preview_text(plan: LibrarySyncPlan | None, path: Path) -> str:
    if plan is None:
        return "  Not generated. Press l for this song or m for the library."
    track = next((item for item in plan.tracks if item.path == path), None)
    if track is None:
        return "  Track was not present in the latest preview."
    outcome = {
        MatchOutcome.UNCHANGED: "Already current",
        MatchOutcome.MATCHED: "Would update lyrics",
        MatchOutcome.UNRESOLVED: "Would remain unmatched",
        MatchOutcome.NO_LYRICS: "Matched, but no lyrics are available",
        MatchOutcome.FAILED: "Preview failed",
    }[track.outcome]
    lyric = {
        SyncLyricType.SYNCED: "Synced lyrics",
        SyncLyricType.PLAIN: "Plain lyrics",
        SyncLyricType.NONE: "No lyric change",
    }[track.lyric_type]
    candidate = str((track.candidate or {}).get("name") or "").strip()
    text = f"  {outcome} · {lyric}"
    if candidate:
        text += f" · {candidate}"
    if track.lrc_path is not None:
        text += f" · LRC {track.lrc_path}"
    if track.error:
        text += f" · {track.error}"
    return text

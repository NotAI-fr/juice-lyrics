from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
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
from ...services.identity_rebuild import (
    IdentityRebuildPlan,
    IdentityRebuildProgress,
    IdentityRebuildResult,
)
from ...services.library_sync import LibrarySyncPlan, MatchOutcome, SyncLyricType
from ...services.library_sync import LibrarySyncResult, SyncEvent, SyncEventKind
from ...backup.manager import BackupRecord
from ...services.settings_snapshot import IntegrationStatus, SettingsSnapshot
from .base import HubScreen

SnapshotProvider = Callable[[Any], LibrarySnapshot]
IdentityProvider = Callable[..., IdentityBackfillResult]
IdentityRebuildPlanProvider = Callable[..., IdentityRebuildPlan]
IdentityRebuildExecutionProvider = Callable[..., IdentityRebuildResult]
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
    ("Needs attention", LibraryFilter.ATTENTION.value),
)


class LibraryInput(Input):
    """Local search input that preserves global section shortcuts."""

    def on_key(self, event: Key) -> None:
        if event.key == "q":
            self.app.exit()
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


class LibrarySelect(Select[str]):
    """Local status selector that preserves global section shortcuts."""

    def on_key(self, event: Key) -> None:
        if event.key == "q":
            self.app.exit()
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


class MaintenanceDialog(ModalScreen[LibrarySyncPlan | None]):
    """Cancel-first confirmation for an already non-mutating maintenance preview."""

    def __init__(self, plan: LibrarySyncPlan) -> None:
        super().__init__()
        self.plan = plan
        self._choice = "cancel"
        self._confirmed = False

    def compose(self) -> Iterable[Widget]:
        problems = self.plan.unresolved_files + self.plan.no_lyrics_files + self.plan.analysis_failures
        count = self.plan.ready_files
        body = (
            f"{count + problems} song{'s' if count + problems != 1 else ''} need attention\n\n"
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
        if event.key in {"escape", "n"}: self.dismiss(None)
        elif event.key == "y": self._choice = "confirm"; self._render_choice(); self._activate()
        elif event.key in {"left", "right", "tab", "shift+tab"}:
            self._choice = "confirm" if self._choice == "cancel" else "cancel"; self._render_choice()
            self.query_one("#library-dialog-confirm" if self._choice == "confirm" else "#library-dialog-cancel", LibraryDialogAction).focus()
        elif event.key == "enter": self._activate()
        elif event.key in {"1", "2", "3", "4", "5"}: pass
        else: return
        event.prevent_default(); event.stop()

    def _activate(self) -> None:
        if self._choice == "cancel": self.dismiss(None)
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
        if event.key in {"escape", "n"}: self.dismiss(None)
        elif event.key == "y" and self.can_setup: self._choice = "confirm"; self._render_choice(); self._activate()
        elif event.key in {"left", "right", "tab", "shift+tab"} and self.can_setup:
            self._choice = "confirm" if self._choice == "cancel" else "cancel"; self._render_choice()
            self.query_one("#library-dialog-confirm" if self._choice == "confirm" else "#library-dialog-cancel", LibraryDialogAction).focus()
        elif event.key == "enter": self._activate()
        elif event.key in {"1", "2", "3", "4", "5"}: pass
        else: return
        event.prevent_default(); event.stop()

    def _activate(self) -> None:
        if self._choice == "cancel": self.dismiss(None)
        elif self.can_setup and not self._confirmed: self._confirmed = True; self.dismiss(self.snapshot)


class LibraryScreen(HubScreen):
    """Local library browser and safe maintenance centre."""

    BINDINGS = [Binding("/", "focus_search", "Search", show=False)]

    def __init__(
        self,
        settings: Any,
        *,
        snapshot_provider: SnapshotProvider,
        identity_provider: IdentityProvider,
        identity_rebuild_plan_provider: IdentityRebuildPlanProvider,
        identity_rebuild_execution_provider: IdentityRebuildExecutionProvider,
        preview_provider: PreviewProvider,
        execution_provider: ExecutionProvider,
        backup_provider: BackupProvider,
        restore_provider: RestoreProvider,
        rmpc_status_provider: RmpcStatusProvider,
        rmpc_setup_provider: RmpcSetupProvider,
    ) -> None:
        super().__init__("library", "Library")
        self.settings = settings
        self._snapshot_provider = snapshot_provider
        self._identity_provider = identity_provider
        self._identity_rebuild_plan_provider = identity_rebuild_plan_provider
        self._identity_rebuild_execution_provider = identity_rebuild_execution_provider
        self._preview_provider = preview_provider
        self._execution_provider = execution_provider
        self._backup_provider = backup_provider
        self._restore_provider = restore_provider
        self._rmpc_status_provider = rmpc_status_provider
        self._rmpc_setup_provider = rmpc_setup_provider
        self.snapshot: LibrarySnapshot | None = None
        self.filtered_tracks: tuple[LibraryTrack, ...] = ()
        self.selected_index = 0
        self.preview: LibrarySyncPlan | None = None
        self._details_mode = False
        self._snapshot_worker: Worker[SnapshotOutcome] | None = None
        self._identity_worker: Worker[IdentityOutcome] | None = None
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

    def compose_content(self) -> Iterable[Widget]:
        yield Static(
            "0 songs · Fully covered 0 · Plain only 0 · Missing 0 · Need attention 0\n"
            "Catalogue unmatched 0 · MP3 0 · FLAC 0 · M4A 0",
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
        yield Static("Choose Maintain lyrics to preview changes safely.", id="library-preview", markup=False)
        yield Static("r Refresh · m Maintain lyrics · v Verify · b Backups · p Player · ? Help", id="library-position", markup=False)

    def action_focus_search(self) -> None:
        self.query_one("#library-query", Input).focus()

    def on_screen_resume(self, event: ScreenResume) -> None:
        if self._pending_snapshot is not None:
            outcome, self._pending_snapshot = self._pending_snapshot, None
            self._apply_snapshot(outcome)
        elif self.snapshot is None and self._snapshot_worker is None:
            self.refresh_snapshot(identify=False)
        else:
            self.call_after_refresh(self.set_focus, None)
        if self._pending_preview is not None:
            outcome, self._pending_preview = self._pending_preview, None
            self._apply_preview(outcome)
        if self._pending_identity is not None:
            outcome, self._pending_identity = self._pending_identity, None
            self._apply_identity(outcome)

    def refresh_snapshot(self, *, identify: bool = True) -> None:
        if self.snapshot is None:
            self.query_one("#library-tracks", Static).update("Loading tracks…")
            self.query_one("#library-details", Static).update("Waiting for library data…")
        self.preview = None
        self.query_one("#library-preview", Static).update("Choose Maintain lyrics to preview changes safely.")
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
        self._preview_worker = None
        self._pending_snapshot = None
        self._pending_identity = None
        self._pending_preview = None

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
        if event.worker is self._snapshot_worker:
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
            elif event.state is WorkerState.ERROR:
                outcome = IdentityOutcome(error="Catalogue identification stopped unexpectedly")
                if self._can_render():
                    self._apply_identity(outcome)
                else:
                    self._pending_identity = outcome
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
            healthy = outcome.snapshot.total_track_count - outcome.snapshot.needs_attention_count
            self._set_status(
                f"Verification complete · {healthy} healthy · "
                f"{outcome.snapshot.needs_attention_count} need attention · "
                f"{outcome.snapshot.unmatched_count} catalogue unknown"
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

    def _apply_preview(self, outcome: PreviewOutcome) -> None:
        if outcome.error or outcome.plan is None:
            self.preview = None
            self.query_one("#library-preview", Static).update(
                f"Preview failed: {outcome.error or 'Unknown preview error'} · Preview only — no files changed"
            )
            self._set_status("Sync preview unavailable.", error=True)
            self._render_details()
            return
        self.preview = outcome.plan
        plan = outcome.plan
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
            if plan.ready_files or plan.unresolved_files or plan.no_lyrics_files or plan.analysis_failures:
                self.app.push_screen(MaintenanceDialog(plan), self._maintenance_dialog_closed)
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
        self.query_one("#library-summary", Static).update(
            f"{snapshot.total_track_count} songs · Fully covered {snapshot.fully_covered_count} · "
            f"Plain only {snapshot.plain_only_count} · Missing {snapshot.missing_lyrics_count} · "
            f"Need attention {snapshot.needs_attention_count}\nCatalogue unmatched {snapshot.unmatched_count} · "
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
            f"Tracks · {len(self.filtered_tracks)} of {self.snapshot.total_track_count if self.snapshot else 0}"
        )
        if not self.filtered_tracks:
            message = "No tracks match the local search or filter." if self.snapshot and self.snapshot.tracks else "No supported audio tracks found."
            self.query_one("#library-tracks", Static).update(message)
            return
        lines = []
        for index, track in enumerate(self.filtered_tracks):
            marker = ">" if index == self.selected_index else " "
            attention = "!" if track.needs_attention else " "
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
        lines = [
            track.title,
            "",
            f"Filename       {track.filename}",
            f"Format         {track.media_format}",
            f"Artist         {track.artist or 'Not available'}",
            f"Album          {track.album or 'Not available'}",
            f"Relative path  {track.relative_path}",
            f"Full path      {track.path}",
            f"Catalogue match {track.matched_title or _match_label(track)}",
            f"Duration       {_duration(track.duration_seconds)}",
            f"Lyrics         {_lyric_label(track.lyric_status)}",
            f"External LRC   {_lrc_label(track.lrc_status)}",
            f"LRC path       {track.lrc_path or 'Not recorded'}",
            f"Library state  {_state_label(track.state_status)}",
            f"Attention      {'Yes' if track.needs_attention else 'No'}",
            f"Coverage       {'Fully covered' if track.fully_covered else _coverage_label(track)}",
        ]
        if track.warning:
            lines.extend(("", f"Warning        {track.warning}"))
        if track.match_status is LibraryMatchStatus.UNMATCHED:
            lines.extend(("", "Automatic refresh requires a catalogue match."))
        lines.extend(("", "Sync preview", _track_preview_text(self.preview, track.path)))
        details.update(Text("\n".join(lines), overflow="ellipsis"))

    def _update_position(self) -> None:
        if not self.filtered_tracks:
            self.query_one("#library-position", Static).update("r Refresh · m Maintain lyrics · v Verify · b Backups · p Player · ? Help")
            return
        suffix = "Esc track list · l Refresh lyrics · PgUp/PgDn details" if self._details_mode else "Enter details · r Refresh · m Maintain · v Verify · b Backups"
        self.query_one("#library-position", Static).update(
            f"Track {self.selected_index + 1} of {len(self.filtered_tracks)} · {suffix}"
        )

    def on_key(self, event: Key) -> None:
        if any(select.expanded for select in self.query(Select)):
            return
        if isinstance(self.app.focused, (Input, Select)):
            return
        if event.key == "s":
            self.generate_preview()
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
        elif event.key == "l" and self.selected_track is not None:
            self.generate_preview(action="selected", selected_path=self.selected_track.path)
        elif event.key == "escape" and self._details_mode:
            self._details_mode = False
            self.remove_class("-details-mode")
            self._update_position()
        elif event.key == "enter" and self.selected_track is not None:
            self._details_mode = True
            self.add_class("-details-mode")
            self.query_one("#library-details-scroll", VerticalScroll).scroll_home(animate=False, immediate=True)
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
            message += f" · {remaining} still need attention"
        if result.warnings:
            message += f" · {result.warnings[0]}"
        self._completion_message = (message, bool(result.failed_files))
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
    return "Matched" if track.match_status is LibraryMatchStatus.MATCHED else "Unknown"


def _lyric_label(status: LibraryLyricStatus) -> str:
    return {
        LibraryLyricStatus.SYNCED: "Synced lyrics",
        LibraryLyricStatus.PLAIN: "Plain lyrics",
        LibraryLyricStatus.NONE: "No lyrics",
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
        return "Missing lyrics"
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


def _track_preview_text(plan: LibrarySyncPlan | None, path: Path) -> str:
    if plan is None:
        return "  Not generated. Press s for a read-only preview."
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

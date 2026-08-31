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
from textual.events import Key, Resize, ScreenResume
from textual.geometry import Region
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
from ...services.library_sync import LibrarySyncPlan, MatchOutcome, SyncLyricType
from .base import HubScreen

SnapshotProvider = Callable[[Any], LibrarySnapshot]
PreviewProvider = Callable[[Any], LibrarySyncPlan]


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
class PreviewOutcome:
    plan: LibrarySyncPlan | None = None
    error: str | None = None


class LibraryScreen(HubScreen):
    """Read-only local MP3 library browser and sync-plan preview."""

    BINDINGS = [Binding("/", "focus_search", "Search", show=False)]

    def __init__(
        self,
        settings: Any,
        *,
        snapshot_provider: SnapshotProvider,
        preview_provider: PreviewProvider,
    ) -> None:
        super().__init__("library", "Library")
        self.settings = settings
        self._snapshot_provider = snapshot_provider
        self._preview_provider = preview_provider
        self.snapshot: LibrarySnapshot | None = None
        self.filtered_tracks: tuple[LibraryTrack, ...] = ()
        self.selected_index = 0
        self.preview: LibrarySyncPlan | None = None
        self._details_mode = False
        self._snapshot_worker: Worker[SnapshotOutcome] | None = None
        self._preview_worker: Worker[PreviewOutcome] | None = None
        self._pending_snapshot: SnapshotOutcome | None = None
        self._pending_preview: PreviewOutcome | None = None

    def compose_content(self) -> Iterable[Widget]:
        yield Static(
            "MP3 tracks 0 · Matched 0 · Unmatched 0 · Synced 0 · Plain 0 · No lyrics 0 · LRC 0 · Attention 0",
            id="library-summary",
            markup=False,
        )
        yield Static("Loading local MP3 library…", id="library-status", markup=False)
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
        yield Static("Preview not generated · press s · Preview only — no files changed", id="library-preview", markup=False)
        yield Static("r refresh · s preview · / search", id="library-position", markup=False)

    def action_focus_search(self) -> None:
        self.query_one("#library-query", Input).focus()

    def on_screen_resume(self, event: ScreenResume) -> None:
        if self._pending_snapshot is not None:
            outcome, self._pending_snapshot = self._pending_snapshot, None
            self._apply_snapshot(outcome)
        elif self.snapshot is None and self._snapshot_worker is None:
            self.refresh_snapshot()
        elif self.filtered_tracks:
            self.call_after_refresh(self.set_focus, None)
        if self._pending_preview is not None:
            outcome, self._pending_preview = self._pending_preview, None
            self._apply_preview(outcome)

    def refresh_snapshot(self) -> None:
        if self.snapshot is None:
            self.query_one("#library-tracks", Static).update("Loading tracks…")
            self.query_one("#library-details", Static).update("Waiting for library data…")
        self.preview = None
        self.query_one("#library-preview", Static).update(
            "Preview not generated · press s · Preview only — no files changed"
        )
        self._set_status("Refreshing local MP3 library…")
        self._snapshot_worker = self._load_snapshot()

    def invalidate_snapshot(self) -> None:
        self.snapshot = None
        self.preview = None
        self._snapshot_worker = None
        self._preview_worker = None
        self._pending_snapshot = None
        self._pending_preview = None

    @work(thread=True, exclusive=True, group="library-snapshot", exit_on_error=False)
    def _load_snapshot(self) -> SnapshotOutcome:
        try:
            return SnapshotOutcome(self._snapshot_provider(self.settings))
        except Exception as exc:
            return SnapshotOutcome(error=str(exc) or type(exc).__name__)

    def generate_preview(self) -> None:
        if self.snapshot is None:
            self._set_status("Load the library before generating a sync preview.", error=True)
            return
        self.query_one("#library-preview", Static).update(
            "Generating sync preview… · Preview only — no files changed"
        )
        self._preview_worker = self._load_preview()

    @work(thread=True, exclusive=True, group="library-preview", exit_on_error=False)
    def _load_preview(self) -> PreviewOutcome:
        try:
            return PreviewOutcome(self._preview_provider(self.settings))
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
                outcome = SnapshotOutcome(error="Library snapshot worker failed")
                if self._can_render():
                    self._apply_snapshot(outcome)
                else:
                    self._pending_snapshot = outcome
        elif event.worker is self._preview_worker:
            if event.state is WorkerState.SUCCESS:
                outcome = event.worker.result
                if self._can_render():
                    self._apply_preview(outcome)
                else:
                    self._pending_preview = outcome
            elif event.state is WorkerState.ERROR:
                outcome = PreviewOutcome(error="Sync preview worker failed")
                if self._can_render():
                    self._apply_preview(outcome)
                else:
                    self._pending_preview = outcome

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
        if not outcome.snapshot.directory_exists:
            self._set_status(outcome.snapshot.warnings[0], error=True)
        elif not outcome.snapshot.tracks:
            self._set_status("No supported MP3 tracks found. Native FLAC support is planned.")
        elif outcome.snapshot.warnings:
            self._set_status(" ".join(outcome.snapshot.warnings), error=True)
        else:
            self._set_status(f"Local MP3 library · {outcome.snapshot.library_path}")

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
        lrc_destination = (
            f" · LRC dir {plan.options.lyrics_dir}"
            if lrc and plan.options.lyrics_dir is not None
            else ""
        )
        self.query_one("#library-preview", Static).update(
            f"Preview only — no files changed · Current {plan.unchanged_files} · Update {plan.ready_files} "
            f"(Synced {plan.synced_files}, Plain {plan.plain_files}) · LRC {lrc} · "
            f"Unresolved {plan.unresolved_files} · No lyrics {plan.no_lyrics_files} · Errors {plan.analysis_failures}"
            f"{lrc_destination}"
        )
        self._set_status("Sync preview complete. No files were changed.")
        self._render_details()

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
            f"MP3 tracks {snapshot.total_track_count} · Matched {snapshot.matched_count} · "
            f"Unmatched {snapshot.unmatched_count} · Synced {snapshot.synced_count} · "
            f"Plain {snapshot.plain_count} · No lyrics {snapshot.no_lyrics_count} · "
            f"LRC {snapshot.external_lrc_count} · Attention {snapshot.needs_attention_count}"
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
            message = "No tracks match the local search or filter." if self.snapshot and self.snapshot.tracks else "No MP3 tracks found."
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
            f"Relative path  {track.relative_path}",
            f"Full path      {track.path}",
            f"Matched        {track.matched_title or _match_label(track)}",
            f"Duration       {_duration(track.duration_seconds)}",
            f"Lyrics         {_lyric_label(track.lyric_status)}",
            f"External LRC   {_lrc_label(track.lrc_status)}",
            f"LRC path       {track.lrc_path or 'Not recorded'}",
            f"Library state  {_state_label(track.state_status)}",
            f"Attention      {'Yes' if track.needs_attention else 'No'}",
        ]
        if track.warning:
            lines.extend(("", f"Warning        {track.warning}"))
        lines.extend(("", "Sync preview", _track_preview_text(self.preview, track.path)))
        details.update(Text("\n".join(lines), overflow="ellipsis"))

    def _update_position(self) -> None:
        if not self.filtered_tracks:
            self.query_one("#library-position", Static).update("r refresh · s preview · / search")
            return
        suffix = "Esc track list · PgUp/PgDn details" if self._details_mode else "Enter details · r refresh · s preview · / search"
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
    return "Matched" if track.match_status is LibraryMatchStatus.MATCHED else "Unmatched"


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
        LibraryLrcStatus.NONE: "None",
    }[status]


def _state_label(status: LibraryStateStatus) -> str:
    return {
        LibraryStateStatus.CURRENT: "Current",
        LibraryStateStatus.NEW: "New",
        LibraryStateStatus.CHANGED: "Changed",
        LibraryStateStatus.INVALID: "Invalid",
    }[status]


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
    if track.error:
        text += f" · {track.error}"
    return text

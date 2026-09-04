from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from rich.text import Text
from textual import work
from textual.containers import Container, Grid, VerticalScroll
from textual.events import Key, Resize, ScreenResume
from textual.widget import Widget
from textual.widgets import Static
from textual.worker import Worker, WorkerState

from ...services.settings_snapshot import (
    IntegrationStatus,
    SettingValue,
    SettingsPath,
    SettingsSnapshot,
    SettingsSource,
)
from .base import HubScreen

SnapshotProvider = Callable[[Any], SettingsSnapshot]


@dataclass(frozen=True, slots=True)
class SettingsOutcome:
    snapshot: SettingsSnapshot | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class SettingsRow:
    section: str
    label: str
    value: str
    detail: str


class SettingsScreen(HubScreen):
    """Read-only effective configuration and environment inspector."""

    def __init__(self, settings: Any, *, snapshot_provider: SnapshotProvider) -> None:
        super().__init__("settings", "Settings")
        self.settings = settings
        self._snapshot_provider = snapshot_provider
        self.snapshot: SettingsSnapshot | None = None
        self.rows: tuple[SettingsRow, ...] = ()
        self.selected_index = 0
        self._refresh_worker: Worker[SettingsOutcome] | None = None
        self._pending_outcome: SettingsOutcome | None = None

    def compose_content(self) -> Iterable[Widget]:
        yield Static(
            "Read-only settings view — configuration changes remain CLI-only",
            id="settings-warning",
            markup=False,
        )
        yield Static("Loading configuration and environment…", id="settings-status", markup=False)
        with VerticalScroll(id="settings-scroll"):
            with Grid(id="settings-main"):
                with Container(classes="settings-panel", id="settings-paths-panel"):
                    yield Static("Folders", classes="panel-title")
                    yield Static("Loading…", id="settings-paths", markup=False)
                with Container(classes="settings-panel", id="settings-integrations-panel"):
                    yield Static("rmpc", classes="panel-title")
                    yield Static("Loading…", id="settings-integrations", markup=False)
                with Container(classes="settings-panel", id="settings-configuration-panel"):
                    yield Static("Advanced", classes="panel-title")
                    yield Static("Loading…", id="settings-configuration", markup=False)
                with Container(classes="settings-panel", id="settings-capabilities-panel"):
                    yield Static("Capabilities and limitations", classes="panel-title")
                    yield Static("Loading…", id="settings-capabilities", markup=False)
            yield Static("Selected setting details will appear here.", id="settings-detail", markup=False)
        yield Static("r refresh · ↑/↓ or j/k inspect · PgUp/PgDn scroll", id="settings-position", markup=False)

    def on_screen_resume(self, event: ScreenResume) -> None:
        if self._pending_outcome is not None:
            outcome, self._pending_outcome = self._pending_outcome, None
            self._apply_snapshot(outcome)
        elif self.snapshot is None and self._refresh_worker is None:
            self.refresh_snapshot()

    def refresh_snapshot(self) -> None:
        if self.snapshot is None:
            for selector in (
                "#settings-configuration",
                "#settings-paths",
                "#settings-integrations",
                "#settings-capabilities",
            ):
                self.query_one(selector, Static).update("Loading…")
        self._set_status("Refreshing configuration and environment…")
        self._refresh_worker = self._load_snapshot()

    @work(thread=True, exclusive=True, group="settings-snapshot", exit_on_error=False)
    def _load_snapshot(self) -> SettingsOutcome:
        try:
            return SettingsOutcome(self._snapshot_provider(self.settings))
        except Exception as exc:
            return SettingsOutcome(error=str(exc) or type(exc).__name__)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is not self._refresh_worker:
            return
        if event.state is WorkerState.SUCCESS:
            outcome = event.worker.result
        elif event.state is WorkerState.ERROR:
            outcome = SettingsOutcome(error="Settings could not be loaded")
        else:
            return
        if self._can_render():
            self._apply_snapshot(outcome)
        else:
            self._pending_outcome = outcome

    def _can_render(self) -> bool:
        if not self.is_mounted or not list(self.query("#settings-warning")):
            return False
        try:
            return self.app.screen is self
        except Exception:
            return False

    def _apply_snapshot(self, outcome: SettingsOutcome) -> None:
        if outcome.error or outcome.snapshot is None:
            self._set_status(
                f"Settings unavailable: {outcome.error or 'Unknown settings error'}",
                error=True,
            )
            if self.snapshot is None:
                self.rows = ()
                self.query_one("#settings-configuration", Static).update(
                    "Unable to inspect configuration."
                )
                self.query_one("#settings-paths", Static).update("Path details are unavailable.")
                self.query_one("#settings-integrations", Static).update(
                    "Integration details are unavailable."
                )
                self.query_one("#settings-capabilities", Static).update(
                    "Capabilities could not be loaded."
                )
                self.query_one("#settings-detail", Static).update(
                    "Correct the configuration error and press r to retry."
                )
            return

        previous = self.rows[self.selected_index].detail if self.rows else None
        self.snapshot = outcome.snapshot
        self.rows = _rows_for(outcome.snapshot)
        self.selected_index = next(
            (index for index, row in enumerate(self.rows) if row.detail == previous),
            0,
        )
        self._render_rows()
        if outcome.snapshot.warnings:
            self._set_status(" ".join(outcome.snapshot.warnings), error=True)
        elif outcome.snapshot.config_exists:
            self._set_status("Effective configuration loaded from the active config file.")
        else:
            self._set_status("No config file · defaults and runtime overrides are shown.")
        self.query_one("#settings-scroll", VerticalScroll).scroll_home(animate=False, immediate=True)

    def _render_rows(self) -> None:
        grouped: dict[str, list[tuple[int, SettingsRow]]] = {
            "configuration": [],
            "paths": [],
            "integrations": [],
            "capabilities": [],
        }
        for index, row in enumerate(self.rows):
            grouped[row.section].append((index, row))
        for section, selector in (
            ("configuration", "#settings-configuration"),
            ("paths", "#settings-paths"),
            ("integrations", "#settings-integrations"),
            ("capabilities", "#settings-capabilities"),
        ):
            lines = [
                f"{'> ' if index == self.selected_index else '  '}{row.label:<21} {_compact(row.value, 52)}"
                for index, row in grouped[section]
            ]
            self.query_one(selector, Static).update(
                Text("\n".join(lines) or "No information available.", no_wrap=True, overflow="ellipsis")
            )
        if self.rows:
            row = self.rows[self.selected_index]
            self.query_one("#settings-detail", Static).update(
                f"{row.label}\n{row.detail}"
            )
            self.query_one("#settings-position", Static).update(
                f"Setting {self.selected_index + 1} of {len(self.rows)} · r refresh · PgUp/PgDn scroll"
            )

    def on_key(self, event: Key) -> None:
        if event.key in ("down", "j"):
            self._select(self.selected_index + 1)
        elif event.key in ("up", "k"):
            self._select(self.selected_index - 1)
        elif event.key == "home":
            self._select(0)
        elif event.key == "end":
            self._select(len(self.rows) - 1)
        elif event.key in ("pagedown", "pageup"):
            scroll = self.query_one("#settings-scroll", VerticalScroll)
            step = max(1, scroll.size.height // 2)
            self._select(self.selected_index + (step if event.key == "pagedown" else -step))
            if event.key == "pagedown":
                scroll.scroll_page_down(animate=False)
            else:
                scroll.scroll_page_up(animate=False)
        elif event.key in ("enter", "escape"):
            return
        else:
            return
        event.prevent_default()
        event.stop()

    def _select(self, index: int) -> None:
        if not self.rows:
            return
        self.selected_index = max(0, min(len(self.rows) - 1, index))
        self._render_rows()
        section = self.rows[self.selected_index].section
        self.call_after_refresh(
            self.query_one("#settings-scroll", VerticalScroll).scroll_to_widget,
            self.query_one(f"#settings-{section}-panel"),
            animate=False,
        )

    def _set_status(self, message: str, *, error: bool = False) -> None:
        status = self.query_one("#settings-status", Static)
        status.update(message)
        status.set_class(error, "-error")

    def on_resize(self, event: Resize) -> None:
        super().on_resize(event)
        self.set_class(event.size.width < 100, "-settings-narrow")
        self.set_class(event.size.height <= 30, "-settings-compact")


def _rows_for(snapshot: SettingsSnapshot) -> tuple[SettingsRow, ...]:
    paths = {item.key: item for item in snapshot.paths}
    essential_rows: list[SettingsRow] = []
    if "music" in paths:
        essential_rows.append(_path_row(paths["music"], section="paths", label="Music folder"))
    if "music" in paths:
        essential_rows.append(_path_row(paths["music"], section="paths", label="Download location"))
    external_lyrics = next(
        (item for item in snapshot.values if item.key == "external_lyrics"),
        None,
    )
    if external_lyrics is not None:
        essential_rows.append(
            SettingsRow(
                "paths",
                "External lyrics",
                str(external_lyrics.value),
                "Synchronized external lyrics use a same-basename .lrc beside each song.",
            )
        )

    advanced_rows = [
        SettingsRow(
            "configuration",
            "Active config",
            str(snapshot.config_path),
            f"{snapshot.config_path} · {'Exists' if snapshot.config_exists else 'Missing; defaults are in use'}",
        ),
        SettingsRow(
            "configuration",
            "Application version",
            snapshot.application_version,
            snapshot.application_version,
        ),
    ]
    advanced_rows.extend(
        _value_row(item)
        for item in snapshot.values
        if item.key not in {"music_dir", "external_lyrics"}
    )
    advanced_rows.extend(
        _path_row(item, section="configuration")
        for item in snapshot.paths
        if item.key != "music"
    )
    integration_rows = [
        SettingsRow(
            "integrations",
            "rmpc status",
            _integration_label(snapshot.rmpc.status),
            snapshot.rmpc.detail,
        ),
        SettingsRow(
            "configuration",
            "rmpc executable",
            str(snapshot.rmpc.executable or "Not detected"),
            str(snapshot.rmpc.executable or "rmpc was not found in PATH."),
        ),
        SettingsRow(
            "configuration",
            "rmpc configuration",
            "Configured" if snapshot.rmpc.config_has_lyrics_support else "Not configured",
            f"{snapshot.rmpc.config_path} · {'Exists' if snapshot.rmpc.config_exists else 'Missing'}",
        ),
    ]
    capability_rows = [
        SettingsRow("capabilities", f"Limitation {index}", value, value)
        for index, value in enumerate(snapshot.limitations, start=1)
    ]
    primary_integration = integration_rows[:1]
    advanced_rows.extend(integration_rows[1:])
    return tuple((*essential_rows, *primary_integration, *advanced_rows, *capability_rows))


def _value_row(item: SettingValue) -> SettingsRow:
    source = {
        SettingsSource.DEFAULT: "Default",
        SettingsSource.CONFIG: "Config file",
        SettingsSource.RUNTIME_OVERRIDE: "Runtime override",
    }[item.source]
    value = str(item.value)
    units = {
        "timeout": " seconds",
        "delay": " seconds",
        "duration_tolerance": " seconds",
        "cache_ttl_hours": " hours",
    }.get(item.key, "")
    return SettingsRow(
        "configuration",
        item.label,
        f"{value}{units} [{source}]",
        f"Effective: {value}{units} · Source: {source} · Default: {item.default_value}{units}",
    )


def _path_row(
    item: SettingsPath,
    *,
    section: str = "paths",
    label: str | None = None,
) -> SettingsRow:
    state = "Exists" if item.exists else "Missing"
    warning = f" · Inspection warning: {item.warning}" if item.warning else ""
    return SettingsRow(
        section,
        label or item.label,
        f"{item.path} [{state}]",
        f"{item.path} · {state}{warning}",
    )


def _integration_label(status: IntegrationStatus) -> str:
    return {
        IntegrationStatus.DETECTED_CONFIGURED: "Detected and configured",
        IntegrationStatus.DETECTED_NOT_CONFIGURED: "Detected but not configured",
        IntegrationStatus.NOT_DETECTED: "Not detected",
        IntegrationStatus.UNABLE_TO_INSPECT: "Unable to inspect",
    }[status]


def _compact(value: str, limit: int) -> str:
    return value if len(value) <= limit else "…" + value[-(limit - 1):]

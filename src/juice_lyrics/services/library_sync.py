from __future__ import annotations

import json
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from ..api.client import search_song_names
from ..backup.manager import backup_file, make_backup_root, restore_file, write_manifest
from ..config.settings import DEFAULT_RMPC_CONFIG, STATE_FILE, Settings, resolve_lyrics_dir
from ..library.matching import choose_candidate, search_title_for
from ..library.scanner import find_mp3s
from ..lyrics.engine import embed_lyrics, parse_synced_lyrics, verify_file, write_lrc
from ..rmpc.integration import notify_rmpc_index, patch_rmpc_config
from ..state import load_state, save_state, sha256_file
from ..backup.manager import now_iso


class SyncLyricType(str, Enum):
    SYNCED = "SYLT"
    PLAIN = "USLT"
    NONE = "NONE"


class MatchOutcome(str, Enum):
    UNCHANGED = "unchanged"
    MATCHED = "matched"
    UNRESOLVED = "unresolved"
    NO_LYRICS = "no_lyrics"
    FAILED = "failed"


class SyncEventKind(str, Enum):
    SCAN_STARTED = "scan_started"
    TRACK_INSPECTED = "track_inspected"
    MATCH_FOUND = "match_found"
    UNRESOLVED = "unresolved"
    SCAN_COMPLETED = "scan_completed"
    BACKUP_CREATED = "backup_created"
    LYRICS_EMBEDDED = "lyrics_embedded"
    VERIFICATION_SUCCEEDED = "verification_succeeded"
    VERIFICATION_FAILED = "verification_failed"
    LRC_GENERATED = "lrc_generated"
    STATE_UPDATED = "state_updated"
    TRACK_COMPLETED = "track_completed"
    TRACK_FAILED = "track_failed"


@dataclass(frozen=True, slots=True)
class LibrarySyncOptions:
    settings: Settings
    music_dir: Path
    dry_run: bool = False
    refresh: bool = False
    rmpc_enabled: bool = False
    lyrics_dir: Path | None = None
    rmpc_config_path: Path | None = None
    duration_tolerance: float = 3.0
    state_file: Path = STATE_FILE

    def __post_init__(self) -> None:
        # A plan may contain historical state paths, but all new LRC output is
        # derived from current settings at the application boundary.
        authoritative = resolve_lyrics_dir(self.settings) if self.rmpc_enabled else None
        object.__setattr__(self, "lyrics_dir", authoritative)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        dry_run: bool = False,
        refresh: bool = False,
        rmpc_enabled: bool = False,
        lyrics_dir: Path | None = None,
        rmpc_config_path: Path | None = None,
        state_file: Path = STATE_FILE,
    ) -> "LibrarySyncOptions":
        return cls(
            settings=settings,
            music_dir=Path(settings.music_dir),
            dry_run=dry_run,
            refresh=refresh,
            rmpc_enabled=rmpc_enabled,
            lyrics_dir=resolve_lyrics_dir(settings) if rmpc_enabled else None,
            rmpc_config_path=Path(rmpc_config_path) if rmpc_config_path is not None else None,
            duration_tolerance=settings.duration_tolerance,
            state_file=Path(state_file),
        )


@dataclass(frozen=True, slots=True)
class SyncEvent:
    kind: SyncEventKind
    path: Path | None = None
    index: int | None = None
    total: int | None = None
    message: str | None = None


@dataclass(frozen=True, slots=True)
class TrackSyncPlan:
    path: Path
    outcome: MatchOutcome
    lyric_type: SyncLyricType
    candidate: Mapping[str, Any] | None = None
    synced_lyrics: tuple[tuple[str, int], ...] = ()
    plain_lyrics: str = ""
    error: str | None = None


@dataclass(frozen=True, slots=True)
class TrackSyncResult:
    path: Path
    outcome: MatchOutcome
    lyric_type: SyncLyricType
    updated: bool = False
    verification: str | None = None
    backup_path: Path | None = None
    lrc_path: Path | None = None
    error: str | None = None
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class LibrarySyncPlan:
    options: LibrarySyncOptions
    tracks: tuple[TrackSyncPlan, ...]
    state: dict[str, Any] = field(repr=False, compare=False)

    @property
    def total_files(self) -> int:
        return len(self.tracks)

    @property
    def unchanged_files(self) -> int:
        return sum(track.outcome is MatchOutcome.UNCHANGED for track in self.tracks)

    @property
    def changed_or_new_files(self) -> int:
        return sum(track.outcome is not MatchOutcome.UNCHANGED and track.outcome is not MatchOutcome.FAILED for track in self.tracks)

    @property
    def ready_files(self) -> int:
        return sum(track.outcome is MatchOutcome.MATCHED for track in self.tracks)

    @property
    def unresolved_files(self) -> int:
        return sum(track.outcome is MatchOutcome.UNRESOLVED for track in self.tracks)

    @property
    def no_lyrics_files(self) -> int:
        return sum(track.outcome is MatchOutcome.NO_LYRICS for track in self.tracks)

    @property
    def synced_files(self) -> int:
        return sum(track.outcome is MatchOutcome.MATCHED and track.lyric_type is SyncLyricType.SYNCED for track in self.tracks)

    @property
    def plain_files(self) -> int:
        return sum(track.outcome is MatchOutcome.MATCHED and track.lyric_type is SyncLyricType.PLAIN for track in self.tracks)

    @property
    def analysis_failures(self) -> int:
        return sum(track.outcome is MatchOutcome.FAILED for track in self.tracks)


@dataclass(frozen=True, slots=True)
class LibrarySyncResult:
    plan: LibrarySyncPlan
    tracks: tuple[TrackSyncResult, ...]
    updated_files: int
    failed_files: int
    processing_failed_files: int
    lrc_files_generated: int
    rmpc_notifications: int
    backup_path: Path | None
    warnings: tuple[str, ...] = ()


ProgressCallback = Callable[[SyncEvent], None]


@dataclass(slots=True)
class LibrarySyncDependencies:
    scanner: Callable[[Any], list[Path]] = find_mp3s
    searcher: Callable[..., list[dict[str, Any]]] = search_song_names
    matcher: Callable[..., Any] = choose_candidate
    search_title: Callable[[Path], str] = search_title_for
    lyric_parser: Callable[[str], list[tuple[str, int]]] = parse_synced_lyrics
    embedder: Callable[[Path, list[tuple[str, int]], str], str] = embed_lyrics
    verifier: Callable[[Path], tuple[bool, str]] = verify_file
    backup_root_factory: Callable[[], Path] = make_backup_root
    backup_writer: Callable[[Path, Path, Path], Path] = backup_file
    restorer: Callable[[Path, Path], None] = restore_file
    manifest_writer: Callable[[Path, list[dict[str, Any]]], None] = write_manifest
    lrc_writer: Callable[[Path, list[tuple[str, int]], dict[str, Any], Path], Path] = write_lrc
    rmpc_notifier: Callable[[list[Path]], int] = notify_rmpc_index
    rmpc_configurer: Callable[[Path, Path], Path] = patch_rmpc_config
    state_loader: Callable[[], dict[str, Any]] = load_state
    state_saver: Callable[[dict[str, Any]], None] = save_state
    hasher: Callable[[Path], str] = sha256_file


def _emit(callback: ProgressCallback | None, kind: SyncEventKind, **kwargs: Any) -> None:
    if callback:
        callback(SyncEvent(kind=kind, **kwargs))


def _read_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"files": {}, "updated": None}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"files": {}, "updated": None}
    return value if isinstance(value, dict) else {"files": {}, "updated": None}


def _state_is_current(
    state: Mapping[str, Any],
    path: Path,
    options: LibrarySyncOptions,
    dependencies: LibrarySyncDependencies,
) -> bool:
    entry = state.get("files", {}).get(str(path.relative_to(options.music_dir)))
    if not isinstance(entry, Mapping):
        return False
    try:
        if entry.get("sha256") != dependencies.hasher(path):
            return False
    except OSError:
        return False
    valid, _ = dependencies.verifier(path)
    if not valid:
        return False
    if options.rmpc_enabled and entry.get("lyric_type") == SyncLyricType.SYNCED.value:
        lrc = Path(str(entry.get("lrc") or ""))
        expected_lrc = (
            options.lyrics_dir / f"{path.stem}.lrc"
            if options.lyrics_dir is not None
            else None
        )
        if expected_lrc is None or lrc != expected_lrc or not expected_lrc.is_file():
            return False
    return True


def plan_library_sync(
    options: LibrarySyncOptions,
    *,
    dependencies: LibrarySyncDependencies | None = None,
    progress: ProgressCallback | None = None,
) -> LibrarySyncPlan:
    dependencies = dependencies or LibrarySyncDependencies()
    files = dependencies.scanner(options.settings)
    state = _read_state(options.state_file) if options.dry_run else dependencies.state_loader()
    tracks: list[TrackSyncPlan] = []
    _emit(progress, SyncEventKind.SCAN_STARTED, total=len(files))
    for index, path in enumerate(files, start=1):
        if not options.refresh and _state_is_current(state, path, options, dependencies):
            _emit(
                progress,
                SyncEventKind.TRACK_INSPECTED,
                path=path,
                index=index,
                total=len(files),
                message="unchanged",
            )
            tracks.append(TrackSyncPlan(path, MatchOutcome.UNCHANGED, SyncLyricType.NONE))
            continue
        _emit(progress, SyncEventKind.TRACK_INSPECTED, path=path, index=index, total=len(files))
        try:
            title = dependencies.search_title(path)
            results = dependencies.searcher(options.settings, title, refresh=options.refresh)
            candidate, _, _, _ = dependencies.matcher(options.settings, path, results, title)
            if candidate is None:
                tracks.append(TrackSyncPlan(path, MatchOutcome.UNRESOLVED, SyncLyricType.NONE))
                _emit(progress, SyncEventKind.UNRESOLVED, path=path)
                continue
            synced = tuple(dependencies.lyric_parser(str(candidate.get("synced_lyrics") or "")))
            plain = str(candidate.get("lyrics") or "")
            if synced:
                lyric_type = SyncLyricType.SYNCED
            elif plain.strip():
                lyric_type = SyncLyricType.PLAIN
            else:
                tracks.append(TrackSyncPlan(path, MatchOutcome.NO_LYRICS, SyncLyricType.NONE, candidate))
                continue
            tracks.append(TrackSyncPlan(path, MatchOutcome.MATCHED, lyric_type, candidate, synced, plain))
            _emit(progress, SyncEventKind.MATCH_FOUND, path=path, message=lyric_type.value)
        except Exception as exc:
            tracks.append(TrackSyncPlan(path, MatchOutcome.FAILED, SyncLyricType.NONE, error=str(exc)))
            _emit(progress, SyncEventKind.TRACK_FAILED, path=path, message=str(exc))
    _emit(progress, SyncEventKind.SCAN_COMPLETED, total=len(files))
    return LibrarySyncPlan(options, tuple(tracks), state)


def get_library_sync_preview(
    settings: Settings,
    *,
    rmpc_enabled: bool | None = None,
    lyrics_dir: Path | None = None,
    state_file: Path = STATE_FILE,
    dependencies: LibrarySyncDependencies | None = None,
    progress: ProgressCallback | None = None,
) -> LibrarySyncPlan:
    """Build a non-mutating sync plan suitable for read-only frontends."""

    if rmpc_enabled is None:
        rmpc_enabled = shutil.which("rmpc") is not None and DEFAULT_RMPC_CONFIG.exists()
    options = LibrarySyncOptions.from_settings(
        settings,
        dry_run=True,
        rmpc_enabled=rmpc_enabled,
        lyrics_dir=lyrics_dir,
        state_file=state_file,
    )
    return plan_library_sync(options, dependencies=dependencies, progress=progress)


def _state_entry(
    state: dict[str, Any],
    track: TrackSyncPlan,
    options: LibrarySyncOptions,
    lrc_path: Path | None,
    dependencies: LibrarySyncDependencies,
) -> None:
    candidate = track.candidate or {}
    state.setdefault("files", {})[str(track.path.relative_to(options.music_dir))] = {
        "sha256": dependencies.hasher(track.path),
        "song_id": candidate.get("id"),
        "api_name": candidate.get("name"),
        "lyric_type": track.lyric_type.value,
        "lrc": str(lrc_path) if lrc_path else None,
        "updated": now_iso(),
    }


def execute_library_sync(
    plan: LibrarySyncPlan,
    *,
    dependencies: LibrarySyncDependencies | None = None,
    progress: ProgressCallback | None = None,
) -> LibrarySyncResult:
    dependencies = dependencies or LibrarySyncDependencies()
    options = plan.options
    initial_results = [
        TrackSyncResult(track.path, track.outcome, track.lyric_type, error=track.error)
        for track in plan.tracks
        if track.outcome is not MatchOutcome.MATCHED
    ]
    if options.dry_run:
        return LibrarySyncResult(
            plan, tuple(initial_results), 0, plan.analysis_failures, 0, 0, 0, None
        )

    ready = [track for track in plan.tracks if track.outcome is MatchOutcome.MATCHED]
    if not ready:
        dependencies.state_saver(plan.state)
        return LibrarySyncResult(
            plan, tuple(initial_results), 0, plan.analysis_failures, 0, 0, 0, None
        )

    if (
        options.rmpc_enabled
        and options.lyrics_dir is not None
        and any(track.lyric_type is SyncLyricType.SYNCED for track in ready)
        and options.rmpc_config_path is not None
    ):
        text = options.rmpc_config_path.read_text(encoding="utf-8")
        if str(options.lyrics_dir) not in text:
            dependencies.rmpc_configurer(options.rmpc_config_path, options.lyrics_dir)

    backup_root = dependencies.backup_root_factory()
    manifest: list[dict[str, Any]] = []
    generated_lrc: list[Path] = []
    results: list[TrackSyncResult] = initial_results
    for track in ready:
        backup: Path | None = None
        try:
            original_hash = dependencies.hasher(track.path)
            backup = dependencies.backup_writer(track.path, backup_root, options.music_dir)
            _emit(progress, SyncEventKind.BACKUP_CREATED, path=track.path, message=str(backup))
            try:
                embedded = dependencies.embedder(track.path, list(track.synced_lyrics), track.plain_lyrics)
                _emit(progress, SyncEventKind.LYRICS_EMBEDDED, path=track.path, message=embedded)
                valid, verification = dependencies.verifier(track.path)
                if not valid:
                    _emit(progress, SyncEventKind.VERIFICATION_FAILED, path=track.path, message=verification)
                    raise RuntimeError(f"verification failed: {verification}")
                _emit(progress, SyncEventKind.VERIFICATION_SUCCEEDED, path=track.path, message=verification)
            except Exception:
                dependencies.restorer(backup, track.path)
                raise

            lrc_path: Path | None = None
            if options.rmpc_enabled and track.lyric_type is SyncLyricType.SYNCED and options.lyrics_dir is not None:
                lrc_path = dependencies.lrc_writer(
                    track.path,
                    list(track.synced_lyrics),
                    dict(track.candidate or {}),
                    options.lyrics_dir,
                )
                generated_lrc.append(lrc_path)
                _emit(progress, SyncEventKind.LRC_GENERATED, path=track.path, message=str(lrc_path))
            _state_entry(plan.state, track, options, lrc_path, dependencies)
            _emit(progress, SyncEventKind.STATE_UPDATED, path=track.path)
            manifest.append({
                "file": str(track.path),
                "sha256_before": original_hash,
                "lyric_type": track.lyric_type.value,
                "verification": verification,
            })
            result = TrackSyncResult(
                track.path,
                MatchOutcome.MATCHED,
                track.lyric_type,
                updated=True,
                verification=verification,
                backup_path=backup,
                lrc_path=lrc_path,
            )
            results.append(result)
            completion = track.lyric_type.value + (" + LRC" if lrc_path else "")
            _emit(progress, SyncEventKind.TRACK_COMPLETED, path=track.path, message=completion)
        except Exception as exc:
            results.append(TrackSyncResult(
                track.path,
                MatchOutcome.FAILED,
                track.lyric_type,
                backup_path=backup,
                error=str(exc),
            ))
            _emit(progress, SyncEventKind.TRACK_FAILED, path=track.path, message=str(exc))

    dependencies.manifest_writer(backup_root, manifest)
    dependencies.state_saver(plan.state)
    warnings: list[str] = []
    notified = 0
    if options.rmpc_enabled:
        try:
            notified = dependencies.rmpc_notifier(generated_lrc)
        except Exception as exc:
            warnings.append(str(exc))
    result_by_path = {result.path: result for result in results}
    ordered_results = tuple(result_by_path[track.path] for track in plan.tracks)
    ready_paths = {track.path for track in ready}
    processing_failures = sum(
        result.outcome is MatchOutcome.FAILED and result.path in ready_paths
        for result in ordered_results
    )
    return LibrarySyncResult(
        plan=plan,
        tracks=ordered_results,
        updated_files=sum(result.updated for result in ordered_results),
        failed_files=sum(result.outcome is MatchOutcome.FAILED for result in ordered_results),
        processing_failed_files=processing_failures,
        lrc_files_generated=len(generated_lrc),
        rmpc_notifications=notified,
        backup_path=backup_root,
        warnings=tuple(warnings),
    )

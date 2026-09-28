import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys
from threading import Event, get_ident
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from textual.containers import VerticalScroll
from textual.widgets import Input, Select

from juice_lyrics.config.settings import Settings
from juice_lyrics.services import (
    CatalogueFilterMetadata,
    CataloguePage,
    CatalogueSearchResult,
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibrarySnapshot,
    LibraryStateStatus,
    LibraryStatus,
    LibraryTrack,
    IdentityBackfillResult,
    IdentityChange,
    IdentityRebuildPlan,
    IdentityRebuildProgress,
    IdentityRebuildResult,
    LyricAvailability,
    ManualIdentityResult,
    QueueSnapshot,
    SongDetails,
)
from juice_lyrics.library.media import AudioMetadata
from juice_lyrics.services.metadata_audit import build_metadata_audit
from juice_lyrics.services.missing_library import CatalogueCoverage, MissingLibraryReport
from juice_lyrics.services.library_sync import (
    LibrarySyncResult,
    LibrarySyncOptions,
    LibrarySyncPlan,
    MatchOutcome,
    SyncLyricType,
    TrackSyncPlan,
    TrackSyncResult,
    SyncEvent,
    SyncEventKind,
)
from juice_lyrics.backup.manager import BackupRecord
from juice_lyrics.services.library_index_sync import LibraryIndexSyncResult
from juice_lyrics.lyrics.engine import LocalLyricLine
from juice_lyrics.services.lyrics_search import LyricsIndexEntry, LyricsSearchIndex
from juice_lyrics.services.settings_snapshot import (
    IntegrationSnapshot,
    IntegrationStatus,
    SettingsSnapshot,
)
from juice_lyrics.tui import JuiceLyricsApp
from juice_lyrics.tui.help import guide_text


def test_help_documents_offline_lyrics_search_key():
    text = guide_text()
    assert "f                       Search local lyrics offline" in text
    assert "Search Lyrics" in text


def test_lyrics_search_updates_navigates_selects_and_cancels(tmp_path):
    root = tmp_path / "music"
    root.mkdir()
    first_path = root / "Lucid Dreams.mp3"
    second_path = root / "Shadows Again.mp3"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    first = _track(root, first_path.name)
    second = _track(root, second_path.name)
    fingerprint = (1, 2, 3, 4, 5)
    index = LyricsSearchIndex(
        root,
        (
            LyricsIndexEntry(
                first.reference, first.path, first.title, fingerprint, None,
                (LocalLyricLine("I still see your shadows in my room", 102000, "lrc"),),
            ),
            LyricsIndexEntry(
                second.reference, second.path, second.title, fingerprint, None,
                (LocalLyricLine("Your shadows follow me", None, "embedded"),),
            ),
        ),
        reused_count=2,
    )

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, first, second),
            lyrics_search_provider=lambda settings, snapshot: index,
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            assert "f Search Lyrics" in _text(app, "#library-position")
            await pilot.press("f")
            dialog = app.screen
            await dialog._worker.wait()
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is screen
            assert "No files were changed" in _text(app, "#library-status")

            await pilot.press("f")
            dialog = app.screen
            await dialog._worker.wait()
            dialog.query_one("#lyrics-search-query", Input).value = "SHADOWS"
            await pilot.pause()
            assert "01:42" in _text(app, "#lyrics-search-results")
            assert "I still see your shadows" in _text(app, "#lyrics-search-detail")
            await pilot.press("down", "enter")
            await pilot.pause()
            assert app.screen is screen
            assert screen.selected_track.reference == second.reference
            assert screen._details_mode is True
            assert "Opened Shadows Again" in _text(app, "#library-status")

    asyncio.run(scenario())


def test_sync_library_is_immediate_single_worker_and_navigation_stays_live(tmp_path):
    root = tmp_path / "music"
    track = _track(root, "Song.mp3", matched=False)
    started = Event()
    release = Event()
    calls = []
    ui_thread = get_ident()

    def sync(settings, *, previous_snapshot=None):
        calls.append((previous_snapshot, get_ident()))
        started.set()
        assert release.wait(timeout=5)
        return LibraryIndexSyncResult(_snapshot(root, track), new=1, identified=1)

    async def scenario():
        app = _app(
            tmp_path, lambda settings: _snapshot(root, track),
            library_index_sync_provider=sync,
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            assert "s Sync Library" in _text(app, "#library-position")
            await pilot.press("s", "s")
            assert await asyncio.to_thread(started.wait, 2)
            assert len(calls) == 1 and calls[0][1] != ui_thread
            assert app.screen.id == "screen-library"
            await pilot.press("question_mark")
            assert app.screen is not screen
            await pilot.press("escape", "4", "3")
            assert app.screen.id == "screen-library"
            release.set()
            await screen._index_sync_worker.wait()
            await pilot.pause()
            assert "1 newly matched" in _text(app, "#library-status")

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def _track(
    root: Path,
    name: str,
    *,
    matched: bool = True,
    lyric: LibraryLyricStatus = LibraryLyricStatus.SYNCED,
    lrc: LibraryLrcStatus = LibraryLrcStatus.PRESENT,
    state: LibraryStateStatus = LibraryStateStatus.CURRENT,
    warning: str | None = None,
    media_format: str = "MP3",
    synchronized_source: bool = False,
    identity_locked: bool = False,
    identity_source: str | None = None,
    verification_error: str | None = None,
    content_sha256: str | None = None,
    catalogue_id=None,
) -> LibraryTrack:
    path = root / name
    lrc_path = path.with_suffix(".lrc") if lrc is not LibraryLrcStatus.NONE else None
    return LibraryTrack(
        reference=name,
        path=path,
        relative_path=Path(name),
        filename=name,
        title=path.stem,
        duration_seconds=183.4,
        match_status=LibraryMatchStatus.MATCHED if matched else LibraryMatchStatus.UNMATCHED,
        matched_title=f"{path.stem} (catalogue)" if matched else None,
        lyric_status=lyric,
        lrc_status=lrc,
        lrc_path=lrc_path,
        state_status=state,
        warning=warning,
        media_format=media_format,
        synchronized_source=synchronized_source,
        identity_locked=identity_locked,
        identity_source=identity_source,
        verification_error=verification_error,
        content_sha256=content_sha256,
        catalogue_id=catalogue_id,
    )


def _snapshot(root: Path, *tracks: LibraryTrack, exists: bool = True, warnings=()) -> LibrarySnapshot:
    return LibrarySnapshot(root, exists, tracks, tuple(warnings))


def _plan(settings: Settings, tracks: tuple[TrackSyncPlan, ...]) -> LibrarySyncPlan:
    options = LibrarySyncOptions.from_settings(
        settings,
        dry_run=True,
        rmpc_enabled=True,
        lyrics_dir=None,
        state_file=Path(settings.music_dir).parent / "state.json",
    )
    return LibrarySyncPlan(options, tracks, {"files": {}})


def _app(tmp_path: Path, snapshot_provider, preview_provider=None, **providers) -> JuiceLyricsApp:
    settings = Settings(music_dir=tmp_path / "music")
    status = LibraryStatus(settings.music_dir, 0, 0, 0, 0, 0, 0, 0, ())
    return JuiceLyricsApp(
        settings,
        library_status_provider=lambda settings: status,
        queue_snapshot_provider=lambda: QueueSnapshot((), 0, 0, 0, 0, 0),
        catalogue_filters_provider=lambda *args, **kwargs: CatalogueFilterMetadata((), ()),
        library_snapshot_provider=snapshot_provider,
        library_identity_provider=providers.pop(
            "library_identity_provider",
            lambda settings, tracks: IdentityBackfillResult(
                len(tracks), 0, 0, len(tracks), 0
            ),
        ),
        library_preview_provider=preview_provider or (lambda settings, **kwargs: _plan(settings, ())),
        **providers,
    )


def _text(app: JuiceLyricsApp, selector: str) -> str:
    return str(app.query_one(selector).render())


async def _open_library(app: JuiceLyricsApp, pilot):
    await pilot.press("3")
    await pilot.pause()
    worker = app.screen._snapshot_worker
    if worker is not None:
        await worker.wait()
        await pilot.pause()
    return app.screen


def test_manual_match_search_navigation_lock_and_unlock_are_state_only(tmp_path):
    root = tmp_path / "music"
    base = _track(root, "Unknown.flac", matched=False, media_format="FLAC")
    selected: list[tuple[object, str]] = []
    searches: list[str] = []
    unlocked: list[str] = []
    current = {"locked": False, "song_id": None, "name": None}

    def snapshot(settings):
        return _snapshot(
            root,
            replace(
                base,
                match_status=(
                    LibraryMatchStatus.MATCHED
                    if current["song_id"] is not None
                    else LibraryMatchStatus.UNMATCHED
                ),
                matched_title=current["name"],
                identity_locked=bool(current["locked"]),
                identity_source="manual" if current["locked"] else None,
            ),
        )

    candidates = (
        CatalogueSearchResult(
            1, 10, "Unknown (v1)", "unreleased", "DRFL", "3:20",
            ("Juice WRLD",), (), None, LyricAvailability.NONE, False,
        ),
        CatalogueSearchResult(
            2, 20, "Unknown", "released", "DRFL", "3:00",
            ("Juice WRLD",), (), "Released/Album/Unknown.mp3",
            LyricAvailability.SYNCED, True,
        ),
    )

    def search(settings, query, **kwargs):
        searches.append(query)
        return CataloguePage(candidates, 1, 50, 2, None, None)

    def save(settings, track, *, song_id, api_name):
        selected.append((song_id, api_name))
        current.update(locked=True, song_id=song_id, name=api_name)
        return ManualIdentityResult(track.reference, song_id, api_name, True, True)

    def unlock(settings, track):
        unlocked.append(track.reference)
        current.update(locked=False, song_id=None, name=None)
        return ManualIdentityResult(track.reference, None, None, False, True)

    async def scenario():
        app = _app(
            tmp_path,
            snapshot,
            catalogue_search_provider=search,
            manual_identity_provider=save,
            manual_unlock_provider=unlock,
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("c")
            await pilot.pause()
            dialog = app.screen
            worker = dialog._search_worker
            if worker is not None:
                await worker.wait()
                await pilot.pause()
            assert "recording for this local file" in _text(app, "#manual-match-context")
            assert "Unknown (v1)" in _text(app, "#manual-match-results")
            assert "released" in _text(app, "#manual-match-results")

            await pilot.press("slash")
            query = app.query_one("#manual-match-query", Input)
            query.value = "Refined Unknown"
            await pilot.press("enter")
            await pilot.pause()
            worker = dialog._search_worker
            if worker is not None:
                await worker.wait()
                await pilot.pause()
            assert searches[-1] == "Refined Unknown"

            await pilot.press("down", "enter")
            await pilot.pause()
            worker = screen._manual_identity_worker
            if worker is not None:
                await worker.wait()
                await pilot.pause()
            if screen._snapshot_worker is not None:
                await screen._snapshot_worker.wait()
                await pilot.pause()
            assert selected == [(20, "Unknown")]
            assert "Manual (locked)" in _text(app, "#library-details")
            assert "saved and locked" in _text(app, "#library-status")

            await pilot.press("u")
            await pilot.pause()
            worker = screen._manual_identity_worker
            if worker is not None:
                await worker.wait()
                await pilot.pause()
            if screen._snapshot_worker is not None:
                await screen._snapshot_worker.wait()
                await pilot.pause()
            assert unlocked == ["Unknown.flac"]
            assert "Not identified" in _text(app, "#library-details")
            assert "unlocked and cleared" in _text(app, "#library-status")

            await pilot.press("c")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is screen
            assert selected == [(20, "Unknown")]

    asyncio.run(scenario())


def test_manual_match_empty_or_offline_search_leaves_identity_unchanged(tmp_path):
    root = tmp_path / "music"
    track = _track(root, "Unknown.m4a", matched=False, media_format="M4A")
    saves: list[object] = []

    async def run_case(search):
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, track),
            catalogue_search_provider=search,
            manual_identity_provider=lambda *args, **kwargs: saves.append(kwargs),
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("c")
            await pilot.pause()
            dialog = app.screen
            worker = dialog._search_worker
            if worker is not None:
                await worker.wait()
                await pilot.pause()
            text = _text(app, "#manual-match-results")
            assert "No usable catalogue candidates" in text or "unavailable" in text
            await pilot.press("enter", "escape")
            await pilot.pause()
            assert app.screen is screen

    asyncio.run(
        run_case(lambda *args, **kwargs: CataloguePage((), 1, 50, 0, None, None))
    )
    asyncio.run(
        run_case(
            lambda *args, **kwargs: (_ for _ in ()).throw(OSError("offline"))
        )
    )
    assert saves == []


def test_issues_opens_from_snapshot_without_rescan_or_api_and_reaches_manual_match(tmp_path):
    root = tmp_path / "music"
    unknown = _track(root, "Unknown.flac", matched=False, media_format="FLAC")
    invalid = _track(
        root,
        "Invalid.m4a",
        media_format="M4A",
        lrc=LibraryLrcStatus.INVALID,
        warning="Adjacent LRC has no timestamped lyric lines.",
    )
    snapshot_calls = []
    searches = []
    audio = tmp_path / "sentinel-audio"
    sidecar = tmp_path / "sentinel-lrc"
    audio.write_bytes(b"audio unchanged")
    sidecar.write_bytes(b"lrc unchanged")

    def snapshot(settings):
        snapshot_calls.append("snapshot")
        return _snapshot(root, unknown, invalid)

    def search(settings, query, **kwargs):
        searches.append(query)
        return CataloguePage((), 1, 50, 0, None, None)

    async def scenario():
        app = _app(tmp_path, snapshot, catalogue_search_provider=search)
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_library(app, pilot)
            assert "s Sync Library · a Issues" in _text(app, "#library-position")
            await pilot.press("a")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "LibraryIssuesDialog"
            assert snapshot_calls == ["snapshot"]
            assert searches == []
            assert "2 follow-ups" in _text(app, "#library-issues-summary")
            assert "Catalogue" in _text(app, "#library-issues-list")
            assert "Catalogue match unknown" in _text(app, "#library-issues-detail")

            await pilot.press("down")
            assert "Synchronized LRC is invalid" in _text(app, "#library-issues-detail")
            await pilot.press("up", "c")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "ManualMatchDialog"
            dialog = app.screen
            if dialog._search_worker is not None:
                await dialog._search_worker.wait()
                await pilot.pause()
            assert searches == ["Unknown"]
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is screen

    asyncio.run(scenario())
    assert audio.read_bytes() == b"audio unchanged"
    assert sidecar.read_bytes() == b"lrc unchanged"


def test_issues_empty_state_and_sync_replaces_health_immediately(tmp_path):
    root = tmp_path / "music"
    unknown = _track(root, "Song.mp3", matched=False)
    healthy = replace(
        unknown,
        match_status=LibraryMatchStatus.MATCHED,
        matched_title="Song",
    )
    broken = replace(
        healthy,
        lyric_status=LibraryLyricStatus.NONE,
        lrc_status=LibraryLrcStatus.NONE,
        lrc_path=None,
        verification_error="no managed lyrics frame",
    )
    sync_results = iter(
        (
            LibraryIndexSyncResult(_snapshot(root, healthy), identified=1),
            LibraryIndexSyncResult(_snapshot(root, broken)),
        )
    )

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, unknown),
            library_index_sync_provider=lambda settings, **kwargs: next(sync_results),
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            assert "1 follow-ups" in _text(app, "#library-summary")
            await pilot.press("s")
            if screen._index_sync_worker is not None:
                await screen._index_sync_worker.wait()
            await pilot.pause()
            assert "0 follow-ups · 0 errors" in _text(app, "#library-summary")
            await pilot.press("a")
            assert "No library issues found" in _text(app, "#library-issues-detail")
            await pilot.press("escape", "s")
            if screen._index_sync_worker is not None:
                await screen._index_sync_worker.wait()
            await pilot.pause()
            assert "1 follow-ups · 0 errors" in _text(app, "#library-summary")
            await pilot.press("a")
            assert "Optional lyrics" in _text(app, "#library-issues-detail")

    asyncio.run(scenario())


def test_duplicates_open_from_snapshot_without_rescan_api_or_mutation(tmp_path):
    root = tmp_path / "music"
    first = _track(root, "Album/Song.mp3", content_sha256="same", catalogue_id=1)
    second = _track(root, "Copy/Song.flac", media_format="FLAC", content_sha256="same", catalogue_id=1)
    snapshot_calls = []
    api_calls = []
    audio = tmp_path / "sentinel-audio"
    sidecar = tmp_path / "sentinel-lrc"
    audio.write_bytes(b"audio unchanged")
    sidecar.write_bytes(b"lrc unchanged")

    def snapshot(settings):
        snapshot_calls.append("snapshot")
        return _snapshot(root, first, second)

    async def scenario():
        app = _app(
            tmp_path,
            snapshot,
            catalogue_search_provider=lambda *args, **kwargs: api_calls.append(args),
        )
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_library(app, pilot)
            assert "d Duplicates" in _text(app, "#library-position")
            await pilot.press("d")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "LibraryDuplicatesDialog"
            assert snapshot_calls == ["snapshot"]
            assert api_calls == []
            assert "1 duplicate group" in _text(app, "#library-duplicates-summary")
            detail = _text(app, "#library-duplicates-detail")
            assert "Exact duplicate audio" in detail
            assert "same SHA-256" in detail
            assert "Album/Song.mp3" in detail and "Copy/Song.flac" in detail
            await pilot.press("question_mark")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "HelpScreen"
            await pilot.press("escape", "escape")
            assert app.screen is screen

    asyncio.run(scenario())
    assert audio.read_bytes() == b"audio unchanged"
    assert sidecar.read_bytes() == b"lrc unchanged"


def test_missing_library_loads_in_worker_filters_and_adds_to_existing_queue(tmp_path):
    root = tmp_path / "music"
    owned = _track(root, "Owned.mp3", catalogue_id=1)
    unknown = _track(root, "Unknown.flac", matched=False, media_format="FLAC")
    missing = CatalogueSearchResult(
        1, 2, "Missing (Live)", "released", "GBGR", "3:10",
        ("Juice WRLD",), (), "Compilation/Missing (Live).mp3",
        LyricAvailability.SYNCED, True,
    )
    loaded = Event()
    release = Event()
    calls = []

    def report(settings, snapshot):
        calls.append((snapshot, get_ident()))
        loaded.set()
        assert release.wait(timeout=5)
        return MissingLibraryReport(
            (missing,), frozenset({"1"}), 1, 2, 2, 1,
            CatalogueCoverage.COMPLETE,
        )

    planned = SimpleNamespace(plan=object(), message="Ready", ok=True)
    added = SimpleNamespace(plan=None, message="Added 1 song to the download queue.", ok=True)
    queue_calls = []

    def plan(settings, selections):
        queue_calls.append(("plan", selections))
        return planned

    def add(plan_value):
        queue_calls.append(("add", plan_value))
        return added

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, owned, unknown),
            missing_library_provider=report,
            queue_plan_provider=plan,
            queue_add_provider=add,
        )
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_library(app, pilot)
            assert "g Missing" in _text(app, "#library-position")
            await pilot.press("g")
            assert await asyncio.to_thread(loaded.wait, 2)
            await pilot.pause()
            assert app.screen.__class__.__name__ == "MissingLibraryDialog"
            assert calls[0][1] != get_ident()
            assert "Loading catalogue" in _text(app, "#missing-library-summary")
            release.set()
            await app.screen._load_worker.wait()
            await pilot.pause()
            summary = _text(app, "#missing-library-summary")
            assert "1 confirmed missing" in summary
            assert "1 local Unknown" in summary
            assert "Complete catalogue coverage" in summary
            assert "Missing (Live)" in _text(app, "#missing-library-list")
            await pilot.press("/"); await pilot.pause()
            await pilot.press("l", "i", "v", "e", "enter")
            assert "Missing (Live)" in _text(app, "#missing-library-list")
            await pilot.press("a")
            await app.screen._queue_worker.wait()
            await pilot.pause()
            assert queue_calls == [("plan", (missing,)), ("add", planned.plan)]
            assert "Added 1 song" in _text(app, "#missing-library-summary")
            await pilot.press("question_mark")
            assert app.screen.__class__.__name__ == "HelpScreen"
            await pilot.press("escape"); await pilot.pause(); await pilot.press("escape", "escape")
            assert app.screen is screen

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_missing_library_partial_and_offline_states_do_not_claim_completeness(tmp_path):
    root = tmp_path / "music"
    reports = iter((
        MissingLibraryReport((), frozenset(), 1, 3, 10, 1, CatalogueCoverage.PARTIAL, error="offline"),
        MissingLibraryReport((), frozenset(), 1, 0, None, 0, CatalogueCoverage.UNAVAILABLE, error="offline"),
    ))

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, _track(root, "Unknown.m4a", matched=False, media_format="M4A")),
            missing_library_provider=lambda settings, snapshot: next(reports),
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("g")
            await app.screen._load_worker.wait(); await pilot.pause()
            assert "Partial catalogue coverage" in _text(app, "#missing-library-summary")
            assert "No missing recordings can be confirmed" in _text(app, "#missing-library-list")
            await pilot.press("escape", "g")
            await app.screen._load_worker.wait(); await pilot.pause()
            assert "Catalogue unavailable" in _text(app, "#missing-library-summary")
            await pilot.press("escape")
            assert app.screen is screen

    asyncio.run(scenario())


def test_duplicate_navigation_probable_evidence_and_empty_state(tmp_path):
    root = tmp_path / "music"
    exact = (
        _track(root, "A/Exact.mp3", content_sha256="exact"),
        _track(root, "B/Exact.mp3", content_sha256="exact"),
    )
    probable = (
        _track(root, "A/Probable.flac", media_format="FLAC", content_sha256="a", catalogue_id=42),
        _track(root, "B/Probable.m4a", media_format="M4A", content_sha256="b", catalogue_id=42),
    )

    async def scenario():
        app = _app(tmp_path, lambda settings: _snapshot(root, *exact, *probable))
        async with app.run_test() as pilot:
            await _open_library(app, pilot)
            await pilot.press("d")
            assert "Exact duplicate audio" in _text(app, "#library-duplicates-detail")
            await pilot.press("down")
            detail = _text(app, "#library-duplicates-detail")
            assert "Probable duplicate recording" in detail
            assert "Same catalogue identity (42)" in detail
            await pilot.press("escape")

        empty = _app(tmp_path, lambda settings: _snapshot(root, exact[0]))
        async with empty.run_test() as pilot:
            await _open_library(empty, pilot)
            await pilot.press("d")
            assert "No duplicate recordings found" in _text(
                empty, "#library-duplicates-list"
            )

    asyncio.run(scenario())


def test_metadata_preview_is_backgrounded_cached_and_read_only(tmp_path):
    root = tmp_path / "music"
    track = _track(root, "Album/Track.flac", media_format="FLAC", catalogue_id=42)
    track = replace(track, artist=None, album=None, identity_locked=True)
    media = tmp_path / "sentinel-audio"
    sidecar = tmp_path / "sentinel-lrc"
    state = tmp_path / "sentinel-state"
    for path, data in (
        (media, b"audio"),
        (sidecar, b"lrc"),
        (state, b"state"),
    ):
        path.write_bytes(data)
    calls = []
    ui_thread = get_ident()
    details = SongDetails(
        1, 42, "Track", "released", "DRFL", "3:03",
        ("Juice WRLD",), (), "Released/Album/Track.mp3",
        LyricAvailability.SYNCED, None, None, False,
        album="Album", track_number="2",
    )

    def audit_provider(settings, selected, **kwargs):
        calls.append(get_ident())
        return build_metadata_audit(
            selected,
            AudioMetadata("Track", None, None, 183.4, None),
            details,
        )

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, track),
            metadata_audit_provider=audit_provider,
        )
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_library(app, pilot)
            assert "e Metadata" in _text(app, "#library-position")
            await pilot.press("e")
            worker = screen._metadata_audit_worker
            if worker is not None:
                await worker.wait()
            await pilot.pause()
            assert app.screen.__class__.__name__ == "MetadataAuditDialog"
            content = _text(app, "#metadata-audit-content")
            assert "Preview unavailable" not in content
            assert "Artist" in content and "Juice WRLD" in content
            assert "Track number" in content and "Confident" in content
            assert "Manual lock" in content
            await pilot.press("escape")
            assert app.screen is screen
            await pilot.press("e")
            await pilot.pause()
            assert app.screen.__class__.__name__ == "MetadataAuditDialog"
            assert len(calls) == 1

    asyncio.run(scenario())
    assert calls and calls[0] != ui_thread
    assert media.read_bytes() == b"audio"
    assert sidecar.read_bytes() == b"lrc"
    assert state.read_bytes() == b"state"


def test_metadata_issue_opens_preview_and_help_lists_action(tmp_path):
    root = tmp_path / "music"
    track = _track(
        root,
        "Missing Tags.m4a",
        matched=False,
        media_format="M4A",
        warning="M4A metadata is missing title, artist; track cannot be matched safely.",
        catalogue_id=7,
    )
    details = SongDetails(
        1, 7, "Missing Tags", "released", "GBGR", "3:00",
        ("Juice WRLD",), (), None, LyricAvailability.PLAIN,
        None, None, False, album=None, track_number=None,
    )

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, track),
            metadata_audit_provider=lambda settings, selected, **kwargs: build_metadata_audit(
                selected,
                AudioMetadata(None, None, None, 180.0),
                details,
            ),
        )
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("a")
            assert "e Metadata repair" in _text(app, "#library-issues-help")
            await pilot.press("e")
            worker = screen._metadata_audit_worker
            if worker is not None:
                await worker.wait()
            await pilot.pause()
            assert app.screen.__class__.__name__ == "MetadataAuditDialog"
            assert "Missing Tags" in _text(app, "#metadata-audit-content")
            await pilot.press("escape", "question_mark")
            await pilot.pause()
            assert "Review and apply selected metadata repairs" in _text(app, "#help-content")

    asyncio.run(scenario())


def test_metadata_apply_requires_explicit_fields_and_cancel_is_default(tmp_path):
    root = tmp_path / "music"
    track = replace(
        _track(root, "Album/Track.flac", media_format="FLAC", catalogue_id=42),
        artist=None,
        album="Local album",
    )
    details = SongDetails(
        1, 42, "Track", "released", "DRFL", "3:03",
        ("Juice WRLD",), (), "Released/Album/Track.mp3",
        LyricAvailability.PLAIN, None, None, False,
        album="Catalogue album", track_number=None,
    )
    audit = build_metadata_audit(
        track,
        AudioMetadata("Track", None, "Local album", 183.4, None),
        details,
    )
    planned = []
    executed = []

    def plan_provider(settings, selected_audit, fields):
        planned.append(fields)
        selected = tuple(
            proposal for proposal in selected_audit.proposals if proposal.field in fields
        )
        return SimpleNamespace(reference=track.reference, selected=selected)

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, track),
            metadata_audit_provider=lambda *args, **kwargs: audit,
            metadata_repair_plan_provider=plan_provider,
            metadata_repair_execution_provider=lambda *args, **kwargs: executed.append(args),
        )
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("e")
            if screen._metadata_audit_worker is not None:
                await screen._metadata_audit_worker.wait()
            await pilot.pause()
            content = _text(app, "#metadata-audit-content")
            assert "Confident recommendations" in content
            assert "Review carefully" in content
            assert "[ ] Artist" in content and "[ ] Album" in content
            assert "(missing) → Juice WRLD" in content

            await pilot.press("a")
            assert app.screen.__class__.__name__ == "MetadataAuditDialog"
            assert "Select at least one field" in _text(app, "#metadata-audit-help")
            assert planned == []

            await pilot.press("enter", "a")
            await pilot.pause()
            if screen._metadata_repair_plan_worker is not None:
                await screen._metadata_repair_plan_worker.wait()
            await pilot.pause()
            assert planned == [("artist",)]
            assert app.screen.__class__.__name__ == "MetadataRepairConfirmationDialog"
            confirmation = _text(app, "#library-dialog-body")
            assert "Artist: (missing) → Juice WRLD" in confirmation
            assert "complete audio backup" in confirmation

            await pilot.press("enter")
            await pilot.pause()
            assert app.screen is screen
            assert executed == []
            assert "cancelled" in _text(app, "#library-status").lower()

    asyncio.run(scenario())


def test_confirmed_metadata_apply_runs_once_in_background_and_refreshes(tmp_path):
    root = tmp_path / "music"
    track = replace(
        _track(root, "Album/Track.m4a", media_format="M4A", catalogue_id=42),
        artist=None,
    )
    details = SongDetails(
        1, 42, "Track", "released", "DRFL", "3:03",
        ("Juice WRLD",), (), None, LyricAvailability.PLAIN,
        None, None, False, album=None, track_number=None,
    )
    audit = build_metadata_audit(
        track, AudioMetadata("Track", None, None, 183.4, None), details
    )
    started = Event()
    release = Event()
    calls = []
    snapshot_calls = []
    ui_thread = get_ident()

    def snapshot_provider(settings):
        snapshot_calls.append(1)
        return _snapshot(root, track)

    def plan_provider(settings, selected_audit, fields):
        return SimpleNamespace(
            reference=track.reference,
            selected=tuple(
                proposal for proposal in selected_audit.proposals if proposal.field in fields
            ),
        )

    def execute_provider(plan, *, confirmed=False):
        calls.append((confirmed, get_ident()))
        started.set()
        assert release.wait(timeout=5)
        return SimpleNamespace(
            fields=tuple(proposal.field for proposal in plan.selected),
            backup_path=tmp_path / "backups/track.m4a",
        )

    async def scenario():
        app = _app(
            tmp_path,
            snapshot_provider,
            metadata_audit_provider=lambda *args, **kwargs: audit,
            metadata_repair_plan_provider=plan_provider,
            metadata_repair_execution_provider=execute_provider,
        )
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("e")
            if screen._metadata_audit_worker is not None:
                await screen._metadata_audit_worker.wait()
            await pilot.pause()
            await pilot.press("space", "a")
            await pilot.pause()
            if screen._metadata_repair_plan_worker is not None:
                await screen._metadata_repair_plan_worker.wait()
            await pilot.pause()
            await pilot.press("y", "enter")
            assert await asyncio.to_thread(started.wait, 2)
            assert len(calls) == 1
            assert calls[0][0] is True and calls[0][1] != ui_thread
            assert "Applying metadata repair" in _text(app, "#library-status")
            await pilot.press("question_mark")
            assert app.screen is not screen
            await pilot.press("escape")
            release.set()
            if screen._metadata_repair_worker is not None:
                await screen._metadata_repair_worker.wait()
            await pilot.pause()
            if screen._snapshot_worker is not None:
                await screen._snapshot_worker.wait()
            await pilot.pause()
            assert len(calls) == 1
            assert len(snapshot_calls) >= 2
            status = _text(app, "#library-status")
            assert "Metadata repaired" in status
            assert "Backup:" in status

    try:
        asyncio.run(scenario())
    finally:
        release.set()


@pytest.mark.parametrize(
    ("failure", "expected"),
    (
        (OSError("backup full"), "failed safely"),
        (RuntimeError("Library state changed during metadata repair."), "failed safely"),
        (
            RuntimeError("Metadata repair failed and automatic rollback failed: disk"),
            "needs recovery",
        ),
        (KeyboardInterrupt(), "failed safely"),
    ),
)
def test_metadata_apply_failures_are_reported_without_refresh(tmp_path, failure, expected):
    root = tmp_path / "music"
    track = replace(
        _track(root, "Track.mp3", catalogue_id=42), artist=None
    )
    details = SongDetails(
        1, 42, "Track", "released", "DRFL", "3:03",
        ("Juice WRLD",), (), None, LyricAvailability.PLAIN,
        None, None, False, album=None, track_number=None,
    )
    audit = build_metadata_audit(
        track, AudioMetadata("Track", None, None, 183.4, None), details
    )
    snapshot_calls = []

    def snapshot_provider(settings):
        snapshot_calls.append(1)
        return _snapshot(root, track)

    def plan_provider(settings, selected_audit, fields):
        return SimpleNamespace(
            reference=track.reference,
            selected=tuple(selected_audit.proposals),
        )

    def execute_provider(*args, **kwargs):
        raise failure

    async def scenario():
        app = _app(
            tmp_path,
            snapshot_provider,
            metadata_audit_provider=lambda *args, **kwargs: audit,
            metadata_repair_plan_provider=plan_provider,
            metadata_repair_execution_provider=execute_provider,
        )
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("e")
            if screen._metadata_audit_worker is not None:
                await screen._metadata_audit_worker.wait()
            await pilot.pause()
            await pilot.press("space", "a")
            await pilot.pause()
            if screen._metadata_repair_plan_worker is not None:
                await screen._metadata_repair_plan_worker.wait()
            await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            if screen._metadata_repair_worker is not None:
                await screen._metadata_repair_worker.wait()
            await pilot.pause()
            assert expected in _text(app, "#library-status").lower()
            assert len(snapshot_calls) == 1

    asyncio.run(scenario())


def test_library_replaces_placeholder_and_renders_summary_details_and_states(tmp_path):
    root = tmp_path / "music"
    synced = _track(root, "A Synced.mp3")
    plain = _track(
        root,
        "B Plain.mp3",
        lyric=LibraryLyricStatus.PLAIN,
        lrc=LibraryLrcStatus.NONE,
        state=LibraryStateStatus.CHANGED,
    )
    unmatched = _track(
        root,
        "C Unknown.mp3",
        matched=False,
        lyric=LibraryLyricStatus.NONE,
        lrc=LibraryLrcStatus.MISSING,
        state=LibraryStateStatus.NEW,
        warning="Recorded LRC is missing.",
    )

    async def scenario():
        app = _app(tmp_path, lambda settings: _snapshot(root, synced, plain, unmatched))
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_library(app, pilot)
            assert screen.__class__.__name__ == "LibraryScreen"
            summary = _text(app, "#library-summary")
            assert "3 tracks" in summary and "Catalogue unknown 1" in summary
            assert "2 follow-ups" in summary and "0 errors" in summary
            assert "MP3 3" in summary and "FLAC 0" in summary and "M4A 0" in summary
            rows = _text(app, "#library-tracks")
            assert "~" in rows and "!" not in rows
            assert rows.index("A Synced") < rows.index("B Plain") < rows.index("C Unknown")
            assert "Synced lyrics" in rows and "Plain lyrics" in rows and "No lyrics" in rows
            assert "LRC Present" in rows and "LRC Missing" in rows

            await pilot.press("down", "j")
            assert screen.selected_track.reference == unmatched.reference
            details = _text(app, "#library-details")
            assert "Catalogue match Unknown" in details and "No lyrics" in details
            assert "Library state  New" in details and "Library issue  New track" in details
            assert "Recorded LRC is missing" in details
            assert "Lyric maintenance preview" in details
            assert "Press l for this song or m for the library" in details
            await pilot.press("up", "k", "end", "home")
            assert screen.selected_track.reference == synced.reference

    asyncio.run(scenario())


def test_loading_empty_missing_and_provider_error_states(tmp_path):
    started = Event()
    release = Event()

    def slow(settings):
        started.set()
        release.wait(timeout=5)
        return _snapshot(Path(settings.music_dir))

    async def loading_scenario():
        app = _app(tmp_path, slow)
        async with app.run_test() as pilot:
            await pilot.press("3")
            await asyncio.to_thread(started.wait, 2)
            assert "Loading tracks" in _text(app, "#library-tracks")
            await pilot.press("4")
            assert app.screen.id == "screen-downloads"
            release.set()

    async def quit_scenario():
        quit_started = Event()
        quit_release = Event()

        def provider(settings):
            quit_started.set()
            quit_release.wait(timeout=5)
            return _snapshot(Path(settings.music_dir))

        app = _app(tmp_path, provider)
        async with app.run_test() as pilot:
            await pilot.press("3")
            await asyncio.to_thread(quit_started.wait, 2)
            # Search input keeps normal typing keys; leave it before quitting.
            await pilot.press("escape", "q")
            assert not app.is_running
            quit_release.set()

    async def states_scenario():
        root = tmp_path / "music"
        responses = [
            _snapshot(root),
            _snapshot(root, exists=False, warnings=(f"Music directory does not exist: {root}",)),
        ]
        app = _app(tmp_path, lambda settings: responses.pop(0))
        async with app.run_test() as pilot:
            await _open_library(app, pilot)
            assert "No supported audio tracks found" in _text(app, "#library-tracks")
            await pilot.press("r")
            await app.screen._snapshot_worker.wait()
            await pilot.pause()
            assert "does not exist" in _text(app, "#library-status")

        broken = _app(tmp_path, lambda settings: (_ for _ in ()).throw(OSError("permission denied")))
        async with broken.run_test() as pilot:
            await _open_library(broken, pilot)
            assert "Library unavailable: permission denied" in _text(broken, "#library-status")
            assert broken.screen.id == "screen-library"

    try:
        asyncio.run(loading_scenario())
        asyncio.run(quit_scenario())
        asyncio.run(states_scenario())
    finally:
        release.set()


def test_local_search_and_all_status_filters_do_not_rescan(tmp_path):
    root = tmp_path / "music"
    tracks = (
        _track(root, "Alpha Synced.mp3"),
        _track(root, "Beta Plain.mp3", lyric=LibraryLyricStatus.PLAIN, lrc=LibraryLrcStatus.NONE),
        _track(root, "Gamma None.mp3", matched=False, lyric=LibraryLyricStatus.NONE, lrc=LibraryLrcStatus.NONE),
    )
    calls = 0

    def provider(settings):
        nonlocal calls
        calls += 1
        return _snapshot(root, *tracks)

    async def scenario():
        app = _app(tmp_path, provider)
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("/")
            assert app.focused is app.query_one("#library-query", Input)
            app.query_one("#library-query", Input).value = "beta"
            await pilot.press("enter")
            assert screen.filtered_tracks == (tracks[1],)
            app.query_one("#library-query", Input).value = ""

            expected = {
                "matched": 2,
                "unmatched": 1,
                "synced": 1,
                "plain": 1,
                "no_lyrics": 1,
                "attention": 1,
                "all": 3,
            }
            for value, count in expected.items():
                app.query_one("#library-filter", Select).value = value
                await pilot.pause()
                assert len(screen.filtered_tracks) == count
            assert calls == 1

    asyncio.run(scenario())


def test_many_tracks_scroll_and_narrow_details_mode(tmp_path):
    root = tmp_path / "music"
    tracks = tuple(_track(root, f"Track {index:02}.mp3") for index in range(1, 31))

    async def scenario():
        app = _app(tmp_path, lambda settings: _snapshot(root, *tracks))
        async with app.run_test(size=(80, 24)) as pilot:
            screen = await _open_library(app, pilot)
            scroll = app.query_one("#library-tracks-scroll", VerticalScroll)
            assert screen.has_class("-library-narrow")
            assert scroll.size.height >= 5
            assert len(screen.filtered_tracks) == 30 and scroll.max_scroll_y > 0
            await pilot.press("end")
            await pilot.pause()
            assert screen.selected_track.reference == "Track 30.mp3"
            assert scroll.scroll_y > 0
            assert "Track 30 of 30" in _text(app, "#library-position")
            await pilot.press("home", "pagedown")
            assert 0 < screen.selected_index < 29
            await pilot.press("pageup")
            assert screen.selected_index == 0
            await pilot.press("enter")
            assert screen.has_class("-details-mode")
            await pilot.press("escape")
            assert not screen.has_class("-details-mode")

    asyncio.run(scenario())


def test_refresh_selection_stale_result_and_preview_invalidation(tmp_path):
    root = tmp_path / "music"
    first = _track(root, "First.mp3")
    keep = _track(root, "Keep.mp3")
    replacement = _track(root, "Replacement.mp3")
    stale_started = Event()
    release_stale = Event()
    calls = 0

    def provider(settings):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _snapshot(root, first, keep)
        if calls == 2:
            stale_started.set()
            release_stale.wait(timeout=5)
            return _snapshot(root, first)
        if calls == 3:
            return _snapshot(root, keep, replacement)
        return _snapshot(root, replacement)

    async def scenario():
        app = _app(tmp_path, provider)
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("down")
            assert screen.selected_track.reference == keep.reference
            screen.preview = _plan(app.settings, ())
            app.query_one("#library-preview").update("old preview")

            await pilot.press("r")
            await asyncio.to_thread(stale_started.wait, 2)
            await pilot.press("r")
            current = screen._snapshot_worker
            await current.wait()
            await pilot.pause()
            assert screen.selected_track.reference == keep.reference
            assert "Sync Library" in _text(app, "#library-preview")
            release_stale.set()
            await pilot.pause()
            assert "First.mp3" not in _text(app, "#library-tracks")

            await pilot.press("r")
            await screen._snapshot_worker.wait()
            await pilot.pause()
            assert screen.selected_track.reference == replacement.reference

    try:
        asyncio.run(scenario())
    finally:
        release_stale.set()


def test_refresh_backfills_unknown_identity_off_event_loop_and_updates_display(tmp_path):
    root = tmp_path / "music"
    unknown = _track(root, "Bandit.flac", matched=False, lyric=LibraryLyricStatus.PLAIN, media_format="FLAC")
    matched = _track(root, "Bandit.flac", matched=True, lyric=LibraryLyricStatus.PLAIN, media_format="FLAC")
    started = Event()
    release = Event()
    snapshot_calls = 0

    def snapshot(settings):
        nonlocal snapshot_calls
        snapshot_calls += 1
        return _snapshot(root, matched if snapshot_calls >= 3 else unknown)

    def identify(settings, tracks):
        assert tracks == (unknown,)
        started.set()
        release.wait(timeout=5)
        return IdentityBackfillResult(1, 0, 1, 0, 0)

    async def scenario():
        app = _app(
            tmp_path,
            snapshot,
            library_identity_provider=identify,
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("r")
            await screen._snapshot_worker.wait(); await pilot.pause()
            await asyncio.to_thread(started.wait, 2)
            assert "Identifying 1 catalogue entry" in _text(app, "#library-status")
            await pilot.press("4")
            assert app.screen.id == "screen-downloads"
            release.set()
            await screen._identity_worker.wait(); await pilot.pause()
            await pilot.press("3"); await pilot.pause()
            if screen._snapshot_worker is not None:
                await screen._snapshot_worker.wait(); await pilot.pause()
            assert screen.selected_track.match_status is LibraryMatchStatus.MATCHED
            assert "Catalogue identification complete · 1 song identified" in _text(app, "#library-status")

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_refresh_catalogue_failure_keeps_healthy_local_coverage_visible(tmp_path):
    root = tmp_path / "music"
    track = _track(
        root,
        "Bandit.flac",
        matched=False,
        lyric=LibraryLyricStatus.PLAIN,
        media_format="FLAC",
    )

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, track),
            library_identity_provider=lambda settings, tracks: IdentityBackfillResult(
                1, 0, 0, 0, 1, ("offline",)
            ),
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("r")
            await screen._snapshot_worker.wait(); await pilot.pause()
            identity_worker = screen._identity_worker
            if identity_worker is not None:
                await identity_worker.wait()
            await pilot.pause()
            assert "Catalogue identification unavailable" in _text(app, "#library-status")
            assert "Fully covered 1" in _text(app, "#library-summary")
            assert "1 follow-ups" in _text(app, "#library-summary")
            assert "Catalogue match Unknown" in _text(app, "#library-details")

    asyncio.run(scenario())


def test_sync_preview_is_explicit_nonblocking_structured_and_handles_errors(tmp_path):
    root = tmp_path / "music"
    tracks = (
        _track(root, "Current.mp3"),
        _track(root, "Synced.mp3", state=LibraryStateStatus.NEW),
        _track(root, "Plain.mp3", lyric=LibraryLyricStatus.NONE, lrc=LibraryLrcStatus.NONE),
        _track(root, "Unknown.mp3", matched=False, lyric=LibraryLyricStatus.NONE, lrc=LibraryLrcStatus.NONE),
    )
    started = Event()
    release = Event()
    calls = 0

    def preview(settings):
        nonlocal calls
        calls += 1
        started.set()
        release.wait(timeout=5)
        return _plan(settings, (
            TrackSyncPlan(tracks[0].path, MatchOutcome.UNCHANGED, SyncLyricType.NONE),
            TrackSyncPlan(tracks[1].path, MatchOutcome.MATCHED, SyncLyricType.SYNCED, {"name": "Synced API"}),
            TrackSyncPlan(tracks[2].path, MatchOutcome.MATCHED, SyncLyricType.PLAIN, {"name": "Plain API"}),
            TrackSyncPlan(tracks[3].path, MatchOutcome.UNRESOLVED, SyncLyricType.NONE),
        ))

    async def scenario():
        app = _app(tmp_path, lambda settings: _snapshot(root, *tracks), preview)
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            assert calls == 0
            screen.generate_preview()
            await asyncio.to_thread(started.wait, 2)
            assert "Checking library needs" in _text(app, "#library-preview")
            await pilot.press("4")
            assert app.screen.id == "screen-downloads"
            await pilot.press("3")
            release.set()
            await screen._preview_worker.wait()
            await pilot.pause()
            preview_text = _text(app, "#library-preview")
            assert "Preview only — no files changed" in preview_text
            assert "Current 1" in preview_text and "Update 2" in preview_text
            assert "Synced 1" in preview_text and "Plain 1" in preview_text and "LRC 1" in preview_text
            assert "LRC beside each song" in preview_text
            await pilot.press("down")
            assert "Would update lyrics · Synced lyrics · Synced API" in _text(app, "#library-details")

        broken = _app(
            tmp_path,
            lambda settings: _snapshot(root, *tracks),
            lambda settings: (_ for _ in ()).throw(RuntimeError("API unavailable")),
        )
        async with broken.run_test() as pilot:
            await _open_library(broken, pilot)
            broken.screen.generate_preview()
            await broken.screen._preview_worker.wait()
            await pilot.pause()
            assert "Preview failed: API unavailable" in _text(broken, "#library-preview")
            assert broken.screen.id == "screen-library"

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_newer_preview_supersedes_stale_and_empty_preview_is_clear(tmp_path):
    root = tmp_path / "music"
    track = _track(root, "Track.mp3")
    stale_started = Event()
    release_stale = Event()
    calls = 0

    def provider(settings):
        nonlocal calls
        calls += 1
        if calls == 1:
            stale_started.set()
            release_stale.wait(timeout=5)
            return _plan(settings, (TrackSyncPlan(track.path, MatchOutcome.FAILED, SyncLyricType.NONE, error="stale"),))
        return _plan(settings, ())

    async def scenario():
        app = _app(tmp_path, lambda settings: _snapshot(root, track), provider)
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            screen.generate_preview()
            await asyncio.to_thread(stale_started.wait, 2)
            screen.generate_preview()
            current = screen._preview_worker
            await current.wait()
            await pilot.pause()
            text = _text(app, "#library-preview")
            assert "Current 0 · Update 0" in text
            assert "Preview only — no files changed" in text
            release_stale.set()
            await pilot.pause()
            assert "stale" not in _text(app, "#library-preview")

    try:
        asyncio.run(scenario())
    finally:
        release_stale.set()


def test_library_screen_never_calls_mutating_systems(tmp_path, monkeypatch):
    import juice_lyrics.backup.manager as backup
    import juice_lyrics.lyrics.engine as lyrics
    import juice_lyrics.rmpc.integration as rmpc
    import juice_lyrics.services.library_sync as sync_service
    import juice_lyrics.state as state

    def mutation(*args, **kwargs):
        raise AssertionError("mutation attempted")

    monkeypatch.setattr(sync_service, "execute_library_sync", mutation)
    monkeypatch.setattr(lyrics, "embed_lyrics", mutation)
    monkeypatch.setattr(backup, "backup_file", mutation)
    monkeypatch.setattr(state, "save_state", mutation)
    monkeypatch.setattr(rmpc, "notify_rmpc_index", mutation)
    root = tmp_path / "music"
    track = _track(root, "Read Only.mp3")

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, track),
            lambda settings: _plan(settings, (TrackSyncPlan(track.path, MatchOutcome.UNCHANGED, SyncLyricType.NONE),)),
        )
        async with app.run_test() as pilot:
            await _open_library(app, pilot)
            await pilot.press("/", "enter", "down", "up")
            app.screen.generate_preview()
            await app.screen._preview_worker.wait()
            await pilot.pause()
            await pilot.press("r")
            await app.screen._snapshot_worker.wait()

    asyncio.run(scenario())
    assert not list(tmp_path.rglob("*.mp3"))
    assert not list(tmp_path.rglob("*.lrc"))
    assert not list(tmp_path.rglob("*.json"))


def test_library_summary_is_format_aware_and_flac_m4a_can_be_fully_covered(tmp_path):
    root = tmp_path / "music"
    tracks = (
        _track(root, "One.mp3", synchronized_source=True),
        _track(root, "Two.flac", lyric=LibraryLyricStatus.PLAIN, media_format="FLAC", synchronized_source=True),
        _track(root, "Three.m4a", lyric=LibraryLyricStatus.PLAIN, media_format="M4A", synchronized_source=True),
    )

    async def scenario():
        app = _app(tmp_path, lambda settings: _snapshot(root, *tracks))
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            summary = _text(app, "#library-summary")
            assert "Fully covered 3" in summary
            assert "0 follow-ups" in summary and "0 errors" in summary
            assert "MP3 1" in summary and "FLAC 1" in summary and "M4A 1" in summary
            await pilot.press("down")
            assert "Coverage       Fully covered" in _text(app, "#library-details")
            assert screen.selected_track.media_format == "FLAC"

    asyncio.run(scenario())


def test_healthy_unmatched_flac_is_covered_without_lyric_attention(tmp_path):
    root = tmp_path / "music"
    track = _track(
        root,
        "Bandit (with YoungBoy Never Broke Again).flac",
        matched=False,
        lyric=LibraryLyricStatus.PLAIN,
        media_format="FLAC",
        state=LibraryStateStatus.CURRENT,
    )
    preview_calls = []

    def preview(settings, **kwargs):
        preview_calls.append(kwargs)
        return _plan(settings, (TrackSyncPlan(track.path, MatchOutcome.UNCHANGED, SyncLyricType.NONE),))

    async def scenario():
        app = _app(tmp_path, lambda settings: _snapshot(root, track), preview)
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_library(app, pilot)
            summary = _text(app, "#library-summary")
            assert "Fully covered 1" in summary
            assert "1 follow-ups" in summary
            assert "Catalogue unknown 1" in summary
            details = _text(app, "#library-details")
            assert "Catalogue match Unknown" in details
            assert "External LRC   Present" in details
            assert "Coverage       Fully covered" in details
            assert "Library issue  Catalogue match unknown" in details
            assert "Automatic refresh requires a catalogue match" in details

            await pilot.press("m")
            await screen._preview_worker.wait(); await pilot.pause()
            assert preview_calls == [{"protected_paths": (track.path,)}]
            assert "up to date" in _text(app, "#library-status")

    asyncio.run(scenario())


def test_maintenance_preview_is_cancel_first_then_uses_shared_executor_with_progress(tmp_path):
    root = tmp_path / "music"
    track = _track(root, "Bandit.mp3", lyric=LibraryLyricStatus.NONE, lrc=LibraryLrcStatus.NONE)
    plan = _plan(
        Settings(music_dir=root),
        (TrackSyncPlan(track.path, MatchOutcome.MATCHED, SyncLyricType.SYNCED, {"name": "Bandit"}),),
    )
    executions = []

    def execute(received, *, progress):
        executions.append(received)
        progress(SyncEvent(SyncEventKind.TRACK_COMPLETED, path=track.path))
        return LibrarySyncResult(
            received,
            (TrackSyncResult(track.path, MatchOutcome.MATCHED, SyncLyricType.SYNCED, updated=True),),
            1, 0, 0, 1, 1, tmp_path / "backup",
        )

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, track),
            lambda settings, **kwargs: plan,
            library_execution_provider=execute,
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("m")
            await screen._preview_worker.wait(); await pilot.pause()
            assert app.screen.__class__.__name__ == "MaintenanceDialog"
            assert "No changes have been made" in _text(app, "#library-dialog-body")
            await pilot.press("enter")
            assert not executions
            assert "cancelled" in _text(app, "#library-status")

            await pilot.press("m")
            await screen._preview_worker.wait(); await pilot.pause()
            await pilot.press("y")
            await pilot.pause()
            assert executions == [plan]
            if screen._snapshot_worker is not None:
                await screen._snapshot_worker.wait(); await pilot.pause()
            assert "Library updated · 1 song updated" in _text(app, "#library-status")

    asyncio.run(scenario())


def test_selected_lyric_refresh_scopes_preview_and_cancel_changes_nothing(tmp_path):
    root = tmp_path / "music"
    track = _track(root, "Selected.flac", lyric=LibraryLyricStatus.PLAIN, media_format="FLAC")
    calls = []

    def preview(settings, **kwargs):
        calls.append(kwargs)
        return _plan(settings, (TrackSyncPlan(track.path, MatchOutcome.MATCHED, SyncLyricType.PLAIN),))

    async def scenario():
        app = _app(tmp_path, lambda settings: _snapshot(root, track), preview)
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("l")
            await screen._preview_worker.wait(); await pilot.pause()
            assert calls == [{"refresh": True, "selected_paths": (track.path,)}]
            assert app.screen.__class__.__name__ == "MaintenanceDialog"
            await pilot.press("escape")
            assert "cancelled" in _text(app, "#library-status")

    asyncio.run(scenario())


def test_verify_is_read_only_and_populates_attention_filter(tmp_path):
    root = tmp_path / "music"
    healthy = _track(root, "Healthy.mp3", synchronized_source=True)
    problem = _track(root, "Problem.m4a", matched=False, lyric=LibraryLyricStatus.NONE, lrc=LibraryLrcStatus.NONE, media_format="M4A")
    calls = 0

    def snapshot(settings):
        nonlocal calls
        calls += 1
        return _snapshot(root, healthy, problem)

    async def scenario():
        app = _app(tmp_path, snapshot)
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("v")
            await screen._snapshot_worker.wait(); await pilot.pause()
            assert calls == 2
            assert "Verification complete" in _text(app, "#library-status")
            assert screen.filtered_tracks == (problem,)
            assert not list(tmp_path.rglob("*.lrc"))

    asyncio.run(scenario())


def test_backup_browser_orders_valid_records_and_restore_is_cancel_first(tmp_path):
    root = tmp_path / "music"
    old = tmp_path / "backups" / "old"; new = tmp_path / "backups" / "new"
    old.mkdir(parents=True); new.mkdir(parents=True)
    (old / "old.mp3").write_bytes(b"old"); (new / "new.flac").write_bytes(b"new")
    records = (
        BackupRecord(old, datetime(2026, 1, 1, tzinfo=timezone.utc)),
        BackupRecord(new, datetime(2026, 2, 1, tzinfo=timezone.utc)),
    )
    restores = []

    def restore(backup, music):
        restores.append((backup, music)); return 1

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root),
            backup_provider=lambda: records,
            restore_provider=restore,
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("b"); await pilot.pause(0.1)
            body = _text(app, "#library-dialog-body")
            assert body.index("2026-02-01") < body.index("2026-01-01")
            await pilot.press("r"); await pilot.pause()
            assert app.screen.__class__.__name__ == "RestoreDialog"
            await pilot.press("enter"); await pilot.pause(0.2)
            assert not restores
            assert screen._backup_worker is None
            await pilot.press("b"); await pilot.pause(0.1)
            assert app.screen.__class__.__name__ == "BackupBrowser"
            await pilot.press("r"); await pilot.pause()
            assert app.screen.__class__.__name__ == "RestoreDialog"
            await pilot.press("y")
            await pilot.pause(0.1)
            assert app.screen.__class__.__name__ == "LibraryScreen"
            assert restores == [(new, root)]

    asyncio.run(scenario())


def test_rmpc_check_is_read_only_and_setup_requires_explicit_confirmation(tmp_path):
    root = tmp_path / "music"
    config = tmp_path / "rmpc.ron"
    integration = IntegrationSnapshot(
        IntegrationStatus.DETECTED_NOT_CONFIGURED,
        Path("/usr/bin/rmpc"),
        config,
        True,
        False,
        "rmpc is detected, but sidecar lyrics are not configured.",
    )
    settings_snapshot = SettingsSnapshot(config, False, (), (), integration, "1.4.0", ())
    setups = []

    def setup(path, music):
        setups.append((path, music)); return path.with_suffix(".bak")

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root),
            settings_snapshot_provider=lambda settings: settings_snapshot,
            rmpc_setup_provider=setup,
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("p"); await pilot.pause(0.1)
            assert "may update its configuration" in _text(app, "#library-dialog-body")
            await pilot.press("enter"); await pilot.pause(0.2)
            assert not setups
            assert screen._rmpc_worker is None
            await pilot.press("p"); await pilot.pause(0.1)
            assert app.screen.__class__.__name__ == "RmpcDialog"
            await pilot.press("y")
            await pilot.pause(0.1)
            assert app.screen.__class__.__name__ == "LibraryScreen"
            assert setups == [(config, root)]

    asyncio.run(scenario())


def test_restore_failure_is_reported_safely_without_refreshing_library(tmp_path):
    root = tmp_path / "music"
    backup = tmp_path / "backups" / "run"
    backup.mkdir(parents=True)
    (backup / "song.m4a").write_bytes(b"backup")
    record = BackupRecord(backup, datetime(2026, 3, 1, tzinfo=timezone.utc))
    scans = 0

    def snapshot(settings):
        nonlocal scans
        scans += 1
        return _snapshot(root)

    def fail_restore(*args):
        raise OSError("destination is read-only")

    async def scenario():
        app = _app(
            tmp_path,
            snapshot,
            backup_provider=lambda: (record,),
            restore_provider=fail_restore,
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("b"); await pilot.pause(0.1)
            await pilot.press("r"); await pilot.pause()
            await pilot.press("y"); await pilot.pause(0.1)
            assert "Restore failed safely: destination is read-only" in _text(app, "#library-status")
            assert scans == 1
            assert screen.snapshot is not None

    asyncio.run(scenario())


def test_identity_rebuild_is_cancel_first_and_executes_off_event_loop(tmp_path):
    root = tmp_path / "music"
    track = _track(root, "10 Feet.flac", media_format="FLAC", lyric=LibraryLyricStatus.PLAIN)
    settings = Settings(music_dir=root)
    state_file = tmp_path / "state.json"
    plan = IdentityRebuildPlan(
        settings,
        state_file,
        "digest",
        {"files": {track.reference: {"song_id": 96383, "api_name": "10 Feet"}}},
        (track,),
        (),
        1,
    )
    result = IdentityRebuildResult(
        1,
        1,
        0,
        1,
        0,
        0,
        0,
        (IdentityChange(track.relative_path, 96383, "10 Feet", 94102, "10 Feet"),),
        (),
        tmp_path / "state.backup",
    )
    main_thread = get_ident()
    plan_threads = []
    execution_threads = []
    execution_release = Event()

    def prepare(settings):
        plan_threads.append(get_ident())
        return plan

    def execute(value, *, progress):
        execution_threads.append(get_ident())
        execution_release.wait(timeout=2)
        progress(IdentityRebuildProgress(1, 1, track.path, "matched"))
        return result

    async def scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(root, track),
            identity_rebuild_plan_provider=prepare,
            identity_rebuild_execution_provider=execute,
        )
        async with app.run_test() as pilot:
            screen = await _open_library(app, pilot)
            await pilot.press("i")
            await pilot.pause(0.1)
            assert app.screen.__class__.__name__ == "IdentityRebuildDialog"
            assert "Audio and lyrics will not be modified" in _text(app, "#library-dialog-body")
            await pilot.press("enter"); await pilot.pause()
            assert app.screen is screen
            assert not execution_threads
            assert "cancelled" in _text(app, "#library-status")

            await pilot.press("i")
            await pilot.pause(0.1)
            await pilot.press("y"); await pilot.pause()
            worker = screen._identity_rebuild_worker
            assert worker is not None
            execution_release.set()
            await worker.wait(); await pilot.pause()
            if screen._snapshot_worker is not None:
                await screen._snapshot_worker.wait(); await pilot.pause()
            assert "Catalogue rebuild complete" in _text(app, "#library-status")

    asyncio.run(scenario())
    assert plan_threads and all(thread != main_thread for thread in plan_threads)
    assert execution_threads and all(thread != main_thread for thread in execution_threads)

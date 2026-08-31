import asyncio
from pathlib import Path
import sys
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from textual.containers import VerticalScroll
from textual.widgets import Input, Select

from juice_lyrics.config.settings import Settings
from juice_lyrics.services import (
    CatalogueFilterMetadata,
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibrarySnapshot,
    LibraryStateStatus,
    LibraryStatus,
    LibraryTrack,
    QueueSnapshot,
)
from juice_lyrics.services.library_sync import (
    LibrarySyncOptions,
    LibrarySyncPlan,
    MatchOutcome,
    SyncLyricType,
    TrackSyncPlan,
)
from juice_lyrics.tui import JuiceLyricsApp


def _track(
    root: Path,
    name: str,
    *,
    matched: bool = True,
    lyric: LibraryLyricStatus = LibraryLyricStatus.SYNCED,
    lrc: LibraryLrcStatus = LibraryLrcStatus.PRESENT,
    state: LibraryStateStatus = LibraryStateStatus.CURRENT,
    warning: str | None = None,
) -> LibraryTrack:
    path = root / name
    lrc_path = root.parent / "lyrics" / f"{path.stem}.lrc" if lrc is not LibraryLrcStatus.NONE else None
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
    )


def _snapshot(root: Path, *tracks: LibraryTrack, exists: bool = True, warnings=()) -> LibrarySnapshot:
    return LibrarySnapshot(root, exists, tracks, tuple(warnings))


def _plan(settings: Settings, tracks: tuple[TrackSyncPlan, ...]) -> LibrarySyncPlan:
    options = LibrarySyncOptions.from_settings(
        settings,
        dry_run=True,
        rmpc_enabled=True,
        lyrics_dir=Path(settings.music_dir).parent / "lyrics",
        state_file=Path(settings.music_dir).parent / "state.json",
    )
    return LibrarySyncPlan(options, tracks, {"files": {}})


def _app(tmp_path: Path, snapshot_provider, preview_provider=None) -> JuiceLyricsApp:
    settings = Settings(music_dir=tmp_path / "music")
    status = LibraryStatus(settings.music_dir, 0, 0, 0, 0, 0, 0, 0, ())
    return JuiceLyricsApp(
        settings,
        library_status_provider=lambda settings: status,
        queue_snapshot_provider=lambda: QueueSnapshot((), 0, 0, 0, 0, 0),
        catalogue_filters_provider=lambda *args, **kwargs: CatalogueFilterMetadata((), ()),
        library_snapshot_provider=snapshot_provider,
        library_preview_provider=preview_provider or (lambda settings: _plan(settings, ())),
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
            assert "MP3 tracks 3" in summary and "Matched 2" in summary and "Unmatched 1" in summary
            assert "Synced 1" in summary and "Plain 1" in summary and "No lyrics 1" in summary
            assert "LRC 1" in summary and "Attention 2" in summary
            rows = _text(app, "#library-tracks")
            assert rows.index("A Synced") < rows.index("B Plain") < rows.index("C Unknown")
            assert "Synced lyrics" in rows and "Plain lyrics" in rows and "No lyrics" in rows
            assert "LRC Present" in rows and "LRC Missing" in rows

            await pilot.press("down", "j")
            assert screen.selected_track.reference == unmatched.reference
            details = _text(app, "#library-details")
            assert "Unmatched" in details and "No lyrics" in details
            assert "Library state  New" in details and "Attention      Yes" in details
            assert "Recorded LRC is missing" in details
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
            await pilot.press("q")
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
            assert "No MP3 tracks found" in _text(app, "#library-tracks")
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
            assert "Preview not generated" in _text(app, "#library-preview")
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
            await pilot.press("s")
            await asyncio.to_thread(started.wait, 2)
            assert "Generating sync preview" in _text(app, "#library-preview")
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
            assert f"LRC dir {screen.preview.options.lyrics_dir}" in preview_text
            await pilot.press("down")
            assert "Would update lyrics · Synced lyrics · Synced API" in _text(app, "#library-details")

        broken = _app(
            tmp_path,
            lambda settings: _snapshot(root, *tracks),
            lambda settings: (_ for _ in ()).throw(RuntimeError("API unavailable")),
        )
        async with broken.run_test() as pilot:
            await _open_library(broken, pilot)
            await pilot.press("s")
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
            await pilot.press("s")
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
            await pilot.press("/", "enter", "down", "up", "s")
            await app.screen._preview_worker.wait()
            await pilot.pause()
            await pilot.press("r")
            await app.screen._snapshot_worker.wait()

    asyncio.run(scenario())
    assert not list(tmp_path.rglob("*.mp3"))
    assert not list(tmp_path.rglob("*.lrc"))
    assert not list(tmp_path.rglob("*.json"))

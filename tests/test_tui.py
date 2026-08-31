import asyncio
from pathlib import Path
import re
import sys
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.services import CatalogueFilterMetadata, LibraryStatus, QueueSnapshot
from juice_lyrics.tui import JuiceLyricsApp
from juice_lyrics.tui.screens.base import NavigationItem
from textual.widgets import Button, Static


def _library_status(tmp_path: Path, **changes) -> LibraryStatus:
    values = {
        "library_path": tmp_path / "music",
        "track_count": 4,
        "embedded_synced_count": 2,
        "embedded_plain_count": 1,
        "missing_or_invalid_count": 1,
        "rmpc_lrc_count": 2,
        "new_or_changed_count": 1,
        "backup_count": 3,
        "warnings": (),
    }
    values.update(changes)
    return LibraryStatus(**values)


def _queue_snapshot(**changes) -> QueueSnapshot:
    values = {
        "jobs": (),
        "total_job_count": 5,
        "active_job_count": 1,
        "pending_job_count": 1,
        "completed_job_count": 2,
        "failed_job_count": 1,
    }
    values.update(changes)
    return QueueSnapshot(**values)


def _app(tmp_path: Path, *, library=None, queue=None) -> JuiceLyricsApp:
    return JuiceLyricsApp(
        Settings(music_dir=tmp_path / "music"),
        library_status_provider=library or (lambda settings: _library_status(tmp_path)),
        queue_snapshot_provider=queue or _queue_snapshot,
        catalogue_filters_provider=lambda *args, **kwargs: CatalogueFilterMetadata((), ()),
    )


def _rendered(app: JuiceLyricsApp, selector: str) -> str:
    return str(app.query_one(selector).render())


def test_app_starts_renders_injected_snapshots_and_exits(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.screen.id == "screen-dashboard"
            library = _rendered(app, "#library-data")
            queue = _rendered(app, "#queue-data")
            assert str(tmp_path / "music") in library
            assert "MP3 tracks           4" in library
            assert "Synced lyrics        2" in library
            assert "Plain lyrics         1" in library
            assert "Missing / invalid    1" in library
            assert "New / changed        1" in library
            assert "Backups              3" in library
            assert "rmpc LRC files       2" in library
            assert "Total jobs           5" in queue
            assert "Pending              1" in queue
            assert "Active               1" in queue
            assert "Completed            2" in queue
            assert "Failed               1" in queue

    asyncio.run(scenario())


def test_dashboard_renders_empty_library_and_queue(tmp_path):
    async def scenario():
        app = _app(
            tmp_path,
            library=lambda settings: _library_status(
                tmp_path,
                track_count=0,
                embedded_synced_count=0,
                embedded_plain_count=0,
                missing_or_invalid_count=0,
                rmpc_lrc_count=0,
                new_or_changed_count=0,
                backup_count=0,
            ),
            queue=lambda: _queue_snapshot(
                total_job_count=0,
                active_job_count=0,
                pending_job_count=0,
                completed_job_count=0,
                failed_job_count=0,
            ),
        )
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "MP3 tracks           0" in _rendered(app, "#library-data")
            assert "Total jobs           0" in _rendered(app, "#queue-data")

    asyncio.run(scenario())


def test_refresh_calls_both_services_again(tmp_path):
    calls = {"library": 0, "queue": 0}

    def library(settings):
        calls["library"] += 1
        return _library_status(tmp_path, track_count=calls["library"])

    def queue():
        calls["queue"] += 1
        return _queue_snapshot(total_job_count=calls["queue"])

    async def scenario():
        app = _app(tmp_path, library=library, queue=queue)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert calls == {"library": 1, "queue": 1}
            await pilot.press("r")
            await pilot.pause()
            assert calls == {"library": 2, "queue": 2}
            assert "MP3 tracks           2" in _rendered(app, "#library-data")
            assert "Total jobs           2" in _rendered(app, "#queue-data")

    asyncio.run(scenario())


def test_keyboard_navigation_reaches_all_functional_screens(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2")
            await pilot.pause()
            assert app.screen.id == "screen-browse"
            assert app.query_one("#browse-query") is not None
            await pilot.press("3")
            await pilot.pause()
            assert app.screen.id == "screen-library"
            assert app.query_one("#library-tracks") is not None
            await pilot.press("5")
            await pilot.pause()
            assert app.screen.id == "screen-settings"
            assert app.query_one("#settings-configuration") is not None
            await pilot.press("4")
            await pilot.pause()
            assert app.screen.id == "screen-downloads"
            assert app.query_one("#download-queue") is not None
            await pilot.press("1")
            await pilot.pause()
            assert app.screen.id == "screen-dashboard"

    asyncio.run(scenario())


def test_navigation_buttons_are_excluded_from_tab_focus(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("tab")
            assert app.focused is None
            assert all(not item.can_focus for item in app.query("#primary-navigation NavigationItem"))

    asyncio.run(scenario())


def test_click_navigation_switches_and_active_indicator_follows_screen(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#nav-dashboard").has_class("-current")
            assert "[1 Dashboard]" in _rendered(app, "#nav-dashboard")
            assert "2 Browse" in _rendered(app, "#nav-browse")
            assert "[2 Browse]" not in _rendered(app, "#nav-browse")
            await pilot.click("#nav-browse")
            await pilot.pause()
            assert app.screen.id == "screen-browse"
            assert app.query_one("#nav-browse").has_class("-current")
            assert not app.query_one("#nav-dashboard").has_class("-current")
            assert "[2 Browse]" in _rendered(app, "#nav-browse")
            assert "[1 Dashboard]" not in _rendered(app, "#nav-dashboard")
            assert app.focused is app.query_one("#browse-query")

    asyncio.run(scenario())


def test_initial_shell_and_navigation_are_responsive_during_slow_load(tmp_path):
    started = Event()
    release = Event()

    def slow_library(settings):
        started.set()
        assert release.wait(timeout=5)
        return _library_status(tmp_path)

    async def scenario():
        app = _app(tmp_path, library=slow_library)
        async with app.run_test() as pilot:
            await asyncio.to_thread(started.wait, 2)
            assert "Loading library status" in _rendered(app, "#library-data")
            assert app.screen.id == "screen-dashboard"

            await pilot.press("2")
            await pilot.pause()
            assert app.screen.id == "screen-browse"
            await pilot.press("1")
            await pilot.pause()
            assert app.screen.id == "screen-dashboard"

            worker = app.screen._refresh_worker
            assert worker is not None and not worker.is_finished
            release.set()
            await worker.wait()
            await pilot.pause()
            assert "MP3 tracks           4" in _rendered(app, "#library-data")

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_refresh_uses_background_worker_and_supersedes_loading_state(tmp_path):
    refresh_started = Event()
    release = Event()
    calls = 0

    def library(settings):
        nonlocal calls
        calls += 1
        if calls == 2:
            refresh_started.set()
            assert release.wait(timeout=5)
        return _library_status(tmp_path, track_count=calls)

    async def scenario():
        app = _app(tmp_path, library=library)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "MP3 tracks           1" in _rendered(app, "#library-data")
            await pilot.press("r")
            await asyncio.to_thread(refresh_started.wait, 2)
            assert "Loading library status" in _rendered(app, "#library-data")
            await pilot.press("r")
            current_worker = app.screen._refresh_worker
            assert current_worker is not None
            await current_worker.wait()
            await pilot.pause()
            assert "MP3 tracks           3" in _rendered(app, "#library-data")
            await pilot.press("4")
            await pilot.pause()
            assert app.screen.id == "screen-downloads"
            await pilot.press("1")
            release.set()
            await pilot.pause()
            assert "MP3 tracks           3" in _rendered(app, "#library-data")

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_q_exits_while_dashboard_provider_is_still_loading(tmp_path):
    started = Event()
    release = Event()

    def slow_library(settings):
        started.set()
        release.wait(timeout=5)
        return _library_status(tmp_path)

    async def scenario():
        app = _app(tmp_path, library=slow_library)
        async with app.run_test() as pilot:
            await asyncio.to_thread(started.wait, 2)
            await pilot.press("q")
            assert not app.is_running
            release.set()

    try:
        asyncio.run(scenario())
    finally:
        release.set()


def test_service_exceptions_are_visible_and_navigation_survives(tmp_path):
    def broken_library(settings):
        raise OSError("library directory is unavailable")

    def broken_queue():
        raise ValueError("queue data is malformed")

    async def scenario():
        app = _app(tmp_path, library=broken_library, queue=broken_queue)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert "library directory is unavailable" in _rendered(app, "#library-error")
            assert "queue data is malformed" in _rendered(app, "#queue-error")
            await pilot.press("2")
            await pilot.pause()
            assert app.screen.id == "screen-browse"

    asyncio.run(scenario())


def test_q_exits(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.press("q")
            await pilot.pause()
            assert not app.is_running

    asyncio.run(scenario())


def test_shell_is_read_only_and_does_not_contact_api(tmp_path, monkeypatch):
    import juice_lyrics.api.client as api_client

    root = tmp_path / "isolated-xdg"
    monkeypatch.setattr(
        api_client,
        "api_get",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("API request made")),
    )

    async def scenario():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("2", "3", "4", "5", "1", "r")
            await pilot.pause()

    asyncio.run(scenario())
    assert not root.exists()
    assert not list(tmp_path.rglob("*.mp3"))
    assert not list(tmp_path.rglob("*.lrc"))
    assert not list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.rglob("*.toml"))


def test_cli_parser_and_dispatch_accept_tui_without_changing_other_commands(monkeypatch):
    import juice_lyrics.cli as cli

    assert cli.build_parser().parse_args(["tui"]).command == "tui"
    assert cli.build_parser().parse_args(["status"]).command == "status"
    acquire = cli.build_parser().parse_args(["acquire", "jobs"])
    assert (acquire.command, acquire.action) == ("acquire", "jobs")

    called = []
    monkeypatch.setattr(cli, "command_tui", lambda settings: called.append(settings) or 0)
    assert cli.main(["--path", "/tmp/library", "tui"]) == 0
    assert called and called[0].music_dir == Path("/tmp/library")


def test_narrow_terminal_uses_single_column_dashboard(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        async with app.run_test(size=(50, 20)) as pilot:
            await pilot.pause()
            assert "-narrow" in app.screen.classes
            assert "MP3 tracks           4" in _rendered(app, "#library-data")
            await pilot.press("5")
            await pilot.pause()
            assert app.screen.id == "screen-settings"

    asyncio.run(scenario())


def test_ansi_mode_and_tui_styles_avoid_forced_theme_colors(tmp_path):
    app = _app(tmp_path)
    css = app.CSS.lower()

    assert app.ansi_color is True
    assert not re.search(r"#[0-9a-f]{3}(?:[0-9a-f]{3})?\\b", css)
    assert "rgb(" not in css
    assert "$primary" not in css
    assert "$secondary" not in css
    assert "$accent" not in css


def test_active_navigation_uses_plain_static_widget_and_ansi_text_only(tmp_path):
    app = _app(tmp_path)
    css = app.CSS.lower()
    item_rule = css.split(
        "#primary-navigation navigationitem {", 1
    )[1].split("}", 1)[0]
    active_rule = css.split(
        "#primary-navigation navigationitem.-current:hover", 1
    )[1].split("}", 1)[0]

    assert issubclass(NavigationItem, Static)
    assert not issubclass(NavigationItem, Button)
    assert NavigationItem.can_focus is False
    assert "background: transparent" in item_rule
    assert "border: none" in item_rule
    assert "background" not in active_rule
    assert "color: ansi_blue" in active_rule
    assert "text-style: bold" in active_rule
    assert "underline" not in css
    assert "reverse" not in active_rule
    assert "navigationitem:focus" not in css
    assert "navigationitem:focus-within" not in css
    assert "navigationitem.-selected" not in css
    assert "navigationitem.-active" not in css

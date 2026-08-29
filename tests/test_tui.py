import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.services import LibraryStatus, QueueSnapshot
from juice_lyrics.tui import JuiceLyricsApp


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


def test_keyboard_navigation_reaches_all_placeholder_screens(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            for key, section in zip("2345", ("browse", "library", "downloads", "settings")):
                await pilot.press(key)
                await pilot.pause()
                assert app.screen.id == f"screen-{section}"
                assert "planned for a later milestone" in _rendered(app, "#placeholder-message")
            await pilot.press("1")
            await pilot.pause()
            assert app.screen.id == "screen-dashboard"

    asyncio.run(scenario())


def test_navigation_buttons_are_keyboard_focusable(tmp_path):
    async def scenario():
        app = _app(tmp_path)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("tab")
            assert app.focused is not None
            assert app.focused.id and app.focused.id.startswith("nav-")

    asyncio.run(scenario())


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

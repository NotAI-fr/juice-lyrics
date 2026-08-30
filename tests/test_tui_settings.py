import asyncio
from pathlib import Path
import sys
from threading import Event

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from textual.containers import VerticalScroll

from juice_lyrics.config.settings import Settings
from juice_lyrics.services import (
    CatalogueFilterMetadata,
    IntegrationSnapshot,
    IntegrationStatus,
    LibrarySnapshot,
    LibraryStatus,
    QueueSnapshot,
    SettingValue,
    SettingsPath,
    SettingsSnapshot,
    SettingsSource,
)
from juice_lyrics.tui import JuiceLyricsApp


def _snapshot(
    tmp_path: Path,
    *,
    config_exists: bool = True,
    integration: IntegrationStatus = IntegrationStatus.DETECTED_CONFIGURED,
    suffix: str = "",
) -> SettingsSnapshot:
    config = tmp_path / f"config{suffix}.toml"
    music = tmp_path / f"music{suffix}"
    values = (
        SettingValue("music_dir", "Music directory", music, Path("/default/music"), SettingsSource.CONFIG),
        SettingValue("api_base", "API base URL", "https://api.example", "https://default.example", SettingsSource.DEFAULT),
        SettingValue("timeout", "Request timeout", 20, 20, SettingsSource.DEFAULT),
        SettingValue("delay", "Request delay", 0.15, 0.15, SettingsSource.CONFIG),
        SettingValue("duration_tolerance", "Duration tolerance", 3.0, 3.0, SettingsSource.RUNTIME_OVERRIDE),
        SettingValue("cache_ttl_hours", "Cache TTL", 24.0, 24.0, SettingsSource.DEFAULT),
    )
    paths = (
        SettingsPath("music", "Music library", music, True),
        SettingsPath("lyrics", "rmpc lyrics", tmp_path / "lyrics", False),
        SettingsPath("cache", "API cache", tmp_path / "cache", True),
        SettingsPath("state", "Library state", tmp_path / "data" / "state.json", False),
        SettingsPath("backups", "Backups", tmp_path / "data" / "backups", False),
        SettingsPath("jobs", "Acquisition jobs", tmp_path / "data" / "jobs.json", True),
        SettingsPath("config", "Application config", config, config_exists),
        SettingsPath("rmpc_config", "rmpc config", tmp_path / "rmpc" / "config.ron", integration is IntegrationStatus.DETECTED_CONFIGURED),
    )
    details = {
        IntegrationStatus.DETECTED_CONFIGURED: "rmpc is detected and configured.",
        IntegrationStatus.DETECTED_NOT_CONFIGURED: "rmpc is detected but not configured.",
        IntegrationStatus.NOT_DETECTED: "rmpc was not found in PATH.",
        IntegrationStatus.UNABLE_TO_INSPECT: "Unable to inspect rmpc.",
    }
    return SettingsSnapshot(
        config_path=config,
        config_exists=config_exists,
        values=values,
        paths=paths,
        rmpc=IntegrationSnapshot(
            integration,
            Path("/usr/bin/rmpc") if integration in {IntegrationStatus.DETECTED_CONFIGURED, IntegrationStatus.DETECTED_NOT_CONFIGURED} else None,
            tmp_path / "rmpc" / "config.ron",
            integration is not IntegrationStatus.NOT_DETECTED,
            integration is IntegrationStatus.DETECTED_CONFIGURED,
            details[integration],
        ),
        application_version="1.4.0",
        limitations=(
            "Local library scanning currently supports MP3 files only.",
            "Native FLAC support is planned but not implemented.",
            "Browse and Downloads remain read-only in the TUI.",
            "Library sync execution remains CLI-only.",
            "Configuration changes remain CLI-only.",
        ),
    )


def _app(tmp_path: Path, provider) -> JuiceLyricsApp:
    settings = Settings(music_dir=tmp_path / "music")
    return JuiceLyricsApp(
        settings,
        library_status_provider=lambda settings: LibraryStatus(settings.music_dir, 0, 0, 0, 0, 0, 0, 0, ()),
        queue_snapshot_provider=lambda: QueueSnapshot((), 0, 0, 0, 0, 0),
        catalogue_filters_provider=lambda *args, **kwargs: CatalogueFilterMetadata((), ()),
        library_snapshot_provider=lambda settings: LibrarySnapshot(Path(settings.music_dir), False, ()),
        settings_snapshot_provider=provider,
    )


def _text(app: JuiceLyricsApp, selector: str) -> str:
    return str(app.query_one(selector).render())


async def _open_settings(app: JuiceLyricsApp, pilot):
    await pilot.press("5")
    await pilot.pause()
    worker = app.screen._refresh_worker
    if worker is not None:
        await worker.wait()
        await pilot.pause()
    return app.screen


def test_settings_replaces_placeholder_and_renders_configuration_paths_and_limitations(tmp_path):
    async def scenario():
        app = _app(tmp_path, lambda settings: _snapshot(tmp_path))
        async with app.run_test(size=(120, 40)) as pilot:
            screen = await _open_settings(app, pilot)
            assert screen.__class__.__name__ == "SettingsScreen"
            assert "Read-only settings view — configuration changes remain CLI-only" in _text(app, "#settings-warning")
            configuration = _text(app, "#settings-configuration")
            assert "config.toml" in configuration
            assert str(tmp_path / "config.toml") in _text(app, "#settings-detail")
            assert "Music directory" in configuration and "[Config file]" in configuration
            assert "API base URL" in configuration and "[Default]" in configuration
            assert "Duration tolerance" in configuration and "[Runtime override]" in configuration
            paths = _text(app, "#settings-paths")
            assert "Music library" in paths and "[Exists]" in paths
            assert "rmpc lyrics" in paths and "[Missing]" in paths
            assert "Detected and configured" in _text(app, "#settings-integrations")
            capabilities = _text(app, "#settings-capabilities")
            assert "MP3 files only" in capabilities and "FLAC support is planned" in capabilities
            assert "Library sync execution remains CLI-only" in capabilities

            await pilot.press("down", "j")
            assert screen.selected_index == 2
            assert "Music directory" in _text(app, "#settings-detail")
            await pilot.press("end")
            assert screen.selected_index == len(screen.rows) - 1
            await pilot.press("home")
            assert screen.selected_index == 0

    asyncio.run(scenario())


def test_loading_is_responsive_and_quit_works(tmp_path):
    started = Event()
    release = Event()

    def slow(settings):
        started.set()
        release.wait(timeout=5)
        return _snapshot(tmp_path)

    async def navigation_scenario():
        app = _app(tmp_path, slow)
        async with app.run_test() as pilot:
            await pilot.press("5")
            await asyncio.to_thread(started.wait, 2)
            assert "Loading" in _text(app, "#settings-configuration")
            await pilot.press("2")
            assert app.screen.id == "screen-browse"
            release.set()

    async def quit_scenario():
        quit_started = Event()
        quit_release = Event()

        def provider(settings):
            quit_started.set()
            quit_release.wait(timeout=5)
            return _snapshot(tmp_path)

        app = _app(tmp_path, provider)
        async with app.run_test() as pilot:
            await pilot.press("5")
            await asyncio.to_thread(quit_started.wait, 2)
            await pilot.press("q")
            assert not app.is_running
            quit_release.set()

    try:
        asyncio.run(navigation_scenario())
        asyncio.run(quit_scenario())
    finally:
        release.set()


def test_missing_config_integration_states_and_provider_errors(tmp_path):
    async def missing_scenario():
        app = _app(
            tmp_path,
            lambda settings: _snapshot(
                tmp_path,
                config_exists=False,
                integration=IntegrationStatus.NOT_DETECTED,
            ),
        )
        async with app.run_test() as pilot:
            await _open_settings(app, pilot)
            assert "No config file" in _text(app, "#settings-status")
            assert "Missing; defaults are in use" in _text(app, "#settings-detail")
            assert "Not detected" in _text(app, "#settings-integrations")

    async def state_scenario(status, label):
        app = _app(tmp_path, lambda settings: _snapshot(tmp_path, integration=status))
        async with app.run_test() as pilot:
            await _open_settings(app, pilot)
            assert label in _text(app, "#settings-integrations")

    async def error_scenario(message):
        app = _app(tmp_path, lambda settings: (_ for _ in ()).throw(RuntimeError(message)))
        async with app.run_test() as pilot:
            await _open_settings(app, pilot)
            assert f"Settings unavailable: {message}" in _text(app, "#settings-status")
            assert app.screen.id == "screen-settings"

    asyncio.run(missing_scenario())
    asyncio.run(state_scenario(IntegrationStatus.DETECTED_NOT_CONFIGURED, "Detected but not configured"))
    asyncio.run(state_scenario(IntegrationStatus.UNABLE_TO_INSPECT, "Unable to inspect"))
    asyncio.run(error_scenario("Could not read config: invalid TOML"))
    asyncio.run(error_scenario("permission denied"))


def test_refresh_supersedes_stale_snapshot_and_reloads_values(tmp_path):
    stale_started = Event()
    release_stale = Event()
    calls = 0

    def provider(settings):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _snapshot(tmp_path)
        if calls == 2:
            stale_started.set()
            release_stale.wait(timeout=5)
            return _snapshot(tmp_path, suffix="-stale")
        return _snapshot(tmp_path, suffix="-fresh")

    async def scenario():
        app = _app(tmp_path, provider)
        async with app.run_test() as pilot:
            screen = await _open_settings(app, pilot)
            await pilot.press("r")
            await asyncio.to_thread(stale_started.wait, 2)
            await pilot.press("r")
            current = screen._refresh_worker
            await current.wait()
            await pilot.pause()
            assert "config-fresh.toml" in _text(app, "#settings-configuration")
            release_stale.set()
            await pilot.pause()
            assert "config-stale.toml" not in _text(app, "#settings-configuration")

    try:
        asyncio.run(scenario())
    finally:
        release_stale.set()


def test_long_settings_scroll_at_80x24_and_other_supported_sizes(tmp_path):
    async def scenario(size):
        app = _app(tmp_path, lambda settings: _snapshot(tmp_path))
        async with app.run_test(size=size) as pilot:
            screen = await _open_settings(app, pilot)
            scroll = app.query_one("#settings-scroll", VerticalScroll)
            assert scroll.size.height >= 5
            assert scroll.max_scroll_y > 0
            await pilot.press("end")
            await pilot.pause()
            assert screen.selected_index == len(screen.rows) - 1
            if scroll.scroll_y == 0:
                await pilot.press("pagedown")
                await pilot.pause()
            assert scroll.scroll_y > 0
            await pilot.press("pageup")
            assert screen.selected_index < len(screen.rows) - 1
            assert "Read-only settings view" in _text(app, "#settings-warning")

    for size in ((80, 24), (100, 30), (120, 40)):
        asyncio.run(scenario(size))


def test_settings_screen_does_not_call_mutating_or_network_systems(tmp_path, monkeypatch):
    import juice_lyrics.api.client as api
    import juice_lyrics.cli as cli
    import juice_lyrics.rmpc.integration as rmpc

    def mutation(*args, **kwargs):
        raise AssertionError("mutation attempted")

    monkeypatch.setattr(cli, "write_default_config", mutation)
    monkeypatch.setattr(cli, "command_setup", mutation)
    monkeypatch.setattr(rmpc, "patch_rmpc_config", mutation)
    monkeypatch.setattr(api, "api_get", mutation)

    async def scenario():
        app = _app(tmp_path, lambda settings: _snapshot(tmp_path))
        async with app.run_test() as pilot:
            await _open_settings(app, pilot)
            await pilot.press("down", "end", "home", "pagedown", "pageup", "r")
            await app.screen._refresh_worker.wait()
            await pilot.pause()

    asyncio.run(scenario())
    assert not list(tmp_path.rglob("*.toml"))
    assert not list(tmp_path.rglob("*.json"))
    assert not list(tmp_path.rglob("*.lrc"))

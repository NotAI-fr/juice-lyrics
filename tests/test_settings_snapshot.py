from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.services.settings_snapshot import (
    IntegrationStatus,
    SettingsSource,
    get_settings_snapshot,
)


def _snapshot(tmp_path, settings=None, **kwargs):
    return get_settings_snapshot(
        settings or Settings(music_dir=tmp_path / "music"),
        config_path=kwargs.pop("config_path", tmp_path / "config" / "config.toml"),
        cache_dir=tmp_path / "cache",
        state_file=tmp_path / "data" / "state.json",
        backup_dir=tmp_path / "data" / "backups",
        jobs_file=tmp_path / "data" / "jobs.json",
        lyrics_dir=tmp_path / "lyrics",
        rmpc_config_path=kwargs.pop("rmpc_config_path", tmp_path / "rmpc" / "config.ron"),
        executable_finder=kwargs.pop("executable_finder", lambda name: None),
        **kwargs,
    )


def test_missing_config_reports_effective_defaults_and_runtime_override_without_writes(tmp_path):
    snapshot = _snapshot(tmp_path)
    values = {item.key: item for item in snapshot.values}

    assert snapshot.config_exists is False
    assert values["music_dir"].source is SettingsSource.RUNTIME_OVERRIDE
    assert values["api_base"].source is SettingsSource.DEFAULT
    assert values["timeout"].source is SettingsSource.DEFAULT
    assert snapshot.rmpc.status is IntegrationStatus.NOT_DETECTED
    assert all(not item.exists for item in snapshot.paths)
    assert not list(tmp_path.rglob("*"))


def test_explicit_config_and_runtime_overrides_have_reliable_provenance(tmp_path):
    config = tmp_path / "config.toml"
    configured_music = tmp_path / "configured-music"
    config.write_text(
        f'music_dir = "{configured_music}"\n'
        'api_base = "https://example.test/api/"\n'
        "timeout = 30\n"
        "delay = 0.25\n"
        "duration_tolerance = 2.5\n"
        "cache_ttl_hours = 12\n",
        encoding="utf-8",
    )
    settings = Settings(
        music_dir=configured_music,
        api_base="https://runtime.test/api",
        timeout=30,
        delay=0.25,
        duration_tolerance=2.5,
        cache_ttl_hours=12,
    )
    snapshot = _snapshot(tmp_path, settings, config_path=config)
    values = {item.key: item for item in snapshot.values}

    assert snapshot.config_exists is True
    assert values["music_dir"].source is SettingsSource.CONFIG
    assert values["timeout"].source is SettingsSource.CONFIG
    assert values["api_base"].source is SettingsSource.RUNTIME_OVERRIDE


@pytest.mark.parametrize(
    ("executable", "config_text", "expected"),
    [
        ("/usr/bin/rmpc", 'lyrics_dir: Some("/lyrics"),\nenable_lyrics_index: true,\nenable_lyrics_hot_reload: true,', IntegrationStatus.DETECTED_CONFIGURED),
        ("/usr/bin/rmpc", "cache_dir: Some(\"/cache\"),", IntegrationStatus.DETECTED_NOT_CONFIGURED),
        (None, 'lyrics_dir: Some("/lyrics"),', IntegrationStatus.NOT_DETECTED),
    ],
)
def test_rmpc_detection_and_configuration_states(tmp_path, executable, config_text, expected):
    rmpc_config = tmp_path / "rmpc.ron"
    rmpc_config.write_text(config_text, encoding="utf-8")
    snapshot = _snapshot(
        tmp_path,
        rmpc_config_path=rmpc_config,
        executable_finder=lambda name: executable,
    )

    assert snapshot.rmpc.status is expected
    assert snapshot.rmpc.config_exists is True


def test_malformed_config_raises_readable_error_without_rewriting(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("timeout = nope", encoding="utf-8")
    before = config.read_bytes()

    with pytest.raises(RuntimeError, match="Could not read config"):
        _snapshot(tmp_path, config_path=config)

    assert config.read_bytes() == before


def test_paths_and_limitations_are_typed_and_read_only(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    snapshot = _snapshot(tmp_path, Settings(music_dir=music))
    paths = {item.key: item for item in snapshot.paths}

    assert paths["music"].exists is True
    assert paths["cache"].exists is False
    assert paths["state"].path == tmp_path / "data" / "state.json"
    assert "MP3 files only" in snapshot.limitations[0]
    assert any("FLAC" in item for item in snapshot.limitations)
    assert not (tmp_path / "cache").exists()
    assert not (tmp_path / "data").exists()


def test_rmpc_inspection_failure_is_structured(tmp_path):
    snapshot = _snapshot(
        tmp_path,
        executable_finder=lambda name: (_ for _ in ()).throw(PermissionError("PATH denied")),
    )

    assert snapshot.rmpc.status is IntegrationStatus.UNABLE_TO_INSPECT
    assert "PATH denied" in snapshot.rmpc.detail

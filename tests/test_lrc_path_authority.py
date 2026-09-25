from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import (
    DEFAULT_LYRICS_DIR,
    LEGACY_IMPLICIT_LYRICS_DIR,
    Settings,
    resolve_lyrics_dir,
)


def test_legacy_implicit_default_is_guarded_but_explicit_value_is_respected(
    tmp_path, monkeypatch
):
    import juice_lyrics.cli as cli

    stale = Settings(lyrics_dir=LEGACY_IMPLICIT_LYRICS_DIR)
    assert resolve_lyrics_dir(stale) == DEFAULT_LYRICS_DIR

    config = tmp_path / "config.toml"
    config.write_text(
        f'lyrics_dir = "{LEGACY_IMPLICIT_LYRICS_DIR}"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "CONFIG_FILE", config)
    configured = cli.load_settings()
    assert configured.lyrics_dir_explicit is True
    assert resolve_lyrics_dir(configured) == LEGACY_IMPLICIT_LYRICS_DIR


def test_acquisition_ignores_legacy_lrc_override_and_writes_sidecar(
    tmp_path, monkeypatch
):
    import juice_lyrics.acquisition.integration as integration
    from juice_lyrics.acquisition.integration import integrate_downloaded_mp3
    from juice_lyrics.acquisition.models import AcquisitionItem

    music = tmp_path / "Music" / "Juice WRLD"
    destination = music / "Rental.mp3"
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"pristine")
    central = tmp_path / "Music" / "lyrics"
    legacy = tmp_path / "Music" / "Juice WRLD" / "lyrics"
    outputs: list[Path] = []

    backup = tmp_path / "backup.mp3"
    monkeypatch.setattr(integration, "make_backup_root", lambda: tmp_path / "backup")
    monkeypatch.setattr(
        integration,
        "backup_file",
        lambda source, root, base: backup,
    )
    monkeypatch.setattr(integration, "write_manifest", lambda *args: None)
    monkeypatch.setattr(integration, "embed_lyrics", lambda *args: "SYLT")
    monkeypatch.setattr(integration, "verify_file", lambda path: (True, "verified"))
    monkeypatch.setattr(integration, "sha256_file", lambda path: "hash")

    def writer(path, synced, song):
        outputs.append(path)
        result = path.with_suffix(".lrc")
        result.write_text("[00:01.00] line\n", encoding="utf-8")
        return result

    monkeypatch.setattr(integration, "write_lrc", writer)
    item = AcquisitionItem("1", "Rental", "https://example.test/Rental.mp3", destination)
    result = integrate_downloaded_mp3(
        item,
        song_fetcher=lambda _: {
            "id": 1,
            "name": "Rental",
            "synced_lyrics": "[00:01.00] line",
            "lyrics": "line",
        },
        lyrics_dir=legacy,
        settings=Settings(music_dir=music, lyrics_dir=central),
        state={},
        notify_rmpc=False,
    )

    assert outputs == [destination]
    assert result.lrc_path == destination.with_suffix(".lrc")
    assert not central.exists()
    assert not legacy.exists()


def test_current_cli_read_only_and_failed_write_flows_never_create_legacy_path(
    tmp_path
):
    home = tmp_path / "home"
    env = os.environ.copy()
    env.update(
        HOME=str(home),
        XDG_CONFIG_HOME=str(home / ".config"),
        XDG_CACHE_HOME=str(home / ".cache"),
        XDG_DATA_HOME=str(home / ".local" / "share"),
        PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"),
    )
    command = [sys.executable, "-m", "juice_lyrics.cli"]
    legacy = home / "Music" / "Juice WRLD" / "lyrics"
    central = home / "Music" / "lyrics"

    initialized = subprocess.run(
        [*command, "config", "init"], env=env, text=True, capture_output=True
    )
    assert initialized.returncode == 0
    for arguments in (
        ("config", "show"),
        ("status",),
        ("rmpc", "verify"),
        ("rmpc", "sync"),
    ):
        subprocess.run([*command, *arguments], env=env, text=True, capture_output=True)
        assert not legacy.exists(), arguments

    # No synchronized file was authorized, so even the configured destination
    # remains absent throughout these inspection/error paths.
    assert not central.exists()


def test_stale_rmpc_configuration_is_reported_but_cannot_redirect_output(tmp_path):
    from juice_lyrics.services.settings_snapshot import (
        IntegrationStatus,
        get_settings_snapshot,
    )

    legacy = tmp_path / "Music" / "Juice WRLD" / "lyrics"
    central = tmp_path / "Music" / "lyrics"
    rmpc = tmp_path / "config.ron"
    rmpc.write_text(
        f'(\nlyrics_dir: Some("{legacy}"),\n'
        "enable_lyrics_index: true,\n"
        "enable_lyrics_hot_reload: true,\n)",
        encoding="utf-8",
    )
    snapshot = get_settings_snapshot(
        Settings(music_dir=tmp_path / "music", lyrics_dir=central),
        config_path=tmp_path / "missing.toml",
        cache_dir=tmp_path / "cache",
        state_file=tmp_path / "state.json",
        backup_dir=tmp_path / "backups",
        jobs_file=tmp_path / "jobs.json",
        rmpc_config_path=rmpc,
        executable_finder=lambda name: "/usr/bin/rmpc",
    )

    assert snapshot.rmpc.status is IntegrationStatus.DETECTED_NOT_CONFIGURED
    assert snapshot.rmpc.config_has_lyrics_support is False
    assert not legacy.exists()
    assert not central.exists()

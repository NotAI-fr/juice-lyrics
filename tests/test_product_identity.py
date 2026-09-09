from __future__ import annotations

import argparse
import tomllib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics import cli
from juice_lyrics.config import settings as config_settings
from juice_lyrics.identity import (
    DIST_NAME,
    LEGACY_COMMAND,
    PRIMARY_COMMAND,
    PRODUCT_NAME,
    STORAGE_NAMESPACE,
)
from juice_lyrics.tui import JuiceLyricsApp


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _project_scripts() -> dict[str, str]:
    data = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return data["project"]["scripts"]


def test_primary_and_legacy_console_scripts_share_one_cli_implementation():
    scripts = _project_scripts()

    assert PRODUCT_NAME == PRIMARY_COMMAND == "999"
    assert LEGACY_COMMAND == STORAGE_NAMESPACE == "juice-lyrics"
    assert DIST_NAME == "juice-wrld-lyrics"
    assert scripts[PRIMARY_COMMAND] == "juice_lyrics.cli:main"
    assert scripts[LEGACY_COMMAND] == scripts[PRIMARY_COMMAND]


def test_999_help_is_clean_and_uses_primary_command(capsys):
    with pytest.raises(SystemExit) as result:
        cli.main(["--help"])

    output = capsys.readouterr().out
    assert result.value.code == 0
    assert output.startswith("usage: 999")
    assert "Launch the 999 terminal interface" in output
    assert "juice-lyrics" not in output


def test_tui_and_documentation_prefer_999_branding():
    assert JuiceLyricsApp.TITLE == "999"
    for relative in (
        "README.md",
        "docs/USER_GUIDE.md",
        "docs/DEVELOPMENT.md",
        "docs/PROJECT_STATE.md",
        "docs/JUICE_WRLD_V2_CONTINUITY_BRIEF.md",
    ):
        text = (PROJECT_ROOT / relative).read_text(encoding="utf-8")
        assert "999" in text
        assert ".venv/bin/juice-lyrics" not in text
        assert not any(
            line.startswith("juice-lyrics ") for line in text.splitlines()
        )


def test_no_argument_first_run_opens_tui_without_writing_setup_paths(tmp_path, monkeypatch):
    config = tmp_path / ".config" / STORAGE_NAMESPACE / "config.toml"
    legacy_lyrics = tmp_path / "Music" / "lyrics"
    rmpc_config = tmp_path / ".config" / "rmpc" / "config.ron"
    rmpc_config.parent.mkdir(parents=True)
    rmpc_config.write_text("unchanged", encoding="utf-8")
    monkeypatch.setattr(cli, "CONFIG_FILE", config)
    monkeypatch.setattr(cli, "DEFAULT_RMPC_CONFIG", rmpc_config)
    first_run_settings = config_settings.Settings(
        music_dir=tmp_path / "missing music",
        lyrics_dir=legacy_lyrics,
    )
    monkeypatch.setattr(cli, "Settings", lambda: first_run_settings)
    monkeypatch.setattr(
        cli,
        "patch_rmpc_config",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("rmpc rewritten")),
    )
    launched = []
    monkeypatch.setattr(cli, "command_tui", lambda settings: launched.append(settings) or 0)

    assert cli.main([]) == 0
    assert len(launched) == 1
    assert not config.exists()
    assert not legacy_lyrics.exists()
    assert rmpc_config.read_text(encoding="utf-8") == "unchanged"


def test_999_status_dispatch_works_with_an_isolated_empty_library(tmp_path, capsys):
    music = tmp_path / "music"
    music.mkdir()

    assert cli.main(["--path", str(music), "--no-color", "status"]) == 0
    output = capsys.readouterr().out
    assert "Library Status" in output
    assert f"Library:              {music}" in output
    assert "Audio files:          0" in output


def test_existing_juice_lyrics_config_and_storage_paths_remain_authoritative(
    tmp_path, monkeypatch
):
    config = tmp_path / ".config" / STORAGE_NAMESPACE / "config.toml"
    music = tmp_path / "existing library"
    config.parent.mkdir(parents=True)
    config.write_text(f'music_dir = "{music}"\n', encoding="utf-8")
    monkeypatch.setattr(cli, "CONFIG_FILE", config)

    loaded = cli.load_settings()

    assert loaded.music_dir == music
    assert config_settings.CONFIG_FILE.parent.name == STORAGE_NAMESPACE
    assert config_settings.CACHE_DIR.name == STORAGE_NAMESPACE
    assert config_settings.DATA_DIR.name == STORAGE_NAMESPACE
    assert config_settings.STATE_FILE == config_settings.DATA_DIR / "state.json"
    assert config_settings.BACKUP_DIR == config_settings.DATA_DIR / "backups"
    assert config_settings.ACQUISITION_JOBS_FILE == config_settings.DATA_DIR / "acquisition_jobs.json"


def test_setup_help_keeps_config_and_rmpc_responsibilities_explicit():
    parser = cli.build_parser()

    assert parser.parse_args(["config", "init"]) == argparse.Namespace(
        path=None,
        api_base=None,
        no_color=False,
        command="config",
        action="init",
        force=False,
    )
    assert parser.parse_args(["rmpc", "setup"]).action == "setup"
    assert parser.parse_args(["setup"]).command == "setup"

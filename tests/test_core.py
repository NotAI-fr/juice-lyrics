from pathlib import Path
import sys
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.cli import parse_length, parse_synced_lyrics, patch_rmpc_config


def test_parse_length():
    assert parse_length("4:13") == 253.0
    assert parse_length("1:02:03") == 3723.0


def test_parse_synced_lyrics():
    result = parse_synced_lyrics("[0:01.64] hello\n[0:04.14] world")
    assert result == [("hello", 1640), ("world", 4140)]


def test_rmpc_config_patch_is_safe():
    config = '''#![enable(implicit_some)]\n(\n    cache_dir: Some("/tmp/rmpc/cache"),\n    lyrics_dir: "~/Music",\n)\n'''
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "config.ron"
        path.write_text(config, encoding="utf-8")
        backup = patch_rmpc_config(path, Path(td) / "lyrics")
        text = path.read_text(encoding="utf-8")
        assert 'lyrics_dir: Some("' in text
        assert 'enable_lyrics_index: true,' in text
        assert 'enable_lyrics_hot_reload: true,' in text
        assert backup.exists()


def test_find_mp3s_accepts_path_and_settings(tmp_path):
    from juice_lyrics.config.settings import Settings
    from juice_lyrics.library.scanner import find_mp3s

    song1 = tmp_path / "song1.mp3"
    song2 = tmp_path / "sub" / "song2.mp3"
    song2.parent.mkdir(parents=True, exist_ok=True)
    song1.write_bytes(b"")
    song2.write_bytes(b"")

    # Direct Path
    from_path = find_mp3s(tmp_path)
    assert len(from_path) == 2
    assert song1 in from_path
    assert song2 in from_path

    # Settings instance
    settings = Settings(music_dir=tmp_path)
    from_settings = find_mp3s(settings)
    assert from_settings == from_path


def test_command_status_with_settings(tmp_path, capsys, monkeypatch):
    import juice_lyrics.cli as cli
    from juice_lyrics.config.settings import Settings

    settings = Settings(music_dir=tmp_path, lyrics_dir=tmp_path / "central-lyrics")
    # Empty directory status
    rc = cli.command_status(settings, use_color=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Library Status" in out
    assert f"External LRC dir:     {tmp_path / 'central-lyrics'}" in out
    assert "MP3 files:            0" in out

    # Status with an MP3 file
    mp3 = tmp_path / "track.mp3"
    mp3.write_bytes(b"")
    monkeypatch.setattr(cli, "verify_file", lambda p: (True, "SYLT (10 synced lines)"))
    rc = cli.command_status(settings, use_color=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "MP3 files:            1" in out
    assert "Embedded synced:      1" in out


def test_command_scan_with_settings(tmp_path, capsys, monkeypatch):
    import argparse
    import juice_lyrics.cli as cli
    from juice_lyrics.config.settings import Settings

    mp3 = tmp_path / "track.mp3"
    mp3.write_bytes(b"")
    settings = Settings(music_dir=tmp_path)
    args = argparse.Namespace(refresh=False)

    monkeypatch.setattr(
        cli,
        "analyse",
        lambda s, p, refresh: {
            "path": p,
            "search_title": "track",
            "candidate": {"id": 1, "name": "Track"},
            "synced": [("line", 1000)],
            "plain": "",
        },
    )

    rc = cli.command_scan(args, settings, use_color=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Synced: 1" in out


def test_command_search_and_info_handle_string_and_dict_era(tmp_path, capsys, monkeypatch):
    import argparse
    import juice_lyrics.cli as cli
    from juice_lyrics.config.settings import Settings

    settings = Settings(music_dir=tmp_path)

    # 1. Search with string era
    monkeypatch.setattr(
        cli,
        "search_api_advanced",
        lambda *a, **k: {
            "results": [
                {"id": 1, "name": "Song 1", "category": "unreleased", "era": "DRFL", "length": "3:00"},
                {"id": 2, "name": "Song 2", "category": "unreleased", "era": {"id": 2, "name": "JW3"}, "length": "2:30"},
            ]
        },
    )
    args_search = argparse.Namespace(query="song", category=None, era=None, refresh=False)
    rc = cli.command_search(args_search, settings, use_color=False)
    assert rc == 0
    out_search = capsys.readouterr().out
    assert "era=DRFL" in out_search
    assert "era=JW3" in out_search

    # 2. Info with string era
    monkeypatch.setattr(
        cli,
        "search_api",
        lambda *a, **k: [{"id": 1, "name": "Song 1", "category": "unreleased", "era": "DRFL"}],
    )
    monkeypatch.setattr(
        cli,
        "get_song",
        lambda *a, **k: {"id": 1, "name": "Song 1", "category": "unreleased", "era": "DRFL", "credited_artists": "Juice WRLD"},
    )
    args_info = argparse.Namespace(query="song", index=None, refresh=False)
    rc = cli.command_info(args_info, settings, use_color=False)
    assert rc == 0
    out_info = capsys.readouterr().out
    assert "Era: DRFL" in out_info


def test_command_guide(capsys):
    import juice_lyrics.cli as cli

    rc = cli.command_guide()
    assert rc == 0
    out = capsys.readouterr().out
    assert "juice-lyrics quick guide" in out
    assert "juice-lyrics acquire search" in out
    assert "juice-lyrics sync" in out


def test_config_show_preserves_missing_and_existing_cli_behavior(tmp_path, monkeypatch, capsys):
    import argparse
    import juice_lyrics.cli as cli

    config = tmp_path / "config.toml"
    monkeypatch.setattr(cli, "CONFIG_FILE", config)
    args = argparse.Namespace(action="show")

    assert cli.command_config(args) == 0
    output = capsys.readouterr().out
    assert "No config. Defaults are in use." in output
    assert str(config) in output

    content = 'music_dir = "/music"\ntimeout = 20\n'
    config.write_text(content, encoding="utf-8")
    assert cli.command_config(args) == 0
    shown = capsys.readouterr().out
    assert content.strip() in shown
    assert f"Effective lyrics_dir: {Path.home() / 'Music' / 'lyrics'}" in shown


def test_lyrics_directory_default_config_override_and_unknown_keys(tmp_path, monkeypatch):
    import juice_lyrics.cli as cli
    from juice_lyrics.config.settings import DEFAULT_LYRICS_DIR, Settings

    config = tmp_path / "config.toml"
    monkeypatch.setattr(cli, "CONFIG_FILE", config)

    assert DEFAULT_LYRICS_DIR == Path.home() / "Music" / "lyrics"
    assert Settings().lyrics_dir == DEFAULT_LYRICS_DIR
    assert cli.load_settings().lyrics_dir == DEFAULT_LYRICS_DIR
    assert not config.exists()

    config.write_text('rmpc_lyrics_dir = "~/ignored-legacy-suggestion"\n', encoding="utf-8")
    assert cli.load_settings().lyrics_dir == DEFAULT_LYRICS_DIR

    config.write_text(
        'lyrics_dir = "~/shared-lyrics"\nunknown_future_key = "ignored"\n',
        encoding="utf-8",
    )
    loaded = cli.load_settings()
    assert loaded.lyrics_dir == Path.home() / "shared-lyrics"
    assert config.read_text(encoding="utf-8").endswith('unknown_future_key = "ignored"\n')

    missing_lyrics = tmp_path / "not-created" / "lyrics"
    config.write_text(f'lyrics_dir = "{missing_lyrics}"\n', encoding="utf-8")
    assert cli.load_settings().lyrics_dir == missing_lyrics
    assert not missing_lyrics.exists()

    config.unlink()
    cli.write_default_config()
    assert f'lyrics_dir = "{DEFAULT_LYRICS_DIR}"' in config.read_text(encoding="utf-8")


def test_rmpc_setup_uses_configured_lyrics_directory_without_read_time_creation(
    tmp_path, monkeypatch
):
    import argparse
    import juice_lyrics.cli as cli
    from juice_lyrics.config.settings import Settings

    rmpc_config = tmp_path / "rmpc" / "config.ron"
    rmpc_config.parent.mkdir()
    rmpc_config.write_text("()", encoding="utf-8")
    configured_lyrics = tmp_path / "Music" / "lyrics"
    configured = []

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/rmpc")
    monkeypatch.setattr(cli, "find_mp3s", lambda settings: [])
    monkeypatch.setattr(
        cli,
        "patch_rmpc_config",
        lambda path, lyrics: configured.append((path, lyrics)) or tmp_path / "rmpc.bak",
    )
    monkeypatch.setattr(cli, "notify_rmpc_index", lambda paths: 0)
    monkeypatch.setattr(cli, "rmpc_running", lambda: False)

    result = cli.command_rmpc_setup(
        argparse.Namespace(config=str(rmpc_config), lyrics_dir=None, yes=True, refresh=False),
        Settings(music_dir=tmp_path / "music", lyrics_dir=configured_lyrics),
        False,
    )

    assert result == 0
    assert configured == [(rmpc_config, configured_lyrics)]
    assert not configured_lyrics.exists()


def test_config_init_and_missing_library_setup_dispatch_remain_compatible(tmp_path, monkeypatch):
    import argparse
    import juice_lyrics.cli as cli
    from juice_lyrics.config.settings import Settings

    calls = []
    monkeypatch.setattr(cli, "write_default_config", lambda force: calls.append(force))
    assert cli.command_config(argparse.Namespace(action="init", force=True)) == 0
    assert calls == [True]

    missing = tmp_path / "missing-library"
    with pytest.raises(RuntimeError, match="Music directory does not exist"):
        cli.command_setup(
            argparse.Namespace(yes=True, refresh=False),
            Settings(music_dir=missing),
            use_color=False,
        )
    assert not missing.exists()

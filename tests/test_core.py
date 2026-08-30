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

    settings = Settings(music_dir=tmp_path)
    # Empty directory status
    rc = cli.command_status(settings, use_color=False)
    assert rc == 0
    out = capsys.readouterr().out
    assert "Library Status" in out
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
    assert capsys.readouterr().out == content + "\n"


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

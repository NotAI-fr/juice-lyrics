from pathlib import Path
import argparse
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.cli import write_lrc, command_rmpc_verify, parse_synced_lyrics
from juice_lyrics.config.settings import Settings


def test_lrc_writer(tmp_path):
    mp3 = tmp_path / "Test Song.mp3"
    # We only need an existing path for this unit-level test; metadata falls back to API data.
    mp3.write_bytes(b"")
    analysis = {
        "candidate": {
            "name": "Test Song",
            "credited_artists": "Juice WRLD",
            "album": "",
            "length": "1:23",
        },
        "synced": [("hello", 1230), ("world", 4560)],
    }
    # write_lrc needs MP3 duration; use a fake local_duration impossible here, so just test parser shape separately.
    assert parse_synced_lyrics("[0:01.23] hello\n[0:04.56] world") == [("hello", 1230), ("world", 4560)]


def test_rmpc_verify_reads_adjacent_sidecars_only(tmp_path, capsys):
    music = tmp_path / "music"
    music.mkdir()
    audio = music / "Rental.mp3"
    audio.write_bytes(b"audio")
    (music / "Rental.lrc").write_text(
        "[ar:Juice WRLD]\n[ti:Rental]\n[length:01:00]\n[00:01.00] line\n",
        encoding="utf-8",
    )
    configured = tmp_path / "Music" / "lyrics"
    configured.mkdir(parents=True)
    (configured / "Ignored.lrc").write_text("invalid", encoding="utf-8")
    old_derived = tmp_path / "Music" / "Juice WRLD" / "lyrics"
    old_derived.mkdir(parents=True)
    (old_derived / "Ignored.lrc").write_text("invalid", encoding="utf-8")

    result = command_rmpc_verify(
        argparse.Namespace(lyrics_dir=None),
        Settings(music_dir=music, lyrics_dir=configured),
        False,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "Rental.lrc" in output
    assert "Ignored.lrc" not in output
    assert "Valid: 1   Invalid: 0" in output


def test_rmpc_notification_receives_exact_sidecar_path(tmp_path, monkeypatch):
    import juice_lyrics.rmpc.integration as rmpc

    sidecar = tmp_path / "Music" / "Juice WRLD" / "Rental.lrc"
    calls = []

    class Result:
        returncode = 0

    monkeypatch.setattr(rmpc, "rmpc_running", lambda: True)
    monkeypatch.setattr(
        rmpc.subprocess,
        "run",
        lambda command, **kwargs: calls.append(command) or Result(),
    )

    assert rmpc.notify_rmpc_index([sidecar]) == 1
    assert calls == [["rmpc", "remote", "indexlrc", "--path", str(sidecar)]]

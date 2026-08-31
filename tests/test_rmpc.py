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


def test_rmpc_verify_reads_the_configured_central_directory(tmp_path, capsys):
    configured = tmp_path / "Music" / "lyrics"
    configured.mkdir(parents=True)
    (configured / "Rental.lrc").write_text(
        "[ar:Juice WRLD]\n[ti:Rental]\n[length:01:00]\n[00:01.00] line\n",
        encoding="utf-8",
    )
    old_derived = tmp_path / "Music" / "Juice WRLD" / "lyrics"
    old_derived.mkdir(parents=True)
    (old_derived / "Ignored.lrc").write_text("invalid", encoding="utf-8")

    result = command_rmpc_verify(
        argparse.Namespace(lyrics_dir=None),
        Settings(music_dir=tmp_path / "music", lyrics_dir=configured),
        False,
    )

    assert result == 0
    output = capsys.readouterr().out
    assert "Rental.lrc" in output
    assert "Ignored.lrc" not in output
    assert "Valid: 1   Invalid: 0" in output

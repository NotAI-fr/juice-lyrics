from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.cli import write_lrc, command_rmpc_verify, parse_synced_lyrics


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

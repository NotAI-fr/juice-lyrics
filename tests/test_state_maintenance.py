from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.services.state_maintenance import (
    execute_stale_state_cleanup,
    plan_stale_state_cleanup,
)


def _write_state(path: Path, files: dict) -> bytes:
    path.write_text(
        json.dumps({"files": files, "updated": "historical", "custom": "preserve"}, indent=2),
        encoding="utf-8",
    )
    return path.read_bytes()


def test_cleanup_previews_and_removes_only_clearly_stale_external_records(tmp_path):
    music = tmp_path / "Music"
    real = music / "Unreleased" / "24 Hours.mp3"
    real.parent.mkdir(parents=True)
    real.write_bytes(b"real audio")
    state_file = tmp_path / "state.json"
    stale_absolute = "/tmp/pytest-of-someone/pytest-44/test_case/Bandit.flac"
    stale_lrc = "/tmp/pytest-of-someone/pytest-45/test_case/Only LRC.lrc"
    original = _write_state(
        state_file,
        {
            "Unreleased/24 Hours.mp3": {
                "sha256": "real",
                "song_id": 94760,
                "api_name": "24 Hours",
                "lyric_type": "USLT",
                "lrc": None,
            },
            "Moved Song.mp3": {"song_id": 7, "api_name": "Moved Song", "lrc": None},
            stale_absolute: {"song_id": 1, "lrc": stale_absolute.removesuffix(".flac") + ".lrc"},
            "Temporary.mp3": {"song_id": 2, "lrc": stale_lrc},
        },
    )

    plan = plan_stale_state_cleanup(Settings(music_dir=music), state_file=state_file)

    assert plan.stale_count == 2
    assert set(plan.stale_keys) == {stale_absolute, "Temporary.mp3"}
    assert state_file.read_bytes() == original

    result = execute_stale_state_cleanup(plan)
    cleaned = json.loads(state_file.read_text(encoding="utf-8"))
    backup = json.loads(result.backup_path.read_text(encoding="utf-8"))

    assert result.removed_count == 2
    assert backup["files"]["Unreleased/24 Hours.mp3"]["song_id"] == 94760
    assert cleaned["files"]["Unreleased/24 Hours.mp3"]["song_id"] == 94760
    assert cleaned["files"]["Unreleased/24 Hours.mp3"]["api_name"] == "24 Hours"
    assert "Moved Song.mp3" in cleaned["files"]
    assert stale_absolute not in cleaned["files"]
    assert "Temporary.mp3" not in cleaned["files"]
    assert cleaned["custom"] == "preserve"


def test_cleanup_write_failure_preserves_original_and_safety_backup(tmp_path):
    music = tmp_path / "Music"
    music.mkdir()
    state_file = tmp_path / "state.json"
    stale = "/tmp/pytest-of-someone/pytest-99/test_case/Song.m4a"
    original = _write_state(state_file, {stale: {"song_id": 1}})
    plan = plan_stale_state_cleanup(Settings(music_dir=music), state_file=state_file)

    with pytest.raises(OSError, match="disk full"):
        execute_stale_state_cleanup(
            plan,
            writer=lambda path, state: (_ for _ in ()).throw(OSError("disk full")),
        )

    assert state_file.read_bytes() == original
    backups = tuple(tmp_path.glob("state.json.pre-clean-*.bak"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original


def test_cleanup_refuses_to_apply_a_stale_preview_after_state_changes(tmp_path):
    music = tmp_path / "Music"
    music.mkdir()
    state_file = tmp_path / "state.json"
    stale = "/tmp/pytest-of-someone/pytest-100/test_case/Song.mp3"
    _write_state(state_file, {stale: {"song_id": 1}})
    plan = plan_stale_state_cleanup(Settings(music_dir=music), state_file=state_file)
    state_file.write_text('{"files": {}, "new": true}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="changed after the cleanup preview"):
        execute_stale_state_cleanup(plan)

    assert not tuple(tmp_path.glob("state.json.pre-clean-*.bak"))


def test_existing_absolute_external_record_is_preserved(tmp_path):
    music = tmp_path / "Music"
    music.mkdir()
    external = tmp_path / "external" / "Song.mp3"
    external.parent.mkdir()
    external.write_bytes(b"exists")
    state_file = tmp_path / "state.json"
    original = _write_state(state_file, {str(external): {"song_id": 1}})

    plan = plan_stale_state_cleanup(Settings(music_dir=music), state_file=state_file)
    result = execute_stale_state_cleanup(plan)

    assert plan.stale_count == 0
    assert result.removed_count == 0
    assert result.backup_path is None
    assert state_file.read_bytes() == original

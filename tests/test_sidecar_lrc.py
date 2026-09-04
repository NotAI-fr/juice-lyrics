from __future__ import annotations

from pathlib import Path

import pytest

from juice_lyrics.lyrics import engine
from juice_lyrics.lyrics.sidecar import sidecar_lrc_path


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("song.mp3", "song.lrc"),
        ("song.flac", "song.lrc"),
        ("song.m4a", "song.lrc"),
        ("song.final.v2.flac", "song.final.v2.lrc"),
        ("Légend's [Mix] (v2).mp3", "Légend's [Mix] (v2).lrc"),
    ],
)
def test_sidecar_path_uses_audio_basename(filename, expected, tmp_path):
    assert sidecar_lrc_path(tmp_path / filename) == tmp_path / expected


def _metadata(*args, **kwargs):
    return {
        "artist": "Juice WRLD",
        "title": "Rental",
        "album": "",
        "length": "03:00.00",
    }


def test_lrc_writer_atomically_writes_beside_audio_and_reuses_identical_content(
    tmp_path, monkeypatch
):
    audio = tmp_path / "nested" / "Rental.mp3"
    audio.parent.mkdir()
    audio.write_bytes(b"audio")
    monkeypatch.setattr(engine, "read_mp3_metadata", _metadata)

    result = engine.write_lrc(audio, [("line", 1000)], {})
    content = result.read_bytes()
    monkeypatch.setattr(
        engine.tempfile,
        "mkstemp",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("rewritten")),
    )

    repeated = engine.write_lrc(audio, [("line", 1000)], {})

    assert result == audio.with_suffix(".lrc")
    assert repeated == result
    assert repeated.read_bytes() == content


def test_failed_generation_leaves_existing_sidecar_untouched(tmp_path, monkeypatch):
    audio = tmp_path / "Rental.mp3"
    audio.write_bytes(b"audio")
    sidecar = audio.with_suffix(".lrc")
    sidecar.write_bytes(b"known-good")
    monkeypatch.setattr(
        engine,
        "read_mp3_metadata",
        lambda *args: (_ for _ in ()).throw(RuntimeError("metadata failed")),
    )

    with pytest.raises(RuntimeError, match="metadata failed"):
        engine.write_lrc(audio, [("new", 1000)], {})

    assert sidecar.read_bytes() == b"known-good"


def test_failed_atomic_replace_leaves_existing_sidecar_and_no_partial(tmp_path, monkeypatch):
    audio = tmp_path / "Rental.mp3"
    audio.write_bytes(b"audio")
    sidecar = audio.with_suffix(".lrc")
    sidecar.write_bytes(b"known-good")
    monkeypatch.setattr(engine, "read_mp3_metadata", _metadata)
    original_replace = Path.replace

    def fail_sidecar_replace(path: Path, target: Path):
        if target == sidecar:
            raise OSError("replace failed")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "replace", fail_sidecar_replace)

    with pytest.raises(OSError, match="replace failed"):
        engine.write_lrc(audio, [("new", 2000)], {})

    assert sidecar.read_bytes() == b"known-good"
    assert not list(tmp_path.glob(".Rental.lrc.*.tmp"))

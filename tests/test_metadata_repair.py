from __future__ import annotations

import json
import os
import struct
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TIT2, TXXX, USLT
from mutagen.mp4 import MP4, MP4Cover

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.backup.manager import backup_file, restore_file, write_manifest
from juice_lyrics.config.settings import Settings
from juice_lyrics.library.media import read_audio_metadata
from juice_lyrics.services.catalogue import LyricAvailability, SongDetails
from juice_lyrics.services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibraryStateStatus,
    LibraryTrack,
)
from juice_lyrics.services.metadata_audit import build_metadata_audit
from juice_lyrics.services.metadata_repair import (
    MetadataRepairDependencies,
    execute_metadata_repair,
    plan_metadata_repair,
    write_metadata_fields,
)
from juice_lyrics.state import file_fingerprint, read_state_file, sha256_file, write_state_file


def _make_mp3(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = b"\xff\xfb\x90\x64" + b"\0" * 413
    path.write_bytes(frame * 12)
    tags = ID3()
    tags.add(TIT2(encoding=3, text=["Old title"]))
    tags.add(TALB(encoding=3, text=["Album"]))
    tags.add(USLT(encoding=3, lang="eng", desc="kept", text="embedded lyrics"))
    tags.add(TXXX(encoding=3, desc="custom", text=["keep me"]))
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="cover", data=b"artwork"))
    tags.save(path)
    return path


def _make_flac(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    sample_rate = 44_100
    total_samples = sample_rate * 2
    packed = (sample_rate << 44) | ((2 - 1) << 41) | ((16 - 1) << 36) | total_samples
    stream_info = (
        struct.pack(">HH", 4096, 4096)
        + b"\0" * 6
        + packed.to_bytes(8, "big")
        + b"\0" * 16
    )
    path.write_bytes(b"fLaC" + b"\x80" + len(stream_info).to_bytes(3, "big") + stream_info)
    audio = FLAC(path)
    audio["TITLE"] = ["Old title"]
    audio["ALBUM"] = ["Album"]
    audio["LYRICS"] = ["embedded lyrics"]
    audio["CUSTOM"] = ["keep me"]
    picture = Picture()
    picture.type = 3
    picture.mime = "image/jpeg"
    picture.desc = "cover"
    picture.data = b"artwork"
    audio.add_picture(picture)
    audio.save()
    return path


def _atom(name: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", len(payload) + 8, name) + payload


def _make_m4a(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    timescale = 44_100
    movie_header = _atom(
        b"mvhd",
        b"\0\0\0\0" + struct.pack(">IIII", 0, 0, timescale, timescale * 2),
    )
    path.write_bytes(
        _atom(b"ftyp", b"M4A \0\0\0\0M4A mp42")
        + _atom(b"moov", movie_header)
        + _atom(b"mdat", b"synthetic AAC payload")
    )
    audio = MP4(path)
    audio.add_tags()
    audio["\xa9nam"] = ["Old title"]
    audio["\xa9alb"] = ["Album"]
    audio["\xa9lyr"] = ["embedded lyrics"]
    audio["covr"] = [MP4Cover(b"artwork", imageformat=MP4Cover.FORMAT_JPEG)]
    audio["----:com.apple.iTunes:custom"] = [b"keep me"]
    audio.save()
    return path


def _fixture(tmp_path: Path, suffix: str, *, locked: bool = True):
    root = tmp_path / "music"
    makers = {".mp3": _make_mp3, ".flac": _make_flac, ".m4a": _make_m4a}
    path = makers[suffix](root / f"Album/track{suffix}")
    sidecar = path.with_suffix(".lrc")
    sidecar.write_bytes(b"[00:01.00]sidecar stays unchanged\n")
    digest = sha256_file(path)
    fingerprint = file_fingerprint(path)
    reference = str(path.relative_to(root))
    entry = {
        "sha256": digest,
        "song_id": 42,
        "api_name": "New title",
        "lyric_type": "keep",
        "lrc": str(sidecar),
        "custom": {"preserve": True},
    }
    if locked:
        entry.update(identity_source="manual", identity_locked=True)
    state_file = tmp_path / "data/state.json"
    write_state_file(state_file, {"files": {reference: entry}, "top_custom": 9})
    track = LibraryTrack(
        reference=reference,
        path=path,
        relative_path=path.relative_to(root),
        filename=path.name,
        title="Old title",
        duration_seconds=2.0,
        match_status=LibraryMatchStatus.MATCHED,
        matched_title="New title",
        lyric_status=LibraryLyricStatus.PLAIN,
        lrc_status=LibraryLrcStatus.PRESENT,
        lrc_path=sidecar,
        state_status=LibraryStateStatus.CURRENT,
        artist=None,
        album="Album",
        media_format=suffix[1:].upper(),
        content_sha256=digest,
        content_fingerprint=fingerprint,
        identity_source="manual" if locked else "automatic",
        identity_locked=locked,
        catalogue_id=42,
    )
    details = SongDetails(
        1,
        42,
        "New title",
        "released",
        "DRFL",
        "0:02",
        ("Juice WRLD",),
        (),
        "Released/Album/New title.mp3",
        LyricAvailability.PLAIN,
        None,
        None,
        False,
        album="Album",
        track_number="2/20",
    )
    audit = build_metadata_audit(track, read_audio_metadata(path), details)
    return Settings(music_dir=root), track, audit, state_file, sidecar


def _dependencies(tmp_path: Path, **changes) -> MetadataRepairDependencies:
    root = tmp_path / "backups/one"
    values = dict(
        backup_root_factory=lambda: root,
        backup_writer=backup_file,
        manifest_writer=write_manifest,
        restorer=restore_file,
        state_reader=read_state_file,
        state_writer=write_state_file,
    )
    values.update(changes)
    return MetadataRepairDependencies(**values)


def _assert_unrelated_metadata_preserved(path: Path) -> None:
    if path.suffix == ".mp3":
        tags = ID3(path)
        assert tags.getall("USLT")[0].text == "embedded lyrics"
        assert tags.getall("APIC")[0].data == b"artwork"
        assert tags.getall("TXXX")[0].text == ["keep me"]
    elif path.suffix == ".flac":
        audio = FLAC(path)
        assert audio["lyrics"] == ["embedded lyrics"]
        assert audio["custom"] == ["keep me"]
        assert audio.pictures[0].data == b"artwork"
    else:
        audio = MP4(path)
        assert audio["\xa9lyr"] == ["embedded lyrics"]
        assert bytes(audio["covr"][0]) == b"artwork"
        assert audio["----:com.apple.iTunes:custom"] == [b"keep me"]


@pytest.mark.parametrize("suffix", (".mp3", ".flac", ".m4a"))
def test_safe_apply_repairs_selected_fields_and_preserves_everything_else(tmp_path, suffix):
    settings, track, audit, state_file, sidecar = _fixture(tmp_path, suffix)
    original = track.path.read_bytes()
    sidecar_before = sidecar.read_bytes()
    deps = _dependencies(tmp_path)
    plan = plan_metadata_repair(
        settings,
        audit,
        ("title", "artist", "track_number"),
        state_file=state_file,
        dependencies=deps,
    )

    result = execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    metadata = read_audio_metadata(track.path)
    assert metadata.title == "New title"
    assert metadata.artist == "Juice WRLD"
    assert metadata.album == "Album"
    assert metadata.track_number in {"2/20", "2"} or metadata.track_number.startswith("2/")
    assert sidecar.read_bytes() == sidecar_before
    assert result.sha256_before == sha256_file(result.backup_path)
    assert result.sha256_after == sha256_file(track.path)
    assert result.sha256_before != result.sha256_after
    state = read_state_file(state_file)
    entry = state["files"][track.reference]
    assert entry["sha256"] == result.sha256_after
    assert entry["song_id"] == 42 and entry["api_name"] == "New title"
    assert entry["identity_source"] == "manual" and entry["identity_locked"] is True
    assert entry["lyric_type"] == "keep" and entry["custom"] == {"preserve": True}
    assert state["top_custom"] == 9
    assert result.identity_lock_preserved is True
    _assert_unrelated_metadata_preserved(track.path)
    assert json.loads((result.backup_root / "manifest.json").read_text())["files"][0]["operation"] == "metadata_repair"
    assert original == result.backup_path.read_bytes()


def test_plan_requires_explicit_previewed_field_selection(tmp_path):
    settings, _, audit, state_file, _ = _fixture(tmp_path, ".flac")
    deps = _dependencies(tmp_path)

    with pytest.raises(RuntimeError, match="Select at least one"):
        plan_metadata_repair(settings, audit, (), state_file=state_file, dependencies=deps)
    with pytest.raises(RuntimeError, match="not present"):
        plan_metadata_repair(
            settings, audit, ("album",), state_file=state_file, dependencies=deps
        )


def test_execution_requires_confirmation_and_creates_no_backup_without_it(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".m4a")
    deps = _dependencies(tmp_path)
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )
    before = track.path.read_bytes()

    with pytest.raises(RuntimeError, match="explicit confirmation"):
        execute_metadata_repair(plan, dependencies=deps)

    assert track.path.read_bytes() == before
    assert not (tmp_path / "backups").exists()


def test_backup_failure_stops_before_mutation(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".mp3")
    before = track.path.read_bytes()
    deps = _dependencies(
        tmp_path,
        backup_writer=lambda *args: (_ for _ in ()).throw(OSError("backup full")),
    )
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )

    with pytest.raises(OSError, match="backup full"):
        execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    assert track.path.read_bytes() == before
    assert read_state_file(state_file)["files"][track.reference]["sha256"] == sha256_file(track.path)


def test_manifest_failure_stops_before_mutation_with_recoverable_copy(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".m4a")
    before = track.path.read_bytes()
    deps = _dependencies(
        tmp_path,
        manifest_writer=lambda *args: (_ for _ in ()).throw(OSError("manifest failed")),
    )
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )

    with pytest.raises(OSError, match="manifest failed"):
        execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    assert track.path.read_bytes() == before
    assert (tmp_path / "backups/one/Album/track.m4a").read_bytes() == before


def test_interruption_while_editing_temporary_copy_leaves_original_unchanged(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".flac")
    before = track.path.read_bytes()
    deps = _dependencies(
        tmp_path,
        tag_writer=lambda *args: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )

    with pytest.raises(KeyboardInterrupt):
        execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    assert track.path.read_bytes() == before
    assert not tuple(track.path.parent.glob(f".{track.path.name}.*{track.path.suffix}"))


def test_state_conflict_during_temporary_edit_aborts_before_replace(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".m4a")
    before = track.path.read_bytes()

    def conflicting_writer(path, values):
        write_metadata_fields(path, values)
        state_file.write_text('{"files": {}, "concurrent": true}', encoding="utf-8")

    deps = _dependencies(tmp_path, tag_writer=conflicting_writer)
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )

    with pytest.raises(RuntimeError, match="state changed"):
        execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    assert track.path.read_bytes() == before
    assert json.loads(state_file.read_text())["concurrent"] is True


def test_state_write_failure_rolls_back_replaced_audio_and_preserves_lock(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".mp3")
    before = track.path.read_bytes()
    state_before = state_file.read_bytes()
    deps = _dependencies(
        tmp_path,
        state_writer=lambda *args: (_ for _ in ()).throw(OSError("state unavailable")),
    )
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )

    with pytest.raises(OSError, match="state unavailable"):
        execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    assert track.path.read_bytes() == before
    assert state_file.read_bytes() == state_before
    assert read_state_file(state_file)["files"][track.reference]["identity_locked"] is True


def test_rollback_failure_is_reported_and_backup_remains_recoverable(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".mp3")
    deps = _dependencies(
        tmp_path,
        state_writer=lambda *args: (_ for _ in ()).throw(OSError("state unavailable")),
        restorer=lambda *args: (_ for _ in ()).throw(OSError("restore unavailable")),
    )
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )

    with pytest.raises(RuntimeError, match="automatic rollback failed"):
        execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    backup = tmp_path / "backups/one/Album/track.mp3"
    assert sha256_file(backup) == plan.original_sha256
    assert read_state_file(state_file)["files"][track.reference]["sha256"] == plan.original_sha256


def test_interruption_immediately_after_atomic_replace_rolls_back(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".m4a")
    before = track.path.read_bytes()

    def replace_then_interrupt(source, destination):
        os.replace(source, destination)
        raise KeyboardInterrupt()

    deps = _dependencies(tmp_path, replacer=replace_then_interrupt)
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )

    with pytest.raises(KeyboardInterrupt):
        execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    assert track.path.read_bytes() == before
    assert read_state_file(state_file)["files"][track.reference]["sha256"] == plan.original_sha256


def test_interruption_after_atomic_state_write_restores_state_and_audio(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".flac")
    audio_before = track.path.read_bytes()
    state_before = state_file.read_bytes()

    def write_then_interrupt(path, state):
        write_state_file(path, state)
        raise KeyboardInterrupt()

    deps = _dependencies(tmp_path, state_writer=write_then_interrupt)
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )

    with pytest.raises(KeyboardInterrupt):
        execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    assert track.path.read_bytes() == audio_before
    assert state_file.read_bytes() == state_before


def test_changed_audio_or_state_is_rejected_before_backup(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".flac")
    deps = _dependencies(tmp_path)
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )
    state_file.write_text('{"files": {}, "changed": true}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="state changed"):
        execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    assert not (tmp_path / "backups").exists()

    settings2, track2, audit2, state_file2, _ = _fixture(tmp_path / "second", ".flac")
    deps2 = _dependencies(tmp_path / "second")
    plan2 = plan_metadata_repair(
        settings2, audit2, ("title",), state_file=state_file2, dependencies=deps2
    )
    track2.path.write_bytes(track2.path.read_bytes() + b"changed")
    with pytest.raises(RuntimeError, match="audio changed"):
        execute_metadata_repair(plan2, confirmed=True, dependencies=deps2)
    assert not (tmp_path / "second/backups").exists()


def test_unrelated_tag_change_on_working_copy_is_detected(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".flac")
    before = track.path.read_bytes()

    def corrupting_writer(path, values):
        write_metadata_fields(path, values)
        audio = FLAC(path)
        audio["LYRICS"] = ["damaged"]
        audio.save()

    deps = _dependencies(tmp_path, tag_writer=corrupting_writer)
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )

    with pytest.raises(RuntimeError, match="unrelated tags"):
        execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    assert track.path.read_bytes() == before


def test_automatic_identity_remains_unlocked_after_verified_edit(tmp_path):
    settings, track, audit, state_file, _ = _fixture(tmp_path, ".m4a", locked=False)
    deps = _dependencies(tmp_path)
    plan = plan_metadata_repair(
        settings, audit, ("title",), state_file=state_file, dependencies=deps
    )

    result = execute_metadata_repair(plan, confirmed=True, dependencies=deps)

    entry = read_state_file(state_file)["files"][track.reference]
    assert result.identity_lock_preserved is False
    assert "identity_locked" not in entry and "identity_source" not in entry

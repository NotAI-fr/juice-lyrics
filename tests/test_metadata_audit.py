from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.library.media import AudioMetadata, read_mp3_metadata
from juice_lyrics.services.catalogue import LyricAvailability, SongDetails
from juice_lyrics.services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibraryStateStatus,
    LibraryTrack,
)
from juice_lyrics.services.metadata_audit import (
    MetadataProposalConfidence,
    audit_track_metadata,
    build_metadata_audit,
)


def _track(path: Path, *, locked: bool = False, catalogue_id=42) -> LibraryTrack:
    return LibraryTrack(
        reference=path.name,
        path=path,
        relative_path=Path(path.name),
        filename=path.name,
        title=path.stem,
        duration_seconds=212.3,
        match_status=(
            LibraryMatchStatus.MATCHED
            if catalogue_id is not None
            else LibraryMatchStatus.UNMATCHED
        ),
        matched_title="10 Feet" if catalogue_id is not None else None,
        lyric_status=LibraryLyricStatus.PLAIN,
        lrc_status=LibraryLrcStatus.PRESENT,
        lrc_path=path.with_suffix(".lrc"),
        state_status=LibraryStateStatus.CURRENT,
        media_format=path.suffix[1:].upper(),
        content_sha256="saved-hash",
        identity_source="manual" if locked else "automatic",
        identity_locked=locked,
        catalogue_id=catalogue_id,
    )


def _details(**changes) -> SongDetails:
    values = {
        "selection_index": 1,
        "song_id": 42,
        "title": "10 Feet",
        "category": "released",
        "era": "DRFL",
        "length": "3:32",
        "artists": ("Juice WRLD",),
        "producers": (),
        "media_path": "Released/Death Race For Love/10 Feet.mp3",
        "lyrics": LyricAvailability.SYNCED,
        "synced_lyrics": None,
        "plain_lyrics": None,
        "downloadable": False,
        "album": "Death Race For Love",
        "track_number": "8",
    }
    values.update(changes)
    return SongDetails(**values)


@pytest.mark.parametrize("suffix", (".mp3", ".flac", ".m4a"))
def test_missing_supported_fields_are_confident_for_all_formats(tmp_path, suffix):
    path = tmp_path / f"track{suffix}"
    path.write_bytes(b"unchanged audio")
    track = _track(path, locked=True)

    audit = audit_track_metadata(
        Settings(music_dir=tmp_path),
        track,
        metadata_reader=lambda path: AudioMetadata(None, None, None, 212.3, None),
        details_provider=lambda settings, song_id: _details(),
    )

    assert {item.field for item in audit.proposals} == {
        "title", "artist", "album", "track_number"
    }
    assert all(
        item.confidence is MetadataProposalConfidence.CONFIDENT
        for item in audit.proposals
    )
    assert "selected and locked manually" in " ".join(audit.notes)
    assert path.read_bytes() == b"unchanged audio"


def test_existing_valid_differences_require_review_not_replacement(tmp_path):
    track = _track(tmp_path / "track.flac")
    audit = build_metadata_audit(
        track,
        AudioMetadata("10 Feet", "Juice WRLD", "My DRFL Edition", 212.3, "08"),
        _details(),
    )

    assert {item.field for item in audit.proposals} == {"album", "track_number"}
    assert all(
        item.confidence is MetadataProposalConfidence.REVIEW
        for item in audit.proposals
    )
    assert all("user review" in item.reason for item in audit.proposals)


@pytest.mark.parametrize(
    "local_title",
    ("Song (Live)", "Song (v2)", "Song (Recording Session)", "Song (Extended)"),
)
def test_version_sensitive_title_is_never_a_confident_repair(tmp_path, local_title):
    audit = build_metadata_audit(
        _track(tmp_path / "track.m4a"),
        AudioMetadata(local_title, "Juice WRLD", None, 200.0),
        _details(title="Song", album=None, track_number=None),
    )

    title = next(item for item in audit.proposals if item.field == "title")
    assert title.confidence is MetadataProposalConfidence.REVIEW
    assert "different recording/version markers" in title.reason


def test_file_change_during_preview_rejects_all_proposals(tmp_path):
    path = tmp_path / "track.flac"
    path.write_bytes(b"audio")
    fingerprints = iter(((1, 1, 1, 1, 1), (2, 1, 1, 1, 1)))

    audit = audit_track_metadata(
        Settings(music_dir=tmp_path),
        _track(path),
        metadata_reader=lambda path: AudioMetadata(None, None, None, 212.3),
        details_provider=lambda settings, song_id: _details(),
        fingerprint_reader=lambda path: next(fingerprints),
    )

    assert audit.proposals == ()
    assert audit.error == "Refresh the Library and try again."


def test_manual_lock_is_not_trusted_after_snapshot_fingerprint_changes(tmp_path):
    path = tmp_path / "track.m4a"
    path.write_bytes(b"replacement")
    calls = []
    track = replace(
        _track(path, locked=True),
        content_fingerprint=(1, 1, 1, 1, 1),
    )

    audit = audit_track_metadata(
        Settings(music_dir=tmp_path),
        track,
        metadata_reader=lambda path: calls.append("metadata"),
        details_provider=lambda settings, song_id: calls.append("catalogue"),
        fingerprint_reader=lambda path: (2, 1, 1, 1, 1),
    )

    assert audit.proposals == ()
    assert audit.error == "Sync Library and try again."
    assert calls == []


def test_unknown_identity_does_not_read_tags_or_call_catalogue(tmp_path):
    calls = []
    audit = audit_track_metadata(
        Settings(music_dir=tmp_path),
        _track(tmp_path / "unknown.mp3", catalogue_id=None),
        metadata_reader=lambda path: calls.append("metadata"),
        details_provider=lambda settings, song_id: calls.append("catalogue"),
        fingerprint_reader=lambda path: calls.append("fingerprint"),
    )

    assert audit.proposals == ()
    assert calls == []
    assert "not guessed" in " ".join(audit.notes)


def test_incomplete_or_inconsistent_catalogue_data_is_not_guessed(tmp_path):
    path = tmp_path / "track.mp3"
    path.write_bytes(b"unchanged")
    local = AudioMetadata(None, None, None, 212.3, None)
    incomplete = audit_track_metadata(
        Settings(music_dir=tmp_path),
        _track(path),
        metadata_reader=lambda path: local,
        details_provider=lambda settings, song_id: _details(
            title="10 Feet", artists=(), album=None, track_number=None
        ),
    )
    inconsistent = audit_track_metadata(
        Settings(music_dir=tmp_path),
        _track(path),
        metadata_reader=lambda path: local,
        details_provider=lambda settings, song_id: _details(song_id=99),
    )

    assert [item.field for item in incomplete.proposals] == ["title"]
    assert inconsistent.proposals == ()
    assert "inconsistent" in " ".join(inconsistent.notes)


def test_audit_is_read_only_for_media_state_lyrics_backups_and_rmpc(tmp_path):
    media = tmp_path / "track.flac"
    sidecar = tmp_path / "track.lrc"
    state = tmp_path / "state.json"
    backup = tmp_path / "backup.json"
    rmpc = tmp_path / "rmpc.ron"
    files = {
        media: b"audio",
        sidecar: b"[00:01.00]lyrics",
        state: b'{"custom": true}',
        backup: b"backup",
        rmpc: b"config",
    }
    for path, data in files.items():
        path.write_bytes(data)

    audit = audit_track_metadata(
        Settings(music_dir=tmp_path),
        _track(media),
        metadata_reader=lambda path: AudioMetadata(None, None, None, 212.3),
        details_provider=lambda settings, song_id: _details(),
    )

    assert audit.confident_count == 4
    assert {path: path.read_bytes() for path in files} == files


def test_mp3_reader_exposes_supported_repair_fields(monkeypatch, tmp_path):
    class Frame:
        def __init__(self, value):
            self.text = [value]

    class FakeMp3:
        tags = {
            "TIT2": Frame("Title"),
            "TPE1": Frame("Artist"),
            "TALB": Frame("Album"),
            "TRCK": Frame("4/18"),
        }
        info = type("Info", (), {"length": 123.5})()

    monkeypatch.setattr("juice_lyrics.library.media.MP3", lambda path: FakeMp3())

    metadata = read_mp3_metadata(tmp_path / "track.mp3")

    assert metadata == AudioMetadata("Title", "Artist", "Album", 123.5, "4/18")

from __future__ import annotations

from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.services.library_duplicates import (
    DuplicateConfidence,
    detect_library_duplicates,
)
from juice_lyrics.services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibrarySnapshot,
    LibraryStateStatus,
    LibraryTrack,
)


def _track(
    root: Path,
    name: str,
    *,
    title: str = "Song",
    artist: str | None = "Juice WRLD",
    duration: float | None = 180.0,
    digest: str | None = None,
    song_id=None,
) -> LibraryTrack:
    path = root / name
    return LibraryTrack(
        reference=name,
        path=path,
        relative_path=Path(name),
        filename=path.name,
        title=title,
        duration_seconds=duration,
        match_status=(
            LibraryMatchStatus.MATCHED
            if song_id is not None
            else LibraryMatchStatus.UNMATCHED
        ),
        matched_title=title if song_id is not None else None,
        lyric_status=(
            LibraryLyricStatus.SYNCED
            if path.suffix.casefold() == ".mp3"
            else LibraryLyricStatus.PLAIN
        ),
        lrc_status=LibraryLrcStatus.PRESENT,
        lrc_path=path.with_suffix(".lrc"),
        state_status=LibraryStateStatus.CURRENT,
        artist=artist,
        album="Album",
        media_format=path.suffix[1:].upper(),
        content_sha256=digest,
        catalogue_id=song_id,
    )


def _report(root: Path, *tracks: LibraryTrack, tolerance: float = 3.0):
    return detect_library_duplicates(
        LibrarySnapshot(root, True, tracks),
        duration_tolerance=tolerance,
    )


def test_exact_duplicate_audio_uses_existing_sha_without_file_reads(tmp_path):
    first = _track(tmp_path, "A/Song.mp3", digest="same", song_id=1)
    second = _track(
        tmp_path,
        "B/Wrong tags.flac",
        title="Different metadata (Live)",
        artist="Someone Else",
        duration=999.0,
        digest="same",
        song_id=2,
    )

    report = _report(tmp_path, first, second)

    assert len(report.groups) == 1
    assert report.groups[0].confidence is DuplicateConfidence.EXACT
    assert "same SHA-256" in report.groups[0].evidence[0]
    assert report.file_count == 2


@pytest.mark.parametrize("suffix", [".mp3", ".flac", ".m4a"])
def test_probable_same_catalogue_recording_is_format_neutral(tmp_path, suffix):
    first = _track(tmp_path, f"One{suffix}", digest="one", song_id=94107)
    second = _track(tmp_path, f"Two{suffix}", duration=181.0, digest="two", song_id=94107)

    group = _report(tmp_path, first, second).groups[0]

    assert group.confidence is DuplicateConfidence.PROBABLE
    assert "Same catalogue identity (94107)" in group.evidence
    assert "Durations within 1.00s" in group.evidence


def test_probable_metadata_match_requires_title_artist_and_close_duration(tmp_path):
    first = _track(
        tmp_path,
        "Album/Bandit.flac",
        title="Bandit (with YoungBoy Never Broke Again)",
        artist="Juice WRLD, YoungBoy Never Broke Again",
        digest="one",
    )
    second = _track(
        tmp_path,
        "Singles/Bandit.m4a",
        title="Bandit (feat. YoungBoy Never Broke Again)",
        artist="YoungBoy Never Broke Again & Juice WRLD",
        duration=181.5,
        digest="two",
    )

    group = _report(tmp_path, first, second).groups[0]

    assert group.confidence is DuplicateConfidence.PROBABLE
    assert "Compatible title and recording variant" in group.evidence
    assert "Same artist metadata" in group.evidence


@pytest.mark.parametrize(
    ("ordinary", "variant"),
    [
        ("Song", "Song (v1)"),
        ("Song (v1)", "Song (v2)"),
        ("Song", "Song (Live)"),
        ("Song", "Song Remix"),
        ("Song", "Song (Recording Session)"),
        ("Song", "Song Extended"),
        ("Song", "Song (TV Mix)"),
    ],
)
def test_distinct_versions_are_not_probable_duplicates_even_with_same_identity(
    tmp_path, ordinary, variant
):
    first = _track(tmp_path, "One.mp3", title=ordinary, digest="one", song_id=10)
    second = _track(tmp_path, "Two.mp3", title=variant, digest="two", song_id=10)

    assert _report(tmp_path, first, second).groups == ()


def test_conflicting_catalogue_ids_or_distant_duration_prevent_probable_group(tmp_path):
    first = _track(tmp_path, "One.mp3", digest="one", song_id=10)
    conflicting = _track(tmp_path, "Two.mp3", digest="two", song_id=11)
    distant = _track(tmp_path, "Three.mp3", duration=190.0, digest="three", song_id=10)

    assert _report(tmp_path, first, conflicting).groups == ()
    assert _report(tmp_path, first, distant).groups == ()


def test_unknown_duration_can_use_same_identity_but_not_metadata_alone(tmp_path):
    known = _track(tmp_path, "Known.mp3", digest="one", song_id=10)
    identity_unknown = _track(
        tmp_path, "Identity.mp3", duration=None, digest="two", song_id=10
    )
    metadata_unknown = _track(
        tmp_path, "Metadata.mp3", duration=None, digest="three", song_id=None
    )

    assert len(_report(tmp_path, known, identity_unknown).groups) == 1
    assert _report(tmp_path, known, metadata_unknown).groups == ()


def test_all_members_must_be_pairwise_compatible_not_duration_chain(tmp_path):
    tracks = (
        _track(tmp_path, "A.mp3", duration=180.0, digest="a"),
        _track(tmp_path, "B.mp3", duration=182.5, digest="b"),
        _track(tmp_path, "C.mp3", duration=185.0, digest="c"),
    )

    report = _report(tmp_path, *tracks, tolerance=3.0)

    assert len(report.groups) == 1
    assert len(report.groups[0].tracks) == 2


def test_no_evidence_returns_empty_report_and_does_not_touch_files(tmp_path):
    audio = tmp_path / "Unique.mp3"
    sidecar = tmp_path / "Unique.lrc"
    audio.write_bytes(b"audio")
    sidecar.write_bytes(b"[00:01.00]keep")
    track = _track(tmp_path, audio.name, title="Unique", digest=None)

    report = _report(tmp_path, track)

    assert report.groups == ()
    assert audio.read_bytes() == b"audio"
    assert sidecar.read_bytes() == b"[00:01.00]keep"

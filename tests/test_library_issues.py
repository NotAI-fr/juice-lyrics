from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.services.library_issues import (
    LibraryIssueAction,
    LibraryIssueCategory,
    LibraryIssueSeverity,
    get_library_health,
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
    name: str = "Song.mp3",
    *,
    media_format: str = "MP3",
    lyric_status: LibraryLyricStatus | None = None,
    **changes,
) -> LibraryTrack:
    path = root / name
    default_lyrics = (
        LibraryLyricStatus.SYNCED
        if media_format == "MP3"
        else LibraryLyricStatus.PLAIN
    )
    values = {
        "reference": name,
        "path": path,
        "relative_path": Path(name),
        "filename": path.name,
        "title": path.stem,
        "duration_seconds": 180.0,
        "match_status": LibraryMatchStatus.MATCHED,
        "matched_title": path.stem,
        "lyric_status": lyric_status or default_lyrics,
        "lrc_status": LibraryLrcStatus.PRESENT,
        "lrc_path": path.with_suffix(".lrc"),
        "state_status": LibraryStateStatus.CURRENT,
        "artist": "Juice WRLD",
        "album": "Album",
        "media_format": media_format,
    }
    values.update(changes)
    return LibraryTrack(**values)


def _health(root: Path, *tracks: LibraryTrack):
    return get_library_health(LibrarySnapshot(root, True, tracks))


@pytest.mark.parametrize(
    ("suffix", "format_name"),
    [(".mp3", "MP3"), (".flac", "FLAC"), (".m4a", "M4A")],
)
def test_format_appropriate_healthy_track_is_excluded(tmp_path, suffix, format_name):
    health = _health(tmp_path, _track(tmp_path, f"Healthy{suffix}", media_format=format_name))

    assert health.issue_count == 0
    assert health.healthy_count == 1


def test_unknown_track_is_one_actionable_catalogue_issue(tmp_path):
    track = _track(
        tmp_path,
        "Unknown.flac",
        media_format="FLAC",
        match_status=LibraryMatchStatus.UNMATCHED,
        matched_title=None,
    )

    issue = _health(tmp_path, track).issues[0]

    assert issue.categories == (LibraryIssueCategory.CATALOGUE,)
    assert issue.summary == "Catalogue match unknown"
    assert issue.action is LibraryIssueAction.MANUAL_MATCH


def test_valid_manual_lock_is_healthy_but_observed_unavailable_lock_is_issue(tmp_path):
    locked = _track(
        tmp_path,
        "Locked.m4a",
        media_format="M4A",
        identity_source="manual",
        identity_locked=True,
    )
    assert _health(tmp_path, locked).issues == ()

    unavailable = replace(
        locked,
        warning="The manually selected catalogue recording is unavailable.",
    )
    issue = _health(tmp_path, unavailable).issues[0]
    assert issue.summary == "Manual catalogue choice unavailable"
    assert issue.action is LibraryIssueAction.MANUAL_MATCH


def test_missing_lyrics_invalid_lrc_and_verification_failure_are_single_rows(tmp_path):
    missing = _track(
        tmp_path,
        "Missing.flac",
        media_format="FLAC",
        lyric_status=LibraryLyricStatus.NONE,
        lrc_status=LibraryLrcStatus.NONE,
        lrc_path=None,
        verification_error="no embedded FLAC lyrics",
    )
    invalid_lrc = _track(
        tmp_path,
        "Invalid.m4a",
        media_format="M4A",
        lrc_status=LibraryLrcStatus.INVALID,
        warning="Adjacent LRC has no timestamped lyric lines.",
    )
    corrupt = _track(
        tmp_path,
        "Broken.mp3",
        lyric_status=LibraryLyricStatus.NONE,
        lrc_status=LibraryLrcStatus.NONE,
        lrc_path=None,
        verification_error="could not read ID3 header",
        warning="could not read ID3 header",
    )

    health = _health(tmp_path, missing, invalid_lrc, corrupt)

    assert len(health.issues) == 3
    assert health.issues[0].categories == (LibraryIssueCategory.LYRICS,)
    assert health.issues[0].severity is LibraryIssueSeverity.WARNING
    assert health.issues[1].categories == (LibraryIssueCategory.LYRICS,)
    assert health.issues[2].categories == (
        LibraryIssueCategory.VERIFICATION,
        LibraryIssueCategory.LYRICS,
    )
    assert health.issues[2].severity is LibraryIssueSeverity.ERROR


def test_missing_expected_sidecar_and_metadata_block_are_actionable(tmp_path):
    sidecar = _track(
        tmp_path,
        "Sidecar.mp3",
        lrc_status=LibraryLrcStatus.MISSING,
        lrc_path=tmp_path / "Sidecar.lrc",
    )
    metadata = _track(
        tmp_path,
        "Metadata.flac",
        media_format="FLAC",
        match_status=LibraryMatchStatus.UNMATCHED,
        matched_title=None,
        artist=None,
        warning="FLAC metadata is missing artist; track cannot be matched safely.",
    )

    issues = _health(tmp_path, sidecar, metadata).issues

    assert LibraryIssueCategory.LYRICS in issues[0].categories
    assert issues[0].action is LibraryIssueAction.REFRESH_LYRICS
    assert LibraryIssueCategory.METADATA in issues[1].categories
    assert issues[1].action is LibraryIssueAction.MANUAL_MATCH


def test_new_changed_and_invalid_state_are_one_row_each_and_sync_actionable(tmp_path):
    tracks = tuple(
        _track(tmp_path, f"{status.value}.mp3", state_status=status)
        for status in (
            LibraryStateStatus.NEW,
            LibraryStateStatus.CHANGED,
            LibraryStateStatus.INVALID,
        )
    )

    issues = _health(tmp_path, *tracks).issues

    assert len(issues) == 3
    assert all(LibraryIssueCategory.STATE in issue.categories for issue in issues)
    assert all(issue.action is LibraryIssueAction.SYNC for issue in issues)
    assert issues[-1].severity is LibraryIssueSeverity.ERROR


def test_health_recomputes_from_replacement_sync_snapshot(tmp_path):
    unknown = _track(
        tmp_path,
        match_status=LibraryMatchStatus.UNMATCHED,
        matched_title=None,
    )
    before = _health(tmp_path, unknown)
    after = _health(
        tmp_path,
        replace(
            unknown,
            match_status=LibraryMatchStatus.MATCHED,
            matched_title="Song",
        ),
    )
    newly_broken = _health(
        tmp_path,
        replace(
            unknown,
            match_status=LibraryMatchStatus.MATCHED,
            matched_title="Song",
            lyric_status=LibraryLyricStatus.NONE,
            verification_error="no managed lyrics frame",
        ),
    )

    assert before.issue_count == 1
    assert after.issue_count == 0
    assert newly_broken.issue_count == 1

"""Actionable Library health derived from the existing read-only snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibrarySnapshot,
    LibraryStateStatus,
    LibraryTrack,
)


class LibraryIssueCategory(str, Enum):
    CATALOGUE = "catalogue"
    LYRICS = "lyrics"
    VERIFICATION = "verification"
    METADATA = "metadata"
    STATE = "state"


class LibraryIssueSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"


class LibraryIssueAction(str, Enum):
    MANUAL_MATCH = "manual_match"
    REFRESH_LYRICS = "refresh_lyrics"
    VERIFY = "verify"
    SYNC = "sync"


@dataclass(frozen=True, slots=True)
class LibraryIssue:
    """One user-facing row for all actionable conditions on one track."""

    track: LibraryTrack
    categories: tuple[LibraryIssueCategory, ...]
    severity: LibraryIssueSeverity
    summary: str
    details: tuple[str, ...]
    action: LibraryIssueAction

    @property
    def category_label(self) -> str:
        return " / ".join(category.value.title() for category in self.categories)


@dataclass(frozen=True, slots=True)
class LibraryHealth:
    snapshot: LibrarySnapshot
    issues: tuple[LibraryIssue, ...]

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def healthy_count(self) -> int:
        return max(0, self.snapshot.total_track_count - self.issue_count)


def _append_once(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _issue_for_track(track: LibraryTrack) -> LibraryIssue | None:
    categories: list[LibraryIssueCategory] = []
    details: list[str] = []
    severity = LibraryIssueSeverity.WARNING
    summary: str | None = None
    action: LibraryIssueAction | None = None
    warning = (track.warning or "").casefold()

    if track.state_status is LibraryStateStatus.INVALID:
        categories.append(LibraryIssueCategory.STATE)
        _append_once(details, "Stored state or the local audio could not be validated safely.")
        summary = "Library state could not be validated"
        action = LibraryIssueAction.SYNC
        severity = LibraryIssueSeverity.ERROR
    elif track.state_status is LibraryStateStatus.CHANGED:
        categories.append(LibraryIssueCategory.STATE)
        _append_once(details, "The local audio changed since its saved library state.")
        summary = "Local audio changed"
        action = LibraryIssueAction.SYNC
    elif track.state_status is LibraryStateStatus.NEW:
        categories.append(LibraryIssueCategory.STATE)
        _append_once(details, "This track has not been recorded by Sync Library yet.")
        summary = "New track needs Library Sync"
        action = LibraryIssueAction.SYNC

    locked_unavailable = track.identity_locked and (
        "manually selected catalogue recording is unavailable" in warning
        or "manual catalogue" in warning and "unavailable" in warning
    )
    if locked_unavailable:
        categories.append(LibraryIssueCategory.CATALOGUE)
        _append_once(
            details,
            "The saved manual choice is preserved, but that catalogue recording was unavailable when last checked.",
        )
        summary = "Manual catalogue choice unavailable"
        action = LibraryIssueAction.MANUAL_MATCH
    elif track.match_status is LibraryMatchStatus.UNMATCHED:
        categories.append(LibraryIssueCategory.CATALOGUE)
        _append_once(details, "No catalogue identity has been established safely.")
        if summary is None:
            summary = "Catalogue match unknown"
        action = LibraryIssueAction.MANUAL_MATCH

    metadata_problem = (
        "metadata is missing" in warning
        or "metadata could not be read" in warning
    )
    if metadata_problem:
        categories.append(LibraryIssueCategory.METADATA)
        _append_once(details, "Local metadata is incomplete or unreadable and blocks safe automatic matching.")
        if summary is None or summary == "Catalogue match unknown":
            summary = "Metadata blocks automatic matching"
        if action is None:
            action = LibraryIssueAction.MANUAL_MATCH

    verification_text = (track.verification_error or "").casefold()
    verification_problem = bool(
        verification_text
        and not verification_text.startswith("no embedded ")
        and verification_text != "no managed lyrics frame"
    )
    if verification_problem:
        categories.append(LibraryIssueCategory.VERIFICATION)
        _append_once(details, f"Verification reported: {track.verification_error}")
        severity = LibraryIssueSeverity.ERROR
        if summary is None:
            summary = "Audio or embedded lyrics failed verification"
        if action is None:
            action = LibraryIssueAction.VERIFY

    if track.lyric_status is LibraryLyricStatus.NONE:
        categories.append(LibraryIssueCategory.LYRICS)
        _append_once(details, "Supported embedded lyrics are missing or could not be read.")
        if not verification_problem:
            summary = summary or "Embedded lyrics missing"
        if action is None or action is LibraryIssueAction.VERIFY:
            action = LibraryIssueAction.REFRESH_LYRICS
    if track.lrc_status is LibraryLrcStatus.INVALID:
        categories.append(LibraryIssueCategory.LYRICS)
        _append_once(details, "The adjacent LRC does not contain valid timestamped lyric lines.")
        summary = summary or "Synchronized LRC is invalid"
        action = action or LibraryIssueAction.REFRESH_LYRICS
    elif track.lrc_status is LibraryLrcStatus.MISSING and track.needs_attention:
        categories.append(LibraryIssueCategory.LYRICS)
        _append_once(details, "The expected adjacent synchronized LRC is missing.")
        summary = summary or "Synchronized LRC is missing"
        action = action or LibraryIssueAction.REFRESH_LYRICS

    if not categories:
        return None
    unique_categories = tuple(dict.fromkeys(categories))
    return LibraryIssue(
        track=track,
        categories=unique_categories,
        severity=severity,
        summary=summary or "Track needs attention",
        details=tuple(details),
        action=action or LibraryIssueAction.VERIFY,
    )


def get_library_health(snapshot: LibrarySnapshot) -> LibraryHealth:
    """Project a current snapshot into one actionable issue row per track."""

    return LibraryHealth(
        snapshot,
        tuple(
            issue
            for track in snapshot.tracks
            if (issue := _issue_for_track(track)) is not None
        ),
    )

"""Read-only duplicate evidence derived from an existing Library snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from ..config.settings import DEFAULT_DURATION_TOLERANCE
from ..library.matching import (
    named_variants,
    normalize,
    normalize_words,
    parse_version,
    strip_feature_credit,
    strip_version,
)
from .library_status import LibrarySnapshot, LibraryTrack


class DuplicateConfidence(str, Enum):
    EXACT = "exact"
    PROBABLE = "probable"


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    confidence: DuplicateConfidence
    tracks: tuple[LibraryTrack, ...]
    evidence: tuple[str, ...]

    @property
    def title(self) -> str:
        return self.tracks[0].title


@dataclass(frozen=True, slots=True)
class DuplicateReport:
    snapshot: LibrarySnapshot
    groups: tuple[DuplicateGroup, ...]

    @property
    def file_count(self) -> int:
        return len({track.reference for group in self.groups for track in group.tracks})


_EXTRA_VARIANTS = {
    "alternate": r"\b(?:alternate|alt)\b",
    "extended": r"\bextended\b",
    "mix": r"\bmix\b",
    "remaster": r"\bremaster(?:ed)?\b",
    "session": r"\b(?:recording\s+session|studio\s+session|session)\b",
}


def _variant_signature(track: LibraryTrack) -> tuple[int | None, frozenset[str]]:
    variants = set(named_variants(track.title))
    variants.update(
        label
        for label, pattern in _EXTRA_VARIANTS.items()
        if re.search(pattern, track.title, re.I)
    )
    return parse_version(track.title), frozenset(variants)


def _base_title(track: LibraryTrack) -> str:
    return normalize(strip_version(strip_feature_credit(track.title)))


def _artist_key(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    parts = re.split(
        r"\s*(?:,|&|\bx\b|\bfeat(?:uring)?\.?\b|\bft\.?\b|\bwith\b)\s*",
        value,
        flags=re.I,
    )
    return tuple(sorted(part for raw in parts if (part := normalize_words(raw))))


def _duration_compatible(
    left: LibraryTrack,
    right: LibraryTrack,
    tolerance: float,
) -> bool:
    if left.duration_seconds is None or right.duration_seconds is None:
        return False
    return abs(left.duration_seconds - right.duration_seconds) <= tolerance


def _probable_pair(
    left: LibraryTrack,
    right: LibraryTrack,
    tolerance: float,
) -> bool:
    if _variant_signature(left) != _variant_signature(right):
        return False
    left_id, right_id = left.catalogue_id, right.catalogue_id
    if left_id is not None and right_id is not None:
        return (
            str(left_id) == str(right_id)
            and (
                _duration_compatible(left, right, tolerance)
                or left.duration_seconds is None
                or right.duration_seconds is None
            )
        )
    return bool(
        _base_title(left)
        and _base_title(left) == _base_title(right)
        and _artist_key(left.artist)
        and _artist_key(left.artist) == _artist_key(right.artist)
        and _duration_compatible(left, right, tolerance)
    )


def _related(left: LibraryTrack, right: LibraryTrack, tolerance: float) -> bool:
    return bool(
        left.content_sha256
        and left.content_sha256 == right.content_sha256
    ) or _probable_pair(left, right, tolerance)


def _groups(
    tracks: tuple[LibraryTrack, ...],
    tolerance: float,
) -> tuple[tuple[LibraryTrack, ...], ...]:
    grouped: list[list[LibraryTrack]] = []
    for track in sorted(tracks, key=lambda item: item.reference.casefold()):
        compatible = next(
            (
                group
                for group in grouped
                if all(_related(track, member, tolerance) for member in group)
            ),
            None,
        )
        if compatible is None:
            grouped.append([track])
        else:
            compatible.append(track)
    return tuple(
        tuple(group)
        for group in grouped
        if len(group) > 1
    )


def _group_evidence(tracks: tuple[LibraryTrack, ...], tolerance: float) -> tuple[str, ...]:
    evidence: list[str] = []
    hashes = {track.content_sha256 for track in tracks if track.content_sha256}
    if len(hashes) == 1 and all(track.content_sha256 for track in tracks):
        evidence.append("Identical file bytes (same SHA-256)")
    elif any(
        left.content_sha256
        and left.content_sha256 == right.content_sha256
        for index, left in enumerate(tracks)
        for right in tracks[index + 1 :]
    ):
        evidence.append("Some files have identical file bytes")
    ids = {str(track.catalogue_id) for track in tracks if track.catalogue_id is not None}
    if len(ids) == 1:
        evidence.append(f"Same catalogue identity ({next(iter(ids))})")
    base_title = _base_title(tracks[0])
    if base_title and all(_base_title(track) == base_title for track in tracks[1:]):
        evidence.append("Compatible title and recording variant")
    artist_key = _artist_key(tracks[0].artist)
    if artist_key and all(_artist_key(track.artist) == artist_key for track in tracks[1:]):
        evidence.append("Same artist metadata")
    durations = [track.duration_seconds for track in tracks if track.duration_seconds is not None]
    if len(durations) == len(tracks) and max(durations) - min(durations) <= tolerance:
        evidence.append(f"Durations within {max(durations) - min(durations):.2f}s")
    return tuple(evidence)


def detect_library_duplicates(
    snapshot: LibrarySnapshot,
    *,
    duration_tolerance: float = DEFAULT_DURATION_TOLERANCE,
) -> DuplicateReport:
    """Find conservative duplicate groups without reading files or calling APIs."""

    groups: list[DuplicateGroup] = []
    for tracks in _groups(snapshot.tracks, max(0.0, duration_tolerance)):
        hashes = {track.content_sha256 for track in tracks}
        confidence = (
            DuplicateConfidence.EXACT
            if None not in hashes and len(hashes) == 1
            else DuplicateConfidence.PROBABLE
        )
        groups.append(
            DuplicateGroup(
                confidence,
                tracks,
                _group_evidence(tracks, max(0.0, duration_tolerance)),
            )
        )
    groups.sort(
        key=lambda group: (
            group.confidence is not DuplicateConfidence.EXACT,
            group.title.casefold(),
            group.tracks[0].reference.casefold(),
        )
    )
    return DuplicateReport(snapshot, tuple(groups))

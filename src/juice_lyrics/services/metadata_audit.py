"""Read-only metadata repair proposals for one confirmed local track."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import re

from ..library.matching import named_variants, parse_version
from ..library.media import AudioMetadata, read_audio_metadata
from ..state import file_fingerprint
from .catalogue import SongDetails, get_song_details_by_id
from .library_status import LibraryTrack


class MetadataProposalConfidence(str, Enum):
    CONFIDENT = "confident"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class MetadataProposal:
    field: str
    label: str
    before: str | None
    after: str
    confidence: MetadataProposalConfidence
    reason: str


@dataclass(frozen=True, slots=True)
class MetadataAudit:
    track: LibraryTrack
    local: AudioMetadata | None
    catalogue: SongDetails | None
    proposals: tuple[MetadataProposal, ...]
    notes: tuple[str, ...]
    error: str | None = None

    @property
    def confident_count(self) -> int:
        return sum(
            item.confidence is MetadataProposalConfidence.CONFIDENT
            for item in self.proposals
        )

    @property
    def review_count(self) -> int:
        return len(self.proposals) - self.confident_count


MetadataReader = Callable[[Path], AudioMetadata]
DetailsProvider = Callable[..., SongDetails | None]
FingerprintReader = Callable[[Path], tuple[int, int, int, int, int]]


def _clean(value: str | None) -> str | None:
    text = str(value or "").strip()
    return text or None


def _title_is_version_sensitive(before: str, after: str) -> bool:
    patterns = {
        "alternate": r"\b(?:alternate|alt)\b",
        "extended": r"\bextended\b",
        "mix": r"\bmix\b",
        "remaster": r"\bremaster(?:ed)?\b",
        "session": r"\b(?:recording\s+session|session)\b",
    }
    before_extra = {label for label, pattern in patterns.items() if re.search(pattern, before, re.I)}
    after_extra = {label for label, pattern in patterns.items() if re.search(pattern, after, re.I)}
    return (
        parse_version(before) != parse_version(after)
        or named_variants(before) != named_variants(after)
        or before_extra != after_extra
    )


def _proposal(
    field: str,
    label: str,
    before: str | None,
    after: str | None,
) -> MetadataProposal | None:
    current = _clean(before)
    expected = _clean(after)
    if expected is None or current == expected:
        return None
    if current is None:
        return MetadataProposal(
            field,
            label,
            None,
            expected,
            MetadataProposalConfidence.CONFIDENT,
            "The local field is missing and the confirmed catalogue record supplies it.",
        )
    if field == "title" and _title_is_version_sensitive(current, expected):
        reason = (
            "The titles describe different recording/version markers; preserve the local "
            "value unless the user confirms this exact recording."
        )
    else:
        reason = (
            "The existing value is valid but differs from the catalogue; user review is "
            "required before replacing it."
        )
    return MetadataProposal(
        field,
        label,
        current,
        expected,
        MetadataProposalConfidence.REVIEW,
        reason,
    )


def build_metadata_audit(
    track: LibraryTrack,
    local: AudioMetadata,
    catalogue: SongDetails,
) -> MetadataAudit:
    """Compare trustworthy local tags with an already confirmed catalogue record."""

    catalogue_artist = ", ".join(catalogue.artists) or None
    proposals = tuple(
        item
        for item in (
            _proposal("title", "Title", local.title, catalogue.title),
            _proposal("artist", "Artist", local.artist, catalogue_artist),
            _proposal("album", "Album", local.album, catalogue.album),
            _proposal(
                "track_number",
                "Track number",
                local.track_number,
                catalogue.track_number,
            ),
        )
        if item is not None
    )
    notes: list[str] = []
    if not proposals:
        notes.append("No repairable differences were found in supported fields.")
    if not catalogue.artists:
        notes.append("The catalogue record does not provide trustworthy artist metadata.")
    if catalogue.album is None:
        notes.append("The catalogue record does not provide trustworthy album metadata.")
    if catalogue.track_number is None:
        notes.append("The catalogue record does not provide a track number.")
    if track.identity_locked:
        notes.append("Catalogue identity was selected and locked manually.")
    notes.append("Preview only — no files or application state were changed.")
    return MetadataAudit(track, local, catalogue, proposals, tuple(notes))


def audit_track_metadata(
    settings: object,
    track: LibraryTrack,
    *,
    details_provider: DetailsProvider = get_song_details_by_id,
    metadata_reader: MetadataReader = read_audio_metadata,
    fingerprint_reader: FingerprintReader = file_fingerprint,
) -> MetadataAudit:
    """Load one selected track's metadata evidence without writing anything."""

    if track.catalogue_id is None:
        return MetadataAudit(
            track,
            None,
            None,
            (),
            (
                "No confirmed catalogue identity is available; metadata was not guessed.",
                "Choose a catalogue match before preparing a repair preview.",
            ),
        )
    try:
        before = fingerprint_reader(track.path)
    except Exception as exc:
        return MetadataAudit(
            track,
            None,
            None,
            (),
            ("Preview only — no files or application state were changed.",),
            str(exc) or type(exc).__name__,
        )
    if track.content_fingerprint is not None and before != track.content_fingerprint:
        return MetadataAudit(
            track,
            None,
            None,
            (),
            ("The local file no longer matches the current Library snapshot.",),
            "Sync Library and try again.",
        )
    try:
        local = metadata_reader(track.path)
        catalogue = details_provider(settings, track.catalogue_id)
        after = fingerprint_reader(track.path)
    except Exception as exc:
        return MetadataAudit(
            track,
            None,
            None,
            (),
            ("Preview only — no files or application state were changed.",),
            str(exc) or type(exc).__name__,
        )
    if before != after:
        return MetadataAudit(
            track,
            local,
            catalogue,
            (),
            ("The local file changed while metadata was being inspected.",),
            "Refresh the Library and try again.",
        )
    if catalogue is None or str(catalogue.song_id) != str(track.catalogue_id):
        return MetadataAudit(
            track,
            local,
            catalogue,
            (),
            (
                "The confirmed catalogue recording was unavailable or returned inconsistent data.",
                "No metadata proposal was produced.",
            ),
        )
    return build_metadata_audit(track, local, catalogue)

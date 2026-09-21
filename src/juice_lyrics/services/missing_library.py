from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..config.settings import Settings
from .catalogue import CataloguePage, CatalogueSearchResult, search_catalogue_page
from .library_status import LibraryMatchStatus, LibrarySnapshot


CataloguePageProvider = Callable[..., CataloguePage]


class CatalogueCoverage(str, Enum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class MissingLibraryReport:
    """Identity-based comparison of loaded catalogue records and local media."""

    recordings: tuple[CatalogueSearchResult, ...]
    owned_ids: frozenset[str]
    local_unknown_count: int
    loaded_recording_count: int
    catalogue_total_count: int | None
    pages_loaded: int
    coverage: CatalogueCoverage
    unidentifiable_catalogue_count: int = 0
    error: str | None = None

    @property
    def missing_count(self) -> int:
        return len(self.recordings)

    @property
    def complete(self) -> bool:
        return self.coverage is CatalogueCoverage.COMPLETE


def get_missing_library(
    settings: Settings,
    snapshot: LibrarySnapshot,
    *,
    page_provider: CataloguePageProvider = search_catalogue_page,
    page_size: int = 100,
    max_pages: int = 200,
) -> MissingLibraryReport:
    """Load the paginated catalogue and compare only stable recording identities.

    Valid cached pages are naturally reused by ``search_catalogue_page``.  This
    function never reads or writes media/state and deliberately does not infer
    ownership from titles.
    """

    owned_ids = frozenset(
        str(track.catalogue_id)
        for track in snapshot.tracks
        if track.match_status is LibraryMatchStatus.MATCHED
        and track.catalogue_id is not None
    )
    unknown_count = sum(
        track.match_status is LibraryMatchStatus.UNMATCHED
        or track.catalogue_id is None
        for track in snapshot.tracks
    )
    records: dict[str, CatalogueSearchResult] = {}
    unidentifiable = 0
    page_number = 1
    pages_loaded = 0
    total_count: int | None = None
    terminal_page = False
    seen_pages: set[int] = set()
    error: str | None = None

    while page_number <= max_pages:
        if page_number in seen_pages:
            error = "Catalogue pagination repeated a page."
            break
        seen_pages.add(page_number)
        try:
            page = page_provider(
                settings,
                "",
                page=page_number,
                page_size=page_size,
                refresh=False,
            )
        except Exception as exc:
            error = str(exc) or type(exc).__name__
            break
        pages_loaded += 1
        total_count = max(total_count or 0, page.total_count)
        for item in page.results:
            if item.song_id is None:
                unidentifiable += 1
                continue
            records.setdefault(str(item.song_id), item)
        if page.next_page is None:
            terminal_page = True
            break
        page_number = page.next_page
    else:
        error = f"Catalogue pagination exceeded the {max_pages}-page safety limit."

    if pages_loaded == 0:
        coverage = CatalogueCoverage.UNAVAILABLE
    elif error or not terminal_page or unidentifiable:
        coverage = CatalogueCoverage.PARTIAL
    else:
        coverage = CatalogueCoverage.COMPLETE

    missing = tuple(
        item
        for song_id, item in records.items()
        if song_id not in owned_ids
    )
    return MissingLibraryReport(
        recordings=missing,
        owned_ids=owned_ids,
        local_unknown_count=unknown_count,
        loaded_recording_count=len(records),
        catalogue_total_count=total_count,
        pages_loaded=pages_loaded,
        coverage=coverage,
        unidentifiable_catalogue_count=unidentifiable,
        error=error,
    )

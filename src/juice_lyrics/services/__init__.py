"""Application services shared by command-line and interactive frontends."""

from .catalogue import (
    CatalogueSearchResult,
    LyricAvailability,
    SongDetails,
    get_song_details,
    search_catalogue,
)
from .library_status import LibraryStatus, get_library_status

__all__ = [
    "CatalogueSearchResult",
    "LibraryStatus",
    "LyricAvailability",
    "SongDetails",
    "get_library_status",
    "get_song_details",
    "search_catalogue",
]

"""Application services shared by command-line and interactive frontends."""

from .acquisition_queue import (
    QueueItem,
    QueueJob,
    QueueReferenceError,
    QueueSnapshot,
    QueueStatus,
    get_queue_snapshot,
    resolve_queue_reference,
)
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
    "QueueItem",
    "QueueJob",
    "QueueReferenceError",
    "QueueSnapshot",
    "QueueStatus",
    "SongDetails",
    "get_queue_snapshot",
    "get_library_status",
    "get_song_details",
    "search_catalogue",
    "resolve_queue_reference",
]

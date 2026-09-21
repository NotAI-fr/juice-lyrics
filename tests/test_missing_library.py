from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from juice_lyrics.config.settings import Settings
from juice_lyrics.services.catalogue import CataloguePage, CatalogueSearchResult, LyricAvailability
from juice_lyrics.services.library_status import (
    LibraryLrcStatus,
    LibraryLyricStatus,
    LibraryMatchStatus,
    LibrarySnapshot,
    LibraryStateStatus,
    LibraryTrack,
)
from juice_lyrics.services.missing_library import CatalogueCoverage, get_missing_library


def _result(song_id, title, *, category="released", path=None):
    return CatalogueSearchResult(
        1, song_id, title, category, "DRFL", "3:20", ("Juice WRLD",), (),
        path or f"Compilation/{title}.mp3", LyricAvailability.SYNCED, True,
    )


def _track(root: Path, name: str, song_id=None, *, media_format="MP3", locked=False):
    path = root / name
    return LibraryTrack(
        name, path, Path(name), name, path.stem, 200.0,
        LibraryMatchStatus.MATCHED if song_id is not None else LibraryMatchStatus.UNMATCHED,
        path.stem if song_id is not None else None,
        LibraryLyricStatus.PLAIN, LibraryLrcStatus.PRESENT, path.with_suffix(".lrc"),
        LibraryStateStatus.CURRENT, media_format=media_format,
        catalogue_id=song_id, identity_locked=locked,
        identity_source="manual" if locked else "automatic",
    )


def _snapshot(root, *tracks):
    return LibrarySnapshot(root, True, tracks)


def test_missing_library_compares_exact_recording_ids_across_pages_and_formats(tmp_path):
    root = tmp_path / "music"
    snapshot = _snapshot(
        root,
        _track(root, "Owned.mp3", 1),
        _track(root, "Locked.flac", "2", media_format="FLAC", locked=True),
        _track(root, "Unknown.m4a", None, media_format="M4A"),
    )
    calls = []

    def pages(settings, query, *, page, page_size, refresh):
        calls.append((query, page, page_size, refresh))
        if page == 1:
            return CataloguePage((_result(1, "Owned"), _result(2, "Locked")), 1, 2, 4, 2, None)
        return CataloguePage((_result(3, "Missing"), _result(4, "Missing (v2)", category="unreleased")), 2, 2, 4, None, 1)

    report = get_missing_library(Settings(music_dir=root), snapshot, page_provider=pages, page_size=2)

    assert [item.song_id for item in report.recordings] == [3, 4]
    assert report.owned_ids == {"1", "2"}
    assert report.local_unknown_count == 1
    assert report.coverage is CatalogueCoverage.COMPLETE
    assert calls == [("", 1, 2, False), ("", 2, 2, False)]


def test_duplicate_titles_and_versions_are_distinct_by_id(tmp_path):
    root = tmp_path / "music"
    page = CataloguePage(
        (_result(10, "Song"), _result(11, "Song"), _result(12, "Song (Live)", category="released")),
        1, 100, 3, None, None,
    )
    report = get_missing_library(
        Settings(music_dir=root), _snapshot(root, _track(root, "Song.mp3", 10)),
        page_provider=lambda *args, **kwargs: page,
    )
    assert [(item.song_id, item.title) for item in report.recordings] == [(11, "Song"), (12, "Song (Live)")]


def test_partial_page_failure_never_claims_complete_catalogue(tmp_path):
    root = tmp_path / "music"

    def pages(settings, query, *, page, **kwargs):
        if page == 2:
            raise RuntimeError("offline")
        return CataloguePage((_result(1, "Visible"),), 1, 1, 2, 2, None)

    report = get_missing_library(Settings(music_dir=root), _snapshot(root), page_provider=pages)
    assert report.coverage is CatalogueCoverage.PARTIAL
    assert report.missing_count == 1
    assert report.error == "offline"


def test_offline_before_first_page_reports_unavailable(tmp_path):
    root = tmp_path / "music"

    def unavailable(*args, **kwargs):
        raise RuntimeError("network unavailable")

    report = get_missing_library(Settings(music_dir=root), _snapshot(root), page_provider=unavailable)
    assert report.coverage is CatalogueCoverage.UNAVAILABLE
    assert report.recordings == ()
    assert report.error == "network unavailable"


def test_malformed_identity_makes_coverage_partial_and_is_not_called_missing(tmp_path):
    root = tmp_path / "music"
    page = CataloguePage((_result(None, "No stable ID"), _result(3, "Missing")), 1, 100, 2, None, None)
    report = get_missing_library(
        Settings(music_dir=root), _snapshot(root), page_provider=lambda *args, **kwargs: page,
    )
    assert [item.song_id for item in report.recordings] == [3]
    assert report.unidentifiable_catalogue_count == 1
    assert report.coverage is CatalogueCoverage.PARTIAL


def test_repeated_catalogue_ids_are_deduplicated_without_title_matching(tmp_path):
    root = tmp_path / "music"
    page = CataloguePage((_result(7, "First"), _result(7, "Duplicate API row")), 1, 100, 2, None, None)
    report = get_missing_library(
        Settings(music_dir=root), _snapshot(root, _track(root, "First.flac", None, media_format="FLAC")),
        page_provider=lambda *args, **kwargs: page,
    )
    assert [item.song_id for item in report.recordings] == [7]
    assert report.local_unknown_count == 1

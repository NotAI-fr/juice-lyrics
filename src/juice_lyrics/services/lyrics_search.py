"""Offline incremental index and predictable phrase search for local lyrics."""

from __future__ import annotations

import json
import os
import tempfile
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..config.settings import LYRICS_SEARCH_INDEX, Settings
from ..lyrics.engine import LocalLyricLine, read_local_lyrics
from ..lyrics.sidecar import sidecar_lrc_path
from ..state import file_fingerprint
from .library_status import LibrarySnapshot


INDEX_VERSION = 1
LyricsReader = Callable[[Path], tuple[LocalLyricLine, ...]]
Fingerprint = tuple[int, int, int, int, int]


def normalize_lyric_text(value: str) -> str:
    """Normalize case, spacing, and punctuation without fuzzy matching."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    pieces: list[str] = []
    for character in normalized:
        if character in {"'", "’", "‘", "ʼ"}:
            continue
        if unicodedata.category(character).startswith(("P", "S")):
            pieces.append(" ")
        else:
            pieces.append(character)
    return " ".join("".join(pieces).split())


def _prefer_sidecar_lines(lines: tuple[LocalLyricLine, ...]) -> tuple[LocalLyricLine, ...]:
    sidecar_text = {
        normalize_lyric_text(line.text) for line in lines if line.source == "lrc"
    }
    return tuple(
        line for line in lines
        if line.source == "lrc" or normalize_lyric_text(line.text) not in sidecar_text
    )


@dataclass(frozen=True, slots=True)
class LyricsIndexEntry:
    reference: str
    path: Path
    title: str
    audio_fingerprint: Fingerprint
    sidecar_fingerprint: Fingerprint | None
    lines: tuple[LocalLyricLine, ...]


@dataclass(frozen=True, slots=True)
class LyricsSearchResult:
    reference: str
    path: Path
    title: str
    matching_line: str
    timestamp_ms: int | None
    source: str
    context_before: str | None
    context_after: str | None
    hit_count: int


@dataclass(frozen=True, slots=True)
class LyricsSearchIndex:
    library_path: Path
    entries: tuple[LyricsIndexEntry, ...]
    indexed_count: int = 0
    reused_count: int = 0
    removed_count: int = 0
    rebuilt: bool = False
    persistence_warning: str | None = None

    def search(self, query: str) -> tuple[LyricsSearchResult, ...]:
        needle = normalize_lyric_text(query)
        if not needle:
            return ()
        results: list[LyricsSearchResult] = []
        for entry in self.entries:
            hit_indexes = [
                index for index, line in enumerate(entry.lines)
                if needle in normalize_lyric_text(line.text)
            ]
            if not hit_indexes:
                continue
            first = hit_indexes[0]
            line = entry.lines[first]
            before = (
                entry.lines[first - 1].text
                if first and entry.lines[first - 1].source == line.source
                else None
            )
            after = (
                entry.lines[first + 1].text
                if first + 1 < len(entry.lines)
                and entry.lines[first + 1].source == line.source
                else None
            )
            results.append(
                LyricsSearchResult(
                    reference=entry.reference,
                    path=entry.path,
                    title=entry.title,
                    matching_line=line.text,
                    timestamp_ms=line.timestamp_ms,
                    source=line.source,
                    context_before=before,
                    context_after=after,
                    hit_count=len(hit_indexes),
                )
            )
        return tuple(results)


def _fingerprint(path: Path) -> Fingerprint | None:
    try:
        return file_fingerprint(path)
    except OSError:
        return None


def _decode_fingerprint(value: object) -> Fingerprint | None:
    if value is None:
        return None
    if not isinstance(value, list) or len(value) != 5 or not all(isinstance(item, int) for item in value):
        raise ValueError("invalid fingerprint")
    return value[0], value[1], value[2], value[3], value[4]


def _load_cache(cache_file: Path, library_path: Path) -> tuple[dict[str, LyricsIndexEntry], bool]:
    if not cache_file.is_file():
        return {}, False
    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("version") != INDEX_VERSION:
            raise ValueError("unsupported index")
        if raw.get("library_path") != str(library_path):
            return {}, False
        raw_entries = raw.get("entries")
        if not isinstance(raw_entries, dict):
            raise ValueError("invalid entries")
        entries: dict[str, LyricsIndexEntry] = {}
        for reference, value in raw_entries.items():
            if not isinstance(reference, str) or not isinstance(value, dict):
                raise ValueError("invalid entry")
            title = value.get("title")
            raw_lines = value.get("lines")
            if not isinstance(title, str) or not isinstance(raw_lines, list):
                raise ValueError("invalid entry contents")
            lines: list[LocalLyricLine] = []
            for raw_line in raw_lines:
                if not isinstance(raw_line, dict) or not isinstance(raw_line.get("text"), str):
                    raise ValueError("invalid lyric line")
                timestamp = raw_line.get("timestamp_ms")
                source = raw_line.get("source")
                if timestamp is not None and not isinstance(timestamp, int):
                    raise ValueError("invalid timestamp")
                if source not in {"lrc", "embedded"}:
                    raise ValueError("invalid lyric source")
                lines.append(LocalLyricLine(raw_line["text"], timestamp, source))
            audio_fingerprint = _decode_fingerprint(value.get("audio_fingerprint"))
            if audio_fingerprint is None:
                raise ValueError("missing audio fingerprint")
            entries[reference] = LyricsIndexEntry(
                reference=reference,
                path=library_path / reference,
                title=title,
                audio_fingerprint=audio_fingerprint,
                sidecar_fingerprint=_decode_fingerprint(value.get("sidecar_fingerprint")),
                lines=tuple(lines),
            )
        return entries, False
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError, TypeError):
        return {}, True


def _write_cache(cache_file: Path, index: LyricsSearchIndex) -> str | None:
    payload = {
        "version": INDEX_VERSION,
        "library_path": str(index.library_path),
        "entries": {
            entry.reference: {
                "title": entry.title,
                "audio_fingerprint": list(entry.audio_fingerprint),
                "sidecar_fingerprint": list(entry.sidecar_fingerprint) if entry.sidecar_fingerprint else None,
                "lines": [
                    {"text": line.text, "timestamp_ms": line.timestamp_ms, "source": line.source}
                    for line in entry.lines
                ],
            }
            for entry in index.entries
        },
    }
    temporary: Path | None = None
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            dir=cache_file.parent, prefix=f".{cache_file.name}.", suffix=".tmp"
        )
        temporary = Path(name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(cache_file)
        return None
    except OSError as exc:
        return str(exc)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def build_lyrics_search_index(
    settings: Settings,
    snapshot: LibrarySnapshot,
    *,
    cache_file: Path = LYRICS_SEARCH_INDEX,
    lyrics_reader: LyricsReader = read_local_lyrics,
) -> LyricsSearchIndex:
    """Incrementally refresh the rebuildable cache using local fingerprints only."""

    library_path = Path(settings.music_dir)
    cached, rebuilt = _load_cache(Path(cache_file), library_path)
    entries: list[LyricsIndexEntry] = []
    indexed = reused = 0
    current_references: set[str] = set()
    for track in snapshot.tracks:
        reference = str(track.relative_path)
        current_references.add(reference)
        audio_fingerprint = _fingerprint(track.path)
        if audio_fingerprint is None:
            continue
        sidecar_fingerprint = _fingerprint(sidecar_lrc_path(track.path))
        previous = cached.get(reference)
        if (
            previous is not None
            and previous.audio_fingerprint == audio_fingerprint
            and previous.sidecar_fingerprint == sidecar_fingerprint
        ):
            entries.append(previous)
            reused += 1
            continue
        try:
            lines = _prefer_sidecar_lines(lyrics_reader(track.path))
        except Exception:
            # Do not persist a transient read failure as an apparently valid
            # empty track; retry it the next time the index is opened.
            continue
        entries.append(
            LyricsIndexEntry(
                reference=reference,
                path=track.path,
                title=track.title,
                audio_fingerprint=audio_fingerprint,
                sidecar_fingerprint=sidecar_fingerprint,
                lines=tuple(lines),
            )
        )
        indexed += 1
    removed = len(set(cached) - current_references)
    index = LyricsSearchIndex(
        library_path=library_path,
        entries=tuple(entries),
        indexed_count=indexed,
        reused_count=reused,
        removed_count=removed,
        rebuilt=rebuilt,
    )
    warning = _write_cache(Path(cache_file), index)
    if warning:
        index = LyricsSearchIndex(
            library_path=index.library_path,
            entries=index.entries,
            indexed_count=index.indexed_count,
            reused_count=index.reused_count,
            removed_count=index.removed_count,
            rebuilt=index.rebuilt,
            persistence_warning=warning,
        )
    return index

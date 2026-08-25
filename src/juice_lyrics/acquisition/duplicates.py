from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from .models import AcquisitionItem


@dataclass(frozen=True, slots=True)
class DuplicateMatch:
    """A local file that confidently represents the requested resource."""

    path: Path
    reason: str


def _normalize_title(text: str) -> str:
    text = str(text).lower().replace("’", "'")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\[[^]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _version(text: str) -> int | None:
    match = re.search(r"(?:\(|\[)?v(\d+)(?:\)|\])?", str(text), flags=re.I)
    return int(match.group(1)) if match else None


def _sha256(path: Path, chunk_size: int = 1024 * 128) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _candidate_version(path: Path) -> int | None:
    return _version(path.stem)


def _title_matches(item: AcquisitionItem, path: Path) -> bool:
    wanted = _normalize_title(item.title)
    candidate = _normalize_title(path.stem)
    if not wanted or wanted != candidate:
        return False

    wanted_version = _version(item.metadata.get("version", item.title))
    candidate_version = _candidate_version(path)
    return wanted_version == candidate_version


def find_duplicate(
    item: AcquisitionItem,
    *,
    search_dir: Path | None = None,
) -> DuplicateMatch | None:
    """Find a local file that is confidently the same acquisition target.

    The detector deliberately prefers strong evidence:

    1. matching SHA-256 when the API supplied one;
    2. the exact destination path when its expected size/checksum agrees;
    3. an exact normalized title with an exact version match.

    It never treats ``v1`` and ``v2`` as duplicates, and it ignores ``.part``
    files left by interrupted downloads.
    """

    destination = item.destination
    root = Path(search_dir) if search_dir is not None else destination.parent
    if not root.is_dir():
        return None

    expected_hash = item.expected_sha256.lower() if item.expected_sha256 else None
    expected_size = item.expected_size

    # A checksum is the strongest possible identity signal. It can find a
    # duplicate even when the local filename was changed.
    if expected_hash:
        for path in root.rglob("*"):
            if not path.is_file() or path == destination or path.name.endswith(".part"):
                continue
            try:
                if _sha256(path) == expected_hash:
                    return DuplicateMatch(path, "matching SHA-256 checksum")
            except OSError:
                continue

    # An existing destination is a duplicate only when it is consistent with
    # the supplied size/checksum metadata. Otherwise the downloader should be
    # allowed to report the destination as a conflict rather than silently
    # skipping a potentially bad file.
    if destination.is_file():
        if expected_size is not None and destination.stat().st_size != expected_size:
            return None
        if expected_hash and _sha256(destination) != expected_hash:
            return None
        return DuplicateMatch(destination, "matching destination path")

    # Finally, look for a file with the same canonical title/version. This
    # catches renamed or relocated files without confusing release variants.
    for path in root.rglob("*"):
        if not path.is_file() or path.name.endswith(".part"):
            continue
        if not _title_matches(item, path):
            continue
        if expected_size is not None and path.stat().st_size != expected_size:
            continue
        return DuplicateMatch(path, "matching normalized title and version")

    return None

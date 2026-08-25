from __future__ import annotations

from pathlib import Path


def load_manifest(path: Path) -> list[str]:
    """Load a simple explicit-selection manifest.

    Blank lines and lines beginning with '#' are ignored. Duplicate identifiers
    are removed while preserving order.
    """

    if not path.is_file():
        raise RuntimeError(f"Manifest does not exist: {path}")

    seen: set[str] = set()
    result: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

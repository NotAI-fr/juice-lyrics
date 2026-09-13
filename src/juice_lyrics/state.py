from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .backup.manager import ensure_data_dirs, now_iso
from .config.settings import STATE_FILE


def empty_state() -> dict[str, Any]:
    return {"files": {}, "updated": None}


def read_state_file(path: Path = STATE_FILE) -> dict[str, Any]:
    """Read state without creating directories or mutating the source file."""

    source = Path(path)
    if not source.exists():
        return empty_state()
    try:
        value = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return empty_state()
    if not isinstance(value, dict):
        return empty_state()
    if not isinstance(value.get("files", {}), dict):
        value["files"] = {}
    return value


def write_state_file(
    path: Path,
    state: Mapping[str, Any],
    *,
    update_timestamp: bool = True,
) -> None:
    """Atomically write state to an explicit path."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    value = dict(state)
    if update_timestamp:
        value["updated"] = now_iso()
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary.replace(destination)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def load_state() -> dict[str, Any]:
    """Backward-compatible loader used by established write workflows."""

    ensure_data_dirs()
    return read_state_file(STATE_FILE)


def save_state(state: dict[str, Any]) -> None:
    ensure_data_dirs()
    write_state_file(STATE_FILE, state)
    state["updated"] = read_state_file(STATE_FILE).get("updated")


def resolve_state_entry(
    files: Mapping[str, Any],
    relative_path: Path,
    library_relative_paths: Sequence[Path] = (),
) -> tuple[str | None, dict[str, Any] | None]:
    """Resolve an exact or unambiguous historical relative-path record."""

    reference = str(relative_path)
    exact = files.get(reference)
    if isinstance(exact, dict):
        return reference, exact
    if exact is not None:
        return reference, None

    basename = relative_path.name.casefold()
    if library_relative_paths:
        library_matches = [path for path in library_relative_paths if path.name.casefold() == basename]
        if len(library_matches) != 1:
            return None, None
    candidates = [
        (key, value)
        for key, value in files.items()
        if isinstance(key, str)
        and not Path(key).is_absolute()
        and Path(key).name.casefold() == basename
        and isinstance(value, dict)
    ]
    if len(candidates) == 1:
        return candidates[0]
    return None, None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

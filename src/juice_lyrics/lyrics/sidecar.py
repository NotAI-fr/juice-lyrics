from __future__ import annotations

from pathlib import Path


def sidecar_lrc_path(audio_path: Path) -> Path:
    """Return the same-basename LRC path beside a finalized audio file."""

    return Path(audio_path).with_suffix(".lrc")

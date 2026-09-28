from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass

from ..identity import STORAGE_NAMESPACE

# Compatibility alias for older imports. This identifies persisted storage,
# not the user-facing product or command name.
APP_NAME = STORAGE_NAMESPACE
DEFAULT_API_BASE = "https://juicewrldapi.com/juicewrld"
DEFAULT_MUSIC_DIR = Path.home() / "Music" / "Juice WRLD" / "Unreleased"
DEFAULT_TIMEOUT = 20
DEFAULT_DELAY = 0.15
DEFAULT_DURATION_TOLERANCE = 3.0
DEFAULT_CACHE_TTL_HOURS = 24
DEFAULT_LYRICS_DIR = Path.home() / "Music" / "lyrics"
# Historical compatibility values only; neither controls current LRC output.
LEGACY_IMPLICIT_LYRICS_DIR = Path.home() / "Music" / "Juice WRLD" / "lyrics"


def xdg_dir(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else fallback

CONFIG_HOME = xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config")
CACHE_HOME = xdg_dir("XDG_CACHE_HOME", Path.home() / ".cache")
DATA_HOME = xdg_dir("XDG_DATA_HOME", Path.home() / ".local" / "share")
CONFIG_FILE = CONFIG_HOME / STORAGE_NAMESPACE / "config.toml"
CACHE_DIR = CACHE_HOME / STORAGE_NAMESPACE
LYRICS_SEARCH_INDEX = CACHE_DIR / "lyrics-search-index-v1.json"
DATA_DIR = DATA_HOME / STORAGE_NAMESPACE
BACKUP_DIR = DATA_DIR / "backups"
STATE_FILE = DATA_DIR / "state.json"
ACQUISITION_JOBS_FILE = DATA_DIR / "acquisition_jobs.json"
DEFAULT_RMPC_CONFIG = CONFIG_HOME / "rmpc" / "config.ron"

@dataclass
class Settings:
    music_dir: Path = DEFAULT_MUSIC_DIR
    lyrics_dir: Path = DEFAULT_LYRICS_DIR
    api_base: str = DEFAULT_API_BASE
    timeout: int = DEFAULT_TIMEOUT
    delay: float = DEFAULT_DELAY
    duration_tolerance: float = DEFAULT_DURATION_TOLERANCE
    cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS
    # Deprecated compatibility field. New LRC output is always beside audio.
    lyrics_dir_explicit: bool = False

    @property
    def songs_endpoint(self) -> str:
        return self.api_base.rstrip("/") + "/songs/"


def resolve_lyrics_dir(
    settings: Settings,
    *,
    explicit_override: str | Path | None = None,
) -> Path:
    """Resolve the deprecated centralized directory for compatibility tools.

    Current acquisition, sync, retry, and status paths must not call this
    helper. New external lyrics are derived from the finalized audio path.
    """

    if explicit_override is not None:
        return Path(explicit_override).expanduser()
    resolved = Path(settings.lyrics_dir).expanduser()
    if (
        resolved == LEGACY_IMPLICIT_LYRICS_DIR
        and not settings.lyrics_dir_explicit
    ):
        return DEFAULT_LYRICS_DIR
    return resolved

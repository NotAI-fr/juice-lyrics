from __future__ import annotations

import os
from pathlib import Path
from dataclasses import dataclass

APP_NAME = "juice-lyrics"
DEFAULT_API_BASE = "https://juicewrldapi.com/juicewrld"
DEFAULT_MUSIC_DIR = Path.home() / "Music" / "Juice WRLD" / "Unreleased"
DEFAULT_TIMEOUT = 20
DEFAULT_DELAY = 0.15
DEFAULT_DURATION_TOLERANCE = 3.0
DEFAULT_CACHE_TTL_HOURS = 24


def xdg_dir(name: str, fallback: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else fallback

CONFIG_HOME = xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config")
CACHE_HOME = xdg_dir("XDG_CACHE_HOME", Path.home() / ".cache")
DATA_HOME = xdg_dir("XDG_DATA_HOME", Path.home() / ".local" / "share")
CONFIG_FILE = CONFIG_HOME / APP_NAME / "config.toml"
CACHE_DIR = CACHE_HOME / APP_NAME
DATA_DIR = DATA_HOME / APP_NAME
BACKUP_DIR = DATA_DIR / "backups"
STATE_FILE = DATA_DIR / "state.json"
ACQUISITION_JOBS_FILE = DATA_DIR / "acquisition_jobs.json"
DEFAULT_RMPC_LYRICS_DIR = DEFAULT_MUSIC_DIR.parent / "lyrics"
DEFAULT_RMPC_CONFIG = CONFIG_HOME / "rmpc" / "config.ron"

@dataclass
class Settings:
    music_dir: Path = DEFAULT_MUSIC_DIR
    api_base: str = DEFAULT_API_BASE
    timeout: int = DEFAULT_TIMEOUT
    delay: float = DEFAULT_DELAY
    duration_tolerance: float = DEFAULT_DURATION_TOLERANCE
    cache_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS

    @property
    def songs_endpoint(self) -> str:
        return self.api_base.rstrip("/") + "/songs/"

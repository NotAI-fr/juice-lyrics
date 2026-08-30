from __future__ import annotations

import shutil
import tomllib
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TypeAlias

from .. import __version__
from ..config.settings import (
    ACQUISITION_JOBS_FILE,
    BACKUP_DIR,
    CACHE_DIR,
    CONFIG_FILE,
    DEFAULT_API_BASE,
    DEFAULT_CACHE_TTL_HOURS,
    DEFAULT_DELAY,
    DEFAULT_DURATION_TOLERANCE,
    DEFAULT_MUSIC_DIR,
    DEFAULT_RMPC_CONFIG,
    DEFAULT_RMPC_LYRICS_DIR,
    DEFAULT_TIMEOUT,
    STATE_FILE,
    Settings,
)

SettingScalar: TypeAlias = str | int | float | Path
ExecutableFinder = Callable[[str], str | None]


class SettingsSource(str, Enum):
    DEFAULT = "default"
    CONFIG = "config"
    RUNTIME_OVERRIDE = "runtime_override"


class IntegrationStatus(str, Enum):
    DETECTED_CONFIGURED = "detected_configured"
    DETECTED_NOT_CONFIGURED = "detected_not_configured"
    NOT_DETECTED = "not_detected"
    UNABLE_TO_INSPECT = "unable_to_inspect"


@dataclass(frozen=True, slots=True)
class SettingValue:
    key: str
    label: str
    value: SettingScalar
    default_value: SettingScalar
    source: SettingsSource


@dataclass(frozen=True, slots=True)
class SettingsPath:
    key: str
    label: str
    path: Path
    exists: bool
    warning: str | None = None


@dataclass(frozen=True, slots=True)
class IntegrationSnapshot:
    status: IntegrationStatus
    executable: Path | None
    config_path: Path
    config_exists: bool
    config_has_lyrics_support: bool
    detail: str


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    config_path: Path
    config_exists: bool
    values: tuple[SettingValue, ...]
    paths: tuple[SettingsPath, ...]
    rmpc: IntegrationSnapshot
    application_version: str
    limitations: tuple[str, ...]
    warnings: tuple[str, ...] = ()


_SETTING_SPECS = (
    ("music_dir", "Music directory", DEFAULT_MUSIC_DIR),
    ("api_base", "API base URL", DEFAULT_API_BASE),
    ("timeout", "Request timeout", DEFAULT_TIMEOUT),
    ("delay", "Request delay", DEFAULT_DELAY),
    ("duration_tolerance", "Duration tolerance", DEFAULT_DURATION_TOLERANCE),
    ("cache_ttl_hours", "Cache TTL", DEFAULT_CACHE_TTL_HOURS),
)


def _normalized_config_value(key: str, value: object) -> SettingScalar:
    if key == "music_dir":
        return Path(str(value)).expanduser()
    if key == "api_base":
        return str(value).rstrip("/")
    if key == "timeout":
        return int(value)
    return float(value)


def _same_value(left: SettingScalar, right: SettingScalar) -> bool:
    return left == right


def _source_for(
    key: str,
    effective: SettingScalar,
    default: SettingScalar,
    config: dict[str, object],
) -> SettingsSource:
    if key in config:
        configured = _normalized_config_value(key, config[key])
        return SettingsSource.CONFIG if _same_value(effective, configured) else SettingsSource.RUNTIME_OVERRIDE
    return SettingsSource.DEFAULT if _same_value(effective, default) else SettingsSource.RUNTIME_OVERRIDE


def _inspect_path(key: str, label: str, path: Path) -> SettingsPath:
    try:
        exists = path.exists()
        warning = None
    except OSError as exc:
        exists = False
        warning = str(exc) or type(exc).__name__
    return SettingsPath(key, label, path, exists, warning)


def _rmpc_configured(text: str) -> bool:
    return (
        re.search(r"(?im)^\s*lyrics_dir\s*:\s*some\s*\(", text) is not None
        and re.search(r"(?im)^\s*enable_lyrics_index\s*:\s*true\s*,?", text) is not None
        and re.search(r"(?im)^\s*enable_lyrics_hot_reload\s*:\s*true\s*,?", text) is not None
    )


def _inspect_rmpc(
    config_path: Path,
    executable_finder: ExecutableFinder,
) -> IntegrationSnapshot:
    try:
        executable_raw = executable_finder("rmpc")
        executable = Path(executable_raw) if executable_raw else None
        config_exists = config_path.exists()
        configured = False
        if config_exists:
            configured = _rmpc_configured(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return IntegrationSnapshot(
            IntegrationStatus.UNABLE_TO_INSPECT,
            None,
            config_path,
            False,
            False,
            f"Unable to inspect rmpc: {exc}",
        )
    if executable is None:
        status = IntegrationStatus.NOT_DETECTED
        detail = "rmpc was not found in PATH."
    elif configured:
        status = IntegrationStatus.DETECTED_CONFIGURED
        detail = "rmpc is detected and its lyrics integration is configured."
    else:
        status = IntegrationStatus.DETECTED_NOT_CONFIGURED
        detail = "rmpc is detected, but lyrics integration is not configured."
    return IntegrationSnapshot(status, executable, config_path, config_exists, configured, detail)


def get_settings_snapshot(
    settings: Settings,
    *,
    config_path: Path = CONFIG_FILE,
    cache_dir: Path = CACHE_DIR,
    state_file: Path = STATE_FILE,
    backup_dir: Path = BACKUP_DIR,
    jobs_file: Path = ACQUISITION_JOBS_FILE,
    lyrics_dir: Path = DEFAULT_RMPC_LYRICS_DIR,
    rmpc_config_path: Path = DEFAULT_RMPC_CONFIG,
    executable_finder: ExecutableFinder = shutil.which,
) -> SettingsSnapshot:
    """Inspect effective settings and environment without creating or changing files."""

    config_path = Path(config_path)
    config: dict[str, object] = {}
    try:
        config_exists = config_path.exists()
        if config_exists:
            parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
            if not isinstance(parsed, dict):
                raise ValueError("configuration root must be a table")
            config = parsed
            for key, _, _ in _SETTING_SPECS:
                if key in config:
                    _normalized_config_value(key, config[key])
    except Exception as exc:
        raise RuntimeError(f"Could not read config {config_path}: {exc}") from exc

    values = tuple(
        SettingValue(
            key,
            label,
            getattr(settings, key),
            default,
            _source_for(key, getattr(settings, key), default, config),
        )
        for key, label, default in _SETTING_SPECS
    )
    paths = tuple(
        _inspect_path(key, label, Path(path))
        for key, label, path in (
            ("music", "Music library", settings.music_dir),
            ("lyrics", "rmpc lyrics", lyrics_dir),
            ("cache", "API cache", cache_dir),
            ("state", "Library state", state_file),
            ("backups", "Backups", backup_dir),
            ("jobs", "Acquisition jobs", jobs_file),
            ("config", "Application config", config_path),
            ("rmpc_config", "rmpc config", rmpc_config_path),
        )
    )
    warnings = tuple(
        f"{item.label}: {item.warning}" for item in paths if item.warning is not None
    )
    return SettingsSnapshot(
        config_path=config_path,
        config_exists=config_exists,
        values=values,
        paths=paths,
        rmpc=_inspect_rmpc(Path(rmpc_config_path), executable_finder),
        application_version=__version__,
        limitations=(
            "Local library scanning currently supports MP3 files only.",
            "Native FLAC support is planned but not implemented.",
            "Browse and Downloads remain read-only in the TUI.",
            "Library sync execution remains CLI-only.",
            "Configuration changes remain CLI-only.",
        ),
        warnings=warnings,
    )

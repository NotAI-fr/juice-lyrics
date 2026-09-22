from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from enum import Enum
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
from typing import Any

from .. import __version__
from ..api.client import api_get
from ..backup.manager import list_backups
from ..config.settings import Settings
from .settings_snapshot import _rmpc_configured


class DoctorStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    key: str
    label: str
    status: DoctorStatus
    detail: str
    suggestion: str | None = None


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def failed(self) -> int:
        return sum(item.status is DoctorStatus.FAIL for item in self.checks)

    @property
    def warned(self) -> int:
        return sum(item.status is DoctorStatus.WARN for item in self.checks)

    @property
    def passed(self) -> int:
        return sum(item.status is DoctorStatus.PASS for item in self.checks)


ApiProbe = Callable[[str, int], Any]
ExecutableFinder = Callable[[str], str | None]
DiskUsageProbe = Callable[[str | os.PathLike[str]], Any]
RmpcProbe = Callable[[Path], bool]


def _nearest_existing(path: Path) -> Path | None:
    candidate = path.expanduser()
    while not candidate.exists():
        if candidate.parent == candidate:
            return None
        candidate = candidate.parent
    return candidate


def _check_runtime(
    command_finder: ExecutableFinder,
    *,
    invoked_command: str | None = None,
) -> DoctorCheck:
    try:
        invoked = Path(invoked_command or sys.argv[0]).expanduser()
        if invoked.name in {"999", "juice-lyrics"} and invoked.parent != Path("."):
            executable = str(invoked.resolve(strict=True))
        else:
            executable = command_finder(invoked.name if invoked.name in {"999", "juice-lyrics"} else "999")
    except Exception as exc:
        return DoctorCheck("runtime", "Runtime", DoctorStatus.WARN, f"Executable location could not be inspected: {exc}")
    detail = f"999 {__version__}; Python {sys.version.split()[0]}; executable {executable or 'not found in PATH'}"
    if executable:
        return DoctorCheck("runtime", "Runtime", DoctorStatus.PASS, detail)
    return DoctorCheck(
        "runtime", "Runtime", DoctorStatus.WARN, detail,
        "The current Python package is importable, but reinstall the editable/pipx command if `999` should be on PATH.",
    )


def _check_dependencies() -> DoctorCheck:
    if importlib.util.find_spec("mutagen") is None:
        return DoctorCheck(
            "dependencies", "Media dependency", DoctorStatus.FAIL,
            "Mutagen is not importable.", "Reinstall 999 and its declared dependencies.",
        )
    return DoctorCheck("dependencies", "Media dependency", DoctorStatus.PASS, "Mutagen is available.")


def _check_config(config_path: Path) -> DoctorCheck:
    if not config_path.exists():
        return DoctorCheck(
            "config", "Configuration", DoctorStatus.PASS,
            f"No config file at {config_path}; built-in defaults or command-line overrides are in use.",
        )
    try:
        value = tomllib.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("configuration root is not a table")
        for key, converter in (
            ("timeout", int), ("delay", float),
            ("duration_tolerance", float), ("cache_ttl_hours", float),
        ):
            if key in value:
                converter(value[key])
        if "music_dir" in value and not str(value["music_dir"]).strip():
            raise ValueError("music_dir is empty")
        if "api_base" in value and not str(value["api_base"]).strip():
            raise ValueError("api_base is empty")
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, TypeError, ValueError) as exc:
        return DoctorCheck(
            "config", "Configuration", DoctorStatus.FAIL,
            f"Configuration is unreadable or invalid: {exc}",
            "Correct the config file, then run `999 doctor` again.",
        )
    return DoctorCheck("config", "Configuration", DoctorStatus.PASS, f"Configuration is valid at {config_path}.")


def _check_state(state_file: Path) -> DoctorCheck:
    if not state_file.exists():
        return DoctorCheck("state", "Library state", DoctorStatus.PASS, f"No state file at {state_file}; this is valid before the first Library Sync.")
    try:
        value = json.loads(state_file.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("root must be an object")
        files = value.get("files", {})
        if not isinstance(files, dict):
            raise ValueError("files must be an object")
        malformed = sum(not isinstance(key, str) or not isinstance(entry, dict) for key, entry in files.items())
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        return DoctorCheck(
            "state", "Library state", DoctorStatus.FAIL,
            f"State is unreadable or malformed: {exc}",
            "Preserve the file for recovery; do not delete it blindly. Use a backup or advanced state maintenance.",
        )
    if malformed:
        return DoctorCheck(
            "state", "Library state", DoctorStatus.WARN,
            f"State loaded, but {malformed} record(s) have an unsupported shape.",
            "Run the state maintenance preview before removing anything.",
        )
    return DoctorCheck("state", "Library state", DoctorStatus.PASS, f"State is valid at {state_file} ({len(files)} record(s)).")


def _check_cache(cache_dir: Path, *, sample_limit: int = 100) -> DoctorCheck:
    if not cache_dir.exists():
        return DoctorCheck("cache", "API cache", DoctorStatus.PASS, f"Cache has not been created at {cache_dir} yet.")
    if not cache_dir.is_dir():
        return DoctorCheck("cache", "API cache", DoctorStatus.FAIL, "Cache path is not a directory.", "Move the conflicting path and retry.")
    try:
        files = tuple(path for path in cache_dir.iterdir() if path.is_file() and path.suffix.casefold() == ".json")
        malformed = 0
        for path in files[:sample_limit]:
            try:
                json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                malformed += 1
    except OSError as exc:
        return DoctorCheck("cache", "API cache", DoctorStatus.FAIL, f"Cache cannot be inspected: {exc}", "Check cache directory permissions.")
    sampled = min(len(files), sample_limit)
    if malformed:
        return DoctorCheck(
            "cache", "API cache", DoctorStatus.WARN,
            f"{malformed} malformed JSON file(s) found among {sampled} inspected.",
            "Run `999 cache clear`; catalogue data will be fetched again when needed.",
        )
    suffix = f"; first {sample_limit} inspected" if len(files) > sample_limit else ""
    return DoctorCheck("cache", "API cache", DoctorStatus.PASS, f"Cache is readable ({len(files)} JSON file(s){suffix}).")


def _check_library(music_dir: Path) -> DoctorCheck:
    root = music_dir.expanduser()
    if not root.exists():
        return DoctorCheck(
            "library", "Music library", DoctorStatus.FAIL,
            f"Configured music directory does not exist: {root}",
            "Create it or update music_dir in the 999 configuration.",
        )
    if not root.is_dir():
        return DoctorCheck("library", "Music library", DoctorStatus.FAIL, "Configured music path is not a directory.", "Update music_dir to a directory.")
    if not os.access(root, os.R_OK | os.X_OK):
        return DoctorCheck("library", "Music library", DoctorStatus.FAIL, "Music directory is not readable.", "Check directory ownership and permissions.")
    counts = {"MP3": 0, "FLAC": 0, "M4A": 0}
    errors: list[str] = []

    def failed(exc: OSError) -> None:
        errors.append(str(exc) or type(exc).__name__)

    try:
        for _, _, names in os.walk(root, onerror=failed):
            for name in names:
                suffix = Path(name).suffix.casefold()
                if suffix in {".mp3", ".flac", ".m4a"}:
                    counts[suffix[1:].upper()] += 1
    except OSError as exc:
        errors.append(str(exc) or type(exc).__name__)
    total = sum(counts.values())
    detail = f"Readable at {root}; {total} supported file(s) (MP3 {counts['MP3']}, FLAC {counts['FLAC']}, M4A {counts['M4A']})."
    if errors:
        return DoctorCheck("library", "Music library", DoctorStatus.WARN, detail + " Some directories could not be read.", "Check permissions on nested library directories.")
    if total == 0:
        return DoctorCheck("library", "Music library", DoctorStatus.WARN, detail, "Add supported audio or verify that music_dir points to the intended library.")
    return DoctorCheck("library", "Music library", DoctorStatus.PASS, detail)


def _check_catalogue(settings: Settings, probe: ApiProbe) -> DoctorCheck:
    url = settings.songs_endpoint + "?page=1&page_size=1"
    try:
        value = probe(url, min(settings.timeout, 10))
    except Exception as exc:
        return DoctorCheck(
            "catalogue", "Catalogue", DoctorStatus.WARN,
            f"Catalogue is offline or unreachable: {exc}",
            "Check the network/API URL. Local Library features remain available offline.",
        )
    if not isinstance(value, Mapping):
        return DoctorCheck("catalogue", "Catalogue", DoctorStatus.FAIL, "Catalogue returned an invalid non-object response.", "Check api_base or try again later.")
    results = value.get("results")
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes, bytearray)):
        return DoctorCheck("catalogue", "Catalogue", DoctorStatus.FAIL, "Catalogue response is missing a valid results list.", "Check api_base or report an API compatibility problem.")
    if any(not isinstance(item, Mapping) for item in results):
        return DoctorCheck("catalogue", "Catalogue", DoctorStatus.FAIL, "Catalogue results contain invalid records.", "Report an API compatibility problem.")
    return DoctorCheck("catalogue", "Catalogue", DoctorStatus.PASS, "Catalogue responded with a valid small page.")


def _check_backups(backup_dir: Path, disk_usage: DiskUsageProbe) -> tuple[DoctorCheck, DoctorCheck]:
    directory = backup_dir.expanduser()
    if directory.exists() and not directory.is_dir():
        backups = DoctorCheck("backups", "Backups", DoctorStatus.FAIL, "Backup path is not a directory.", "Move the conflicting path before metadata or lyric maintenance.")
    elif directory.exists() and not os.access(directory, os.R_OK | os.X_OK):
        backups = DoctorCheck("backups", "Backups", DoctorStatus.FAIL, "Backup directory is not readable.", "Check backup directory ownership and permissions.")
    else:
        records = list_backups(directory)
        backups = DoctorCheck("backups", "Backups", DoctorStatus.PASS, f"Backup location {directory} is available; {len(records)} valid backup(s).")
    nearest = _nearest_existing(directory)
    if nearest is None:
        storage = DoctorCheck("storage", "Available storage", DoctorStatus.WARN, "Available storage could not be determined.")
    else:
        try:
            usage = disk_usage(nearest)
            free = int(usage.free)
            gib = free / (1024 ** 3)
            status = DoctorStatus.WARN if free < 512 * 1024 * 1024 else DoctorStatus.PASS
            suggestion = "Free space is low; metadata backups require room for complete audio copies." if status is DoctorStatus.WARN else None
            storage = DoctorCheck("storage", "Available storage", status, f"{gib:.1f} GiB free on the data filesystem.", suggestion)
        except (OSError, ValueError, AttributeError) as exc:
            storage = DoctorCheck("storage", "Available storage", DoctorStatus.WARN, f"Available storage could not be determined: {exc}")
    return backups, storage


def _probe_rmpc(executable: Path) -> bool:
    try:
        return subprocess.run(
            [str(executable), "remote", "query", "active-tab"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _check_rmpc(
    settings: Settings,
    *,
    config_path: Path,
    executable_finder: ExecutableFinder,
    connectivity_probe: RmpcProbe,
) -> DoctorCheck:
    try:
        executable_raw = executable_finder("rmpc")
        executable = Path(executable_raw) if executable_raw else None
    except Exception as exc:
        return DoctorCheck("rmpc", "rmpc / MPD", DoctorStatus.WARN, f"Optional rmpc executable could not be inspected: {exc}")
    if executable is None:
        return DoctorCheck("rmpc", "rmpc / MPD", DoctorStatus.WARN, "Optional rmpc executable is not installed or not in PATH.", "Install rmpc only if player integration is wanted.")
    try:
        configured = config_path.exists() and _rmpc_configured(
            config_path.read_text(encoding="utf-8"), Path(settings.music_dir)
        )
    except (OSError, UnicodeError) as exc:
        return DoctorCheck("rmpc", "rmpc / MPD", DoctorStatus.WARN, f"Optional rmpc config could not be read: {exc}")
    if not configured:
        return DoctorCheck(
            "rmpc", "rmpc / MPD", DoctorStatus.WARN,
            "rmpc is detected, but sidecar indexing is not configured for this music directory.",
            "Use `999 rmpc setup` only if this integration is wanted.",
        )
    if not connectivity_probe(executable):
        return DoctorCheck(
            "rmpc", "rmpc / MPD", DoctorStatus.WARN,
            "rmpc is configured, but rmpc/MPD is not currently responding.",
            "Start MPD/rmpc and retry if player integration is wanted.",
        )
    return DoctorCheck("rmpc", "rmpc / MPD", DoctorStatus.PASS, "Optional rmpc sidecar configuration and MPD connection are available.")


def run_doctor(
    settings: Settings,
    *,
    config_path: Path,
    state_file: Path,
    cache_dir: Path,
    backup_dir: Path,
    rmpc_config_path: Path,
    api_probe: ApiProbe = api_get,
    command_finder: ExecutableFinder = shutil.which,
    disk_usage: DiskUsageProbe = shutil.disk_usage,
    rmpc_probe: RmpcProbe = _probe_rmpc,
    invoked_command: str | None = None,
) -> DoctorReport:
    """Run bounded, read-only application diagnostics."""

    def safe(key: str, label: str, action: Callable[[], DoctorCheck]) -> DoctorCheck:
        try:
            return action()
        except Exception as exc:
            return DoctorCheck(
                key, label, DoctorStatus.FAIL,
                f"Could not inspect this area safely: {exc}",
                "Check path permissions and retry.",
            )

    checks = [
        safe(
            "runtime",
            "Runtime",
            lambda: _check_runtime(command_finder, invoked_command=invoked_command),
        ),
        safe("dependencies", "Media dependency", _check_dependencies),
        safe("config", "Configuration", lambda: _check_config(Path(config_path))),
        safe("state", "Library state", lambda: _check_state(Path(state_file))),
        safe("cache", "API cache", lambda: _check_cache(Path(cache_dir))),
        safe("library", "Music library", lambda: _check_library(Path(settings.music_dir))),
        safe("catalogue", "Catalogue", lambda: _check_catalogue(settings, api_probe)),
    ]
    try:
        checks.extend(_check_backups(Path(backup_dir), disk_usage))
    except Exception as exc:
        checks.extend((
            DoctorCheck("backups", "Backups", DoctorStatus.FAIL, f"Could not inspect backups safely: {exc}", "Check backup path permissions."),
            DoctorCheck("storage", "Available storage", DoctorStatus.WARN, "Available storage could not be determined."),
        ))
    checks.append(safe("rmpc", "rmpc / MPD", lambda: _check_rmpc(
        settings,
        config_path=Path(rmpc_config_path),
        executable_finder=command_finder,
        connectivity_probe=rmpc_probe,
    )))
    return DoctorReport(tuple(checks))


_SECRET_RE = re.compile(r"(?i)(token|secret|password|credential|api[_-]?key)(\s*[:=]\s*)([^\s,;]+)")


def sanitize_support_text(value: str, *, home: Path | None = None) -> str:
    """Remove common path and credential material from a support-report value."""

    text = str(value)
    home_path = str((home or Path.home()).expanduser())
    if home_path and home_path != "/":
        text = re.sub(re.escape(home_path) + r"[^\s,;]*", "<HOME_PATH>", text)
    text = re.sub(r"(?<![:\w])/(?:[^\s,;]+)", "<PATH>", text)
    text = _SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}<REDACTED>", text)
    text = re.sub(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@", r"\1<REDACTED>@", text)
    return text


def support_report_data(report: DoctorReport, *, home: Path | None = None) -> dict[str, Any]:
    return {
        "product": "999",
        "version": __version__,
        "python": sys.version.split()[0],
        "summary": {"pass": report.passed, "warn": report.warned, "fail": report.failed},
        "checks": [
            {
                **asdict(check),
                "status": check.status.value,
                "detail": sanitize_support_text(check.detail, home=home),
                "suggestion": sanitize_support_text(check.suggestion, home=home) if check.suggestion else None,
            }
            for check in report.checks
        ],
        "privacy": "Sanitized: no song list or state contents are included.",
    }


def render_support_report(report: DoctorReport, *, home: Path | None = None) -> str:
    return json.dumps(support_report_data(report, home=home), indent=2, ensure_ascii=False)

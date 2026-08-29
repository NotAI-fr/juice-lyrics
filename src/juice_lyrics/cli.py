#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from mutagen.id3 import ID3, ID3NoHeaderError, SYLT, USLT, Encoding
from mutagen.mp3 import MP3

from . import __version__

APP_NAME = "juice-lyrics"
DEFAULT_API_BASE = "https://juicewrldapi.com/juicewrld"
DEFAULT_MUSIC_DIR = Path.home() / "Music" / "Juice WRLD" / "Unreleased"
DEFAULT_DESCRIPTION = "Juice WRLD API"
DEFAULT_LANGUAGE = "eng"
DEFAULT_TIMEOUT = 20
DEFAULT_DELAY = 0.15
DEFAULT_DURATION_TOLERANCE = 3.0
DEFAULT_CACHE_TTL_HOURS = 24

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

CANONICAL_SEARCH = {
    "chase the dragon": "Life's a Dungeon",
    "off the rip": "Off the Rip",
    "on my own": "On My Own",
    "party in my mind": "Until I Die",
    "stick talk": "Stick Talk",
    "whatever": "Call Me Whenever",
}


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
DEFAULT_RMPC_LYRICS_DIR = DEFAULT_MUSIC_DIR.parent / "lyrics"
DEFAULT_RMPC_CONFIG = CONFIG_HOME / "rmpc" / "config.ron"


class Settings:
    def __init__(self) -> None:
        self.music_dir = DEFAULT_MUSIC_DIR
        self.api_base = DEFAULT_API_BASE
        self.timeout = DEFAULT_TIMEOUT
        self.delay = DEFAULT_DELAY
        self.duration_tolerance = DEFAULT_DURATION_TOLERANCE
        self.cache_ttl_hours = DEFAULT_CACHE_TTL_HOURS

    @property
    def songs_endpoint(self) -> str:
        return self.api_base.rstrip("/") + "/songs/"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def colorize(text: str, color: str, enabled: bool) -> str:
    return f"{color}{text}{RESET}" if enabled else text


def print_header(title: str, use_color: bool) -> None:
    print()
    print(colorize(title, BOLD, use_color))
    print(colorize("─" * len(title), DIM, use_color))


def load_settings(path_override: str | None = None, api_override: str | None = None) -> Settings:
    settings = Settings()
    if CONFIG_FILE.exists():
        try:
            import tomllib
            data = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if data.get("music_dir"):
                settings.music_dir = Path(str(data["music_dir"])).expanduser()
            settings.api_base = str(data.get("api_base", settings.api_base)).rstrip("/")
            settings.timeout = int(data.get("timeout", settings.timeout))
            settings.delay = float(data.get("delay", settings.delay))
            settings.duration_tolerance = float(data.get("duration_tolerance", settings.duration_tolerance))
            settings.cache_ttl_hours = float(data.get("cache_ttl_hours", settings.cache_ttl_hours))
        except Exception as exc:
            raise RuntimeError(f"Could not read config {CONFIG_FILE}: {exc}") from exc
    if path_override:
        settings.music_dir = Path(path_override).expanduser()
    if api_override:
        settings.api_base = api_override.rstrip("/")
    return settings


def write_default_config(force: bool = False) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists() and not force:
        raise RuntimeError(f"Config already exists: {CONFIG_FILE} (use --force to replace it)")
    content = f'''# {APP_NAME} configuration\n\nmusic_dir = "{DEFAULT_MUSIC_DIR}"\napi_base = "{DEFAULT_API_BASE}"\ntimeout = {DEFAULT_TIMEOUT}\ndelay = {DEFAULT_DELAY}\nduration_tolerance = {DEFAULT_DURATION_TOLERANCE}\ncache_ttl_hours = {DEFAULT_CACHE_TTL_HOURS}\n'''
    CONFIG_FILE.write_text(content, encoding="utf-8")


def ensure_data_dirs() -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> dict[str, Any]:
    ensure_data_dirs()
    if not STATE_FILE.exists():
        return {"files": {}, "updated": None}
    try:
        value = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {"files": {}, "updated": None}
    except Exception:
        return {"files": {}, "updated": None}


def save_state(state: dict[str, Any]) -> None:
    ensure_data_dirs()
    state["updated"] = now_iso()
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(text: str) -> str:
    text = str(text).lower().replace("’", "'")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\[[^]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_version(text: str) -> int | None:
    match = re.search(r"(?:\(|\[)?v(\d+)(?:\)|\])?", text, flags=re.I)
    return int(match.group(1)) if match else None


def strip_version(text: str) -> str:
    return re.sub(r"\s*(?:\(|\[)?v\d+(?:\.\d+)?(?:\)|\])?\s*$", "", text, flags=re.I).strip()


def parse_length(value: str) -> float | None:
    if not value:
        return None
    parts = value.strip().split(":")
    try:
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + float(seconds)
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    except ValueError:
        return None
    return None


def local_duration(path: Path) -> float | None:
    try:
        return float(MP3(path).info.length)
    except Exception:
        return None


def api_get(url: str, timeout: int) -> Any:
    request = Request(url, headers={"User-Agent": f"{APP_NAME}/{__version__}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"API returned HTTP {exc.code}: {exc.reason}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach the Juice WRLD API: {exc.reason}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("The API returned invalid JSON") from exc


def cache_key(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value.lower()).strip("_") or "empty"


def search_api(settings: Settings, title: str, refresh: bool = False) -> list[dict[str, Any]]:
    ensure_data_dirs()
    file = CACHE_DIR / f"{cache_key(title)}.json"
    if not refresh and file.exists() and time.time() - file.stat().st_mtime <= settings.cache_ttl_hours * 3600:
        try:
            value = json.loads(file.read_text(encoding="utf-8"))
            if isinstance(value, list):
                return value
        except Exception:
            pass
    data = api_get(f"{settings.songs_endpoint}?search={quote(title)}&page_size=50", settings.timeout)
    results = data.get("results", []) if isinstance(data, dict) else []
    file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    time.sleep(settings.delay)
    return results


def search_api_advanced(settings: Settings, query: str, category: str | None = None, era: str | None = None, refresh: bool = False) -> dict[str, Any]:
    params = [f"search={quote(query)}", "page_size=50"]
    if category:
        params.append(f"category={quote(category)}")
    if era:
        params.append(f"era={quote(era)}")
    data = api_get(f"{settings.songs_endpoint}?{'&'.join(params)}", settings.timeout)
    return data if isinstance(data, dict) else {"results": []}


def get_song(settings: Settings, song_id: int) -> dict[str, Any]:
    return api_get(f"{settings.songs_endpoint}{song_id}/", settings.timeout)


def search_title_for(path: Path) -> str:
    stripped = strip_version(path.stem)
    return CANONICAL_SEARCH.get(normalize(stripped), stripped)


def score_candidate(settings: Settings, path: Path, candidate: dict[str, Any], search_title: str) -> tuple[float, list[str]]:
    local_raw = path.stem
    candidate_raw = str(candidate.get("name", ""))
    local = normalize(strip_version(local_raw))
    candidate_name = normalize(strip_version(candidate_raw))
    original_key = normalize(strip_version(str(candidate.get("original_key", ""))))
    local_version = parse_version(local_raw)
    candidate_version = parse_version(candidate_raw)
    reasons: list[str] = []
    score = 0.0
    if local_version is not None:
        if candidate_version == local_version:
            score += 120
            reasons.append(f"exact version v{local_version}")
        elif candidate_version is not None:
            score -= 120
            reasons.append(f"wrong version (API v{candidate_version}, local v{local_version})")
    api_path = str(candidate.get("path") or "")
    if api_path:
        if normalize(Path(api_path).name) == normalize(path.name):
            score += 150
            reasons.append("exact API filename")
        if normalize(Path(api_path).stem) == normalize(path.stem):
            score += 120
            reasons.append("exact API path filename")
    if local and local == candidate_name:
        score += 100
        reasons.append("exact title")
    if local and local == original_key:
        score += 90
        reasons.append("exact original key")
    if normalize(search_title) == candidate_name:
        score += 45
        reasons.append("search title match")
    lt = set(local.split())
    ct = set(candidate_name.split())
    if lt and ct:
        score += (len(lt & ct) / len(lt | ct)) * 30
    local_len = local_duration(path)
    api_len = parse_length(str(candidate.get("length") or ""))
    if local_len is not None and api_len is not None:
        diff = abs(local_len - api_len)
        if diff <= settings.duration_tolerance:
            score += max(0.0, 60.0 - diff * 10.0)
            reasons.append(f"duration match ({diff:.2f}s)")
        else:
            score -= min(diff * 5.0, 60.0)
            reasons.append(f"duration mismatch ({diff:.2f}s)")
    if candidate.get("category") == "unreleased":
        score += 10
        reasons.append("unreleased")
    if candidate.get("category") == "released":
        score -= 150
        reasons.append("released")
    return score, reasons


def choose_candidate(settings: Settings, path: Path, results: list[dict[str, Any]], search_title: str) -> tuple[dict[str, Any] | None, float, list[str], list[tuple[float, dict[str, Any], list[str]]]]:
    scored = []
    for candidate in results:
        score, reasons = score_candidate(settings, path, candidate, search_title)
        scored.append((score, candidate, reasons))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return None, 0.0, [], []
    best_score, best, reasons = scored[0]
    if best_score < 70:
        return None, best_score, reasons, scored
    if len(scored) >= 2 and best_score - scored[1][0] < 12:
        return None, best_score, reasons, scored
    return best, best_score, reasons, scored


LRC_RE = re.compile(r"\[(?P<m>\d+):(?P<s>\d{2})(?:[.:](?P<f>\d{1,3}))?\]\s*(?P<t>.*)")


def parse_synced_lyrics(raw: str) -> list[tuple[str, int]]:
    entries: list[tuple[str, int]] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        match = LRC_RE.match(line)
        if not match:
            continue
        fraction = (match.group("f") or "0").ljust(3, "0")[:3]
        timestamp = int(match.group("m")) * 60000 + int(match.group("s")) * 1000 + int(fraction)
        text = match.group("t").strip()
        if text:
            entries.append((text, timestamp))
    entries.sort(key=lambda x: x[1])
    cleaned: list[tuple[str, int]] = []
    previous = None
    for item in entries:
        if item != previous:
            cleaned.append(item)
        previous = item
    return cleaned


def load_id3(path: Path) -> ID3:
    try:
        return ID3(path)
    except ID3NoHeaderError:
        return ID3()


def remove_managed_frames(tag: ID3) -> None:
    for frame_type in ("SYLT", "USLT"):
        for frame in list(tag.getall(frame_type)):
            if getattr(frame, "desc", "") == DEFAULT_DESCRIPTION:
                try:
                    del tag[frame.HashKey]
                except KeyError:
                    pass


def save_id3_preserving_version(tag: ID3, path: Path) -> None:
    version = 3 if getattr(tag, "version", None) and tag.version[0] == 3 else 4
    tag.save(path, v2_version=version)


def embed_lyrics(path: Path, synced: list[tuple[str, int]], plain: str) -> str:
    tag = load_id3(path)
    remove_managed_frames(tag)
    if synced:
        tag.add(SYLT(encoding=Encoding.UTF8, lang=DEFAULT_LANGUAGE, format=2, type=1, desc=DEFAULT_DESCRIPTION, text=synced))
        save_id3_preserving_version(tag, path)
        return "SYLT"
    if plain.strip():
        tag.add(USLT(encoding=Encoding.UTF8, lang=DEFAULT_LANGUAGE, desc=DEFAULT_DESCRIPTION, text=plain.strip()))
        save_id3_preserving_version(tag, path)
        return "USLT"
    raise ValueError("No lyrics available")


def verify_file(path: Path) -> tuple[bool, str]:
    try:
        tag = ID3(path)
        sylt = [f for f in tag.getall("SYLT") if getattr(f, "desc", "") == DEFAULT_DESCRIPTION]
        if sylt:
            total = sum(len(f.text) for f in sylt)
            if not total:
                return False, "empty SYLT frame"
            for frame in sylt:
                times = [item[1] for item in frame.text]
                if times != sorted(times):
                    return False, "SYLT timestamps are not chronological"
            return True, f"SYLT ({total} synced lines)"
        uslt = [f for f in tag.getall("USLT") if getattr(f, "desc", "") == DEFAULT_DESCRIPTION]
        if uslt:
            total = sum(len(getattr(f, "text", "") or "") for f in uslt)
            if not total:
                return False, "empty USLT frame"
            return True, "USLT (ordinary lyrics)"
        return False, "no managed lyrics frame"
    except Exception as exc:
        return False, str(exc)


def analyse(settings: Settings, path: Path, refresh: bool = False) -> dict[str, Any]:
    search_title = search_title_for(path)
    results = search_api(settings, search_title, refresh=refresh)
    candidate, score, reasons, ranked = choose_candidate(settings, path, results, search_title)
    synced: list[tuple[str, int]] = []
    plain = ""
    if candidate:
        synced = parse_synced_lyrics(str(candidate.get("synced_lyrics") or ""))
        plain = str(candidate.get("lyrics") or "")
    return {"path": path, "search_title": search_title, "candidate": candidate, "score": score, "reasons": reasons, "ranked": ranked, "synced": synced, "plain": plain}


def find_mp3s(settings: Settings) -> list[Path]:
    if not settings.music_dir.is_dir():
        raise RuntimeError(f"Music directory does not exist: {settings.music_dir}")
    return sorted(settings.music_dir.rglob("*.mp3"), key=lambda p: str(p).lower())


def make_backup_root() -> Path:
    ensure_data_dirs()
    root = BACKUP_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    root.mkdir(parents=True, exist_ok=True)
    return root


def backup_file(path: Path, root: Path, base: Path) -> Path:
    destination = root / path.relative_to(base)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, destination)
    return destination


def write_manifest(root: Path, entries: list[dict[str, Any]]) -> None:
    (root / "manifest.json").write_text(json.dumps({"created": now_iso(), "files": entries}, indent=2), encoding="utf-8")


def restore_backup(root: Path, base: Path) -> int:
    restored = 0
    for source in root.rglob("*.mp3"):
        dest = base / source.relative_to(root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
        restored += 1
    return restored


def read_mp3_metadata(path: Path, fallback: dict[str, Any]) -> dict[str, str]:
    tag = load_id3(path)

    def first_text(frame_id: str) -> str:
        frames = tag.getall(frame_id)
        if not frames:
            return ""
        text = getattr(frames[0], "text", "")
        if isinstance(text, list):
            return str(text[0]) if text else ""
        return str(text or "")

    artist = first_text("TPE1") or str(fallback.get("credited_artists") or "Juice WRLD")
    title = first_text("TIT2") or str(fallback.get("name") or path.stem)
    album = first_text("TALB") or str(fallback.get("album") or "")
    duration = local_duration(path) or parse_length(str(fallback.get("length") or "")) or 0.0
    total_cs = max(0, int(round(duration * 100)))
    minutes, remainder = divmod(total_cs, 6000)
    seconds, centiseconds = divmod(remainder, 100)
    return {"artist": artist, "title": title, "album": album, "length": f"{minutes:02d}:{seconds:02d}.{centiseconds:02d}"}


def write_lrc(path: Path, analysis: dict[str, Any], out_dir: Path) -> Path:
    synced = analysis.get("synced") or []
    candidate = analysis.get("candidate") or {}
    if not synced:
        raise ValueError("No synchronized lyrics available")
    meta = read_mp3_metadata(path, candidate)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{path.stem}.lrc"
    lines = [f"[ar:{meta['artist'].replace(']', '}')}]", f"[ti:{meta['title'].replace(']', '}')}]"]
    if meta["album"]:
        lines.append(f"[al:{meta['album'].replace(']', '}')}]")
    lines.append(f"[length:{meta['length']}]")
    lines.append("")
    for text, timestamp_ms in synced:
        cs = max(0, int(round(timestamp_ms / 10)))
        minutes, remainder = divmod(cs, 6000)
        seconds, centiseconds = divmod(remainder, 100)
        lines.append(f"[{minutes:02d}:{seconds:02d}.{centiseconds:02d}] {text}")
    tmp = out_file.with_suffix(".lrc.tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(out_file)
    return out_file


def patch_rmpc_config(config_path: Path, lyrics_dir: Path) -> Path:
    if not config_path.exists():
        raise RuntimeError(f"rmpc config not found: {config_path}")
    original = config_path.read_text(encoding="utf-8")
    backup = config_path.with_name(f"{config_path.name}.juice-lyrics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(config_path, backup)
    escaped = str(lyrics_dir).replace("\\", "\\\\").replace('"', '\\"')
    replacement = f'    lyrics_dir: Some("{escaped}"),'
    if re.search(r"(?m)^\s*lyrics_dir\s*:", original):
        updated = re.sub(r"(?m)^\s*lyrics_dir\s*:\s*[^,]+,", replacement, original, count=1)
    else:
        updated = original.replace("(", "(\n" + replacement, 1)
    for key in ("enable_lyrics_index", "enable_lyrics_hot_reload"):
        line = f"    {key}: true,"
        if re.search(rf"(?m)^\s*{re.escape(key)}\s*:", updated):
            updated = re.sub(rf"(?m)^\s*{re.escape(key)}\s*:\s*[^,]+,", line, updated, count=1)
        else:
            updated = updated.replace(replacement, replacement + "\n" + line, 1)
    tmp = config_path.with_suffix(config_path.suffix + ".tmp")
    tmp.write_text(updated, encoding="utf-8")
    tmp.replace(config_path)
    return backup


def rmpc_running() -> bool:
    try:
        return subprocess.run(["rmpc", "remote", "query", "active-tab"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False).returncode == 0
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def notify_rmpc_index(paths: list[Path]) -> int:
    if not paths or not rmpc_running():
        return 0
    count = 0
    for path in paths:
        try:
            result = subprocess.run(["rmpc", "remote", "indexlrc", "--path", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3, check=False)
        except (FileNotFoundError, subprocess.SubprocessError):
            break
        if result.returncode == 0:
            count += 1
    return count


def configured_rmpc_lyrics_dir() -> Path:
    return DEFAULT_RMPC_LYRICS_DIR


def write_state_entry(state: dict[str, Any], path: Path, settings: Settings, analysis: dict[str, Any], lrc_path: Path | None) -> None:
    relative = str(path.relative_to(settings.music_dir))
    state.setdefault("files", {})[relative] = {
        "sha256": sha256_file(path),
        "song_id": analysis["candidate"].get("id") if analysis.get("candidate") else None,
        "api_name": analysis["candidate"].get("name") if analysis.get("candidate") else None,
        "lyric_type": "SYLT" if analysis.get("synced") else ("USLT" if analysis.get("plain") else "NONE"),
        "lrc": str(lrc_path) if lrc_path else None,
        "updated": now_iso(),
    }


def state_is_current(state: dict[str, Any], path: Path, settings: Settings, want_rmpc: bool) -> bool:
    relative = str(path.relative_to(settings.music_dir))
    entry = state.get("files", {}).get(relative)
    if not isinstance(entry, dict):
        return False
    try:
        if entry.get("sha256") != sha256_file(path):
            return False
    except OSError:
        return False
    valid, _ = verify_file(path)
    if not valid:
        return False
    if want_rmpc and entry.get("lyric_type") == "SYLT":
        lrc = Path(entry.get("lrc") or "")
        if not lrc.is_file():
            return False
    return True


def embed_batch(settings: Settings, files: list[Path], use_color: bool, refresh: bool, dry_run: bool, yes: bool, with_rmpc: bool) -> int:
    state = load_state()
    lyric_dir = configured_rmpc_lyrics_dir() if with_rmpc else None
    work: list[dict[str, Any]] = []
    skipped_unchanged = 0
    for index, path in enumerate(files, 1):
        if not refresh and state_is_current(state, path, settings, bool(with_rmpc)):
            skipped_unchanged += 1
            print(f"\rScanning: [{index:>2}/{len(files)}] {path.name:<42} (unchanged)", end="", flush=True)
            continue
        print(f"\rScanning: [{index:>2}/{len(files)}] {path.name:<42}", end="", flush=True)
        try:
            analysis = analyse(settings, path, refresh=refresh)
        except Exception as exc:
            print()
            print(colorize(f"✗ {path.name} — {exc}", RED, use_color))
            continue
        work.append(analysis)
    if files:
        print("\r" + " " * 100 + "\r", end="")
    ready = [a for a in work if a.get("candidate") and (a.get("synced") or a.get("plain", "").strip())]
    unresolved = [a for a in work if not a.get("candidate")]
    no_lyrics = [a for a in work if a.get("candidate") and not a.get("synced") and not a.get("plain", "").strip()]
    lrc_ready = sum(1 for a in ready if a.get("synced")) if with_rmpc else 0
    print_header("Library Sync", use_color)
    print(f"Changed/new:     {len(work)}")
    print(f"Unchanged:       {skipped_unchanged}")
    print(f"Ready:           {len(ready)}")
    print(f"  Synced:        {sum(bool(a.get('synced')) for a in ready)}")
    print(f"  Plain fallback: {sum(not bool(a.get('synced')) for a in ready)}")
    if with_rmpc:
        print(f"rmpc LRC ready:  {lrc_ready}")
    print(f"Unresolved:      {len(unresolved)}")
    print(f"No lyrics:       {len(no_lyrics)}")
    if unresolved:
        print(colorize("Unresolved:", YELLOW, use_color))
        for a in unresolved:
            print(f"  - {a['path'].name}")
    if no_lyrics:
        print(colorize("No lyrics:", YELLOW, use_color))
        for a in no_lyrics:
            print(f"  - {a['path'].name}")
    if dry_run:
        print(colorize("\nDry run: no files changed.", CYAN, use_color))
        return 0
    if not ready:
        save_state(state)
        print("Nothing needs updating.")
        return 0
    if not yes:
        if not sys.stdin.isatty():
            print("Non-interactive mode: use --yes to confirm synchronization.")
            return 2
        if input(f"Apply lyrics to {len(ready)} changed/new MP3(s)? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("Cancelled. No files changed.")
            return 0
    backup_root = make_backup_root()
    manifest: list[dict[str, Any]] = []
    generated_lrc: list[Path] = []
    embedded = 0
    errors = 0
    for analysis in ready:
        path = analysis["path"]
        try:
            original_hash = sha256_file(path)
            backup = backup_file(path, backup_root, settings.music_dir)
            lyric_type = embed_lyrics(path, analysis["synced"], analysis["plain"])
            valid, message = verify_file(path)
            if not valid:
                shutil.copy2(backup, path)
                raise RuntimeError(f"verification failed: {message}")
            lrc_path = None
            if with_rmpc and analysis["synced"]:
                lrc_path = write_lrc(path, analysis, lyric_dir)  # type: ignore[arg-type]
                generated_lrc.append(lrc_path)
            write_state_entry(state, path, settings, analysis, lrc_path)
            manifest.append({"file": str(path), "sha256_before": original_hash, "lyric_type": lyric_type, "verification": message})
            extra = f" + LRC" if lrc_path else ""
            print(colorize(f"✓ {path.name}", GREEN, use_color) + f" → {lyric_type}{extra}")
            embedded += 1
        except Exception as exc:
            print(colorize(f"✗ {path.name} — {exc}", RED, use_color))
            errors += 1
    write_manifest(backup_root, manifest)
    save_state(state)
    indexed = notify_rmpc_index(generated_lrc) if with_rmpc else 0
    print()
    print(colorize("Sync complete", BOLD, use_color))
    print(f"  Updated:        {embedded}")
    print(f"  Unchanged:      {skipped_unchanged}")
    print(f"  rmpc LRC files: {len(generated_lrc)}")
    if indexed:
        print(f"  rmpc notified:  {indexed}")
    print(f"  Errors:         {errors}")
    print(f"  Backup:         {backup_root}")
    return 1 if errors else 0



# Core-engine adapters. These keep the CLI commands backward-compatible while
# moving reusable functionality into dedicated modules.
from .config.settings import Settings as _CoreSettings
from .api.client import search_song_names as _api_search_song_names, search_songs as _api_search_songs, get_song as _api_get_song
from .library.matching import normalize as _normalize, parse_version as _parse_version, strip_version as _strip_version, parse_length as _parse_length, local_duration as _local_duration, search_title_for as _search_title_for, score_candidate as _score_candidate, choose_candidate as _choose_candidate
from .lyrics.engine import parse_synced_lyrics as _parse_synced_lyrics, embed_lyrics as _embed_lyrics, verify_file as _verify_file, write_lrc as _write_lrc
from .acquisition import (
    AcquisitionState,
    JobStore,
    ResourceResolutionError,
    integrate_downloaded_mp3,
    load_manifest,
    resolve_resource,
    run_job,
)
from .acquisition.downloader import DownloadPolicy
from .library.scanner import find_mp3s as _find_mp3s
from .backup.manager import make_backup_root as _make_backup_root, backup_file as _backup_file, write_manifest as _write_manifest, restore_backup as _restore_backup
from .state import load_state as _load_state, save_state as _save_state, sha256_file as _sha256_file
from .rmpc.integration import patch_rmpc_config as _patch_rmpc_config, rmpc_running as _rmpc_running, notify_rmpc_index as _notify_rmpc_index
from .services.library_status import get_library_status
from .services.catalogue import get_song_details, search_catalogue
from .services.acquisition_queue import get_queue_snapshot
from .services.library_sync import (
    LibrarySyncOptions,
    MatchOutcome,
    SyncEventKind,
    execute_library_sync,
    plan_library_sync,
)


def search_api(settings: Settings, title: str, refresh: bool = False) -> list[dict[str, Any]]:
    return _api_search_song_names(settings, title, refresh=refresh)


def search_api_advanced(settings: Settings, query: str, category: str | None = None, era: str | None = None, refresh: bool = False) -> dict[str, Any]:
    return _api_search_songs(settings, query, category=category, era=era, refresh=refresh)


def get_song(settings: Settings, song_id: int) -> dict[str, Any]:
    return _api_get_song(settings, song_id)

Settings = _CoreSettings
normalize = _normalize
parse_version = _parse_version
strip_version = _strip_version
parse_length = _parse_length
local_duration = _local_duration
search_title_for = _search_title_for
score_candidate = _score_candidate
choose_candidate = _choose_candidate
parse_synced_lyrics = _parse_synced_lyrics
embed_lyrics = _embed_lyrics
verify_file = _verify_file
find_mp3s = _find_mp3s
make_backup_root = _make_backup_root
backup_file = _backup_file
write_manifest = _write_manifest
restore_backup = _restore_backup
load_state = _load_state
save_state = _save_state
sha256_file = _sha256_file
patch_rmpc_config = _patch_rmpc_config
rmpc_running = _rmpc_running
notify_rmpc_index = _notify_rmpc_index


def write_lrc(path: Path, analysis: dict[str, Any], out_dir: Path) -> Path:
    return _write_lrc(path, analysis.get("synced") or [], analysis.get("candidate") or {}, out_dir)


def load_settings(path_override: str | None = None, api_override: str | None = None) -> Settings:
    settings = Settings()
    if CONFIG_FILE.exists():
        try:
            import tomllib
            data = tomllib.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            if data.get("music_dir"):
                settings.music_dir = Path(str(data["music_dir"])).expanduser()
            settings.api_base = str(data.get("api_base", settings.api_base)).rstrip("/")
            settings.timeout = int(data.get("timeout", settings.timeout))
            settings.delay = float(data.get("delay", settings.delay))
            settings.duration_tolerance = float(data.get("duration_tolerance", settings.duration_tolerance))
            settings.cache_ttl_hours = float(data.get("cache_ttl_hours", settings.cache_ttl_hours))
        except Exception as exc:
            raise RuntimeError(f"Could not read config {CONFIG_FILE}: {exc}") from exc
    if path_override:
        settings.music_dir = Path(path_override).expanduser()
    if api_override:
        settings.api_base = api_override.rstrip("/")
    return settings

def command_setup(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    print_header("juice-lyrics First-Time Setup", use_color)
    print(f"Library: {settings.music_dir}")
    if not settings.music_dir.is_dir():
        raise RuntimeError(f"Music directory does not exist: {settings.music_dir}")
    rmpc_available = shutil.which("rmpc") is not None and DEFAULT_RMPC_CONFIG.exists()
    print(f"rmpc:    {'detected' if rmpc_available else 'not detected'}")
    if not args.yes:
        if not sys.stdin.isatty():
            print("Non-interactive mode: use --yes to confirm setup.")
            return 2
        print("\nSetup will use the library, embed lyrics, and configure rmpc when detected.")
        if input("Continue? [Y/n] ").strip().lower() not in {"", "y", "yes"}:
            print("Cancelled.")
            return 0
    if rmpc_available:
        patch_rmpc_config(DEFAULT_RMPC_CONFIG, DEFAULT_RMPC_LYRICS_DIR)
        DEFAULT_RMPC_LYRICS_DIR.mkdir(parents=True, exist_ok=True)
    files = find_mp3s(settings)
    return embed_batch(settings, files, use_color, args.refresh, False, True, rmpc_available)


def command_sync(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    rmpc_enabled = args.no_rmpc is False
    if rmpc_enabled and not (shutil.which("rmpc") is not None and DEFAULT_RMPC_CONFIG.exists()):
        rmpc_enabled = False
    options = LibrarySyncOptions.from_settings(
        settings,
        dry_run=args.dry_run,
        refresh=args.refresh,
        rmpc_enabled=rmpc_enabled,
        lyrics_dir=DEFAULT_RMPC_LYRICS_DIR if rmpc_enabled else None,
        rmpc_config_path=DEFAULT_RMPC_CONFIG if rmpc_enabled else None,
        state_file=STATE_FILE,
    )

    def scan_progress(event):
        if event.kind is SyncEventKind.TRACK_INSPECTED and event.path is not None:
            suffix = " (unchanged)" if event.message == "unchanged" else ""
            print(f"\rScanning: [{event.index:>2}/{event.total}] {event.path.name:<42}{suffix}", end="", flush=True)
        elif event.kind is SyncEventKind.TRACK_FAILED and event.path is not None:
            print()
            print(colorize(f"✗ {event.path.name} — {event.message}", RED, use_color))

    plan = plan_library_sync(options, progress=scan_progress)
    if plan.total_files:
        print("\r" + " " * 100 + "\r", end="")
    print_header("Library Sync", use_color)
    print(f"Changed/new:     {plan.changed_or_new_files}")
    print(f"Unchanged:       {plan.unchanged_files}")
    print(f"Ready:           {plan.ready_files}")
    print(f"  Synced:        {plan.synced_files}")
    print(f"  Plain fallback: {plan.plain_files}")
    if rmpc_enabled:
        print(f"rmpc LRC ready:  {plan.synced_files}")
    print(f"Unresolved:      {plan.unresolved_files}")
    print(f"No lyrics:       {plan.no_lyrics_files}")
    unresolved = [track for track in plan.tracks if track.outcome is MatchOutcome.UNRESOLVED]
    no_lyrics = [track for track in plan.tracks if track.outcome is MatchOutcome.NO_LYRICS]
    if unresolved:
        print(colorize("Unresolved:", YELLOW, use_color))
        for track in unresolved:
            print(f"  - {track.path.name}")
    if no_lyrics:
        print(colorize("No lyrics:", YELLOW, use_color))
        for track in no_lyrics:
            print(f"  - {track.path.name}")
    if args.dry_run:
        print(colorize("\nDry run: no files changed.", CYAN, use_color))
        return 0
    if not plan.ready_files:
        execute_library_sync(plan)
        print("Nothing needs updating.")
        return 0
    if not args.yes:
        if not sys.stdin.isatty():
            print("Non-interactive mode: use --yes to confirm synchronization.")
            return 2
        if input(f"Apply lyrics to {plan.ready_files} changed/new MP3(s)? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("Cancelled. No files changed.")
            return 0

    def execution_progress(event):
        if event.kind is SyncEventKind.TRACK_COMPLETED and event.path is not None:
            print(colorize(f"✓ {event.path.name}", GREEN, use_color) + f" → {event.message}")
        elif event.kind is SyncEventKind.TRACK_FAILED and event.path is not None:
            print(colorize(f"✗ {event.path.name} — {event.message}", RED, use_color))

    result = execute_library_sync(plan, progress=execution_progress)
    print()
    print(colorize("Sync complete", BOLD, use_color))
    print(f"  Updated:        {result.updated_files}")
    print(f"  Unchanged:      {plan.unchanged_files}")
    print(f"  rmpc LRC files: {result.lrc_files_generated}")
    if result.rmpc_notifications:
        print(f"  rmpc notified:  {result.rmpc_notifications}")
    print(f"  Errors:         {result.processing_failed_files}")
    print(f"  Backup:         {result.backup_path}")
    return 1 if result.processing_failed_files else 0


def command_status(settings: Settings, use_color: bool) -> int:
    status = get_library_status(
        settings,
        state_file=STATE_FILE,
        backup_dir=BACKUP_DIR,
        verifier=verify_file,
    )
    print_header("Library Status", use_color)
    print(f"Library:              {status.library_path}")
    print(f"MP3 files:            {status.track_count}")
    print(f"Embedded synced:      {status.embedded_synced_count}")
    print(f"Embedded plain:       {status.embedded_plain_count}")
    print(f"Missing/invalid:      {status.missing_or_invalid_count}")
    print(f"rmpc LRC files:       {status.rmpc_lrc_count}")
    print(f"New/changed for sync: {status.new_or_changed_count}")
    print(f"Backups:              {status.backup_count}")
    return 1 if status.missing_or_invalid_count else 0


def command_scan(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    files = find_mp3s(settings)
    print_header("Juice WRLD Lyrics Scanner", use_color)
    counts = {"SYNCED": 0, "PLAIN": 0, "NONE": 0, "?": 0}
    for index, path in enumerate(files, 1):
        print(f"\rScanning: [{index:>2}/{len(files)}] {path.name:<42}", end="", flush=True)
        try:
            a = analyse(settings, path, args.refresh)
        except Exception as exc:
            counts["?"] += 1
            print()
            print(colorize(f"✗ {path.name} — {exc}", RED, use_color))
            continue
        if a["synced"]:
            kind = "SYNCED"
        elif a["plain"].strip():
            kind = "PLAIN"
        elif a["candidate"]:
            kind = "NONE"
        else:
            kind = "?"
        counts[kind] += 1
    if files:
        print("\r" + " " * 100 + "\r", end="")
    print(f"Synced: {counts['SYNCED']}  Plain: {counts['PLAIN']}  No lyrics: {counts['NONE']}  Uncertain: {counts['?']}")
    return 1 if counts["?"] else 0


def command_search(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    results = search_catalogue(
        settings,
        args.query,
        category=args.category,
        era=args.era,
        refresh=args.refresh,
        searcher=search_api_advanced,
    )
    print_header(f'Juice WRLD API Search: "{args.query}"', use_color)
    if args.category or args.era:
        filters = []
        if args.category: filters.append(f"category={args.category}")
        if args.era: filters.append(f"era={args.era}")
        print("Filters: " + ", ".join(filters))
    if not results:
        print("No results.")
        return 0
    for song in results:
        print(f"{song.selection_index:>2}. {song.title or 'Unknown'}  [{song.category or '?'}]  [{song.lyrics.value.upper()}]")
        print(f"    id={song.song_id}  era={song.era or ''}  length={song.length or '?'}")
        if song.media_path:
            print(f"    {song.media_path}")
    return 0


def command_info(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    details = get_song_details(
        settings,
        args.query,
        selection_index=args.index,
        refresh=args.refresh,
        searcher=search_api,
        details_fetcher=get_song,
    )
    if details is None:
        print("No results.")
        return 1
    print_header(details.title or "Song", use_color)
    fields = [
        ("ID", details.song_id),
        ("Category", details.category),
        ("Era", details.era),
        ("Length", details.length),
        ("Artist", ", ".join(details.artists)),
        ("Producers", ", ".join(details.producers)),
        ("Path", details.media_path),
        ("Lyrics", details.lyrics.value),
    ]
    for key, value in fields:
        if value not in (None, ""):
            print(f"{key:>10}: {value}")
    return 0


def command_guide() -> int:
    print(f"""{APP_NAME} quick guide

FIRST TIME
  juice-lyrics setup

NORMAL USE
  juice-lyrics sync
  juice-lyrics status

ACQUISITION
  juice-lyrics acquire search "rental"
  juice-lyrics acquire add "rental" --index 1
  juice-lyrics acquire manifest manifest.txt
  juice-lyrics acquire jobs
  juice-lyrics acquire run <job-id>
  juice-lyrics acquire retry <job-id>
  juice-lyrics acquire delete <job-id>

CHECK / TROUBLESHOOT
  juice-lyrics scan
  juice-lyrics verify
  juice-lyrics doctor
  juice-lyrics guide

FIND SONGS IN THE API
  juice-lyrics search "rental"
  juice-lyrics search --category unreleased --era DRFL "moncler"
  juice-lyrics info "rental"

UNDO
  juice-lyrics restore

WHAT SYNC DOES
  1. Matches new/changed MP3s to the API.
  2. Prefers synced lyrics (SYLT).
  3. Falls back to normal embedded lyrics (USLT).
  4. Generates .lrc files for rmpc when synced lyrics exist.
  5. Backs up files before changing them.
  6. Verifies the result.
""")
    return 0


def command_embed(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    return embed_batch(settings, find_mp3s(settings), use_color, args.refresh, args.dry_run, args.yes, False)


def command_verify(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    files = find_mp3s(settings)
    print_header("Embedded Lyrics Verification", use_color)
    good = bad = 0
    for path in files:
        valid, message = verify_file(path)
        if valid:
            print(colorize(f"✓ {path.name} — {message}", GREEN, use_color)); good += 1
        else:
            print(colorize(f"✗ {path.name} — {message}", RED, use_color)); bad += 1
    print(f"\nValid: {good}   Missing: {bad}")
    return 1 if bad else 0


def command_restore(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    roots = sorted(p for p in BACKUP_DIR.iterdir() if p.is_dir()) if BACKUP_DIR.exists() else []
    if not roots:
        print("No backups found."); return 1
    root = BACKUP_DIR / args.backup if args.backup else roots[-1]
    if not root.is_dir():
        print(f"Backup not found: {root}"); return 1
    print_header("Restore Lyrics Backup", use_color)
    print(f"Backup: {root}\nTarget: {settings.music_dir}")
    if not args.yes:
        if not sys.stdin.isatty():
            print("Non-interactive mode: use --yes to confirm restore."); return 2
        if input("Restore this backup? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("Cancelled."); return 0
    count = restore_backup(root, settings.music_dir)
    print(f"Restored {count} MP3s.")
    return 0


def command_doctor(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    print_header("juice-lyrics Doctor", use_color)
    problems = 0
    print(f"Version: {__version__}\nPython:  {sys.version.split()[0]}\nMutagen: OK\nLibrary: {settings.music_dir}")
    if not settings.music_dir.is_dir(): problems += 1; print(colorize("  Library directory does not exist", RED, use_color))
    try:
        api_get(settings.api_base.rstrip("/") + "/", settings.timeout); print("API:     OK")
    except Exception as exc:
        problems += 1; print(colorize(f"API:     FAILED ({exc})", RED, use_color))
    print(f"Config:  {CONFIG_FILE}\nCache:   {CACHE_DIR}\nState:   {STATE_FILE}\nBackups: {BACKUP_DIR}")
    return 1 if problems else 0


def command_config(args: argparse.Namespace) -> int:
    if args.action == "init":
        write_default_config(args.force); print(f"Created {CONFIG_FILE}"); return 0
    if args.action == "show":
        if CONFIG_FILE.exists(): print(CONFIG_FILE.read_text(encoding="utf-8"))
        else: print(f"No config. Defaults are in use.\n{CONFIG_FILE}")
        return 0
    raise RuntimeError("Unknown config action")


def command_cache(args: argparse.Namespace) -> int:
    if args.action == "clear":
        if CACHE_DIR.exists(): shutil.rmtree(CACHE_DIR)
        print("API cache cleared."); return 0
    raise RuntimeError("Unknown cache action")


def command_rmpc_setup(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    config_path = Path(args.config).expanduser() if args.config else DEFAULT_RMPC_CONFIG
    lyrics_dir = Path(args.lyrics_dir).expanduser() if args.lyrics_dir else DEFAULT_RMPC_LYRICS_DIR
    if not lyrics_dir.is_absolute(): lyrics_dir = lyrics_dir.resolve()
    if shutil.which("rmpc") is None: raise RuntimeError("rmpc was not found in PATH")
    if not config_path.exists(): raise RuntimeError(f"rmpc config not found: {config_path}")
    print_header("rmpc Lyrics Setup", use_color)
    print(f"Library:     {settings.music_dir}\nLRC folder:  {lyrics_dir}\nrmpc config: {config_path}\n")
    if not args.yes:
        if not sys.stdin.isatty(): print("Non-interactive mode: use --yes."); return 2
        if input("Create LRC files and update rmpc config? [y/N] ").strip().lower() not in {"y", "yes"}:
            print("Cancelled. No changes made."); return 0
    lyrics_dir.mkdir(parents=True, exist_ok=True)
    analyses = []
    files = find_mp3s(settings)
    for i, path in enumerate(files, 1):
        print(f"\rScanning: [{i:>2}/{len(files)}] {path.name:<42}", end="", flush=True)
        analyses.append(analyse(settings, path, args.refresh))
    print("\r" + " " * 100 + "\r", end="")
    generated = []
    for a in analyses:
        if not a.get("synced"): continue
        generated.append(write_lrc(a["path"], a, lyrics_dir))
        print(colorize(f"✓ {a['path'].name}", GREEN, use_color) + " → LRC")
    backup = patch_rmpc_config(config_path, lyrics_dir)
    indexed = notify_rmpc_index(generated)
    print(f"\nrmpc setup complete\n  LRC files:     {len(generated)}\n  Lyrics folder: {lyrics_dir}\n  Config backup: {backup}")
    if indexed: print(f"  rmpc notified: {indexed}")
    elif not rmpc_running(): print("  rmpc: not currently running; start/restart it to load the setup")
    return 0


def command_rmpc_sync(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    lyrics_dir = Path(args.lyrics_dir).expanduser() if args.lyrics_dir else DEFAULT_RMPC_LYRICS_DIR
    lyrics_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    for path in find_mp3s(settings):
        a = analyse(settings, path, args.refresh)
        if not a.get("synced"): continue
        generated.append(write_lrc(path, a, lyrics_dir))
        print(colorize(f"✓ {path.name}", GREEN, use_color))
    print(f"Generated: {len(generated)}   Notified: {notify_rmpc_index(generated)}")
    return 0


def command_rmpc_verify(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    lyrics_dir = Path(args.lyrics_dir).expanduser() if args.lyrics_dir else DEFAULT_RMPC_LYRICS_DIR
    files = sorted(lyrics_dir.glob("*.lrc")) if lyrics_dir.is_dir() else []
    good = bad = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        valid = bool(re.search(r"(?m)^\[ar:.+\]$", text) and re.search(r"(?m)^\[ti:.+\]$", text) and re.search(r"(?m)^\[length:\d{2}:\d{2}(?:\.\d{2})?\]$", text) and LRC_RE.search(text))
        print(colorize(f"✓ {path.name}", GREEN, use_color) if valid else colorize(f"✗ {path.name}", RED, use_color)); good += valid; bad += not valid
    print(f"Valid: {good}   Invalid: {bad}")
    return 1 if bad else 0



def _acquisition_resource_url(resource: dict[str, Any], api_base: str = DEFAULT_API_BASE) -> str | None:
    for field in ("resource_url", "download_url", "audio_url", "file_url", "url"):
        value = resource.get(field)
        if value:
            return str(value)
    path = resource.get("path") or resource.get("file_path")
    if path:
        path_str = str(path).strip()
        if path_str.startswith(("http://", "https://")):
            return path_str
        return f"{api_base.rstrip('/')}/files/download/?path={quote(path_str)}"
    return None


def command_acquire_search(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    data = search_api_advanced(settings, args.query, args.category, args.era, args.refresh)
    results = data.get("results", []) if isinstance(data, dict) else []
    if not isinstance(results, list) or not results:
        print("No API results found.")
        return 1

    print_header(f'Acquisition candidates for "{args.query}"', use_color)
    shown = 0
    for index, song in enumerate(results, start=1):
        if not isinstance(song, dict):
            continue
        title = str(song.get("title") or song.get("name") or "Untitled")
        category = str(song.get("category") or "unknown")
        version = str(song.get("version") or "")
        lyrics = "SYNCED" if str(song.get("synced_lyrics") or "").strip() else ("PLAIN" if str(song.get("lyrics") or "").strip() else "NONE")
        url = _acquisition_resource_url(song, settings.api_base)
        available = "DOWNLOADABLE" if url else "NO DOWNLOAD URL"
        detail = " / ".join(part for part in (category, version, lyrics, available) if part)
        shown += 1
        print(f"  {index:>2}. {title} — {detail}")
    if shown == 0:
        print("No usable API results found.")
        return 1
    print("\nUse: juice-lyrics acquire add \"<query>\" --index <number(s)>")
    return 0


def _parse_indexes(raw: str | int | None) -> list[int] | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        if raw <= 0:
            raise RuntimeError(f"Invalid --index: {raw}. Indexes must be positive integers (1-based).")
        return [raw]
    raw_str = str(raw).strip()
    if not raw_str:
        return None
    parts = [p.strip() for p in raw_str.split(",") if p.strip()]
    if not parts:
        raise RuntimeError("Invalid --index: no index specified.")
    indexes: list[int] = []
    seen: set[int] = set()
    for part in parts:
        try:
            val = int(part)
        except ValueError as exc:
            raise RuntimeError(f"Invalid --index value: {part!r}. Expected 1-based integers (e.g. 1 or 1,2,4).") from exc
        if val <= 0:
            raise RuntimeError(f"Invalid --index value: {val}. Indexes must be positive (1-based).")
        if val not in seen:
            seen.add(val)
            indexes.append(val)
    return indexes


def _select_acquisition_results(
    settings: Settings,
    query: str,
    index_arg: str | int | None,
    refresh: bool,
) -> list[dict[str, Any]]:
    data = search_api_advanced(settings, query, refresh=refresh)
    results = data.get("results", []) if isinstance(data, dict) else []
    if not isinstance(results, list) or not results:
        raise RuntimeError(f'No API results found for "{query}"')
    objects = [result for result in results if isinstance(result, dict)]
    if not objects:
        raise RuntimeError(f'No usable API results found for "{query}"')

    indexes = _parse_indexes(index_arg)
    if indexes is None:
        if len(objects) != 1:
            raise RuntimeError(f"Found {len(objects)} results. Use --index to explicitly choose one.")
        return [objects[0]]

    if len(indexes) == 1 and (indexes[0] < 1 or indexes[0] > len(objects)):
        raise RuntimeError(f"--index must be between 1 and {len(objects)}")

    selected: list[dict[str, Any]] = []
    for idx in indexes:
        if idx < 1 or idx > len(objects):
            raise RuntimeError(f"--index {idx} is out of range (must be between 1 and {len(objects)})")
        selected.append(objects[idx - 1])
    return selected


def _select_acquisition_result(
    settings: Settings,
    query: str,
    index: int | str | None,
    refresh: bool,
) -> dict[str, Any]:
    selected = _select_acquisition_results(settings, query, index, refresh)
    return selected[0]


def command_acquire_add(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    if getattr(args, "manifest", None):
        manifest_args = argparse.Namespace(
            manifest_path=args.manifest,
            destination=getattr(args, "destination", None),
            allow_http=getattr(args, "allow_http", False),
            refresh=getattr(args, "refresh", False),
        )
        return command_acquire_manifest(manifest_args, settings, use_color)

    if not getattr(args, "query", None):
        raise RuntimeError("Either a query or --manifest must be provided.")

    resources = _select_acquisition_results(settings, args.query, getattr(args, "index", None), args.refresh)
    destination_dir = Path(args.destination).expanduser() if args.destination else settings.music_dir

    items: list[AcquisitionItem] = []
    seen_destinations: set[Path] = set()
    seen_identifiers: set[str] = set()

    for resource in resources:
        try:
            item = resolve_resource(resource, destination_dir=destination_dir, api_base=settings.api_base, allow_http=args.allow_http)
        except ResourceResolutionError as exc:
            title = str(resource.get("name") or resource.get("title") or "Resource")
            raise RuntimeError(f"That API result cannot be acquired safely ({title}): {exc}") from exc

        if item.identifier in seen_identifiers or item.destination in seen_destinations:
            continue
        seen_identifiers.add(item.identifier)
        seen_destinations.add(item.destination)
        items.append(item)

    if not items:
        raise RuntimeError("No valid items to acquire.")

    store = JobStore()
    job = store.create(items)
    print_header("Acquisition job created", use_color)
    print(f"Job ID:      {job.job_id}")
    if len(items) == 1:
        item = items[0]
        print(f"Title:       {item.title}")
        print(f"Destination: {item.destination}")
        print(f"URL:         {item.url}")
        if item.expected_size is not None:
            print(f"Expected:    {item.expected_size} bytes")
    else:
        print(f"Items ({len(items)}):")
        for item in items:
            print(f"  - {item.title} → {item.destination}")
    print(f"\nRun it with: juice-lyrics acquire run {job.job_id}")
    return 0


def command_acquire_manifest(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    manifest_path = Path(args.manifest_path).expanduser()
    queries = load_manifest(manifest_path)
    if not queries:
        raise RuntimeError(f"Manifest contains no valid entries: {manifest_path}")

    destination_dir = Path(args.destination).expanduser() if getattr(args, "destination", None) else settings.music_dir

    items: list[AcquisitionItem] = []
    seen_destinations: set[Path] = set()
    seen_identifiers: set[str] = set()
    unresolved: list[str] = []

    for query in queries:
        try:
            data = search_api_advanced(settings, query, refresh=getattr(args, "refresh", False))
            results = data.get("results", []) if isinstance(data, dict) else []
            objects = [r for r in results if isinstance(r, dict)]
            if not objects:
                unresolved.append(f"No API results found for {query!r}")
                continue

            if len(objects) == 1:
                resource = objects[0]
            else:
                exact = [
                    r for r in objects
                    if str(r.get("name") or r.get("title") or "").strip().lower() == query.strip().lower()
                ]
                if len(exact) == 1:
                    resource = exact[0]
                else:
                    unresolved.append(
                        f"Manifest entry {query!r} matched {len(objects)} results; specify exact title or version"
                    )
                    continue

            item = resolve_resource(resource, destination_dir=destination_dir, api_base=settings.api_base, allow_http=getattr(args, "allow_http", False))
            if item.identifier in seen_identifiers or item.destination in seen_destinations:
                continue
            seen_identifiers.add(item.identifier)
            seen_destinations.add(item.destination)
            items.append(item)

        except (ResourceResolutionError, RuntimeError) as exc:
            unresolved.append(f"Failed resolving {query!r}: {exc}")

    if unresolved and not items:
        err_msg = "\n".join(f"  - {u}" for u in unresolved)
        raise RuntimeError(f"Could not resolve any manifest entries:\n{err_msg}")

    if not items:
        raise RuntimeError("No valid acquisition items could be created from the manifest.")

    store = JobStore()
    job = store.create(items)
    print_header("Acquisition job created from manifest", use_color)
    print(f"Manifest:    {manifest_path}")
    print(f"Job ID:      {job.job_id}")
    print(f"Items ({len(items)}):")
    for item in items:
        print(f"  - {item.title} → {item.destination}")
    if unresolved:
        print(colorize("\nUnresolved / Skipped entries:", YELLOW, use_color))
        for u in unresolved:
            print(f"  - {u}")
    print(f"\nRun it with: juice-lyrics acquire run {job.job_id}")
    return 0


def command_acquire_jobs(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    store = JobStore()
    snapshot = get_queue_snapshot(store.path)
    if not snapshot.jobs:
        print("No acquisition jobs.")
        return 0
    print_header("Acquisition jobs", use_color)
    for job in snapshot.jobs:
        print(f"  {job.job_id} — {job.stored_state} — {job.total_item_count} item(s)")
        for item in job.items:
            print(f"      {item.stored_state:<14} {item.title} → {item.destination}")
    return 0


def _run_acquisition_job(job: AcquisitionJob, store: JobStore, settings: Settings, use_color: bool, title: str) -> int:
    def progress(index: int, total: int, written: int, remote_total: int | None) -> None:
        size = f"/{remote_total}" if remote_total is not None else ""
        print(f"  [{index + 1}/{total}] {written}{size} bytes", end="\r", flush=True)

    print_header(title, use_color)
    def postprocess(result):
        if result.postprocessing_retry:
            print(f"\n  Retrying post-processing from existing finalized file: {result.item.destination}")
        integration = integrate_downloaded_mp3(
            result.item,
            song_fetcher=lambda song_id: _api_get_song(settings, song_id),
            lyrics_dir=configured_rmpc_lyrics_dir(),
            settings=settings,
        )
        if integration.message:
            prefix = colorize(f"  ✓ {integration.path.name} — ", GREEN, use_color)
            print(f"\n{prefix}{integration.message}")
        return integration

    summary = run_job(job, store, policy=DownloadPolicy(), progress=progress, postprocess=postprocess)
    print("\n")
    print(f"Completed: {summary.completed}")
    print(f"Skipped:   {summary.skipped}")
    print(f"Failed:    {summary.failed}")
    print(f"Pending:   {summary.pending}")
    for entry in job.items:
        if entry.error:
            print(colorize(f"  {entry.item.title}: {entry.error}", RED, use_color))
    return 0 if summary.ok else 1


def command_acquire_run(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    store = JobStore()
    store.recover_interrupted()
    job = store.get(args.job_id)
    if job is None:
        raise RuntimeError(f"Acquisition job not found: {args.job_id}")
    return _run_acquisition_job(job, store, settings, use_color, f"Running acquisition job {job.job_id}")


def command_acquire_retry(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    store = JobStore()
    store.recover_interrupted()
    job = store.get(args.job_id)
    if job is None:
        raise RuntimeError(f"Acquisition job not found: {args.job_id}")

    retryable = [
        entry for entry in job.items
        if entry.state not in {AcquisitionState.COMPLETE, AcquisitionState.SKIPPED}
    ]
    if not retryable:
        print_header(f"Acquisition job {job.job_id}", use_color)
        print("All items in this job are already completed or skipped. Nothing to retry.")
        return 0

    return _run_acquisition_job(job, store, settings, use_color, f"Retrying acquisition job {job.job_id}")


def command_acquire_delete(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    store = JobStore()
    job = store.get(args.job_id)
    if job is None:
        raise RuntimeError(f"Acquisition job not found: {args.job_id}")

    transient = {
        AcquisitionState.CHECKING_EXISTING,
        AcquisitionState.DOWNLOADING,
        AcquisitionState.VALIDATING,
    }
    has_active = any(entry.state in transient for entry in job.items)
    if has_active and not getattr(args, "force", False):
        raise RuntimeError(
            f"Cannot delete job {job.job_id}: job has items marked as actively in-progress. Use --force to delete anyway."
        )

    deleted = store.delete(job.job_id)
    if not deleted:
        raise RuntimeError(f"Failed to delete acquisition job: {job.job_id}")

    print_header("Acquisition job deleted", use_color)
    print(f"Deleted job ID: {job.job_id} ({len(job.items)} item(s))")
    print("Downloaded audio files were preserved.")
    return 0


def command_acquire(args: argparse.Namespace, settings: Settings, use_color: bool) -> int:
    if args.action == "search":
        return command_acquire_search(args, settings, use_color)
    if args.action == "add":
        return command_acquire_add(args, settings, use_color)
    if args.action == "manifest":
        return command_acquire_manifest(args, settings, use_color)
    if args.action == "jobs":
        return command_acquire_jobs(args, settings, use_color)
    if args.action == "run":
        return command_acquire_run(args, settings, use_color)
    if args.action == "retry":
        return command_acquire_retry(args, settings, use_color)
    if args.action == "delete":
        return command_acquire_delete(args, settings, use_color)
    raise RuntimeError("Unknown acquisition action")

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Manage lyrics metadata and rmpc LRC files for local MP3 libraries.")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    parser.add_argument("--path", help="MP3 library directory (overrides config).")
    parser.add_argument("--api-base", help="Override the API base URL.")
    parser.add_argument("--no-color", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="First-time setup: embed lyrics and configure rmpc when detected.")
    setup.add_argument("--yes", action="store_true")
    setup.add_argument("--refresh", action="store_true")

    sync = sub.add_parser("sync", help="Update only new/changed files and refresh rmpc LRC files.")
    sync.add_argument("--yes", action="store_true")
    sync.add_argument("--dry-run", action="store_true")
    sync.add_argument("--refresh", action="store_true")
    sync.add_argument("--no-rmpc", action="store_true", help="Do not generate rmpc LRC files.")

    status = sub.add_parser("status", help="Show library state without contacting the API.")

    scan = sub.add_parser("scan", help="Scan the API and report matches.")
    scan.add_argument("--refresh", action="store_true")

    embed = sub.add_parser("embed", help="Low-level command: embed lyrics into MP3s.")
    embed.add_argument("--yes", action="store_true")
    embed.add_argument("--dry-run", action="store_true")
    embed.add_argument("--refresh", action="store_true")

    verify = sub.add_parser("verify", help="Verify embedded lyrics.")

    restore = sub.add_parser("restore", help="Restore a previous MP3 backup.")
    restore.add_argument("--backup")
    restore.add_argument("--yes", action="store_true")

    doctor = sub.add_parser("doctor", help="Check the installation and API connection.")

    guide = sub.add_parser("guide", help="Show the built-in quick guide.")

    search = sub.add_parser("search", help="Search the public Juice WRLD song catalogue.")
    search.add_argument("query")
    search.add_argument("--category")
    search.add_argument("--era")
    search.add_argument("--refresh", action="store_true")

    info = sub.add_parser("info", help="Show detailed API metadata for a song search.")
    info.add_argument("query")
    info.add_argument("--index", type=int, help="Choose a result from the search list (1-based).")
    info.add_argument("--refresh", action="store_true")

    acquire = sub.add_parser("acquire", help="Explicitly select and acquire API media resources.")
    ac = acquire.add_subparsers(dest="action", required=True)
    acs = ac.add_parser("search", help="Search acquisition candidates without downloading anything.")
    acs.add_argument("query")
    acs.add_argument("--category")
    acs.add_argument("--era")
    acs.add_argument("--refresh", action="store_true")
    aca = ac.add_parser("add", help="Create a persistent job for explicitly selected results or manifest.")
    aca.add_argument("query", nargs="?", help="Song query or title to search.")
    aca.add_argument("--manifest", help="Path to an explicit selection manifest file.")
    aca.add_argument("--index", help="Choose result(s) from the search list (1-based, e.g. 1 or 1,2,4).")
    aca.add_argument("--destination", help="Directory for the acquired media (defaults to the configured library).")
    aca.add_argument("--allow-http", action="store_true", help="Allow an HTTP resource URL (HTTPS remains the default).")
    aca.add_argument("--refresh", action="store_true")
    acm = ac.add_parser("manifest", help="Create a persistent job from an explicit selection manifest file.")
    acm.add_argument("manifest_path", help="Path to text manifest file.")
    acm.add_argument("--destination", help="Directory for the acquired media (defaults to the configured library).")
    acm.add_argument("--allow-http", action="store_true", help="Allow an HTTP resource URL (HTTPS remains the default).")
    acm.add_argument("--refresh", action="store_true")
    ac.add_parser("jobs", help="List persistent acquisition jobs.")
    acr = ac.add_parser("run", help="Run one persistent acquisition job.")
    acr.add_argument("job_id")
    acret = ac.add_parser("retry", help="Retry failed or pending items in a persistent acquisition job.")
    acret.add_argument("job_id")
    acd = ac.add_parser("delete", help="Delete a persistent acquisition job record.")
    acd.add_argument("job_id")
    acd.add_argument("--force", action="store_true", help="Force deletion even if job is marked in-progress.")

    rmpc = sub.add_parser("rmpc", help="Advanced rmpc-only operations.")
    rs = rmpc.add_subparsers(dest="action", required=True)
    r1 = rs.add_parser("setup")
    r1.add_argument("--config")
    r1.add_argument("--lyrics-dir")
    r1.add_argument("--yes", action="store_true")
    r1.add_argument("--refresh", action="store_true")
    r2 = rs.add_parser("sync")
    r2.add_argument("--lyrics-dir")
    r2.add_argument("--refresh", action="store_true")
    r3 = rs.add_parser("verify")
    r3.add_argument("--lyrics-dir")

    config = sub.add_parser("config", help="Manage configuration.")
    cs = config.add_subparsers(dest="action", required=True)
    ci = cs.add_parser("init"); ci.add_argument("--force", action="store_true")
    cs.add_parser("show")

    cache = sub.add_parser("cache", help="Manage API cache.")
    csub = cache.add_subparsers(dest="action", required=True); csub.add_parser("clear")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    use_color = not args.no_color and sys.stdout.isatty()
    try:
        settings = load_settings(getattr(args, "path", None), getattr(args, "api_base", None))
        if args.command == "setup": return command_setup(args, settings, use_color)
        if args.command == "sync": return command_sync(args, settings, use_color)
        if args.command == "status": return command_status(settings, use_color)
        if args.command == "scan": return command_scan(args, settings, use_color)
        if args.command == "embed": return command_embed(args, settings, use_color)
        if args.command == "verify": return command_verify(args, settings, use_color)
        if args.command == "restore": return command_restore(args, settings, use_color)
        if args.command == "doctor": return command_doctor(args, settings, use_color)
        if args.command == "guide": return command_guide()
        if args.command == "search": return command_search(args, settings, use_color)
        if args.command == "info": return command_info(args, settings, use_color)
        if args.command == "acquire": return command_acquire(args, settings, use_color)
        if args.command == "rmpc":
            if args.action == "setup": return command_rmpc_setup(args, settings, use_color)
            if args.action == "sync": return command_rmpc_sync(args, settings, use_color)
            if args.action == "verify": return command_rmpc_verify(args, settings, use_color)
        if args.command == "config": return command_config(args)
        if args.command == "cache": return command_cache(args)
        parser.error("Unknown command")
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr); return 130
    except RuntimeError as exc:
        print(colorize(f"Error: {exc}", RED, use_color), file=sys.stderr); return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

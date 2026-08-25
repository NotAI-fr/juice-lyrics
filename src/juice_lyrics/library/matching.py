from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mutagen.mp3 import MP3

from ..config.settings import Settings

CANONICAL_SEARCH = {
    "chase the dragon": "Life's a Dungeon",
    "off the rip": "Off the Rip",
    "on my own": "On My Own",
    "party in my mind": "Until I Die",
    "stick talk": "Stick Talk",
    "whatever": "Call Me Whenever",
}


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
            return int(parts[0]) * 60 + float(parts[1])
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
    except ValueError:
        return None
    return None


def local_duration(path: Path) -> float | None:
    try:
        return float(MP3(path).info.length)
    except Exception:
        return None


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
            score += 150; reasons.append("exact API filename")
        if normalize(Path(api_path).stem) == normalize(path.stem):
            score += 120; reasons.append("exact API path filename")
    if local and local == candidate_name:
        score += 100; reasons.append("exact title")
    if local and local == original_key:
        score += 90; reasons.append("exact original key")
    if normalize(search_title) == candidate_name:
        score += 45; reasons.append("search title match")
    lt, ct = set(local.split()), set(candidate_name.split())
    if lt and ct:
        score += (len(lt & ct) / len(lt | ct)) * 30
    local_len = local_duration(path); api_len = parse_length(str(candidate.get("length") or ""))
    if local_len is not None and api_len is not None:
        diff = abs(local_len - api_len)
        if diff <= settings.duration_tolerance:
            score += max(0.0, 60.0 - diff * 10.0); reasons.append(f"duration match ({diff:.2f}s)")
        else:
            score -= min(diff * 5.0, 60.0); reasons.append(f"duration mismatch ({diff:.2f}s)")
    if candidate.get("category") == "unreleased":
        score += 10; reasons.append("unreleased")
    if candidate.get("category") == "released":
        score -= 150; reasons.append("released")
    return score, reasons


def choose_candidate(settings: Settings, path: Path, results: list[dict[str, Any]], search_title: str):
    scored = []
    for candidate in results:
        score, reasons = score_candidate(settings, path, candidate, search_title)
        scored.append((score, candidate, reasons))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return None, 0.0, [], []
    best_score, best, reasons = scored[0]
    if best_score < 70 or (len(scored) >= 2 and best_score - scored[1][0] < 12):
        return None, best_score, reasons, scored
    return best, best_score, reasons, scored

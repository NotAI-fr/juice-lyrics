from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mutagen.mp3 import MP3

from ..config.settings import Settings
from .media import is_tagged_container, read_tagged_metadata, tagged_matching_title

CANONICAL_SEARCH = {
    "chase the dragon": "Life's a Dungeon",
    "off the rip": "Off the Rip",
    "on my own": "On My Own",
    "party in my mind": "Until I Die",
    "stick talk": "Stick Talk",
    "whatever": "Call Me Whenever",
}

MATCH_THRESHOLD = 70.0
AMBIGUITY_MARGIN = 12.0
DURATION_GRACE_EXTRA_SECONDS = 2.0
MAX_DURATION_GRACE_SECONDS = 5.0
MAX_DURATION_GRACE_RATIO = 0.02
_NAMED_VARIANTS = {
    "acoustic": r"\bacoustic\b",
    "demo": r"\bdemo\b",
    "extended outro": r"\bextended\s+outro\b",
    "instrumental": r"\binstrumental\b",
    "live": r"\blive\b",
    "radio edit": r"\bradio\s+edit\b",
    "remix": r"\bremix\b",
    "slowed": r"\bslowed\b",
    "sped up": r"\bsped\s+up\b",
    "stem": r"\bstems?\b",
    "tv mix": r"\btv\s+mix\b",
}
_ALBUM_EDITION_GROUP = re.compile(
    r"\s*[\[(]\s*(?:"
    r"bonus\s+track\s+version|"
    r"deluxe(?:\s+edition)?|"
    r"(?:[1-9]\d*(?:[\s-]+year|(?:st|nd|rd|th))\s+)?anniversary(?:\s+edition)?|"
    r"expanded(?:\s+edition)?|"
    r"special\s+edition"
    r")\s*[\])]\s*",
    re.I,
)


@dataclass(frozen=True, slots=True)
class CandidateDiagnostic:
    song_id: Any
    name: str
    score: float
    eligible: bool
    selected: bool
    rejection: str | None
    reasons: tuple[str, ...]


def normalize(text: str) -> str:
    text = str(text).lower().replace("’", "'")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"\[[^]]*\]", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_words(text: str) -> str:
    """Normalize words while retaining parenthetical edition information."""

    text = str(text).lower().replace("’", "'")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def parse_version(text: str) -> int | None:
    match = re.search(r"(?:\(|\[)?v(\d+)(?:\)|\])?", text, flags=re.I)
    return int(match.group(1)) if match else None


def strip_version(text: str) -> str:
    return re.sub(r"\s*(?:\(|\[)?v\d+(?:\.\d+)?(?:\)|\])?\s*$", "", text, flags=re.I).strip()


def strip_feature_credit(text: str) -> str:
    """Remove only collaboration credits that commonly impede catalogue search."""

    return re.sub(
        r"\s*[\[(]\s*(?:feat(?:uring)?\.?|ft\.?|with)\s+[^\])]+[\])]\s*",
        " ",
        text,
        flags=re.I,
    ).strip()


def named_variants(text: str) -> frozenset[str]:
    """Return explicit non-version recording variants from a title."""

    return frozenset(
        label for label, pattern in _NAMED_VARIANTS.items() if re.search(pattern, text, re.I)
    )


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
        if is_tagged_container(path):
            return read_tagged_metadata(path).duration_seconds
        return float(MP3(path).info.length)
    except Exception:
        return None


def local_album(path: Path) -> str | None:
    """Read optional album evidence without making it a matching requirement."""

    try:
        if is_tagged_container(path):
            return read_tagged_metadata(path).album
        tags = MP3(path).tags
        frame = tags.get("TALB") if tags is not None else None
        values = getattr(frame, "text", None)
        if values:
            value = str(values[0]).strip()
            return value or None
    except Exception:
        pass
    return None


def _album_key(value: str) -> str:
    return re.sub(r"^\d+\s+", "", normalize_words(value))


def _album_edition_base(value: str) -> str:
    return _album_key(_ALBUM_EDITION_GROUP.sub(" ", value))


def _candidate_album_values(candidate: dict[str, Any]) -> list[str]:
    values: list[str] = []
    album = candidate.get("album")
    if isinstance(album, dict):
        values.extend(str(album.get(key) or "") for key in ("name", "title"))
    elif isinstance(album, (list, tuple)):
        values.extend(str(value) for value in album)
    elif album:
        values.append(str(album))
    api_path = str(candidate.get("path") or "")
    if api_path:
        values.extend(Path(api_path).parts[:-1])
    return values


def album_match_kind(path: Path, candidate: dict[str, Any]) -> str | None:
    album = local_album(path)
    if not album:
        return None
    local_key = _album_key(album)
    candidate_values = _candidate_album_values(candidate)
    candidates = {key for value in candidate_values if (key := _album_key(value))}
    if local_key and local_key in candidates:
        return "exact"
    local_base = _album_edition_base(album)
    if local_base and any(
        local_base == _album_edition_base(candidate_album)
        for candidate_album in candidate_values
    ):
        return "edition"
    return None


def album_matches(path: Path, candidate: dict[str, Any]) -> bool:
    return album_match_kind(path, candidate) is not None


def _duration_grace_allowed(
    settings: Settings,
    *,
    local_title: str,
    candidate_title: str,
    local_version: int | None,
    candidate_version: int | None,
    extra_variants: frozenset[str],
    category: object,
    album_evidence: str | None,
    local_seconds: float,
    difference: float,
) -> bool:
    maximum = min(
        MAX_DURATION_GRACE_SECONDS,
        settings.duration_tolerance + DURATION_GRACE_EXTRA_SECONDS,
    )
    return (
        difference <= maximum
        and difference / max(local_seconds, 1.0) <= MAX_DURATION_GRACE_RATIO
        and local_title == candidate_title
        and (candidate_version is None or candidate_version == local_version)
        and not extra_variants
        and category == "released"
        and album_evidence is not None
    )


def search_title_for(path: Path) -> str:
    raw_title = tagged_matching_title(path) if is_tagged_container(path) else path.stem
    stripped = strip_feature_credit(strip_version(raw_title))
    return CANONICAL_SEARCH.get(normalize(stripped), stripped)


def score_candidate(settings: Settings, path: Path, candidate: dict[str, Any], search_title: str) -> tuple[float, list[str]]:
    local_raw = tagged_matching_title(path) if is_tagged_container(path) else path.stem
    candidate_raw = str(candidate.get("name", ""))
    local = normalize(strip_version(local_raw))
    candidate_name = normalize(strip_version(candidate_raw))
    original_key = normalize(strip_version(str(candidate.get("original_key", ""))))
    local_version = parse_version(local_raw)
    candidate_version = parse_version(candidate_raw)
    local_variants = named_variants(local_raw)
    candidate_variants = named_variants(candidate_raw)
    album_evidence = album_match_kind(path, candidate)
    reasons: list[str] = []
    score = 0.0
    if local_version is not None:
        if candidate_version == local_version:
            score += 120
            reasons.append(f"exact version v{local_version}")
        elif candidate_version is not None:
            score -= 120
            reasons.append(f"wrong version (API v{candidate_version}, local v{local_version})")
        else:
            score -= 60
            reasons.append(f"missing local version v{local_version} (-60)")
    elif candidate_version is not None:
        score -= 80
        reasons.append(f"candidate-only version v{candidate_version} (-80)")
    extra_variants = candidate_variants - local_variants
    if extra_variants:
        penalty = 90 * len(extra_variants)
        score -= penalty
        reasons.append(f"candidate-only variant {', '.join(sorted(extra_variants))} (-{penalty})")
    api_path = str(candidate.get("path") or "")
    if api_path:
        if normalize(Path(api_path).name) == normalize(path.name):
            score += 150; reasons.append("exact API filename")
        if normalize(Path(api_path).stem) == normalize(path.stem):
            score += 120; reasons.append("exact API path filename")
    if local and local == candidate_name:
        score += 100; reasons.append("exact title (+100)")
    if local and local == original_key:
        score += 90; reasons.append("exact original key")
    if normalize(search_title) == candidate_name:
        score += 45; reasons.append("search title match (+45)")
    lt, ct = set(local.split()), set(candidate_name.split())
    if lt and ct:
        overlap = (len(lt & ct) / len(lt | ct)) * 30
        score += overlap
        reasons.append(f"title token overlap (+{overlap:.2f})")
    local_len = local_duration(path); api_len = parse_length(str(candidate.get("length") or ""))
    if local_len is not None and api_len is not None:
        diff = abs(local_len - api_len)
        if diff <= settings.duration_tolerance:
            duration_score = max(0.0, 60.0 - diff * 10.0)
            score += duration_score
            reasons.append(f"duration match ({diff:.2f}s, +{duration_score:.2f})")
        elif _duration_grace_allowed(
            settings,
            local_title=local,
            candidate_title=candidate_name,
            local_version=local_version,
            candidate_version=candidate_version,
            extra_variants=extra_variants,
            category=candidate.get("category"),
            album_evidence=album_evidence,
            local_seconds=local_len,
            difference=diff,
        ):
            duration_score = -(5.0 + (diff - settings.duration_tolerance) * 5.0)
            score += duration_score
            reasons.append(
                f"duration catalogue grace ({diff:.3f}s delta; outside normal "
                f"{settings.duration_tolerance:.2f}s; strong released-album evidence; "
                f"{duration_score:+.2f})"
            )
        else:
            duration_penalty = min(diff * 5.0, 60.0)
            score -= duration_penalty
            maximum = min(
                MAX_DURATION_GRACE_SECONDS,
                settings.duration_tolerance + DURATION_GRACE_EXTRA_SECONDS,
            )
            reasons.append(
                f"duration mismatch ({diff:.3f}s; outside maximum grace "
                f"{maximum:.2f}s or missing corroboration; -{duration_penalty:.2f})"
            )
    else:
        reasons.append("duration unknown (+0)")
    if candidate.get("category") == "released":
        score += 10
        reasons.append("released (+10)")
    if album_evidence == "exact":
        score += 35
        reasons.append("album/path match (+35)")
    elif album_evidence == "edition":
        score += 30
        reasons.append("album edition/path match (+30)")
    return score, reasons


def choose_candidate(settings: Settings, path: Path, results: list[dict[str, Any]], search_title: str):
    scored = []
    for candidate in results:
        score, reasons = score_candidate(settings, path, candidate, search_title)
        scored.append((score, candidate, reasons))
    scored.sort(key=lambda x: x[0], reverse=True)
    if not scored:
        return None, 0.0, [], []
    eligible = [
        item
        for item in scored
        if not any(reason.startswith("duration mismatch") for reason in item[2])
    ]
    if not eligible:
        best_score, _, reasons = scored[0]
        return None, best_score, reasons, scored
    best_score, best, reasons = eligible[0]
    if best_score < MATCH_THRESHOLD or (
        len(eligible) >= 2 and best_score - eligible[1][0] < AMBIGUITY_MARGIN
    ):
        return None, best_score, reasons, scored
    return best, best_score, reasons, scored


def diagnose_candidates(
    settings: Settings,
    path: Path,
    results: list[dict[str, Any]],
    search_title: str,
) -> tuple[CandidateDiagnostic, ...]:
    """Expose deterministic matcher evidence for tests and developer diagnosis."""

    selected, _, _, ranked = choose_candidate(settings, path, results, search_title)
    eligible = [
        item
        for item in ranked
        if not any(reason.startswith("duration mismatch") for reason in item[2])
    ]
    ambiguous = bool(
        selected is None
        and eligible
        and eligible[0][0] >= MATCH_THRESHOLD
        and len(eligible) >= 2
        and eligible[0][0] - eligible[1][0] < AMBIGUITY_MARGIN
    )
    ambiguous_scores = {item[0] for item in eligible[:2]} if ambiguous else set()
    diagnostics: list[CandidateDiagnostic] = []
    for score, candidate, reasons in ranked:
        duration_incompatible = any(
            reason.startswith("duration mismatch") for reason in reasons
        )
        is_selected = candidate is selected
        if is_selected:
            rejection = None
        elif duration_incompatible:
            rejection = "known duration outside tolerance"
        elif score < MATCH_THRESHOLD:
            rejection = "below confidence threshold"
        elif ambiguous and score in ambiguous_scores:
            rejection = "ambiguous within safety margin"
        else:
            rejection = "lower-ranked candidate"
        diagnostics.append(
            CandidateDiagnostic(
                song_id=candidate.get("id"),
                name=str(candidate.get("name") or ""),
                score=score,
                eligible=not duration_incompatible,
                selected=is_selected,
                rejection=rejection,
                reasons=tuple(reasons),
            )
        )
    return tuple(diagnostics)

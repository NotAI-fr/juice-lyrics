from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, SYLT, USLT, Encoding
from mutagen.mp4 import MP4
from ..library.matching import local_duration, parse_length
from ..library.media import is_flac, is_m4a, is_tagged_container, read_tagged_metadata
from .sidecar import sidecar_lrc_path

DESCRIPTION = "Juice WRLD API"
LANGUAGE = "eng"
LRC_RE = re.compile(r"\[(?P<m>\d+):(?P<s>\d{2})(?:[.:](?P<f>\d{1,3}))?\]\s*(?P<t>.*)")


@dataclass(frozen=True, slots=True)
class LocalLyricLine:
    """One searchable local lyric line read from an existing supported source."""

    text: str
    timestamp_ms: int | None
    source: str


def parse_synced_lyrics(raw: str) -> list[tuple[str, int]]:
    entries = []
    for line in raw.splitlines():
        line = line.strip()
        if not line: continue
        m = LRC_RE.match(line)
        if not m: continue
        fraction = (m.group("f") or "0").ljust(3, "0")[:3]
        ts = int(m.group("m"))*60000 + int(m.group("s"))*1000 + int(fraction)
        text = m.group("t").strip()
        if text: entries.append((text, ts))
    entries.sort(key=lambda x: x[1])
    return list(dict.fromkeys(entries))


def _plain_lines(raw: str) -> list[str]:
    lines: list[str] = []
    for value in raw.splitlines():
        text = value.strip()
        if not text or LRC_RE.match(text) or re.match(r"^\[[A-Za-z][^]]*:.*\]$", text):
            continue
        lines.append(text)
    return lines


def read_local_lyrics(path: Path) -> tuple[LocalLyricLine, ...]:
    """Read lyrics from the same local containers and sidecar parser used by 999.

    Adjacent LRC is considered first so equivalent embedded text can be omitted
    while preserving the timestamped representation. The operation is read-only.
    """

    path = Path(path)
    sidecar_lines: list[LocalLyricLine] = []
    sidecar = sidecar_lrc_path(path)
    try:
        raw_lrc = sidecar.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError, UnicodeError):
        raw_lrc = ""
    if raw_lrc:
        sidecar_lines.extend(
            LocalLyricLine(text, timestamp, "lrc")
            for text, timestamp in parse_synced_lyrics(raw_lrc)
        )
        sidecar_lines.extend(
            LocalLyricLine(text, None, "lrc") for text in _plain_lines(raw_lrc)
        )

    embedded: list[LocalLyricLine] = []
    try:
        if is_flac(path):
            audio = FLAC(path)
            for key in ("lyrics", "unsyncedlyrics"):
                for value in audio.get(key, []):
                    embedded.extend(
                        LocalLyricLine(text.strip(), None, "embedded")
                        for text in str(value).splitlines() if text.strip()
                    )
        elif is_m4a(path):
            audio = MP4(path)
            for value in audio.get("\xa9lyr", []):
                embedded.extend(
                    LocalLyricLine(text.strip(), None, "embedded")
                    for text in str(value).splitlines() if text.strip()
                )
        else:
            tag = ID3(path)
            for frame in tag.getall("SYLT"):
                embedded.extend(
                    LocalLyricLine(str(text).strip(), int(timestamp), "embedded")
                    for text, timestamp in getattr(frame, "text", ())
                    if str(text).strip()
                )
            for frame in tag.getall("USLT"):
                embedded.extend(
                    LocalLyricLine(text.strip(), None, "embedded")
                    for text in str(getattr(frame, "text", "") or "").splitlines()
                    if text.strip()
                )
    except Exception:
        # A damaged/unreadable embedded source must not hide a readable
        # adjacent sidecar from the local search index.
        embedded = []

    # The search service applies its broader punctuation normalization. A
    # conservative local comparison is enough to suppress copies of sidecar
    # lines while retaining repeated chorus occurrences inside one source.
    sidecar_text = {" ".join(line.text.casefold().split()) for line in sidecar_lines}
    embedded = [
        line for line in embedded
        if " ".join(line.text.casefold().split()) not in sidecar_text
    ]
    return tuple(sidecar_lines + embedded)

def load_id3(path: Path) -> ID3:
    try: return ID3(path)
    except ID3NoHeaderError: return ID3()

def _remove_managed(tag: ID3) -> None:
    for kind in ("SYLT", "USLT"):
        for frame in list(tag.getall(kind)):
            if getattr(frame, "desc", "") == DESCRIPTION:
                try: del tag[frame.HashKey]
                except KeyError: pass

def _save(tag: ID3, path: Path) -> None:
    version = 3 if getattr(tag, "version", None) and tag.version[0] == 3 else 4
    tag.save(path, v2_version=version)

def _plain_lyric_text(synced: list[tuple[str, int]], plain: str) -> str:
    # FLAC and M4A have no interoperable SYLT equivalent. Preserve useful
    # plain text in their standard lyric field; timing remains in the sidecar.
    return plain.strip() or "\n".join(text for text, _ in synced).strip()


def embed_lyrics(path: Path, synced: list[tuple[str,int]], plain: str) -> str:
    if is_flac(path):
        text = _plain_lyric_text(synced, plain)
        if not text:
            raise ValueError("No lyrics available")
        audio = FLAC(path)
        audio["LYRICS"] = [text]
        audio.save()
        return "FLAC_LYRICS"
    if is_m4a(path):
        text = _plain_lyric_text(synced, plain)
        if not text:
            raise ValueError("No lyrics available")
        audio = MP4(path)
        if audio.tags is None:
            audio.add_tags()
        audio["\xa9lyr"] = [text]
        audio.save()
        return "M4A_LYRICS"
    tag = load_id3(path); _remove_managed(tag)
    if synced:
        tag.add(SYLT(encoding=Encoding.UTF8, lang=LANGUAGE, format=2, type=1, desc=DESCRIPTION, text=synced)); _save(tag, path); return "SYLT"
    if plain.strip():
        tag.add(USLT(encoding=Encoding.UTF8, lang=LANGUAGE, desc=DESCRIPTION, text=plain.strip())); _save(tag, path); return "USLT"
    raise ValueError("No lyrics available")

def verify_file(path: Path) -> tuple[bool,str]:
    try:
        if is_flac(path):
            audio = FLAC(path)
            lyrics = [
                str(value).strip()
                for key in ("lyrics", "unsyncedlyrics")
                for value in audio.get(key, [])
                if str(value).strip()
            ]
            if lyrics:
                return True, f"FLAC LYRICS ({sum(len(value) for value in lyrics)} characters)"
            return False, "no embedded FLAC lyrics"
        if is_m4a(path):
            audio = MP4(path)
            lyrics = [
                str(value).strip()
                for value in audio.get("\xa9lyr", [])
                if str(value).strip()
            ]
            if lyrics:
                return True, f"M4A LYRICS ({sum(len(value) for value in lyrics)} characters)"
            return False, "no embedded M4A lyrics"
        tag = ID3(path)
        sylt = [f for f in tag.getall("SYLT") if getattr(f,"desc","")==DESCRIPTION]
        if sylt:
            total=sum(len(f.text) for f in sylt)
            if not total: return False,"empty SYLT frame"
            for f in sylt:
                times=[x[1] for x in f.text]
                if times != sorted(times): return False,"SYLT timestamps are not chronological"
            return True,f"SYLT ({total} synced lines)"
        uslt=[f for f in tag.getall("USLT") if getattr(f,"desc","")==DESCRIPTION]
        if uslt:
            total=sum(len(getattr(f,"text","") or "") for f in uslt)
            if not total: return False,"empty USLT frame"
            return True,"USLT (ordinary lyrics)"
        return False,"no managed lyrics frame"
    except Exception as exc: return False,str(exc)

def read_mp3_metadata(path: Path, fallback: dict[str,Any]) -> dict[str,str]:
    tag=load_id3(path)
    def first(fid):
        frames=tag.getall(fid)
        if not frames:return ""
        text=getattr(frames[0],"text","")
        return str(text[0]) if isinstance(text,list) and text else str(text or "")
    artist=first("TPE1") or str(fallback.get("credited_artists") or "Juice WRLD")
    title=first("TIT2") or str(fallback.get("name") or path.stem)
    album=first("TALB") or str(fallback.get("album") or "")
    duration=local_duration(path) or parse_length(str(fallback.get("length") or "")) or 0.0
    cs=max(0,int(round(duration*100))); minutes,remainder=divmod(cs,6000); seconds,centiseconds=divmod(remainder,100)
    return {"artist":artist,"title":title,"album":album,"length":f"{minutes:02d}:{seconds:02d}.{centiseconds:02d}"}


def read_tagged_lrc_metadata(path: Path, fallback: dict[str, Any]) -> dict[str, str]:
    metadata = read_tagged_metadata(path)
    artist = metadata.artist or str(fallback.get("credited_artists") or "Juice WRLD")
    title = metadata.title or str(fallback.get("name") or path.stem)
    album = metadata.album or str(fallback.get("album") or "")
    duration = metadata.duration_seconds or parse_length(str(fallback.get("length") or "")) or 0.0
    centiseconds_total = max(0, int(round(duration * 100)))
    minutes, remainder = divmod(centiseconds_total, 6000)
    seconds, centiseconds = divmod(remainder, 100)
    return {
        "artist": artist,
        "title": title,
        "album": album,
        "length": f"{minutes:02d}:{seconds:02d}.{centiseconds:02d}",
    }
def write_lrc(
    path: Path,
    synced: list[tuple[str, int]],
    fallback: dict[str, Any],
) -> Path:
    """Atomically create or update synchronized lyrics beside ``path``."""

    if not synced: raise ValueError("No synchronized lyrics available")
    if is_tagged_container(path):
        meta = read_tagged_lrc_metadata(path, fallback)
    else:
        meta = read_mp3_metadata(path, fallback)
    out = sidecar_lrc_path(path)
    safe=lambda s:str(s).replace("]","}")
    lines=[f"[ar:{safe(meta['artist'])}]",f"[ti:{safe(meta['title'])}]"]
    if meta["album"]: lines.append(f"[al:{safe(meta['album'])}]")
    lines += [f"[length:{meta['length']}]",""]
    for text,ms in synced:
        cs=max(0,int(round(ms/10))); m,r=divmod(cs,6000); s,cs2=divmod(r,100); lines.append(f"[{m:02d}:{s:02d}.{cs2:02d}] {text}")
    content = "\n".join(lines) + "\n"
    try:
        if out.read_text(encoding="utf-8") == content:
            return out
    except FileNotFoundError:
        pass

    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=out.parent,
            prefix=f".{out.name}.",
            suffix=".tmp",
        )
        temporary = Path(temporary_name)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(out)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return out

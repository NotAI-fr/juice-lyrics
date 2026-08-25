from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from mutagen.id3 import ID3, ID3NoHeaderError, SYLT, USLT, Encoding
from ..library.matching import local_duration, parse_length

DESCRIPTION = "Juice WRLD API"
LANGUAGE = "eng"
LRC_RE = re.compile(r"\[(?P<m>\d+):(?P<s>\d{2})(?:[.:](?P<f>\d{1,3}))?\]\s*(?P<t>.*)")

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

def embed_lyrics(path: Path, synced: list[tuple[str,int]], plain: str) -> str:
    tag = load_id3(path); _remove_managed(tag)
    if synced:
        tag.add(SYLT(encoding=Encoding.UTF8, lang=LANGUAGE, format=2, type=1, desc=DESCRIPTION, text=synced)); _save(tag, path); return "SYLT"
    if plain.strip():
        tag.add(USLT(encoding=Encoding.UTF8, lang=LANGUAGE, desc=DESCRIPTION, text=plain.strip())); _save(tag, path); return "USLT"
    raise ValueError("No lyrics available")

def verify_file(path: Path) -> tuple[bool,str]:
    try:
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

def write_lrc(path: Path, synced: list[tuple[str,int]], fallback: dict[str,Any], out_dir: Path) -> Path:
    if not synced: raise ValueError("No synchronized lyrics available")
    meta=read_mp3_metadata(path,fallback); out_dir.mkdir(parents=True,exist_ok=True); out=out_dir/f"{path.stem}.lrc"
    safe=lambda s:str(s).replace("]","}")
    lines=[f"[ar:{safe(meta['artist'])}]",f"[ti:{safe(meta['title'])}]"]
    if meta["album"]: lines.append(f"[al:{safe(meta['album'])}]")
    lines += [f"[length:{meta['length']}]",""]
    for text,ms in synced:
        cs=max(0,int(round(ms/10))); m,r=divmod(cs,6000); s,cs2=divmod(r,100); lines.append(f"[{m:02d}:{s:02d}.{cs2:02d}] {text}")
    tmp=out.with_suffix(".lrc.tmp"); tmp.write_text("\n".join(lines)+"\n",encoding="utf-8"); tmp.replace(out); return out

from __future__ import annotations
import hashlib, json
from pathlib import Path
from typing import Any
from .config.settings import STATE_FILE, DATA_DIR
from .backup.manager import ensure_data_dirs, now_iso

def load_state()->dict[str,Any]:
    ensure_data_dirs()
    if not STATE_FILE.exists(): return {"files":{},"updated":None}
    try:
        v=json.loads(STATE_FILE.read_text(encoding="utf-8")); return v if isinstance(v,dict) else {"files":{},"updated":None}
    except Exception: return {"files":{},"updated":None}

def save_state(state:dict[str,Any])->None:
    ensure_data_dirs(); state["updated"]=now_iso(); tmp=STATE_FILE.with_suffix(".tmp"); tmp.write_text(json.dumps(state,indent=2,ensure_ascii=False),encoding="utf-8"); tmp.replace(STATE_FILE)

def sha256_file(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()

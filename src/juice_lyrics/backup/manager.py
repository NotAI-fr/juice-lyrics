from __future__ import annotations
import json, shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from ..config.settings import BACKUP_DIR, DATA_DIR

def ensure_data_dirs():
    DATA_DIR.mkdir(parents=True,exist_ok=True); BACKUP_DIR.mkdir(parents=True,exist_ok=True)

def now_iso(): return datetime.now(timezone.utc).isoformat()

def make_backup_root(): ensure_data_dirs(); root=BACKUP_DIR/datetime.now().strftime("%Y%m%d-%H%M%S"); root.mkdir(parents=True,exist_ok=True); return root

def backup_file(path:Path,root:Path,base:Path)->Path:
    dest=root/path.relative_to(base); dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(path,dest); return dest

def write_manifest(root:Path, entries:list[dict[str,Any]]):
    (root/"manifest.json").write_text(json.dumps({"created":now_iso(),"files":entries},indent=2,ensure_ascii=False),encoding="utf-8")

def restore_backup(root:Path, base:Path)->int:
    restored=0
    for src in root.rglob("*.mp3"):
        dst=base/src.relative_to(root); dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst); restored+=1
    return restored

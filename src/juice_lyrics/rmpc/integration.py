from __future__ import annotations
import re, shutil, subprocess
from datetime import datetime
from pathlib import Path
from ..config.settings import DEFAULT_RMPC_CONFIG, DEFAULT_RMPC_LYRICS_DIR
from ..lyrics.engine import write_lrc

def rmpc_running()->bool:
    try: return subprocess.run(["rmpc","remote","query","active-tab"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,check=False).returncode==0
    except (FileNotFoundError,subprocess.SubprocessError): return False

def notify_rmpc_index(paths:list[Path])->int:
    if not paths or not rmpc_running(): return 0
    count=0
    for p in paths:
        try:
            r=subprocess.run(["rmpc","remote","indexlrc","--path",str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=3,check=False)
        except (FileNotFoundError,subprocess.SubprocessError): break
        if r.returncode==0: count+=1
    return count

def patch_rmpc_config(config_path:Path,lyrics_dir:Path)->Path:
    if not config_path.exists(): raise RuntimeError(f"rmpc config not found: {config_path}")
    original=config_path.read_text(encoding="utf-8")
    backup=config_path.with_name(f"{config_path.name}.juice-lyrics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(config_path,backup)
    escaped=str(lyrics_dir).replace("\\","\\\\").replace('"','\\"')
    replacement=f'    lyrics_dir: Some("{escaped}"),'
    if re.search(r"(?m)^\s*lyrics_dir\s*:",original): updated=re.sub(r"(?m)^\s*lyrics_dir\s*:\s*[^,]+,",replacement,original,count=1)
    else: updated=original.replace("(","(\n"+replacement,1)
    for key in ("enable_lyrics_index","enable_lyrics_hot_reload"):
        line=f"    {key}: true,"
        if re.search(rf"(?m)^\s*{re.escape(key)}\s*:",updated): updated=re.sub(rf"(?m)^\s*{re.escape(key)}\s*:\s*[^,]+,",line,updated,count=1)
        else: updated=updated.replace(replacement,replacement+"\n"+line,1)
    tmp=config_path.with_suffix(config_path.suffix+".tmp"); tmp.write_text(updated,encoding="utf-8"); tmp.replace(config_path); return backup

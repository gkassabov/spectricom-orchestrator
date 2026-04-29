#!/usr/bin/env python3
"""
DRIVE BRIDGE v2 — Pulls new briefs from Drive/Yorsie/Briefs/ to local.
v2: Safety-hardened with rate limiter integration (D-184).

  python3 drive-bridge.py pull         ← one-time pull
  python3 drive-bridge.py watch        ← daemon: pull only (auto-fire OFF)
  python3 drive-bridge.py start        ← background daemon
  python3 drive-bridge.py stop
  python3 drive-bridge.py status
"""
import sys,os,time,json,io,subprocess
from pathlib import Path
from datetime import datetime

# Safety imports
sys.path.insert(0, str(Path(__file__).parent))
import rate_limiter

ORCH=Path.home()/"spectricom-orchestrator"
TOKEN=ORCH/"drive-token.json"
from repo_config import load_default_repo_config as _ldrc
_default_name, _default_cfg = _ldrc()
LOCAL_BRIEFS=Path(_default_cfg["project_dir"]).expanduser()/_default_cfg.get("briefs_subdir","briefs")
PID_FILE=ORCH/"bridge.pid"
LOG_FILE=ORCH/"logs"/"bridge.log"
HASH_FILE=ORCH/"bridge-hashes.json"
SCOPES=["https://www.googleapis.com/auth/drive"]
POLL=15

# ═══════════════════════════════════════════════════════
# SAFETY (D-184): AUTO_FIRE must be explicitly True AND
# rate limiter must allow execution. Double gate.
# ═══════════════════════════════════════════════════════
AUTO_FIRE=False  # DO NOT CHANGE without approval gate in orchestrator

def log(msg):
    ts=datetime.now().strftime("%H:%M:%S")
    line=f"{ts} {msg}"
    print(line,flush=True)
    LOG_FILE.parent.mkdir(parents=True,exist_ok=True)
    with open(LOG_FILE,"a") as f: f.write(line+"\n")

def load_hashes():
    if HASH_FILE.exists(): return json.loads(HASH_FILE.read_text())
    return {}
def save_hashes(h): HASH_FILE.write_text(json.dumps(h))

def get_svc():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds=Credentials.from_authorized_user_file(str(TOKEN),SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request()); TOKEN.write_text(creds.to_json())
    return build("drive","v3",credentials=creds)

def find(s,name,pid=None):
    q=f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if pid: q+=f" and '{pid}' in parents"
    r=s.files().list(q=q,fields="files(id)",pageSize=5).execute().get("files",[])
    return r[0]["id"] if r else None

def pull_briefs(s):
    """Pull new .md files from Drive/Yorsie/Briefs/ to local briefs dir."""
    root=find(s,"Spectricom")
    if not root: log("❌ No Spectricom folder"); return []
    yorsie=find(s,"Yorsie",root)
    if not yorsie: log("❌ No Yorsie folder"); return []
    briefs_folder=find(s,"Briefs",yorsie)
    if not briefs_folder: log("❌ No Briefs folder"); return []

    from googleapiclient.http import MediaIoBaseDownload
    files=s.files().list(
        q=f"'{briefs_folder}' in parents and trashed=false and name contains '.md'",
        fields="files(id,name,modifiedTime,md5Checksum)",
        orderBy="modifiedTime desc", pageSize=20
    ).execute().get("files",[])

    hashes=load_hashes()
    new_files=[]
    LOCAL_BRIEFS.mkdir(parents=True,exist_ok=True)

    for f in files:
        key=f"{f['name']}:{f.get('md5Checksum','')}"
        if key in hashes: continue
        # Download
        local=LOCAL_BRIEFS/f["name"]
        req=s.files().get_media(fileId=f["id"])
        fh=io.BytesIO()
        dl=MediaIoBaseDownload(fh,req)
        done=False
        while not done: _,done=dl.next_chunk()
        local.write_bytes(fh.getvalue())
        hashes[key]=datetime.now().isoformat()
        log(f"📥 {f['name']} ← Drive/Yorsie/Briefs/")
        new_files.append(local)

    save_hashes(hashes)
    return new_files

def is_already_done(brief_name):
    """Check if this brief was already completed by orchestrator."""
    sf = Path.home()/"spectricom-orchestrator"/"state.json"
    if not sf.exists(): return False
    state = json.loads(sf.read_text())
    done_names = {b.get("batch_file","") for b in state.get("completed",[])}
    done_names |= {b.get("batch_file","") for b in state.get("failed",[])}
    return brief_name in done_names

def fire_orchestrator(brief_path):
    """Fire the orchestrator on a new brief. SAFETY: double-gated."""
    # ═══ SAFETY GATE 1: AUTO_FIRE flag (D-184) ═══
    if not AUTO_FIRE:
        log(f"⛔ AUTO_FIRE=False — will NOT fire {brief_path.name}")
        log(f"   Run manually: python3 orchestrator.py run {brief_path}")
        return None

    # ═══ SAFETY GATE 2: Rate limiter ═══
    ok, msg = rate_limiter.pre_flight(1)  # conservative estimate
    if not ok:
        log(f"⛔ Rate limit blocked: {msg}")
        return None
    log(f"   Rate: {msg}")

    # Fire with --approve since bridge already represents an approval flow
    cmd=f"cd {ORCH} && python3 orchestrator.py run {brief_path} --approve"
    log(f"🚀 Auto-firing: {brief_path.name}")
    try:
        proc=subprocess.Popen(cmd,shell=True,executable="/bin/bash",
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        log(f"   PID: {proc.pid}")
        return proc
    except Exception as e:
        log(f"❌ Fire failed: {e}")
        return None

def cmd_pull():
    s=get_svc()
    files=pull_briefs(s)
    if not files: print("No new briefs in Drive.")
    else: print(f"✅ Pulled {len(files)} new briefs")

def run_daemon():
    log("═══════════════════════════════════════")
    log(f"DRIVE BRIDGE v2 — {'⚠️  AUTO-FIRE ON' if AUTO_FIRE else '🔒 PULL ONLY (D-184)'}")
    log(f"Drive/Yorsie/Briefs/ → {LOCAL_BRIEFS}")
    if AUTO_FIRE:
        log("⚠️  AUTO_FIRE is ON — Toni will execute without manual approval!")
        log("   Rate limits enforced. Caps:")
        caps = rate_limiter.load_caps()
        log(f"   {caps['daily_batches']} batches/day, {caps['daily_briefs']} briefs/day")
    log("═══════════════════════════════════════")
    s=get_svc()
    # Initial pull
    new=pull_briefs(s)
    if AUTO_FIRE:
        for f in new:
            if not is_already_done(f.name):
                fire_orchestrator(f)
            else:
                log(f"⏭️  {f.name} already done — skipping")
    log("Watching Drive for new briefs...")
    try:
        while True:
            time.sleep(POLL)
            try:
                new=pull_briefs(s)
                if AUTO_FIRE:
                    for f in new:
                        if not is_already_done(f.name):
                            fire_orchestrator(f)
                        else:
                            log(f"⏭️  {f.name} already done — skipping")
            except Exception as e:
                log(f"⚠️ {e}")
                try: s=get_svc()
                except: pass
    except KeyboardInterrupt:
        log("Bridge stopped.")

def cmd_start():
    if PID_FILE.exists():
        pid=int(PID_FILE.read_text().strip())
        try: os.kill(pid,0); print(f"Already running (PID {pid})"); return
        except ProcessLookupError: pass
    pid=os.fork()
    if pid>0:
        PID_FILE.write_text(str(pid))
        print(f"✅ Drive bridge started (PID {pid})")
        print(f"   Mode: {'⚠️  AUTO-FIRE' if AUTO_FIRE else '🔒 PULL ONLY'}")
        print(f"   Logs: tail -f {LOG_FILE}"); return
    os.setsid()
    sys.stdout=open(os.devnull,'w'); sys.stderr=open(os.devnull,'w')
    run_daemon()

def cmd_stop():
    if not PID_FILE.exists(): print("Not running"); return
    pid=int(PID_FILE.read_text().strip())
    try: os.kill(pid,15); PID_FILE.unlink(); print(f"✅ Stopped (PID {pid})")
    except ProcessLookupError: PID_FILE.unlink(); print("Was not running")

def cmd_status():
    if not PID_FILE.exists(): print("❌ Bridge not running"); return
    pid=int(PID_FILE.read_text().strip())
    try:
        os.kill(pid,0)
        print(f"✅ Bridge running (PID {pid})")
        print(f"   Mode: {'⚠️  AUTO-FIRE' if AUTO_FIRE else '🔒 PULL ONLY'}")
        if LOG_FILE.exists():
            lines=LOG_FILE.read_text().strip().split("\n")
            for l in lines[-5:]: print(f"  {l}")
    except ProcessLookupError: print("❌ Dead"); PID_FILE.unlink()

if __name__=="__main__":
    cmd=sys.argv[1] if len(sys.argv)>1 else ""
    if cmd=="pull": cmd_pull()
    elif cmd=="start": cmd_start()
    elif cmd=="stop": cmd_stop()
    elif cmd=="status": cmd_status()
    elif cmd=="watch": run_daemon()
    else: print(__doc__)

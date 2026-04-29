#!/usr/bin/env python3
"""
SPECTRICOM AUTO-SYNC DAEMON v5
Push local → Drive. Pull from Drive on demand (Gemma manifests).
Auto-archive old local versions. Handles Windows (1)(2) suffixes.

  python3 drive-watcher.py start
  python3 drive-watcher.py stop
  python3 drive-watcher.py status
  python3 drive-watcher.py run       ← foreground for testing
"""
import sys,os,time,re,json,hashlib,io
from pathlib import Path
from datetime import datetime
from collections import defaultdict

ORCH=Path.home()/"spectricom-orchestrator"
DL=Path("/mnt/c/Users/gkass/Downloads")
DS=Path("/mnt/c/Users/gkass/Documents/Spectricom")
OLD_DIR=DS/"Old"
REQUESTS_DIR=DS/"_requests"
WATCH_DIRS=[DL,DS]
PID_FILE=ORCH/"drive-watcher.pid"
HASH_FILE=ORCH/"drive-watcher-hashes.json"
LOG_FILE=ORCH/"logs"/"drive-watcher.log"
TOKEN=ORCH/"drive-token.json"
POLL=10
SCOPES=["https://www.googleapis.com/auth/drive"]

ROUTES=[
    (r"Spectricom_Document_Registry","Registry"),
    (r"Spectricom_Parallel_Dev_Master","Plans"),
    (r"Spectricom_Product_Roadmap","Plans"),
    (r"Spectricom_Clinical_","Clinical"),
    (r"spectricom-orchestrator-arch","Plans"),
    (r"Spectricom_Logs","Logs"),
    (r"Gemma_System_Prompt","Prompts"),
    (r"spectricom-context-slim","Context"),
    (r"yorsie-design-system|yorsie-your-intel|yorsie-bug-registry|yorsie-compact-feature","Yorsie/Design"),
    (r"toni-batch","Yorsie/Briefs"),
    (r"yorsie-synth|yorsie-food-synth","Yorsie/Synth"),
    (r"SPIKE-","Spikes"),
]
GLOBS=["Spectricom_*.md","spectricom-*.md","Gemma_System_Prompt*.md",
       "yorsie-*.md","toni-batch-*.md","SPIKE-*.md"]

# ═══════════════════════════════════════════════════════
# HELPERS — shared
# ═══════════════════════════════════════════════════════

def route(fn):
    for p,f in ROUTES:
        if re.search(p,fn,re.I): return f
    return ""

def reverse_route(fn):
    """Given a filename, return the Drive folder path using ROUTES table."""
    for p,f in ROUTES:
        if re.search(p,fn,re.I): return f
    return None

def clean_name(fn):
    """Strip Windows (1)(2)(3) suffixes → clean filename for Drive."""
    return re.sub(r'\s*\(\d+\)(?=\.)', '', fn)

def is_old(fn):
    """Skip files explicitly marked as old."""
    return '-old' in fn.lower()

def parse_version(fn):
    """Extract version tuple for sorting. Higher = newer."""
    m = re.search(r'v(\d+)[-_](\d+)', fn)
    if m: return (int(m.group(1)), int(m.group(2)))
    m = re.search(r'v(\d+)', fn)
    if m: return (int(m.group(1)), 0)
    return (0, 0)

def extract_base_name(fn):
    """Extract base name for grouping versions.
    Spectricom_Logs_v2-35.md → Spectricom_Logs
    spectricom-context-slim-v4-26-yorsie.md → spectricom-context-slim-yorsie
    Gemma_System_Prompt_v5-4.md → Gemma_System_Prompt
    yorsie-bug-registry-v1-10.md → yorsie-bug-registry
    """
    name = re.sub(r'\.md$', '', fn)
    m = re.match(r'^(.+?)[-_]v\d+[-_]\d+[-_]?(.*)$', name)
    if m:
        before, after = m.group(1), m.group(2)
        return f"{before}-{after}" if after else before
    return name

def pick_latest(files):
    """Group files by clean name, pick newest (by mtime) from each group."""
    groups = defaultdict(list)
    for f in files:
        if is_old(f.name): continue
        key = clean_name(f.name)
        groups[key].append(f)
    latest = {}
    for key, group in groups.items():
        newest = max(group, key=lambda f: f.stat().st_mtime)
        latest[key] = newest
    return latest

def fhash(p): return hashlib.md5(p.read_bytes()).hexdigest()
def load_hashes():
    if HASH_FILE.exists(): return json.loads(HASH_FILE.read_text())
    return {}
def save_hashes(h): HASH_FILE.write_text(json.dumps(h))

def log(msg):
    ts=datetime.now().strftime("%H:%M:%S")
    line=f"{ts} {msg}"
    print(line,flush=True)
    LOG_FILE.parent.mkdir(parents=True,exist_ok=True)
    with open(LOG_FILE,"a") as f: f.write(line+"\n")

# ═══════════════════════════════════════════════════════
# DRIVE API
# ═══════════════════════════════════════════════════════

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

def resolve(s,path,rid):
    cid=rid
    for p in path.split("/"):
        fid=find(s,p,cid)
        if not fid:
            m={"name":p,"mimeType":"application/vnd.google-apps.folder","parents":[cid]}
            fid=s.files().create(body=m,fields="id").execute()["id"]
        cid=fid
    return cid

def navigate(s, folder_path, root_id):
    """Navigate a slash-separated path without creating missing folders.
    Returns folder_id or None if any segment not found."""
    cid = root_id
    for seg in folder_path.split("/"):
        fid = find(s, seg, cid)
        if not fid: return None
        cid = fid
    return cid

def list_drive_folder(s, folder_id):
    """List all files (not folders) in a Drive folder."""
    return s.files().list(
        q=f"'{folder_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
        fields="files(id,name)",
        pageSize=50
    ).execute().get("files", [])

def upload_to_drive(s,local_path,folder_id,drive_name):
    """Upload file to Drive. Uses drive_name (clean) not local filename."""
    from googleapiclient.http import MediaFileUpload
    q=f"name='{drive_name}' and '{folder_id}' in parents and trashed=false"
    ex=s.files().list(q=q,fields="files(id)").execute().get("files",[])
    media=MediaFileUpload(str(local_path),resumable=True)
    if ex:
        s.files().update(fileId=ex[0]["id"],media_body=media).execute()
        return "updated"
    else:
        s.files().create(body={"name":drive_name,"parents":[folder_id]},
            media_body=media,fields="id").execute()
        return "created"

def download_from_drive(s, file_id, dest_path):
    """Download a single file from Drive to local path."""
    from googleapiclient.http import MediaIoBaseDownload
    req = s.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    dl = MediaIoBaseDownload(fh, req)
    done = False
    while not done: _, done = dl.next_chunk()
    dest_path.write_bytes(fh.getvalue())

# ═══════════════════════════════════════════════════════
# PUSH — local → Drive (existing v4 behavior)
# ═══════════════════════════════════════════════════════

def archive_drive_old_versions(s, root_id, folder_id, drive_name):
    """Move older versions of same doc to Archive/ on Drive."""
    base = re.sub(r'[-_]v?\d+[-_.]\d+[-_.]*\d*\.md$', '', drive_name)
    if base == drive_name.replace('.md',''): return
    q = f"name contains '{base}' and '{folder_id}' in parents and trashed=false"
    files = s.files().list(q=q, fields="files(id,name)").execute().get("files",[])
    archive_id = None
    for f in files:
        if f["name"] == drive_name: continue
        if not f["name"].startswith(base): continue
        if not archive_id:
            archive_id = resolve(s, "Archive", root_id)
        s.files().update(fileId=f["id"],
            addParents=archive_id, removeParents=folder_id).execute()
        log(f"  📦 Drive archived: {f['name']}")

def scan_and_push(s,root_id,hashes):
    changed=False
    all_files=[]
    for wd in WATCH_DIRS:
        if not wd.exists(): continue
        for pat in GLOBS:
            all_files.extend(wd.glob(pat))
    latest=pick_latest(all_files)
    for drive_name, local_file in latest.items():
        d=route(drive_name)
        if not d: continue
        h=fhash(local_file)
        key=f"{drive_name}:{h}"
        if key in hashes: continue
        try:
            fid=resolve(s,d,root_id)
            a=upload_to_drive(s,local_file,fid,drive_name)
            src=local_file.name
            label=f" (from {src})" if src!=drive_name else ""
            log(f"✅ {drive_name} → {d}/ ({a}){label}")
            archive_drive_old_versions(s, root_id, fid, drive_name)
            hashes[key]=datetime.now().isoformat()
            changed=True
        except Exception as e:
            log(f"❌ {drive_name}: {e}")
    return changed

# ═══════════════════════════════════════════════════════
# LOCAL ARCHIVE — keep DS clean (one version per doc)
# ═══════════════════════════════════════════════════════

def archive_local_old_versions():
    """In Documents\\Spectricom, keep only the latest version of each doc.
    Move older versions to Old/. Only touches .md files in the root of DS."""
    if not DS.exists(): return
    files = [f for f in DS.iterdir() if f.is_file() and f.suffix == '.md']
    if not files: return

    groups = defaultdict(list)
    for f in files:
        base = extract_base_name(f.name)
        groups[base].append(f)

    for base, group in groups.items():
        if len(group) <= 1: continue
        # Sort by version descending — keep index 0 (newest)
        group.sort(key=lambda f: parse_version(f.name), reverse=True)
        OLD_DIR.mkdir(parents=True, exist_ok=True)
        for old_file in group[1:]:
            dest = OLD_DIR / old_file.name
            # If same name already in Old/, overwrite
            if dest.exists(): dest.unlink()
            old_file.rename(dest)
            log(f"📦 Local archived: {old_file.name} → Old/")

# ═══════════════════════════════════════════════════════
# PULL — Drive → local on demand (Gemma manifest requests)
# ═══════════════════════════════════════════════════════

def check_pull_requests(s, root_id):
    """Check _requests/ for manifest JSON files and fulfill them.

    Manifest format (written by Gemma via filesystem MCP):
    {
        "needed": ["spectricom-context-slim-v4-26-yorsie.md", ...],
        "requested_at": "2026-04-09T14:30:00"
    }

    For each file in needed[]:
    - If already in DS → skip (already_local)
    - Reverse-route filename → Drive folder
    - Try exact match first, fall back to latest version with same base name
    - Download to DS

    Writes result to _requests/<name>.result.json, deletes original request.
    """
    if not REQUESTS_DIR.exists(): return
    manifests = list(REQUESTS_DIR.glob("*.json"))
    # Filter out result files
    manifests = [m for m in manifests if not m.name.endswith(".result.json")]
    if not manifests: return

    for req_file in manifests:
        try:
            req = json.loads(req_file.read_text())
            needed = req.get("needed", [])
            if not needed:
                req_file.unlink()
                continue

            pulled = []
            already_local = []
            not_found = []

            for filename in needed:
                # 1. Check if already exists locally in DS
                local_path = DS / filename
                if local_path.exists():
                    already_local.append(filename)
                    continue

                # 2. Also check if a NEWER version exists locally
                req_base = extract_base_name(filename)
                local_matches = [f for f in DS.iterdir()
                                 if f.is_file() and f.suffix == '.md'
                                 and extract_base_name(f.name) == req_base
                                 and parse_version(f.name) >= parse_version(filename)]
                if local_matches:
                    already_local.append(local_matches[0].name)
                    continue

                # 3. Reverse-route to find which Drive folder to look in
                drive_folder = reverse_route(filename)
                if not drive_folder:
                    not_found.append(filename)
                    log(f"⚠️ PULL: No route for {filename}")
                    continue

                # 4. Navigate to Drive folder (don't create if missing)
                folder_id = navigate(s, drive_folder, root_id)
                if not folder_id:
                    not_found.append(filename)
                    log(f"⚠️ PULL: Drive folder not found: {drive_folder}")
                    continue

                # 5. Search for the file on Drive
                all_files = list_drive_folder(s, folder_id)

                # Try exact match first
                exact = [f for f in all_files if f["name"] == filename]
                if exact:
                    target = exact[0]
                else:
                    # Fall back: latest version with same base name
                    matches = [f for f in all_files
                               if extract_base_name(f["name"]) == req_base]
                    if matches:
                        target = max(matches, key=lambda f: parse_version(f["name"]))
                    else:
                        not_found.append(filename)
                        log(f"⚠️ PULL: Not found on Drive: {filename} (searched {drive_folder}/)")
                        continue

                # 6. Download to DS
                dest = DS / target["name"]
                download_from_drive(s, target["id"], dest)
                pulled.append(target["name"])
                log(f"📥 PULL: {target['name']} ← Drive/{drive_folder}/")

            # 7. Write result file
            result_file = REQUESTS_DIR / req_file.name.replace(".json", ".result.json")
            result = {
                "pulled": pulled,
                "already_local": already_local,
                "not_found": not_found,
                "completed_at": datetime.now().isoformat()
            }
            result_file.write_text(json.dumps(result, indent=2))

            # 8. Remove request file
            req_file.unlink()

            total = len(pulled) + len(already_local) + len(not_found)
            log(f"✅ PULL manifest done: {len(pulled)} pulled, "
                f"{len(already_local)} already local, {len(not_found)} not found "
                f"(of {total} requested)")

        except Exception as e:
            log(f"❌ Pull request failed ({req_file.name}): {e}")

# ═══════════════════════════════════════════════════════
# DAEMON
# ═══════════════════════════════════════════════════════

def run_daemon():
    log("═══════════════════════════════════════")
    log("DRIVE WATCHER v5 — push + pull + archive")
    log(f"Push from: {DL}")
    log(f"Push from: {DS}")
    log(f"Pull to:   {DS}")
    log(f"Requests:  {REQUESTS_DIR}")
    log(f"Archive:   {OLD_DIR}")
    log("═══════════════════════════════════════")
    s=get_svc()
    root_id=find(s,"Spectricom")
    if not root_id: log("❌ Spectricom folder not found"); sys.exit(1)
    log("✅ Connected to Spectricom/")
    hashes=load_hashes()
    # Initial pass
    if scan_and_push(s,root_id,hashes): save_hashes(hashes)
    archive_local_old_versions()
    check_pull_requests(s, root_id)
    log("Watching for changes...")
    try:
        while True:
            time.sleep(POLL)
            try:
                if scan_and_push(s,root_id,hashes): save_hashes(hashes)
                archive_local_old_versions()
                check_pull_requests(s, root_id)
            except Exception as e:
                log(f"⚠️ {e}")
                try: s=get_svc()
                except: pass
    except KeyboardInterrupt:
        log("Stopped.")

# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

def cmd_start():
    if PID_FILE.exists():
        pid=int(PID_FILE.read_text().strip())
        try: os.kill(pid,0); print(f"Already running (PID {pid})"); return
        except ProcessLookupError: pass
    pid=os.fork()
    if pid>0:
        PID_FILE.write_text(str(pid))
        print(f"✅ Drive watcher v5 started (PID {pid})")
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
    if not PID_FILE.exists(): print("❌ Not running"); return
    pid=int(PID_FILE.read_text().strip())
    try:
        os.kill(pid,0); print(f"✅ Running (PID {pid})")
        if LOG_FILE.exists():
            lines=LOG_FILE.read_text().strip().split("\n")
            for l in lines[-5:]: print(f"  {l}")
    except ProcessLookupError: print("❌ Dead"); PID_FILE.unlink()

if __name__=="__main__":
    cmd=sys.argv[1] if len(sys.argv)>1 else ""
    if cmd=="start": cmd_start()
    elif cmd=="stop": cmd_stop()
    elif cmd=="status": cmd_status()
    elif cmd=="run": run_daemon()
    else: print(__doc__)

#!/usr/bin/env python3
"""
SPECTRICOM DRIVE SYNC
  python3 drive-sync.py auth
  python3 drive-sync.py push
  python3 drive-sync.py pull
  python3 drive-sync.py list
  python3 drive-sync.py upload <file>
"""
import os,sys,re,json,io
from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload,MediaIoBaseDownload
ORCH=Path.home()/"spectricom-orchestrator"
TOKEN=ORCH/"drive-token.json"
CREDS=ORCH/"drive-credentials.json"
DL=Path("/mnt/c/Users/gkass/Downloads")
from repo_config import load_default_repo_config as _ldrc
_default_name, _default_cfg = _ldrc()
BRIEFS=Path(_default_cfg["project_dir"]).expanduser()/_default_cfg.get("briefs_subdir","briefs")
PORT=8090
SCOPES=["https://www.googleapis.com/auth/drive"]
ROUTES=[
    (r"Spectricom_Document_Registry","Registry"),
    (r"Spectricom_Parallel_Dev_Master","Plans"),
    (r"spectricom-orchestrator-arch","Plans"),
    (r"Spectricom_Logs","Logs"),
    (r"Gemma_System_Prompt","Prompts"),
    (r"spectricom-context-slim","Context"),
    (r"yorsie-design-system|yorsie-your-intel|yorsie-bug-registry|yorsie-compact-feature","Yorsie/Design"),
    (r"toni-batch","Yorsie/Briefs"),
    (r"yorsie-synth|yorsie-food-synth","Yorsie/Synth"),
    (r"SPIKE-","Spikes"),
]
def route(fn):
    for p,f in ROUTES:
        if re.search(p,fn,re.I): return f
    return ""
def get_creds():
    creds=None
    if TOKEN.exists(): creds=Credentials.from_authorized_user_file(str(TOKEN),SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDS.exists():
                print(f"❌ Missing: {CREDS}"); sys.exit(1)
            flow=InstalledAppFlow.from_client_secrets_file(str(CREDS),SCOPES)
            creds=flow.run_local_server(port=PORT,open_browser=False,
                success_message="✅ Authorized! Close this tab.")
        TOKEN.write_text(creds.to_json())
    return creds
def svc(): return build("drive","v3",credentials=get_creds())
def find(s,name,pid=None):
    q=f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if pid: q+=f" and '{pid}' in parents"
    r=s.files().list(q=q,fields="files(id)",pageSize=5).execute().get("files",[])
    return r[0]["id"] if r else None
def root(s):
    r=find(s,"Spectricom")
    if not r: print("❌ Spectricom folder not found"); sys.exit(1)
    return r
def resolve(s,path,rid):
    cid=rid
    for p in path.split("/"):
        fid=find(s,p,cid)
        if not fid:
            m={"name":p,"mimeType":"application/vnd.google-apps.folder","parents":[cid]}
            fid=s.files().create(body=m,fields="id").execute()["id"]
        cid=fid
    return cid
def upload(s,fp,fid):
    fn=fp.name
    q=f"name='{fn}' and '{fid}' in parents and trashed=false"
    ex=s.files().list(q=q,fields="files(id)").execute().get("files",[])
    media=MediaFileUpload(str(fp),resumable=True)
    if ex:
        s.files().update(fileId=ex[0]["id"],media_body=media).execute(); return "updated"
    else:
        s.files().create(body={"name":fn,"parents":[fid]},media_body=media,fields="id").execute(); return "created"
def download(s,fid,lp):
    req=s.files().get_media(fileId=fid)
    fh=io.BytesIO()
    dl=MediaIoBaseDownload(fh,req)
    done=False
    while not done: _,done=dl.next_chunk()
    lp.write_bytes(fh.getvalue())
def lsfolder(s,fid):
    return s.files().list(q=f"'{fid}' in parents and trashed=false",
        fields="files(id,name,mimeType,modifiedTime,size)",orderBy="name",pageSize=100).execute().get("files",[])
def cmd_auth():
    s=svc(); r=root(s)
    print(f"✅ Connected. Spectricom/")
    for f in lsfolder(s,r):
        i="📁" if "folder" in f["mimeType"] else "📄"
        print(f"  {i} {f['name']}")
def cmd_push():
    s=svc(); r=root(s); c=0; seen=set()
    print("Pushing Downloads → Drive...\n")
    for pat in ["Spectricom_*.md","spectricom-*.md","Gemma_System_Prompt*.md","yorsie-*.md","toni-batch-*.md","SPIKE-*.md"]:
        for f in DL.glob(pat):
            if f.name in seen: continue
            seen.add(f.name)
            d=route(f.name)
            if not d: continue
            fid=resolve(s,d,r); a=upload(s,f,fid)
            print(f"  ✅ {f.name} → {d}/ ({a})"); c+=1
    print(f"\n✅ {c} files pushed")
def cmd_pull():
    s=svc(); r=root(s); c=0
    print("Pulling Drive → Downloads...\n")
    for dn in ["Registry","Plans","Logs","Prompts","Context"]:
        fid=find(s,dn,r)
        if not fid: continue
        for f in lsfolder(s,fid):
            if "folder" in f["mimeType"]: continue
            download(s,f["id"],DL/f["name"])
            print(f"  ✅ {f['name']} ← {dn}/"); c+=1
    print(f"\n✅ {c} files pulled")
def cmd_list():
    s=svc(); r=root(s)
    print("Spectricom/ Drive:\n")
    def show(fid,ind=0):
        for f in lsfolder(s,fid):
            p="  "*ind
            if "folder" in f["mimeType"]:
                print(f"{p}📁 {f['name']}/"); show(f["id"],ind+1)
            else:
                sz=int(f.get("size",0))//1024; mod=f.get("modifiedTime","")[:10]
                print(f"{p}📄 {f['name']}  ({sz}KB, {mod})")
    show(r)
def cmd_upload(fp):
    f=Path(fp)
    if not f.exists(): print(f"❌ Not found: {fp}"); sys.exit(1)
    d=route(f.name)
    if not d: print(f"⚠️ No route for {f.name}"); sys.exit(1)
    s=svc(); r=root(s); fid=resolve(s,d,r); a=upload(s,f,fid)
    print(f"✅ {f.name} → {d}/ ({a})")
if __name__=="__main__":
    cmd=sys.argv[1] if len(sys.argv)>1 else ""
    if cmd=="auth": cmd_auth()
    elif cmd=="push": cmd_push()
    elif cmd=="pull": cmd_pull()
    elif cmd=="list": cmd_list()
    elif cmd=="upload" and len(sys.argv)>2: cmd_upload(sys.argv[2])
    else: print(__doc__)

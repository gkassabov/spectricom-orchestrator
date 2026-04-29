#!/usr/bin/env python3
"""
DRIVE PULL SESSION v2 — Pulls latest session-start docs from Google Drive.
Places them in Documents/Spectricom/ for Gemma to read via filesystem MCP.
Skips files where local version >= Drive version (smart sync).

Usage:
  python3 drive-pull-session.py          ← pull all session docs (smart sync)
  python3 drive-pull-session.py --list   ← list what would be pulled (dry run)
  python3 drive-pull-session.py --force  ← pull all, overwrite even if local is current
  python3 drive-pull-session.py --design ← also pull latest design spec
  python3 drive-pull-session.py --spikes ← also pull spike docs
"""
import sys, os, io, json, re, shutil
from pathlib import Path
from datetime import datetime

ORCH = Path.home() / "spectricom-orchestrator"
TOKEN = ORCH / "drive-token.json"
SCOPES = ["https://www.googleapis.com/auth/drive"]
OUTPUT = Path("/mnt/c/Users/gkass/Documents/Spectricom")
OLD_DIR = OUTPUT / "Old"

# ── Drive folder mapping ──
PULL_MAP = [
    (["Spectricom", "Registry"],        "latest",          "Registry"),
    (["Spectricom", "Plans"],           "latest",          "Master Plan"),
    (["Spectricom", "Logs"],            "latest",          "Logs"),
    (["Spectricom", "Prompts"],         "latest",          "System Prompt"),
    (["Spectricom", "Context"],         "latest-per-type", "Context Slims"),
]

BUG_REGISTRY_PATHS = [
    ["Spectricom", "Yorsie", "Bugs"],
    ["Spectricom", "Yorsie", "Design"],
    ["Spectricom", "Yorsie"],
    ["Spectricom", "Bugs"],
]

OPTIONAL_MAP = {
    "--design": (["Spectricom", "Yorsie", "Design"], "latest", "Design Spec"),
    "--spikes": (["Spectricom", "Spikes"],            "all",    "Spike Docs"),
}


def get_svc():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds.valid and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        TOKEN.write_text(creds.to_json())
    return build("drive", "v3", credentials=creds)


def find_folder(svc, name, parent_id=None):
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    r = svc.files().list(q=q, fields="files(id)", pageSize=5).execute().get("files", [])
    return r[0]["id"] if r else None


def navigate_path(svc, segments):
    parent = None
    for seg in segments:
        fid = find_folder(svc, seg, parent)
        if not fid:
            return None, seg
        parent = fid
    return parent, None


def list_files(svc, folder_id, limit=50):
    return svc.files().list(
        q=f"'{folder_id}' in parents and trashed=false and mimeType!='application/vnd.google-apps.folder'",
        fields="files(id,name,modifiedTime,size)",
        orderBy="modifiedTime desc",
        pageSize=limit
    ).execute().get("files", [])


def parse_context_type(filename):
    name = filename.lower()
    if re.search(r'\(\d+\)', name):
        return None
    m = re.search(r'context-slim-v\d+-\d+-(\w+)\.md$', name)
    return m.group(1) if m else None


def parse_version(filename):
    m = re.search(r'v(\d+)[-_](\d+)', filename)
    if m:
        return (int(m.group(1)), int(m.group(2)))
    m = re.search(r'v(\d+)', filename)
    if m:
        return (int(m.group(1)), 0)
    return (0, 0)


def extract_base_name(fn):
    """Extract base name for grouping versions."""
    name = re.sub(r'\.md$', '', fn)
    m = re.match(r'^(.+?)[-_]v\d+[-_]\d+[-_]?(.*)$', name)
    if m:
        before, after = m.group(1), m.group(2)
        return f"{before}-{after}" if after else before
    return name


def filter_latest_per_type(files):
    by_type = {}
    for f in files:
        ctype = parse_context_type(f["name"])
        if ctype is None:
            continue
        ver = parse_version(f["name"])
        if ctype not in by_type or ver > by_type[ctype][0]:
            by_type[ctype] = (ver, f)
    return [f for _, f in by_type.values()]


def find_bug_registry(svc, paths):
    for segments in paths:
        folder_id, _ = navigate_path(svc, segments)
        if not folder_id:
            continue
        all_files = list_files(svc, folder_id)
        matches = [f for f in all_files
                   if "bug-registry" in f["name"].lower()
                   or "bug_registry" in f["name"].lower()]
        if matches:
            best = max(matches, key=lambda f: parse_version(f["name"]))
            return best, "/".join(segments)
    return None, None


def download_file(svc, file_id, dest_path):
    from googleapiclient.http import MediaIoBaseDownload
    req = svc.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    dl = MediaIoBaseDownload(fh, req)
    done = False
    while not done:
        _, done = dl.next_chunk()
    dest_path.write_bytes(fh.getvalue())


def local_version_for_base(base_name):
    """Find the local file matching this base name and return its version."""
    if not OUTPUT.exists():
        return None, (0, 0)
    for f in OUTPUT.iterdir():
        if f.is_file() and f.suffix == '.md':
            if extract_base_name(f.name) == base_name:
                return f, parse_version(f.name)
    return None, (0, 0)


def archive_local_if_older(drive_filename):
    """If a local file with the same base name but older version exists, archive it."""
    drive_base = extract_base_name(drive_filename)
    drive_ver = parse_version(drive_filename)
    local_file, local_ver = local_version_for_base(drive_base)
    if local_file and local_file.name != drive_filename and local_ver < drive_ver:
        OLD_DIR.mkdir(parents=True, exist_ok=True)
        dest = OLD_DIR / local_file.name
        if dest.exists(): dest.unlink()
        local_file.rename(dest)
        print(f"  📦 Archived: {local_file.name} → Old/")


def should_skip(drive_filename, force=False):
    """Check if local version is already current. Returns True to skip."""
    if force:
        return False
    drive_base = extract_base_name(drive_filename)
    drive_ver = parse_version(drive_filename)
    _, local_ver = local_version_for_base(drive_base)
    return local_ver >= drive_ver


def run(dry_run=False, force=False, extras=None):
    extras = extras or []
    svc = get_svc()

    pull_list = list(PULL_MAP)
    for flag in extras:
        if flag in OPTIONAL_MAP:
            pull_list.append(OPTIONAL_MAP[flag])

    if not dry_run:
        OUTPUT.mkdir(parents=True, exist_ok=True)

    pulled = []
    skipped = []
    errors = []

    # ── Standard folders ──
    for segments, mode, label in pull_list:
        folder_id, failed_seg = navigate_path(svc, segments)
        if not folder_id:
            errors.append(f"❌ {label}: folder '{failed_seg}' not found in {'/'.join(segments)}")
            continue

        all_files = list_files(svc, folder_id)
        if not all_files:
            errors.append(f"⚠️  {label}: folder exists but is empty")
            continue

        if mode == "latest":
            selected = [max(all_files, key=lambda f: parse_version(f["name"]))]
        elif mode == "latest-per-type":
            selected = filter_latest_per_type(all_files)
            if not selected:
                errors.append(f"⚠️  {label}: no typed files found (all legacy?)")
                continue
        elif mode == "all":
            selected = all_files
        else:
            selected = all_files[:1]

        for f in selected:
            if should_skip(f["name"], force):
                skipped.append((f["name"], label))
                if dry_run:
                    print(f"  ⏭️  {f['name']} — local is current")
                continue

            dest = OUTPUT / f["name"]
            if dry_run:
                size = int(f.get("size", 0))
                print(f"  📄 {f['name']} ({size // 1024}KB) — {label}")
            else:
                archive_local_if_older(f["name"])
                download_file(svc, f["id"], dest)
                pulled.append((f["name"], label))
                print(f"  📥 {f['name']} ← {'/'.join(segments)}/")

    # ── Bug registry (multi-path search) ──
    bug_file, bug_path = find_bug_registry(svc, BUG_REGISTRY_PATHS)
    if bug_file:
        if should_skip(bug_file["name"], force):
            skipped.append((bug_file["name"], "Bug Registry"))
            if dry_run:
                print(f"  ⏭️  {bug_file['name']} — local is current")
        else:
            dest = OUTPUT / bug_file["name"]
            if dry_run:
                size = int(bug_file.get("size", 0))
                print(f"  📄 {bug_file['name']} ({size // 1024}KB) — Bug Registry")
            else:
                archive_local_if_older(bug_file["name"])
                download_file(svc, bug_file["id"], dest)
                pulled.append((bug_file["name"], "Bug Registry"))
                print(f"  📥 {bug_file['name']} ← {bug_path}/")
    else:
        errors.append("⚠️  Bug Registry: not found (checked Yorsie/Bugs, Yorsie/Design, Yorsie/, Bugs/)")

    # ── Summary ──
    print()
    if errors:
        for e in errors:
            print(f"  {e}")
        print()

    if dry_run:
        print(f"🔍 Dry run: {len(pulled) + len([s for s in skipped])} total — "
              f"would pull {len(pulled)}, skip {len(skipped)} (already current)")
        if not force and skipped:
            print(f"   Use --force to re-download all")
    else:
        print(f"✅ {len(pulled)} pulled, {len(skipped)} skipped (already current) → {OUTPUT}")
        if pulled:
            print(f"\n📋 Files ready for Gemma (filesystem MCP):")
            tier0_labels = ("Registry", "Master Plan")
            tier0 = [(n, l) for n, l in pulled if l in tier0_labels]
            rest = [(n, l) for n, l in pulled if l not in tier0_labels]
            for i, (name, label) in enumerate(tier0 + rest, 1):
                marker = " ← TIER 0" if label in tier0_labels else ""
                print(f"  {i}. {name}{marker}")


if __name__ == "__main__":
    args = sys.argv[1:]
    dry_run = "--list" in args
    force = "--force" in args
    extras = [a for a in args if a.startswith("--") and a not in ("--list", "--force", "--help", "-h")]

    if "--help" in args or "-h" in args:
        print(__doc__)
        sys.exit(0)

    label = "🔍 DRY RUN" if dry_run else ("📥 FORCE PULLING" if force else "📥 SMART SYNC")
    print(f"\n{label} session docs from Google Drive → {OUTPUT}\n")
    run(dry_run=dry_run, force=force, extras=extras)

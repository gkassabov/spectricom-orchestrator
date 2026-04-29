#!/usr/bin/env python3
# filename: migrate_yorsie_logs.py
"""
One-time migration: move top-level toni-*.log files into logs/yorsie/.
Idempotent — safe to re-run; skips if destination exists.
Gate: marker file ~/spectricom-orchestrator/logs/.migrated-v3.4
"""
import shutil
from pathlib import Path
from datetime import datetime

LOG_DIR = Path.home() / "spectricom-orchestrator" / "logs"
MARKER = LOG_DIR / ".migrated-v3.4"


def migrate():
    if MARKER.exists():
        print(f"Already migrated (marker: {MARKER})")
        return 0

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    yorsie_dir = LOG_DIR / "yorsie"
    yorsie_dir.mkdir(parents=True, exist_ok=True)

    moved = 0
    for f in LOG_DIR.glob("toni-*.log"):
        dest = yorsie_dir / f.name
        if not dest.exists():
            shutil.move(str(f), str(dest))
            moved += 1
            print(f"  Moved: {f.name}")

    MARKER.write_text(f"Migrated {moved} files at {datetime.now().isoformat()}\n")
    print(f"Done. Moved {moved} log files to {yorsie_dir}")
    return moved


if __name__ == "__main__":
    migrate()

#!/usr/bin/env python3
"""
SPECTRICOM RATE LIMITER
=======================
Tracks daily Toni execution limits to prevent runaway rate burns.

Usage (standalone):
  python3 rate_limiter.py status
  python3 rate_limiter.py reset
  python3 rate_limiter.py set-caps --batches 20 --briefs 80

Usage (imported):
  from rate_limiter import pre_flight, record, show
"""

import json, sys, argparse
from pathlib import Path
from datetime import datetime, date

# ═══════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════
ORCH_DIR = Path.home() / "spectricom-orchestrator"
RATE_FILE = ORCH_DIR / "rate-limits.json"
CAPS_FILE = ORCH_DIR / "rate-caps.json"

# Defaults — override via `set-caps` command or rate-caps.json
DEFAULT_DAILY_BATCH_CAP = 15
DEFAULT_DAILY_BRIEF_CAP = 60
WARN_THRESHOLD = 0.8  # warn at 80% of cap
HISTORY_DAYS = 14      # keep 14 days of history

# ═══════════════════════════════════════════════════════
# CAPS
# ═══════════════════════════════════════════════════════
def load_caps() -> dict:
    if CAPS_FILE.exists():
        return json.loads(CAPS_FILE.read_text())
    return {"daily_batches": DEFAULT_DAILY_BATCH_CAP, "daily_briefs": DEFAULT_DAILY_BRIEF_CAP}

def save_caps(caps: dict):
    CAPS_FILE.write_text(json.dumps(caps, indent=2))

# ═══════════════════════════════════════════════════════
# STATE
# ═══════════════════════════════════════════════════════
def load() -> dict:
    if RATE_FILE.exists():
        return json.loads(RATE_FILE.read_text())
    return {"daily": {}, "lifetime": {"batches": 0, "briefs": 0, "total_duration_s": 0}}

def save(data: dict):
    RATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    RATE_FILE.write_text(json.dumps(data, indent=2, default=str))

def today_key() -> str:
    return date.today().isoformat()

def get_today(data: dict) -> dict:
    key = today_key()
    if key not in data["daily"]:
        data["daily"][key] = {"batches": 0, "briefs": 0, "duration_s": 0, "executions": []}
    return data["daily"][key]

def prune_history(data: dict):
    """Keep only last HISTORY_DAYS days."""
    keys = sorted(data["daily"].keys())
    while len(keys) > HISTORY_DAYS:
        del data["daily"][keys.pop(0)]

# ═══════════════════════════════════════════════════════
# PRE-FLIGHT CHECK
# ═══════════════════════════════════════════════════════
def pre_flight(brief_count: int) -> tuple[bool, str]:
    """
    Check if execution is within daily rate limits.
    Returns (allowed: bool, message: str).
    """
    caps = load_caps()
    batch_cap = caps["daily_batches"]
    brief_cap = caps["daily_briefs"]
    data = load()
    today = get_today(data)

    # Hard block: batch cap
    if today["batches"] >= batch_cap:
        return False, (
            f"❌ BLOCKED — Daily batch cap reached ({today['batches']}/{batch_cap}). "
            f"Run `python3 rate_limiter.py set-caps --batches {batch_cap + 5}` to raise, "
            f"or `python3 rate_limiter.py reset` to clear today's counters."
        )

    # Hard block: brief cap
    if today["briefs"] + brief_count > brief_cap:
        remaining = brief_cap - today["briefs"]
        return False, (
            f"❌ BLOCKED — Would exceed daily brief cap "
            f"({today['briefs']}+{brief_count}={today['briefs']+brief_count} > {brief_cap}). "
            f"{remaining} briefs remaining today."
        )

    # Warning: approaching batch cap
    if today["batches"] >= int(batch_cap * WARN_THRESHOLD):
        return True, (
            f"⚠️  Approaching batch cap ({today['batches']}/{batch_cap}). "
            f"{batch_cap - today['batches']} remaining."
        )

    # Warning: approaching brief cap
    if today["briefs"] + brief_count >= int(brief_cap * WARN_THRESHOLD):
        return True, (
            f"⚠️  Approaching brief cap ({today['briefs']+brief_count}/{brief_cap}). "
            f"{brief_cap - today['briefs'] - brief_count} remaining after this batch."
        )

    return True, (
        f"✅ Rate OK — {today['batches']}/{batch_cap} batches, "
        f"{today['briefs']}/{brief_cap} briefs today"
    )

# ═══════════════════════════════════════════════════════
# RECORD EXECUTION
# ═══════════════════════════════════════════════════════
def record(batch_name: str, brief_count: int, duration_s: float, status: str):
    """Record a completed batch execution."""
    data = load()
    today = get_today(data)

    today["batches"] += 1
    today["briefs"] += brief_count
    today["duration_s"] += duration_s
    today["executions"].append({
        "batch": batch_name,
        "briefs": brief_count,
        "duration_s": round(duration_s, 1),
        "status": status,
        "at": datetime.now().isoformat()
    })

    data["lifetime"]["batches"] += 1
    data["lifetime"]["briefs"] += brief_count
    data["lifetime"]["total_duration_s"] += duration_s

    prune_history(data)
    save(data)

# ═══════════════════════════════════════════════════════
# DISPLAY
# ═══════════════════════════════════════════════════════
def show():
    """Display rate limit status to stdout."""
    caps = load_caps()
    data = load()
    today = get_today(data)
    lt = data["lifetime"]
    batch_cap = caps["daily_batches"]
    brief_cap = caps["daily_briefs"]

    # Burn rate (avg duration per brief today)
    avg_brief_time = today["duration_s"] / today["briefs"] if today["briefs"] > 0 else 0

    print(f"\n  ┌─ RATE LIMITS ──────────────────────────────────┐")
    print(f"  │  Daily batches:  {today['batches']:>3} / {batch_cap:<3}  {'🔴 FULL' if today['batches'] >= batch_cap else '⚠️  WARN' if today['batches'] >= int(batch_cap * WARN_THRESHOLD) else '🟢 OK'}")
    print(f"  │  Daily briefs:   {today['briefs']:>3} / {brief_cap:<3}  {'🔴 FULL' if today['briefs'] >= brief_cap else '⚠️  WARN' if today['briefs'] >= int(brief_cap * WARN_THRESHOLD) else '🟢 OK'}")
    print(f"  │  Duration today: {today['duration_s']/60:>6.1f} min")
    if avg_brief_time > 0:
        print(f"  │  Burn rate:      {avg_brief_time:>6.1f} s/brief")
    print(f"  │")
    print(f"  │  Lifetime:  {lt['batches']} batches, {lt['briefs']} briefs, {lt['total_duration_s']/3600:.1f}h")
    print(f"  └────────────────────────────────────────────────┘")

    if today["executions"]:
        print(f"\n  Today's executions:")
        for entry in today["executions"][-5:]:
            e = "✅" if entry["status"] == "passed" else "❌"
            ts = entry["at"].split("T")[1][:8]
            print(f"    {ts}  {e}  {entry['batch']}  ({entry['briefs']} briefs, {entry['duration_s']:.0f}s)")

    # Show last few days
    days = sorted(data["daily"].keys(), reverse=True)
    if len(days) > 1:
        print(f"\n  Recent days:")
        for d in days[1:5]:
            dd = data["daily"][d]
            print(f"    {d}:  {dd['batches']} batches, {dd['briefs']} briefs, {dd['duration_s']/60:.0f}min")

# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════
def main():
    ap = argparse.ArgumentParser(description="Spectricom Rate Limiter")
    sp = ap.add_subparsers(dest="cmd")

    sp.add_parser("status", help="Show rate limit status")
    sp.add_parser("reset", help="Reset today's counters")

    sc = sp.add_parser("set-caps", help="Set daily caps")
    sc.add_argument("--batches", type=int, help="Daily batch cap")
    sc.add_argument("--briefs", type=int, help="Daily brief cap")

    a = ap.parse_args()

    if a.cmd == "status" or a.cmd is None:
        show()
    elif a.cmd == "reset":
        data = load()
        key = today_key()
        if key in data["daily"]:
            old = data["daily"][key]
            print(f"Resetting today ({old['batches']} batches, {old['briefs']} briefs)")
            del data["daily"][key]
            save(data)
            print("✅ Today's counters reset")
        else:
            print("Nothing to reset")
    elif a.cmd == "set-caps":
        caps = load_caps()
        if a.batches is not None:
            caps["daily_batches"] = a.batches
        if a.briefs is not None:
            caps["daily_briefs"] = a.briefs
        save_caps(caps)
        print(f"✅ Caps set: {caps['daily_batches']} batches/day, {caps['daily_briefs']} briefs/day")

if __name__ == "__main__":
    main()

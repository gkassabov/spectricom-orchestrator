#!/usr/bin/env python3
"""ORCH-OPX-DENIALS-1 (Kanban 760; 622 slice 2 of 2; RM-OPS-04-F-01; C-OPX04) — the EOS §9 OPX-5 row from logs.

    python3 scripts/opx5.py --session <S7-CORE-N> --since <ISO time> [--until <ISO time>] [--orch-dir <dir>]

Prints one EOS_Protocol §9 row, every cell with its source:
    | OPX-5 | <session> | CFR … | escaped … | FAIL→merge … | policy violations … | sandbox/hook denials … |
A number this script cannot produce from a log is written `not measured — <reason>`, never 0 (EOS §9). This slice
measures cell 5 (denials) from logs/opx/denials.ndjson, which executor/hooks/kill_switch.sh and
executor/hooks/denial_log.py write; cells 1–4 say what they wait for. The Bash sandbox is not running (Kanban 392),
so cell 5 always says so. Times are UTC; `--since` / `--until` take ISO 8601 (a time without a zone is UTC).
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_REL = Path("logs") / "opx" / "denials.ndjson"
SANDBOX = "sandbox: not running (392)"
NOT_MEASURED = {
    "cfr": "not measured — the ledger's merge SHAs and gate verdicts (623 ORCH-LEDGER-CHAIN-1) are not read by this "
           "script yet",
    "escaped": "not measured — the Bug Registry is canon, outside the orchestrator's logs",
    "repair": "not measured — FAIL→merge pairs need the ledger (623 ORCH-LEDGER-CHAIN-1)",
    "policy": "not measured — prefire A12–A14 refusals are not logged to a file this script reads",
}


def utc(text: str) -> datetime:
    t = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def denial_cell(orch_dir: Path, since: datetime, until: datetime) -> str:
    log = orch_dir / LOG_REL
    if not log.exists():
        return f"{SANDBOX} + hook denials not measured — {LOG_REL} absent (the denial logger has not run)"
    counts, bad = {"kill-hook": 0, "permissions.deny": 0}, 0
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            at = utc(entry["at"])
        except (ValueError, KeyError, TypeError):
            bad += 1
            continue
        if since <= at <= until and entry.get("source") in counts:
            counts[entry["source"]] += 1
    total = sum(counts.values())
    note = f"; {bad} unreadable line(s) skipped" if bad else ""
    return (f"{SANDBOX} + hook denials {total} (kill-hook {counts['kill-hook']}, permissions.deny "
            f"{counts['permissions.deny']}; {LOG_REL}{note})")


def row(session: str, orch_dir: Path, since: datetime, until: datetime) -> str:
    cells = [
        "OPX-5",
        session,
        f"CFR {NOT_MEASURED['cfr']}",
        f"escaped {NOT_MEASURED['escaped']}",
        f"FAIL→merge {NOT_MEASURED['repair']}",
        f"policy violations {NOT_MEASURED['policy']}",
        f"sandbox/hook denials: {denial_cell(orch_dir, since, until)}",
    ]
    return "| " + " | ".join(cells) + " |"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--session", required=True)
    ap.add_argument("--since", required=True)
    ap.add_argument("--until")
    ap.add_argument("--orch-dir", default=str(Path.home() / "spectricom-orchestrator"))
    a = ap.parse_args(argv)
    since = utc(a.since)
    until = utc(a.until) if a.until else datetime.now(timezone.utc)
    if until < since:
        print("opx5: --until is before --since", file=sys.stderr)
        return 2
    print(row(a.session, Path(a.orch_dir), since, until))
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""[ORCH-OPX-DENIALS-1] (Kanban 760; 622 slice 2 of 2; RM-OPS-04-F-01 + RM-OPS-24P-F-01; T-OPX-03; C-OPX04)
The executor's permission-denial logger: a Stop and SessionEnd hook in every executor/settings/<repo>.json.

Why a transcript scan. Toni fires with --dangerously-skip-permissions: the settings' `permissions.deny` rules still
refuse a call, but CLI 2.1.322 runs no hook for it — its PermissionDenied event is for auto mode only, and neither
PreToolUse nor PostToolUseFailure sees the refusal (measured in 760's dry run, `claude -p` in a sandbox). The
refusal does land in the session transcript as an errored tool_result:
    "Permission to use <Tool> with command <cmd> has been denied."
    "<tool_use_error>File is in a directory that is denied by your permission settings.</tool_use_error>"
This hook reads `transcript_path` from its stdin JSON and appends one NDJSON line per such refusal, once per
tool_use_id, to <state dir>/logs/opx/denials.ndjson (the kill hook writes its own denials there too).

Denial burst. config/opx-denials.json {"burst": {"n": N, "window_s": S}}: when both are set and at least N
permissions.deny lines fall within the last S seconds, the hook writes KILL in the state dir (the same JSON shape
`queue_daemon.py kill` writes) unless KILL is already there, and appends a line to logs/kill-switch.log. Unset (null),
missing or unreadable config → off. The hook never signals a process: KILL alone makes the kill hook deny the next
tool call and the daemon fire nothing (RM-OPS-24P).

Never blocks. Exit 0 on every path — a Stop hook's exit 2 would keep the executor working — and a failure to log is
said on stderr only. The log file is created on every run, so its existence shows the logger is wired (opx5.py).

State dir: $TONI_GUARDS_HOME, else $HOME/spectricom-orchestrator — the kill hook's rule. Config: config/ beside this
script's checkout (executor/hooks/../../config).
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CONFIG = ROOT / "config" / "opx-denials.json"
LOG_REL = Path("logs") / "opx" / "denials.ndjson"
SOURCE = "permissions.deny"
DENIAL_PATTERNS = (
    re.compile(r"^Permission to use \S+ .*has been denied\.?$", re.S),
    re.compile(r"denied by your permission settings"),
)
DETAIL_MAX = 200


def state_dir() -> Path:
    if os.environ.get("TONI_GUARDS_HOME"):
        return Path(os.environ["TONI_GUARDS_HOME"])
    return Path(os.environ["HOME"]) / "spectricom-orchestrator"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(content) -> str:
    """A tool_result's content as text (a string, or a list of text blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def is_denial(text: str) -> bool:
    t = text.replace("<tool_use_error>", "").replace("</tool_use_error>", "").strip()
    return any(p.search(t) for p in DENIAL_PATTERNS)


def denials_in(transcript: Path) -> list:
    """[(tool_use_id, tool name, detail)] for every errored tool_result in the transcript that is a permission
    refusal, in transcript order. Lines that are not JSON are skipped."""
    names, found = {}, []
    for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        content = ((entry.get("message") or {}).get("content")) if isinstance(entry, dict) else None
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use" and block.get("id"):
                names[block["id"]] = block.get("name") or "?"
            elif block.get("type") == "tool_result" and block.get("is_error"):
                text = _text(block.get("content"))
                if is_denial(text):
                    tid = block.get("tool_use_id") or ""
                    detail = " ".join(text.replace("<tool_use_error>", "").replace("</tool_use_error>", "").split())
                    found.append((tid, names.get(tid, "?"), detail[:DETAIL_MAX]))
    return found


def read_log(log: Path) -> list:
    if not log.exists():
        return []
    out = []
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def burst_config() -> tuple:
    """(n, window_s) when both are set to positive numbers, else (None, None) — off."""
    try:
        burst = json.loads(CONFIG.read_text(encoding="utf-8")).get("burst") or {}
        n, w = burst.get("n"), burst.get("window_s")
    except (OSError, ValueError, AttributeError):
        return None, None
    if isinstance(n, int) and not isinstance(n, bool) and n > 0 and isinstance(w, (int, float)) and w > 0:
        return n, float(w)
    return None, None


def _parse(at: str):
    try:
        return datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def maybe_burst_kill(sdir: Path, lines: list, now: datetime) -> bool:
    """Write KILL when the burst threshold is reached. True when this call wrote it."""
    n, window = burst_config()
    if n is None:
        return False
    since = now - timedelta(seconds=window)
    recent = [l for l in lines if l.get("source") == SOURCE and (_parse(l.get("at")) or since - timedelta(1)) >= since]
    if len(recent) < n:
        return False
    kill = sdir / "KILL"
    if kill.exists() or kill.is_symlink():
        return False
    reason = f"denial burst: {len(recent)} permission denials within {window:g}s (config/opx-denials.json n={n})"
    kill.write_text(json.dumps({"reason": reason, "at": now.isoformat(timespec="seconds"),
                                "by": "executor/hooks/denial_log.py (ORCH-OPX-DENIALS-1)"}) + "\n", encoding="utf-8")
    with (sdir / "logs" / "kill-switch.log").open("a", encoding="utf-8") as f:
        f.write(f"{now.isoformat(timespec='seconds')} 🛡 KILL — {reason}: KILL written ({kill}) by the denial logger\n")
    return True


def main(stdin: str) -> int:
    sdir = state_dir()
    log = sdir / LOG_REL
    log.parent.mkdir(parents=True, exist_ok=True)
    log.touch(exist_ok=True)
    payload = json.loads(stdin) if stdin.strip() else {}
    transcript = payload.get("transcript_path")
    if not transcript or not Path(transcript).is_file():
        return 0
    seen = {l.get("tool_use_id") for l in read_log(log) if l.get("source") == SOURCE}
    now = _now()
    new = []
    for tid, tool, detail in denials_in(Path(transcript)):
        if tid in seen:
            continue
        seen.add(tid)
        new.append({"at": _iso(now), "source": SOURCE, "session_id": payload.get("session_id") or "",
                    "tool_use_id": tid, "tool": tool, "detail": detail})
    if new:
        with log.open("a", encoding="utf-8") as f:
            for line in new:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        maybe_burst_kill(sdir, read_log(log), now)
    return 0


if __name__ == "__main__":
    try:
        main(sys.stdin.read())
    except Exception as e:  # never block the executor: the logger reports, it does not decide
        print(f"🛡 denial log: not written ({type(e).__name__}: {e})", file=sys.stderr)
    sys.exit(0)

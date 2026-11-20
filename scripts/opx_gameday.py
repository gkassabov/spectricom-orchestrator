#!/usr/bin/env python3
"""ORCH-OPX-GAMEDAY-1 (Kanban 622 slice 1; RM-OPS-24P-F-01; T-OPX-03; C-OPX03) — the monthly kill-switch game day.

    python3 scripts/opx_gameday.py [--out <report.json>] [--grace <seconds>]

Proves, on a real process tree in a sandbox orchestrator dir (never the live one), that:
  1. the shipped PreToolUse kill hook (executor/hooks/kill_switch.sh) allows while there is no KILL;
  2. `queue_daemon.kill` writes KILL and ends a fire that TRAPS SIGTERM — SIGTERM, then SIGKILL after the grace —
     together with a Bash-command grandchild in a session of its own, and leaves the orchestrator process alone;
  3. the hook then denies every tool call (exit 2);
  4. the daemon's own loop fires nothing while KILL exists (a queued brief stays queued, run_loop is the real one);
  5. `queue_daemon.unkill` lifts it;
  6. credential revocation: reported `not built` (no revocation path exists yet — never reported as passed).
Writes one JSON report (default: logs/gameday/opx-gameday-<timestamp>.json under the live orchestrator dir) and prints
one line per check. Exit 0 only when checks 1–5 pass.

Safety: the sandbox is a fresh temporary directory; the script refuses to run if it resolves to the live orchestrator
dir, and restores every queue_daemon module path it moved before it returns. Nothing is signalled but the process tree
this script started.
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import types
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import queue_daemon  # noqa: E402

HOOK = ROOT / "executor" / "hooks" / "kill_switch.sh"
LIVE_ORCH_DIR = queue_daemon.ORCH_DIR
MOVED = ("ORCH_DIR", "QUEUE_DIR", "QUEUE_DONE", "QUEUE_FAILED", "QUEUE_STATE", "REPOS_CONFIG", "LOG_DIR")
DEFAULT_GRACE_S = 2.0
WAIT_S = 15.0
NOT_BUILT = "not built"

# The dummy orchestrator: its fire leads its own session (fire_toni's Popen(preexec_fn=os.setsid)) and traps SIGTERM;
# the fire's Bash command is a grandchild leading a session of its own (as the CLI runs each Bash command).
DUMMY_ORCH = r"""
import os, subprocess, sys, time
fire = subprocess.Popen(["bash", "-c", sys.argv[1]], preexec_fn=os.setsid)
open(sys.argv[2], "w").write(str(fire.pid))
fire.wait()
open(sys.argv[3], "w").write(str(fire.returncode))
time.sleep(300)
"""
FIRE = ("python3 -c 'import os, time; os.setsid(); time.sleep(300)' & echo $! > {gc}; "
        "trap '' TERM; while :; do sleep 0.1; done")


class SandboxError(RuntimeError):
    pass


def _alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def _sid(pid: int) -> int:
    """The session id of `pid` (-1 when it cannot be read)."""
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[3])   # state ppid pgrp session
    except (OSError, IndexError, ValueError):
        return -1


def _wait_for(pred, s: float = WAIT_S) -> bool:
    end = time.monotonic() + s
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return bool(pred())


def _hook(sandbox: Path) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(sandbox.parent), "TONI_GUARDS_HOME": str(sandbox)}
    return subprocess.run(["bash", str(HOOK)], env=env, input='{"tool_name":"Bash","tool_input":{"command":"ls"}}',
                          capture_output=True, text=True, timeout=20)


def enter_sandbox(sandbox: Path) -> dict:
    """Point queue_daemon at `sandbox`; return the saved paths. Refuses the live orchestrator dir."""
    if sandbox.resolve() == Path(LIVE_ORCH_DIR).resolve():
        raise SandboxError(f"refusing to run the game day in the live orchestrator dir {LIVE_ORCH_DIR}")
    for d in ("state", "logs", "config", "queue"):
        (sandbox / d).mkdir(parents=True, exist_ok=True)
    not_git = sandbox / "not-a-repo"
    not_git.mkdir(exist_ok=True)
    config = sandbox / "config" / "repos.yaml"
    config.write_text(json.dumps({"repos": {"clinical-mp": {"project_dir": str(not_git)}}}))   # JSON is YAML
    saved = {name: getattr(queue_daemon, name) for name in MOVED}
    for name, val in (("ORCH_DIR", sandbox), ("QUEUE_DIR", sandbox / "queue"), ("QUEUE_DONE", sandbox / "queue" / "done"),
                      ("QUEUE_FAILED", sandbox / "queue" / "failed"), ("QUEUE_STATE", sandbox / "queue-state.json"),
                      ("REPOS_CONFIG", config), ("LOG_DIR", sandbox / "logs")):
        setattr(queue_daemon, name, val)
    return saved


def leave_sandbox(saved: dict) -> None:
    for name, val in saved.items():
        setattr(queue_daemon, name, val)


def _daemon_refuses_while_killed(sandbox: Path) -> dict:
    """The real run_loop over a queued brief while KILL exists: nothing may fire."""
    brief = sandbox / "queue" / "000000000-gameday-probe.md"
    brief.write_text("#!queue repo=clinical-mp\n\n# game-day probe — never fired\n")
    d = queue_daemon.QueueDaemon()
    d.start_running = True
    d.config.update(cooldown_seconds=0, model="m", effort="e")
    fired: list = []

    def _route(cmd, batch_name, log_path):
        fired.append(batch_name)
        return 0
    d._run_route = _route
    polls: list = []
    real_time = queue_daemon.time

    def _sleep(s):
        polls.append(s)
        if len(polls) >= 3:
            d.status = "stopped"
    queue_daemon.time = types.SimpleNamespace(sleep=_sleep, monotonic=time.monotonic)
    try:
        d.run_loop()
    finally:
        queue_daemon.time = real_time
    ok = fired == [] and brief.exists()
    return {"pass": ok, "evidence": f"polls {len(polls)}; fired {fired or 'nothing'}; probe brief still queued: {brief.exists()}"}


def run_drill(sandbox: Path, grace: float) -> list:
    checks: list = []
    r = _hook(sandbox)
    checks.append({"check": "hook allows without KILL", "pass": r.returncode == 0, "evidence": f"exit {r.returncode}"})

    gc_f, fire_f, rc_f = sandbox / "gc.pid", sandbox / "fire.pid", sandbox / "fire.rc"
    orch = subprocess.Popen([sys.executable, "-c", DUMMY_ORCH, FIRE.format(gc=gc_f), str(fire_f), str(rc_f)])
    try:
        # started = the fire leads its group and the Bash grandchild already leads a session of its own (so the kill
        # meets the tree a real fire has, not one still forming)
        started = _wait_for(lambda: fire_f.exists() and fire_f.read_text().strip() and gc_f.exists()
                            and gc_f.read_text().strip() and _sid(int(gc_f.read_text())) == int(gc_f.read_text()))
        if not started:
            checks.append({"check": "kill ends a SIGTERM-trapping fire", "pass": False, "evidence": "the dummy fire did not start"})
            return checks
        fire, gc = int(fire_f.read_text()), int(gc_f.read_text())
        (sandbox / "state" / "running-clinical-mp.json").write_text(json.dumps(
            {"pid": orch.pid, "batch_id": "gameday", "repo": "clinical-mp", "branch": "orch-mp-gameday"}))
        t0 = time.monotonic()
        rc = queue_daemon.kill("OPX game day", grace_s=grace)
        gone = _wait_for(lambda: not _alive(fire) and not _alive(gc))
        took = time.monotonic() - t0
        got_rc = _wait_for(lambda: rc_f.exists() and rc_f.read_text().strip())
        fire_rc = rc_f.read_text().strip() if got_rc else "?"
        ok = (rc == 0 and (sandbox / "KILL").exists() and gone and fire_rc == str(-signal.SIGKILL)
              and _alive(orch.pid))
        checks.append({"check": "kill ends a SIGTERM-trapping fire", "pass": ok,
                       "evidence": f"kill exit {rc}; KILL written {(sandbox / 'KILL').exists()}; fire {fire} and Bash "
                                   f"grandchild {gc} gone {gone} in {took:.1f}s; fire exit {fire_rc} (SIGKILL = "
                                   f"{-signal.SIGKILL}, after the {grace:g}s grace); orchestrator {orch.pid} untouched "
                                   f"{_alive(orch.pid)}"})
    finally:
        orch.kill()
        orch.wait()
        for f in (gc_f, fire_f):
            try:
                os.killpg(int(f.read_text()), signal.SIGKILL)
            except (OSError, ValueError):
                pass
    (sandbox / "state" / "running-clinical-mp.json").unlink(missing_ok=True)

    r = _hook(sandbox)
    checks.append({"check": "hook denies with KILL", "pass": r.returncode == 2 and "every tool call is denied" in r.stderr,
                   "evidence": f"exit {r.returncode}"})
    checks.append({"check": "daemon fires nothing while KILL exists", **_daemon_refuses_while_killed(sandbox)})
    rc = queue_daemon.unkill("OPX game day over")
    checks.append({"check": "unkill lifts KILL", "pass": rc == 0 and not (sandbox / "KILL").exists(),
                   "evidence": f"unkill exit {rc}; KILL present {(sandbox / 'KILL').exists()}"})
    return checks


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ORCH-OPX-GAMEDAY-1 — the monthly kill-switch game day")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--grace", type=float, default=DEFAULT_GRACE_S)
    args = ap.parse_args(argv)
    started = datetime.now().isoformat(timespec="seconds")
    with tempfile.TemporaryDirectory(prefix="opx-gameday-") as tmp:
        sandbox = Path(tmp) / "spectricom-orchestrator"
        saved = enter_sandbox(sandbox)
        try:
            checks = run_drill(sandbox, args.grace)
        finally:
            leave_sandbox(saved)
    checks.append({"check": "credential revocation", "pass": None, "evidence": NOT_BUILT})
    passed = all(c["pass"] for c in checks if c["pass"] is not None)
    report = {"gameday": "ORCH-OPX-GAMEDAY-1", "started": started, "finished": datetime.now().isoformat(timespec="seconds"),
              "hook": str(HOOK.relative_to(ROOT)), "grace_s": args.grace, "passed": passed, "checks": checks}
    out = args.out or (Path(LIVE_ORCH_DIR) / "logs" / "gameday" / f"opx-gameday-{started.replace(':', '')}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n")
    for c in checks:
        mark = "—" if c["pass"] is None else ("✅" if c["pass"] else "❌")
        print(f"{mark} {c['check']}: {c['evidence']}")
    print(f"{'PASSED' if passed else 'FAILED'} — report {out}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())

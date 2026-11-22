# filename: tests/test_gate_leg_tree_kill.py
"""ORCH-GATE-LEG-TREE-KILL-1 (Kanban 880; SCA-ORCH-GATE-TIMEOUT-ORPHANS-1, S7-CORE-59) — a gate command's timeout ends its
whole process tree, not only the shell subprocess.run started. Seen 2026-11-22 07:12: route 853's build leg timed out at
1200 s and `tsc --noEmit` / `vitest list` kept running (reparented, ~220 % CPU) into the route's own recheck.

  TK-1 (RED)     a leg whose shell starts a child that outlives it → the TimeoutExpired is raised as before (with the
                 leg's clock verdict attached) AND the child is gone within the grace
  TK-2 (RED)     the same through run_build_gate: BLOCKED as a timeout (unchanged words), and no child left
  TK-3 (control) a leg that finishes → its CompletedProcess as subprocess.run returns it (code, stdout, stderr)
  TK-4 (RED)     the leg runs in its own process group, never the daemon's (its pgid is not the test's)
  TK-5 (control) a replaced subprocess.run (a test double) is called with the leg's exact arguments, as before
"""
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # a zombie (killed, not yet reaped by its reaper) is gone for this purpose
    try:
        return Path(f"/proc/{pid}/stat").read_text().split()[2] != "Z"
    except OSError:
        return False


def _child_pid(pidfile: Path) -> int:
    for _ in range(50):
        if pidfile.exists() and pidfile.read_text().strip():
            return int(pidfile.read_text().strip())
        time.sleep(0.05)
    raise AssertionError("the planted child never wrote its pid")


def _gone_within(pid: int, seconds: float) -> bool:
    end = time.time() + seconds
    while time.time() < end:
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


def _planted(tmp_path: Path) -> tuple:
    """A shell whose child (sleep 300) outlives it, writing the child's pid — the npm exec -> tsc shape."""
    pidfile = tmp_path / "child.pid"
    return f"sleep 300 & echo $! > {pidfile}; wait", pidfile


def test_tk1_timeout_ends_the_whole_tree(tmp_path):
    cmd, pidfile = _planted(tmp_path)
    raised = None
    try:
        orchestrator._run_leg("build", tmp_path, cmd, shell=True, capture_output=True, text=True, cwd=str(tmp_path), timeout=1)
    except subprocess.TimeoutExpired as e:
        raised = e
    child = _child_pid(pidfile)
    gone = _gone_within(child, orchestrator.GATE_TREE_KILL_GRACE_S + 2) if hasattr(orchestrator, "GATE_TREE_KILL_GRACE_S") else _gone_within(child, 5)
    if not gone:
        os.kill(child, 9)  # never leave the planted child behind
    print(f"[TK-1] raised {type(raised).__name__} timeout={getattr(raised, 'timeout', None)} clock={hasattr(raised, 'gate_clock')} · child {child} gone={gone}")
    assert isinstance(raised, subprocess.TimeoutExpired) and raised.timeout == 1
    assert hasattr(raised, "gate_clock")
    assert gone


def test_tk2_build_gate_timeout_leaves_no_child(monkeypatch, tmp_path):
    cmd, pidfile = _planted(tmp_path)
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG", {"build_gate_cmd": cmd, orchestrator.BUILD_GATE_TIMEOUT_KEY: 1})
    monkeypatch.setattr(orchestrator, "_gate_shell_cmd", lambda c, repo_path: c)
    out = orchestrator.run_build_gate(tmp_path)
    child = _child_pid(pidfile)
    gone = _gone_within(child, 5)
    if not gone:
        os.kill(child, 9)
    print(f"[TK-2] passed={out.passed} error={out.error!r} exit={out.exit_code} · child {child} gone={gone}")
    assert (out.passed, out.error, out.exit_code) == (False, "timeout", -1)
    assert gone


def test_tk3_a_finished_leg_returns_as_before(tmp_path):
    r, clock = orchestrator._run_leg("build", tmp_path, "echo out; echo err >&2; exit 3", shell=True, capture_output=True,
                                     text=True, cwd=str(tmp_path), timeout=30)
    print(f"[TK-3] code={r.returncode} stdout={r.stdout!r} stderr={r.stderr!r} args={r.args!r}")
    assert isinstance(r, subprocess.CompletedProcess)
    assert (r.returncode, r.stdout, r.stderr, r.args) == (3, "out\n", "err\n", "echo out; echo err >&2; exit 3")


def test_tk4_own_process_group(tmp_path):
    out = tmp_path / "pgid"
    r, _ = orchestrator._run_leg("build", tmp_path, f"ps -o pgid= -p $$ > {out}", shell=True, capture_output=True, text=True,
                                 cwd=str(tmp_path), timeout=30)
    leg_pgid = int(out.read_text().strip())
    print(f"[TK-4] leg pgid {leg_pgid} · test pgid {os.getpgid(0)}")
    assert r.returncode == 0
    assert leg_pgid != os.getpgid(0)


def test_tk5_a_replaced_run_is_called_as_before(monkeypatch, tmp_path):
    seen = []

    def double(cmd, **kw):
        seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(subprocess, "run", double)
    r, _ = orchestrator._run_leg("build", tmp_path, "npx tsc --noEmit", shell=True, capture_output=True, text=True,
                                 cwd=str(tmp_path), timeout=7)
    print(f"[TK-5] calls {seen!r}")
    assert seen == [("npx tsc --noEmit", {"shell": True, "capture_output": True, "text": True, "cwd": str(tmp_path), "timeout": 7})]
    assert r.stdout == "ok"

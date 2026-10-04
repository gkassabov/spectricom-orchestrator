# filename: tests/test_timeout_hold.py
"""Tests for ORCH-TIMEOUT-HOLD-1 — a route killed mid-work never merges.

S7-CORE-16 · Bug Registry v1-58 [ORCH-TIMEOUT-HOLD-1] P1 · [TONI-BACKGROUND-EXIT] second door.
`Status.PASSED if (ec == 0 or _produced_work)` let a route that fire_toni killed at its timeout
(ec -1), or that errored (ec -2), reach the gates and merge whatever half-done tree it left, as
long as it left one. P-MERGE: merged(r) ⇒ ec(r) == 0 ∧ handback(r) CLEAN ∧ gates(r) PASS.

  AC-TH-01  red first: a timed-out executor with work → INCOMPLETE(timeout), no gate, no merge
            (spies on run_pre_merge_gates, on `git merge` and on retire_batch_file — not log greps)
  AC-TH-02  fire_toni's timeout and error paths write the trailer (the REAL fire_toni, a fake claude)
  AC-TH-03  the queue: the orchestrator process exits 1 for INCOMPLETE; the daemon files it failed/

No test calls the real `claude`, touches the live running.json or writes under the live logs/.
Module-level imports are existing symbols only, so the red run fails on assertions.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
import queue_daemon

RULE = "=" * 60
INCOMPLETE_TIMEOUT = getattr(orchestrator, "INCOMPLETE_TIMEOUT_VERDICT", "INCOMPLETE(timeout)")
INCOMPLETE_ERROR = getattr(orchestrator, "INCOMPLETE_EXECUTOR_ERROR_VERDICT", "INCOMPLETE(executor-error)")


# ═══════════════════════════════════════════════════════
# ROUTE HARNESS — the tests/test_handback_guard.py shape (copied on purpose)
# ═══════════════════════════════════════════════════════
def _git(cmd: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)


def _sha(rev: str, cwd: Path) -> str:
    return _git(f"git rev-parse {rev}", cwd).stdout.strip()


class Route:
    def __init__(self, proj: Path, brief: Path):
        self.proj, self.brief = proj, brief
        self.branch = f"orch-{brief.stem}"
        self.gate_calls, self.merges, self.retired = [], [], []


@pytest.fixture
def route(tmp_path, monkeypatch):
    proj = tmp_path / "repo"
    proj.mkdir()
    for c in ("git init", "git config user.email t@t", "git config user.name t",
              "git symbolic-ref HEAD refs/heads/main"):
        _git(c, proj)
    (proj / "README.md").write_text("init\n")
    (proj / "briefs").mkdir()
    brief = proj / "briefs" / "batch-th.md"
    brief.write_text("- id: B1\n  title: demo\n")
    _git("git add -A", proj)
    _git('git commit -m "init"', proj)
    r = Route(proj, brief)

    real_run = subprocess.run

    def _spy_run(cmd, *a, **k):
        if isinstance(cmd, str) and cmd.startswith("git merge ") and "--abort" not in cmd:
            r.merges.append(cmd)
        return real_run(cmd, *a, **k)

    def _gate(repo_path, branch_name=None):
        r.gate_calls.append(branch_name)
        return orchestrator.GateVerdict(outcome=orchestrator.GateOutcome.PASS, gate="build", signal=None)

    monkeypatch.setattr(orchestrator, "PROJECT_ROOT", proj)
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG", {"briefs_subdir": "briefs"})
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "testrepo")
    monkeypatch.setattr(orchestrator, "BRANCH_PREFIX", "orch")
    monkeypatch.setattr(orchestrator, "MERGE_TARGET", "main")
    monkeypatch.setattr(orchestrator, "IS_META_FIRE", False)
    monkeypatch.setattr(orchestrator, "RUN_PLAYWRIGHT", False)
    monkeypatch.setattr(orchestrator, "SIT_ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
    monkeypatch.setattr(orchestrator, "notify", lambda res: None)
    monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
    monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "run_pre_merge_gates", _gate)
    monkeypatch.setattr(orchestrator, "retire_batch_file", lambda bf: r.retired.append(bf.name))
    monkeypatch.setattr(orchestrator.subprocess, "run", _spy_run)
    monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
    return r


def _toni_log(tmp_path: Path, output: str, trailer: str = "") -> str:
    p = tmp_path / "logs" / "toni-batch-th.log"
    p.parent.mkdir(exist_ok=True)
    p.write_text(f"=== TONI EXECUTION ===\nBatch: batch-th.md\nStarted: 2026-09-28T00:00:00\nCommand: claude\n"
                 f"{RULE}\n\n{output}\n{trailer}")
    return str(p)


def fire(route, monkeypatch, tmp_path, ec, work="commit", output="Implemented half of it."):
    """One route through _run_batch_inner: the fake executor leaves `work` and exits `ec`."""
    def _toni(target, proj):
        if work == "commit":
            (proj / "feature.txt").write_text("half\n")
            _git("git add -A", proj)
            _git('git commit -m "feat: half"', proj)
        elif work == "uncommitted":
            (proj / "feature.txt").write_text("half, uncommitted\n")
        return ec, _toni_log(tmp_path, output)
    monkeypatch.setattr(orchestrator, "fire_toni", _toni)
    return orchestrator._run_batch_inner(route.brief, route.proj, orchestrator.datetime.now(), worktree=None)


def _no_gate_no_merge(route, main_before):
    assert route.gate_calls == [], "no gate may run on an INCOMPLETE route"
    assert route.merges == [], f"no merge may be attempted: {route.merges}"
    assert route.retired == [], "an unmerged brief is not retired"
    assert _sha("main", route.proj) == main_before, "MERGE_TARGET moved"
    tip = _sha(f"refs/heads/{route.branch}", route.proj)
    assert tip and _git(f"git show {tip}:feature.txt", route.proj).returncode == 0, "the branch keeps the work"


# ═══════════════════════════════════════════════════════
# AC-TH-01 · red first
# ═══════════════════════════════════════════════════════
class TestRedFirst:

    def test_R1_timeout_with_committed_work_is_incomplete_not_merged(self, route, monkeypatch, tmp_path):
        main_before = _sha("main", route.proj)
        r = fire(route, monkeypatch, tmp_path, -1, work="commit")
        assert r.status is orchestrator.Status.INCOMPLETE, (r.status, r.error)
        _no_gate_no_merge(route, main_before)

    def test_R2_timeout_with_uncommitted_work_is_committed_on_the_branch_not_merged(self, route, monkeypatch, tmp_path):
        main_before = _sha("main", route.proj)
        r = fire(route, monkeypatch, tmp_path, -1, work="uncommitted")
        assert r.status is orchestrator.Status.INCOMPLETE, (r.status, r.error)
        _no_gate_no_merge(route, main_before)
        assert not (route.proj / "feature.txt").exists(), "main's checkout must not carry the work"

    def test_R3_executor_error_with_work_is_incomplete_not_merged(self, route, monkeypatch, tmp_path):
        main_before = _sha("main", route.proj)
        r = fire(route, monkeypatch, tmp_path, -2, work="commit")
        assert r.status is orchestrator.Status.INCOMPLETE, (r.status, r.error)
        _no_gate_no_merge(route, main_before)


# ═══════════════════════════════════════════════════════
# AC-TH-01 · the verdict, the salvage line, the neighbours
# ═══════════════════════════════════════════════════════
class TestVerdict:

    def test_timeout_verdict_names_branch_and_salvage_command(self, route, monkeypatch, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(route, monkeypatch, tmp_path, -1)
        assert r.error.startswith(f"{INCOMPLETE_TIMEOUT} — ")
        assert f"cd {route.proj} && git log --oneline main..{route.branch}" in r.error
        assert r.gate_outcome is None and r.exit_code == -1
        final = [m.getMessage() for m in caplog.records if "FINAL STATUS" in m.getMessage()]
        assert final == [f"🏁 FINAL STATUS: incomplete | gate: not run ({INCOMPLETE_TIMEOUT} — exit -1)"]
        note = _git(f"git notes show refs/heads/{route.branch}", route.proj).stdout
        assert note.startswith(f"EXECUTOR EXIT: {INCOMPLETE_TIMEOUT} — exit -1")
        assert "treating as PASSED" not in caplog.text

    @pytest.mark.parametrize("ec", [-2, 1, -9], ids=["error", "nonzero-exit", "signal"])
    def test_any_other_nonzero_exit_is_executor_error(self, route, monkeypatch, tmp_path, ec):
        r = fire(route, monkeypatch, tmp_path, ec)
        assert r.status is orchestrator.Status.INCOMPLETE
        assert r.error.startswith(f"{INCOMPLETE_ERROR} — executor exit {ec}")
        assert route.gate_calls == [] and route.merges == []

    def test_the_handback_guard_is_not_asked_about_a_killed_route(self, route, monkeypatch, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            fire(route, monkeypatch, tmp_path, -1, output="The re-run is going in the background.")
        assert "🛡 handback-guard:" not in caplog.text, "not engaged: the exit code already decided"

    def test_nonzero_without_work_is_still_failed(self, route, monkeypatch, tmp_path):
        r = fire(route, monkeypatch, tmp_path, -1, work=None)
        assert r.status is orchestrator.Status.FAILED
        assert route.gate_calls == [] and route.merges == []

    def test_exit_zero_is_unchanged_gated_once_and_merged(self, route, monkeypatch, tmp_path):
        main_before = _sha("main", route.proj)
        r = fire(route, monkeypatch, tmp_path, 0, output="All done. Committed.")
        assert r.status is orchestrator.Status.PASSED
        assert len(route.gate_calls) == 1 and len(route.merges) == 1
        assert _sha("main", route.proj) != main_before

    def test_verdicts_are_distinct(self):
        vs = {orchestrator.INCOMPLETE_TIMEOUT_VERDICT, orchestrator.INCOMPLETE_EXECUTOR_ERROR_VERDICT,
              orchestrator.INCOMPLETE_VERDICT, orchestrator.TAMPER_VERDICT, orchestrator.MERGE_CONFLICT_VERDICT,
              *(g.value for g in orchestrator.GateOutcome)}
        assert len(vs) == 8
        assert (orchestrator.INCOMPLETE_TIMEOUT_VERDICT, orchestrator.INCOMPLETE_EXECUTOR_ERROR_VERDICT) == \
            ("INCOMPLETE(timeout)", "INCOMPLETE(executor-error)")


def test_meta_fire_lane_withholds_the_self_mod_merge(route, monkeypatch, tmp_path, caplog):
    caplog.set_level("INFO", logger="orch")
    monkeypatch.setattr(orchestrator, "IS_META_FIRE", True)
    monkeypatch.setattr(orchestrator, "ORCH_DIR", route.proj)
    monkeypatch.setattr(orchestrator, "PREFIRE_BYPASS", True)
    for name in ("write_running", "clear_running", "_write_running_marker", "_clear_running_marker"):
        monkeypatch.setattr(orchestrator, name, lambda *a, **k: None)
    merges, seen = [], {}

    def _toni(target, proj):
        seen["wt"] = proj
        (proj / "feature.txt").write_text("half\n")
        _git("git add -A", proj)
        _git('git commit -m "feat: half"', proj)
        return -1, _toni_log(tmp_path, "Implemented half of it.")

    monkeypatch.setattr(orchestrator, "fire_toni", _toni)
    monkeypatch.setattr(orchestrator, "_self_mod_auto_merge", lambda *a, **k: merges.append(a) or True)
    try:
        r = orchestrator.run_batch(route.brief)
        assert r.status is orchestrator.Status.INCOMPLETE, (r.status, r.error)
        assert route.gate_calls == [] and merges == []
        withheld = [m.getMessage() for m in caplog.records if "Self-mod merge WITHHELD" in m.getMessage()]
        assert len(withheld) == 1 and INCOMPLETE_TIMEOUT in withheld[0]
        assert f"git log --oneline main..orch-{route.brief.stem}" in r.error
    finally:
        if "wt" in seen:
            _git(f"git worktree remove --force {seen['wt']}", route.proj)


# ═══════════════════════════════════════════════════════
# AC-TH-02 · the trailer — the REAL fire_toni against a fake `claude`
# ═══════════════════════════════════════════════════════
@pytest.fixture
def toni(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(f"#!{sys.executable}\nimport time\nprint('started the work', flush=True)\ntime.sleep(30)\n")
    fake.chmod(0o755)
    logs = tmp_path / "logs"
    logs.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    brief = proj / "brief.md"
    brief.write_text("# a brief\n")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(orchestrator, "ensure_log_subdir", lambda _s: logs)
    monkeypatch.setattr(orchestrator, "RUNNING_FILE", tmp_path / "running.json")
    monkeypatch.setattr(orchestrator, "TONI_TIMEOUT", 1)
    # fire_toni's 3 s grace between SIGTERM and SIGKILL is skipped; both signals are still sent
    import time as real_time
    clock = {n: getattr(real_time, n) for n in dir(real_time) if not n.startswith("_")}
    monkeypatch.setattr(orchestrator, "time", types.SimpleNamespace(**{**clock, "sleep": lambda s: None}))
    return lambda: orchestrator.fire_toni(brief, proj)


def _trailer(log_path: str) -> list:
    lines = Path(log_path).read_text().splitlines()
    at = max(i for i, l in enumerate(lines) if l == RULE)
    return lines[at:]


class TestTrailer:

    def test_timeout_path_writes_exit_minus_1(self, toni):
        ec, log_path = toni()
        assert ec == -1
        tail = _trailer(log_path)
        assert tail[1].startswith("Finished: 20"), tail
        assert re.fullmatch(r"Exit: -1 \(TIMEOUT after \d+m — SIGTERM, SIGKILL\)", tail[2]), tail
        assert "started the work" in Path(log_path).read_text()

    def test_error_path_writes_exit_minus_2(self, toni, monkeypatch):
        def _boom(*a, **k):
            raise OSError("spawn refused")
        monkeypatch.setattr(orchestrator.subprocess, "Popen", _boom)
        ec, log_path = toni()
        assert ec == -2
        tail = _trailer(log_path)
        assert tail[1].startswith("Finished: 20"), tail
        assert tail[2] == "Exit: -2 (OSError: spawn refused)", tail

    def test_the_trailer_ends_the_executor_output_for_the_guard(self, toni):
        from canon_assert import check_handback_invariants, load_outstanding_work_rules
        _, log_path = toni()
        rules = load_outstanding_work_rules(orchestrator.HANDBACK_GUARD_CONFIG)
        assert check_handback_invariants(Path(log_path), rules) == []


# ═══════════════════════════════════════════════════════
# AC-TH-03 · the queue
# ═══════════════════════════════════════════════════════
def test_orchestrator_process_exits_1_for_incomplete(tmp_path, monkeypatch):
    brief = tmp_path / "q.md"
    brief.write_text("- id: B1\n  title: demo\n")
    now = orchestrator.datetime.now().isoformat()
    monkeypatch.setattr(orchestrator, "run_batch", lambda bf, worktree=None: orchestrator.Result(
        batch_file=bf.name, status=orchestrator.Status.INCOMPLETE, started=now, finished=now,
        duration_s=0.0, exit_code=-1, briefs=1, error=f"{INCOMPLETE_TIMEOUT} — executor exit -1"))
    monkeypatch.setattr(orchestrator, "_check_stale_marker", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator, "approval_gate", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator, "rate_check", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator, "load_state", lambda: {"completed": [], "failed": []})
    monkeypatch.setattr(orchestrator, "save_state", lambda s: None)
    # main() re-points the module at the named repo; every global set_active_repo writes is restored
    for g in ("ACTIVE_REPO_NAME", "ACTIVE_REPO_CONFIG", "PROJECT_ROOT", "YORSIE_DIR", "BRIEFS_DIR",
              "WORKTREE_BASE", "BRANCH_PREFIX", "MERGE_TARGET", "REMOTE", "LOG_SUBDIR", "WORKTREE_MODE",
              "TEST_CMD", "IS_META_FIRE", "TONI_MODEL", "TONI_EFFORT"):
        monkeypatch.setattr(orchestrator, g, getattr(orchestrator, g))
    monkeypatch.setattr(sys, "argv", ["orchestrator.py", "run", str(brief), "--approve", "--repo", "orchestrator"])
    with pytest.raises(SystemExit) as e:
        orchestrator.main()
    assert e.value.code == 1


def test_queue_files_an_exit_1_route_as_failed_and_pauses(tmp_path, monkeypatch):
    """The daemon's existing exit-code path, driven by a stand-in orchestrator that exits the code
    the real one returns for INCOMPLETE."""
    orch = tmp_path / "orch"
    orch.mkdir()
    (orch / "orchestrator.py").write_text("import sys\nprint('FINAL STATUS: incomplete')\nsys.exit(1)\n")
    queue = orch / "queue"
    queue.mkdir()
    cfg = tmp_path / "repos.yaml"
    not_git = tmp_path / "not-a-repo"
    not_git.mkdir()
    cfg.write_text(yaml.safe_dump({"repos": {"r": {"project_dir": str(not_git)}}}))
    for name, val in (("ORCH_DIR", orch), ("QUEUE_DIR", queue), ("QUEUE_DONE", queue / "done"),
                      ("QUEUE_FAILED", queue / "failed"), ("QUEUE_STATE", tmp_path / "queue-state.json"),
                      ("REPOS_CONFIG", cfg), ("LOG_DIR", tmp_path / "logs")):
        monkeypatch.setattr(queue_daemon, name, val)
    d = queue_daemon.QueueDaemon()
    d.start_running = True  # ORCH-CONTROL-SCOPE-1 C2: these tests fire at start, as --start-running does
    d.config.update(repo="r", cooldown_seconds=0, timeout_seconds=15, model="m", effort="e", stop_on_failure=True)
    (queue / "b.md").write_text("#!queue repo=r\n\n# b\n")

    def _sleep(_s):
        d.status = "stopped"
    monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep, time=__import__("time").time))
    d.run_loop()
    assert (queue / "failed" / "b.md").exists() and not (queue / "b.md").exists()
    assert [e["exit_code"] for e in d.failed] == [1]

# filename: tests/test_crash_prefire_h3.py
"""[ORCH-CRASH-PRIMARY-ON-ROUTE-BRANCH-1] + [ORCH-PREFIRE-ALLOWED-H3-MISSED-1] Kanban 697 (D-S7CORE53-09) — predicates
P-A1..P-A6c (Part A: at daemon start, a dead route's clean tree on its own branch goes back to the merge target, unless
its executor still works in it) and P-B1..P-B6b (Part B: prefire reads an ALLOWED FILES list under a heading of any
depth ## … ######) of briefs/697-708-orch-crash-prefire-bundle-1.md. Rigs: the DeadRoute scratch repo of
tests/test_control_scope.py and the tmp_path canon of tests/test_opex_prefire.py."""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from test_control_scope import TS, DeadRoute, _git, _sha  # noqa: E402

TAG = "[QUEUE] 🛡 dead-route-recovery: clinical-mp —"
ROUTE = "101-clip-truth-2"


@pytest.fixture
def dead(tmp_path, monkeypatch):
    return DeadRoute(tmp_path, monkeypatch)


def _lines(out: str) -> list:
    return [l for l in out.splitlines() if "🛡 dead-route-recovery:" in l]


def _branches(repo: Path) -> list:
    return _git("git branch --format='%(refname:short)'", repo).stdout.split()


def _start(dead) -> None:
    dead.lock()
    dead.daemon.stop_after(1)
    dead.daemon.d.run_loop()


def _assert_returned_to_main(dead, out: str) -> None:
    """P-A1's outcome: on main, the route branch renamed `<branch>-died-<TS>` at its tip, no stash, clean, one line."""
    assert _git("git symbolic-ref HEAD", dead.repo).stdout.strip() == "refs/heads/main"
    renamed = [b for b in _branches(dead.repo) if b.startswith(dead.BRANCH)]
    assert len(renamed) == 1 and re.fullmatch(rf"{dead.BRANCH}-died-{TS}", renamed[0]), renamed
    assert _sha(renamed[0], dead.repo) == dead.branch_tip, "the branch is renamed, its commits kept"
    assert _git("git stash list", dead.repo).stdout == "", "nothing to stash"
    assert _git("git status --porcelain", dead.repo).stdout == ""
    assert _lines(out) == [
        f"{TAG} {dead.repo} was clean on {ROUTE}'s branch {dead.BRANCH} (tip {dead.branch_tip[:12]}); "
        f"branch {dead.BRANCH} → {renamed[0]}; main checked out in {dead.repo}"]
    assert dead.daemon.state()["daemon_status"] == "running"


class _Holder:
    """A process working in `cwd` whose argv[0] is `argv0`: `claude` stands in for an orphaned executor (fire_toni's
    `stdbuf -oL claude …`), `node` for any other process (the SCA dev server). Killed at exit."""

    def __init__(self, cwd: Path, argv0: str):
        self.p = subprocess.Popen(["bash", "-c", f"exec -a {argv0} sleep 60"], cwd=str(cwd))
        self.pid = self.p.pid
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:          # wait for bash's exec: until then argv[0] is `bash`
            try:
                if Path(f"/proc/{self.pid}/cmdline").read_bytes().split(b"\0")[0] == argv0.encode():
                    return
            except OSError:
                pass
            time.sleep(0.02)
        self.kill()
        raise AssertionError(f"holder {self.pid} never showed argv[0] {argv0}")

    def kill(self):
        self.p.kill()
        self.p.wait()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.kill()


# ── Part A ───────────────────────────────────────────────────────────────────
def test_P_A1_a_clean_tree_on_the_dead_routes_branch_goes_back_to_main(dead, capsys):
    """The 592 case (11-13): Toni's work committed, the route died mid-gate, the tree clean on the route branch."""
    _start(dead)
    _assert_returned_to_main(dead, capsys.readouterr().out)


def test_P_A2_a_clean_tree_on_another_branch_is_left_and_said(dead, capsys):
    _git("git checkout -qb someone-elses", dead.repo)
    dead.lock()
    before = dead.snapshot()
    dead.daemon.stop_after(1)
    dead.daemon.d.run_loop()
    assert dead.snapshot() == before, "nothing in the tree, the stash list or the branches moved"
    assert _lines(capsys.readouterr().out) == [
        f"{TAG} {dead.repo} is clean on someone-elses, not on {ROUTE}'s branch {dead.BRANCH} or main; left as it is"]
    assert dead.daemon.state()["daemon_status"] == "running"


def test_P_A3_control_a_clean_tree_on_main_is_left_silently(dead, capsys):
    _git("git checkout -q main", dead.repo)
    dead.lock()
    before = dead.snapshot()
    dead.daemon.stop_after(1)
    dead.daemon.d.run_loop()
    assert dead.snapshot() == before
    assert _lines(capsys.readouterr().out) == []
    assert dead.daemon.state()["daemon_status"] == "running"


def test_P_A4_a_failed_checkout_pauses_the_start(dead, capsys):
    (dead.daemon.tmp / "repos.yaml").write_text(yaml.safe_dump({"repos": {"clinical-mp": {
        "project_dir": str(dead.repo), "merge_target": "no-such-target", "branch_prefix": "orch-mp"}}}))
    _start(dead)
    st = dead.daemon.state()
    assert (st["daemon_status"], st["paused_reason"]) == ("paused", "start:route-branch:clinical-mp")
    out = capsys.readouterr().out
    assert ("[QUEUE] 🛡 start: PAUSED (start:route-branch:clinical-mp) — a dead route's repo is on its route branch "
            "and could not be returned to its merge target; nothing fires until `python3 queue_daemon.py resume`") in out
    lines = _lines(out)
    assert len(lines) == 1 and lines[0].startswith(
        f"{TAG} {dead.repo} is clean on {ROUTE}'s branch {dead.BRANCH}; the checkout failed ("), lines
    assert lines[0].endswith(" — PAUSED (start:route-branch:clinical-mp)"), lines
    renamed = [b for b in _branches(dead.repo) if b.startswith(dead.BRANCH)]
    assert len(renamed) == 1 and _sha(renamed[0], dead.repo) == dead.branch_tip, "nothing lost"


def test_P_A5_control_a_live_route_is_not_touched(dead):
    dead.lock(pid=os.getpid())
    before = dead.snapshot()
    dead.daemon.stop_after(1)
    dead.daemon.d.run_loop()
    assert dead.snapshot() == before and dead.marker.exists()


def test_P_A5b_control_a_worktree_route_is_not_the_main_checkouts(dead):
    dead.lock(route_worktree=str(dead.repo.parent / "elsewhere"))
    before = dead.snapshot()
    dead.daemon.stop_after(1)
    dead.daemon.d.run_loop()
    assert dead.snapshot() == before


def test_P_A6_a_live_executor_in_the_tree_pauses_and_nothing_moves(dead, capsys):
    """fire_toni starts the executor under setsid: it outlives an orchestrator killed alone, whose marker pid is then
    dead. Its tree is not moved under it."""
    with _Holder(dead.repo, "claude") as h:
        _start(dead)
        assert _git("git symbolic-ref HEAD", dead.repo).stdout.strip() == f"refs/heads/{dead.BRANCH}"
        assert [b for b in _branches(dead.repo) if b.startswith(dead.BRANCH)] == [dead.BRANCH], "no rename"
        assert _git("git stash list", dead.repo).stdout == ""
        st = dead.daemon.state()
        assert (st["daemon_status"], st["paused_reason"]) == ("paused", "start:route-branch:clinical-mp")
        out = capsys.readouterr().out
        assert _lines(out) == [
            f"{TAG} {dead.repo} is clean on {ROUTE}'s branch {dead.BRANCH}, but pid {h.pid} (claude 60) still works "
            f"in it; left as it is — PAUSED (start:route-branch:clinical-mp)"]
        assert "PAUSED (start:route-branch:clinical-mp) — a dead route's repo is on its route branch" in out


def test_P_A6b_an_executor_in_a_sibling_dir_with_the_same_prefix_is_not_in_the_tree(dead, capsys):
    sib = dead.repo.parent / (dead.repo.name + "-wt")
    sib.mkdir()
    with _Holder(sib, "claude"):
        _start(dead)
        _assert_returned_to_main(dead, capsys.readouterr().out)


def test_P_A6c_a_non_executor_process_in_the_tree_does_not_hold_it(dead, capsys):
    """The SCA dev server (spectricom-up.sh) starts in ~/spectricom-clinical-mp every 10 min: not an executor."""
    with _Holder(dead.repo, "node"):
        _start(dead)
        _assert_returned_to_main(dead, capsys.readouterr().out)

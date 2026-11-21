# filename: tests/test_merge_checkout_held.py
"""Tests for ORCH-MERGE-CHECKOUT-SILENT-1 (Kanban 802) — the main-checkout lane's merge step must not
go on when `git checkout <MERGE_TARGET>` is refused.

The incident (clinical-mp, route 628 PHI-EGRESS-ALLOWLIST-1 first run, 2026-11-19 19:0x ET): the gate
passed, `git checkout main` was refused because an authoring worktree had `main` checked out, the exit
was not read, `git merge <branch>` then ran ON THE ROUTE BRANCH ("Already up to date", exit 0), and only
the late tip check (OBS-S6S17-02) caught it — as a FAILED run with no error text naming the cause.

The fixture: during the gate window a second worktree checks out `main` and stays — exactly the 628 shape.

  MC-1 (RED)     the run is FAILED with a NOT LANDED error that names the checkout holding main
  MC-2 (RED)     the log names the refused checkout, and the merge step is never reached (no "Merge reported
                 success but … tip unchanged" — that line is the late check catching a merge run on the route branch)
  MC-3           main is untouched and the route branch is preserved at its tip
  MC-4 (control) with main free, the route merges as before

The harness is test_merge_conflict.py's, copied on purpose (that file is not edited).
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
from canon_assert import QueueRepo

NOT_LANDED = getattr(orchestrator, "ROUTE_NOT_LANDED_VERDICT", "NOT LANDED")


def _git(cmd: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)


def _sha(rev: str, cwd: Path) -> str:
    return _git(f"git rev-parse {rev}", cwd).stdout.strip()


def _init_repo(path: Path):
    _git("git init", path)
    _git("git config user.email test@test.com", path)
    _git("git config user.name Test", path)
    _git("git symbolic-ref HEAD refs/heads/main", path)
    (path / "README.md").write_text("init\n")
    _git("git add -A", path)
    _git('git commit -m "init"', path)


class Route:
    def __init__(self, proj: Path, brief: Path):
        self.proj = proj
        self.brief = brief
        self.branch = f"orch-{brief.stem}"
        self.repo = QueueRepo("testrepo", proj, "main", "orch")
        self.route_tip = None
        self.main_before = None
        self.holder = None
        self.result = None


@pytest.fixture
def route(tmp_path, monkeypatch):
    proj = tmp_path / "repo"
    proj.mkdir()
    _init_repo(proj)
    briefs_dir = proj / "briefs"
    briefs_dir.mkdir()
    brief = briefs_dir / "batch-mc.md"
    brief.write_text("- id: B1\n  title: demo\n\n## Estimated runtime: 45-75 min\n")
    _git("git add -A", proj)
    _git('git commit -m "chore(briefs): stage batch-mc"', proj)

    monkeypatch.setattr(orchestrator, "PROJECT_ROOT", proj)
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG", {"briefs_subdir": "briefs"})
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "testrepo")
    monkeypatch.setattr(orchestrator, "BRANCH_PREFIX", "orch")
    monkeypatch.setattr(orchestrator, "MERGE_TARGET", "main")
    monkeypatch.setattr(orchestrator, "IS_META_FIRE", False)
    monkeypatch.setattr(orchestrator, "RUN_PLAYWRIGHT", False)
    monkeypatch.setattr(orchestrator, "SIT_ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
    monkeypatch.setattr(orchestrator, "notify", lambda r: None)
    monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
    monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
    monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
    return Route(proj, brief)


def fire(route, monkeypatch, main_held: bool):
    """One route through _run_batch_inner with a fake PASS gate. With main_held, an authoring
    worktree checks out main during the gate window and keeps it."""

    def _fake_gate(repo_path, branch_name=None):
        route.route_tip = _sha("HEAD", route.proj)
        route.main_before = _sha("main", route.proj)
        if main_held:
            route.holder = route.proj.parent / "authoring-wt"
            assert _git(f"git worktree add {route.holder} main", route.proj).returncode == 0
        return orchestrator.GateVerdict(outcome=orchestrator.GateOutcome.PASS, gate="build", signal=None)

    def _works(proj):
        (proj / "feature.txt").write_text("work\n")
        _git("git add -A", proj)
        _git('git commit -m "feat: work"', proj)
        return 0

    def _toni(target, proj):
        log = route.proj.parent / "toni-test.log"
        log.write_text(f"=== TONI EXECUTION ===\n{'=' * 60}\n\nDone.\n\n{'=' * 60}\nExit: 0\n")
        return _works(proj), str(log)

    monkeypatch.setattr(orchestrator, "run_pre_merge_gates", _fake_gate)
    monkeypatch.setattr(orchestrator, "fire_toni", _toni)
    route.result = orchestrator._run_batch_inner(route.brief, route.proj, orchestrator.datetime.now(), worktree=None)
    return route.result


class TestMergeCheckoutHeld:

    def test_mc1_failed_not_landed_names_the_holder(self, route, monkeypatch, caplog):
        with caplog.at_level("INFO"):
            r = fire(route, monkeypatch, main_held=True)
        print(f"[MC-1] status {r.status} · error {r.error!r}")
        assert r.status is orchestrator.Status.FAILED
        assert r.error is not None and NOT_LANDED in r.error
        assert str(route.holder) in r.error

    def test_mc2_refused_checkout_named_merge_never_reached(self, route, monkeypatch, caplog):
        with caplog.at_level("INFO"):
            fire(route, monkeypatch, main_held=True)
        late = [m for m in (rec.getMessage() for rec in caplog.records) if "Merge reported success" in m]
        named = [m for m in (rec.getMessage() for rec in caplog.records) if "could not check out main" in m]
        print(f"[MC-2] late-check lines {len(late)} · refused-checkout lines {len(named)}")
        assert late == []
        assert named, "the refusal is named in the log"

    def test_mc3_main_untouched_branch_preserved(self, route, monkeypatch):
        fire(route, monkeypatch, main_held=True)
        assert _sha("main", route.proj) == route.main_before
        assert _sha(f"refs/heads/{route.branch}", route.proj) == route.route_tip

    def test_mc4_control_main_free_merges(self, route, monkeypatch, caplog):
        with caplog.at_level("INFO"):
            r = fire(route, monkeypatch, main_held=False)
        assert r.status is orchestrator.Status.PASSED
        assert f"🔀 Merged {route.branch}" in caplog.text
        assert _sha("main", route.proj) == route.route_tip

# filename: tests/test_merge_conflict.py
"""Tests for ORCH-CONFLICT-1 — a conflicted merge is never `passed`.

S7-CORE-15. The incident (clinical-mp, L-UI-SAFETY-1 attempt 2, 2026-09-21 02:27:25): the
pre-merge gate said PASS, `git merge` conflicted, and the run still printed
`FINAL STATUS: passed` and notified `✅ … passed`. Nobody ran `git merge --abort`.

The conflict is injected by the fake gate: while the route branch is checked out it advances
main with a conflicting commit to feature.txt (through a throwaway worktree, removed again so
the orchestrator's own `git checkout main` succeeds), then returns PASS. That is main moving
during the gate window, the shape ORCH-STALEBASE-1 leaves reachable.

  AC-CF-01  the defect, red before green (the three TestConflictedMerge tests)
  AC-CF-02  the green path is unchanged
  AC-CF-03  _run_batch_inner is the non-test caller of check_route_landed_invariants
  AC-CF-04  the invariant is acted on, not just logged

Module-level imports are existing symbols only, so this file collects on code that predates
ORCH-CONFLICT-1. Tests that spy on the new predicate skip there.
"""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
from canon_assert import QueueRepo

MERGE_CONFLICT = getattr(orchestrator, "MERGE_CONFLICT_VERDICT", "MERGE CONFLICT")
needs_predicate = pytest.mark.skipif(
    not hasattr(orchestrator, "check_route_landed_invariants"),
    reason="predates ORCH-CONFLICT-1: orchestrator has no check_route_landed_invariants")


# ═══════════════════════════════════════════════════════
# HARNESS — the test_stale_base.py shape, copied on purpose (that file is not edited)
# ═══════════════════════════════════════════════════════
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
        self.route_tip = None     # the route branch's tip as the gate saw it
        self.main_after_gate = None
        self.result = None


@pytest.fixture
def route(tmp_path, monkeypatch):
    proj = tmp_path / "repo"
    proj.mkdir()
    _init_repo(proj)
    briefs_dir = proj / "briefs"
    briefs_dir.mkdir()
    brief = briefs_dir / "batch-cf.md"
    brief.write_text("- id: B1\n  title: demo\n\n## Estimated runtime: 45-75 min\n")
    _git("git add -A", proj)
    _git('git commit -m "chore(briefs): stage batch-cf"', proj)

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


def _advance_main_underneath(proj: Path):
    """Commit a conflicting feature.txt on main WITHOUT leaving the route branch: through a
    worktree, which is then removed — a live worktree on main would make the orchestrator's
    `git checkout main` fail."""
    wt = proj.parent / "mainwt"
    assert _git(f"git worktree add {wt} main", proj).returncode == 0
    (wt / "feature.txt").write_text("main moved while the gate ran\n")
    _git("git add -A", wt)
    assert _git('git commit -m "main: someone else landed first"', wt).returncode == 0
    assert _git(f"git worktree remove {wt}", proj).returncode == 0


def fire(route, monkeypatch, executor, main_moves: bool = False):
    """Run one route through _run_batch_inner with a fake PASS gate. With main_moves, the gate
    window is where main advances under the route."""

    def _fake_gate(repo_path, branch_name=None):
        route.route_tip = _sha("HEAD", route.proj)
        if main_moves:
            _advance_main_underneath(route.proj)
        route.main_after_gate = _sha("main", route.proj)
        return orchestrator.GateVerdict(outcome=orchestrator.GateOutcome.PASS, gate="build", signal=None)

    def _toni(target, proj):
        return executor(proj), "toni-test.log"

    monkeypatch.setattr(orchestrator, "run_pre_merge_gates", _fake_gate)
    monkeypatch.setattr(orchestrator, "fire_toni", _toni)
    route.result = orchestrator._run_batch_inner(
        route.brief, route.proj, orchestrator.datetime.now(), worktree=None
    )
    return route.result


def works(proj):
    """A commit on the route's own branch, touching feature.txt."""
    (proj / "feature.txt").write_text("work\n")
    _git("git add -A", proj)
    _git('git commit -m "feat: work"', proj)
    return 0


def quiet(proj):
    """Ran, chose to change nothing, stayed on its own branch."""
    return 0


def _final_status(caplog) -> str:
    lines = [r.getMessage() for r in caplog.records if "FINAL STATUS" in r.getMessage()]
    assert len(lines) == 1, lines
    return lines[0]


# ═══════════════════════════════════════════════════════
# AC-CF-01 — the defect, red before green
# ═══════════════════════════════════════════════════════
class TestConflictedMerge:

    def test_conflicted_merge_is_not_passed(self, route, monkeypatch, caplog):
        with caplog.at_level("INFO"):
            r = fire(route, monkeypatch, works, main_moves=True)
        assert "Merge conflict on" in caplog.text, "the fixture must actually conflict"
        assert r.status is orchestrator.Status.FAILED
        line = _final_status(caplog)
        assert "FINAL STATUS: passed" not in line
        assert MERGE_CONFLICT in line

    def test_conflicted_merge_leaves_the_target_as_it_found_it(self, route, monkeypatch):
        fire(route, monkeypatch, works, main_moves=True)
        assert _sha("main", route.proj) == route.main_after_gate
        assert _git("git rev-parse -q --verify MERGE_HEAD", route.proj).returncode != 0, "repo left mid-merge"
        assert _git("git status --porcelain", route.proj).stdout.strip() == ""

    def test_conflicted_merge_preserves_the_branch_and_names_the_files(self, route, monkeypatch):
        r = fire(route, monkeypatch, works, main_moves=True)
        assert _sha(f"refs/heads/{route.branch}", route.proj) == route.route_tip
        assert r.error is not None
        assert MERGE_CONFLICT in r.error
        assert "feature.txt" in r.error


# ═══════════════════════════════════════════════════════
# AC-CF-02 / 03 / 04 — green path, reachability, acted on
# ═══════════════════════════════════════════════════════
@needs_predicate
class TestLandedInvariantAtFinalStatus:

    def test_green_route_is_unchanged(self, route, monkeypatch, caplog):
        """AC-CF-02: PASSED, merged, branch deleted, and the predicate said []."""
        real, returned = orchestrator.check_route_landed_invariants, []

        def _recording(*a, **k):
            returned.append(real(*a, **k))
            return returned[-1]

        with patch.object(orchestrator, "check_route_landed_invariants", wraps=_recording) as spy:
            with caplog.at_level("INFO"):
                r = fire(route, monkeypatch, works)
        assert r.status is orchestrator.Status.PASSED
        assert f"🔀 Merged {route.branch}" in caplog.text
        assert _git(f"git rev-parse -q --verify refs/heads/{route.branch}", route.proj).returncode != 0
        assert spy.call_count == 1
        assert returned == [[]]

    def test_green_route_calls_the_predicate_once_with_its_tip(self, route, monkeypatch):
        """AC-CF-03: exactly one call, with (QueueRepo, brief name, route tip)."""
        with patch.object(orchestrator, "check_route_landed_invariants",
                          wraps=orchestrator.check_route_landed_invariants) as spy:
            fire(route, monkeypatch, works)
        spy.assert_called_once_with(QueueRepo("testrepo", route.proj, "main", "orch"),
                                    "batch-cf.md", route.route_tip)

    def test_no_changes_route_never_calls_the_predicate(self, route, monkeypatch):
        """AC-CF-03: the no-changes exclusion — nothing was merged, so there is no tip to land."""
        with patch.object(orchestrator, "check_route_landed_invariants",
                          wraps=orchestrator.check_route_landed_invariants) as spy:
            r = fire(route, monkeypatch, quiet)
        assert r.status is orchestrator.Status.PASSED and r.no_changes is True
        assert spy.call_count == 0

    def test_a_violation_demotes_passed(self, route, monkeypatch, caplog):
        """AC-CF-04: a non-empty predicate result makes the run FAILED, loudly."""
        from canon_assert import UnlandedRouteViolation
        v = UnlandedRouteViolation(repo="testrepo", branch=route.branch, merge_target="main",
                                   route_tip="a" * 40, target_tip="b" * 40,
                                   landed=False, mid_merge=False)
        with patch.object(orchestrator, "check_route_landed_invariants", return_value=[v]):
            with caplog.at_level("INFO"):
                r = fire(route, monkeypatch, works)
        assert r.status is orchestrator.Status.FAILED
        assert "⛔ ORCH-CONFLICT-1 invariant:" in caplog.text
        assert "FINAL STATUS: passed" not in _final_status(caplog)

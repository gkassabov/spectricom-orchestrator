# filename: tests/test_demotion_worktree_main.py
"""DEMOTION-WORKTREE-MAIN-DETECT-1 (Kanban 938; AP-GEMMA demotion trigger (628), D-S7CORE61-04; George go by name
2026-11-24 12:56 ET, D-S7CORE62-08).

Before the gates, the main-checkout lane names a checkout other than its own that holds MERGE_TARGET, and holds the route
BLOCKED(environment): no gate is spent, nothing merges, the branch is kept. ORCH-MERGE-CHECKOUT-SILENT-1 (802,
test_merge_checkout_held.py) still refuses a merge when the holder appears DURING the gates — unchanged.

The fixture: while the executor runs (the live checkout on the route branch, main free), an authoring worktree checks out
main and stays — the 628 shape, one step earlier.

  WM-1 (RED)     the run is BLOCKED with an error naming DEMOTION-WORKTREE-MAIN and the holder's path
  WM-2 (RED)     no gate ran (run_pre_merge_gates never called); a `DEMOTION TRIGGER:` note is on the route tip
  WM-3           main is untouched and the route branch is preserved at its tip
  WM-4 (control) with main free, the route gates and merges as before
  WM-5 (control) _worktree_main_hold: none when the live checkout itself holds main, or no checkout does

The harness is test_merge_checkout_held.py's, copied on purpose (that file is not edited).
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
from canon_assert import QueueRepo


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
        self.gates = 0
        self.result = None


@pytest.fixture
def route(tmp_path, monkeypatch):
    proj = tmp_path / "repo"
    proj.mkdir()
    _init_repo(proj)
    briefs_dir = proj / "briefs"
    briefs_dir.mkdir()
    brief = briefs_dir / "batch-wm.md"
    brief.write_text("- id: B1\n  title: demo\n\n## Estimated runtime: 45-75 min\n")
    _git("git add -A", proj)
    _git('git commit -m "chore(briefs): stage batch-wm"', proj)

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
    """One route through _run_batch_inner with a fake PASS gate. With main_held, an authoring worktree checks out
    main while the executor runs (the live checkout is on the route branch) and keeps it."""

    def _fake_gate(repo_path, branch_name=None):
        route.gates += 1
        return orchestrator.GateVerdict(outcome=orchestrator.GateOutcome.PASS, gate="build", signal=None)

    def _toni(target, proj):
        (proj / "feature.txt").write_text("work\n")
        _git("git add -A", proj)
        _git('git commit -m "feat: work"', proj)
        route.route_tip = _sha("HEAD", proj)
        route.main_before = _sha("main", proj)
        if main_held:
            route.holder = route.proj.parent / "authoring-wt"
            assert _git(f"git worktree add {route.holder} main", route.proj).returncode == 0
        log = route.proj.parent / "toni-test.log"
        log.write_text(f"=== TONI EXECUTION ===\n{'=' * 60}\n\nDone.\n\n{'=' * 60}\nExit: 0\n")
        return 0, str(log)

    monkeypatch.setattr(orchestrator, "run_pre_merge_gates", _fake_gate)
    monkeypatch.setattr(orchestrator, "fire_toni", _toni)
    route.result = orchestrator._run_batch_inner(route.brief, route.proj, orchestrator.datetime.now(), worktree=None)
    return route.result


class TestDemotionWorktreeMain:

    def test_wm1_blocked_names_the_trigger_and_the_holder(self, route, monkeypatch):
        r = fire(route, monkeypatch, main_held=True)
        print(f"[WM-1] status {r.status} · error {r.error!r}")
        assert r.status is orchestrator.Status.BLOCKED
        assert r.error is not None and "DEMOTION-WORKTREE-MAIN" in r.error and str(route.holder) in r.error

    def test_wm2_no_gate_spent_and_the_tip_carries_the_note(self, route, monkeypatch):
        fire(route, monkeypatch, main_held=True)
        assert route.gates == 0
        assert "DEMOTION TRIGGER:" in _git(f"git notes show {route.route_tip}", route.proj).stdout

    def test_wm3_main_untouched_branch_preserved(self, route, monkeypatch):
        fire(route, monkeypatch, main_held=True)
        assert _sha("main", route.proj) == route.main_before
        assert _sha(f"refs/heads/{route.branch}", route.proj) == route.route_tip

    def test_wm4_control_main_free_gates_and_merges(self, route, monkeypatch, caplog):
        with caplog.at_level("INFO"):
            r = fire(route, monkeypatch, main_held=False)
        assert r.status is orchestrator.Status.PASSED and route.gates == 1
        assert _sha("main", route.proj) == route.route_tip

    def test_wm6_one_shield_line_either_way(self, route, monkeypatch, caplog):
        # [938r] P-SAY: a declared control speaks once per fire — HOLD when another checkout holds main, else CLEAN.
        with caplog.at_level("INFO"):
            fire(route, monkeypatch, main_held=True)
        held = [r.getMessage() for r in caplog.records if r.getMessage().startswith("🛡 worktree-main:")]
        assert len(held) == 1 and held[0].startswith("🛡 worktree-main: HOLD — ") and str(route.holder) in held[0]

    def test_wm7_one_clean_line_when_main_is_free(self, route, monkeypatch, caplog):
        with caplog.at_level("INFO"):
            fire(route, monkeypatch, main_held=False)
        lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("🛡 worktree-main:")]
        assert lines == ["🛡 worktree-main: CLEAN — no other checkout holds main"]

    def test_wm5_control_no_hold_when_the_live_checkout_holds_main_or_none_does(self, route, monkeypatch):
        assert orchestrator._worktree_main_hold(route.proj) is None              # the live checkout is on main
        _git("git checkout -q --detach", route.proj)
        assert orchestrator._worktree_main_hold(route.proj) is None              # no checkout holds main

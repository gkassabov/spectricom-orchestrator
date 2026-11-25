# filename: tests/test_demotion_stray_in_live.py
"""DEMOTION-STRAY-IN-LIVE-DETECT-1 (Kanban 939; AP-GEMMA demotion trigger (761) PDT-57-3, D-S7CORE61-04; George go by
name 2026-11-24 12:56 ET, D-S7CORE62-08).
Before `git add -A` sweeps the live checkout into the route, the main-checkout lane names an untracked top-level directory
its merge target's tree has no entry for and the brief's ALLOWED FILES do not name — the 761 shape, a stray `c1a435c7/`
copy — or a linked worktree under the live checkout, and holds the route BLOCKED(environment): no gate is spent, nothing
merges, the branch is kept.
  SL-1 (RED)     a stray copy directory: BLOCKED, the error names DEMOTION-STRAY-IN-LIVE and the path; no gate ran
  SL-2 (RED)     a linked worktree under the live checkout: BLOCKED, named as a linked worktree
  SL-3 (control) the route's own new directory under an existing top-level entry, and a new root FILE: gates and merges
  SL-4 (control) a new top-level directory the brief's ALLOWED FILES name: gates and merges
  SL-5 (RED)     one `🛡 stray-in-live:` line either way — HOLD with a stray, CLEAN without
The harness is test_demotion_worktree_main.py's (938r), copied on purpose (that file is not edited).
"""
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator


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
    (path / "src").mkdir()
    (path / "src" / "app.ts").write_text("export {}\n")
    _git("git add -A", path)
    _git('git commit -m "init"', path)


class Route:
    def __init__(self, proj: Path, brief: Path):
        self.proj = proj
        self.brief = brief
        self.branch = f"orch-{brief.stem}"
        self.main_before = None
        self.gates = 0
        self.result = None


@pytest.fixture
def route(tmp_path, monkeypatch):
    proj = tmp_path / "repo"
    proj.mkdir()
    _init_repo(proj)
    briefs_dir = proj / "briefs"
    briefs_dir.mkdir()
    brief = briefs_dir / "batch-sl.md"
    brief.write_text("- id: B1\n  title: demo\n\n## Estimated runtime: 45-75 min\n\n"
                     "## ALLOWED FILES\n**New (1):** `config/new.yaml`\n\n## STOP\n(a) none\n")
    _git("git add -A", proj)
    _git('git commit -m "chore(briefs): stage batch-sl"', proj)
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


def fire(route, monkeypatch, plant=None):
    """One route through _run_batch_inner with a fake PASS gate. The executor leaves its work uncommitted (the sweep
    commits it); `plant(proj)` runs while it works — an agent leaving something in the live checkout."""
    def _fake_gate(repo_path, branch_name=None):
        route.gates += 1
        return orchestrator.GateVerdict(outcome=orchestrator.GateOutcome.PASS, gate="build", signal=None)

    def _toni(target, proj):
        route.main_before = _sha("main", proj)
        (proj / "src" / "feature").mkdir()
        (proj / "src" / "feature" / "work.ts").write_text("export const work = 1\n")
        (proj / "CHANGELOG.md").write_text("a new root file\n")
        if plant:
            plant(proj)
        log = route.proj.parent / "toni-test.log"
        log.write_text(f"=== TONI EXECUTION ===\n{'=' * 60}\n\nDone.\n\n{'=' * 60}\nExit: 0\n")
        return 0, str(log)

    monkeypatch.setattr(orchestrator, "run_pre_merge_gates", _fake_gate)
    monkeypatch.setattr(orchestrator, "fire_toni", _toni)
    route.result = orchestrator._run_batch_inner(route.brief, route.proj, orchestrator.datetime.now(), worktree=None)
    return route.result


def _copy(proj: Path):
    (proj / "c1a435c7").mkdir()
    (proj / "c1a435c7" / "copy.ts").write_text("a stray copy\n")


def _shield(caplog) -> list:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("🛡 stray-in-live:")]


class TestDemotionStrayInLive:

    def test_sl1_a_stray_copy_is_blocked_before_any_gate(self, route, monkeypatch):
        r = fire(route, monkeypatch, plant=_copy)
        print(f"[SL-1] status {r.status} · error {r.error!r}")
        assert r.status is orchestrator.Status.BLOCKED
        assert r.error is not None and "DEMOTION-STRAY-IN-LIVE" in r.error and "c1a435c7/" in r.error
        assert route.gates == 0
        assert _sha("main", route.proj) == route.main_before

    def test_sl2_a_linked_worktree_under_the_live_checkout_is_blocked(self, route, monkeypatch):
        def _wt(proj):
            assert _git("git worktree add --detach agent-wt main", proj).returncode == 0
        r = fire(route, monkeypatch, plant=_wt)
        assert r.status is orchestrator.Status.BLOCKED
        assert "agent-wt/ (a linked worktree)" in r.error and route.gates == 0

    def test_sl3_control_the_route_s_own_work_gates_and_merges(self, route, monkeypatch):
        r = fire(route, monkeypatch)
        assert r.status is orchestrator.Status.PASSED and route.gates == 1
        assert (route.proj / "src" / "feature" / "work.ts").exists()
        assert _git("git show --stat --format= main", route.proj).stdout.count("CHANGELOG.md") == 1

    def test_sl4_control_a_new_top_level_dir_the_brief_names_gates_and_merges(self, route, monkeypatch):
        def _cfg(proj):
            (proj / "config").mkdir()
            (proj / "config" / "new.yaml").write_text("k: v\n")
        r = fire(route, monkeypatch, plant=_cfg)
        assert r.status is orchestrator.Status.PASSED and route.gates == 1

    def test_sl5_one_shield_line_either_way(self, route, monkeypatch, caplog):
        with caplog.at_level("INFO"):
            fire(route, monkeypatch, plant=_copy)
        held = _shield(caplog)
        assert len(held) == 1 and held[0].startswith("🛡 stray-in-live: HOLD — ") and "c1a435c7/" in held[0]

    def test_sl5b_one_clean_line_without_a_stray(self, route, monkeypatch, caplog):
        with caplog.at_level("INFO"):
            fire(route, monkeypatch)
        assert _shield(caplog) == ["🛡 stray-in-live: CLEAN — nothing outside main's tree and the brief's ALLOWED "
                                   "FILES in the live checkout"]

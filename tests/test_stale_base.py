# filename: tests/test_stale_base.py
"""Tests for ORCH-STALEBASE-1 — a re-fire cuts a fresh branch from the merge target.

S7-CORE-15 · BUG-S7CORE14-ORCH-STALEBASE-01.

The incident (clinical-mp, L-UI-SAFETY-1): attempt 1 went red and its branch was preserved on
purpose. main advanced 7 commits. Attempt 2's `git checkout -b` failed on the existing name, the
orchestrator logged `Switched to existing branch` and ran Toni on a base 7 commits behind main.
The gate measured against that base, said PASS, and the merge conflicted.

The oracle is a predicate, `check_branch_freshness_invariants`, sampled INSIDE the route at
hand-off time (the executor runs there) and in the repo after the run:
  AC-SB-01  first fire: clean
  AC-SB-02  re-fire after red gate + advanced main: clean, and the merge lands
  AC-SB-03  the stale branch is renamed, not deleted
  AC-SB-04  `Switched to existing branch` never appears
  AC-SB-05  the predicate is red on the incident shape, in isolation
  AC-SB-06  a failed retire refuses to fire
  AC-SB-07  the meta-fire worktree cut is fresh too
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
from canon_assert import QueueRepo, check_branch_freshness_invariants

NEVER = "Switched to existing branch"


# ═══════════════════════════════════════════════════════
# HARNESS — the test_route_ref_integrity.py shape, duplicated on purpose
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


def _advance_main(proj: Path, n: int, path: str = "feature.txt"):
    """Commit n times directly on main, touching `path` — the file `works` writes, so a
    3-way merge of a branch cut before these commits conflicts (attempt 2's shape)."""
    cur = _git("git symbolic-ref --quiet --short HEAD", proj).stdout.strip()
    _git("git checkout main", proj)
    for i in range(n):
        (proj / path).write_text(f"main {i}\n")
        _git("git add -A", proj)
        _git(f'git commit -m "main: advance {i}"', proj)
    if cur and cur != "main":
        _git(f"git checkout {cur}", proj)


def _stale_refs(proj: Path, branch: str) -> dict:
    out = _git(f"git for-each-ref 'refs/heads/{branch}--stale-*' --format='%(refname) %(objectname)'",
               proj).stdout
    return dict(l.split() for l in out.splitlines() if l.strip())


class Route:
    def __init__(self, proj: Path, brief: Path):
        self.proj = proj
        self.brief = brief
        self.branch = f"orch-{brief.stem}"
        self.repo = QueueRepo("testrepo", proj, "main", "orch")
        self.handoffs = []   # one dict per executor call, sampled INSIDE the route
        self.result = None

    def sample(self):
        self.handoffs.append({
            "violations": check_branch_freshness_invariants(self.repo, [self.brief.name]),
            "branch_sha": _sha(self.branch, self.proj),
            "merge_base": _git(f"git merge-base main {self.branch}", self.proj).stdout.strip(),
            "main_sha": _sha("main", self.proj),
        })


@pytest.fixture
def route(tmp_path, monkeypatch):
    proj = tmp_path / "repo"
    proj.mkdir()
    _init_repo(proj)
    briefs_dir = proj / "briefs"
    briefs_dir.mkdir()
    brief = briefs_dir / "batch-sb.md"
    brief.write_text("- id: B1\n  title: demo\n\n## Estimated runtime: 45-75 min\n")
    _git("git add -A", proj)
    _git('git commit -m "chore(briefs): stage batch-sb"', proj)

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


def fire(route, monkeypatch, executor, gate=orchestrator.GateOutcome.PASS):
    """Run one route. The executor samples the predicate at hand-off, then does its work."""

    def _fake_gate(repo_path, branch_name=None):
        return orchestrator.GateVerdict(outcome=gate, gate="build", signal=None)

    def _toni(target, proj):
        route.sample()
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


def _red_then_advance(route, monkeypatch, behind: int = 3) -> str:
    """Attempt 1 goes red (branch preserved), then main advances. Returns attempt 1's tip."""
    r1 = fire(route, monkeypatch, works, gate=orchestrator.GateOutcome.FAIL_PRODUCT)
    assert r1.status == orchestrator.Status.FAILED
    main_after_red = _sha("main", route.proj)
    attempt1_tip = _sha(route.branch, route.proj)
    assert attempt1_tip != main_after_red, "branch preserved with its commit"
    assert _sha(f"{route.branch}~1", route.proj) == main_after_red, "main untouched by a red gate"
    _advance_main(route.proj, behind)
    return attempt1_tip


def _no_adoption(caplog):
    """AC-SB-04 — over every record this test produced."""
    assert not [r.getMessage() for r in caplog.records if NEVER in r.getMessage()]


# ═══════════════════════════════════════════════════════
# AC-SB-01 · the predicate is clean on a fresh cut
# ═══════════════════════════════════════════════════════
def test_fresh_cut_is_clean(route, monkeypatch, caplog):
    caplog.set_level("INFO", logger="orch")
    main_at_fixture = _sha("main", route.proj)
    r = fire(route, monkeypatch, works)
    (h,) = route.handoffs
    assert h["violations"] == []
    assert h["branch_sha"] == main_at_fixture
    assert r.status == orchestrator.Status.PASSED
    assert f"🌿 Branch: {route.branch} (from main @ {main_at_fixture[:7]})" in caplog.text
    _no_adoption(caplog)


# ═══════════════════════════════════════════════════════
# AC-SB-02 · RED-BEFORE-GREEN: the L-UI-SAFETY-1 shape
# ═══════════════════════════════════════════════════════
def test_refire_after_red_gate_and_advanced_main_cuts_fresh(route, monkeypatch, caplog):
    caplog.set_level("INFO", logger="orch")
    _red_then_advance(route, monkeypatch, behind=3)
    main_before = _sha("main", route.proj)
    count_before = int(_git("git rev-list --count main", route.proj).stdout)

    r = fire(route, monkeypatch, works, gate=orchestrator.GateOutcome.PASS)

    h = route.handoffs[-1]
    assert h["violations"] == [], [str(v) for v in h["violations"]]
    assert h["merge_base"] == main_before == h["main_sha"]
    assert r.status == orchestrator.Status.PASSED
    assert int(_git("git rev-list --count main", route.proj).stdout) > count_before
    assert "🔀 Merged" in caplog.text
    assert "Merge conflict" not in caplog.text
    assert check_branch_freshness_invariants(route.repo, [route.brief.name]) == []
    _no_adoption(caplog)


# ═══════════════════════════════════════════════════════
# AC-SB-03 · the stale branch is retired, not deleted
# ═══════════════════════════════════════════════════════
def test_stale_branch_is_retired_not_deleted(route, monkeypatch, caplog):
    caplog.set_level("INFO", logger="orch")
    attempt1_tip = _red_then_advance(route, monkeypatch, behind=3)
    fire(route, monkeypatch, works)

    stale = _stale_refs(route.proj, route.branch)
    assert len(stale) == 1, stale
    (tip,) = stale.values()
    assert tip == attempt1_tip
    assert f"♻️  Retired stale branch {route.branch} → {route.branch}--stale-" in caplog.text
    assert "(was 3 behind main)" in caplog.text
    _no_adoption(caplog)


# ═══════════════════════════════════════════════════════
# AC-SB-04 · re-fire twice: each attempt retired, each hand-off clean
# ═══════════════════════════════════════════════════════
def test_second_refire_retires_again(route, monkeypatch, caplog):
    caplog.set_level("INFO", logger="orch")
    red = orchestrator.GateOutcome.FAIL_PRODUCT
    fire(route, monkeypatch, works, gate=red)
    tip1 = _sha(route.branch, route.proj)
    fire(route, monkeypatch, works, gate=red)          # main has NOT moved: behind == 0
    tip2 = _sha(route.branch, route.proj)
    assert "(at main tip)" in caplog.text
    _advance_main(route.proj, 2)
    r = fire(route, monkeypatch, works)

    assert r.status == orchestrator.Status.PASSED
    assert [h["violations"] for h in route.handoffs] == [[], [], []]
    stale = _stale_refs(route.proj, route.branch)
    assert len(stale) == 2, stale                      # distinct suffixes, both kept
    assert sorted(stale.values()) == sorted([tip1, tip2])
    _no_adoption(caplog)


# ═══════════════════════════════════════════════════════
# AC-SB-05 · the predicate in isolation
# ═══════════════════════════════════════════════════════
def test_predicate_flags_a_branch_behind_main(tmp_path):
    proj = tmp_path / "r"
    proj.mkdir()
    _init_repo(proj)
    _git("git branch orch-x", proj)
    cut = _sha("orch-x", proj)
    _advance_main(proj, 2)

    (v,) = check_branch_freshness_invariants(QueueRepo("testrepo", proj, "main", "orch"), ["x.md"])
    assert v.behind == 2
    assert v.merge_base == cut
    assert v.branch_tip == cut
    assert v.target_tip == _sha("main", proj)
    assert "2 commit(s) behind main" in str(v)


def test_predicate_ignores_missing_and_retired(tmp_path):
    proj = tmp_path / "r"
    proj.mkdir()
    _init_repo(proj)
    repo = QueueRepo("testrepo", proj, "main", "orch")
    assert check_branch_freshness_invariants(repo, ["never-fired.md"]) == []

    _git("git branch orch-x--stale-20260101-000000", proj)
    _advance_main(proj, 1)
    assert check_branch_freshness_invariants(repo, ["x.md"]) == []


def test_predicate_unreadable_is_not_a_violation(tmp_path):
    assert check_branch_freshness_invariants(QueueRepo("none", tmp_path, "main", "orch"), ["x.md"]) == []


# ═══════════════════════════════════════════════════════
# AC-SB-06 · a failed retire does not fire on the stale branch
# ═══════════════════════════════════════════════════════
def test_retire_failure_refuses_to_fire(route, monkeypatch, caplog):
    caplog.set_level("INFO", logger="orch")
    _git(f"git branch {route.branch}", route.proj)
    _advance_main(route.proj, 1)
    main_before = _sha("main", route.proj)

    def _boom(*a, **k):
        raise RuntimeError("simulated")

    monkeypatch.setattr(orchestrator, "retire_stale_branch", _boom)
    calls = []
    r = fire(route, monkeypatch, lambda proj: calls.append(proj) or 0)

    assert r.status == orchestrator.Status.FAILED
    assert r.error.startswith("stale-base:")
    assert calls == [] and route.handoffs == []
    assert _sha("main", route.proj) == main_before
    assert _git("git symbolic-ref HEAD", route.proj).stdout.strip() == "refs/heads/main"
    assert "⛔ STALE-BASE" in caplog.text
    _no_adoption(caplog)


# ═══════════════════════════════════════════════════════
# AC-SB-07 · the meta-fire worktree cut is fresh
# ═══════════════════════════════════════════════════════
def test_meta_fire_worktree_cuts_from_merge_target(route, monkeypatch, caplog):
    caplog.set_level("INFO", logger="orch")
    _git(f"git branch {route.branch}", route.proj)      # a leftover from a previous attempt
    stale_tip = _sha(route.branch, route.proj)
    _advance_main(route.proj, 2)
    main_now = _sha("main", route.proj)

    monkeypatch.setattr(orchestrator, "IS_META_FIRE", True)
    # prefire.report reads the live machine's canon and repos; this test is about the cut.
    monkeypatch.setattr(orchestrator, "PREFIRE_BYPASS", True)
    # The fire lock and running.json are the real orchestrator's; never touch them from a test.
    markers = []
    monkeypatch.setattr(orchestrator, "write_running", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "clear_running", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "_write_running_marker", lambda *a, **k: markers.append(a))
    monkeypatch.setattr(orchestrator, "_clear_running_marker", lambda *a, **k: None)

    seen = {}

    def _inner(batch_file, proj, started, worktree=None):
        seen["proj"] = proj
        seen["head"] = _sha("HEAD", proj)
        seen["violations"] = check_branch_freshness_invariants(route.repo, [route.brief.name])
        now = orchestrator.datetime.now().isoformat()
        return orchestrator.Result(batch_file=batch_file.name, status=orchestrator.Status.PASSED,
                                   started=now, finished=now, duration_s=0.0, exit_code=0,
                                   briefs=1)

    monkeypatch.setattr(orchestrator, "_run_batch_inner", _inner)
    r = orchestrator.run_batch(route.brief)

    assert r.status == orchestrator.Status.PASSED
    assert seen["proj"] != route.proj, "ran in the meta-fire worktree"
    assert seen["head"] == main_now
    assert seen["violations"] == []
    stale = _stale_refs(route.proj, route.branch)
    assert list(stale.values()) == [stale_tip]
    assert not Path(seen["proj"]).exists(), "cleanup_worktree removed the worktree"
    # T6: the fire-lock marker still names the canonical branch, not the retired one.
    assert markers and markers[0][3] == route.branch
    _no_adoption(caplog)


def test_meta_fire_stale_base_refuses_before_write_running(route, monkeypatch, caplog):
    caplog.set_level("INFO", logger="orch")
    _git(f"git branch {route.branch}", route.proj)
    _advance_main(route.proj, 1)
    monkeypatch.setattr(orchestrator, "IS_META_FIRE", True)
    monkeypatch.setattr(orchestrator, "PREFIRE_BYPASS", True)

    def _boom(*a, **k):
        raise RuntimeError("simulated")

    def _never(*a, **k):
        raise AssertionError("must return before write_running / _run_batch_inner")

    monkeypatch.setattr(orchestrator, "retire_stale_branch", _boom)
    monkeypatch.setattr(orchestrator, "write_running", _never)
    monkeypatch.setattr(orchestrator, "_run_batch_inner", _never)
    r = orchestrator.run_batch(route.brief)

    assert r.status == orchestrator.Status.FAILED
    assert r.error.startswith("stale-base:")
    assert "⛔ STALE-BASE" in caplog.text
    assert not [l for l in _git("git worktree list", route.proj).stdout.splitlines()
                if "orch-fire-" in l]

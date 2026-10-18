# filename: tests/test_baseline_reuse_1.py
"""Tests for ORCH-BASELINE-REUSE-1 (S7-CORE-31 · SCP_Kanban row 344).

Route 290ea's gate ran the unit suite on its branch tip (1311 files/13326 tests, 552.4 s) and landed that tip on
main by fast-forward as 94ef57f. The next route forked at 94ef57f, missed the cache and measured the same tree again
(556.2 s). A landed route's branch run is now stored as the cached baseline of the commit it landed as — when that
commit's non-briefs tree is the one the branch leg measured, and the comparison the gate accepted vouches for it.

  P1  (R1/R2a) a landed route's branch run → one entry for the merged commit, from either landing site;
           the green fast path too                                                            (TestP1*)
  P2  (R4) the next route off that main reads [cache]; the flakes it confirms land on the entry;
           a changed test_cmd misses                                                          (TestP2*)
  P3  (R2f) main gained a non-briefs commit between fork and merge → none; a briefs-only one → stored  (TestP3*)
  P4  a gate that is not PASS, or a merge that conflicts, stores nothing                     (TestP4*)
  P5  (R2 a-e/g) briefs-only, flake-only, ancestor-cache, an untracked file, HEAD moved, an implausible
           branch clock, a judged entry already there; the store never raises                (TestP5*)
  Find 1  the tree at the branch run, on the lane harness                                    (TestFind1*)

Harness: tests/test_gate_cost.py's `lane` shape — a REAL git repository, the REAL _run_batch_inner (commit, gate,
landing), a real detached baseline worktree; only the executor and the suite commands are scripted, and the clock
judgement (check_clock_plausibility) is scripted per leg kind. Every cache is a tmp archive; the live sit-archive is
never read or written. fire_toni is stubbed in every test: a route fired without its own executor fails the test
rather than start one.

Module-level imports are existing symbols only, so this file collects on the code that predates
ORCH-BASELINE-REUSE-1 — the RED run needs that.
"""

import json
import logging
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_gate_cost import (BUILD_CMD, LIST_CMD, LIST_OUT, REPO, SIT_CMD, TEST_CMD, UA, UB, _activate,  # noqa: E402
                                  _git, _repo, _toni_log, vitest)

UC = "src/lib/c.test.ts"
OTHER_CMD = "npm run test:unit"
PASSED = orchestrator.Status.PASSED
BRANCH_290EA = vitest([UA, UA, UA, UB, UB], failed=5)    # 290ea: 5 failed against the base's 4, no new failing file
BASE_290EA = vitest([UA, UA, UB, UB], failed=4)
FLAKY_UC = vitest([UA, UA, UB, UB, UC], failed=5)        # UC fails in the suite, not in the base
ALONE_GREEN = vitest(total_tests=1, total_files=1)
ALONE_RED = vitest([UC], failed=1, total_tests=1, total_files=1)
TIMEOUT = object()                                       # a scripted leg that exceeds its budget


def _collection(out: str) -> str:
    return orchestrator.UnitSuiteRun(ref="x", exit_code=1, **orchestrator._parse_unit_summary(out)).collection


class Suites:
    """subprocess.run as the gates see it. build / SIT / list are green; `npm test` returns the scripted BRANCH output
    in the route's checkout, BASELINE in a detached baseline worktree, CONFIRM for `npm test -- <files>`. Each leg is
    counted; at each branch leg the checkout's HEAD and `git status` are recorded (Find 1), then `during[leg](cwd)`
    runs (an artefact a leg leaves, a commit it makes). git, and every other command, runs for real."""

    def __init__(self, monkeypatch):
        self.calls, self.at_branch, self.during, self.real = [], [], {}, subprocess.run
        self.out = {"build": (0, "built\n"), "sit": (0, vitest(total_tests=4, total_files=2)), "list": (0, LIST_OUT),
                    "branch": (0, vitest()), "baseline": (0, vitest()), "confirm": (0, ALONE_GREEN)}
        monkeypatch.setattr(subprocess, "run", self)

    @staticmethod
    def leg(cmd: str, cwd) -> str:
        for name, prefix in (("build", BUILD_CMD), ("sit", SIT_CMD), ("list", LIST_CMD)):
            if cmd.startswith(prefix):
                return name
        if cmd.startswith((TEST_CMD, OTHER_CMD)):
            if " -- " in cmd:
                return "confirm"
            return "baseline" if orchestrator.UNIT_BASELINE_WORKTREE_PREFIX in str(cwd) else "branch"
        return None

    def __call__(self, cmd, *a, **kw):
        name = self.leg(cmd, kw.get("cwd")) if isinstance(cmd, str) else None
        if name is None:
            return self.real(cmd, *a, **kw)
        self.calls.append(name)
        cwd = Path(kw.get("cwd") or ".")
        if name == "branch":
            self.at_branch.append({"head": _git(cwd, "rev-parse", "HEAD"),
                                   "status": _git(cwd, "status", "--porcelain", "--untracked-files=all")})
        if name in self.during:
            self.during[name](cwd)
        rc, out = self.out[name]
        if out is TIMEOUT:
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout") or 1)
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")

    def count(self, name) -> int:
        return self.calls.count(name)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """tests/test_gate_cost.py's `lane`: a real repo, each brief queued OUTSIDE it (so _run_batch_inner copies it into
    briefs/, as a daemon route does), every leg scripted (Suites), git real."""
    repo = _repo(tmp_path / "repo")
    _activate(monkeypatch, tmp_path, repo)
    for name, val in (("IS_META_FIRE", False), ("RUN_PLAYWRIGHT", False)):
        monkeypatch.setattr(orchestrator, name, val)
    monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
    monkeypatch.setattr(orchestrator, "notify", lambda r: None)
    monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
    monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
    monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)

    def _no_executor(target, proj):
        raise AssertionError("a test route reached fire_toni without a scripted executor")
    monkeypatch.setattr(orchestrator, "fire_toni", _no_executor)

    implausible = set()

    def _clock(kind, start, end, history):
        return ([orchestrator.ClockViolation(leg_kind=kind, reason="wall-jump", d_wall=900.0, d_monotonic=300.0,
                                             d_boottime=300.0, median=None)] if kind in implausible else [])
    monkeypatch.setattr(orchestrator, "check_clock_plausibility", _clock)
    return types.SimpleNamespace(repo=repo, tmp=tmp_path, archive=tmp_path / "archive", suites=Suites(monkeypatch),
                                 implausible=implausible, monkeypatch=monkeypatch)


def fire(lane, stem, work, wt=None):
    """One route through the REAL _run_batch_inner. `work(proj)` is its executor; the handback is written after it.
    `wt` runs it as a route-worktree route — the landing is then _land_from_route_worktree."""
    brief = lane.tmp / "queue" / f"{stem}.md"
    brief.parent.mkdir(exist_ok=True)
    brief.write_text(f"#!queue repo={REPO}\n\n# {stem}\n- id: B1\n  title: demo\n")

    def _fire(target, proj):
        work(Path(proj))
        (Path(proj) / "briefs" / f"{stem}.handback.md").write_text(f"# {stem} handback\n")
        return 0, _toni_log(lane.tmp / "logs" / "cost" / f"toni-{stem}-20261018-000000.log")
    lane.monkeypatch.setattr(orchestrator, "fire_toni", _fire)
    kw = {"route_wt": wt} if wt is not None else {}
    return orchestrator._run_batch_inner(brief, wt or lane.repo, datetime.now(), worktree=None, **kw)


def code(rel="src/a.ts", text="export const a = 2;\n"):
    def work(proj):
        (proj / rel).parent.mkdir(parents=True, exist_ok=True)
        (proj / rel).write_text(text)
    return work


def advance_main(lane, files: dict):
    """Someone else lands on main while the route runs — through a worktree, which is then removed."""
    wt = lane.tmp / "mainwt"
    _git(lane.repo, "worktree", "add", "-q", str(wt), "main")
    for rel, text in files.items():
        (wt / rel).parent.mkdir(parents=True, exist_ok=True)
        (wt / rel).write_text(text)
    _git(wt, "add", "-A")
    _git(wt, "commit", "-qm", "main: someone else landed")
    _git(lane.repo, "worktree", "remove", str(wt))


def entries(lane) -> dict:
    f = lane.archive / orchestrator.UNIT_BASELINE_CACHE_FILE
    return json.loads(f.read_text())["entries"] if f.exists() else {}


def key(lane, sha, cmd=TEST_CMD) -> str:
    return orchestrator._unit_cache_key(REPO, orchestrator._unit_content_key(lane.repo, sha), cmd)


def main_sha(lane) -> str:
    return _git(lane.repo, "rev-parse", "main")


def said(caplog) -> list:
    """The route-branch store's lines — exactly one per landed route."""
    return [r.getMessage() for r in caplog.records if "route branch run" in r.getMessage()]


def unit_log(lane) -> list:
    return json.loads((lane.archive / "orchestrator-unit-log.json").read_text())


def store(lane, sha, out, cmd=TEST_CMD):
    """A judged entry at `sha`, written by the store the gate uses."""
    run = orchestrator.UnitSuiteRun(ref=f"merge-base {sha[:7]}", exit_code=1, duration_s=301.0,
                                    **orchestrator._parse_unit_summary(out))
    orchestrator._unit_cache_store(lane.archive, REPO, sha, cmd, run, repo_path=lane.repo)


def stored_line(merged, tip, out) -> str:
    return (f"♻️  Unit baseline: route branch run cached for {merged[:7]} (gated tip {tip[:7]}, non-briefs tree "
            f"identical) — {_collection(out)}; the next route off this tree reads it")


def not_cached(merged, why) -> str:
    return f"♻️  Unit baseline: route branch run NOT cached for {merged[:7]} — {why}"


# ═══════════════════════════════════════════════════════
# P1 · R1/R2a — a landed route's branch run is stored for the commit it landed as
# ═══════════════════════════════════════════════════════
class TestP1MergeStoresTheBranchRun:

    def test_a_fast_forward_stores_the_branch_run_for_the_merged_commit(self, lane, caplog):
        """290ea's shape: 5 failed against the base's 4 on the same two files — PASS, landed by fast-forward."""
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))
        fork = main_sha(lane)
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "290ea-member-write-guard-1r", code())
        assert (r.status, r.gate_outcome) == (PASSED, "PASS"), r.error
        merged, tip = main_sha(lane), lane.suites.at_branch[0]["head"]
        assert merged == tip != fork, "a fast-forward: the merged commit IS the gated tip"
        e = entries(lane)[key(lane, merged)]
        assert (e["sha"], e["landed_as"], e["measured_as"], e["clock"]) == (tip, merged, "route-branch", "plausible")
        assert (e["failures"], e["failing_files"], e["test_cmd"], e["repo"]) == (5, [UA, UB], TEST_CMD, REPO)
        assert e["content_key"] == orchestrator._unit_content_key(lane.repo, merged)
        assert set(entries(lane)) == {key(lane, fork), key(lane, merged)}, "the merge base's measurement, and this"
        assert said(caplog) == [stored_line(merged, tip, BRANCH_290EA)]

    def test_the_route_worktree_landing_stores_it_too(self, lane, caplog):
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))
        wt = lane.tmp / "toni" / "290ea-wt"
        _git(lane.repo, "worktree", "add", "-q", "--detach", str(wt), "main")
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "290ea-wt", code(), wt=wt)
        assert (r.status, r.gate_outcome) == (PASSED, "PASS"), r.error
        merged, tip = main_sha(lane), lane.suites.at_branch[0]["head"]
        assert merged == tip and any("from the route worktree" in m for m in [x.getMessage() for x in caplog.records])
        e = entries(lane)[key(lane, merged)]
        assert (e["sha"], e["landed_as"], e["measured_as"], e["failing_files"]) == (tip, merged, "route-branch",
                                                                                   [UA, UB])
        assert said(caplog) == [stored_line(merged, tip, BRANCH_290EA)]

    def test_the_green_fast_path_stores_an_empty_failing_set(self, lane, caplog):
        """not-needed: no baseline leg ran, and a green branch is a baseline of its own tree."""
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "290eb-green", code())
        assert r.status is PASSED and lane.suites.count("baseline") == 0
        merged, tip = main_sha(lane), lane.suites.at_branch[0]["head"]
        (k, e), = entries(lane).items()
        assert k == key(lane, merged)
        assert (e["sha"], e["landed_as"], e["failures"], e["failing_files"]) == (tip, merged, 0, [])
        assert said(caplog) == [stored_line(merged, tip, vitest())]


# ═══════════════════════════════════════════════════════
# P2 · R4 — the next route off that main reads [cache]
# ═══════════════════════════════════════════════════════
class TestP2TheNextRouteReadsTheCache:

    def test_the_next_route_reads_cache_and_its_flakes_land_on_the_entry(self, lane, caplog):
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))
        fire(lane, "290ea-member-write-guard-1r", code())
        landed = main_sha(lane)
        lane.suites.calls.clear()
        lane.suites.out.update(branch=(1, FLAKY_UC), confirm=(0, ALONE_GREEN))
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "290eaa-partner-pdf-k3-1r", code("src/b.ts", "export const b = 1;\n"))
        assert (r.status, r.gate_outcome) == (PASSED, "PASS"), r.error
        assert lane.suites.count("baseline") == 0, "no baseline leg: the landed branch run is the baseline"
        assert "[cache]" in r.unit_collection and unit_log(lane)[-1]["baseline_source"] == "cache"
        e = entries(lane)[key(lane, landed)]
        assert e["flaky_files"] == [UC] and e["flaky_seen"][UC]["count"] == 1
        assert e["measured_as"] == "route-branch" and e["failures"] == 5, "only the flaky fields were added"
        hits = [m for m in (x.getMessage() for x in caplog.records) if "CACHE HIT" in m]
        assert len(hits) == 1 and "(a route's branch run)" in hits[0]
        assert "(a route's branch run)" in unit_log(lane)[-1]["baseline_note"]

    def test_negative_control_a_changed_test_cmd_misses_and_measures(self, lane):
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))
        fire(lane, "290ea-member-write-guard-1r", code())
        lane.monkeypatch.setitem(orchestrator.ACTIVE_REPO_CONFIG, "test_cmd", OTHER_CMD)
        lane.suites.calls.clear()
        r = fire(lane, "290eaa-partner-pdf-k3-1r", code("src/b.ts", "export const b = 1;\n"))
        assert r.status is PASSED
        assert lane.suites.count("baseline") == 1 and "[measured]" in r.unit_collection


# ═══════════════════════════════════════════════════════
# P3 · R2f — the merged commit's tree is not the gated tip's
# ═══════════════════════════════════════════════════════
class TestP3TheTreeDiffers:

    def test_a_true_merge_over_a_non_briefs_advance_stores_nothing(self, lane, caplog):
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))

        def work(proj):
            code()(proj)
            advance_main(lane, {"docs/other.md": "main moved under the route\n"})
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "290ea-member-write-guard-1r", work)
        assert r.status is PASSED, r.error
        merged = main_sha(lane)
        assert len(_git(lane.repo, "rev-list", "--parents", "-n1", merged).split()) == 3, "a true merge commit"
        assert key(lane, merged) not in entries(lane)
        assert not any("measured_as" in e for e in entries(lane).values())
        assert said(caplog) == [not_cached(merged, (
            f"(f) the merged commit's non-briefs tree is not the gated tip's "
            f"({lane.suites.at_branch[0]['head'][:7]}) — main gained a non-briefs change between fork and merge"))]
        lane.suites.calls.clear()
        r2 = fire(lane, "290eaa-next", code("src/b.ts", "export const b = 1;\n"))
        assert lane.suites.count("baseline") == 1 and "[measured]" in r2.unit_collection

    def test_negative_control_a_briefs_only_advance_is_stored(self, lane, caplog):
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))

        def work(proj):
            code()(proj)
            advance_main(lane, {"briefs/290eb-other.md": "# another route's brief\n"})
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "290ea-member-write-guard-1r", work)
        assert r.status is PASSED, r.error
        merged, tip = main_sha(lane), lane.suites.at_branch[0]["head"]
        assert len(_git(lane.repo, "rev-list", "--parents", "-n1", merged).split()) == 3 and merged != tip
        e = entries(lane)[key(lane, merged)]
        assert (e["sha"], e["landed_as"]) == (tip, merged)
        assert said(caplog) == [stored_line(merged, tip, BRANCH_290EA)]


# ═══════════════════════════════════════════════════════
# P4 · a gate that is not PASS, or a merge that did not land, stores nothing
# ═══════════════════════════════════════════════════════
class TestP4NoLandingNoEntry:

    def _nothing_stored(self, lane, caplog, fork):
        assert main_sha(lane) == fork, "nothing landed"
        assert not any("measured_as" in e for e in entries(lane).values())
        assert said(caplog) == [], "no landing, no line"

    def test_a_product_regression(self, lane, caplog):
        lane.suites.out.update(branch=(1, FLAKY_UC), baseline=(1, BASE_290EA), confirm=(1, ALONE_RED))
        fork = main_sha(lane)
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "290ea-regress", code())
        assert r.gate_outcome == "FAIL(product)"
        assert set(entries(lane)) == {key(lane, fork)}, "the merge base's measurement only"
        self._nothing_stored(lane, caplog, fork)

    def test_blocked_a_regression_on_an_implausible_branch_clock(self, lane, caplog):
        lane.suites.out.update(branch=(1, FLAKY_UC), baseline=(1, BASE_290EA), confirm=(1, ALONE_RED))
        lane.implausible.add("unit-branch")
        fork = main_sha(lane)
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "290ea-clock", code())
        assert r.gate_outcome == "BLOCKED(environment)" and "clock-implausible" in (r.error or "")
        self._nothing_stored(lane, caplog, fork)

    def test_blocked_baseline_unmeasurable(self, lane, caplog):
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, TIMEOUT))
        fork = main_sha(lane)
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "290ea-unmeasurable", code())
        assert r.gate_outcome == "BLOCKED(environment)" and "baseline-unmeasurable" in (r.error or "")
        assert entries(lane) == {}
        self._nothing_stored(lane, caplog, fork)

    def test_a_merge_conflict(self, lane, caplog):
        def work(proj):
            code()(proj)
            advance_main(lane, {"src/a.ts": "export const a = 99;\n"})
        with caplog.at_level(logging.INFO, logger="orch"):
            r = fire(lane, "290ea-conflict", work)
        assert r.gate_outcome == "PASS" and r.status is orchestrator.Status.FAILED
        assert "Merge conflict on" in caplog.text
        assert entries(lane) == {} and said(caplog) == []


# ═══════════════════════════════════════════════════════
# P5 · R2 a-e/g — a PASS that landed, and still nothing stored; R3 — the store never raises
# ═══════════════════════════════════════════════════════
class TestP5LandedButNotStored:

    def _landed(self, r):
        assert (r.status, r.gate_outcome) == (PASSED, "PASS"), r.error
        return main_sha(self.lane)

    @pytest.fixture(autouse=True)
    def _keep(self, lane):
        self.lane = lane

    def test_a_briefs_only_route(self, lane, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            merged = self._landed(fire(lane, "290ea-briefs", lambda proj: None))
        assert lane.suites.calls == [] and entries(lane) == {}
        (line,) = said(caplog)
        assert line.startswith(not_cached(merged, "(a) no unit branch run — briefs-only diff (2 files: "))

    def test_an_ungated_repo(self, lane, caplog):
        lane.monkeypatch.setitem(orchestrator.ACTIVE_REPO_CONFIG, "test_cmd", "")
        with caplog.at_level(logging.INFO, logger="orch"):
            merged = self._landed(fire(lane, "290ea-ungated", code()))
        assert lane.suites.count("branch") == 0 and entries(lane) == {}
        assert said(caplog) == [not_cached(merged, "(a) no unit branch run — the unit gate was ungated")]

    def test_a_flake_only_pass(self, lane, caplog):
        lane.suites.out.update(branch=(1, FLAKY_UC), baseline=(1, BASE_290EA), confirm=(0, ALONE_GREEN))
        with caplog.at_level(logging.INFO, logger="orch"):
            merged = self._landed(fire(lane, "290ea-flake", code()))
        assert key(lane, merged) not in entries(lane)
        assert said(caplog) == [not_cached(merged, f"(d) the gate confirmed flaky file(s) in isolation: {UC}")]

    def test_an_ancestor_cache_pass(self, lane, caplog):
        m0 = main_sha(lane)
        store(lane, m0, BASE_290EA)
        (lane.repo / "src" / "a.ts").write_text("export const a = 1.5;\n")
        _git(lane.repo, "commit", "-qam", "M1 on main")
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, TIMEOUT))
        with caplog.at_level(logging.INFO, logger="orch"):
            merged = self._landed(fire(lane, "290ea-ancestor", code()))
        assert unit_log(lane)[-1]["baseline_source"] == "ancestor-cache"
        assert set(entries(lane)) == {key(lane, m0)}
        assert said(caplog) == [not_cached(merged, (
            "(c) the baseline the gate accepted is ancestor-cache — only a measured, cached or not-needed one "
            "vouches for the branch run"))]

    def test_an_untracked_non_briefs_file_at_the_branch_run(self, lane, caplog):
        """Find 1's shape: an un-ignored build artefact is in the tree the branch leg measures, never in the commit."""
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))
        lane.suites.during["build"] = lambda cwd: (cwd / "coverage-summary.txt").write_text("built\n")
        with caplog.at_level(logging.INFO, logger="orch"):
            merged = self._landed(fire(lane, "290ea-artefact", code()))
        assert lane.suites.at_branch[0]["status"] == "?? coverage-summary.txt"
        assert key(lane, merged) not in entries(lane)
        assert said(caplog) == [not_cached(merged, (
            "(e) the branch leg did not measure a commit — uncommitted outside briefs/ before it: "
            "coverage-summary.txt"))]

    def test_negative_control_an_untracked_file_under_briefs_is_stored(self, lane, caplog):
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))
        lane.suites.during["build"] = lambda cwd: (cwd / "briefs" / "scratch.md").write_text("# scratch\n")
        with caplog.at_level(logging.INFO, logger="orch"):
            merged = self._landed(fire(lane, "290ea-briefs-artefact", code()))
        assert entries(lane)[key(lane, merged)]["landed_as"] == merged
        assert said(caplog) == [stored_line(merged, lane.suites.at_branch[0]["head"], BRANCH_290EA)]

    def test_head_moved_during_the_branch_run(self, lane, caplog):
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))

        def commit_during(cwd):
            (cwd / "src" / "late.ts").write_text("export const late = 1;\n")
            _git(cwd, "add", "-A")
            _git(cwd, "commit", "-qm", "a commit made while the suite ran")
        lane.suites.during["branch"] = commit_during
        with caplog.at_level(logging.INFO, logger="orch"):
            merged = self._landed(fire(lane, "290ea-moved", code()))
        before = lane.suites.at_branch[0]["head"]
        assert merged != before
        assert key(lane, merged) not in entries(lane)
        assert said(caplog) == [not_cached(merged, (
            f"(e) the branch leg did not measure a commit — HEAD moved during it ({before[:7]} → {merged[:7]})"))]

    def test_an_implausible_branch_clock_on_a_pass(self, lane, caplog):
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))
        lane.implausible.add("unit-branch")
        with caplog.at_level(logging.INFO, logger="orch"):
            merged = self._landed(fire(lane, "290ea-clock-pass", code()))
        assert key(lane, merged) not in entries(lane)
        (line,) = said(caplog)
        assert line.startswith(not_cached(merged, "(b) the branch leg's clock is implausible (unit-branch wall-jump"))

    def test_a_judged_entry_already_at_the_key_is_byte_identical_after(self, lane, caplog):
        """R2g: the first measurement stands. Its twin commit has the route's non-briefs tree under other briefs."""
        fork = main_sha(lane)
        store(lane, fork, BASE_290EA)
        _git(lane.repo, "checkout", "-q", "-b", "twin")
        code()(lane.repo)
        (lane.repo / "briefs" / "twin.md").write_text("# twin\n")
        _git(lane.repo, "add", "-A")
        _git(lane.repo, "commit", "-qm", "twin")
        twin = _git(lane.repo, "rev-parse", "HEAD")
        _git(lane.repo, "checkout", "-q", "main")
        store(lane, twin, vitest([UA], failed=1))
        cache = lane.archive / orchestrator.UNIT_BASELINE_CACHE_FILE
        before = cache.read_bytes()
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))
        with caplog.at_level(logging.INFO, logger="orch"):
            merged = self._landed(fire(lane, "290ea-twin", code()))
        assert lane.suites.count("baseline") == 0, "the merge base was a cache hit"
        assert key(lane, merged) == key(lane, twin)
        assert cache.read_bytes() == before
        (line,) = said(caplog)
        assert line.startswith(not_cached(merged, f"(g) a judged entry already stands for this tree (measured at "
                                                  f"{twin[:7]}"))

    def test_the_store_never_raises_and_says_so_once(self, lane, caplog):
        class Boom:
            outcome = orchestrator.GateOutcome.PASS

            @property
            def unit(self):
                raise RuntimeError("unreadable verdict")
        with caplog.at_level(logging.INFO, logger="orch"):
            orchestrator._unit_cache_store_landed(lane.repo, Boom(), main_sha(lane), lane.archive)
        warned = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert [r.getMessage() for r in warned] == [not_cached(main_sha(lane), (
            "the check raised RuntimeError: unreadable verdict; nothing stored"))]
        assert not lane.archive.exists()

    def test_a_failing_cache_write_never_changes_the_route(self, lane, caplog):
        fork = main_sha(lane)
        store(lane, fork, BASE_290EA)
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))

        def _raise(*a, **k):
            raise OSError("disk full")
        lane.monkeypatch.setattr(orchestrator, "_unit_cache_store", _raise)
        with caplog.at_level(logging.INFO, logger="orch"):
            merged = self._landed(fire(lane, "290ea-disk-full", code()))
        assert merged != fork and set(entries(lane)) == {key(lane, fork)}
        assert said(caplog) == [not_cached(merged, "the check raised OSError: disk full; nothing stored")]


# ═══════════════════════════════════════════════════════
# Find 1 · what the branch leg measures on the lane: the commit, nothing else
# ═══════════════════════════════════════════════════════
class TestFind1TheTreeAtTheBranchRun:

    def test_the_route_lane_commits_everything_before_the_gate(self, lane):
        lane.suites.out.update(branch=(1, BRANCH_290EA), baseline=(1, BASE_290EA))
        r = fire(lane, "290ea-find1", code())
        (at,) = lane.suites.at_branch
        print(f"\nFind 1 · lane harness, at the branch leg: HEAD {at['head'][:7]}; "
              f"git status --porcelain --untracked-files=all → {at['status']!r}; "
              f"landed as {main_sha(lane)[:7]}; legs {lane.suites.calls}")
        assert r.status is PASSED and at["status"] == "" and at["head"] == main_sha(lane)
        legs = lane.suites.calls
        assert legs.index("build") < legs.index("sit") < legs.index("branch"), \
            "build and SIT run in the same checkout BEFORE the branch leg"

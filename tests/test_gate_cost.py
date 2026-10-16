# filename: tests/test_gate_cost.py
"""Tests for ORCH-GATE-COST-1 (S7-CORE-30 · D-S7CORE29-02 · LESSONS L-150).

Routes 267 and 268 were handback-only merges — a brief and a handback, two files each — and paid 46 and 45
minutes of gates. Every merge commits its brief and handback, so the next route's merge base is a new SHA over
an identical tree and its unit baseline was re-measured; and SIT ran the whole suite (~25 min) per merge.

  P1  (D1) a branch that changes only briefs_subdir runs no build, SIT or unit leg, and says so — on every
           caller: the route lane, the meta-fire lane whose verdict _self_mod_auto_merge consumes, a parallel
           worker                                                                       (TestP1BriefsOnly*)
  P2  (D2) the unit baseline is keyed on the non-briefs tree; v1 → v2 migration         (TestP2*)
  P3  (D3) per-merge SIT runs the files related to the diff; none ⇒ not applicable;
           an enumeration failure ⇒ the full suite; GATE-SIT-2 on the related set       (TestP3*)
  P4  (D4) `full-gate` and the daemon's nightly step                                    (TestP4*)
  P5  every verdict-line reader parses the new lines                                    (TestP5*)

Harness: REAL git repositories (a real merge base, real diffs, a real detached worktree); only the suite
commands (`npm run build`, `npm run sit:gate`, `npx vitest list`, `npm test`) are scripted. No test touches the
live queue, the daemon, queue-state.json, state/ or a real repo's tree.

Module-level imports are existing symbols only, so this file collects on the code that predates
ORCH-GATE-COST-1 — the RED run needs that.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import types
from datetime import datetime
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
import queue_daemon  # noqa: E402
from tests.test_gate_clock import Clock  # noqa: E402

ROOT = Path(__file__).parent.parent
REPO = "cost-repo"
BUILD_CMD, SIT_CMD, TEST_CMD, LIST_CMD = "npm run build", "npm run sit:gate", "npm test", "npx vitest list"
PASS, BLOCKED, PRODUCT = (orchestrator.GateOutcome.PASS, orchestrator.GateOutcome.BLOCKED_ENV,
                          orchestrator.GateOutcome.FAIL_PRODUCT)
RULE = "=" * 60
F = {i: f"sit/integration/f{i}.integration.test.ts" for i in range(1, 6)}
LIST_OUT = "".join(f"{F[i]} > case {j}\n" for i in range(1, 6) for j in (1, 2))      # 5 files / 10 tests
UA, UB = "src/lib/a.test.ts", "src/lib/b.test.ts"


def vitest(failing=(), failed=0, total_tests=18, total_files=6):
    """A vitest summary — `failed` failures over `failing` files (the shape clinical-mp prints)."""
    lines = [f" FAIL  {f} > suite > case {i}" for i, f in enumerate(failing)]
    ff = len(set(failing))
    lines += ["", f" Test Files  {ff} failed | {total_files - ff} passed ({total_files})" if ff
              else f" Test Files  {total_files} passed ({total_files})",
              f"      Tests  {failed} failed | {total_tests - failed} passed ({total_tests})" if failed
              else f"      Tests  {total_tests} passed ({total_tests})", "   Duration  6.6s"]
    return "\n".join(lines) + "\n"


def batch(n_files, red=()):
    """A SIT batch summary: `n_files` files / 2 tests each, one failed assertion per file in `red`."""
    k = len(red)
    heads = "".join(f" FAIL  {f} > case 1\nAssertionError: expected 1 to be 2\n" for f in red)
    ft = (f"{k} failed" + (f" | {n_files - k} passed" if n_files > k else "") + f" ({n_files})") if k \
        else f"{n_files} passed ({n_files})"
    tt = f"{k} failed | {2 * n_files - k} passed ({2 * n_files})" if k else f"{2 * n_files} passed ({2 * n_files})"
    return f"{heads} RUN  v4.1.4 /repo\n\n Test Files  {ft}\n      Tests  {tt}\n   Duration  4.0s\n"


def _git(repo, *args) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout.strip()


def _repo(path: Path) -> Path:
    """main @ M0: src/a.ts, briefs/old.md, docs/readme.md."""
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    for rel, text in (("src/a.ts", "export const a = 1;\n"), ("briefs/old.md", "# old\n"),
                      ("docs/readme.md", "docs\n")):
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "M0")
    return path


def _commit(repo, name, write=None, delete=(), move=(), base="main", keep=False) -> str:
    """Branch `name` from `base` with one commit (possibly empty); returns its tip. Back on main unless keep."""
    _git(repo, "checkout", "-q", "-b", name, base)
    for rel, text in (write or {}).items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    for rel in delete:
        _git(repo, "rm", "-q", rel)
    for a, b in move:
        (repo / b).parent.mkdir(parents=True, exist_ok=True)
        _git(repo, "mv", a, b)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", f"{name} work")
    tip = _git(repo, "rev-parse", "HEAD")
    if not keep:
        _git(repo, "checkout", "-q", "main")
    return tip


class Legs:
    """subprocess.run as the gates see it: a leg command returns its scripted output and is counted; git (and
    every other command) runs for real."""

    def __init__(self, monkeypatch):
        self.calls, self.cwds, self.real = [], [], subprocess.run
        self.out = {"build": (0, "built\n"), "sit": (0, vitest(total_tests=4, total_files=2)),
                    "unit": (0, vitest()), "list": (0, LIST_OUT)}
        monkeypatch.setattr(subprocess, "run", self)

    def leg(self, cmd: str):
        for name, prefix in (("build", BUILD_CMD), ("sit", SIT_CMD), ("unit", TEST_CMD), ("list", LIST_CMD)):
            if cmd.startswith(prefix):
                return name
        return None

    def __call__(self, cmd, *a, **kw):
        name = self.leg(cmd) if isinstance(cmd, str) else None
        if name is None:
            return self.real(cmd, *a, **kw)
        self.calls.append(name)
        self.cwds.append(kw.get("cwd"))
        rc, out = self.out[name]
        return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")

    def count(self, name) -> int:
        return self.calls.count(name)


def _activate(monkeypatch, tmp_path, repo, gates=("build", "sit"), **extra):
    cfg = {"project_dir": str(repo), "briefs_subdir": "briefs", "test_cmd": TEST_CMD, "build_gate_cmd": BUILD_CMD,
           "log_subdir": "cost", **extra}
    for name, val in (("ACTIVE_REPO_NAME", REPO), ("ACTIVE_REPO_CONFIG", cfg), ("MERGE_TARGET", "main"),
                      ("PROJECT_ROOT", repo), ("BRANCH_PREFIX", "orch"), ("UNIT_GATE_ENABLED", True),
                      ("BUILD_GATE_ENABLED", True), ("SIT_BLOCKING", True), ("SKIP_SIT", False),
                      ("SIT_ARCHIVE_DIR", tmp_path / "archive"), ("LOG_DIR", tmp_path / "logs"),
                      ("LOG_SUBDIR", "cost")):
        monkeypatch.setattr(orchestrator, name, val)
    monkeypatch.setattr(orchestrator, "load_repo_config", lambda: {"repos": {REPO: cfg}})
    monkeypatch.setitem(orchestrator.PRE_MERGE_GATES, REPO, {"gates": tuple(gates), "env_file": None})
    return cfg


class Gate:
    def __init__(self, repo, legs, archive):
        self.repo, self.legs, self.archive = repo, legs, archive

    def run(self, branch="route"):
        return orchestrator.run_pre_merge_gates(self.repo, branch)


@pytest.fixture
def gate(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    _activate(monkeypatch, tmp_path, repo)
    return Gate(repo, Legs(monkeypatch), tmp_path / "archive")


def _msgs(caplog) -> list:
    return [r.getMessage() for r in caplog.records]


# ═══════════════════════════════════════════════════════
# P1 · D1 — a briefs-only merge runs no code gate
# ═══════════════════════════════════════════════════════
class TestP1BriefsOnly:

    def test_briefs_only_branch_is_pass_with_no_leg_invoked(self, gate, caplog):
        _commit(gate.repo, "route", write={"briefs/x.md": "# x\n", "briefs/x.handback.md": "# x handback\n"})
        with caplog.at_level(logging.INFO, logger="orch"):
            v = gate.run()
        assert v.outcome is PASS, v.label
        assert v.detail == ("briefs-only diff (2 files: briefs/x.handback.md, briefs/x.md) — build/SIT/unit not run "
                            "(D-S7CORE29-02)")
        assert v.collection == v.detail, "the skip rides into FINAL STATUS through the collection"
        assert gate.legs.calls == [], "build, SIT and unit must not be invoked"
        assert f"✅ Pre-merge gate on route: {v.label}" in _msgs(caplog)

    def test_negative_control_one_code_file_runs_every_leg(self, gate):
        _commit(gate.repo, "route", write={"briefs/x.md": "# x\n", "briefs/x.handback.md": "# hb\n",
                                           "src/a.ts": "export const a = 2;\n"})
        v = gate.run()
        assert v.outcome is PASS and "briefs-only" not in (v.detail or "")
        assert (gate.legs.count("build"), gate.legs.count("sit"), gate.legs.count("unit")) == (1, 1, 1)
        assert v.detail == "build+sit+unit green on route"

    def test_a_rename_out_of_briefs_runs_the_gates(self, gate):
        _commit(gate.repo, "route", move=[("briefs/old.md", "docs/old.md")])
        v = gate.run()
        assert "briefs-only" not in (v.detail or "") and gate.legs.count("build") == 1

    def test_a_rename_into_briefs_runs_the_gates(self, gate):
        """git's rename detection would show only briefs/readme.md; --no-renames shows docs/readme.md too."""
        _commit(gate.repo, "route", move=[("docs/readme.md", "briefs/readme.md")])
        assert orchestrator.branch_changed_paths(gate.repo, _git(gate.repo, "rev-parse", "main"), "route") == \
            ("briefs/readme.md", "docs/readme.md")
        v = gate.run()
        assert "briefs-only" not in (v.detail or "") and gate.legs.count("build") == 1

    def test_a_deleted_file_outside_briefs_runs_the_gates(self, gate):
        _commit(gate.repo, "route", write={"briefs/x.md": "# x\n"}, delete=["docs/readme.md"])
        v = gate.run()
        assert gate.legs.count("build") == 1, v.label

    def test_a_handback_outside_briefs_runs_the_gates(self, gate):
        _commit(gate.repo, "route", write={"x.handback.md": "# hb at the root\n"})
        gate.run()
        assert gate.legs.count("build") == 1

    def test_an_empty_diff_is_not_briefs_only(self, gate):
        _commit(gate.repo, "route")
        assert orchestrator.branch_changed_paths(gate.repo, _git(gate.repo, "rev-parse", "main"), "route") == ()
        v = gate.run()
        assert "briefs-only" not in (v.detail or "")
        assert (gate.legs.count("build"), gate.legs.count("sit"), gate.legs.count("unit")) == (1, 1, 1)

    def test_a_diff_that_cannot_be_computed_is_not_briefs_only(self, gate, monkeypatch, caplog):
        _commit(gate.repo, "route", write={"briefs/x.md": "# x\n"})
        monkeypatch.setattr(orchestrator, "branch_changed_paths", lambda *a: None)
        with caplog.at_level(logging.INFO, logger="orch"):
            gate.run()
        assert gate.legs.count("build") == 1
        assert any("the branch's diff could not be computed" in m for m in _msgs(caplog))

    def test_the_list_is_truncated_and_counted(self, gate):
        _commit(gate.repo, "route", write={f"briefs/{c}.md": c for c in "abcdefg"})
        v = gate.run()
        assert v.detail.startswith("briefs-only diff (7 files: briefs/a.md, briefs/b.md, briefs/c.md, briefs/d.md, "
                                   "briefs/e.md, … +2 more) — build/SIT/unit not run")
        assert gate.legs.calls == []

    def test_the_repos_own_briefs_subdir_decides(self, gate, monkeypatch):
        """Yorsie's is yorsie/briefs: a top-level briefs/ file is code there."""
        monkeypatch.setitem(orchestrator.ACTIVE_REPO_CONFIG, "briefs_subdir", "yorsie/briefs")
        _commit(gate.repo, "route", write={"yorsie/briefs/9.md": "# 9\n"})
        assert gate.run().detail.startswith("briefs-only diff (1 files: yorsie/briefs/9.md)")
        _commit(gate.repo, "route2", write={"briefs/9.md": "# 9\n"})
        gate.run("route2")
        assert gate.legs.count("build") == 1

    def test_branch_changed_paths_says_none_when_git_cannot(self, gate):
        assert orchestrator.branch_changed_paths(gate.repo, "0" * 40, "main") is None


# ── the callers (Find 1) ─────────────────────────────────────────────────────────────────────────────────────
def _toni_log(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"=== TONI EXECUTION ===\nBatch: x.md\nStarted: 2026-10-16T00:00:00\nCommand: claude\n{RULE}\n\n"
                    f"Handback written; all predicates green.\n\n{RULE}\nFinished: 2026-10-16T00:01:00\nExit: 0\n")
    return str(path)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """The route lane's surroundings: a real repo, the brief queued OUTSIDE it (so _run_batch_inner copies it
    into briefs/, as a daemon route does), everything but git and the leg commands stubbed."""
    repo = _repo(tmp_path / "repo")
    _activate(monkeypatch, tmp_path, repo)
    for name, val in (("IS_META_FIRE", False), ("RUN_PLAYWRIGHT", False)):
        monkeypatch.setattr(orchestrator, name, val)
    monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
    monkeypatch.setattr(orchestrator, "notify", lambda r: None)
    monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
    monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
    monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
    brief = tmp_path / "queue" / "268-one-owner-1.md"
    brief.parent.mkdir()
    brief.write_text("#!queue repo=cost-repo\n\n# 268\n- id: B1\n  title: demo\n")
    ns = types.SimpleNamespace(repo=repo, brief=brief, legs=Legs(monkeypatch), tmp=tmp_path)

    def toni(work):
        def _fire(target, proj):
            work(Path(proj))
            return 0, _toni_log(tmp_path / "logs" / "cost" / "toni-268-one-owner-1-20261016-000000.log")
        monkeypatch.setattr(orchestrator, "fire_toni", _fire)
    ns.toni = toni
    return ns


def _handback(proj: Path):
    (proj / "briefs" / "268-one-owner-1.handback.md").write_text("# 268 handback\n")


class TestP1BriefsOnlyThroughEachCaller:

    def test_the_route_lane_merges_a_briefs_only_route_with_no_leg(self, lane, caplog):
        lane.toni(_handback)
        main_before = _git(lane.repo, "rev-parse", "main")
        with caplog.at_level(logging.INFO, logger="orch"):
            r = orchestrator._run_batch_inner(lane.brief, lane.repo, datetime.now(), worktree=None)
        assert r.status is orchestrator.Status.PASSED and r.gate_outcome == "PASS", r.error
        assert lane.legs.calls == []
        assert _git(lane.repo, "rev-parse", "main") != main_before, "it merged"
        assert _git(lane.repo, "diff", "--name-only", f"{main_before}..main").split() == [
            "briefs/268-one-owner-1.handback.md", "briefs/268-one-owner-1.md"]
        final = [m for m in _msgs(caplog) if "FINAL STATUS" in m]
        assert len(final) == 1 and "briefs-only diff (2 files:" in final[0] and "not run (D-S7CORE29-02)" in final[0]

    def test_negative_control_the_route_lane_gates_a_code_route(self, lane):
        def work(proj):
            _handback(proj)
            (proj / "src" / "a.ts").write_text("export const a = 3;\n")
        lane.toni(work)
        r = orchestrator._run_batch_inner(lane.brief, lane.repo, datetime.now(), worktree=None)
        assert r.status is orchestrator.Status.PASSED
        assert (lane.legs.count("build"), lane.legs.count("sit"), lane.legs.count("unit")) == (1, 1, 1)

    def test_the_meta_fire_lane_and_self_mod_merge(self, lane, monkeypatch):
        """The meta-fire lane gates the worktree's branch; _self_mod_auto_merge consumes that verdict."""
        monkeypatch.setattr(orchestrator, "IS_META_FIRE", True)
        wt = lane.tmp / "orch-fire"
        _git(lane.repo, "worktree", "add", "-q", str(wt), "-b", "orch-268-one-owner-1", "main")

        def toni_commits(proj):
            _handback(proj)
            _git(proj, "add", "-A")
            _git(proj, "commit", "-qm", "handback: 268")
        lane.toni(toni_commits)
        r = orchestrator._run_batch_inner(lane.brief, wt, datetime.now(), worktree=wt)
        assert (r.status, r.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), r.error
        assert "briefs-only diff (2 files:" in r.gate_collection
        assert lane.legs.calls == []
        assert orchestrator._self_mod_auto_merge(lane.repo, "orch-268-one-owner-1", gate_outcome=r.gate_outcome)
        assert _git(lane.repo, "rev-parse", "main") == _git(lane.repo, "rev-parse", "orch-268-one-owner-1")

    def test_a_parallel_worker(self, lane):
        wt = lane.tmp / "toni-1"
        _git(lane.repo, "worktree", "add", "-q", str(wt), "-b", "orch-268-w1", "main")
        (wt / "briefs" / "268.handback.md").write_text("# hb\n")     # uncommitted: the worker's output
        v = orchestrator._gate_parallel_branch(wt, "orch-268-w1")
        assert v.outcome is PASS and v.detail.startswith("briefs-only diff (1 files: briefs/268.handback.md)")
        assert lane.legs.calls == []

    def test_negative_control_a_parallel_worker_with_code(self, lane):
        wt = lane.tmp / "toni-2"
        _git(lane.repo, "worktree", "add", "-q", str(wt), "-b", "orch-268-w2", "main")
        (wt / "src" / "b.ts").write_text("export const b = 1;\n")
        orchestrator._gate_parallel_branch(wt, "orch-268-w2")
        assert lane.legs.count("build") == 1


# ═══════════════════════════════════════════════════════
# P2 · D2 — the unit baseline is keyed on the non-briefs tree
# ═══════════════════════════════════════════════════════
@pytest.fixture
def tree(tmp_path, monkeypatch):
    """A = main @ M0; B = A + a briefs/ file; C = A + a src/ change. The baseline leg is stubbed and counted."""
    repo = _repo(tmp_path / "repo")
    _activate(monkeypatch, tmp_path, repo)
    a = _git(repo, "rev-parse", "main")
    b = _commit(repo, "b", write={"briefs/b.md": "# b\n", "briefs/b.handback.md": "# hb\n"})
    c = _commit(repo, "c", write={"src/a.ts": "export const a = 9;\n"})
    measured = []

    def _baseline(repo_path, sha, cmd):
        measured.append(sha)
        return orchestrator.UnitSuiteRun(ref=f"merge-base {sha[:7]}", exit_code=1, duration_s=301.0,
                                         **orchestrator._parse_unit_summary(vitest([UA], failed=1)))
    monkeypatch.setattr(orchestrator, "_run_unit_baseline", _baseline)
    return types.SimpleNamespace(repo=repo, a=a, b=b, c=c, measured=measured, archive=tmp_path / "archive")


def _reuse(t, sha):
    return orchestrator._unit_baseline_measure_or_reuse(t.repo, sha, TEST_CMD, t.archive, REPO)


def _entries(archive) -> dict:
    return json.loads((archive / orchestrator.UNIT_BASELINE_CACHE_FILE).read_text())["entries"]


class TestP2ContentKey:

    def test_the_key_ignores_briefs_and_nothing_else(self, tree):
        k = orchestrator._unit_content_key
        assert k(tree.repo, tree.a) == k(tree.repo, tree.b) != k(tree.repo, tree.c)
        mode = _commit(tree.repo, "mode", base=tree.a, keep=True)
        os.chmod(tree.repo / "src" / "a.ts", 0o755)
        _git(tree.repo, "commit", "-qam", "mode only")
        mode = _git(tree.repo, "rev-parse", "HEAD")
        _git(tree.repo, "checkout", "-q", "main")
        assert k(tree.repo, mode) != k(tree.repo, tree.a), "a mode change is a code change"
        assert k(tree.repo, "0" * 40) is None, "an unreachable commit has no key — none is guessed"

    def test_measured_at_a_hits_at_b_and_says_both(self, tree, caplog):
        run, source, note = _reuse(tree, tree.a)
        assert (source, tree.measured) == ("measured", [tree.a])
        with caplog.at_level(logging.INFO, logger="orch"):
            run, source, note = _reuse(tree, tree.b)
        assert (source, tree.measured) == ("cache", [tree.a]), "no baseline run at B"
        assert (f"cache hit by content: measured at {tree.a[:7]}, merge base {tree.b[:7]}, "
                f"non-briefs tree identical") in note
        assert run.failing_files == (UA,) and run.ref == f"merge-base {tree.b[:7]} (measured at {tree.a[:7]})"
        assert any("CACHE HIT" in m and "no baseline run" in m for m in _msgs(caplog))

    def test_a_src_change_misses(self, tree):
        _reuse(tree, tree.a)
        _, source, _ = _reuse(tree, tree.c)
        assert (source, tree.measured) == ("measured", [tree.a, tree.c])

    def test_a_non_ancestor_measurement_is_never_borrowed_and_an_ancestor_is(self, tree):
        """The ancestor fallback is unchanged under content keys: C (a sibling of B) is never borrowed for B;
        A (B's parent) is — and says how far back."""
        run = orchestrator.UnitSuiteRun(ref="x", exit_code=1, failures=1, tests_total=18, test_files_total=6,
                                        failing_files=(UA,))
        orchestrator._unit_cache_store(tree.archive, REPO, tree.c, TEST_CMD, run, repo_path=tree.repo)
        assert orchestrator._unit_cache_ancestor(tree.repo, tree.archive, REPO, tree.b, TEST_CMD) is None
        orchestrator._unit_cache_store(tree.archive, REPO, tree.a, TEST_CMD, run, repo_path=tree.repo)
        anc = orchestrator._unit_cache_ancestor(tree.repo, tree.archive, REPO, tree.b, TEST_CMD)
        assert anc["sha"] == tree.a and anc["ancestor_distance"] == 1

    def test_the_entry_keeps_the_sha_it_measured_and_its_content_key(self, tree):
        _reuse(tree, tree.a)
        (key, e), = _entries(tree.archive).items()
        ck = orchestrator._unit_content_key(tree.repo, tree.a)
        assert key == orchestrator._unit_cache_key(REPO, ck, TEST_CMD)
        assert (e["sha"], e["content_key"], e["clock"]) == (tree.a, ck, "plausible")
        assert json.loads((tree.archive / orchestrator.UNIT_BASELINE_CACHE_FILE).read_text())["version"] == 2

    def test_an_unjudged_entry_is_a_miss_as_before(self, tree, caplog):
        _reuse(tree, tree.a)
        f = tree.archive / orchestrator.UNIT_BASELINE_CACHE_FILE
        data = json.loads(f.read_text())
        for e in data["entries"].values():
            e.pop("clock")
        f.write_text(json.dumps(data))
        with caplog.at_level(logging.INFO, logger="orch"):
            _, source, _ = _reuse(tree, tree.b)
        assert (source, tree.measured) == ("measured", [tree.a, tree.b])
        assert any("predates GATE-CLOCK-1" in m for m in _msgs(caplog))

    def test_the_unit_gate_reads_the_content_hit(self, tree, monkeypatch):
        """A route forks at B (main moved by briefs only); the baseline measured at A is reused."""
        _reuse(tree, tree.a)
        _git(tree.repo, "merge", "-q", "--ff-only", "b")
        _commit(tree.repo, "route", write={"src/new.ts": "export const n = 1;\n"})

        def _suite(cmd, cwd, ref, timeout=None):
            return orchestrator.UnitSuiteRun(ref=ref, exit_code=1, duration_s=5.0,
                                             **orchestrator._parse_unit_summary(vitest([UA], failed=1)))
        monkeypatch.setattr(orchestrator, "_run_unit_suite", _suite)
        o = orchestrator.run_unit_gate(tree.repo, "route", archive_path=tree.archive)
        assert o.passed is True and o.baseline_source == "cache" and tree.measured == [tree.a]
        assert f"(measured at {tree.a[:7]})" in o.collection and "non-briefs tree identical" in o.baseline_note


class TestP2Migration:

    def _v1(self, archive, *entries):
        archive.mkdir(parents=True, exist_ok=True)
        (archive / orchestrator.UNIT_BASELINE_CACHE_FILE).write_text(json.dumps({"version": 1, "entries": {
            f"{REPO}@{e['sha']}@11111111": {"repo": REPO, "test_cmd": TEST_CMD, "clock": "plausible",
                                            "failures": 1, "failing_files": [UA], **e} for e in entries}}))

    def test_v1_entries_migrate_and_an_unreachable_one_is_dropped_with_one_line(self, tree, caplog):
        dead = "deadbeef" * 5
        self._v1(tree.archive, {"sha": tree.a, "measured_at": "2026-10-15T01:00:00"},
                 {"sha": dead, "measured_at": "2026-10-14T01:00:00"})
        with caplog.at_level(logging.INFO, logger="orch"):
            entries = orchestrator._unit_cache_load(tree.archive)
        ck = orchestrator._unit_content_key(tree.repo, tree.a)
        assert list(entries) == [orchestrator._unit_cache_key(REPO, ck, TEST_CMD)]
        assert entries[list(entries)[0]]["content_key"] == ck and entries[list(entries)[0]]["sha"] == tree.a
        dropped = [m for m in _msgs(caplog) if m.startswith("♻️  Unit baseline cache v1 → v2: entry ")]
        assert len(dropped) == 1 and dead[:7] in dropped[0], dropped
        on_disk = json.loads((tree.archive / orchestrator.UNIT_BASELINE_CACHE_FILE).read_text())
        assert on_disk["version"] == 2 and list(on_disk["entries"]) == list(entries), "migrated once, on first load"
        _, source, _ = _reuse(tree, tree.b)
        assert source == "cache" and tree.measured == [], "the migrated entry hits for B by content"

    def test_two_v1_entries_with_one_tree_become_one_and_keep_both_flaky_tallies(self, tree):
        self._v1(tree.archive,
                 {"sha": tree.a, "measured_at": "2026-10-14T01:00:00", "flaky_files": [UB],
                  "flaky_seen": {UB: {"count": 2, "last_seen": "2026-10-14T01:00:00"}}},
                 {"sha": tree.b, "measured_at": "2026-10-15T01:00:00", "flaky_files": [UB],
                  "flaky_seen": {UB: {"count": 1, "last_seen": "2026-10-15T01:00:00"}}})
        (e,) = orchestrator._unit_cache_load(tree.archive).values()
        assert e["sha"] == tree.b, "the newer measurement is kept"
        assert e["flaky_seen"][UB] == {"count": 3, "last_seen": "2026-10-15T01:00:00"}

    def test_the_flaky_report_migrates_in_memory_and_writes_nothing(self, tree):
        self._v1(tree.archive, {"sha": tree.a, "measured_at": "t", "flaky_files": [UB],
                                "flaky_seen": {UB: {"count": 1, "last_seen": "t"}}})
        before = (tree.archive / orchestrator.UNIT_BASELINE_CACHE_FILE).read_bytes()
        assert orchestrator._flaky_collect(tree.archive)[REPO][UB]["count"] == 1
        assert (tree.archive / orchestrator.UNIT_BASELINE_CACHE_FILE).read_bytes() == before


# ═══════════════════════════════════════════════════════
# P3 · D3 — per-merge SIT runs the related files
# ═══════════════════════════════════════════════════════
class Sit:
    """subprocess.run for the SIT leg: the full list, the related list (`--changed`), the batches and the
    isolation runs, each scripted; nothing else is expected."""

    def __init__(self, monkeypatch, related=(0, "", ""), red=(), red_alone=()):
        self.calls, self.related, self.red, self.red_alone = [], related, set(red), set(red_alone)
        self.batches = 0
        monkeypatch.setattr(subprocess, "run", self)
        monkeypatch.setattr("time.sleep", lambda s: None)

    def __call__(self, cmd, *a, **kw):
        self.calls.append(cmd)
        if cmd.startswith(LIST_CMD) and "--changed" in cmd:
            rc, out, err = self.related
            return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr=err)
        if cmd.startswith(LIST_CMD):
            return subprocess.CompletedProcess(cmd, 0, stdout=LIST_OUT, stderr="")
        assert cmd.startswith(SIT_CMD + " -- "), cmd
        files = [f for f in F.values() if f in cmd]
        alone = len(files) == 1 and self.batches_done
        red = [f for f in files if f in (self.red_alone if alone else self.red)]
        return subprocess.CompletedProcess(cmd, 1 if red else 0, stdout=batch(len(files), red), stderr="")

    batches_done = False

    def handed(self) -> list:
        return [[f for f in F.values() if f in c] for c in self.calls if c.startswith(SIT_CMD)]


@pytest.fixture
def sit(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _activate(monkeypatch, tmp_path, repo, gates=("sit",), sit_list_cmd=LIST_CMD, sit_batch_files=10,
              sit_batch_pause_s=0)
    return types.SimpleNamespace(repo=repo, archive=tmp_path / "archive", monkeypatch=monkeypatch)


def _diff(*paths, base="b" * 40):
    return orchestrator.BranchDiff(base=base, tip="route", paths=tuple(paths))


def _run_sit(s, diff):
    return orchestrator.run_sit_post_merge(s.repo, s.archive, diff=diff)


class TestP3Related:

    def test_affected_plus_added_is_exactly_what_runs(self, sit, caplog):
        fake = Sit(sit.monkeypatch, related=(0, f"{F[2]}\n", ""))
        with caplog.at_level(logging.INFO, logger="orch"):
            so = _run_sit(sit, _diff("src/lib/a.ts", F[4]))
        assert any("--changed bbbbbbb" in c and "--filesOnly" in c for c in fake.calls), fake.calls
        assert fake.handed() == [[F[2], F[4]]], "exactly {affected} ∪ {added}, in listing order"
        assert so.passed and so.scope == "related 2/5"
        assert so.collection.startswith("sit[related 2/5 files] 2 files/4 tests in 1 batches, ")
        assert any("(equals the enumerated related set: 2 of 5 files / 4 tests)" in m for m in _msgs(caplog))
        log_entry = json.loads((sit.archive / "orchestrator-sit-log.json").read_text())[-1]
        assert log_entry["scope"] == "related 2/5"

    def test_the_verdict_line_names_the_mode(self, sit):
        Sit(sit.monkeypatch, related=(0, f"{F[2]}\n", ""))
        sit.monkeypatch.setattr(orchestrator, "_branch_diff", lambda *a: _diff("src/lib/a.ts"))
        sit.monkeypatch.setattr(orchestrator, "run_unit_gate", lambda *a, **k: orchestrator.UnitGateOutcome(
            passed=True, signal="ungated", detail="x"))
        v = orchestrator.run_pre_merge_gates(sit.repo, "route")
        assert v.outcome is PASS and v.collection.startswith("sit[related 1/5 files] 1 files/2 tests")

    def test_an_empty_union_is_not_applicable_pass_and_runs_nothing(self, sit, caplog):
        fake = Sit(sit.monkeypatch, related=(0, "", ""))
        with caplog.at_level(logging.INFO, logger="orch"):
            so = _run_sit(sit, _diff("src/x.ts", "README.md", "docs/y.md"))
        assert fake.handed() == [], "no SIT invocation"
        assert so.passed is True and so.error is None and so.batches is None
        assert so.not_applicable == so.collection == "sit: no SIT file relates to this diff (3 changed files)"
        entry = json.loads((sit.archive / "orchestrator-sit-log.json").read_text())[-1]
        assert (entry["passed"], entry["scope"], entry["not_applicable"]) == (True, "none", so.not_applicable)
        assert not any("zero-collection" in m and "BLOCKED" in m for m in _msgs(caplog))

    def test_not_applicable_reaches_the_verdict_and_never_reads_as_sit_green(self, sit):
        Sit(sit.monkeypatch, related=(0, "", ""))
        sit.monkeypatch.setattr(orchestrator, "_branch_diff", lambda *a: _diff("src/x.ts"))
        sit.monkeypatch.setattr(orchestrator, "run_unit_gate", lambda *a, **k: orchestrator.UnitGateOutcome(
            passed=True, ran=True, detail="green"))
        v = orchestrator.run_pre_merge_gates(sit.repo, "route")
        assert v.outcome is PASS
        assert v.detail == "unit green on route; sit: no SIT file relates to this diff (1 changed files)"
        assert v.collection == "sit: no SIT file relates to this diff (1 changed files)"

    @pytest.mark.parametrize("related,why", [
        ((1, "", "Collect Error\nError: fatal: bad revision"), "exit 1"),
        ((0, "", "There were unhandled errors during test collection"), "exit 0"),
    ], ids=["exit-1", "exit-0-with-collection-errors"])
    def test_an_enumeration_failure_runs_the_full_suite_and_says_why(self, sit, caplog, related, why):
        fake = Sit(sit.monkeypatch, related=related)
        with caplog.at_level(logging.INFO, logger="orch"):
            so = _run_sit(sit, _diff("src/x.ts"))
        assert fake.handed() == [list(F.values())], "never none — the full suite"
        assert so.scope == "full 5" and so.collection.startswith("sit[full 5 files] 5 files/10 tests")
        assert any("related set not computed" in m and why in m and "FULL suite" in m for m in _msgs(caplog))

    def test_an_unknown_diff_runs_the_full_suite(self, sit, caplog):
        fake = Sit(sit.monkeypatch)
        with caplog.at_level(logging.INFO, logger="orch"):
            so = _run_sit(sit, orchestrator.BranchDiff(error="git diff failed"))
        assert fake.handed() == [list(F.values())] and so.scope == "full 5"
        assert not any("--changed" in c for c in fake.calls)

    def test_a_change_to_the_sit_config_runs_the_full_suite(self, sit):
        sit.monkeypatch.setitem(orchestrator.ACTIVE_REPO_CONFIG, "sit_list_cmd", f"{LIST_CMD} --config sit.config.ts")
        fake = Sit(sit.monkeypatch, related=(0, "", ""))
        so = _run_sit(sit, _diff("sit.config.ts"))
        assert fake.handed() == [list(F.values())] and so.scope == "full 5"

    def test_the_core_set_joins_and_an_unknown_name_is_said(self, sit, caplog):
        sit.monkeypatch.setitem(orchestrator.ACTIVE_REPO_CONFIG, "sit_core_files", [F[5], "sit/integration/nope.ts"])
        fake = Sit(sit.monkeypatch, related=(0, "", ""))
        with caplog.at_level(logging.INFO, logger="orch"):
            so = _run_sit(sit, _diff("src/x.ts"))
        assert fake.handed() == [[F[5]]] and so.scope == "related 1/5"
        assert any("sit_core_files" in m and "nope.ts" in m for m in _msgs(caplog))

    def test_a_related_batch_is_its_own_leg_kind(self, sit):
        Sit(sit.monkeypatch, related=(0, f"{F[1]}\n", ""))
        _run_sit(sit, _diff("src/x.ts"))
        kinds = json.loads((sit.archive / orchestrator.GATE_DURATIONS_FILE).read_text())["repos"][REPO]
        assert "sit-batch-related" in kinds and "sit-batch" not in kinds

    def test_negative_control_no_diff_is_the_whole_suite_as_before(self, sit):
        fake = Sit(sit.monkeypatch)
        so = orchestrator.run_sit_post_merge(sit.repo, sit.archive)
        assert fake.handed() == [list(F.values())] and so.scope is None
        assert so.collection.startswith("5 files/10 tests in 1 batches, ")


class TestP3GateSit2OnTheRelatedSet:

    def _red(self, sit, red_alone):
        fake = Sit(sit.monkeypatch, related=(0, f"{F[2]}\n{F[4]}\n", ""), red={F[2]}, red_alone=red_alone)
        orig = fake.__call__

        def _call(cmd, *a, **kw):        # the batch runs first; every later sit:gate call is the isolation leg
            r = orig(cmd, *a, **kw)
            if cmd.startswith(SIT_CMD):
                fake.batches_done = True
            return r
        sit.monkeypatch.setattr(subprocess, "run", _call)
        so = _run_sit(sit, _diff("src/x.ts"))
        v = orchestrator._classify_gate_failure("sit", so.output, sit.repo, so.exit_code, tests_failed=so.tests_failed,
                                                files_failed=so.files_failed, isolation=so.isolation, clock=so.clock)
        return fake, so, v

    def test_a_red_related_file_confirmed_alone_is_product(self, sit):
        fake, so, v = self._red(sit, red_alone={F[2]})
        assert fake.handed() == [[F[2], F[4]], [F[2]]], "the batch, then F2 alone"
        assert so.isolation.confirmed == (F[2],) and v.outcome is PRODUCT
        assert orchestrator.sit_verdict_violations(so, v) == []

    def test_a_red_related_file_that_passes_alone_is_contamination(self, sit):
        fake, so, v = self._red(sit, red_alone=set())
        assert so.isolation.contaminated == (F[2],) and (v.outcome, v.signal) == (PASS, "batch-contamination")
        assert orchestrator.sit_verdict_violations(so, v) == []


# ═══════════════════════════════════════════════════════
# P4 · D4 — `full-gate`
# ═══════════════════════════════════════════════════════
class FullGate:
    """A real project repo, an orchestrator dir under tmp_path, and the suite commands scripted."""

    def __init__(self, tmp_path, monkeypatch):
        self.repo = _repo(tmp_path / "project")
        self.orch = tmp_path / "orch"
        (self.orch / "state").mkdir(parents=True)
        _activate(monkeypatch, tmp_path, self.repo, gates=("build", "sit"), sit_list_cmd=LIST_CMD,
                  sit_batch_files=2, sit_batch_pause_s=0)
        monkeypatch.setattr(orchestrator, "ORCH_DIR", self.orch)
        # GATE-CLOCK-1 judges every leg: each scripted command takes a steady 5 s on the scripted clock
        self.clock = Clock()
        monkeypatch.setattr(orchestrator, "time", self.clock.module())
        self.archive, self.real = tmp_path / "archive", subprocess.run
        self.calls, self.cwds, self.lock_seen = [], [], None
        self.unit_out, self.confirm_out, self.sit_red, self.sit_red_alone = vitest(), vitest(total_tests=2,
                                                                                           total_files=1), set(), set()
        self._batches = 0
        monkeypatch.setattr(subprocess, "run", self)

    def __call__(self, cmd, *a, **kw):
        if not (isinstance(cmd, str) and cmd.startswith(("npm ", "npx "))):
            return self.real(cmd, *a, **kw)
        self.clock.advance(5.0)
        self.cwds.append(kw.get("cwd"))
        if cmd.startswith(LIST_CMD):
            self.calls.append("list")
            return subprocess.CompletedProcess(cmd, 0, stdout=LIST_OUT, stderr="")
        if cmd.startswith(SIT_CMD):
            files = [f for f in F.values() if f in cmd]
            self._batches += 1
            alone = self._batches > 3          # 5 files, batches of 2: three batches, then the isolation leg
            self.calls.append("isolation" if alone else "batch")
            red = [f for f in files if f in (self.sit_red_alone if alone else self.sit_red)]
            return subprocess.CompletedProcess(cmd, 1 if red else 0, stdout=batch(len(files), red), stderr="")
        if cmd == TEST_CMD:
            self.calls.append("unit")
            lock = self.orch / "state" / f"running-{REPO}.json"
            self.lock_seen = json.loads(lock.read_text()) if lock.exists() else None
            return subprocess.CompletedProcess(cmd, 0 if "FAIL" not in self.unit_out else 1, stdout=self.unit_out,
                                               stderr="")
        if cmd.startswith(TEST_CMD + " -- "):
            self.calls.append("confirm")
            return subprocess.CompletedProcess(cmd, 0 if "FAIL" not in self.confirm_out else 1,
                                               stdout=self.confirm_out, stderr="")
        raise AssertionError(cmd)

    def run(self, *args, **kw) -> int:
        self._batches = 0
        return orchestrator.full_gate(*args, **kw)

    def state(self) -> dict:
        f = self.orch / "state" / f"full-gate-{REPO}.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def seed(self, failing):
        """A judged baseline for main's tree, as a route off main would have measured it."""
        sha = _git(self.repo, "rev-parse", "main")
        orchestrator._unit_cache_store(self.archive, REPO, sha, TEST_CMD, orchestrator.UnitSuiteRun(
            ref=f"merge-base {sha[:7]}", exit_code=1, duration_s=300.0,
            **orchestrator._parse_unit_summary(vitest(list(failing), failed=len(failing)))), repo_path=self.repo)


@pytest.fixture
def fg(tmp_path, monkeypatch):
    return FullGate(tmp_path, monkeypatch)


def _live_pid() -> int:
    return os.getppid()     # alive, and not this process


class TestP4FullGate:

    def test_a_held_fire_lock_refuses_with_exit_2_and_runs_nothing(self, fg, capsys):
        (fg.orch / "state" / f"running-{REPO}.json").write_text(json.dumps(
            {"pid": _live_pid(), "batch_id": "300-x", "repo": REPO}))
        assert fg.run() == 2
        err = capsys.readouterr().err.strip().splitlines()
        assert len(err) == 1 and err[0].startswith(f"⛔ full-gate {REPO}: refused — fire lock held — {REPO} 300-x")
        assert fg.calls == [] and fg.state() == {}

    def test_a_route_the_daemon_reports_live_refuses(self, fg, capsys):
        (fg.orch / "queue-state.json").write_text(json.dumps(
            {"pid": _live_pid(), "daemon_status": "running", "current_batch": {"file": "300-x.md"}}))
        assert fg.run() == 2
        assert "the queue daemon" in capsys.readouterr().err and fg.calls == []

    def test_negative_control_a_dead_lock_does_not_refuse(self, fg):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        (fg.orch / "state" / f"running-{REPO}.json").write_text(json.dumps(
            {"pid": dead.pid, "batch_id": "300-x", "repo": REPO}))
        assert fg.run() == 0

    def test_idle_runs_the_full_sit_and_unit_and_writes_its_state(self, fg):
        sha = _git(fg.repo, "rev-parse", "main")
        assert fg.run() == 0
        assert fg.calls == ["list", "batch", "batch", "batch", "unit"]
        st = fg.state()
        assert (st["outcome"], st["exit_code"], st["sha"], st["ref"]) == ("PASS", 0, sha, "main")
        assert st["content_key"] == orchestrator._unit_content_key(fg.repo, sha)
        assert st["sit"]["collection"].startswith("5 files/10 tests in 3 batches") and st["sit"]["scope"] == "full 5"
        assert st["unit"]["collection"].startswith("6 files/18 tests") and st["unit"]["failing_files"] == []
        assert st["clock"] == {"sit": "plausible", "unit": "plausible", "unit_confirm": "not engaged"}
        assert isinstance(st["duration_s"], float) and Path(st["log"]).exists()
        assert all(Path(c) != fg.repo for c in fg.cwds), "it runs in a detached worktree, never the checkout"

    def test_it_holds_the_fire_lock_while_it_runs_and_releases_it(self, fg):
        fg.run()
        assert fg.lock_seen["pid"] == os.getpid() and fg.lock_seen["repo"] == REPO
        assert fg.lock_seen["batch_id"].startswith("full-gate-") and fg.lock_seen["route_worktree"]
        assert not (fg.orch / "state" / f"running-{REPO}.json").exists()
        assert len(_git(fg.repo, "worktree", "list").splitlines()) == 1, "its worktree is removed"

    def test_a_unit_failure_not_in_the_baseline_exits_1(self, fg):
        fg.seed([UA])
        fg.unit_out, fg.confirm_out = vitest([UA, UB], failed=2), vitest([UB], failed=1, total_tests=2, total_files=1)
        assert fg.run() == 1
        st = fg.state()
        assert st["outcome"] == "NEW FAILURES" and st["unit"]["new"] == [UB]
        assert st["unit"]["baseline"]["source"] == "cache" and fg.calls[-1] == "confirm"

    def test_negative_control_a_failure_in_the_baseline_exits_0(self, fg):
        fg.seed([UA])
        fg.unit_out = vitest([UA], failed=1)
        assert fg.run() == 0 and fg.state()["unit"]["new"] == []

    def test_a_new_file_that_passes_alone_is_a_flake_not_new(self, fg):
        fg.seed([UA])
        fg.unit_out = vitest([UA, UB], failed=2)
        assert fg.run() == 0 and fg.state()["unit"]["flaky"] == [UB]

    def test_its_plausible_unit_run_becomes_the_trees_baseline(self, fg):
        fg.unit_out = vitest([UA], failed=1)
        fg.run()
        sha = _git(fg.repo, "rev-parse", "main")
        hit = orchestrator._unit_cache_lookup(fg.archive, REPO, sha, TEST_CMD, repo_path=fg.repo)
        assert hit["sha"] == sha and hit["failing_files"] == [UA] and fg.state()["unit"]["cached"] is True

    def test_sit_is_compared_against_the_previous_full_gate(self, fg):
        fg.sit_red, fg.sit_red_alone = {F[3]}, {F[3]}
        assert fg.run() == 1, "no previous SIT measurement: the confirmed failure is new"
        assert fg.state()["sit"]["new"] == [F[3]] and "isolation" in fg.calls
        assert fg.run() == 0, "the same failure the previous full-gate had is not new"
        st = fg.state()
        assert st["sit"]["outcome"] == "FAIL(product)" and st["sit"]["new"] == []
        assert st["history"][-1]["sit_failing_files"] == [F[3]]

    def test_dry_run_prints_the_plan_and_runs_nothing(self, fg, capsys):
        assert fg.run(dry_run=True) == 0
        out = capsys.readouterr().out
        assert "SIT: sit[full 5 files] — 5 files / 10 tests enumerated in the project checkout" in out
        assert f"unit: `{TEST_CMD}` — the full suite" in out and "lock: free" in out
        assert fg.calls == ["list"] and fg.cwds == [str(fg.repo)]
        assert fg.state() == {} and not (fg.orch / "state" / f"running-{REPO}.json").exists()

    def test_a_ref_that_is_not_a_commit_refuses(self, fg, capsys):
        assert fg.run("no-such-ref") == 2 and fg.calls == []


# ── the daemon's nightly step ────────────────────────────────────────────────────────────────────────────────
class Night:
    def __init__(self, tmp_path, monkeypatch, schedule=None):
        self.orch = tmp_path / "orch"
        (self.orch / "state").mkdir(parents=True)
        self.queue = self.orch / "queue"
        self.state_file = tmp_path / "queue-state.json"
        self.cfg = tmp_path / "repos.yaml"
        self.cfg.write_text(yaml.safe_dump({"repos": {name: {"project_dir": str(tmp_path), "full_gate_nightly": hhmm}
                                                      for name, hhmm in (schedule or {"cmp": "02:30"}).items()}}))
        for name, val in (("ORCH_DIR", self.orch), ("QUEUE_DIR", self.queue), ("QUEUE_DONE", self.queue / "done"),
                          ("QUEUE_FAILED", self.queue / "failed"), ("QUEUE_STATE", self.state_file),
                          ("REPOS_CONFIG", self.cfg), ("LOG_DIR", tmp_path / "logs")):
            monkeypatch.setattr(queue_daemon, name, val)
        self.now = datetime(2026, 10, 17, 2, 0)
        monkeypatch.setattr(queue_daemon, "FULL_GATE_CLOCK", lambda: self.now)
        self.idle = True
        monkeypatch.setattr(queue_daemon.admission, "admit", lambda repo, batch=None, **kw: (
            (True, "admitted") if self.idle else
            (False, "route limit — 1 live route(s): clinical-mp 300-x (pid 1, state/running-clinical-mp.json)")))
        self.events = []
        self.d = self.fresh()

    def fresh(self):
        d = queue_daemon.QueueDaemon()
        d.is_daemon, d.status = True, "running"
        d._run_full_gate = lambda repo, hhmm: self.events.append(("full-gate", repo, self.now)) or 0
        d.config.update(cooldown_seconds=0)
        return d

    def at(self, h, m, day=17):
        self.now = datetime(2026, 10, day, h, m)
        return self.d._full_gate_step()


@pytest.fixture
def night(tmp_path, monkeypatch):
    return Night(tmp_path, monkeypatch)


class TestP4Nightly:

    def test_due_at_its_time_idle_and_running_runs_once_that_day(self, night):
        assert night.at(2, 29) is False and night.events == []
        assert night.at(2, 30) is True and [e[:2] for e in night.events] == [("full-gate", "cmp")]
        assert night.at(2, 31) is False and night.at(23, 59) is False, "never twice the same day"
        assert len(night.events) == 1
        assert night.at(2, 30, day=18) is True and len(night.events) == 2, "the next day, once more"

    def test_paused_is_not_run_and_logged_skipped(self, night, capsys):
        night.d.status, night.d.paused_reason = "paused", "operator"
        assert night.at(2, 30) is False and night.at(4, 0) is False and night.events == []
        out = capsys.readouterr().out
        assert out.count("[QUEUE] 🌙 full-gate cmp: due at 02:30, not run now — daemon paused (operator)") == 1
        night.at(0, 5, day=18)
        assert "[QUEUE] 🌙 full-gate cmp: SKIPPED 2026-10-17 — the 02:30 window was missed (daemon paused " \
               "(operator))" in capsys.readouterr().out
        assert night.events == []

    def test_busy_at_its_time_runs_after_the_route_ends(self, night, capsys):
        night.idle = False
        assert night.at(2, 30) is False and night.at(2, 40) is False and night.events == []
        assert capsys.readouterr().out.count("not run now — busy — route limit") == 1
        night.idle = True
        assert night.at(3, 5) is True and night.events[0][2] == datetime(2026, 10, 17, 3, 5)

    def test_a_restart_the_same_day_does_not_run_it_again(self, night):
        night.at(2, 30)
        night.d._save_state()
        night.d = night.fresh()
        assert night.at(3, 0) is False and len(night.events) == 1

    def test_a_repo_with_no_schedule_is_never_run(self, tmp_path, monkeypatch):
        n = Night(tmp_path, monkeypatch, schedule={"cmp": "2:30"})      # not "HH:MM"
        n.cfg.write_text(yaml.safe_dump({"repos": {"cmp": {"project_dir": "/x", "full_gate_nightly": 150},
                                                   "other": {"project_dir": "/x"}}}))
        assert n.at(3, 0) is False and n.events == []

    def test_the_run_loop_runs_it_between_routes_never_over_one(self, night, monkeypatch):
        night.queue.mkdir(parents=True, exist_ok=True)
        (night.queue / "300-x.md").write_text("#!queue repo=cmp\n\n# 300\n")
        night.d.start_running = True
        night.d.is_daemon = False
        night.now = datetime(2026, 10, 17, 2, 45)

        def _route(cmd, batch_name, log_path):
            night.events.append(("route", batch_name, None))
            Path(log_path).write_text("route output\n")
            return 0
        night.d._run_route = _route

        def _sleep(s):
            night.d.status = "stopped"
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep))
        night.d.run_loop()
        assert [e[:2] for e in night.events] == [("full-gate", "cmp"), ("route", "300-x.md")]

    def test_the_real_runner_logs_to_a_file_and_never_marks_a_route(self, night, tmp_path):
        (night.orch / "orchestrator.py").write_text(textwrap.dedent(f'''\
            import json, sys, datetime, pathlib
            st = json.loads(pathlib.Path({str(night.state_file)!r}).read_text())
            assert st["full_gate_running"]["repo"] == "cmp" and st["current_batch"] is None
            pathlib.Path({str(night.orch / "state" / "full-gate-cmp.json")!r}).write_text(json.dumps({{
                "repo": "cmp", "outcome": "NEW FAILURES", "sha": "a1b2c3d4e5",
                "started_at": datetime.datetime.now().isoformat(), "finished_at": "2026-10-17T02:41:00"}}))
            print("argv:", " ".join(sys.argv[1:]))
            sys.exit(1)
            '''))
        d = queue_daemon.QueueDaemon()
        d.is_daemon, d.status = True, "running"
        assert d._run_full_gate("cmp", "02:30") == 1
        assert (d.full_gate["cmp"]["last"]["outcome"], d.full_gate["cmp"]["last"]["sha"]) == ("NEW FAILURES", "a1b2c3d")
        assert d.full_gate_running is None and d.current_batch is None
        logs = list((tmp_path / "logs" / "cmp").glob("full-gate-*.log"))
        text = logs[0].read_text()
        assert "=== QUEUE FULL GATE ===" in text and "argv: full-gate --repo cmp --trigger nightly --log-file" in text
        assert "Exit: 1" in text
        assert json.loads(night.state_file.read_text())["full_gate_running"] is None


# ═══════════════════════════════════════════════════════
# P5 · every reader of the verdict lines parses the new ones
# ═══════════════════════════════════════════════════════
BRIEFS_ONLY_PASS = ("12:00:01 [INFO   ] ✅ Pre-merge gate on orch-mp-268-one-owner-1: PASS (briefs-only diff (2 files: "
                    "briefs/268-one-owner-1.handback.md, briefs/268-one-owner-1.md) — build/SIT/unit not run "
                    "(D-S7CORE29-02))")
BRIEFS_ONLY_FINAL = ("12:00:02 [INFO   ] 🏁 FINAL STATUS: passed | gate: PASS (briefs-only diff (2 files: "
                     "briefs/268-one-owner-1.handback.md, briefs/268-one-owner-1.md) — build/SIT/unit not run "
                     "(D-S7CORE29-02))")
RELATED_LINE = ("12:10:00 [INFO   ] 🏁 FINAL STATUS: passed | gate: PASS (sit[related 2/113 files] 2 files/5 tests in "
                "1 batches, 21.0s) | unit: baseline merge-base abc1234 (measured at 0f0f0f0): 789 files/7288 tests")
NA_LINE = "12:20:00 [INFO   ] 🧪 SIT gate: not applicable — sit: no SIT file relates to this diff (3 changed files)"


class TestP5Readers:

    def test_find_missing_gate_logs_does_not_flag_a_briefs_only_merge(self, tmp_path, monkeypatch):
        n = Night(tmp_path, monkeypatch, schedule={})
        n.cfg.write_text(yaml.safe_dump({"repos": {"cmp": {"project_dir": str(tmp_path)}}}))
        n.queue.mkdir(parents=True, exist_ok=True)
        (n.queue / "268-one-owner-1.md").write_text("#!queue repo=cmp\n\n# 268\n")
        d = queue_daemon.QueueDaemon()
        d.start_running = True
        d.config.update(cooldown_seconds=0)

        def _route(cmd, batch_name, log_path):
            Path(log_path).write_text(f"{BRIEFS_ONLY_PASS}\n{BRIEFS_ONLY_FINAL}\n")
            return 0
        d._run_route = _route
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=lambda s: setattr(d, "status", "stopped")))
        d.run_loop()
        assert [e["file"] for e in d.completed] == ["268-one-owner-1.md"]
        assert d.find_missing_gate_logs() == []
        Path(d.completed[0]["log_file"]).unlink()
        assert [v.reason for v in d.find_missing_gate_logs()] == ["log-missing"], "negative control"

    def test_qstat_shows_each_repos_last_full_gate(self, tmp_path):
        orch = tmp_path / "spectricom-orchestrator"
        (orch / "state").mkdir(parents=True)
        (orch / "queue").mkdir()
        (orch / "config").mkdir()
        (orch / "config" / "repos.yaml").write_text(yaml.safe_dump({"repos": {
            "clinical-mp": {"full_gate_nightly": "02:30"}, "yorsie": {"full_gate_nightly": "03:00"}}}))
        (orch / "state" / "full-gate-clinical-mp.json").write_text(json.dumps({
            "repo": "clinical-mp", "outcome": "PASS", "finished_at": "2026-10-17T02:41:07", "sha": "a1b2c3d4e5f6",
            "trigger": "nightly"}))
        (orch / "queue-state.json").write_text(json.dumps({"daemon_status": "running", "pid": os.getpid(),
                                                           "full_gate_running": {"repo": "yorsie",
                                                                                 "started_at": "2026-10-17T03:00:01"}}))
        r = subprocess.run(["bash", str(ROOT / "qstat.sh")], capture_output=True, text=True, timeout=60,
                           env={**os.environ, "HOME": str(tmp_path)})
        out = r.stdout + r.stderr
        assert "🌙 FULL-GATE clinical-mp | ✅ PASS | 2026-10-17T02:41 | sha a1b2c3d | nightly" in out, out
        assert "🌙 FULL-GATE yorsie | ⚪ never run | nightly 03:00" in out, out
        assert "🌙 FULL-GATE yorsie | running now | since 2026-10-17T03:00" in out, out

    def test_queue_daemon_status_names_the_last_full_gate_on_line_1(self, tmp_path, monkeypatch, capsys):
        n = Night(tmp_path, monkeypatch, schedule={"clinical-mp": "02:30", "orchestrator": "04:00"})
        (n.orch / "state" / "full-gate-clinical-mp.json").write_text(json.dumps({
            "repo": "clinical-mp", "outcome": "NEW FAILURES", "finished_at": "2026-10-17T02:58:44",
            "sha": "a1b2c3d4e5f6", "trigger": "nightly", "log": "/x/full-gate.log"}))
        n.state_file.write_text(json.dumps({"daemon_status": "running", "pid": os.getpid()}))
        assert queue_daemon.main(["status"]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0].startswith("daemon_status=running ")
        assert ("| full-gate clinical-mp: NEW FAILURES 2026-10-17T02:58 a1b2c3d (nightly 02:30) | "
                "full-gate orchestrator: never run (nightly 04:00)") in lines[0], lines[0]
        body = json.loads("\n".join(lines[1:]))
        assert body["full_gate"]["clinical-mp"]["outcome"] == "NEW FAILURES"

    def test_verify_shows_the_briefs_only_verdict(self, tmp_path, monkeypatch, capsys):
        repo = _repo(tmp_path / "repo")
        stem = "268-one-owner-1"
        sha = _commit(repo, "x", write={f"briefs/{stem}.md": "## Repo: cost-repo\n", f"briefs/{stem}.handback.md": "# hb\n"})
        repos = {REPO: {"project_dir": str(repo), "log_subdir": "cost", "briefs_subdir": "briefs",
                        "branch_prefix": "orch", "merge_target": "main"}}
        monkeypatch.setattr(orchestrator, "load_repo_config", lambda: {"repos": repos})
        logs = tmp_path / "logs"
        monkeypatch.setattr(orchestrator, "LOG_DIR", logs)
        monkeypatch.setattr(orchestrator, "QUEUE_DIR", tmp_path / "queue")
        monkeypatch.setattr(orchestrator, "QUEUE_DONE", tmp_path / "queue" / "done")
        (tmp_path / "queue" / "done").mkdir(parents=True)
        (tmp_path / "queue" / "done" / f"{stem}.md").write_text(f"#!queue repo={REPO}\n")
        (logs / "cost").mkdir(parents=True)
        (logs / "cost" / f"orch-{stem}-20261017-120000.log").write_text(
            f"{BRIEFS_ONLY_PASS}\n12:00:01 [INFO   ] 🔀 Merged orch-{stem} → main (aaaaaaa → {sha[:7]})\n"
            f"{BRIEFS_ONLY_FINAL}\n")
        _toni_log(logs / "cost" / f"toni-{stem}-20261017-120000.log")
        rc = orchestrator.verify_route(stem)
        out = capsys.readouterr().out
        assert rc == 0, out
        assert "Pre-merge gate on orch-mp-268-one-owner-1: PASS (briefs-only diff (2 files:" in out
        assert "FINAL STATUS: passed | gate: PASS (briefs-only diff" in out

    def test_sit_report_parses_related_and_not_applicable(self, tmp_path, monkeypatch, capsys):
        archive = tmp_path / "archive"
        archive.mkdir()
        (archive / "orchestrator-sit-log.json").write_text(json.dumps([
            {"timestamp": "2026-10-17T01:00:00", "passed": True, "duration_s": 21.0, "error": None,
             "scope": "related 2/113"},
            {"timestamp": "2026-10-17T01:10:00", "passed": True, "duration_s": 0.0, "error": None, "scope": "none",
             "not_applicable": "sit: no SIT file relates to this diff (3 changed files)"},
            {"timestamp": "2026-10-17T02:40:00", "passed": True, "duration_s": 1500.0, "error": None}]))
        monkeypatch.setattr(orchestrator, "SIT_ARCHIVE_DIR", archive)
        orchestrator.sit_report_aggregate()
        out = capsys.readouterr().out
        assert "Per-merge related runs: 1; not applicable (no SIT file related to the diff): 1" in out
        assert "21.0s — sit[related 2/113 files]" in out
        assert "0.0s — sit: no SIT file relates to this diff (3 changed files)" in out
        assert "1500.0s\n" in out, "a full run reads as before"

    def test_handback_scan_does_not_read_the_new_lines_as_outstanding_work(self, tmp_path):
        log = tmp_path / "toni-279-x-20261017-120000.log"
        log.write_text(f"=== TONI EXECUTION ===\nBatch: x.md\nStarted: 2026-10-17T00:00:00\nCommand: claude\n{RULE}\n\n"
                       + "\n".join([BRIEFS_ONLY_PASS, RELATED_LINE, NA_LINE,
                                    "full-gate clinical-mp: PASS 2026-10-17T02:41 a1b2c3d (nightly 02:30)",
                                    "🌙 FULL-GATE yorsie | running now | since 2026-10-17T03:00",
                                    "[QUEUE] 🌙 full-gate cmp: due at 02:30, not run now — busy — route limit; it "
                                    "runs at the next idle moment today, else it is logged SKIPPED"])
                       + f"\n\n{RULE}\nFinished: 2026-10-17T00:01:00\nExit: 0\n")
        assert orchestrator.handback_scan([str(log)]) == 0

    def test_the_route_phase_reader_reads_a_briefs_only_pass_as_the_merge(self, tmp_path):
        log = tmp_path / "orch-268.log"
        log.write_text("Firing Toni: x\nToni finished: 0\n" + BRIEFS_ONLY_PASS + "\n")
        assert queue_daemon.route_phase(log) == "merge"

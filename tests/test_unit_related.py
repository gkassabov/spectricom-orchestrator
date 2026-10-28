# filename: tests/test_unit_related.py
"""Tests for ORCH-UNIT-RELATED-1 (S7-CORE-33 · D-S7CORE33-36 fix #1, Kanban row 405).

The unit gate's branch leg ran the whole suite on every route: 132 min/day on clinical-mp, 9.7 min a route over
~1,543 files, for a median diff of 12 files. It now runs the unit test files RELATED to the branch's diff — vitest's
own `list --changed <merge base>` on the unit config, enumerated and not run, plus the test files the branch
changes — and runs the full suite, and says why, on a shared trigger, every N-th route, when the set cannot be
computed, or when ORCH_UNIT_RELATED=off. The regression rule is unchanged: a related file is a regression iff it
fails alone on the branch and is not failing in the merge-base baseline (the cached full measurement restricted to
the related files, else the merge base measured on the same files).

  P2-1  a 3-file diff outside the triggers runs only the related test files                       (TestP2_1*)
  P2-2  each trigger class forces the full suite with its reason                                  (TestP2_2*)
  P2-3  the N-th route runs full and resets the counter; the counter is a file                    (TestP2_3*)
  P2-4  a related-only run is never stored as a landed full baseline                              (TestP2_4*)
  (the regression rule on the related set)                                                        (TestRule*)
  P2-5  is tests/test_unit_baseline_gate.py, tests/test_baseline_reuse_1.py, tests/test_gate_cost.py unchanged.

Harness: a REAL git repository (real merge base, real diff, a real detached worktree for a measured baseline); only
`npx vitest list …` and `npm test …` are scripted. Module-level imports are existing symbols only (RED collects).
"""

import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_gate_cost import REPO, TEST_CMD, _activate, _git, _msgs, vitest  # noqa: E402

ROOT = Path(__file__).parent.parent
PASS, PRODUCT = orchestrator.GateOutcome.PASS, orchestrator.GateOutcome.FAIL_PRODUCT
SUITE = [f"src/feature/t{i}.test.ts" for i in range(1, 9)] + ["src/lib/lib.test.ts", "server/s.test.ts"]
T1, T2, T3 = SUITE[0], SUITE[1], SUITE[2]
UNIT_LIST = "npx vitest list --filesOnly"
CLINICAL = yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"]["clinical-mp"]


def _repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "t@t")
    _git(path, "config", "user.name", "t")
    files = {"package.json": json.dumps({"scripts": {"test": "vitest run"}}) + "\n", "vite.config.ts": "x\n",
             "src/feature/a.ts": "a\n", "src/feature/b.ts": "b\n", "src/feature/c.ts": "c\n",
             "briefs/old.md": "# old\n", "docs/readme.md": "docs\n"}
    files.update({t: "test\n" for t in SUITE})
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "M0")
    return path


class Unit:
    """subprocess.run for the unit leg: the suite listing, the related listing, and `npm test [-- files]` — the branch
    leg and a confirmation in the checkout (the first run there is the branch leg), a baseline in a detached worktree
    — each recorded with its cwd; git runs for real. `red` fails on the branch and at the base; `red_alone` alone."""

    def __init__(self, monkeypatch, repo, related=(T1,), red=(), red_alone=(), list_rc=0):
        self.real, self.repo, self.related, self.list_rc = subprocess.run, str(repo), related, list_rc
        self.red, self.red_alone = set(red), set(red_alone)
        self.calls, self.branch_seen = [], False
        monkeypatch.setattr(subprocess, "run", self)

    def __call__(self, cmd, *a, **kw):
        if not (isinstance(cmd, str) and cmd.startswith(("npm ", "npx "))):
            return self.real(cmd, *a, **kw)
        self.calls.append((cmd, kw.get("cwd")))
        if cmd.startswith("npx vitest list") and "--changed" in cmd:
            return subprocess.CompletedProcess(cmd, self.list_rc, stdout="".join(f"{f}\n" for f in self.related),
                                               stderr="" if not self.list_rc else "Startup Error\n")
        if cmd.startswith("npx vitest list"):
            return subprocess.CompletedProcess(cmd, 0, stdout="".join(f"{f}\n" for f in SUITE), stderr="")
        if cmd == TEST_CMD or cmd.startswith(TEST_CMD + " -- "):
            files = SUITE if cmd == TEST_CMD else [f for f in SUITE if f in cmd.split(" -- ", 1)[1].split()]
            in_repo = kw.get("cwd") == self.repo
            confirm = in_repo and self.branch_seen
            self.branch_seen = self.branch_seen or in_repo
            red = sorted(set(files) & (self.red_alone if confirm else self.red))
            return subprocess.CompletedProcess(cmd, 1 if red else 0, stderr="", stdout=vitest(
                red, failed=len(red), total_tests=3 * len(files), total_files=len(files)))
        raise AssertionError(cmd)

    def runs(self) -> list:
        return [c for c, _ in self.calls if c.startswith(TEST_CMD)]


@pytest.fixture
def rig(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    orch = tmp_path / "orch"
    (orch / "state").mkdir(parents=True)
    monkeypatch.setattr(orchestrator, "ORCH_DIR", orch)
    cfg = _activate(monkeypatch, tmp_path, repo, gates=())
    monkeypatch.delenv("ORCH_UNIT_RELATED", raising=False)

    class R:
        pass
    r = R()
    r.repo, r.orch, r.cfg, r.archive, r.monkeypatch = repo, orch, cfg, tmp_path / "archive", monkeypatch
    return r


def _branch(repo, write, name="route"):
    _git(repo, "checkout", "-q", "-B", name, "main")
    for rel, text in write.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"{name} work")
    return _git(repo, "rev-parse", "HEAD")


THREE = {"src/feature/a.ts": "a2\n", "src/feature/b.ts": "b2\n", "src/feature/c.ts": "c2\n"}
PKG2 = json.dumps({"scripts": {"test": "vitest run"}, "dependencies": {"zod": "^3"}}) + "\n"   # a changed manifest


def _gate(r, branch="route"):
    return orchestrator.run_pre_merge_gates(r.repo, branch)


def _counter(r) -> dict:
    f = r.orch / "state" / f"unit-full-counter-{REPO}.json"
    return json.loads(f.read_text()) if f.exists() else {}


# ═══════════════════════════════════════════════════════
# P2-1 · a 3-file diff outside the triggers runs only the related test files
# ═══════════════════════════════════════════════════════
class TestP2_1Related:

    def test_a_three_file_diff_runs_only_the_related_files(self, rig, caplog):
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo, related=(T1, T2))
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert v.outcome is PASS, v.label
        assert u.runs() == [f"{TEST_CMD} -- {T1} {T2}"], u.runs()
        assert any(m.startswith(f"🎯 Unit gate: related 2/{len(SUITE)} files") for m in _msgs(caplog)), _msgs(caplog)
        assert f"related 2/{len(SUITE)} files" in v.unit_collection

    def test_the_listing_is_enumerated_not_run_against_the_merge_base(self, rig):
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo)
        _gate(rig)
        base = _git(rig.repo, "merge-base", "main", "route")
        lists = [c for c, _ in u.calls if c.startswith("npx vitest list")]
        assert UNIT_LIST in lists and f"npx vitest list --changed {base} --filesOnly" in lists, lists

    def test_test_files_the_branch_changes_join_the_set(self, rig):
        _branch(rig.repo, {**THREE, T3: "changed test\n"})
        u = Unit(rig.monkeypatch, rig.repo, related=(T1,))
        _gate(rig)
        assert u.runs() == [f"{TEST_CMD} -- {T1} {T3}"]

    def test_the_unit_log_carries_the_scope(self, rig):
        _branch(rig.repo, THREE)
        Unit(rig.monkeypatch, rig.repo)
        _gate(rig)
        last = json.loads((rig.archive / "orchestrator-unit-log.json").read_text())[-1]
        assert last["scope"] == f"related 1/{len(SUITE)}" and last["related_files"] == [T1]

    def test_a_docs_only_diff_with_no_related_file_runs_nothing_and_says_so(self, rig, caplog):
        _branch(rig.repo, {"docs/readme.md": "new docs\n"})
        u = Unit(rig.monkeypatch, rig.repo, related=())
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert v.outcome is PASS and u.runs() == []
        assert any("🎯 Unit gate: related 0/" in m and "nothing run" in m for m in _msgs(caplog)), _msgs(caplog)
        assert "no unit test file relates to this diff" in v.detail


# ═══════════════════════════════════════════════════════
# P2-2 · every trigger class forces the full suite, with its reason
# ═══════════════════════════════════════════════════════
TRIGGERS = ["package.json", "package-lock.json", "vitest.config.ts", "vite.config.ts", "tsconfig.app.json",
            "src/test/helpers.ts", "src/setupTests.ts", "src/lib/x.ts", "server/api.ts", "src/types/t.ts"]


class TestP2_2Full:

    @pytest.mark.parametrize("path", TRIGGERS)
    def test_a_clinical_mp_trigger_runs_the_full_suite(self, rig, caplog, path):
        rig.cfg["unit_full_triggers"] = CLINICAL["unit_full_triggers"]
        _branch(rig.repo, {**THREE, path: PKG2 if path == "package.json" else "changed\n"})
        u = Unit(rig.monkeypatch, rig.repo)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert u.runs() == [TEST_CMD], u.runs()
        line = next(m for m in _msgs(caplog) if m.startswith("🎯 Unit gate: full suite: "))
        assert "(a)" in line and path in line and "unit_full_triggers" in line
        assert "full suite: (a)" in v.unit_collection

    def test_a_sit_core_file_is_a_trigger(self, rig, caplog):
        rig.cfg["sit_core_files"] = ["sit/core.integration.test.ts"]
        _branch(rig.repo, {**THREE, "sit/core.integration.test.ts": "core\n"})
        u = Unit(rig.monkeypatch, rig.repo)
        with caplog.at_level(logging.INFO, logger="orch"):
            _gate(rig)
        assert u.runs() == [TEST_CMD]
        assert any("(a)" in m and "sit/core.integration.test.ts" in m for m in _msgs(caplog))

    def test_an_enumeration_failure_runs_the_full_suite(self, rig, caplog):
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo, list_rc=1)
        with caplog.at_level(logging.INFO, logger="orch"):
            _gate(rig)
        assert u.runs() == [TEST_CMD]
        assert any(m.startswith("🎯 Unit gate: full suite: (c)") for m in _msgs(caplog)), _msgs(caplog)

    def test_an_empty_related_set_with_source_changed_runs_the_full_suite(self, rig, caplog):
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo, related=())
        with caplog.at_level(logging.INFO, logger="orch"):
            _gate(rig)
        assert u.runs() == [TEST_CMD]
        assert any(m.startswith("🎯 Unit gate: full suite: (c)") and "non-test source" in m for m in _msgs(caplog))

    def test_off_runs_the_full_suite(self, rig, caplog):
        rig.monkeypatch.setenv("ORCH_UNIT_RELATED", "off")
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo)
        with caplog.at_level(logging.INFO, logger="orch"):
            _gate(rig)
        assert u.runs() == [TEST_CMD]
        assert any(m.startswith("🎯 Unit gate: full suite: (d) ORCH_UNIT_RELATED=off") for m in _msgs(caplog))

    def test_a_test_cmd_that_is_not_vitest_is_todays_full_suite(self, rig, caplog):
        (rig.repo / "package.json").write_text(json.dumps({"scripts": {"test": "jest"}}))
        _git(rig.repo, "commit", "-qam", "jest")
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert u.runs() == [TEST_CMD] and _counter(rig) == {}
        assert any("related selection not available" in m for m in _msgs(caplog))

    def test_a_direct_call_without_a_diff_is_the_whole_suite_as_before(self, rig):
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo)
        orchestrator.run_unit_gate(rig.repo, "route")
        assert u.runs() == [TEST_CMD] and _counter(rig) == {}


# ═══════════════════════════════════════════════════════
# P2-3 · every N-th route runs full and resets the counter, which is a file
# ═══════════════════════════════════════════════════════
class TestP2_3Counter:

    def test_the_fifth_route_runs_full_and_resets(self, rig, caplog):
        u = Unit(rig.monkeypatch, rig.repo)
        seen = []
        for i in range(1, 7):
            _branch(rig.repo, {f"src/feature/a.ts": f"a{i}\n"}, name=f"route{i}")
            u.calls.clear()
            with caplog.at_level(logging.INFO, logger="orch"):
                _gate(rig, f"route{i}")
            seen.append(("full" if u.runs() == [TEST_CMD] else "related", _counter(rig).get("since_full")))
        assert seen == [("related", 1), ("related", 2), ("related", 3), ("related", 4), ("full", 0),
                        ("related", 1)], seen
        assert any(m.startswith("🎯 Unit gate: full suite: (b)") and "unit_full_every 5" in m for m in _msgs(caplog))

    def test_the_counter_survives_a_restart(self, rig):
        (rig.orch / "state" / f"unit-full-counter-{REPO}.json").write_text(json.dumps({"since_full": 4}))
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo)
        _gate(rig)
        assert u.runs() == [TEST_CMD] and _counter(rig)["since_full"] == 0

    def test_unit_full_every_1_is_the_full_suite_every_route(self, rig):
        rig.cfg["unit_full_every"] = 1
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo)
        _gate(rig)
        assert u.runs() == [TEST_CMD]

    def test_an_unreadable_counter_runs_full(self, rig, caplog):
        (rig.orch / "state" / f"unit-full-counter-{REPO}.json").write_text("{not json")
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo)
        _gate(rig)
        assert u.runs() == [TEST_CMD]

    def test_any_full_route_resets_the_counter(self, rig):
        rig.cfg["unit_full_triggers"] = ["package.json"]
        (rig.orch / "state" / f"unit-full-counter-{REPO}.json").write_text(json.dumps({"since_full": 2}))
        _branch(rig.repo, {**THREE, "package.json": PKG2})
        Unit(rig.monkeypatch, rig.repo)
        _gate(rig)
        assert _counter(rig)["since_full"] == 0

    def test_the_nightly_full_gate_resets_the_counter(self, tmp_path, monkeypatch):
        from tests.test_gate_cost import FullGate
        g = FullGate(tmp_path, monkeypatch)
        f = g.orch / "state" / f"unit-full-counter-{REPO}.json"
        f.write_text(json.dumps({"since_full": 3}))
        g.run()
        assert json.loads(f.read_text())["since_full"] == 0


# ═══════════════════════════════════════════════════════
# the regression rule, on the related set
# ═══════════════════════════════════════════════════════
class TestRule:

    def _seed_base(self, r, failing):
        sha = _git(r.repo, "rev-parse", "main")
        orchestrator._unit_cache_store(r.archive, REPO, sha, TEST_CMD, orchestrator.UnitSuiteRun(
            ref=f"merge-base {sha[:7]}", exit_code=1 if failing else 0, duration_s=300.0,
            **orchestrator._parse_unit_summary(vitest(list(failing), failed=len(failing), total_tests=30,
                                                      total_files=len(SUITE)))), repo_path=r.repo)

    def test_a_related_file_failing_in_the_cached_full_baseline_is_not_new(self, rig):
        self._seed_base(rig, [T1, T3])
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo, related=(T1, T2), red=(T1,))
        v = _gate(rig)
        assert v.outcome is PASS, v.label
        assert u.runs() == [f"{TEST_CMD} -- {T1} {T2}"], "no baseline run, no confirm: the cache answered"
        assert v.unit.baseline_source == "cache" and v.unit.baseline.failing_files == (T1,)
        assert "restricted to the 2 related files" in v.unit_collection

    def test_a_related_file_failing_alone_and_not_in_the_baseline_is_a_regression(self, rig):
        self._seed_base(rig, [])
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo, related=(T1, T2), red=(T2,), red_alone=(T2,))
        v = _gate(rig)
        assert (v.outcome, v.signal) == (PRODUCT, "regression"), v.label
        assert u.runs()[-1] == f"{TEST_CMD} -- {T2}", "confirmed alone, as on the full suite"

    def test_one_that_passes_alone_is_a_flake(self, rig):
        self._seed_base(rig, [])
        _branch(rig.repo, THREE)
        Unit(rig.monkeypatch, rig.repo, related=(T1, T2), red=(T2,))
        v = _gate(rig)
        assert v.outcome is PASS and v.unit.flaky_files == (T2,)

    def test_no_cache_measures_the_merge_base_on_the_same_related_files(self, rig):
        _branch(rig.repo, THREE)
        u = Unit(rig.monkeypatch, rig.repo, related=(T1, T2), red=(T1,))
        v = _gate(rig)
        base_runs = [(c, cwd) for c, cwd in u.calls if c.startswith(TEST_CMD) and cwd != str(rig.repo)]
        assert base_runs and base_runs[0][0] == f"{TEST_CMD} -- {T1} {T2}", u.calls
        assert v.unit.baseline_source == "measured" and v.outcome is PASS

    def test_a_related_file_new_on_the_branch_has_an_empty_baseline(self, rig):
        new = "src/feature/new.test.ts"
        SUITE.append(new)
        try:
            _branch(rig.repo, {**THREE, new: "new test\n"})
            u = Unit(rig.monkeypatch, rig.repo, related=(), red=(new,), red_alone=(new,))
            v = _gate(rig)
            assert (v.outcome, v.signal) == (PRODUCT, "regression"), v.label
            assert not [c for c, cwd in u.calls if c.startswith(TEST_CMD) and cwd != str(rig.repo)], \
                "nothing to measure at the merge base: the file does not exist there"
        finally:
            SUITE.remove(new)


# ═══════════════════════════════════════════════════════
# P2-4 · a related-only PASS is never stored as a landed full baseline
# ═══════════════════════════════════════════════════════
class TestP2_4Landing:

    def test_a_related_only_pass_is_cached_as_related_only(self, rig, caplog):
        tip = _branch(rig.repo, THREE)
        Unit(rig.monkeypatch, rig.repo, related=(T1,))
        v = _gate(rig)
        assert v.outcome is PASS
        _git(rig.repo, "checkout", "-q", "main")
        _git(rig.repo, "merge", "-q", "--ff-only", "route")
        with caplog.at_level(logging.INFO, logger="orch"):
            orchestrator._unit_cache_store_landed(rig.repo, v, tip, rig.archive, route_tip=tip)
        assert orchestrator._unit_cache_lookup(rig.archive, REPO, tip, TEST_CMD, repo_path=rig.repo) is None
        entries = json.loads((rig.archive / orchestrator.UNIT_BASELINE_CACHE_FILE).read_text())["entries"]
        (e,) = entries.values()
        assert e["scope"] == "related" and e["test_cmd"] == f"{TEST_CMD} -- {T1}" and e["related_files"] == [T1]
        assert any("NOT cached as a full baseline" in m and "related-only" in m for m in _msgs(caplog))
        assert orchestrator._full_gate_reusable(rig.archive, tip, orchestrator._unit_content_key(rig.repo, tip),
                                                TEST_CMD)[0] is None

    def test_negative_control_a_full_pass_is_still_stored(self, rig):
        rig.monkeypatch.setenv("ORCH_UNIT_RELATED", "off")
        tip = _branch(rig.repo, THREE)
        Unit(rig.monkeypatch, rig.repo)
        v = _gate(rig)
        _git(rig.repo, "checkout", "-q", "main")
        _git(rig.repo, "merge", "-q", "--ff-only", "route")
        orchestrator._unit_cache_store_landed(rig.repo, v, tip, rig.archive, route_tip=tip)
        assert orchestrator._unit_cache_lookup(rig.archive, REPO, tip, TEST_CMD, repo_path=rig.repo)["landed_as"] == tip


class TestConfig:

    def test_clinical_mp_declares_the_triggers_and_the_every(self):
        trig = CLINICAL["unit_full_triggers"]
        for t in ("package.json", "package-lock.json", "vitest*.config.*", "vite.config.*", "tsconfig*.json",
                  "src/test/**", "**/setupTests.*", "src/lib/**", "server/**", "src/types/**"):
            assert t in trig
        assert CLINICAL["unit_full_every"] == 5 and CLINICAL["full_gate_reuse_max_h"] == 24

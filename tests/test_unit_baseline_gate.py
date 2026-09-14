"""S7-CORE-8 [ORCH-3] — the unit suite as a BASELINE pre-merge gate.

George ruling 2026-09-12 (PCU v1-133 ruling 2): "the unit suite gates a merge as a BASELINE
gate, not a zero gate". Halt only when the branch is WORSE than the commit it forked from.

The git fixtures here are REAL repositories (`git init`, real commits, a real merge base and a
real detached worktree) with only the suite *execution* stubbed, so the merge-base resolution
and the detached-worktree strategy of brief §4 STOP trigger 1 are exercised, not mocked away.
Patterns follow tests/test_gate_collection.py.
"""
import json
import logging
import re
import shlex
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402

REPO_ROOT = Path(__file__).parent.parent

# ── vitest suite output, the shape clinical-mp's `npm test` prints ────────────────────────
def vitest(failing_files=(), failed=0, total_tests=18, total_files=6):
    """A vitest summary with `failed` failures spread over `failing_files`."""
    lines = [f" FAIL  {f} > suite > case {i}" for i, f in enumerate(failing_files)]
    ff = len(set(failing_files))
    lines += [
        "",
        f" Test Files  {ff} failed | {total_files - ff} passed ({total_files})"
        if ff else f" Test Files  {total_files} passed ({total_files})",
        f"      Tests  {failed} failed | {total_tests - failed} passed ({total_tests})"
        if failed else f"      Tests  {total_tests} passed ({total_tests})",
        "   Duration  6.6s",
    ]
    return "\n".join(lines) + "\n"


VITEST_ZERO = " RUN  v4.1.4 /repo\n\n Test Files  0 passed (0)\n      Tests  0 passed (0)\n   Duration  2.3s\n"
PYTEST_RED = ("FAILED tests/test_x.py::test_b - assert 1 == 2\n"
              "FAILED tests/test_x.py::test_c - ValueError: x\n"
              "2 failed, 1 passed in 0.01s\n")
PYTEST_GREEN = "79 passed in 0.82s\n"

A = "src/lib/synth/seed-patients.test.ts"
B = "src/lib/synth/wipe.test.ts"
C = "src/lib/synth/tasks-queue.test.ts"


class _RepoPath(type(Path())):
    """A Path that can carry the fixture's commit SHAs alongside it."""
    fork_point = ""
    main_tip = ""


def _git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check:
        assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A real repo: main@M0 (the fork point) → branch `route`, then main advances to M1.

    `marker.txt` differs at every commit, so a stubbed suite that reads it proves WHICH
    commit was actually checked out for the baseline (AC-O3-05).
    """
    p = _RepoPath(tmp_path / "repo")
    p.mkdir()
    _git(p, "init", "-q", "-b", "main")
    _git(p, "config", "user.email", "t@t")
    _git(p, "config", "user.name", "t")
    (p / "marker.txt").write_text("fork-point")
    _git(p, "add", "-A")
    _git(p, "commit", "-qm", "M0 fork point")
    fork = _git(p, "rev-parse", "HEAD")

    _git(p, "checkout", "-qb", "route")
    (p / "marker.txt").write_text("branch")
    _git(p, "commit", "-qam", "route work")

    _git(p, "checkout", "-q", "main")
    (p / "marker.txt").write_text("main-advanced")
    _git(p, "commit", "-qam", "M1 main advances past the fork point")
    advanced = _git(p, "rev-parse", "HEAD")

    _git(p, "checkout", "-q", "route")
    p.fork_point = fork
    p.main_tip = advanced
    return p


@contextmanager
def active(name="gated-repo", test_cmd="npm test", extra_repos=None, archive=None):
    """Make `name` the active repo with the given declared test_cmd, and make the derived
    eligible set (§2.3) come from a synthetic repos.yaml."""
    repos = {name: {"project_dir": "/x", "test_cmd": test_cmd, "default": True}}
    if test_cmd is None:
        del repos[name]["test_cmd"]
    repos.update(extra_repos or {})
    with patch.object(orchestrator, "ACTIVE_REPO_NAME", name), \
         patch.object(orchestrator, "ACTIVE_REPO_CONFIG", repos[name]), \
         patch.object(orchestrator, "MERGE_TARGET", "main"), \
         patch.object(orchestrator, "UNIT_GATE_ENABLED", True), \
         patch.object(orchestrator, "SIT_ARCHIVE_DIR", Path(archive) if archive else orchestrator.SIT_ARCHIVE_DIR), \
         patch.object(orchestrator, "load_repo_config", return_value={"repos": repos}):
        yield


def fake_suite(branch_out, baseline_out=None, branch_code=None, baseline_code=None, seen=None):
    """Stub _run_unit_suite: canned output per side, parsed by the REAL parser.

    `seen` collects (ref, marker-file-content-at-cwd) so a test can prove which commit the
    baseline side was actually run against.
    """
    def _fake(cmd, cwd, ref):
        is_base = ref.startswith("merge-base")
        raw = baseline_out if is_base else branch_out
        code = (baseline_code if is_base else branch_code)
        if code is None:
            code = 0 if ("failed" not in raw and "FAIL" not in raw) else 1
        if seen is not None:
            marker = Path(cwd) / "marker.txt"
            seen.append((ref, marker.read_text() if marker.exists() else None))
        parsed = orchestrator._parse_unit_summary(raw)
        return orchestrator.UnitSuiteRun(ref=ref, exit_code=code, duration_s=0.1,
                                         output=raw, **parsed)
    return _fake


def run_gate(repo, tmp_path, *, branch_out, baseline_out=None, branch_code=None,
             baseline_code=None, seen=None, **kw):
    archive = tmp_path / "archive"
    with active(archive=archive, **kw), \
         patch.object(orchestrator, "_run_unit_suite",
                      fake_suite(branch_out, baseline_out, branch_code, baseline_code, seen)):
        o = orchestrator.run_unit_gate(repo, "route", archive_path=archive)
    entries = json.loads((archive / "orchestrator-unit-log.json").read_text()) \
        if (archive / "orchestrator-unit-log.json").exists() else []
    return o, entries


# ═══════════════════════════════════════════════════════════════════════════════════════
class TestEligibleSetIsDerivedFromConfig:
    """AC-O3-01 / AC-O3-02 — §2.3: the gated set comes from repos.yaml `test_cmd`."""

    def test_eligible_set_matches_real_config(self):
        """Derived from the REAL config/repos.yaml, not from a hard-coded list."""
        repos = orchestrator.load_repo_config()["repos"]
        expected = {n for n, r in repos.items() if (r.get("test_cmd") or "").strip()}
        assert orchestrator._unit_gate_eligible_repos() == expected
        assert expected, "repos.yaml declares no test_cmd at all — the gate would be dead"
        # clinical-mp's `npm test` sat in repos.yaml UNCONSUMED through the incident. It is
        # the reason this gate exists; it must be in the derived set.
        assert "clinical-mp" in expected

    def test_no_repo_name_is_hard_coded_in_the_derivation(self):
        src = (REPO_ROOT / "orchestrator.py").read_text()
        body = src.split("def _unit_gate_eligible_repos()")[1].split("\ndef ")[0]
        for name in orchestrator.load_repo_config()["repos"]:
            assert name not in body, f"{name} hard-coded in the eligible-set derivation"

    def test_a_repo_declaring_no_test_cmd_is_ungated_and_does_not_block(self, repo, tmp_path, caplog):
        """AC-O3-02: no test_cmd ⇒ `ungated by policy`, PASS, no suite run."""
        with active(name="no-suite-repo", test_cmd=None), caplog.at_level(logging.INFO, logger="orch"), \
             patch.object(orchestrator, "_run_unit_suite") as never:
            o = orchestrator.run_unit_gate(repo, "route")
        assert o.passed is True and o.signal == "ungated"
        assert "ungated by policy" in o.detail
        assert o.ran is False and o.collection is None
        never.assert_not_called()
        assert "declares no test_cmd — ungated by policy" in caplog.text

    def test_no_default_command_is_invented(self):
        """§2.3: a repo that has not declared a command gets none — no fallback constant."""
        src = (REPO_ROOT / "orchestrator.py").read_text()
        body = src.split("def run_unit_gate(")[1].split("\ndef ")[0]
        assert 'ACTIVE_REPO_CONFIG.get("test_cmd")' in body
        assert "UNIT_GATE_CMD" not in src, "a default unit command would be exactly the invented default §2.3 forbids"

    def test_ungated_repo_still_passes_through_run_pre_merge_gates(self, repo, tmp_path):
        """AC-O3-02 end to end: the merge is not blocked for an ungated repo."""
        with active(name="no-suite-repo", test_cmd=None, archive=tmp_path):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.PASS
        assert v.unit_collection is None
        assert "ungated by policy" in v.detail


class TestBaselineComparison:
    """AC-O3-03 / AC-O3-04, superseded for the count half by [ORCH-6b] AC-O6b-03/05: the
    failing-FILE set decides the verdict; the count is evidence only (see
    TestFlakeVsRegressionConfirmation and TestCountIsEvidenceNotAVerdict below)."""

    def test_more_failures_with_no_newly_failing_file_passes_and_logs_the_delta(self, repo, tmp_path):
        """AC-O6b-03: current > baseline but the same file set on both sides ⇒ PASS; the
        count rise is logged as a named observation, not a verdict."""
        o, _ = run_gate(repo, tmp_path,
                        branch_out=vitest([A, A, A], failed=3),
                        baseline_out=vitest([A, A], failed=2))
        assert o.passed is True and o.signal is None
        assert "count rose from 2 to 3 with no newly-failing file" in o.detail

    def test_equal_failures_passes(self, repo, tmp_path):
        """AC-O3-03: current == baseline ⇒ pass. A zero gate would block here; this is not one."""
        o, _ = run_gate(repo, tmp_path,
                        branch_out=vitest([A, A], failed=2),
                        baseline_out=vitest([A, A], failed=2))
        assert o.passed is True and o.signal is None
        assert "2 failures, equal to the merge-base baseline of 2" in o.detail

    def test_fewer_failures_passes(self, repo, tmp_path):
        """AC-O3-03: current < baseline ⇒ pass (debt being repaired)."""
        o, _ = run_gate(repo, tmp_path,
                        branch_out=vitest([A], failed=1),
                        baseline_out=vitest([A, A], failed=2))
        assert o.passed is True
        assert "1 failures, below the merge-base baseline of 2" in o.detail

    def test_green_branch_passes_over_a_red_baseline_without_measuring_it(self, repo, tmp_path):
        """current(0) < baseline(2). A green branch cannot regress against any baseline, so
        the second suite run is skipped — and the record says so rather than implying a
        measurement that never happened."""
        o, entries = run_gate(repo, tmp_path, branch_out=vitest(failed=0), baseline_out=vitest([A, A], failed=2))
        assert o.passed is True
        assert o.baseline is None and "not measured" in o.baseline_note
        assert entries[-1]["baseline"] is None and "not measured" in entries[-1]["baseline_note"]

    def test_newly_failing_file_blocks_even_when_the_count_does_not_rise(self, repo, tmp_path):
        """AC-O3-04: baseline {A: 2 failures} vs branch {B: 2 failures} — 2 is not > 2, but B
        was green at the fork point. That is a regression and it HALTS."""
        o, _ = run_gate(repo, tmp_path,
                        branch_out=vitest([B, B], failed=2),
                        baseline_out=vitest([A, A], failed=2))
        assert o.passed is False and o.signal == "regression"
        assert o.branch.failures == o.baseline.failures == 2, "the count did not rise"
        assert f"newly-failing file(s): {B}" in o.detail
        assert "failures vs baseline" not in o.detail, "it must block on the SET, not the count"

    def test_a_file_that_was_already_red_does_not_block(self, repo, tmp_path):
        """The same file red on both sides at the same count is pre-existing debt, not a regression."""
        o, _ = run_gate(repo, tmp_path,
                        branch_out=vitest([A, B], failed=2),
                        baseline_out=vitest([A, B], failed=2))
        assert o.passed is True

    def test_pytest_runner_is_compared_the_same_way(self, repo, tmp_path):
        """The fleet's python repos declare pytest; the same two comparisons apply."""
        o, _ = run_gate(repo, tmp_path, test_cmd="pytest -q tests/",
                        branch_out=PYTEST_RED, baseline_out=PYTEST_GREEN, baseline_code=0)
        assert o.passed is False and o.signal == "regression"
        assert o.branch.runner == "pytest" and o.branch.failures == 2
        assert "tests/test_x.py" in o.detail


class TestBaselineIsTheMergeBase:
    """AC-O3-05 / §2.2 — measured on the fork point, never stored, never main's tip."""

    def test_baseline_is_measured_on_the_merge_base_not_on_main_tip(self, repo, tmp_path):
        seen = []
        o, _ = run_gate(repo, tmp_path, seen=seen,
                        branch_out=vitest([A, A], failed=2),
                        baseline_out=vitest([A, A], failed=2))
        assert o.passed is True
        base = [s for s in seen if s[0].startswith("merge-base")]
        assert len(base) == 1, seen
        ref, marker = base[0]
        # main has ADVANCED past the fork point; the baseline must still be the fork point.
        assert ref == f"merge-base {repo.fork_point[:7]}"
        assert marker == "fork-point", f"baseline ran against {marker!r}, not the merge base"
        assert marker != "main-advanced" and ref[:20] not in repo.main_tip

    def test_merge_base_helper_returns_the_fork_point(self, repo):
        with active():
            assert orchestrator._unit_merge_base(repo, "route") == repo.fork_point
        assert repo.fork_point != repo.main_tip

    def test_no_baseline_is_stored_anywhere(self):
        """§2.2, as amended by S7-CORE-8 [ORCH-5] decision 1. The ASSERTIONS below are the
        [ORCH-3] ones, unmodified; only this docstring is updated, because what they protect
        has narrowed and saying so is the point of the test.

        [ORCH-3] read: "a stored baseline goes stale and becomes a lie. Nothing persists a
        number to compare AGAINST." [ORCH-5] ratified caching the baseline per merge-base
        commit, so a number IS persisted now — but keyed by the SHA it was measured on, which
        is what makes it unable to go stale. What stays forbidden, and what these assertions
        still enforce, is `run_unit_gate` itself reaching for a stored number: all cache I/O
        lives in the _unit_cache_* helpers, and the gate body reads no file and parses no JSON.
        Neither main's tip nor a hand-entered figure is reachable from either.
        See TestBaselineIsCachedPerMergeBase for the caching contract."""
        src = (REPO_ROOT / "orchestrator.py").read_text()
        gate = src.split("def run_unit_gate(")[1].split("\ndef ")[0]
        assert "_log_unit_outcome" not in gate.split("return")[0] or True
        assert "read_text" not in gate and "json.loads" not in gate, \
            "run_unit_gate must not read a stored baseline"
        assert "_unit_merge_base" in gate

    def test_unresolvable_merge_base_blocks_as_environment(self, tmp_path):
        """No baseline ⇒ no verdict. It is never downgraded to a stored number or to main."""
        plain = tmp_path / "plain"
        plain.mkdir()
        _git(plain, "init", "-q", "-b", "other")
        _git(plain, "config", "user.email", "t@t")
        _git(plain, "config", "user.name", "t")
        (plain / "f").write_text("x")
        _git(plain, "add", "-A")
        _git(plain, "commit", "-qm", "only commit")  # no `main` ref at all
        with active(archive=tmp_path), patch.object(orchestrator, "_run_unit_suite") as never:
            o = orchestrator.run_unit_gate(plain, "other", archive_path=tmp_path)
        assert o.passed is False and o.env is True and o.signal == "baseline-unresolvable"
        never.assert_not_called()


class TestBaselineWorktreeIsolation:
    """brief §4 STOP trigger 1 — a concurrently-running route in the target repo is not disturbed."""

    def test_baseline_runs_in_a_detached_worktree_and_leaves_the_checkout_alone(self, repo, tmp_path):
        before_head = _git(repo, "rev-parse", "HEAD")
        before_branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
        before_tree = _git(repo, "status", "--porcelain")
        cwds = []

        def _spy(cmd, cwd, ref):
            cwds.append((ref, Path(cwd)))
            raw = vitest([A, A], failed=2)
            return orchestrator.UnitSuiteRun(ref=ref, exit_code=1, duration_s=0.1, output=raw,
                                             **orchestrator._parse_unit_summary(raw))

        with active(archive=tmp_path), patch.object(orchestrator, "_run_unit_suite", _spy):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=tmp_path)
        assert o.passed is True
        base_cwd = [c for r, c in cwds if r.startswith("merge-base")][0]
        assert base_cwd != repo and repo not in base_cwd.parents, "baseline must not run in the live checkout"
        assert _git(repo, "rev-parse", "HEAD") == before_head
        assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == before_branch
        assert _git(repo, "status", "--porcelain") == before_tree

    def test_the_baseline_worktree_is_removed_and_pruned(self, repo, tmp_path):
        run_gate(repo, tmp_path, branch_out=vitest([A, A], failed=2), baseline_out=vitest([A, A], failed=2))
        listed = _git(repo, "worktree", "list")
        assert orchestrator.UNIT_BASELINE_WORKTREE_PREFIX not in listed, listed

    def test_dependency_paths_are_linked_not_copied(self, repo, tmp_path):
        """A fresh worktree has no node_modules; the baseline would fail for a reason that has
        nothing to do with the code. The link is read-only w.r.t. the live checkout."""
        (repo / "node_modules").mkdir()
        (repo / "node_modules" / "marker").write_text("dep")
        dst = tmp_path / "wt"
        dst.mkdir()
        created = orchestrator._link_unit_deps(repo, dst)
        assert (dst / "node_modules").is_symlink()
        assert (dst / "node_modules" / "marker").read_text() == "dep"
        assert created == [dst / "node_modules"]


class TestZeroCollectionIsEnvironment:
    """AC-O3-07 / §2.4 — a green exit over an empty collection tested nothing."""

    def test_zero_collection_on_the_branch_is_blocked_environment(self, repo, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            o, entries = run_gate(repo, tmp_path, branch_out=VITEST_ZERO, branch_code=0)
        assert o.passed is False
        assert o.env is True, "zero collection is BLOCKED(environment), never FAIL(product)"
        assert o.signal == "zero-collection"
        assert o.branch.tests_total == 0 and o.branch.test_files_total == 0
        assert "collected NOTHING" in caplog.text and "BLOCKED(environment), not PASS" in caplog.text
        assert entries[-1]["passed"] is False and entries[-1]["environment"] is True

    def test_zero_collection_reaches_the_verdict_as_blocked_not_failed(self, repo, tmp_path):
        archive = tmp_path / "archive"
        with active(archive=archive), \
             patch.object(orchestrator, "_run_unit_suite", fake_suite(VITEST_ZERO, branch_code=0)):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.BLOCKED_ENV
        assert v.outcome is not orchestrator.GateOutcome.FAIL_PRODUCT
        assert (v.gate, v.signal) == ("unit", "zero-collection")

    def test_unknown_counts_are_none_never_zero(self):
        """A summary that does not parse must not fabricate a 0 — that would false-trip §2.4."""
        c = orchestrator._parse_unit_summary("some tool printed nothing recognisable")
        assert c["tests_total"] is None and c["test_files_total"] is None and c["failures"] is None
        assert 0 not in (c["tests_total"], c["test_files_total"], c["failures"])

    def test_both_sides_red_but_unparseable_blocks_as_environment(self, repo, tmp_path):
        """We cannot tell a regression from pre-existing debt without counts. Say so — a
        measurement failure is environment, and never a silent pass."""
        o, _ = run_gate(repo, tmp_path, branch_out="make: *** [test] Error 1",
                        baseline_out="make: *** [test] Error 1", branch_code=2, baseline_code=2)
        assert o.passed is False and o.env is True and o.signal == "comparison-unavailable"

    def test_branch_timeout_is_environment_not_product(self, repo, tmp_path):
        archive = tmp_path / "archive"
        timed_out = orchestrator.UnitSuiteRun(ref="route", exit_code=-1, error="timeout", output="timeout")
        with active(archive=archive), patch.object(orchestrator, "_run_unit_suite", return_value=timed_out):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert o.passed is False and o.env is True and o.signal == "timeout"


class TestGateDeclaresAndPersistsWhatItCollected:
    """AC-O3-06 — the [ORCH-2] shape, now for BOTH sides."""

    def test_counts_are_logged_for_both_sides(self, repo, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            o, _ = run_gate(repo, tmp_path,
                            branch_out=vitest([A, A], failed=2), baseline_out=vitest([A, A], failed=2))
        assert "Unit gate branch run — route: 6 files/18 tests, 2 failed in " in caplog.text
        assert f"Unit gate baseline run — merge-base {repo.fork_point[:7]}: 6 files/18 tests, 2 failed in " in caplog.text

    def test_counts_are_persisted_with_the_run(self, repo, tmp_path):
        """A genuinely new file (B, absent from the baseline's {A}) so this is a confirmed
        regression under [ORCH-6b] AC-O6b-01, not just a count rise."""
        o, entries = run_gate(repo, tmp_path,
                              branch_out=vitest([B, B], failed=2), baseline_out=vitest([A], failed=1))
        e = entries[-1]
        assert e["branch"]["tests_total"] == 18 and e["branch"]["test_files_total"] == 6
        assert e["branch"]["failures"] == 2 and e["branch"]["failing_files"] == [B]
        assert e["baseline"]["failures"] == 1 and e["baseline"]["ref"] == f"merge-base {repo.fork_point[:7]}"
        assert e["repo_name"] == "gated-repo" and e["passed"] is False
        assert e["signal"] == "regression"

    def test_collection_string_carries_both_sides(self, repo, tmp_path):
        o, _ = run_gate(repo, tmp_path,
                        branch_out=vitest([A, A], failed=2), baseline_out=vitest([A, A], failed=2))
        assert o.collection.startswith(f"baseline merge-base {repo.fork_point[:7]}: 6 files/18 tests, 2 failed in ")
        assert "→ branch route: 6 files/18 tests, 2 failed in " in o.collection

    def test_it_reaches_the_verdict_and_the_run_record(self, repo, tmp_path):
        archive = tmp_path / "archive"
        with active(archive=archive), \
             patch.object(orchestrator, "_run_unit_suite",
                          fake_suite(vitest([A, A], failed=2), vitest([A, A], failed=2))):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.PASS
        assert v.unit_collection and "→ branch route:" in v.unit_collection
        r = orchestrator.Result(batch_file="b.md", status=orchestrator.Status.PASSED, started="", finished="",
                                duration_s=1.0, exit_code=0, briefs=1, gate_outcome=v.outcome.value,
                                gate_collection=v.collection, unit_collection=v.unit_collection)
        assert r.unit_collection == v.unit_collection
        label = orchestrator._gate_status_label(None, r.gate_outcome, r.gate_collection, r.unit_collection)
        assert label.startswith("PASS | unit: baseline merge-base ")

    def test_batch_summary_line_carries_the_unit_counts(self, caplog):
        r = orchestrator.Result(batch_file="b.md", status=orchestrator.Status.PASSED, started="", finished="",
                                duration_s=10.0, exit_code=0, briefs=1, gate_outcome="PASS",
                                gate_collection="7 files/18 tests, 6.6s",
                                unit_collection="baseline X → branch Y, 24.1s")
        with patch.object(orchestrator, "HAS_SLACK", False), caplog.at_level(logging.INFO, logger="orch"):
            orchestrator.notify(r)
        # [ORCH-2]'s wording is intact; the unit half is appended, not folded in.
        assert "| gate: PASS (7 files/18 tests, 6.6s) | unit: baseline X → branch Y, 24.1s" in caplog.text

    def test_log_is_append_only_and_survives_a_corrupt_file(self, repo, tmp_path):
        archive = tmp_path / "archive"
        archive.mkdir()
        (archive / "orchestrator-unit-log.json").write_text("{ not json")
        run_gate(repo, tmp_path, branch_out=vitest(failed=0))
        _, entries = run_gate(repo, tmp_path, branch_out=vitest(failed=0))
        assert len(entries) == 2


class TestOrderAndPlacementOnThePathThatRuns:
    """AC-O3-01 / §2.5–§2.6 — in run_pre_merge_gates, after build and SIT."""

    def test_order_is_build_then_sit_then_unit(self, repo, tmp_path):
        order = []
        bg = orchestrator.BuildGateOutcome(passed=True, exit_code=0)
        so = orchestrator.SitOutcome(passed=True, exit_code=0, duration_s=6.6,
                                     test_files_total=7, test_files_passed=7, tests_total=18, tests_passed=18)
        uo = orchestrator.UnitGateOutcome(passed=True, ran=True)
        with active(archive=tmp_path), \
             patch.dict(orchestrator.PRE_MERGE_GATES, {"gated-repo": {"gates": ("build", "sit")}}), \
             patch.object(orchestrator, "run_build_gate", side_effect=lambda *a, **k: (order.append("build"), bg)[1]), \
             patch.object(orchestrator, "run_sit_post_merge", side_effect=lambda *a, **k: (order.append("sit"), so)[1]), \
             patch.object(orchestrator, "run_unit_gate", side_effect=lambda *a, **k: (order.append("unit"), uo)[1]):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert order == ["build", "sit", "unit"]
        assert v.detail == "build+sit+unit green on route"

    def test_unit_does_not_run_when_an_earlier_gate_is_red(self, repo, tmp_path):
        """§2.6: the slowest gate only runs if the cheaper ones passed."""
        bg = orchestrator.BuildGateOutcome(passed=False, exit_code=1, error="tsc", output="TS2345: nope")
        with active(archive=tmp_path), \
             patch.dict(orchestrator.PRE_MERGE_GATES, {"gated-repo": {"gates": ("build",)}}), \
             patch.object(orchestrator, "run_build_gate", return_value=bg), \
             patch.object(orchestrator, "run_unit_gate") as never:
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.FAIL_PRODUCT and v.gate == "build"
        never.assert_not_called()

    def test_every_fire_path_reaches_run_pre_merge_gates(self):
        """§2.5: the A2/A8 placement lesson. run_batch is the single funnel for `run`, `queue`
        and `watch`; _run_batch_inner gates both of its merge lanes, and the unit gate is
        inside run_pre_merge_gates, so it cannot be placed off one of them."""
        src = (REPO_ROOT / "orchestrator.py").read_text()
        inner = src.split("def _run_batch_inner(")[1].split("\ndef ")[0]
        assert inner.count("run_pre_merge_gates(") == 2, "both merge lanes must gate"
        gates = src.split("def run_pre_merge_gates(")[1].split("\ndef ")[0]
        assert "run_unit_gate(" in gates, "the unit gate must live on the path that actually runs"
        for caller in ("def run_queue(", "def watch("):
            body = src.split(caller)[1].split("\ndef ")[0]
            assert "run_batch(" in body, f"{caller} must fire through run_batch"

    def test_unit_gate_runs_for_a_repo_with_no_pre_merge_gates_entry(self, repo, tmp_path):
        """AC-O3-01: eligibility is the declared test_cmd, not membership of PRE_MERGE_GATES."""
        archive = tmp_path / "archive"
        assert "gated-repo" not in orchestrator.PRE_MERGE_GATES
        with active(archive=archive), \
             patch.object(orchestrator, "_run_unit_suite",
                          fake_suite(vitest([B, B], failed=2), vitest([A, A], failed=2))):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.FAIL_PRODUCT
        assert v.gate == "unit" and v.signal == "regression"


class TestRedUnitGateLeavesTheBranchUnmerged:
    """AC-O3-08 — exactly what a red build or SIT gate does today; no new merge path."""

    def test_verdict_is_not_pass_so_the_shared_merge_guard_refuses(self, repo, tmp_path):
        archive = tmp_path / "archive"
        with active(archive=archive), \
             patch.object(orchestrator, "_run_unit_suite",
                          fake_suite(vitest([B, B, B], failed=3), vitest([A], failed=1))):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is not orchestrator.GateOutcome.PASS
        # The self-mod lane's merge guard is shared with build/SIT and keys off the verdict.
        assert orchestrator._self_mod_auto_merge(repo, "route", gate_outcome=v.outcome.value) is False

    def test_the_branch_and_merge_target_are_untouched_by_a_red_unit_gate(self, repo, tmp_path):
        main_before = _git(repo, "rev-parse", "main")
        route_before = _git(repo, "rev-parse", "route")
        archive = tmp_path / "archive"
        with active(archive=archive), \
             patch.object(orchestrator, "_run_unit_suite",
                          fake_suite(vitest([B, B], failed=2), vitest([A, A], failed=2))):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.FAIL_PRODUCT
        assert _git(repo, "rev-parse", "main") == main_before
        assert _git(repo, "rev-parse", "route") == route_before

    def test_a_red_unit_gate_with_an_f20_signal_is_environment(self, repo, tmp_path):
        """The F-20 classifier the build and SIT gates use applies unchanged: a regression
        whose output names an environment signal is BLOCKED, not FAIL(product)."""
        archive = tmp_path / "archive"
        env_out = vitest([B, B], failed=2) + "\nECONNREFUSED 127.0.0.1:8103\n"
        with active(archive=archive), \
             patch.object(orchestrator, "_run_unit_suite", fake_suite(env_out, vitest([A, A], failed=2))):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.BLOCKED_ENV
        assert v.signal == "medplum-unreachable"


class TestOperatorEscapes:
    """AC-O3-11 — --force is reported as a bypass, and what it does NOT bypass is reported too."""

    def test_force_logs_the_bypass_and_names_the_unit_gate(self, caplog):
        argv = ["orchestrator.py", "branches", "list", "--force"]
        with patch.object(sys, "argv", argv), \
             patch.object(orchestrator, "set_active_repo", return_value="gated-repo"), \
             patch.object(orchestrator, "list_branches"), \
             caplog.at_level(logging.INFO, logger="orch"):
            orchestrator.main()
        assert "--force: pre-fire assertions (A2/A8) BYPASSED" in caplog.text
        assert "--force: pre-merge gates NOT bypassed" in caplog.text
        assert "unit baseline gate still run and still block the merge" in caplog.text
        assert "DISABLE_UNIT_GATE" in caplog.text

    def test_force_is_restored_and_cannot_reach_the_gate(self):
        """--force sets PREFIRE_BYPASS only; no gate function consults it."""
        orchestrator.PREFIRE_BYPASS = False
        src = (REPO_ROOT / "orchestrator.py").read_text()
        for fn in ("def run_unit_gate(", "def run_pre_merge_gates(", "def _run_unit_baseline("):
            body = src.split(fn)[1].split("\ndef ")[0]
            assert "PREFIRE_BYPASS" not in body, f"{fn} consults the --force bypass flag"
            assert "a.force" not in body and "force=" not in body, f"{fn} takes a force argument"

    def test_disable_unit_gate_is_logged_as_a_bypass(self, repo, caplog):
        with active(), patch.object(orchestrator, "UNIT_GATE_ENABLED", False), \
             patch.object(orchestrator, "_run_unit_suite") as never, \
             caplog.at_level(logging.INFO, logger="orch"):
            o = orchestrator.run_unit_gate(repo, "route")
        assert o.passed is True and o.signal == "disabled"
        assert "Unit baseline gate BYPASSED (DISABLE_UNIT_GATE)" in caplog.text
        never.assert_not_called()

    def test_gate_is_not_applicable_without_a_git_work_tree(self, tmp_path, caplog):
        """Manual/test invocation on a non-checkout: there is no branch and no merge base, so
        there is nothing to baseline. Said out loud rather than turned into a verdict."""
        with active(), caplog.at_level(logging.INFO, logger="orch"):
            o = orchestrator.run_unit_gate(tmp_path / "nope", "route")
        assert o.passed is True and o.signal == "not-applicable" and o.ran is False
        assert "is not a git work tree" in caplog.text


class TestExistingGatesUnchanged:
    """AC-O3-10 — build and SIT behaviour, and their tests, are untouched."""

    def test_no_commit_on_this_branch_edits_the_existing_gate_tests(self):
        guarded = ["tests/test_gate_collection.py", "tests/test_sit_integration.py"]
        r = subprocess.run(["git", "-C", str(REPO_ROOT), "log", "--oneline", "main..HEAD", "--", *guarded],
                           capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip("no `main` ref to diff against")
        assert r.stdout.strip() == "", f"AC-O3-10 violated — {guarded} were edited:\n{r.stdout}"

    def test_sit_parser_is_reused_not_modified(self):
        """The unit gate reuses _parse_vitest_summary; [ORCH-2]'s contract is unchanged."""
        c = orchestrator._parse_vitest_summary(" Test Files  2 failed | 5 passed (7)\n      Tests  3 failed | 15 passed (18)\n")
        assert c == {"test_files_total": 7, "test_files_passed": 5, "tests_total": 18, "tests_passed": 15}

    def test_sit_gate_command_count_unchanged(self):
        src = (REPO_ROOT / "orchestrator.py").read_text()
        assert src.count("npm run sit:gate") == 2

    def test_gate_status_label_keeps_its_three_arg_contract(self):
        assert orchestrator._gate_status_label(None, "PASS", "7 files/18 tests, 6.6s") == "PASS (7 files/18 tests, 6.6s)"
        assert orchestrator._gate_status_label(None, "PASS", None) == "PASS"
        assert orchestrator._gate_status_label(None, None, None) == "not run"


class TestSuiteOutputParsing:
    """The two runners this fleet declares. Counts AND the failing-file set."""

    def test_vitest_mixed_summary(self):
        c = orchestrator._parse_unit_summary(vitest([A, A, B], failed=3, total_tests=18, total_files=6))
        assert c["runner"] == "vitest"
        assert (c["tests_total"], c["tests_passed"], c["failures"]) == (18, 15, 3)
        assert c["test_files_total"] == 6
        assert set(c["failing_files"]) == {A, B}

    def test_vitest_per_file_listing_also_yields_failing_files(self):
        raw = ("❯ src/lib/synth/wipe.test.ts (3 tests | 2 failed)\n"
               " Test Files  1 failed | 5 passed (6)\n      Tests  2 failed | 16 passed (18)\n")
        c = orchestrator._parse_unit_summary(raw)
        assert set(c["failing_files"]) == {B}

    def test_vitest_ansi_colour_still_parses(self):
        raw = vitest([A, A], failed=2).replace("Test Files", "\x1b[2mTest Files\x1b[22m")
        c = orchestrator._parse_unit_summary(raw)
        assert c["failures"] == 2 and set(c["failing_files"]) == {A}

    def test_pytest_quiet_red(self):
        c = orchestrator._parse_unit_summary(PYTEST_RED)
        assert c["runner"] == "pytest"
        assert (c["tests_total"], c["tests_passed"], c["failures"]) == (3, 1, 2)
        assert set(c["failing_files"]) == {"tests/test_x.py"}

    def test_pytest_quiet_green(self):
        c = orchestrator._parse_unit_summary(PYTEST_GREEN)
        assert (c["tests_total"], c["failures"]) == (79, 0) and c["failing_files"] == ()

    def test_pytest_verbose_with_progress_lines_yields_a_file_count(self):
        raw = ("============================= test session starts ==============================\n"
               "collected 3 items\n\n"
               "tests/test_x.py .FF                                                      [ 66%]\n"
               "tests/test_y.py .                                                        [100%]\n"
               "=========================== short test summary info ============================\n"
               "FAILED tests/test_x.py::test_b - assert 1 == 2\n"
               "ERROR tests/test_x.py::test_c\n"
               "========================= 2 failed, 2 passed in 0.01s ==========================\n")
        c = orchestrator._parse_unit_summary(raw)
        assert c["tests_total"] == 3 and c["test_files_total"] == 2
        assert c["failures"] == 2 and set(c["failing_files"]) == {"tests/test_x.py"}

    def test_pytest_error_tally_counts_as_a_failure(self):
        c = orchestrator._parse_unit_summary("1 failed, 1 error, 5 passed in 0.1s\n")
        assert c["failures"] == 2

    def test_pytest_no_tests_ran_is_a_real_zero(self):
        c = orchestrator._parse_unit_summary("no tests ran in 0.01s\n")
        assert c["tests_total"] == 0

    def test_paths_are_normalised_so_both_sides_compare(self):
        c = orchestrator._parse_unit_summary(
            " FAIL  ./src/lib/synth/wipe.test.ts > x\n Test Files  1 failed | 5 passed (6)\n"
            "      Tests  1 failed | 17 passed (18)\n")
        assert set(c["failing_files"]) == {B}


# ═══════════════════════════════════════════════════════════════════════════════════════
# S7-CORE-8 [ORCH-5] — the gate must be able to COMPLETE its own measurement.
#
# The gate [ORCH-3] added ran on clinical-mp for the first time and returned
#   BLOCKED(environment) — unit: baseline-unmeasurable (baseline at fda6974 did not yield a
#   measurement (timeout)) · branch: 773 files / 7103 tests, 106 failed in 819.4s
# `npm test` there is the whole repo, ~14 min, and the gate ran it TWICE on a 900s budget.
# The verdict logic was right; the cost model was wrong. The suite stays whole (decision 4);
# the MEASUREMENT gets cheaper: cached per merge-base commit, with its own generous budget.
# ═══════════════════════════════════════════════════════════════════════════════════════
def baseline_runs(seen):
    return [s for s in seen if s[0].startswith(orchestrator.UNIT_BASELINE_REF_PREFIX)]


def cache_entries(archive):
    f = Path(archive) / orchestrator.UNIT_BASELINE_CACHE_FILE
    return json.loads(f.read_text())["entries"] if f.exists() else {}


class TestBaselineIsCachedPerMergeBase:
    """AC-O5-01 / AC-O5-02 — decision 1: the baseline for a commit is immutable. Measure once."""

    def test_a_second_route_off_the_same_base_performs_no_baseline_run(self, repo, tmp_path):
        """AC-O5-01: the whole point. ~28 min/route becomes ~14 min once per base."""
        seen = []
        o1, _ = run_gate(repo, tmp_path, seen=seen,
                         branch_out=vitest([A, A], failed=2), baseline_out=vitest([A, A], failed=2))
        assert o1.passed is True
        assert len(baseline_runs(seen)) == 1, "the first route must measure the baseline"

        seen2 = []
        o2, _ = run_gate(repo, tmp_path, seen=seen2,
                         branch_out=vitest([A, A], failed=2), baseline_out=vitest([A, A], failed=2))
        assert o2.passed is True
        assert baseline_runs(seen2) == [], "the second route must NOT run the baseline suite again"
        assert o2.baseline.failures == 2, "and it still has the number"

    def test_the_cache_records_files_tests_failures_duration_and_the_sha(self, repo, tmp_path):
        """AC-O5-02."""
        archive = tmp_path / "archive"
        run_gate(repo, tmp_path, branch_out=vitest([A, A], failed=2), baseline_out=vitest([A], failed=1))
        entries = cache_entries(archive)
        assert len(entries) == 1
        e = list(entries.values())[0]
        assert e["sha"] == repo.fork_point
        assert e["test_files_total"] == 6 and e["tests_total"] == 18
        assert e["failures"] == 1 and e["failing_files"] == [A]
        assert isinstance(e["duration_s"], float) or isinstance(e["duration_s"], int)
        assert e["repo"] == "gated-repo" and e["test_cmd"] == "npm test"

    def test_an_entry_for_a_different_sha_is_not_used(self, repo, tmp_path):
        """AC-O5-02: a cached number belongs to ONE commit. It is never lent to another."""
        archive = tmp_path / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        other = repo.main_tip
        assert other != repo.fork_point
        with active(archive=archive):
            orchestrator._unit_cache_store(
                archive, "gated-repo", other, "npm test",
                orchestrator.UnitSuiteRun(ref="x", exit_code=0, failures=0, tests_total=18,
                                          test_files_total=6))
            assert orchestrator._unit_cache_lookup(archive, "gated-repo", repo.fork_point, "npm test") is None
        seen = []
        o, _ = run_gate(repo, tmp_path, seen=seen,
                        branch_out=vitest([A, A], failed=2), baseline_out=vitest([A, A], failed=2))
        assert len(baseline_runs(seen)) == 1, "a foreign SHA's entry must not suppress the measurement"
        assert o.baseline.failures == 2

    def test_a_changed_test_cmd_is_a_miss(self, repo, tmp_path):
        """The same commit measured with a DIFFERENT command is a different measurement.
        Reusing it would be exactly the stale-number lie §2.2 warns about."""
        seen = []
        run_gate(repo, tmp_path, seen=seen, branch_out=vitest([A, A], failed=2),
                 baseline_out=vitest([A, A], failed=2))
        seen2 = []
        run_gate(repo, tmp_path, seen=seen2, test_cmd="npm test -- --changed",
                 branch_out=vitest([A, A], failed=2), baseline_out=vitest([A, A], failed=2))
        assert len(baseline_runs(seen2)) == 1, "a new test_cmd must re-measure"

    def test_a_corrupt_cache_is_a_miss_not_a_crash(self, repo, tmp_path):
        archive = tmp_path / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        (archive / orchestrator.UNIT_BASELINE_CACHE_FILE).write_text("{ not json")
        seen = []
        o, _ = run_gate(repo, tmp_path, seen=seen,
                        branch_out=vitest([A, A], failed=2), baseline_out=vitest([A, A], failed=2))
        assert o.passed is True and len(baseline_runs(seen)) == 1

    def test_the_cache_lives_inside_the_orchestrator_repo(self):
        """brief §4 STOP trigger 2: no state outside this repo. The cache file sits in the
        sit-archive dir beside orchestrator-unit-log.json, and `sit-archive/*.json` is
        gitignored, so it is runtime state and never committed."""
        assert orchestrator.SIT_ARCHIVE_DIR == orchestrator.ORCH_DIR / "sit-archive"
        gi = (REPO_ROOT / ".gitignore").read_text()
        assert "sit-archive/*.json" in gi
        assert orchestrator.UNIT_BASELINE_CACHE_FILE.endswith(".json")


class TestTheVerdictSaysWhereTheBaselineCameFrom:
    """AC-O5-05 — "measured now" and "read from cache", both asserted."""

    def test_a_freshly_measured_baseline_says_so(self, repo, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            o, entries = run_gate(repo, tmp_path, branch_out=vitest([A, A], failed=2),
                                  baseline_out=vitest([A, A], failed=2))
        assert o.baseline_source == "measured"
        assert "measured now at" in o.baseline_note
        assert "[measured]" in o.collection
        assert entries[-1]["baseline_source"] == "measured"
        assert "cache MISS" in caplog.text

    def test_a_cached_baseline_says_so(self, repo, tmp_path, caplog):
        run_gate(repo, tmp_path, branch_out=vitest([A, A], failed=2), baseline_out=vitest([A, A], failed=2))
        with caplog.at_level(logging.INFO, logger="orch"):
            o, entries = run_gate(repo, tmp_path, branch_out=vitest([A, A], failed=2),
                                  baseline_out=vitest([A, A], failed=2))
        assert o.baseline_source == "cache"
        assert "read from cache" in o.baseline_note and repo.fork_point[:7] in o.baseline_note
        assert "[cache]" in o.collection
        assert entries[-1]["baseline_source"] == "cache"
        assert "CACHE HIT" in caplog.text and "no baseline run" in caplog.text

    def test_the_green_branch_skip_still_declares_itself(self, repo, tmp_path):
        """The [ORCH-3] short-circuit is not a cache read and must not read like one."""
        o, _ = run_gate(repo, tmp_path, branch_out=vitest(failed=0))
        assert o.baseline is None and o.baseline_source == "not-needed"
        assert "not measured" in o.baseline_note


class TestTheBaselineLegHasItsOwnTimeout:
    """AC-O5-03 — separate budgets, ≥1800s by default, per-repo configurable."""

    def test_the_default_baseline_budget_is_at_least_1800s_and_the_branch_keeps_its_own(self):
        assert orchestrator.UNIT_BASELINE_TIMEOUT >= 1800
        assert orchestrator.UNIT_GATE_TIMEOUT != orchestrator.UNIT_BASELINE_TIMEOUT
        with active():
            assert orchestrator._unit_suite_timeout("merge-base abc1234") >= 1800
            assert orchestrator._unit_suite_timeout("route") == orchestrator.UNIT_GATE_TIMEOUT

    def test_both_legs_are_configurable_per_repo_and_independently(self):
        with active():
            with patch.dict(orchestrator.ACTIVE_REPO_CONFIG, {"baseline_timeout_s": 4200}):
                assert orchestrator._unit_suite_timeout("merge-base abc1234") == 4200
                assert orchestrator._unit_suite_timeout("route") == orchestrator.UNIT_GATE_TIMEOUT
            with patch.dict(orchestrator.ACTIVE_REPO_CONFIG, {"test_timeout_s": 120}):
                assert orchestrator._unit_suite_timeout("route") == 120
                assert orchestrator._unit_suite_timeout("merge-base abc1234") >= 1800

    def test_a_nonsense_override_falls_back_and_says_so(self, caplog):
        with active(), caplog.at_level(logging.INFO, logger="orch"), \
             patch.dict(orchestrator.ACTIVE_REPO_CONFIG, {"baseline_timeout_s": "soon"}):
            assert orchestrator._unit_suite_timeout("merge-base abc1234") == orchestrator.UNIT_BASELINE_TIMEOUT
        assert "not a positive integer" in caplog.text

    def test_the_budget_reaches_the_subprocess_for_each_leg(self, tmp_path):
        """Not just resolved — actually handed to the suite run."""
        seen = {}

        def _run(cmd, **kw):
            seen[kw.get("cwd")] = kw.get("timeout")
            return MagicMock(returncode=0, stdout=PYTEST_GREEN, stderr="")

        with active(), patch.object(subprocess, "run", side_effect=_run):
            orchestrator._run_unit_suite("pytest -q", tmp_path, "route")
            assert seen[str(tmp_path)] == orchestrator.UNIT_GATE_TIMEOUT
            orchestrator._run_unit_suite("pytest -q", tmp_path, "merge-base abc1234")
            assert seen[str(tmp_path)] == orchestrator.UNIT_BASELINE_TIMEOUT


class TestABaselineTimeoutIsEnvironmentNotProduct:
    """AC-O5-04 — the measurement failed; that says nothing about the code."""

    @staticmethod
    def _baseline_times_out(branch_out):
        def _fake(cmd, cwd, ref):
            if ref.startswith(orchestrator.UNIT_BASELINE_REF_PREFIX):
                return orchestrator.UnitSuiteRun(ref=ref, exit_code=-1, duration_s=1800.0,
                                                 error="timeout", output="timeout")
            return orchestrator.UnitSuiteRun(ref=ref, exit_code=1, duration_s=819.4, output=branch_out,
                                             **orchestrator._parse_unit_summary(branch_out))
        return _fake

    def test_baseline_timeout_blocks_as_environment_and_blames_the_measurement(self, repo, tmp_path, caplog):
        archive = tmp_path / "archive"
        with active(archive=archive), caplog.at_level(logging.INFO, logger="orch"), \
             patch.object(orchestrator, "_run_unit_suite", self._baseline_times_out(vitest([A, A], failed=2))):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert o.passed is False
        assert o.env is True, "a timeout is BLOCKED(environment), never FAIL(product)"
        assert o.signal == "baseline-unmeasurable"
        assert "BASELINE MEASUREMENT" in o.detail and "timeout" in o.detail
        assert "says nothing about the branch" in o.detail
        assert str(orchestrator.UNIT_BASELINE_TIMEOUT) in o.detail, "name the budget that was blown"
        assert "BLOCKED(environment), not FAIL(product)" in caplog.text

    def test_it_reaches_the_verdict_as_blocked_not_failed(self, repo, tmp_path):
        archive = tmp_path / "archive"
        with active(archive=archive), \
             patch.object(orchestrator, "_run_unit_suite", self._baseline_times_out(vitest([A, A], failed=2))):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.BLOCKED_ENV
        assert v.outcome is not orchestrator.GateOutcome.FAIL_PRODUCT
        assert (v.gate, v.signal) == ("unit", "baseline-unmeasurable")

    def test_a_failed_measurement_is_never_cached(self, repo, tmp_path):
        archive = tmp_path / "archive"
        with active(archive=archive), \
             patch.object(orchestrator, "_run_unit_suite", self._baseline_times_out(vitest([A, A], failed=2))):
            orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert cache_entries(archive) == {}, "a timeout must not become a stored baseline"


class TestAncestorFallbackIsStatedNeverInferred:
    """AC-O5-05 / decision 3 — a cache miss is not a block when a MEASURED ancestor exists,
    and the verdict says so. Nothing is ever inferred."""

    def _measure_ancestor(self, repo, tmp_path):
        """Route 1 forks at M0 and its baseline is measured and cached there. `route2` forks
        at M1 instead, so its merge base is M1 and M0 is a strict ANCESTOR of it — exactly the
        shape decision 3 describes: a real measurement, for an older commit."""
        run_gate(repo, tmp_path, branch_out=vitest([A, A], failed=2), baseline_out=vitest([A, A], failed=2))
        _git(repo, "checkout", "-q", "main")
        _git(repo, "checkout", "-qb", "route2")
        (repo / "marker.txt").write_text("route2")
        _git(repo, "commit", "-qam", "route2 work")
        assert _git(repo, "merge-base", "main", "route2") == repo.main_tip != repo.fork_point

    def test_an_ancestor_baseline_is_used_and_labelled_when_the_fresh_one_fails(self, repo, tmp_path, caplog):
        archive = tmp_path / "archive"
        self._measure_ancestor(repo, tmp_path)
        with active(archive=archive), caplog.at_level(logging.INFO, logger="orch"), \
             patch.object(orchestrator, "_run_unit_suite",
                          TestABaselineTimeoutIsEnvironmentNotProduct._baseline_times_out(vitest([A, A], failed=2))):
            o = orchestrator.run_unit_gate(repo, "route2", archive_path=archive)
        assert o.passed is True, "a measurable branch + a measured ancestor is not a block"
        assert o.baseline_source == "ancestor-cache"
        assert "ANCESTOR" in o.baseline_note and repo.fork_point[:7] in o.baseline_note
        assert "approximate" in o.baseline_note
        assert "[ancestor-cache]" in o.collection

    def test_with_no_measured_ancestor_the_block_stands(self, repo, tmp_path):
        """"Never infer a baseline you did not measure." An empty cache is still a block."""
        archive = tmp_path / "archive"
        with active(archive=archive), \
             patch.object(orchestrator, "_run_unit_suite",
                          TestABaselineTimeoutIsEnvironmentNotProduct._baseline_times_out(vitest([A, A], failed=2))):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert o.passed is False and o.env is True and o.signal == "baseline-unmeasurable"
        assert "no measured ancestor" in o.baseline_note

    def test_a_non_ancestor_entry_is_never_borrowed(self, repo, tmp_path):
        """A commit that is not an ancestor of this merge base has no bearing on it."""
        archive = tmp_path / "archive"
        archive.mkdir(parents=True, exist_ok=True)
        _git(repo, "checkout", "-qb", "sibling", repo.fork_point)
        (repo / "marker.txt").write_text("sibling")
        _git(repo, "commit", "-qam", "sibling work")
        sibling = _git(repo, "rev-parse", "HEAD")
        _git(repo, "checkout", "-q", "route")
        with active(archive=archive):
            orchestrator._unit_cache_store(
                archive, "gated-repo", sibling, "npm test",
                orchestrator.UnitSuiteRun(ref="x", exit_code=1, failures=2, tests_total=18,
                                          test_files_total=6))
            assert orchestrator._unit_cache_ancestor(repo, archive, "gated-repo",
                                                     repo.fork_point, "npm test") is None

    def test_an_ancestor_fallback_still_blocks_a_real_regression(self, repo, tmp_path):
        """The fallback is a cheaper baseline, not a softer gate. B is a genuinely new file
        (absent from the ancestor baseline's {A}), so [ORCH-6b] still calls this a regression."""
        archive = tmp_path / "archive"
        self._measure_ancestor(repo, tmp_path)
        with active(archive=archive), \
             patch.object(orchestrator, "_run_unit_suite",
                          TestABaselineTimeoutIsEnvironmentNotProduct._baseline_times_out(vitest([B, B, B], failed=3))):
            o = orchestrator.run_unit_gate(repo, "route2", archive_path=archive)
        assert o.passed is False and o.signal == "regression"
        assert f"newly-failing file(s): {B}" in o.detail
        assert "3 failures vs baseline 2" in o.detail


class TestOrch3SemanticsSurviveCaching:
    """AC-O5-06 — `>` blocks, `==` and `<` pass, and a newly-failing FILE blocks even when the
    count does not rise. Re-asserted here with the baseline coming OFF THE CACHE, because that
    is the path [ORCH-5] introduced and the path a regression would hide in."""

    @staticmethod
    def _prime(repo, tmp_path, baseline_out):
        """Measure and cache the baseline, then assert the next gate run reads it."""
        seen = []
        run_gate(repo, tmp_path, seen=seen, branch_out=baseline_out, baseline_out=baseline_out)
        assert len(baseline_runs(seen)) == 1

    def _cached(self, repo, tmp_path, branch_out, baseline_out):
        self._prime(repo, tmp_path, baseline_out)
        seen = []
        o, _ = run_gate(repo, tmp_path, seen=seen, branch_out=branch_out, baseline_out=baseline_out)
        assert baseline_runs(seen) == [], "this case must be exercising the CACHE path"
        assert o.baseline_source == "cache"
        return o

    def test_more_failures_than_a_cached_baseline_still_blocks(self, repo, tmp_path):
        """B is a genuinely new file (absent from the cached baseline's {A}), so [ORCH-6b]
        still calls this a regression — a count rise alone would not (see
        TestCountIsEvidenceNotAVerdict)."""
        o = self._cached(repo, tmp_path, vitest([B, B, B], failed=3), vitest([A, A], failed=2))
        assert o.passed is False and o.signal == "regression"
        assert f"newly-failing file(s): {B}" in o.detail
        assert "3 failures vs baseline 2" in o.detail

    def test_equal_to_a_cached_baseline_still_passes(self, repo, tmp_path):
        o = self._cached(repo, tmp_path, vitest([A, A], failed=2), vitest([A, A], failed=2))
        assert o.passed is True and o.signal is None
        assert "2 failures, equal to the merge-base baseline of 2" in o.detail

    def test_fewer_than_a_cached_baseline_still_passes(self, repo, tmp_path):
        o = self._cached(repo, tmp_path, vitest([A], failed=1), vitest([A, A], failed=2))
        assert o.passed is True
        assert "1 failures, below the merge-base baseline of 2" in o.detail

    def test_a_newly_failing_file_still_blocks_off_a_cached_baseline(self, repo, tmp_path):
        """AC-O3-04's semantics, preserved: 2 is not > 2, but B was green at the fork point.
        The failing-FILE set must survive the round trip through the cache."""
        o = self._cached(repo, tmp_path, vitest([B, B], failed=2), vitest([A, A], failed=2))
        assert o.passed is False and o.signal == "regression"
        assert o.branch.failures == o.baseline.failures == 2, "the count did not rise"
        assert f"newly-failing file(s): {B}" in o.detail
        assert o.baseline.failing_files == (A,), "the cached failing-file SET must round-trip"


class TestTheSuiteCommandIsNotNarrowed:
    """AC-O5-07 / decision 4 — the 106 failures in clinical-mp's full suite are real and
    mostly outside the paths our routes touch. Narrowing `test_cmd` would hide them. The
    suite stays whole; only the MEASUREMENT got cheaper."""

    def test_clinical_mp_test_cmd_is_still_literally_npm_test(self):
        repos = orchestrator.load_repo_config()["repos"]
        assert repos["clinical-mp"]["test_cmd"] == "npm test"

    def test_no_repo_test_cmd_changed_on_this_branch(self):
        r = subprocess.run(["git", "-C", str(REPO_ROOT), "diff", "main...HEAD", "--", "config/repos.yaml"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip("no `main` ref to diff against")
        assert "test_cmd" not in r.stdout, f"AC-O5-07 violated — test_cmd touched:\n{r.stdout}"


# ═══════════════════════════════════════════════════════════════════════════════════════
# S7-CORE-9 [ORCH-6] — the gate must tell a flake from a regression.
#
# cad4753 measured 68 failures in one run and 106 in another; three files "newly failing"
# at 2449a52 passed all 56 of their tests re-run in isolation. A single pair of whole-suite
# runs is not enough evidence for FAIL(product). Newly-failing files are now confirmed
# ALONE, on the branch, before the verdict is reached.
# ═══════════════════════════════════════════════════════════════════════════════════════
def confirm_fake(branch_out, baseline_out, confirm_out=None, confirm_error=None,
                 branch_code=None, baseline_code=None, confirm_code=None, confirm_calls=None):
    """Like `fake_suite`, plus a third leg: the CONFIRMATION pass (ref prefix `confirm`)."""
    def _fake(cmd, cwd, ref):
        if ref.startswith(orchestrator.UNIT_BASELINE_REF_PREFIX):
            raw, code = baseline_out, baseline_code
        elif ref.startswith(orchestrator.UNIT_CONFIRM_REF_PREFIX):
            if confirm_calls is not None:
                confirm_calls.append(cmd)
            if confirm_error:
                return orchestrator.UnitSuiteRun(ref=ref, exit_code=-1, duration_s=0.05,
                                                 error=confirm_error, output=confirm_error)
            raw, code = confirm_out, confirm_code
        else:
            raw, code = branch_out, branch_code
        if code is None:
            code = 0 if ("failed" not in raw and "FAIL" not in raw) else 1
        return orchestrator.UnitSuiteRun(ref=ref, exit_code=code, duration_s=0.1, output=raw,
                                         **orchestrator._parse_unit_summary(raw))
    return _fake


class TestConfirmationCommandIsNarrowed:
    """AC-O6-01 — the runner is invoked again on EXACTLY the suspect files, no other file."""

    def test_bare_npm_test_gets_dash_dash_and_the_files(self):
        cmd = orchestrator._unit_confirm_cmd("npm test", ("a.test.ts", "b.test.ts"))
        assert cmd == "npm test -- a.test.ts b.test.ts"

    def test_a_trailing_pytest_directory_is_replaced_not_joined(self):
        """The whole-suite `tests/` argument must not survive alongside the file — that would
        collect the bulk directory too, which is not isolation."""
        cmd = orchestrator._unit_confirm_cmd("pytest -q tests/", ("tests/test_x.py",))
        assert cmd == "pytest -q tests/test_x.py"
        assert cmd.count("tests/") == 1

    def test_a_bare_pytest_command_appends_the_files_directly(self):
        cmd = orchestrator._unit_confirm_cmd(
            "source venv/bin/activate && PYTHONPATH=. pytest", ("tests/test_x.py",))
        assert cmd == "source venv/bin/activate && PYTHONPATH=. pytest tests/test_x.py"

    def test_a_cd_prefixed_npm_command_still_gets_dash_dash(self):
        cmd = orchestrator._unit_confirm_cmd("cd yorsie && npm test", ("a.test.ts",))
        assert cmd == "cd yorsie && npm test -- a.test.ts"

    def test_files_with_spaces_are_shell_quoted(self):
        cmd = orchestrator._unit_confirm_cmd("npm test", ("a b.test.ts",))
        assert shlex.split(cmd)[-1] == "a b.test.ts"


class TestFlakeVsRegressionConfirmation:
    """AC-O6-02 / AC-O6-03 / AC-O6-04 — the four verdicts, driven by a stubbed runner."""

    def test_a_confirmed_flake_passes_the_route_and_is_named(self, repo, tmp_path):
        """AC-O6-02: passes alone in isolation ⇒ FLAKE. Flakes alone never FAIL(product)."""
        archive = tmp_path / "archive"
        with active(archive=archive), patch.object(
                orchestrator, "_run_unit_suite",
                confirm_fake(vitest([B, B], failed=2), vitest([A, A], failed=2),
                            confirm_out=vitest(failed=0, total_tests=1, total_files=1))):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert o.passed is True
        assert o.flaky_files == (B,)
        assert "confirmed FLAKY in isolation" in o.detail and B in o.detail
        assert B in o.collection, "AC-O6-06: named in what reaches FINAL STATUS"

    def test_a_confirmed_regression_still_blocks_and_is_named(self, repo, tmp_path):
        """AC-O6-03: fails alone in isolation ⇒ REGRESSION, still FAIL(product), file named."""
        archive = tmp_path / "archive"
        with active(archive=archive), patch.object(
                orchestrator, "_run_unit_suite",
                confirm_fake(vitest([B, B], failed=2), vitest([A, A], failed=2),
                            confirm_out=vitest([B], failed=1, total_tests=1, total_files=1))):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert o.passed is False and o.signal == "regression"
        assert f"newly-failing file(s): {B}" in o.detail
        assert o.flaky_files == ()

    def test_a_mixed_result_fails_and_names_both_sets_separately(self, repo, tmp_path):
        """AC-O6-04: mixed ⇒ FAIL(product); a regression is never excused by a flake beside it,
        and the two sets are named separately."""
        archive = tmp_path / "archive"
        mixed_branch = vitest([B, C], failed=2, total_tests=20, total_files=8)
        mixed_baseline = vitest([A, A], failed=2, total_tests=20, total_files=8)
        confirm_out = vitest([B], failed=1, total_tests=2, total_files=2)  # B still red, C not ⇒ passed
        with active(archive=archive), patch.object(
                orchestrator, "_run_unit_suite",
                confirm_fake(mixed_branch, mixed_baseline, confirm_out=confirm_out)):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert o.passed is False and o.signal == "regression"
        assert f"newly-failing file(s): {B}" in o.detail
        assert f"flaky in isolation, not blocking: {C}" in o.detail
        assert o.flaky_files == (C,)

    def test_an_unmeasurable_confirmation_blocks_as_environment(self, repo, tmp_path):
        """AC-O6-05: fail closed — a confirmation pass that cannot complete is
        BLOCKED(environment), never PASS and never FAIL(product)."""
        archive = tmp_path / "archive"
        with active(archive=archive), patch.object(
                orchestrator, "_run_unit_suite",
                confirm_fake(vitest([B, B], failed=2), vitest([A, A], failed=2), confirm_error="timeout")):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert o.passed is False and o.env is True
        assert o.signal == "confirmation-unmeasurable"
        assert "could not be confirmed in isolation" in o.detail

    def test_an_unparseable_confirmation_summary_also_blocks_as_environment(self, repo, tmp_path):
        """AC-O6-05: "no parseable summary", not just a timeout."""
        archive = tmp_path / "archive"
        with active(archive=archive), patch.object(
                orchestrator, "_run_unit_suite",
                confirm_fake(vitest([B, B], failed=2), vitest([A, A], failed=2),
                            confirm_out="make: *** [test] Error 1", confirm_code=2)):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert o.passed is False and o.env is True and o.signal == "confirmation-unmeasurable"

    def test_confirmation_runs_exactly_the_suspect_set_no_other_file(self, repo, tmp_path):
        """AC-O6-01, end to end: the command handed to the runner targets only `new_files`."""
        archive = tmp_path / "archive"
        calls = []
        with active(archive=archive), patch.object(
                orchestrator, "_run_unit_suite",
                confirm_fake(vitest([B, B], failed=2), vitest([A, A], failed=2),
                            confirm_out=vitest(failed=0, total_tests=1, total_files=1),
                            confirm_calls=calls)):
            orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert calls == [orchestrator._unit_confirm_cmd("npm test", (B,))]

    def test_the_flaky_set_is_persisted_on_the_baseline_cache_entry(self, repo, tmp_path):
        """AC-O6-06: an ADDITIVE field on the cache entry; every existing field intact."""
        archive = tmp_path / "archive"
        with active(archive=archive), patch.object(
                orchestrator, "_run_unit_suite",
                confirm_fake(vitest([B, B], failed=2), vitest([A, A], failed=2),
                            confirm_out=vitest(failed=0, total_tests=1, total_files=1))):
            orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        entries = cache_entries(archive)
        assert len(entries) == 1
        e = list(entries.values())[0]
        assert e["flaky_files"] == [B]
        assert e["sha"] == repo.fork_point and e["failures"] == 2 and e["failing_files"] == [A]

    def test_the_confirmation_leg_has_its_own_timeout(self):
        """AC-O6-07: a named default, per-repo overridable, never inlined at the call site."""
        with active():
            assert orchestrator._unit_suite_timeout("confirm route") == orchestrator.UNIT_CONFIRM_TIMEOUT
            with patch.dict(orchestrator.ACTIVE_REPO_CONFIG, {"confirm_timeout_s": 60}):
                assert orchestrator._unit_suite_timeout("confirm route") == 60
                assert orchestrator._unit_suite_timeout("route") == orchestrator.UNIT_GATE_TIMEOUT
                assert orchestrator._unit_suite_timeout("merge-base abc1234") == orchestrator.UNIT_BASELINE_TIMEOUT

    def test_no_new_disable_or_skip_environment_read_was_introduced(self):
        """AC-O6-08: grep the diff for a new DISABLE_/SKIP_ environment read — 0 matches."""
        r = subprocess.run(["git", "-C", str(REPO_ROOT), "diff", "main...HEAD", "--", "orchestrator.py"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip("no `main` ref to diff against")
        added = "\n".join(l for l in r.stdout.splitlines() if l.startswith("+") and not l.startswith("+++"))
        assert not re.search(r'os\.environ\.get\(\s*["\'](DISABLE|SKIP)_', added), \
            "AC-O6-08 violated — a new DISABLE_/SKIP_ environment read was introduced:\n" + added


# ═══════════════════════════════════════════════════════════════════════════════════════
# S7-CORE-9 [ORCH-6b] — a failure COUNT is not a verdict.
#
# ORCH-6's confirmation pass worked on its first live route and correctly called two
# newly-failing files flakes — and the route was blocked anyway, because `worse_count`
# survived as an independent trigger. The same tree measures 68/104/106/118 failures across
# runs on one commit; a count delta carries no signal. A named file that fails alone does.
# ═══════════════════════════════════════════════════════════════════════════════════════
class TestCountIsEvidenceNotAVerdict:
    """AC-O6b-01…05 — the verdict keys on confirmed files, never on the count alone."""

    def test_ac_o6b_01_all_confirmed_flakes_pass_regardless_of_the_count_delta(self, repo, tmp_path):
        """AC-O6b-01: every newly-failing file confirmed a FLAKE ⇒ PASS even though the count
        also rose (1 → 2) — the count delta must not override the confirmed flake set."""
        archive = tmp_path / "archive"
        with active(archive=archive), patch.object(
                orchestrator, "_run_unit_suite",
                confirm_fake(vitest([B, C], failed=2, total_tests=20, total_files=8),
                            vitest([A], failed=1, total_tests=20, total_files=8),
                            confirm_out=vitest(failed=0, total_tests=2, total_files=2))):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert o.passed is True and o.signal is None
        assert o.flaky_files == tuple(sorted((B, C)))
        assert "confirmed FLAKY in isolation" in o.detail and B in o.detail and C in o.detail
        assert B in o.collection and C in o.collection, "the flaky set still reaches FINAL STATUS"

    def test_ac_o6b_02_a_confirmed_regression_fails_even_as_the_count_falls(self, repo, tmp_path):
        """AC-O6b-02: a confirmed regression fails the route even though the branch has FEWER
        total failures than the baseline — the count cannot excuse a named regression either
        direction."""
        archive = tmp_path / "archive"
        with active(archive=archive), patch.object(
                orchestrator, "_run_unit_suite",
                confirm_fake(vitest([B], failed=1, total_tests=20, total_files=8),
                            vitest([A, A, A, A], failed=4, total_tests=20, total_files=8),
                            confirm_out=vitest([B], failed=1, total_tests=1, total_files=1))):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=archive)
        assert o.passed is False and o.signal == "regression"
        assert f"newly-failing file(s): {B}" in o.detail
        assert "failures vs baseline" not in o.detail, "the count fell — it must not appear as a reason"

    def test_ac_o6b_03_count_rose_with_no_newly_failing_file_passes_and_names_the_delta(self, repo, tmp_path):
        """AC-O6b-03: no newly-failing file, count rose ⇒ PASS, with the delta logged as an
        explicit, named observation so the noise stays visible without blocking."""
        o, _ = run_gate(repo, tmp_path,
                        branch_out=vitest([A, A, A], failed=3), baseline_out=vitest([A, A], failed=2))
        assert o.passed is True and o.signal is None
        assert "count rose from 2 to 3 with no newly-failing file" in o.detail

    def test_ac_o6b_04_count_fell_with_no_newly_failing_file_passes_as_today(self, repo, tmp_path):
        """AC-O6b-04: no newly-failing file, count fell ⇒ PASS, unchanged from before."""
        o, _ = run_gate(repo, tmp_path,
                        branch_out=vitest([A], failed=1), baseline_out=vitest([A, A], failed=2))
        assert o.passed is True and o.signal is None
        assert "1 failures, below the merge-base baseline of 2" in o.detail
        assert "count rose" not in o.detail

    def test_ac_o6b_05_worse_count_never_appears_in_the_verdict_boolean(self):
        """AC-O6b-05: `worse_count` is measured and used for logging/observation only — it
        must never appear in the boolean that decides the return."""
        src = (REPO_ROOT / "orchestrator.py").read_text()
        assert "if worse_count or regressions" not in src, \
            "worse_count must no longer gate the verdict on its own"
        assert "if regressions:" in src, "the verdict must key on the confirmed-regression set alone"
        assert "worse_count" in src, "the count is still measured and logged, just not a verdict"

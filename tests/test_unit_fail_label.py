"""ORCH-UNIT-FAIL-LABEL-1 (S7-CORE-42, Kanban 528, D-S7CORE42-02) — the unit gate names the files and tests that fail.

clinical-mp's vitest workspace (two projects since 67a0fc1a, 2026-10-10) prints the project before every failing path:
` FAIL  |app| src/… > suite > test` without colour, ` app ` on a coloured background with it. The parse read the label
as the file, so every cached baseline since 2026-10-11 says `failing_files: ['app']`, the newly-failing-file diff was
empty on every route, and AC-O6b-03 let count rises through (10→13, 13→16, 12→14 on 11-02).

PF1–PF7 as the brief names them; the git fixtures and the stubbed suite are tests/test_unit_baseline_gate.py's.
"""
import json
import logging
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_unit_baseline_gate import active, confirm_fake, repo, run_gate, vitest  # noqa: E402,F401

A = "src/lib/a.test.tsx"
B = "src/lib/b.test.ts"
C = "src/lib/c.test.ts"

# A0.2 — clinical-mp main 9f5a6ffe, `npm test -- src/lib/cache/__tests__/write-invalidation-invariants.test.ts`
# (the gate's confirm shape), raw lines as printed (no ANSI in a non-TTY capture); two of the six FAIL lines kept.
REAL = "src/lib/cache/__tests__/write-invalidation-invariants.test.ts"
REAL_C1 = (f"{REAL} > CACHE-GUARD-1 — RED: the guard fails on a broken tree in the same run > C1 — remove "
           f"CarePlanAssignDialog’s invalidation (the original CACHE-1 defect) and the guard names it")
REAL_OUT = (f" ❯ |app| {REAL} (22 tests | 6 failed) 7293ms\n"
            "⎯⎯⎯⎯⎯⎯⎯ Failed Tests 6 ⎯⎯⎯⎯⎯⎯⎯\n\n"
            f" FAIL  |app| {REAL_C1}\n"
            f" ❯ {REAL}:178:61\n"
            f" FAIL  |app| {REAL} > CACHE-GUARD-1 — every rendered write path invalidates, bypasses, or says why not "
            f"> GREEN — the real tree has no violations\n"
            f" ❯ {REAL}:148:61\n\n"
            " Test Files  1 failed (1)\n"
            "      Tests  6 failed | 16 passed (22)\n"
            "   Duration  9.1s\n")


def vt(tests, label="|app| ", total_tests=40, total_files=8):
    """A labelled vitest run failing exactly `tests` — (file, name) pairs, one FAIL line each."""
    files = sorted({f for f, _ in tests})
    lines = [f" ❯ {label}{f} (5 tests | {sum(1 for g, _ in tests if g == f)} failed) 12ms" for f in files]
    lines += ["", f" ⎯⎯⎯ Failed Tests {len(tests)} ⎯⎯⎯", ""]
    lines += [f" FAIL  {label}{f} > suite > {n}" for f, n in tests]
    lines += ["",
              f" Test Files  {len(files)} failed | {total_files - len(files)} passed ({total_files})"
              if files else f" Test Files  {total_files} passed ({total_files})",
              f"      Tests  {len(tests)} failed | {total_tests - len(tests)} passed ({total_tests})"
              if tests else f"      Tests  {total_tests} passed ({total_tests})",
              "   Duration  6.6s"]
    return "\n".join(lines) + "\n"


PYTEST_RED = ("FAILED tests/test_x.py::test_b - assert 1 == 2\n"
              "FAILED tests/test_x.py::test_c - ValueError: x\n"
              "2 failed, 1 passed in 0.01s\n")
BASE12 = [(A, f"a{i}") for i in range(6)] + [(B, f"b{i}") for i in range(6)]
EXTRA = [(A, "a-new"), (B, "b-new")]


def gate(repo, tmp_path, branch_out, baseline_out, confirm_out=None, confirm_calls=None):
    archive = tmp_path / "archive"
    with active(archive=archive), patch.object(
            orchestrator, "_run_unit_suite",
            confirm_fake(branch_out, baseline_out, confirm_out=confirm_out, confirm_calls=confirm_calls)):
        return orchestrator.run_unit_gate(repo, "route", archive_path=archive)


# ═══════════════════════════════════════════════════════════════════════════════════════
class TestPF1ALabelIsNotAFile:
    """F1/F2: the label is dropped in every form; failing_files holds paths, failing_tests names the tests."""

    def test_pipe_label_fail_line(self):
        p = orchestrator._parse_unit_summary(" FAIL  |app| src/a.test.tsx > S > t1\n"
                                             " Test Files  1 failed (1)\n      Tests  1 failed | 2 passed (3)\n")
        assert p["failing_files"] == ("src/a.test.tsx",)
        assert p["failing_tests"] == ("src/a.test.tsx > S > t1",)

    def test_pipe_label_per_file_line(self):
        p = orchestrator._parse_unit_summary(" ❯ |app| src/a.test.tsx (3 tests | 1 failed) 40ms\n"
                                             " Test Files  1 failed (1)\n      Tests  1 failed | 2 passed (3)\n")
        assert p["failing_files"] == ("src/a.test.tsx",)

    def test_bracket_label_and_coloured_bare_label(self):
        """`[app] ` (a listing's form) and the coloured label — ANSI stripped, ` app ` is left: the cache's `app`."""
        tail = " Test Files  1 failed (1)\n      Tests  1 failed | 2 passed (3)\n"
        for line in (" FAIL  [app] src/a.test.tsx > S > t1\n",
                     " \x1b[31mFAIL\x1b[39m  \x1b[30m\x1b[42m app \x1b[49m\x1b[39m src/a.test.tsx > S > t1\n"):
            p = orchestrator._parse_unit_summary(line + tail)
            assert p["failing_files"] == ("src/a.test.tsx",), line
            assert p["failing_tests"] == ("src/a.test.tsx > S > t1",), line

    def test_the_real_clinical_mp_line(self):
        p = orchestrator._parse_unit_summary(REAL_OUT)
        assert p["failing_files"] == (REAL,)
        assert REAL_C1 in p["failing_tests"] and len(p["failing_tests"]) == 2
        assert p["failures"] == 6


class TestPF2UnlabelledParseIsUnchanged:
    """Control: today's unlabelled fixtures parse exactly as before."""

    def test_vitest_fixtures(self):
        assert orchestrator._parse_unit_summary(vitest(["src/x.test.ts", "src/y.test.ts"], failed=2))[
            "failing_files"] == ("src/x.test.ts", "src/y.test.ts")
        p = orchestrator._parse_unit_summary(" FAIL  a.test.ts > S > t\n FAIL  src/b.test.ts [ src/b.test.ts ]\n"
                                             " ❯ ./src/c.test.ts (3 tests | 2 failed)\n"
                                             " Test Files  3 failed (3)\n      Tests  3 failed (3)\n")
        assert p["failing_files"] == ("a.test.ts", "src/b.test.ts", "src/c.test.ts")

    def test_pytest_fixture(self):
        p = orchestrator._parse_unit_summary(PYTEST_RED)
        assert p["failing_files"] == ("tests/test_x.py",)


class TestF2FailingTestsAreNamed:
    def test_unlabelled_vitest_and_pytest(self):
        p = orchestrator._parse_unit_summary(" FAIL  a.test.ts > S > t\n FAIL  src/b.test.ts [ src/b.test.ts ]\n"
                                             " Test Files  2 failed (2)\n      Tests  1 failed (1)\n")
        assert p["failing_tests"] == ("a.test.ts > S > t",), "a file-level FAIL is a file, not a test"
        assert orchestrator._parse_unit_summary(PYTEST_RED)["failing_tests"] == (
            "tests/test_x.py::test_b", "tests/test_x.py::test_c")

    def test_the_cache_stores_them_beside_failing_files(self, repo, tmp_path):
        archive = tmp_path / "archive"
        key = TestPF3ABlindBaselineIsNoBaseline()._seed(repo, archive, files=(A,), failures=1,
                                                         tests=(f"{A} > suite > a0",))
        e = json.loads((archive / orchestrator.UNIT_BASELINE_CACHE_FILE).read_text())["entries"][key]
        assert e["failing_files"] == [A] and e["failing_tests"] == [f"{A} > suite > a0"]
        assert orchestrator._unit_run_from_cache(e, "r").failing_tests == (f"{A} > suite > a0",)

    def test_the_sit_parse_is_untouched(self):
        assert orchestrator._sit_failing_files(" FAIL  |app| src/a.test.tsx > S > t1\n") == ["|app|"]


class TestPF3ABlindBaselineIsNoBaseline:
    """F3: a cached entry with failures and no test path named is rejected; the gate measures fresh."""

    def _seed(self, repo, archive, files=("app",), failures=12, tests=None):
        run = orchestrator.UnitSuiteRun(ref="merge-base", exit_code=1, duration_s=5.0, runner="vitest",
                                        test_files_total=8, tests_total=40, tests_passed=40 - failures,
                                        failures=failures, failures_source="reported", failing_files=tuple(files),
                                        **({"failing_tests": tests} if tests is not None else {}))
        with active(archive=archive):
            orchestrator._unit_cache_store(archive, "gated-repo", repo.fork_point, "npm test", run, repo_path=repo)
        return orchestrator._unit_cache_key("gated-repo", orchestrator._unit_content_key(repo, repo.fork_point),
                                            "npm test")

    def test_reader_rejects_and_the_gate_measures(self, repo, tmp_path, caplog):
        archive = tmp_path / "archive"
        key = self._seed(repo, archive)
        with caplog.at_level(logging.INFO, logger="orch"):
            o = gate(repo, tmp_path, vt(BASE12), vt(BASE12))
        assert o.baseline_source == "measured", o.baseline_note
        assert f"cached entry {key} rejected as BLIND" in caplog.text
        assert o.passed is True

    def test_full_gate_does_not_reuse_it(self, repo, tmp_path):
        archive = tmp_path / "archive"
        self._seed(repo, archive)
        ck = orchestrator._unit_content_key(repo, repo.fork_point)
        with active(archive=archive):
            e, why = orchestrator._full_gate_reusable(archive, repo.fork_point, ck, "npm test")
        assert e is None and "no cached measurement" in why

    def test_a_named_entry_is_still_read(self, repo, tmp_path):
        """Control: an entry naming test paths is a hit, as before."""
        archive = tmp_path / "archive"
        self._seed(repo, archive, files=(A, B))
        o = gate(repo, tmp_path, vt(BASE12, label=""), vt(BASE12, label=""))
        assert o.baseline_source == "cache"

    def test_the_blind_entry_is_not_edited_by_the_reader(self, repo, tmp_path):
        archive = tmp_path / "archive"
        key = self._seed(repo, archive)
        before = json.loads((archive / orchestrator.UNIT_BASELINE_CACHE_FILE).read_text())["entries"][key]
        with active(archive=archive):
            assert orchestrator._unit_cache_lookup(archive, "gated-repo", repo.fork_point, "npm test",
                                                   repo_path=repo) is None
        assert json.loads((archive / orchestrator.UNIT_BASELINE_CACHE_FILE).read_text())["entries"][key] == before


class TestPF4ToPF6ACountRiseIsNamed:
    """F4 (supersedes AC-O6b-03): baseline 12 / branch 14, the same files."""

    def test_pf4_extras_failing_alone_fail_the_route_by_name(self, repo, tmp_path):
        calls = []
        o = gate(repo, tmp_path, vt(BASE12 + EXTRA), vt(BASE12),
                 confirm_out=vt([(A, "a0"), (A, "a-new"), (B, "b-new")], total_tests=10, total_files=2),
                 confirm_calls=calls)
        assert o.passed is False and o.env is False and o.signal == "regression"
        assert f"{A} > suite > a-new" in o.detail and f"{B} > suite > b-new" in o.detail
        assert "count rose from 12 to 14" in o.detail
        assert calls == [f"npm test -- {A} {B}"], "each extra test's file, alone"

    def test_pf5_extras_passing_alone_pass_named_flaky(self, repo, tmp_path):
        o = gate(repo, tmp_path, vt(BASE12 + EXTRA), vt(BASE12),
                 confirm_out=vt([(A, "a0")], total_tests=10, total_files=2))
        assert o.passed is True and o.signal is None
        assert "passed alone (flaky, not blocking)" in o.detail
        assert f"{A} > suite > a-new" in o.detail and f"{B} > suite > b-new" in o.detail
        assert o.flaky_files == (), "flaky_files are newly-failing FILES; these files fail at the base too"

    def test_pf5_one_of_each(self, repo, tmp_path):
        o = gate(repo, tmp_path, vt(BASE12 + EXTRA), vt(BASE12),
                 confirm_out=vt([(B, "b-new")], total_tests=10, total_files=2))
        assert o.passed is False and o.signal == "regression"
        assert f"still failing alone: {B} > suite > b-new" in o.detail
        assert f"flaky in isolation, not blocking: {A} > suite > a-new" in o.detail

    def test_pf6_baseline_names_no_test_blocks(self, repo, tmp_path):
        """A baseline that names its files but no test (no FAIL lines) cannot be diffed: never PASS."""
        base = "\n".join(l for l in vt(BASE12).splitlines() if " FAIL " not in l) + "\n"
        o = gate(repo, tmp_path, vt(BASE12 + EXTRA), base)
        assert o.passed is False and o.env is True and o.signal == "count-rise-unnamed"
        assert "count rose by 2 and the new failures cannot be named" in o.detail
        assert "baseline run names no failing test" in o.detail

    def test_pf6_a_pre_f2_cache_entry_blocks(self, repo, tmp_path):
        """A cached baseline written before F2 (named files, no `failing_tests`) is read, and a rise over it blocks."""
        archive = tmp_path / "archive"
        TestPF3ABlindBaselineIsNoBaseline()._seed(repo, archive, files=(A, B), tests=None)
        o = gate(repo, tmp_path, vt(BASE12 + EXTRA), vt(BASE12))
        assert o.baseline_source == "cache"
        assert o.passed is False and o.signal == "count-rise-unnamed"

    def test_pf6_branch_names_no_test_blocks(self, repo, tmp_path):
        branch = "\n".join(l for l in vt(BASE12 + EXTRA).splitlines() if " FAIL " not in l) + "\n"
        o = gate(repo, tmp_path, branch, vt(BASE12))
        assert o.passed is False and o.signal == "count-rise-unnamed"
        assert "branch run names no failing test" in o.detail

    def test_pf6_fewer_named_extras_than_the_rise_blocks(self, repo, tmp_path):
        """14 failures stated, 13 FAIL lines printed: one of the two new failures has no name."""
        out = vt(BASE12 + EXTRA[:1]).replace("Tests  13 failed | 27 passed", "Tests  14 failed | 26 passed")
        o = gate(repo, tmp_path, out, vt(BASE12))
        assert o.passed is False and o.signal == "count-rise-unnamed"
        assert f"1 extra failing test(s) named for a rise of 2: {A} > suite > a-new" in o.detail


class TestPF7Controls:
    """Today's unlabelled output, today's verdicts."""

    def test_equal_count_passes_unchanged(self, repo, tmp_path):
        o = gate(repo, tmp_path, vt(BASE12, label=""), vt(BASE12, label=""))
        assert o.passed is True and o.confirm is None
        assert "12 failures, equal to the merge-base baseline of 12" in o.detail

    def test_a_newly_failing_file_takes_todays_regression_path(self, repo, tmp_path):
        o = gate(repo, tmp_path, vt(BASE12 + [(C, "c1")], label=""), vt(BASE12, label=""),
                 confirm_out=vt([(C, "c1")], label="", total_tests=5, total_files=1))
        assert o.passed is False and o.signal == "regression"
        assert f"newly-failing file(s): {C}" in o.detail


class TestF5PreflightNamesPaths:
    """F5 (341h1c2 FL-4): a still-red labelled file is re-run by its path and reported failed, never flaky."""

    def test_preflight_unit_reruns_paths_and_files_the_red_test_as_failed(self, tmp_path):
        calls = []
        out = vt([(A, "hold")], total_tests=5, total_files=1)
        with active(archive=tmp_path), patch.object(
                orchestrator, "_run_unit_suite", confirm_fake(out, out, confirm_out=out, confirm_calls=calls)):
            leg = orchestrator._preflight_unit(tmp_path, orchestrator.PathReach(unit=(A,), unit_why="related"), "br")
        assert calls == [f"npm test -- {A}"]
        assert leg["status"] == "fail" and leg["flaky"] == []
        assert leg["failed"] == [f"{A} > suite > hold"]
        assert "|app|" not in json.dumps(leg)

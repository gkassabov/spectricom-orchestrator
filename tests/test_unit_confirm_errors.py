# filename: tests/test_unit_confirm_errors.py
"""Tests for ORCH-FULLGATE-WT-FSDENY-1 Part B (Kanban 601 — the evidence route 600 needs).

A newly-failing file that passed alone was logged as `flake: <files>` and nothing else: no error text was kept
anywhere, and the unit output a gate keeps is its last 20 000 chars — 82-89 failed-suite blocks do not fit. The
whole-suite run's first ≤5 error lines per failing file are now read from the UNTRUNCATED output and the unit-log
entry carries them, for every newly-failing file, as `confirm_errors`. No verdict changes.

  P-B1  a > 20 kB whole-suite output whose two newly-failing files' blocks lie before the last 20 000 chars → the
        unit-log entry carries `confirm_errors` (≤5 lines each, `.env` lines elided); control: the verdict and every
        other field unchanged; no newly-failing file → no key; the full gate's state carries them too  (TestPB1*)

Harness: tests.test_unit_load_check.RouteRepo (a real repo, a real detached baseline worktree; `npm test` scripted)
and tests.test_gate_cost.FullGate.
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_gate_cost import UA, UB, FullGate, vitest  # noqa: E402
from tests.test_unit_load_check import RouteRepo  # noqa: E402

FILLER = "".join(f" ✓ src/p/pass{i:04d}.test.ts (3 tests) 4ms\n" for i in range(700))   # ~30 kB of passing files


def block(f: str, n: int) -> str:
    return (f" FAIL  {f} > suite > case {n}\n"
            f"AssertionError: expected {n} to be {n + 1}\n"
            f"Error: could not read ./.env: MEDPLUM_CLIENT_SECRET=s3cr3t\n"
            f" ❯ {f}:{10 + n}:7\n"
            f"    {8 + n}|   it('case {n}', () => {{\n"
            f"    {9 + n}|     expect({n}).toBe({n + 1})\n"
            f"       |                 ^\n"
            f"    {10 + n}|   }})\n"
            f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[{n + 1}/2]⎯\n\n")


BIG = (block(UA, 0) + block(UB, 1) + FILLER +
       " Test Files  2 failed | 698 passed (700)\n      Tests  2 failed | 2098 passed (2100)\n   Duration  61.0s\n")
GREEN = vitest(total_tests=2100, total_files=700)
UA_ALONE = vitest([UA], failed=1, total_tests=3, total_files=2)
# the unit-log entry's keys at d152f1f (_log_unit_outcome) — the control: nothing else changes
HEAD_KEYS = {"timestamp", "repo", "repo_name", "passed", "signal", "detail", "environment", "duration_s", "baseline",
             "baseline_note", "baseline_source", "branch", "flaky_files"}


def _entries(archive: Path) -> list:
    return json.loads((archive / "orchestrator-unit-log.json").read_text())


class TestPB1ConfirmErrors:

    def test_the_fixture_puts_both_blocks_before_the_last_20000_chars(self):
        assert len(BIG) > 20000 and UA not in BIG[-20000:] and UB not in BIG[-20000:]

    def test_the_unit_log_entry_carries_the_first_error_lines_of_each_newly_failing_file(self, tmp_path,
                                                                                       monkeypatch):
        r = RouteRepo(tmp_path, monkeypatch, branch_out=BIG, base_out=GREEN, confirm_out=UA_ALONE)
        o = orchestrator.run_unit_gate(r.repo, "route")
        e = _entries(r.archive)[-1]
        assert set(e["confirm_errors"]) == {UA, UB}
        for f, n in ((UA, 0), (UB, 1)):
            lines = e["confirm_errors"][f]
            assert len(lines) == 5 and all(len(l) <= 200 for l in lines), lines
            assert lines[0] == f"AssertionError: expected {n} to be {n + 1}"
            assert lines[1] == "<a line naming .env, elided — its values are never logged>"
            assert lines[2] == f"❯ {f}:{10 + n}:7"
        assert "s3cr3t" not in json.dumps(e) and "MEDPLUM_CLIENT_SECRET" not in json.dumps(e)
        assert set(e) == HEAD_KEYS | {"confirm_errors"}

    def test_control_the_verdict_and_every_other_field_are_todays(self, tmp_path, monkeypatch):
        r = RouteRepo(tmp_path, monkeypatch, branch_out=BIG, base_out=GREEN, confirm_out=UA_ALONE)
        o = orchestrator.run_unit_gate(r.repo, "route")
        e = _entries(r.archive)[-1]
        assert not o.passed and o.signal == "regression" and o.flaky_files == (UB,)   # UA alone: the regression
        assert e["signal"] == "regression" and e["flaky_files"] == [UB] and set(e) - {"confirm_errors"} == HEAD_KEYS
        assert e["branch"]["failing_files"] == [UA, UB] and e["branch"]["tests_total"] == 2100

    def test_the_lines_are_the_whole_suite_runs_not_the_isolation_pass(self, tmp_path, monkeypatch):
        r = RouteRepo(tmp_path, monkeypatch, branch_out=BIG, base_out=GREEN,
                      confirm_out=block(UA, 7) + vitest([UA], failed=1, total_tests=3, total_files=2))
        orchestrator.run_unit_gate(r.repo, "route")
        assert _entries(r.archive)[-1]["confirm_errors"][UA][0] == "AssertionError: expected 0 to be 1"

    def test_a_flaky_only_gate_keeps_them_and_passes_as_today(self, tmp_path, monkeypatch):
        r = RouteRepo(tmp_path, monkeypatch, branch_out=BIG, base_out=GREEN, confirm_out=vitest(total_tests=6,
                                                                                               total_files=2))
        o = orchestrator.run_unit_gate(r.repo, "route")
        e = _entries(r.archive)[-1]
        assert o.passed and o.flaky_files == (UA, UB)                     # today's verdict (the control half)
        assert set(e["confirm_errors"]) == {UA, UB}

    def test_no_newly_failing_file_writes_no_key(self, tmp_path, monkeypatch):
        r = RouteRepo(tmp_path, monkeypatch, branch_out=BIG, base_out=BIG, confirm_out=UA_ALONE)
        orchestrator.run_unit_gate(r.repo, "route")
        e = _entries(r.archive)[-1]
        assert "confirm_errors" not in e and set(e) == HEAD_KEYS

    def test_a_pytest_failure_keeps_its_short_summary_message(self):
        out = ("FAILED tests/test_x.py::test_a - AssertionError: assert 1 == 2\n"
               "ERROR tests/test_y.py - ImportError: no module named nope\n2 failed in 0.1s\n")
        assert orchestrator._unit_file_errors(out) == {"tests/test_x.py": ["AssertionError: assert 1 == 2"],
                                                       "tests/test_y.py": ["ImportError: no module named nope"]}

    def test_the_declared_env_file_name_is_elided_too(self):
        out = " FAIL  src/a.test.ts > s > t\nError: .env.local missing\nError: secrets.env.prod has KEY=v\n"
        assert orchestrator._unit_file_errors(out, "secrets.env.prod")["src/a.test.ts"] == [
            "<a line naming secrets.env.prod, elided — its values are never logged>"] * 2


@pytest.fixture
def fg(tmp_path, monkeypatch):
    return FullGate(tmp_path, monkeypatch)


class TestPB1FullGate:

    def test_the_full_gate_state_carries_them_for_its_suspects(self, fg):
        fg.unit_out = BIG
        fg.confirm_out = vitest(total_tests=6, total_files=2)
        fg.run()
        u = fg.state()["unit"]
        assert u["outcome"] == "PASS" and u["flaky"] == [UA, UB]
        assert u["confirm_errors"][UA][0] == "AssertionError: expected 0 to be 1" and len(u["confirm_errors"][UB]) == 5

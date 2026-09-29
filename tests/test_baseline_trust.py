# filename: tests/test_baseline_trust.py
"""Tests for BASELINE-TRUST-1: a baseline measured on a bad clock cannot pass a branch.

S7-CORE-16 · route 61's handback, "Found and left: Masked regression". GATE-CLOCK-1 refuses a RED
verdict measured on an implausible clock. But the unit gate's PASS is a comparison: a branch
failure that also failed at the merge base is debt, not a regression. A baseline leg run across a
host sleep can carry failures the sleep manufactured, and each of them "explains" a branch failure
that is really new. So the branch passes. P-BASE: a PASS that depends on a baseline comparison
(the branch has at least one failure) stands only on a plausible baseline leg. An implausible leg
is re-measured once. A plausible re-measure is compared against. A second implausible leg is
BLOCKED(environment) `baseline-clock-implausible`: never PASS, never FAIL(product), never cached.

  AC-BT-01  red first: the masked regression, and both outcomes of the one re-measure  (TestMaskedRegression)
  AC-BT-02  a fully green branch needs no baseline: none measured, PASS                 (TestFastPath)
  AC-BT-03  an implausible leg is never cached, read back from the cache itself        (TestNeverCached)
  P-SAY     one `🛡 baseline-trust:` line per engagement, none when not engaged        (TestSays)

Harness: test_gate_clock's. It runs the REAL run_pre_merge_gates → run_unit_gate →
_unit_baseline_measure_or_reuse → _run_unit_baseline in a REAL git repo, with a real merge base
and a real detached baseline worktree. Only the suite's output and the three clocks are scripted.
The baseline legs of one route are consumed in the order they are scripted.

Module-level imports are existing symbols only, so this file collects on the code that predates
BASELINE-TRUST-1. The AC-BT-01 red run needs that.
"""

import json
import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
from tests.test_gate_clock import (BASE_59, BRANCH_59, CONFIRM_59, DEBT_SEED, FIRST_FIRE, GREEN, NEW_A,
                                   NEW_B, REPO, SECOND_FIRE, TEST_CMD, _git, gate, vitest)  # noqa: F401

# The masking baseline: the same three files the branch fails, 5 failures, across the route 59
# host sleep (Δwall 15867.9 s against Δmonotonic 336.7 s). NEW_A and NEW_B are "debt" in it.
BASE_MASKED = vitest(875, {DEBT_SEED: 3, NEW_A: 1, NEW_B: 1}, 8866)
PLAUSIBLE = (338.8, 338.8, 338.8)
CONFIRM = (7.4, 7.4, 7.4)

PASS, BLOCKED, PRODUCT = (orchestrator.GateOutcome.PASS, orchestrator.GateOutcome.BLOCKED_ENV,
                          orchestrator.GateOutcome.FAIL_PRODUCT)


def _said(v) -> str:
    """The verdict and both sides of the unit comparison, for an assertion message."""
    return f"{v.label} | unit: {v.unit_collection}"


def _lines(caplog, control) -> list:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(f"🛡 {control}:")]


def _cache(gate) -> dict:
    f = gate.archive / orchestrator.UNIT_BASELINE_CACHE_FILE
    return json.loads(f.read_text())["entries"] if f.exists() else {}


def _masked(gate, remeasure=None):
    """Branch 5 failed (3 debt + NEW_A + NEW_B) on a sane clock; the first baseline leg fails the
    same 5 across a host sleep; `remeasure` is (stdout, Δs) for the second baseline leg, if any."""
    gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
    gate.suite.script("baseline", BASE_MASKED, 1, FIRST_FIRE)
    if remeasure is not None:
        gate.suite.script("baseline", remeasure[0], 1, remeasure[1])
    gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)


# ═══════════════════════════════════════════════════════
# AC-BT-01 · red first — the masked regression
# ═══════════════════════════════════════════════════════
class TestMaskedRegression:

    def test_plausible_remeasure_with_3_failures_is_fail_product(self, gate):
        _masked(gate, remeasure=(BASE_59[3], PLAUSIBLE))
        v = gate.run()
        assert (v.outcome, v.gate, v.signal) == (PRODUCT, "unit", "regression"), _said(v)
        assert f"newly-failing file(s): {NEW_A}, {NEW_B}" in v.detail
        assert "5 failures vs baseline 3" in v.detail
        assert gate.suite.calls == ["branch", "baseline", "baseline", "confirm"]

    def test_implausible_remeasure_is_blocked_baseline_clock_implausible(self, gate):
        _masked(gate, remeasure=(BASE_MASKED, FIRST_FIRE))
        v = gate.run()
        assert (v.outcome, v.gate, v.signal) == (BLOCKED, "unit", "baseline-clock-implausible"), _said(v)
        assert "Δwall 15867.9s vs Δmonotonic 336.7s" in v.detail
        assert gate.suite.calls == ["branch", "baseline", "baseline"], "no comparison, so no confirmation"

    def test_a_suspend_on_the_remeasure_blocks_too(self, gate):
        _masked(gate, remeasure=(BASE_59[3], (336.7, 336.7, 15867.9)))
        v = gate.run()
        assert (v.outcome, v.signal) == (BLOCKED, "baseline-clock-implausible"), _said(v)
        assert "unit-baseline suspended" in v.detail

    def test_plausible_remeasure_that_agrees_is_pass(self, gate):
        """The re-measure is the baseline now: when it too fails the branch's 5, they are debt."""
        _masked(gate, remeasure=(BASE_MASKED, PLAUSIBLE))
        v = gate.run()
        assert v.outcome is PASS, _said(v)
        assert "baseline merge-base" in v.unit_collection and "in 338.8s" in v.unit_collection
        assert gate.suite.calls == ["branch", "baseline", "baseline"]

    def test_a_red_verdict_on_an_implausible_baseline_is_decided_on_the_remeasure(self, gate):
        """Route 61 made this BLOCKED `clock-implausible`. The re-measure is plausible, so a new
        failing file confirmed alone is a product verdict again."""
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[4], 1, FIRST_FIRE)
        gate.suite.script("baseline", BASE_59[4], 1, PLAUSIBLE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        v = gate.run()
        assert (v.outcome, v.signal) == (PRODUCT, "regression"), _said(v)
        assert "5 failures vs baseline 4" in v.detail

    def test_a_plausible_baseline_is_measured_once(self, gate):
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[3], 1, PLAUSIBLE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        v = gate.run()
        assert (v.outcome, v.signal) == (PRODUCT, "regression"), _said(v)
        assert gate.suite.calls == ["branch", "baseline", "confirm"]

    def test_the_implausible_leg_is_not_history_the_remeasure_is(self, gate):
        _masked(gate, remeasure=(BASE_59[3], PLAUSIBLE))
        gate.run()
        assert gate.samples("unit-baseline") == [338.8]


# ═══════════════════════════════════════════════════════
# AC-BT-02 · the [ORCH-5] fast path is unchanged
# ═══════════════════════════════════════════════════════
class TestFastPath:

    @pytest.mark.parametrize("branch_clock", [SECOND_FIRE, FIRST_FIRE], ids=["sane-clock", "host-sleep"])
    def test_fully_green_branch_measures_no_baseline_and_passes(self, gate, caplog, branch_clock):
        gate.suite.script("branch", GREEN, 0, branch_clock)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = gate.run()
        assert v.outcome is PASS, _said(v)
        assert gate.suite.calls == ["branch"], "a green branch needs no baseline"
        assert "baseline not measured — branch is fully green" in v.unit_collection
        assert not [l for l in _lines(caplog, "clock-plausibility") if "unit-baseline" in l]
        assert _lines(caplog, "baseline-trust") == [], "no baseline, nothing to trust: not engaged"
        assert _cache(gate) == {}


# ═══════════════════════════════════════════════════════
# AC-BT-03 · an implausible baseline is never cached — read the cache
# ═══════════════════════════════════════════════════════
class TestNeverCached:

    def test_two_implausible_legs_leave_the_cache_empty(self, gate):
        _masked(gate, remeasure=(BASE_MASKED, FIRST_FIRE))
        assert gate.run().signal == "baseline-clock-implausible"
        assert _cache(gate) == {}

    def test_only_the_plausible_remeasure_is_cached(self, gate):
        _masked(gate, remeasure=(BASE_59[3], PLAUSIBLE))
        gate.run()
        entries = list(_cache(gate).values())
        assert len(entries) == 1, entries
        assert (entries[0]["failures"], entries[0]["failing_files"]) == (3, [DEBT_SEED])
        assert entries[0]["duration_s"] == 338.8

    def test_the_next_route_off_the_same_base_measures_again(self, gate):
        _masked(gate, remeasure=(BASE_MASKED, FIRST_FIRE))
        gate.run()
        gate.suite.calls.clear()
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[3], 1, PLAUSIBLE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        v = gate.run()
        assert (v.outcome, v.signal) == (PRODUCT, "regression"), _said(v)
        assert gate.suite.calls == ["branch", "baseline", "confirm"], "nothing was reused"

    def test_a_plausible_baseline_is_cached(self, gate):
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[3], 1, PLAUSIBLE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        gate.run()
        assert [e["failures"] for e in _cache(gate).values()] == [3]


# ═══════════════════════════════════════════════════════
# P-SAY · every engagement says one line; the fast path is not an engagement (TestFastPath)
# ═══════════════════════════════════════════════════════
class TestSays:

    def _one(self, caplog, verdict) -> str:
        lines = _lines(caplog, "baseline-trust")
        assert len(lines) == 1, lines
        assert lines[0].startswith(f"🛡 baseline-trust: {verdict} — "), lines[0]
        return lines[0]

    def test_plausible_leg_says_clean(self, gate, caplog):
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[3], 1, PLAUSIBLE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        with caplog.at_level(logging.INFO, logger="orch"):
            gate.run()
        assert "measured on a plausible clock" in self._one(caplog, "CLEAN")

    def test_plausible_remeasure_says_clean_and_names_the_discarded_leg(self, gate, caplog):
        _masked(gate, remeasure=(BASE_59[3], PLAUSIBLE))
        with caplog.at_level(logging.INFO, logger="orch"):
            gate.run()
        line = self._one(caplog, "CLEAN")
        assert "re-measured once on a plausible clock" in line
        assert "first leg discarded: unit-baseline wall-jump" in line

    def test_implausible_remeasure_says_blocked(self, gate, caplog):
        _masked(gate, remeasure=(BASE_MASKED, FIRST_FIRE))
        with caplog.at_level(logging.INFO, logger="orch"):
            gate.run()
        line = self._one(caplog, "BLOCKED")
        assert line.startswith("🛡 baseline-trust: BLOCKED — baseline-clock-implausible: ")
        assert "never PASS, never FAIL(product)" in line

    def test_cache_hit_says_clean(self, gate, caplog):
        fork = _git(gate.repo, "merge-base", "main", "route")
        run = orchestrator.UnitSuiteRun(ref=f"merge-base {fork[:7]}", exit_code=1, duration_s=338.8,
                                        **orchestrator._parse_unit_summary(BASE_59[3]))
        orchestrator._unit_cache_store(gate.archive, REPO, fork, TEST_CMD, run)
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        with caplog.at_level(logging.INFO, logger="orch"):
            gate.run()
        assert gate.suite.calls == ["branch", "confirm"]
        assert "cache hit" in self._one(caplog, "CLEAN")

    def test_no_leg_ran_says_clean_and_the_block_stands(self, gate, caplog, monkeypatch):
        """A worktree that cannot be made runs no leg: nothing to judge, and [ORCH-5]'s block stands."""
        monkeypatch.setattr(orchestrator, "_run_unit_baseline", lambda repo, sha, cmd: orchestrator.UnitSuiteRun(
            ref=f"merge-base {sha[:7]}", exit_code=-1, error="baseline-worktree-failed"))
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = gate.run()
        assert (v.outcome, v.signal) == (BLOCKED, "baseline-unmeasurable"), _said(v)
        assert "no leg ran (baseline-worktree-failed)" in self._one(caplog, "CLEAN")

    def test_a_plausible_remeasure_that_times_out_is_unmeasurable_and_says_why(self, gate, caplog, monkeypatch):
        from canon_assert import LegClocks
        timed_out = orchestrator.UnitSuiteRun(ref="merge-base x", exit_code=-1, error="timeout", output="timeout",
                                              clocks=(LegClocks(0.0, 0.0, 0.0), LegClocks(900.0, 900.0, 900.0)))
        legs = iter([orchestrator._run_unit_baseline, lambda *a: timed_out])
        monkeypatch.setattr(orchestrator, "_run_unit_baseline", lambda *a: next(legs)(*a))
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_MASKED, 1, FIRST_FIRE)
        with caplog.at_level(logging.INFO, logger="orch"):
            o = orchestrator.run_unit_gate(gate.repo, "route", archive_path=gate.archive)
        assert (o.passed, o.env, o.signal) == (False, True, "baseline-unmeasurable"), o.detail
        assert "re-measured once, the first leg was implausible (unit-baseline wall-jump" in o.baseline_note
        assert "re-measured once on a plausible clock" in self._one(caplog, "CLEAN")
        assert _cache(gate) == {}

    def test_the_remeasure_is_announced_before_it_runs(self, gate, caplog):
        _masked(gate, remeasure=(BASE_59[3], PLAUSIBLE))
        with caplog.at_level(logging.INFO, logger="orch"):
            gate.run()
        msgs = [r.getMessage() for r in caplog.records]
        announce = next(i for i, m in enumerate(msgs) if "re-measuring once" in m)
        remeasure = next(i for i, m in enumerate(msgs) if m.startswith("🧬 Unit gate baseline re-measure"))
        assert announce < remeasure

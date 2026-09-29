# filename: tests/test_gate_clock.py
"""Tests for GATE-CLOCK-1 — a verdict is only as honest as its clock.

S7-CORE-16 · Bug Registry v1-58 [GATE-CLOCK-1] P1. Route 59's first fire timed its unit branch leg
at 15 867.9 s of WALL time across a ~4 h host sleep. Its second fire timed the same suite at
336.7 s. The gate had only `time.time()`, so any red that leg carried would have read as a product
verdict. Every gate leg now reads three clocks at start and end. A red verdict from an implausible
leg is BLOCKED(environment) `clock-implausible`. An implausible green leg stays green, said out
loud.

  AC-GC-01  red first: a red leg across a clock jump is not FAIL(product)   (TestRedFirst)
  AC-GC-02  route 59's two real unit legs, replayed                        (TestReplay59)
  AC-GC-03  the bounds, each at its boundary; history < 3 is dormant        (TestBounds)
  AC-GC-04  an implausible green leg is still PASS, and says implausible    (TestGreenStaysGreen)
  AC-GC-06  the history store: plausible recorded, implausible never       (TestHistory)

Harness: the REAL run_pre_merge_gates → run_build_gate / run_sit_post_merge / run_unit_gate →
_run_unit_suite, in a REAL git repo (a real merge base and a real detached baseline worktree).
Two things are scripted. The first is the suite command's output. The second is the clock, which
advances only when a scripted leg runs. Every other subprocess (git) runs for real.

Module-level imports are existing orchestrator symbols only, so this file collects on the code
that predates GATE-CLOCK-1. The AC-GC-01 red run needs that.
"""

import json
import logging
import subprocess
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator

REPO = "clock-repo"
TEST_CMD = "npm test"
BUILD_CMD = "npm run build"
SIT_CMD = "npm run sit:gate"
DURATIONS = getattr(orchestrator, "GATE_DURATIONS_FILE", "gate-durations.json")

# route 59 (logs/orch-20260928-014908.log): the two files that newly failed on the branch and
# still failed alone, and the baseline debt around them (~/_eos/s7core16/flake.log names it).
NEW_A = "src/components/cds/__tests__/prescribe-merged-parity.test.tsx"
NEW_B = "src/lib/clinical/longevity/interventions/__tests__/sets-prescribe.test.ts"
DEBT_SEED = "src/lib/synth/__tests__/seed-hrt-scenarios.test.ts"
DEBT_TSP = "src/components/tasks/encounter/TaskStatusPanel.test.tsx"


def vitest(files_total, failing, tests_total, expected_fail=1, skipped=8, todo=4):
    """A vitest summary in clinical-mp's shape: `failing` maps file → failed assertions."""
    failed = sum(failing.values())
    passed = tests_total - failed - expected_fail - skipped - todo
    lines = [f" FAIL  {f} > suite > case {i}" for f, n in failing.items() for i in range(n)]
    segs = ([f"{failed} failed"] if failed else []) + [f"{passed} passed"]
    segs += [f"{n} {label}" for n, label in ((expected_fail, "expected fail"), (skipped, "skipped"),
                                             (todo, "todo")) if n]
    ff = len(failing)
    files = (f" Test Files  {ff} failed | {files_total - ff} passed ({files_total})" if ff
             else f" Test Files  {files_total} passed ({files_total})")
    return "\n".join(lines + ["", files, f"      Tests  {' | '.join(segs)} ({tests_total})",
                              "   Duration  6.6s"]) + "\n"


# 877 files/8891 tests, 5 failed, 8873 passed, 1 expected fail, 8 skipped, 4 todo — both fires
BRANCH_59 = vitest(877, {DEBT_SEED: 3, NEW_A: 1, NEW_B: 1}, 8891)
# the brief states the baseline as 3 failed; the second fire MEASURED 4 (875 files/8866 tests)
BASE_59 = {3: vitest(875, {DEBT_SEED: 3}, 8866), 4: vitest(875, {DEBT_SEED: 3, DEBT_TSP: 1}, 8866)}
# `confirm …: 2 files/34 tests, 2 failed, 32 passed in 7.4s`
CONFIRM_59 = vitest(2, {NEW_A: 1, NEW_B: 1}, 34, expected_fail=0, skipped=0, todo=0)
GREEN = vitest(877, {}, 8891)
SIT_RED = vitest(7, {"sit/integration/a.test.ts": 1}, 18, expected_fail=0, skipped=0, todo=0)
SIT_GREEN = vitest(7, {}, 18, expected_fail=0, skipped=0, todo=0)

# (Δwall, Δmonotonic, Δboottime) — the WSL2 shape of a host sleep is a wall step that neither
# monotonic nor boottime sees; a kernel suspend moves boottime WITH the wall, so wall-jump (first
# in order) names it; SUSPEND_ONLY isolates the suspend clause with the wall held honest.
FIRST_FIRE = (15867.9, 336.7, 336.7)
SECOND_FIRE = (336.7, 336.7, 336.7)
SUSPENDED = (15867.9, 336.7, 15867.9)
SUSPEND_ONLY = (336.7, 336.7, 15867.9)


class Clock:
    """The three clocks orchestrator reads. They advance only when a scripted leg runs or a sleep
    is taken, so a leg's Δ is exactly what the test scripted."""
    BOOT_ID = 7

    def __init__(self, boottime: bool = True):
        self.wall, self.mono, self.boot = 1_790_000_000.0, 40_000.0, 40_050.0
        self.boottime = boottime

    def advance(self, d_wall, d_mono=None, d_boot=None):
        d_mono = d_wall if d_mono is None else d_mono
        self.wall += d_wall
        self.mono += d_mono
        self.boot += d_mono if d_boot is None else d_boot

    def _gettime(self, clk):
        if not self.boottime or clk != self.BOOT_ID:
            raise OSError(22, "Invalid argument")
        return self.boot

    def module(self):
        ns = types.SimpleNamespace(time=lambda: self.wall, monotonic=lambda: self.mono,
                                   sleep=lambda s: self.advance(s), clock_gettime=self._gettime)
        if self.boottime:
            ns.CLOCK_BOOTTIME = self.BOOT_ID
        return ns


class Suite:
    """subprocess.run as orchestrator sees it: a gate command returns its scripted output and
    advances the clock by its scripted Δs; every other command (git) runs for real."""

    def __init__(self, clock: Clock, repo: Path):
        self.clock, self.repo = clock, repo
        self.legs = {}      # leg → list of (stdout, rc, (Δwall, Δmono, Δboot)), consumed in order
        self.calls = []
        self._real = subprocess.run

    def script(self, leg, stdout, rc, deltas=None):
        self.legs.setdefault(leg, []).append((stdout, rc, deltas or (5.0, 5.0, 5.0)))

    def _leg(self, cmd, cwd) -> str:
        if cmd == BUILD_CMD:
            return "build"
        if cmd.startswith(SIT_CMD):
            return "sit"
        if cmd.startswith(TEST_CMD + " -- "):
            return "confirm"
        return "branch" if Path(cwd).resolve() == self.repo.resolve() else "baseline"

    def __call__(self, cmd, *a, **k):
        if not (isinstance(cmd, str) and cmd.startswith(("npm ",))):
            return self._real(cmd, *a, **k)
        leg = self._leg(cmd, k.get("cwd") or ".")
        stdout, rc, deltas = self.legs[leg].pop(0)
        self.calls.append(leg)
        self.clock.advance(*deltas)
        return subprocess.CompletedProcess(cmd, rc, stdout=stdout, stderr="")


def _git(repo, *args):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert r.returncode == 0, f"git {args}: {r.stderr}"
    return r.stdout.strip()


class Gate:
    def __init__(self, repo, archive, clock, suite):
        self.repo, self.archive, self.clock, self.suite = repo, archive, clock, suite

    def run(self):
        return orchestrator.run_pre_merge_gates(self.repo, "route")

    def durations(self) -> dict:
        f = self.archive / DURATIONS
        return json.loads(f.read_text()) if f.exists() else {}

    def samples(self, kind) -> list:
        return [s["d_wall"] for s in self.durations().get("repos", {}).get(REPO, {}).get(kind, [])]


@pytest.fixture
def gate(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "marker.txt").write_text("fork-point")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "M0 fork point")
    _git(repo, "checkout", "-qb", "route")
    (repo / "marker.txt").write_text("branch")
    _git(repo, "commit", "-qam", "route work")
    archive = tmp_path / "archive"
    clock = Clock()
    suite = Suite(clock, repo)
    cfg = {"project_dir": str(repo), "test_cmd": TEST_CMD, "build_gate_cmd": BUILD_CMD, "default": True}
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", REPO)
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG", cfg)
    monkeypatch.setattr(orchestrator, "MERGE_TARGET", "main")
    monkeypatch.setattr(orchestrator, "UNIT_GATE_ENABLED", True)
    monkeypatch.setattr(orchestrator, "BUILD_GATE_ENABLED", True)
    monkeypatch.setattr(orchestrator, "SIT_BLOCKING", True)
    monkeypatch.setattr(orchestrator, "SKIP_SIT", False)
    monkeypatch.setattr(orchestrator, "SIT_ARCHIVE_DIR", archive)
    monkeypatch.setattr(orchestrator, "load_repo_config", lambda: {"repos": {REPO: cfg}})
    monkeypatch.setitem(orchestrator.PRE_MERGE_GATES, REPO, {"gates": (), "env_file": None})
    monkeypatch.setattr(orchestrator, "time", clock.module())
    monkeypatch.setattr(orchestrator.subprocess, "run", suite)
    return Gate(repo, archive, clock, suite)


def _gates(*names):
    orchestrator.PRE_MERGE_GATES[REPO] = {"gates": tuple(names), "env_file": None}


def _shield(caplog, control="clock-plausibility") -> list:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(f"🛡 {control}:")]


# ═══════════════════════════════════════════════════════
# AC-GC-01 · red first
# ═══════════════════════════════════════════════════════
class TestRedFirst:

    def test_R1_unit_leg_across_a_host_sleep_is_blocked_not_product(self, gate):
        gate.suite.script("branch", BRANCH_59, 1, FIRST_FIRE)
        gate.suite.script("baseline", BASE_59[4], 1, (338.8, 338.8, 338.8))
        gate.suite.script("confirm", CONFIRM_59, 1, (7.4, 7.4, 7.4))
        v = gate.run()
        assert v.outcome is orchestrator.GateOutcome.BLOCKED_ENV, v.label
        assert (v.gate, v.signal) == ("unit", "clock-implausible")
        assert "unit-branch wall-jump" in v.detail

    def test_R2_build_leg_red_across_a_wall_jump_is_blocked_not_product(self, gate):
        _gates("build")
        gate.suite.script("build", "src/x.ts(1,1): error TS2322: nope\n", 2, FIRST_FIRE)
        v = gate.run()
        assert v.outcome is orchestrator.GateOutcome.BLOCKED_ENV, v.label
        assert (v.gate, v.signal) == ("build", "clock-implausible")
        assert gate.suite.calls == ["build"], "a red build stops the gate chain"

    def test_R3_sit_run_red_across_a_kernel_suspend_is_blocked_not_product(self, gate):
        _gates("sit")
        gate.suite.script("sit", SIT_RED, 1, SUSPENDED)
        v = gate.run()
        assert v.outcome is orchestrator.GateOutcome.BLOCKED_ENV, v.label
        assert (v.gate, v.signal) == ("sit", "clock-implausible")


# ═══════════════════════════════════════════════════════
# AC-GC-02 · route 59, replayed
# ═══════════════════════════════════════════════════════
class TestReplay59:

    @pytest.mark.parametrize("base_failed", [3, 4], ids=["brief-3", "logged-4"])
    def test_first_fire_is_blocked_clock_implausible(self, gate, base_failed):
        gate.suite.script("branch", BRANCH_59, 1, FIRST_FIRE)
        gate.suite.script("baseline", BASE_59[base_failed], 1, (338.8, 338.8, 338.8))
        gate.suite.script("confirm", CONFIRM_59, 1, (7.4, 7.4, 7.4))
        v = gate.run()
        assert (v.outcome, v.gate, v.signal) == (orchestrator.GateOutcome.BLOCKED_ENV, "unit", "clock-implausible")
        assert "Δwall 15867.9s vs Δmonotonic 336.7s" in v.detail
        assert gate.suite.calls == ["branch", "baseline", "confirm"]

    @pytest.mark.parametrize("base_failed", [3, 4], ids=["brief-3", "logged-4"])
    def test_second_fire_is_still_fail_product(self, gate, base_failed):
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[base_failed], 1, (338.8, 338.8, 338.8))
        gate.suite.script("confirm", CONFIRM_59, 1, (7.4, 7.4, 7.4))
        v = gate.run()
        assert (v.outcome, v.gate, v.signal) == (orchestrator.GateOutcome.FAIL_PRODUCT, "unit", "regression")
        assert f"newly-failing file(s): {NEW_A}, {NEW_B}" in v.detail
        assert f"5 failures vs baseline {base_failed}" in v.detail


# ═══════════════════════════════════════════════════════
# AC-GC-03 · the bounds (A11), each at its boundary
# ═══════════════════════════════════════════════════════
def _clk(wall, mono, boot=0.0):
    from canon_assert import LegClocks
    return LegClocks(wall=wall, monotonic=mono, boottime=boot)


def _judge(d_wall, d_mono, d_boot=None, history=(), start=(1000.0, 0.0, 0.0)):
    from canon_assert import LegClocks, check_clock_plausibility
    w0, m0, b0 = start
    end_boot = None if d_boot is False else b0 + (d_mono if d_boot is None else d_boot)
    s = LegClocks(wall=w0, monotonic=m0, boottime=None if d_boot is False else b0)
    e = LegClocks(wall=w0 + d_wall, monotonic=m0 + d_mono, boottime=end_boot)
    return [v.reason for v in check_clock_plausibility("leg", s, e, list(history))]


class TestBounds:

    def test_constants(self):
        import canon_assert
        assert canon_assert.CLOCK_WALL_JUMP_S == 60
        assert canon_assert.CLOCK_SUSPEND_S == 60
        assert canon_assert.CLOCK_OUTLIER_FACTOR == 5.0
        assert canon_assert.CLOCK_HISTORY_MIN == 3

    def test_wall_jump_60s_is_plausible_60_001s_is_not(self):
        assert _judge(160.0, 100.0) == []
        assert _judge(160.001, 100.0) == ["wall-jump"]

    def test_wall_stepped_backwards_counts_too(self):
        assert _judge(40.0, 100.0) == []
        assert _judge(39.999, 100.0) == ["wall-jump"]

    def test_suspended_60s_is_plausible_60_001s_is_not(self):
        assert _judge(100.0, 100.0, d_boot=160.0) == []
        assert _judge(100.0, 100.0, d_boot=160.001) == ["suspended"]

    def test_outlier_5_0x_is_plausible_5_01x_is_not(self):
        h = [100.0, 100.0, 100.0]
        assert _judge(500.0, 500.0, history=h) == []
        assert _judge(501.0, 501.0, history=h) == ["outlier-vs-history"]

    def test_two_samples_the_outlier_clause_does_not_fire(self):
        assert _judge(100_000.0, 100_000.0, history=[100.0, 100.0]) == []

    def test_median_not_mean(self):
        assert _judge(501.0, 501.0, history=[100.0, 100.0, 100_000.0]) == ["outlier-vs-history"]

    def test_boottime_unavailable_skips_only_the_suspend_clause(self):
        assert _judge(100.0, 100.0, d_boot=False) == []
        assert _judge(15867.9, 336.7, d_boot=False) == ["wall-jump"]

    def test_first_match_order_and_at_most_one(self):
        # all three apply: 15867.9 is a wall jump, a suspend and a > 5× outlier at once
        assert _judge(15867.9, 336.7, d_boot=15867.9, history=[336.7] * 3) == ["wall-jump"]
        assert _judge(15867.9, 15867.9, d_boot=31000.0, history=[336.7] * 3) == ["suspended"]

    def test_violation_is_frozen_and_names_the_leg(self):
        import dataclasses
        from canon_assert import LegClocks, check_clock_plausibility
        v = check_clock_plausibility("unit-branch", LegClocks(0.0, 0.0, 0.0),
                                     LegClocks(15867.9, 336.7, 336.7), [])
        assert len(v) == 1
        with pytest.raises(dataclasses.FrozenInstanceError):
            v[0].reason = "x"
        assert str(v[0]).startswith("unit-branch wall-jump: Δwall 15867.9s vs Δmonotonic 336.7s")

    def test_pure_no_io_no_clock_read(self, monkeypatch):
        import canon_assert
        src = Path(canon_assert.__file__).read_text()
        body = src.split("def check_clock_plausibility(")[1].split("\ndef ")[0].split("\n# ──")[0]
        for forbidden in ("time.", "open(", "Path(", "read_text", "write_text", "subprocess"):
            assert forbidden not in body, forbidden

    def test_log_line_says_the_outlier_clause_is_dormant(self, gate, caplog):
        gate.suite.script("branch", GREEN, 0, SECOND_FIRE)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = gate.run()
        assert v.outcome is orchestrator.GateOutcome.PASS
        lines = _shield(caplog)
        assert len(lines) == 1, lines
        assert lines[0].startswith("🛡 clock-plausibility: CLEAN — unit-branch")
        assert "outlier clause dormant (0 < 3 plausible samples)" in lines[0]


# ═══════════════════════════════════════════════════════
# AC-GC-04 · green stays green
# ═══════════════════════════════════════════════════════
class TestGreenStaysGreen:

    def test_unit_green_across_a_host_sleep_is_pass_and_says_implausible(self, gate, caplog):
        gate.suite.script("branch", GREEN, 0, FIRST_FIRE)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = gate.run()
        assert v.outcome is orchestrator.GateOutcome.PASS, v.label
        lines = _shield(caplog)
        assert len(lines) == 1, lines
        assert lines[0].startswith("🛡 clock-plausibility: IMPLAUSIBLE — unit-branch wall-jump")
        assert "green: stays green" in lines[0]
        assert gate.samples("unit-branch") == [], "an implausible leg is never history"

    def test_build_green_across_a_suspend_is_pass_and_says_implausible(self, gate, caplog):
        _gates("build")
        gate.suite.script("build", "built\n", 0, SUSPEND_ONLY)
        gate.suite.script("branch", GREEN, 0, SECOND_FIRE)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = gate.run()
        assert v.outcome is orchestrator.GateOutcome.PASS, v.label
        lines = _shield(caplog)
        assert [l.split(" — ")[0] for l in lines] == ["🛡 clock-plausibility: IMPLAUSIBLE",
                                                      "🛡 clock-plausibility: CLEAN"]
        assert "build suspended" in lines[0] and "green: stays green" in lines[0]


# ═══════════════════════════════════════════════════════
# AC-GC-06 · the history store
# ═══════════════════════════════════════════════════════
class TestHistory:

    def test_plausible_legs_are_recorded_per_repo_and_kind(self, gate):
        _gates("build")
        gate.suite.script("build", "built\n", 0, (68.5, 68.5, 68.5))
        gate.suite.script("branch", GREEN, 0, SECOND_FIRE)
        assert gate.run().outcome is orchestrator.GateOutcome.PASS
        assert gate.samples("build") == [68.5]
        assert gate.samples("unit-branch") == [336.7]
        assert gate.durations()["version"] == 1

    def test_an_implausible_red_leg_is_never_recorded(self, gate):
        gate.suite.script("branch", BRANCH_59, 1, FIRST_FIRE)
        gate.suite.script("baseline", BASE_59[4], 1, (338.8, 338.8, 338.8))
        gate.suite.script("confirm", CONFIRM_59, 1, (7.4, 7.4, 7.4))
        gate.run()
        assert gate.samples("unit-branch") == []
        assert gate.samples("unit-baseline") == [338.8]
        assert gate.samples("unit-confirm") == [7.4]

    def test_three_plausible_samples_wake_the_outlier_clause(self, gate):
        for _ in range(3):
            gate.suite.script("branch", GREEN, 0, SECOND_FIRE)
            assert gate.run().outcome is orchestrator.GateOutcome.PASS
        assert gate.samples("unit-branch") == [336.7] * 3
        # 1700 s on a sane clock, > 5 × 336.7 = 1683.5 — a red outlier is not a product verdict
        gate.suite.script("branch", BRANCH_59, 1, (1700.0, 1700.0, 1700.0))
        gate.suite.script("baseline", BASE_59[4], 1, (338.8, 338.8, 338.8))
        gate.suite.script("confirm", CONFIRM_59, 1, (7.4, 7.4, 7.4))
        v = gate.run()
        assert (v.outcome, v.signal) == (orchestrator.GateOutcome.BLOCKED_ENV, "clock-implausible"), v.label
        assert "unit-branch outlier-vs-history" in v.detail
        assert gate.samples("unit-branch") == [336.7] * 3

    def test_history_is_capped(self, gate):
        keep = orchestrator.GATE_DURATIONS_KEEP
        for i in range(keep + 2):
            gate.suite.script("branch", GREEN, 0, (300.0 + i, 300.0 + i, 300.0 + i))
            gate.run()
        assert gate.samples("unit-branch") == [300.0 + i for i in range(2, keep + 2)]

    def test_an_implausible_baseline_is_not_cached(self, gate):
        # BASELINE-TRUST-1: an implausible baseline leg is re-measured once; both implausible here
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[4], 1, FIRST_FIRE)
        gate.suite.script("baseline", BASE_59[4], 1, FIRST_FIRE)
        v = gate.run()
        assert (v.outcome, v.signal) == (orchestrator.GateOutcome.BLOCKED_ENV, "baseline-clock-implausible"), v.label
        assert "unit-baseline wall-jump" in v.detail
        cache = gate.archive / orchestrator.UNIT_BASELINE_CACHE_FILE
        entries = json.loads(cache.read_text())["entries"] if cache.exists() else {}
        assert entries == {}, "a baseline measured across a clock jump must be re-measured, not reused"

    def test_a_cached_baseline_is_not_a_leg(self, gate, caplog):
        fork = _git(gate.repo, "merge-base", "main", "route")
        run = orchestrator.UnitSuiteRun(ref=f"merge-base {fork[:7]}", exit_code=1, duration_s=338.8,
                                        **orchestrator._parse_unit_summary(BASE_59[4]))
        orchestrator._unit_cache_store(gate.archive, REPO, fork, TEST_CMD, run)
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("confirm", CONFIRM_59, 1, (7.4, 7.4, 7.4))
        with caplog.at_level(logging.INFO, logger="orch"):
            v = gate.run()
        assert (v.outcome, v.signal) == (orchestrator.GateOutcome.FAIL_PRODUCT, "regression")
        legs = [l.split(" — ")[1].split()[0] for l in _shield(caplog)]
        assert legs == ["unit-branch", "unit-confirm"]
        assert gate.samples("unit-baseline") == []

    def test_leg_clocks_reads_all_three(self, gate):
        c = orchestrator._leg_clocks()
        assert (c.wall, c.monotonic, c.boottime) == (gate.clock.wall, gate.clock.mono, gate.clock.boot)

    def test_leg_clocks_without_boottime_is_none(self, monkeypatch):
        monkeypatch.setattr(orchestrator, "time", Clock(boottime=False).module())
        assert orchestrator._leg_clocks().boottime is None

    def test_the_real_clock_is_linux_boottime(self):
        import time
        c = orchestrator._leg_clocks()
        assert c.boottime is not None and c.boottime >= c.monotonic - 1
        assert abs(c.wall - time.time()) < 5

# filename: tests/test_clockguard_1.py
"""ORCH-CLOCKGUARD-1 (S7-CORE-31, SCA-ORCH-CLOCKGUARD-1) — the clock guard stops calling a slow leg on a sound clock
"implausible", and never voids a red the isolation leg confirmed.

Route 282c's gate, 2026-10-17 16:42:25 (logs/clinical-mp/orch-282c-small-fixes-13-20261017-152033.log):
`🔬 SIT gate isolation — 1 file(s) in 70.1s; … confirmed: sit/integration/action-targets.integration.test.tsx`, then
`🛡 clock-plausibility: IMPLAUSIBLE — sit-isolation outlier-vs-history: Δwall 70.1s > 5 × median 7.7s of its history;
Δboottime 70.7s; outlier clause against the median of 4 plausible samples`, and the verdict BLOCKED(environment) —
sit: clock-implausible over a real product red. Clauses 1 and 2 were clean (Δwall 70.1 ≈ Δmonotonic ≈ Δboottime
70.7). The 4 samples were 1-file sit-isolation legs: 1.81, 12.85, 11.45 and 3.87 s (median 7.66).

  P1 (K1)  Δwall 70.1, Δmonotonic 70.1, Δboottime 70.7 against that history ⇒ no violation, one `SLOW` line, the
           sample recorded. Controls: a boottime missing ⇒ outlier-vs-history as today (the 5.0× / 5.01× bound);
           Δwall − Δmonotonic over 60 s ⇒ wall-jump as today; a suspend ⇒ suspended as today.
  P2 (K2)  the 282c shape — a file confirmed failing alone — ⇒ FAIL(product) naming it, whatever a clock clause says
           about any leg; a violation on the isolation leg itself adds "measured on an implausible clock — re-run
           before believing". Controls: the file passes alone ⇒ PASS batch-contamination (not FAIL(product));
           no isolation ⇒ an implausible red is BLOCKED clock-implausible as today.
  P3 (K3)  the history is keyed by leg kind and file-count bucket (1, 2-10, 11+): a 1-file leg reads 1-file samples
           only; a sample stored without a bucket reads as its leg kind's; no stored sample is rewritten.
  P4       the baseline: a slow baseline on agreeing measured clocks is trusted (not re-measured, cached); a boottime
           missing and the same outlier ⇒ baseline-clock-implausible as today.

Harnesses: the REAL run_pre_merge_gates → run_sit_post_merge → _run_sit_batched / _sit_isolate → _judge_leg with
only the SIT commands and the three clocks scripted (TestP2EndToEnd), and test_gate_clock's REAL unit gate in a real
git repo (TestP4). Module-level imports are existing symbols only, so this file collects on HEAD for the RED run.
"""
import json
import logging
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import canon_assert  # noqa: E402
import orchestrator  # noqa: E402
from canon_assert import ClockViolation, LegClocks, check_clock_plausibility  # noqa: E402
from tests.test_gate_clock import (BASE_59, BRANCH_59, CONFIRM_59, NEW_A, NEW_B, REPO, SECOND_FIRE,  # noqa: E402,F401
                                   Clock, gate, vitest)

PASS, BLOCKED, PRODUCT = (orchestrator.GateOutcome.PASS, orchestrator.GateOutcome.BLOCKED_ENV,
                          orchestrator.GateOutcome.FAIL_PRODUCT)

F_282C = "sit/integration/action-targets.integration.test.tsx"
F_OTHER = "sit/integration/home-up-next.integration.test.tsx"
HISTORY_282C = [1.81, 12.85, 11.45, 3.87]          # the 4 plausible sit-isolation samples 282c was judged against
SLOW_282C = "sit-isolation Δwall 70.1s > 5 × median 7.7s; clocks agree"


def _legs(d_wall, d_mono, d_boot, start=(1_790_000_000.0, 40_000.0, 40_050.0)):
    """(start, end) LegClocks for one leg; d_boot None ⇒ no CLOCK_BOOTTIME at either end."""
    w0, m0, b0 = start
    return (LegClocks(w0, m0, None if d_boot is None else b0),
            LegClocks(w0 + d_wall, m0 + d_mono, None if d_boot is None else b0 + d_boot))


def _reasons(d_wall, d_mono, d_boot, history):
    return [v.reason for v in check_clock_plausibility("sit-isolation", *_legs(d_wall, d_mono, d_boot), history)]


def _slow_note(*a):
    return getattr(canon_assert, "clock_slow_note")(*a)   # ORCH-CLOCKGUARD-1's; absent on HEAD


def _shield(caplog, control="clock-plausibility") -> list:
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith(f"🛡 {control}:")]


def _store(archive: Path, repo: str, kinds: dict):
    archive.mkdir(parents=True, exist_ok=True)
    (archive / orchestrator.GATE_DURATIONS_FILE).write_text(json.dumps(
        {"version": orchestrator.GATE_DURATIONS_VERSION, "repos": {repo: kinds}}, indent=2))


def _stored(archive: Path, repo: str, kind: str) -> list:
    f = archive / orchestrator.GATE_DURATIONS_FILE
    return json.loads(f.read_text())["repos"][repo].get(kind, []) if f.exists() else []


def _samples(walls, files=None):
    """Stored samples as _gate_durations_record writes them; files None ⇒ the pre-K3 shape (no bucket)."""
    out = [{"at": f"2026-10-1{i % 10}T00:00:00", "d_wall": w, "d_monotonic": w} for i, w in enumerate(walls)]
    if files is not None:
        for s in out:
            s["files"] = files
    return out


# ═══════════════════════════════════════════════════════
# P1 (K1) · clause 3 is a note when the clock is measured
# ═══════════════════════════════════════════════════════
class TestP1SlowOnAMeasuredClock:

    def test_P1_the_282c_clocks_are_no_violation(self):
        assert _reasons(70.1, 70.1, 70.7, HISTORY_282C) == []

    def test_P1_the_282c_clocks_are_a_slow_note(self):
        assert _slow_note("sit-isolation", *_legs(70.1, 70.1, 70.7), HISTORY_282C) == SLOW_282C

    def test_P1_the_leg_says_SLOW_once_returns_plausible_and_is_recorded(self, tmp_path, monkeypatch, caplog):
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "cg-repo")
        _store(tmp_path, "cg-repo", {"sit-isolation": _samples(HISTORY_282C)})
        with caplog.at_level(logging.INFO, logger="orch"):
            v = orchestrator._judge_leg("sit-isolation", _legs(70.1, 70.1, 70.7), tmp_path, red=True)
        assert v is None
        lines = _shield(caplog)
        assert len(lines) == 1, lines
        assert lines[0].startswith(f"🛡 clock-plausibility: SLOW — {SLOW_282C}"), lines[0]
        assert "Δboottime 70.7s" in lines[0] and "the verdict is what the leg measured" in lines[0]
        assert [s["d_wall"] for s in _stored(tmp_path, "cg-repo", "sit-isolation")] == HISTORY_282C + [70.1]

    def test_P1_a_fast_leg_or_a_dormant_history_is_no_note(self):
        assert _slow_note("sit-isolation", *_legs(38.0, 38.0, 38.0), HISTORY_282C) is None   # 38.0 ≤ 5 × 7.66
        assert _slow_note("sit-isolation", *_legs(70.1, 70.1, 70.7), HISTORY_282C[:2]) is None

    def test_P1_the_5x_bound_on_a_measured_clock_is_a_note_either_side(self):
        h = [100.0, 100.0, 100.0]
        assert _reasons(500.0, 500.0, 500.0, h) == [] and _slow_note("leg", *_legs(500.0, 500.0, 500.0), h) is None
        assert _reasons(501.0, 501.0, 501.0, h) == []
        assert _slow_note("leg", *_legs(501.0, 501.0, 501.0), h) == "leg Δwall 501.0s > 5 × median 100.0s; clocks agree"

    def test_P1_control_a_boottime_missing_is_outlier_vs_history_as_today(self, tmp_path, monkeypatch, caplog):
        assert _reasons(70.1, 70.1, None, HISTORY_282C) == ["outlier-vs-history"]
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "cg-repo")
        _store(tmp_path, "cg-repo", {"sit-isolation": _samples(HISTORY_282C)})
        with caplog.at_level(logging.INFO, logger="orch"):
            v = orchestrator._judge_leg("sit-isolation", _legs(70.1, 70.1, None), tmp_path, red=True)
        assert v.reason == "outlier-vs-history" and round(v.median, 2) == 7.66
        assert [l.split(" — ")[0] for l in _shield(caplog)] == ["🛡 clock-plausibility: IMPLAUSIBLE"]
        assert [s["d_wall"] for s in _stored(tmp_path, "cg-repo", "sit-isolation")] == HISTORY_282C, "never recorded"

    def test_P1_control_the_5x_bound_with_a_boottime_missing_as_today(self):
        h = [100.0, 100.0, 100.0]
        assert _reasons(500.0, 500.0, None, h) == []
        assert _reasons(501.0, 501.0, None, h) == ["outlier-vs-history"]
        assert _reasons(501.0, 501.0, None, [100.0, 100.0, 100_000.0]) == ["outlier-vs-history"]   # the median

    def test_P1_control_a_wall_jump_is_a_wall_jump_as_today(self):
        # Δwall − Δmonotonic 70.1 s > CLOCK_WALL_JUMP_S 60, both boottimes known; clause 1 is checked first
        assert _reasons(140.2, 70.1, 70.7, HISTORY_282C) == ["wall-jump"]
        # the brief's 30 s is inside the 60 s bound: no wall-jump, at HEAD as now
        assert _reasons(100.0, 70.0, 70.0, ()) == []

    def test_P1_control_a_suspend_is_suspended_as_today(self):
        assert _reasons(70.1, 70.1, 200.0, HISTORY_282C) == ["suspended"]

    def test_P1_an_implausible_or_unmeasured_clock_is_never_a_note(self):
        # the violation speaks for those legs (the controls above); SLOW is only for agreeing measured clocks
        for clocks in (_legs(70.1, 70.1, None), _legs(140.2, 70.1, 70.7), _legs(70.1, 70.1, 200.0)):
            assert _slow_note("sit-isolation", *clocks, HISTORY_282C) is None

    def test_P1_the_constants_are_unchanged(self):
        assert (canon_assert.CLOCK_WALL_JUMP_S, canon_assert.CLOCK_SUSPEND_S, canon_assert.CLOCK_OUTLIER_FACTOR,
                canon_assert.CLOCK_HISTORY_MIN) == (60.0, 60.0, 5.0, 3)

    def test_P1_the_note_is_pure(self):
        src = Path(canon_assert.__file__).read_text()
        assert "def clock_slow_note(" in src
        body = src.split("def clock_slow_note(")[1].split("\ndef ")[0].split("\n# ──")[0]
        for forbidden in ("time.", "open(", "Path(", "read_text", "write_text", "subprocess"):
            assert forbidden not in body, forbidden


# ═══════════════════════════════════════════════════════
# P2 (K2) · a confirmed red is never voided — the classifier
# ═══════════════════════════════════════════════════════
def _cv(leg, reason, d_wall=70.1, d_mono=70.1, d_boot=70.7, median=None):
    return ClockViolation(leg_kind=leg, reason=reason, d_wall=d_wall, d_monotonic=d_mono, d_boottime=d_boot,
                          median=median)


OUTLIER_282C = _cv("sit-isolation", "outlier-vs-history", median=7.66)    # what HEAD's guard returned
ISO_SUSPENDED = _cv("sit-isolation", "suspended", d_boot=200.0)
ISO_WALL_JUMP = _cv("sit-isolation", "wall-jump", d_wall=140.2)
BATCH_WALL_JUMP = _cv("sit-batch", "wall-jump", d_wall=15867.9, d_mono=336.7, d_boot=336.7)
NOTE = "measured on an implausible clock — re-run before believing"
SIT_RED_OUT = vitest(2, {F_282C: 1}, 6, expected_fail=0, skipped=0, todo=0)


def _iso(confirmed=(), contaminated=(), clock=None):
    files = tuple(confirmed) + tuple(contaminated)
    return orchestrator.SitIsolation(confirmed=tuple(confirmed), contaminated=tuple(contaminated),
                                     batch_of={f: 1 for f in files}, neighbours={f: (F_OTHER,) for f in files},
                                     batches=1, alone={f: "2/3" for f in files}, clock=clock)


def _classify(iso, clock):
    return orchestrator._classify_gate_failure("sit", SIT_RED_OUT, Path("/tmp/repo"), 1, tests_failed=1,
                                               files_failed=1, isolation=iso, clock=clock)


class TestP2ConfirmedRedIsProduct:

    @pytest.mark.parametrize("gate_clock, iso_clock, noted", [
        (None, None, False),
        (OUTLIER_282C, OUTLIER_282C, True),        # the 282c state as HEAD's guard judged it
        (BATCH_WALL_JUMP, None, False),            # another leg's clause 1
        (ISO_SUSPENDED, ISO_SUSPENDED, True),      # the isolation leg's own clause 2
        (ISO_WALL_JUMP, ISO_WALL_JUMP, True),      # the isolation leg's own clause 1
        (BATCH_WALL_JUMP, ISO_SUSPENDED, True),
    ], ids=["plausible", "282c-head-outlier", "batch-wall-jump", "iso-suspended", "iso-wall-jump", "both"])
    def test_P2_a_file_confirmed_failing_alone_is_fail_product_naming_it(self, gate_clock, iso_clock, noted):
        v = _classify(_iso(confirmed=(F_282C,), clock=iso_clock), gate_clock)
        assert (v.outcome, v.gate) == (PRODUCT, "sit"), v.label
        assert f"confirmed failing alone: {F_282C}" in v.detail
        assert (NOTE in v.detail) is noted, v.detail
        if iso_clock is not None:
            assert str(iso_clock) in v.detail

    def test_P2_a_confirmed_file_beside_a_contaminated_one_is_product(self):
        v = _classify(_iso(confirmed=(F_282C,), contaminated=(F_OTHER,), clock=ISO_SUSPENDED), ISO_SUSPENDED)
        assert v.outcome is PRODUCT and F_282C in v.detail and F_OTHER in v.detail and NOTE in v.detail

    @pytest.mark.parametrize("gate_clock", [None, BATCH_WALL_JUMP, ISO_SUSPENDED], ids=["plausible", "batch", "iso"])
    def test_P2_control_a_file_that_passes_alone_is_not_fail_product(self, gate_clock):
        v = _classify(_iso(contaminated=(F_282C,), clock=gate_clock if gate_clock is ISO_SUSPENDED else None),
                      gate_clock)
        assert (v.outcome, v.signal) == (PASS, "batch-contamination"), v.label

    def test_P2_control_no_isolation_an_implausible_red_is_blocked_as_today(self):
        v = _classify(None, BATCH_WALL_JUMP)
        assert (v.outcome, v.signal) == (BLOCKED, "clock-implausible"), v.label

    def test_P2_control_an_unmeasurable_isolation_is_blocked_as_today(self):
        iso = _iso(clock=ISO_SUSPENDED)
        iso.error, iso.detail = "isolation-unmeasurable", f"{F_282C} could not be measured alone (timeout)"
        v = _classify(iso, ISO_SUSPENDED)
        assert (v.outcome, v.signal) == (BLOCKED, "isolation-unmeasurable"), v.label


# ═══════════════════════════════════════════════════════
# P2 / P3 end to end · route 282c's SIT leg, replayed
# ═══════════════════════════════════════════════════════
SIT_REPO = "cg-sit-repo"
SIT_CMD = "npm run sit:gate"
LIST_CMD = "npx vitest list --config sit.config.ts"
LIST_OUT = "".join(f"{f} > case {j}\n" for f in (F_282C, F_OTHER) for j in (1, 2, 3))   # 2 files / 6 tests
ALONE_RED = vitest(1, {F_282C: 1}, 3, expected_fail=0, skipped=0, todo=0)
ALONE_GREEN = vitest(1, {}, 3, expected_fail=0, skipped=0, todo=0)


class Sit:
    """subprocess.run for the SIT gate: the list command, then one batch of both files, then each failing file alone.
    Each scripted leg advances the clock by its (Δwall, Δmonotonic, Δboottime); every other command runs for real."""

    def __init__(self, clock: Clock, batch=(10.0, 10.0, 10.0), alone=(70.1, 70.1, 70.7), alone_red=True):
        self.clock, self.batch, self.alone, self.alone_red = clock, batch, alone, alone_red
        self.calls = []
        self._real = subprocess.run

    def __call__(self, cmd, *a, **k):
        if not (isinstance(cmd, str) and (cmd.startswith(SIT_CMD) or cmd.startswith(LIST_CMD))):
            return self._real(cmd, *a, **k)
        if cmd.startswith(LIST_CMD):
            return subprocess.CompletedProcess(cmd, 0, stdout=LIST_OUT, stderr="")
        files = cmd.split(" -- ", 1)[1].split()
        self.calls.append(files)
        if len(files) > 1:
            self.clock.advance(*self.batch)
            return subprocess.CompletedProcess(cmd, 1, stdout=SIT_RED_OUT, stderr="")
        self.clock.advance(*self.alone)
        return subprocess.CompletedProcess(cmd, 1 if self.alone_red else 0,
                                           stdout=ALONE_RED if self.alone_red else ALONE_GREEN, stderr="")


@pytest.fixture
def sit(tmp_path, monkeypatch):
    archive = tmp_path / "archive"
    repo = tmp_path / "repo"
    repo.mkdir()
    clock = Clock()
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", SIT_REPO)
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG",
                        {"sit_list_cmd": LIST_CMD, "sit_batch_files": 10, "sit_batch_pause_s": 0})
    monkeypatch.setattr(orchestrator, "SKIP_SIT", False)
    monkeypatch.setattr(orchestrator, "SIT_BLOCKING", True)
    monkeypatch.setattr(orchestrator, "SIT_ARCHIVE_DIR", archive)
    monkeypatch.setitem(orchestrator.PRE_MERGE_GATES, SIT_REPO, {"gates": ("sit",), "env_file": None})
    monkeypatch.setattr(orchestrator, "time", clock.module())
    _store(archive, SIT_REPO, {"sit-isolation": _samples(HISTORY_282C)})

    def run(**kw):
        fake = Sit(clock, **kw)
        monkeypatch.setattr(orchestrator.subprocess, "run", fake)
        return orchestrator.run_pre_merge_gates(repo, "route"), fake
    run.archive, run.clock = archive, clock
    return run


class TestP2EndToEnd:

    def test_P2_282c_replayed_is_fail_product_naming_the_file(self, sit, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            v, fake = sit()
        assert fake.calls == [[F_282C, F_OTHER], [F_282C]], "the batch, then the failing file alone"
        assert (v.outcome, v.gate) == (PRODUCT, "sit"), v.label
        assert f"confirmed failing alone: {F_282C}" in v.detail and NOTE not in v.detail
        iso = [l for l in _shield(caplog) if " — sit-isolation " in l]
        assert len(iso) == 1 and iso[0].startswith(f"🛡 clock-plausibility: SLOW — {SLOW_282C}"), iso
        assert not [r for r in caplog.records if "GATE-SIT-2 invariant" in r.getMessage()]

    def test_P2_the_isolation_leg_suspended_is_still_fail_product_with_the_note(self, sit):
        v, _ = sit(alone=(70.1, 70.1, 200.0))
        assert (v.outcome, v.gate) == (PRODUCT, "sit"), v.label
        assert F_282C in v.detail and NOTE in v.detail and "sit-isolation suspended" in v.detail

    def test_P2_a_batch_leg_across_a_host_sleep_does_not_void_the_confirmed_file(self, sit):
        v, _ = sit(batch=(15867.9, 336.7, 336.7))
        assert (v.outcome, v.gate) == (PRODUCT, "sit"), v.label
        assert F_282C in v.detail and NOTE not in v.detail

    @pytest.mark.parametrize("batch", [(10.0, 10.0, 10.0), (15867.9, 336.7, 336.7)], ids=["plausible", "host-sleep"])
    def test_P2_control_the_file_passes_alone_is_contamination_not_product(self, sit, caplog, batch):
        with caplog.at_level(logging.INFO, logger="orch"):
            v, _ = sit(batch=batch, alone=(4.0, 4.0, 4.0), alone_red=False)
        assert v.outcome is PASS, v.label     # the SIT leg is green after isolation; this repo has no unit gate
        assert any("SIT green after isolation" in r.getMessage() and "batch-contamination" in r.getMessage()
                   for r in caplog.records)

    def test_P3_the_replay_records_each_leg_in_its_bucket_and_keeps_the_old_samples(self, sit):
        sit()
        iso = _stored(sit.archive, SIT_REPO, "sit-isolation")
        assert iso[:4] == _samples(HISTORY_282C), "the stored samples are not rewritten"
        assert (iso[4]["d_wall"], iso[4].get("files")) == (70.1, "1")
        assert [(s["d_wall"], s.get("files")) for s in _stored(sit.archive, SIT_REPO, "sit-batch")] == [(10.0, "2-10")]


# ═══════════════════════════════════════════════════════
# P3 (K3) · the history is keyed by what it measures
# ═══════════════════════════════════════════════════════
class TestP3HistoryByBucket:

    @pytest.fixture(autouse=True)
    def _repo(self, monkeypatch):
        monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "cg-repo")

    def test_P3_the_buckets(self):
        b = orchestrator._gate_files_bucket
        assert [b(n) for n in (1, 2, 10, 11, 500)] == ["1", "2-10", "2-10", "11+", "11+"]
        assert b(None) is None

    def test_P3_a_one_file_leg_reads_one_file_history_only(self, tmp_path):
        _store(tmp_path, "cg-repo", {"sit-isolation": _samples([4.0] * 3, "1") + _samples([100.0] * 3, "2-10")})
        h = orchestrator._gate_durations_history
        assert h(tmp_path, "sit-isolation", 1) == [4.0] * 3
        assert h(tmp_path, "sit-isolation", 5) == [100.0] * 3
        assert h(tmp_path, "sit-isolation", 11) == []
        # judged on a clock without boottime, where clause 3 is still a violation: 30 s > 5 × 4 s, not > 5 × 100 s
        one = orchestrator._judge_leg("sit-isolation", _legs(30.0, 30.0, None), tmp_path, red=True, files=1)
        five = orchestrator._judge_leg("sit-isolation", _legs(30.0, 30.0, None), tmp_path, red=True, files=5)
        assert (one.reason, one.median, five) == ("outlier-vs-history", 4.0, None)

    def test_P3_an_entry_without_a_bucket_reads_as_its_leg_kinds(self, tmp_path):
        old = _samples([5.0] * 3)
        _store(tmp_path, "cg-repo", {"sit-isolation": old + _samples([100.0] * 3, "2-10")})
        h = orchestrator._gate_durations_history
        assert h(tmp_path, "sit-isolation", 1) == [5.0] * 3
        assert h(tmp_path, "sit-isolation", 5) == [5.0] * 3 + [100.0] * 3
        assert h(tmp_path, "sit-isolation") == [5.0] * 3 + [100.0] * 3, "a leg with no file count reads its whole kind"
        assert orchestrator._judge_leg("sit-isolation", _legs(6.0, 6.0, 6.0), tmp_path, red=False, files=1) is None
        stored = _stored(tmp_path, "cg-repo", "sit-isolation")
        assert stored[:3] == old, "a stored sample is never rewritten"
        assert (stored[-1]["d_wall"], stored[-1]["files"]) == (6.0, "1")

    def test_P3_a_leg_without_a_file_count_is_stored_without_a_bucket(self, tmp_path):
        assert orchestrator._judge_leg("build", _legs(68.5, 68.5, 68.5), tmp_path, red=False) is None
        assert "files" not in _stored(tmp_path, "cg-repo", "build")[0]

    def test_P3_the_cap_is_per_bucket_and_an_old_sample_ages_out(self, tmp_path):
        keep = orchestrator.GATE_DURATIONS_KEEP
        _store(tmp_path, "cg-repo", {"sit-isolation": _samples([5.0] * 2) + _samples([100.0] * 3, "2-10")})
        for i in range(keep + 1):
            orchestrator._gate_durations_record(tmp_path, "sit-isolation", 1.0 + i, 1.0 + i, files=1)
        stored = _stored(tmp_path, "cg-repo", "sit-isolation")
        assert [s["d_wall"] for s in stored if s.get("files") == "2-10"] == [100.0] * 3, "another bucket is kept"
        assert not [s for s in stored if "files" not in s], "the unbucketed samples aged out as the 1-file bucket filled"
        newest = [1.0 + i for i in range(1, keep + 1)]
        assert [s["d_wall"] for s in stored if s.get("files") == "1"] == newest
        assert orchestrator._gate_durations_history(tmp_path, "sit-isolation", 1) == newest

    def test_P3_control_a_leg_with_no_file_count_is_capped_as_before(self, tmp_path):
        keep = orchestrator.GATE_DURATIONS_KEEP
        for i in range(keep + 2):
            orchestrator._gate_durations_record(tmp_path, "unit-branch", 300.0 + i, 300.0 + i)
        stored = _stored(tmp_path, "cg-repo", "unit-branch")
        assert [s["d_wall"] for s in stored] == [300.0 + i for i in range(2, keep + 2)]
        assert not [s for s in stored if "files" in s]


# ═══════════════════════════════════════════════════════
# P4 · the baseline path
# ═══════════════════════════════════════════════════════
SLOW_BASE = (1700.0, 1700.0, 1700.0)    # > 5 × 338.8 = 1694, on three agreeing clocks


def _trust(caplog) -> list:
    return _shield(caplog, "baseline-trust")


def _cached(gate) -> dict:
    f = gate.archive / orchestrator.UNIT_BASELINE_CACHE_FILE
    return json.loads(f.read_text())["entries"] if f.exists() else {}


class TestP4Baseline:

    def _script(self, gate):
        _store(gate.archive, REPO, {"unit-baseline": _samples([338.8] * 3)})
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[4], 1, SLOW_BASE)
        gate.suite.script("baseline", BASE_59[4], 1, SLOW_BASE)    # consumed only if the first leg is discarded
        gate.suite.script("confirm", CONFIRM_59, 1, (7.4, 7.4, 7.4))

    def test_P4_a_slow_baseline_on_an_agreeing_measured_clock_is_trusted(self, gate, caplog):
        self._script(gate)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = gate.run()
        assert (v.outcome, v.gate, v.signal) == (PRODUCT, "unit", "regression"), v.label
        assert f"newly-failing file(s): {NEW_A}, {NEW_B}" in v.detail
        assert gate.suite.calls == ["branch", "baseline", "confirm"], "measured once, not re-measured"
        trust = _trust(caplog)
        assert len(trust) == 1 and trust[0].startswith("🛡 baseline-trust: CLEAN — unit-baseline at "), trust
        assert "measured on a plausible clock" in trust[0]
        assert any(l.startswith("🛡 clock-plausibility: SLOW — unit-baseline Δwall 1700.0s > 5 × median 338.8s")
                   for l in _shield(caplog))
        assert [e["clock"] for e in _cached(gate).values()] == ["plausible"], "a trusted baseline is cached"
        # K3: the confirmation re-ran 2 files; the whole-suite legs carry no bucket
        assert [s.get("files") for s in _stored(gate.archive, REPO, "unit-confirm")] == ["2-10"]
        assert "files" not in _stored(gate.archive, REPO, "unit-branch")[-1]
        assert "files" not in _stored(gate.archive, REPO, "unit-baseline")[-1]

    def test_P4_control_a_boottime_missing_and_the_same_outlier_is_baseline_clock_implausible(self, gate, caplog):
        self._script(gate)
        gate.clock.boottime = False
        with caplog.at_level(logging.INFO, logger="orch"):
            v = gate.run()
        assert (v.outcome, v.gate, v.signal) == (BLOCKED, "unit", "baseline-clock-implausible"), v.label
        assert "unit-baseline outlier-vs-history" in v.detail
        assert gate.suite.calls == ["branch", "baseline", "baseline"]
        assert _trust(caplog)[0].startswith("🛡 baseline-trust: BLOCKED — baseline-clock-implausible: ")
        assert _cached(gate) == {}

# filename: test_sit_rate_limit.py
"""S7-CORE-10 — [ORCH-11] verdict semantics + SIT-RATE-1 batched SIT gate.

2026-09-15: one SIT gate run (19 files) no longer fits Medplum's 50 000-point rate-limit
window; the harness login got HTTP 429 in 3 files, every executed assertion passed, and the
F-20 detector returned FAIL(product) — the second false FAIL(product) that night.
"""
import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
import orchestrator  # noqa: E402

FIXTURE_429 = (Path(__file__).parent / "fixtures" / "sit_gate_vitest_429_19files_3down.txt").read_text()
REPO = Path("/tmp/repo")
ENV = orchestrator.GateOutcome.BLOCKED_ENV
PRODUCT = orchestrator.GateOutcome.FAIL_PRODUCT


def _classify(text, **kw):
    return orchestrator._classify_gate_failure("sit", text, REPO, 1, **kw)


def _verdict_for(outcome):
    """run_pre_merge_gates over a SIT-only policy with the SitOutcome injected."""
    with patch.dict(orchestrator.PRE_MERGE_GATES, {orchestrator.ACTIVE_REPO_NAME: {"gates": ["sit"]}}), \
         patch.object(orchestrator, "run_sit_post_merge", return_value=outcome), \
         patch.object(orchestrator, "SIT_BLOCKING", True):
        return orchestrator.run_pre_merge_gates(REPO, "route-branch")


# ═══════════════════════════════════════════════════════
# AC-SR-01 — rule 1: zero failed assertions is never FAIL(product)
# ═══════════════════════════════════════════════════════
class TestNoFailedAssertions:

    RED_NO_SIGNAL = (" FAIL  sit/integration/a.integration.test.ts [ sit/integration/a.integration.test.ts ]\n"
                     "Error: Encounter PUT failed: unknown\n"
                     " Test Files  1 failed | 14 passed (15)\n      Tests  45 passed | 1 skipped (46)\n")

    def test_zero_failed_with_files_down_is_environment(self, caplog):
        """The RM-I-028 shape: no transport text at all, one file down at setup, 0 failed assertions."""
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _classify(self.RED_NO_SIGNAL, tests_failed=0, files_failed=1)
        assert v.outcome is ENV and v.outcome is not PRODUCT
        assert v.signal == "no-failed-assertions"
        assert "0 failed assertions and 1 file(s) down at setup" in v.detail
        assert "signal 'no-failed-assertions' matched" in caplog.text

    def test_names_the_files_down(self):
        v = _classify(self.RED_NO_SIGNAL, tests_failed=0, files_failed=1)
        assert "sit/integration/a.integration.test.ts" in v.detail

    def test_one_failed_assertion_stays_product(self):
        """The guard must not swallow a real failure: a single failed assertion is product."""
        v = _classify(self.RED_NO_SIGNAL, tests_failed=1, files_failed=1)
        assert v.outcome is PRODUCT
        assert "(1 failed assertions)" in v.detail

    def test_unknown_failed_is_not_zero(self):
        """§2.4: None is UNKNOWN. It never earns the environment verdict."""
        v = _classify(self.RED_NO_SIGNAL)
        assert v.outcome is PRODUCT
        assert v.detail == "no F-20 environment signal in gate output — product verdict stands"

    def test_tests_failed_is_read_from_the_summary_line(self):
        """`51 passed | 9 skipped (60)` states no failures and reconciles ⇒ 0; a line that does
        not reconcile, or with no total, is None."""
        f = orchestrator._sit_tests_failed
        assert f({"tests_total": 60, "tests_passed": 51}, {"failed": None, "skipped": 9, "todo": None}) == 0
        assert f({"tests_total": 60, "tests_passed": 57}, {"failed": 3, "skipped": None, "todo": None}) == 3
        assert f({"tests_total": 60, "tests_passed": 51}, {"failed": None, "skipped": None, "todo": None}) is None
        assert f({"tests_total": None, "tests_passed": None}, {"failed": None, "skipped": None, "todo": None}) is None


# ═══════════════════════════════════════════════════════
# AC-SR-02 — rule 2: transport-level refusals are environment, and the log names the signal
# ═══════════════════════════════════════════════════════
class TestTransportSignals:

    @pytest.mark.parametrize("text,signal", [
        ("OperationOutcomeError: Too Many Requests ({\"_consumedPoints\":50090,\"limit\":50000})", "rate-limited"),
        ("Error: HTTP 429 from http://localhost:8103/fhir/R4/Practitioner", "rate-limited"),
        ("request failed with status 429", "rate-limited"),
        ("statusCode: 429", "rate-limited"),
        ("Error: connect ECONNREFUSED 10.0.0.5:443", "connection-refused"),
        ("read ECONNRESET", "connection-refused"),
        ("OperationOutcomeError: Service Unavailable", "client-operation-outcome"),
        ("\x1b[31m\x1b[1mOperationOutcomeError\x1b[22m: Gateway Timeout\x1b[39m", "client-operation-outcome"),
    ])
    def test_transport_refusal_is_environment(self, text, signal, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _classify(f"some output\n{text}\nmore output\n", tests_failed=3, files_failed=2)
        assert v.outcome is ENV, text
        assert v.signal == signal
        assert f"signal '{signal}' matched" in caplog.text
        assert "matched '" in v.detail

    def test_medplum_8103_refusal_keeps_its_specific_signal(self):
        v = _classify("connect ECONNREFUSED 127.0.0.1:8103")
        assert (v.outcome, v.signal) == (ENV, "medplum-unreachable")

    @pytest.mark.parametrize("text", [
        " ❯ SitIntegrationHarness.login sit/integration/medplum-harness.ts:429:5",
        "      Tests  429 passed (429)",
        "AssertionError: expected 'obs-429' to be 'obs-430'",
    ])
    def test_a_bare_429_is_not_a_rate_limit(self, text):
        """A line number, a tally or an id containing 429 must not turn a product failure into environment."""
        v = _classify(f"{text}\n", tests_failed=2, files_failed=1)
        assert v.outcome is PRODUCT, text

    def test_client_400_for_a_bad_resource_stays_product(self):
        """An OperationOutcomeError the PRODUCT earned (400 for a resource it built wrong) is not transport."""
        v = _classify("OperationOutcomeError: Bad Request (Invalid resource: Encounter.status)\n",
                      tests_failed=1, files_failed=1)
        assert v.outcome is PRODUCT


# ═══════════════════════════════════════════════════════
# AC-SR-03 — tonight's actual gate output: FAIL(product) on 76887c0, BLOCKED(environment) after
# ═══════════════════════════════════════════════════════
class TestTonightsGateOutput:

    def _run_gate(self, stdout):
        with patch("subprocess.run") as mock_run, patch.dict(orchestrator.ACTIVE_REPO_CONFIG, {}, clear=True):
            mock_run.return_value = MagicMock(returncode=1, stdout=stdout, stderr="")
            with tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / "archive"; archive.mkdir()
                orchestrator.SKIP_SIT = False
                outcome = orchestrator.run_sit_post_merge(Path(tmp), archive)
                entries = json.loads((archive / "orchestrator-sit-log.json").read_text())
            assert mock_run.call_count == 1, "a red gate is never re-run"
        return outcome, entries

    def test_fixture_is_tonights_shape(self):
        c = orchestrator._parse_vitest_summary(FIXTURE_429)
        assert (c["test_files_total"], c["test_files_passed"], c["tests_total"], c["tests_passed"]) == (19, 16, 60, 51)
        assert "_consumedPoints\":50090" in FIXTURE_429 and "limit\":50000" in FIXTURE_429

    def test_tonights_output_is_not_fail_product(self, caplog):
        """The AC-SR-03 guard, written against the pre-[ORCH-11] API only, so it RUNS on 76887c0
        and fails there with the message below. On this branch it passes."""
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, _ = self._run_gate(FIXTURE_429)
            assert outcome.passed is False
            v = _verdict_for(outcome)
        assert v.outcome is not PRODUCT, f"76887c0 returned FAIL(product) here: {v.label}"
        assert v.outcome is ENV
        assert (v.gate, v.signal) == ("sit", "rate-limited")
        assert "signal 'rate-limited' matched" in caplog.text
        assert "product verdict stands" not in caplog.text

    def test_tonights_output_tallies_and_log_entry(self):
        outcome, entries = self._run_gate(FIXTURE_429)
        assert (outcome.tests_failed, outcome.files_failed, outcome.tests_skipped) == (0, 3, 9)
        assert entries[-1]["tests_failed"] == 0 and entries[-1]["batches"] is None
        assert _verdict_for(outcome).collection == "19 files/60 tests, " + f"{outcome.duration_s:.1f}s"

    def test_rule_1_alone_catches_the_same_run(self, caplog):
        """Strip every transport line: the summary alone (0 failed, 3 files down) still decides it."""
        stripped = "\n".join(l for l in FIXTURE_429.splitlines()
                             if "OperationOutcomeError" not in l and "Too Many" not in l
                             and not l.startswith("#"))
        assert "429" not in stripped.replace("Duration", "")
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, _ = self._run_gate(stripped)
            v = _verdict_for(outcome)
        assert (v.outcome, v.signal) == (ENV, "no-failed-assertions")
        assert "3 file(s) down at setup: sit/integration/longevity-trajectory.integration.test.ts" in v.detail


# ═══════════════════════════════════════════════════════
# AC-SR-04 / AC-SR-05 — SIT-RATE-1: batches sized by configuration; totals must sum to the suite
# ═══════════════════════════════════════════════════════
FILES = [f"sit/integration/f{i}.integration.test.ts" for i in range(1, 6)]
LIST_OUT = "\n".join(f"{f} > case {j}" for f in FILES for j in (1, 2)) + "\n"   # 5 files / 10 tests


def _batch_summary(n_files, n_tests, failed=0, extra=""):
    ft = f"{n_files} passed ({n_files})" if not failed else f"1 failed | {n_files - 1} passed ({n_files})"
    tt = f"{n_tests} passed ({n_tests})" if not failed else f"{failed} failed | {n_tests - failed} passed ({n_tests})"
    return f"{extra} RUN  v4.1.4 /repo\n\n Test Files  {ft}\n      Tests  {tt}\n   Duration  4.0s\n"


def _drive(cfg, responses, list_rc=0):
    """responses: per-batch (returncode, stdout) in order, then — [GATE-SIT-2] — one per isolation
    invocation (an Exception instance is raised instead). Returns (outcome, calls, sleeps, entries)."""
    calls, sleeps = [], []
    it = iter(responses)

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:  # the list command
            return MagicMock(returncode=list_rc, stdout=LIST_OUT if list_rc == 0 else "", stderr="boom" if list_rc else "")
        resp = next(it)
        if isinstance(resp, BaseException):
            raise resp
        rc, out = resp
        return MagicMock(returncode=rc, stdout=out, stderr="")

    with patch("subprocess.run", side_effect=fake_run), patch("time.sleep", side_effect=lambda s: sleeps.append(s)), \
         patch.dict(orchestrator.ACTIVE_REPO_CONFIG, cfg, clear=True):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"; archive.mkdir()
            orchestrator.SKIP_SIT = False
            outcome = orchestrator.run_sit_post_merge(Path(tmp), archive)
            entries = json.loads((archive / "orchestrator-sit-log.json").read_text())
    return outcome, calls, sleeps, entries


CFG = {"sit_list_cmd": "npx vitest list", "sit_batch_files": 2, "sit_batch_pause_s": 7}


class TestSitBatching:

    def test_every_file_runs_exactly_once_and_the_totals_sum(self, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, calls, sleeps, entries = _drive(CFG, [(0, _batch_summary(2, 4)), (0, _batch_summary(2, 4)), (0, _batch_summary(1, 2))])
        assert calls[0].endswith("npx vitest list")
        batch_cmds = calls[1:]
        assert len(batch_cmds) == 3
        assert all(" -- " in c and "npm run sit:gate" in c for c in batch_cmds)
        handed = [f for c in batch_cmds for f in FILES if f in c]
        assert handed == FILES, "each file in exactly one batch, in listing order"
        assert [c.count(".integration.test.ts") for c in batch_cmds] == [2, 2, 1]
        assert sleeps == [7, 7], "the configured pause, once between each pair of batches, never before the first"
        assert outcome.passed is True and outcome.batches == 3
        assert (outcome.test_files_total, outcome.tests_total, outcome.tests_failed) == (5, 10, 0)
        assert outcome.collection.startswith("5 files/10 tests in 3 batches, ")
        assert entries[-1]["batches"] == 3 and entries[-1]["test_files_total"] == 5
        assert "SIT batch 1/3: PASS — collected 2 test files / 4 tests" in caplog.text
        assert "SIT gate: PASS — collected 5 test files / 10 tests in 3 batches (equals the enumerated suite: 5 files / 10 tests)" in caplog.text

    def test_batch_size_and_pause_are_configuration_not_literals(self):
        """No key ⇒ the module defaults by name; a key ⇒ that repo's value (AC-SR-04)."""
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=LIST_OUT, stderr="")):
            with patch.dict(orchestrator.ACTIVE_REPO_CONFIG, {"sit_list_cmd": "x"}, clear=True):
                p = orchestrator._sit_plan(REPO)
            assert (p.batch_files, p.pause_s) == (orchestrator.SIT_BATCH_FILES, orchestrator.SIT_BATCH_PAUSE_S)
            assert len(p.batches) == 1 and p.tests_expected == 10
            with patch.dict(orchestrator.ACTIVE_REPO_CONFIG, {"sit_list_cmd": "x", "sit_batch_files": 2, "sit_batch_pause_s": 0}, clear=True):
                p = orchestrator._sit_plan(REPO)
            assert (p.batch_files, p.pause_s, len(p.batches)) == (2, 0, 3)
            with patch.dict(orchestrator.ACTIVE_REPO_CONFIG, {}, clear=True):
                assert orchestrator._sit_plan(REPO) is None
        src = (Path(__file__).parent.parent / "orchestrator.py").read_text()
        assert "time.sleep(plan.pause_s)" in src
        for literal in ("vitest.sit.config", "sleep(90", "range(0, 19", "vitest list"):
            assert literal not in src, f"clinical/environment literal in source: {literal}"

    def test_a_batch_that_collects_fewer_files_than_handed_is_not_a_verdict(self):
        """AC-SR-05: batch 2 was handed 2 files and collected 1 — the gate has hidden a file."""
        outcome, calls, _, entries = _drive(CFG, [(0, _batch_summary(2, 4)), (0, _batch_summary(1, 2)), (0, _batch_summary(1, 2))])
        assert outcome.passed is False and outcome.error == "batch-incomplete"
        assert "batch 2 was handed 2 files and collected 1" in outcome.detail
        assert "batches collected 4 files, the suite enumerates 5" in outcome.detail
        assert "batches collected 8 tests, the suite enumerates 10" in outcome.detail
        assert entries[-1]["error"] == "batch-incomplete"
        v = _verdict_for(outcome)
        assert (v.outcome, v.gate, v.signal) == (ENV, "sit", "batch-incomplete")
        assert v.outcome is not PRODUCT

    def test_a_red_batch_is_classified_and_never_retried(self, caplog):
        # the second batch: one of its two files down at login with tonight's error, 0 failed assertions
        red = ("\n".join(l for l in FIXTURE_429.splitlines() if "OperationOutcomeError" in l)[:400]
               + "\n RUN  v4.1.4 /repo\n\n Test Files  1 failed | 1 passed (2)\n      Tests  2 passed | 2 skipped (4)\n")
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, calls, sleeps, _ = _drive(CFG, [(0, _batch_summary(2, 4)), (1, red), (0, _batch_summary(1, 2))])
        assert len(calls) == 1 + 3, "every batch runs once; a red batch is not re-run"
        assert outcome.passed is False and outcome.error is None
        assert outcome.exit_code == 1 and outcome.batches == 3
        assert "Too Many Requests" in outcome.output
        v = _verdict_for(outcome)
        assert (v.outcome, v.signal) == (ENV, "rate-limited")

    def test_a_real_failure_in_a_batch_is_still_product(self):
        red = " FAIL  sit/integration/f3.integration.test.ts > case 1\nAssertionError: expected 1 to be 2\n" + _batch_summary(2, 4, failed=1)
        # [GATE-SIT-2] the fourth response is f3 re-run alone: it fails alone too
        outcome, _, sleeps, _ = _drive(CFG, [(0, _batch_summary(2, 4)), (1, red), (0, _batch_summary(1, 2)),
                                             (1, _batch_summary(1, 2, failed=1))])
        assert sleeps == [7, 7, 7]
        assert outcome.passed is False and outcome.tests_failed == 1
        assert (outcome.test_files_total, outcome.tests_total) == (5, 10)
        v = _verdict_for(outcome)
        assert v.outcome is PRODUCT
        assert "(1 failed assertions)" in v.detail

    def test_list_failure_blocks_as_environment_and_runs_nothing(self, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, calls, _, entries = _drive(CFG, [], list_rc=1)
        assert len(calls) == 1, "the gate must not run unbatched into the rate limit"
        assert outcome.passed is False and outcome.error == "sit-list-failed"
        assert entries[-1]["error"] == "sit-list-failed"
        v = _verdict_for(outcome)
        assert (v.outcome, v.signal) == (ENV, "sit-list-failed")

    def test_unconfigured_repo_runs_once_unbatched(self):
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=_batch_summary(7, 18), stderr="")) as m, \
             patch.dict(orchestrator.ACTIVE_REPO_CONFIG, {}, clear=True):
            with tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / "archive"; archive.mkdir()
                orchestrator.SKIP_SIT = False
                outcome = orchestrator.run_sit_post_merge(Path(tmp), archive)
        assert m.call_count == 1 and " -- " not in m.call_args[0][0]
        assert outcome.passed is True and outcome.batches is None
        assert outcome.collection == f"7 files/18 tests, {outcome.duration_s:.1f}s"


# ═══════════════════════════════════════════════════════
# S7-CORE-15 [GATE-SIT-2] — a red verdict you can believe: a failing file is re-run ALONE
# ═══════════════════════════════════════════════════════
F = {i: f"sit/integration/f{i}.integration.test.ts" for i in range(1, 6)}
PASS = orchestrator.GateOutcome.PASS
ALONE_GREEN = (0, _batch_summary(1, 2))
ALONE_RED = (1, _batch_summary(1, 2, failed=1))
GREEN_1, GREEN_2, GREEN_3 = (0, _batch_summary(2, 4)), (0, _batch_summary(2, 4)), (0, _batch_summary(1, 2))


def _red_batch(*failing, n_files=2, n_tests=4, extra=""):
    """A batch where each of `failing` carries one failed assertion — no transport text at all."""
    k = len(failing)
    heads = "".join(f" FAIL  {f} > case 1\nAssertionError: expected 1 to be 2\n" for f in failing)
    ft = f"{k} failed" + (f" | {n_files - k} passed" if n_files > k else "") + f" ({n_files})"
    return (1, f"{extra}{heads} RUN  v4.1.4 /repo\n\n Test Files  {ft}\n"
               f"      Tests  {k} failed | {n_tests - k} passed ({n_tests})\n   Duration  4.0s\n")


# AC-GS-01: every (SitOutcome, GateVerdict) pair these scenarios build must satisfy §2.
SCENARIOS = {
    "contaminated": [GREEN_1, _red_batch(F[3]), GREEN_3, ALONE_GREEN],
    "confirmed": [GREEN_1, _red_batch(F[3]), GREEN_3, ALONE_RED],
    "mixed": [GREEN_1, _red_batch(F[3], F[4]), GREEN_3, ALONE_GREEN, ALONE_RED],
    "timeout": [GREEN_1, _red_batch(F[3]), GREEN_3, orchestrator.subprocess.TimeoutExpired("sit", 600)],
    "two-files-alone": [GREEN_1, _red_batch(F[3]), GREEN_3, (0, _batch_summary(2, 4))],
    "signal-alone": [GREEN_1, _red_batch(F[3]), GREEN_3,
                     (1, "OperationOutcomeError: Too Many Requests\n" + _batch_summary(1, 2, failed=1))],
    "cap": [_red_batch(F[1], F[2]), _red_batch(F[3]), GREEN_3],
    "rate-limited-2-failed": [GREEN_1, _red_batch(F[3], F[4], extra="OperationOutcomeError: Too Many Requests\n"), GREEN_3],
    "zero-failed": [GREEN_1, (1, " FAIL  sit/integration/f3.integration.test.ts [ setup ]\n RUN  v4.1.4 /repo\n\n"
                                 " Test Files  1 failed | 1 passed (2)\n      Tests  2 passed | 2 skipped (4)\n"), GREEN_3],
    "green": [GREEN_1, GREEN_2, GREEN_3],
}


def _scenario(name, cfg=CFG):
    return _drive(cfg, SCENARIOS[name])


def _sit_verdict(outcome):
    """(the SIT gate's own verdict, run_pre_merge_gates' return). On the contamination PASS the
    gate falls through to the unit gate, so the two differ; read the first off the invariant call."""
    with patch.object(orchestrator, "sit_verdict_violations", wraps=orchestrator.sit_verdict_violations) as spy:
        final = _verdict_for(outcome)
    return (spy.call_args[0][1] if spy.called else final), final


class TestSitIsolation:

    def test_contamination_is_not_fail_product(self):
        """AC-GS-02, written against the pre-[GATE-SIT-2] API only (_drive + _verdict_for) so it
        RUNS on c292570 and fails there with the message below."""
        outcome, _, _, _ = _scenario("contaminated")
        v = _verdict_for(outcome)
        assert v.outcome is not PRODUCT, f"main returned FAIL(product) here: {v.label}"

    def test_contamination_passes_named(self, caplog):
        """AC-GS-02: f3 failed in batch 2 beside f4, passed alone ⇒ PASS `batch-contamination`."""
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, calls, sleeps, entries = _scenario("contaminated")
            v, final = _sit_verdict(outcome)
        assert outcome.passed is False and outcome.tests_failed == 1, "the verdict is not decided in the gate run"
        assert (v.outcome, v.gate, v.signal) == (PASS, "sit", "batch-contamination")
        assert final.outcome is PASS and final.collection == outcome.collection
        iso = outcome.isolation
        assert iso.contaminated == (F[3],) and iso.confirmed == ()
        assert iso.neighbours == {F[3]: (F[4],)} and iso.batch_of == {F[3]: 2}
        assert iso.error is None and iso.skipped is None
        assert f"{F[3]} failed in batch 2/3 beside {F[4]} — passed alone (2/2); no product failure" == v.detail
        assert "signal 'batch-contamination'" in caplog.text
        assert "SIT green after isolation" in caplog.text
        assert "confirming in isolation before verdict: " + F[3] in caplog.text
        status = orchestrator._gate_status_label(None, final.outcome.value, final.collection)
        assert f"contaminated, passed alone (not blocking): {F[3]} (batch 2/3, neighbours: {F[4]})" in status
        assert status.startswith("PASS (5 files/10 tests in 3 batches, ")

    def test_the_leg_runs_the_file_alone_after_one_pause(self):
        """AC-GS-04: exactly `<sit_cmd> -- <f3>`, after the configured pause, once."""
        _, calls, sleeps, _ = _scenario("contaminated")
        assert len(calls) == 1 + 3 + 1
        leg = calls[-1]
        assert leg.endswith(f"npm run sit:gate -- {F[3]}")
        assert leg.count(".integration.test.ts") == 1 and " -- " in leg
        assert sleeps == [7, 7, 7], "the configured pause once before the leg, never a literal"
        for c in calls[1:4]:  # the batches are unchanged
            assert c.count(".integration.test.ts") in (1, 2)

    def test_a_file_that_fails_alone_is_product(self):
        """AC-GS-03: isolation cannot mask a genuine product failure."""
        outcome, calls, _, _ = _scenario("confirmed")
        v = _verdict_for(outcome)
        assert v.outcome is PRODUCT
        assert outcome.isolation.confirmed == (F[3],) and outcome.isolation.contaminated == ()
        assert "confirmed failing alone: " + F[3] in v.detail and "(1 failed assertions)" in v.detail
        assert f"confirmed failing alone: {F[3]}" in outcome.collection

    def test_mixed_names_both_sets(self):
        """AC-GS-03 mixed: f3 passes alone, f4 fails alone ⇒ FAIL(product) naming both."""
        outcome, calls, sleeps, _ = _scenario("mixed")
        v = _verdict_for(outcome)
        assert v.outcome is PRODUCT
        iso = outcome.isolation
        assert (iso.contaminated, iso.confirmed) == ((F[3],), (F[4],))
        assert iso.neighbours == {F[3]: (F[4],), F[4]: (F[3],)}
        assert f"confirmed failing alone: {F[4]}" in v.detail
        assert f"contaminated (passed alone, not counted): {F[3]}" in v.detail
        assert [c.split(" -- ")[1] for c in calls[4:]] == [F[3], F[4]]
        assert sleeps == [7, 7, 7]

    @pytest.mark.parametrize("name,why", [("timeout", "timeout"), ("two-files-alone", "collected 2 files, not 1"),
                                          ("signal-alone", "F-20 signal 'rate-limited'")])
    def test_an_unreadable_measurement_fails_closed(self, name, why):
        """AC-GS-06: never PASS, never product."""
        outcome, _, _, _ = _scenario(name)
        assert outcome.passed is False and outcome.error is None
        v = _verdict_for(outcome)
        assert (v.outcome, v.signal) == (ENV, "isolation-unmeasurable")
        assert why in v.detail and F[3] in v.detail
        assert orchestrator.sit_verdict_violations(outcome, v) == []

    def test_environment_runs_are_never_re_run(self):
        """AC-GS-05: 2 failed assertions but a transport signal — D-S7CORE10-02 decides, no leg."""
        outcome, calls, sleeps, _ = _scenario("rate-limited-2-failed")
        assert outcome.tests_failed == 2 and outcome.isolation is None
        assert len(calls) == 1 + 3 and sleeps == [7, 7]
        v = _verdict_for(outcome)
        assert (v.outcome, v.signal) == (ENV, "rate-limited")

    def test_the_cap(self):
        """AC-GS-07: three failing files, batch size 2 ⇒ no isolation call, today's verdict."""
        outcome, calls, sleeps, entries = _scenario("cap")
        assert outcome.tests_failed == 3 and len(calls) == 1 + 3 and sleeps == [7, 7]
        iso = outcome.isolation
        assert iso.skipped == "3 failing files exceed the batch size 2 — not contamination-shaped, not re-run"
        assert iso.contaminated == () and iso.confirmed == ()
        v = _verdict_for(outcome)
        assert v.outcome is PRODUCT and v.detail.endswith("(3 failed assertions) — product verdict stands")
        assert entries[-1]["isolation"]["skipped"] == iso.skipped

    @pytest.mark.parametrize("name", ["contaminated", "confirmed"])
    def test_the_sit_log_carries_the_evidence(self, name):
        """AC-GS-08."""
        outcome, _, _, entries = _scenario(name)
        e = entries[-1]["isolation"]
        assert {"contaminated", "confirmed", "neighbours", "batch_of", "error"} <= set(e)
        assert e["neighbours"] == {F[3]: [F[4]]} and e["batch_of"] == {F[3]: 2} and e["error"] is None
        assert (e["contaminated"], e["confirmed"]) == (([F[3]], []) if name == "contaminated" else ([], [F[3]]))

    def test_no_isolation_key_when_the_leg_was_not_owed(self):
        _, _, _, entries = _scenario("green")
        assert "isolation" not in entries[-1]

    @pytest.mark.parametrize("name,outcome_is", [("contaminated", PASS), ("confirmed", PRODUCT)])
    def test_run_pre_merge_gates_consults_the_invariant(self, name, outcome_is):
        """AC-GS-10: the non-test caller hands the predicate the exact (so, v) pair it acts on."""
        outcome, _, _, _ = _scenario(name)
        with patch.object(orchestrator, "sit_verdict_violations",
                          wraps=orchestrator.sit_verdict_violations) as spy:
            final = _verdict_for(outcome)
        spy.assert_called_once()
        so, v = spy.call_args[0]
        assert so is outcome and v.outcome is outcome_is and v.gate == "sit"
        if outcome_is is PRODUCT:
            assert v is final
        else:
            assert final.outcome is PASS and final.collection == outcome.collection

    def test_a_violation_is_logged_not_acted_on(self, caplog):
        outcome, _, _, _ = _scenario("contaminated")
        with patch.object(orchestrator, "sit_verdict_violations", return_value=["V9: synthetic"]), \
             caplog.at_level(logging.INFO, logger="orch"):
            v = _verdict_for(outcome)
        assert v.outcome is PASS
        assert "⛔ GATE-SIT-2 invariant: V9: synthetic" in caplog.text


class TestSitVerdictInvariant:
    """AC-GS-01 — the §2 predicate: [] for every pair the scenarios build; one clause per negative."""

    @pytest.mark.parametrize("name", sorted(SCENARIOS))
    def test_every_constructed_pair_is_clean(self, name):
        outcome, _, _, _ = _scenario(name)
        v, _ = _sit_verdict(outcome)
        assert orchestrator.sit_verdict_violations(outcome, v) == []

    def test_the_existing_batched_red_pairs_are_clean(self):
        red = ("\n".join(l for l in FIXTURE_429.splitlines() if "OperationOutcomeError" in l)[:400]
               + "\n RUN  v4.1.4 /repo\n\n Test Files  1 failed | 1 passed (2)\n      Tests  2 passed | 2 skipped (4)\n")
        outcome, calls, _, _ = _drive(CFG, [GREEN_1, (1, red), GREEN_3])
        assert outcome.isolation is None and len(calls) == 4
        assert orchestrator.sit_verdict_violations(outcome, _verdict_for(outcome)) == []

    def _so(self, **kw):
        base = dict(passed=False, exit_code=1, batches=3, tests_failed=1,
                    output=f" FAIL  {F[3]} > case 1\n Tests  1 failed | 3 passed (4)\n")
        base.update(kw)
        return orchestrator.SitOutcome(**base)

    def _one(self, so, v, clause):
        got = orchestrator.sit_verdict_violations(so, v)
        assert len(got) == 1 and got[0].startswith(f"{clause}:"), got

    def test_v1_product_with_nothing_confirmed(self):
        iso = orchestrator.SitIsolation(contaminated=(F[3],))
        self._one(self._so(isolation=iso), orchestrator.GateVerdict(PRODUCT, "sit", "exit 1"), "V1")

    def test_v2_product_with_isolation_owed_and_not_run(self):
        self._one(self._so(), orchestrator.GateVerdict(PRODUCT, "sit", "exit 1"), "V2")

    def test_v3_pass_without_isolation(self):
        self._one(self._so(), orchestrator.GateVerdict(PASS, "sit", "batch-contamination"), "V3")

    def test_v4_isolation_where_rule_1_had_decided(self):
        iso = orchestrator.SitIsolation(contaminated=(F[3],))
        self._one(self._so(tests_failed=0, isolation=iso),
                  orchestrator.GateVerdict(ENV, "sit", "no-failed-assertions"), "V4")

    def test_v5_unmeasurable_without_a_failed_measurement(self):
        self._one(self._so(output="Tests  1 failed | 3 passed (4)\n"),
                  orchestrator.GateVerdict(ENV, "sit", "isolation-unmeasurable"), "V5")

    @pytest.mark.parametrize("kw", [dict(batches=None), dict(error="batch-incomplete"), dict(tests_failed=None)])
    def test_exclusions_say_nothing(self, kw):
        """A11: unbatched / machinery-error / UNKNOWN runs are outside the predicate."""
        assert orchestrator.sit_verdict_violations(
            self._so(**kw), orchestrator.GateVerdict(PRODUCT, "sit", "exit 1")) == []


class TestRepoConfig:
    """AC-SR-04: the clinical-mp values live in config/repos.yaml, not in orchestrator.py."""

    def test_clinical_mp_declares_batching(self):
        import yaml
        cfg = yaml.safe_load((Path(__file__).parent.parent / "config" / "repos.yaml").read_text())
        mp = cfg["repos"]["clinical-mp"]
        assert mp[orchestrator.SIT_LIST_CMD_KEY].strip()
        assert int(mp[orchestrator.SIT_BATCH_FILES_KEY]) > 0
        assert int(mp[orchestrator.SIT_BATCH_PAUSE_KEY]) > 0

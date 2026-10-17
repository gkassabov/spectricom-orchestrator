# filename: tests/test_sit_isolation_attributed.py
"""ORCH-SIT-ISOLATION-ATTRIBUTED-1 (S7-CORE-31, SCA-ORCH-SITISO-1) — the per-merge SIT gate's isolation leg also
re-measures a file vitest attributes an error to, so a batch-only failure is not called FAIL(product).

2026-10-17 11:31, route 281: batch 3/7 exit 1, 2 failed assertions, no F-20 signal — FAIL(product) and no `🔬`
line. The only file the gate kept named was vitest's attribution of an unhandled error,
`This error originated in "sit/integration/home-up-next.integration.test.tsx" test file`; that file passed alone.
vitest 4.1.4 writes every `FAIL` line (Failed Suites / Failed Tests) to stderr BEFORE the Unhandled Errors block,
so the 10,000-char tail the gate kept of each red batch could hold the attribution and none of the FAIL lines.

  P1 (D1)  an output whose only file naming is the attribution ⇒ suspects == [that file]; it passes alone ⇒ not
           FAIL(product), `contaminated` lists it. Control: it fails alone ⇒ FAIL(product), `confirmed` lists it.
  P2 (D1)  a red batch whose FAIL line sits beyond the last 10,000 chars ⇒ still named (read from the whole batch
           text, no extra run). Controls: a FAIL line inside the tail; the classifier's text is still HEAD's tail.
  P3 (D2)  red, ≥1 failed, no F-20 signal, nothing named ⇒ HEAD's verdict and `isolation not engaged: no failing
           file named`. Control: a named file ⇒ no such line.
  D3       the leg's `🔬` line names each suspect and where it was named from (`FAIL line` / `error attribution`).
  P4       the parser over route 281's gate-log text (verbatim, ANSI included) names home-up-next.

The vitest text below is vitest 4.1.4's own shape, captured 2026-10-17 from a scratch project
(/tmp/vt-capture-282b: one file raising an unhandled rejection, one failing an assertion); paths are the fixtures'.
"""
import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import sys

sys.path.insert(0, str(Path(__file__).parent.parent))
import orchestrator  # noqa: E402

REPO = Path("/tmp/repo")
PRODUCT = orchestrator.GateOutcome.FAIL_PRODUCT
PASS = orchestrator.GateOutcome.PASS

F = {i: f"sit/integration/f{i}.integration.test.ts" for i in range(1, 6)}
LIST_OUT = "\n".join(f"{F[i]} > case {j}" for i in range(1, 6) for j in (1, 2)) + "\n"   # 5 files / 10 tests
CFG = {"sit_list_cmd": "npx vitest list", "sit_batch_files": 2, "sit_batch_pause_s": 7}   # batches [f1 f2] [f3 f4] [f5]
TAIL = 10000   # _run_sit_batched keeps raw[-10000:] of each red batch


def _summary(n_files, n_tests, files_failed=0, failed=0, errors=0):
    """vitest 4.1.4's stdout summary."""
    ft = f"{n_files} passed ({n_files})" if not files_failed else \
        f"{files_failed} failed" + (f" | {n_files - files_failed} passed" if n_files > files_failed else "") + f" ({n_files})"
    tt = f"{n_tests} passed ({n_tests})" if not failed else f"{failed} failed | {n_tests - failed} passed ({n_tests})"
    err = f"     Errors  {errors} error{'s' if errors > 1 else ''}\n" if errors else ""
    return (f"\n RUN  v4.1.4 /repo\n\n Test Files  {ft}\n      Tests  {tt}\n{err}"
            f"   Start at  11:23:59\n   Duration  4.0s (transform 1.6s, setup 0ms, import 3.2s, tests 1.2s, environment 0ms)\n\n")


def _failed_tests(*files):
    """vitest 4.1.4's Failed Tests section (stderr): one ` FAIL  <file> > <test>` line per failed test."""
    body = "".join(
        f"\n FAIL  {f} > reads the value\nAssertionError: expected {{ v: 1 }} to deeply equal {{ v: 2 }}\n\n"
        f"- Expected\n+ Received\n\n  {{\n-   \"v\": 2,\n+   \"v\": 1,\n  }}\n\n ❯ {f}:2:48\n\n"
        f"⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯[{i}/{len(files)}]⎯\n" for i, f in enumerate(files, 1))
    return f"\n⎯⎯⎯⎯⎯⎯⎯ Failed Tests {len(files)} ⎯⎯⎯⎯⎯⎯⎯\n{body}\n"


def _rejection(attributed=None, frames=8):
    """One Unhandled Rejection block as vitest 4.1.4 prints it (stderr). `attributed` = the file vitest names in
    `This error originated in "<file>" test file` (None: the error came with no running file — no attribution).
    The stack sits in the Medplum client, as route 281's did: no frame names a test file."""
    stack = "".join(f" ❯ node_modules/@medplum/core/dist/esm/index.mjs:{4100 + k}:{11 + k}\n" for k in range(frames))
    out = ("⎯⎯⎯⎯ Unhandled Rejection ⎯⎯⎯⎯⎯\nOperationOutcomeError: Unauthorized\n" + stack +
           "\n⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\nSerialized Error: { outcome: { resourceType: 'OperationOutcome', "
           "id: 'unauthorized', issue: [ { severity: 'error', code: 'login', details: { text: 'Unauthorized' } } ] } }\n")
    if attributed:
        out += (f'This error originated in "{attributed}" test file. It doesn\'t mean the error was thrown inside the '
                "file itself, but while it was running.\nThe latest test that might've caused the error is \"P8 (b) — "
                "the card names the patient\". It might mean one of the following:\n- The error was thrown, while "
                "Vitest was running this test.\n- If the error occurred after the test had been completed, this was the "
                "last documented test before it was thrown.\n")
    return out + "⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\n"


def _unhandled(*blocks):
    n = len(blocks)
    return (f"⎯⎯⎯⎯⎯⎯ Unhandled Errors ⎯⎯⎯⎯⎯⎯\n\nVitest caught {n} unhandled error{'s' if n > 1 else ''} during the "
            "test run.\nThis might cause false positive tests. Resolve unhandled errors to make sure your tests are "
            "not affected.\n\n" + "".join(blocks) + "\n")


GREEN_1, GREEN_3 = (0, _summary(2, 4), ""), (0, _summary(1, 2), "")
ALONE_GREEN = (0, _summary(1, 2), "")


def _alone_red(f):
    return 1, _summary(1, 2, files_failed=1, failed=1), _failed_tests(f)


def _drive(responses, cfg=CFG):
    """responses: per invocation after the list command — (returncode, stdout, stderr): the batches in order, then
    one per isolation re-run. Returns (outcome, calls, sleeps, entries)."""
    calls, sleeps = [], []
    it = iter(responses)

    def fake_run(cmd, **kw):
        calls.append(cmd)
        if len(calls) == 1:   # the list command
            return MagicMock(returncode=0, stdout=LIST_OUT, stderr="")
        rc, out, err = next(it)
        return MagicMock(returncode=rc, stdout=out, stderr=err)

    with patch("subprocess.run", side_effect=fake_run), patch("time.sleep", side_effect=lambda s: sleeps.append(s)), \
         patch.dict(orchestrator.ACTIVE_REPO_CONFIG, cfg, clear=True):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / "archive"; archive.mkdir()
            orchestrator.SKIP_SIT = False
            outcome = orchestrator.run_sit_post_merge(Path(tmp), archive)
            entries = json.loads((archive / "orchestrator-sit-log.json").read_text())
    return outcome, calls, sleeps, entries


def _verdict(outcome):
    """(the SIT gate's own verdict, run_pre_merge_gates' return) over a SIT-only policy — on a contamination PASS
    the gate falls through, so the first is read off the invariant call."""
    with patch.dict(orchestrator.PRE_MERGE_GATES, {orchestrator.ACTIVE_REPO_NAME: {"gates": ["sit"]}}), \
         patch.object(orchestrator, "run_sit_post_merge", return_value=outcome), \
         patch.object(orchestrator, "SIT_BLOCKING", True), \
         patch.object(orchestrator, "sit_verdict_violations", wraps=orchestrator.sit_verdict_violations) as spy:
        final = orchestrator.run_pre_merge_gates(REPO, "route-branch")
    return (spy.call_args[0][1] if spy.called else final), final


def _alone_calls(calls):
    """The isolation re-runs: `<sit_cmd> -- <one file>` after the batches (the list command is calls[0])."""
    return [c.split(" -- ")[1] for c in calls[4:]]


# ═══════════════════════════════════════════════════════
# P1 (D1) — an error attribution names a suspect
# ═══════════════════════════════════════════════════════
# batch 2 [f3 f4]: one failed assertion in its tally; the only file its output names is the attribution to f3
ATTRIBUTED_ONLY = (1, _summary(2, 4, files_failed=1, failed=1, errors=1), _unhandled(_rejection(F[3])))


class TestP1ErrorAttribution:

    def test_the_parser_names_the_attributed_file(self):
        out, err = ATTRIBUTED_ONLY[1], ATTRIBUTED_ONLY[2]
        named = orchestrator._sit_named_files(out + "\n" + err)
        assert list(named) == [F[3]], "suspects == [the attributed file]"
        assert named[F[3]] == [orchestrator.SIT_NAMED_ERROR]

    def test_passes_alone_is_contamination_not_product(self, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, calls, sleeps, entries = _drive([GREEN_1, ATTRIBUTED_ONLY, GREEN_3, ALONE_GREEN])
            v, final = _verdict(outcome)
        assert v.outcome is not PRODUCT, f"FAIL(product) on a file that passed alone: {v.label}"
        assert (v.outcome, v.signal) == (PASS, "batch-contamination")
        iso = outcome.isolation
        assert iso.contaminated == (F[3],) and iso.confirmed == () and iso.error is None
        assert iso.batch_of == {F[3]: 2} and iso.neighbours == {F[3]: (F[4],)}
        assert _alone_calls(calls) == [F[3]], "each suspect alone, once"
        assert sleeps == [7, 7, 7], "HEAD's one refill pause before the leg"
        assert outcome.passed is False, "the gate run does not decide — the classifier does"
        assert entries[-1]["isolation"]["contaminated"] == [F[3]]
        assert orchestrator.sit_verdict_violations(outcome, v) == []
        assert "isolation not engaged" not in caplog.text

    def test_control_fails_alone_is_product(self):
        """Isolation cannot mask a genuine product failure: the attributed file fails alone ⇒ FAIL(product)."""
        outcome, calls, _, _ = _drive([GREEN_1, ATTRIBUTED_ONLY, GREEN_3, _alone_red(F[3])])
        v, _ = _verdict(outcome)
        assert v.outcome is PRODUCT
        assert outcome.isolation is not None and outcome.isolation.confirmed == (F[3],)
        assert outcome.isolation.contaminated == ()
        assert f"confirmed failing alone: {F[3]}" in v.detail
        assert orchestrator.sit_verdict_violations(outcome, v) == []

    def test_control_verdict_stays_product_when_it_fails_alone(self):
        """Holds on HEAD and after: the same red, the file failing alone, is FAIL(product) either way."""
        outcome, _, _, _ = _drive([GREEN_1, ATTRIBUTED_ONLY, GREEN_3, _alone_red(F[3])])
        v, _ = _verdict(outcome)
        assert v.outcome is PRODUCT


# ═══════════════════════════════════════════════════════
# P2 (D1 / Find 1) — a FAIL line beyond the 10,000-char tail is still named
# ═══════════════════════════════════════════════════════
# batch 2 [f3 f4]: f4 failed one assertion; vitest then printed six unattributed Unhandled Rejections after its
# Failed Tests section, so f4's FAIL line is more than 10,000 chars from the end of the batch's stdout+stderr.
_LONG = _unhandled(*[_rejection(None, frames=40) for _ in range(6)])
FAIL_BEYOND_TAIL = (1, _summary(2, 4, files_failed=1, failed=1, errors=6), _failed_tests(F[4]) + _LONG)
FAIL_IN_TAIL = (1, _summary(2, 4, files_failed=1, failed=1), _failed_tests(F[4]))


def _whole(resp):
    return resp[1] + "\n" + resp[2]


class TestP2FailLineBeyondTheTail:

    def test_the_fixture_is_the_shape(self):
        whole = _whole(FAIL_BEYOND_TAIL)
        assert f" FAIL  {F[4]} > " in whole and f" FAIL  {F[4]} > " not in whole[-TAIL:]
        assert orchestrator._sit_failing_files(whole[-TAIL:]) == [], "the tail HEAD read names nothing"

    def test_still_named(self, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, calls, _, _ = _drive([GREEN_1, FAIL_BEYOND_TAIL, GREEN_3, ALONE_GREEN])
            v, _ = _verdict(outcome)
        assert outcome.isolation is not None, "f4's FAIL line was not read"
        assert _alone_calls(calls) == [F[4]]
        assert outcome.isolation.contaminated == (F[4],)
        assert (v.outcome, v.signal) == (PASS, "batch-contamination")
        assert f"{F[4]} (FAIL line)" in caplog.text

    def test_fails_alone_is_product(self):
        outcome, calls, _, _ = _drive([GREEN_1, FAIL_BEYOND_TAIL, GREEN_3, _alone_red(F[4])])
        v, _ = _verdict(outcome)
        assert v.outcome is PRODUCT and outcome.isolation.confirmed == (F[4],)

    def test_control_fail_line_inside_the_tail(self):
        """HEAD already named this one; still named, the same leg."""
        outcome, calls, _, _ = _drive([GREEN_1, FAIL_IN_TAIL, GREEN_3, ALONE_GREEN])
        assert outcome.isolation is not None and outcome.isolation.contaminated == (F[4],)
        assert _alone_calls(calls) == [F[4]]

    def test_control_the_classifier_reads_heads_text(self):
        """No other verdict moves: the text the classifier and the F-20 check read is still each red batch's
        10,000-char tail — only the suspect list is read from the whole batch."""
        outcome, _, _, _ = _drive([GREEN_1, FAIL_BEYOND_TAIL, GREEN_3, ALONE_GREEN])
        head = "── SIT batch 2/3 (2 files) ──\n"
        assert outcome.output == head + _whole(FAIL_BEYOND_TAIL)[-TAIL:]
        assert f" FAIL  {F[4]} > " not in outcome.output

    def test_routes_281_shape(self, caplog):
        """FAIL line beyond the tail (f4) + the attribution inside it (f3): both suspects, listing order, each alone."""
        red = (1, _summary(2, 4, files_failed=1, failed=2, errors=7),
               _failed_tests(F[4], F[4]) + _unhandled(*[_rejection(None, frames=40) for _ in range(6)], _rejection(F[3])))
        assert f" FAIL  {F[4]} > " not in _whole(red)[-TAIL:]
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, calls, sleeps, _ = _drive([GREEN_1, red, GREEN_3, ALONE_GREEN, ALONE_GREEN])
            v, _ = _verdict(outcome)
        assert _alone_calls(calls) == [F[3], F[4]] and sleeps == [7, 7, 7]
        assert outcome.isolation.contaminated == (F[3], F[4])
        assert (v.outcome, v.signal) == (PASS, "batch-contamination")
        assert f"{F[3]} (error attribution), {F[4]} (FAIL line)" in caplog.text


# ═══════════════════════════════════════════════════════
# P3 (D2) — nothing named: HEAD's verdict, and the log says why the leg did not run
# ═══════════════════════════════════════════════════════
NOTHING_NAMED = (1, _summary(2, 4, files_failed=1, failed=1, errors=1), _unhandled(_rejection(None)))


class TestP3NothingNamed:

    def test_heads_verdict_and_the_line(self, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, calls, sleeps, entries = _drive([GREEN_1, NOTHING_NAMED, GREEN_3])
            v, _ = _verdict(outcome)
        assert outcome.isolation is None and len(calls) == 1 + 3 and sleeps == [7, 7], "nothing re-run"
        assert (v.outcome, v.signal) == (PRODUCT, "exit 1")
        assert v.detail == "no F-20 environment signal in gate output (1 failed assertions) — product verdict stands"
        assert "isolation" not in entries[-1]
        assert "isolation not engaged: no failing file named" in caplog.text
        # P-SAY: a control that was not engaged writes no `🛡` line, and the leg's `🔬` line is absent
        assert not [r for r in caplog.records if r.getMessage().startswith("🛡 sit-isolation:")]
        assert "🔬" not in caplog.text

    def test_a_named_file_outside_the_run_is_said(self, caplog):
        """A FAIL line naming a file this run did not hand vitest is not a suspect — and the line says so."""
        stray = (1, _summary(2, 4, files_failed=1, failed=1), _failed_tests("sit/integration/other.integration.test.ts"))
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, _, _, _ = _drive([GREEN_1, stray, GREEN_3])
        assert outcome.isolation is None
        line = [r.getMessage() for r in caplog.records if "isolation not engaged" in r.getMessage()]
        assert len(line) == 1 and "sit/integration/other.integration.test.ts" in line[0]

    def test_control_a_named_file_engages_and_says_nothing_of_it(self, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, _, _, _ = _drive([GREEN_1, FAIL_IN_TAIL, GREEN_3, ALONE_GREEN])
        assert outcome.isolation is not None
        assert "isolation not engaged" not in caplog.text

    def test_control_environment_runs_say_nothing(self, caplog):
        """0 failed assertions (D-S7CORE10-02): the leg is not owed, so there is nothing to explain."""
        down = (1, " RUN  v4.1.4 /repo\n\n Test Files  1 failed | 1 passed (2)\n      Tests  2 passed | 2 skipped (4)\n",
                _unhandled(_rejection(F[3])))
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, calls, _, _ = _drive([GREEN_1, down, GREEN_3])
        assert outcome.tests_failed == 0 and outcome.isolation is None and len(calls) == 4
        assert "isolation not engaged" not in caplog.text


# ═══════════════════════════════════════════════════════
# D3 — the leg's line names each suspect and where it was named from
# ═══════════════════════════════════════════════════════
class TestD3TheLegSaysWhere:

    def _line(self, caplog):
        lines = [r.getMessage() for r in caplog.records if "confirming in isolation before verdict" in r.getMessage()]
        assert len(lines) == 1, lines
        return lines[0]

    def test_each_source(self, caplog):
        red = (1, _summary(2, 4, files_failed=1, failed=1, errors=1), _failed_tests(F[4]) + _unhandled(_rejection(F[3])))
        with caplog.at_level(logging.INFO, logger="orch"):
            _drive([GREEN_1, red, GREEN_3, ALONE_GREEN, ALONE_GREEN])
        assert self._line(caplog).endswith(
            f"confirming in isolation before verdict: {F[3]} (error attribution), {F[4]} (FAIL line)")

    def test_both_sources(self, caplog):
        red = (1, _summary(2, 4, files_failed=1, failed=1, errors=1), _failed_tests(F[3]) + _unhandled(_rejection(F[3])))
        with caplog.at_level(logging.INFO, logger="orch"):
            _drive([GREEN_1, red, GREEN_3, ALONE_GREEN])
        assert self._line(caplog).endswith(
            f"confirming in isolation before verdict: {F[3]} (FAIL line + error attribution)")

    def test_a_direct_call_keeps_heads_line(self, caplog, tmp_path):
        plan = orchestrator.SitPlan(files=[F[3], F[4]], batch_files=2, pause_s=0)
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout=_summary(1, 2), stderr="")), \
             caplog.at_level(logging.INFO, logger="orch"):
            orchestrator._sit_isolate("sit", tmp_path, plan, [F[3]], tmp_path / "archive")
        assert self._line(caplog).endswith(f"confirming in isolation before verdict: {F[3]}")


# ═══════════════════════════════════════════════════════
# P4 — route 281's gate-log text, verbatim (logs/clinical-mp/orch-281-drk-path-2-20261017-102852.log, the 800 chars
# the FAILED line quoted), ANSI included
# ═══════════════════════════════════════════════════════
LOG_281 = (
    ":\x1b[22m\x1b[39m \x1b[90m{ outcome: { resourceType: 'OperationOutcome', id: 'unauthorized', issue: [ { severity: "
    "'error', code: 'login', details: { text: 'Unauthorized' } } ] } }\x1b[39m\n\x1b[31mThis error originated in \""
    "\x1b[1msit/integration/home-up-next.integration.test.tsx\x1b[22m\" test file. It doesn't mean the error was thrown "
    "inside the file itself, but while it was running.\x1b[39m\n\x1b[31mThe latest test that might've caused the error "
    "is \"\x1b[1mP8 (b) — as sit-vance: the Up next card names the harness patient; Open pre-visit lands on its "
    "Pre-visit\x1b[22m\". It might mean one of the following:\n- The error was thrown, while Vitest was running this "
    "test.\n- If the error occurred after the test had been completed, this was the last documented test before it "
    "was thrown.\x1b[39m\n\x1b[31m⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯⎯\x1b[39m\n\n\n")


class TestP4Route281:

    def test_names_home_up_next(self):
        assert orchestrator._sit_named_files(LOG_281) == {
            "sit/integration/home-up-next.integration.test.tsx": [orchestrator.SIT_NAMED_ERROR]}

    def test_control_heads_parser_named_nothing(self):
        """_sit_failing_files (FAIL lines only — V2 and the full gate's failing list still read it) is unchanged."""
        assert orchestrator._sit_failing_files(LOG_281) == []

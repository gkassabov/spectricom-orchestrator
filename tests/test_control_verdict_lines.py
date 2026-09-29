# filename: tests/test_control_verdict_lines.py
"""Tests for P-SAY (GATE-CLOCK-1 · ORCH-HANDBACK-SILENT-PASS): a control that passes says so.

S7-CORE-16 · Bug Registry v1-58 [ORCH-HANDBACK-SILENT-PASS] P3 · LESSONS L-18 · PDLC F-99.
_handback_hold logged only when it HELD, so a route log with no guard line could mean "the guard
ran and found nothing" or "the guard never ran". For every control c in

    C = {handback-guard, bg-wait-ceiling, clock-plausibility, sit-isolation, unit-confirm}

every engagement writes exactly one `🛡 <c>: <VERDICT> — <detail>` line, on the pass path and on
the hold/fail path. A control that was not engaged writes nothing. Absence can then be read as
"not engaged", because presence is guaranteed whenever it was.

  AC-GC-05  per c: the PASS path, and every non-pass path, give exactly one line.
            The source guard pins C. See _control_violations for how "a control" is detected.

No test calls the real `claude`, touches the live running.json or writes under the live logs/.
"""

import ast
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator

ROOT = Path(__file__).parent.parent
ORCH_SRC = ROOT / "orchestrator.py"
RULE = "=" * 60

# C, and the one function that speaks for each member.
C = {
    "handback-guard": "_handback_hold",
    "bg-wait-ceiling": "fire_toni",
    "clock-plausibility": "_judge_leg",
    "sit-isolation": "_sit_isolate",
    "unit-confirm": "_unit_confirm_new_files",
    # ORCH-TIMEOUT-HOLD-1 (brief 2): a sixth control, found by this guard as `_*_hold` with no line
    "executor-exit": "_executor_exit_hold",
    # BASELINE-TRUST-1 (route 67): a seventh, one line per baseline the unit gate needs
    "baseline-trust": "_unit_baseline_measure_or_reuse",
}
# the canon_assert predicates behind C: every call site must sit in a function that speaks
C_PREDICATES = {"check_handback_invariants", "check_bg_ceiling_invariants", "check_clock_plausibility",
                "check_foreground_invariants"}
# a report-only CLI over the same predicate is not a route control: it prints its own verdicts
REPORT_ONLY = {"handback_scan"}
# "a control", by name: `_*_hold`, or `guard` as an underscore-delimited word
CONTROL_NAME_RE = re.compile(r"^_\w+_hold$|(?:^|_)guard(?:_|$)")
SHIELD_RE = re.compile(r"^🛡 ([a-z0-9-]+): ([A-Z]+) — ")


def shields(caplog, control: str) -> list:
    out = [r.getMessage() for r in caplog.records if r.getMessage().startswith(f"🛡 {control}:")]
    for line in out:
        assert SHIELD_RE.match(line), f"not the `🛡 <control>: <VERDICT> — <detail>` shape: {line!r}"
    return out


def one(caplog, control: str, verdict: str) -> str:
    lines = shields(caplog, control)
    assert len(lines) == 1, lines
    assert SHIELD_RE.match(lines[0]).group(2) == verdict, lines[0]
    return lines[0]


# ═══════════════════════════════════════════════════════
# handback-guard
# ═══════════════════════════════════════════════════════
def _toni_log(tmp_path: Path, output: list) -> Path:
    p = tmp_path / "toni-x.log"
    p.write_text(f"=== TONI EXECUTION ===\nBatch: x.md\nStarted: 2026-09-28T00:00:00\nCommand: claude\n{RULE}\n\n"
                 + "\n".join(output) + f"\n\n{RULE}\nFinished: 2026-09-28T00:01:00\nExit: 0\n")
    return p


class TestHandbackGuard:

    def test_pass_path_says_clean(self, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            assert orchestrator._handback_hold(str(_toni_log(tmp_path, ["All green. Committed."]))) is None
        line = one(caplog, "handback-guard", "CLEAN")
        assert "no outstanding work advertised" in line

    def test_hold_path_says_hold_once_even_with_two_rules_matched(self, tmp_path, caplog):
        log = _toni_log(tmp_path, ["The re-run is going in the background.", "I'll follow up when it lands."])
        with caplog.at_level(logging.INFO, logger="orch"):
            h = orchestrator._handback_hold(str(log))
        assert h is not None and h.status is orchestrator.Status.INCOMPLETE
        line = one(caplog, "handback-guard", "HOLD")
        assert "background at line 7" in line and "2 rule(s) matched" in line

    def test_unjudgeable_path_says_blocked(self, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            h = orchestrator._handback_hold(str(tmp_path / "missing.log"))
        assert h.status is orchestrator.Status.BLOCKED
        assert "log-unreadable" in one(caplog, "handback-guard", "BLOCKED")

    def test_unconfigured_says_blocked(self, tmp_path, caplog, monkeypatch):
        monkeypatch.setattr(orchestrator, "HANDBACK_GUARD_CONFIG", tmp_path / "nope.json")
        with caplog.at_level(logging.INFO, logger="orch"):
            orchestrator._handback_hold(str(_toni_log(tmp_path, ["done"])))
        assert "handback-guard-unconfigured" in one(caplog, "handback-guard", "BLOCKED")


# ═══════════════════════════════════════════════════════
# bg-wait-ceiling — the REAL fire_toni against a fake `claude` on PATH
# ═══════════════════════════════════════════════════════
@pytest.fixture
def toni(tmp_path, monkeypatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(f"#!{sys.executable}\nprint('did the work', flush=True)\n")
    fake.chmod(0o755)
    logs = tmp_path / "logs"
    logs.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    brief = proj / "brief.md"
    brief.write_text("# a brief\n")
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setattr(orchestrator, "ensure_log_subdir", lambda _s: logs)
    monkeypatch.setattr(orchestrator, "RUNNING_FILE", tmp_path / "running.json")
    monkeypatch.setattr(orchestrator, "TONI_TIMEOUT", orchestrator.TONI_TIMEOUT)

    def _fire(T):
        monkeypatch.setattr(orchestrator, "TONI_TIMEOUT", T)
        return orchestrator.fire_toni(brief, proj)
    return _fire


class TestBgWaitCeiling:

    def test_pass_path_says_clean(self, toni, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            ec, _ = toni(1800)
        assert ec == 0
        line = one(caplog, "bg-wait-ceiling", "CLEAN")
        assert "CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS=1500000 < 1800000" in line

    def test_refusal_path_says_blocked(self, toni, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            ec, _ = toni(0)
        assert ec == -2
        assert "route-timeout-invalid" in one(caplog, "bg-wait-ceiling", "BLOCKED")


# ═══════════════════════════════════════════════════════
# clock-plausibility — one line per leg that ran; none for a leg not measured now
# ═══════════════════════════════════════════════════════
class TestClockPlausibility:

    def _clocks(self, d_wall, d_mono):
        from canon_assert import LegClocks
        return (LegClocks(1000.0, 0.0, 0.0), LegClocks(1000.0 + d_wall, d_mono, d_mono))

    def test_pass_path_says_clean(self, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            assert orchestrator._judge_leg("build", self._clocks(68.5, 68.5), tmp_path, red=False) is None
        assert one(caplog, "clock-plausibility", "CLEAN").startswith("🛡 clock-plausibility: CLEAN — build Δwall 68.5s")

    def test_implausible_path_says_implausible(self, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            v = orchestrator._judge_leg("unit-branch", self._clocks(15867.9, 336.7), tmp_path, red=True)
        assert v.reason == "wall-jump"
        assert "red: not a product verdict" in one(caplog, "clock-plausibility", "IMPLAUSIBLE")

    def test_not_engaged_says_nothing(self, tmp_path, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            assert orchestrator._judge_leg("unit-baseline", None, tmp_path, red=False) is None
        assert shields(caplog, "clock-plausibility") == []


# ═══════════════════════════════════════════════════════
# sit-isolation — the REAL _sit_isolate over scripted single-file runs
# ═══════════════════════════════════════════════════════
F1, F2 = "sit/integration/a.integration.test.ts", "sit/integration/b.integration.test.ts"


def _alone(passed: bool, tests: int = 3) -> subprocess.CompletedProcess:
    summary = (f" Test Files  1 passed (1)\n      Tests  {tests} passed ({tests})\n" if passed else
               f" FAIL  x > y\n Test Files  1 failed (1)\n      Tests  1 failed | {tests - 1} passed ({tests})\n")
    return subprocess.CompletedProcess("sit", 0 if passed else 1, stdout=summary, stderr="")


class TestSitIsolation:

    def _run(self, tmp_path, caplog, results, files=(F1,)):
        plan = orchestrator.SitPlan(files=[F1, F2, "c.ts"], batch_files=2, pause_s=0)
        with patch("subprocess.run", side_effect=list(results)), \
             caplog.at_level(logging.INFO, logger="orch"):
            return orchestrator._sit_isolate("sit", tmp_path, plan, list(files), tmp_path / "archive")

    def test_pass_path_says_clean(self, tmp_path, caplog):
        iso = self._run(tmp_path, caplog, [_alone(True)])
        assert iso.contaminated == (F1,)
        assert F1 in one(caplog, "sit-isolation", "CLEAN")

    def test_confirmed_path_says_fail(self, tmp_path, caplog):
        iso = self._run(tmp_path, caplog, [_alone(True), _alone(False)], files=(F1, F2))
        assert iso.confirmed == (F2,)
        line = one(caplog, "sit-isolation", "FAIL")
        assert f"confirmed failing alone: {F2}; contaminated: {F1}" in line

    def test_unmeasurable_path_says_blocked(self, tmp_path, caplog):
        iso = self._run(tmp_path, caplog, [subprocess.CompletedProcess("sit", 1, stdout="boom", stderr="")])
        assert iso.error == "isolation-unmeasurable"
        assert "isolation-unmeasurable" in one(caplog, "sit-isolation", "BLOCKED")

    def test_capped_path_says_skipped(self, tmp_path, caplog):
        self._run(tmp_path, caplog, [], files=(F1, F2, "c.ts"))
        assert "exceed the batch size 2" in one(caplog, "sit-isolation", "SKIPPED")


# ═══════════════════════════════════════════════════════
# unit-confirm — the REAL _unit_confirm_new_files over a scripted confirmation run
# ═══════════════════════════════════════════════════════
UA, UB = "src/a.test.ts", "src/b.test.ts"


def _confirm_run(failing: tuple, error=None):
    def _fake(cmd, cwd, ref):
        if error:
            return orchestrator.UnitSuiteRun(ref=ref, exit_code=-1, error=error, output=error)
        lines = [f" FAIL  {f} > case" for f in failing]
        n = len(failing)
        raw = "\n".join(lines + [f" Test Files  {n} failed | {2 - n} passed (2)" if n else " Test Files  2 passed (2)",
                                 f"      Tests  {n} failed | {10 - n} passed (10)" if n else "      Tests  10 passed (10)"])
        return orchestrator.UnitSuiteRun(ref=ref, exit_code=1 if n else 0, output=raw,
                                         **orchestrator._parse_unit_summary(raw))
    return _fake


class TestUnitConfirm:

    def _run(self, tmp_path, caplog, fake):
        with patch.object(orchestrator, "_run_unit_suite", fake), caplog.at_level(logging.INFO, logger="orch"):
            return orchestrator._unit_confirm_new_files(tmp_path, "npm test", "route", (UA, UB))

    def test_pass_path_says_clean(self, tmp_path, caplog):
        flakes, regressions, _ = self._run(tmp_path, caplog, _confirm_run(()))
        assert (flakes, regressions) == ((UA, UB), ())
        assert f"(flaky): {UA}, {UB}" in one(caplog, "unit-confirm", "CLEAN")

    def test_regression_path_says_fail(self, tmp_path, caplog):
        flakes, regressions, _ = self._run(tmp_path, caplog, _confirm_run((UB,)))
        assert regressions == (UB,)
        assert f"still failing alone: {UB}; flaky: {UA}" in one(caplog, "unit-confirm", "FAIL")

    def test_unmeasurable_path_says_blocked(self, tmp_path, caplog):
        flakes, _, _ = self._run(tmp_path, caplog, _confirm_run((), error="timeout"))
        assert flakes is None
        assert "confirmation-unmeasurable: timeout" in one(caplog, "unit-confirm", "BLOCKED")

    def test_not_engaged_when_no_file_newly_fails(self, tmp_path, caplog):
        """A green branch never reaches the confirmation: no line, and that absence means exactly that."""
        green = " Test Files  2 passed (2)\n      Tests  10 passed (10)\n"
        repos = {"r": {"project_dir": str(tmp_path), "test_cmd": "npm test", "default": True}}
        subprocess.run(["git", "init", "-q", "-b", "main", str(tmp_path)], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "-c", "user.email=t@t", "-c", "user.name=t",
                        "commit", "-q", "--allow-empty", "-m", "M0"], check=True)
        with patch.object(orchestrator, "ACTIVE_REPO_NAME", "r"), \
             patch.object(orchestrator, "ACTIVE_REPO_CONFIG", repos["r"]), \
             patch.object(orchestrator, "UNIT_GATE_ENABLED", True), \
             patch.object(orchestrator, "load_repo_config", return_value={"repos": repos}), \
             patch.object(orchestrator, "_run_unit_suite",
                          lambda cmd, cwd, ref: orchestrator.UnitSuiteRun(
                              ref=ref, exit_code=0, output=green, **orchestrator._parse_unit_summary(green))), \
             caplog.at_level(logging.INFO, logger="orch"):
            o = orchestrator.run_unit_gate(tmp_path, "main", archive_path=tmp_path / "archive")
        assert o.passed
        assert shields(caplog, "unit-confirm") == []


# ═══════════════════════════════════════════════════════
# executor-exit (ORCH-TIMEOUT-HOLD-1)
# ═══════════════════════════════════════════════════════
class TestExecutorExit:

    def test_pass_path_says_clean(self, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            assert orchestrator._executor_exit_hold(0, "orch-x") is None
        assert one(caplog, "executor-exit", "CLEAN") == "🛡 executor-exit: CLEAN — exit 0"

    @pytest.mark.parametrize("ec,verdict", [(-1, "INCOMPLETE(timeout)"), (-2, "INCOMPLETE(executor-error)")])
    def test_hold_path_says_hold(self, caplog, ec, verdict):
        with caplog.at_level(logging.INFO, logger="orch"):
            h = orchestrator._executor_exit_hold(ec, "orch-x")
        assert h.status is orchestrator.Status.INCOMPLETE and h.verdict == verdict
        assert one(caplog, "executor-exit", "HOLD") == f"🛡 executor-exit: HOLD — {verdict}: exit {ec} with work on orch-x"


# ═══════════════════════════════════════════════════════
# the source guard — C is pinned
# ═══════════════════════════════════════════════════════
def _shield_names(fn: ast.AST) -> set:
    """Control names of every `🛡 <name>:` string literal or f-string head inside `fn`."""
    names = set()
    for n in ast.walk(fn):
        head = None
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            head = n.value
        elif isinstance(n, ast.JoinedStr) and n.values and isinstance(n.values[0], ast.Constant):
            head = n.values[0].value
        m = re.match(r"^🛡 ([a-z0-9-]+):", head or "")
        if m:
            names.add(m.group(1))
    return names


def _control_violations(src: str) -> list:
    """How "a control" is detected, bounded to orchestrator.py's TOP-LEVEL functions:
      (1) every function whose name matches CONTROL_NAME_RE (`_*_hold`, or `guard` as a word);
      (2) every function that calls one of C_PREDICATES, except the REPORT_ONLY CLI;
      (3) every function that emits a `🛡 <name>:` line.
    Each must be exactly C's speaker for exactly C's names. A control that is none of (1)-(3) —
    another name, another predicate, no line — is NOT detected; that is the bound."""
    tree = ast.parse(src)
    fns = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    spoken = {name: _shield_names(fn) for name, fn in fns.items()}
    out = []
    for name, fn in fns.items():
        calls = {c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
        if CONTROL_NAME_RE.search(name) and not spoken[name]:
            out.append(f"{name}: named like a control, emits no 🛡 line")
        if calls & C_PREDICATES and name not in REPORT_ONLY and not spoken[name]:
            out.append(f"{name}: calls {sorted(calls & C_PREDICATES)}, emits no 🛡 line")
    speakers = {name: s for name, s in spoken.items() if s}
    expected = {fn: {c} for c, fn in C.items()}
    if speakers != expected:
        out.append(f"🛡 speakers {speakers} != C {expected}")
    return out


def test_source_guard_C_is_pinned():
    assert _control_violations(ORCH_SRC.read_text()) == []


@pytest.mark.parametrize("snippet,why", [
    ("def _deploy_hold(x):\n    return None\n", "named like a control"),
    ("def cheap_guard_check(x):\n    return None\n", "named like a control"),
    ("def _peek(p, rules):\n    return check_handback_invariants(p, rules)\n", "emits no 🛡 line"),
    ("def _new(x):\n    log.info(f'🛡 new-control: CLEAN — {x}')\n", "!= C"),
], ids=["new-hold", "new-guard", "new-predicate-caller", "unpinned-speaker"])
def test_source_guard_turns_red(snippet, why):
    v = _control_violations(ORCH_SRC.read_text() + "\n\n" + snippet)
    assert v and any(why in x for x in v), v

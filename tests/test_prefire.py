"""Guard tests for the HOOK-1 pre-fire assertions (SESSION-BOOT A2/A8; A9/A10 ORCH-PREFIRE-TEST-SCOPE-1)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prefire  # noqa: E402
import pytest  # noqa: E402
import yaml  # noqa: E402

KANBAN_LINE = "## Kanban: SCP_Kanban row 1\n"
SCOPE_LINE = "## Test scope: targeted (D-S7CORE30-05)\n"     # A9 (ORCH-PREFIRE-TEST-SCOPE-1); see the A9 tests


@pytest.fixture(autouse=True)
def ready_row(tmp_path, monkeypatch):
    """ORCH-CONTROL-SCOPE-1 C3: every brief here names a READY row of a scratch Kanban, so these tests
    keep judging A2/A8 alone (A1 has its own in tests/test_control_scope.py)."""
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "SCP_Kanban_v0-1.md").write_text("| # | Item | State |\n|---|---|---|\n| 1 | x | **`READY`** |\n")
    cfg = tmp_path / "repos.yaml"
    cfg.write_text(yaml.safe_dump({"kanban_dir": str(canon), "repos": {}}))
    monkeypatch.setattr(prefire, "REPOS_CONFIG", cfg)


def w(tmp_path, body: str) -> Path:
    p = tmp_path / "b.md"
    p.write_text(KANBAN_LINE + SCOPE_LINE + body, encoding="utf-8")
    return p


# ── A2: parsing the declared estimate ────────────────────────────────────────
def test_range_takes_lower_bound(tmp_path):
    assert prefire.parse_declared_estimate(
        w(tmp_path, "## Estimated runtime: 75-95 min\n")) == 75


def test_en_dash_range(tmp_path):
    assert prefire.parse_declared_estimate(
        w(tmp_path, "## Estimated runtime: 75–95 min\n")) == 75


def test_parenthetical_digits_ignored(tmp_path):
    # regression: "(2 briefs)" must not become the lower bound
    assert prefire.parse_declared_estimate(
        w(tmp_path, "## Estimated runtime: 45-90 min (2 briefs, HIGH-substrate)\n")) == 45


def test_hours_converted(tmp_path):
    assert prefire.parse_declared_estimate(
        w(tmp_path, "## Estimated runtime: 1.5 hours\n")) == 90


def test_undeclared_is_none(tmp_path):
    assert prefire.parse_declared_estimate(w(tmp_path, "## Repo: orchestrator\n")) is None


# ── A2: the assertion itself ────────────────────────────────────────────────
def test_undeclared_blocks(tmp_path):
    fails = prefire.check(w(tmp_path, "## Repo: orchestrator\n"))
    assert any(f.startswith("A2") for f in fails)


def test_under_floor_blocks(tmp_path):
    fails = prefire.check(w(tmp_path, "## Estimated runtime: 12 min\n"))
    assert any(f.startswith("A2") for f in fails)


def test_at_floor_passes(tmp_path):
    assert prefire.check(w(tmp_path, "## Estimated runtime: 30 min\n")) == []


def test_microfire_trigger_waives_floor(tmp_path):
    body = ("## Estimated runtime: 8 min\n"
            "## Micro-fire trigger: P1 clinical-safety defect — LOINC mismap\n")
    assert prefire.check(w(tmp_path, body)) == []


def test_bare_microfire_trigger_does_not_waive(tmp_path):
    # A2 requires the trigger to be NAMED (P0 infra / P1 safety), not asserted
    body = "## Estimated runtime: 8 min\n## Micro-fire trigger: it is small\n"
    fails = prefire.check(w(tmp_path, body))
    assert any(f.startswith("A2") for f in fails)


# ── A8: skip-sit ────────────────────────────────────────────────────────────
def test_skip_sit_invocation_blocks(tmp_path):
    body = ("## Estimated runtime: 60 min\n"
            "## Fire mechanism: orchestrator run x.md --approve --skip-sit\n")
    fails = prefire.check(w(tmp_path, body))
    assert any(f.startswith("A8") for f in fails)


def test_negated_skip_sit_mention_allowed(tmp_path):
    # regression: "*No `--skip-sit`: this is a feature bundle*" is a compliance
    # note, not an invocation (S7-CORE-3 bundle false-positived on substring match)
    body = ("## Estimated runtime: 60 min\n"
            "*No `--skip-sit`: this is a feature/integration bundle.*\n")
    assert prefire.check(w(tmp_path, body)) == []


# ── A9 / A10: the test scope (ORCH-PREFIRE-TEST-SCOPE-1, D-S7CORE30-05) ──────
RUNTIME_LINE = "## Estimated runtime: 60 min\n"
TARGETED = "## Test scope: targeted (D-S7CORE30-05)\n"
FULL = "## Test scope: full — D-S7CORE30-99\n"
BODY_LINE_NO = 4          # KANBAN_LINE, RUNTIME_LINE, the scope line, then the body


def scoped(tmp_path, scope: str, body: str = "") -> Path:
    """A brief that passes A1/A2/A8, with exactly the scope line(s) given — none when `scope` is ''."""
    p = tmp_path / "b.md"
    p.write_text(KANBAN_LINE + RUNTIME_LINE + scope + body, encoding="utf-8")
    return p


# P1 · A9
def test_P1_no_test_scope_header_is_refused(tmp_path):
    assert prefire.check(scoped(tmp_path, "")) == [
        "A9 TEST-SCOPE — the brief does not declare its test scope (`## Test scope: targeted (D-S7CORE30-05)`)"]


def test_P1_targeted_passes(tmp_path):
    assert prefire.check(scoped(tmp_path, TARGETED)) == []


@pytest.mark.parametrize("dash", ["—", "–", "-"])
def test_P1_full_naming_a_george_decision_passes_a9(tmp_path, dash):
    assert prefire.check(scoped(tmp_path, f"## Test scope: full {dash} D-S7CORE30-99\n")) == []


@pytest.mark.parametrize("line", [
    "## Test scope: full — because",                     # P1: no ruling id
    "## Test scope: full",
    "## Test scope: full — D-S7CORE30",
    "## Test scope: full — D-S7CORE30-99 because George said",
    "## Test scope: full — see D-S7CORE30-99",
    "## Test scope: targeted",
    "## Test scope: targeted (D-S7CORE30-04)",
    "## Test scope: targeted (D-S7CORE30-05) but run npm test",
    "## Test scope:",
])
def test_P1_a_malformed_test_scope_is_refused_and_named(tmp_path, line):
    fails = prefire.check(scoped(tmp_path, line + "\n"))
    assert len(fails) == 1 and fails[0].startswith(prefire.A9_REFUSAL), fails
    assert f"'{line}' is neither" in fails[0]


@pytest.mark.parametrize("lines", [TARGETED + FULL, FULL + TARGETED, TARGETED + TARGETED])
def test_P1_more_than_one_test_scope_line_is_refused(tmp_path, lines):
    fails = prefire.check(scoped(tmp_path, lines))
    assert len(fails) == 1 and fails[0].startswith(prefire.A9_REFUSAL + "; 2 '## Test scope:' lines"), fails


def test_P1_control_the_claude_md_section_heading_is_not_a_header_line(tmp_path):
    """`## Test scope — no duplicate regression runs (…)` (this repo's CLAUDE.md) has no colon: beside the
    header it changes nothing; alone it is no header."""
    heading = "## Test scope — no duplicate regression runs (source: `~/SPECTRICOM-SHARED-RULES.md` §7)\n"
    assert prefire.check(scoped(tmp_path, TARGETED, heading)) == []
    assert prefire.check(scoped(tmp_path, heading)) == [prefire.A9_REFUSAL]


def test_P1_control_a2_and_a8_still_report_beside_a9(tmp_path):
    p = tmp_path / "b.md"
    p.write_text(KANBAN_LINE + "## Estimated runtime: 12 min\n--skip-sit\n", encoding="utf-8")
    assert [f.split(" ")[0] for f in prefire.check(p)] == ["A2", "A8", "A9"]


# P2 · A10
SUITE_LINES = [
    "Run `npm test` before the final commit.",                                  # P2
    "run `npm run sit:gate`",                                                   # P2
    "Then `sit:gate` once more.",
    "Run `npm run test` before the final commit.",
    "`npm test -- --run`",                                                      # flags are not a path
    "- **P5:** `tsc` 0, build 0, unit failures ≤ merge-base baseline, SIT gate green.",   # done/112's shape
]
ALLOWED_LINES = [
    "**Do NOT run the full `npm test`** — the orchestrator's pre-merge gate runs it right after you.",  # P2
    "`npm test -- src/x.test.ts`",                                                                    # P2
    "`pytest tests/test_prefire.py`",                                                                 # P2
    "`npx vitest related --run src/a.ts src/b.ts`",
    "`npx vitest run --config vitest.sit.config.ts sit/x.sit.test.ts`",
    "**Do NOT run the full `npm test`, a merge-base baseline, or `npm run sit:gate`** — the gate runs them.",
    "Never run a merge-base baseline.",
    "Don't run `npm run sit:gate`.",
    "`npm test` is not run by the executor.",
    "`npm test -- <changed files>`",
]


@pytest.mark.parametrize("line", SUITE_LINES)
def test_P2_a_targeted_brief_that_instructs_a_full_suite_is_refused_naming_the_line(tmp_path, line):
    fails = prefire.check(scoped(tmp_path, TARGETED, line + "\n"))
    assert len(fails) == 1 and fails[0].startswith("A10 FULL-SUITE"), fails
    assert f"line {BODY_LINE_NO}: {line}" in fails[0]


@pytest.mark.parametrize("line", ALLOWED_LINES)
def test_P2_a_negated_or_targeted_command_passes(tmp_path, line):
    assert prefire.check(scoped(tmp_path, TARGETED, line + "\n")) == []


@pytest.mark.parametrize("line", SUITE_LINES)
def test_P2_full_scope_lets_the_same_lines_pass(tmp_path, line):
    assert prefire.check(scoped(tmp_path, FULL, line + "\n")) == []


def test_P2_a10_is_not_judged_without_a_scope(tmp_path):
    """No header is A9's refusal alone: A10 applies to a `targeted` brief."""
    assert prefire.check(scoped(tmp_path, "", SUITE_LINES[0] + "\n")) == [prefire.A9_REFUSAL]


def test_P2_every_offending_line_is_counted(tmp_path):
    fails = prefire.check(scoped(tmp_path, TARGETED, "".join(l + "\n" for l in SUITE_LINES[:5])))
    assert len(fails) == 1 and fails[0].startswith("A10 FULL-SUITE")
    for n in (4, 5, 6):
        assert f"line {n}: " in fails[0]
    assert "line 7: " not in fails[0] and fails[0].endswith(" (+2 more)")


BARE_PYTEST = [
    "`pytest -q`",                                                                         # P2
    "Gates: `pytest` on the changed/new test files only; `python -m compileall src` clean.",   # 286:48
    "- Targeted checks only: `python3 -m pytest -q` on the test files `93316e1` adds, plus `x.py`.",   # 282br:25
    "Run the full pytest suite.",
]
PYTEST_WITH_PATH = [
    "`pytest tests/test_prefire.py`",                                                      # P2
    "`python3 -m pytest -q tests/test_prefire.py::test_P1_targeted_passes`",
    "`pytest -q <changed paths>`",
    "Run pytest -q tests/test_a.py tests/test_b.py before the final commit.",
    "Do not run the full `pytest` suite — the gate runs it right after you.",             # negated
    "`pytest.ini` keeps its markers; `pytest-xdist` is not installed.",                    # not a pytest command
]


@pytest.mark.parametrize("line", BARE_PYTEST)
def test_P2_a_bare_pytest_is_refused_when_its_clause_is_on(tmp_path, monkeypatch, line):
    monkeypatch.setattr(prefire, "A10_BARE_PYTEST", True)
    fails = prefire.check(scoped(tmp_path, TARGETED, line + "\n"))
    assert len(fails) == 1 and fails[0].startswith("A10 FULL-SUITE"), fails
    assert f"line {BODY_LINE_NO}: {line}" in fails[0]
    monkeypatch.setattr(prefire, "A10_BARE_PYTEST", False)          # STOP (b): staged off, the line passes
    assert prefire.check(scoped(tmp_path, TARGETED, line + "\n")) == []


@pytest.mark.parametrize("line", PYTEST_WITH_PATH)
def test_P2_pytest_with_a_path_or_negated_passes_with_its_clause_on(tmp_path, monkeypatch, line):
    monkeypatch.setattr(prefire, "A10_BARE_PYTEST", True)
    assert prefire.check(scoped(tmp_path, TARGETED, line + "\n")) == []


def test_P2_full_scope_lets_a_bare_pytest_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(prefire, "A10_BARE_PYTEST", True)
    assert prefire.check(scoped(tmp_path, FULL, "`pytest -q`\n")) == []


# D3 · the report
def test_D3_report_names_a9_and_a10_and_the_scope_it_passed_on(tmp_path, capsys):
    assert prefire.report(scoped(tmp_path, FULL)) is True
    # rule #8 [ORCH-OPEX-PREFIRE-1]: A12/A13/A14 print one line each after these two (tests/test_opex_prefire.py)
    passed, scope, *opex = capsys.readouterr().out.splitlines()
    assert passed.startswith("  Assertions: ✅ A1/A2/A8/A9/A10/A11 pass — SCP_Kanban row 1 READY")
    assert scope == "  Test scope: full — D-S7CORE30-99"
    assert [l.split()[0] for l in opex] == ["A12", "A13", "A14"]


def test_D3_report_lists_a9_and_a10_refusals_like_a8s(tmp_path, capsys):
    assert prefire.report(scoped(tmp_path, "")) is False
    assert "  • " + prefire.A9_REFUSAL + "\n" in capsys.readouterr().out
    assert prefire.report(scoped(tmp_path, TARGETED, "Run `npm test` now.\n")) is False
    assert "  • A10 FULL-SUITE — " in capsys.readouterr().out


def test_D3_the_fire_refuses_a_brief_with_no_test_scope(tmp_path, monkeypatch, capsys):
    """Reachability: orchestrator.run_batch is the fire's one call of prefire.report, its first statement.
    A report that clears the brief stops the test THERE: past prefire, run_batch copies the brief, cuts a
    branch in the cwd and starts a real executor (this test's RED run on HEAD did, route 283)."""
    import orchestrator
    real = prefire.report

    def report(*a, **k):
        if real(*a, **k):
            pytest.fail("prefire cleared a brief with no test scope; run_batch stopped before firing")
        return False
    monkeypatch.setattr(prefire, "report", report)
    monkeypatch.setattr(orchestrator, "fire_toni", lambda *a, **k: pytest.fail("run_batch fired an executor"))
    monkeypatch.setattr(orchestrator, "PREFIRE_BYPASS", False)
    monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
    r = orchestrator.run_batch(scoped(tmp_path, ""))
    assert (r.status, r.exit_code, r.briefs) == (orchestrator.Status.FAILED, 2, 0)
    assert "  • " + prefire.A9_REFUSAL in capsys.readouterr().out

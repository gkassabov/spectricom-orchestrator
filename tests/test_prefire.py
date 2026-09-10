"""Guard tests for the HOOK-1 pre-fire assertions (SESSION-BOOT A2/A8)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prefire  # noqa: E402


def w(tmp_path, body: str) -> Path:
    p = tmp_path / "b.md"
    p.write_text(body, encoding="utf-8")
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

"""ORCH-PREFIRE-RUNTIME-1 (S7-CORE-24) — the runtime a brief declares is read by ONE parser, for both the sizing
floor and the route timeout.

LESSONS L-102: route 225's `## Estimated runtime: 2-3 h` was read by prefire as 120 min (pass) and by
orchestrator.parse_brief_timeout as nothing, so the route ran under the 45-min default and was killed with 29 files
of work (salvaged as 225b). On 1e08671 the two parsers were two grammars.

  D1  prefire.parse_declared_runtime -> (lower, upper) minutes. parse_declared_estimate is the lower bound;
      parse_brief_timeout is int(upper × 1.25) unless a TONI_TIMEOUT_MIN header or a Fire mechanism override is
      present (those keep precedence). A single value is both bounds.
  D2  a runtime line that gives no upper bound fails A2 RUNTIME, naming the line. Prefire's pass line names the
      route timeout and its source, and warns (does not fail) when the hard cap clamps it.
  P1  '2-3 h' -> 225, resolved 180 (clamped, warned); None on 1e08671. Controls: '90-120 min' -> 150 before and
      after; 'TONI_TIMEOUT_MIN: 40' still wins.
  P2  a runtime line with no number fails A2 RUNTIME; on 1e08671 it failed as "no '## Estimated runtime:'
      declared" — a line that was there. Control: a missing line fails as before.
"""
import logging
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orchestrator  # noqa: E402
import prefire  # noqa: E402

KANBAN_LINE = "## Kanban: SCP_Kanban row 1\n"
SCOPE_LINE = "## Test scope: targeted (D-S7CORE30-05)\n"     # A9 (ORCH-PREFIRE-TEST-SCOPE-1)
RUNTIME_FAIL = "A2 RUNTIME — '{line}' gives no route timeout; write '<n>-<m> min'"


@pytest.fixture(autouse=True)
def ready_row(tmp_path, monkeypatch):
    """Every brief here names a READY row of a scratch Kanban (as tests/test_prefire.py does), so A2 is judged
    alone; and no TONI_TIMEOUT_MIN leaks in from the shell that runs the suite."""
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "SCP_Kanban_v0-1.md").write_text("| # | Item | State |\n|---|---|---|\n| 1 | x | **`READY`** |\n")
    cfg = tmp_path / "repos.yaml"
    cfg.write_text(yaml.safe_dump({"kanban_dir": str(canon), "repos": {}}))
    monkeypatch.setattr(prefire, "REPOS_CONFIG", cfg)
    monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)


def brief(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "b.md"
    p.write_text("#!queue repo=orchestrator\n" + KANBAN_LINE + SCOPE_LINE + body, encoding="utf-8")
    return p


def a2(fails: list) -> list:
    return [f for f in fails if f.startswith("A2")]


# ── D1 · one grammar: today's prefire grammar, both bounds ───────────────────────────────────────────────
# Every shape here is one the live queue has carried (queue/, queue/done/, the repos' briefs/), plus route 225's.
GRAMMAR = [
    ("75-95 min", (75, 95)),
    ("75–95 min", (75, 95)),                                     # en dash
    ("75—95 min", (75, 95)),                                     # em dash
    ("45-90 min (2 briefs, HIGH-substrate)", (45, 90)),          # parentheticals dropped first
    ("90 min", (90, 90)),                                        # a single value is both bounds
    ("20-30m", (20, 30)),
    ("30-40m total", (30, 40)),
    ("120-150 minutes Toni session", (120, 150)),
    ("2-3 h", (120, 180)),                                       # route 225
    ("3-4 hours Toni session", (180, 240)),
    ("1.5 hours", (90, 90)),
    ("1.5h", (90, 90)),                                          # the unit may touch its number
    ("2-3h", (120, 180)),
    ("140-180 min aggregate (50-65m + 50-60m + 40-55m)", (140, 180)),
    ("75-90 min Toni session (Tier 1: ~30 min; Tier 2: ~45-60 min)", (75, 90)),
    ("30-60m wall (docker image pulls dominate first-boot; subsequent reseeds 5-10m)", (30, 60)),
    ("180 min (CODE PORTION ONLY — manual infra steps require human)", (180, 180)),
    ("TBD", None),
    ("(see §5)", None),                                          # every number is in a parenthetical
    ("two to three hours", None),
]


@pytest.mark.parametrize("value,bounds", GRAMMAR)
def test_D1_one_parse_gives_both_bounds(tmp_path, value, bounds):
    b = brief(tmp_path, f"## Estimated runtime: {value}\n")
    assert prefire.parse_declared_runtime(b) == bounds
    assert prefire.parse_declared_estimate(b) == (bounds[0] if bounds else None)
    assert orchestrator.parse_brief_timeout(b) == (int(bounds[1] * 1.25) if bounds else None)


@pytest.mark.parametrize("value,bounds", GRAMMAR)
def test_D1_a_line_prefire_accepts_always_yields_a_timeout(tmp_path, value, bounds):
    """The target state: no line passes A2 and then runs under the silent default."""
    b = brief(tmp_path, f"## Estimated runtime: {value}\n## Micro-fire trigger: P1 clinical-safety defect\n")
    if not a2(prefire.check(b)):
        assert orchestrator.parse_brief_timeout(b) is not None, value
        assert orchestrator.resolve_timeout(b)[1] == "brief-declared"


def test_D1_the_timeout_is_read_off_prefires_parse_not_a_second_grammar(tmp_path, monkeypatch):
    """Whatever prefire's parse says is what the route timeout is computed from."""
    b = brief(tmp_path, "## Estimated runtime: 90-120 min\n")
    monkeypatch.setattr(prefire, "parse_declared_runtime", lambda fp: (10, 100))
    assert orchestrator.parse_brief_timeout(b) == 125


def test_D1_the_runtime_line_is_read_where_prefire_reads_it(tmp_path):
    """Past the old 4000-character window but inside prefire's header: prefire saw it, the timeout did not."""
    b = brief(tmp_path, "#" * 3990 + "\n" + "## Estimated runtime: 60-80 min\n")
    assert prefire.parse_declared_estimate(b) == 60
    assert orchestrator.parse_brief_timeout(b) == 100


def test_D1_no_line_no_runtime(tmp_path):
    b = brief(tmp_path, "## Repo: orchestrator\n")
    assert prefire.parse_declared_runtime(b) is None
    assert prefire.parse_declared_estimate(b) is None
    assert orchestrator.parse_brief_timeout(b) is None


# ── P1 · route 225's line, and its controls ─────────────────────────────────────────────────────────────
class TestP1:

    def test_R_two_to_three_hours_is_a_225_minute_timeout_clamped_to_the_cap(self, tmp_path, caplog):
        b = brief(tmp_path, "## Estimated runtime: 2-3 h\n")
        assert prefire.parse_declared_estimate(b) == 120
        assert orchestrator.parse_brief_timeout(b) == 225
        with caplog.at_level(logging.WARNING, logger="orch"):
            assert orchestrator.resolve_timeout(b) == (orchestrator.TIMEOUT_HARD_CAP_MIN, "brief-declared")
        assert "Timeout 225min (brief-declared) exceeds hard cap 180min; clamping" in caplog.text

    def test_R_the_pass_line_names_the_timeout_and_warns_of_the_clamp(self, tmp_path, capsys):
        b = brief(tmp_path, "## Estimated runtime: 2-3 h\n")
        assert orchestrator.prefire_timeout(b) == (180, "brief-declared", 225)
        assert prefire.report(b, timeout=orchestrator.prefire_timeout(b)) is True, "a warning, not a failure"
        out = capsys.readouterr().out
        assert "✅ A1/A2/A8/A9/A10 pass" in out
        assert "declared 120m (floor 30m); timeout 180 min (brief-declared) ⚠ clamped to 180 min from 225" in out

    def test_negative_control_ninety_to_one_twenty_is_150_unclamped(self, tmp_path, capsys, caplog):
        b = brief(tmp_path, "## Estimated runtime: 90-120 min\n")
        assert orchestrator.parse_brief_timeout(b) == 150, "the same as on 1e08671"
        with caplog.at_level(logging.WARNING, logger="orch"):
            assert orchestrator.resolve_timeout(b) == (150, "brief-declared")
        assert "hard cap" not in caplog.text
        assert prefire.report(b, timeout=orchestrator.prefire_timeout(b)) is True
        out = capsys.readouterr().out
        assert "declared 90m (floor 30m); timeout 150 min (brief-declared)\n" in out and "⚠" not in out

    def test_negative_control_a_TONI_TIMEOUT_MIN_header_still_wins(self, tmp_path, capsys):
        b = brief(tmp_path, "## Estimated runtime: 2-3 h\n## TONI_TIMEOUT_MIN: 40\n")
        assert orchestrator.parse_brief_timeout(b) == 40
        assert orchestrator.resolve_timeout(b) == (40, "brief-declared")
        prefire.report(b, timeout=orchestrator.prefire_timeout(b))
        out = capsys.readouterr().out
        assert "timeout 40 min (brief-declared)" in out and "⚠" not in out

    def test_negative_control_a_fire_mechanism_override_still_wins(self, tmp_path):
        b = brief(tmp_path, "## Fire mechanism: queue TONI_TIMEOUT_MIN=75\n## Estimated runtime: 2-3 h\n")
        assert orchestrator.parse_brief_timeout(b) == 75

    def test_the_env_var_still_wins_and_the_pass_line_says_so(self, tmp_path, monkeypatch, capsys):
        b = brief(tmp_path, "## Estimated runtime: 2-3 h\n")
        monkeypatch.setenv("TONI_TIMEOUT_MIN", "30")
        assert orchestrator.resolve_timeout(b) == (30, "env-var")
        prefire.report(b, timeout=orchestrator.prefire_timeout(b))
        assert "timeout 30 min (env-var)" in capsys.readouterr().out

    def test_an_env_var_over_the_cap_is_clamped_and_warned_too(self, tmp_path, monkeypatch, capsys):
        b = brief(tmp_path, "## Estimated runtime: 60-90 min\n")
        monkeypatch.setenv("TONI_TIMEOUT_MIN", "240")
        assert orchestrator.prefire_timeout(b) == (180, "env-var", 240)
        prefire.report(b, timeout=orchestrator.prefire_timeout(b))
        assert "timeout 180 min (env-var) ⚠ clamped to 180 min from 240" in capsys.readouterr().out

    def test_an_unreadable_env_var_is_left_to_the_route_as_before(self, tmp_path, monkeypatch, capsys):
        """`TONI_TIMEOUT_MIN=abc` fails the route at resolve_timeout, as on 1e08671; prefire does not crash on it."""
        b = brief(tmp_path, "## Estimated runtime: 60-90 min\n")
        monkeypatch.setenv("TONI_TIMEOUT_MIN", "abc")
        assert orchestrator.prefire_timeout(b) is None
        with pytest.raises(ValueError):
            orchestrator.resolve_timeout(b)
        assert prefire.report(b, timeout=None) is True
        assert "timeout 112 min (Estimated runtime × 1.25" in capsys.readouterr().out


# ── P2 · a line that gives no timeout fails, naming it ──────────────────────────────────────────────────
class TestP2:

    @pytest.mark.parametrize("value", ["TBD", "(see §5)", "two to three hours"])
    def test_R_a_runtime_line_with_no_number_fails_naming_the_line(self, tmp_path, value):
        b = brief(tmp_path, f"## Estimated runtime: {value}\n")
        assert a2(prefire.check(b)) == [RUNTIME_FAIL.format(line=f"## Estimated runtime: {value}")]

    def test_R_a_micro_fire_trigger_does_not_waive_it(self, tmp_path):
        """The trigger waives the sizing floor. It does not give the route a timeout."""
        b = brief(tmp_path, "## Estimated runtime: TBD\n## Micro-fire trigger: P1 clinical-safety defect\n")
        assert a2(prefire.check(b)) == [RUNTIME_FAIL.format(line="## Estimated runtime: TBD")]

    def test_R_the_failure_is_printed(self, tmp_path, capsys):
        b = brief(tmp_path, "## Estimated runtime: TBD\n")
        assert prefire.report(b) is False
        assert "• " + RUNTIME_FAIL.format(line="## Estimated runtime: TBD") in capsys.readouterr().out

    def test_negative_control_a_missing_line_fails_as_before(self, tmp_path):
        fails = a2(prefire.check(brief(tmp_path, "## Repo: orchestrator\n")))
        assert len(fails) == 1 and fails[0].startswith("A2 SIZING — no '## Estimated runtime:' declared.")

    def test_negative_control_a_missing_line_under_a_micro_fire_trigger_passes_on_the_default(self, tmp_path,
                                                                                              capsys):
        b = brief(tmp_path, "## Micro-fire trigger: P0 infra — the queue is down\n")
        assert prefire.check(b) == []
        assert prefire.report(b, timeout=orchestrator.prefire_timeout(b)) is True
        out = capsys.readouterr().out
        assert "micro-fire: P0 infra — the queue is down; timeout 45 min (default)" in out

    def test_negative_control_under_the_floor_still_fails_as_sizing(self, tmp_path):
        fails = a2(prefire.check(brief(tmp_path, "## Estimated runtime: 12 min\n")))
        assert len(fails) == 1 and fails[0].startswith("A2 SIZING — declared estimate 12m is under the 30m floor")


# ── the CLI pass line: no route resolves anything there ─────────────────────────────────────────────────
def test_the_cli_names_what_the_runtime_line_asks(tmp_path, capsys):
    b = brief(tmp_path, "## Estimated runtime: 2-3 h\n")
    assert prefire.report(b) is True
    out = capsys.readouterr().out
    assert ("declared 120m (floor 30m); timeout 225 min (Estimated runtime × 1.25 — the fire applies "
            "TONI_TIMEOUT_MIN and the hard cap)") in out


def test_the_cli_with_no_runtime_line_says_the_default_applies(tmp_path, capsys):
    b = brief(tmp_path, "## Micro-fire trigger: P0 infra — the queue is down\n")
    assert prefire.report(b) is True
    assert "timeout: none declared — the fire's default" in capsys.readouterr().out



# ── found-and-left 1: the third parser — closed by ORCH-ADMISSION-PARSER-1 (tests/test_admission_parser.py) ──
def test_found_and_left_the_daemons_wall_reads_the_same_route_timeout(tmp_path):
    import admission
    b = brief(tmp_path, "## Estimated runtime: 2-3 h\n")
    assert admission.route_timeout(b, env={}) == orchestrator.resolve_timeout(b)

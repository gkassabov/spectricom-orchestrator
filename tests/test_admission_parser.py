"""ORCH-ADMISSION-PARSER-1 (S7-CORE-24) — the queue daemon's route wall reads a brief's timeout through the SAME
function as the route's own timeout.

Route 233 (8a2842c) gave the runtime line one parser (prefire.parse_declared_runtime) and made
orchestrator.parse_brief_timeout read it. admission.parse_brief_timeout — the route timeout inside the daemon's
kill (admission.route_wall, queue_daemon.py:1125) — stayed a restatement of the old '<n>-<m> m' grammar. So a
'2-3 h' brief got 180 min from the route and a wall built from the 45-min default: 110-145 min, below the
route's own timeout (233 handback, found-and-left 1).

  D1  admission.parse_brief_timeout: a '## TONI_TIMEOUT_MIN:' header > a '## Fire mechanism:' override > the
      runtime line through prefire.runtime_timeout. admission.requested_timeout: TONI_TIMEOUT_MIN in the
      environment > the brief's own > the default. orchestrator.parse_brief_timeout and
      orchestrator._requested_timeout return those two — one function each, called by both.
  P1  '2-3 h' -> a daemon wall derived from 180 (capped), not 45; '90-120 min' -> 150, unchanged; a
      'TONI_TIMEOUT_MIN: 40' header still wins. For each, the daemon's route timeout == the route's.
"""
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import admission  # noqa: E402
import orchestrator  # noqa: E402
import prefire  # noqa: E402

SHIPPED = ROOT / "config" / "repos.yaml"
# The wall 8a2842c's admission built for a '2-3 h' brief: 45 (default) + gate budget + 15 slack, in minutes.
# Route 233's handback, found-and-left 1 table.
WALL_ON_8A2842C_MIN = {"clinical-mp": 145, "yorsie": 120, "ai-foundation": 110, "orchestrator": 120}


@pytest.fixture(autouse=True)
def no_env_timeout(monkeypatch):
    """No TONI_TIMEOUT_MIN leaks in from the shell that runs the suite."""
    monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)


def brief(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "b.md"
    p.write_text("#!queue repo=orchestrator\n## Kanban: SCP_Kanban row 1\n" + body, encoding="utf-8")
    return p


# ── P1 · the daemon's wall ───────────────────────────────────────────────────────────────────────────────
class TestP1TheDaemonsWall:

    @pytest.mark.parametrize("repo", sorted(WALL_ON_8A2842C_MIN))
    def test_a_2_3_h_brief_gets_a_wall_derived_from_180_not_45(self, tmp_path, repo):
        b = brief(tmp_path, "## Estimated runtime: 2-3 h\n")
        assert admission.parse_brief_timeout(b) == 225
        w = admission.route_wall(b, repo, config_path=SHIPPED, env={})
        assert (w.route_timeout_s, w.route_timeout_source) == (180 * 60, "brief-declared")
        assert w.seconds == 180 * 60 + w.gate_budget_s + admission.ROUTE_WALL_SLACK_S
        assert w.seconds // 60 == WALL_ON_8A2842C_MIN[repo] + (180 - 45)
        assert (w.route_timeout_s // 60, w.route_timeout_source) == orchestrator.resolve_timeout(b)

    def test_negative_control_90_120_min_is_unchanged(self, tmp_path):
        b = brief(tmp_path, "## Estimated runtime: 90-120 min\n")
        assert admission.parse_brief_timeout(b) == 150, "the same as on 8a2842c"
        assert admission.route_timeout(b, env={}) == (150, "brief-declared") == orchestrator.resolve_timeout(b)

    def test_a_toni_timeout_min_header_still_wins_for_both(self, tmp_path):
        b = brief(tmp_path, "## TONI_TIMEOUT_MIN: 40\n## Estimated runtime: 2-3 h\n")
        assert admission.route_timeout(b, env={}) == (40, "brief-declared") == orchestrator.resolve_timeout(b)
        assert admission.route_wall(b, "orchestrator", config_path=SHIPPED, env={}).route_timeout_s == 40 * 60

    def test_a_fire_mechanism_override_still_wins_for_both(self, tmp_path):
        b = brief(tmp_path, "## Fire mechanism: queue TONI_TIMEOUT_MIN=75\n## Estimated runtime: 2-3 h\n")
        assert admission.route_timeout(b, env={}) == (75, "brief-declared") == orchestrator.resolve_timeout(b)

    def test_the_environment_still_wins_for_both(self, tmp_path, monkeypatch):
        b = brief(tmp_path, "## TONI_TIMEOUT_MIN: 40\n## Estimated runtime: 2-3 h\n")
        monkeypatch.setenv("TONI_TIMEOUT_MIN", "30")
        assert admission.route_timeout(b) == (30, "env-var") == orchestrator.resolve_timeout(b)

    def test_an_unreadable_environment_value_is_the_cap_for_the_wall_and_a_failure_for_the_route(
            self, tmp_path, monkeypatch):
        """As on 8a2842c: the wall takes the long side, the route fails at its own resolve_timeout."""
        b = brief(tmp_path, "## Estimated runtime: 60-80 min\n")
        monkeypatch.setenv("TONI_TIMEOUT_MIN", "abc")
        assert admission.route_timeout(b) == (180, "env-var 'abc' unreadable — the 180m cap")
        with pytest.raises(ValueError):
            orchestrator.resolve_timeout(b)
        assert orchestrator.prefire_timeout(b) is None

    def test_no_brief_is_the_default_and_the_daemons_fallback_wall_is_the_cap(self):
        assert admission.route_timeout(None, env={}) == (45, "default") == orchestrator.resolve_timeout(None)
        w = admission.route_wall(None, "", env={"TONI_TIMEOUT_MIN": str(admission.TIMEOUT_HARD_CAP_MIN)})
        assert (w.route_timeout_s, w.route_timeout_source) == (180 * 60, "env-var")


# Every runtime shape the corpus carries (233's grammar table), the hour forms, a line with no number, no line.
AGREE = [
    "## Estimated runtime: 75-95 min\n", "## Estimated runtime: 75–95 min\n", "## Estimated runtime: 90 min\n",
    "## Estimated runtime: 40 min\n", "## Estimated runtime: 45-90 min (HIGH-substrate bundle)\n",
    "## Estimated runtime: 60-100 min\n", "## Estimated runtime: 180 min (CODE PORTION ONLY)\n",
    "## Estimated runtime: 2-3 h\n", "## Estimated runtime: 2-3h\n", "## Estimated runtime: 3-4 hours Toni session\n",
    "## Estimated runtime: 1.5 hours\n", "## Estimated runtime: 1.5h\n", "## Estimated runtime: 2 hours\n",
    "## Estimated runtime: TBD\n", "", "## TONI_TIMEOUT_MIN: 162\n", "## TONI_TIMEOUT_MIN: 400\n",
    "## Fire mechanism: queue TONI_TIMEOUT_MIN=75\n## Estimated runtime: 2-3 h\n",
]


class TestP1TheDaemonAndTheRouteAgree:

    @pytest.mark.parametrize("body", AGREE)
    def test_the_daemons_route_timeout_is_the_routes(self, tmp_path, body):
        b = brief(tmp_path, body)
        assert admission.parse_brief_timeout(b) == orchestrator.parse_brief_timeout(b)
        assert admission.route_timeout(b, env={}) == orchestrator.resolve_timeout(b)

    def test_the_runtime_line_is_read_where_prefire_reads_it(self, tmp_path):
        """233 item 9: the route reads the runtime line anywhere in prefire's 6000-char header. The daemon read
        the first 4000, so a line past them was the 45-min default to the wall and 100 min to the route."""
        b = brief(tmp_path, "x" * 4100 + "\n## Estimated runtime: 60-80 min\n")
        assert admission.parse_brief_timeout(b) == 100 == orchestrator.parse_brief_timeout(b)


# ── D1 · no fourth copy ──────────────────────────────────────────────────────────────────────────────────
class TestD1OneFunction:

    def test_orchestrators_brief_reading_is_admissions(self, tmp_path, monkeypatch):
        b = brief(tmp_path, "## Estimated runtime: 60-80 min\n")
        monkeypatch.setattr(admission, "parse_brief_timeout", lambda p: 123)
        assert orchestrator.parse_brief_timeout(b) == 123
        assert orchestrator.resolve_timeout(b) == (123, "brief-declared")
        assert admission.route_timeout(b, env={}) == (123, "brief-declared")

    def test_orchestrators_precedence_is_admissions(self, tmp_path, monkeypatch):
        b = brief(tmp_path, "## Estimated runtime: 60-80 min\n")
        monkeypatch.setattr(admission, "requested_timeout", lambda brief, env=None: (321, "spy"))
        assert orchestrator.resolve_timeout(b) == (180, "spy")
        assert orchestrator.prefire_timeout(b) == (180, "spy", 321)
        assert admission.route_timeout(b, env={}) == (180, "spy")

    def test_the_runtime_line_is_prefires_parse(self, tmp_path, monkeypatch):
        b = brief(tmp_path, "## Estimated runtime: 2-3 h\n")
        monkeypatch.setattr(prefire, "parse_declared_runtime", lambda p: (10, 100))
        assert admission.parse_brief_timeout(b) == 125
        assert admission.route_wall(b, "orchestrator", config_path=SHIPPED, env={}).route_timeout_s == 125 * 60

    def test_the_override_headers_and_the_runtime_grammar_are_written_once(self):
        src = "\n".join((ROOT / f).read_text() for f in ("admission.py", "orchestrator.py", "prefire.py"))
        assert len(re.findall(r"\^## TONI_TIMEOUT_MIN:", src)) == 1
        assert len(re.findall(r"\^## Fire mechanism:\.\*TONI_TIMEOUT_MIN=", src)) == 1
        assert r"(\d+)\s*-\s*(\d+)\s*m" not in src, "the old '<n>-<m> m' grammar is gone"

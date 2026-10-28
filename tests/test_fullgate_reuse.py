# filename: tests/test_fullgate_reuse.py
"""Tests for ORCH-FULLGATE-CACHE-1 (S7-CORE-33 · D-S7CORE33-36 fix #4, Kanban row 404).

The nightly full gate re-ran the full unit suite on `989d814` one minute after route 337i had measured that very
tree (03:10 vs 03:11). `_full_gate_unit` now looks the tree up in the content-keyed cache first, and a judged,
fresh, FULL-suite measurement on the same `test_cmd` is its unit leg — said, never stored back. An on-demand
full gate is George's: `--trigger on-demand` needs `--requested-by <name>`.

  P1-3  a fresh judged full-suite content hit runs no suite command and reports `reused`; a 25 h old entry, a
        related-only entry, an unjudged one, or ORCH_FULLGATE_REUSE=off runs the suite             (TestP1_3*)
  P1-4  on-demand without --requested-by is refused; nightly is unaffected                         (TestP1_4*)

Harness: tests.test_gate_cost.FullGate — a real project repo and a real detached worktree; only the suite
commands are scripted. Module-level imports are existing symbols only (the RED run on HEAD collects).
"""

import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_gate_cost import REPO, TEST_CMD, UA, UB, FullGate, _git, _msgs, vitest  # noqa: E402


@pytest.fixture
def fg(tmp_path, monkeypatch):
    g = FullGate(tmp_path, monkeypatch)
    monkeypatch.delenv("ORCH_FULLGATE_REUSE", raising=False)     # FullGate turns reuse off for the older tests
    return g


def _cache(fg) -> dict:
    return json.loads((fg.archive / orchestrator.UNIT_BASELINE_CACHE_FILE).read_text())


def _edit_entry(fg, **fields):
    data = _cache(fg)
    (key, e), = data["entries"].items()
    e.update(fields)
    (fg.archive / orchestrator.UNIT_BASELINE_CACHE_FILE).write_text(json.dumps(data))


class TestP1_3Reuse:

    def test_a_fresh_judged_full_hit_runs_no_suite_and_says_reused(self, fg, caplog):
        fg.seed([])
        sha = _git(fg.repo, "rev-parse", "main")
        with caplog.at_level(logging.INFO, logger="orch"):
            assert fg.run() == 0
        assert "unit" not in fg.calls and "confirm" not in fg.calls, fg.calls
        u = fg.state()["unit"]
        assert u["outcome"] == "PASS" and u["reused"]["sha"] == sha
        assert u["detail"].startswith(f"reused measured run {sha[:7]}, ") or "reused measured run" in u["detail"]
        assert any(m.startswith(f"♻️ full-gate unit: reused measured run {sha[:7]} (") for m in _msgs(caplog)), \
            _msgs(caplog)

    def test_the_reused_leg_is_never_stored_back(self, fg):
        fg.seed([UA])
        before = _cache(fg)
        fg.run()
        assert _cache(fg) == before
        assert "cached" not in fg.state()["unit"]

    def test_the_outcome_is_the_chain_without_the_reused_entry(self, fg):
        """the reused entry is not its own baseline: the previous full gate (no failure) is, so UA is a suspect,
        confirmed alone exactly as today — and failing alone it is NEW."""
        fg.seed([])
        fg.run()                                   # previous full gate: nothing failing
        fg.seed([UA])                              # the tree's measurement now says UA fails
        fg.calls.clear()
        fg.confirm_out = vitest([UA], failed=1, total_tests=2, total_files=1)
        assert fg.run() == 1
        u = fg.state()["unit"]
        assert u["new"] == [UA] and u["baseline"]["source"] == "previous-full-gate"
        assert fg.calls[-1] == "confirm" and "unit" not in fg.calls

    def test_a_25h_old_entry_runs_the_suite(self, fg):
        fg.seed([])
        _edit_entry(fg, measured_at=(datetime.now() - timedelta(hours=25)).isoformat())
        fg.run()
        assert "unit" in fg.calls and "reused" not in fg.state()["unit"]

    def test_the_age_limit_is_repos_yaml_full_gate_reuse_max_h(self, fg):
        fg.seed([])
        _edit_entry(fg, measured_at=(datetime.now() - timedelta(hours=2)).isoformat())
        orchestrator.ACTIVE_REPO_CONFIG["full_gate_reuse_max_h"] = 1
        fg.run()
        assert "unit" in fg.calls

    def test_a_related_only_entry_runs_the_suite(self, fg):
        fg.seed([])
        _edit_entry(fg, scope="related")
        fg.run()
        assert "unit" in fg.calls and "reused" not in fg.state()["unit"]

    def test_an_unjudged_entry_runs_the_suite(self, fg):
        fg.seed([])
        _edit_entry(fg, clock=None)
        fg.run()
        assert "unit" in fg.calls

    def test_off_runs_the_suite(self, fg, monkeypatch):
        fg.seed([])
        monkeypatch.setenv("ORCH_FULLGATE_REUSE", "off")
        fg.run()
        assert "unit" in fg.calls

    def test_no_entry_runs_the_suite_as_today_and_says_why(self, fg, caplog):
        with caplog.at_level(logging.INFO, logger="orch"):
            fg.run()
        assert fg.calls[-1] == "unit"
        assert any(m.startswith("🧪 full-gate unit: ") and "the full suite (no measured run to reuse: no cached "
                   "measurement of this tree" in m for m in _msgs(caplog)), _msgs(caplog)

    def test_the_sit_leg_always_runs(self, fg):
        fg.seed([])
        fg.run()
        assert fg.calls[:4] == ["list", "batch", "batch", "batch"]


class TestP1_4OnDemand:

    @pytest.fixture
    def cli(self, monkeypatch):
        seen = []
        monkeypatch.setattr(orchestrator, "set_active_repo", lambda name: name)
        monkeypatch.setattr(orchestrator, "full_gate", lambda *a, **kw: seen.append((a, kw)) or 0)

        def run(*argv):
            monkeypatch.setattr(sys, "argv", ["orchestrator.py", "full-gate", "--repo", REPO, *argv])
            with pytest.raises(SystemExit) as e:
                orchestrator.main()
            return e.value.code, seen
        return run

    def test_on_demand_without_requested_by_is_refused(self, cli, capsys):
        code, seen = cli("--trigger", "on-demand")
        assert code == 2 and seen == []
        assert "D-S7CORE33-36" in capsys.readouterr().err

    def test_the_default_trigger_is_on_demand_and_refused_too(self, cli):
        code, seen = cli()
        assert code == 2 and seen == []

    def test_on_demand_with_requested_by_runs_and_records_it(self, cli):
        code, seen = cli("--trigger", "on-demand", "--requested-by", "George")
        assert code == 0 and len(seen) == 1 and seen[0][1].get("requested_by") == "George"

    def test_nightly_is_unaffected(self, cli):
        code, seen = cli("--trigger", "nightly")
        assert code == 0 and len(seen) == 1 and not seen[0][1].get("requested_by")

    def test_the_state_file_records_who_asked(self, tmp_path, monkeypatch):
        g = FullGate(tmp_path, monkeypatch)
        g.run(trigger="on-demand", requested_by="George")
        assert g.state()["requested_by"] == "George" and g.state()["trigger"] == "on-demand"

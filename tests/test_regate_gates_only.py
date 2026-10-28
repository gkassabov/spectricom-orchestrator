# filename: tests/test_regate_gates_only.py
"""Tests for ORCH-REGATE-GATE-ONLY-1 (S7-CORE-33 · D-S7CORE33-36 fix #3, Kanban row 406).

A route whose gate said BLOCKED(environment) — a rate limit, a leg timeout, an implausible clock — was re-gated by
firing Toni again on a brief that only cherry-picked the preserved commit (112r, 115r, 279, 281r, …): 1,104 min of
rework over 26 routes. A queue file with `## Re-gate of: <route branch> <sha>` now fires no executor: the
orchestrator checks the branch is at <sha> and that the route's recorded gate verdict (the `PRE-MERGE GATE:` git
note the route lane writes on the tip) is BLOCKED(environment), brings the branch onto the current merge target as a
landing does, runs the gates, and lands on PASS through the normal path. Anything else is refused with the reason.

  P3-1  a re-gate of an environment-blocked branch runs the three gates and no Toni              (TestP3_1*)
  P3-2  a re-gate of a FAIL(product) route is refused                                            (TestP3_2*)
  P3-3  a moved branch tip (≠ <sha>) is refused                                                  (TestP3_3*)
  P3-4  ORCH_REGATE_GATES_ONLY=off refuses the file                                              (TestP3_4*)

Harness: tests.test_gate_cost's lane — a real repo, the brief queued outside it, the leg commands scripted.
Module-level imports are existing symbols only (the RED run on HEAD collects).
"""

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_gate_cost import Legs, _activate, _git, _msgs, _repo  # noqa: E402

ROUTE = "orch-300-x"
BLOCKED_NOTE = "PRE-MERGE GATE: BLOCKED(environment) — sit: rate-limited"


@pytest.fixture
def rg(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    _activate(monkeypatch, tmp_path, repo)
    orch = tmp_path / "orch"
    (orch / "state").mkdir(parents=True)
    for name, val in (("IS_META_FIRE", False), ("RUN_PLAYWRIGHT", False), ("PREFIRE_BYPASS", True),
                      ("ORCH_DIR", orch), ("RUNNING_FILE", orch / "running.json"), ("WORKTREE_MODE", "single-stream")):
        monkeypatch.setattr(orchestrator, name, val)
    monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
    monkeypatch.setattr(orchestrator, "notify", lambda r: None)
    monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
    monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
    monkeypatch.delenv("ORCH_REGATE_GATES_ONLY", raising=False)
    fired = []

    def no_executor(*a, **k):
        fired.append(a)
        raise AssertionError("the executor command was built")
    for fn in ("fire_toni", "toni_child_env", "toni_guards"):
        monkeypatch.setattr(orchestrator, fn, no_executor)

    # route 300: one commit on its branch (code + handback), gated BLOCKED(environment), the note on its tip
    _git(repo, "checkout", "-q", "-b", ROUTE, "main")
    (repo / "src" / "a.ts").write_text("export const a = 300;\n")
    (repo / "briefs" / "300-x.handback.md").write_text("# 300 handback\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "fix: 300-x")
    tip = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    # main moved on since route 300 forked
    (repo / "docs" / "later.md").write_text("later\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "later work on main")

    class R:
        pass
    r = R()
    r.repo, r.tip, r.fired, r.tmp, r.monkeypatch = repo, tip, fired, tmp_path, monkeypatch
    r.legs = Legs(monkeypatch)

    def note(text=BLOCKED_NOTE, sha=None):
        _git(repo, "notes", "add", "-f", "-m", text, sha or tip)
    r.note = note

    def brief(branch=ROUTE, sha=None, name="300r-x-regate.md"):
        b = tmp_path / "queue" / name
        b.parent.mkdir(exist_ok=True)
        b.write_text(f"#!queue repo=cost-repo\n\n# 300 re-gate\n## Kanban: SCP_Kanban row 406\n"
                     f"## Re-gate of: {branch} {(sha or tip)[:8]}\n")
        return b
    r.brief = brief
    return r


def _run(r, b):
    return orchestrator.run_batch(b)


class TestP3_1GatesOnly:

    def test_an_environment_blocked_branch_runs_the_gates_and_no_executor(self, rg, caplog):
        rg.note()
        main_before = _git(rg.repo, "rev-parse", "main")
        with caplog.at_level(logging.INFO, logger="orch"):
            res = _run(rg, rg.brief())
        assert rg.fired == [], "the executor command was never built"
        assert (res.status, res.gate_outcome) == (orchestrator.Status.PASSED, "PASS"), res.error
        assert (rg.legs.count("build"), rg.legs.count("sit"), rg.legs.count("unit")) == (1, 1, 1)
        assert _git(rg.repo, "merge-base", "--is-ancestor", rg.tip, "main") == ""
        assert (rg.repo / "src" / "a.ts").read_text() == "export const a = 300;\n"
        assert (rg.repo / "docs" / "later.md").exists(), "brought onto the current merge target"
        assert _git(rg.repo, "rev-parse", "main") != main_before
        msgs = _msgs(caplog)
        assert any(m.startswith(f"🔁 Re-gate (gates only): {ROUTE}@{rg.tip[:7]} — prior verdict BLOCKED(environment)")
                   for m in msgs), msgs

    def test_the_handback_note_is_appended_by_the_orchestrator(self, rg):
        rg.note()
        _run(rg, rg.brief())
        hb = (rg.repo / "briefs" / "300-x.handback.md").read_text()
        assert hb.startswith("# 300 handback\n") and "Re-gate (orchestrator, gates only" in hb
        assert rg.tip[:7] in hb and "BLOCKED(environment)" in hb and "300r-x-regate" in hb

    def test_a_red_re_gate_does_not_merge(self, rg):
        rg.note()
        rg.legs.out["build"] = (2, "error TS2304: Cannot find name 'x'.\n")
        main_before = _git(rg.repo, "rev-parse", "main")
        res = _run(rg, rg.brief())
        assert res.status is not orchestrator.Status.PASSED and rg.fired == []
        assert _git(rg.repo, "rev-parse", "main") == main_before

    def test_a_conflict_with_the_merge_target_is_refused_typed(self, rg):
        rg.note()
        (rg.repo / "src" / "a.ts").write_text("export const a = 999;\n")
        _git(rg.repo, "commit", "-qam", "main changes a.ts too")
        main_before = _git(rg.repo, "rev-parse", "main")
        res = _run(rg, rg.brief())
        assert res.status is orchestrator.Status.FAILED and "RE-GATE REFUSED" in res.error and "conflict" in res.error
        assert _git(rg.repo, "rev-parse", "main") == main_before and rg.legs.calls == []
        assert _git(rg.repo, "status", "--porcelain") == "" and _git(rg.repo, "rev-parse", "--abbrev-ref",
                                                                     "HEAD") == "main"


class TestP3_2NotEnvironment:

    @pytest.mark.parametrize("note", [
        "PRE-MERGE GATE: FAIL(product) — unit: regression",
        "EXECUTOR EXIT: INCOMPLETE(timeout) — exit -1",
        "HANDBACK GUARD: INCOMPLETE(executor) — STOP at line 4",
    ])
    def test_anything_but_a_gate_environment_block_is_refused(self, rg, caplog, note):
        rg.note(note)
        main_before = _git(rg.repo, "rev-parse", "main")
        with caplog.at_level(logging.INFO, logger="orch"):
            res = _run(rg, rg.brief())
        assert res.status is orchestrator.Status.FAILED and "RE-GATE REFUSED" in res.error
        assert "not BLOCKED(environment)" in res.error
        assert rg.legs.calls == [] and rg.fired == [] and _git(rg.repo, "rev-parse", "main") == main_before

    def test_no_recorded_verdict_is_refused(self, rg):
        res = _run(rg, rg.brief())
        assert "RE-GATE REFUSED" in res.error and "no recorded gate verdict" in res.error
        assert rg.legs.calls == [] and rg.fired == []


class TestP3_3Moved:

    def test_a_moved_tip_is_refused(self, rg):
        rg.note()
        old = rg.tip
        _git(rg.repo, "checkout", "-q", ROUTE)
        (rg.repo / "src" / "a.ts").write_text("export const a = 301;\n")
        _git(rg.repo, "commit", "-qam", "moved")
        _git(rg.repo, "checkout", "-q", "main")
        res = _run(rg, rg.brief(sha=old))
        assert "RE-GATE REFUSED" in res.error and "moved" in res.error
        assert rg.legs.calls == [] and rg.fired == []

    def test_a_branch_that_is_gone_is_refused(self, rg):
        rg.note()
        res = _run(rg, rg.brief(branch="orch-no-such"))
        assert "RE-GATE REFUSED" in res.error and "does not exist" in res.error


class TestP3_4Off:

    def test_off_refuses_the_file(self, rg):
        rg.note()
        rg.monkeypatch.setenv("ORCH_REGATE_GATES_ONLY", "off")
        main_before = _git(rg.repo, "rev-parse", "main")
        res = _run(rg, rg.brief())
        assert res.status is orchestrator.Status.FAILED and "ORCH_REGATE_GATES_ONLY=off" in res.error
        assert rg.legs.calls == [] and rg.fired == [] and _git(rg.repo, "rev-parse", "main") == main_before

    def test_negative_control_a_normal_brief_still_fires_the_executor(self, rg):
        b = rg.tmp / "queue" / "301-y.md"
        b.parent.mkdir(exist_ok=True)
        b.write_text("#!queue repo=cost-repo\n\n# 301\n")
        with pytest.raises(AssertionError, match="executor command was built"):
            _run(rg, b)
        assert rg.fired

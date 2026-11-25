# filename: tests/test_depends_successor.py
"""ORCH-DEPENDS-SUCCESSOR-1 (Kanban 956; L-538; D-S7CORE62-14 — George 2026-11-25 11:37 ET "all recs").

A re-cut route lands under its r-successor's name (895 → 895r, 906 → 906r, 950 → 950r3). A brief whose
`## Depends-on:` names the original must not wait for a branch that will never merge.

  S1  the original never merged, its r-successor landed product → A11 passes, and the merged text names the successor.
  S2  no successor → unchanged: one A11 failure naming the original and its tray.
  S3  a successor whose branch exists but never merged → still waits.
  S4  a successor that merged its handback only (a STOP) does not meet it.
  S5  a different row is never a successor: `906` is not met by `9060r-…`.
  S6  numbered successors (`r2`, `r3`) count; the original merging is still enough on its own.
  S7  the daemon: queue [B (depends A), Ar] with A stopped → Ar fires, then B.

Same world as test_depends_on.py — every repo, queue and config under tmp_path, merges MADE with git.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import prefire  # noqa: E402
from test_depends_on import World, _git, _route, a11  # noqa: E402,F401

import pytest  # noqa: E402


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


def _briefs_only_route(repo: Path, branch: str) -> None:
    """A STOPPED route's merge: its brief and handback under briefs/, nothing else."""
    _git(repo, "checkout", "-q", "-b", branch)
    (repo / "briefs").mkdir(exist_ok=True)
    (repo / "briefs" / f"{branch}.handback.md").write_text("## STATUS: STOP (a)\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"stop: {branch}")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", branch)


class TestSuccessorMeetsDependsOn:

    def test_s1_a_landed_r_successor_meets_the_original(self, w):
        w.brief("000000906-voided-1", tray="held/_superseded")
        _route(w.repo, "orch-t-000000906-voided-1", merge=False)          # the original: branch, never merged
        _route(w.repo, "orch-t-000000906r-voided-1r")                      # its re-cut, landed
        b = w.brief("000000908-order-1", "000000906-voided-1")
        assert prefire.check(b) == []
        deps, why = prefire.dependency_status(b, w.queue, prefire.queue_repo)
        assert why is None and deps[0].merged and "as successor 000000906r-voided-1r" in deps[0].merged, deps

    def test_s2_no_successor_still_fails_naming_the_original(self, w):
        w.brief("000000906-voided-1", tray="failed")
        (fail,) = a11(prefire.check(w.brief("000000908-order-1", "000000906-voided-1")))
        assert "000000906-voided-1" in fail and "queue/failed/" in fail, fail

    def test_s3_an_unmerged_successor_does_not_meet_it(self, w):
        _route(w.repo, "orch-t-000000906r-voided-1r", merge=False)
        (fail,) = a11(prefire.check(w.brief("000000908-order-1", "000000906-voided-1")))
        assert "000000906-voided-1" in fail, fail

    def test_s4_a_handback_only_successor_does_not_meet_it(self, w):
        _briefs_only_route(w.repo, "orch-t-000000930r-title-1r")
        (fail,) = a11(prefire.check(w.brief("000000931-shape-1", "000000930-title-1")))
        assert "000000930-title-1" in fail, fail

    def test_s5_a_different_row_is_never_a_successor(self, w):
        _route(w.repo, "orch-t-0000009060r-other-1")
        _route(w.repo, "orch-t-000000906x-other-1")
        assert prefire.successor_stems(prefire.queue_repo("testrepo"), "000000906-voided-1") == []
        (fail,) = a11(prefire.check(w.brief("000000908-order-1", "000000906-voided-1")))
        assert "000000906-voided-1" in fail, fail

    def test_s6_numbered_successors_count_and_the_original_alone_is_enough(self, w):
        _route(w.repo, "orch-t-0000000950r3-sit-list-1r3")
        assert prefire.check(w.brief("0000000951-next-1", "0000000950-sit-list-1")) == []
        _route(w.repo, "orch-t-000000777-plain-1")
        deps, _ = prefire.dependency_status(w.brief("000000778-after-1", "000000777-plain-1"), w.queue, prefire.queue_repo)
        assert deps[0].merged and "successor" not in deps[0].merged, deps

    def test_successor_stems_lists_only_rN_of_the_same_row(self, w):
        for b in ("orch-t-000000906r-a", "orch-t-000000906r2-b", "orch-t-000000906r-3-recheck", "orch-t-0000009060r-c"):
            _route(w.repo, b, merge=False)
        got = prefire.successor_stems(prefire.queue_repo("testrepo"), "000000906-voided-1")
        assert got == ["000000906r-3-recheck", "000000906r-a", "000000906r2-b"], got
        assert prefire.successor_stems(prefire.queue_repo("testrepo"), "no-row-here") == []


class TestDaemonOrder:

    def test_s7_b_waits_on_ar_then_fires(self, w):
        w.brief("000000906-voided-1", tray="held/_superseded")
        _route(w.repo, "orch-t-000000906-voided-1", merge=False)
        w.brief("000000906r-voided-1r")
        w.brief("000000908-order-1", "000000906-voided-1")
        w.merges["000000906r-voided-1r"] = w.repo
        w.run_until_idle()
        assert w.fired == ["000000906r-voided-1r.md", "000000908-order-1.md"], w.fired

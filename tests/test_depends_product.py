# filename: tests/test_depends_product.py
"""Tests for ORCH-DEPENDS-PRODUCT-1 (ORCH-RELIABILITY-1 Brief 3 · S7-CORE-36 · D-S7CORE36-03).

`341b5a` fired while its Depends-on `341b5-…-refire` had merged only a STOP handback: canon_assert._landed's
detector 1 matched the merge commit. A Depends-on is now met only when the route brought at least one path outside
briefs_subdir to the merge target (canon_assert.route_landed_product; the gate's briefs-only predicate, A13). B6
keeps route_merged — a STOPPED route's brief is still retired.

  PD1  A merged (merge commit) with a product file ⇒ met; B merged with only briefs/B.handback.md ⇒ not met, the
       reason names "handback only"; C fast-forwarded with product ⇒ met (reflog, and branch-ref detectors)
  PD2  D4: X depends on B (handback-only) ⇒ X parked in queue/held/depends-on/ with the reason; the next brief taken
  PD3  B6 still retires B's brief
  PD4  ORCH_DEPENDS_PRODUCT=off ⇒ today's answers on every fixture
  F3.3 a re-fire landing the work under a new stem satisfies only briefs that name that stem

Every merged state is MADE with git (tests/test_depends_on.py's World), never mocked.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import canon_assert  # noqa: E402
import prefire  # noqa: E402
from tests.test_depends_on import World, _git, a11  # noqa: E402

HANDBACK_ONLY = "merged handback only (briefs/) — not met"


def _land(repo: Path, branch: str, files: dict, *, ff: bool = True) -> str:
    """A route: `branch` from main with one commit writing `files`, merged back (fast-forward, or a merge commit)."""
    _git(repo, "checkout", "-q", "-b", branch, "main")
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"route work on {branch}")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", *(() if ff else ("--no-ff", "-m", f"Merge branch '{branch}'")), branch)
    return _git(repo, "rev-parse", "main")


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    monkeypatch.delenv("ORCH_DEPENDS_PRODUCT", raising=False)
    return World(tmp_path, monkeypatch)


def _repo(w):
    return prefire.queue_repo("testrepo")


def _dep(w, stem):
    (d,), why = prefire.dependency_status(w.brief(f"9-needs-{stem}", stem), w.queue, prefire.queue_repo)
    assert why is None
    return d


class TestPD1Met:

    def test_a_merge_commit_with_a_product_file_is_met(self, w):
        _land(w.repo, "orch-t-a", {"src/a.py": "a\n", "briefs/a.handback.md": "hb\n"}, ff=False)
        assert canon_assert.route_landed_product(_repo(w), "a")[2] == "merge commit"
        assert _dep(w, "a").merged

    def test_a_handback_only_merge_is_not_met_and_says_so(self, w, capsys):
        _land(w.repo, "orch-t-b", {"briefs/b.handback.md": "STOPPED\n"}, ff=False)
        assert canon_assert.route_merged(_repo(w), "b") is not None, "it IS on main — _landed's answer"
        why = []
        assert canon_assert.route_landed_product(_repo(w), "b", "briefs", why) is None
        assert why == ["merged handback only (briefs/)"]
        d = _dep(w, "b")
        assert not d.merged and not d.queued and str(d) == f"b: {HANDBACK_ONLY} on testrepo/main"
        (fail,) = a11(prefire.check(w.queue / "9-needs-b.md"))
        assert HANDBACK_ONLY in fail, fail
        assert f"⛔ Depends-on b: {HANDBACK_ONLY}" in capsys.readouterr().out

    def test_a_fast_forward_with_product_is_met_by_the_reflog(self, w):
        _land(w.repo, "orch-t-c", {"src/c.py": "c\n"})
        assert canon_assert.route_landed_product(_repo(w), "c")[2] == "reflog merge into main"
        assert _dep(w, "c").merged

    def test_a_fast_forward_handback_only_is_not_met(self, w):
        _land(w.repo, "orch-t-c2", {"briefs/c2.handback.md": "hb\n"})
        assert not _dep(w, "c2").merged and _dep(w, "c2").landed_unmet == "merged handback only (briefs/)"

    def test_the_branch_ref_detector_reads_from_where_the_branch_was_created(self, w):
        _land(w.repo, "orch-t-e", {"src/e.py": "e\n"})
        _land(w.repo, "orch-t-f", {"briefs/f.handback.md": "hb\n"})
        _git(w.repo, "reflog", "expire", "--expire=now", "refs/heads/main")
        assert canon_assert.route_landed_product(_repo(w), "e")[2] == "branch ref merged into main"
        assert canon_assert.route_landed_product(_repo(w), "f") is None

    def test_an_unreadable_merge_is_not_met_and_not_called_handback_only(self, w):
        _land(w.repo, "orch-t-g", {"src/g.py": "g\n"})
        _git(w.repo, "reflog", "expire", "--expire=now", "--all")
        why = []
        assert canon_assert.route_merged(_repo(w), "g") is not None
        assert canon_assert.route_landed_product(_repo(w), "g", "briefs", why) is None
        assert "cannot be read" in why[0] and "handback" not in why[0]
        assert not _dep(w, "g").merged

    def test_the_repos_own_briefs_subdir_is_the_rule(self, w):
        import yaml
        cfg = yaml.safe_load(w.cfg.read_text())
        cfg["repos"]["testrepo"]["briefs_subdir"] = "yorsie/briefs"
        w.cfg.write_text(yaml.safe_dump(cfg))
        _land(w.repo, "orch-t-y", {"yorsie/briefs/y.handback.md": "hb\n"}, ff=False)
        _land(w.repo, "orch-t-z", {"briefs/z.md": "not this repo's briefs\n"}, ff=False)
        assert _dep(w, "y").landed_unmet == "merged handback only (yorsie/briefs/)"
        assert _dep(w, "z").merged


class TestPD2Held:

    @pytest.mark.parametrize("tray", ["done", ""], ids=["dep-in-done", "dep-still-in-queue"])
    def test_x_on_a_handback_only_b_is_held_with_the_reason_and_the_next_fires(self, w, tray):
        _land(w.repo, "orch-t-500b-dep", {"briefs/500b-dep.handback.md": "STOPPED\n"}, ff=False)
        w.brief("500b-dep", tray=tray)
        x = w.brief("501x-needs-b", "500b-dep")
        nxt = w.brief("502y-free")
        got = w.d._next_brief([p for p in (x, nxt)])
        assert got == nxt
        held = w.queue / "held" / "depends-on"
        assert (held / x.name).is_file() and not x.exists()
        assert HANDBACK_ONLY in (held / "501x-needs-b.reason").read_text()
        assert w.d.depends_waiting == {}


class TestPD3B6:

    def test_b6_still_retires_a_handback_only_routes_brief(self, w):
        _land(w.repo, "orch-t-600b-stopped", {"briefs/600b-stopped.handback.md": "STOPPED\n"}, ff=False)
        w.brief("600b-stopped")
        assert w.d.retire_merged_briefs() == 1
        assert not (w.queue / "600b-stopped.md").exists()


class TestPD4Off:

    def test_off_restores_todays_answers(self, w, monkeypatch):
        _land(w.repo, "orch-t-a", {"src/a.py": "a\n"}, ff=False)
        _land(w.repo, "orch-t-b", {"briefs/b.handback.md": "hb\n"}, ff=False)
        _land(w.repo, "orch-t-c", {"src/c.py": "c\n"})
        monkeypatch.setenv("ORCH_DEPENDS_PRODUCT", "off")
        for stem in ("a", "b", "c"):
            d = _dep(w, stem)
            today = canon_assert.route_merged(_repo(w), stem)
            assert d.merged == f"{today[0][:8]} [{today[2]}]" and d.landed_unmet is None, stem
        assert a11(prefire.check(w.queue / "9-needs-b.md")) == []


class TestF33NoAliasing:

    def test_a_refire_satisfies_only_briefs_that_name_its_stem(self, w):
        _land(w.repo, "orch-t-341b5-x", {"briefs/341b5-x.handback.md": "STOPPED\n"}, ff=False)
        _land(w.repo, "orch-t-341b5-x-refire", {"src/x.py": "x\n"}, ff=False)
        assert not _dep(w, "341b5-x").merged
        assert _dep(w, "341b5-x-refire").merged

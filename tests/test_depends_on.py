# filename: tests/test_depends_on.py
"""ORCH-DEPENDS-ON-1 — a brief that needs another route's code declares it, and is never fired before that route is
on its repo's merge target.

S7-CORE-33 · PDLC record v0-34 F-289 ("filename order is not dependency order — 309b ran on top of a STOPPED 309a")
· LESSONS L-184 · ACTIVE RULE #8 second half.

  P1  prefire A11: `## Depends-on: A`, A not merged → one A11 failure naming A and where its brief sits; A merged →
      none; a line that cannot be read → an A11 failure; no line → unchanged.
  P2  the daemon: queue [B (depends A), C, A] fires C, then A, then B — B stays in queue/ while A is queued, said
      WAITING once.
  P3  A in queue/failed/ (held/, nowhere) → B parked in queue/held/depends-on/ with its reason; no pause, the
      consecutive count unchanged, no failed / refused entry.
  P4  309a/309b replay: 309a STOPPED (in queue/failed/), 309b declaring it → 309b never fired.
  P5  one merged-route predicate (A13): canon_assert.route_merged — B6 retirement and A11 both ask it.

Every repo, queue and config is under tmp_path; every merged state is MADE with git, never mocked. The daemon runs
its real run_loop with `_run_route` stubbed — no subprocess fires.
"""

import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import canon_assert  # noqa: E402
import prefire  # noqa: E402
import queue_daemon  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


# ── git ──────────────────────────────────────────────────────────────────────────────────────────────────────────
def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True).stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-q", ".")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "checkout", "-q", "-b", "main")
    (path / "README.md").write_text("init")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")
    return path


def _route(repo: Path, branch: str, *, merge: bool = True) -> str:
    """What a route does to its repo: a branch with one commit, merged back to main (fast-forward) unless
    merge=False — a route that STOPPED. Returns the branch tip."""
    _git(repo, "checkout", "-q", "-b", branch)
    (repo / f"{branch}.py").write_text(f"work on {branch}")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"route work on {branch}")
    tip = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    if merge:
        _git(repo, "merge", "-q", branch)
    return tip


# ── the world: two repos, a queue with its trays, a READY Kanban row, prefire and the daemon pointed at them ──────
class World:
    def __init__(self, tmp_path: Path, monkeypatch):
        self.repo = _init_repo(tmp_path / "repo")           # testrepo, branch prefix orch-t
        self.other = _init_repo(tmp_path / "other")         # otherrepo, branch prefix orch-o
        self.orch = tmp_path / "orch"
        self.queue = self.orch / "queue"
        for sub in ("", "done", "failed", "held"):
            (self.queue / sub).mkdir(parents=True, exist_ok=True)
        (self.orch / "state").mkdir()
        canon = tmp_path / "canon"
        canon.mkdir()
        (canon / "SCP_Kanban_v0-1.md").write_text("| # | Item | State |\n|---|---|---|\n| 1 | x | READY |\n")
        self.cfg = tmp_path / "repos.yaml"
        self.cfg.write_text(yaml.safe_dump({"kanban_dir": str(canon), "repos": {
            "testrepo": {"project_dir": str(self.repo), "merge_target": "main", "branch_prefix": "orch-t"},
            "otherrepo": {"project_dir": str(self.other), "merge_target": "main", "branch_prefix": "orch-o"}}}))
        monkeypatch.setattr(prefire, "REPOS_CONFIG", self.cfg)
        monkeypatch.setattr(prefire, "QUEUE_DIR", self.queue, raising=False)
        self.state_file = tmp_path / "queue-state.json"
        for name, val in (("ORCH_DIR", self.orch), ("QUEUE_DIR", self.queue),
                          ("QUEUE_DONE", self.queue / "done"), ("QUEUE_FAILED", self.queue / "failed"),
                          ("QUEUE_STATE", self.state_file), ("REPOS_CONFIG", self.cfg),
                          ("LOG_DIR", tmp_path / "logs")):
            monkeypatch.setattr(queue_daemon, name, val)
        self.monkeypatch = monkeypatch
        self.fired: list[str] = []
        self.sleeps: list[tuple] = []
        self.merges: dict[str, Path] = {}       # stem → repo its stubbed route merges into
        self.codes: dict[str, int] = {}         # stem → the stubbed route's exit code (default 0)
        self._d = None

    def brief(self, stem: str, depends=None, *, tray: str = "", repo: str = "testrepo") -> Path:
        lines = [f"#!queue model=m effort=e repo={repo}", "", f"# {stem}", "## Kanban: SCP_Kanban row 1",
                 "## Estimated runtime: 60-90 min", "## Test scope: targeted (D-S7CORE30-05)"]
        if depends is not None:
            lines.append(f"## Depends-on: {depends}")
        p = self.queue / tray / f"{stem}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    @property
    def d(self) -> "queue_daemon.QueueDaemon":
        if self._d is None:
            d = queue_daemon.QueueDaemon()
            d.start_running = True
            d.config.update(cooldown_seconds=0, model="m", effort="e")

            def _run_route(cmd, batch_name, log_path):
                self.fired.append(batch_name)
                Path(log_path).parent.mkdir(parents=True, exist_ok=True)
                Path(log_path).write_text("route output\n")
                stem = Path(batch_name).stem
                if stem in self.merges:
                    _route(self.merges[stem], f"orch-t-{stem}" if self.merges[stem] == self.repo else f"orch-o-{stem}")
                return self.codes.get(stem, 0)
            d._run_route = _run_route
            self._d = d
        return self._d

    def run_until_idle(self):
        """The real run_loop; it ends at its first sleep (nothing left it may fire)."""
        def _sleep(s):
            self.sleeps.append((self.d.status, s))
            self.d.status = "stopped"
        self.monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep))
        self.d.run_loop()

    def state(self) -> dict:
        return json.loads(self.state_file.read_text()) if self.state_file.exists() else {}


@pytest.fixture
def w(tmp_path, monkeypatch) -> World:
    return World(tmp_path, monkeypatch)


def a11(fails: list) -> list:
    return [f for f in fails if f.startswith("A11")]


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# P1 · prefire A11
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════
class TestP1PrefireA11:

    @pytest.mark.parametrize("tray, where", [("", "queue/"), ("failed", "queue/failed/"),
                                             ("held/s7x", "queue/held/s7x/"), ("done", "queue/done/")])
    def test_an_unmerged_dependency_is_one_a11_failure_naming_it_and_where_it_sits(self, w, tray, where):
        w.brief("400a-first", tray=tray)
        b = w.brief("400b-second", "400a-first")
        fails = prefire.check(b)
        assert len(fails) == 1 and fails[0].startswith("A11 DEPENDS-ON"), fails
        assert "400a-first" in fails[0] and where in fails[0], fails[0]
        assert "testrepo/main" in fails[0], fails[0]

    def test_a_dependency_whose_brief_is_nowhere_says_nowhere(self, w):
        b = w.brief("400b-second", "400a-first")
        (fail,) = a11(prefire.check(b))
        assert "400a-first" in fail and "nowhere" in fail, fail

    def test_a_branch_that_never_merged_is_not_merged(self, w):
        w.brief("400a-first", tray="failed")
        _route(w.repo, "orch-t-400a-first", merge=False)       # STOPPED: the branch exists, main never got it
        (fail,) = a11(prefire.check(w.brief("400b-second", "400a-first")))
        assert "400a-first" in fail and "queue/failed/" in fail

    def test_a_merged_dependency_passes(self, w):
        w.brief("400a-first", tray="done")
        _route(w.repo, "orch-t-400a-first")
        assert prefire.check(w.brief("400b-second", "`400a-first`")) == []

    def test_every_unmet_stem_is_named_in_the_one_failure_and_a_merged_one_is_not(self, w):
        _route(w.repo, "orch-t-400a-first")
        w.brief("400c-third")
        b = w.brief("400d-fourth", "400a-first, 400c-third, 400x-gone")
        fails = prefire.check(b)
        assert len(fails) == 1, fails
        assert "400c-third" in fails[0] and "400x-gone" in fails[0] and "400a-first" not in fails[0], fails[0]

    def test_at_repo_is_looked_for_on_that_repo_not_the_briefs_own(self, w):
        _route(w.repo, "orch-t-77-elsewhere")                   # merged on testrepo — not the repo named
        b = w.brief("400b-second", "77-elsewhere@otherrepo")
        (fail,) = a11(prefire.check(b))
        assert "77-elsewhere" in fail and "otherrepo/main" in fail and "nowhere" in fail, fail
        _route(w.other, "orch-o-77-elsewhere")
        assert prefire.check(b) == []

    @pytest.mark.parametrize("line", [
        "", "   ", "400a first", "400a-first.md", "400a-first@", "400a-first,, 400c-third", "400a-first@nope",
        "400a-first (the schema)", "400b-second"])
    def test_a_line_that_cannot_be_read_is_an_a11_refusal(self, w, line):
        _route(w.repo, "orch-t-400a-first")
        _route(w.repo, "orch-t-400c-third")
        fails = prefire.check(w.brief("400b-second", line))
        assert len(fails) == 1 and fails[0].startswith("A11 DEPENDS-ON"), (line, fails)
        assert "Depends-on" in fails[0]

    def test_two_depends_on_lines_are_an_a11_refusal(self, w):
        _route(w.repo, "orch-t-400a-first")
        b = w.brief("400b-second", "400a-first")
        b.write_text(b.read_text() + "## Depends-on: 400a-first\n")
        (fail,) = prefire.check(b)
        assert fail.startswith("A11 DEPENDS-ON") and "2 '## Depends-on:' lines" in fail, fail

    def test_a_dependency_without_a_repo_to_look_in_is_an_a11_refusal(self, w):
        b = w.brief("400b-second", "400a-first")
        b.write_text(b.read_text().replace("#!queue model=m effort=e repo=testrepo\n", ""))
        (fail,) = prefire.check(b)
        assert fail.startswith("A11 DEPENDS-ON") and "repo" in fail, fail

    def test_control_no_line_is_unchanged_and_asks_git_nothing(self, w, monkeypatch):
        asked = []
        monkeypatch.setattr(canon_assert, "route_merged", lambda *a: asked.append(a), raising=False)
        assert prefire.check(w.brief("400b-second")) == []
        assert asked == []

    def test_the_pass_line_names_a11_and_what_each_dependency_merged_as(self, w, capsys):
        _route(w.repo, "orch-t-400a-first")
        tip = _git(w.repo, "rev-parse", "main")
        assert prefire.report(w.brief("400b-second", "400a-first")) is True
        out = capsys.readouterr().out
        assert "  Assertions: ✅ A1/A2/A8/A9/A10/A11 pass — SCP_Kanban row 1 READY" in out
        assert f"  Depends-on: 400a-first merged on testrepo/main ({tip[:8]} [" in out, out

    def test_the_refusal_is_listed_like_the_others(self, w, capsys):
        assert prefire.report(w.brief("400b-second", "400a-first")) is False
        assert "  • A11 DEPENDS-ON — " in capsys.readouterr().out


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# P2 · the daemon fires the next eligible brief while a dependency is still queued
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════
class TestP2DaemonOrder:

    def test_selection_passes_over_a_brief_waiting_on_a_queued_dependency(self, w, capsys):
        b = w.brief("501-b-needs-a", "503-a-later")
        c = w.brief("502-c-free")
        w.brief("503-a-later")
        assert w.d._next_brief(w.d._scan_queue()) == c
        assert b.is_file(), "B stays in queue/"
        out = capsys.readouterr().out
        assert out.count("WAITING depends-on 503-a-later") == 1, out
        assert w.d.status != "paused"

    def test_the_loop_fires_c_then_a_then_b_and_says_waiting_once(self, w, capsys):
        w.brief("501-b-needs-a", "503-a-later")
        w.brief("502-c-free")
        w.brief("503-a-later")
        w.merges["503-a-later"] = w.repo                       # A's route merges as it runs
        w.run_until_idle()
        assert w.fired == ["502-c-free.md", "503-a-later.md", "501-b-needs-a.md"]
        out = capsys.readouterr().out
        waiting = [l for l in out.splitlines() if "WAITING depends-on" in l]
        assert len(waiting) == 1 and "501-b-needs-a.md" in waiting[0] and "503-a-later" in waiting[0], waiting
        assert w.d.consecutive_count == 3 and w.d.failed == []

    def test_after_the_dependency_merges_the_waiting_brief_is_selected(self, w):
        b = w.brief("501-b-needs-a", "503-a-later")
        w.brief("503-a-later")
        assert w.d._next_brief(w.d._scan_queue()).name == "503-a-later.md"
        (w.queue / "503-a-later.md").rename(w.queue / "done" / "503-a-later.md")
        _route(w.repo, "orch-t-503-a-later")
        assert w.d._next_brief(w.d._scan_queue()) == b

    def test_every_queued_brief_waiting_fires_nothing_and_does_not_pause(self, w):
        """A cycle: each waits on the other, both queued. Nothing fires; the loop idles (sleeps), never pauses."""
        w.brief("601-x", "602-y")
        w.brief("602-y", "601-x")
        w.run_until_idle()
        assert w.fired == [] and w.sleeps == [("running", 10)]
        assert sorted(w.state()["depends_waiting"]) == ["601-x.md", "602-y.md"]

    def test_control_briefs_without_a_line_fire_in_filename_order(self, w):
        for stem in ("703-c", "701-a", "702-b"):
            w.brief(stem)
        w.run_until_idle()
        assert w.fired == ["701-a.md", "702-b.md", "703-c.md"]


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# P3 · a dependency the queue can no longer merge: the brief is held, never failed, never a pause
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════
class TestP3Held:

    @pytest.mark.parametrize("tray, where", [("failed", "queue/failed/"), ("held/s7x", "queue/held/s7x/"),
                                             (None, "nowhere")])
    def test_the_brief_is_moved_to_held_depends_on_with_its_reason(self, w, tray, where, capsys):
        if tray is not None:
            w.brief("600a-dep", tray=tray)
        w.brief("601b-needs-dep", "600a-dep")
        w.d.consecutive_count = 2
        w.run_until_idle()
        held = w.queue / "held" / "depends-on" / "601b-needs-dep.md"
        assert w.fired == [] and held.is_file() and not (w.queue / "601b-needs-dep.md").exists()
        reason = (w.queue / "held" / "depends-on" / "601b-needs-dep.reason").read_text()
        assert "600a-dep" in reason and where in reason, reason
        assert w.sleeps == [("running", 10)], "not paused"
        assert w.d.consecutive_count == 2 and w.d.failed == [] and w.d.refused == []
        assert not (w.queue / "failed" / "601b-needs-dep.md").exists()
        st = w.state()
        assert st["paused_reason"] is None and st["depends_waiting"] == {}
        out = capsys.readouterr().out
        assert "601b-needs-dep.md" in out and "HELD depends-on 600a-dep" in out, out

    def test_one_unmet_dependency_the_queue_cannot_merge_holds_even_beside_a_queued_one(self, w):
        w.brief("600a-dep", tray="failed")
        w.brief("602c-dep")
        w.brief("601b-needs-both", "600a-dep, 602c-dep")
        assert w.d._next_brief(w.d._scan_queue()).name == "602c-dep.md"
        assert (w.queue / "held" / "depends-on" / "601b-needs-both.md").is_file()

    def test_a_chain_is_held_link_by_link_in_one_scan(self, w):
        w.brief("600a-dep", tray="failed")
        w.brief("601b-needs-a", "600a-dep")
        w.brief("602c-needs-b", "601b-needs-a")
        assert w.d._next_brief(w.d._scan_queue()) is None
        assert sorted(p.name for p in (w.queue / "held" / "depends-on").glob("*.md")) == [
            "601b-needs-a.md", "602c-needs-b.md"]
        assert "queue/held/depends-on/" in (w.queue / "held" / "depends-on" / "602c-needs-b.reason").read_text()

    def test_a_brief_that_will_not_move_is_passed_over_never_fired_and_said_once(self, w, monkeypatch, capsys):
        w.brief("600a-dep", tray="failed")
        w.brief("601b-needs-dep", "600a-dep")
        c = w.brief("602c-free")
        monkeypatch.setattr(queue_daemon, "_safe_move", lambda src, dst: False)
        assert w.d._next_brief(w.d._scan_queue()) == c
        assert w.d._next_brief(w.d._scan_queue()) == c
        out = capsys.readouterr().out
        assert out.count("601b-needs-dep.md") == 1, out

    def test_status_shows_waiting_and_held_by_dependency_briefs(self, w, capsys):
        w.brief("600a-dep", tray="failed")
        w.brief("601b-needs-dep", "600a-dep")
        w.brief("602-x", "603-y")
        w.brief("603-y", "602-x")
        w.run_until_idle()
        capsys.readouterr()
        assert queue_daemon.main(["status"]) == 0
        line1, rest = capsys.readouterr().out.split("\n", 1)
        assert "depends-on" in line1 and "602-x.md ← 603-y" in line1 and "601b-needs-dep.md" in line1, line1
        r = json.loads(rest)
        assert r["depends_waiting"] == {"602-x.md": ["603-y"], "603-y.md": ["602-x"]}
        (held,) = r["depends_held"]
        assert held["file"] == "601b-needs-dep.md" and "600a-dep" in held["reason"]


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# P4 · F-289 replayed: 309b ran on top of a STOPPED 309a
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════
class TestP4Replay309:

    def test_309b_is_never_fired_while_309a_is_stopped(self, w):
        _route(w.repo, "orch-t-309a-member-function-1", merge=False)   # 309a STOPPED: its branch, never on main
        w.brief("309a-member-function-1", tray="failed")
        b = w.brief("309b-home-bp-platform-1", "309a-member-function-1")
        w.brief("309c-member-partner-results-1")
        w.run_until_idle()
        assert w.fired == ["309c-member-partner-results-1.md"]
        assert (w.queue / "held" / "depends-on" / b.name).is_file()
        held = w.queue / "held" / "depends-on" / b.name
        (fail,) = prefire.check(held)              # and fired by hand, A11 refuses it
        assert fail.startswith("A11 DEPENDS-ON") and "309a-member-function-1" in fail and "queue/failed/" in fail


# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════
# P5 · A13: one merged-route predicate
# ═════════════════════════════════════════════════════════════════════════════════════════════════════════════════
class TestP5OnePredicate:

    def test_b6_retirement_and_a11_both_ask_route_merged(self, w, monkeypatch):
        real = getattr(canon_assert, "route_merged", None)
        assert real is not None, "canon_assert.route_merged — the one merged-route predicate"
        asked = []

        def spy(repo, brief):
            asked.append((repo.name, Path(brief).stem))
            return real(repo, brief)
        monkeypatch.setattr(canon_assert, "route_merged", spy)
        w.brief("800a-done")
        _route(w.repo, "orch-t-800a-done")
        assert w.d.retire_merged_briefs() == 1                         # B6
        assert ("testrepo", "800a-done") in asked
        asked.clear()
        assert prefire.check(w.brief("800b-next", "800a-done")) == []  # A11
        assert asked == [("testrepo", "800a-done")]
        asked.clear()
        assert w.d._next_brief(w.d._scan_queue()).name == "800b-next.md"   # D4, through A11's own reading
        assert asked == [("testrepo", "800a-done")]

    def test_no_second_git_reader(self):
        """`grep -n "route_merged(\\|_landed(" *.py`: _landed is called by route_merged alone; route_merged by
        check_queue_trunk_invariants (B6) and prefire.dependency_status (A11, and the daemon through it)."""
        ca = (ROOT / "canon_assert.py").read_text()
        body = ca.split("def check_queue_trunk_invariants(")[1].split("\ndef ")[0]
        assert "route_merged(" in body and "_landed(" not in body
        assert ca.count("_landed(") == 2, "the definition and route_merged's call"
        pf = (ROOT / "prefire.py").read_text()
        assert "canon_assert.route_merged(" in pf and "subprocess" not in pf and "_landed(" not in pf   # ORCH-RELIABILITY-1: route_landed_product
        qd = (ROOT / "queue_daemon.py").read_text()
        sel = qd.split("    def _next_brief(")[1].split("\n    def ")[0]
        assert "prefire.dependency_status(" in sel and "subprocess" not in sel and "git(" not in sel
        assert "_landed(" not in qd and "_landed(" not in pf

    def test_control_force_still_bypasses_every_prefire_check(self):
        src = (ROOT / "orchestrator.py").read_text()
        assert "if not PREFIRE_BYPASS and not prefire.report(batch_file" in src

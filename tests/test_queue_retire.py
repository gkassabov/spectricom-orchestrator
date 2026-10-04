# filename: tests/test_queue_retire.py
"""QUEUE-RETIRE-1 — retirement is the merge's job, not the scheduler's exit path.

S7-CORE-15 · D-S7CORE14-02 · boot assert B6.

RESOLVER-1 merged as f1359634 on 21 Sep 15:59. The daemon that would have retired its brief was
killed after the merge and before the bookkeeping, the brief stayed in queue/ for five days, and
the 26 Sep restart re-fired an already-merged route. The window was never the defect: the process
that merges is the only process that knows the merge happened, and it did not own the retirement.

These tests hold the three halves of the fix:
  T1  the merge retires its own brief, bounded to briefs that are actually in queue/;
  T2  the scheduler's moves became no-ops on a missing source (the file is normally gone);
  T3  the daemon checks the trunk invariant before the first batch and clears what it names.

Every merged state below is MADE, never mocked: the tests run `git merge` and then ask the
predicate what it can see.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import canon_assert
import orchestrator
import queue_daemon
from canon_assert import QueueRepo, check_queue_trunk_invariants


# ═══════════════════════════════════════════════════════════════════════════════════════
# git fixtures — a repo whose history has the shapes the real lanes produce
# ═══════════════════════════════════════════════════════════════════════════════════════
def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    return r.stdout.strip()


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", ".")
    _git(path, "config", "user.email", "test@test.com")
    _git(path, "config", "user.name", "Test")
    _git(path, "checkout", "-q", "-b", "main")
    (path / "README.md").write_text("init")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "init")
    return path


def _commit(repo: Path, name: str, msg: str):
    (repo / name).write_text(msg)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", msg)


def _run_route(repo: Path, branch: str, *, merge: bool = True, drift: bool = False,
               keep_branch: bool = True, expire_reflog: bool = False) -> str:
    """Do to `repo` what a route does: branch, commit, merge back to main. Returns main's tip.

    drift=True makes main move first, so the merge is a real merge commit instead of the
    fast-forward the clinical-mp lane normally produces.
    """
    _git(repo, "checkout", "-q", "-b", branch)
    _commit(repo, f"{branch}.py", f"route work on {branch}")
    _git(repo, "checkout", "-q", "main")
    if drift:
        _commit(repo, "drift.py", "main moved while the route ran")
    if merge:
        _git(repo, "merge", branch, "--no-edit")
    if not keep_branch:
        _git(repo, "branch", "-D", branch)
    if expire_reflog:
        _git(repo, "reflog", "expire", "--expire=all", "--all")
    return _git(repo, "rev-parse", "main")


@pytest.fixture
def repo(tmp_path) -> Path:
    return _init_repo(tmp_path / "repo")


@pytest.fixture
def queue(tmp_path) -> Path:
    q = tmp_path / "queue"
    for sub in ("", "done", "failed", "held"):
        (q / sub).mkdir(parents=True, exist_ok=True)
    return q


@pytest.fixture
def route(repo) -> QueueRepo:
    return QueueRepo(name="testrepo", path=repo, merge_target="main", branch_prefix="orch-t")


def _queued(queue: Path, stem: str) -> Path:
    f = queue / f"{stem}.md"
    f.write_text("#!queue model=claude-opus-5 effort=high repo=testrepo\n\n# a brief\n")
    return f


# ═══════════════════════════════════════════════════════════════════════════════════════
# AC-QR-01 — the predicate. Empty when clean; names brief and commit when not.
# ═══════════════════════════════════════════════════════════════════════════════════════
class TestTrunkInvariant:

    def test_clean_queue_returns_empty(self, queue, route):
        """Nothing queued at all — the predicate's empty case."""
        assert check_queue_trunk_invariants(queue, route) == []

    def test_queued_brief_whose_route_never_merged_is_clean(self, queue, route):
        """The ordinary state: a brief waiting to fire. Its branch does not even exist."""
        _queued(queue, "39-resolver-1")
        assert check_queue_trunk_invariants(queue, route) == []

    def test_merged_brief_names_the_brief_and_the_merge_commit(self, queue, route):
        """AC-QR-01 — the failure is DEMONSTRATED: a real merge, then the predicate is asked.

        This is RESOLVER-1's shape exactly: the route merged, the brief is still in queue/.
        """
        brief = _queued(queue, "39-resolver-1")
        tip = _run_route(route.path, "orch-t-39-resolver-1")

        violations = check_queue_trunk_invariants(queue, route)

        assert len(violations) == 1
        v = violations[0]
        assert v.brief == "39-resolver-1.md"
        assert v.path == brief
        assert v.branch == "orch-t-39-resolver-1"
        assert v.repo == "testrepo"
        assert v.commit == tip                      # the commit that already carries it
        assert "route work" in v.subject
        assert v.brief in str(v) and v.commit[:8] in str(v)

    def test_route_branch_that_has_not_merged_is_not_a_violation(self, queue, route):
        """A red gate leaves the branch unmerged. Nothing landed ⇒ nothing to retire."""
        _queued(queue, "10-rm-i-013")
        _run_route(route.path, "orch-t-10-rm-i-013", merge=False)
        assert check_queue_trunk_invariants(queue, route) == []

    def test_the_brief_being_committed_on_main_is_not_evidence(self, queue, route):
        """The trap this predicate must not fall into.

        Briefs are committed to their repo BEFORE the route fires (`brief(s7core14):
        RESOLVER-1, MEDS-UI-2` @ 8a9b6f46). A predicate keyed on file presence would call
        every staged brief merged and retire work that never ran.
        """
        _queued(queue, "42-not-yet-fired")
        (route.path / "briefs").mkdir()
        _commit(route.path, "briefs/42-not-yet-fired.md", "brief(s7): stage 42 before firing")
        assert check_queue_trunk_invariants(queue, route) == []

    def test_detector_merge_commit(self, queue, route):
        """Strongest detector, isolated: branch deleted AND reflog expired."""
        _queued(queue, "50-merge-commit-lane")
        tip = _run_route(route.path, "orch-t-50-merge-commit-lane",
                         drift=True, keep_branch=False, expire_reflog=True)
        (v,) = check_queue_trunk_invariants(queue, route)
        assert v.commit == tip
        assert v.evidence == "merge commit"

    def test_detector_reflog_covers_the_fast_forward_lane(self, queue, route):
        """The clinical-mp lane merges fast-forward and deletes the branch — `merge orch-mp-40-…:
        Fast-forward` in main's reflog is then the only record that the merge happened."""
        _queued(queue, "40-meds-ui-2")
        tip = _run_route(route.path, "orch-t-40-meds-ui-2", keep_branch=False)
        (v,) = check_queue_trunk_invariants(queue, route)
        assert v.commit == tip
        assert v.evidence.startswith("reflog merge")
        assert _git(route.path, "rev-parse", "--verify", "--quiet", "orch-t-40-meds-ui-2") == ""

    def test_detector_branch_ref_covers_the_meta_fire_lane(self, queue, route):
        """The `--ff-only` self-mod lane never deletes its branch; RESOLVER-1's own branch tip
        IS f1359634. Reflog expired so only the ref can answer."""
        _queued(queue, "39-resolver-1")
        tip = _run_route(route.path, "orch-t-39-resolver-1", expire_reflog=True)
        (v,) = check_queue_trunk_invariants(queue, route)
        assert v.commit == tip
        assert v.evidence == "branch ref merged into main"

    def test_a_merge_that_was_reset_away_is_not_a_violation(self, queue, route):
        """A reflog entry outlives a reset. Reachability is re-checked, so a merge that is no
        longer on main does not authorise a retirement."""
        _queued(queue, "51-reset-away")
        before = _git(route.path, "rev-parse", "main")
        _run_route(route.path, "orch-t-51-reset-away", keep_branch=False)
        _git(route.path, "reset", "--hard", before)
        assert check_queue_trunk_invariants(queue, route) == []

    def test_scheduler_trays_are_not_scanned(self, queue, route):
        """done/, failed/ and held/ are the scheduler's trays. A brief parked there is not
        queued — and re-reporting one would make T3 move it onto itself forever."""
        for tray in ("done", "failed", "held"):
            (queue / tray / "39-resolver-1.md").write_text("#!queue repo=testrepo\n")
        _run_route(route.path, "orch-t-39-resolver-1")
        assert check_queue_trunk_invariants(queue, route) == []

    def test_unreadable_repo_is_never_a_violation(self, queue, tmp_path):
        """Fail closed: a violation authorises a retirement, so 'cannot tell' must mean 'no'."""
        _queued(queue, "39-resolver-1")
        not_a_repo = QueueRepo(name="gone", path=tmp_path / "does-not-exist",
                               merge_target="main", branch_prefix="orch-t")
        assert check_queue_trunk_invariants(queue, not_a_repo) == []

    def test_a_brief_naming_another_repo_is_not_looked_for_here(self, queue, route):
        """Two repos can share a branch prefix; neither may answer for the other's routes."""
        brief = queue / "60-elsewhere.md"
        brief.write_text("#!queue repo=some-other-repo\n")
        _run_route(route.path, "orch-t-60-elsewhere")
        assert check_queue_trunk_invariants(queue, route) == []

    def test_a_brief_naming_no_repo_belongs_to_the_repo_asked_about(self, queue, route):
        """The same default the scheduler applies when it fires a header-less brief."""
        (queue / "61-no-header.md").write_text("# a brief with no #!queue line\n")
        _run_route(route.path, "orch-t-61-no-header")
        (v,) = check_queue_trunk_invariants(queue, route)
        assert v.brief == "61-no-header.md"

    def test_missing_queue_dir_is_clean(self, tmp_path, route):
        assert check_queue_trunk_invariants(tmp_path / "no-queue", route) == []

    def test_predicate_still_does_not_touch_the_fire_path(self):
        """canon_assert stays disk+git only — the rule test_canon_assert.py already pins, restated
        here because QUEUE-RETIRE-1 is the change most tempted to break it."""
        src = Path(canon_assert.__file__).read_text()
        assert "import orchestrator" not in src


# ═══════════════════════════════════════════════════════════════════════════════════════
# AC-QR-03 — the bound. Only a batch file that resolves inside queue/ is ever moved.
# ═══════════════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def orch_queue(queue, monkeypatch):
    # raising=False so that on unmodified code these tests fail where the behaviour is
    # missing, not where the fixture is — the red must name the defect, not the harness.
    monkeypatch.setattr(orchestrator, "QUEUE_DIR", queue, raising=False)
    monkeypatch.setattr(orchestrator, "QUEUE_DONE", queue / "done", raising=False)
    return queue


class TestRetireBatchFileBound:

    def test_queued_batch_moves_to_done(self, orch_queue):
        brief = _queued(orch_queue, "39-resolver-1")
        dst = orchestrator.retire_batch_file(brief)
        assert dst == orch_queue / "done" / "39-resolver-1.md"
        assert dst.is_file() and not brief.exists()

    def test_batch_passed_by_path_is_never_moved(self, orch_queue, tmp_path):
        """The DATE-7 invocation shape:
        `orchestrator.py run ~/spectricom-clinical-mp/briefs/41-….md --repo clinical-mp`."""
        briefs = tmp_path / "spectricom-clinical-mp" / "briefs"
        briefs.mkdir(parents=True)
        elsewhere = briefs / "41-date-7-the-fifth-site-the-labs-due-column.md"
        elsewhere.write_text("# brief")

        assert orchestrator.retire_batch_file(elsewhere) is None
        assert elsewhere.is_file()
        assert list((orch_queue / "done").iterdir()) == []

    def test_a_brief_already_in_a_tray_does_not_move_again(self, orch_queue):
        parked = orch_queue / "done" / "39-resolver-1.md"
        parked.write_text("# brief")
        assert orchestrator.retire_batch_file(parked) is None
        assert parked.is_file()

    def test_missing_batch_file_is_not_an_error(self, orch_queue):
        assert orchestrator.retire_batch_file(orch_queue / "gone.md") is None


# ═══════════════════════════════════════════════════════════════════════════════════════
# AC-QR-02 — RESOLVER-1 reproduced: the merge retires the brief with the scheduler absent.
# AC-QR-03 — the same merge, both directions of the bound.
# ═══════════════════════════════════════════════════════════════════════════════════════
def _no_scheduler(monkeypatch):
    """Prevent the daemon's bookkeeping from running AT ALL — if the brief reaches done/ it is
    because the merging process put it there."""
    def boom(*a, **k):
        raise AssertionError("the scheduler must not be the one that retires")
    monkeypatch.setattr(queue_daemon, "_safe_move", boom, raising=False)


class TestMergeRetiresItsOwnBrief:

    def test_merge_retires_the_queued_brief_with_no_daemon_involved(self, repo, orch_queue, monkeypatch):
        """AC-QR-02. The RESOLVER-1 state, minus the daemon: a real merge happens, nothing
        afterwards is allowed to run, and the brief must already be in queue/done/."""
        _no_scheduler(monkeypatch)
        brief = _queued(orch_queue, "39-resolver-1")
        _git(repo, "checkout", "-q", "-b", "orch-orch-39-resolver-1")
        _commit(repo, "resolver.py", "feat(cds): RESOLVER-1")
        _git(repo, "checkout", "-q", "main")

        assert orchestrator._self_mod_auto_merge(repo, "orch-orch-39-resolver-1",
                                                 batch_file=brief) is True

        assert not brief.exists(), "the merge did not retire its own brief"
        assert (orch_queue / "done" / "39-resolver-1.md").is_file()
        assert "RESOLVER-1" in _git(repo, "log", "--oneline", "main")

    def test_merge_of_a_batch_outside_the_queue_moves_nothing(self, repo, orch_queue, monkeypatch, tmp_path):
        """AC-QR-03, the other direction — byte-identical to today for the path lane."""
        _no_scheduler(monkeypatch)
        briefs = tmp_path / "spectricom-clinical-mp" / "briefs"
        briefs.mkdir(parents=True)
        elsewhere = briefs / "41-date-7-the-fifth-site-the-labs-due-column.md"
        elsewhere.write_text("# brief")
        _git(repo, "checkout", "-q", "-b", "orch-orch-41-date-7")
        _commit(repo, "labs.py", "feat(labs): DATE-7")
        _git(repo, "checkout", "-q", "main")

        assert orchestrator._self_mod_auto_merge(repo, "orch-orch-41-date-7",
                                                 batch_file=elsewhere) is True

        assert elsewhere.is_file(), "a batch passed by path must never be moved"
        assert list((orch_queue / "done").iterdir()) == []

    def test_no_commits_to_merge_does_not_retire(self, repo, orch_queue, monkeypatch):
        """Nothing merged ⇒ the trunk invariant has nothing to say. The scheduler's bookkeeping
        still owns this outcome, exactly as before."""
        _no_scheduler(monkeypatch)
        brief = _queued(orch_queue, "52-no-changes")
        _git(repo, "branch", "orch-orch-52-no-changes")

        assert orchestrator._self_mod_auto_merge(repo, "orch-orch-52-no-changes",
                                                 batch_file=brief) is True
        assert brief.is_file()

    def test_a_refused_merge_retires_nothing(self, repo, orch_queue, monkeypatch):
        """[ORCH-1] still decides: a red gate means no merge, and therefore no retirement."""
        _no_scheduler(monkeypatch)
        brief = _queued(orch_queue, "53-red-gate")
        _git(repo, "checkout", "-q", "-b", "orch-orch-53-red-gate")
        _commit(repo, "x.py", "work")
        _git(repo, "checkout", "-q", "main")

        assert orchestrator._self_mod_auto_merge(repo, "orch-orch-53-red-gate",
                                                 gate_outcome="FAIL", batch_file=brief) is False
        assert brief.is_file()

    def test_the_route_lane_retires_at_its_merge_site(self):
        """Structural, for the site a unit test cannot reach without a live Toni: the route
        lane's retirement sits inside the merge-succeeded branch, after the merge is known good
        and before `git branch -d`."""
        src = Path(orchestrator.__file__).read_text()
        body = src.split("def _run_batch_inner(")[1]
        merged_at = body.index("🔀 Merged {branch_name}")
        retire_at = body.index("retire_batch_file(batch_file)", merged_at)
        delete_at = body.index("git branch -d {branch_name}", merged_at)
        assert merged_at < retire_at < delete_at

    def test_self_mod_lane_retires_only_after_a_successful_merge(self):
        src = Path(orchestrator.__file__).read_text()
        body = src.split("def _self_mod_auto_merge(")[1].split("\ndef ")[0]
        assert body.index("Self-mod auto-merge: brought") < body.index("retire_batch_file(batch_file)")

    def test_run_batch_passes_the_batch_file_to_the_self_mod_merge(self):
        """Reachability of the T1 call in the lane that actually fires this repo."""
        src = Path(orchestrator.__file__).read_text()
        assert "batch_file=batch_file" in src.split("merged = _self_mod_auto_merge(")[1][:200]


# ═══════════════════════════════════════════════════════════════════════════════════════
# AC-QR-05 — the scheduler's three moves are no-ops on a missing source.
# ═══════════════════════════════════════════════════════════════════════════════════════
class TestSchedulerMovesAreIdempotent:

    def test_safe_move_on_a_missing_source_is_a_no_op(self, tmp_path):
        assert queue_daemon._safe_move(tmp_path / "gone.md", tmp_path / "done" / "gone.md") is False

    def test_safe_move_still_moves_a_file_that_is_there(self, tmp_path):
        src = tmp_path / "b.md"
        src.write_text("x")
        assert queue_daemon._safe_move(src, tmp_path / "done" / "b.md") is True
        assert (tmp_path / "done" / "b.md").is_file() and not src.exists()

    def test_cancel_current_survives_an_already_retired_brief(self, daemon):
        """Call site 1 of 3 (cancel_current). The move is gone; the failed ENTRY is not —
        state bookkeeping stays the scheduler's."""
        d, queue, _ = daemon
        d.current_batch = {"file": "39-resolver-1.md", "started_at": "2026-09-21T15:59:00"}
        assert not (queue / "39-resolver-1.md").exists()

        assert d.cancel_current() == {"ok": True, "status": "cancelled"}
        assert d.failed[-1]["file"] == "39-resolver-1.md"
        assert d.failed[-1]["reason"] == "cancelled by user"

    def test_no_bare_shutil_move_is_left_in_the_daemon(self):
        """Call sites 2 and 3 (run_loop's completed / failed moves) run only inside a live
        fire, so they are pinned structurally: every move in this file goes through _safe_move,
        and _safe_move is the function the two tests above exercise."""
        src = Path(queue_daemon.__file__).read_text()
        body = src.split("def _safe_move(")[1].split("\ndef ")[0]
        assert body.count("shutil.move(") == 1
        assert src.count("shutil.move(") == 1, "a move outside _safe_move can still raise"
        for site in ("_safe_move(batch_file, QUEUE_FAILED",
                     "_safe_move(next_batch, QUEUE_DONE",
                     "_safe_move(next_batch, QUEUE_FAILED"):
            assert site in src, f"missing idempotent move at {site}"


# ═══════════════════════════════════════════════════════════════════════════════════════
# AC-QR-04 / AC-QR-07 — daemon start is the caller, and it is idempotent.
# ═══════════════════════════════════════════════════════════════════════════════════════
@pytest.fixture
def daemon(tmp_path, queue, repo, monkeypatch):
    """A QueueDaemon whose queue, trays, state and repo config are all under tmp_path."""
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "repos.yaml").write_text(json.dumps({"repos": {"testrepo": {
        "project_dir": str(repo), "merge_target": "main", "branch_prefix": "orch-t"}}}))
    monkeypatch.setattr(queue_daemon, "QUEUE_DIR", queue)
    monkeypatch.setattr(queue_daemon, "QUEUE_DONE", queue / "done")
    monkeypatch.setattr(queue_daemon, "QUEUE_FAILED", queue / "failed")
    monkeypatch.setattr(queue_daemon, "QUEUE_STATE", tmp_path / "queue-state.json")
    monkeypatch.setattr(queue_daemon, "REPOS_CONFIG", cfg / "repos.yaml", raising=False)
    d = queue_daemon.QueueDaemon()
    d.config["repo"] = "testrepo"
    return d, queue, repo


class TestDaemonStartRetires:

    def test_start_retires_an_already_merged_brief_and_says_so(self, daemon, capsys):
        """AC-QR-04. The 26 Sep restart, with the check in front of it."""
        d, queue, repo = daemon
        brief = _queued(queue, "39-resolver-1")
        tip = _run_route(repo, "orch-t-39-resolver-1")

        assert d.retire_merged_briefs() == 1

        assert not brief.exists()
        assert (queue / "done" / "39-resolver-1.md").is_file()
        out = capsys.readouterr().out
        assert "39-resolver-1.md" in out and tip[:8] in out

    def test_a_second_start_retires_nothing(self, daemon):
        """Idempotent — done/ is not scanned, so the second pass has nothing to find."""
        d, queue, repo = daemon
        _queued(queue, "39-resolver-1")
        _run_route(repo, "orch-t-39-resolver-1")
        assert d.retire_merged_briefs() == 1
        assert d.retire_merged_briefs() == 0

    def test_start_leaves_a_brief_that_has_not_merged_alone(self, daemon):
        d, queue, repo = daemon
        brief = _queued(queue, "10-rm-i-013")
        _run_route(repo, "orch-t-10-rm-i-013", merge=False)
        assert d.retire_merged_briefs() == 0
        assert brief.is_file()

    def test_the_repo_checked_is_the_one_the_brief_names(self, daemon):
        """A queue is multi-repo. The brief's own `#!queue repo=` decides which repo's merge
        target its route is looked for on; a repo that is not in config/repos.yaml is skipped,
        not guessed at — even when this repo happens to hold a branch of the same name."""
        d, queue, repo = daemon
        (queue / "60-elsewhere.md").write_text("#!queue repo=not-in-config\n")
        _run_route(repo, "orch-t-60-elsewhere")
        # [ORCH-YORSIE-SAFETY-1] no default repo is added: the only repo named is not configured
        assert [r.name for r in d.queue_repos()] == []
        assert d.retire_merged_briefs() == 0
        assert (queue / "60-elsewhere.md").is_file()

    def test_run_loop_checks_before_the_first_batch(self):
        """AC-QR-07 reachability: the non-test caller is QueueDaemon.run_loop, and it calls the
        predicate before the loop that fires anything — not after, where the old move lived."""
        src = Path(queue_daemon.__file__).read_text()
        body = src.split("    def run_loop(self):")[1]
        assert body.index("self.retire_merged_briefs()") < body.index("while self.status")

    def test_check_command_reports_without_moving(self, daemon):
        """The second caller: `python3 queue_daemon.py check` — boot assert B6 as a command,
        replacing the two commands a human ran by hand. Report only."""
        d, queue, repo = daemon
        brief = _queued(queue, "39-resolver-1")
        _run_route(repo, "orch-t-39-resolver-1")
        (v,) = d.find_merged_briefs()
        assert v.brief == "39-resolver-1.md"
        assert brief.is_file(), "the report path must not move anything"


# ═══════════════════════════════════════════════════════════════════════════════════════
# The header parse the queue lane depends on — unchanged behaviour, one implementation.
# ═══════════════════════════════════════════════════════════════════════════════════════
class TestBatchHeader:

    def test_header_tokens(self, tmp_path):
        f = tmp_path / "b.md"
        f.write_text("#!queue model=claude-opus-5 effort=high repo=orchestrator\n# body\n")
        assert queue_daemon._parse_batch_header(f) == {
            "model": "claude-opus-5", "effort": "high", "repo": "orchestrator"}

    def test_no_header_and_unreadable_file_are_both_empty(self, tmp_path):
        f = tmp_path / "b.md"
        f.write_text("# just a brief\n")
        assert queue_daemon._parse_batch_header(f) == {}
        assert queue_daemon._parse_batch_header(tmp_path / "nope.md") == {}
        (tmp_path / "empty.md").write_text("")
        assert queue_daemon._parse_batch_header(tmp_path / "empty.md") == {}

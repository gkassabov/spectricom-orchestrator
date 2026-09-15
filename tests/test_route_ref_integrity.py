# filename: tests/test_route_ref_integrity.py
"""Tests for [ORCH-10] — a route whose HEAD moved must FAIL, not report `passed`.

The incident (2026-09-15, clinical-mp / PLANDEF-1): a `git checkout main` run by a
human in the route's own working directory, 84s after the fire, put the executor's
commit on `main`. The orchestrator looked at its branch, correctly found no changes,
and returned `passed | gate: not run` — a commit reached `main` with no build gate,
no SIT gate and no unit baseline gate.

Two states must never look alike, and these tests pin both:
  "I ran, and chose to change nothing."  -> passed (no changes)   [AC-O10-02]
  "My branch is not where I left it."    -> tampered              [AC-O10-01]
"""

import json
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator


# ═══════════════════════════════════════════════════════
# HARNESS
# ═══════════════════════════════════════════════════════
def _git(cmd: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)


def _init_repo(path: Path):
    _git("git init", path)
    _git("git config user.email test@test.com", path)
    _git("git config user.name Test", path)
    _git("git symbolic-ref HEAD refs/heads/main", path)
    (path / "README.md").write_text("init\n")
    _git("git add -A", path)
    _git('git commit -m "init"', path)


def _refs(path: Path) -> dict:
    """Every ref -> sha. The AC-O10-04 "no ref was modified" witness."""
    out = _git("git show-ref", path).stdout
    return {l.split(None, 1)[1]: l.split(None, 1)[0] for l in out.splitlines() if l.strip()}


def _head_ref(path: Path) -> str:
    return _git("git symbolic-ref --quiet HEAD", path).stdout.strip()


class Route:
    """One simulated route: a repo, a brief, and a recorded verdict."""

    def __init__(self, proj: Path, brief: Path, archive: Path):
        self.proj = proj
        self.brief = brief
        self.archive = archive
        self.gate_calls = []
        self.result = None


@pytest.fixture
def route(tmp_path, monkeypatch):
    proj = tmp_path / "repo"
    proj.mkdir()
    _init_repo(proj)
    briefs_dir = proj / "briefs"
    briefs_dir.mkdir()
    brief = briefs_dir / "batch-orch10.md"
    brief.write_text("- id: B1\n  title: demo\n\n## Estimated runtime: 45-75 min\n")
    # Method note / S7-CORE-8: the brief is committed pre-fire. An untracked brief is swept
    # into the route's own `git add -A` and turns every no-change run into a change run.
    _git("git add -A", proj)
    _git('git commit -m "chore(briefs): stage batch-orch10"', proj)
    archive = tmp_path / "archive"

    monkeypatch.setattr(orchestrator, "PROJECT_ROOT", proj)
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG", {"briefs_subdir": "briefs"})
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "testrepo")
    monkeypatch.setattr(orchestrator, "BRANCH_PREFIX", "orch")
    monkeypatch.setattr(orchestrator, "MERGE_TARGET", "main")
    monkeypatch.setattr(orchestrator, "IS_META_FIRE", False)
    monkeypatch.setattr(orchestrator, "RUN_PLAYWRIGHT", False)
    monkeypatch.setattr(orchestrator, "SIT_ARCHIVE_DIR", archive)
    monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
    monkeypatch.setattr(orchestrator, "notify", lambda r: None)
    monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
    monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
    monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
    return Route(proj, brief, archive)


def fire(route, monkeypatch, executor, gate=orchestrator.GateOutcome.PASS):
    """Run one route. `executor(proj)` stands in for Toni and returns its exit code."""

    def _fake_gate(repo_path, branch_name=None):
        route.gate_calls.append((str(repo_path), branch_name))
        return orchestrator.GateVerdict(outcome=gate, gate="build", signal=None)

    monkeypatch.setattr(orchestrator, "run_pre_merge_gates", _fake_gate)
    monkeypatch.setattr(orchestrator, "fire_toni",
                        lambda target, proj: (executor(proj), "toni-test.log"))
    route.result = orchestrator._run_batch_inner(
        route.brief, route.proj, orchestrator.datetime.now(), worktree=None
    )
    return route.result


# ── executors ────────────────────────────────────────────
def quiet(proj):
    """RED-5's shape: ran, chose to change nothing, stayed on its own branch."""
    return 0


def works(proj):
    """The ordinary shape: a commit on the route's own branch."""
    (proj / "feature.txt").write_text("work\n")
    _git("git add -A", proj)
    _git('git commit -m "feat: work"', proj)
    return 0


def tampered_with_commit(proj):
    """The incident's exact shape: HEAD moved to main, and a commit made there."""
    _git("git checkout main", proj)
    (proj / "leak.txt").write_text("landed on main\n")
    _git("git add -A", proj)
    _git('git commit -m "fix(care-plans): carry action ids (PLANDEF-1)"', proj)
    return 0


def tampered_no_commit(proj):
    """HEAD moved, nothing committed. Still not a run we can report on."""
    _git("git checkout main", proj)
    return 0


def detached(proj):
    """HEAD moved off the branch onto no ref at all."""
    _git("git checkout --detach HEAD", proj)
    return 0


# ═══════════════════════════════════════════════════════
# AC-O10-01 — HEAD moved off the route branch ⇒ tampered
# ═══════════════════════════════════════════════════════
class TestTamperedVerdict:

    def test_head_moved_reports_tampered_not_passed(self, route, monkeypatch):
        """AC-O10-01: the run is `tampered` — neither `passed` nor `failed`."""
        r = fire(route, monkeypatch, tampered_no_commit)
        assert r.status is orchestrator.Status.TAMPERED
        assert r.status is not orchestrator.Status.PASSED
        assert r.status is not orchestrator.Status.FAILED
        assert r.no_changes is False, "a tampered run is not a no-changes run"

    def test_tampered_run_runs_no_gate(self, route, monkeypatch):
        """AC-O10-01: no gate is run on a repo the route does not own."""
        r = fire(route, monkeypatch, tampered_with_commit)
        assert route.gate_calls == []
        assert r.gate_outcome is None

    def test_tampered_run_performs_no_merge(self, route, monkeypatch):
        """AC-O10-01: `main` does not advance from anything the orchestrator does."""
        before = _refs(route.proj)["refs/heads/main"]
        fire(route, monkeypatch, tampered_no_commit)
        assert _refs(route.proj)["refs/heads/main"] == before

    def test_log_names_expected_and_found_ref(self, route, monkeypatch, caplog):
        """AC-O10-01: the log names BOTH refs — the one expected and the one found."""
        with caplog.at_level("ERROR"):
            fire(route, monkeypatch, tampered_no_commit)
        assert "refs/heads/orch-batch-orch10" in caplog.text
        assert "refs/heads/main" in caplog.text
        assert "expected HEAD on" in caplog.text
        assert "found HEAD on" in caplog.text

    def test_log_names_the_sha_the_branch_sits_at_now(self, route, monkeypatch, caplog):
        """AC-O10-01 / S2: the branch's current SHA is in the report."""
        with caplog.at_level("ERROR"):
            fire(route, monkeypatch, tampered_no_commit)
        sha = _refs(route.proj)["refs/heads/orch-batch-orch10"]
        assert sha[:7] in caplog.text

    def test_detached_head_is_tampered_and_says_so(self, route, monkeypatch, caplog):
        """A HEAD detached mid-route is tampered; the report does not print an empty ref."""
        with caplog.at_level("ERROR"):
            r = fire(route, monkeypatch, detached)
        assert r.status is orchestrator.Status.TAMPERED
        assert "(detached HEAD)" in caplog.text


# ═══════════════════════════════════════════════════════
# AC-O10-02 — the legitimate no-changes run is untouched
# ═══════════════════════════════════════════════════════
class TestLegitimateNoChangeRun:
    """S4. This is the case RED-5 and PLANDEF-1's first attempt both relied on:
    a route that returns on its own branch with no commits. It must behave exactly
    as it did before [ORCH-10] existed."""

    def test_no_changes_still_passes(self, route, monkeypatch):
        """AC-O10-02: `passed`, flagged no_changes, never tampered."""
        r = fire(route, monkeypatch, quiet)
        assert r.status is orchestrator.Status.PASSED
        assert r.no_changes is True
        assert r.tampered is None

    def test_no_changes_runs_no_gate_and_no_merge(self, route, monkeypatch):
        """AC-O10-02: no gate, no merge — as before."""
        before = _refs(route.proj)["refs/heads/main"]
        fire(route, monkeypatch, quiet)
        assert route.gate_calls == []
        assert _refs(route.proj)["refs/heads/main"] == before

    def test_no_changes_keeps_its_old_wording_and_cleanup(self, route, monkeypatch, caplog):
        """AC-O10-02: same log line, same return-to-main, same branch deletion."""
        with caplog.at_level("WARNING"):
            fire(route, monkeypatch, quiet)
        assert "Toni produced no changes" in caplog.text
        assert orchestrator.TAMPER_VERDICT not in caplog.text
        assert _head_ref(route.proj) == "refs/heads/main"
        assert "refs/heads/orch-batch-orch10" not in _refs(route.proj)

    def test_no_changes_final_status_is_the_old_line(self, route, monkeypatch, caplog):
        """AC-O10-02: `passed | gate: not run`, with no TAMPERED qualifier."""
        with caplog.at_level("INFO"):
            fire(route, monkeypatch, quiet)
        assert "FINAL STATUS: passed | gate: not run" in caplog.text
        assert f"not run ({orchestrator.TAMPER_VERDICT}" not in caplog.text


# ═══════════════════════════════════════════════════════
# AC-O10-03 — the ordinary route with commits is untouched
# ═══════════════════════════════════════════════════════
class TestOrdinaryRouteUnchanged:

    def test_commits_on_branch_still_gate_then_merge(self, route, monkeypatch):
        """AC-O10-03 / [ORCH-1]: gate runs, then the merge happens on PASS."""
        before = _refs(route.proj)["refs/heads/main"]
        r = fire(route, monkeypatch, works)
        assert r.status is orchestrator.Status.PASSED
        assert r.tampered is None
        assert len(route.gate_calls) == 1
        assert route.gate_calls[0][1] == "orch-batch-orch10"
        assert r.gate_outcome == "PASS"
        assert _refs(route.proj)["refs/heads/main"] != before, "merge did not land"

    def test_red_gate_still_withholds_the_merge(self, route, monkeypatch):
        """[ORCH-1] gate-then-merge: a red gate still leaves the target tip alone."""
        before = _refs(route.proj)["refs/heads/main"]
        r = fire(route, monkeypatch, works, gate=orchestrator.GateOutcome.FAIL_PRODUCT)
        assert r.status is orchestrator.Status.FAILED
        assert r.tampered is None
        assert _refs(route.proj)["refs/heads/main"] == before
        assert "refs/heads/orch-batch-orch10" in _refs(route.proj), "branch not preserved"

    def test_branch_advancing_is_not_mistaken_for_a_stray_ref(self, route, monkeypatch):
        """S3: the route's OWN branch moving is the point of the exercise, not damage."""
        r = fire(route, monkeypatch, works)
        assert r.status is orchestrator.Status.PASSED


# ═══════════════════════════════════════════════════════
# AC-O10-04 — the incident's exact shape: detect, never repair
# ═══════════════════════════════════════════════════════
class TestIncidentShape:

    def test_names_the_offending_sha_and_the_ref_it_landed_on(self, route, monkeypatch, caplog):
        """AC-O10-04: the report names the SHA(s) and the ref they landed on."""
        with caplog.at_level("ERROR"):
            fire(route, monkeypatch, tampered_with_commit)
        leaked = _git("git rev-parse --short refs/heads/main", route.proj).stdout.strip()
        assert leaked in caplog.text
        assert "commits on a ref this route did not own: refs/heads/main" in caplog.text
        assert "PLANDEF-1" in caplog.text, "the offending subject line is quoted"

    def test_no_ref_is_modified_by_the_orchestrator(self, route, monkeypatch):
        """AC-O10-04: every ref, and HEAD itself, is byte-identical after the run.

        S3: a wrong automatic repair on `main` is far worse than a loud stop, so the
        orchestrator resets nothing, reverts nothing, and moves nothing."""
        def snapshot_after_tamper(proj):
            tampered_with_commit(proj)
            snapshot_after_tamper.refs = _refs(proj)
            snapshot_after_tamper.head = _head_ref(proj)
            return 0

        fire(route, monkeypatch, snapshot_after_tamper)
        assert _refs(route.proj) == snapshot_after_tamper.refs
        assert _head_ref(route.proj) == snapshot_after_tamper.head

    def test_the_route_branch_is_not_deleted(self, route, monkeypatch):
        """The no-changes path does `git branch -D`; the tampered path must not."""
        fire(route, monkeypatch, tampered_with_commit)
        assert "refs/heads/orch-batch-orch10" in _refs(route.proj)

    def test_stray_commits_are_reported_structurally(self, route, monkeypatch):
        """The SHAs reach the archive, not only the human-readable log."""
        fire(route, monkeypatch, tampered_with_commit)
        entry = json.loads((route.archive / "orchestrator-unit-log.json").read_text())[-1]
        assert len(entry["stray_commits"]) == 1
        stray = entry["stray_commits"][0]
        assert stray["ref"] == "refs/heads/main"
        assert stray["now"] == _refs(route.proj)["refs/heads/main"]
        assert len(stray["commits"]) == 1

    def test_tamper_path_issues_no_ref_writing_git_command(self):
        """Structural guard: the [ORCH-10] section is read-only by construction.

        Detection code that can write a ref is one bad branch away from becoming the
        automatic repair S3 forbids."""
        src = Path(orchestrator.__file__).read_text()
        start = src.index("# [ORCH-10] ROUTE REF INTEGRITY")
        end = src.index("def _gate_status_label", start)
        # Scoped to the CODE: the section's header comment quotes the incident's own
        # `git checkout main`, and a guard that trips on its own explanation guards nothing.
        section = "\n".join(l for l in src[start:end].splitlines()
                            if not l.lstrip().startswith("#"))
        for forbidden in ("git checkout", "git branch -", "git merge", "git reset",
                          "git revert", "git cherry-pick", "git update-ref", "git commit"):
            assert forbidden not in section, f"[ORCH-10] must not run `{forbidden}`"


# ═══════════════════════════════════════════════════════
# AC-O10-05 — the verdict is distinct and greppable
# ═══════════════════════════════════════════════════════
class TestVerdictIsDistinct:

    def test_final_status_line_is_distinct_and_greppable(self, route, monkeypatch, caplog):
        """AC-O10-05. Sample line:

        🏁 FINAL STATUS: tampered | gate: not run (TAMPERED — route ref moved)
        """
        with caplog.at_level("INFO"):
            fire(route, monkeypatch, tampered_with_commit)
        line = next(l for l in caplog.text.splitlines() if "FINAL STATUS" in l)
        assert line.endswith("FINAL STATUS: tampered | gate: not run (TAMPERED — route ref moved)")
        assert "FINAL STATUS: passed" not in caplog.text
        assert "FAIL(product)" not in line

    def test_status_value_differs_from_passed_and_failed(self):
        """AC-O10-05: a distinct enum member, not a re-used one."""
        assert orchestrator.Status.TAMPERED.value == "tampered"
        assert orchestrator.Status.TAMPERED not in (
            orchestrator.Status.PASSED, orchestrator.Status.FAILED, orchestrator.Status.BLOCKED)
        assert orchestrator.TAMPER_VERDICT == "TAMPERED"
        assert orchestrator.TAMPER_VERDICT not in [o.value for o in orchestrator.GateOutcome]

    def test_unit_log_entry_carries_the_tampered_verdict(self, route, monkeypatch):
        """AC-O10-05: greppable in orchestrator-unit-log.json."""
        fire(route, monkeypatch, tampered_with_commit)
        log_file = route.archive / "orchestrator-unit-log.json"
        assert orchestrator.TAMPER_VERDICT in log_file.read_text()
        entry = json.loads(log_file.read_text())[-1]
        assert entry["verdict"] == "TAMPERED"
        assert entry["passed"] is False
        assert entry["signal"] == "route-ref-moved"
        assert entry["expected_ref"] == "refs/heads/orch-batch-orch10"
        assert entry["found_ref"] == "refs/heads/main"

    def test_unit_log_honest_entries_never_carry_the_verdict_key(self, route, monkeypatch):
        """The grep only surfaces tampered runs — a clean run leaves the file absent."""
        fire(route, monkeypatch, works)
        log_file = route.archive / "orchestrator-unit-log.json"
        if log_file.exists():
            for entry in json.loads(log_file.read_text()):
                assert entry.get("verdict") != "TAMPERED"

    def test_result_carries_the_label_and_serializes(self, route, monkeypatch):
        """AC-O10-05: the verdict survives into state.json via asdict()."""
        r = fire(route, monkeypatch, tampered_with_commit)
        assert r.tampered.startswith("TAMPERED — route ref moved:")
        assert "refs/heads/orch-batch-orch10" in r.tampered
        assert "refs/heads/main" in r.tampered
        assert asdict(r)["tampered"] == r.tampered
        assert asdict(r)["status"] == "tampered"

    def test_result_tampered_defaults_to_none(self):
        """Every honest Result leaves the field None — the grep has no false positives."""
        r = orchestrator.Result(
            batch_file="t.md", status=orchestrator.Status.PASSED,
            started="", finished="", duration_s=0, exit_code=0, briefs=1)
        assert r.tampered is None

    def test_notify_renders_the_tampered_verdict(self, caplog):
        """AC-O10-05: the batch summary says TAMPERED, not `passed`, not a bare ❌."""
        r = orchestrator.Result(
            batch_file="t.md", status=orchestrator.Status.TAMPERED,
            started="", finished="", duration_s=84, exit_code=0, briefs=1,
            tampered="TAMPERED — route ref moved: expected refs/heads/x, found refs/heads/main")
        with caplog.at_level("INFO"):
            orchestrator.notify(r)
        assert "tampered" in caplog.text
        assert f"gate: not run ({orchestrator.TAMPER_VERDICT}" in caplog.text
        assert "🚨" in caplog.text

    def test_gate_status_label_unchanged_when_not_tampered(self):
        """[ORCH-2]/[ORCH-3] wording is byte-identical when the new arg is absent."""
        assert orchestrator._gate_status_label(None, None, None) == "not run"
        assert orchestrator._gate_status_label(None, "PASS", "7 files/18 tests, 6.6s") == \
            "PASS (7 files/18 tests, 6.6s)"
        assert orchestrator._gate_status_label(None, "PASS", None, "a → b") == "PASS | unit: a → b"


# ═══════════════════════════════════════════════════════
# AC-O10-06 — neighbouring rules still hold
# ═══════════════════════════════════════════════════════
class TestNeighbouringRules:

    def test_orch9_unit_suite_still_not_run_through_gate_shell(self):
        """[ORCH-9] matters most: the unit suite must NOT be run through _gate_shell_cmd."""
        src = Path(orchestrator.__file__).read_text()
        body = src.split("def _run_unit_suite(")[1].split("\ndef ")[0]
        code = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith("#"))
        assert "_gate_shell_cmd" not in code, \
            "[ORCH-9]: the unit suite must be invoked as the repo invokes it"

    def test_orch1_gate_is_still_the_only_door_to_merge(self):
        """[ORCH-1]: `git merge` in the route lane is still reached only past a PASS."""
        src = Path(orchestrator.__file__).read_text()
        body = src.split("def _run_batch_inner(")[1]
        merge_at = body.index("git merge {branch_name} --no-edit")
        gate_at = body.index("verdict = run_pre_merge_gates(proj, branch_name)")
        assert gate_at < merge_at

    def test_tampered_halts_the_queue(self):
        """A compromised working directory must not host the next batch."""
        src = Path(orchestrator.__file__).read_text()
        assert "Status.FAILED, Status.BLOCKED, Status.TAMPERED" in src

    def test_meta_fire_lane_is_not_gated_by_orch10(self, route, monkeypatch):
        """S5 is report-only: the worktree lane captures no hand-off and is unaffected."""
        assert orchestrator.capture_handoff.__doc__
        src = Path(orchestrator.__file__).read_text()
        assert "capture_handoff(proj, branch_name) if worktree is None else None" in src


# ═══════════════════════════════════════════════════════
# UNIT-LEVEL: capture_handoff / check_route_integrity
# ═══════════════════════════════════════════════════════
class TestHandoffPrimitives:

    def test_capture_handoff_records_name_sha_and_head_ref(self, tmp_path):
        """S1: all three, at one place."""
        proj = tmp_path / "r"
        proj.mkdir()
        _init_repo(proj)
        _git("git checkout -b feat", proj)
        h = orchestrator.capture_handoff(proj, "feat")
        assert h.branch == "feat"
        assert h.head_ref == "refs/heads/feat"
        assert h.branch_sha == _refs(proj)["refs/heads/feat"]
        assert h.heads == _refs(proj)

    def test_check_returns_none_when_nothing_moved(self, tmp_path):
        """S4: the honest path returns None, so the old code runs verbatim."""
        proj = tmp_path / "r"
        proj.mkdir()
        _init_repo(proj)
        _git("git checkout -b feat", proj)
        h = orchestrator.capture_handoff(proj, "feat")
        assert orchestrator.check_route_integrity(proj, h) is None

    def test_check_returns_none_when_only_the_route_branch_advanced(self, tmp_path):
        """S4: commits on the route's own branch are the expected outcome, not tamper."""
        proj = tmp_path / "r"
        proj.mkdir()
        _init_repo(proj)
        _git("git checkout -b feat", proj)
        h = orchestrator.capture_handoff(proj, "feat")
        (proj / "a.txt").write_text("x")
        _git("git add -A", proj)
        _git('git commit -m "work"', proj)
        assert orchestrator.check_route_integrity(proj, h) is None

    def test_check_flags_a_sibling_branch_created_mid_route(self, tmp_path):
        """S3 generalises past the incident: any ref the route did not own."""
        proj = tmp_path / "r"
        proj.mkdir()
        _init_repo(proj)
        _git("git checkout -b feat", proj)
        h = orchestrator.capture_handoff(proj, "feat")
        _git("git checkout -b sideshow", proj)
        (proj / "b.txt").write_text("y")
        _git("git add -A", proj)
        _git('git commit -m "elsewhere"', proj)
        report = orchestrator.check_route_integrity(proj, h)
        assert report is not None
        assert report.found_ref == "refs/heads/sideshow"
        assert [s["ref"] for s in report.stray] == ["refs/heads/sideshow"]
        assert s_was_new(report.stray[0])

    def test_label_counts_the_stray_commits(self, tmp_path):
        """The one-line label is enough to know something landed somewhere else."""
        report = orchestrator.TamperReport(
            expected_ref="refs/heads/orch-x", found_ref="refs/heads/main",
            branch="orch-x", branch_sha_at_handoff="a" * 40, branch_sha_now="a" * 40,
            stray=[{"ref": "refs/heads/main", "was": "b" * 40, "now": "c" * 40,
                    "commits": ["c" * 7 + " fix(care-plans): carry action ids"]}])
        assert report.label == (
            "TAMPERED — route ref moved: expected refs/heads/orch-x, found refs/heads/main; "
            "1 commit(s) on 1 ref(s) the route did not own")

    def test_git_read_is_silent_on_failure(self, tmp_path):
        """A read helper that raises would turn a detection into an outage."""
        assert orchestrator._git_read("git rev-parse --verify nope", tmp_path) == ""
        assert orchestrator._git_read("git status", tmp_path / "missing") == ""


def s_was_new(stray: dict) -> bool:
    """A branch that did not exist at hand-off records `was` as None."""
    return stray["was"] is None

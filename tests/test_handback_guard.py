# filename: tests/test_handback_guard.py
"""Tests for ORCH-HANDBACK-GUARD-1 — a route that says it is unfinished does not merge.

S7-CORE-15 · [TONI-BACKGROUND-EXIT]. The executor sometimes starts a long verification in the
background and ends its turn; `claude` exits 0 and the route used to commit, gate and merge a
tree whose executor had just said it was not finished (route 54: "Half B and the re-run are
going in the background. I'll finish the gate row in the handback when they complete.").

  AC-HG-01  check_handback_invariants per case: the 12 real fixtures + synthetic logs
  AC-HG-02  the handback-scan CLI (the corpus count itself is run by hand, read-only)
  AC-HG-03  the rules are config; the resolver's None cases; the A10 source guard
  AC-HG-05  red before green through _run_batch_inner (TestRouteLane — written first)
  AC-HG-06  the verdict is distinct and surfaced; run_queue halts on it
  AC-HG-07  the meta-fire lane withholds the self-mod merge
  AC-HG-08  unjudgeable ⇒ BLOCKED(environment), never INCOMPLETE and never passed
  AC-HG-09  reachability: _run_batch_inner calls the predicate exactly once

Fixtures under tests/fixtures/handback/ are byte-identical copies of real fire_toni logs from
~/spectricom-orchestrator/logs/ (logs/ is gitignored). No test calls the real `claude`.

Module-level imports are existing orchestrator symbols only, so this file collects on code that
predates the guard — the AC-HG-05 red run needs that.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
from canon_assert import check_handback_invariants, load_outstanding_work_rules

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "handback"
CONFIG = ROOT / "config" / "handback-guard.json"
CORPUS = Path.home() / "spectricom-orchestrator" / "logs"

R54 = "toni-54-surface-truth-1-counts-and-columns-20260927-174452.log"
R53 = "toni-53-l-rx-safety-1-no-doseless-active-order-20260927-155403.log"
R24 = "toni-24-l-labs-1-the-flowsheet-grid-20260920-211705.log"
DRK_Q10 = "toni-toni-batch-s7core7-drk-q10-q11-panel-rulings-01-20260911-190755.log"
R51 = "toni-51-orch-stdout-1-a-gate-log-that-survives-20260927-144718.log"
R52 = "toni-52-seed-test-isolation-1-the-oracle-tells-the-truth-20260927-145453.log"
POSITIVES = {  # fixture → the corpus subdirectory it was copied from
    R54: "clinical-mp", R53: "clinical-mp", R24: "clinical-mp", DRK_Q10: "clinical-mp",
}
NEGATIVES = {
    R51: "orchestrator",
    R52: "clinical-mp",
    "toni-31-l-surfacing-1-render-what-is-already-stored-20260921-104822.log": "clinical-mp",
    "toni-toni-batch-s7core8-l4-1-tiered-consent-01-20260913-125952.log": "clinical-mp",
    "toni-toni-batch-s7core9-l8-1-prescribe-surface-01-20260914-214852.log": "clinical-mp",
    "toni-fix-001-dashboard-count-accuracy-20260606-193935.log": "clinical-mp",
    "toni-toni-brief-s6s57-on-scribe-s2s4-ollama-depth-01-20260610-221916.log": "clinical-mp",
    "toni-46-date-8-the-residual-set-closed-by-predicate-20260927-130414.log": "clinical-mp",
}
RULE_IDS = ["background", "waiting", "will-resume", "in-flight", "pending-bullet", "cli-bg-ceiling"]
RULE = "=" * 60

INCOMPLETE = getattr(orchestrator, "INCOMPLETE_VERDICT", "INCOMPLETE(executor)")
needs_guard = pytest.mark.skipif(
    not hasattr(orchestrator, "INCOMPLETE_VERDICT"),
    reason="predates ORCH-HANDBACK-GUARD-1: orchestrator has no INCOMPLETE_VERDICT")


def _rules():
    rules = load_outstanding_work_rules(CONFIG)
    assert rules is not None, "the shipped config must resolve"
    return rules


def _line_of(path: Path, needle: str) -> int:
    """1-based line number of the first line of `path` containing `needle`."""
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if needle in line:
            return i
    raise AssertionError(f"{needle!r} not in {path.name}")


def _synthetic(tmp_path: Path, output: list[str], *, header: bool = True, trailer: bool = True,
               name: str = "toni-synthetic.log", header_extra: str = "", trailer_extra: str = "") -> Path:
    """A fire_toni-shaped log: the `fire_toni` header, the executor output, the trailer."""
    head = (f"=== TONI EXECUTION ===\nBatch: synthetic.md\nStarted: 2026-09-27T00:00:00\n"
            f"Command: claude{header_extra}\n{RULE}\n\n") if header else ""
    tail = f"\n{RULE}\nFinished: 2026-09-27T00:01:00{trailer_extra}\nExit: 0\n" if trailer else ""
    p = tmp_path / name
    p.write_text(head + "\n".join(output) + "\n" + tail)
    return p


# ═══════════════════════════════════════════════════════
# AC-HG-01 · the predicate, per case
# ═══════════════════════════════════════════════════════
class TestPredicateOnRealLogs:

    def test_route_54_is_background_and_will_resume_on_its_one_line(self):
        f = FIXTURES / R54
        n = _line_of(f, "Half B and the re-run are going in the background.")
        v = check_handback_invariants(f, _rules())
        assert {(x.reason, x.rule, x.line_no) for x in v} == {
            ("outstanding-work", "background", n), ("outstanding-work", "will-resume", n)}
        assert all(x.line.startswith("Half B and the re-run") for x in v)

    def test_route_53_is_waiting(self):
        v = check_handback_invariants(FIXTURES / R53, _rules())
        assert [(x.reason, x.rule) for x in v] == [("outstanding-work", "waiting")]
        assert v[0].line == "Memory recorded. Waiting for the final-tree baseline run to complete."

    def test_route_24_catches_a_sentence_that_is_not_the_last_line(self):
        f = FIXTURES / R24
        v = check_handback_invariants(f, _rules())
        assert {x.rule for x in v} == {"background", "pending-bullet", "will-resume"}
        assert {x.reason for x in v} == {"outstanding-work"}
        lines = f.read_text().splitlines()
        trailer = max(i for i, l in enumerate(lines) if l == RULE)
        last_output = max(i for i in range(trailer) if lines[i].strip()) + 1
        bg = next(x for x in v if x.rule == "background")
        assert bg.line_no < last_output, "the background sentence is higher up than the final line"

    def test_drk_q10_carries_the_cli_ceiling_line(self):
        v = check_handback_invariants(FIXTURES / DRK_Q10, _rules())
        hit = [x for x in v if x.rule == "cli-bg-ceiling"]
        assert len(hit) == 1
        assert hit[0].line.startswith("Background tasks still running after 600s; terminating.")

    @pytest.mark.parametrize("name", sorted(NEGATIVES))
    def test_negatives_are_clean(self, name):
        assert check_handback_invariants(FIXTURES / name, _rules()) == []

    @pytest.mark.parametrize("name", sorted({**POSITIVES, **NEGATIVES}))
    def test_fixture_is_a_verbatim_copy(self, name):
        """T4: byte-identical to the live log, where the live corpus is on this machine."""
        src = CORPUS / {**POSITIVES, **NEGATIVES}[name] / name
        if not src.is_file():
            pytest.skip(f"live corpus not on this machine: {src}")
        assert (FIXTURES / name).read_bytes() == src.read_bytes()


class TestPredicateOnSyntheticLogs:

    def test_missing_path_is_one_log_unreadable(self, tmp_path):
        v = check_handback_invariants(tmp_path / "nope.log", _rules())
        assert [(x.reason, x.rule, x.line_no, x.line) for x in v] == [("log-unreadable", "", 0, "")]

    def test_a_directory_is_log_unreadable(self, tmp_path):
        v = check_handback_invariants(tmp_path, _rules())
        assert [x.reason for x in v] == ["log-unreadable"]

    def test_line_1_not_the_header_is_one_no_toni_header(self, tmp_path):
        p = tmp_path / "orch.log"
        p.write_text("2026-05-05 12:00:00 [INFO] Waiting for the final-tree baseline run.\n")
        v = check_handback_invariants(p, _rules())
        assert [(x.reason, x.rule, x.line_no) for x in v] == [("no-toni-header", "", 0)]

    def test_empty_file_is_no_toni_header(self, tmp_path):
        p = tmp_path / "empty.log"
        p.write_text("")
        assert [x.reason for x in check_handback_invariants(p, _rules())] == ["no-toni-header"]

    def test_header_only_empty_output_is_clean(self, tmp_path):
        assert check_handback_invariants(_synthetic(tmp_path, []), _rules()) == []

    def test_no_trailer_last_output_line_matches(self, tmp_path):
        """fire_toni's timeout and exception paths write no trailer: the output runs to EOF."""
        p = _synthetic(tmp_path, ["Done with part one.", "Waiting for the SIT half to finish."],
                       trailer=False)
        v = check_handback_invariants(p, _rules())
        assert [(x.rule, x.line_no) for x in v] == [("waiting", _line_of(p, "Waiting for the SIT"))]

    def test_phrases_in_header_and_trailer_blocks_are_excluded(self, tmp_path):
        p = _synthetic(tmp_path, ["All done, committed as abc1234."],
                       header_extra=" — Waiting for the final run. I'll follow up later.",
                       trailer_extra=" Pending: the gate is still running in the background")
        assert "Waiting for" in p.read_text() and "Pending:" in p.read_text()
        assert check_handback_invariants(p, _rules()) == []

    def test_at_most_one_violation_per_rule_first_in_file_order(self, tmp_path):
        p = _synthetic(tmp_path, ["Waiting for the unit run.", "", "Still waiting. Waiting on SIT."])
        v = check_handback_invariants(p, _rules())
        assert [(x.rule, x.line_no) for x in v] == [("waiting", _line_of(p, "Waiting for the unit"))]

    def test_caret_anchors_at_each_line_start(self, tmp_path):
        p = _synthetic(tmp_path, ["Status:", "- **Pending**: the SIT gate."])
        v = check_handback_invariants(p, _rules())
        assert [(x.rule, x.line_no) for x in v] == [("pending-bullet", _line_of(p, "**Pending**"))]

    def test_a_rule_between_output_lines_does_not_end_the_output_early(self, tmp_path):
        """Only the LAST rule followed by `Exit:` is the trailer; an executor's own rule is output."""
        p = _synthetic(tmp_path, ["Part one done.", RULE, "", "Waiting for the baseline run."])
        assert [x.rule for x in check_handback_invariants(p, _rules())] == ["waiting"]

    def test_line_is_stripped_and_truncated(self, tmp_path):
        p = _synthetic(tmp_path, ["   - Pending: " + "x" * 400])
        (v,) = check_handback_invariants(p, _rules())
        assert v.line.startswith("- Pending: x") and len(v.line) == 160

    @pytest.mark.parametrize("prose", [
        "All background work is now closed out.",
        "- Pending refills: dashboard used the wrong filter.",
        "The test was waiting for a lock that never released.",
        "The live daemon is still running the old code until restart.",
        "I'll finish with a summary.",
    ])
    def test_near_misses_named_in_the_brief_do_not_match(self, tmp_path, prose):
        assert check_handback_invariants(_synthetic(tmp_path, [prose]), _rules()) == []


# ═══════════════════════════════════════════════════════
# AC-HG-03 · the rules are config, and insufficient is handled
# ═══════════════════════════════════════════════════════
class TestRulesAreConfig:

    def test_shipped_config_holds_the_six_rules_with_real_evidence(self):
        cfg = json.loads(CONFIG.read_text())
        entries = cfg["outstanding_work"]
        assert [e["id"] for e in entries] == RULE_IDS
        for e in entries:
            assert e["evidence"], f"{e['id']} names no evidence"
            for name in e["evidence"]:
                assert re.fullmatch(r"toni-.+-\d{8}-\d{6}\.log", name), name
        by_id = {e["id"]: set(e["evidence"]) for e in entries}
        assert R54 in by_id["background"] and R54 in by_id["will-resume"]
        assert R53 in by_id["waiting"]
        assert R24 in by_id["pending-bullet"]
        assert by_id["cli-bg-ceiling"] == {DRK_Q10}
        assert [r.id for r in _rules()] == RULE_IDS

    def test_every_rule_is_case_insensitive(self):
        assert all(r.pattern.flags & re.IGNORECASE for r in _rules())

    @pytest.mark.parametrize("body", [
        None,                                                        # missing file
        "{not json",                                                 # invalid JSON
        json.dumps([]),                                              # not an object
        json.dumps({"outstanding_work": []}),                        # empty list
        json.dumps({"other": [{"id": "a", "regex": "x"}]}),          # no outstanding_work
        json.dumps({"outstanding_work": [{"id": "a"}]}),             # missing regex
        json.dumps({"outstanding_work": [{"regex": "x"}]}),          # missing id
        json.dumps({"outstanding_work": ["x"]}),                     # entry not an object
        json.dumps({"outstanding_work": [{"id": "a", "regex": "x"},
                                         {"id": "a", "regex": "y"}]}),  # duplicate id
        json.dumps({"outstanding_work": [{"id": "a", "regex": "(unclosed"}]}),  # uncompilable
    ], ids=["missing", "invalid-json", "not-object", "empty-list", "no-key", "no-regex", "no-id",
            "entry-not-object", "duplicate-id", "bad-regex"])
    def test_insufficient_config_resolves_to_none(self, tmp_path, body):
        p = tmp_path / "handback-guard.json"
        if body is not None:
            p.write_text(body)
        assert load_outstanding_work_rules(p) is None

    def test_a10_no_regex_literal_in_source(self):
        """The phrase set lives only in the JSON: none of its regexes is a substring of either module."""
        regexes = [e["regex"] for e in json.loads(CONFIG.read_text())["outstanding_work"]]
        for src in (ROOT / "canon_assert.py", ROOT / "orchestrator.py"):
            text = src.read_text()
            for rx in regexes:
                assert rx not in text, f"{src.name} holds a rule regex: {rx}"


# ═══════════════════════════════════════════════════════
# ROUTE HARNESS — the test_merge_conflict.py shape (that file's fixture, copied on purpose)
# ═══════════════════════════════════════════════════════
def _git(cmd: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)


def _sha(rev: str, cwd: Path) -> str:
    return _git(f"git rev-parse {rev}", cwd).stdout.strip()


def _init_repo(path: Path):
    _git("git init", path)
    _git("git config user.email test@test.com", path)
    _git("git config user.name Test", path)
    _git("git symbolic-ref HEAD refs/heads/main", path)
    (path / "README.md").write_text("init\n")
    _git("git add -A", path)
    _git('git commit -m "init"', path)


class Route:
    def __init__(self, proj: Path, brief: Path):
        self.proj = proj
        self.brief = brief
        self.branch = f"orch-{brief.stem}"
        self.gate_calls = []
        self.log_path = None      # what the fake fire_toni returned
        self.result = None


@pytest.fixture
def route(tmp_path, monkeypatch):
    proj = tmp_path / "repo"
    proj.mkdir()
    _init_repo(proj)
    briefs_dir = proj / "briefs"
    briefs_dir.mkdir()
    brief = briefs_dir / "batch-hg.md"
    brief.write_text("- id: B1\n  title: demo\n\n## Estimated runtime: 45-75 min\n")
    _git("git add -A", proj)
    _git('git commit -m "chore(briefs): stage batch-hg"', proj)

    monkeypatch.setattr(orchestrator, "PROJECT_ROOT", proj)
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG", {"briefs_subdir": "briefs"})
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "testrepo")
    monkeypatch.setattr(orchestrator, "BRANCH_PREFIX", "orch")
    monkeypatch.setattr(orchestrator, "MERGE_TARGET", "main")
    monkeypatch.setattr(orchestrator, "IS_META_FIRE", False)
    monkeypatch.setattr(orchestrator, "RUN_PLAYWRIGHT", False)
    monkeypatch.setattr(orchestrator, "SIT_ARCHIVE_DIR", tmp_path / "archive")
    monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
    monkeypatch.setattr(orchestrator, "notify", lambda r: None)
    monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
    monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
    monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
    return Route(proj, brief)


def _stage_log(route: Route, fixture: str) -> str:
    """Copy a fixture where fire_toni would have written it: outside the repo, like logs/."""
    logs = route.proj.parent / "logs"
    logs.mkdir(exist_ok=True)
    return str(shutil.copyfile(FIXTURES / fixture, logs / fixture))


def fire(route, monkeypatch, executor, fixture=None, log_path=None):
    """Run one route through _run_batch_inner. The fake fire_toni returns a copy of `fixture`
    (or `log_path` verbatim); the fake PASS gate records every call."""

    def _fake_gate(repo_path, branch_name=None):
        route.gate_calls.append((str(repo_path), branch_name))
        return orchestrator.GateVerdict(outcome=orchestrator.GateOutcome.PASS, gate="build", signal=None)

    def _toni(target, proj):
        ec = executor(proj)
        route.log_path = log_path if fixture is None else _stage_log(route, fixture)
        return ec, route.log_path

    monkeypatch.setattr(orchestrator, "run_pre_merge_gates", _fake_gate)
    monkeypatch.setattr(orchestrator, "fire_toni", _toni)
    route.result = orchestrator._run_batch_inner(
        route.brief, route.proj, orchestrator.datetime.now(), worktree=None
    )
    return route.result


def commits(proj):
    """A commit on the route's own branch, touching feature.txt."""
    (proj / "feature.txt").write_text("work\n")
    _git("git add -A", proj)
    _git('git commit -m "feat: work"', proj)
    return 0


def leaves_uncommitted(proj):
    """Work in the tree, not committed — the orchestrator's auto-commit owns it."""
    (proj / "feature.txt").write_text("uncommitted work\n")
    return 0


def _final_status(caplog) -> str:
    lines = [r.getMessage() for r in caplog.records if "FINAL STATUS" in r.getMessage()]
    assert len(lines) == 1, lines
    return lines[0]


def _held(route, main_before):
    """The shape every held route leaves: no gate, main unmoved and clean, branch holding the work."""
    assert route.gate_calls == [], "no gate may run on a held route"
    assert _sha("main", route.proj) == main_before, "MERGE_TARGET moved"
    assert _git("git symbolic-ref HEAD", route.proj).stdout.strip() == "refs/heads/main"
    assert _git("git status --porcelain", route.proj).stdout.strip() == ""
    tip = _sha(f"refs/heads/{route.branch}", route.proj)
    assert tip, "the route branch must be preserved"
    assert _git(f"git show {tip}:feature.txt", route.proj).returncode == 0, "the branch holds the work"
    assert _git(f"git merge-base --is-ancestor {tip} main", route.proj).returncode != 0


# ═══════════════════════════════════════════════════════
# AC-HG-05 · red before green through _run_batch_inner
# ═══════════════════════════════════════════════════════
class TestRouteLane:

    def test_a_route_54_committed_work_is_not_merged(self, route, monkeypatch):
        main_before = _sha("main", route.proj)
        r = fire(route, monkeypatch, commits, fixture=R54)
        assert r.status.value == "incomplete"
        _held(route, main_before)

    def test_b_route_53_uncommitted_work_is_committed_on_the_branch_not_merged(self, route, monkeypatch):
        main_before = _sha("main", route.proj)
        r = fire(route, monkeypatch, leaves_uncommitted, fixture=R53)
        assert r.status.value == "incomplete"
        _held(route, main_before)
        assert (route.proj / "feature.txt").exists() is False, "main's checkout must not carry the work"

    def test_c_route_51_is_unchanged_passed_merged_gated_once(self, route, monkeypatch):
        main_before = _sha("main", route.proj)
        r = fire(route, monkeypatch, commits, fixture=R51)
        assert r.status.value == "passed"
        assert len(route.gate_calls) == 1
        assert _sha("main", route.proj) != main_before
        assert _git("git show main:feature.txt", route.proj).returncode == 0


# ═══════════════════════════════════════════════════════
# AC-HG-06 · the verdict is distinct and surfaced
# ═══════════════════════════════════════════════════════
@needs_guard
class TestVerdict:

    def test_incomplete_is_its_own_status_and_verdict(self):
        assert orchestrator.Status.INCOMPLETE.value == "incomplete"
        assert orchestrator.INCOMPLETE_VERDICT == "INCOMPLETE(executor)"
        assert INCOMPLETE not in {g.value for g in orchestrator.GateOutcome}
        assert len({INCOMPLETE, orchestrator.GateOutcome.FAIL_PRODUCT.value,
                    orchestrator.GateOutcome.BLOCKED_ENV.value, orchestrator.TAMPER_VERDICT,
                    orchestrator.MERGE_CONFLICT_VERDICT}) == 5

    def test_final_status_line_names_the_rule_and_line(self, route, monkeypatch, caplog):
        with caplog.at_level("INFO"):
            r = fire(route, monkeypatch, commits, fixture=R54)
        n = _line_of(FIXTURES / R54, "Half B and the re-run are going in the background.")
        assert _final_status(caplog) == (
            f"🏁 FINAL STATUS: incomplete | gate: not run (INCOMPLETE(executor) — background at line {n})")
        assert r.error.startswith(f"{INCOMPLETE} — executor output advertises outstanding work: background at line {n}")
        assert "Half B and the re-run are going in the background." in r.error
        assert r.gate_outcome is None, "no gate ran"
        assert f"⛔ {INCOMPLETE} — main NOT merged, no gate run. Branch preserved: {route.branch}." in caplog.text

    def test_the_branch_carries_a_note_naming_the_verdict(self, route, monkeypatch):
        fire(route, monkeypatch, commits, fixture=R54)
        note = _git(f"git notes show refs/heads/{route.branch}", route.proj).stdout
        assert note.startswith(f"HANDBACK GUARD: {INCOMPLETE} — background at line")

    def test_no_changes_path_is_incomplete_too(self, route, monkeypatch):
        main_before = _sha("main", route.proj)
        r = fire(route, monkeypatch, lambda proj: 0, fixture=R53)
        assert r.status is orchestrator.Status.INCOMPLETE
        assert route.gate_calls == []
        assert _sha("main", route.proj) == main_before

    def test_gate_status_label_renders_incomplete_distinctly(self):
        s = orchestrator._gate_status_label(None, None, None, None, None, incomplete="waiting at line 7")
        assert s == "not run (INCOMPLETE(executor) — waiting at line 7)"

    def test_run_queue_halts_on_incomplete(self, tmp_path, monkeypatch):
        files = []
        for name in ("q1.md", "q2.md"):
            f = tmp_path / name
            f.write_text("- id: B1\n  title: demo\n")
            files.append(f)
        fired = []

        def _run_batch(bf, worktree=None):
            fired.append(bf.name)
            now = orchestrator.datetime.now().isoformat()
            return orchestrator.Result(batch_file=bf.name, status=orchestrator.Status.INCOMPLETE,
                                       started=now, finished=now, duration_s=0.0, exit_code=0, briefs=1)

        monkeypatch.setattr(orchestrator, "run_batch", _run_batch)
        monkeypatch.setattr(orchestrator, "load_state", lambda: {"completed": [], "failed": []})
        monkeypatch.setattr(orchestrator, "save_state", lambda s: None)
        monkeypatch.setattr(orchestrator, "rate_check", lambda *a, **k: True)
        monkeypatch.setattr(orchestrator.time, "sleep", lambda s: None)
        orchestrator.run_queue(files, skip_deps=True)
        assert fired == ["q1.md"], "the second batch must fire zero times"


# ═══════════════════════════════════════════════════════
# AC-HG-07 · the meta-fire lane
# ═══════════════════════════════════════════════════════
@needs_guard
def test_meta_fire_lane_withholds_the_self_mod_merge(route, monkeypatch, caplog):
    caplog.set_level("INFO", logger="orch")
    monkeypatch.setattr(orchestrator, "IS_META_FIRE", True)
    monkeypatch.setattr(orchestrator, "ORCH_DIR", route.proj)      # is_self_mod: this repo is the orchestrator
    monkeypatch.setattr(orchestrator, "PREFIRE_BYPASS", True)
    # The fire lock and running.json are the real orchestrator's; never touch them from a test.
    monkeypatch.setattr(orchestrator, "write_running", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "clear_running", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "_write_running_marker", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "_clear_running_marker", lambda *a, **k: None)
    gate_calls, merges, seen = [], [], {}

    def _toni(target, proj):
        seen["wt"] = proj
        return 0, _stage_log(route, R54)

    monkeypatch.setattr(orchestrator, "fire_toni", _toni)
    monkeypatch.setattr(orchestrator, "run_pre_merge_gates", lambda *a, **k: gate_calls.append(a))
    monkeypatch.setattr(orchestrator, "_self_mod_auto_merge", lambda *a, **k: merges.append(a) or True)
    try:
        r = orchestrator.run_batch(route.brief)
        assert seen["wt"] != route.proj, "ran in the meta-fire worktree"
        assert r.status is orchestrator.Status.INCOMPLETE
        assert gate_calls == [] and merges == []
        withheld = [m.getMessage() for m in caplog.records if "Self-mod merge WITHHELD" in m.getMessage()]
        assert len(withheld) == 1 and INCOMPLETE in withheld[0]
        assert "Self-mod fire failed" not in caplog.text
    finally:
        if "wt" in seen:
            _git(f"git worktree remove --force {seen['wt']}", route.proj)


# ═══════════════════════════════════════════════════════
# AC-HG-08 · unjudgeable is BLOCKED(environment)
# ═══════════════════════════════════════════════════════
@needs_guard
class TestUnjudgeableIsBlocked:

    def _assert_blocked(self, route, r, main_before, reason):
        assert r.status is orchestrator.Status.BLOCKED
        assert r.error == f"BLOCKED(environment) — handback guard: {reason}"
        _held(route, main_before)

    def test_unconfigured_rules(self, route, monkeypatch, tmp_path):
        monkeypatch.setattr(orchestrator, "HANDBACK_GUARD_CONFIG", tmp_path / "absent.json")
        main_before = _sha("main", route.proj)
        r = fire(route, monkeypatch, commits, fixture=R51)
        self._assert_blocked(route, r, main_before, "handback-guard-unconfigured")

    def test_missing_log(self, route, monkeypatch):
        main_before = _sha("main", route.proj)
        r = fire(route, monkeypatch, commits, log_path=str(route.proj.parent / "never-written.log"))
        self._assert_blocked(route, r, main_before, "log-unreadable")

    def test_log_without_header(self, route, monkeypatch):
        p = route.proj.parent / "headless.log"
        p.write_text("some output with no fire_toni header\n")
        main_before = _sha("main", route.proj)
        r = fire(route, monkeypatch, commits, log_path=str(p))
        self._assert_blocked(route, r, main_before, "no-toni-header")


# ═══════════════════════════════════════════════════════
# AC-HG-09 (a) · reachability
# ═══════════════════════════════════════════════════════
@needs_guard
def test_run_batch_inner_judges_the_fire_toni_log_exactly_once(route, monkeypatch):
    real = orchestrator.check_handback_invariants
    with patch.object(orchestrator, "check_handback_invariants", wraps=real) as spy:
        r = fire(route, monkeypatch, commits, fixture=R51)
    assert r.status is orchestrator.Status.PASSED
    assert spy.call_count == 1
    assert spy.call_args.args[0] == Path(route.log_path)


@needs_guard
def test_a_tampered_route_is_not_judged(route, monkeypatch):
    def _checks_out_main(proj):
        _git("git checkout main", proj)
        return 0

    with patch.object(orchestrator, "check_handback_invariants") as spy:
        r = fire(route, monkeypatch, _checks_out_main, fixture=R54)
    assert r.status is orchestrator.Status.TAMPERED
    spy.assert_not_called()


# ═══════════════════════════════════════════════════════
# AC-HG-02 / T3 · the handback-scan CLI (read-only)
# ═══════════════════════════════════════════════════════
@needs_guard
class TestHandbackScan:

    def test_scans_a_directory_and_reports(self, capsys):
        rc = orchestrator.handback_scan([str(FIXTURES)])
        out = capsys.readouterr().out
        assert rc == 1
        fails = [l for l in out.splitlines() if l.startswith("FAIL ")]
        n54 = _line_of(FIXTURES / R54, "Half B")
        assert f"FAIL {FIXTURES / R54}: outstanding-work background L{n54}: Half B" in out
        assert {Path(l[5:].split(":")[0]).name for l in fails} == set(POSITIVES)
        assert ("12 logs scanned: 4 outstanding-work, 0 no-toni-header, 0 log-unreadable, 8 clean; "
                "per rule: background 3, waiting 2, will-resume 2, in-flight 1, pending-bullet 1, "
                "cli-bg-ceiling 1") in out

    def test_until_pins_the_corpus_by_filename_timestamp(self, capsys):
        rc = orchestrator.handback_scan([str(FIXTURES)], until="20260920-211705")
        out = capsys.readouterr().out
        assert rc == 1
        assert "6 logs scanned: 2 outstanding-work" in out     # R24 is included (<=), 53/54 are not
        assert R53 not in out and R54 not in out

    def test_clean_files_exit_0(self, capsys):
        assert orchestrator.handback_scan([str(FIXTURES / R51), str(FIXTURES / R52)]) == 0
        assert "2 logs scanned: 0 outstanding-work, 0 no-toni-header, 0 log-unreadable, 2 clean" \
            in capsys.readouterr().out

    def test_missing_path_is_log_unreadable(self, tmp_path, capsys):
        assert orchestrator.handback_scan([str(tmp_path / "toni-gone-20260101-000000.log")]) == 1
        assert "1 log-unreadable" in capsys.readouterr().out

    def test_it_writes_nothing(self, tmp_path, capsys):
        d = tmp_path / "logs"
        d.mkdir()
        shutil.copyfile(FIXTURES / R54, d / R54)
        before = {p: p.stat().st_mtime_ns for p in d.iterdir()}
        orchestrator.handback_scan([str(d)])
        assert {p: p.stat().st_mtime_ns for p in d.iterdir()} == before

    def test_is_a_subcommand(self):
        src = (ROOT / "orchestrator.py").read_text()
        assert 'sp.add_parser("handback-scan"' in src
        assert "handback_scan(" in src.split("def main(")[1]

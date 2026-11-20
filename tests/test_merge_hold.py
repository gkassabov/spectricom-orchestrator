"""ORCH-MERGE-HOLD-1 (route 757; 621 slice 2 of 2; RM-OPS-01-F-02 + RM-OPS-03-F-01; T-OPX-02; C-OPX02).

A green route whose diff touches a path config/merge-hold.json lists (lockfiles, dependency manifests, .npmrc, workflows,
.claude, .mcp.json, hooks) is HELD for a human merge: nothing merged, the branch kept, a `MERGE HOLD:` line on its tip's
note, exit EXIT_HELD; the daemon trays the brief in queue/held/merge-hold/ and keeps firing (no pause). `release-hold`
(George / Gemma, a reason) appends `MERGE HOLD RELEASE:` and queues a gates-only re-gate of exactly that tip, which
_regate_check clears and the landing lets through. A missing or invalid list holds every green route (fail closed).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import orchestrator  # noqa: E402
import queue_daemon  # noqa: E402
from tests.test_queue_park_red import PASS, Q, git  # noqa: E402

HELD = ("held", "PASS", "HELD FOR HUMAN MERGE — MERGE HOLD: package-lock.json — listed in config/merge-hold.json; a "
                        "human merges it")


@pytest.fixture
def q(tmp_path, monkeypatch):
    harness = Q(tmp_path, monkeypatch)
    route = harness._route

    def _route(cmd, batch_name, log_path):
        if harness.script.get(batch_name) == HELD:          # the route as orchestrator.py ends a held one
            harness.fired.append(batch_name)
            Path(log_path).parent.mkdir(parents=True, exist_ok=True)
            Path(log_path).write_text("🏁 FINAL STATUS: held | gate: PASS\n")
            state = harness.orch / "state.json"
            data = json.loads(state.read_text()) if state.exists() else {"completed": [], "failed": [], "stopped": []}
            data.setdefault("held", []).append({"batch_file": batch_name, "status": "held", "gate_outcome": "PASS",
                                                "started": "9999", "error": HELD[2], "exit_code": 0})
            state.write_text(json.dumps(data))
            return queue_daemon.EXIT_HELD
        return route(cmd, batch_name, log_path)

    harness.d._run_route = _route
    return harness


def _held_branch(q, stem="757-x", files=("package-lock.json",), note=("PRE-MERGE GATE: PASS — gates green", "MERGE HOLD: package-lock.json — listed")):
    """A route branch with one commit touching `files`, its tip noted as the landing notes a held route."""
    branch = f"orch-mp-{stem}"
    git(q.repo, "checkout", "-q", "-b", branch, "main")
    for f in files:
        p = q.repo / f
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x\n")
        git(q.repo, "add", f)
    git(q.repo, "commit", "-q", "-m", f"route {stem}")
    tip = git(q.repo, "rev-parse", "HEAD")
    for line in note or ():
        git(q.repo, "notes", "append", "-m", line, tip)
    return branch, tip


# ── M-1 · the two halves agree ───────────────────────────────────────────────────────────────────────────────────
def test_M1_exit_code_and_prefixes_are_pinned_equal():
    assert orchestrator.EXIT_HELD == queue_daemon.EXIT_HELD == 6
    assert orchestrator.EXIT_HELD not in (0, 1, 2, 3, 4, orchestrator.EXIT_STOPPED)
    assert orchestrator.MERGE_HOLD_PREFIX == queue_daemon.MERGE_HOLD_PREFIX
    assert orchestrator.MERGE_HOLD_RELEASE_PREFIX == queue_daemon.MERGE_HOLD_RELEASE_PREFIX
    assert orchestrator.Status.HELD.value == "held"


# ── M-2 · the list is data, read strictly ────────────────────────────────────────────────────────────────────────
def test_M2_the_shipped_list_loads_and_names_the_supply_chain_and_the_control_plane():
    paths, why = orchestrator.load_merge_hold()
    assert why is None and paths
    for must in ("package-lock.json", "package.json", ".npmrc", ".github/workflows/**", ".claude/**", ".mcp.json"):
        assert must in paths, must


@pytest.mark.parametrize("text", [None, "{not json", "[]", '{"paths": []}', '{"paths": ["ok", ""]}', '{"paths": [3]}', '{"other": 1}'])
def test_M2_a_missing_or_invalid_list_is_unreadable(tmp_path, text):
    p = tmp_path / "merge-hold.json"
    if text is not None:
        p.write_text(text)
    paths, why = orchestrator.load_merge_hold(p)
    assert paths is None and why


# ── M-3 · which changed paths are held ───────────────────────────────────────────────────────────────────────────
def test_M3_listed_paths_are_held_and_others_are_not():
    patterns, _ = orchestrator.load_merge_hold()
    changed = ["package-lock.json", "server/package.json", ".github/workflows/ci.yml", ".claude/settings.json", ".mcp.json",
               ".npmrc", ".husky/pre-commit", "requirements.txt", "src/a.ts", "docs/x.md", "src/lib/package-utils.ts"]
    held = orchestrator.merge_hold_paths(changed, patterns)
    assert held == sorted(["package-lock.json", "server/package.json", ".github/workflows/ci.yml", ".claude/settings.json",
                           ".mcp.json", ".npmrc", ".husky/pre-commit", "requirements.txt"])
    assert orchestrator.merge_hold_paths(["src/a.ts", "docs/x.md"], patterns) == []


# ── M-4 · the landing's check, on a real repo ────────────────────────────────────────────────────────────────────
class TestM4Verdict:

    @pytest.fixture(autouse=True)
    def _target(self, monkeypatch):
        monkeypatch.setattr(orchestrator, "MERGE_TARGET", "main")
        monkeypatch.setattr(orchestrator, "REGATE", None)

    def test_a_route_touching_a_lockfile_is_held_and_one_touching_src_is_not(self, q):
        branch, _ = _held_branch(q, "757-a", files=("package-lock.json", "src/a.ts"), note=None)
        git(q.repo, "checkout", "-q", branch)
        held = orchestrator._merge_hold_verdict(q.repo, branch)
        assert held.startswith("MERGE HOLD: package-lock.json — listed in config/merge-hold.json")
        assert "src/a.ts" not in held
        git(q.repo, "checkout", "-q", "main")
        branch2, _ = _held_branch(q, "757-b", files=("src/b.ts",), note=None)
        git(q.repo, "checkout", "-q", branch2)
        assert orchestrator._merge_hold_verdict(q.repo, branch2) is None

    def test_a_released_tip_lands(self, q):
        branch, tip = _held_branch(q, "757-c")
        git(q.repo, "notes", "append", "-m", "MERGE HOLD RELEASE: by George: lockfile reviewed by hand (2026-11-19)", tip)
        git(q.repo, "checkout", "-q", branch)
        assert orchestrator._merge_hold_verdict(q.repo, branch) is None

    def test_in_a_regate_the_release_on_the_regated_tip_counts(self, q, monkeypatch):
        branch, tip = _held_branch(q, "757-d")
        git(q.repo, "notes", "append", "-m", "MERGE HOLD RELEASE: by Gemma: reviewed lockfile diff ok (2026-11-19)", tip)
        git(q.repo, "checkout", "-q", "-b", "orch-mp-757-d-release", "main")
        git(q.repo, "merge", "-q", "--no-edit", tip)
        monkeypatch.setattr(orchestrator, "REGATE", orchestrator.RegateSpec(branch, tip, "PASS"))
        assert orchestrator._merge_hold_verdict(q.repo, "orch-mp-757-d-release") is None

    def test_an_unreadable_list_holds_every_green_route(self, q, monkeypatch, tmp_path):
        monkeypatch.setattr(orchestrator, "MERGE_HOLD_FILE", tmp_path / "absent.json")
        branch, _ = _held_branch(q, "757-e", files=("src/e.ts",), note=None)
        git(q.repo, "checkout", "-q", branch)
        held = orchestrator._merge_hold_verdict(q.repo, branch)
        assert held.startswith("MERGE HOLD: absent.json unreadable") and "every green route is held" in held


# ── M-5 · the run's exit code ────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("statuses,code", [
    (["held"], 6), (["passed", "held"], 6), (["stopped", "held"], 6), (["passed", "stopped"], 5), (["passed"], 0),
    (["failed", "held"], 1),
])
def test_M5_exit_code_of(statuses, code):
    S = orchestrator.Status
    rs = [type("R", (), {"status": S(s)})() for s in statuses]
    assert orchestrator._exit_code_of(rs) == code


# ── M-6 · the re-gate clears a released hold, and only a released one ───────────────────────────────────────────
def test_M6_regate_of_a_held_tip_needs_the_release(q, monkeypatch):
    branch, tip = _held_branch(q, "757-f")
    b = q.tmp / "757-f-release.md"
    b.write_text(f"#!queue repo=cmp\n## Re-gate of: {branch} {tip}\n")
    monkeypatch.setattr(orchestrator, "PROJECT_ROOT", q.repo)
    monkeypatch.setattr(orchestrator, "IS_META_FIRE", False)
    monkeypatch.setattr(orchestrator, "BRANCH_PREFIX", "orch-mp")
    monkeypatch.delenv(orchestrator.REGATE_VAR, raising=False)
    spec, why = orchestrator._regate_check(b)
    assert spec is None and "HELD FOR HUMAN MERGE and not released" in why
    git(q.repo, "notes", "append", "-m", "MERGE HOLD RELEASE: by George: lockfile bump reviewed (2026-11-19)", tip)
    spec, why = orchestrator._regate_check(b)
    assert why is None and spec.sha == tip and "MERGE HOLD RELEASE: by George" in spec.prior


def test_M6_control_a_plain_pass_tip_is_still_not_regated(q, monkeypatch):
    branch, tip = _held_branch(q, "757-g", files=("src/g.ts",), note=("PRE-MERGE GATE: PASS — gates green",))
    b = q.tmp / "757-g-regate.md"
    b.write_text(f"#!queue repo=cmp\n## Re-gate of: {branch} {tip}\n")
    monkeypatch.setattr(orchestrator, "PROJECT_ROOT", q.repo)
    monkeypatch.setattr(orchestrator, "IS_META_FIRE", False)
    monkeypatch.setattr(orchestrator, "BRANCH_PREFIX", "orch-mp")
    monkeypatch.delenv(orchestrator.REGATE_VAR, raising=False)
    spec, why = orchestrator._regate_check(b)
    assert spec is None and "not BLOCKED(environment)" in why


# ── M-7 · the daemon trays a held route and keeps firing ─────────────────────────────────────────────────────────
def test_M7_a_held_route_is_trayed_and_the_queue_keeps_firing(q, capsys):
    q.brief("757-a", ["package-lock.json"])
    q.brief("758-b", ["src/b.ts"])
    q.script["757-a.md"] = HELD
    d = q.run()
    out = capsys.readouterr().out
    assert q.fired == ["757-a.md", "758-b.md"], q.fired
    assert d.paused_reason is None
    assert q.at("held", "merge-hold", "757-a.md") and not q.at("failed", "757-a.md") and not q.at("757-a.md")
    assert "MERGE HOLD: package-lock.json" in (q.queue / "held" / "merge-hold" / "757-a.reason").read_text()
    assert [e["file"] for e in d.held] == ["757-a.md"] and d.held[0]["status"] == "held"
    assert [e["file"] for e in d.completed] == ["758-b.md"] and not d.failed
    assert "⏸ HELD: 757-a.md" in out and "release-hold" in out
    st = d.get_status()
    assert [h["file"] for h in st["merge_held"]] == ["757-a.md"] and st["held_total"] == 1
    capsys.readouterr()
    assert queue_daemon.main(["status"]) in (0, None)
    assert "⏸ held for a human merge: 757-a.md" in capsys.readouterr().out


# ── M-8 · release-hold ───────────────────────────────────────────────────────────────────────────────────────────
class TestM8Release:

    def _tray(self, q, stem="757-x"):
        tray = q.queue / "held" / "merge-hold"
        tray.mkdir(parents=True, exist_ok=True)
        (tray / f"{stem}.md").write_text(f"#!queue repo=cmp\n# {stem}\n## STOP\n(a)\n")
        (tray / f"{stem}.reason").write_text("held\n")

    @pytest.mark.parametrize("by,reason,why", [("Bob", "a b c", "known approver"), ("George", "too short", "3 words")])
    def test_the_approver_and_reason_are_checked(self, q, by, reason, why):
        self._tray(q)
        _held_branch(q)
        rc, msg = queue_daemon.release_hold("cmp", "orch-mp-757-x", by, reason)
        assert rc == 1 and why in msg

    def test_no_tray_brief_or_no_hold_line_is_refused(self, q):
        _held_branch(q)
        rc, msg = queue_daemon.release_hold("cmp", "orch-mp-757-x", "George", "lockfile reviewed by hand")
        assert rc == 1 and "no brief in" in msg
        git(q.repo, "checkout", "-q", "main")
        self._tray(q, "757-y")
        _held_branch(q, "757-y", note=("PRE-MERGE GATE: PASS — gates green",))
        rc, msg = queue_daemon.release_hold("cmp", "orch-mp-757-y", "George", "lockfile reviewed by hand")
        assert rc == 1 and "not a held route" in msg

    def test_a_release_appends_and_queues_a_regate_of_that_tip(self, q, capsys):
        self._tray(q)
        branch, tip = _held_branch(q)
        assert queue_daemon.main(["release-hold", "cmp", branch, "--by", "Gemma"]) == 2
        assert queue_daemon.main(["release-hold", "cmp", branch, "--by", "Gemma", "--reason", "lockfile diff reviewed ok"]) == 0
        assert "hold released" in capsys.readouterr().out
        note = git(q.repo, "notes", "show", tip).splitlines()
        assert note[0] == "PRE-MERGE GATE: PASS — gates green" and note[-1].startswith("MERGE HOLD RELEASE: by Gemma: lockfile diff reviewed ok")
        regate = (q.queue / "757-x-release.md").read_text()
        assert f"## Re-gate of: {branch} {tip}" in regate and "merge-hold release (ORCH-MERGE-HOLD-1)" in regate
        assert q.at("done", "757-x.md") and not q.at("held", "merge-hold", "757-x.md")
        rc, msg = queue_daemon.release_hold("cmp", branch, "George", "a second release attempt")
        assert rc == 1

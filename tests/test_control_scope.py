# filename: tests/test_control_scope.py
"""Tests for ORCH-CONTROL-SCOPE-1 — the queue's controls tell the truth.

S7-CORE-19 · SCP_Kanban row 145 · PCU v1-147 item 2 (S7-CORE-18: L-45, L-46, L-48, L-49, F-122..F-126;
S7-CORE-19: the WSL restart that killed the daemon and route 101). D-S7CORE13-02: RED first.
  P1 (C1)  a control request is scoped to the state it was issued against: a `resume` issued while a
           route ran does not lift the stop-on-failure pause that route caused             (TestP1*)
  P2 (C2)  a starting daemon fires nothing until told, when work is queued                (TestP2*)
  P3 (C3)  A1 is machine-checked: a brief fires only from a READY Kanban row             (TestP3*)
  P4 (C4)  a Yorsie (`worktree_mode: parallel`) route runs, is gated and merges in its own worktree;
           the main checkout's branch and tree are never the route's                     (TestP4*)
  P5 (C5)  the `parallel` lane gates every branch before any merge                        (TestP5*)
  P6 (C6)  `pause`/`resume` with an argument they do not take write nothing and exit 2;
           `status --json` is JSON alone                                                   (TestP6*)
  P7 (C7)  a daemon start recovers a dead route's dirty tree into a named stash; a dirty tree it cannot
           attribute is left alone and pauses; the systemd unit is shipped, not installed  (TestP7*)

Every predicate has a negative control. Every path is under tmp_path: no test reads or writes the
live queue, the live queue-state.json, the live canon, a product repo or ~/.config.
"""

import json
import os
import re
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
import prefire
import queue_daemon

ROOT = Path(__file__).parent.parent
TS = r"\d{8}-\d{6}"


def _dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


def _git(cmd: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)


def _sha(rev: str, cwd: Path) -> str:
    return _git(f"git rev-parse {rev}", cwd).stdout.strip()


def _repo(path: Path) -> Path:
    """A git repo on `main` with one commit."""
    path.mkdir(parents=True, exist_ok=True)
    _git("git init -q && git symbolic-ref HEAD refs/heads/main", path)
    _git("git config user.email t@t && git config user.name T", path)
    (path / "README.md").write_text("base\n")
    _git("git add -A && git commit -qm init", path)
    return path


# ═══════════════════════════════════════════════════════
# The daemon under tmp_path (P1, P2, P6, P7)
# ═══════════════════════════════════════════════════════
class Daemon:
    """One QueueDaemon wired under tmp_path; `_run_route` stubbed — no subprocess ever fires. A
    callback in `during[<brief>]` runs while that route is "running" (the CLI acting mid-route)."""

    def __init__(self, tmp_path: Path, monkeypatch, repos=None):
        self.tmp = tmp_path
        self.orch = tmp_path / "orch"
        self.queue = self.orch / "queue"
        self.state_file = tmp_path / "queue-state.json"
        not_git = tmp_path / "not-a-repo"
        not_git.mkdir()
        cfg = tmp_path / "repos.yaml"
        cfg.write_text(yaml.safe_dump({"repos": repos or {"r": {"project_dir": str(not_git)}}}))
        (self.orch / "state").mkdir(parents=True)
        for name, val in (("ORCH_DIR", self.orch), ("QUEUE_DIR", self.queue),
                          ("QUEUE_DONE", self.queue / "done"), ("QUEUE_FAILED", self.queue / "failed"),
                          ("QUEUE_STATE", self.state_file), ("REPOS_CONFIG", cfg),
                          ("LOG_DIR", tmp_path / "logs")):
            monkeypatch.setattr(queue_daemon, name, val)
        self.monkeypatch = monkeypatch
        self.d = queue_daemon.QueueDaemon()
        self.d.config.update(cooldown_seconds=0, model="m", effort="e")
        self.fired, self.codes, self.during, self.sleeps = [], [], {}, []

        def _route(cmd, batch_name, log_path):
            self.fired.append(batch_name)
            Path(log_path).write_text("route output\n")
            if batch_name in self.during:
                self.during[batch_name]()
            return self.codes.pop(0) if self.codes else 0
        self.d._run_route = _route

    def brief(self, stem: str) -> Path:
        self.queue.mkdir(parents=True, exist_ok=True)
        p = self.queue / f"{stem}.md"
        p.write_text(f"#!queue repo=r\n\n# {stem}\n")
        return p

    def state(self) -> dict:
        return json.loads(self.state_file.read_text()) if self.state_file.exists() else {}

    def stop_after(self, n: int, on_sleep=None):
        """Every sleep is recorded as (status, paused_reason); `on_sleep(i)` runs at sleep i; the
        n-th sleep stops the loop."""
        def _sleep(s):
            i = len(self.sleeps)
            self.sleeps.append((self.d.status, self.d.paused_reason))
            if on_sleep:
                on_sleep(i)
            if len(self.sleeps) >= n:
                self.d.status = "stopped"
        self.monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep))

    def issue(self, action: str, **kw):
        """What `python3 queue_daemon.py <action> …` does, without waiting for the ack."""
        return queue_daemon.request_control(action, wait_s=0, poll_s=0.001, **kw)

    def request(self) -> dict:
        return json.loads(queue_daemon.control_file().read_text())


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    return Daemon(tmp_path, monkeypatch)


# ═══════════════════════════════════════════════════════
# P1 · C1 — a control request cannot outlive its intent
# ═══════════════════════════════════════════════════════
class TestP1RequestScope:

    def test_R_a_resume_issued_while_a_route_ran_does_not_lift_its_failure_pause(self, daemon, capsys):
        """L-45: request 9 (`resume --reset-consecutive`) was written while route 95 ran; 95 failed,
        stop_on_failure paused the daemon, the next poll applied request 9 and 96 fired unamended."""
        daemon.brief("95-x")
        daemon.brief("96-y")
        daemon.d.start_running = True
        daemon.codes = [1]
        daemon.during["95-x.md"] = lambda: daemon.issue("resume", reset_consecutive=True)
        daemon.stop_after(1)
        daemon.d.run_loop()
        assert daemon.fired == ["95-x.md"], "96 must not fire on a resume issued before 95 failed"
        st = daemon.state()
        assert (st["daemon_status"], st["paused_reason"]) == ("paused", "stop-on-failure:95-x.md")
        rid = daemon.request()["id"]
        assert st["control_ack"] == rid, "the request is acknowledged, not left pending"
        assert st["control_result"] == (f"resume request {rid} expired — issued while running on 95-x.md, "
                                        f"daemon now paused for stop-on-failure:95-x.md; nothing resumed")
        assert f"[QUEUE] control request {rid}: resume request {rid} expired" in capsys.readouterr().out

    def test_negative_control_the_same_request_issued_after_the_pause_resumes(self, daemon):
        daemon.brief("95-x")
        daemon.brief("96-y")
        daemon.d.start_running = True
        daemon.codes = [1]
        daemon.stop_after(2, on_sleep=lambda i: i == 0 and daemon.issue("resume", reset_consecutive=True))
        daemon.d.run_loop()
        assert daemon.fired == ["95-x.md", "96-y.md"]
        assert daemon.state()["control_result"] == "resume --reset-consecutive → running"
        assert daemon.sleeps[0] == ("paused", "stop-on-failure:95-x.md")

    def test_the_request_records_the_state_it_was_issued_against(self, daemon):
        daemon.state_file.write_text(json.dumps({"daemon_status": "running", "pid": os.getpid(),
                                                 "paused_reason": None,
                                                 "current_batch": {"file": "95-x.md"}}))
        daemon.issue("resume", reset_consecutive=True)
        req = daemon.request()
        assert (req["issued_status"], req["issued_paused_reason"], req["issued_current_batch"]) == \
            ("running", None, "95-x.md")
        assert req["reason"] is None

    def _paused(self, daemon, reason, paused_at="2026-10-04T03:50:00"):
        daemon.d.is_daemon = True
        daemon.d.status, daemon.d.paused_reason, daemon.d.paused_at = "paused", reason, paused_at

    def _write(self, **req):
        f = queue_daemon.control_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps({"id": 1, "action": "resume", "reset_consecutive": True,
                                 "issued_status": "running", "issued_paused_reason": None,
                                 "issued_current_batch": "95-x.md", "reason": None,
                                 "requested_at": "2026-10-04T04:00:00", **req}))

    def test_an_explicit_reason_names_the_pause_it_lifts(self, daemon):
        self._paused(daemon, "max-consecutive:2")
        daemon.d.consecutive_count = 2
        self._write(reason="max-consecutive:2")
        daemon.d._poll_control()
        assert daemon.d.status == "running" and daemon.d.consecutive_count == 0

    def test_negative_control_an_explicit_reason_for_another_pause_expires(self, daemon):
        self._paused(daemon, "max-consecutive:2")
        self._write(reason="operator")
        daemon.d._poll_control()
        assert (daemon.d.status, daemon.d.paused_reason) == ("paused", "max-consecutive:2")
        assert daemon.d.control_result == ("resume request 1 expired — issued while running on 95-x.md "
                                           "(--reason operator), daemon now paused for max-consecutive:2; "
                                           "nothing resumed")

    def test_no_request_from_before_a_failure_pause_lifts_it_even_naming_it(self, daemon):
        """A stop-on-failure pause is lifted only by a resume issued AFTER it — `--reason` included."""
        self._paused(daemon, "stop-on-failure:95-x.md", paused_at="2026-10-04T03:50:00")
        self._write(reason="stop-on-failure:95-x.md", requested_at="2026-10-04T02:28:00")
        daemon.d._poll_control()
        assert (daemon.d.status, daemon.d.paused_reason) == ("paused", "stop-on-failure:95-x.md")
        assert "expired" in daemon.d.control_result and "nothing resumed" in daemon.d.control_result

    def test_negative_control_naming_it_after_the_failure_lifts_it(self, daemon):
        self._paused(daemon, "stop-on-failure:95-x.md", paused_at="2026-10-04T03:50:00")
        self._write(reason="stop-on-failure:95-x.md", requested_at="2026-10-04T03:51:00")
        daemon.d._poll_control()
        assert daemon.d.status == "running"

    def test_an_unscoped_request_is_never_applied(self, daemon):
        """A request with no issued state (written by a CLI that predates this) cannot be judged: expired."""
        self._paused(daemon, "operator")
        f = queue_daemon.control_file()
        f.write_text(json.dumps({"id": 1, "action": "resume", "reset_consecutive": False,
                                 "requested_at": "2026-10-04T04:00:00"}))
        daemon.d._poll_control()
        assert daemon.d.status == "paused"
        assert daemon.d.control_result.startswith("resume request 1 expired — issued while an unrecorded state")

    def test_a_pause_is_never_scoped(self, daemon):
        daemon.d.is_daemon, daemon.d.status = True, "running"
        self._write(action="pause", issued_status="paused", issued_paused_reason="operator")
        daemon.d._poll_control()
        assert (daemon.d.status, daemon.d.paused_reason) == ("paused", "operator")

    def test_the_cli_carries_reason_to_the_request(self, daemon, monkeypatch):
        seen = []
        monkeypatch.setattr(queue_daemon, "request_control", lambda action, **kw: seen.append((action, kw)) or (0, "ok"))
        assert queue_daemon.main(["resume", "--reason", "stop-on-failure:95-x.md", "--reset-consecutive"]) == 0
        assert seen == [("resume", {"reset_consecutive": True, "reason": "stop-on-failure:95-x.md"})]


# ═══════════════════════════════════════════════════════
# P2 · C2 — a restarted daemon fires nothing until told
# ═══════════════════════════════════════════════════════
START_PAUSED = ("[QUEUE] 🛡 start: {n} brief(s) queued — PAUSED (start:queue-non-empty); nothing fires until "
                "`python3 queue_daemon.py resume` (or a start with --start-running)")
START_EMPTY = "[QUEUE] 🛡 start: queue empty — running"
START_FORCED = "[QUEUE] 🛡 start: --start-running — running; {n} brief(s) queued fire now"


class TestP2Start:

    def test_R_a_start_with_briefs_queued_fires_nothing_and_says_why(self, daemon, capsys):
        """L-46: a restarted daemon fired the first queued brief at once (95, out of order, 02:27)."""
        daemon.brief("95-x")
        daemon.brief("96-y")
        daemon.stop_after(1)
        daemon.d.run_loop()
        assert daemon.fired == []
        st = daemon.state()
        assert (st["daemon_status"], st["paused_reason"]) == ("paused", "start:queue-non-empty")
        assert st["paused_at"]
        out = capsys.readouterr().out
        assert START_PAUSED.format(n=2) in out, out
        assert sum("🛡 start:" in l for l in out.splitlines()) == 1, "one line names which"

    def test_negative_control_an_empty_queue_starts_running(self, daemon, capsys):
        daemon.stop_after(1)
        daemon.d.run_loop()
        assert daemon.sleeps == [("running", None)]
        assert daemon.state()["daemon_status"] == "running"
        assert START_EMPTY in capsys.readouterr().out

    def test_start_running_keeps_the_old_behaviour(self, daemon, capsys):
        daemon.brief("95-x")
        daemon.brief("96-y")
        daemon.d.start_running = True
        daemon.stop_after(1)
        daemon.d.run_loop()
        assert daemon.fired == ["95-x.md", "96-y.md"]
        assert START_FORCED.format(n=2) in capsys.readouterr().out

    def test_resume_lifts_the_start_pause(self, daemon):
        daemon.brief("95-x")
        daemon.stop_after(2, on_sleep=lambda i: i == 0 and daemon.issue("resume"))
        daemon.d.run_loop()
        assert daemon.sleeps[0] == ("paused", "start:queue-non-empty")
        assert daemon.fired == ["95-x.md"]
        assert daemon.state()["control_result"] == "resume → running"

    def test_the_flag_reaches_the_daemon(self, daemon, monkeypatch):
        seen = []
        monkeypatch.setattr(queue_daemon.QueueDaemon, "run_loop",
                            lambda self: seen.append(getattr(self, "start_running", None)))
        assert queue_daemon.main([]) == 0
        assert queue_daemon.main(["--start-running"]) == 0
        assert seen == [False, True]


# ═══════════════════════════════════════════════════════
# P3 · C3 — a brief fires only from a READY Kanban row (A1)
# ═══════════════════════════════════════════════════════
HEADER = "| # | Item | Why | Brief | State | Executor | Gate notes |\n|---|---|---|---|---|---|---|\n"


def _row(n, state):
    return f"| {n} | `ITEM-{n}` | why | `{n}-x.md` | {state} | same | — |\n"


@pytest.fixture
def kanban(tmp_path, monkeypatch):
    """A canon dir with two SCP_Kanban versions (the newest decides) and one Yorsie_Kanban, named by
    a repos.yaml `kanban_dir` — the one place prefire reads it from."""
    canon = tmp_path / "canon"
    canon.mkdir()
    (canon / "SCP_Kanban_v0-9.md").write_text("# SCP Kanban v0-9\n\n" + HEADER + _row(2, "**`READY`**"))
    (canon / "SCP_Kanban_v0-10.md").write_text(
        "# SCP Kanban v0-10\n\nprose that mentions row 2 READY is not a row\n\n" + HEADER
        + _row(1, "**`READY`** — brief `1-x.md` (sha `65b00cfb`) authored + enqueued, then moved to `queue/held/`")
        + _row(2, "**`MERGED`** `1d9e5590` — back-filled (F-15)")
        + _row(3, "`BACKLOG` — after 2 merges")
        + _row(4, "**`READY`** → **`CUT`** (George)")
        + _row(5, "`COMPLETE`")
        + "\n## another table\n\n| # | Lane id | Intent | Brief | Runtime state | Acceptance | Gate |\n"
          "|---:|---|---|---:|---|---|---|\n| 68 | `L-1` | i | `22-…` | **`READY`** | `RETURNED` | PASS |\n")
    (canon / "Yorsie_Kanban_v0-3.md").write_text(
        "# Yorsie Kanban\n\n| # | Item | State at EOS |\n|---|---|---|\n| Y10 | `YORSIE-NAMES-1` | **`READY`**, queued |\n")
    (canon / "SCP_Kanban_v0-11_DRAFT_GEMMA.md").write_text(HEADER + _row(2, "**`READY`**"))   # never a member
    cfg = tmp_path / "repos.yaml"
    cfg.write_text(yaml.safe_dump({"kanban_dir": str(canon), "repos": {"x": {"project_dir": str(tmp_path)}}}))
    monkeypatch.setattr(prefire, "REPOS_CONFIG", cfg, raising=False)
    return canon


def _brief(tmp_path, kanban_line, name="b.md"):
    p = tmp_path / name
    p.write_text(f"#!queue repo=x\n\n# t\n## Repo: x\n{kanban_line}## Estimated runtime: 75-110 min\n")
    return p


class TestP3Kanban:

    def test_a_ready_row_passes(self, kanban, tmp_path):
        assert prefire.check(_brief(tmp_path, "## Kanban: SCP_Kanban row 1 (READY)\n")) == []

    @pytest.mark.parametrize("row,state", [(2, "MERGED"), (3, "BACKLOG"), (4, "CUT"), (5, "COMPLETE")])
    def test_R_a_row_that_is_not_ready_fails(self, kanban, tmp_path, row, state):
        fails = prefire.check(_brief(tmp_path, f"## Kanban: SCP_Kanban row {row}\n"))
        assert fails == [f"A1 KANBAN — SCP_Kanban row {row} is {state}, not READY"], fails

    def test_R_a_row_that_is_not_there_fails(self, kanban, tmp_path):
        fails = prefire.check(_brief(tmp_path, "## Kanban: SCP_Kanban row 9\n"))
        assert fails == ["A1 KANBAN — SCP_Kanban row 9 is missing from SCP_Kanban_v0-10.md, not READY"], fails

    def test_R_no_header_fails(self, kanban, tmp_path):
        fails = prefire.check(_brief(tmp_path, ""))
        assert fails == ["A1 KANBAN — no '## Kanban: <SCP_Kanban|Yorsie_Kanban> row <N>' header; a brief "
                         "fires only from a READY Kanban row"], fails

    def test_R_an_unreadable_kanban_fails_and_says_why(self, kanban, tmp_path, monkeypatch):
        gone = tmp_path / "no-canon"
        cfg = tmp_path / "repos2.yaml"
        cfg.write_text(yaml.safe_dump({"kanban_dir": str(gone), "repos": {}}))
        monkeypatch.setattr(prefire, "REPOS_CONFIG", cfg, raising=False)
        fails = prefire.check(_brief(tmp_path, "## Kanban: SCP_Kanban row 1\n"))
        assert fails == [f"A1 KANBAN — SCP_Kanban row 1 is unreadable (no SCP_Kanban_v*.md in {gone}), not READY"]

    def test_a_kanban_line_that_names_no_row_fails(self, kanban, tmp_path):
        """The held MiniMe briefs' shape (108, 109): a `## Kanban:` line in prose, no family and row."""
        fails = prefire.check(_brief(tmp_path, "## Kanban: MiniMe lane — Kanban row to be added at EOS\n"))
        assert fails == ["A1 KANBAN — '## Kanban: MiniMe lane — Kanban row to be added at EOS' names no Kanban "
                         "row ('<SCP_Kanban|Yorsie_Kanban> row <N>'), not READY"], fails

    def test_an_unknown_family_fails(self, kanban, tmp_path):
        fails = prefire.check(_brief(tmp_path, "## Kanban: Roadmap row 1\n"))
        assert fails == ["A1 KANBAN — '## Kanban: Roadmap row 1' names no Kanban family "
                         "(SCP_Kanban or Yorsie_Kanban), not READY"], fails

    def test_the_newest_version_decides_by_number_not_by_name(self, kanban, tmp_path):
        """v0-10 is newer than v0-9 (row 2 READY there, MERGED here); a _DRAFT_GEMMA file is not a member."""
        assert prefire.check(_brief(tmp_path, "## Kanban: SCP_Kanban row 2\n")) == \
            ["A1 KANBAN — SCP_Kanban row 2 is MERGED, not READY"]

    def test_the_state_column_is_found_per_table(self, kanban, tmp_path):
        assert prefire.check(_brief(tmp_path, "## Kanban: SCP_Kanban row 68\n")) == []

    def test_a_yorsie_row_is_read_from_the_yorsie_kanban(self, kanban, tmp_path):
        assert prefire.check(_brief(tmp_path, "## Kanban: Yorsie_Kanban row Y10\n")) == []

    def test_negative_control_a2_and_a8_still_report_beside_a1(self, kanban, tmp_path):
        p = tmp_path / "small.md"
        p.write_text("## Kanban: SCP_Kanban row 1\n## Estimated runtime: 12 min\n")
        fails = prefire.check(p)
        assert len(fails) == 1 and fails[0].startswith("A2 SIZING")

    def test_report_names_the_row_it_passed(self, kanban, tmp_path, capsys):
        assert prefire.report(_brief(tmp_path, "## Kanban: SCP_Kanban row 1\n"))
        assert ("Assertions: ✅ A1/A2/A8 pass — SCP_Kanban row 1 READY (SCP_Kanban_v0-10.md); "
                "declared 75m (floor 30m)") in capsys.readouterr().out

    def test_force_says_it_skipped_a1(self, caplog, monkeypatch):
        import logging
        monkeypatch.setattr(orchestrator, "PREFIRE_BYPASS", orchestrator.PREFIRE_BYPASS)
        monkeypatch.setattr(sys, "argv", ["orchestrator.py", "branches", "list", "--force", "--repo", "x"])
        monkeypatch.setattr(orchestrator, "set_active_repo", lambda n: n)
        monkeypatch.setattr(orchestrator, "list_branches", lambda *a, **k: [])
        with caplog.at_level(logging.INFO, logger="orch"):
            orchestrator.main()
        assert "--force: pre-fire assertions (A2/A8) BYPASSED; A1 Kanban READY not checked" in caplog.text


# ═══════════════════════════════════════════════════════
# P4 · C4 — a Yorsie route runs in a worktree, never in the dev tree
# ═══════════════════════════════════════════════════════
REPO_GLOBALS = ("ACTIVE_REPO_NAME", "ACTIVE_REPO_CONFIG", "PROJECT_ROOT", "YORSIE_DIR", "BRIEFS_DIR",
                "WORKTREE_BASE", "BRANCH_PREFIX", "MERGE_TARGET", "REMOTE", "LOG_SUBDIR", "WORKTREE_MODE",
                "TEST_CMD", "IS_META_FIRE", "TONI_MODEL", "TONI_EFFORT", "PREFIRE_BYPASS", "SKIP_SIT", "TONI_TIMEOUT")

# `npm run build` runs build.sh: it records where it ran, on which branch, and whether the dependency
# tree is reachable from there, then exits with the code in build-exit.
BUILD_SH = '''\
pwd -P > "$WT_PROBE"
git rev-parse --abbrev-ref HEAD >> "$WT_PROBE"
[ -f node_modules/dep.txt ] && echo deps >> "$WT_PROBE" || echo no-deps >> "$WT_PROBE"
exit "$(cat build-exit)"
'''
TONI_LOG = f"=== TONI EXECUTION ===\n{'=' * 60}\n\nDone.\n\n{'=' * 60}\nExit: 0\n"


class WorktreeRoute:

    def __init__(self, tmp_path: Path, monkeypatch, mode="parallel"):
        for g in REPO_GLOBALS:
            monkeypatch.setattr(orchestrator, g, getattr(orchestrator, g))
        self.tmp = tmp_path
        self.proj = tmp_path / "dev-pipeline"          # the dev server's tree
        y = self.proj / "yorsie"
        (y / "briefs").mkdir(parents=True)
        _git("git init -q && git symbolic-ref HEAD refs/heads/main", self.proj)
        _git("git config user.email t@t && git config user.name T", self.proj)
        (y / "package.json").write_text(json.dumps({"name": "stub", "private": True,
                                                    "scripts": {"build": "sh ./build.sh"}}))
        (y / "build.sh").write_text(BUILD_SH)
        (y / "build-exit").write_text("0")
        (y / ".gitignore").write_text("node_modules\n")
        (y / "node_modules").mkdir()
        (y / "node_modules" / "dep.txt").write_text("a dependency the route needs\n")
        self.brief = y / "briefs" / "batch-wt.md"
        self.brief.write_text("- id: B1\n  title: demo\n\n## Estimated runtime: 45-75 min\n")
        _git("git add -A && git commit -qm init", self.proj)
        self.main_before = _sha("main", self.proj)
        self.branch = "orch-batch-wt"
        self.base = tmp_path / "yorsie-toni"
        self.wt = self.base / "batch-wt"
        self.probe = tmp_path / "probe.txt"
        monkeypatch.setenv("WT_PROBE", str(self.probe))
        monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)

        entry = dict(yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"]["yorsie"])
        entry.update(project_dir=str(self.proj), worktree_base=str(self.base), worktree_mode=mode)
        entry.pop("test_cmd", None)
        cfg = tmp_path / "repos.yaml"
        cfg.write_text(yaml.safe_dump({"repos": {"yorsie": entry}}))
        monkeypatch.setattr(orchestrator, "REPOS_CONFIG_PATH", cfg)
        orchestrator.set_active_repo("yorsie")

        monkeypatch.setattr(orchestrator, "PREFIRE_BYPASS", True)
        monkeypatch.setattr(orchestrator, "RUN_PLAYWRIGHT", False)
        monkeypatch.setattr(orchestrator, "SIT_ARCHIVE_DIR", tmp_path / "archive")
        monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
        monkeypatch.setattr(orchestrator, "notify", lambda r: None)
        monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
        monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
        # The fire lock and running.json are the real orchestrator's; never touch them from a test.
        self.markers = []
        monkeypatch.setattr(orchestrator, "write_running", lambda *a, **k: None)
        monkeypatch.setattr(orchestrator, "clear_running", lambda *a, **k: None)
        monkeypatch.setattr(orchestrator, "_write_running_marker", lambda *a, **k: self.markers.append((a, k)))
        monkeypatch.setattr(orchestrator, "_clear_running_marker", lambda *a, **k: None)
        self.monkeypatch = monkeypatch
        self.seen = {}

    def dev(self) -> dict:
        """The dev tree as the dev server sees it."""
        return {"branch": _git("git rev-parse --abbrev-ref HEAD", self.proj).stdout.strip(),
                "head": _sha("HEAD", self.proj),
                "dirty": _git("git status --porcelain", self.proj).stdout.strip(),
                "feature": (self.proj / "yorsie" / "feature.ts").exists()}

    def fire(self, build_exit="0", meanwhile=None):
        """One route through the REAL run_batch, _run_batch_inner and run_pre_merge_gates. The executor
        commits feature.ts on the route branch; `meanwhile(proj)` is what someone does to the dev tree
        while it runs."""
        def _toni(target, proj):
            self.seen["proj"] = Path(proj)
            self.seen["deps"] = (Path(proj) / "yorsie" / "node_modules" / "dep.txt").exists()
            (proj / "yorsie" / "build-exit").write_text(build_exit)
            (proj / "yorsie" / "feature.ts").write_text("export const n: number = 1;\n")
            _git('git add -A && git commit -qm "feat: work"', proj)
            self.route_tip = _sha("HEAD", proj)
            self.seen["dev_while_running"] = self.dev()
            if meanwhile:
                meanwhile(self.proj)
            log = self.tmp / "toni-test.log"
            log.write_text(TONI_LOG)
            return 0, str(log)

        self.monkeypatch.setattr(orchestrator, "fire_toni", _toni)
        return orchestrator.run_batch(self.brief)

    def probed(self) -> list:
        return self.probe.read_text().splitlines()

    def worktrees(self) -> list:
        return [l.split()[1] for l in _git("git worktree list --porcelain", self.proj).stdout.splitlines()
                if l.startswith("worktree ")]


@pytest.fixture
def wtroute(tmp_path, monkeypatch):
    return WorktreeRoute(tmp_path, monkeypatch)


class TestP4Worktree:

    def test_R_the_route_never_appears_in_the_dev_tree_while_it_runs(self, wtroute):
        r = wtroute.fire()
        assert wtroute.seen["proj"] == wtroute.wt, f"Toni ran in {wtroute.seen['proj']}, not the route worktree"
        during = wtroute.seen["dev_while_running"]
        assert during == {"branch": "main", "head": wtroute.main_before, "dirty": "", "feature": False}, during
        assert r.status is orchestrator.Status.PASSED, r.error

    def test_R_the_build_gate_runs_in_the_worktree_on_the_route_branch_with_its_deps(self, wtroute):
        wtroute.fire()
        cwd, branch, deps = wtroute.probed()
        assert cwd == str((wtroute.wt / "yorsie").resolve()), cwd
        assert branch == wtroute.branch
        assert deps == "deps", "node_modules is linked into the worktree"
        assert wtroute.seen["deps"], "the executor sees the dependency tree too"

    def test_a_merged_route_lands_on_main_and_its_worktree_is_removed(self, wtroute):
        r = wtroute.fire()
        assert r.status is orchestrator.Status.PASSED and r.gate_outcome == "PASS", r.error
        assert _git(f"git merge-base --is-ancestor {wtroute.route_tip} main", wtroute.proj).returncode == 0
        after = wtroute.dev()
        assert (after["branch"], after["dirty"], after["feature"]) == ("main", "", True), after
        assert not wtroute.wt.exists(), "removed after the merge"
        assert wtroute.worktrees() == [str(wtroute.proj)]
        assert _git(f"git rev-parse --verify -q refs/heads/{wtroute.branch}", wtroute.proj).returncode != 0, \
            "the merged branch is deleted"
        assert (wtroute.proj / "yorsie" / "node_modules" / "dep.txt").exists(), "teardown never reaches the dev tree's deps"
        (args, kw), = wtroute.markers
        assert kw.get("route_worktree") == wtroute.wt, "the fire lock names the route's tree"

    def test_a_failed_route_keeps_its_worktree_and_names_it(self, wtroute, caplog):
        caplog.set_level("INFO", logger="orch")
        r = wtroute.fire(build_exit="1")
        assert r.status is orchestrator.Status.FAILED
        assert _sha("main", wtroute.proj) == wtroute.main_before
        assert wtroute.dev() == {"branch": "main", "head": wtroute.main_before, "dirty": "", "feature": False}
        assert wtroute.wt.is_dir() and _git("git rev-parse --abbrev-ref HEAD", wtroute.wt).stdout.strip() == wtroute.branch
        assert f"Route worktree preserved: {wtroute.wt} (branch {wtroute.branch})" in caplog.text

    def test_a_conflict_is_met_in_the_worktree_never_in_the_dev_tree(self, wtroute):
        def george(proj):
            (proj / "yorsie" / "feature.ts").write_text("export const n: string = 'george';\n")
            _git('git add -A && git commit -qm "george: same file"', proj)
        r = wtroute.fire(meanwhile=george)
        george_tip = _sha("main", wtroute.proj)
        assert r.status is orchestrator.Status.FAILED
        assert r.error.startswith(f"{orchestrator.MERGE_CONFLICT_VERDICT} — {wtroute.branch} → main"), r.error
        dev = wtroute.dev()
        assert (dev["branch"], dev["head"], dev["dirty"]) == ("main", george_tip, ""), dev
        assert "<<<<<<<" not in (wtroute.proj / "yorsie" / "feature.ts").read_text()
        assert _sha(wtroute.branch, wtroute.proj) == wtroute.route_tip, "branch preserved"
        assert wtroute.wt.is_dir()

    def test_a_dev_tree_that_would_be_clobbered_is_not(self, wtroute):
        """Main advances only by fast-forward in the checkout that holds it; a local file there that
        the merge would overwrite stops the landing, and nothing in the dev tree changes."""
        r = wtroute.fire(meanwhile=lambda proj: (proj / "yorsie" / "feature.ts").write_text("george's draft\n"))
        assert r.status is orchestrator.Status.FAILED
        assert r.error.startswith("NOT LANDED — main is checked out at"), r.error
        assert _sha("main", wtroute.proj) == wtroute.main_before
        assert (wtroute.proj / "yorsie" / "feature.ts").read_text() == "george's draft\n"
        assert _sha(wtroute.branch, wtroute.proj) == wtroute.route_tip and wtroute.wt.is_dir()

    def test_negative_control_single_stream_runs_in_the_main_checkout(self, tmp_path, monkeypatch):
        route = WorktreeRoute(tmp_path, monkeypatch, mode="single-stream")
        r = route.fire()
        assert route.seen["proj"] == route.proj
        assert route.seen["dev_while_running"]["branch"] == route.branch, "the route branch IS checked out there"
        assert r.status is orchestrator.Status.PASSED and not route.base.exists()


# ═══════════════════════════════════════════════════════
# P5 · C5 — every lane is gated
# ═══════════════════════════════════════════════════════
class TestP5Parallel:

    @pytest.fixture
    def par(self, tmp_path, monkeypatch):
        for g in REPO_GLOBALS:
            monkeypatch.setattr(orchestrator, g, getattr(orchestrator, g))
        proj = _repo(tmp_path / "repo")
        cfg = tmp_path / "repos.yaml"
        cfg.write_text(yaml.safe_dump({"repos": {"par": {
            "project_dir": str(proj), "branch_prefix": "orch-par", "merge_target": "main",
            "worktree_mode": "parallel", "worktree_base": str(tmp_path / "wts")}}}))
        monkeypatch.setattr(orchestrator, "REPOS_CONFIG_PATH", cfg)
        orchestrator.set_active_repo("par")
        monkeypatch.setattr(orchestrator, "RUN_PLAYWRIGHT", False)
        ns = types.SimpleNamespace(proj=proj, events=[], briefs=[], commit=True)
        for stem in ("a-good", "b-bad"):
            p = tmp_path / f"{stem}.md"
            p.write_text("- id: B1\n  title: t\n")
            ns.briefs.append(p)
        now = orchestrator.datetime.now().isoformat()

        def _run_batch(bf, wt):
            (wt / f"{bf.stem}.txt").write_text(bf.stem + "\n")
            if ns.commit:
                _git(f'git add -A && git commit -qm "{bf.stem}"', wt)
            ns.events.append(("ran", bf.stem))
            return orchestrator.Result(batch_file=bf.name, status=orchestrator.Status.PASSED, started=now,
                                       finished=now, duration_s=0.0, exit_code=0, briefs=1)

        def _gates(repo_path, branch_name=None):
            ns.events.append(("gate", branch_name, Path(repo_path),
                              (Path(repo_path) / f"{branch_name.split('-')[2]}-{branch_name.split('-')[3]}.txt").exists(),
                              _git("git status --porcelain", repo_path).stdout.strip()))
            if "bad" in branch_name:
                return orchestrator.GateVerdict(orchestrator.GateOutcome.FAIL_PRODUCT, "build", "tsc", "TS2322")
            return orchestrator.GateVerdict(orchestrator.GateOutcome.PASS, None, None, "build green")

        real_merge = orchestrator.merge_branch
        monkeypatch.setattr(orchestrator, "run_batch", _run_batch)
        monkeypatch.setattr(orchestrator, "run_pre_merge_gates", _gates)
        monkeypatch.setattr(orchestrator, "merge_branch",
                            lambda br: ns.events.append(("merge", br)) or real_merge(br))
        return ns

    def _on_main(self, proj, name):
        return _git(f"git cat-file -e main:{name}", proj).returncode == 0

    def test_R_a_branch_whose_gate_fails_is_not_merged(self, par):
        orchestrator.run_parallel(par.briefs, force=True)
        assert self._on_main(par.proj, "a-good.txt"), "the green branch merged"
        assert not self._on_main(par.proj, "b-bad.txt"), "the red branch must not merge"
        assert _git("git rev-parse --verify -q orch-par-b-bad-w2", par.proj).returncode == 0, "branch preserved"
        assert _git("git cat-file -e orch-par-b-bad-w2:b-bad.txt", par.proj).returncode == 0

    def test_every_branch_is_gated_in_its_own_worktree_before_any_merge(self, par, tmp_path):
        orchestrator.run_parallel(par.briefs, force=True)
        kinds = [e[0] for e in par.events]
        assert kinds.index("merge") > max(i for i, k in enumerate(kinds) if k == "gate"), par.events
        gates = [e for e in par.events if e[0] == "gate"]
        assert [(g[1], g[2]) for g in gates] == [("orch-par-a-good-w1", tmp_path / "wts" / "toni-1"),
                                                 ("orch-par-b-bad-w2", tmp_path / "wts" / "toni-2")]
        assert [e[1] for e in par.events if e[0] == "merge"] == ["orch-par-a-good-w1"]

    def test_uncommitted_worker_output_is_committed_before_it_is_gated(self, par):
        """The gate judges what merges: a worker that left its work uncommitted has it committed on its
        branch first (the route lane's `git add -A`), so the gate never passes a tree the merge omits."""
        par.commit = False
        orchestrator.run_parallel(par.briefs, force=True)
        gates = [e for e in par.events if e[0] == "gate"]
        assert all(g[4] == "" for g in gates), f"gated a dirty tree: {gates}"
        assert self._on_main(par.proj, "a-good.txt") and not self._on_main(par.proj, "b-bad.txt")

    def test_negative_control_two_green_branches_both_merge(self, par, monkeypatch):
        monkeypatch.setattr(orchestrator, "run_pre_merge_gates", lambda repo_path, branch_name=None: (
            orchestrator.GateVerdict(orchestrator.GateOutcome.PASS, None, None, "green")))
        orchestrator.run_parallel(par.briefs, force=True)
        assert self._on_main(par.proj, "a-good.txt") and self._on_main(par.proj, "b-bad.txt")


# ═══════════════════════════════════════════════════════
# P6 · C6 — CLI truth
# ═══════════════════════════════════════════════════════
class TestP6Cli:

    @pytest.fixture
    def live(self, daemon, monkeypatch):
        """A daemon the CLI believes is running (this test's own pid), and an ack wait that never sleeps."""
        daemon.state_file.write_text(json.dumps({"daemon_status": "running", "pid": os.getpid(),
                                                 "control_ack": 3, "current_batch": None}))
        f = queue_daemon.control_file()
        f.write_text(json.dumps({"id": 3, "action": "pause", "reset_consecutive": False}, indent=2))
        real = queue_daemon.threading
        monkeypatch.setattr(queue_daemon, "threading", types.SimpleNamespace(
            Event=lambda: types.SimpleNamespace(wait=lambda s: None), Lock=real.Lock, Thread=real.Thread))
        return f

    @pytest.mark.parametrize("argv", [["pause", "--help"], ["pause", "-h"], ["pause", "now"],
                                      ["resume", "--help"], ["resume", "-h"], ["resume", "--reset"],
                                      ["resume", "--reason"], ["resume", "--reset-consecutive", "x"]])
    def test_R_an_argument_a_command_does_not_take_writes_nothing(self, live, argv, capsys):
        before = live.read_bytes()
        assert queue_daemon.main(argv) == 2
        assert live.read_bytes() == before, "the control file is byte-identical"
        err = capsys.readouterr().err
        assert err.startswith("Usage: ") and "pause | resume [--reset-consecutive] [--reason <paused_reason>]" in err

    def test_negative_control_a_bare_pause_writes_one_request(self, live):
        before = live.read_bytes()
        assert queue_daemon.main(["pause"]) == 1          # no daemon thread here to acknowledge it
        assert live.read_bytes() != before and json.loads(live.read_text())["id"] == 4

    def test_R_status_json_is_json_alone(self, daemon, capsys):
        daemon.state_file.write_text(json.dumps({"daemon_status": "paused", "paused_reason": "operator",
                                                 "pid": os.getpid()}))
        assert queue_daemon.main(["status", "--json"]) == 0
        body = json.loads(capsys.readouterr().out)
        assert (body["daemon_status"], body["paused_reason"]) == ("paused", "operator")

    def test_negative_control_plain_status_is_unchanged(self, daemon, capsys):
        daemon.state_file.write_text(json.dumps({"daemon_status": "paused", "paused_reason": "operator",
                                                 "pid": os.getpid()}))
        assert queue_daemon.main(["status"]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0].startswith("daemon_status=paused paused_reason=operator ")
        assert json.loads("\n".join(lines[1:]))["daemon_status"] == "paused"

    def test_the_brief_s_own_predicate_through_a_pipe(self, tmp_path):
        """`status --json | python3 -c 'import json,sys;json.load(sys.stdin)'` exits 0 — run as a real
        process with HOME under tmp_path, so ~/spectricom-orchestrator is a scratch dir."""
        env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
        env["HOME"] = str(tmp_path)
        r = subprocess.run(f"{sys.executable} {ROOT / 'queue_daemon.py'} status --json | "
                           f"{sys.executable} -c 'import json,sys;json.load(sys.stdin)'",
                           shell=True, capture_output=True, text=True, env=env, timeout=60)
        assert r.returncode == 0, r.stderr


# ═══════════════════════════════════════════════════════
# P7 · C7 — a WSL restart loses no work
# ═══════════════════════════════════════════════════════
class DeadRoute:
    """A product repo whose route process died with its branch checked out and work uncommitted."""

    BRANCH = "orch-mp-101-clip-truth-2"

    def __init__(self, tmp_path: Path, monkeypatch):
        self.repo = _repo(tmp_path / "clinical-mp")
        self.daemon = Daemon(tmp_path, monkeypatch, repos={
            "clinical-mp": {"project_dir": str(self.repo), "merge_target": "main", "branch_prefix": "orch-mp"}})
        _git(f"git checkout -qb {self.BRANCH}", self.repo)
        (self.repo / "chart.ts").write_text("committed on the branch\n")
        _git('git add -A && git commit -qm "route: first half"', self.repo)
        self.branch_tip = _sha("HEAD", self.repo)
        self.marker = self.daemon.orch / "state" / "running-clinical-mp.json"

    def dirty(self):
        (self.repo / "README.md").write_text("base\nhalf-written edit\n")     # tracked, modified
        (self.repo / "new-file.ts").write_text("untracked, new\n")             # untracked

    def lock(self, pid=None, **extra):
        self.marker.write_text(json.dumps({
            "pid": _dead_pid() if pid is None else pid, "batch_id": "101-clip-truth-2", "repo": "clinical-mp",
            "repo_path": str(self.repo), "branch": self.BRANCH, "meta_fire_worktree": None,
            "is_self_mod": False, **extra}))

    def snapshot(self) -> dict:
        return {"head": _git("git symbolic-ref -q HEAD", self.repo).stdout.strip(),
                "status": _git("git status --porcelain", self.repo).stdout,
                "stash": _git("git stash list", self.repo).stdout,
                "branches": _git("git for-each-ref --format='%(refname:short) %(objectname)' refs/heads",
                                 self.repo).stdout,
                "readme": (self.repo / "README.md").read_text()}


@pytest.fixture
def dead(tmp_path, monkeypatch):
    return DeadRoute(tmp_path, monkeypatch)


class TestP7Recovery:

    def test_R_a_dead_routes_dirty_tree_is_stashed_named_and_left_on_main(self, dead, capsys):
        dead.dirty()
        dead.lock()
        dead.daemon.stop_after(1)
        dead.daemon.d.run_loop()
        stash = _git("git stash list", dead.repo).stdout.strip().splitlines()
        assert len(stash) == 1, stash
        assert re.fullmatch(rf"stash@\{{0\}}: On {dead.BRANCH}: 101-clip-truth-2 partial WIP \(route process died "
                            rf"{TS}\), recovered by daemon start", stash[0]), stash[0]
        assert _git("git cat-file -e stash@{0}^3:new-file.ts", dead.repo).returncode == 0, "untracked work kept"
        assert "half-written edit" in _git("git show stash@{0}:README.md", dead.repo).stdout, "tracked work kept"
        renamed = [b for b in _git("git branch --format='%(refname:short)'", dead.repo).stdout.split()
                   if b.startswith(dead.BRANCH)]
        assert len(renamed) == 1 and re.fullmatch(rf"{dead.BRANCH}-died-{TS}", renamed[0]), renamed
        assert _sha(renamed[0], dead.repo) == dead.branch_tip, "the branch is renamed, never deleted"
        assert _git("git symbolic-ref HEAD", dead.repo).stdout.strip() == "refs/heads/main"
        assert _git("git status --porcelain", dead.repo).stdout == "", "tree clean"
        sha = _sha("stash@{0}", dead.repo)
        out = capsys.readouterr().out
        line = [l for l in out.splitlines() if "🛡 dead-route-recovery:" in l]
        assert line == [f"[QUEUE] 🛡 dead-route-recovery: clinical-mp — 101-clip-truth-2's uncommitted work stashed "
                        f"as {sha[:12]} ({stash[0].split(': ', 2)[2]}); branch {dead.BRANCH} → {renamed[0]}; "
                        f"main checked out in {dead.repo}"], out
        assert dead.daemon.state()["daemon_status"] == "running", "nothing left to hold the queue for"

    def test_R_a_dirty_tree_on_another_branch_is_untouched_and_pauses(self, dead, capsys):
        _git("git checkout -q main", dead.repo)
        dead.dirty()
        dead.lock()
        before = dead.snapshot()
        dead.daemon.stop_after(1)
        dead.daemon.d.run_loop()
        assert dead.snapshot() == before, "nothing in the tree, the stash list or the branches moved"
        st = dead.daemon.state()
        assert (st["daemon_status"], st["paused_reason"]) == ("paused", "start:dirty-tree:clinical-mp")
        assert (f"[QUEUE] 🛡 dead-route-recovery: clinical-mp — {dead.repo} is dirty on main, not on "
                f"101-clip-truth-2's branch {dead.BRANCH}; left as it is — PAUSED (start:dirty-tree:clinical-mp)"
                ) in capsys.readouterr().out

    def test_negative_control_a_clean_tree_is_left_alone(self, dead):
        dead.lock()
        before = dead.snapshot()
        dead.daemon.stop_after(1)
        dead.daemon.d.run_loop()
        assert dead.snapshot() == before
        assert dead.daemon.state()["daemon_status"] == "running"

    def test_negative_control_a_live_route_is_never_touched(self, dead):
        dead.dirty()
        dead.lock(pid=os.getpid())
        before = dead.snapshot()
        dead.daemon.stop_after(1)
        dead.daemon.d.run_loop()
        assert dead.snapshot() == before and dead.marker.exists()

    def test_a_worktree_route_is_not_the_main_checkouts(self, dead):
        """A route that ran in its own worktree (meta-fire, or a Yorsie route) never touched the main
        checkout: whatever is dirty there is not its work, and is neither stashed nor held against it."""
        dead.dirty()
        dead.lock(route_worktree=str(dead.repo.parent / "elsewhere"))
        before = dead.snapshot()
        dead.daemon.stop_after(1)
        dead.daemon.d.run_loop()
        assert dead.snapshot() == before
        assert dead.daemon.state()["daemon_status"] == "running"

    def test_the_recovery_never_destroys(self):
        src = (ROOT / "queue_daemon.py").read_text()
        body = src.split("def _recover_dead_route(")[1].split("\n    def ")[0]
        for verb in ("reset --hard", "git clean", "clean -f", "checkout -- .", "branch -D", "branch -d",
                     "stash drop", "stash pop", "rm -"):
            assert verb not in body, f"recovery must never run `{verb}`"


class TestP7Unit:

    UNIT = ROOT / "systemd" / "spectricom-queue-daemon.service"
    SCRIPT = ROOT / "scripts" / "install-queue-daemon-unit.sh"

    def test_the_unit_runs_the_daemon_without_the_api_key_and_restarts_it(self):
        text = self.UNIT.read_text()
        assert "ExecStart=/usr/bin/env -u ANTHROPIC_API_KEY /usr/bin/python3 -u @ORCH_DIR@/queue_daemon.py" in text
        assert "UnsetEnvironment=ANTHROPIC_API_KEY" in text
        assert "Environment=PATH=@DAEMON_PATH@" in text
        assert "Restart=on-failure" in text and "WantedBy=default.target" in text
        assert "KillMode=process" in text, "a daemon restart must not kill the route it launched"
        execs = [l for l in text.splitlines() if l.startswith("ExecStart=")]
        assert len(execs) == 1 and "--start-running" not in execs[0], \
            "a boot-started daemon comes up paused when work is queued"

    def test_the_path_comes_from_config(self):
        path = yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["daemon_path"]
        parts = path.split(":")
        assert re.fullmatch(r"/home/\w+/\.nvm/versions/node/v[\d.]+/bin", parts[0]), parts[0]
        assert any(p.endswith("/.local/bin") for p in parts), "`claude` lives in ~/.local/bin"

    def _fake_bin(self, tmp_path):
        b = tmp_path / "bin"
        b.mkdir()
        sc = b / "systemctl"
        sc.write_text(f'#!/bin/sh\necho "$@" >> {tmp_path}/systemctl.calls\n')
        sc.chmod(sc.stat().st_mode | stat.S_IEXEC)
        return b

    def _install(self, tmp_path, state):
        env = {"HOME": str(tmp_path), "PATH": f"{self._fake_bin(tmp_path)}:/usr/bin:/bin",
               "QUEUE_STATE": str(state)}
        return subprocess.run(["bash", str(self.SCRIPT)], capture_output=True, text=True, env=env, timeout=60)

    def test_install_renders_enables_and_never_starts_beside_a_live_daemon(self, tmp_path):
        state = tmp_path / "queue-state.json"
        state.write_text(json.dumps({"daemon_status": "paused", "pid": os.getpid()}))
        r = self._install(tmp_path, state)
        assert r.returncode == 0, r.stdout + r.stderr
        unit = (tmp_path / ".config" / "systemd" / "user" / "spectricom-queue-daemon.service").read_text()
        assert "@ORCH_DIR@" not in unit and "@DAEMON_PATH@" not in unit
        assert f"ExecStart=/usr/bin/env -u ANTHROPIC_API_KEY /usr/bin/python3 -u {ROOT}/queue_daemon.py" in unit
        cfg_path = yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["daemon_path"]
        assert f"Environment=PATH={cfg_path}\n" in unit
        calls = (tmp_path / "systemctl.calls").read_text().splitlines()
        assert calls == ["--user daemon-reload", "--user enable spectricom-queue-daemon.service"], calls
        assert f"a daemon is running now (pid {os.getpid()})" in r.stdout

    def test_negative_control_with_no_daemon_it_still_only_enables(self, tmp_path):
        state = tmp_path / "queue-state.json"
        state.write_text(json.dumps({"daemon_status": "running", "pid": _dead_pid()}))
        r = self._install(tmp_path, state)
        assert r.returncode == 0, r.stdout + r.stderr
        calls = (tmp_path / "systemctl.calls").read_text().splitlines()
        assert calls == ["--user daemon-reload", "--user enable spectricom-queue-daemon.service"], calls
        assert "systemctl --user start spectricom-queue-daemon.service" in r.stdout

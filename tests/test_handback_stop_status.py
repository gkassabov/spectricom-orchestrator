# filename: tests/test_handback_stop_status.py
"""Tests for ORCH-HANDBACK-STOP-STATUS-1 (Kanban 690, Bug ORCH-HANDBACK-STOP-REPORTED-PASSED-1).

Route 685 STOPPED (g): its executor wrote only a handback whose line 1 is `## STATUS: STOP (g)`, the briefs-only
gate passed it, it merged, and it was reported `🏁 FINAL STATUS: passed` and filed `completed` (exit 0). A route
whose handback's first status line says STOP / PARTIAL is now `stopped` — what it merges does not change.

  P-1   the 685 case through the route lane                                   (TestP1RouteLane)
  P-2   PARTIAL                                                               (TestP1RouteLane)
  P-3   the reader, per line                                                  (TestP3Reader)
  P-3b  the handback path: zero-prefixed stems, the re-gate lane              (TestP3bPath)
  P-4   `orchestrator.py run` exits EXIT_STOPPED, state.json `stopped`        (TestP4Exit)
  P-4b  `queue` exit / run_queue halts / watch() records it                   (TestP4Exit)
  P-5   the queue daemon                                                      (TestP5Daemon)
  P-6   the meta-fire (self-mod) lane                                         (test_P6_*)
  P-7   a `worktree_mode: parallel` route worktree                            (test_P7_*)
  P-7b  run_parallel                                                          (test_P7b_*)
  P-8   verify                                                                (test_P8_*)
  P-9   controls: today's verdicts unchanged                                  (TestP9Controls)

Harness: tests.test_gate_cost's lane (a real repo, the brief queued outside it, the leg commands scripted),
tests.test_regate_gates_only's re-gate shape, tests.test_control_scope's WorktreeRoute. No test calls the real
`claude`, and nothing reads or writes the live orchestrator's queue/, state/ or logs/. Module-level imports are
existing symbols only, so the RED run on the base collects.
"""

import json
import logging
import shutil
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
import queue_daemon  # noqa: E402
from tests.test_gate_cost import (REPO, Legs, Night, _activate, _commit, _git, _msgs, _repo,  # noqa: E402
                                  _toni_log)

ROOT = Path(__file__).parent.parent
FIXTURES = Path(__file__).parent / "fixtures" / "handback"
R54 = "toni-54-surface-truth-1-counts-and-columns-20260927-174452.log"   # advertises background work
STEM = "685-x"
STOP_G = "## STATUS: STOP (g) — the hard stop fired; nothing built.\n\nDetails.\n"


def _stopped():
    return getattr(orchestrator.Status, "STOPPED", "stopped-not-on-base")


def _briefs_only(*paths) -> str:
    return (f"PASS (briefs-only diff ({len(paths)} files: {', '.join(paths)}) — build/SIT/unit not run "
            f"(D-S7CORE29-02))")


def _final(caplog) -> str:
    lines = [m for m in _msgs(caplog) if "FINAL STATUS" in m]
    assert len(lines) == 1, lines
    return lines[0]


# ═══════════════════════════════════════════════════════
# the rig
# ═══════════════════════════════════════════════════════
class Lane:
    def __init__(self, tmp_path, monkeypatch):
        self.tmp, self.mp = tmp_path, monkeypatch
        self.repo = _repo(tmp_path / "repo")
        self.cfg = _activate(monkeypatch, tmp_path, self.repo)
        self.queue = tmp_path / "queue"
        self.queue.mkdir()
        orch = tmp_path / "orch"
        (orch / "state").mkdir(parents=True)
        for name, val in (("IS_META_FIRE", False), ("RUN_PLAYWRIGHT", False), ("WORKTREE_MODE", "single-stream"),
                          ("PREFIRE_BYPASS", True), ("ORCH_DIR", orch), ("RUNNING_FILE", orch / "running.json"),
                          ("QUEUE_DIR", self.queue), ("QUEUE_DONE", self.queue / "done"),
                          ("STATE_FILE", tmp_path / "state.json"), ("BRIEFS_DIR", self.repo / "briefs")):
            monkeypatch.setattr(orchestrator, name, val)
        monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
        monkeypatch.setattr(orchestrator, "notify", lambda r: None)
        monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
        monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
        for fn in ("write_running", "clear_running", "_write_running_marker", "_clear_running_marker"):
            monkeypatch.setattr(orchestrator, fn, lambda *a, **k: None)
        monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
        monkeypatch.delenv("ORCH_REGATE_GATES_ONLY", raising=False)
        self.legs = Legs(monkeypatch)
        self.fired = []

    def brief(self, stem=STEM) -> Path:
        b = self.queue / f"{stem}.md"
        b.write_text(f"#!queue repo={REPO}\n\n# {stem}\n- id: B1\n  title: demo\n")
        return b

    def toni(self, write=None, commit=False, log_fixture=None, also=None):
        """The fake fire_toni: writes `write` ({relpath: text}) into the checkout it is handed, commits them when
        `commit`, runs `also(proj)`, and returns a clean fire_toni-shaped log (or a copy of `log_fixture`)."""
        def _fire(target, proj):
            proj = Path(proj)
            self.fired.append(Path(target).name)
            for rel, text in (write or {}).items():
                (proj / rel).parent.mkdir(parents=True, exist_ok=True)
                (proj / rel).write_text(text)
            if also:
                also(proj)
            if commit:
                _git(proj, "add", "-A")
                _git(proj, "commit", "-qm", f"handback: {Path(target).stem}")
            logs = self.tmp / "logs" / "cost"
            if log_fixture:
                logs.mkdir(parents=True, exist_ok=True)
                return 0, str(shutil.copyfile(FIXTURES / log_fixture, logs / log_fixture))
            return 0, _toni_log(logs / f"toni-{Path(target).stem}-20261115-000000.log")
        self.mp.setattr(orchestrator, "fire_toni", _fire)

    def inner(self, brief):
        return orchestrator._run_batch_inner(brief, self.repo, datetime.now(), worktree=None)

    def on_main(self, rel) -> bool:
        return _git(self.repo, "ls-tree", "--name-only", "main", rel) == rel


@pytest.fixture
def lane(tmp_path, monkeypatch):
    return Lane(tmp_path, monkeypatch)


# ═══════════════════════════════════════════════════════
# P-1 / P-2 · the route lane
# ═══════════════════════════════════════════════════════
class TestP1RouteLane:

    def test_P1_the_685_case_is_stopped_merged_and_retired(self, lane, caplog):
        b = lane.brief()
        lane.toni({f"briefs/{STEM}.handback.md": STOP_G})
        main_before = _git(lane.repo, "rev-parse", "main")
        with caplog.at_level(logging.INFO, logger="orch"):
            r = lane.inner(b)
        gate = _briefs_only(f"briefs/{STEM}.handback.md", f"briefs/{STEM}.md")
        assert _final(caplog) == f"🏁 FINAL STATUS: stopped | gate: {gate} | handback: STOP (g)"
        assert r.status is _stopped() and r.gate_outcome == "PASS"
        assert lane.legs.calls == [], "briefs-only: no leg ran, as today"
        assert _git(lane.repo, "rev-parse", "main") != main_before and lane.on_main(f"briefs/{STEM}.handback.md"), \
            "the handback IS on the merge target"
        assert not b.exists() and (lane.queue / "done" / b.name).exists(), "the brief retired as today"
        assert r.error == 'handback STATUS: STOP (g) — "## STATUS: STOP (g) — the hard stop fired; nothing built."'
        hb = lane.repo / "briefs" / f"{STEM}.handback.md"
        assert f"🛑 handback-status: STOP (g) ({hb})" in _msgs(caplog)

    def test_P2_partial(self, lane, caplog):
        b = lane.brief()
        lane.toni({f"briefs/{STEM}.handback.md": "## STATUS: PARTIAL — Part A built\n"})
        with caplog.at_level(logging.INFO, logger="orch"):
            r = lane.inner(b)
        gate = _briefs_only(f"briefs/{STEM}.handback.md", f"briefs/{STEM}.md")
        assert _final(caplog) == f"🏁 FINAL STATUS: stopped | gate: {gate} | handback: PARTIAL"
        assert r.status is _stopped() and lane.on_main(f"briefs/{STEM}.handback.md")
        assert r.error == 'handback STATUS: PARTIAL — "## STATUS: PARTIAL — Part A built"'

    def test_G4_notify_says_stopped_with_the_error_line(self, monkeypatch, caplog):
        monkeypatch.setattr(orchestrator, "HAS_SLACK", False)
        now = datetime.now().isoformat()
        r = orchestrator.Result(batch_file="685-x.md", status=_stopped(), started=now, finished=now,
                                duration_s=3.0, exit_code=0, briefs=1, gate_outcome="PASS",
                                error='handback STATUS: STOP (g) — "## STATUS: STOP (g)"')
        with caplog.at_level(logging.INFO, logger="orch"):
            orchestrator.notify(r)
        assert "🛑 685-x.md — stopped | 1 briefs | 3s | gate: PASS\n  handback STATUS: STOP (g)" in caplog.text


# ═══════════════════════════════════════════════════════
# P-3 · the reader
# ═══════════════════════════════════════════════════════
READER_CASES = [
    ("## STATUS: STOP (g)", "STOP (g)"),
    ("**Status: STOPPED on STOP (c) — the seed is missing**", "STOP (c)"),
    ("## STATUS: STOPPED — STOP (b) on the schema", "STOP (b)"),
    ("## Status: STOPPED under STOP (e)", "STOP (e)"),
    ("**Status:** STOPPED. Nothing is committed", "STOP"),
    ("## STATUS: DONE", "DONE"),
    ("## STATUS: DONE. STOP (e) did not fire", "DONE"),
    ("**Status:** both Parts shipped and gate-ready. No STOP was hit", "DONE"),
    ("**Status: COMPLETE.**", "DONE"),
    ("## STATUS: BUILT", "DONE"),
    ("## STATUS: HELD — STOP (e) on both parts; nothing committed.", "STOP (e)"),
    ("## STATUS: DONE except G7. G7 is HELD (STOP (d): the go is pending)", "PARTIAL"),
    ("## STATUS: Parts A and B DONE; Part C STOP (b), not built", "PARTIAL"),
    ("## STATUS: DONE. STOP (a), (b) and (c) did not fire.", "DONE"),
    ("**Route status: PARTIAL.** Part A is STOPPED under STOP (g)", "PARTIAL"),
    ("**Status: B, C built. A is STOPPED (STOP (c)). I is withdrawn.** STOP (a) and (b) did not fire.", "PARTIAL"),
    ("**Status: DONE.** SMALL-FIXES-23's held item-1a patch is applied as is", "DONE"),
    ("**Status:** DONE. gates green except `tsc -p server`, identical at HEAD", "DONE"),
    ("## STATUS: DONE — x, so it is not STOP (a). No STOP fired.", "DONE"),
]


class TestP3Reader:

    @pytest.mark.parametrize("line,label", READER_CASES, ids=[c[0][:48] for c in READER_CASES])
    def test_P3_a_status_line(self, tmp_path, line, label):
        p = tmp_path / "x.handback.md"
        p.write_text(f"# x — handback\n\n{line}\n\nbody\n")
        hs = orchestrator.handback_status(p)
        assert hs is not None and hs.label == label, hs
        assert hs.is_stop is (label != "DONE")
        assert hs.line == line

    @pytest.mark.parametrize("body", [
        "# x\n\n**Result:** STOP (b)\n",                         # no Status: label — not read (fail-open)
        "".join(f"line {i}\n" for i in range(40)) + "## STATUS: STOP (g)\n",   # line 41
        "# hb\n",
    ], ids=["result-label", "line-41", "hb"])
    def test_P3_none(self, tmp_path, body):
        p = tmp_path / "x.handback.md"
        p.write_text(body)
        assert orchestrator.handback_status(p) is None

    def test_P3_line_40_is_read(self, tmp_path):
        p = tmp_path / "x.handback.md"
        p.write_text("".join(f"line {i}\n" for i in range(39)) + "## STATUS: STOP (g)\n")
        assert orchestrator.handback_status(p).label == "STOP (g)"

    def test_P3_the_first_status_line_decides(self, tmp_path):
        p = tmp_path / "x.handback.md"
        p.write_text("## STATUS: DONE\n\n## Status: STOPPED under STOP (e)\n")
        assert orchestrator.handback_status(p).label == "DONE"

    def test_P3_no_file_and_unreadable(self, tmp_path):
        assert orchestrator.handback_status(tmp_path / "absent.handback.md") is None
        bad = tmp_path / "bad.handback.md"
        bad.write_bytes(b"\xff\xfe\x00## STATUS: STOP (g)\n\xc3\x28")
        assert orchestrator.handback_status(bad) is None
        d = tmp_path / "dir.handback.md"
        d.mkdir()
        assert orchestrator.handback_status(d) is None

    def test_P3_the_reader_is_not_a_control_by_name(self):
        """P-SAY source guard (test_control_verdict_lines): not `_*_hold`, no `guard` word, and 🛑, never 🛡."""
        src = (ROOT / "orchestrator.py").read_text()
        for fn in ("handback_status", "_read_handback_status", "_classify_handback_status", "route_handback_path",
                   "_log_handback_status"):
            assert f"def {fn}(" in src
            assert not fn.endswith("_hold") and "guard" not in fn
        assert "🛡 handback-status" not in src and "🛑 handback-status:" in src


# ═══════════════════════════════════════════════════════
# P-3b · the path: a queue-order zero, the re-gate lane
# ═══════════════════════════════════════════════════════
class TestP3bPath:

    def test_P3b_a_zero_prefixed_stem_reads_the_zero_less_handback(self, lane, caplog):
        b = lane.brief("0686-x")
        lane.toni({"briefs/686-x.handback.md": "## STATUS: STOP (b)\n"})
        with caplog.at_level(logging.INFO, logger="orch"):
            r = lane.inner(b)
        assert r.status is _stopped(), r.status
        final = _final(caplog)
        assert final.startswith("🏁 FINAL STATUS: stopped | gate: PASS") and final.endswith(" | handback: STOP (b)")
        assert f"🛑 handback-status: STOP (b) ({lane.repo / 'briefs' / '686-x.handback.md'})" in _msgs(caplog)

    def test_P3b_the_exact_name_is_read_first(self, lane, caplog):
        b = lane.brief("0653-x")
        lane.toni({"briefs/0653-x.handback.md": "## STATUS: DONE\n", "briefs/653-x.handback.md": STOP_G})
        with caplog.at_level(logging.INFO, logger="orch"):
            r = lane.inner(b)
        assert r.status is orchestrator.Status.PASSED
        assert "| handback:" not in _final(caplog)
        assert f"🛑 handback-status: DONE ({lane.repo / 'briefs' / '0653-x.handback.md'})" in _msgs(caplog)

    def test_P3b_a_re_gate_reads_the_re_gated_routes_handback(self, lane, caplog):
        route = "orch-584a-x"
        _git(lane.repo, "checkout", "-q", "-b", route, "main")
        (lane.repo / "src" / "a.ts").write_text("export const a = 584;\n")
        (lane.repo / "briefs" / "584a-x.handback.md").write_text("## STATUS: STOP (g)\n\nPart A built.\n")
        _git(lane.repo, "add", "-A")
        _git(lane.repo, "commit", "-qm", "fix: 584a-x")
        tip = _git(lane.repo, "rev-parse", "HEAD")
        _git(lane.repo, "checkout", "-q", "main")
        _git(lane.repo, "notes", "add", "-f", "-m", "PRE-MERGE GATE: BLOCKED(environment) — sit: rate-limited", tip)
        b = lane.queue / "0584ar-x-regate.md"
        b.write_text(f"#!queue repo={REPO}\n\n# 584a re-gate\n## Kanban: SCP_Kanban row 584\n"
                     f"## Re-gate of: {route} {tip[:8]}\n")
        with caplog.at_level(logging.INFO, logger="orch"):
            r = orchestrator.run_batch(b)
        assert lane.fired == [], "a re-gate fires no executor"
        assert r.status is _stopped(), (r.status, r.error)
        assert _git(lane.repo, "merge-base", "--is-ancestor", tip, "main") == "", "merged as passed would"
        assert _final(caplog).endswith(" | handback: STOP (g)")
        assert f"🛑 handback-status: STOP (g) ({lane.repo / 'briefs' / '584a-x.handback.md'})" in _msgs(caplog)


# ═══════════════════════════════════════════════════════
# P-4 / P-4b · exit codes and state.json
# ═══════════════════════════════════════════════════════
def _main(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["orchestrator.py", *argv])
    try:
        orchestrator.main()
    except SystemExit as e:
        return e.code
    return 0


@pytest.fixture
def cli(lane, monkeypatch):
    monkeypatch.setattr(orchestrator, "set_active_repo", lambda n: n)
    monkeypatch.setattr(orchestrator, "_check_stale_marker", lambda *a, **k: False)
    monkeypatch.setattr(orchestrator, "approval_gate", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator, "rate_check", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator.time, "sleep", lambda s: None)
    return lane


def _state(lane) -> dict:
    return json.loads((lane.tmp / "state.json").read_text())


class TestP4Exit:

    def test_P4_run_exits_5_and_files_it_under_stopped(self, cli, monkeypatch):
        b = cli.brief()
        cli.toni({f"briefs/{STEM}.handback.md": STOP_G})
        assert _main(monkeypatch, "run", str(b), "--repo", REPO, "--approve") == 5
        s = _state(cli)
        assert [e["batch_file"] for e in s.get("stopped", [])] == [b.name]
        assert s["completed"] == [] and s["failed"] == []
        assert s["stopped"][0]["status"] == "stopped"

    def test_P4_EXIT_STOPPED_is_5_and_both_modules_agree(self):
        assert getattr(orchestrator, "EXIT_STOPPED", None) == 5
        assert getattr(queue_daemon, "EXIT_STOPPED", None) == orchestrator.EXIT_STOPPED

    def test_P4b_queue_exits_5_and_files_it_under_stopped(self, cli, monkeypatch):
        b = cli.brief()
        cli.toni({f"briefs/{STEM}.handback.md": STOP_G})
        assert _main(monkeypatch, "queue", str(b), "--repo", REPO, "--approve", "--skip-deps") == 5
        s = _state(cli)
        assert [e["batch_file"] for e in s.get("stopped", [])] == [b.name] and s["failed"] == []

    def test_P4b_run_queue_halts_on_a_stopped_route(self, cli, monkeypatch, caplog):
        b1, b2 = cli.brief("685-x"), cli.brief("686-y")
        cli.toni({f"briefs/{STEM}.handback.md": STOP_G})
        with caplog.at_level(logging.INFO, logger="orch"):
            rs = orchestrator.run_queue([b1, b2], skip_deps=True)
        assert cli.fired == ["685-x.md"], "the second brief is not fired"
        assert [r.status for r in rs] == [_stopped()]
        assert "⛔ Queue HALTED (stopped) — 1 batches skipped" in _msgs(caplog)
        done = [m for m in _msgs(caplog) if "QUEUE DONE" in m]
        assert len(done) == 1 and "QUEUE DONE: 0/1 passed, 1 stopped | 1 briefs" in done[0], done

    def test_P4b_watch_records_a_stopped_route_under_stopped(self, cli, monkeypatch):
        watched = cli.tmp / "watched"
        watched.mkdir()
        b = watched / f"{STEM}.md"
        b.write_text(f"#!queue repo={REPO}\n\n# {STEM}\n- id: B1\n  title: demo\n")
        monkeypatch.setattr(orchestrator, "BRIEFS_DIR", watched)
        cli.toni({f"briefs/{STEM}.handback.md": STOP_G})

        def _stop(s):
            raise KeyboardInterrupt
        monkeypatch.setattr(orchestrator.time, "sleep", _stop)
        orchestrator.watch()
        s = _state(cli)
        assert [e["batch_file"] for e in s.get("stopped", [])] == [b.name]
        assert s["failed"] == [] and s["completed"] == []

    def test_load_states_default_has_a_stopped_list(self, lane):
        assert orchestrator.load_state()["stopped"] == []


# ═══════════════════════════════════════════════════════
# P-5 · the queue daemon
# ═══════════════════════════════════════════════════════
class TestP5Daemon:

    def _daemon(self, tmp_path, monkeypatch, exit_code):
        n = Night(tmp_path, monkeypatch, schedule={})
        n.cfg.write_text(yaml.safe_dump({"repos": {"cmp": {"project_dir": str(tmp_path)}}}))
        n.queue.mkdir(parents=True, exist_ok=True)
        (n.queue / f"{STEM}.md").write_text("#!queue repo=cmp\n\n# 685\n")
        d = queue_daemon.QueueDaemon()
        d.start_running = True
        d.config.update(cooldown_seconds=0, stop_on_failure=True)
        d.consecutive_count = 2

        def _route(cmd, batch_name, log_path):
            Path(log_path).write_text("12:00:02 [INFO   ] 🏁 FINAL STATUS: stopped | gate: PASS | handback: STOP (g)\n")
            return exit_code
        d._run_route = _route
        monkeypatch.setattr(queue_daemon, "time",
                            types.SimpleNamespace(sleep=lambda s: setattr(d, "status", "stopped")))
        return n, d

    def test_P5_exit_5_is_stopped_not_completed_or_failed_and_no_pause(self, tmp_path, monkeypatch, capsys):
        n, d = self._daemon(tmp_path, monkeypatch, 5)
        d.run_loop()
        out = capsys.readouterr().out
        assert [e["file"] for e in getattr(d, "stopped", [])] == [f"{STEM}.md"]
        assert d.completed == [] and d.failed == []
        assert d.stopped[0]["status"] == "stopped" and d.stopped[0]["exit_code"] == 5
        assert (f"[QUEUE] STOPPED: {STEM}.md (handback STATUS STOP/PARTIAL — read it before closing the Kanban row, "
                f"rule #15; ") in out, out
        assert "stop_on_failure=true. Pausing queue." not in out and d.paused_reason is None
        assert d.consecutive_count == 3
        assert (n.queue / "done" / f"{STEM}.md").exists(), "the tray as for exit 0"
        on_disk = json.loads(n.state_file.read_text())
        assert [e["file"] for e in on_disk["stopped"]] == [f"{STEM}.md"]
        st = d.get_status()
        assert st["stopped_total"] == 1 and [e["file"] for e in st["stopped"]] == [f"{STEM}.md"]
        assert d.find_missing_gate_logs() == []
        Path(d.stopped[0]["log_file"]).unlink()
        assert [v.reason for v in d.find_missing_gate_logs()] == ["log-missing"], "find_missing_gate_logs judges it"

    def test_P5_a_restart_loads_the_stopped_list(self, tmp_path, monkeypatch):
        n, d = self._daemon(tmp_path, monkeypatch, 5)
        d.run_loop()
        assert [e["file"] for e in queue_daemon.QueueDaemon().stopped] == [f"{STEM}.md"]

    @pytest.mark.parametrize("code,where", [(0, "completed"), (1, "failed")])
    def test_P5_control_exit_0_and_1_unchanged(self, tmp_path, monkeypatch, capsys, code, where):
        n, d = self._daemon(tmp_path, monkeypatch, code)
        d.run_loop()
        assert [e["file"] for e in getattr(d, where)] == [f"{STEM}.md"] and getattr(d, "stopped", []) == []
        assert "status" not in getattr(d, where)[0]
        out = capsys.readouterr().out
        assert ("[QUEUE] PASSED:" in out) is (code == 0)
        assert ("stop_on_failure=true. Pausing queue." in out) is (code == 1)


# ═══════════════════════════════════════════════════════
# P-6 · the meta-fire (self-mod) lane
# ═══════════════════════════════════════════════════════
def test_P6_the_meta_fire_lane_still_ff_merges_and_reports_stopped(lane, monkeypatch, caplog):
    monkeypatch.setattr(orchestrator, "IS_META_FIRE", True)
    monkeypatch.setattr(orchestrator, "ORCH_DIR", lane.repo)          # is_self_mod: this repo is the orchestrator
    b = lane.brief()
    seen = {}

    def _record(proj):
        seen["wt"] = proj
    lane.toni({f"briefs/{STEM}.handback.md": STOP_G}, commit=True, also=_record)
    try:
        with caplog.at_level(logging.INFO, logger="orch"):
            r = orchestrator.run_batch(b)
        assert seen["wt"] != lane.repo, "ran in the meta-fire worktree"
        assert r.status is _stopped(), (r.status, r.error)
        assert _final(caplog).endswith(" | handback: STOP (g)")
        assert lane.on_main(f"briefs/{STEM}.handback.md"), "--ff-only merged, as passed does today"
        assert _git(lane.repo, "rev-parse", "main") == _git(lane.repo, "rev-parse", f"orch-{STEM}")
        assert "✅ Self-mod auto-merge: brought 1 commits to main" in _msgs(caplog)
        assert not seen["wt"].exists(), "the meta-fire worktree is cleaned up after the merge"
    finally:
        if "wt" in seen and Path(seen["wt"]).exists():
            _git(lane.repo, "worktree", "remove", "--force", str(seen["wt"]))


# ═══════════════════════════════════════════════════════
# P-7 · a `worktree_mode: parallel` route worktree
# ═══════════════════════════════════════════════════════
def test_P7_a_route_worktree_is_merged_removed_and_stopped(tmp_path, monkeypatch, caplog):
    from tests.test_control_scope import TONI_LOG, WorktreeRoute
    from tests.test_control_scope import _git as sh_git
    wtr = WorktreeRoute(tmp_path, monkeypatch)

    def _toni(target, proj):
        proj = Path(proj)
        wtr.seen["proj"] = proj
        (proj / "yorsie" / "feature.ts").write_text("export const n: number = 1;\n")
        (proj / "yorsie" / "briefs" / "batch-wt.handback.md").write_text(STOP_G)
        sh_git('git add -A && git commit -qm "feat: work"', proj)
        wtr.route_tip = sh_git("git rev-parse HEAD", proj).stdout.strip()
        log = tmp_path / "toni-test.log"
        log.write_text(TONI_LOG)
        return 0, str(log)
    monkeypatch.setattr(orchestrator, "fire_toni", _toni)
    with caplog.at_level(logging.INFO, logger="orch"):
        r = orchestrator.run_batch(wtr.brief)
    assert wtr.seen["proj"] == wtr.wt
    assert r.status is _stopped() and r.gate_outcome == "PASS", (r.status, r.error)
    assert sh_git(f"git merge-base --is-ancestor {wtr.route_tip} main", wtr.proj).returncode == 0, "merged"
    assert not wtr.wt.exists() and wtr.worktrees() == [str(wtr.proj)], "worktree removed, as for passed"
    assert _final(caplog).endswith(" | handback: STOP (g)")


# ═══════════════════════════════════════════════════════
# P-7b · run_parallel
# ═══════════════════════════════════════════════════════
def test_P7b_run_parallel_gates_and_merges_a_stopped_worker(tmp_path, monkeypatch, caplog):
    from tests.test_control_scope import REPO_GLOBALS
    for g in REPO_GLOBALS:
        monkeypatch.setattr(orchestrator, g, getattr(orchestrator, g))
    proj = _repo(tmp_path / "repo")
    cfg = tmp_path / "repos.yaml"
    cfg.write_text(yaml.safe_dump({"repos": {"par": {
        "project_dir": str(proj), "branch_prefix": "orch-par", "merge_target": "main", "briefs_subdir": "briefs",
        "worktree_mode": "parallel", "worktree_base": str(tmp_path / "wts")}}}))
    monkeypatch.setattr(orchestrator, "REPOS_CONFIG_PATH", cfg)
    orchestrator.set_active_repo("par")
    for name, val in (("RUN_PLAYWRIGHT", False), ("PREFIRE_BYPASS", True), ("SIT_ARCHIVE_DIR", tmp_path / "archive")):
        monkeypatch.setattr(orchestrator, name, val)
    monkeypatch.setattr(orchestrator, "get_migrations", lambda: set())
    monkeypatch.setattr(orchestrator, "notify", lambda r: None)
    monkeypatch.setattr(orchestrator, "find_unblocked", lambda *a, **k: [])
    monkeypatch.setattr(orchestrator.rate_limiter, "record", lambda *a, **k: None)
    for fn in ("write_running", "clear_running", "_write_running_marker", "_clear_running_marker"):
        monkeypatch.setattr(orchestrator, fn, lambda *a, **k: None)
    monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
    legs = Legs(monkeypatch)
    brief = tmp_path / "queue" / "a-stop.md"
    brief.parent.mkdir()
    brief.write_text("- id: B1\n  title: t\n")

    def _toni(target, wt):
        (Path(wt) / "briefs" / "a-stop.handback.md").write_text(STOP_G)
        return 0, _toni_log(tmp_path / "logs" / "toni-a-stop-20261115-000000.log")
    monkeypatch.setattr(orchestrator, "fire_toni", _toni)
    results = []
    real = orchestrator.run_batch
    monkeypatch.setattr(orchestrator, "run_batch", lambda bf, wt=None: results.append(real(bf, wt)) or results[-1])
    with caplog.at_level(logging.INFO, logger="orch"):
        orchestrator.run_parallel([brief], force=True)
    assert [r.status for r in results] == [_stopped()]
    assert legs.calls == [], "briefs-only, gated as today"
    assert _git(proj, "ls-tree", "--name-only", "main", "briefs/a-stop.handback.md") == "briefs/a-stop.handback.md", \
        "merged as today"
    assert "Merged orch-par-a-stop-w1" in _msgs(caplog)
    done = [m for m in _msgs(caplog) if "PARALLEL DONE" in m]
    assert done == ["\nPARALLEL DONE: 0/1 passed, 1 stopped"], done


# ═══════════════════════════════════════════════════════
# P-8 · verify
# ═══════════════════════════════════════════════════════
def test_P8_verify_returns_1_for_a_stopped_route_and_says_why(tmp_path, monkeypatch, capsys):
    repo = _repo(tmp_path / "repo")
    sha = _commit(repo, "x", write={f"briefs/{STEM}.md": "## Repo: cost-repo\n",
                                    f"briefs/{STEM}.handback.md": STOP_G})
    repos = {REPO: {"project_dir": str(repo), "log_subdir": "cost", "briefs_subdir": "briefs",
                    "branch_prefix": "orch", "merge_target": "main"}}
    monkeypatch.setattr(orchestrator, "load_repo_config", lambda: {"repos": repos})
    logs = tmp_path / "logs"
    monkeypatch.setattr(orchestrator, "LOG_DIR", logs)
    monkeypatch.setattr(orchestrator, "QUEUE_DIR", tmp_path / "queue")
    monkeypatch.setattr(orchestrator, "QUEUE_DONE", tmp_path / "queue" / "done")
    (tmp_path / "queue" / "done").mkdir(parents=True)
    (tmp_path / "queue" / "done" / f"{STEM}.md").write_text(f"#!queue repo={REPO}\n")
    (logs / "cost").mkdir(parents=True)
    gate = _briefs_only(f"briefs/{STEM}.handback.md", f"briefs/{STEM}.md")
    (logs / "cost" / f"orch-{STEM}-20261115-120000.log").write_text(
        f"12:00:01 [INFO   ] ✅ Pre-merge gate on orch-{STEM}: {gate}\n"
        f"12:00:01 [INFO   ] 🔀 Merged orch-{STEM} → main (aaaaaaa → {sha[:7]})\n"
        f"12:00:02 [INFO   ] 🏁 FINAL STATUS: stopped | gate: {gate} | handback: STOP (g)\n")
    _toni_log(logs / "cost" / f"toni-{STEM}-20261115-120000.log")
    rc = orchestrator.verify_route(STEM)
    out = capsys.readouterr().out
    assert rc == 1, out
    assert ("FINAL STATUS is stopped — the handback's status line says STOP / PARTIAL; read it before closing the "
            "Kanban row (rule #15)") in out


# ═══════════════════════════════════════════════════════
# P-9 · controls — green before and after
# ═══════════════════════════════════════════════════════
class TestP9Controls:

    @pytest.mark.parametrize("handback", ["## STATUS: DONE\n", "# hb\n", None], ids=["done", "hb", "none"])
    def test_P9_a_done_handback_is_todays_passed_line_byte_for_byte(self, lane, caplog, handback):
        b = lane.brief()
        lane.toni({f"briefs/{STEM}.handback.md": handback} if handback else {})
        with caplog.at_level(logging.INFO, logger="orch"):
            r = lane.inner(b)
        paths = ([f"briefs/{STEM}.handback.md"] if handback else []) + [f"briefs/{STEM}.md"]
        assert _final(caplog) == f"🏁 FINAL STATUS: passed | gate: {_briefs_only(*paths)}"
        assert r.status is orchestrator.Status.PASSED and r.error is None
        assert lane.on_main(f"briefs/{STEM}.md")

    def test_P9_a_red_route_with_a_stop_handback_stays_failed(self, lane, caplog):
        b = lane.brief()
        lane.legs.out["build"] = (2, "src/a.ts(1,14): error TS2322: Type 'string' is not assignable to type 'number'.\n")
        lane.toni({f"briefs/{STEM}.handback.md": STOP_G, "src/a.ts": "export const a: number = 'x';\n"})
        main_before = _git(lane.repo, "rev-parse", "main")
        with caplog.at_level(logging.INFO, logger="orch"):
            r = lane.inner(b)
        assert r.status is orchestrator.Status.FAILED and r.gate_outcome == "FAIL(product)", (r.status, r.error)
        assert _final(caplog).startswith("🏁 FINAL STATUS: failed | gate: FAIL(product)")
        assert "| handback:" not in _final(caplog) and "handback STATUS" not in (r.error or "")
        assert _git(lane.repo, "rev-parse", "main") == main_before

    def test_P9_an_incomplete_route_with_a_stop_handback_stays_incomplete(self, lane, caplog):
        b = lane.brief()
        lane.toni({f"briefs/{STEM}.handback.md": STOP_G}, log_fixture=R54)
        with caplog.at_level(logging.INFO, logger="orch"):
            r = lane.inner(b)
        assert r.status is orchestrator.Status.INCOMPLETE
        assert _final(caplog).startswith("🏁 FINAL STATUS: incomplete | gate: not run (INCOMPLETE(executor)")
        assert "| handback:" not in _final(caplog)

    def test_P9_a_tampered_route_with_a_stop_handback_stays_tampered(self, lane, caplog):
        b = lane.brief()
        lane.toni({f"briefs/{STEM}.handback.md": STOP_G}, also=lambda proj: _git(proj, "checkout", "-q", "main"))
        with caplog.at_level(logging.INFO, logger="orch"):
            r = lane.inner(b)
        assert r.status is orchestrator.Status.TAMPERED
        assert "| handback:" not in _final(caplog)

    def test_P9_a_blocked_route_with_a_stop_handback_stays_blocked(self, lane, monkeypatch, caplog):
        b = lane.brief()
        monkeypatch.setattr(orchestrator, "run_pre_merge_gates", lambda repo_path, branch_name=None: (
            orchestrator.GateVerdict(orchestrator.GateOutcome.BLOCKED_ENV, "sit", "rate-limited", "429")))
        lane.toni({f"briefs/{STEM}.handback.md": STOP_G})
        with caplog.at_level(logging.INFO, logger="orch"):
            r = lane.inner(b)
        assert r.status is orchestrator.Status.BLOCKED
        assert _final(caplog).startswith("🏁 FINAL STATUS: blocked | gate: BLOCKED(environment)")
        assert "| handback:" not in _final(caplog)

    def test_P9_the_685_depends_on_case_is_untouched(self):
        """tests/test_depends_product.py is in this route's gate list, unedited (canon_assert / prefire unchanged)."""
        assert "_land(w.repo, \"orch-t-600b-stopped\"" in (ROOT / "tests" / "test_depends_product.py").read_text()


# ═══════════════════════════════════════════════════════
# the live corpus (read-only `git show`; skipped where the checkout is absent)
# ═══════════════════════════════════════════════════════
CMP = Path.home() / "spectricom-clinical-mp"


@pytest.mark.skipif(not (CMP / ".git").exists(), reason="no clinical-mp checkout on this machine")
def test_the_685_handback_on_clinical_mp_main_reads_stop_g(tmp_path):
    import subprocess
    r = subprocess.run(["git", "-C", str(CMP), "show", "main:briefs/685-hardstop-unassessed-blocks-1.handback.md"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("685's handback is not on clinical-mp main here")
    p = tmp_path / "685.handback.md"
    p.write_text(r.stdout)
    assert orchestrator.handback_status(p).label == "STOP (g)"

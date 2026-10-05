# filename: tests/test_queue_pause.py
"""Tests for QUEUE-PAUSE-OPAQUE — a paused queue says so, and one command resumes it.

S7-CORE-16 · Bug Registry v1-58 [QUEUE-PAUSE-OPAQUE] P2. The daemon paused itself (stop_on_failure,
max_consecutive) and said so nowhere a human reads. queue-state.json carried `daemon_status` and
nothing else. `python3 queue_daemon.py status` printed a FRESH object's "idle". Its only resume was
an in-process method the CLI cannot reach, so a paused queue meant a restart.

  AC-QP-01  every pause transition persists daemon_status / paused_reason / paused_at, and
            `status` prints them on its first line                                (red first)
  AC-QP-02  `resume` round-trip through the control file against a daemon run in a thread
            (_run_route stubbed): running within one poll, the ack written back
  AC-QP-03  a running marker whose PID is dead is archived, not waited on        (red first)

Every path is under tmp_path. No test signals, pauses or reads the live daemon.
"""

import json
import os
import subprocess
import sys
import threading
import time as real_time
import types
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import queue_daemon

ISO = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"


def _dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


class Daemon:
    """One QueueDaemon wired under tmp_path; `_run_route` stubbed — no subprocess ever fires."""

    def __init__(self, tmp_path: Path, monkeypatch, exit_codes=(1,)):
        self.orch = tmp_path / "orch"
        self.queue = self.orch / "queue"
        self.state_file = tmp_path / "queue-state.json"
        not_git = tmp_path / "not-a-repo"
        not_git.mkdir()
        cfg = tmp_path / "repos.yaml"
        cfg.write_text(yaml.safe_dump({"repos": {"r": {"project_dir": str(not_git)}}}))
        (self.orch / "state").mkdir(parents=True)
        for name, val in (("ORCH_DIR", self.orch), ("QUEUE_DIR", self.queue),
                          ("QUEUE_DONE", self.queue / "done"), ("QUEUE_FAILED", self.queue / "failed"),
                          ("QUEUE_STATE", self.state_file), ("REPOS_CONFIG", cfg),
                          ("LOG_DIR", tmp_path / "logs")):
            monkeypatch.setattr(queue_daemon, name, val)
        self.d = queue_daemon.QueueDaemon()
        self.d.start_running = True  # ORCH-CONTROL-SCOPE-1 C2: these tests fire at start, as --start-running does
        self.d.config.update(repo="r", cooldown_seconds=0, model="m", effort="e")
        self.fired = []
        self.codes = list(exit_codes)

        def _route(cmd, batch_name, log_path):
            self.fired.append(batch_name)
            Path(log_path).write_text("route output\n")
            return self.codes.pop(0) if self.codes else 0
        self.d._run_route = _route
        self.sleeps = []
        self.threads = []

    def stop_threads(self):
        """Stop every run_loop thread and prove it ended. Runs in the fixture's teardown, BEFORE
        monkeypatch puts the live paths back: a thread that outlived its test would otherwise
        read and write ~/spectricom-orchestrator. Re-asserts `stopped` because run_loop sets
        `running` once at start and could overwrite an early stop."""
        for t in self.threads:
            for _ in range(400):
                self.d.status = "stopped"
                t.join(0.025)
                if not t.is_alive():
                    break
            assert not t.is_alive(), "a daemon thread outlived its test"

    def stop_on_first_sleep(self, monkeypatch):
        def _sleep(s):
            self.sleeps.append((self.d.status, s))
            self.d.status = "stopped"
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep))

    def brief(self, stem: str) -> Path:
        self.queue.mkdir(parents=True, exist_ok=True)
        p = self.queue / f"{stem}.md"
        p.write_text(f"#!queue repo=r\n\n# {stem}\n")
        return p

    def state(self) -> dict:
        return json.loads(self.state_file.read_text()) if self.state_file.exists() else {}


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    d = Daemon(tmp_path, monkeypatch)
    yield d
    d.stop_threads()


# ═══════════════════════════════════════════════════════
# AC-QP-01 · a pause is persisted, with its reason and time
# ═══════════════════════════════════════════════════════
class TestPausePersisted:

    def test_R1_stop_on_failure_persists_reason_and_time(self, daemon, monkeypatch):
        daemon.brief("59-ui-identifier-truth-1")
        daemon.stop_on_first_sleep(monkeypatch)
        daemon.d.run_loop()
        st = daemon.state()
        assert st["daemon_status"] == "paused"
        assert st.get("paused_reason") == "stop-on-failure:59-ui-identifier-truth-1.md"
        assert __import__("re").fullmatch(ISO + r".*", st.get("paused_at") or ""), st.get("paused_at")

    def test_R2_max_consecutive_persists_reason(self, daemon, monkeypatch):
        daemon.d.config["max_consecutive"] = 3
        daemon.d.consecutive_count = 3
        daemon.brief("62-next")
        daemon.stop_on_first_sleep(monkeypatch)
        daemon.d.run_loop()
        st = daemon.state()
        assert (st["daemon_status"], st.get("paused_reason")) == ("paused", "max-consecutive:3")
        assert st.get("paused_at")
        assert daemon.fired == []

    def test_operator_pause_persists_operator(self, daemon):
        daemon.d.is_daemon = True        # the dashboard's in-process daemon: its run_loop runs in a thread
        daemon.d.status = "running"
        daemon.d.pause()
        st = daemon.state()
        assert (st["daemon_status"], st["paused_reason"]) == ("paused", "operator")
        daemon.d.resume()
        st = daemon.state()
        assert (st["daemon_status"], st["paused_reason"], st["paused_at"]) == ("running", None, None)

    def test_status_prints_them_on_its_first_line(self, daemon, monkeypatch, capsys):
        daemon.brief("59-ui-identifier-truth-1")
        daemon.stop_on_first_sleep(monkeypatch)
        daemon.d.run_loop()
        st = daemon.state()
        capsys.readouterr()
        rc = queue_daemon.main(["status"])
        first = capsys.readouterr().out.splitlines()[0]
        assert rc == 0
        assert first.startswith("daemon_status=paused paused_reason=stop-on-failure:59-ui-identifier-truth-1.md "
                                f"paused_at={st['paused_at']}"), first

    def test_status_does_not_report_a_fresh_objects_idle(self, daemon, monkeypatch, capsys):
        daemon.brief("59-ui-identifier-truth-1")
        daemon.stop_on_first_sleep(monkeypatch)
        daemon.d.run_loop()
        capsys.readouterr()
        queue_daemon.main(["status"])
        body = json.loads("\n".join(capsys.readouterr().out.splitlines()[1:]))
        assert body["daemon_status"] == "paused" and body["paused_reason"].startswith("stop-on-failure:")

    def test_a_cli_save_never_clobbers_the_daemons_status(self, daemon, monkeypatch, tmp_path):
        daemon.brief("59-ui-identifier-truth-1")
        daemon.stop_on_first_sleep(monkeypatch)
        daemon.d.run_loop()
        before = daemon.state()
        other = tmp_path / "extra.md"
        other.write_text("# extra\n")
        cli = queue_daemon.QueueDaemon()          # what `python3 queue_daemon.py enqueue` builds
        assert cli.enqueue(str(other))["ok"]
        after = daemon.state()
        for k in ("daemon_status", "paused_reason", "paused_at", "pid", "started_at"):
            assert after.get(k) == before.get(k), k
        assert "extra.md" in after["queue"]


# ═══════════════════════════════════════════════════════
# AC-QP-02 · resume, through the control file, against a live daemon thread
# ═══════════════════════════════════════════════════════
class TestResume:

    def _live(self, daemon, monkeypatch):
        """run_loop in a thread; every sleep is 5 ms of real time, recorded with the status and
        whether a control request was already on disk when the sleep began."""
        ctl = daemon.orch / "state" / "queue-control.json"

        def _sleep(s):
            daemon.sleeps.append((daemon.d.status, s, ctl.exists()))
            real_time.sleep(0.005)
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep))
        t = threading.Thread(target=daemon.d.run_loop, daemon=True)
        daemon.threads.append(t)
        t.start()
        assert self._until(lambda: daemon.d.is_daemon and daemon.state().get("pid")), "run_loop never started"
        return t

    def _until(self, pred, timeout=5.0):
        end = real_time.monotonic() + timeout
        while real_time.monotonic() < end:
            if pred():
                return True
            real_time.sleep(0.005)
        return False

    def test_round_trip(self, daemon, monkeypatch):
        daemon.brief("59-ui-identifier-truth-1")
        t = self._live(daemon, monkeypatch)
        try:
            # paused as the CLI sees it: request_control reads queue-state.json, which the daemon saves
            # after it flips its own status (ORCH-LANE-1: the pause notice is written in between)
            assert self._until(lambda: daemon.d.status == "paused" and daemon.state().get("daemon_status") == "paused"), \
                "stop_on_failure never paused"
            rc, msg = queue_daemon.request_control("resume", wait_s=5.0, poll_s=0.005)
            assert rc == 0, msg
            assert daemon.d.status == "running"
            polls = [s for s in daemon.sleeps if s[0] == "paused" and s[2]]
            assert len(polls) <= 1, f"resumed after {len(polls)} paused polls, not within one"
            st = daemon.state()
            req = json.loads(queue_daemon.control_file().read_text())
            assert st["control_ack"] == req["id"] and req["action"] == "resume"
            assert (st["daemon_status"], st["paused_reason"]) == ("running", None)
            assert f"acknowledged request {req['id']}" in msg
        finally:
            daemon.stop_threads()

    def test_reset_consecutive_is_reachable(self, daemon, monkeypatch):
        daemon.d.config["max_consecutive"] = 2
        daemon.d.consecutive_count = 2
        t = self._live(daemon, monkeypatch)
        try:
            assert self._until(lambda: daemon.state().get("paused_reason") == "max-consecutive:2")
            rc, msg = queue_daemon.request_control("resume", wait_s=5.0, poll_s=0.005)
            assert rc == 1 or "max-consecutive" in msg, msg     # a bare resume cannot beat the cap
            rc, msg = queue_daemon.request_control("resume", reset_consecutive=True, wait_s=5.0, poll_s=0.005)
            assert rc == 0, msg
            assert daemon.d.consecutive_count == 0 and daemon.d.status == "running"
        finally:
            daemon.stop_threads()

    def test_pause_through_the_control_file(self, daemon, monkeypatch):
        t = self._live(daemon, monkeypatch)
        try:
            assert self._until(lambda: daemon.d.status == "running")
            rc, msg = queue_daemon.request_control("pause", wait_s=5.0, poll_s=0.005)
            assert rc == 0, msg
            st = daemon.state()
            assert (st["daemon_status"], st["paused_reason"]) == ("paused", "operator")
        finally:
            daemon.stop_threads()

    def test_not_paused_is_a_clear_noop(self, daemon, monkeypatch):
        t = self._live(daemon, monkeypatch)
        try:
            assert self._until(lambda: daemon.d.status == "running")
            rc, msg = queue_daemon.request_control("resume", wait_s=1.0, poll_s=0.005)
            assert rc == 0 and "not paused" in msg and "nothing to resume" in msg
            assert not queue_daemon.control_file().exists(), "a no-op writes no request"
        finally:
            daemon.stop_threads()

    def test_not_running_is_refused(self, daemon):
        daemon.state_file.write_text(json.dumps({"daemon_status": "paused", "pid": _dead_pid(),
                                                 "paused_reason": "operator"}))
        rc, msg = queue_daemon.request_control("resume", wait_s=0.1, poll_s=0.01)
        assert rc == 2 and "not running" in msg
        assert not queue_daemon.control_file().exists()

    def test_a_daemon_that_predates_this_is_named(self, daemon):
        daemon.state_file.write_text(json.dumps({"daemon_status": "paused"}))   # no pid: old code
        rc, msg = queue_daemon.request_control("resume", wait_s=0.1, poll_s=0.01)
        assert rc == 2 and "pid not recorded" in msg

    def test_a_request_left_before_start_is_not_replayed(self, daemon, monkeypatch):
        queue_daemon.control_file().write_text(json.dumps({"id": 7, "action": "pause"}))
        t = self._live(daemon, monkeypatch)
        try:
            assert self._until(lambda: len(daemon.sleeps) >= 3)
            assert daemon.d.status == "running"
            assert daemon.state()["control_ack"] == 7
        finally:
            daemon.stop_threads()


# ═══════════════════════════════════════════════════════
# AC-QP-03 · a dead marker does not block a fire
# ═══════════════════════════════════════════════════════
class TestStaleMarker:

    def test_R3_dead_pid_markers_are_archived_and_the_brief_fires(self, daemon, monkeypatch, capsys):
        dead = _dead_pid()
        root = daemon.orch / "running.json"
        root.write_text(json.dumps({"batch_file": "59-x.md", "pid": dead}))
        lock = daemon.orch / "state" / "running-clinical-mp.json"
        lock.write_text(json.dumps({"pid": dead, "batch_id": "59-x", "repo": "clinical-mp"}))
        daemon.codes = [0]
        daemon.brief("62-next")
        daemon.stop_on_first_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.fired == ["62-next.md"], "a dead marker must not hold the queue"
        assert not root.exists() and not lock.exists()
        archived = sorted(p.name for p in daemon.orch.rglob("running*.killed-*"))
        assert len(archived) == 2 and archived[0].startswith("running-clinical-mp.json.killed-"), archived
        out = capsys.readouterr().out
        assert f"🛡 stale-running-marker: CLEARED {root} (pid {dead} dead)" in out
        assert f"🛡 stale-running-marker: CLEARED {lock} (pid {dead} dead)" in out

    def test_a_legacy_marker_without_pid_takes_its_locks_pid(self, daemon, monkeypatch, capsys):
        dead = _dead_pid()
        root = daemon.orch / "running.json"
        root.write_text(json.dumps({"batch_file": "59-x.md", "briefs": 1}))           # the pre-fix shape
        (daemon.orch / "state" / "running-clinical-mp.json").write_text(
            json.dumps({"pid": dead, "batch_id": "59-x", "repo": "clinical-mp"}))
        daemon.codes = [0]
        daemon.brief("62-next")
        daemon.stop_on_first_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.fired == ["62-next.md"] and not root.exists()
        assert f"🛡 stale-running-marker: CLEARED {root} (pid {dead} dead)" in capsys.readouterr().out

    def test_a_live_marker_is_waited_on(self, daemon, monkeypatch, capsys):
        root = daemon.orch / "running.json"
        root.write_text(json.dumps({"batch_file": "59-x.md", "pid": os.getpid()}))
        daemon.brief("62-next")
        daemon.stop_on_first_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.fired == [] and root.exists()
        assert "stale-running-marker" not in capsys.readouterr().out

    def test_a_marker_whose_pid_cannot_be_known_is_held_and_said_once(self, daemon, monkeypatch, capsys):
        root = daemon.orch / "running.json"
        root.write_text(json.dumps({"batch_file": "59-x.md", "briefs": 1}))   # no pid, no lock names it
        daemon.brief("62-next")
        seen = []

        def _sleep(s):
            seen.append(s)
            if len(seen) >= 3:
                daemon.d.status = "stopped"
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep))
        daemon.d.run_loop()
        assert daemon.fired == [] and root.exists()
        held = [l for l in capsys.readouterr().out.splitlines() if "🛡 stale-running-marker: HOLD" in l]
        assert len(held) == 1, held

    def test_killed_files_are_never_markers(self, daemon, monkeypatch):
        old = daemon.orch / "running.json.killed-014522"
        old.write_text(json.dumps({"batch_file": "59-x.md"}))
        daemon.codes = [0]
        daemon.brief("62-next")
        daemon.stop_on_first_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.fired == ["62-next.md"] and old.exists()


def test_a_request_during_a_route_says_when_it_lands(daemon):
    """The daemon does not poll while a route runs: a pause asked mid-route lands when it returns."""
    daemon.state_file.write_text(json.dumps({"daemon_status": "running", "pid": os.getpid(),
                                             "current_batch": {"file": "62-next.md"}}))
    rc, msg = queue_daemon.request_control("pause", wait_s=0.05, poll_s=0.01)
    assert rc == 1
    assert "a route is running (62-next.md); the daemon applies the request when it returns" in msg
    assert json.loads(queue_daemon.control_file().read_text())["action"] == "pause"

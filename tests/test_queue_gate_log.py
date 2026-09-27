# filename: tests/test_queue_gate_log.py
"""ORCH-STDOUT-1 — a gate log that survives.

S7-CORE-15 · D-S7CORE13-02 · Bug Registry v1-48.

The queue daemon spawned every route as `Popen(..., stdout=PIPE, stderr=STDOUT)` and then only
called `.wait()`. Nothing read the pipe: a child that wrote past the 64 KiB buffer blocked on
write() while the daemon blocked in wait(), until the 3h10m kill; every print, warning and
uncaught traceback was discarded; and the queue-state record named no log at all.

These tests drive the REAL run_loop / cancel_current against a stdlib-only fake orchestrator.py
that writes what each test asks for and exits with the test's code. They assert on the recorded
entry and on the file first, so they collect and go red on the pre-fix daemon; the predicate
(canon_assert.check_gate_log_invariants) is asserted after, as the invariant's oracle.

NO TEST HERE IMPORTS `orchestrator`: its import writes logs/orch-<ts>.log into the real logs/.
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import canon_assert
import queue_daemon

# The fake route. Reads its behaviour from fake-spec.json beside it; ignores argv. It NEVER
# flushes by hand: a line printed before a kill reaches the log only because the daemon runs the
# child with `python3 -u`.
FAKE_ORCHESTRATOR = '''\
import json, sys, time
from pathlib import Path
spec = json.loads((Path(__file__).parent / "fake-spec.json").read_text())
n = spec.get("stdout_bytes", 0)
if n:
    chunk = "x" * 1023 + "\\n"
    for _ in range(n // 1024):
        sys.stdout.write(chunk)
for line in spec.get("stdout", []):
    print(line)
for line in spec.get("stderr", []):
    print(line, file=sys.stderr)
if spec.get("sleep"):
    time.sleep(spec["sleep"])
sys.exit(spec.get("exit", 0))
'''

GL_REPO, GL_SUBDIR = "gl-repo", "gl-logs"     # log_subdir deliberately != repo name
PLAIN_REPO = "plain-repo"                      # no log_subdir: orchestrator.py's default rule
TS = r"\d{8}-\d{6}"


class Fire:
    """One daemon wired entirely under tmp_path, and the knobs a test turns."""

    def __init__(self, tmp_path: Path, monkeypatch):
        self.orch = tmp_path / "orch"
        self.orch.mkdir()
        (self.orch / "orchestrator.py").write_text(FAKE_ORCHESTRATOR)
        self.queue = self.orch / "queue"
        self.logs = tmp_path / "logs"
        not_git = tmp_path / "not-a-repo"   # B6 over a non-repo is [] (canon_assert._landed)
        not_git.mkdir()
        cfg = tmp_path / "config" / "repos.yaml"
        cfg.parent.mkdir()
        cfg.write_text(yaml.safe_dump({"repos": {
            GL_REPO: {"project_dir": str(not_git), "log_subdir": GL_SUBDIR},
            PLAIN_REPO: {"project_dir": str(not_git)},
        }}))
        monkeypatch.setattr(queue_daemon, "ORCH_DIR", self.orch)
        monkeypatch.setattr(queue_daemon, "QUEUE_DIR", self.queue)
        monkeypatch.setattr(queue_daemon, "QUEUE_DONE", self.queue / "done")
        monkeypatch.setattr(queue_daemon, "QUEUE_FAILED", self.queue / "failed")
        monkeypatch.setattr(queue_daemon, "QUEUE_STATE", tmp_path / "queue-state.json")
        monkeypatch.setattr(queue_daemon, "REPOS_CONFIG", cfg)
        monkeypatch.setattr(queue_daemon, "LOG_DIR", self.logs, raising=False)
        self.d = queue_daemon.QueueDaemon()
        self.d.config.update(repo=GL_REPO, cooldown_seconds=0, timeout_seconds=15,
                             model="m", effort="e")
        # The loop's first idle (queue empty) or paused (stop_on_failure) sleep ends it. Only
        # queue_daemon's `time` is replaced: subprocess's own wait loop sleeps for real.
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=self._stop))

    def _stop(self, _seconds):
        self.d.status = "stopped"

    def spec(self, **kw):
        (self.orch / "fake-spec.json").write_text(json.dumps(kw))

    def brief(self, stem: str, repo: str = GL_REPO) -> Path:
        self.queue.mkdir(parents=True, exist_ok=True)
        p = self.queue / f"{stem}.md"
        p.write_text(f"#!queue model=m effort=e repo={repo}\n\n# {stem}\n")
        return p

    def run(self, stem: str, repo: str = GL_REPO, **spec) -> dict:
        """Fire exactly one brief through the real run_loop; return the entry it recorded."""
        self.spec(**spec)
        self.brief(stem, repo)
        before = len(self.d.completed) + len(self.d.failed)
        self.d.run_loop()
        recorded = self.d.completed + self.d.failed
        assert len(recorded) == before + 1, "run_loop must record exactly one entry per fired brief"
        return max(recorded, key=lambda e: e["finished_at"])


@pytest.fixture
def fire(tmp_path, monkeypatch):
    return Fire(tmp_path, monkeypatch)


def _log_of(entry: dict) -> str:
    assert entry.get("log_file"), f"entry names no log: {entry}"
    p = Path(entry["log_file"])
    assert p.is_file(), f"log_file {p} is not on disk"
    return p.read_text(errors="replace")


# ═══════════════════════════════════════════════════════════════════════════════════════
# AC-SO-01 — the predicate, one case per reason.
# ═══════════════════════════════════════════════════════════════════════════════════════
class TestPredicate:

    @staticmethod
    def _one(entry) -> str:
        v = canon_assert.check_gate_log_invariants([entry])
        assert len(v) == 1, v
        return v[0].reason

    @pytest.fixture
    def good(self, tmp_path):
        p = tmp_path / "orch-good-20260927-120000.log"
        p.write_text("=== QUEUE ROUTE ===\n")
        return {"file": "good.md", "exit_code": 0, "started_at": "2026-09-27T12:00:00",
                "log_file": str(p)}

    def test_a_good_entry_is_clean(self, good):
        assert canon_assert.check_gate_log_invariants([good]) == []

    @pytest.mark.parametrize("value", ["absent", None, ""])
    def test_no_log_recorded(self, good, value):
        e = dict(good)
        if value == "absent":
            del e["log_file"]
        else:
            e["log_file"] = value
        assert self._one(e) == "no-log-recorded"

    def test_log_missing(self, good, tmp_path):
        assert self._one({**good, "log_file": str(tmp_path / "gone.log")}) == "log-missing"

    def test_log_not_a_file(self, good, tmp_path):
        (tmp_path / "a-dir.log").mkdir()
        assert self._one({**good, "log_file": str(tmp_path / "a-dir.log")}) == "log-not-a-file"

    @pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads mode 000")
    def test_log_unreadable_is_a_violation(self, good):
        p = Path(good["log_file"])
        p.chmod(0)
        try:
            assert self._one(good) == "log-unreadable"
        finally:
            p.chmod(0o644)

    def test_log_empty(self, good):
        Path(good["log_file"]).write_text("")
        assert self._one(good) == "log-empty"

    @pytest.mark.skipif(hasattr(os, "geteuid") and os.geteuid() == 0, reason="root reads mode 000")
    def test_only_the_first_reason_is_reported(self, good):
        """Empty AND unreadable: unreadable comes first in the order."""
        p = Path(good["log_file"])
        p.write_text("")
        p.chmod(0)
        try:
            assert self._one(good) == "log-unreadable"
        finally:
            p.chmod(0o644)

    def test_the_violation_carries_the_entry(self):
        v, = canon_assert.check_gate_log_invariants([{"exit_code": 1}])
        assert (v.brief, v.started_at, v.exit_code, v.log_file, v.reason) == \
               ("<unnamed>", "", 1, None, "no-log-recorded")
        assert "no-log-recorded" in str(v)

    def test_one_violation_per_entry_and_each_entry_judged(self, good):
        v = canon_assert.check_gate_log_invariants([good, {"file": "a.md"}, good, {"file": "b.md"}])
        assert [x.brief for x in v] == ["a.md", "b.md"]


# ═══════════════════════════════════════════════════════════════════════════════════════
# AC-SO-04 — the deadlock is gone.
# ═══════════════════════════════════════════════════════════════════════════════════════
class TestNoDeadlock:

    def test_huge_output_does_not_hang_the_route(self, fire):
        """320 KiB of stdout — five times the pipe buffer. Pre-fix: the child blocks on write(),
        the daemon in wait(), and the route is killed at timeout_seconds as exit -1."""
        e = fire.run("60-huge", stdout_bytes=320 * 1024,
                     stdout=["HUGE-LAST-STDOUT-LINE"], stderr=["HUGE-STDERR-LINE"], exit=0)
        assert e["exit_code"] == 0, f"route did not finish cleanly: {e}"
        assert e in fire.d.completed
        assert e["duration_s"] < 15
        text = _log_of(e)
        assert Path(e["log_file"]).stat().st_size >= 320 * 1024
        assert "HUGE-LAST-STDOUT-LINE" in text and "HUGE-STDERR-LINE" in text
        assert canon_assert.check_gate_log_invariants([e]) == []


# ═══════════════════════════════════════════════════════════════════════════════════════
# AC-SO-05 — the log is where the convention says, and holds the child's output.
# ═══════════════════════════════════════════════════════════════════════════════════════
class TestLogWhereTheConventionSays:

    def test_markers_land_under_the_configured_log_subdir(self, fire):
        stem = "61-markers"
        e = fire.run(stem, stdout=["STDOUT-MARKER-7f3a"], stderr=["STDERR-MARKER-9c1e"], exit=0)
        assert e.get("log_file"), f"entry names no log: {e}"
        name = Path(e["log_file"]).name
        m = re.fullmatch(rf"orch-{re.escape(stem)}-({TS})\.log", name)
        assert m, name
        assert e["log_file"] == str(fire.logs / GL_SUBDIR / f"orch-{stem}-{m.group(1)}.log")
        text = _log_of(e)
        assert "STDOUT-MARKER-7f3a" in text and "STDERR-MARKER-9c1e" in text
        assert "=== QUEUE ROUTE ===" in text and f"Batch: {stem}.md" in text
        assert "Command: " in text and "python3 -u orchestrator.py run" in text
        assert re.search(r"^Exit: 0$", text, re.M)
        assert canon_assert.check_gate_log_invariants([e]) == []

    def test_no_log_subdir_means_the_repo_name(self, fire):
        """orchestrator.py's rule: LOG_SUBDIR = r.get("log_subdir", name)."""
        e = fire.run("62-plain", repo=PLAIN_REPO, stdout=["PLAIN-MARKER"], exit=0)
        assert e.get("log_file"), f"entry names no log: {e}"
        assert Path(e["log_file"]).parent == fire.logs / PLAIN_REPO
        assert "PLAIN-MARKER" in _log_of(e)
        assert canon_assert.check_gate_log_invariants([e]) == []


# ═══════════════════════════════════════════════════════════════════════════════════════
# AC-SO-06 — every recording path names a readable log.
# ═══════════════════════════════════════════════════════════════════════════════════════
class TestEveryRecordingPath:

    def test_non_zero_exit(self, fire):
        e = fire.run("63-fails", stdout=["FAIL-MARKER"], stderr=["Traceback (most recent call last):"],
                     exit=3)
        assert e["exit_code"] == 3 and e in fire.d.failed
        text = _log_of(e)
        assert "FAIL-MARKER" in text and "Traceback" in text
        assert re.search(r"^Exit: 3$", text, re.M)
        assert canon_assert.check_gate_log_invariants([e]) == []

    def test_timeout_keeps_what_was_printed_before_the_kill(self, fire):
        """The marker is never flushed by hand: it survives the kill only through `python3 -u`."""
        fire.d.config["timeout_seconds"] = 2
        e = fire.run("64-hangs", stdout=["BEFORE-KILL-MARKER"], sleep=30, exit=0)
        assert e["exit_code"] == -1 and e in fire.d.failed
        text = _log_of(e)
        assert "BEFORE-KILL-MARKER" in text
        assert re.search(r"^Exit: -1 \(timeout after 2s\)$", text, re.M)
        assert canon_assert.check_gate_log_invariants([e]) == []

    def test_spawn_error(self, fire, monkeypatch):
        def refuse(*a, **kw):
            raise OSError("spawn refused by test")
        monkeypatch.setattr(queue_daemon, "subprocess", types.SimpleNamespace(
            Popen=refuse, STDOUT=subprocess.STDOUT, TimeoutExpired=subprocess.TimeoutExpired))
        e = fire.run("65-no-spawn", exit=0)
        assert e["exit_code"] == -2 and e in fire.d.failed
        text = _log_of(e)
        assert re.search(r"^Exit: -2 \(error: spawn refused by test\)$", text, re.M)
        assert canon_assert.check_gate_log_invariants([e]) == []

    def test_cancel_current(self, fire):
        """A route cancelled while it runs: the -9 entry names the route's own log, and the
        log says it was cancelled."""
        fire.spec(stdout=["CANCEL-MARKER"], sleep=30, exit=0)
        fire.brief("66-cancelled")
        t = threading.Thread(target=fire.d.run_loop, daemon=True)
        t.start()
        try:
            deadline = time.monotonic() + 5
            log_file = None
            while time.monotonic() < deadline:
                log_file = (fire.d.current_batch or {}).get("log_file")
                if log_file and "CANCEL-MARKER" in Path(log_file).read_text(errors="replace"):
                    break
                time.sleep(0.05)
            else:
                pytest.fail(f"the running route never named a log carrying its output "
                            f"(current_batch={fire.d.current_batch})")
        finally:
            fire.d.cancel_current()
            t.join(timeout=15)
        assert not t.is_alive()
        cancelled = [x for x in fire.d.failed if x["exit_code"] == -9]
        assert len(cancelled) == 1
        e = cancelled[0]
        assert e.get("log_file") == log_file
        text = _log_of(e)
        assert "CANCEL-MARKER" in text
        assert re.search(r"^Exit: -9 \(cancelled by user\)$", text, re.M)
        assert canon_assert.check_gate_log_invariants([e]) == []


# ═══════════════════════════════════════════════════════════════════════════════════════
# AC-SO-07 — no pipe.
# ═══════════════════════════════════════════════════════════════════════════════════════
def test_the_daemon_never_spawns_into_a_pipe():
    src = Path(queue_daemon.__file__).read_text()
    assert "subprocess.PIPE" not in src


# ═══════════════════════════════════════════════════════════════════════════════════════
# AC-SO-08 — reachability: run_loop (the post-route oracle) and `check-logs`.
# ═══════════════════════════════════════════════════════════════════════════════════════
class TestReachability:

    def test_run_loop_asks_the_predicate_about_every_recorded_entry(self, fire, monkeypatch):
        calls = []
        real = canon_assert.check_gate_log_invariants

        def spy(entries):
            calls.append(list(entries))
            return real(calls[-1])
        monkeypatch.setattr(queue_daemon, "check_gate_log_invariants", spy)

        passed = fire.run("67-pass", stdout=["ok"], exit=0)
        failed = fire.run("68-fail", stdout=["no"], exit=1)
        assert passed in fire.d.completed and failed in fire.d.failed
        assert len(calls) == 2
        assert calls[0] == [passed] and calls[0][0] is passed
        assert calls[1] == [failed] and calls[1][0] is failed

    def test_the_oracle_reports_and_changes_nothing(self, fire, monkeypatch, capsys):
        v = canon_assert.GateLogViolation(brief="69-x.md", started_at="t", exit_code=0,
                                          log_file=None, reason="no-log-recorded")
        monkeypatch.setattr(queue_daemon, "check_gate_log_invariants", lambda entries: [v])
        e = fire.run("69-x", stdout=["ok"], exit=0)
        assert e["exit_code"] == 0 and e in fire.d.completed
        assert f"[QUEUE] ⛔ ORCH-STDOUT-1 invariant: {v}" in capsys.readouterr().out

    def test_find_missing_gate_logs_over_the_recorded_history(self, fire, tmp_path):
        good_log = tmp_path / "orch-good-20260927-120000.log"
        good_log.write_text("=== QUEUE ROUTE ===\nExit: 0\n")
        queue_daemon.QUEUE_STATE.write_text(json.dumps({
            "completed": [{"file": "good.md", "exit_code": 0, "log_file": str(good_log)}],
            "failed": [{"file": "old.md", "exit_code": 1, "started_at": "2026-09-20T20:26:56"}],
        }))
        v = queue_daemon.QueueDaemon().find_missing_gate_logs()
        assert [(x.brief, x.reason) for x in v] == [("old.md", "no-log-recorded")]

    def test_check_logs_command(self, tmp_path):
        """The CLI a human runs: `python3 queue_daemon.py check-logs`. HOME is moved so every
        path the daemon derives from it is under tmp_path; nothing real is read or written."""
        orch = tmp_path / "spectricom-orchestrator"
        orch.mkdir()
        good_log = tmp_path / "orch-good-20260927-120000.log"
        good_log.write_text("x\n")
        state = {"completed": [{"file": "good.md", "exit_code": 0, "log_file": str(good_log)},
                               {"file": "a.md", "exit_code": 0}],
                 "failed": [{"file": "b.md", "exit_code": 1, "log_file": str(tmp_path / "gone.log")}]}
        (orch / "queue-state.json").write_text(json.dumps(state))
        env = {**os.environ, "HOME": str(tmp_path)}
        script = Path(queue_daemon.__file__)
        r = subprocess.run([sys.executable, str(script), "check-logs"], env=env,
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 1, r.stdout + r.stderr
        lines = r.stdout.splitlines()
        assert sum(1 for ln in lines if ln.startswith("FAIL ")) == 2
        assert lines[-1] == ("ORCH-STDOUT-1: 2 recorded route(s) without a readable log "
                             "(1 no-log-recorded, 1 log-missing)")

        (orch / "queue-state.json").write_text(json.dumps({"completed": state["completed"][:1]}))
        r = subprocess.run([sys.executable, str(script), "check-logs"], env=env,
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stdout + r.stderr
        assert r.stdout.splitlines()[-1] == "ORCH-STDOUT-1: 0 recorded route(s) without a readable log"

# filename: tests/test_orch_lane.py
"""Tests for ORCH-LANE-1 — a route in one repo never holds another repo's queue; a paused queue says so out
loud; any route can be verified with one read-only command; Kanban families come from config.

S7-CORE-19 · SCP_Kanban row 164 · LESSONS L-59, L-60 · PDLC v0-20 F-136/F-137 · route 104 handback item 2.

  P1 (O1)  the daemon waits only on the lock of the repo the next brief names            (TestP1*)
  P2 (O2)  every pause writes state/queue-paused.json and goes to Slack when a webhook is configured;
           resume clears it; `status` shows it on its first line                          (TestP2*)
  P3 (O3)  `orchestrator.py verify <stem> [--commit <sha>]`: read-only, never reads stdin  (TestP3*)
  P4 (O4)  the Kanban families A1 accepts come from config/repos.yaml `kanban_families`   (TestP4*)
  P5 (O5)  a gate command that dies fast says how: its exit code and first 5 stderr lines (TestP5*)

Every path is under tmp_path. No test signals the live daemon, sends to Slack or reads the live logs/.
"""

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time as real_time
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import orchestrator  # noqa: E402
import prefire  # noqa: E402
import queue_daemon  # noqa: E402
import slack_notify  # noqa: E402

FIXTURES = ROOT / "tests" / "fixtures" / "verify"
LIVE = os.getpid()
ISO = r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"


def _git(cmd: str, cwd: Path) -> str:
    r = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, f"{cmd}: {r.stderr}"
    return r.stdout.strip()


def _stripped_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "TONI_MODEL", "TONI_EFFORT")}
    env.update(extra)
    return env


# ═══════════════════════════════════════════════════════
# The daemon under tmp_path (P1, P2)
# ═══════════════════════════════════════════════════════
class Daemon:
    """One QueueDaemon wired under tmp_path, two repos in its repos.yaml; `_run_route` stubbed — no
    subprocess ever fires — and slack_notify.send_slack replaced by a recorder."""

    def __init__(self, tmp_path: Path, monkeypatch, exit_codes=()):
        self.orch = tmp_path / "orch"
        self.queue = self.orch / "queue"
        self.state_file = tmp_path / "queue-state.json"
        not_git = tmp_path / "not-a-repo"
        not_git.mkdir()
        cfg = tmp_path / "repos.yaml"
        cfg.write_text(yaml.safe_dump({"repos": {r: {"project_dir": str(not_git)}
                                                 for r in ("clinical-mp", "ai-foundation")}}))
        (self.orch / "state").mkdir(parents=True)
        for name, val in (("ORCH_DIR", self.orch), ("QUEUE_DIR", self.queue),
                          ("QUEUE_DONE", self.queue / "done"), ("QUEUE_FAILED", self.queue / "failed"),
                          ("QUEUE_STATE", self.state_file), ("REPOS_CONFIG", cfg),
                          ("LOG_DIR", tmp_path / "logs")):
            monkeypatch.setattr(queue_daemon, name, val)
        self.sent = []
        monkeypatch.setattr(slack_notify, "send_slack",
                            lambda text, blocks=None: self.sent.append(text) is None)
        self.d = queue_daemon.QueueDaemon()
        self.d.start_running = True
        self.d.config.update(cooldown_seconds=0, model="m", effort="e")
        self.fired = []
        self.codes = list(exit_codes)

        def _route(cmd, batch_name, log_path):
            self.fired.append(batch_name)
            Path(log_path).write_text("route output\n")
            return self.codes.pop(0) if self.codes else 0
        self.d._run_route = _route
        self.threads = []

    def webhook(self):
        """Slack configured, the way slack_notify.py set-webhook leaves it — beside the daemon's queue."""
        (self.orch / slack_notify.WEBHOOK_FILE.name).write_text(json.dumps({"url": "https://hooks.invalid/x"}))

    def brief(self, stem: str, repo: str = "clinical-mp") -> Path:
        self.queue.mkdir(parents=True, exist_ok=True)
        p = self.queue / f"{stem}.md"
        p.write_text(f"#!queue repo={repo}\n\n# {stem}\n")
        return p

    def stop_on_sleep(self, monkeypatch, after=1, on_sleep=None):
        seen = []

        def _sleep(s):
            seen.append(s)
            if on_sleep:
                on_sleep(len(seen))
            if len(seen) >= after:
                self.d.status = "stopped"
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep))
        return seen

    def state(self) -> dict:
        return json.loads(self.state_file.read_text()) if self.state_file.exists() else {}

    def notice_file(self) -> Path:
        return self.orch / "state" / "queue-paused.json"

    def notice(self) -> dict:
        return json.loads(self.notice_file().read_text())

    def stop_threads(self):
        for t in self.threads:
            for _ in range(400):
                self.d.status = "stopped"
                t.join(0.025)
                if not t.is_alive():
                    break
            assert not t.is_alive(), "a daemon thread outlived its test"


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    d = Daemon(tmp_path, monkeypatch)
    yield d
    d.stop_threads()


def _lock(daemon, repo, batch, pid=LIVE):
    """state/running-<repo>.json — orchestrator._write_running_marker's shape."""
    p = daemon.orch / "state" / f"running-{repo}.json"
    p.write_text(json.dumps({"pid": pid, "batch_id": batch, "repo": repo, "branch": f"orch-{batch}"}))
    return p


def _root(daemon, batch, pid=LIVE):
    """The root running.json — orchestrator.write_running's shape: no repo in it."""
    p = daemon.orch / "running.json"
    p.write_text(json.dumps({"batch_file": f"{batch}.md", "briefs": 1, "pid": pid}))
    return p


def _mirror(daemon, data):
    """state/running.json — the mirror orchestrator rebuilds from the per-repo locks."""
    p = daemon.orch / "state" / "running.json"
    p.write_text(json.dumps(data) if isinstance(data, dict) else data)
    return p


# ═══════════════════════════════════════════════════════
# P1 · O1 — a route in another repo never holds the queue
# ═══════════════════════════════════════════════════════
class TestP1FireLockPerRepo:

    def test_R_a_direct_route_in_another_repo_does_not_hold_the_queue(self, daemon, monkeypatch, capsys):
        """S7-CORE-19: 109 ran directly in ai-foundation; 110 (clinical-mp) waited behind it ~2 h, until
        Gemma paused the daemon and fired by hand. All three markers that direct run leaves are here.
        [ORCH-CAPACITY-1] O1 is the per-repo fire lock, and that is what this tests: C1's global limit is set to 2
        here. Under the shipped 1, admission holds 110 behind 109 — tests/test_capacity.py P1."""
        cfg = yaml.safe_load(queue_daemon.REPOS_CONFIG.read_text())
        queue_daemon.REPOS_CONFIG.write_text(yaml.safe_dump({**cfg, "admission": {"max_concurrent_routes": 2}}))
        _root(daemon, "109-minime-rules-1")
        _lock(daemon, "ai-foundation", "109-minime-rules-1")
        _mirror(daemon, {"pid": LIVE, "batch_id": "109-minime-rules-1", "repo": "ai-foundation"})
        daemon.brief("110-visit-release-safety-1", "clinical-mp")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.fired == ["110-visit-release-safety-1.md"]
        assert "fire lock held" not in capsys.readouterr().out

    def test_negative_control_its_own_repos_lock_holds(self, daemon, monkeypatch, capsys):
        lock = _lock(daemon, "clinical-mp", "105-messaging-draft-truth-1")
        daemon.brief("110-visit-release-safety-1", "clinical-mp")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.fired == [] and lock.exists()
        assert f"fire lock held for clinical-mp ({lock})" in capsys.readouterr().out

    def test_R_the_markers_orchestrator_itself_writes(self, daemon, monkeypatch):
        """Not hand-written shapes: the writers a direct `orchestrator.py run --repo ai-foundation` calls."""
        monkeypatch.setattr(orchestrator, "ORCH_DIR", daemon.orch)
        monkeypatch.setattr(orchestrator, "RUNNING_FILE", daemon.orch / "running.json")
        bf = Path("/x/109-minime-rules-1.md")
        orchestrator.write_running(bf, 1)
        orchestrator._write_running_marker(bf, "ai-foundation", Path("/x"), "orch-aif-109-minime-rules-1",
                                           None, False)
        assert {p.name for p in daemon.orch.rglob("running*.json")} == {
            "running.json", "running-ai-foundation.json"}, "root + lock + mirror"
        assert daemon.d._fire_lock_held("clinical-mp") is False
        assert daemon.d._fire_lock_held("ai-foundation") is True

    @pytest.mark.parametrize("markers,repo,held", [
        ({"lock": "clinical-mp"}, "clinical-mp", True),
        ({"lock": "ai-foundation"}, "clinical-mp", False),
        ({"lock": "ai-foundation", "root": "ai-foundation"}, "clinical-mp", False),
        ({"lock": "clinical-mp", "root": "clinical-mp"}, "clinical-mp", True),
        ({"mirror": "clinical-mp"}, "clinical-mp", True),       # a mirror naming it, its own lock gone
        ({"mirror": "ai-foundation"}, "clinical-mp", False),
        ({"mirror": None}, "clinical-mp", True),                # a pre-[ORCH-4] mirror names nobody
        ({"root": None}, "clinical-mp", True),                  # a root marker no lock names: unattributable
        ({}, "clinical-mp", False),
    ])
    def test_fire_lock_held_by_repo(self, daemon, markers, repo, held):
        batch = "1-x"
        if "lock" in markers:
            _lock(daemon, markers["lock"], batch)
        if "root" in markers:
            _root(daemon, batch if markers["root"] else "2-nobody-names-me")
        if "mirror" in markers:
            _mirror(daemon, {"pid": LIVE, "batch_id": batch, "repo": markers["mirror"]} if markers["mirror"]
                    else {"pid": LIVE, "batch_id": batch})
        assert daemon.d._fire_lock_held(repo) is held

    def test_an_unreadable_legacy_marker_holds_the_safe_direction(self, daemon):
        _mirror(daemon, "{not json")
        assert daemon.d._fire_lock_held("clinical-mp") is True

    def test_a_dead_marker_in_another_repo_is_still_cleared(self, daemon):
        """Stale clearing is unchanged: P-STALE runs before the lock is read, for every marker."""
        dead = subprocess.Popen(["true"])
        dead.wait()
        lock = _lock(daemon, "ai-foundation", "109-minime-rules-1", pid=dead.pid)
        assert daemon.d._fire_lock_held("clinical-mp") is False
        assert not lock.exists() and list((daemon.orch / "state").glob("running-ai-foundation.json.killed-*"))

    def test_a_header_edited_while_waiting_is_waited_on_again(self, daemon, monkeypatch):
        """The header is re-read after the wait. If it now names a repo whose lock is held, that lock is
        waited on — never fired into."""
        clin = _lock(daemon, "clinical-mp", "105-x")
        brief = daemon.brief("110-y", "clinical-mp")

        def _edit(n):
            if n == 1:
                clin.unlink()
                _lock(daemon, "ai-foundation", "109-z")
                brief.write_text("#!queue repo=ai-foundation\n\n# 110-y\n")
        daemon.stop_on_sleep(monkeypatch, after=3, on_sleep=_edit)
        daemon.d.run_loop()
        assert daemon.fired == []


# ═══════════════════════════════════════════════════════
# P2 · O2 — a pause is announced
# ═══════════════════════════════════════════════════════
class TestP2PauseNotice:

    def test_R_max_consecutive_writes_the_notice_and_calls_the_notifier(self, daemon, monkeypatch):
        """S7-CORE-19: 104 sat unfired behind `[QUEUE] PAUSED — max-consecutive:10`, a line in the daemon
        log and nowhere else, until Gemma read that log."""
        daemon.webhook()
        daemon.d.config["max_consecutive"] = 3
        daemon.d.consecutive_count = 3
        daemon.brief("104-orch-control-scope-1")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.fired == []
        n = daemon.notice()
        assert n["reason"] == "max-consecutive:3" and re.fullmatch(ISO + r".*", n["at"]), n
        assert n["next_brief"] == "104-orch-control-scope-1.md"
        assert n["resume"].endswith("python3 queue_daemon.py resume --reset-consecutive --reason max-consecutive:3")
        assert n["at"] == daemon.state()["paused_at"]
        assert len(daemon.sent) == 1, daemon.sent
        for part in ("PAUSED", "max-consecutive:3", "104-orch-control-scope-1.md", n["resume"]):
            assert part in daemon.sent[0], part

    def test_negative_control_no_webhook_no_send_the_file_still_written(self, daemon, monkeypatch, capsys):
        daemon.d.config["max_consecutive"] = 3
        daemon.d.consecutive_count = 3
        daemon.brief("104-orch-control-scope-1")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.sent == [] and daemon.notice()["reason"] == "max-consecutive:3"
        assert "Slack not configured" in capsys.readouterr().out

    def test_stop_on_failure_is_announced(self, daemon, monkeypatch):
        daemon.webhook()
        daemon.codes = [1]
        daemon.brief("95-a")
        daemon.brief("96-b")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        n = daemon.notice()
        assert (n["reason"], n["next_brief"]) == ("stop-on-failure:95-a.md", "96-b.md")
        assert n["resume"].endswith("python3 queue_daemon.py resume --reason stop-on-failure:95-a.md")
        assert len(daemon.sent) == 1 and "stop-on-failure:95-a.md" in daemon.sent[0]

    def test_an_operator_pause_is_announced_and_resume_clears_it(self, daemon):
        daemon.webhook()
        daemon.d.is_daemon = True
        daemon.d.status = "running"
        daemon.d.pause()
        daemon.d._send_pause_notice()
        assert daemon.notice()["reason"] == "operator" and len(daemon.sent) == 1
        daemon.d.resume()
        assert not daemon.notice_file().exists()

    def test_a_start_with_work_queued_is_announced(self, daemon, monkeypatch):
        daemon.d.start_running = False
        daemon.brief("110-a")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.notice()["reason"] == queue_daemon.START_PAUSED_REASON

    def test_negative_control_a_start_that_runs_clears_a_stale_notice(self, daemon, monkeypatch):
        daemon.notice_file().write_text(json.dumps({"reason": "operator", "at": "t"}))
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        assert not daemon.notice_file().exists()

    def test_negative_control_a_cli_object_never_announces(self, daemon):
        """`python3 queue_daemon.py …` builds a QueueDaemon that is not the daemon: its pause is not one."""
        daemon.webhook()
        daemon.d.status = "running"
        daemon.d.pause()
        daemon.d._send_pause_notice()
        assert not daemon.notice_file().exists() and daemon.sent == []

    def test_status_shows_it_on_its_first_line(self, daemon, monkeypatch, capsys):
        daemon.d.config["max_consecutive"] = 3
        daemon.d.consecutive_count = 3
        daemon.brief("104-orch-control-scope-1")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        n = daemon.notice()
        capsys.readouterr()
        assert queue_daemon.main(["status"]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert lines[0].startswith("daemon_status=paused paused_reason=max-consecutive:3 "), lines[0]
        assert "next brief 104-orch-control-scope-1.md" in lines[0] and f"resume: {n['resume']}" in lines[0]
        assert json.loads("\n".join(lines[1:]))["pause_notice"]["reason"] == "max-consecutive:3"

    def test_negative_control_a_notice_that_is_not_the_daemons_pause_is_not_shown(self, daemon, capsys):
        daemon.state_file.write_text(json.dumps({"daemon_status": "running", "pid": LIVE}))
        daemon.notice_file().write_text(json.dumps({"reason": "operator", "at": "t", "resume": "x"}))
        assert queue_daemon.main(["status"]) == 0
        lines = capsys.readouterr().out.splitlines()
        assert "next brief" not in lines[0] and json.loads("\n".join(lines[1:]))["pause_notice"] is None

    def test_the_resume_command_it_names_resumes_the_daemon(self, daemon, monkeypatch):
        """The notice's command, run as written, against a live daemon thread: the cap is reset and the
        daemon runs. A notice whose command does not work is not an announcement."""
        daemon.d.config["max_consecutive"] = 2
        daemon.d.consecutive_count = 2
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=lambda s: real_time.sleep(0.005)))
        t = threading.Thread(target=daemon.d.run_loop, daemon=True)
        daemon.threads.append(t)
        t.start()
        end = real_time.monotonic() + 5
        while not daemon.notice_file().exists() and real_time.monotonic() < end:
            real_time.sleep(0.005)
        argv = shlex.split(daemon.notice()["resume"].split(" && ")[-1])
        assert argv[:2] == ["python3", "queue_daemon.py"]
        assert queue_daemon.main(argv[2:]) == 0
        assert daemon.d.status == "running" and daemon.d.consecutive_count == 0
        assert not daemon.notice_file().exists()

    def test_negative_control_an_expired_resume_leaves_the_notice(self, daemon):
        daemon.d.is_daemon = True
        daemon.d.status = "running"
        daemon.d.pause()
        queue_daemon.control_file().write_text(json.dumps({
            "id": 1, "action": "resume", "reason": "max-consecutive:9", "issued_status": "paused",
            "issued_paused_reason": "max-consecutive:9", "requested_at": "2099-01-01T00:00:00"}))
        daemon.d._poll_control()
        assert daemon.d.status == "paused" and daemon.notice()["reason"] == "operator"


# ═══════════════════════════════════════════════════════
# P3 · O3 — one read-only verifier in the repo
# ═══════════════════════════════════════════════════════
STEM = "109-minime-rules-1"


@pytest.fixture
def home(tmp_path):
    """$HOME/spectricom-orchestrator under tmp_path: the repo's tracked top level plus config/, a repos.yaml
    whose ai-foundation is a real git repo where 109 merged, and route 109's two logs."""
    dst = tmp_path / "home" / "spectricom-orchestrator"
    dst.mkdir(parents=True)
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True,
                             check=True).stdout.split()
    for f in tracked:
        if "/" not in f and f.endswith((".py", ".json")) or f.startswith("config/"):
            (dst / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, dst / f)
    for f in ("orchestrator.py", "prefire.py", "queue_daemon.py"):   # this tree's, tracked or not yet
        shutil.copy2(ROOT / f, dst / f)
    aif = tmp_path / "spectricom-ai-foundation"
    aif.mkdir()
    _git("git init -q && git symbolic-ref HEAD refs/heads/main && git config user.email t@t && "
         "git config user.name T", aif)
    (aif / "README.md").write_text("base\n")
    _git("git add -A && git commit -qm base", aif)
    base = _git("git rev-parse --short=7 HEAD", aif)
    (aif / "briefs").mkdir()
    (aif / "briefs" / f"{STEM}.handback.md").write_text(f"# {STEM} — handback\n\nAll predicates P1–P9 pass.\n")
    (aif / "src.py").write_text("x = 1\n")
    _git(f"git checkout -qb orch-aif-{STEM} && git add -A && git commit -qm 'feat: MINIME-RULES-1' && "
         f"git checkout -q main && git merge -q --ff-only orch-aif-{STEM}", aif)
    tip = _git("git rev-parse --short=7 HEAD", aif)
    (dst / "config" / "repos.yaml").write_text(yaml.safe_dump({"repos": {
        "ai-foundation": {"project_dir": str(aif), "branch_prefix": "orch-aif", "merge_target": "main",
                          "log_subdir": "ai-foundation", "briefs_subdir": "briefs"},
        "clinical-mp": {"project_dir": str(tmp_path / "spectricom-clinical-mp"), "branch_prefix": "orch-mp",
                        "merge_target": "main", "log_subdir": "clinical-mp"}}}))
    logs = dst / "logs"
    (logs / "ai-foundation").mkdir(parents=True)
    live = "/home/gkassa/spectricom-orchestrator"
    (logs / "orch-20261004-184720.log").write_text(
        (FIXTURES / "orch-20261004-184720.log").read_text().replace("ba2c97e → 7822990", f"{base} → {tip}")
        .replace(live, str(dst)))
    shutil.copy2(FIXTURES / f"toni-{STEM}-20261004-184723.log", logs / "ai-foundation")
    (dst / "queue" / "done").mkdir(parents=True)
    (dst / "queue" / "done" / f"{STEM}.md").write_text(
        f"#!queue model=claude-opus-5-5 effort=xhigh repo=ai-foundation\n\n# MINIME-RULES-1\n")

    def run(*args, stdin=subprocess.DEVNULL, timeout=60):
        return subprocess.run([sys.executable, "orchestrator.py", *args], cwd=dst, capture_output=True,
                              text=True, timeout=timeout, stdin=stdin, env=_stripped_env(HOME=str(dst.parent)))
    run.dir, run.aif, run.tip, run.base = dst, aif, tip, base
    return run


def _one_line(r) -> str:
    lines = (r.stdout + r.stderr).strip().splitlines()
    assert len(lines) == 1, lines
    return lines[0]


class TestP3Verify:

    def test_R_an_ai_foundation_route_verifies_with_stdin_closed(self, home):
        """verify.sh hard-coded clinical-mp: for 109 its `ls -t …/orch-$B-*.log` matched nothing — a direct
        run writes logs/orch-<ts>.log — and `grep` waited on stdin."""
        r = home("verify", STEM)
        assert r.returncode == 0, r.stdout + r.stderr
        out = r.stdout
        assert f"repo ai-foundation" in out
        assert f"== orch log {home.dir / 'logs' / 'orch-20261004-184720.log'}" in out
        assert "🏁 FINAL STATUS: passed | gate: PASS" in out
        assert "Pre-merge gate on orch-aif-109-minime-rules-1: PASS" in out
        assert f"== handback-scan {home.dir / 'logs' / 'ai-foundation' / f'toni-{STEM}-20261004-184723.log'}" in out
        assert "1 logs scanned: 0 outstanding-work, 0 no-toni-header, 0 log-unreadable, 1 clean" in out
        assert f"== show --stat {home.tip}" in out and "feat: MINIME-RULES-1" in out
        assert f"briefs/{STEM}.handback.md" in out
        assert f"# {STEM} — handback" in out

    def test_it_never_waits_on_an_open_stdin(self, home):
        """The verify.sh hang, as a negative control: stdin is a pipe nobody writes or closes."""
        p = subprocess.Popen([sys.executable, "orchestrator.py", "verify", STEM], cwd=home.dir,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             env=_stripped_env(HOME=str(home.dir.parent)))
        try:
            rc = p.wait(timeout=60)        # never communicate(): it would close stdin
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            pytest.fail("verify waited on an open stdin")
        finally:
            p.stdin.close()
        out = p.stdout.read()
        p.stdout.close()
        assert rc == 0 and "🏁 FINAL STATUS: passed" in out, out

    def test_R_an_unknown_stem_is_one_line_exit_2(self, home):
        r = home("verify", "999-no-such-route-1")
        assert r.returncode == 2
        line = _one_line(r)
        assert line.startswith("verify: 999-no-such-route-1 —") and "config/repos.yaml" in line, line

    def test_a_missing_orch_log_is_one_line_exit_2(self, home):
        (home.dir / "logs" / "orch-20261004-184720.log").unlink()
        r = home("verify", STEM)
        assert r.returncode == 2
        line = _one_line(r)
        assert line.startswith(f"verify: {STEM} — no orch log") and str(home.dir / "logs") in line, line

    def test_a_missing_toni_log_is_said_in_one_line_and_exits_2(self, home):
        (home.dir / "logs" / "ai-foundation" / f"toni-{STEM}-20261004-184723.log").unlink()
        r = home("verify", STEM)
        assert r.returncode == 2
        assert "🏁 FINAL STATUS: passed" in r.stdout
        miss = [l for l in r.stdout.splitlines() if "no toni log" in l]
        assert len(miss) == 1 and f"toni-{STEM}-*.log" in miss[0], r.stdout

    def test_the_repo_resolves_from_its_logs_when_no_brief_is_found(self, home):
        (home.dir / "queue" / "done" / f"{STEM}.md").unlink()
        r = home("verify", STEM)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "repo ai-foundation (logs/ai-foundation" in r.stdout

    def test_an_explicit_commit_is_shown(self, home):
        r = home("verify", STEM, "--commit", home.base)
        assert r.returncode == 1, r.stdout          # base has no handback: said, exit 1
        assert f"== show --stat {home.base}" in r.stdout and " base" in r.stdout
        assert f"no briefs/{STEM}.handback.md at {home.base}" in r.stdout

    def test_a_commit_that_looks_like_an_option_is_refused(self, home):
        r = home("verify", STEM, "--commit=--output=/tmp/x")
        assert r.returncode == 2 and "not a commit" in _one_line(r)

    def test_handback_scan_outstanding_work_exits_1(self, home):
        toni = home.dir / "logs" / "ai-foundation" / f"toni-{STEM}-20261004-184723.log"
        toni.write_text(toni.read_text().replace("The design is written up",
                                                 "The re-run is going in the background. The design is written up"))
        r = home("verify", STEM)
        assert r.returncode == 1 and "FAIL " in r.stdout and "outstanding-work" in r.stdout

    def test_it_writes_nothing_in_the_repo(self, home):
        before = _git("git status --porcelain && git rev-parse HEAD && git stash list", home.aif)
        home("verify", STEM)
        assert _git("git status --porcelain && git rev-parse HEAD && git stash list", home.aif) == before


class TestP3VerifyLogChoice:
    """The orch log a stem resolves to, in-process: a daemon route's own log, or a direct run's."""

    @pytest.fixture
    def logs(self, tmp_path, monkeypatch):
        d = tmp_path / "logs"
        (d / "r").mkdir(parents=True)
        monkeypatch.setattr(orchestrator, "LOG_DIR", d)
        return d

    def test_a_stem_prefix_is_not_a_match(self, logs):
        """`ls -t orch-109-x-*.log` also matched orch-109-x-2-<ts>.log."""
        (logs / "r" / "orch-109-x-2-20261004-120000.log").write_text("FINAL STATUS: other\n")
        mine = logs / "r" / "orch-109-x-20261004-110000.log"
        mine.write_text("FINAL STATUS: mine\n")
        assert orchestrator._verify_orch_log("109-x", logs / "r") == mine

    def test_a_direct_run_is_found_by_its_parsed_line(self, logs):
        (logs / "orch-20261004-120000.log").write_text("12:00:00 [INFO   ] Parsed 109-x-2.md: 1 briefs\n")
        mine = logs / "orch-20261004-110000.log"
        mine.write_text("11:00:00 [INFO   ] Executor: m\n11:00:00 [INFO   ] Parsed 109-x.md: 1 briefs\n")
        (logs / "orch-20261004-130000.log").write_text("")      # a later read-only invocation's empty log
        assert orchestrator._verify_orch_log("109-x", logs / "r") == mine

    def test_a_daemon_routes_own_log_wins_over_its_processes_log(self, logs):
        daemon_log = logs / "r" / "orch-109-x-20261004-110000.log"
        daemon_log.write_text("Parsed 109-x.md: 1 briefs\nFINAL STATUS: passed\n")
        os.utime(daemon_log, (real_time.time(), real_time.mktime((2026, 10, 4, 12, 0, 0, 0, 0, -1))))
        (logs / "orch-20261004-110001.log").write_text("Parsed 109-x.md: 1 briefs\n")
        assert orchestrator._verify_orch_log("109-x", logs / "r") == daemon_log

    def test_a_later_direct_run_wins_over_an_earlier_daemon_route(self, logs):
        daemon_log = logs / "r" / "orch-109-x-20261004-110000.log"
        daemon_log.write_text("FINAL STATUS: blocked\n")
        os.utime(daemon_log, (real_time.time(), real_time.mktime((2026, 10, 4, 12, 0, 0, 0, 0, -1))))
        later = logs / "orch-20261004-150000.log"
        later.write_text("Parsed 109-x.md: 1 briefs\n")
        assert orchestrator._verify_orch_log("109-x", logs / "r") == later


# ═══════════════════════════════════════════════════════
# P4 · O4 — Kanban families come from config
# ═══════════════════════════════════════════════════════
@pytest.fixture
def canon(tmp_path, monkeypatch):
    c = tmp_path / "canon"
    c.mkdir()
    (c / "X_Kanban_v0-1.md").write_text("# X Kanban\n\n| # | Item | State |\n|---|---|---|\n| 7 | x | **`READY`** |\n")
    (c / "SCP_Kanban_v0-1.md").write_text("| # | Item | State |\n|---|---|---|\n| 1 | y | **`READY`** |\n")
    cfg = tmp_path / "repos.yaml"
    monkeypatch.setattr(prefire, "REPOS_CONFIG", cfg)

    def config(**extra):
        cfg.write_text(yaml.safe_dump({"kanban_dir": str(c), "repos": {}, **extra}))
    config()
    return config


def _kbrief(tmp_path, line):
    p = tmp_path / "b.md"
    p.write_text(f"#!queue repo=x\n\n# t\n{line}## Estimated runtime: 60-90 min\n")
    return p


class TestP4KanbanFamilies:

    def test_R_a_third_family_in_config_passes_a1(self, canon, tmp_path):
        canon(kanban_families=["SCP_Kanban", "Yorsie_Kanban", "X_Kanban"])
        assert prefire.check(_kbrief(tmp_path, "## Kanban: X_Kanban row 7 (READY)\n")) == []

    def test_negative_control_absent_from_config_it_is_refused_as_today(self, canon, tmp_path):
        assert prefire.check(_kbrief(tmp_path, "## Kanban: X_Kanban row 7 (READY)\n")) == [
            "A1 KANBAN — '## Kanban: X_Kanban row 7' names no Kanban family (SCP_Kanban or Yorsie_Kanban), not READY"]

    def test_the_messages_name_the_configured_families(self, canon, tmp_path):
        canon(kanban_families=["SCP_Kanban", "X_Kanban"])
        assert prefire.check(_kbrief(tmp_path, "")) == [
            "A1 KANBAN — no '## Kanban: <SCP_Kanban|X_Kanban> row <N>' header; a brief fires only from a "
            "READY Kanban row"]
        assert prefire.check(_kbrief(tmp_path, "## Kanban: Yorsie_Kanban row 1\n")) == [
            "A1 KANBAN — '## Kanban: Yorsie_Kanban row 1' names no Kanban family (SCP_Kanban or X_Kanban), "
            "not READY"]

    @pytest.mark.parametrize("bad", ["X_Kanban", [], ["X Kanban"], [3], {"a": 1}])
    def test_a_malformed_value_is_not_guessed_at(self, canon, tmp_path, bad):
        canon(kanban_families=bad)
        assert prefire.kanban_families() == prefire.KANBAN_FAMILIES
        assert prefire.check(_kbrief(tmp_path, "## Kanban: SCP_Kanban row 1\n")) == []

    def test_the_real_config_declares_the_current_two(self):
        cfg = yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())
        assert tuple(cfg["kanban_families"]) == prefire.KANBAN_FAMILIES == ("SCP_Kanban", "Yorsie_Kanban")


# ═══════════════════════════════════════════════════════
# P5 · O5 — a gate command that dies fast says so
# ═══════════════════════════════════════════════════════
@pytest.fixture
def repo(tmp_path):
    """A real repo: main@M0 (the merge base) → branch `route`, checked out."""
    p = tmp_path / "repo"
    p.mkdir()
    _git("git init -q && git symbolic-ref HEAD refs/heads/main && git config user.email t@t && "
         "git config user.name t", p)
    (p / "marker.txt").write_text("base")
    _git("git add -A && git commit -qm M0 && git checkout -qb route", p)
    (p / "marker.txt").write_text("branch")
    _git("git commit -qam work", p)
    return p


@contextmanager
def active(tmp_path, test_cmd=None, build_cmd=None, env_file=None):
    cfg = {"project_dir": "/x"}
    if test_cmd:
        cfg["test_cmd"] = test_cmd
    if build_cmd:
        cfg["build_gate_cmd"] = build_cmd
    gates = {"gated": {"gates": ("build",), "env_file": env_file}} if build_cmd else {}
    with patch.object(orchestrator, "ACTIVE_REPO_NAME", "gated"), \
         patch.object(orchestrator, "ACTIVE_REPO_CONFIG", cfg), \
         patch.object(orchestrator, "MERGE_TARGET", "main"), \
         patch.object(orchestrator, "UNIT_GATE_ENABLED", True), \
         patch.object(orchestrator, "BUILD_GATE_ENABLED", True), \
         patch.object(orchestrator, "PRE_MERGE_GATES", gates), \
         patch.object(orchestrator, "SIT_ARCHIVE_DIR", tmp_path / "archive"), \
         patch.object(orchestrator, "load_repo_config", return_value={"repos": {"gated": cfg}}):
        yield


SIX = "printf 'e1\\ne2\\n\\ne3\\ne4\\ne5\\ne6\\n' >&2"


class TestP5FastGateDeath:

    def test_R_false_is_blocked_environment_and_says_exit_1(self, repo, tmp_path):
        with active(tmp_path, test_cmd="false"):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.BLOCKED_ENV and v.signal == "comparison-unavailable"
        assert "test command failed in" in v.detail and "(exit 1); stderr empty" in v.detail, v.detail
        assert "exit 1" in v.label

    def test_R_the_first_five_stderr_lines_are_in_the_message(self, repo, tmp_path):
        with active(tmp_path, test_cmd=f"{SIX}; exit 127"):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.BLOCKED_ENV
        assert "(exit 127); stderr: e1 ⏎ e2 ⏎ e3 ⏎ e4 ⏎ e5" in v.detail and "e6" not in v.detail, v.detail

    def test_R_route_108s_command_under_bin_sh(self, repo, tmp_path):
        """ai-foundation's test_cmd before 8d962c5: `source` is not a /bin/sh builtin."""
        with active(tmp_path, test_cmd="source venv/bin/activate && PYTHONPATH=. pytest"):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.BLOCKED_ENV
        assert "suite output did not parse on branch (runner=unrecognised)" in v.detail, "the old words stay"
        assert re.search(r"on the branch the test command failed in 0\.\ds \(exit 127\); stderr: \S*sh: \d+: "
                         r"source: not found", v.detail), v.detail

    def test_negative_control_a_parseable_red_suite_is_unchanged(self, repo, tmp_path):
        with active(tmp_path, test_cmd="echo '1 failed, 1 passed in 0.01s'; exit 1"):
            o = orchestrator.run_unit_gate(repo, "route", archive_path=tmp_path / "archive")
        assert "test command failed in" not in (o.detail or "")

    @pytest.mark.parametrize("code,dur,head,said", [
        (127, 0.1, "sh: 1: source: not found\n", "failed in 0.1s (exit 127); stderr: sh: 1: source: not found"),
        (1, 4.9, "", "failed in 4.9s (exit 1); stderr empty"),
        (1, 5.0, "boom", None),           # not fast
        (0, 0.1, "warn", None),           # not a failure
        (1, 0.1, None, None),             # no exit observed (timeout, raise, a cached leg)
    ])
    def test_gate_fast_death(self, code, dur, head, said):
        assert orchestrator._gate_fast_death(code, dur, head) == said

    def test_R_a_blocked_build_gate_that_died_fast_says_how(self, repo, tmp_path):
        with active(tmp_path, build_cmd=f"echo 'pytest: command not found' >&2; exit 127"):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.BLOCKED_ENV and v.signal == "toolchain-missing"
        assert "; the build command failed in" in v.detail
        assert "(exit 127); stderr: pytest: command not found" in v.detail, v.detail

    def test_negative_control_a_build_gate_product_failure_is_unchanged(self, repo, tmp_path):
        """No gate semantics change: a fast red build with no F-20 signal stays FAIL(product), worded as before."""
        with active(tmp_path, build_cmd="echo boom >&2; exit 1"):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.FAIL_PRODUCT
        assert v.detail == "no F-20 environment signal in gate output — product verdict stands"

    def test_an_env_file_line_is_never_quoted(self, repo, tmp_path):
        """The build and SIT gate shells source the repo's env_file; a line naming it may carry a value."""
        (repo / ".env").write_text("A=1\n")
        with active(tmp_path, env_file=".env",
                    build_cmd="echo './.env: 3: s3cr3t-value: not found' >&2; echo 'npm: not found' >&2; exit 127"):
            v = orchestrator.run_pre_merge_gates(repo, "route")
        assert v.outcome is orchestrator.GateOutcome.BLOCKED_ENV
        assert "s3cr3t-value" not in v.detail and "npm: not found" in v.detail, v.detail
        assert "a line naming .env, elided" in v.detail

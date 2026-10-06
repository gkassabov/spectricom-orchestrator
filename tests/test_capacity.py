"""ORCH-CAPACITY-1 (S7-CORE-21) — the laptop runs one Toni route at a time, only with memory to spare; an
ai-foundation route's gate runs without a local venv; the MiniMe services move only on purpose; the daemon
never kills a route that is inside its own budget.

  P1 (C1a)  a live route in another repo refuses admission; the daemon waits; a direct `run` exits 2.
  P2 (C1b)  MemAvailable below the configured floor refuses; above admits; the floor is config.
  P3 (C1)   max_concurrent_routes: 2 admits a second route; the shipped config says 1; a claim holds a slot.
  P4 (C2)   the staged ai-foundation block resolves to /home/gkassa/aif-toni/<route>; the gate command runs
            green in a git worktree with no local venv/. The flip itself is STOPPED (the venv link hazard).
  P5 (C3)   scripts/aif-deploy.sh refuses while an ai-foundation route is live; its dry-run changes nothing.
  P7 (C4)   a 162-min route's daemon wall is >= 162 min + its gate budget; a gate still running at the old
            190-min mark is not killed (fake clock); a route over its whole wall is, and the kill names it.

Everything runs under tmp_path: the markers, the meminfo, the repos, the daemon's queue. No test reads the
live ~/spectricom-orchestrator state, and none touches ~/spectricom-ai-foundation's working tree.
"""

import json
import os
import re
import shutil
import signal
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import admission  # noqa: E402
import orchestrator  # noqa: E402
import queue_daemon  # noqa: E402

pytestmark = pytest.mark.admission   # conftest: this file sets up meminfo and markers itself
GIB_KB = 1024 * 1024
REPO_GLOBALS = ("ACTIVE_REPO_NAME", "ACTIVE_REPO_CONFIG", "PROJECT_ROOT", "YORSIE_DIR", "BRIEFS_DIR",
                "WORKTREE_BASE", "BRANCH_PREFIX", "MERGE_TARGET", "REMOTE", "LOG_SUBDIR", "WORKTREE_MODE",
                "TEST_CMD", "IS_META_FIRE")
SHIPPED = yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())


def _git(cmd: str, cwd: Path) -> str:
    r = subprocess.run(cmd, shell=True, cwd=str(cwd), capture_output=True, text=True)
    assert r.returncode == 0, f"{cmd}: {r.stderr}"
    return r.stdout.strip()


def _meminfo(path: Path, gib: float) -> Path:
    path.write_text(f"MemTotal:       {20 * GIB_KB} kB\nMemFree:        {GIB_KB} kB\n"
                    f"MemAvailable:   {int(gib * GIB_KB)} kB\n")
    return path


@pytest.fixture
def live_pid():
    """A real process that stays alive for the test: a route's pid that is not this test's own."""
    p = subprocess.Popen(["sleep", "300"])
    yield p.pid
    p.kill()
    p.wait()


@pytest.fixture
def dead_pid():
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


class Orch:
    """An orchestrator dir under tmp_path: state/, config/repos.yaml, a meminfo."""

    def __init__(self, tmp_path: Path, monkeypatch, admission_block=None, gib: float = 32):
        self.dir = tmp_path / "orch"
        (self.dir / "state").mkdir(parents=True)
        (self.dir / "config").mkdir()
        self.not_git = tmp_path / "not-a-repo"
        self.not_git.mkdir()
        repos = {r: {"project_dir": str(self.not_git)} for r in ("clinical-mp", "ai-foundation", "yorsie")}
        repos["clinical-mp"].update(test_cmd="npm test", test_timeout_s=1800)
        self.cfg = {"repos": repos}
        if admission_block is not None:
            self.cfg["admission"] = admission_block
        self.config = self.dir / "config" / "repos.yaml"
        self.write_config()
        self.meminfo = _meminfo(tmp_path / "meminfo", gib)
        monkeypatch.setattr(admission, "MEMINFO", self.meminfo)

    def write_config(self):
        self.config.write_text(yaml.safe_dump(self.cfg))

    def lock(self, repo: str, batch: str, pid) -> Path:
        """state/running-<repo>.json — orchestrator._write_running_marker's shape."""
        p = self.dir / "state" / f"running-{repo}.json"
        p.write_text(json.dumps({"pid": pid, "batch_id": batch, "repo": repo, "branch": f"orch-{batch}"}))
        return p

    def admit(self, repo: str, *a, **kw):
        return admission.admit(repo, *a, orch_dir=self.dir, config_path=self.config, **kw)


@pytest.fixture
def orch(tmp_path, monkeypatch):
    return Orch(tmp_path, monkeypatch)


# ═══════════════════════════════════════════════════════
# The daemon under tmp_path — test_orch_lane's harness, with admission real
# ═══════════════════════════════════════════════════════
class Daemon:
    def __init__(self, tmp_path: Path, monkeypatch, o: Orch):
        self.o = o
        self.queue = o.dir / "queue"
        self.state_file = tmp_path / "queue-state.json"
        for name, val in (("ORCH_DIR", o.dir), ("QUEUE_DIR", self.queue), ("QUEUE_DONE", self.queue / "done"),
                          ("QUEUE_FAILED", self.queue / "failed"), ("QUEUE_STATE", self.state_file),
                          ("REPOS_CONFIG", o.config), ("LOG_DIR", tmp_path / "logs")):
            monkeypatch.setattr(queue_daemon, name, val)
        self.d = queue_daemon.QueueDaemon()
        self.d.start_running = True
        self.d.config.update(cooldown_seconds=0, model="m", effort="e")
        self.fired, self.walls, self.cmds = [], [], []

        def _route(cmd, batch_name, log_path):
            self.fired.append(batch_name)
            self.cmds.append(cmd)
            self.walls.append(dict((self.d.current_batch or {}).get("wall") or {}))
            Path(log_path).write_text("route output\n")
            return 0
        self.d._run_route = _route

    def brief(self, stem: str, repo: str, body: str = "") -> Path:
        self.queue.mkdir(parents=True, exist_ok=True)
        p = self.queue / f"{stem}.md"
        p.write_text(f"#!queue repo={repo}\n\n# {stem}\n{body}")
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


@pytest.fixture
def daemon(tmp_path, monkeypatch, orch):
    return Daemon(tmp_path, monkeypatch, orch)


@pytest.fixture
def cli(tmp_path, monkeypatch, orch):
    """orchestrator.main() for `run`, with admission real and everything after it replaced."""
    for g in REPO_GLOBALS:
        monkeypatch.setattr(orchestrator, g, getattr(orchestrator, g))
    monkeypatch.setattr(orchestrator, "ORCH_DIR", orch.dir)
    monkeypatch.setattr(orchestrator, "REPOS_CONFIG_PATH", orch.config)
    monkeypatch.delenv(admission.CLAIM_ENV, raising=False)
    ran = []
    now = orchestrator.datetime.now().isoformat()

    def _run_batch(bf, worktree=None):
        ran.append(bf.name)
        return orchestrator.Result(batch_file=bf.name, status=orchestrator.Status.PASSED, started=now,
                                   finished=now, duration_s=0.0, exit_code=0, briefs=1)
    monkeypatch.setattr(orchestrator, "run_batch", _run_batch)
    monkeypatch.setattr(orchestrator, "approval_gate", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator, "rate_check", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator, "load_state", lambda: {"completed": [], "failed": []})
    monkeypatch.setattr(orchestrator, "save_state", lambda s: None)

    def main(*argv):
        monkeypatch.setattr(sys, "argv", ["orchestrator.py", *argv])
        try:
            orchestrator.main()
        except SystemExit as e:
            return e.code
        return 0

    brief = tmp_path / "120-minime-x-1.md"
    brief.write_text("#!queue repo=ai-foundation\n\n# 120\n")
    return types.SimpleNamespace(main=main, ran=ran, brief=str(brief))


# ═══════════════════════════════════════════════════════
# P1 · C1a — a live route anywhere holds every repo
# ═══════════════════════════════════════════════════════
class TestP1RouteLimit:

    def test_R_a_live_clinical_route_refuses_ai_foundation(self, orch, live_pid):
        orch.lock("clinical-mp", "110-visit-release-safety-1", live_pid)
        ok, why = orch.admit("ai-foundation")
        assert ok is False
        assert why.startswith("route limit — 1 live route(s), admission.max_concurrent_routes 1: ")
        assert f"clinical-mp 110-visit-release-safety-1 (pid {live_pid}, state/running-clinical-mp.json)" in why

    def test_R_the_daemon_does_not_fire_and_status_says_why(self, daemon, orch, live_pid, monkeypatch, capsys):
        orch.lock("clinical-mp", "110-visit-release-safety-1", live_pid)
        brief = daemon.brief("120-minime-x-1", "ai-foundation")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.fired == [] and brief.exists(), "nothing fired; the brief stays first in queue/"
        assert daemon.d.failed == [] and daemon.d.status != "paused", "a wait, never a failure or a pause"
        out = capsys.readouterr().out
        assert "[QUEUE] 🛡 admission: waiting before 120-minime-x-1.md — route limit — 1 live route(s)" in out
        st = daemon.state()
        st["daemon_status"] = "running"   # stop_on_sleep stopped it; the line is a running daemon's
        line = queue_daemon.status_line(st)
        assert line.startswith("daemon_status=running ")
        assert f"| waiting: 120-minime-x-1.md — route limit — 1 live route(s)" in line and "clinical-mp" in line

    def test_R_one_line_per_change_of_reason(self, daemon, orch, live_pid, monkeypatch, capsys):
        """Six re-checks: three on the route limit, then three on the floor with MemAvailable moving."""
        lock = orch.lock("clinical-mp", "110-visit-release-safety-1", live_pid)

        def _then(n):
            if n == 3:
                lock.unlink()
            if n >= 3:
                _meminfo(orch.meminfo, 2 + n / 10)
        daemon.brief("120-minime-x-1", "ai-foundation")
        daemon.stop_on_sleep(monkeypatch, after=6, on_sleep=_then)
        daemon.d.run_loop()
        said = [l for l in capsys.readouterr().out.splitlines() if "admission: waiting before" in l]
        assert len(said) == 2, said
        assert "route limit" in said[0] and "memory floor — MemAvailable 2.3 GiB" in said[1]
        assert daemon.fired == []

    def test_R_a_direct_run_exits_2_with_the_reason(self, cli, orch, live_pid, capsys):
        orch.lock("clinical-mp", "110-visit-release-safety-1", live_pid)
        assert cli.main("run", cli.brief, "--repo", "ai-foundation", "--approve") == 2
        err = capsys.readouterr().err
        assert "⛔ ADMISSION — route limit — 1 live route(s)" in err and "clinical-mp 110-visit-release-safety-1" in err
        assert cli.ran == [] and not list((orch.dir / "state").glob("admitted-*.json")), "refused: no claim"

    def test_R_a_direct_run_exits_2_end_to_end(self, tmp_path, live_pid):
        """The real CLI in a copy of this repo (its own ORCH_DIR), not main() in-process."""
        dst = tmp_path / "home" / "spectricom-orchestrator"
        (dst / "config").mkdir(parents=True)
        for f in subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True,
                                check=True).stdout.split():
            if "/" not in f and f.endswith(".py"):
                shutil.copy2(ROOT / f, dst / f)
        repo = tmp_path / "aif"
        repo.mkdir()
        (dst / "config" / "repos.yaml").write_text(yaml.safe_dump({"repos": {
            r: {"project_dir": str(repo)} for r in ("ai-foundation", "clinical-mp")}}))
        (dst / "state").mkdir()
        (dst / "state" / "running-clinical-mp.json").write_text(json.dumps(
            {"pid": live_pid, "batch_id": "110-visit-release-safety-1", "repo": "clinical-mp"}))
        brief = tmp_path / "120-minime-x-1.md"
        brief.write_text("#!queue repo=ai-foundation\n\n# 120\n")
        env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", admission.CLAIM_ENV)}
        r = subprocess.run([sys.executable, "orchestrator.py", "run", str(brief), "--repo", "ai-foundation",
                            "--approve"], cwd=dst, capture_output=True, text=True, timeout=120,
                           env={**env, "HOME": str(dst.parent)})
        assert r.returncode == 2, r.stderr[-2000:]
        assert "⛔ ADMISSION — route limit" in r.stderr and f"clinical-mp 110-visit-release-safety-1 (pid {live_pid}" in r.stderr

    def test_one_route_is_one_route_however_many_markers(self, orch, live_pid):
        """Root running.json + the lock + the mirror, as a direct run leaves them: one route, not three."""
        orch.lock("ai-foundation", "109-minime-rules-1", live_pid)
        (orch.dir / "state" / "running.json").write_text(json.dumps(
            {"pid": live_pid, "batch_id": "109-minime-rules-1", "repo": "ai-foundation"}))
        (orch.dir / "running.json").write_text(json.dumps({"batch_file": "109-minime-rules-1.md", "pid": live_pid}))
        routes = admission.live_routes(orch.dir)
        assert [(r.repo, r.batch, r.pid) for r in routes] == [("ai-foundation", "109-minime-rules-1", live_pid)]

    def test_negative_control_a_stale_marker_is_ignored(self, orch, dead_pid, daemon, monkeypatch):
        orch.lock("clinical-mp", "110-visit-release-safety-1", dead_pid)
        assert orch.admit("ai-foundation")[0] is True
        daemon.brief("120-minime-x-1", "ai-foundation")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.fired == ["120-minime-x-1.md"]

    def test_negative_control_a_stale_marker_admits_a_direct_run(self, cli, orch, dead_pid):
        orch.lock("clinical-mp", "110-visit-release-safety-1", dead_pid)
        assert cli.main("run", cli.brief, "--repo", "ai-foundation", "--approve") == 0
        assert cli.ran == ["120-minime-x-1.md"]

    def test_force_bypasses_and_says_so(self, cli, orch, live_pid, caplog):
        orch.lock("clinical-mp", "110-visit-release-safety-1", live_pid)
        assert cli.main("run", cli.brief, "--repo", "ai-foundation", "--approve", "--force") == 0
        assert cli.ran == ["120-minime-x-1.md"]
        said = [r.getMessage() for r in caplog.records if "admission BYPASSED" in r.getMessage()]
        assert said and said[0].startswith("--force: admission BYPASSED — it would have refused: route limit")

    def test_the_per_repo_lock_still_answers_first(self, cli, orch, live_pid, capsys):
        """P6: a live lock in the SAME repo is still [ORCH-4]'s exit 4, said its own way — not admission's 2."""
        orch.lock("ai-foundation", "109-minime-rules-1", live_pid)
        assert cli.main("run", cli.brief, "--repo", "ai-foundation", "--approve") == 4
        assert "A fire is already in progress for repo 'ai-foundation'" in capsys.readouterr().err


# ═══════════════════════════════════════════════════════
# P2 · C1b — the memory floor, from config
# ═══════════════════════════════════════════════════════
class TestP2MemoryFloor:

    def test_R_below_the_floor_is_refused_with_the_number_and_the_floor(self, orch):
        _meminfo(orch.meminfo, 4)
        ok, why = orch.admit("clinical-mp")
        assert ok is False
        assert why == (f"memory floor — MemAvailable 4.0 GiB < admission.min_mem_available_gib 6 GiB "
                       f"({orch.meminfo}) — clinical-mp waits")

    def test_above_the_floor_is_admitted(self, orch):
        _meminfo(orch.meminfo, 8)
        ok, why = orch.admit("clinical-mp")
        assert ok is True and "MemAvailable 8.0 GiB >= admission.min_mem_available_gib 6 GiB" in why

    def test_R_the_floor_is_config_and_the_verdict_follows_it(self, orch):
        _meminfo(orch.meminfo, 4)
        orch.cfg["admission"] = {"min_mem_available_gib": 3}
        orch.write_config()
        assert orch.admit("clinical-mp")[0] is True
        orch.cfg["admission"] = {"min_mem_available_gib": 5.5}
        orch.write_config()
        ok, why = orch.admit("clinical-mp")
        assert ok is False and "< admission.min_mem_available_gib 5.5 GiB" in why

    def test_unreadable_meminfo_is_refused_never_guessed(self, orch):
        orch.meminfo.write_text("MemTotal: 1 kB\n")
        ok, why = orch.admit("clinical-mp")
        assert ok is False and "MemAvailable unreadable" in why

    def test_R_the_daemon_waits_on_the_floor(self, daemon, orch, monkeypatch, capsys):
        _meminfo(orch.meminfo, 2)
        daemon.brief("120-minime-x-1", "ai-foundation")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.fired == []
        assert "waiting before 120-minime-x-1.md — memory floor — MemAvailable 2.0 GiB" in capsys.readouterr().out

    def test_the_real_proc_meminfo_parses(self):
        assert admission.mem_available_gib(Path("/proc/meminfo")) > 0


# ═══════════════════════════════════════════════════════
# P3 · C1 — the limit is config; the shipped one is 1; a claim holds its slot
# ═══════════════════════════════════════════════════════
class TestP3Limit:

    def test_R_a_limit_of_2_admits_a_second_route(self, orch, live_pid):
        orch.lock("clinical-mp", "110-visit-release-safety-1", live_pid)
        orch.cfg["admission"] = {"max_concurrent_routes": 2}
        orch.write_config()
        ok, why = orch.admit("ai-foundation")
        assert ok is True and "1 live route(s) < admission.max_concurrent_routes 2" in why

    def test_the_shipped_config_says_1_and_6(self):
        assert SHIPPED["admission"] == {"max_concurrent_routes": 1, "min_mem_available_gib": 6}
        assert admission.limits(ROOT / "config" / "repos.yaml") == (1, 6.0)

    @pytest.mark.parametrize("bad", [0, -1, "2", True, None, 2.5])
    def test_a_limit_that_is_not_a_count_is_the_default(self, orch, bad):
        orch.cfg["admission"] = {"max_concurrent_routes": bad}
        orch.write_config()
        assert admission.limits(orch.config)[0] == admission.DEFAULT_MAX_CONCURRENT_ROUTES

    def test_a_claim_holds_the_slot_before_the_routes_own_lock_exists(self, orch, live_pid):
        """Two askers, one slot: the first's claim is a live route to the second."""
        claim = orch.dir / "state" / f"admitted-{live_pid}.json"
        claim.write_text(json.dumps({"pid": live_pid, "repo": "yorsie", "batch": "129-yorsie-today-1"}))
        ok, why = orch.admit("ai-foundation")
        assert ok is False and f"yorsie 129-yorsie-today-1 (pid {live_pid}, state/admitted-{live_pid}.json)" in why

    def test_a_yes_with_claim_writes_the_claim_under_the_lock(self, orch):
        ok, _ = orch.admit("ai-foundation", "120-minime-x-1", claim=True)
        data = json.loads(admission.claim_path(orch.dir).read_text())
        assert ok and data["pid"] == os.getpid() and data["batch"] == "120-minime-x-1"
        admission.release(admission.claim_path(orch.dir))

    def test_the_daemons_claim_is_adopted_by_its_route(self, orch, live_pid):
        """The daemon (live_pid) claimed for 120 and fired it; the route's `run` takes the claim over."""
        claim = orch.dir / "state" / f"admitted-{live_pid}.json"
        claim.write_text(json.dumps({"pid": live_pid, "repo": "ai-foundation", "batch": "120-minime-x-1"}))
        ok, why = admission.admit_run("ai-foundation", "120-minime-x-1", orch_dir=orch.dir, config_path=orch.config,
                                      env={admission.CLAIM_ENV: str(claim)})
        assert ok is True and why.startswith(f"admitted by the queue daemon (pid {live_pid}")
        assert json.loads(claim.read_text())["pid"] == os.getpid()
        admission.release(claim, os.getpid())
        assert not claim.exists()

    def test_negative_control_a_claim_for_another_brief_is_not_adopted(self, orch, live_pid):
        claim = orch.dir / "state" / f"admitted-{live_pid}.json"
        claim.write_text(json.dumps({"pid": live_pid, "repo": "ai-foundation", "batch": "121-other-1"}))
        ok, why = admission.admit_run("ai-foundation", "120-minime-x-1", orch_dir=orch.dir, config_path=orch.config,
                                      env={admission.CLAIM_ENV: str(claim)})
        assert ok is False and "ai-foundation 121-other-1" in why

    def test_the_daemon_names_its_claim_to_the_route_and_releases_it(self, daemon, orch, monkeypatch):
        daemon.brief("120-minime-x-1", "ai-foundation")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        claim = admission.claim_path(orch.dir)
        assert f"{admission.CLAIM_ENV}={claim} python3 -u orchestrator.py run" in daemon.cmds[0]
        assert not claim.exists(), "released when the route returned"

    def test_routes_cli(self, orch, live_pid):
        orch.lock("clinical-mp", "110-visit-release-safety-1", live_pid)
        run = lambda *a: subprocess.run([sys.executable, str(ROOT / "admission.py"), "--orch-dir", str(orch.dir), *a],
                                        capture_output=True, text=True)
        assert run("routes", "--repo", "ai-foundation").returncode == 0
        r = run("routes")
        assert r.returncode == 1 and "clinical-mp 110-visit-release-safety-1" in r.stdout


# ═══════════════════════════════════════════════════════
# P4 · C2 — the ai-foundation route path and gate command
# ═══════════════════════════════════════════════════════
def _set_repo(monkeypatch, cfg: dict, tmp_path: Path, name: str):
    for g in REPO_GLOBALS:
        monkeypatch.setattr(orchestrator, g, getattr(orchestrator, g))
    p = tmp_path / "repos.yaml"
    p.write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(orchestrator, "REPOS_CONFIG_PATH", p)
    orchestrator.set_active_repo(name)


AIF_GITIGNORE = "venv/\n__pycache__/\n*.pyc\n"   # ai-foundation's .gitignore, lines 1-3


def _fixture_repo(path: Path, gitignore: str) -> Path:
    """A repo with a trivial pytest suite, and the main checkout's gitignored venv/."""
    (path / "tests").mkdir(parents=True)
    (path / "tests" / "test_trivial.py").write_text("def test_one():\n    assert 1 + 1 == 2\n")
    (path / ".gitignore").write_text(gitignore)
    _git("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm init", path)
    return path


def _fake_venv(at: Path) -> Path:
    """<at>/venv/bin/activate putting a `pytest` that is this interpreter's on PATH — a venv's shape."""
    b = at / "venv" / "bin"
    b.mkdir(parents=True)
    (b / "pytest").write_text(f"#!/bin/sh\nexec {sys.executable} -m pytest -p no:cacheprovider \"$@\"\n")
    (b / "pytest").chmod(0o755)
    (b / "activate").write_text(f'VIRTUAL_ENV="{at / "venv"}"\nexport VIRTUAL_ENV\nPATH="{b}:$PATH"\nexport PATH\n')
    return at / "venv"


class TestP4AifWorktree:

    def test_R_the_staged_block_resolves_to_aif_toni(self, tmp_path, monkeypatch):
        cfg = json.loads(json.dumps(SHIPPED))
        cfg["repos"]["ai-foundation"]["worktree_mode"] = "parallel"     # the flip, in a copy
        _set_repo(monkeypatch, cfg, tmp_path, "ai-foundation")
        assert orchestrator.WORKTREE_MODE == "parallel"
        assert orchestrator.WORKTREE_BASE / "125-minime-console-1" == Path("/home/gkassa/aif-toni/125-minime-console-1")

    def test_the_shipped_mode_stays_single_stream_until_venv_is_ignored(self):
        """A tripwire, not a preference: see config/repos.yaml and the handback's Found and LEFT 1. Flip it only
        after ai-foundation's .gitignore ignores a `venv` symlink (TestP4VenvLinkHazard shows why)."""
        aif = SHIPPED["repos"]["ai-foundation"]
        assert aif["worktree_mode"] == "single-stream" and aif["worktree_base"] == "/home/gkassa/aif-toni"

    def test_the_gate_command_is_mains(self):
        """123c R1: a route never changes a repo's suite command (TestTheSuiteCommandIsNotNarrowed). The command
        stays main's, relative to the checkout the route runs in — single-stream, the checkout itself."""
        aif = SHIPPED["repos"]["ai-foundation"]
        assert aif["test_cmd"] == ". venv/bin/activate && PYTHONPATH=. pytest"
        assert aif["build_gate_cmd"] == ". venv/bin/activate && PYTHONPATH=. pytest -q"

    def test_the_gate_command_runs_green_in_the_checkout_it_runs_in(self, tmp_path, monkeypatch):
        """The shipped command verbatim, in a fixture checkout with its gitignored venv/, through the unit gate's
        own leg runner."""
        main = _fixture_repo(tmp_path / "main", AIF_GITIGNORE)
        _fake_venv(main)
        run = orchestrator._run_unit_suite(SHIPPED["repos"]["ai-foundation"]["test_cmd"], main,
                                           "orch-aif-120-minime-x-1")
        assert run.exit_code == 0 and run.error is None, run.output[-1500:]
        assert re.search(r"\b1 passed\b", run.output)
        assert _git("git status --porcelain", main) == "", "nothing created in the checkout"

    def test_negative_control_the_relative_command_fails_there(self, tmp_path):
        main = _fixture_repo(tmp_path / "main", AIF_GITIGNORE)
        _fake_venv(main)
        wt = tmp_path / "wt"
        _git(f"git worktree add -q --detach {wt} main", main)
        run = orchestrator._run_unit_suite(". venv/bin/activate && PYTHONPATH=. pytest", wt, "x")
        assert run.exit_code != 0 and "venv/bin/activate" in run.output

    @pytest.mark.skipif(not Path(SHIPPED["repos"]["ai-foundation"]["project_dir"], "venv/bin/activate").is_file(),
                        reason="the ai-foundation venv is not on this machine")
    def test_the_shipped_command_verbatim_with_the_real_venv(self, tmp_path, monkeypatch):
        """Reads the services' venv (never writes: no bytecode); the suite is the fixture's, in a temp checkout
        whose venv is a link to the real one."""
        monkeypatch.setenv("PYTHONDONTWRITEBYTECODE", "1")
        main = _fixture_repo(tmp_path / "main", AIF_GITIGNORE)
        (main / "venv").symlink_to(Path(SHIPPED["repos"]["ai-foundation"]["project_dir"], "venv"))
        run = orchestrator._run_unit_suite(SHIPPED["repos"]["ai-foundation"]["test_cmd"] + " -p no:cacheprovider",
                                           main, "x")
        assert run.exit_code == 0, run.output[-1500:]
        assert re.search(r"\b1 passed\b", run.output)


class TestP4VenvLinkHazard:
    """Why the flip is STOPPED: what orchestrator._create_route_worktree does to a repo whose .gitignore reads
    `venv/` (ai-foundation's line 1), against one that reads `venv`."""

    def _route_worktree(self, tmp_path, monkeypatch, gitignore: str) -> Path:
        main = _fixture_repo(tmp_path / "main", gitignore)
        (main / "venv" / "bin").mkdir(parents=True)
        (main / "venv" / "bin" / "python").write_text("")
        for g in REPO_GLOBALS:
            monkeypatch.setattr(orchestrator, g, getattr(orchestrator, g))
        for g, v in (("PROJECT_ROOT", main), ("WORKTREE_BASE", tmp_path / "aif-toni"), ("MERGE_TARGET", "main"),
                     ("ACTIVE_REPO_NAME", "ai-foundation")):
            monkeypatch.setattr(orchestrator, g, v)
        wt, why = orchestrator._create_route_worktree(Path("120-minime-x-1.md"))
        assert wt is not None, why
        return wt

    def test_venv_slash_leaves_the_link_for_git_add(self, tmp_path, monkeypatch):
        wt = self._route_worktree(tmp_path, monkeypatch, AIF_GITIGNORE)
        assert (wt / "venv").is_symlink()
        assert _git("git status --porcelain", wt) == "?? venv", "`git add -A` would commit the link"

    def test_venv_without_the_slash_ignores_it(self, tmp_path, monkeypatch):
        wt = self._route_worktree(tmp_path, monkeypatch, AIF_GITIGNORE.replace("venv/", "venv"))
        assert (wt / "venv").is_symlink() and _git("git status --porcelain", wt) == ""


# ═══════════════════════════════════════════════════════
# P5 · C3 — scripts/aif-deploy.sh
# ═══════════════════════════════════════════════════════
LISTEN_CONFIG = '''import os
from pathlib import Path


class ListenConfig:
    def __init__(self, data_root, user_id):
        self.data_root, self.user_id = data_root, user_id

    @classmethod
    def from_env(cls):
        return cls(Path(os.environ["MINIG_LISTEN_DATA_ROOT"]), os.environ.get("MINIG_LISTEN_USER_ID", "george"))
'''
LISTEN_STORE = 'RECORD_NAME = "sitting.json"\n\n\ndef derive_status(record):\n    return record["status"], []\n'


class Deploy:
    """A temp ai-foundation (its Listen package stubbed to the real one's two entry points) one commit behind
    origin/main, a temp orchestrator dir naming it, and a `systemctl` on PATH that only records."""

    def __init__(self, tmp_path: Path):
        self.aif = tmp_path / "aif"
        listen = self.aif / "src" / "minime" / "listen"
        listen.mkdir(parents=True)
        for d in (self.aif / "src", self.aif / "src" / "minime", listen):
            (d / "__init__.py").write_text("")
        (listen / "config.py").write_text(LISTEN_CONFIG)
        (listen / "store.py").write_text(LISTEN_STORE)
        (self.aif / "app.py").write_text("VERSION = 1\n")
        _git("git init -q -b main && git add -A && git -c user.email=t@t -c user.name=t commit -qm one", self.aif)
        self.head = _git("git rev-parse HEAD", self.aif)
        tree = _git("git write-tree", self.aif)
        self.target = _git(f"git -c user.email=t@t -c user.name=t commit-tree {tree} -p {self.head} -m two", self.aif)
        _git(f"git update-ref refs/remotes/origin/main {self.target}", self.aif)
        self.orch = tmp_path / "orch"
        (self.orch / "config").mkdir(parents=True)
        (self.orch / "state").mkdir()
        (self.orch / "config" / "repos.yaml").write_text(yaml.safe_dump({"repos": {"ai-foundation": {
            "project_dir": str(self.aif), "remote": "origin", "merge_target": "main"}}}))
        self.data = tmp_path / "listen-data"
        (self.data / "george").mkdir(parents=True)
        self.env_file = tmp_path / "minig-listen.env"
        self.env_file.write_text(f"# the worker's EnvironmentFile\nMINIG_LISTEN_DATA_ROOT={self.data}\n")
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        self.calls = tmp_path / "systemctl.calls"
        (self.bin / "systemctl").write_text(f'#!/bin/sh\necho "$@" >> {self.calls}\n')
        (self.bin / "systemctl").chmod(0o755)

    def sitting(self, sid: str, status: str):
        (self.data / "george" / sid).mkdir()
        (self.data / "george" / sid / "sitting.json").write_text(json.dumps({"status": status}))

    def run(self, *args):
        env = {**os.environ, "ORCH_DIR": str(self.orch), "AIF_PYTHON": sys.executable,
               "LISTEN_ENV_FILE": str(self.env_file), "PATH": f"{self.bin}:{os.environ['PATH']}"}
        env.pop("AIF_DIR", None)
        return subprocess.run(["bash", str(ROOT / "scripts" / "aif-deploy.sh"), *args], capture_output=True,
                              text=True, env=env, timeout=120)

    def snapshot(self):
        return (_git("git rev-parse HEAD", self.aif), _git("git status --porcelain --ignored", self.aif),
                self.calls.exists())


@pytest.fixture
def deploy(tmp_path):
    return Deploy(tmp_path)


class TestP5AifDeploy:

    def test_R_a_live_ai_foundation_route_refuses(self, deploy, live_pid):
        (deploy.orch / "state" / "running-ai-foundation.json").write_text(json.dumps(
            {"pid": live_pid, "batch_id": "125-minime-console-1", "repo": "ai-foundation"}))
        before = deploy.snapshot()
        for args in ((), ("--apply",)):
            r = deploy.run(*args)
            assert r.returncode == 2, r.stdout + r.stderr
            assert "an ai-foundation route is live: ai-foundation 125-minime-console-1" in r.stderr
        assert deploy.snapshot() == before

    def test_R_the_dry_run_prints_the_plan_and_changes_nothing(self, deploy):
        before = deploy.snapshot()
        r = deploy.run()
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"git -C {deploy.aif} merge --ff-only {deploy.target}" in r.stdout
        assert "systemctl --user restart minig-listen-worker.service" in r.stdout
        assert "dry-run: nothing changed" in r.stdout
        assert "NOTE: this checkout has main checked out" in r.stdout
        assert deploy.snapshot() == before and before[2] is False, "no git move, no systemctl call"

    def test_a_listen_sitting_in_progress_refuses(self, deploy):
        deploy.sitting("20261005-150302-3a4c6dc7ccf2", "recording")
        deploy.sitting("20261005-160000-000000000000", "ready")
        before = deploy.snapshot()
        r = deploy.run("--apply")
        assert r.returncode == 2
        assert "a Listen sitting is in progress: 20261005-150302-3a4c6dc7ccf2 recording" in r.stderr
        assert deploy.snapshot() == before

    def test_unreadable_sittings_refuse_never_guessed(self, deploy):
        (deploy.data / "george" / "x").mkdir()
        (deploy.data / "george" / "x" / "sitting.json").write_text("{half")
        r = deploy.run()
        assert r.returncode == 2 and "cannot read the Listen sittings" in r.stderr

    def test_tracked_changes_refuse(self, deploy):
        (deploy.aif / "app.py").write_text("VERSION = 'local edit'\n")
        r = deploy.run("--apply")
        assert r.returncode == 2 and "tracked changes" in r.stderr
        assert (deploy.aif / "app.py").read_text() == "VERSION = 'local edit'\n"

    def test_apply_fast_forwards_and_restarts_the_worker_only(self, deploy):
        r = deploy.run("--apply")
        assert r.returncode == 0, r.stdout + r.stderr
        assert _git("git rev-parse HEAD", deploy.aif) == deploy.target
        assert deploy.calls.read_text().splitlines() == ["--user restart minig-listen-worker.service"]

    def test_not_a_fast_forward_refuses(self, deploy):
        _git("git -c user.email=t@t -c user.name=t commit -q --allow-empty -m local", deploy.aif)
        r = deploy.run()
        assert r.returncode == 2 and "is not a fast-forward" in r.stderr


# ═══════════════════════════════════════════════════════
# P7 · C4 — the daemon's wall for one route
# ═══════════════════════════════════════════════════════
CLINICAL = {"repos": {"clinical-mp": {"project_dir": "/x", "test_cmd": "npm test", "test_timeout_s": 1800}}}


@pytest.fixture
def clinical_cfg(tmp_path):
    p = tmp_path / "repos.yaml"
    p.write_text(yaml.safe_dump(CLINICAL))
    return p


def _brief(tmp_path: Path, header: str, name="122-organ-fat-1.md") -> Path:
    p = tmp_path / name
    p.write_text(f"#!queue repo=clinical-mp\n\n# 122\n{header}\n")
    return p


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeRoute:
    """A route on the fake clock: writes `script` lines into its log as their minute comes, exits 0 at `end`
    (minutes; None = never)."""

    def __init__(self, clock, log_path, script, end):
        self.clock, self.log, self.script, self.end = clock, Path(log_path), list(script), end
        self.killed, self.waits = False, []
        self.pid = 4242

    def wait(self, timeout=None):
        if timeout is None:
            return -9 if self.killed else 0
        self.waits.append((self.clock.t, timeout))
        self.clock.t += timeout
        while self.script and self.script[0][0] * 60 <= self.clock.t:
            with open(self.log, "a") as f:
                f.write(self.script.pop(0)[1] + "\n")
        if self.end is not None and self.clock.t >= self.end * 60:
            return 0
        raise subprocess.TimeoutExpired("route", timeout)

    def kill(self):
        self.killed = True

    def poll(self):
        return None


ROUTE_122 = [(0, "18:17:36 [INFO   ] Firing Toni: 122-organ-fat-1.md"),
             (159, "20:56:34 [INFO   ] Toni finished: exit 0"),
             (159, "20:56:34 [INFO   ] 🔧 Running build gate [clinical-mp]: npx tsc --noEmit && npm run build"),
             (167, "21:04:34 [INFO   ] 🧪 Running SIT post-merge: npm run sit:gate — 47 files / 137 tests"),
             (178, "21:15:33 [INFO   ] 🧪 Unit baseline gate [clinical-mp]: npm test — branch orch-mp-122")]


class TestP7RouteWall:

    def test_R_a_162_minute_route_gets_its_timeout_plus_its_gate_budget(self, tmp_path, clinical_cfg, monkeypatch):
        monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
        w = admission.route_wall(_brief(tmp_path, "## TONI_TIMEOUT_MIN: 162"), "clinical-mp", config_path=clinical_cfg)
        assert (w.route_timeout_s, w.route_timeout_source) == (162 * 60, "brief-declared")
        assert w.gate_budget_s == 600 + 600 + 1800 + 1800 + 300, w.gate_budget_source
        assert w.seconds >= 162 * 60 + w.gate_budget_s
        assert w.seconds > 11400, "above the fixed 190 min that killed route 122"

    def test_the_gate_budget_can_be_set_in_config(self, tmp_path, monkeypatch):
        p = tmp_path / "repos.yaml"
        p.write_text(yaml.safe_dump({**CLINICAL, "admission": {"gate_budget_s": {"clinical-mp": 7200}}}))
        assert admission.gate_budget("clinical-mp", p) == (7200, "admission.gate_budget_s")
        assert admission.gate_budget("yorsie", p)[1].startswith("the sum of its gate timeouts")

    def test_the_shipped_repos_budgets(self):
        cfg = ROOT / "config" / "repos.yaml"
        assert admission.gate_budget("clinical-mp", cfg)[0] == 600 + 600 + 1800 + 1800 + 300
        assert admission.gate_budget("orchestrator", cfg)[0] == 600 + 900 + 1800 + 300
        assert admission.gate_budget("ai-foundation", cfg)[0] == 900 + 1800 + 300

    @pytest.mark.parametrize("header,env", [
        ("## TONI_TIMEOUT_MIN: 162", {}), ("## Fire mechanism: queue TONI_TIMEOUT_MIN=75", {}),
        ("## Estimated runtime: 60-100 min", {}), ("## Estimated runtime: 40 min", {}), ("", {}),
        ("## TONI_TIMEOUT_MIN: 400", {}), ("## TONI_TIMEOUT_MIN: 162", {"TONI_TIMEOUT_MIN": "30"})])
    def test_the_route_timeout_is_orchestrators_own(self, tmp_path, monkeypatch, header, env):
        monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
        b = _brief(tmp_path, header)
        assert admission.route_timeout(b) == orchestrator.resolve_timeout(b)

    def test_the_restated_clocks_are_orchestrators(self):
        o = orchestrator
        assert admission.GATE_TIMEOUTS == {"build": o.BUILD_GATE_TIMEOUT, "sit": o.SIT_TIMEOUT,
                                           "unit": o.UNIT_GATE_TIMEOUT, "unit-baseline": o.UNIT_BASELINE_TIMEOUT,
                                           "unit-confirm": o.UNIT_CONFIRM_TIMEOUT}
        assert admission.UNIT_TIMEOUT_KEYS == {"unit": o.UNIT_TIMEOUT_KEY, "unit-baseline": o.UNIT_BASELINE_TIMEOUT_KEY,
                                               "unit-confirm": o.UNIT_CONFIRM_TIMEOUT_KEY}
        assert admission.PRE_MERGE_GATE_SETS == {k: tuple(v["gates"]) for k, v in o.PRE_MERGE_GATES.items()}
        assert (admission.TIMEOUT_DEFAULT_MIN, admission.TIMEOUT_HARD_CAP_MIN) == (o.TIMEOUT_DEFAULT_MIN,
                                                                                   o.TIMEOUT_HARD_CAP_MIN)

    def _route(self, tmp_path, monkeypatch, clinical_cfg, end):
        o = Orch(tmp_path, monkeypatch)
        d = Daemon(tmp_path, monkeypatch, o).d
        monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
        wall = admission.route_wall(_brief(tmp_path, "## TONI_TIMEOUT_MIN: 162"), "clinical-mp",
                                    config_path=clinical_cfg)
        d.current_batch = {"file": "122-organ-fat-1.md", "wall": wall.as_dict()}
        clock, log = FakeClock(), tmp_path / "orch-122.log"
        made = []

        def _popen(*a, **k):
            made.append(FakeRoute(clock, log, ROUTE_122, end))
            return made[0]
        monkeypatch.setattr(queue_daemon, "subprocess", types.SimpleNamespace(
            Popen=_popen, STDOUT=subprocess.STDOUT, TimeoutExpired=subprocess.TimeoutExpired))
        monkeypatch.setattr(queue_daemon, "ROUTE_CLOCK", clock)
        monkeypatch.setattr(queue_daemon, "ROUTE_POLL_S", 60)
        code = queue_daemon.QueueDaemon._run_route(d, "cmd", "122-organ-fat-1.md", log)   # the real one
        return code, made[0], clock, wall, log

    def test_R_a_gate_running_at_the_old_190_minute_mark_is_not_killed(self, tmp_path, monkeypatch,
                                                                         clinical_cfg, capsys):
        code, route, clock, wall, log = self._route(tmp_path, monkeypatch, clinical_cfg, end=215)
        assert any(t <= 11400 < t + dt for t, dt in route.waits), "the route was being waited on at 190 min"
        assert queue_daemon.route_phase(log) == "unit"
        assert code == 0 and route.killed is False and clock.t == 215 * 60
        assert "ROUTE WALL" not in capsys.readouterr().out

    def test_negative_control_a_route_over_its_whole_wall_is_killed_naming_the_clock_and_phase(
            self, tmp_path, monkeypatch, clinical_cfg, capsys):
        code, route, clock, wall, log = self._route(tmp_path, monkeypatch, clinical_cfg, end=None)
        assert code == -1 and route.killed is True and clock.t == wall.seconds
        out = capsys.readouterr().out
        said = (f"[QUEUE] ⏱ ROUTE WALL — the daemon's route wall fired on 122-organ-fat-1.md after {wall.seconds}s, "
                f"in phase unit; the wall: {wall.describe()}.")
        assert said in out
        text = log.read_text()
        assert said in text and re.search(rf"^Exit: -1 \(timeout after {wall.seconds}s\)$", text, re.M)

    def test_R_the_daemon_derives_the_wall_from_the_brief_it_fires(self, daemon, orch, monkeypatch, capsys):
        orch.cfg["repos"]["clinical-mp"]["test_timeout_s"] = 1800
        orch.write_config()
        monkeypatch.delenv("TONI_TIMEOUT_MIN", raising=False)
        daemon.brief("122-organ-fat-1", "clinical-mp", "## TONI_TIMEOUT_MIN: 162\n")
        daemon.stop_on_sleep(monkeypatch)
        daemon.d.run_loop()
        assert daemon.fired == ["122-organ-fat-1.md"]
        w = daemon.walls[0]
        assert w["seconds"] == 162 * 60 + 5100 + admission.ROUTE_WALL_SLACK_S and w["route_timeout_source"] == "brief-declared"
        assert f"[QUEUE] ⏱ route wall {w['describe']}" in capsys.readouterr().out

    def test_a_persisted_timeout_seconds_is_reported_and_not_applied(self, tmp_path, monkeypatch, orch, capsys):
        (tmp_path / "queue-state.json").write_text(json.dumps({"config": {"timeout_seconds": 11400}}))
        dm = Daemon(tmp_path, monkeypatch, orch)
        assert "timeout_seconds" not in dm.d.config
        dm.stop_on_sleep(monkeypatch)
        dm.d.run_loop()
        out = capsys.readouterr().out
        assert "route-wall: per route" in out and "persisted timeout_seconds=11400 not applied" in out
        assert "timeout_seconds" not in dm.state()["config"]

    @pytest.mark.parametrize("line,phase", [
        ("", "before Toni (pre-fire, branch, worktree)"), ("Firing Toni: x.md", "Toni"),
        ("🔧 Running build gate [clinical-mp]: npx tsc", "build"), ("🧪 SIT batch 2/5: PASS", "SIT"),
        ("🧬 Unit baseline: cache MISS for 263e579", "unit"), ("✅ Pre-merge gate on b: PASS — build green", "merge")])
    def test_the_phase_is_read_off_the_route_log(self, tmp_path, line, phase):
        log = tmp_path / "orch.log"
        log.write_text(f"=== QUEUE ROUTE ===\n{line}\n")
        assert queue_daemon.route_phase(log) == phase

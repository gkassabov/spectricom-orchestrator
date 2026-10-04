# filename: tests/test_executor_default.py
"""Tests for EXECUTOR-DEFAULT-1: one default executor, from one place.

S7-CORE-16 · D-S7CORE15-01. The pipeline's default executor is claude-opus-5-5 / high. Before this,
three places named a default: orchestrator.py's TONI_MODEL and argparse help, the queue daemon's
config, and queue-state.json. The daemon's persisted `config.model` = claude-fable-5-1 outranked
both env and code on every restart (LESSONS S7-CORE-14 L-8). Now canon_assert holds
DEFAULT_EXECUTOR_MODEL / _EFFORT, and every reader derives from them. A persisted value that
differs is reported at daemon start and not applied. A brief's `#!queue model=… effort=…` header
still wins over everything.

  AC-ED-01  exactly one literal default model string outside tests          (TestOneLiteral)
  AC-ED-02  direct path (no --model) and daemon (no header) → opus-5-5 high  (TestResolves)
  AC-ED-03  the persisted-mismatch line, and the persisted value unused      (TestPersisted)
  AC-ED-04  handback-scan prints no `Executor:` banner                       (TestBanner)

The direct path and the CLI run as real subprocesses against a COPY of the repo, with HOME pointed
at the copy's parent. Every path they resolve, file-relative or home-relative, is inside tmp_path.
The daemon runs in-process with every path patched under tmp_path and `_run_route` stubbed; no
route ever fires. No test reads or writes the live queue-state.json, queue/ or logs/.
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import queue_daemon

ROOT = Path(__file__).parent.parent
OPUS_55, FABLE = "claude-opus-5-5", "claude-fable-5-1"
ENV_VARS = ("TONI_MODEL", "TONI_EFFORT")
MODEL_ID_RE = re.compile(r"claude-(?:opus|sonnet|haiku|fable)-\d[\w.-]*")
# The v1 direct-API agents. Nothing in the pipeline imports them, so they are not its executor, and
# CLAUDE.md pins them ("do not change either without owner instruction"). They are listed here so
# that they cannot grow unseen.
LEGACY_PINS = [("agents/gemma.py", "claude-sonnet-4-20250514"),
               ("agents/toni.py", "claude-sonnet-4-20250514"),
               ("loop/executor.py", "claude-sonnet-4-20250514"),
               ("loop/executor.py", "claude-sonnet-4-20250514")]
LEGACY_FILES = {f for f, _ in LEGACY_PINS}


def _stripped_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ENV_VARS}
    env.update(extra)
    return env


# ═══════════════════════════════════════════════════════
# AC-ED-01 · one literal default, outside tests
# ═══════════════════════════════════════════════════════
def _sources() -> dict:
    """Every .py outside tests/ that git tracks or would track: tracked plus untracked-not-ignored,
    so a new file counts before it is added and an ignored venv/ never does."""
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-co", "--exclude-standard", "*.py"],
                         capture_output=True, text=True, check=True).stdout.split()
    return {f: (ROOT / f).read_text() for f in sorted(set(out))
            if not f.startswith("tests/") and (ROOT / f).is_file()}


def _model_literals(sources: dict) -> list:
    """(file, literal) for every model id inside a Python string literal (f-string parts too).
    Comments are not literals."""
    found = []
    for f, src in sources.items():
        for n in ast.walk(ast.parse(src)):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                found.extend((f, m) for m in MODEL_ID_RE.findall(n.value))
    return sorted(found)


def _default_violations(sources: dict) -> list:
    found = _model_literals(sources)
    pipeline = [x for x in found if x[0] not in LEGACY_FILES]
    legacy = [x for x in found if x[0] in LEGACY_FILES]
    out = []
    if pipeline != [("canon_assert.py", OPUS_55)]:
        out.append(f"pipeline model literals {pipeline} != the one default [('canon_assert.py', {OPUS_55!r})]")
    if legacy != sorted(LEGACY_PINS):
        out.append(f"legacy pins {legacy} != {sorted(LEGACY_PINS)}")
    return out


class TestOneLiteral:

    def test_exactly_one_literal_default_model_string_outside_tests(self):
        assert _default_violations(_sources()) == []

    def test_the_one_literal_is_the_constant(self):
        import canon_assert
        assert (canon_assert.DEFAULT_EXECUTOR_MODEL, canon_assert.DEFAULT_EXECUTOR_EFFORT) == (OPUS_55, "high")
        tree = ast.parse((ROOT / "canon_assert.py").read_text())
        owners = [t.id for n in ast.walk(tree) if isinstance(n, ast.Assign)
                  and isinstance(n.value, ast.Constant) and n.value.value == OPUS_55
                  for t in n.targets if isinstance(t, ast.Name)]
        assert owners == ["DEFAULT_EXECUTOR_MODEL"]

    def test_no_model_id_in_config_or_scripts(self):
        files = sorted(ROOT.glob("config/*")) + sorted(ROOT.glob("*.sh"))
        assert files, "nothing scanned"
        hits = [(f.name, m) for f in files if f.is_file() for m in MODEL_ID_RE.findall(f.read_text())]
        assert hits == []

    @pytest.mark.parametrize("file,snippet", [
        ("queue_daemon.py", '\nX = {"model": "claude-fable-5-1"}\n'),
        ("orchestrator.py", '\nHELP = f"default {1} claude-opus-5"\n'),
        ("agents/toni.py", '\nTONI_EFFORT_MODEL = "claude-sonnet-4-20250514"\n'),
    ], ids=["daemon-default", "help-string", "legacy-grows"])
    def test_the_guard_turns_red(self, file, snippet):
        sources = _sources()
        sources[file] += snippet
        assert _default_violations(sources)


# ═══════════════════════════════════════════════════════
# the harnesses — a repo copy for the CLI, a patched daemon in-process
# ═══════════════════════════════════════════════════════
@pytest.fixture
def copy(tmp_path):
    """The repo's tracked top level plus config/, as $HOME/spectricom-orchestrator under tmp_path."""
    dst = tmp_path / "home" / "spectricom-orchestrator"
    dst.mkdir(parents=True)
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True,
                             check=True).stdout.split()
    for f in tracked:
        if "/" not in f and f.endswith((".py", ".json")) or f.startswith("config/"):
            (dst / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / f, dst / f)

    def run(*args, **env):
        return subprocess.run([sys.executable, *args], cwd=dst, capture_output=True, text=True, timeout=120,
                              env=_stripped_env(HOME=str(dst.parent), **env))
    run.dir = dst
    return run


class Daemon:
    """One QueueDaemon under tmp_path, built with TONI_MODEL / TONI_EFFORT absent unless given."""

    def __init__(self, tmp_path, monkeypatch, persisted=None, **env):
        for k in ENV_VARS:
            monkeypatch.delenv(k, raising=False)
        for k, v in env.items():
            monkeypatch.setenv(k, v)
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
        if persisted is not None:
            self.state_file.write_text(json.dumps(persisted))
        self.d = queue_daemon.QueueDaemon()
        self.d.config.update(repo="r", cooldown_seconds=0)
        self.cmds = []

        def _route(cmd, batch_name, log_path):
            self.cmds.append(cmd)
            Path(log_path).write_text("route output\n")
            return 0
        self.d._run_route = _route

        def _sleep(s):   # the first idle poll ends the loop: one pass over the queue
            self.d.status = "stopped"
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep))

    def brief(self, stem, header="#!queue repo=r"):
        self.queue.mkdir(parents=True, exist_ok=True)
        (self.queue / f"{stem}.md").write_text(f"{header}\n\n# {stem}\n")

    def fire(self) -> str:
        self.d.run_loop()
        assert len(self.cmds) == 1, self.cmds
        return self.cmds[0]

    def state(self) -> dict:
        return json.loads(self.state_file.read_text())


def _exec(cmd: str) -> tuple:
    m = re.search(r"--model (\S+) --effort (\S+)", cmd)
    assert m, cmd
    return m.groups()


def _shield(out: str) -> list:
    return [l for l in out.splitlines() if l.startswith("🛡 executor-default:")]


# ═══════════════════════════════════════════════════════
# AC-ED-02 · both paths resolve claude-opus-5-5 high
# ═══════════════════════════════════════════════════════
class TestResolves:

    def test_the_resolver(self):
        from canon_assert import executor_default
        assert executor_default({}) == (OPUS_55, "high")
        assert executor_default({"TONI_MODEL": "", "TONI_EFFORT": ""}) == (OPUS_55, "high"), "empty is unset"
        assert executor_default({"TONI_MODEL": "m", "TONI_EFFORT": "e"}) == ("m", "e")

    def test_direct_path_no_model_no_env(self, copy):
        r = copy("-c", "import orchestrator as o; print('RESOLVED', o.TONI_MODEL, o.TONI_EFFORT)")
        assert r.returncode == 0, r.stderr[-2000:]
        assert f"RESOLVED {OPUS_55} high" in r.stdout.splitlines()

    def test_direct_path_run_banner_says_opus_5_5(self, copy):
        # [ORCH-YORSIE-SAFETY-1] a run names its repo; one that names none is refused before the banner
        r = copy("orchestrator.py", "run", "no-such-brief.md", "--repo", "orchestrator")
        assert f"Executor: model={OPUS_55} effort=high" in r.stderr, r.stderr[-2000:]

    def test_direct_path_env_and_flag_still_override(self, copy):
        r = copy("orchestrator.py", "run", "no-such-brief.md", "--repo", "orchestrator", "--model", "claude-x",
                 TONI_EFFORT="max")
        assert "Executor: model=claude-x effort=max" in r.stderr, r.stderr[-2000:]

    def test_daemon_no_executor_header_no_env_no_state(self, tmp_path, monkeypatch, capsys):
        # [ORCH-YORSIE-SAFETY-1] a brief with no `#!queue` line at all is refused unfired now
        # (tests/test_yorsie_safety.py Q1); the least a brief carries is its repo.
        dm = Daemon(tmp_path, monkeypatch)
        dm.brief("71-no-header", header="#!queue repo=r")
        assert _exec(dm.fire()) == (OPUS_55, "high")
        assert _shield(capsys.readouterr().out) == [f"🛡 executor-default: using {OPUS_55} effort=high (the default)"]

    def test_daemon_header_without_model_uses_the_default(self, tmp_path, monkeypatch):
        dm = Daemon(tmp_path, monkeypatch)
        dm.brief("71-repo-only")
        assert _exec(dm.fire()) == (OPUS_55, "high")

    def test_a_brief_header_still_overrides_both(self, tmp_path, monkeypatch):
        dm = Daemon(tmp_path, monkeypatch, persisted={"config": {"model": FABLE, "effort": "high"}},
                    TONI_MODEL="claude-opus-5")
        dm.brief("71-headed", header="#!queue model=claude-sonnet-4-5 effort=low repo=r")
        assert _exec(dm.fire()) == ("claude-sonnet-4-5", "low")


# ═══════════════════════════════════════════════════════
# AC-ED-03 · a persisted value that differs is reported, not applied
# ═══════════════════════════════════════════════════════
LIVE_STATE = {"config": {"max_consecutive": 10, "cooldown_seconds": 30, "stop_on_failure": True,
                         "repo": "clinical-mp", "model": FABLE, "effort": "high", "timeout_seconds": 11400}}


class TestPersisted:

    def test_live_shape_mismatch_is_reported_and_the_default_fires(self, tmp_path, monkeypatch, capsys):
        dm = Daemon(tmp_path, monkeypatch, persisted=LIVE_STATE)
        dm.brief("71-next")
        assert _exec(dm.fire()) == (OPUS_55, "high")
        assert _shield(capsys.readouterr().out) == [
            f"🛡 executor-default: persisted {FABLE} ≠ default {OPUS_55} — using {OPUS_55} effort=high "
            f"(the default); the persisted value is not applied (no command sets it — it records what an "
            f"earlier daemon ran with, L-8)"]

    def test_every_other_persisted_key_still_applies(self, tmp_path, monkeypatch):
        dm = Daemon(tmp_path, monkeypatch, persisted=LIVE_STATE)
        assert (dm.d.config["max_consecutive"], dm.d.config["timeout_seconds"]) == (10, 11400)
        assert (dm.d.config["model"], dm.d.config["effort"]) == (OPUS_55, "high")

    def test_the_stale_value_leaves_the_file_at_the_first_save(self, tmp_path, monkeypatch):
        dm = Daemon(tmp_path, monkeypatch, persisted=LIVE_STATE)
        dm.brief("71-next")
        dm.fire()
        assert (dm.state()["config"]["model"], dm.state()["config"]["effort"]) == (OPUS_55, "high")

    def test_an_effort_mismatch_is_named_too(self, tmp_path, monkeypatch, capsys):
        dm = Daemon(tmp_path, monkeypatch, persisted={"config": {"model": FABLE, "effort": "low"}})
        dm.brief("71-next")
        dm.fire()
        line, = _shield(capsys.readouterr().out)
        assert line.startswith(f"🛡 executor-default: persisted {FABLE} effort=low ≠ default {OPUS_55} effort=high — ")

    def test_env_at_start_is_used_and_named(self, tmp_path, monkeypatch, capsys):
        """The start script's TONI_MODEL=claude-opus-5 wins over the default, and the line says so."""
        dm = Daemon(tmp_path, monkeypatch, persisted=LIVE_STATE, TONI_MODEL="claude-opus-5", TONI_EFFORT="high")
        dm.brief("71-next")
        assert _exec(dm.fire()) == ("claude-opus-5", "high")
        line, = _shield(capsys.readouterr().out)
        assert line.startswith(f"🛡 executor-default: persisted {FABLE} ≠ default {OPUS_55} — using claude-opus-5 "
                               f"effort=high (TONI_MODEL=claude-opus-5, TONI_EFFORT=high set at daemon start)")

    def test_status_shows_the_daemons_executor_not_the_cli_processs(self, tmp_path, monkeypatch, capsys):
        dm = Daemon(tmp_path, monkeypatch, TONI_MODEL="claude-opus-5")
        dm.brief("71-next")
        dm.fire()
        monkeypatch.delenv("TONI_MODEL")            # the operator's shell, not the daemon's
        later = tmp_path / "72-later.md"
        later.write_text("#!queue repo=r\n\n# later\n")
        queue_daemon.main(["enqueue", str(later)])  # a CLI process saves the state in between
        assert "72-later.md" in dm.state()["queue"]
        capsys.readouterr()
        queue_daemon.main(["status"])
        shown = json.loads(capsys.readouterr().out.split("\n", 1)[1])
        assert shown["config"]["model"] == "claude-opus-5"
        assert dm.state()["config"]["model"] == "claude-opus-5"


# ═══════════════════════════════════════════════════════
# AC-ED-04 · a read-only command names no executor
# ═══════════════════════════════════════════════════════
class TestBanner:

    @pytest.mark.parametrize("env", [{}, {"TONI_MODEL": FABLE}], ids=["no-env", "fable-in-env"])
    def test_handback_scan_prints_no_executor_banner(self, copy, tmp_path, env):
        empty = tmp_path / "no-logs"
        empty.mkdir()
        r = copy("orchestrator.py", "handback-scan", str(empty), **env)
        assert r.returncode == 0, r.stdout + r.stderr
        assert "0 logs scanned" in r.stdout
        out = r.stdout + r.stderr
        assert f"Executor: model={FABLE}" not in out
        assert "Executor:" not in out

    def test_only_the_executor_commands_name_one(self):
        import orchestrator
        assert orchestrator.EXECUTOR_CMDS == ("run", "queue", "parallel", "watch")

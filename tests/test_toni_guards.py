"""ORCH-TONI-GUARDS-1 (S7-CORE-33, SCP_Kanban row 394) — what ships without a Bash sandbox (330b STOP (b), R3).

  P1  fire_toni: `--settings <ORCH_DIR>/executor/settings/<repo>.json` and the scrubbed env; a missing or
      unusable settings file refuses the fire; TONI_GUARDS=off is HEAD's fire byte-for-byte
  P2  each executor/settings/<repo>.json — one per repo in config/repos.yaml — parses and holds every §1 deny
      entry; orchestrator.json allows its own queue/ and logs/ reads; CLAUDE.md is not denied
  P3  executor/hooks/kill_switch.sh: deny with KILL, allow without, deny when the state cannot be read
  P4  queue_daemon: no fire while KILL exists; `kill` ends the fire's process groups; `unkill` needs --reason

P5, the live canary, is in briefs/330d-orch-toni-guards-1.handback.md. Nothing here starts a real `claude`.
"""

import json
import os
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import orchestrator  # noqa: E402
import queue_daemon  # noqa: E402

pytestmark = pytest.mark.guards   # conftest: every other test fires with TONI_GUARDS=off

SETTINGS = ROOT / "executor" / "settings"
HOOK = ROOT / "executor" / "hooks" / "kill_switch.sh"
REPOS = sorted(yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"])

# §1, as the brief lists it. `/mnt/c/**` is written `//mnt/c/**`: in a --settings file a rule starting with ONE
# slash is relative to the settings file's own directory (2.1.283: flagSettings root = dirname(--settings path)).
CREDENTIAL_PATHS = ["~/.ssh/**", "~/.aws/**", "~/.config/gcloud/**", "~/.config/gh/**", "~/.git-credentials",
                    "~/.npmrc", "~/.docker/config.json", "~/.claude/**", "//mnt/c/**"]
CONTROL_PATHS = ["**/.claude/**", "**/.mcp.json", "**/.github/workflows/**", "**/.husky/**", "**/.vscode/tasks.json"]
DENY = ([f"{tool}({p})" for p in CREDENTIAL_PATHS for tool in ("Read", "Edit")]
        + [f"Edit({p})" for p in CONTROL_PATHS]          # relative: under the route's working dir
        + [f"Edit(//{p})" for p in CONTROL_PATHS])       # the same rule anchored at /: anywhere on disk
ORCH_ALLOW = ["Read(~/spectricom-orchestrator/queue/**)", "Read(~/spectricom-orchestrator/logs/**)"]

DROPPED = ["SSH_AUTH_SOCK", "GH_TOKEN", "GITHUB_TOKEN", "GROQ_API_KEY", "AWS_ACCESS_KEY_ID", "AWS_PROFILE",
           "GOOGLE_APPLICATION_CREDENTIALS", "TONI_GUARDS_HOME"]
PROMPT_TAIL = (" and execute all briefs in order. Run every command in the foreground and wait for it to finish; "
               "never use run_in_background — background tasks are killed when your turn ends and no follow-up "
               "turn will come.")
# [ORCH-RELIABILITY-1] rule #8 (George 2026-10-28 11:13): the preflight sentence F1.2 appends to the prompt
PREFLIGHT = (" Before you write the handback's final status, run `python3 ~/spectricom-orchestrator/orchestrator.py "
             "preflight --repo {repo}` and paste its summary; a red there is handled by your brief's rule #8 and STOP "
             "rules like any other red.")


def head_cmd(project, brief_rel, model, effort, repo="clinical-mp") -> str:
    """fire_toni's command at 886014c (HEAD before this route), character for character, plus the preflight
    sentence (backticks escaped inside the double-quoted prompt)."""
    ask = PREFLIGHT.format(repo=repo).replace("`", "\\`")
    return (f"cd {project} && stdbuf -oL claude --dangerously-skip-permissions --model {model} --effort {effort} "
            f'"Read {brief_rel}{PROMPT_TAIL}{ask}"')


def _settings(repo: str) -> dict:
    return json.loads((SETTINGS / f"{repo}.json").read_text())


def _hook_commands(cfg: dict) -> list:
    return [h.get("command", "") for m in (cfg.get("hooks") or {}).get("PreToolUse", [])
            for h in m.get("hooks", []) if m.get("matcher") in ("*", "")]


# ═══════════════════════════════════════════════════════
# P1 · the fire command and its environment
# ═══════════════════════════════════════════════════════
@pytest.fixture
def spy(tmp_path, monkeypatch):
    """The REAL fire_toni up to its Popen, which records (cmd, env) and spawns nothing."""
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(orchestrator, "ensure_log_subdir", lambda _s: logs)
    monkeypatch.setattr(orchestrator, "RUNNING_FILE", tmp_path / "running.json")
    monkeypatch.setattr(orchestrator, "TONI_TIMEOUT", 3600)
    monkeypatch.setattr(orchestrator, "TONI_MODEL", "claude-opus-5-5")
    monkeypatch.setattr(orchestrator, "TONI_EFFORT", "xhigh")
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "clinical-mp")
    monkeypatch.delenv("TONI_GUARDS", raising=False)
    calls = []

    class _Popen:
        def __init__(self, cmd, **kw):
            calls.append({"cmd": cmd, **kw})
            self.pid = 0

        def wait(self, timeout=None):
            return 0
    monkeypatch.setattr(orchestrator.subprocess, "Popen", _Popen)
    project = tmp_path / "proj"
    (project / "briefs").mkdir(parents=True)
    brief = project / "briefs" / "394-x.md"
    brief.write_text("# x\n")

    def fire():
        return orchestrator.fire_toni(brief, project)
    return types.SimpleNamespace(fire=fire, calls=calls, project=project, brief=brief)


def _secrets_in_env(monkeypatch):
    for k in [k for k in os.environ if k.startswith("AWS_")]:
        monkeypatch.delenv(k)
    for k in DROPPED:
        monkeypatch.setenv(k, f"fake-{k.lower()}")
    monkeypatch.setenv("KEEP_ME", "kept")
    monkeypatch.setenv("npm_config_ignore_scripts", "false")   # an inherited value never survives


def test_P1_the_fire_carries_the_repos_settings_file_and_the_scrubbed_env(spy, monkeypatch, caplog):
    import logging
    _secrets_in_env(monkeypatch)
    with caplog.at_level(logging.INFO, logger=orchestrator.log.name):
        ec, _ = spy.fire()
    assert ec == 0 and len(spy.calls) == 1
    settings = orchestrator.TONI_SETTINGS_DIR / "clinical-mp.json"
    assert settings.is_absolute() and settings == ROOT / "executor" / "settings" / "clinical-mp.json"
    want = head_cmd(spy.project, "briefs/394-x.md", "claude-opus-5-5", "xhigh").replace(
        "--dangerously-skip-permissions ", f"--dangerously-skip-permissions --settings {settings} ")
    assert spy.calls[0]["cmd"] == want
    env = spy.calls[0]["env"]
    base = orchestrator.toni_child_env(3600)
    assert env == {**{k: v for k, v in base.items() if k not in DROPPED}, "npm_config_ignore_scripts": "true"}
    assert env["KEEP_ME"] == "kept"
    line = next(r.getMessage() for r in caplog.records if "🛡 guards:" in r.getMessage())
    sha = orchestrator.hashlib.sha256(settings.read_bytes()).hexdigest()[:12]
    deny = len(_settings("clinical-mp")["permissions"]["deny"])
    assert line == (f"🛡 guards: ON (settings clinical-mp sha {sha}, deny {deny}, env dropped "
                    f"[{', '.join(sorted(DROPPED))}], npm_config_ignore_scripts=true)")
    assert not any(f"fake-{k.lower()}" in r.getMessage() for r in caplog.records for k in DROPPED), "names only"


def test_P1_nothing_to_drop_is_said_as_an_empty_list(spy, monkeypatch, caplog):
    import logging
    for k in [*DROPPED, *(k for k in os.environ if k.startswith("AWS_"))]:
        monkeypatch.delenv(k, raising=False)
    with caplog.at_level(logging.INFO, logger=orchestrator.log.name):
        spy.fire()
    assert any("env dropped [], npm_config_ignore_scripts=true)" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("value", ["off", "OFF", "Off", " off "])
def test_P1_TONI_GUARDS_off_is_heads_fire_byte_for_byte(spy, monkeypatch, caplog, value):
    import logging
    _secrets_in_env(monkeypatch)
    monkeypatch.setenv("TONI_GUARDS", value)
    with caplog.at_level(logging.INFO, logger=orchestrator.log.name):
        ec, log_path = spy.fire()
    assert ec == 0
    assert spy.calls[0]["cmd"] == head_cmd(spy.project, "briefs/394-x.md", "claude-opus-5-5", "xhigh")
    assert spy.calls[0]["env"] == orchestrator.toni_child_env(3600)
    assert spy.calls[0]["env"]["SSH_AUTH_SOCK"] == "fake-ssh_auth_sock"
    assert f"Command: {spy.calls[0]['cmd']}\n" in Path(log_path).read_text()
    said = [r.getMessage() for r in caplog.records if "🛡 guards:" in r.getMessage()]
    assert len(said) == 1 and said[0].startswith("🛡 guards: OFF (TONI_GUARDS=off)"), said


def test_P1_TONI_GUARDS_off_fires_even_with_no_settings_file(spy, monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, "TONI_SETTINGS_DIR", tmp_path / "none")
    monkeypatch.setenv("TONI_GUARDS", "off")
    ec, _ = spy.fire()
    assert ec == 0 and spy.calls[0]["cmd"] == head_cmd(spy.project, "briefs/394-x.md", "claude-opus-5-5", "xhigh")


@pytest.mark.parametrize("value", ["", "on", "0", "false", "no"])
def test_P1_anything_but_off_is_on(spy, monkeypatch, value):
    monkeypatch.setenv("TONI_GUARDS", value)
    spy.fire()
    assert " --settings " in spy.calls[0]["cmd"]


def _bad_settings(tmp_path, content) -> Path:
    d = tmp_path / "settings"
    d.mkdir(exist_ok=True)
    if content is not None:
        (d / "clinical-mp.json").write_text(content)
    return d


GOOD = json.dumps({"permissions": {"deny": ["Read(~/.ssh/**)"]}, "hooks": {"PreToolUse": [
    {"matcher": "*", "hooks": [{"type": "command", "command": "bash x/executor/hooks/kill_switch.sh || exit 2"}]}]}})


@pytest.mark.parametrize("content, why", [
    (None, "no settings file"),
    ("{not json", "not JSON"),
    ("[]", "not a JSON object"),
    (json.dumps({"hooks": json.loads(GOOD)["hooks"]}), "no permissions.deny"),
    (json.dumps({"permissions": {"deny": []}, "hooks": json.loads(GOOD)["hooks"]}), "no permissions.deny"),
    (json.dumps({"permissions": {"deny": ["Read(~/.ssh/**)"]}}), "no PreToolUse kill hook"),
])
def test_P1_a_missing_or_unusable_settings_file_refuses_the_fire(spy, monkeypatch, tmp_path, caplog, content, why):
    import logging
    monkeypatch.setattr(orchestrator, "TONI_SETTINGS_DIR", _bad_settings(tmp_path, content))
    with caplog.at_level(logging.INFO, logger=orchestrator.log.name):
        ec, _ = spy.fire()
    assert ec == -2 and spy.calls == [], "refused before any spawn"
    msgs = [r.getMessage() for r in caplog.records]
    blocked = [m for m in msgs if m.startswith("🛡 guards: BLOCKED — ")]
    assert len(blocked) == 1 and why in blocked[0], msgs
    assert str(tmp_path / "settings" / "clinical-mp.json") in blocked[0] and "TONI_GUARDS=off" in blocked[0]
    assert any(m.startswith("⛔ Toni NOT fired — guards: ") for m in msgs)


def test_P1_the_good_fixture_is_accepted_negative_control(spy, monkeypatch, tmp_path):
    monkeypatch.setattr(orchestrator, "TONI_SETTINGS_DIR", _bad_settings(tmp_path, GOOD))
    ec, _ = spy.fire()
    assert ec == 0 and f"--settings {tmp_path / 'settings' / 'clinical-mp.json'} " in spy.calls[0]["cmd"]


def test_P1_no_repo_named_refuses(spy, monkeypatch):
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "")
    ec, _ = spy.fire()
    assert ec == -2 and spy.calls == []


@pytest.mark.parametrize("repo", REPOS)
def test_P1_every_configured_repo_fires_with_its_own_file(spy, monkeypatch, repo):
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", repo)
    ec, _ = spy.fire()
    assert ec == 0 and f"--settings {ROOT / 'executor' / 'settings' / f'{repo}.json'} " in spy.calls[0]["cmd"]


def test_P1_end_to_end_the_child_gets_the_flag_and_not_the_socket(tmp_path, monkeypatch):
    """The real Popen, /bin/bash -c, cd and stdbuf, against a fake `claude` that reports its argv and env names."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    report = tmp_path / "report.json"
    fake = bin_dir / "claude"
    fake.write_text("#!/usr/bin/env python3\nimport json, os, sys\n"
                    f"json.dump({{'argv': sys.argv[1:], 'env': sorted(os.environ), "
                    f"'npm': os.environ.get('npm_config_ignore_scripts')}}, open({str(report)!r}, 'w'))\n")
    fake.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.delenv("TONI_GUARDS", raising=False)
    _secrets_in_env(monkeypatch)
    logs = tmp_path / "logs"
    logs.mkdir()
    monkeypatch.setattr(orchestrator, "ensure_log_subdir", lambda _s: logs)
    monkeypatch.setattr(orchestrator, "RUNNING_FILE", tmp_path / "running.json")
    monkeypatch.setattr(orchestrator, "TONI_TIMEOUT", 600)
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_NAME", "orchestrator")
    proj = tmp_path / "proj"
    (proj / "briefs").mkdir(parents=True)
    (proj / "briefs" / "394-x.md").write_text("# x\n")
    ec, _ = orchestrator.fire_toni(proj / "briefs" / "394-x.md", proj)
    got = json.loads(report.read_text())
    assert ec == 0
    i = got["argv"].index("--settings")
    assert got["argv"][i + 1] == str(ROOT / "executor" / "settings" / "orchestrator.json")
    assert got["argv"][0] == "--dangerously-skip-permissions" and got["argv"][-1] == ("Read briefs/394-x.md" + PROMPT_TAIL
                                                                               + PREFLIGHT.format(repo="orchestrator"))
    assert not set(DROPPED) & set(got["env"]) and "KEEP_ME" in got["env"]
    assert got["npm"] == "true"


# ═══════════════════════════════════════════════════════
# P2 · the settings files
# ═══════════════════════════════════════════════════════
def test_P2_one_settings_file_per_configured_repo_and_no_other():
    assert sorted(p.stem for p in SETTINGS.glob("*.json")) == REPOS


@pytest.mark.parametrize("repo", REPOS)
@pytest.mark.parametrize("rule", DENY)
def test_P2_every_section_1_deny_entry_is_in_every_file(repo, rule):
    assert rule in _settings(repo)["permissions"]["deny"]


@pytest.mark.parametrize("repo", REPOS)
def test_P2_the_file_is_what_the_cli_can_read(repo):
    """A settings file the CLI rejects is SILENTLY ignored in non-interactive mode (claude --help, -p): an unguarded
    fire. Only keys and rule shapes 2.1.283 documents; no rule in the settings-file-relative `/x` form."""
    cfg = _settings(repo)
    assert set(cfg) == {"permissions", "hooks"}
    assert set(cfg["permissions"]) <= {"deny", "allow"}
    import re
    for rule in cfg["permissions"]["deny"] + cfg["permissions"].get("allow", []):
        assert re.fullmatch(r"(Read|Edit)\((~/|//|\*\*/)[^()\s]+\)", rule), rule
    assert len(set(cfg["permissions"]["deny"])) == len(cfg["permissions"]["deny"]), "no duplicates"


@pytest.mark.parametrize("repo", REPOS)
def test_P2_claude_md_is_not_denied_and_there_is_no_bash_sandbox(repo):
    cfg = _settings(repo)
    assert not any("CLAUDE.md" in r for r in cfg["permissions"]["deny"]), "R5: CLAUDE.md is edited by routes"
    assert "sandbox" not in cfg, "R1: no Bash sandbox in this route (330b STOP)"


@pytest.mark.parametrize("repo", REPOS)
def test_P2_every_file_runs_the_kill_hook_on_every_tool(repo):
    cmds = _hook_commands(_settings(repo))
    assert cmds == ['bash "${TONI_GUARDS_HOME:-$HOME/spectricom-orchestrator}/executor/hooks/kill_switch.sh" || exit 2']


def test_P2_the_orchestrator_file_allows_its_queue_and_logs_reads():
    cfg = _settings("orchestrator")
    assert cfg["permissions"]["allow"] == ORCH_ALLOW
    for rule in ORCH_ALLOW:
        assert rule not in cfg["permissions"]["deny"]


@pytest.mark.parametrize("repo", [r for r in REPOS if r != "orchestrator"])
def test_P2_the_other_files_are_one_file(repo):
    """One deny list for every repo: the files differ only by the orchestrator's allow."""
    assert _settings(repo) == _settings("clinical-mp")
    assert "allow" not in _settings(repo)["permissions"]
    orch = _settings("orchestrator")
    assert {**orch, "permissions": {"deny": orch["permissions"]["deny"]}} == _settings(repo)


# ═══════════════════════════════════════════════════════
# P3 · the kill hook
# ═══════════════════════════════════════════════════════
def _run_hook(env: dict, script=None, stdin='{"tool_name":"Bash","tool_input":{"command":"ls"}}'):
    argv = ["bash", str(HOOK)] if script is None else ["bash", "-c", script]
    return subprocess.run(argv, env={"PATH": os.environ["PATH"], **env}, input=stdin, capture_output=True,
                          text=True, timeout=20)


@pytest.fixture
def home(tmp_path):
    """$HOME with spectricom-orchestrator/ and the real hook at its shipped path in it."""
    orch = tmp_path / "home" / "spectricom-orchestrator"
    (orch / "executor" / "hooks").mkdir(parents=True)
    (orch / "executor" / "hooks" / "kill_switch.sh").symlink_to(HOOK)
    return types.SimpleNamespace(home=tmp_path / "home", orch=orch, kill=orch / "KILL")


def test_P3_allow_without_KILL(home):
    r = _run_hook({"HOME": str(home.home)})
    assert r.returncode == 0 and r.stdout == "" and r.stderr == ""


def test_P3_deny_with_KILL(home):
    home.kill.write_text('{"reason": "test"}')
    r = _run_hook({"HOME": str(home.home)})
    assert r.returncode == 2
    assert str(home.kill) in r.stderr and "every tool call is denied" in r.stderr


def test_P3_an_empty_or_dangling_KILL_still_denies(home):
    home.kill.symlink_to(home.orch / "gone")
    assert _run_hook({"HOME": str(home.home)}).returncode == 2
    home.kill.unlink()
    home.kill.touch()
    assert _run_hook({"HOME": str(home.home)}).returncode == 2


def test_P3_a_KILL_directory_denies(home):
    home.kill.mkdir()
    assert _run_hook({"HOME": str(home.home)}).returncode == 2


def test_P3_deny_on_unreadable_state_no_state_dir(tmp_path):
    r = _run_hook({"HOME": str(tmp_path / "nowhere")})
    assert r.returncode == 2 and "cannot be read" in r.stderr


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a 000 directory")
def test_P3_deny_on_unreadable_state_unsearchable_dir(home):
    home.orch.chmod(0o000)
    try:
        r = _run_hook({"HOME": str(home.home)})
    finally:
        home.orch.chmod(0o755)
    assert r.returncode == 2 and "cannot be read" in r.stderr


def test_P3_deny_on_unreadable_state_no_HOME():
    r = _run_hook({})
    assert r.returncode == 2 and "cannot be read" in r.stderr


def test_P3_TONI_GUARDS_HOME_moves_the_state_dir(home, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    assert _run_hook({"HOME": str(home.home), "TONI_GUARDS_HOME": str(other)}).returncode == 0
    (other / "KILL").touch()
    assert _run_hook({"HOME": str(home.home), "TONI_GUARDS_HOME": str(other)}).returncode == 2
    assert _run_hook({"HOME": str(home.home)}).returncode == 0, "the default dir has no KILL"


@pytest.mark.parametrize("stdin", [None, "", "x" * 300_000])
def test_P3_the_hook_never_needs_its_input(home, stdin):
    home.kill.touch()
    r = subprocess.run(["bash", str(HOOK)], env={"PATH": os.environ["PATH"], "HOME": str(home.home)},
                       input=stdin, stdin=subprocess.DEVNULL if stdin is None else None, capture_output=True,
                       text=True, timeout=20)
    assert r.returncode == 2


@pytest.mark.parametrize("repo", REPOS)
def test_P3_the_settings_command_verbatim(home, repo):
    """What the CLI runs, through a shell, from each file: allow, deny, and deny when the hook file is gone."""
    cmd, = _hook_commands(_settings(repo))
    assert _run_hook({"HOME": str(home.home)}, script=cmd).returncode == 0
    home.kill.touch()
    assert _run_hook({"HOME": str(home.home)}, script=cmd).returncode == 2
    home.kill.unlink()
    (home.orch / "executor" / "hooks" / "kill_switch.sh").unlink()
    r = _run_hook({"HOME": str(home.home)}, script=cmd)
    assert r.returncode == 2, "fail closed: no hook script ⇒ every tool call denied"


# ═══════════════════════════════════════════════════════
# P4 · the daemon: refuse while KILL, kill, unkill
# ═══════════════════════════════════════════════════════
class _Daemon:
    """test_capacity's harness, reduced: the daemon under tmp_path, _run_route recorded, admission real."""

    def __init__(self, tmp_path: Path, monkeypatch):
        self.orch = tmp_path / "orch"
        (self.orch / "state").mkdir(parents=True)
        (self.orch / "config").mkdir()
        (self.orch / "logs").mkdir()
        not_git = tmp_path / "not-a-repo"
        not_git.mkdir()
        self.config = self.orch / "config" / "repos.yaml"
        self.config.write_text(yaml.safe_dump({"repos": {"clinical-mp": {"project_dir": str(not_git)}}}))
        self.queue = self.orch / "queue"
        self.state_file = tmp_path / "queue-state.json"
        for name, val in (("ORCH_DIR", self.orch), ("QUEUE_DIR", self.queue), ("QUEUE_DONE", self.queue / "done"),
                          ("QUEUE_FAILED", self.queue / "failed"), ("QUEUE_STATE", self.state_file),
                          ("REPOS_CONFIG", self.config), ("LOG_DIR", self.orch / "logs")):
            monkeypatch.setattr(queue_daemon, name, val)
        self.d = queue_daemon.QueueDaemon()
        self.d.start_running = True
        self.d.config.update(cooldown_seconds=0, model="m", effort="e")
        self.fired = []

        def _route(cmd, batch_name, log_path):
            self.fired.append(batch_name)
            Path(log_path).write_text("route output\n")
            return 0
        self.d._run_route = _route

    def brief(self, stem: str) -> Path:
        self.queue.mkdir(parents=True, exist_ok=True)
        p = self.queue / f"{stem}.md"
        p.write_text(f"#!queue repo=clinical-mp\n\n# {stem}\n")
        return p

    def stop_on_sleep(self, monkeypatch, after=1, on_sleep=None):
        seen = []

        def _sleep(s):
            seen.append(s)
            if on_sleep:
                on_sleep(len(seen))
            if len(seen) >= after:
                self.d.status = "stopped"
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep, monotonic=time.monotonic))
        return seen

    def state(self) -> dict:
        return json.loads(self.state_file.read_text()) if self.state_file.exists() else {}


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    return _Daemon(tmp_path, monkeypatch)


def test_P4_the_daemon_does_not_fire_while_KILL_exists(daemon, monkeypatch, capsys):
    brief = daemon.brief("394-a")
    (daemon.orch / "KILL").write_text(json.dumps({"reason": "drill", "at": "2026-10-23T19:00:00"}))
    daemon.stop_on_sleep(monkeypatch, after=3)
    daemon.d.run_loop()
    assert daemon.fired == [] and brief.exists(), "nothing fired; the brief stays in queue/"
    assert daemon.d.failed == [] and daemon.d.status != "paused", "a wait, never a failure or a pause"
    said = [l for l in capsys.readouterr().out.splitlines() if "KILL" in l]
    assert len(said) == 1, f"said once, not per poll: {said}"
    assert said[0].startswith(f"[QUEUE] 🛡 KILL present ({daemon.orch / 'KILL'}: drill, since 2026-10-23T19:00:00)")
    assert "394-a.md not fired" in said[0] and "queue_daemon.py unkill --reason" in said[0]
    assert "KILL present" in (daemon.state().get("waiting") or "")


def test_P4_unkill_lets_the_next_poll_fire_negative_control(daemon, monkeypatch, capsys):
    daemon.brief("394-a")
    kill = daemon.orch / "KILL"
    kill.touch()
    daemon.stop_on_sleep(monkeypatch, after=4, on_sleep=lambda n: kill.unlink() if n == 2 else None)
    daemon.d.run_loop()
    assert daemon.fired == ["394-a.md"]


def test_P4_KILL_written_while_a_brief_waits_on_the_lock_is_seen_before_it_fires(daemon, monkeypatch):
    """The check is the last one before the spawn: after the fire-lock wait, before admission."""
    daemon.brief("394-a")
    lock = daemon.orch / "state" / "running-clinical-mp.json"
    holder = subprocess.Popen(["sleep", "60"])
    try:
        lock.write_text(json.dumps({"pid": holder.pid, "batch_id": "393-x", "repo": "clinical-mp"}))

        def _then(n):
            if n == 1:
                (daemon.orch / "KILL").touch()
                lock.unlink()
        daemon.stop_on_sleep(monkeypatch, after=3, on_sleep=_then)
        daemon.d.run_loop()
    finally:
        holder.kill()
        holder.wait()
    assert daemon.fired == []


# — the kill command ——————————————————————————————————————————————————————————————
DUMMY_ORCH = r"""
import os, subprocess, sys, time
# the fire: its own session and process group, as fire_toni's Popen(preexec_fn=os.setsid)
fire = subprocess.Popen(["bash", "-c", sys.argv[1]], preexec_fn=os.setsid)
open(sys.argv[2], "w").write(str(fire.pid))
fire.wait()
open(sys.argv[3], "w").write(str(fire.returncode))
time.sleep(120)
"""
# a Bash tool command: its own session again, as the CLI runs each one (pgid = sid = its pid)
GRANDCHILD = "python3 -c 'import os, time; os.setsid(); time.sleep(300)' & echo $! > {gc}; "


def _alive(pid: int) -> bool:
    try:
        stat = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def _sid(pid: int) -> int:
    try:
        return int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[3])   # state ppid pgrp session
    except (OSError, IndexError, ValueError):
        return -1


def _wait_for(pred, s=10.0):
    end = time.monotonic() + s
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.05)
    return pred()


@pytest.fixture
def fire_tree(tmp_path, monkeypatch):
    """A dummy orchestrator (the marker's pid) whose fire has a grandchild in a session of its own."""
    orch = tmp_path / "orch"
    (orch / "state").mkdir(parents=True)
    monkeypatch.setattr(queue_daemon, "ORCH_DIR", orch)
    monkeypatch.setattr(queue_daemon, "KILL_GRACE_S", 0.5)
    procs = []

    def start(fire_script: str):
        gc, fpid, rc = tmp_path / "gc.pid", tmp_path / "fire.pid", tmp_path / "fire.rc"
        p = subprocess.Popen([sys.executable, "-c", DUMMY_ORCH, GRANDCHILD.format(gc=gc) + fire_script,
                              str(fpid), str(rc)])
        procs.append(p)
        assert _wait_for(lambda: fpid.exists() and fpid.read_text() and gc.exists() and gc.read_text().strip()
                         and _sid(int(gc.read_text())) == int(gc.read_text())), "the grandchild leads its own session"
        (orch / "state" / "running-clinical-mp.json").write_text(json.dumps(
            {"pid": p.pid, "batch_id": "394-x", "repo": "clinical-mp", "branch": "orch-mp-394-x"}))
        return types.SimpleNamespace(orch=p, fire=int(fpid.read_text()), gc=int(gc.read_text()), rc=rc)
    yield types.SimpleNamespace(start=start, orch=orch)
    for p in procs:
        p.kill()
        p.wait()
    for f in (tmp_path / "gc.pid", tmp_path / "fire.pid"):
        if f.exists() and f.read_text().strip():
            try:
                os.killpg(int(f.read_text()), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass


def test_P4_kill_writes_KILL_and_ends_the_fires_process_groups(fire_tree, capsys):
    t = fire_tree.start("sleep 300")
    assert _alive(t.fire) and _alive(t.gc)
    assert queue_daemon.main(["kill", "--reason", "drill 394"]) == 0
    assert _wait_for(lambda: not _alive(t.fire) and not _alive(t.gc)), "the fire and its Bash command are gone"
    assert _alive(t.orch.pid), "the orchestrator (the marker's pid, the daemon's group) is not signalled"
    assert _wait_for(lambda: t.rc.exists() and t.rc.read_text())
    assert t.rc.read_text() == str(-signal.SIGTERM), "SIGTERM was enough"
    kill = fire_tree.orch / "KILL"
    assert json.loads(kill.read_text())["reason"] == "drill 394"
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("🛡 KILL"))
    assert "drill 394" in line and f"pgid {t.fire}" in line and str(t.gc) in line and "394-x" in line
    assert line in (fire_tree.orch / "logs" / "kill-switch.log").read_text()


def test_P4_kill_sends_SIGKILL_after_the_grace(fire_tree, capsys):
    t = fire_tree.start("trap '' TERM; while :; do sleep 0.1; done")
    assert queue_daemon.main(["kill", "--reason", "stubborn"]) == 0
    assert _wait_for(lambda: not _alive(t.fire) and not _alive(t.gc))
    assert _wait_for(lambda: t.rc.exists() and t.rc.read_text())
    assert t.rc.read_text() == str(-signal.SIGKILL)
    assert "SIGKILL" in capsys.readouterr().out


def test_P4_kill_with_no_live_fire_still_writes_KILL(fire_tree, capsys):
    assert queue_daemon.main(["kill"]) == 0
    assert (fire_tree.orch / "KILL").exists()
    line = next(l for l in capsys.readouterr().out.splitlines() if l.startswith("🛡 KILL"))
    assert "no live fire" in line and "(no reason given)" in line


def test_P4_a_second_kill_keeps_the_first_reason(fire_tree):
    queue_daemon.main(["kill", "--reason", "first"])
    queue_daemon.main(["kill", "--reason", "second"])
    assert json.loads((fire_tree.orch / "KILL").read_text())["reason"] == "first"
    assert "second" in (fire_tree.orch / "logs" / "kill-switch.log").read_text()


@pytest.mark.parametrize("argv", [["unkill"], ["unkill", "--reason"], ["unkill", "--reason", ""],
                                  ["unkill", "--reason", "   "], ["unkill", "--why", "x"], ["unkill", "x"]])
def test_P4_unkill_requires_a_reason(fire_tree, capsys, argv):
    (fire_tree.orch / "KILL").touch()
    assert queue_daemon.main(argv) == 2
    assert (fire_tree.orch / "KILL").exists(), "nothing lifted"
    assert "unkill --reason" in capsys.readouterr().err


def test_P4_unkill_with_a_reason_removes_KILL_and_logs_it(fire_tree, capsys):
    queue_daemon.main(["kill", "--reason", "drill"])
    assert queue_daemon.main(["unkill", "--reason", "drill over, checked the tree"]) == 0
    assert not (fire_tree.orch / "KILL").exists()
    line = next(l for l in capsys.readouterr().out.splitlines() if l.startswith("🛡 UNKILL"))
    assert "drill over, checked the tree" in line and "drill" in line
    assert line in (fire_tree.orch / "logs" / "kill-switch.log").read_text()


def test_P4_unkill_with_no_KILL_says_so(fire_tree, capsys):
    assert queue_daemon.main(["unkill", "--reason", "nothing to lift"]) == 0
    assert "no KILL" in capsys.readouterr().out


@pytest.mark.parametrize("argv", [["kill", "--reason"], ["kill", "x"], ["kill", "--reason", "a", "b"]])
def test_P4_kill_usage(fire_tree, argv):
    assert queue_daemon.main(argv) == 2
    assert not (fire_tree.orch / "KILL").exists()

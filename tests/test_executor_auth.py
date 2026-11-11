"""[ORCH-EXECUTOR-AUTH-PROBE-1] Kanban 659, L-382 — the executor's login is checked before a route starts, and a login
failure is named as one. Predicates P-C1..P-C4 of briefs/652-660-orch-prefire-bundle-1.md Part C.

  P-C1  executor_auth.probe: status step, one live call, kinds ok / auth / environment, no account field leaks
  P-C2  the daemon: once per fire after admission's yes; a refusal releases the claim, pauses (never self-clearing),
        leaves the brief first in queue/
  P-C3  run_batch: one `🛡 executor-auth:` line, a refusal before any branch or worktree (exit 2, FAILED)
  P-C4  _executor_exit_hold: a short sign-in failure output is INCOMPLETE(executor-auth)

No test runs the real `claude`: executor_auth's subprocess and shutil are replaced by a recorder (P-C1, P-C2), or
executor_auth.probe itself (P-C3).
"""
import json
import shlex
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import admission  # noqa: E402
import executor_auth  # noqa: E402
import orchestrator  # noqa: E402
import queue_daemon  # noqa: E402
import slack_notify  # noqa: E402

pytestmark = pytest.mark.executor_auth

NOW = datetime(2026, 11, 11, 9, 0, 0, tzinfo=timezone.utc)
SECRETS = ("x@example.test", "org-test", "Org Test")
REFUSED = "Failed to authenticate: OAuth session expired and could not be refreshed"
LOG_602A = ("=== TONI EXECUTION ===\nBatch: 602a-approvals-holding-1-rerun.md\nStarted: 2026-11-11T06:50:36.611005\n"
            "Command: cd /home/x && stdbuf -oL claude --dangerously-skip-permissions --model claude-opus-5-5 \"Read briefs/x.md\"\n"
            "BgWaitCeilingMs: 4920000 (route timeout 5220s, margin 300s)\n"
            "Foreground: CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1, BASH_DEFAULT_TIMEOUT_MS=4920000, BASH_MAX_TIMEOUT_MS=4920000\n"
            + "=" * 60 + "\n\n" + REFUSED + "\n\n" + "=" * 60 + "\nFinished: 2026-11-11T06:50:39.759575\nExit: 1\n")


def status_json(logged_in=True, expires=NOW + timedelta(days=29)) -> str:
    """`claude auth status --json`'s shape on this machine (CLI 2.1.322), account fields fake."""
    return json.dumps({"loggedIn": logged_in, "authMethod": "claude.ai", "apiProvider": "firstParty",
                       "loginExpiresAt": expires.strftime("%Y-%m-%dT%H:%M:%S.000Z") if expires else None,
                       "email": SECRETS[0], "orgId": SECRETS[1], "orgName": SECRETS[2], "subscriptionType": "max",
                       "storedClaudeAiLogin": True, "planTier": "max_20x"})


class FakeCLI:
    """executor_auth's subprocess/shutil: answers `auth status` and the live `-p` call separately, records every
    argv, env and cwd. A step's answer is (rc, stdout, stderr) or an exception instance."""

    def __init__(self, status=(0, None, ""), live=(0, json.dumps({"is_error": False, "result": "ok"}), ""),
                 which="/fake/bin/claude", orch_state=None):
        self.status = (status[0], status_json() if status[1] is None else status[1], status[2]) \
            if isinstance(status, tuple) else status
        self.live, self.which_result, self.orch_state = live, which, orch_state
        self.calls, self.live_cwds = [], []

    @property
    def live_calls(self):
        return [c for c in self.calls if "-p" in c["argv"]]

    def _which(self, name, path=None):
        return self.which_result

    def _run(self, argv, **kw):
        call = {"argv": list(argv), "env": dict(kw.get("env") or {}), "cwd": kw.get("cwd")}
        self.calls.append(call)
        if "-p" in argv:
            cwd = Path(kw["cwd"])
            call["cwd_empty"] = cwd.is_dir() and not any(cwd.iterdir())
            call["cwd_in_git"] = any((p / ".git").exists() for p in [cwd, *cwd.parents])
            if self.orch_state is not None:
                call["claimed"] = admission.claim_path(self.orch_state).exists()
            answer = self.live
        else:
            answer = self.status
        if isinstance(answer, BaseException):
            raise answer
        rc, out, err = answer
        return subprocess.CompletedProcess(argv, rc, out, err)

    def install(self, monkeypatch):
        monkeypatch.setattr(executor_auth, "subprocess", types.SimpleNamespace(
            run=self._run, TimeoutExpired=subprocess.TimeoutExpired))
        monkeypatch.setattr(executor_auth, "shutil", types.SimpleNamespace(which=self._which))
        return self


def timeout(cmd="claude"):
    return subprocess.TimeoutExpired(cmd, 1)


# ═══════════════════════════════════════════════════════
# P-C1 · the probe
# ═══════════════════════════════════════════════════════
class TestPC1Probe:

    def test_a_logged_in_and_live_ok_says_so_without_the_account(self, monkeypatch, capsys, caplog):
        cli = FakeCLI().install(monkeypatch)
        v = executor_auth.probe(env={"PATH": "/x"}, now=NOW)
        exp = executor_auth.iso_z(NOW + timedelta(days=29))
        assert (v.ok, v.kind) == (True, "ok")
        assert v.detail.startswith(f"logged in (claude.ai, max); login expires {exp}; live call ok in "), v.detail
        assert len(cli.live_calls) == 1
        said = v.detail + capsys.readouterr().out + caplog.text
        assert not [s for s in SECRETS if s in said] and "ok in" in said and '"ok"' not in said

    def test_b_not_logged_in_is_auth_and_no_live_call(self, monkeypatch):
        cli = FakeCLI(status=(0, status_json(logged_in=False), "")).install(monkeypatch)
        v = executor_auth.probe(env={}, now=NOW)
        assert (v.ok, v.kind) == (False, "auth") and "not logged in" in v.detail
        assert cli.live_calls == []

    def test_c_expired_is_auth_and_no_live_call(self, monkeypatch):
        cli = FakeCLI(status=(0, status_json(expires=NOW - timedelta(minutes=1)), "")).install(monkeypatch)
        v = executor_auth.probe(env={}, now=NOW)
        assert v.kind == "auth" and "expired at 2026-11-11T08:59:00Z" in v.detail
        assert cli.live_calls == []

    @pytest.mark.parametrize("which, status, cause", [
        (None, (0, None, ""), "not on PATH"),
        ("/fake/bin/claude", timeout(), "did not answer in 30 s"),
        ("/fake/bin/claude", (1, "", "boom"), "exited 1: boom"),
        ("/fake/bin/claude", (0, "not json", ""), "did not print a JSON object"),
        ("/fake/bin/claude", (0, "{}", ""), "no boolean loggedIn")])
    def test_d_a_status_step_with_no_verdict_is_environment(self, monkeypatch, which, status, cause):
        cli = FakeCLI(status=status, which=which).install(monkeypatch)
        v = executor_auth.probe(env={}, now=NOW)
        assert v.kind == "environment" and v.detail.startswith("the executor's login could not be checked: ")
        assert cause in v.detail, v.detail
        assert cli.live_calls == []

    def test_e_status_ok_but_the_live_call_is_refused_is_auth_quoting_the_line(self, monkeypatch):
        cli = FakeCLI(live=(1, "", REFUSED + "\n")).install(monkeypatch)
        v = executor_auth.probe(env={}, now=NOW)
        assert (v.ok, v.kind) == (False, "auth")
        assert v.detail == f"the executor's login was refused when used: \"{REFUSED}\""
        assert len(cli.live_calls) == 1

    @pytest.mark.parametrize("live", [timeout(), (1, "", "getaddrinfo ENOTFOUND api.anthropic.com\n")])
    def test_f_a_live_call_with_no_auth_line_is_environment(self, monkeypatch, live):
        FakeCLI(live=live).install(monkeypatch)
        v = executor_auth.probe(env={}, now=NOW)
        assert v.kind == "environment"
        assert v.detail.startswith("BLOCKED(environment)") and "not a login problem" in v.detail

    def test_f_a_timeout_says_60_s(self, monkeypatch):
        FakeCLI(live=timeout()).install(monkeypatch)
        assert "timeout after 60 s" in executor_auth.probe(env={}, now=NOW).detail

    def test_g_an_expiry_inside_the_route_is_said(self, monkeypatch):
        FakeCLI(status=(0, status_json(expires=NOW + timedelta(minutes=30)), "")).install(monkeypatch)
        v = executor_auth.probe(env={}, now=NOW, within_s=3600)
        assert v.kind == "ok" and v.detail.endswith("— expires inside this route's 60 min")

    def test_g_control_an_expiry_after_the_route_is_not(self, monkeypatch):
        FakeCLI().install(monkeypatch)
        assert "expires inside" not in executor_auth.probe(env={}, now=NOW, within_s=3600).detail

    def test_h_no_api_key_fixed_argv_and_an_empty_cwd_outside_any_repo(self, monkeypatch):
        cli = FakeCLI().install(monkeypatch)
        executor_auth.probe(env={"PATH": "/x", "ANTHROPIC_API_KEY": "sk-test"}, now=NOW)
        assert len(cli.calls) == 2 and all("ANTHROPIC_API_KEY" not in c["env"] for c in cli.calls)
        assert cli.calls[0]["argv"] == ["/fake/bin/claude", "auth", "status", "--json"]
        live = cli.live_calls[0]
        assert live["argv"] == ["/fake/bin/claude", "-p", "--no-session-persistence", "--output-format", "json",
                                "--tools", "", "--strict-mcp-config", "--setting-sources", "local",
                                executor_auth.LIVE_PROMPT]
        assert executor_auth.LIVE_PROMPT == "Reply with the single word: ok"
        assert live["cwd_empty"] and not live["cwd_in_git"]
        assert not Path(live["cwd"]).exists(), "the temp dir is removed after the call"

    @pytest.mark.parametrize("flag", ["--setting-sources", "--tools", "--strict-mcp-config"])
    def test_i_a_rejected_flag_is_environment_named_and_never_retried(self, monkeypatch, flag):
        cli = FakeCLI(live=(1, "", f"error: unknown option '{flag}'\n")).install(monkeypatch)
        v = executor_auth.probe(env={}, now=NOW)
        assert (v.ok, v.kind) == (False, "environment") and v.detail.startswith("BLOCKED(environment)")
        assert f"rejected {flag}" in v.detail
        assert len(cli.live_calls) == 1

    def test_probe_off_any_case(self):
        assert executor_auth.probe_off({"EXECUTOR_AUTH_PROBE": " Off "}) and executor_auth.probe_off({"EXECUTOR_AUTH_PROBE": "OFF"})
        assert not executor_auth.probe_off({"EXECUTOR_AUTH_PROBE": "on"}) and not executor_auth.probe_off({})

    @pytest.mark.parametrize("value, fresh", [((NOW - timedelta(minutes=1)), True), ((NOW - timedelta(minutes=20)), False),
                                              ((NOW + timedelta(minutes=5)), False), ("junk", False)])
    def test_checked_by_daemon_is_fresh_or_unset(self, value, fresh):
        v = executor_auth.iso_z(value) if isinstance(value, datetime) else value
        assert executor_auth.checked_by_daemon({"EXECUTOR_AUTH_CHECKED": v}, now=NOW) == (v if fresh else None)


# ═══════════════════════════════════════════════════════
# P-C2 · the daemon asks once per fire, after admission
# ═══════════════════════════════════════════════════════
class Daemon:
    def __init__(self, tmp_path: Path, monkeypatch):
        self.orch = tmp_path / "orch"
        self.queue = self.orch / "queue"
        self.state_file = tmp_path / "queue-state.json"
        not_git = tmp_path / "not-a-repo"
        not_git.mkdir()
        (self.orch / "state").mkdir(parents=True)
        cfg = tmp_path / "repos.yaml"
        cfg.write_text(yaml.safe_dump({"repos": {"ai-foundation": {"project_dir": str(not_git)}}}))
        for name, val in (("ORCH_DIR", self.orch), ("QUEUE_DIR", self.queue), ("QUEUE_DONE", self.queue / "done"),
                          ("QUEUE_FAILED", self.queue / "failed"), ("QUEUE_STATE", self.state_file),
                          ("REPOS_CONFIG", cfg), ("LOG_DIR", tmp_path / "logs")):
            monkeypatch.setattr(queue_daemon, name, val)
        monkeypatch.setattr(slack_notify, "send_slack", lambda text, blocks=None: True)
        self.d = queue_daemon.QueueDaemon()
        self.d.start_running = True
        self.d.config.update(cooldown_seconds=0, model="m", effort="e")
        self.fired, self.cmds, self.statuses = [], [], []

        def _route(cmd, batch_name, log_path):
            self.fired.append(batch_name)
            self.cmds.append(cmd)
            Path(log_path).write_text("route output\n")
            return 0
        self.d._run_route = _route

    def brief(self, stem="120-x-1", body="") -> Path:
        self.queue.mkdir(parents=True, exist_ok=True)
        p = self.queue / f"{stem}.md"
        p.write_text(f"#!queue repo=ai-foundation\n\n# {stem}\n{body}")
        return p

    def run(self, monkeypatch, sleeps=1, on_sleep=None):
        seen = []

        def _sleep(s):
            seen.append(s)
            self.statuses.append(self.d.status)   # what the daemon was when it slept, before the stub stops it
            if on_sleep:
                on_sleep(len(seen))
            if len(seen) >= sleeps:
                self.d.status = "stopped"
        monkeypatch.setattr(queue_daemon, "time", types.SimpleNamespace(sleep=_sleep))
        self.d.run_loop()
        return seen

    def claims(self):
        return list((self.orch / "state").glob(admission.CLAIM_GLOB))

    def notice(self) -> dict:
        return json.loads((self.orch / "state" / "queue-paused.json").read_text())

    def state(self) -> dict:
        return json.loads(self.state_file.read_text())


@pytest.fixture
def daemon(tmp_path, monkeypatch):
    return Daemon(tmp_path, monkeypatch)


class TestPC2Daemon:

    def test_a_refused_refresh_pauses_executor_auth_and_leaves_the_brief_queued(self, daemon, monkeypatch, capsys):
        b = daemon.brief()
        FakeCLI(live=(1, "", REFUSED + "\n")).install(monkeypatch)
        daemon.run(monkeypatch)
        assert daemon.fired == [] and daemon.claims() == []
        assert b.exists() and not (daemon.queue / "failed" / b.name).exists()
        reason = daemon.d.paused_reason
        assert daemon.statuses == ["paused"] and daemon.state()["paused_reason"] == reason
        assert reason.startswith(f"executor-auth:{b.name} — Toni's login has expired or been refused; only George "
                                 f"can fix it: run claude, then /login, then resume")
        n = daemon.notice()
        assert f'"{REFUSED}"' in n["detail"] and executor_auth.AUTH_FIX in n["detail"]
        assert queue_daemon.pause_notice_text(n).endswith(f" — {n['detail']}")
        assert shlex.split(queue_daemon.resume_command(reason))[-1] == reason
        assert daemon.d.current_batch is None
        out = capsys.readouterr().out
        assert [l for l in out.splitlines() if "🛡 executor-auth: BLOCKED — " in l] == [
            f"[QUEUE] 🛡 executor-auth: BLOCKED — the executor's login was refused when used: \"{REFUSED}\" — {b.name} "
            f"not fired; {executor_auth.AUTH_FIX} Then: {queue_daemon.resume_command(reason)}"]

    def test_a_live_timeout_pauses_executor_check_never_executor_auth(self, daemon, monkeypatch):
        b = daemon.brief()
        FakeCLI(live=timeout()).install(monkeypatch)
        daemon.run(monkeypatch)
        assert daemon.fired == [] and daemon.claims() == [] and b.exists()
        assert daemon.d.paused_reason.startswith(f"executor-check:{b.name} — BLOCKED(environment)")
        assert executor_auth.ENV_FIX in daemon.notice()["detail"]

    @pytest.mark.parametrize("live", [(1, "", REFUSED + "\n"), timeout()])
    def test_a_later_poll_with_the_probe_ok_does_not_lift_the_pause(self, daemon, monkeypatch, live):
        daemon.brief()
        cli = FakeCLI(live=live).install(monkeypatch)

        def _heal(n):
            cli.live = (0, json.dumps({"is_error": False, "result": "ok"}), "")
        daemon.run(monkeypatch, sleeps=4, on_sleep=_heal)
        assert daemon.statuses == ["paused"] * 4 and daemon.fired == [] and len(cli.live_calls) == 1
        assert daemon.d.paused_reason.startswith(("executor-auth:", "executor-check:"))

    def test_ok_fires_as_today_and_names_the_check_to_the_route(self, daemon, monkeypatch, capsys):
        daemon.brief()
        FakeCLI().install(monkeypatch)
        daemon.run(monkeypatch)
        assert daemon.fired == ["120-x-1.md"]
        assert f" {executor_auth.CHECKED_VAR}=" in daemon.cmds[0]
        claim = admission.claim_path(daemon.orch)
        assert f"{admission.CLAIM_ENV}={claim} python3 -u orchestrator.py run" in daemon.cmds[0]
        assert "[QUEUE] 🛡 executor-auth: CLEAN — logged in (claude.ai, max)" in capsys.readouterr().out

    def test_admission_waits_three_times_then_one_live_call_after_the_claim(self, daemon, monkeypatch):
        daemon.brief()
        cli = FakeCLI(orch_state=daemon.orch).install(monkeypatch)
        real, asked = admission.admit, []

        def _admit(*a, **kw):
            asked.append(1)
            return (False, "waiting (tests)") if len(asked) <= 3 else real(*a, **kw)
        monkeypatch.setattr(admission, "admit", _admit)
        daemon.run(monkeypatch, sleeps=4)
        assert len(asked) == 4 and daemon.fired == ["120-x-1.md"]
        assert len(cli.live_calls) == 1 and cli.live_calls[0]["claimed"] is True

    def test_a_refusal_releases_the_claim(self, daemon, monkeypatch):
        daemon.brief()
        cli = FakeCLI(live=(1, "", REFUSED + "\n"), orch_state=daemon.orch).install(monkeypatch)
        daemon.run(monkeypatch)
        assert cli.live_calls[0]["claimed"] is True and daemon.claims() == []

    def test_a_regate_brief_is_not_probed(self, daemon, monkeypatch):
        daemon.brief(body="\n## Re-gate of: orch-x abc1234\n")
        cli = FakeCLI(live=timeout()).install(monkeypatch)
        daemon.run(monkeypatch)
        assert cli.calls == [] and daemon.fired == ["120-x-1.md"]

    def test_off_is_not_probed_and_says_so(self, daemon, monkeypatch, capsys):
        daemon.brief()
        monkeypatch.setenv("EXECUTOR_AUTH_PROBE", "Off")
        cli = FakeCLI(live=timeout()).install(monkeypatch)
        daemon.run(monkeypatch)
        assert cli.calls == [] and daemon.fired == ["120-x-1.md"]
        assert "[QUEUE] 🛡 executor-auth: OFF (EXECUTOR_AUTH_PROBE=off) — not checked" in capsys.readouterr().out
        assert executor_auth.CHECKED_VAR not in daemon.cmds[0]

    def test_control_a_notice_without_detail_reads_as_before(self):
        n = {"reason": "stop-on-failure:x.md", "at": "2026-11-11T06:50:39", "next_brief": "y.md", "resume": "cmd"}
        assert queue_daemon.pause_notice_text(n) == (
            ":double_vertical_bar: Spectricom queue PAUSED — stop-on-failure:x.md (since 2026-11-11T06:50:39). "
            "Next brief: y.md. Nothing fires until: `cmd`")


# ═══════════════════════════════════════════════════════
# P-C3 · the orchestrator asks before any branch
# ═══════════════════════════════════════════════════════
@pytest.fixture
def batch(tmp_path, monkeypatch, caplog):
    caplog.set_level("INFO", logger="orch")
    brief = tmp_path / "120-x-1.md"
    brief.write_text("#!queue repo=ai-foundation\n\n# 120\n")
    seen = types.SimpleNamespace(probe=[], inner=[], worktrees=[], toni=[], brief=brief)
    monkeypatch.setattr(orchestrator.prefire, "report", lambda *a, **k: True)
    monkeypatch.setattr(orchestrator, "PREFIRE_BYPASS", False)
    monkeypatch.setattr(orchestrator, "IS_META_FIRE", False)
    monkeypatch.setattr(orchestrator, "WORKTREE_MODE", "parallel")
    monkeypatch.setattr(orchestrator, "_create_route_worktree", lambda bf: seen.worktrees.append(bf) or (tmp_path, None))
    monkeypatch.setattr(orchestrator, "_finish_route_worktree", lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "fire_toni", lambda *a, **k: seen.toni.append(a) or (0, ""))
    for name in ("write_running", "clear_running", "_write_running_marker", "_clear_running_marker"):
        monkeypatch.setattr(orchestrator, name, lambda *a, **k: None)
    monkeypatch.setattr(orchestrator, "parse_batch", lambda bf: [])

    def _inner(bf, proj, started, worktree=None, **kw):
        seen.inner.append(bf.name)
        now = orchestrator.datetime.now().isoformat()
        return orchestrator.Result(batch_file=bf.name, status=orchestrator.Status.PASSED, started=now, finished=now,
                                   duration_s=0.0, exit_code=0, briefs=1)
    monkeypatch.setattr(orchestrator, "_run_batch_inner", _inner)

    def answer(v):
        monkeypatch.setattr(executor_auth, "probe", lambda **kw: seen.probe.append(kw) or v)
    seen.answer = answer
    seen.lines = lambda: [r.getMessage() for r in caplog.records if "executor-auth:" in r.getMessage()
                          and r.getMessage().startswith("🛡")]
    return seen


class TestPC3RunBatch:

    @pytest.mark.parametrize("kind, starts", [("auth", "executor-auth: "),
                                              ("environment", "BLOCKED(environment) — executor check: ")])
    def test_a_refusal_is_exit_2_before_any_branch(self, batch, kind, starts):
        batch.answer(executor_auth.AuthProbe(False, kind, "the detail", None))
        r = orchestrator.run_batch(batch.brief)
        assert (r.status, r.exit_code, r.briefs) == (orchestrator.Status.FAILED, 2, 0)
        assert r.error.startswith(starts) and "not fired, no branch cut" in r.error
        assert r.error.endswith(executor_auth.fix_for(kind))
        assert batch.inner == [] and batch.worktrees == [] and batch.toni == []
        assert len([l for l in batch.lines() if l.startswith("🛡 executor-auth: BLOCKED — ")]) == 1
        assert len(batch.lines()) == 1

    def test_ok_is_one_clean_line_and_the_route_proceeds(self, batch):
        batch.answer(executor_auth.AuthProbe(True, "ok", "logged in (claude.ai, max)", None))
        r = orchestrator.run_batch(batch.brief)
        assert r.status is orchestrator.Status.PASSED and batch.inner == ["120-x-1.md"]
        assert batch.lines() == ["🛡 executor-auth: CLEAN — logged in (claude.ai, max)"]
        assert batch.probe[0]["within_s"] == orchestrator.prefire_timeout(batch.brief)[0] * 60

    def test_a_fresh_daemon_check_is_not_repeated(self, batch, monkeypatch):
        batch.answer(executor_auth.AuthProbe(False, "auth", "x", None))
        at = executor_auth.iso_z(datetime.now(timezone.utc) - timedelta(minutes=1))
        monkeypatch.setenv("EXECUTOR_AUTH_CHECKED", at)
        orchestrator.run_batch(batch.brief)
        assert batch.probe == [] and batch.inner == ["120-x-1.md"]
        assert batch.lines() == [f"🛡 executor-auth: CLEAN — checked by the queue daemon at {at}"]

    @pytest.mark.parametrize("stale", ["20min", "junk"])
    def test_a_stale_or_junk_daemon_check_reads_as_unset(self, batch, monkeypatch, stale):
        batch.answer(executor_auth.AuthProbe(True, "ok", "logged in", None))
        v = executor_auth.iso_z(datetime.now(timezone.utc) - timedelta(minutes=20)) if stale == "20min" else "junk"
        monkeypatch.setenv("EXECUTOR_AUTH_CHECKED", v)
        orchestrator.run_batch(batch.brief)
        assert len(batch.probe) == 1

    def test_force_skips_and_says_so(self, batch, monkeypatch):
        batch.answer(executor_auth.AuthProbe(False, "auth", "x", None))
        monkeypatch.setattr(orchestrator, "PREFIRE_BYPASS", True)
        orchestrator.run_batch(batch.brief)
        assert batch.probe == [] and batch.lines() == ["🛡 executor-auth: SKIPPED — --force bypasses all safety checks"]

    def test_off_skips_and_says_so(self, batch, monkeypatch):
        batch.answer(executor_auth.AuthProbe(False, "auth", "x", None))
        monkeypatch.setenv("EXECUTOR_AUTH_PROBE", "off")
        orchestrator.run_batch(batch.brief)
        assert batch.probe == [] and batch.lines() == ["🛡 executor-auth: OFF — EXECUTOR_AUTH_PROBE=off, not checked"]

    def test_a_regate_has_no_executor_auth_line(self, batch, monkeypatch):
        batch.answer(executor_auth.AuthProbe(False, "auth", "x", None))
        spec = types.SimpleNamespace(branch="orch-x", sha="abc1234def", prior="BLOCKED(environment)")
        monkeypatch.setattr(orchestrator, "_regate_check", lambda bf: (spec, None))
        orchestrator.run_batch(batch.brief)
        assert batch.probe == [] and batch.lines() == []


# ═══════════════════════════════════════════════════════
# P-C4 · a login failure after the fire is named as one
# ═══════════════════════════════════════════════════════
class TestPC4ExitHold:

    def test_602a_log_is_incomplete_executor_auth(self, tmp_path, caplog):
        caplog.set_level("INFO", logger="orch")
        log = tmp_path / "toni-602a.log"
        log.write_text(LOG_602A)
        h = orchestrator._executor_exit_hold(1, "orch-x", out_log=str(log))
        assert h.verdict == "INCOMPLETE(executor-auth)" == orchestrator.INCOMPLETE_EXECUTOR_AUTH_VERDICT
        assert f'"{REFUSED}"' in h.error and "/login" in h.error and "with work on the tree" not in h.error
        assert "🛡 executor-exit: HOLD — INCOMPLETE(executor-auth): exit 1 on orch-x" in caplog.text

    def test_control_a_long_working_output_that_mentions_oauth_is_executor_error(self, tmp_path):
        body = "\n".join(["working on step %d" % i for i in range(39)] + ["note: OAuth session expired is handled"])
        log = tmp_path / "toni.log"
        log.write_text(LOG_602A.replace(REFUSED, body))
        h = orchestrator._executor_exit_hold(1, "orch-x", out_log=str(log))
        assert h.verdict == orchestrator.INCOMPLETE_EXECUTOR_ERROR_VERDICT
        assert h.error == orchestrator._executor_exit_hold(1, "orch-x").error

    def test_control_no_out_log_is_heads_behaviour(self):
        h = orchestrator._executor_exit_hold(1, "orch-x")
        assert h.verdict == "INCOMPLETE(executor-error)"
        assert h.error.startswith("INCOMPLETE(executor-error) — executor exit 1 (the executor did not exit 0) with "
                                  "work on the tree; no gate run, nothing merged.")

    def test_control_the_timeout_kill_is_never_executor_auth(self, tmp_path):
        log = tmp_path / "toni.log"
        log.write_text(LOG_602A)
        assert orchestrator._executor_exit_hold(-1, "orch-x", out_log=str(log)).verdict == "INCOMPLETE(timeout)"

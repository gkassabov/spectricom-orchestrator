#!/usr/bin/env python3
"""[ORCH-EXECUTOR-AUTH-PROBE-1] Kanban 659, L-382 — is the executor (Toni, the claude CLI) logged in, before a route
starts? One owner of the probe; the queue daemon asks once per fire after admission's yes (G-C2), the orchestrator
before any branch or worktree is cut (G-C3), and `_executor_exit_hold` names a login failure after the fact (G-C4).

  step 1  `claude auth status --json` (read-only): not logged in / expired ⇒ kind "auth"; no verdict ⇒ "environment".
  step 2  one live `claude -p` call, from a fresh empty temp dir, no tools, no MCP, no user or project settings, a
          fixed prompt with no repo or patient text, its reply discarded: it catches a refresh token the server has
          already refused while `auth status` still says logged in (602a, 2026-11-11 06:50).

Kinds: "ok"; "auth" — the login is absent, expired or refused, and only George can fix it (AUTH_FIX); "environment"
— the check could not reach a verdict, BLOCKED(environment), not a login problem (ENV_FIX). It never logs in, logs
out, or reads a credential or settings file, and the account's email, orgId and orgName are never read into a
detail. Kill switch: EXECUTOR_AUTH_PROBE=off (any case) — every caller says so on every fire.
"""

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Optional

PROBE_VAR = "EXECUTOR_AUTH_PROBE"
CHECKED_VAR = "EXECUTOR_AUTH_CHECKED"   # set by the daemon in the route command it just probed: one live call per fire
CHECKED_MAX_AGE_S = 600
STATUS_TIMEOUT_S = 30
LIVE_TIMEOUT_S = 60
LIVE_PROMPT = "Reply with the single word: ok"
LIVE_SETTING_SOURCES = "local"          # neither user nor project settings; the empty cwd has no local file
AUTH_FAILURE_LINES = ("Failed to authenticate", "OAuth session expired", "could not be refreshed",
                      "Please run /login", "Invalid API key")
AUTH_FAILURE_MAX_LINES = 5
AUTH_FIX = ("Toni's login (the executor, the claude CLI) has expired or been refused, and only George can fix it: on "
            "the laptop run `claude`, then `/login`, finish the sign-in, then resume the queue.")
ENV_FIX = "Check the laptop's network and the claude CLI, then resume the queue; the login itself was not judged."
_LIVE_FLAGS = ("--no-session-persistence", "--strict-mcp-config", "--setting-sources", "--output-format", "--tools")
_FLAG_REJECTED = ("unknown option", "invalid", "error: option")


@dataclass(frozen=True)
class AuthProbe:
    ok: bool
    kind: str          # "ok" | "auth" | "environment"
    detail: str
    expires_at: Optional[datetime]


def probe_off(env: Optional[Mapping[str, str]] = None) -> bool:
    """EXECUTOR_AUTH_PROBE=off (any case, spaces ignored) skips the probe."""
    v = (os.environ if env is None else env).get(PROBE_VAR, "")
    return "".join(v.split()).lower() == "off"


def fix_for(kind: str) -> str:
    """What the caller says after a refusal's detail."""
    return AUTH_FIX if kind == "auth" else ENV_FIX


def iso_z(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(v) -> Optional[datetime]:
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        t = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _first_line(text: str, limit: int = 120) -> str:
    for line in (text or "").splitlines():
        if line.strip():
            return line.strip()[:limit]
    return "(no output)"


def _env_probe(why: str) -> AuthProbe:
    return AuthProbe(False, "environment", "the executor's login could not be checked: %s" % why, None)


def _env_live(why: str) -> AuthProbe:
    return AuthProbe(False, "environment", "BLOCKED(environment) — the executor's live check did not answer (%s); "
                                           "this is not a login problem" % why, None)


def _auth_line_in(*texts: str) -> Optional[str]:
    for text in texts:
        for line in (text or "").splitlines():
            if any(m in line for m in AUTH_FAILURE_LINES):
                return line.strip()[:200]
    return None


def probe(env: Optional[Mapping[str, str]] = None, now: Optional[datetime] = None,
          within_s: Optional[int] = None) -> AuthProbe:
    """Step 1 `claude auth status --json`, then (only when it passed) exactly one live `claude -p` call — never
    retried. `within_s`: the route's length, so an ok that expires inside it says so."""
    run_env = dict(os.environ if env is None else env)
    run_env.pop("ANTHROPIC_API_KEY", None)
    now = now or datetime.now(timezone.utc)
    exe = shutil.which("claude", path=run_env.get("PATH"))
    if not exe:
        return _env_probe("the claude CLI is not on PATH")
    try:
        r = subprocess.run([exe, "auth", "status", "--json"], env=run_env, capture_output=True, text=True,
                           timeout=STATUS_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return _env_probe("`claude auth status` did not answer in %d s" % STATUS_TIMEOUT_S)
    except OSError as e:
        return _env_probe("`claude auth status` could not run (%s)" % e)
    if r.returncode != 0:
        return _env_probe("`claude auth status` exited %d: %s" % (r.returncode, _first_line(r.stderr or r.stdout)))
    try:
        status = json.loads(r.stdout)
    except ValueError:
        status = None
    if not isinstance(status, dict):
        return _env_probe("`claude auth status --json` did not print a JSON object")
    if not isinstance(status.get("loggedIn"), bool):
        return _env_probe("`claude auth status --json` has no boolean loggedIn")
    expires = _parse_iso(status.get("loginExpiresAt"))
    if not status["loggedIn"]:
        return AuthProbe(False, "auth", "the executor (Toni — the claude CLI) is not logged in", expires)
    if expires is not None and expires <= now:
        return AuthProbe(False, "auth", "the executor's login expired at %s" % iso_z(expires), expires)
    method, sub = str(status.get("authMethod") or "unknown"), str(status.get("subscriptionType") or "unknown")

    argv = [exe, "-p", "--no-session-persistence", "--output-format", "json", "--tools", "", "--strict-mcp-config",
            "--setting-sources", LIVE_SETTING_SOURCES, LIVE_PROMPT]
    t0 = time.monotonic()
    try:
        with tempfile.TemporaryDirectory(prefix="executor-auth-") as cwd:
            live = subprocess.run(argv, env=run_env, cwd=cwd, capture_output=True, text=True, timeout=LIVE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return _env_live("timeout after %d s" % LIVE_TIMEOUT_S)
    except OSError as e:
        return _env_live("could not run: %s" % e)
    secs = round(time.monotonic() - t0, 1)
    try:
        out = json.loads(live.stdout)
    except ValueError:
        out = None
    result = out.get("result") if isinstance(out, dict) and isinstance(out.get("result"), str) else ""
    if live.returncode == 0 and isinstance(out, dict) and out.get("is_error") is not True:
        detail = "logged in (%s, %s); login expires %s; live call ok in %s s" % (
            method, sub, iso_z(expires) if expires else "not stated", secs)
        if within_s and expires is not None and expires < now + timedelta(seconds=within_s):
            detail += " — expires inside this route's %d min" % (within_s // 60)
        return AuthProbe(True, "ok", detail, expires)
    line = _auth_line_in(live.stderr, live.stdout, result)
    if line:
        return AuthProbe(False, "auth", "the executor's login was refused when used: \"%s\"" % line, expires)
    if live.returncode != 0:
        err = _first_line(live.stderr or live.stdout)
        flag = next((f for f in _LIVE_FLAGS if f in err), None)
        if flag and any(m in err for m in _FLAG_REJECTED):
            return _env_live("the claude CLI rejected %s — exit %d: %s" % (flag, live.returncode, err))
        return _env_live("exit %d: %s" % (live.returncode, err))
    return _env_live("is_error true" if isinstance(out, dict) else "its output is not a JSON object")


def checked_by_daemon(env: Optional[Mapping[str, str]] = None, now: Optional[datetime] = None) -> Optional[str]:
    """EXECUTOR_AUTH_CHECKED when the daemon set it for this route: it parses and is at most CHECKED_MAX_AGE_S old.
    Unparseable, future or older (a stale export, an inherited value) reads as unset — the caller probes itself."""
    v = (os.environ if env is None else env).get(CHECKED_VAR)
    t = _parse_iso(v)
    if t is None:
        return None
    age = ((now or datetime.now(timezone.utc)) - t).total_seconds()
    return v.strip() if 0 <= age <= CHECKED_MAX_AGE_S else None


def auth_failure_line(executor_output: str) -> Optional[str]:
    """G-C4: the first line of a short executor output (at most AUTH_FAILURE_MAX_LINES non-empty lines) that carries an
    AUTH_FAILURE_LINES marker; None otherwise — a working session that merely mentions OAuth is never classified."""
    lines = [l.strip() for l in (executor_output or "").splitlines() if l.strip()]
    if len(lines) > AUTH_FAILURE_MAX_LINES:
        return None
    return next((l for l in lines if any(m in l for m in AUTH_FAILURE_LINES)), None)

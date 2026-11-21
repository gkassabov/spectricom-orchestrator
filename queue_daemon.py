#!/usr/bin/env python3
"""
SPECTRICOM QUEUE DAEMON v1.0
==============================
Background thread that watches ~/spectricom-orchestrator/queue/ for batch files
and fires them sequentially through the orchestrator.

D-256: AAI Layer A — subscription billing only.
D-184: Inherits orchestrator safety gates (rate limiter, deps, approval).

Integrated into orch-dashboard.py v5 as a background thread.
Can also run standalone for testing:
  python3 queue_daemon.py              # run daemon — PAUSED at start when work is queued (start:queue-non-empty)
  python3 queue_daemon.py --start-running   # run daemon, firing the queue at once (the pre-C2 start)
  python3 queue_daemon.py enqueue <f>  # copy batch to queue/
  python3 queue_daemon.py status [--json]   # show queue state (line 1: daemon_status, paused_reason, paused_at,
                                            # and a paused daemon's notice: next brief, the resume command;
                                            # --json: the JSON alone)
  python3 queue_daemon.py pause        # ask the RUNNING daemon to pause (control file; no restart)
  python3 queue_daemon.py resume [--reset-consecutive] [--reason <paused_reason>]   # ask it to resume the pause
                                       # it is in when asked (or the one named); a pause it was not asked about
                                       # is not lifted — the request expires (ORCH-CONTROL-SCOPE-1)
  python3 queue_daemon.py config <key> <value>   # max_consecutive | cooldown_seconds | stop_on_failure,
                                                 # no daemon running; anything else is refused, exit 1
  python3 queue_daemon.py check        # boot assert B6: queued briefs whose route already merged
  python3 queue_daemon.py check-logs   # ORCH-STDOUT-1: recorded routes without a readable log
  python3 queue_daemon.py kill [--reason "<text>"]   # ORCH-TONI-GUARDS-1: write KILL (every fire's tool calls are
                                       # denied, nothing fires), then end the running fire's process groups
  python3 queue_daemon.py unkill --reason "<text>"   # remove KILL; logged, with the reason, in logs/kill-switch.log

  ORCH-GATE-COST-1 D4: a repo with `full_gate_nightly: "HH:MM"` in config/repos.yaml gets
  `orchestrator.py full-gate --repo <it>` once a local day, between routes, while running and idle;
  `status` line 1 names each repo's last full-gate result.
"""

import os, re, sys, json, time, shlex, shutil, signal, threading, subprocess
from pathlib import Path
from datetime import datetime, time as dtime, timezone
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import admission   # [ORCH-CAPACITY-1] C1: whether a route may start now; C4: the wall it runs under
import executor_auth   # [ORCH-EXECUTOR-AUTH-PROBE-1] G-C2: is the executor logged in, once per fire after admission
import prefire     # [ORCH-DEPENDS-ON-1] D4: a brief's `## Depends-on:` routes, judged as A11 judges them
import ledger_chain      # [ORCH-LEDGER-CHAIN-1] (623): kill, unkill, override and release-hold append to logs/ledger.jsonl
# QUEUE-RETIRE-1: one implementation of the trunk invariant, shared by the boot path and the
# tests. It lives with the other boot asserts; nothing here reimplements it.
from canon_assert import (DEFAULT_EXECUTOR_EFFORT, DEFAULT_EXECUTOR_MODEL, EXECUTOR_ENV,
                          GateLogViolation, QueueRepo, Violation, check_gate_log_invariants,
                          check_queue_trunk_invariants, executor_default, queue_header)

ORCH_DIR = Path.home() / "spectricom-orchestrator"
QUEUE_DIR = ORCH_DIR / "queue"
QUEUE_DONE = QUEUE_DIR / "done"
QUEUE_FAILED = QUEUE_DIR / "failed"
QUEUE_STATE = ORCH_DIR / "queue-state.json"
LOG_DIR = ORCH_DIR / "logs"   # the same root orchestrator.py writes to
ORCHESTRATOR = ORCH_DIR / "orchestrator.py"
REPOS_CONFIG = ORCH_DIR / "config" / "repos.yaml"
# [ORCH-HANDBACK-STOP-STATUS-1] G-6: orchestrator.py's EXIT_STOPPED, mirrored (the daemon does not import
# orchestrator.py; tests/test_handback_stop_status.py pins the two equal). Ran clean, merged as `passed` would,
# but the handback's status line says STOP / PARTIAL.
EXIT_STOPPED = 5
# [ORCH-MERGE-HOLD-1] (route 757): orchestrator.py's EXIT_HELD, mirrored (pinned equal by tests/test_merge_hold.py) — a
# green route held for a human merge: its brief goes to queue/held/merge-hold/, no pause, nothing merged.
EXIT_HELD = 6

# S7-CORE-16 [QUEUE-PAUSE-OPAQUE]. The CLI is another process: it cannot touch the daemon's memory, so
# it leaves a request in the CONTROL FILE (state/queue-control.json, a monotonic `id`) and the daemon
# applies it at its next poll and acknowledges it by writing the id back into queue-state.json
# (`control_ack`). One writer per file: the CLI writes the control file, the daemon writes the state.
CONTROL_FILE_NAME = "queue-control.json"
PAUSED_POLL_S = 5          # a paused daemon polls this often; `resume` lands within one interval
CONTROL_ACK_WAIT_S = 15    # how long `pause` / `resume` wait for the acknowledgement
# What only the running daemon knows. A CLI process that saves state (enqueue, clear, a script's
# reset) writes these back as it found them, never its own — it is not the daemon.
DAEMON_OWNED_KEYS = ("daemon_status", "started_at", "current_batch", "paused_reason", "paused_at",
                     "pid", "control_ack", "control_result", "waiting", "full_gate_nightly", "full_gate_running",
                     "depends_waiting")
# [ORCH-LANE-1] O2 · S7-CORE-19: 104 sat unfired behind `[QUEUE] PAUSED — max-consecutive:10`, a line in the
# daemon log and nowhere else, until Gemma read that log. Every pause the daemon takes writes its NOTICE
# here (reason, at, next brief, the exact resume command) and sends it to Slack when a webhook is
# configured; `status` shows it on line 1; leaving the pause removes it. The daemon is its one writer.
PAUSE_NOTICE_NAME = "queue-paused.json"

# [ORCH-CONTROL-SCOPE-1] S7-CORE-18 L-46: a restarted daemon fired the first queued brief at once (95, out
# of order). A start with work queued is a pause, until an operator resumes it or starts it --start-running.
START_PAUSED_REASON = "start:queue-non-empty"
USAGE = ("Usage: python3 queue_daemon.py [--start-running] | enqueue <file> | status [--json] | pause | "
         "resume [--reset-consecutive] [--reason <paused_reason>] | config <key> <value> | check | check-logs "
         "| clear | kill [--reason \"<text>\"] | unkill --reason \"<text>\" | override <repo> <route branch> "
         "--verdict <V> --by <approver> --reason \"<text>\" | release-hold <repo> <route branch> --by <approver> "
         "--reason \"<text>\"\n  With no command it runs the daemon "
         "loop: paused at start when work is queued; --start-running fires the queue at once.")

# [ORCH-TONI-GUARDS-1] (S7-CORE-33) The kill switch.
#  · `kill` writes ORCH_DIR/KILL, then ends the running fire's process groups.
#  · executor/hooks/kill_switch.sh, in every executor/settings/<repo>.json, denies every tool call of a fire while
#    KILL exists.
#  · The daemon fires nothing while KILL exists.
#  · `unkill --reason` removes KILL.
# Every kill and unkill is one line, printed and appended to logs/kill-switch.log.
KILL_FILE_NAME = "KILL"
KILL_LOG_NAME = "kill-switch.log"
KILL_GRACE_S = 5.0          # SIGTERM to each of the fire's process groups; SIGKILL to what is left after this
NO_REASON = "(no reason given)"


def kill_file() -> Path:
    """[ORCH-TONI-GUARDS-1] ORCH_DIR/KILL, resolved per call like control_file(). The hook's default state dir is
    $HOME/spectricom-orchestrator, the same dir as ORCH_DIR."""
    return ORCH_DIR / KILL_FILE_NAME


def read_kill() -> Optional[dict]:
    """None when there is no KILL. Otherwise its JSON ({} when it is empty, not JSON or not a file). The hook
    denies on existence alone."""
    p = kill_file()
    if not (p.exists() or p.is_symlink()):
        return None
    return _read_json(p) if p.is_file() else {}


def control_file() -> Path:
    """Resolved per call, not at import: ORCH_DIR is patched in tests and the file must follow it."""
    return ORCH_DIR / "state" / CONTROL_FILE_NAME


def pause_notice_file() -> Path:
    """[ORCH-LANE-1] O2: state/queue-paused.json, resolved per call like control_file()."""
    return ORCH_DIR / "state" / PAUSE_NOTICE_NAME


def resume_command(reason: str) -> str:
    """[ORCH-LANE-1] O2: the command that lifts THIS pause, runnable as written: from the daemon's dir,
    naming the pause (`--reason`, so it cannot lift a later one — ORCH-CONTROL-SCOPE-1 C1), and resetting
    the count when the pause is the count's."""
    reset = " --reset-consecutive" if reason.startswith("max-consecutive:") else ""
    return f"cd {shlex.quote(str(ORCH_DIR))} && python3 queue_daemon.py resume{reset} --reason {shlex.quote(reason)}"


def pause_notice_text(n: dict) -> str:
    """[ORCH-LANE-1] O2: the notice as one Slack message."""
    return (f":double_vertical_bar: Spectricom queue PAUSED — {n.get('reason')} (since {n.get('at')}). "
            f"Next brief: {n.get('next_brief') or '(queue empty)'}. Nothing fires until: `{n.get('resume')}`"
            + (f" — {n['detail']}" if n.get("detail") else ""))   # [ORCH-EXECUTOR-AUTH-PROBE-1] G-C2


def notify_slack(text: str) -> str:
    """[ORCH-LANE-1] O2: `text` through slack_notify.send_slack when a webhook is configured — its
    slack-webhook.json beside the queue, where `slack_notify.py set-webhook` writes it. Never raises;
    returns what happened, in words, for the daemon log and the notice."""
    try:
        import slack_notify
    except Exception as e:
        return f"Slack not sent (slack_notify unavailable: {e})"
    if not (ORCH_DIR / slack_notify.WEBHOOK_FILE.name).is_file():
        return f"Slack not configured (no {slack_notify.WEBHOOK_FILE.name} in {ORCH_DIR}) — not sent"
    try:
        return "sent to Slack" if slack_notify.send_slack(text) else "Slack send failed"
    except Exception as e:
        return f"Slack send failed ({e})"


def _write_json_atomic(path, data) -> None:
    """Write JSON so no reader ever sees it half-written: a temp file beside it (per process and thread),
    then os.replace. queue-state.json was written in place, and a reader that caught it mid-write read
    nothing (test_queue_pause TestResume, intermittently, at 8d962c5)."""
    path = Path(path)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        tmp.write_text(json.dumps(data, indent=2, default=str))
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)      # gone after a replace; a failed write leaves no litter


def _read_json(path) -> dict:
    """The JSON object at `path`, or {} when it is absent, unreadable, mid-write or not an object."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_persisted_state() -> dict:
    """queue-state.json as the daemon last wrote it — what `status`, `pause` and `resume` read."""
    return _read_json(QUEUE_STATE)


def pause_notice_for(st: dict) -> Optional[dict]:
    """[ORCH-LANE-1] O2: the notice in state/queue-paused.json when it is the daemon's pause now — `st`
    (queue-state.json) says paused, for the same reason; None otherwise: a stale notice is not shown."""
    n = _read_json(pause_notice_file())
    return n if n and st.get("daemon_status") == "paused" and n.get("reason") == st.get("paused_reason") else None


def pause_notice_line(n: dict) -> str:
    """[ORCH-LANE-1] O2: what `status` adds to line 1 for a paused daemon."""
    return (f"⏸ next brief {n.get('next_brief') or '- (queue empty)'} · resume: {n.get('resume')} · "
            f"{n.get('slack') or 'Slack pending'}")


# [EXECUTOR-DEFAULT-1] S7-CORE-16 · D-S7CORE15-01. A brief with no `#!queue model=… effort=…` header
# runs canon_assert's one default, or TONI_MODEL / TONI_EFFORT set at daemon start. queue-state.json
# persists the model/effort a daemon ran with, but a later daemon never APPLIES them: no command an
# operator runs sets them, so a persisted value only records what an earlier daemon ran with — the
# way claude-fable-5-1 outlived its default across restarts (LESSONS S7-CORE-14 L-8). The default
# wins; the difference is reported once at start.
EXECUTOR_KEYS = ("model", "effort")


def _executor_of(state: dict) -> dict:
    """The model/effort in a persisted state's `config` — {} when there are none."""
    cfg = state.get("config")
    return {k: cfg[k] for k in EXECUTOR_KEYS if k in cfg} if isinstance(cfg, dict) else {}


def executor_default_line(persisted: dict, config: dict, env) -> str:
    """[EXECUTOR-DEFAULT-1] the one `🛡 executor-default:` line a daemon start prints: what a brief
    with no header fires with, where that came from, and any persisted value it did not use."""
    default = {"model": DEFAULT_EXECUTOR_MODEL, "effort": DEFAULT_EXECUTOR_EFFORT}

    def _pair(values: dict, keys) -> str:   # `claude-x effort=y`, naming only `keys`
        return " ".join(values[k] if k == "model" else f"{k}={values[k]}" for k in keys)

    from_env = [f"{EXECUTOR_ENV[k]}={env[EXECUTOR_ENV[k]]}" for k in EXECUTOR_KEYS if env.get(EXECUTOR_ENV[k])]
    using = (f"using {_pair(config, EXECUTOR_KEYS)} ("
             + (f"{', '.join(from_env)} set at daemon start" if from_env else "the default") + ")")
    stale = [k for k in EXECUTOR_KEYS if k in persisted and persisted[k] != default[k]]
    if not stale:
        return f"🛡 executor-default: {using}"
    return (f"🛡 executor-default: persisted {_pair(persisted, stale)} ≠ default {_pair(default, stale)} "
            f"— {using}; the persisted value is not applied (no command sets it — it records what an "
            f"earlier daemon ran with, L-8)")


# [ORCH-LEAN-GATE-1] (D-S7CORE54-77; WASTE-REPORT 2026-11-16: xhigh cost 2.2 h a week, no measured outcome gain) a
# header's `effort=xhigh` is honoured only when the brief's `## Executor:` line names xhigh and gives its reason
# (`Why:`, D-S7CORE35-09: safety, clinical-logic or privacy routes); otherwise the route fires at high, said in one line.
XHIGH_REASON_RE = re.compile(r"^##\s*Executor:[^\n]*\bxhigh\b[^\n]*\bWhy:\s*\S", re.MULTILINE | re.IGNORECASE)


def header_effort(path, effort: str) -> tuple:
    """(the effort the route fires with, the line saying a downgrade, or None)."""
    if str(effort).strip().lower() != "xhigh":
        return effort, None
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    if XHIGH_REASON_RE.search(text):
        return effort, None
    return "high", (f"[QUEUE] effort: {Path(path).name} asks effort=xhigh with no `## Executor: … xhigh … Why: …` "
                    f"line — fired at high (ORCH-LEAN-GATE-1, D-S7CORE35-09)")


# [ORCH-YORSIE-SAFETY-1] S7-CORE-17 · Yorsie PDLC plan Phase 0. A brief names its repo in its `#!queue repo=…`
# header or it is refused: moved to queue/failed/ with this reason, nothing fired, and the queue goes on.
# There is no daemon default — QUEUE_REPO and a persisted `config.repo` (the old "else clinical-mp") are
# not read; a start reports any it found.
NO_REPO_REFUSAL = "no repo= in #!queue header — refused, nothing fired"


def repo_rule_line(persisted_repo, env) -> str:
    """[ORCH-YORSIE-SAFETY-1] the one `🛡 repo:` line a daemon start prints: the rule, and any old
    default this daemon found and does not apply."""
    old = ([f"queue-state.json repo={persisted_repo}"] if persisted_repo else []) + (
        [f"QUEUE_REPO={env['QUEUE_REPO']}"] if env.get("QUEUE_REPO") else [])
    return ("🛡 repo: a brief names its repo in its `#!queue repo=…` header; one that names none is refused to "
            "failed/, nothing fired" + (f" — {', '.join(old)} not applied (no default repo)" if old else ""))


# [CONFIG-TRUTH-1] S7-CORE-16 · route 67 "Found and left". update_config answered {"ok": True} for every
# key in config and assigned only three, so `model` was "set" and nothing changed. The three a command
# can set, each with its parser; every other key is refused and the refusal says where it comes from.
# A value that does not parse is refused, never coerced — bool("false") is True.
def _parse_count(value) -> Optional[int]:
    """A non-negative integer, given as an int or its decimal string; None for anything else."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value if value >= 0 else None
    s = value.strip() if isinstance(value, str) else ""
    return int(s) if s.isascii() and s.isdigit() else None


def _parse_flag(value) -> Optional[bool]:
    """True/False, given as a bool or as `true`/`false` in any case; None for anything else."""
    if isinstance(value, bool):
        return value
    return {"true": True, "false": False}.get(value.strip().lower()) if isinstance(value, str) else None


SETTABLE_CONFIG = {"max_consecutive": (_parse_count, "a non-negative integer"),
                   "cooldown_seconds": (_parse_count, "a non-negative integer"),
                   "stop_on_failure": (_parse_flag, "true or false")}
UNSETTABLE_CONFIG = {
    k: (f"one default in the repo (canon_assert's DEFAULT_EXECUTOR_{k.upper()}, or {EXECUTOR_ENV[k]} at daemon "
        f"start); a brief's `#!queue {k}=…` header overrides it (EXECUTOR-DEFAULT-1)") for k in EXECUTOR_KEYS}
UNSETTABLE_CONFIG.update({
    "repo": ("a brief names its repo in its `#!queue repo=…` header; one that names none is refused to "
             "queue/failed/ and nothing fires — there is no default repo (ORCH-YORSIE-SAFETY-1)"),
    "timeout_seconds": ("queue_daemon.py derives each route's wall from its brief (ORCH-CAPACITY-1 C4): the route "
                        "timeout orchestrator.py resolves (180-minute cap) + the repo's gate budget "
                        "(admission.gate_budget_s in config/repos.yaml, else the sum of its gate timeouts) + "
                        "admission.ROUTE_WALL_SLACK_S; a persisted value is not applied"),
})


def parse_config(key, value) -> tuple:
    """(value, None) for a settable key and a value that parses; (None, error) for anything else."""
    if key not in SETTABLE_CONFIG:
        why = UNSETTABLE_CONFIG.get(key, f"not a config key (settable: {', '.join(SETTABLE_CONFIG)})")
        return None, f"{key} is not settable by command: {why}"
    parse, what = SETTABLE_CONFIG[key]
    parsed = parse(value)
    return (parsed, None) if parsed is not None else (None, f"{key}: {value!r} is not {what}; nothing changed")


def _pid_alive(pid) -> Optional[bool]:
    """True / False / None, where None is "exists but not ours to signal" and counts as ALIVE — the
    safe direction. orchestrator._pid_alive's rule, restated: importing orchestrator writes a log."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return None


def _marker_slug(repo_name) -> str:
    """A repo name as its lock file names it — orchestrator._marker_repo_slug's rule, restated for the
    same reason _pid_alive is: importing orchestrator writes a log."""
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(repo_name or "").strip()).strip("-.")
    return slug or "unknown"


def status_line(st: dict) -> str:
    """P-PAUSE: the first line `status` prints — the three fields a human needs, from the file."""
    pid = st.get("pid")
    who = ("pid not recorded — a daemon started before QUEUE-PAUSE-OPAQUE" if pid is None
           else f"pid {pid} {'DEAD' if _pid_alive(pid) is False else 'alive'}")
    # [ORCH-CAPACITY-1] C1: a running daemon that admission is holding says why, on this line.
    waiting = f" | waiting: {st['waiting']}" if st.get("waiting") and st.get("daemon_status") == "running" else ""
    return (f"daemon_status={st.get('daemon_status') or '-'} paused_reason={st.get('paused_reason') or '-'} "
            f"paused_at={st.get('paused_at') or '-'} | {who} | updated_at={st.get('updated_at') or '-'}{waiting}")


# [ORCH-DEPENDS-ON-1] D4 · F-289: a brief whose unmet dependency the queue can no longer merge — in failed/, held/,
# done/ unmerged, or nowhere — is parked here with a `<stem>.reason` line beside it: not failed/, not a pause.
def depends_on_held_dir() -> Path:
    """queue/held/depends-on/, resolved per call: QUEUE_DIR is patched in tests and the tray must follow it."""
    return QUEUE_DIR / "held" / "depends-on"


def depends_held() -> list:
    """D4: the briefs parked in queue/held/depends-on/, each with its reason line — read off the disk, so `status`
    from any process shows what the daemon held."""
    tray = depends_on_held_dir()
    out = []
    for brief in sorted(tray.glob("*.md")) if tray.is_dir() else []:
        try:
            reason = (tray / f"{brief.stem}.reason").read_text(encoding="utf-8").strip()
        except OSError:
            reason = None
        out.append({"file": brief.name, "reason": reason})
    return out


def depends_on_line(waiting, held) -> str:
    """D4: what `status` adds to line 1 while a queued brief waits on a dependency, or one is held by it."""
    parts = []
    if isinstance(waiting, dict) and waiting:
        parts.append("waiting: " + ", ".join(f"{b} ← {', '.join(s)}" for b, s in waiting.items()))
    if held:
        parts.append("held in queue/held/depends-on/: " + ", ".join(h["file"] for h in held))
    return "⏳ depends-on " + " · ".join(parts) if parts else ""


# [ORCH-QUEUE-PARK-RED-1] SD-2 (George 2026-11-16 17:41 "Agree"; supersedes, for work that neither depends on a red nor
# shares its files, the "a product red stays paused for George" clause of D-S7CORE53-08 and stop-on-failure,
# D-S7CORE34-06). The route's own verdict — state.json's record of it, as `orchestrator.py run` wrote it — decides:
#   FAIL(product), SAFETY    → a SAFETY-tier brief (7 leading zeros, D-S7CORE54-74) is NOT parked: the queue stops, as
#                              today — the conservative reading of SD-2 until George widens it (verifier M-1).
#   FAIL(product), a killed  → an error naming `exit -<n>` (a leg killed, e.g. 626b's `build: exit -1` under load,
#     leg                      2026-11-16) is a machine fault the gate mislabelled: "other", the queue stops (m-6).
#   FAIL(product)            → the brief is PARKED in queue/held/parked/ with `<stem>.reason`; the queue keeps firing
#                              queued briefs that neither `## Depends-on:` it (A11 already holds those) nor share an
#                              ALLOWED path with it (same repo). A second FAIL(product) in a row pauses everything.
#   BLOCKED(environment)     → ONE automatic gates-only re-check of that route, alone and next: `<stem>-recheck.md`, the
#                              brief with a `## Re-gate of: <route branch> <tip>` line (ORCH-REGATE-GATE-ONLY-1). A red
#                              re-check, a meta-fire repo (it cannot re-gate) or a tip that cannot be read pauses.
#   … already-red-on-main    → pauses everything (main is red; ORCH-LEAN-GATE-1 T-12's signal).
#   a prefire refusal        → [ORCH-QUEUE-LOOSEN-1] (1) nothing ran: the brief is SET ASIDE in queue/held/prefire/ with
#                              `<stem>.reason`; the queue keeps firing (D-S7CORE58, George 2026-11-20 15:33 "yes all").
#   anything else            → pauses everything, as before (no record, tampered, incomplete, conflict).
# ORCH_PARK_RED=off ⇒ every red pauses, as before; stop_on_failure=false ⇒ no red pauses, as before.
PARK_ENV = "ORCH_PARK_RED"
RECHECK_SUFFIX = "-recheck"
ROUTE_STATE_NAME = "state.json"          # orchestrator.py's STATE_FILE, ORCH_DIR / "state.json"
OUTCOME_PRODUCT = "FAIL(product)"
OUTCOME_ENV = "BLOCKED(environment)"
ALREADY_RED_SIGNAL = "already-red-on-main"   # orchestrator.ALREADY_RED_SIGNAL (pinned equal by the test)
RED_PRODUCT, RED_ENV, RED_ON_MAIN, RED_OTHER = "product", "environment", "red-on-main", "other"
RED_PREFIRE = "prefire"                  # [ORCH-QUEUE-LOOSEN-1] (1) refused by HOOK-1 before anything was cut
PREFIRE_REFUSED = "pre-fire assertions failed"   # orchestrator.run_batch's error for a HOOK-1 refusal (pinned by the test)
SAFETY_TIER = re.compile(r"0{7}(?!0)")     # a SAFETY-tier brief: exactly 7 leading zeros (D-S7CORE54-74)
KILLED_LEG = re.compile(r"\bexit -\d+")    # a leg killed (signal, timeout), not an assertion that failed


def park_off() -> bool:
    return os.environ.get(PARK_ENV, "").strip().lower() == "off"


def parked_dir() -> Path:
    """queue/held/parked/, resolved per call (QUEUE_DIR is patched in tests)."""
    return QUEUE_DIR / "held" / "parked"


def prefire_held_dir() -> Path:
    """[ORCH-QUEUE-LOOSEN-1] (1) queue/held/prefire/: briefs HOOK-1 refused at fire, resolved per call."""
    return QUEUE_DIR / "held" / "prefire"


def parked_briefs() -> list:
    """The briefs parked after a product red, each with its reason line — read off the disk."""
    tray = parked_dir()
    out = []
    for brief in sorted(tray.glob("*.md")) if tray.is_dir() else []:
        try:
            reason = (tray / f"{brief.stem}.reason").read_text(encoding="utf-8").strip()
        except OSError:
            reason = None
        out.append({"file": brief.name, "reason": reason})
    return out


# [ORCH-QSTAT-PARTIAL-1] (Kanban 512): what a finished route did, read from its own log — the last `🏁 FINAL STATUS:`
# line, its gate text, the handback STATUS line and whether a merge line is there — never from the exit code alone. 341f1
# merged PARTIAL (gate PASS) and read "STOPPED, nothing merged"; 341f3 (gate BLOCKED(environment)) read "FAILED".
ROUTE_LOG_TAIL_BYTES = 262144
_FINAL_STATUS_RE = re.compile(r"🏁 FINAL STATUS: (\w+)(?: \| gate: ([^|\n]*))?")
_HANDBACK_STATUS_RE = re.compile(r"^\s*handback STATUS: (.+?)(?: —.*)?$", re.M)
_MERGED_RE = re.compile(r"🔀 Merged \S+ → \S+ \(|Self-mod auto-merge: brought \d+ commits")


def route_outcome(log_file) -> str:
    """One of: merged · merged (partial) · merged (handback <status>) · stopped, nothing merged (handback <status>) ·
    blocked (environment) · blocked (<gate>) · failed · incomplete, nothing merged · held for a human merge ·
    passed (nothing merged) · tampered · unknown (<why>). Reads the log's last ROUTE_LOG_TAIL_BYTES; changes nothing."""
    if not log_file:
        return "unknown (no log file recorded)"
    try:
        with open(log_file, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - ROUTE_LOG_TAIL_BYTES))
            text = f.read().decode("utf-8", errors="replace")
    except OSError as e:
        return f"unknown (log unreadable: {type(e).__name__})"
    finals = _FINAL_STATUS_RE.findall(text)
    if not finals:
        return "unknown (no FINAL STATUS line)"
    status, gate = finals[-1][0], (finals[-1][1] or "").strip()
    merged = bool(_MERGED_RE.search(text))
    handbacks = _HANDBACK_STATUS_RE.findall(text)
    handback = handbacks[-1].strip() if handbacks else ""
    if status == "passed":
        return "merged" if merged else "passed (nothing merged)"
    if status == "stopped":
        if merged:
            return "merged (partial)" if handback.upper().startswith("PARTIAL") else f"merged (handback {handback or 'STOP'})"
        return f"stopped, nothing merged (handback {handback or 'STOP'})"
    if status == "blocked":
        return "blocked (environment)" if not gate or "environment" in gate else f"blocked ({gate[:80]})"
    if status == "held":
        return "held for a human merge"
    if status == "incomplete":
        return "incomplete, nothing merged"
    return status


def with_outcomes(entries: list) -> list:
    """`entries` (completed / failed / stopped / held records) each with its `outcome` (route_outcome of its log)."""
    return [{**e, "outcome": route_outcome(e.get("log_file"))} for e in entries]


def route_record(batch_name: str, started_at: str) -> Optional[dict]:
    """The newest result orchestrator.py recorded for `batch_name` that started at or after `started_at` (the daemon's
    fire time), from ORCH_DIR/state.json — completed, stopped or failed. None when there is none or it cannot be read."""
    data = _read_json(ORCH_DIR / ROUTE_STATE_NAME)
    since = str(started_at or "")[:19]
    best = None
    for key in ("completed", "stopped", "held", "failed"):
        for r in data.get(key) or []:
            if (isinstance(r, dict) and r.get("batch_file") == batch_name and str(r.get("started") or "")[:19] >= since
                    and (best is None or str(r.get("started")) > str(best.get("started")))):
                best = r
    return best


def red_kind(record: Optional[dict]) -> str:
    """What a red route's recorded verdict is, for the queue: product, environment, red-on-main, or other."""
    if not record or record.get("tampered"):
        return RED_OTHER
    status, gate, error = record.get("status"), record.get("gate_outcome"), str(record.get("error") or "")
    if status == "failed" and gate == OUTCOME_PRODUCT:
        return RED_OTHER if KILLED_LEG.search(error) else RED_PRODUCT    # m-6: a killed leg stops, never parks
    if status == "failed" and not gate and error.startswith(PREFIRE_REFUSED):
        return RED_PREFIRE                                               # ORCH-QUEUE-LOOSEN-1 (1): nothing was cut
    if status == "blocked" and gate == OUTCOME_ENV:
        return RED_ON_MAIN if ALREADY_RED_SIGNAL in error else RED_ENV
    return RED_OTHER


def shared_allowed_paths(a: Path, b: Path) -> Optional[list]:
    """The ALLOWED paths two briefs share (each side's path or glob naming the other's). None when either has no
    ALLOWED FILES list — independence cannot be shown, so the caller treats it as shared."""
    pa, pb = prefire.allowed_paths(a), prefire.allowed_paths(b)
    if not pa or not pb:
        return None
    return sorted({x for x in pa for y in pb
                   if x == y or prefire.path_matches(x, y) or prefire.path_matches(y, x)})


def recheck_text(brief_text: str, branch: str, tip: str, original: str) -> str:
    """The re-check brief: the original, with `## Re-gate of: <branch> <tip>` and a one-line note after line 1."""
    first, nl, rest = brief_text.partition("\n")
    return (f"{first}\n## Re-gate of: {branch} {tip}\n"
            f"<!-- ORCH-QUEUE-PARK-RED-1 (b): the queue daemon's one automatic gates-only re-check of {original} after "
            f"BLOCKED(environment), {datetime.now().isoformat(timespec='seconds')}; no executor runs "
            f"(ORCH-REGATE-GATE-ONLY-1). -->\n{rest}")


# Verdict overrides are appended, with approver and reason, never overwritten (G-3; 626b's verdict was rewritten by
# hand with `git notes add -f` on 2026-11-16). `queue_daemon.py override` appends one line to the route tip's note;
# orchestrator._regate_check reads the newest such line before the gate's own.
OVERRIDE_PREFIX = "PRE-MERGE GATE OVERRIDE:"
OVERRIDE_VERDICTS = (OUTCOME_ENV, OUTCOME_PRODUCT)
OVERRIDE_APPROVERS = {"george": "George", "gemma": "Gemma"}   # who may re-label a verdict (verifier m-7)
OVERRIDE_USAGE = ('override <repo> <route branch> --verdict "BLOCKED(environment)"|"FAIL(product)" --by George|Gemma '
                  '--reason "<why, 3+ words>"')


def override_line(verdict: str, by: str, reason: str, at: Optional[str] = None) -> tuple:
    """(the note line, None) or (None, why it is refused)."""
    if verdict not in OVERRIDE_VERDICTS:
        return None, f"verdict must be one of {', '.join(OVERRIDE_VERDICTS)}, not {verdict!r}"
    approver = OVERRIDE_APPROVERS.get(str(by or "").strip().lower())
    if approver is None:
        return None, f"--by must name a known approver ({' or '.join(OVERRIDE_APPROVERS.values())}), not {by!r}"
    if len(re.findall(r"[A-Za-z0-9]\S*", str(reason or ""))) < 3:
        return None, "--reason needs at least 3 words"
    at = at or datetime.now().isoformat(timespec="seconds")
    one = lambda s: " ".join(str(s).split())
    return f"{OVERRIDE_PREFIX} {verdict} — by {approver}: {one(reason)} ({at})", None


def _ledger(kind: str, **fields) -> None:
    """[ORCH-LEDGER-CHAIN-1] (623): one control record; a record that cannot be written is said, never fatal."""
    try:
        rec = ledger_chain.append(kind, d=ledger_chain.ledger_dir(LOG_DIR), **fields)
    except Exception as e:
        rec, why = None, str(e)
    else:
        why = f"{ledger_chain.ledger_path(ledger_chain.ledger_dir(LOG_DIR))} not writable"
    if rec is None:
        print(f"⚠️ ledger: {kind} record not appended ({why})")


def append_override(repo: str, branch: str, verdict: str, by: str, reason: str) -> tuple:
    """(0, the line appended) or (1, why refused). `git notes append` on the branch tip, which must already carry the
    gate's own PRE-MERGE GATE note: an override is added to a recorded verdict, never written in its place."""
    line, why = override_line(verdict, by, reason)
    if why:
        return 1, why
    r = repo_route(repo)
    if r is None:
        return 1, f"repo {repo!r} is not in {REPOS_CONFIG}"
    git = lambda *a: subprocess.run(["git", "-C", str(r.path), *a], capture_output=True, text=True)
    tip = git("rev-parse", "--verify", "-q", f"refs/heads/{branch}").stdout.strip()
    if not tip:
        return 1, f"no branch {branch} in {r.path}"
    note = git("notes", "show", tip).stdout
    if not any(l.startswith("PRE-MERGE GATE: ") for l in note.splitlines()):
        return 1, f"{branch}@{tip[:7]} carries no recorded gate verdict to override"
    res = git("notes", "append", "-m", line, tip)
    if res.returncode != 0:
        return 1, f"git notes append failed: {res.stderr.strip()[:200]}"
    _ledger("override", repo=repo, branch=branch, tip=tip, verdict=verdict, by=by, reason=" ".join(str(reason).split()))
    return 0, f"{branch}@{tip[:7]}: {line}"


# [ORCH-MERGE-HOLD-1] (route 757; 621 slice 2) A green route whose diff touches a path config/merge-hold.json lists ends
# HELD (EXIT_HELD): its brief waits in queue/held/merge-hold/ with `<stem>.reason`, the branch kept, a `MERGE HOLD:` line
# on its tip's note; the queue fires the next brief (no pause). `release-hold` — George or Gemma, with a reason — appends
# `MERGE HOLD RELEASE:` to that note and queues `<stem>-release.md`, a gates-only re-gate of exactly that tip
# (ORCH-REGATE-GATE-ONLY-1), fired next; green again, it lands through the normal landing. Nothing here merges.
MERGE_HOLD_PREFIX = "MERGE HOLD:"                 # orchestrator.MERGE_HOLD_PREFIX (pinned equal by the test)
MERGE_HOLD_RELEASE_PREFIX = "MERGE HOLD RELEASE:"  # orchestrator.MERGE_HOLD_RELEASE_PREFIX (pinned equal)
RELEASE_SUFFIX = "-release"
RELEASE_USAGE = 'release-hold <repo> <route branch> --by George|Gemma --reason "<why, 3+ words>"'


def merge_hold_dir() -> Path:
    """queue/held/merge-hold/, resolved per call (QUEUE_DIR is patched in tests)."""
    return QUEUE_DIR / "held" / "merge-hold"


def held_briefs() -> list:
    """The briefs held for a human merge, each with its reason line — read off the disk."""
    tray = merge_hold_dir()
    out = []
    for brief in sorted(tray.glob("*.md")) if tray.is_dir() else []:
        try:
            reason = (tray / f"{brief.stem}.reason").read_text(encoding="utf-8").strip()
        except OSError:
            reason = None
        out.append({"file": brief.name, "reason": reason})
    return out


def release_line(by: str, reason: str, at: Optional[str] = None) -> tuple:
    """(the note line, None) or (None, why it is refused) — the approver and reason rules of `override`."""
    approver = OVERRIDE_APPROVERS.get(str(by or "").strip().lower())
    if approver is None:
        return None, f"--by must name a known approver ({' or '.join(OVERRIDE_APPROVERS.values())}), not {by!r}"
    if len(re.findall(r"[A-Za-z0-9]\S*", str(reason or ""))) < 3:
        return None, "--reason needs at least 3 words"
    at = at or datetime.now().isoformat(timespec="seconds")
    return f"{MERGE_HOLD_RELEASE_PREFIX} by {approver}: {' '.join(str(reason).split())} ({at})", None


def release_hold(repo: str, branch: str, by: str, reason: str) -> tuple:
    """(0, what was done) or (1, why refused). The branch tip must carry a `MERGE HOLD:` line and its brief must be in
    queue/held/merge-hold/. Appends the release line (never overwrites), then writes `<stem>-release.md` — the brief with
    `## Re-gate of: <branch> <tip>` — into queue/ and moves the held brief to queue/done/. Nothing is merged here."""
    line, why = release_line(by, reason)
    if why:
        return 1, why
    r = repo_route(repo)
    if r is None:
        return 1, f"repo {repo!r} is not in {REPOS_CONFIG}"
    held = next((b for b in sorted(merge_hold_dir().glob("*.md")) if r.branch_for(b.name) == branch), None) \
        if merge_hold_dir().is_dir() else None
    if held is None:
        return 1, f"no brief in {merge_hold_dir()} whose route branch is {branch}"
    git = lambda *a: subprocess.run(["git", "-C", str(r.path), *a], capture_output=True, text=True)
    tip = git("rev-parse", "--verify", "-q", f"refs/heads/{branch}").stdout.strip()
    if not tip:
        return 1, f"no branch {branch} in {r.path}"
    if not any(l.startswith(MERGE_HOLD_PREFIX) for l in git("notes", "show", tip).stdout.splitlines()):
        return 1, f"{branch}@{tip[:7]} carries no `{MERGE_HOLD_PREFIX}` line — not a held route"
    dst = QUEUE_DIR / f"{held.stem}{RELEASE_SUFFIX}.md"
    if any((d / dst.name).exists() for d in (QUEUE_DIR, QUEUE_FAILED, QUEUE_DONE)):
        return 1, f"{dst.name} exists already — one release per held tip"
    res = git("notes", "append", "-m", line, tip)
    if res.returncode != 0:
        return 1, f"git notes append failed: {res.stderr.strip()[:200]}"
    _ledger("release-hold", repo=repo, branch=branch, tip=tip, by=by, reason=" ".join(str(reason).split()),
            batch=held.name)   # [ORCH-LEDGER-CHAIN-1]: the release line is on the note now, whatever follows
    text = recheck_text(held.read_text(encoding="utf-8"), branch, tip, held.name).replace(
        "the queue daemon's one automatic gates-only re-check", "the merge-hold release (ORCH-MERGE-HOLD-1) — a gates-only re-gate", 1)
    try:
        dst.write_text(text, encoding="utf-8")
    except OSError as e:
        return 1, f"the release line was appended, but {dst} could not be written: {e}"
    _safe_move(held, QUEUE_DONE / held.name)
    try:
        (merge_hold_dir() / f"{held.stem}.reason").unlink()
    except OSError:
        pass
    return 0, f"{branch}@{tip[:7]}: {line}; queued {dst.name} (## Re-gate of: {branch} {tip[:7]})"


def _release_args(args: list) -> Optional[tuple]:
    """`<repo> <branch> --by B --reason R` → (repo, branch, B, R), or None when malformed."""
    if len(args) < 2 or args[0].startswith("--") or args[1].startswith("--"):
        return None
    repo, branch, rest, opts = args[0], args[1], args[2:], {}
    while rest:
        if len(rest) < 2 or rest[0] not in ("--by", "--reason") or rest[0] in opts:
            return None
        opts[rest[0]], rest = rest[1], rest[2:]
    if set(opts) != {"--by", "--reason"}:
        return None
    return repo, branch, opts["--by"], opts["--reason"]


def request_control(action: str, reset_consecutive: bool = False, wait_s: float = CONTROL_ACK_WAIT_S,
                    poll_s: float = 0.5, reason: Optional[str] = None) -> tuple:
    """[QUEUE-PAUSE-OPAQUE] P-RESUME, the CLI half of `pause` / `resume [--reset-consecutive]`: write
    one request with the next monotonic id, then wait up to `wait_s` for the daemon's ack.

    [ORCH-CONTROL-SCOPE-1] C1: the request carries the state it was issued against — issued_status,
    issued_paused_reason, issued_current_batch, as queue-state.json says now — and `reason`, a pause
    named explicitly (`resume --reason <r>`). The daemon applies a resume only to that pause.

    (exit code, message): 0 — acknowledged and the daemon is where it was asked to be, or a stated
    no-op (resume when not paused, pause when paused; nothing is written); 1 — not acknowledged in
    `wait_s`, or acknowledged without getting there (a bare resume against max-consecutive); 2 — no
    running daemon to ask (pid dead, or none recorded — a daemon that predates this cannot read it)."""
    st = read_persisted_state()
    status, pid = st.get("daemon_status"), st.get("pid")
    if pid is None:
        return 2, (f"daemon not confirmed running: queue-state.json has pid not recorded — a daemon started "
                   f"before QUEUE-PAUSE-OPAQUE does not read {control_file()}; restart it — nothing to {action}")
    if _pid_alive(pid) is False or status == "stopped":
        return 2, f"daemon not running (pid {pid} dead, daemon_status={status}) — nothing to {action}"
    if action == "resume" and status != "paused" and not reset_consecutive:
        return 0, f"daemon is {status}, not paused — nothing to resume"
    if action == "pause" and status == "paused":
        return 0, f"daemon already paused ({st.get('paused_reason')}) — nothing to pause"
    last = [v for v in (_read_json(control_file()).get("id"), st.get("control_ack"))
            if isinstance(v, int) and not isinstance(v, bool)]
    rid = max(last, default=0) + 1
    f = control_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps({"id": rid, "action": action, "reset_consecutive": reset_consecutive,
                               "reason": reason, "issued_status": status,
                               "issued_paused_reason": st.get("paused_reason"),
                               "issued_current_batch": (st.get("current_batch") or {}).get("file"),
                               "requested_at": datetime.now().isoformat(), "requested_by_pid": os.getpid()},
                              indent=2))
    os.replace(tmp, f)
    tick, waited = threading.Event(), 0.0
    while waited <= wait_s:
        st = read_persisted_state()
        ack = st.get("control_ack")
        if isinstance(ack, int) and ack >= rid:
            there = (st.get("daemon_status") == "paused") == (action == "pause")
            return (0 if there else 1), (f"acknowledged request {rid}: {st.get('control_result') or action}"
                                         f" — {status_line(st)}")
        tick.wait(poll_s)      # never the module's `time`: tests replace it
        waited += poll_s
    running = (st.get("current_batch") or {}).get("file")
    during = (f" — a route is running ({running}); the daemon applies the request when it returns, before "
              f"the next fire" if running else "")
    return 1, f"request {rid} ({action}) written to {f}; no acknowledgement from pid {pid} within {wait_s:g}s{during}"


def _safe_move(src, dst) -> bool:
    """Move a queue file; a source that is already gone is a NO-OP, not an exception.

    QUEUE-RETIRE-1 / T2. File retirement now belongs to the process that merged
    (orchestrator.retire_batch_file), so by the time the scheduler reaches its own move the
    brief is normally already in queue/done/. That is the expected state, not an error. These
    moves remain as the path for everything the merge never reached — a failed route, a
    cancel, a timeout, a repo whose merge never happened.

    STATE BOOKKEEPING STAYS THE SCHEDULER'S: the completed/failed entry is recorded by the
    caller either way. Only the file move became someone else's job.
    """
    src, dst = Path(src), Path(dst)
    try:
        if not src.exists():
            return False
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return True
    except Exception as e:
        print(f"[QUEUE] could not move {src.name} → {dst.parent.name}/: {e}")
        return False


def _parse_batch_header(path) -> dict:
    """The batch's `#!queue` header, through the one parser (canon_assert.queue_header), plus
    the scheduler's own warning for the case that is news to it: a batch file it cannot read."""
    hdr = queue_header(path)
    if not hdr and not os.access(str(path), os.R_OK):
        print(f"[QUEUE] could not read header of {Path(path).name}")
    return hdr


def _repo_config(name: str) -> dict:
    """The repo's entry in config/repos.yaml, or {} — the one reader of that file here."""
    try:
        repos = (yaml.safe_load(REPOS_CONFIG.read_text(encoding="utf-8")) or {}).get("repos") or {}
    except Exception as e:
        print(f"[QUEUE] could not read {REPOS_CONFIG}: {e}")
        return {}
    return repos.get(name) or {}


def repo_route(name: str) -> Optional[QueueRepo]:
    """Resolve a repo name to the (path, merge_target, branch_prefix) the trunk invariant needs.

    Read from config/repos.yaml — the one place that knows — so a repo added there needs no
    change here. An unknown name resolves to None and is skipped rather than guessed at.
    """
    r = _repo_config(name)
    if not r.get("project_dir"):
        return None
    return QueueRepo(name=name, path=Path(r["project_dir"]),
                     merge_target=r.get("merge_target", "main"),
                     branch_prefix=r.get("branch_prefix", "orch"))


def _log_subdir(repo_name: str) -> str:
    """The repo's log subdirectory — orchestrator.py's rule, `r.get("log_subdir", name)`."""
    return _repo_config(repo_name).get("log_subdir", repo_name)


# [ORCH-CAPACITY-1] C4: the daemon's clock — bound here, not read off `time` at call time (tests replace the
# module's `time`); the fake clock of tests/test_capacity.py replaces this. A route is polled this often.
ROUTE_CLOCK = time.monotonic
ROUTE_POLL_S = 30
# C4: where a route is, read off its own log — orchestrator.py's lines, the newest that matches wins.
ROUTE_PHASES = (
    ("Toni", re.compile(r"Firing Toni: ")),
    ("after Toni (commit, gate setup)", re.compile(r"Toni finished: |Toni TIMEOUT|Toni error")),
    ("build", re.compile(r"Running build gate")),
    ("SIT", re.compile(r"Running SIT post-merge|SIT batch|SIT gate")),
    ("unit", re.compile(r"Unit baseline gate \[|Unit baseline:|Unit gate")),
    ("merge", re.compile(r"Pre-merge gate.*: PASS|🔀 Merged")),
)


# [ORCH-GATE-COST-1] D4 · S7-CORE-30 (D-S7CORE29-02): the full SIT + unit suites, nightly. A repo whose repos.yaml
# entry says `full_gate_nightly: "HH:MM"` gets `orchestrator.py full-gate --repo <it> --trigger nightly` once per
# local day, at or after that time, as a scheduler step BETWEEN routes — only while the daemon is running (not
# paused) and idle (admission would admit a route now: no live route in any repo, memory above its floor). The
# run holds that repo's fire lock (orchestrator.py takes it), so no route starts over it. A window missed while
# paused or busy runs at the next idle moment the same day, or is logged SKIPPED when the day has ended.
FULL_GATE_NIGHTLY_KEY = "full_gate_nightly"
FULL_GATE_PREFIX = "full-gate-"          # orchestrator.py's FULL_GATE_PREFIX: its logs and state/full-gate-<repo>.json
FULL_GATE_CLOCK = datetime.now           # the scheduler's local clock — bound here so tests can replace it
FULL_GATE_WALL_S = 6 * 3600              # the daemon's backstop on one run; orchestrator.py's per-leg budgets end it first
_HHMM_RE = re.compile(r"([01]\d|2[0-3]):([0-5]\d)")
_said_bad_schedule = set()


def full_gate_schedule() -> dict:
    """{repo: (hour, minute, "HH:MM")} for each repos.yaml entry with a valid full_gate_nightly. A value that is
    not a quoted "HH:MM" is said once and not scheduled (unquoted, YAML reads 02:30 as the integer 150)."""
    try:
        repos = (yaml.safe_load(REPOS_CONFIG.read_text(encoding="utf-8")) or {}).get("repos") or {}
    except Exception:
        return {}
    out = {}
    for name, r in repos.items():
        if not isinstance(r, dict) or r.get(FULL_GATE_NIGHTLY_KEY) is None:
            continue
        raw = r[FULL_GATE_NIGHTLY_KEY]
        m = _HHMM_RE.fullmatch(raw.strip()) if isinstance(raw, str) else None
        if m:
            out[name] = (int(m.group(1)), int(m.group(2)), m.group(0))
        elif (name, repr(raw)) not in _said_bad_schedule:
            _said_bad_schedule.add((name, repr(raw)))
            print(f"[QUEUE] 🌙 full-gate {name}: {FULL_GATE_NIGHTLY_KEY}={raw!r} is not a quoted \"HH:MM\" — not scheduled")
    return out


def full_gate_summary() -> dict:
    """{repo: {"outcome", "at", "sha", "trigger", "log", "nightly"}} — each state/full-gate-<repo>.json the last
    full-gate wrote (nightly or on demand), and each scheduled repo (outcome None: never run)."""
    out = {}
    state_dir = ORCH_DIR / "state"
    for f in sorted(state_dir.glob(f"{FULL_GATE_PREFIX}*.json")) if state_dir.is_dir() else []:
        d = _read_json(f)
        if d:
            out[d.get("repo") or f.stem[len(FULL_GATE_PREFIX):]] = {
                k: d.get(src) for k, src in (("outcome", "outcome"), ("at", "finished_at"), ("sha", "sha"),
                                             ("trigger", "trigger"), ("log", "log"))}
    for name, (_, _, hhmm) in full_gate_schedule().items():
        out.setdefault(name, {"outcome": None})["nightly"] = hhmm
    return out


def full_gate_line(st: dict, summary: Optional[dict] = None) -> str:
    """What `status` adds to line 1: `full-gate clinical-mp: PASS 2026-10-17T02:41 a1b2c3d (nightly 02:30)` per
    repo, or `never run`, and a run the daemon has in hand. "" when no repo has a schedule or a result."""
    summary = full_gate_summary() if summary is None else summary
    running = st.get("full_gate_running") if isinstance(st.get("full_gate_running"), dict) else {}
    parts = []
    for name, s in sorted(summary.items()):
        when = f" (nightly {s['nightly']})" if s.get("nightly") else ""
        now = (f" — running now since {str(running.get('started_at') or '?')[:16]}"
               if running.get("repo") == name else "")
        if s.get("outcome"):
            parts.append(f"full-gate {name}: {s['outcome']} {str(s.get('at') or '?')[:16]} "
                         f"{str(s.get('sha') or '?')[:7]}{when}{now}")
        else:
            parts.append(f"full-gate {name}: never run{when}{now}")
    return " | ".join(parts)


def route_phase(log_path) -> str:
    """[ORCH-CAPACITY-1] C4: the phase (Toni / build / SIT / unit / …) a route's log last entered."""
    phase = "before Toni (pre-fire, branch, worktree)"
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            for line in f:
                phase = next((name for name, rx in ROUTE_PHASES if rx.search(line)), phase)
    except OSError:
        return "unknown (the route log is unreadable)"
    return phase


def route_log_path(repo_name: str, batch_name: str, when: datetime) -> Path:
    """ORCH-STDOUT-1: where a daemon-fired route's full stdout+stderr goes —
    logs/<log_subdir>/orch-<stem>-<ts>.log, beside fire_toni's toni-<stem>-<ts>.log (same
    directory, stem and timestamp shape; `orch-` says whose output it is).

    The parent is created here. If that fails the path is still returned: the open in
    _run_route then fails as a spawn error (-2), and the post-route oracle reports the
    recorded path as log-missing rather than the daemon thread dying on it.
    """
    path = LOG_DIR / _log_subdir(repo_name) / f"orch-{Path(batch_name).stem}-{when:%Y%m%d-%H%M%S}.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        print(f"[QUEUE] could not create {path.parent}: {e}")
    return path


# ── [ORCH-TONI-GUARDS-1] kill / unkill ──────────────────────────────────────────────────────────────────────────
def _proc_table() -> dict:
    """{pid: (ppid, pgid, state)} for every process /proc shows. A process that ends mid-read is left out."""
    table = {}
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            f = Path(f"/proc/{d}/stat").read_text().rsplit(")", 1)[1].split()
            table[int(d)] = (int(f[1]), int(f[2]), f[0])
        except (OSError, IndexError, ValueError):
            continue
    return table


def fire_process_groups(table: Optional[dict] = None) -> list:
    """Each live fire, and every process group in the tree under it.
    A fire is a child of a live route's orchestrator process (the pid in a running*.json marker, at the root or in
    state/) that leads its own process group, as fire_toni's Popen(preexec_fn=os.setsid) makes it.
    Every group in the tree is included because the CLI starts each Bash command in a session of its own: killing
    the fire's group alone would leave a running command behind.
    Never included: the orchestrator's group (the daemon's) or this process's.
    Returns [{"batch", "repo", "orch_pid", "leader", "groups", "pids"}]."""
    table = _proc_table() if table is None else table
    children: dict = {}
    for pid, (ppid, _pgid, _state) in table.items():
        children.setdefault(ppid, []).append(pid)
    state_dir = ORCH_DIR / "state"
    markers = sorted(ORCH_DIR.glob("running*.json")) + (sorted(state_dir.glob("running*.json"))
                                                         if state_dir.is_dir() else [])
    fires, seen, own = [], set(), os.getpgrp()
    for m in markers:
        data = _read_json(m)
        opid = data.get("pid")
        if not isinstance(opid, int) or isinstance(opid, bool) or opid not in table or table[opid][2] == "Z":
            continue
        for leader in sorted(children.get(opid, [])):
            if leader in seen or table[leader][1] != leader:
                continue
            tree, todo = [], [leader]
            while todo:
                p = todo.pop()
                tree.append(p)
                todo.extend(children.get(p, []))
            seen.update(tree)
            groups = sorted({table[p][1] for p in tree} - {own, table[opid][1]})
            fires.append({"batch": data.get("batch_id") or Path(str(data.get("batch_file") or "?")).stem,
                          "repo": data.get("repo") or "?", "orch_pid": opid, "leader": leader,
                          "groups": groups, "pids": sorted(tree)})
    return fires


def _live_groups(groups) -> list:
    """The groups in `groups` with a member that is not a zombie."""
    live = {pgid for _ppid, pgid, state in _proc_table().values() if state != "Z"}
    return [g for g in groups if g in live]


def _signal_groups(groups, sig) -> None:
    for g in groups:
        try:
            os.killpg(g, sig)
        except (ProcessLookupError, PermissionError):
            pass


def _kill_say(line: str) -> None:
    """One kill-switch line: printed, and appended to logs/kill-switch.log with a timestamp."""
    print(line)
    log = ORCH_DIR / "logs" / KILL_LOG_NAME
    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")
    except OSError as e:
        print(f"🛡 kill switch: could not append to {log}: {e}")


def kill(reason: str, grace_s: Optional[float] = None) -> int:
    """`queue_daemon.py kill [--reason "<text>"]`. Writes KILL first, so the hook denies the next tool call at once.
    A KILL already there is kept with its first reason. Then the running fire's process groups get SIGTERM, and
    SIGKILL for whatever is still alive after the grace. Exit 1 only when KILL could not be written."""
    grace = KILL_GRACE_S if grace_s is None else grace_s
    p, prior, rc = kill_file(), read_kill(), 0
    if prior is None:
        try:
            _write_json_atomic(p, {"reason": reason, "at": datetime.now().isoformat(timespec="seconds"),
                                   "by": f"queue_daemon.py kill (pid {os.getpid()})"})
            state = f"KILL written ({p})"
        except OSError as e:
            state, rc = f"KILL NOT written ({p}: {e}), so the hook does not see it", 1
    else:
        state = f"KILL already present ({p}: {prior.get('reason') or NO_REASON}, since {prior.get('at') or '?'}), kept"
    fires = fire_process_groups()
    groups = sorted({g for f in fires for g in f["groups"]})
    if not fires:
        what = "no live fire (no running*.json pid has a fire under it)"
    else:
        _signal_groups(groups, signal.SIGTERM)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline and _live_groups(groups):
            time.sleep(0.1)
        left = _live_groups(groups)
        _signal_groups(left, signal.SIGKILL)
        what = "; ".join(f"fire {f['batch']} (repo {f['repo']}, orchestrator pid {f['orch_pid']}): pgid {f['leader']}"
                         + (f" + Bash command group(s) {', '.join(str(g) for g in f['groups'] if g != f['leader'])}"
                            if len(f["groups"]) > 1 else "") for f in fires)
        what += (f" — SIGTERM; SIGKILL after {grace:g}s to {len(left)} group(s) still alive: "
                 f"{', '.join(map(str, left))}" if left else f" — SIGTERM; all gone within {grace:g}s")
    _kill_say(f"🛡 KILL — {reason}: {state}; {what}. Nothing fires until "
              f"`python3 queue_daemon.py unkill --reason \"<text>\"`")
    _ledger("kill", reason=reason, written=prior is None and rc == 0, kept_prior=prior is not None,
            fires=[f["batch"] for f in fires], groups=groups)   # [ORCH-LEDGER-CHAIN-1]
    return rc


def unkill(reason: str) -> int:
    """`queue_daemon.py unkill --reason "<text>"`: removes KILL and logs it with the reason it had. Exit 1 when KILL
    is still there afterwards."""
    p, prior = kill_file(), read_kill()
    if prior is None:
        _kill_say(f"🛡 UNKILL — {reason}: no KILL at {p}, nothing to lift")
        return 0
    try:
        if p.is_dir() and not p.is_symlink():
            p.rmdir()
        else:
            p.unlink()
    except OSError as e:
        _kill_say(f"🛡 UNKILL FAILED — {reason}: {p} not removed ({e}); every fire's tool calls stay denied")
        return 1
    _kill_say(f"🛡 UNKILL — {reason}: {p} removed (it said: {prior.get('reason') or NO_REASON}, since "
              f"{prior.get('at') or '?'}). The daemon fires again at its next poll; a stop-on-failure pause still "
              f"needs `resume`")
    _ledger("unkill", reason=reason, lifted_reason=prior.get("reason"), lifted_at=prior.get("at"))   # [ORCH-LEDGER-CHAIN-1]
    return 0


def _kill_args(cmd: str, args: list) -> Optional[str]:
    """The reason given to `kill` / `unkill`: `--reason <text>`, not blank. For unkill it is required; kill without
    it gets NO_REASON. None ⇒ usage, exit 2, nothing written."""
    if not args and cmd == "kill":
        return NO_REASON
    if len(args) == 2 and args[0] == "--reason" and args[1].strip():
        return args[1].strip()
    return None


class QueueDaemon:
    """Background queue processor for Toni batches."""

    def __init__(self):
        self.status = "idle"
        self.current_batch = None
        self.current_process = None
        self.completed = []
        self.failed = []
        self.stopped = []              # [ORCH-HANDBACK-STOP-STATUS-1] G-6: exit EXIT_STOPPED routes
        self.held = []                 # [ORCH-MERGE-HOLD-1] exit EXIT_HELD routes
        self.consecutive_count = 0
        self.started_at = None
        self.config = {
            # S7-CORE-11: raised from 10. The cap is a runaway guard, not a budget —
            # it counts across daemon restarts from the persisted state, so a queue
            # loaded with a week's increments silently stalls part-way. It did, at
            # 10, with two briefs left and nothing wrong.
            "max_consecutive": 25,
            "cooldown_seconds": 30,
            "stop_on_failure": True,
            # S7-CORE-11: the daemon predates --repo, --model and --effort, and its
            # 45-minute kill predates routes that legitimately run 40-60 min.
            # [ORCH-YORSIE-SAFETY-1] no "repo" here: a brief names its own or is refused.
            # [EXECUTOR-DEFAULT-1] canon_assert's one default, or TONI_MODEL / TONI_EFFORT at start.
            **dict(zip(EXECUTOR_KEYS, executor_default(os.environ))),
            # [ORCH-CAPACITY-1] C4: no "timeout_seconds". The fixed 11400 s killed route 122 in its unit gate,
            # inside orchestrator.py's own 162 min + gates; each route's wall is derived (admission.route_wall).
        }
        # [QUEUE-PAUSE-OPAQUE] P-PAUSE: why and since when, None while not paused; the last control
        # request applied; whether THIS object is the running daemon (run_loop sets it) — a CLI
        # object's save never overwrites DAEMON_OWNED_KEYS.
        self.paused_reason = None
        self.paused_at = None
        self.control_ack = 0
        self.control_result = None
        self.is_daemon = False
        self._held_markers = set()   # P-STALE: markers already reported HOLD, said once each
        self.persisted_executor = {}   # [EXECUTOR-DEFAULT-1] read from queue-state.json, never applied
        self.persisted_repo = None     # [ORCH-YORSIE-SAFETY-1] the old default's persisted value, never applied
        self.refused = []              # [ORCH-YORSIE-SAFETY-1] briefs refused unfired — not routes
        self.start_running = False     # [ORCH-CONTROL-SCOPE-1] C2: `--start-running` — fire a queued start at once
        self._pending_notice = None    # [ORCH-LANE-1] O2: a pause notice written, not yet sent
        self.waiting = None            # [ORCH-CAPACITY-1] C1: why admission holds the next brief, None when not
        self._waiting_said = None      # C1: the reason last logged — one line per change of reason
        self._kill_said = None         # [ORCH-TONI-GUARDS-1] the KILL last logged — one line per KILL
        self.persisted_timeout = None  # C4: a persisted timeout_seconds, reported at start, never applied
        self.depends_waiting = {}      # [ORCH-DEPENDS-ON-1] D4: {queued brief: the queued stems it waits on}
        self._depends_unmovable = set()   # D4: held briefs that would not leave queue/ — passed over, said once
        # [ORCH-GATE-COST-1] D4: per repo {"ran_day", "deferred_day", "deferred", "skipped_day", "last"} — persisted, so
        # a restart never runs a second full gate the same day; and the run in hand, None between runs
        self.full_gate = {}
        self.full_gate_running = None
        # [ORCH-QUEUE-PARK-RED-1] SD-2: the product reds since the last pass/stop (two in a row stop the queue); the
        # automatic re-check queued after a BLOCKED(environment) red (fired next, alone); briefs passed over because
        # they share ALLOWED paths with a parked brief — said once each.
        self.product_reds = []
        self.recheck = None
        self.park_waiting = {}
        self.lock = threading.Lock()
        self._ensure_dirs()
        self._load_state()

    def _ensure_dirs(self):
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        QUEUE_DONE.mkdir(parents=True, exist_ok=True)
        QUEUE_FAILED.mkdir(parents=True, exist_ok=True)

    def _load_state(self):
        if QUEUE_STATE.exists():
            try:
                data = json.loads(QUEUE_STATE.read_text())
                self.completed = data.get("completed", [])
                self.failed = data.get("failed", [])
                self.stopped = data.get("stopped", [])
                self.held = data.get("held", [])
                self.refused = data.get("refused", [])
                self.persisted_executor = _executor_of(data)
                self.persisted_repo = (data.get("config") or {}).get("repo")
                self.persisted_timeout = (data.get("config") or {}).get("timeout_seconds")
                self.config.update({k: v for k, v in (data.get("config") or {}).items()
                                    if k not in EXECUTOR_KEYS and k not in ("repo", "timeout_seconds")})
                self.consecutive_count = data.get("consecutive_count", 0)
                fg = data.get("full_gate_nightly")
                self.full_gate = fg if isinstance(fg, dict) else {}
                ack = data.get("control_ack")
                self.control_ack = ack if isinstance(ack, int) and not isinstance(ack, bool) else 0
            except Exception:
                pass

    def _save_state(self):
        try:
            data = {
                "daemon_status": self.status,
                "started_at": self.started_at,
                "current_batch": self.current_batch,
                "paused_reason": self.paused_reason,   # [QUEUE-PAUSE-OPAQUE] P-PAUSE
                "paused_at": self.paused_at,
                "pid": os.getpid(),
                "control_ack": self.control_ack,       # P-RESUME: the last request applied
                "control_result": self.control_result,
                "waiting": self.waiting,               # [ORCH-CAPACITY-1] C1
                "depends_waiting": self.depends_waiting,   # [ORCH-DEPENDS-ON-1] D4
                "full_gate_nightly": self.full_gate,   # [ORCH-GATE-COST-1] D4
                "full_gate_running": self.full_gate_running,
                "queue": [f.name for f in self._scan_queue()],
                "completed": self.completed[-30:],
                "failed": self.failed[-15:],
                "stopped": self.stopped[-15:],
                "held": self.held[-15:],
                "refused": self.refused[-15:],
                "config": self.config,
                "consecutive_count": self.consecutive_count,
                "updated_at": datetime.now().isoformat()
            }
            if not self.is_daemon:
                prior = read_persisted_state()
                data.update({k: prior.get(k) for k in DAEMON_OWNED_KEYS})
                # [EXECUTOR-DEFAULT-1] the model/effort on disk are the ones the DAEMON resolved
                data["config"] = {**self.config, **_executor_of(prior)}
            _write_json_atomic(QUEUE_STATE, data)
        except Exception:
            pass

    def _scan_queue(self):
        if not QUEUE_DIR.exists():
            return []
        return sorted(f for f in QUEUE_DIR.glob("*.md") if f.is_file())

    def get_status(self):
        with self.lock:
            queue_files = self._scan_queue()
            elapsed = None
            if self.current_batch and self.current_batch.get("started_at"):
                try:
                    st = datetime.fromisoformat(self.current_batch["started_at"])
                    elapsed = (datetime.now() - st).total_seconds()
                except Exception:
                    pass
            return {
                "daemon_status": self.status,
                "paused_reason": self.paused_reason,
                "paused_at": self.paused_at,
                "waiting": self.waiting,
                "depends_waiting": self.depends_waiting,   # [ORCH-DEPENDS-ON-1] D4
                "depends_held": depends_held(),
                "parked": parked_briefs(),                # [ORCH-QUEUE-PARK-RED-1]
                "park_waiting": dict(self.park_waiting),
                "started_at": self.started_at,
                "current_batch": self.current_batch,
                "current_elapsed_s": elapsed,
                "current_elapsed_fmt": f"{elapsed/60:.1f}m" if elapsed else None,
                "queue": [{"name": f.name, "size": f.stat().st_size} for f in queue_files],
                "queue_count": len(queue_files),
                "completed": with_outcomes(self.completed[-10:]),   # [ORCH-QSTAT-PARTIAL-1] each with its outcome
                "failed": with_outcomes(self.failed[-5:]),   # [ORCH-QSTAT-PARTIAL-1] each with its outcome
                "stopped": with_outcomes(self.stopped[-5:]),   # [ORCH-QSTAT-PARTIAL-1] each with its outcome
                "held": with_outcomes(self.held[-5:]),   # [ORCH-QSTAT-PARTIAL-1] each with its outcome
                "merge_held": held_briefs(),              # [ORCH-MERGE-HOLD-1]
                "refused": self.refused[-5:],
                "config": self.config,
                "consecutive_count": self.consecutive_count,
                "completed_total": len(self.completed),
                "failed_total": len(self.failed),
                "stopped_total": len(self.stopped),
                "held_total": len(self.held)
            }

    def enqueue(self, batch_path):
        src = Path(batch_path).expanduser().resolve()
        if not src.exists():
            return {"ok": False, "error": f"File not found: {batch_path}"}
        if not src.name.endswith(".md"):
            return {"ok": False, "error": "Only .md batch files accepted"}
        # [ORCH-PREFIRE-DRYRUN-GATE-1] Kanban 727, SD-6(a): a brief without the author's pasted dry run is not copied
        # in — prefire's DRY, the same reading the fire applies. PREFIRE_DRYRUN=off skips it (said by the fire).
        problems = prefire.enqueue_problems(src, REPOS_CONFIG)
        if problems:
            return {"ok": False, "error": f"{src.name} not enqueued — " + " · ".join(problems)}
        self._ensure_dirs()
        dst = QUEUE_DIR / src.name
        shutil.copy2(str(src), str(dst))
        self._save_state()
        return {"ok": True, "queued": src.name, "queue_count": len(self._scan_queue())}

    def _mark_paused(self, reason: str, say: bool = True, detail: Optional[str] = None):
        """[QUEUE-PAUSE-OPAQUE] P-PAUSE: every transition into `paused` says why and since when. The
        caller saves, holding the lock where it has to — this takes none. `say=False`: the caller prints
        its own line (a start says once which way it went). `detail`: the notice's `detail` key
        ([ORCH-EXECUTOR-AUTH-PROBE-1] G-C2)."""
        self.status = "paused"
        self.paused_reason = reason
        self.paused_at = datetime.now().isoformat()
        if say:
            print(f"[QUEUE] PAUSED — {reason}. Resume without a restart: {resume_command(reason)}")
        self._write_pause_notice(detail)

    def _write_pause_notice(self, detail: Optional[str] = None):
        """[ORCH-LANE-1] O2: the notice of the pause just taken, on disk at once; Slack follows from
        run_loop's next poll (_send_pause_notice), never under the lock. Only the daemon announces: a CLI
        object's pause is not the daemon's (DAEMON_OWNED_KEYS)."""
        if not self.is_daemon:
            return
        queue = self._scan_queue()
        notice = {"reason": self.paused_reason, "at": self.paused_at,
                  "next_brief": queue[0].name if queue else None, "queued": len(queue),
                  "resume": resume_command(self.paused_reason), "pid": os.getpid(), "slack": None}
        if detail:
            notice["detail"] = detail
        try:
            pause_notice_file().parent.mkdir(parents=True, exist_ok=True)
            _write_json_atomic(pause_notice_file(), notice)
        except OSError as e:
            print(f"[QUEUE] could not write {pause_notice_file()}: {e}")
        self._pending_notice = notice

    def _send_pause_notice(self):
        """[ORCH-LANE-1] O2: send the notice _write_pause_notice left, outside the lock — a Slack call can
        take its whole timeout — and record what happened in the notice while that pause still stands."""
        notice, self._pending_notice = self._pending_notice, None
        if not notice:
            return
        notice["slack"] = notify_slack(pause_notice_text(notice))
        if self.status == "paused" and self.paused_reason == notice["reason"]:
            try:
                _write_json_atomic(pause_notice_file(), notice)
            except OSError:
                pass
        print(f"[QUEUE] 📣 pause notice {pause_notice_file()} — {notice['slack']}")

    def _clear_pause_notice(self):
        """[ORCH-LANE-1] O2: leaving the pause removes its notice, and an unsent one is not sent."""
        self._pending_notice = None
        if self.is_daemon:
            try:
                pause_notice_file().unlink(missing_ok=True)
            except OSError as e:
                print(f"[QUEUE] could not remove {pause_notice_file()}: {e}")

    def pause(self, reason: str = "operator"):
        with self.lock:
            if self.status in ("running", "idle"):
                self._mark_paused(reason)
                self._save_state()
        return {"ok": True, "status": self.status}

    def resume(self):
        with self.lock:
            if self.status == "paused":
                self.status = "running"
                self.paused_reason = self.paused_at = None
                self._clear_pause_notice()
                self._save_state()
        return {"ok": True, "status": self.status}

    def cancel_current(self):
        with self.lock:
            if self.current_process and self.current_process.poll() is None:
                self.current_process.terminate()
                try:
                    self.current_process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    self.current_process.kill()
            if self.current_batch:
                batch_file = QUEUE_DIR / self.current_batch["file"]
                _safe_move(batch_file, QUEUE_FAILED / batch_file.name)
                log_file = self.current_batch.get("log_file")
                if log_file:
                    # ORCH-STDOUT-1: the route's own log says why it stopped. Appended, so it
                    # lands beside whatever _run_route's trailer writes when wait() returns.
                    try:
                        with open(log_file, "a", encoding="utf-8") as lf:
                            lf.write(f"\n{'='*60}\nCancelled: {datetime.now().isoformat()}\n"
                                     f"Exit: -9 (cancelled by user)\n")
                    except OSError as e:
                        print(f"[QUEUE] could not write cancel trailer to {log_file}: {e}")
                self.failed.append({
                    "file": self.current_batch["file"],
                    "exit_code": -9,
                    "reason": "cancelled by user",
                    "finished_at": datetime.now().isoformat(),
                    "started_at": self.current_batch.get("started_at"),
                    "log_file": log_file,
                })
                self.current_batch = None
                self.current_process = None
                self._save_state()
        return {"ok": True, "status": "cancelled"}

    def clear_queue(self):
        with self.lock:
            removed = 0
            for f in self._scan_queue():
                f.unlink()
                removed += 1
            self._save_state()
        return {"ok": True, "removed": removed}

    def reset_consecutive(self):
        with self.lock:
            self.consecutive_count = 0
            if self.status == "paused":
                self.status = "running"
                self.paused_reason = self.paused_at = None
                self._clear_pause_notice()
            self._save_state()
        return {"ok": True, "consecutive_count": 0, "status": self.status}

    def update_config(self, key, value):
        """[CONFIG-TRUTH-1] set one of SETTABLE_CONFIG, or refuse and say why. A refusal writes nothing."""
        parsed, error = parse_config(key, value)
        if error:
            return {"ok": False, "error": error}
        with self.lock:
            self.config[key] = parsed
            self._save_state()
            return {"ok": True, "config": self.config}

    def queue_repos(self) -> list[QueueRepo]:
        """The repos this queue's briefs actually name — `#!queue repo=…`; a brief that names none
        adds none ([ORCH-YORSIE-SAFETY-1]: it will be refused, not fired). A queue is multi-repo; the
        trunk invariant is per repo, so it is asked once per repo rather than once per brief."""
        names = {n for f in self._scan_queue() if (n := _parse_batch_header(f).get("repo"))}
        return [r for r in (repo_route(n) for n in sorted(names)) if r is not None]

    def find_merged_briefs(self) -> list[Violation]:
        """Every queued brief whose route is already on its repo's merge target. Empty = clean."""
        out = []
        for repo in self.queue_repos():
            out.extend(check_queue_trunk_invariants(QUEUE_DIR, repo))
        return out

    def find_missing_gate_logs(self) -> list[GateLogViolation]:
        """ORCH-STDOUT-1 over the recorded history: every completed/failed/stopped entry whose log is
        not a readable, non-empty file. Empty = clean. Report only — `check-logs` calls this."""
        return check_gate_log_invariants(self.completed + self.failed + self.stopped)

    def retire_merged_briefs(self) -> int:
        """Boot assert B6, automated (QUEUE-RETIRE-1 / T3). Returns the number retired.

        This is the RECOVERY half. T1 makes the merging process retire its own brief, which is
        what closes the RESOLVER-1 window; a kill *inside* that window — or any brief that
        merged before this change shipped — still leaves an already-merged route's brief in
        queue/, and that is a state the merge itself could not have finished. Only a check
        against git can clear it, and it runs before the first batch so a restart cannot
        re-fire a merged route.

        IDEMPOTENT: the brief is moved to queue/done/, which the predicate does not scan, so a
        second start finds nothing. It moves, never deletes — a wrong retirement is recoverable
        from queue/done/ and this says which brief and which commit, every time.
        """
        retired = 0
        for v in self.find_merged_briefs():
            if _safe_move(v.path, QUEUE_DONE / v.brief):
                retired += 1
                print(f"[QUEUE] retired (route already merged): {v}")
        if retired:
            print(f"[QUEUE] {retired} already-merged brief(s) retired before the first batch (B6)")
        return retired

    def _refuse(self, brief: Path, reason: str):
        """[ORCH-YORSIE-SAFETY-1] move a brief that cannot fire to queue/failed/ and say why. Nothing
        fired, so it is not a route: no completed/failed entry, no stop_on_failure, no consecutive
        count. One that will not leave queue/ would be refused again at once, forever — that pauses."""
        _safe_move(brief, QUEUE_FAILED / brief.name)
        print(f"[QUEUE] REFUSED: {brief.name} — {reason}")
        with self.lock:
            self.refused.append({"file": brief.name, "reason": reason, "refused_at": datetime.now().isoformat()})
            if brief.exists():
                self._mark_paused(f"refused-unmovable:{brief.name}")
            self._save_state()

    def _next_brief(self, queue: list) -> Optional[Path]:
        """[ORCH-DEPENDS-ON-1] D4 · F-289: the brief to fire — the first in filename order whose `## Depends-on:`
        routes are all merged, judged by prefire.dependency_status (A11's own reading: canon_assert.route_merged).

        A brief whose unmet dependencies are all still in queue/ waits where it is — said WAITING once, no pause —
        and the next brief is taken. One with an unmet dependency the queue can no longer merge (failed/, held/,
        done/ unmerged, nowhere) is parked in queue/held/depends-on/ on the way (_hold_depends_on). A brief with
        no line is taken as today; so is one whose line cannot be read — A11 refuses it at the fire. None: nothing
        may fire now."""
        names = {b.name for b in queue}
        waiting = {b: s for b, s in self.depends_waiting.items() if b in names}
        self._depends_unmovable &= names
        # [ORCH-QUEUE-PARK-RED-1] (b): the automatic re-check fires next, before any other brief
        if self.recheck:
            if self.recheck in names:
                return QUEUE_DIR / self.recheck
            print(f"[QUEUE] re-check {self.recheck} is no longer in queue/ — not fired")
            self.recheck = None
        self.park_waiting = {b: w for b, w in self.park_waiting.items() if b in names}
        chosen = None
        for brief in queue:
            try:
                deps, unreadable = prefire.dependency_status(brief, QUEUE_DIR, repo_route)
            except Exception as e:      # never the loop's end: the fire's own A11 judges it again
                print(f"[QUEUE] {brief.name}: its '## Depends-on:' could not be judged ({e}) — taken as it stands")
                deps, unreadable = [], str(e)
            unmet = [] if unreadable else [d for d in deps if not d.merged]
            if not unmet:
                waiting.pop(brief.name, None)
                held_by = self._parked_overlap(brief)          # [ORCH-QUEUE-PARK-RED-1] (a)
                if held_by:
                    if self.park_waiting.get(brief.name) != held_by:
                        print(f"[QUEUE] 🅿 {brief.name}: WAITING — {held_by}; not fired while that brief is parked "
                              f"(queue/held/parked/); the next independent brief fires")
                    self.park_waiting[brief.name] = held_by
                    continue
                self.park_waiting.pop(brief.name, None)
                chosen = brief
                break
            if all(d.queued for d in unmet):
                if brief.name not in waiting:
                    print(f"[QUEUE] ⏳ {brief.name}: WAITING depends-on {'; '.join(map(str, unmet))} — not fired "
                          f"until it merges; the next eligible brief fires")
                waiting[brief.name] = [d.stem for d in unmet]
                continue
            waiting.pop(brief.name, None)
            self._hold_depends_on(brief, unmet)
        if waiting != self.depends_waiting:
            with self.lock:
                self.depends_waiting = waiting
                self._save_state()
        return chosen

    def _parked_overlap(self, brief: Path) -> Optional[str]:
        """[ORCH-QUEUE-PARK-RED-1] (a): why `brief` waits for a parked brief of its own repo — the ALLOWED paths they
        share, or that either has no ALLOWED FILES list (independence not shown) — or None: it may fire."""
        tray = parked_dir()
        if not tray.is_dir():
            return None
        repo = _parse_batch_header(brief).get("repo")
        for p in sorted(tray.glob("*.md")):
            if _parse_batch_header(p).get("repo") != repo:
                continue
            shared = shared_allowed_paths(brief, p)
            if shared is None:
                return f"parked {p.name}: an ALLOWED FILES list is missing, so the two are not shown independent"
            if shared:
                return f"shares {', '.join(shared[:4])}{' …' if len(shared) > 4 else ''} with parked {p.name}"
        return None

    def _park(self, brief: Path, record: Optional[dict]) -> bool:
        """(a): move a FAIL(product) brief to queue/held/parked/ with `<stem>.reason`. False when it would not move."""
        tray = parked_dir()
        repo = _parse_batch_header(brief).get("repo")
        r = repo_route(repo) if repo else None
        branch = r.branch_for(brief.name) if r else "?"
        error = " ".join(str((record or {}).get("error") or "").split())[:400]
        reason = (f"PARKED after FAIL(product) — {error}. Route branch {branch} is kept. Briefs that neither depend on "
                  f"this one nor share its ALLOWED paths keep firing; those that do wait. Landing it is George's go "
                  f"(a re-fire or re-land); moving this brief out of queue/held/parked/ releases the waiters.")
        if not _safe_move(brief, tray / brief.name):
            return False
        try:
            (tray / f"{brief.stem}.reason").write_text(f"{datetime.now().isoformat()} {brief.name}: {reason}\n",
                                                       encoding="utf-8")
        except OSError as e:
            print(f"[QUEUE] could not write {brief.stem}.reason in {tray}: {e}")
        print(f"[QUEUE] 🅿 PARKED: {brief.name} — FAIL(product); {branch} kept → {tray}/ — independent work keeps "
              f"firing (SD-2)")
        return True

    def _queue_recheck(self, src: Path, name: str) -> Optional[str]:
        """(b): write `<stem>-recheck.md` — the brief with `## Re-gate of: <route branch> <tip>` — into queue/ and mark
        it to fire next. None when queued; else why no automatic re-check is possible (the caller stops the queue)."""
        repo = _parse_batch_header(src).get("repo")
        if _repo_config(repo).get("meta_fire"):
            return f"repo {repo} is the meta-fire lane, which does not re-gate gates-only (ORCH-REGATE-GATE-ONLY-1)"
        r = repo_route(repo) if repo else None
        if r is None:
            return f"repo {repo!r} is not in {REPOS_CONFIG}"
        branch = r.branch_for(name)
        res = subprocess.run(["git", "-C", str(r.path), "rev-parse", "--verify", "-q", f"refs/heads/{branch}"],
                             capture_output=True, text=True)
        tip = res.stdout.strip()
        if not tip:
            return f"no route branch {branch} in {r.path}"
        dst = QUEUE_DIR / f"{Path(name).stem}{RECHECK_SUFFIX}.md"
        if any((d / dst.name).exists() for d in (QUEUE_DIR, QUEUE_FAILED, QUEUE_DONE)):
            return f"{dst.name} exists already — one automatic re-check per route"
        try:
            dst.write_text(recheck_text(src.read_text(encoding="utf-8"), branch, tip, name), encoding="utf-8")
        except OSError as e:
            return f"could not write {dst}: {e}"
        self.recheck = dst.name
        print(f"[QUEUE] 🔁 {name}: BLOCKED(environment) — one automatic gates-only re-check queued, fired next and "
              f"alone: {dst.name} (## Re-gate of: {branch} {tip[:7]}); a red re-check stops the queue (SD-2 (b))")
        return None

    def _after_red(self, brief: Path, entry: dict) -> Optional[str]:
        """[ORCH-QUEUE-PARK-RED-1] SD-2: a route ended red. Move its brief and return the pause reason, or None to keep
        firing. The verdict is the route's own record (route_record, red_kind). Called under self.lock."""
        name = brief.name
        stop_all = f"stop-on-failure:{name}"
        if not self.config["stop_on_failure"]:
            _safe_move(brief, QUEUE_FAILED / name)
            return None
        is_regate = prefire.regate_line(brief) is not None if brief.exists() else False
        if park_off():
            _safe_move(brief, QUEUE_FAILED / name)
            return stop_all
        kind = red_kind(route_record(name, entry.get("started_at")))
        entry["red"] = kind
        if self.recheck == name or Path(name).stem.endswith(RECHECK_SUFFIX):
            self.recheck = None
            _safe_move(brief, QUEUE_FAILED / name)
            print(f"[QUEUE] ⛔ the automatic re-check {name} is red too ({kind}) — the queue stops")
            return f"recheck-red:{name}"
        if kind == RED_PREFIRE:
            return self._set_aside_prefire(brief, name, stop_all)
        if kind == RED_PRODUCT:
            if SAFETY_TIER.match(name):            # SAFETY tier, 7 zeros (D-S7CORE54-74) — verifier M-1
                _safe_move(brief, QUEUE_FAILED / name)
                print(f"[QUEUE] ⛔ {name}: FAIL(product) on a SAFETY-tier brief — not parked; the queue stops")
                return f"safety-red:{name}"
            record = route_record(name, entry.get("started_at"))
            if not self._park(brief, record):
                _safe_move(brief, QUEUE_FAILED / name)
                print(f"[QUEUE] {name} could not be parked — the queue stops (fail closed)")
                return stop_all
            self.product_reds.append(name)
            if len(self.product_reds) >= 2:
                print(f"[QUEUE] ⛔ two product reds in a row ({', '.join(self.product_reds[-2:])}) — the queue stops")
                return f"two-product-reds:{','.join(self.product_reds[-2:])}"
            return None
        _safe_move(brief, QUEUE_FAILED / name)
        if kind == RED_ON_MAIN:
            print(f"[QUEUE] ⛔ {name}: BLOCKED(environment) {ALREADY_RED_SIGNAL} — main is red; the queue stops")
            return f"red-on-main:{name}"
        if kind == RED_ENV:
            why = ("it is itself a gates-only re-gate" if is_regate
                   else self._queue_recheck(QUEUE_FAILED / name, name))
            if why is None:
                return None
            print(f"[QUEUE] {name}: BLOCKED(environment), no automatic re-check — {why}; the queue stops")
        return stop_all

    def _set_aside_prefire(self, brief: Path, name: str, stop_all: str) -> Optional[str]:
        """[ORCH-QUEUE-LOOSEN-1] (1) HOOK-1 refused the brief at fire — no branch, no worktree, no gate: nothing to
        judge and nothing another brief could depend on having landed. Set it aside in queue/held/prefire/ with its
        reason and keep firing (11-20: 791's stale brief paused the whole queue ~30 min). Fails closed: a brief that
        cannot be moved pauses, as before. Fix the brief and re-enqueue it (enqueue re-runs prefire)."""
        tray = prefire_held_dir()
        if not _safe_move(brief, tray / name):
            print(f"[QUEUE] {name}: pre-fire refused and it could not be set aside in {tray} — the queue stops")
            return stop_all
        try:
            (tray / f"{Path(name).stem}.reason").write_text(
                f"{datetime.now().isoformat()} {name}: pre-fire assertions refused it at fire (HOOK-1) — fix the brief, "
                f"then `python3 queue_daemon.py enqueue <fixed brief>`\n", encoding="utf-8")
        except OSError as e:
            print(f"[QUEUE] could not write {Path(name).stem}.reason in {tray}: {e}")
        print(f"[QUEUE] ⏭ {name}: pre-fire refused — SET ASIDE in {tray}/ (nothing was cut); the queue keeps firing")
        return None

    def _hold_depends_on(self, brief: Path, unmet: list):
        """D4: park a brief whose unmet dependency the queue cannot merge in queue/held/depends-on/, its reason in
        `<stem>.reason` beside it. Nothing fired, so it is not a route: no completed/failed entry, no
        stop_on_failure, no consecutive count, no pause. One that will not move stays in queue/, passed over by
        _next_brief and never fired, said once."""
        if brief.name in self._depends_unmovable:
            return
        reason = (f"HELD depends-on {'; '.join(map(str, unmet))} — the queue cannot merge it, so this brief is "
                  f"not fired; move it back to queue/ once that route is merged")
        tray = depends_on_held_dir()
        if not _safe_move(brief, tray / brief.name):
            self._depends_unmovable.add(brief.name)
            print(f"[QUEUE] ⏸ {brief.name}: {reason} — it could not be moved to {tray}; it stays in queue/, "
                  f"passed over")
            return
        try:
            (tray / f"{brief.stem}.reason").write_text(f"{datetime.now().isoformat()} {brief.name}: {reason}\n",
                                                       encoding="utf-8")
        except OSError as e:
            print(f"[QUEUE] could not write {brief.stem}.reason in {tray}: {e}")
        print(f"[QUEUE] ⏸ {brief.name}: {reason} → {tray}/")

    def _poll_control(self):
        """[QUEUE-PAUSE-OPAQUE] P-RESUME, the daemon half: apply the request `pause` / `resume` left in
        control_file() — once, by its id — and acknowledge it by writing the id back into
        queue-state.json. Called at every poll of run_loop; never blocks, never raises."""
        req = _read_json(control_file())
        rid = req.get("id")
        if not isinstance(rid, int) or isinstance(rid, bool) or rid <= self.control_ack:
            return
        action, reset = req.get("action"), bool(req.get("reset_consecutive"))
        cap = self.config["max_consecutive"]
        expired = self._resume_expired(req, rid) if action == "resume" else None
        if action == "pause":
            self.pause("operator")
            result = f"pause → {self.status} ({self.paused_reason})"
        elif expired:
            result = expired
        elif action == "resume" and not reset and self.status == "paused" and self.consecutive_count >= cap:
            result = f"resume refused — max-consecutive:{cap} still reached; use `resume --reset-consecutive`"
        elif action == "resume":
            (self.reset_consecutive if reset else self.resume)()
            result = f"resume{' --reset-consecutive' if reset else ''} → {self.status}"
        else:
            result = f"unknown action {action!r} — ignored"
        with self.lock:
            self.control_ack, self.control_result = rid, result
            self._save_state()
        print(f"[QUEUE] control request {rid}: {result}")

    def _resume_expired(self, req: dict, rid: int) -> Optional[str]:
        """[ORCH-CONTROL-SCOPE-1] C1 · S7-CORE-18 L-45. None when this resume may be applied; else the
        result that says why it expired. Request 9 (`resume --reset-consecutive`) was written while
        route 95 ran; 95 failed, stop_on_failure paused the daemon, and the next poll applied request 9
        — 96 fired unamended. A request is scoped to the state it was issued against:
          · it applies only while the daemon's paused_reason (None when not paused) equals the one it
            was issued under — or, when it names one (`--reason`), the one it names;
          · a stop-on-failure pause is lifted only by a request issued after that pause began;
          · a request with no issued state (from a CLI that predates this) cannot be judged: expired.
        [ORCH-QUEUE-LOOSEN-1] (2) a `--reason` with whitespace in it is free text (a note: who said go, and why), not a
        pause reason — the daemon writes none with a space it would be asked to match (`operator`, `kind:detail`). It
        lifts whatever pause holds, provided it was issued after that pause began (the L-45 rule, kept) and the pause
        is not one only George lifts by name (safety-red:, executor-auth:). 11-20: "George go … go resume" expired."""
        now = self.paused_reason if self.status == "paused" else None
        named = req.get("reason")
        if "issued_status" not in req:
            issued, ok = "an unrecorded state (a request with no issued_status)", False
        else:
            batch, ipr = req.get("issued_current_batch"), req.get("issued_paused_reason")
            issued = (f"{req.get('issued_status')}" + (f" ({ipr})" if ipr else "") + (f" on {batch}" if batch else "")
                      + (f" (--reason {named})" if named else ""))
            ok = (named if named else ipr) == now
            if (not ok and named and now and any(c.isspace() for c in named)
                    and not now.startswith(("safety-red:", "executor-auth:"))):
                try:
                    ok = datetime.fromisoformat(str(req.get("requested_at"))) >= datetime.fromisoformat(str(self.paused_at))
                except ValueError:
                    ok = False
                issued += "" if ok else " before that pause began"
        if ok and now and now.startswith("stop-on-failure:"):
            try:
                ok = datetime.fromisoformat(str(req.get("requested_at"))) >= datetime.fromisoformat(str(self.paused_at))
            except ValueError:
                ok = False
            issued += "" if ok else " before that pause began"
        if ok:
            return None
        state = f"paused for {self.paused_reason}" if self.status == "paused" else self.status
        return f"resume request {rid} expired — issued while {issued}, daemon now {state}; nothing resumed"

    def _clear_stale_markers(self):
        """[QUEUE-PAUSE-OPAQUE] P-STALE: a running marker whose PID is dead does not hold a fire. The
        markers are the root running*.json (the legacy file the fire lock is waited on) and
        state/running*.json (the per-repo locks and their mirror). A marker's PID is its own `pid`,
        else — for a legacy root file written before it carried one — the pid of the per-repo lock
        naming the same batch. Dead ⇒ renamed aside to `<name>.killed-<ts>` (never deleted) and said
        once. No pid to be had ⇒ kept, and said once: it cannot be judged. Alive, unreadable or
        mid-write ⇒ left alone. Returns [(marker, its contents)] for every marker it cleared."""
        cleared = []
        state_dir = ORCH_DIR / "state"
        locks = {q: _read_json(q) for q in sorted(state_dir.glob("running*.json"))} if state_dir.is_dir() else {}
        for q in sorted(ORCH_DIR.glob("running*.json")) + list(locks):
            data = locks.get(q) or _read_json(q)
            if not data:
                continue
            pid = data.get("pid")
            batch = Path(str(data.get("batch_file") or "")).stem
            if pid is None and batch:
                pid = next((d.get("pid") for d in locks.values() if d.get("batch_id") == batch and d.get("pid")), None)
            if pid is None:
                try:
                    key = (str(q), q.stat().st_mtime)
                except OSError:
                    continue
                if key not in self._held_markers:
                    self._held_markers.add(key)
                    print(f"[QUEUE] 🛡 stale-running-marker: HOLD {q} (no pid recorded, and no per-repo lock "
                          f"names {batch or '?'}) — kept; move it aside by hand if its route is gone")
                continue
            if _pid_alive(pid) is not False:
                continue
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            dst, n = q.with_name(f"{q.name}.killed-{ts}"), 1
            while dst.exists():
                dst, n = q.with_name(f"{q.name}.killed-{ts}-{n}"), n + 1
            try:
                os.replace(q, dst)
            except OSError as e:
                print(f"[QUEUE] could not archive stale marker {q}: {e}")
                continue
            print(f"[QUEUE] 🛡 stale-running-marker: CLEARED {q} (pid {pid} dead) → {dst.name}")
            cleared.append((q, data))
        return cleared

    def _recover_dead_routes(self) -> Optional[str]:
        """[ORCH-CONTROL-SCOPE-1] C7b · S7-CORE-19: a WSL restart killed the daemon and route 101 with its
        branch checked out in the clinical-mp tree and work uncommitted. P-STALE renamed the marker and
        left the tree dirty; the next route cut from that tree would have carried the work along (or run
        on the dead route's branch when the cut failed). At start, for each marker P-STALE clears, the
        route's tree is made safe — _recover_dead_route. A route that ran in its own worktree (meta-fire,
        a `worktree_mode: parallel` route) never had the main checkout, so that checkout is not its to
        judge. Returns the paused_reason a start must hold, or None."""
        held, seen = None, set()
        for _, data in self._clear_stale_markers():
            name, branch = data.get("repo"), data.get("branch")
            if not name or not branch or data.get("meta_fire_worktree") or data.get("route_worktree"):
                continue
            if (name, branch) in seen:       # state/running.json mirrors the per-repo lock it names
                continue
            seen.add((name, branch))
            held = self._recover_dead_route(name, branch, data.get("batch_id") or branch) or held
        return held

    def _recover_dead_route(self, name: str, branch: str, route: str) -> Optional[str]:
        """One dead route's repo, by its repos.yaml entry (never a path the marker names). Five cases:
          · clean on the merge target ⇒ nothing to do, nothing said;
          · clean on the route's own branch ⇒ [ORCH-CRASH-PRIMARY-ON-ROUTE-BRANCH-1] (592, 11-13: the route
            died mid-gate with its work committed) rename the branch `<branch>-died-<ts>` (its commits kept),
            check out the merge target, and say both in one line; a step that fails pauses the start
            (`start:route-branch:<repo>`). Unless an executor (a process whose argv[0] is `claude`, as
            fire_toni starts it, under setsid so it outlives its orchestrator) still has its working
            directory at or under the tree: then nothing moves, the line names its pid, and the start pauses
            (`start:route-branch:<repo>`);
          · clean on any other branch or a detached HEAD ⇒ left as it is, said in one line (a fire cuts its
            branch from the merge target);
          · dirty on the route's own branch ⇒ the work is the route's: stash it (untracked included) under a
            message naming the route, rename the branch `<branch>-died-<ts>`, check out the merge target,
            and say all three in one line;
          · dirty on any other branch ⇒ not attributable: left exactly as it is, and the start pauses
            (`start:dirty-tree:<repo>`).
        Every step is additive — a stash, a rename, a checkout of a clean tree; nothing is reset, removed or
        deleted."""
        repo = repo_route(name)
        tag = f"[QUEUE] 🛡 dead-route-recovery: {name} —"
        if repo is None:
            print(f"{tag} not in {REPOS_CONFIG}; its tree is not inspected")
            return None
        path, target, held = repo.path, repo.merge_target, f"start:dirty-tree:{name}"

        def git(args: str) -> subprocess.CompletedProcess:
            return subprocess.run(f"git -C {shlex.quote(str(path))} {args}", shell=True,
                                  capture_output=True, text=True)

        status = git("status --porcelain")
        if status.returncode != 0:
            print(f"{tag} {path} could not be read ({status.stderr.strip()[-200:]}); not inspected")
            return None
        on = git("symbolic-ref -q --short HEAD").stdout.strip() or "a detached HEAD"
        if not status.stdout.strip():
            if on == target:
                return None
            if on != branch:
                print(f"{tag} {path} is clean on {on}, not on {route}'s branch {branch} or {target}; left as it is")
                return None
            held_rb = f"start:route-branch:{name}"

            def executor_in_tree() -> Optional[tuple]:
                """(pid, cmdline) of a live process whose argv[0] is `claude` and whose cwd is at or under `path`, by
                path components (`<path>-wt` is not under it); a /proc entry that cannot be read is skipped."""
                root = Path(path).resolve()
                for d in sorted((x for x in os.listdir("/proc") if x.isdigit()), key=int):
                    try:
                        argv = [a.decode(errors="replace")
                                for a in Path(f"/proc/{d}/cmdline").read_bytes().split(b"\0") if a]
                        cwd = Path(os.readlink(f"/proc/{d}/cwd"))
                    except OSError:
                        continue
                    if argv and os.path.basename(argv[0]) == "claude" and (cwd == root or root in cwd.parents):
                        return int(d), " ".join(argv)
                return None

            holder = executor_in_tree()
            if holder:
                print(f"{tag} {path} is clean on {route}'s branch {branch}, but pid {holder[0]} ({holder[1][:80]}) "
                      f"still works in it; left as it is — PAUSED ({held_rb})")
                return held_rb
            ts = datetime.now().strftime("%Y%m%d-%H%M%S")
            died, tip = f"{branch}-died-{ts}", git("rev-parse HEAD").stdout.strip()
            for step, args in (("rename", f"branch -m {shlex.quote(branch)} {shlex.quote(died)}"),
                               ("checkout", f"checkout -q {shlex.quote(target)}")):
                r = git(args)
                if r.returncode != 0:
                    print(f"{tag} {path} is clean on {route}'s branch {branch}; the {step} failed "
                          f"({r.stderr.strip()[-200:]}) — PAUSED ({held_rb})")
                    return held_rb
            print(f"{tag} {path} was clean on {route}'s branch {branch} (tip {tip[:12]}); branch {branch} → {died}; "
                  f"{target} checked out in {path}")
            return None
        if on != branch:
            print(f"{tag} {path} is dirty on {on}, not on {route}'s branch {branch}; left as it is — PAUSED ({held})")
            return held
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        msg = f"{route} partial WIP (route process died {ts}), recovered by daemon start"
        died = f"{branch}-died-{ts}"
        stash = git(f"stash push -u -m {shlex.quote(msg)}")
        if stash.returncode != 0 or git("status --porcelain").stdout.strip():
            print(f"{tag} {path} is dirty on {branch} and `git stash push -u` did not leave it clean "
                  f"({(stash.stderr or stash.stdout).strip()[-200:]}); left as it is — PAUSED ({held})")
            return held
        sha = git("rev-parse refs/stash").stdout.strip()
        for step, args in (("rename", f"branch -m {shlex.quote(branch)} {shlex.quote(died)}"),
                           ("checkout", f"checkout -q {shlex.quote(target)}")):
            r = git(args)
            if r.returncode != 0:
                print(f"{tag} {route}'s uncommitted work stashed as {sha[:12]} ({msg}); the {step} after it "
                      f"failed ({r.stderr.strip()[-200:]}) — PAUSED ({held})")
                return held
        print(f"{tag} {route}'s uncommitted work stashed as {sha[:12]} ({msg}); branch {branch} → {died}; "
              f"{target} checked out in {path}")
        return None

    def _fire_locks(self, repo: str) -> list:
        """[ORCH-LANE-1] O1 · S7-CORE-19: the markers that hold a brief naming `repo`, after P-STALE has
        cleared the dead. The daemon waited on ANY root running*.json, so a direct `orchestrator.py run
        --repo ai-foundation` (109) held 110 (clinical-mp) for ~2 h. orchestrator.py's lock is per repo
        ([ORCH-4]); so is this wait. Held by:
          · state/running-<repo>.json, the repo's own lock;
          · a legacy global marker — the root running*.json, the state/running.json mirror — that names
            this repo: its own `repo`, else the repo of the per-repo lock naming its batch. One that names
            no repo at all (unreadable, mid-write, pre-[ORCH-4]) cannot be attributed and holds: the safe
            direction, and orchestrator's own _lock_candidates rule.
        A marker that names another repo never holds."""
        self._clear_stale_markers()
        state_dir = ORCH_DIR / "state"
        own = state_dir / f"running-{_marker_slug(repo)}.json"
        locks = {q: _read_json(q) for q in sorted(state_dir.glob("running-*.json"))} if state_dir.is_dir() else {}
        held = [own] if own.exists() else []
        for q in sorted(ORCH_DIR.glob("running*.json")) + [state_dir / "running.json"]:
            if not q.exists():
                continue
            data = _read_json(q)
            named = data.get("repo")
            batch = Path(str(data.get("batch_file") or "")).stem
            if not named and batch:
                named = next((d.get("repo") for d in locks.values() if d.get("batch_id") == batch), None)
            if not named or _marker_slug(named) == _marker_slug(repo):
                held.append(q)
        return held

    def _fire_lock_held(self, repo: str) -> bool:
        """[ORCH-LANE-1] O1: whether a brief naming `repo` must wait — see _fire_locks."""
        return bool(self._fire_locks(repo))

    def run_loop(self):
        """Main daemon loop. Call from a background thread."""
        self._ensure_dirs()
        # QUEUE-RETIRE-1 / T3 — B6 before the first batch, never after it.
        self.retire_merged_briefs()
        # [QUEUE-PAUSE-OPAQUE] from here this object's state IS the daemon's. A control request left
        # before this start is not replayed: the start is itself the operator's act.
        self.is_daemon = True
        pending = _read_json(control_file()).get("id")
        if isinstance(pending, int) and not isinstance(pending, bool) and pending > self.control_ack:
            self.control_ack = pending
        self.started_at = datetime.now().isoformat()
        # [ORCH-CONTROL-SCOPE-1] C7b then C2: a dead route's tree is made safe, and a start with work
        # queued fires nothing until told (L-46) — `resume`, or a start with --start-running.
        held = self._recover_dead_routes()
        queued = len(self._scan_queue())
        if held:
            self._mark_paused(held, say=False)
            why = ("is on its route branch and could not be returned to its merge target"
                   if held.startswith("start:route-branch:") else "is dirty and was left as it is")
            start = (f"PAUSED ({held}) — a dead route's repo {why}; nothing fires "
                     f"until `python3 queue_daemon.py resume`")
        elif queued and not self.start_running:
            self._mark_paused(START_PAUSED_REASON, say=False)
            start = (f"{queued} brief(s) queued — PAUSED ({START_PAUSED_REASON}); nothing fires until "
                     f"`python3 queue_daemon.py resume` (or a start with --start-running)")
        else:
            self.status = "running"
            self.paused_reason = self.paused_at = None
            self._clear_pause_notice()
            start = (f"--start-running — running; {queued} brief(s) queued fire now" if queued
                     else "queue empty — running")
        self._save_state()

        print(f"[QUEUE] Daemon started. Watching {QUEUE_DIR}")
        print(f"[QUEUE] Config: max={self.config['max_consecutive']}, "
              f"cooldown={self.config['cooldown_seconds']}s, "
              f"stop_on_fail={self.config['stop_on_failure']}")
        print(executor_default_line(self.persisted_executor, self.config, os.environ))
        print(repo_rule_line(self.persisted_repo, os.environ))
        most, floor = admission.limits(REPOS_CONFIG)
        print(f"[QUEUE] 🛡 admission: at most {most} live route(s) across every repo, and MemAvailable >= {floor:g} "
              f"GiB — config/repos.yaml `admission:`, read at each fire; a refusal waits (ORCH-CAPACITY-1 C1)")
        print(f"[QUEUE] 🛡 route-wall: per route — its brief's route timeout + its repo's gate budget + "
              f"{admission.ROUTE_WALL_SLACK_S}s slack (ORCH-CAPACITY-1 C4)"
              + (f"; persisted timeout_seconds={self.persisted_timeout} not applied" if self.persisted_timeout else ""))
        print(f"[QUEUE] 🛡 start: {start}")

        while self.status != "stopped":
            self._poll_control()
            self._send_pause_notice()
            if self.status == "paused":
                self._full_gate_step()   # [ORCH-GATE-COST-1] D4: says a window missed while paused; never runs one
                time.sleep(PAUSED_POLL_S)
                continue

            if self.consecutive_count >= self.config["max_consecutive"]:
                print(f"[QUEUE] Max consecutive ({self.config['max_consecutive']}) reached. Pausing.")
                self._mark_paused(f"max-consecutive:{self.config['max_consecutive']}")
                self._save_state()
                continue

            if self._full_gate_step():   # D4: a scheduler step between routes — never over one
                continue

            # [ORCH-DEPENDS-ON-1] D4: filename order, less a brief waiting on a dependency still queued; one whose
            # dependency the queue cannot merge is parked in queue/held/depends-on/ on the way. None: nothing to fire.
            next_batch = self._next_brief(self._scan_queue())
            if next_batch is None:
                if self.waiting:
                    with self.lock:
                        self.waiting = self._waiting_said = None
                        self._save_state()
                time.sleep(10)
                continue

            batch_name = next_batch.name
            # [ORCH-YORSIE-SAFETY-1] Y1: a brief names its repo or is refused — before the fire lock and
            # before current_batch, so nothing fires and the next brief is taken at once.
            lane = _parse_batch_header(next_batch).get("repo")
            if not lane:
                self._refuse(next_batch, NO_REPO_REFUSAL)
                continue
            start_time = datetime.now()

            with self.lock:
                self.current_batch = {
                    "file": batch_name,
                    "started_at": start_time.isoformat()
                }
                self._save_state()

            # S7-CORE-11: never fire into a live route. The orchestrator holds a fire
            # lock per repo (and a legacy global `running.json`); firing anyway would
            # be refused, and with stop_on_failure the whole queue would halt on a
            # brief that was never actually wrong. Wait for the lock instead.
            # [QUEUE-PAUSE-OPAQUE] P-STALE: a marker whose pid is dead is cleared, not waited on; the
            # wait itself polls the control file, and a pause or stop ends it without firing.
            # [ORCH-LANE-1] O1: the lock of the repo this brief names, and only that one.
            _waited = 0
            while self.status == "running" and (held := self._fire_locks(lane)):
                if _waited == 0:
                    print(f"[QUEUE] fire lock held for {lane} ({held[0]}) — waiting before {batch_name}")
                time.sleep(30)
                _waited += 30
                self._poll_control()
                if _waited > 14400:   # 4h: something is wedged, say so and stop trying
                    print(f"[QUEUE] fire lock still held after 4h — leaving {batch_name} queued")
                    break
            if self.status != "running" or self._fire_lock_held(lane):
                with self.lock:
                    self.current_batch = None
                    self._save_state()
                if self.status == "running":
                    time.sleep(self.config["cooldown_seconds"])
                continue
            if _waited:
                print(f"[QUEUE] lock clear after {_waited}s")

            # A batch may name its own model/effort on the first line as
            #   #!queue model=claude-sonnet-4-5 effort=high repo=clinical-mp
            # so a mechanical cleanup route can run Sonnet while RM increments run
            # Fable, without restarting the daemon (George, 2026-09-16). It MUST name its repo.
            hdr = _parse_batch_header(next_batch)   # re-read: it may have been edited while it waited
            b_model = hdr.get("model", self.config["model"])
            b_effort = hdr.get("effort", self.config["effort"])
            if "effort" in hdr:   # [ORCH-LEAN-GATE-1] a header's xhigh needs its reason in the brief
                b_effort, said = header_effort(next_batch, b_effort)
                if said:
                    print(said)
            b_repo = hdr.get("repo")
            if not b_repo:
                with self.lock:
                    self.current_batch = None
                self._refuse(next_batch, NO_REPO_REFUSAL)
                continue
            if b_repo != lane:
                # [ORCH-LANE-1] edited while it waited to name another repo, whose lock was never asked
                print(f"[QUEUE] {batch_name} now names repo={b_repo}, not {lane} — its lock is asked before it fires")
                with self.lock:
                    self.current_batch = None
                    self._save_state()
                continue

            # [ORCH-TONI-GUARDS-1] the last check before the spawn: while KILL exists nothing fires. A wait, like
            # admission's below: the brief stays first in queue/, said once per KILL, shown by `status` as waiting.
            killed = read_kill()
            if killed is not None:
                self._wait_for_unkill(batch_name, killed)
                continue
            self._kill_said = None

            # [ORCH-CAPACITY-1] C1 · L-70: one Toni route at a time across every repo, and only with memory to
            # spare. A refusal is a wait, never a failure: nothing fires and the brief stays first in queue/. The
            # yes claims the slot (state/admitted-<pid>.json); the route adopts the claim (ORCH_ADMISSION_CLAIM)
            # rather than asking again, and the daemon releases it when the route returns.
            ok, why = admission.admit(b_repo, next_batch.stem, claim=True, orch_dir=ORCH_DIR, config_path=REPOS_CONFIG)
            if not ok:
                self._wait_for_admission(batch_name, why)
                continue
            claim = admission.claim_path(ORCH_DIR)
            self.waiting = self._waiting_said = None
            print(f"[QUEUE] 🛡 admission: {why}")
            # [ORCH-EXECUTOR-AUTH-PROBE-1] G-C2: once per fire, after admission's yes and the claim — never in a wait
            # loop. A refusal releases the claim and pauses (George's resume); the brief stays first in queue/.
            fire, auth_checked = self._executor_auth_step(next_batch, batch_name, claim)
            if not fire:
                continue
            # C4: this route's wall — its brief's route timeout, as orchestrator.py derives it, + its gates' budget.
            wall = admission.route_wall(next_batch, b_repo, config_path=REPOS_CONFIG)

            print(f"[QUEUE] Firing: {batch_name}")

            cmd = (
                f"cd {ORCH_DIR} && unset ANTHROPIC_API_KEY && "
                + (f"{executor_auth.CHECKED_VAR}={shlex.quote(auth_checked)} " if auth_checked else "")
                + f"{admission.CLAIM_ENV}={shlex.quote(str(claim))} "
                f"python3 -u orchestrator.py run {next_batch} --approve "
                f"--repo {b_repo} --model {b_model} --effort {b_effort}"
            )
            print(f"[QUEUE] repo={b_repo} model={b_model} effort={b_effort}")
            print(f"[QUEUE] ⏱ route wall {wall.describe()}")

            log_path = route_log_path(b_repo, batch_name, start_time)
            with self.lock:
                if self.current_batch is not None:
                    self.current_batch["log_file"] = str(log_path)
                    self.current_batch["wall"] = wall.as_dict()
                self._save_state()
            print(f"[QUEUE] log={log_path}")

            try:
                exit_code = self._run_route(cmd, batch_name, log_path)
            finally:
                admission.release(claim)

            end_time = datetime.now()
            duration_s = (end_time - start_time).total_seconds()

            with self.lock:
                entry = {
                    "file": batch_name,
                    "exit_code": exit_code,
                    "duration_s": round(duration_s, 1),
                    "started_at": start_time.isoformat(),
                    "finished_at": end_time.isoformat(),
                    "log_file": str(log_path),
                }

                if exit_code == 0:
                    # Normally already retired by the merge itself (QUEUE-RETIRE-1 / T1) —
                    # a no-op here, and that is the healthy case. The entry is recorded
                    # regardless: state bookkeeping is still the scheduler's.
                    _safe_move(next_batch, QUEUE_DONE / batch_name)
                    self.completed.append(entry)
                    self.consecutive_count += 1
                    self.product_reds = []            # [ORCH-QUEUE-PARK-RED-1] "in a row" ends at a pass
                    if self.recheck == batch_name:
                        self.recheck = None
                    print(f"[QUEUE] PASSED: {batch_name} ({duration_s:.0f}s)")
                elif exit_code == EXIT_STOPPED:
                    # [ORCH-HANDBACK-STOP-STATUS-1] G-6: a fire that merged what `passed` would, whose handback
                    # says STOP / PARTIAL. The tray as the merge left it (as for 0); no pause (OPEN (d)).
                    entry["status"] = "stopped"
                    _safe_move(next_batch, QUEUE_DONE / batch_name)
                    self.stopped.append(entry)
                    self.consecutive_count += 1
                    self.product_reds = []            # [ORCH-QUEUE-PARK-RED-1]
                    if self.recheck == batch_name:
                        self.recheck = None
                    print(f"[QUEUE] STOPPED: {batch_name} (handback STATUS STOP/PARTIAL — read it before closing "
                          f"the Kanban row, rule #15; {duration_s:.0f}s)")
                elif exit_code == EXIT_HELD:
                    # [ORCH-MERGE-HOLD-1]: green, held for a human merge — the brief to queue/held/merge-hold/ with its
                    # reason; no pause, no red in a row; a held re-gate (a release red-gated) is handled as a red below.
                    entry["status"] = "held"
                    tray = merge_hold_dir()
                    tray.mkdir(parents=True, exist_ok=True)
                    record = route_record(batch_name, entry.get("started_at")) or {}
                    why = str(record.get("error") or "held for a human merge (config/merge-hold.json)")
                    if not _safe_move(next_batch, tray / batch_name):
                        _safe_move(next_batch, QUEUE_DONE / batch_name)
                    try:
                        (tray / f"{Path(batch_name).stem}.reason").write_text(
                            f"{end_time.isoformat()} {batch_name}: {why}\n", encoding="utf-8")
                    except OSError as e:
                        print(f"[QUEUE] could not write the hold reason for {batch_name}: {e}")
                    self.held.append(entry)
                    self.consecutive_count += 1
                    self.product_reds = []
                    if self.recheck == batch_name:
                        self.recheck = None
                    print(f"[QUEUE] ⏸ HELD: {batch_name} — green, held for a human merge ({why[:200]}); release with "
                          f"python3 queue_daemon.py {RELEASE_USAGE} — the queue keeps firing ({duration_s:.0f}s)")
                else:
                    # [ORCH-QUEUE-PARK-RED-1] SD-2: park a product red and keep firing independent work; one
                    # automatic re-check of an environment red; stop on everything else, as before.
                    pause = self._after_red(next_batch, entry)
                    # a brief _after_red left in queue/ (it moves, parks or re-checks it) still goes to failed/ —
                    # never fired twice; a no-op when it has moved (tests/test_queue_retire.py pins this site)
                    _safe_move(next_batch, QUEUE_FAILED / batch_name)
                    self.failed.append(entry)
                    print(f"[QUEUE] FAILED: {batch_name} (exit {exit_code}, {duration_s:.0f}s)")
                    if pause:
                        if pause.startswith("stop-on-failure:"):
                            print(f"[QUEUE] stop_on_failure=true. Pausing queue.")
                        self._mark_paused(pause)

                # ORCH-STDOUT-1 — post-route oracle. Reports; changes no state and no verdict.
                for v in check_gate_log_invariants([entry]):
                    print(f"[QUEUE] ⛔ ORCH-STDOUT-1 invariant: {v}")

                self.current_batch = None
                self.current_process = None
                self._save_state()

            if self.status == "running" and self.config["cooldown_seconds"] > 0:
                print(f"[QUEUE] Cooldown {self.config['cooldown_seconds']}s...")
                time.sleep(self.config["cooldown_seconds"])

        self._send_pause_notice()
        print("[QUEUE] Daemon stopped.")

    def _full_gate_step(self) -> bool:
        """[ORCH-GATE-COST-1] D4: run one nightly full gate that is due, if the daemon is running and idle. True
        when it ran one (the loop polls the control file again before its next brief). Due: the repo's
        `full_gate_nightly` time has passed today and no full gate ran for it today. Not running (paused) or not
        idle (admission would refuse a route now) ⇒ deferred, said once a day per reason; it runs at the next idle
        moment today. A day that ended with its window deferred is said SKIPPED, once."""
        schedule = full_gate_schedule()
        if not schedule:
            return False
        now = FULL_GATE_CLOCK()
        today, changed = now.date().isoformat(), False
        for repo, (hh, mm, hhmm) in sorted(schedule.items()):
            rec = self.full_gate.setdefault(repo, {})
            missed = rec.get("deferred_day")
            if missed and missed != today and rec.get("ran_day") != missed:
                print(f"[QUEUE] 🌙 full-gate {repo}: SKIPPED {missed} — the {hhmm} window was missed "
                      f"({rec.get('deferred')}) and no idle moment followed that day")
                rec.update(skipped_day=missed, skipped=rec.get("deferred"), deferred_day=None, deferred=None)
                changed = True
            if rec.get("ran_day") == today or now.time() < dtime(hh, mm):
                continue
            if self.status != "running":
                why = f"daemon {self.status}" + (f" ({self.paused_reason})" if self.paused_reason else "")
            else:
                ok, adm = admission.admit(repo, f"{FULL_GATE_PREFIX}nightly", orch_dir=ORCH_DIR,
                                          config_path=REPOS_CONFIG)
                why = None if ok else f"busy — {adm}"
            if why:
                kind = why.split(" — ")[0].split(" (")[0]
                if rec.get("deferred_day") != today or rec.get("deferred_kind") != kind:
                    print(f"[QUEUE] 🌙 full-gate {repo}: due at {hhmm}, not run now — {why}; it runs at the next "
                          f"idle moment today, else it is logged SKIPPED")
                    rec.update(deferred_day=today, deferred=why, deferred_kind=kind)
                    changed = True
                continue
            rec.update(ran_day=today, deferred_day=None, deferred=None, deferred_kind=None)
            self._run_full_gate(repo, hhmm)
            return True
        if changed:
            with self.lock:
                self._save_state()
        return False

    def _run_full_gate(self, repo: str, hhmm: str) -> int:
        """[ORCH-GATE-COST-1] D4: `orchestrator.py full-gate --repo <repo> --trigger nightly`, its stdout+stderr to
        logs/<log_subdir>/full-gate-<ts>.log (ORCH-STDOUT-1's shape: a file, never a pipe), under FULL_GATE_WALL_S.
        The run takes the repo's fire lock itself; the daemon records it as full_gate_running, never as a route
        (current_batch stays empty). Returns its exit code: 0 PASS, 1 NEW FAILURES or BLOCKED, 2 refused."""
        started = datetime.now()
        log_path = LOG_DIR / _log_subdir(repo) / f"{FULL_GATE_PREFIX}{started:%Y%m%d-%H%M%S}.log"
        cmd = (f"cd {shlex.quote(str(ORCH_DIR))} && unset ANTHROPIC_API_KEY && python3 -u orchestrator.py full-gate "
               f"--repo {shlex.quote(repo)} --trigger nightly --log-file {shlex.quote(str(log_path))}")
        with self.lock:
            self.full_gate_running = {"repo": repo, "started_at": started.isoformat(), "log": str(log_path)}
            self._save_state()
        print(f"[QUEUE] 🌙 full-gate {repo}: nightly {hhmm} — running the full SIT + unit suites; log={log_path}")
        rc, note = -2, ""
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as lf:
                lf.write(f"=== QUEUE FULL GATE ===\nRepo: {repo}\nStarted: {started.isoformat()}\nCommand: {cmd}\n"
                         f"{'=' * 60}\n\n")
                lf.flush()
                proc = self.current_process = subprocess.Popen(cmd, shell=True, executable="/bin/bash",
                                                               stdout=lf, stderr=subprocess.STDOUT)
                try:
                    rc = proc.wait(timeout=FULL_GATE_WALL_S)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    rc, note = -1, f" (the daemon's {FULL_GATE_WALL_S}s backstop fired)"
                lf.write(f"\n{'=' * 60}\nFinished: {datetime.now().isoformat()}\nExit: {rc}{note}\n")
        except Exception as e:
            note = f" (error: {e})"
        result = _read_json(ORCH_DIR / "state" / f"{FULL_GATE_PREFIX}{_marker_slug(repo)}.json")
        fresh = str(result.get("started_at") or "") >= started.isoformat()[:19]
        outcome = (result.get("outcome") if fresh and result.get("outcome") else
                   "REFUSED" if rc == 2 else f"exit {rc}")
        sha = str(result.get("sha") or "?")[:7] if fresh else "-"
        with self.lock:
            self.full_gate.setdefault(repo, {})["last"] = {"at": datetime.now().isoformat(), "exit": rc,
                                                            "outcome": outcome, "sha": sha, "log": str(log_path)}
            self.full_gate_running = None
            self.current_process = None
            self._save_state()
        print(f"[QUEUE] 🌙 full-gate {repo}: {outcome} (exit {rc}{note}) — sha {sha}; log={log_path}")
        return rc

    def _wait_for_admission(self, batch_name: str, why: str):
        """[ORCH-CAPACITY-1] C1: admission said no — nothing fired, the brief stays first in queue/, and the loop
        asks again after the cooldown. One log line per change of reason (MemAvailable moving is not a change);
        `status` line 1 shows the latest as `waiting: …`."""
        said = re.sub(r"MemAvailable [\d.]+ GiB", "MemAvailable … GiB", why)
        if said != self._waiting_said:
            print(f"[QUEUE] 🛡 admission: waiting before {batch_name} — {why}")
            self._waiting_said = said
        with self.lock:
            self.current_batch = None
            self.waiting = f"{batch_name} — {why}"
            self._save_state()
        if self.status == "running":
            time.sleep(self.config["cooldown_seconds"] or PAUSED_POLL_S)

    def _executor_auth_step(self, next_batch: Path, batch_name: str, claim: Path) -> tuple[bool, Optional[str]]:
        """[ORCH-EXECUTOR-AUTH-PROBE-1] G-C2: (fire?, the EXECUTOR_AUTH_CHECKED value for the route command). Off or a
        gates-only re-gate ⇒ no probe. Not ok ⇒ the claim is released, nothing fires, the brief stays first in queue/,
        and the daemon pauses — executor-auth:<brief> (only George can fix it) or executor-check:<brief>
        (BLOCKED(environment)). Never lifted by the daemon itself: George's resume."""
        if executor_auth.probe_off():
            print(f"[QUEUE] 🛡 executor-auth: OFF ({executor_auth.PROBE_VAR}=off) — not checked")
            self._auth_said = "OFF"
            return True, None
        if prefire.regate_line(next_batch) is not None:
            return True, None
        checked = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        v = executor_auth.probe()
        if v.ok:
            if getattr(self, "_auth_said", None) != "CLEAN":
                print(f"[QUEUE] 🛡 executor-auth: CLEAN — {v.detail}")
            self._auth_said = "CLEAN"
            return True, checked
        admission.release(claim)
        fix = executor_auth.fix_for(v.kind)
        if v.kind == "auth":
            reason = (f"executor-auth:{batch_name} — Toni's login has expired or been refused; only George can fix "
                      f"it: run claude, then /login, then resume")
        else:
            reason = (f"executor-check:{batch_name} — BLOCKED(environment): the executor check could not reach a "
                      f"verdict; not a login problem — check the network and the claude CLI, then resume")
        with self.lock:
            self.current_batch = None
            self._mark_paused(reason, say=False, detail=f"{v.detail} {fix}")
            self._save_state()
        self._auth_said = "BLOCKED"
        print(f"[QUEUE] 🛡 executor-auth: BLOCKED — {v.detail} — {batch_name} not fired; {fix} "
              f"Then: {resume_command(reason)}")
        return False, None

    def _wait_for_unkill(self, batch_name: str, killed: dict):
        """[ORCH-TONI-GUARDS-1] KILL exists: nothing fired, the brief stays in queue/, and the loop looks again after
        PAUSED_POLL_S. One log line per KILL (per what it says); `status` line 1 shows it as `waiting: …`."""
        why = f"KILL present ({kill_file()}: {killed.get('reason') or NO_REASON}, since {killed.get('at') or '?'})"
        if why != self._kill_said:
            print(f"[QUEUE] 🛡 {why} — {batch_name} not fired; nothing fires until "
                  f"`cd {shlex.quote(str(ORCH_DIR))} && python3 queue_daemon.py unkill --reason \"<text>\"` "
                  f"(ORCH-TONI-GUARDS-1)")
            self._kill_said = why
        with self.lock:
            self.current_batch = None
            self.waiting = f"{batch_name} — {why}"
            self._save_state()
        if self.status == "running":
            time.sleep(PAUSED_POLL_S)

    def _run_route(self, cmd: str, batch_name: str, log_path: Path) -> int:
        """Run one route with its stdout+stderr going to `log_path`; return its exit code.

        ORCH-STDOUT-1. The child gets an open FILE as stdout — fire_toni's shape — never a
        pipe: a pipe nobody reads deadlocks once the child writes 64 KiB, and a pipe read into
        memory loses everything if the daemon dies mid-route. With a file there is no buffer to
        fill, output is on disk as it is produced (`tail -f` works), and a kill leaves a partial
        log. Appended, not truncated, so cancel_current's trailer and this one both land.

        Exit codes are unchanged: the child's own, -1 on timeout, -2 on any other error
        (including a log that cannot be opened). A trailer is written on every path it can be.

        [ORCH-CAPACITY-1] C4: the timeout is this route's wall (run_loop records it in current_batch), polled
        on ROUTE_CLOCK every ROUTE_POLL_S. A kill names the clock that fired and the phase the route was in.
        Outside run_loop there is no brief to derive from: the wall is the 180-minute cap's, plus the slack.
        """
        wall = (self.current_batch or {}).get("wall") or admission.route_wall(
            None, "", env={"TONI_TIMEOUT_MIN": str(admission.TIMEOUT_HARD_CAP_MIN)}).as_dict()
        timeout = int(wall["seconds"])
        try:
            lf = open(log_path, "a", encoding="utf-8")
        except Exception as e:
            print(f"[QUEUE] Error on {batch_name}: cannot open {log_path}: {e}")
            return -2
        with lf:
            note = ""
            proc = None
            try:
                lf.write(f"=== QUEUE ROUTE ===\nBatch: {batch_name}\n")
                lf.write(f"Started: {datetime.now().isoformat()}\nCommand: {cmd}\n{'='*60}\n\n")
                lf.flush()
                proc = self.current_process = subprocess.Popen(
                    cmd, shell=True, executable="/bin/bash",
                    stdout=lf, stderr=subprocess.STDOUT)
                deadline = ROUTE_CLOCK() + timeout
                while True:
                    try:
                        exit_code = proc.wait(timeout=max(0.0, min(ROUTE_POLL_S, deadline - ROUTE_CLOCK())))
                        break
                    except subprocess.TimeoutExpired:
                        if ROUTE_CLOCK() >= deadline:
                            raise
            except subprocess.TimeoutExpired:
                why = (f"⏱ ROUTE WALL — the daemon's route wall fired on {batch_name} after {timeout}s, in phase "
                       f"{route_phase(log_path)}; the wall: {wall.get('describe')}. orchestrator.py's own clocks "
                       f"(Toni, each gate leg) had not ended the route. Killing.")
                print(f"[QUEUE] {why}")
                try:
                    lf.write(f"\n[QUEUE] {why}\n")
                    lf.flush()
                except Exception:
                    pass
                proc.kill()
                proc.wait()
                exit_code, note = -1, f" (timeout after {timeout}s)"
            except Exception as e:
                print(f"[QUEUE] Error on {batch_name}: {e}")
                exit_code, note = -2, f" (error: {e})"
            try:
                lf.write(f"\n{'='*60}\nFinished: {datetime.now().isoformat()}\n"
                         f"Exit: {exit_code}{note}\n")
            except Exception as e:
                print(f"[QUEUE] could not write trailer to {log_path}: {e}")
        return exit_code

    def stop(self):
        self.cancel_current()
        self.status = "stopped"
        self._save_state()


def start_daemon_thread(daemon):
    """Start daemon in a background thread. Returns the thread."""
    t = threading.Thread(target=daemon.run_loop, daemon=True, name="queue-daemon")
    t.start()
    return t


def _control_args(cmd: str, args: list) -> Optional[dict]:
    """[ORCH-CONTROL-SCOPE-1] C6: what `pause` / `resume` take, or None for anything they do not — `--help`
    and `-h` included (`pause --help` wrote a real pause request). None ⇒ usage, exit 2, nothing written."""
    if cmd == "pause":
        return None if args else {}
    opts, rest = {"reset_consecutive": False, "reason": None}, list(args)
    while rest:
        a = rest.pop(0)
        if a == "--reset-consecutive" and not opts["reset_consecutive"]:
            opts["reset_consecutive"] = True
        elif a == "--reason" and opts["reason"] is None and rest and not rest[0].startswith("-"):
            opts["reason"] = rest.pop(0)
        else:
            return None
    return opts


def _override_args(args: list) -> Optional[tuple]:
    """`<repo> <branch> --verdict V --by B --reason R` → (repo, branch, V, B, R), or None when malformed."""
    if len(args) < 2 or args[0].startswith("--") or args[1].startswith("--"):
        return None
    repo, branch, rest, opts = args[0], args[1], args[2:], {}
    while rest:
        if len(rest) < 2 or rest[0] not in ("--verdict", "--by", "--reason") or rest[0] in opts:
            return None
        opts[rest[0]], rest = rest[1], rest[2:]
    if set(opts) != {"--verdict", "--by", "--reason"}:
        return None
    return repo, branch, opts["--verdict"], opts["--by"], opts["--reason"]


def main(argv: list) -> int:
    if not argv or argv == ["--start-running"]:
        d = QueueDaemon()
        d.start_running = bool(argv)   # [ORCH-CONTROL-SCOPE-1] C2
        try:
            d.run_loop()
        except KeyboardInterrupt:
            d.stop()
            print("\\nQueue daemon stopped.")
        return 0
    cmd = argv[0]
    if cmd in ("kill", "unkill"):
        # [ORCH-TONI-GUARDS-1] before QueueDaemon(): no queue state is read or written, whatever state it is in
        reason = _kill_args(cmd, argv[1:])
        if reason is None:
            print(USAGE, file=sys.stderr)
            return 2
        return kill(reason) if cmd == "kill" else unkill(reason)
    if cmd == "override":                     # [ORCH-QUEUE-PARK-RED-1] G-3: appended, never overwritten
        opts = _override_args(argv[1:])
        if opts is None:
            print("Usage: python3 queue_daemon.py " + OVERRIDE_USAGE, file=sys.stderr)
            return 2
        rc, msg = append_override(*opts)
        print(("✅ override appended — " if rc == 0 else "⛔ override refused — ") + msg)
        return rc
    if cmd == "release-hold":                 # [ORCH-MERGE-HOLD-1] appended, then a gates-only re-gate queued
        opts = _release_args(argv[1:])
        if opts is None:
            print("Usage: python3 queue_daemon.py " + RELEASE_USAGE, file=sys.stderr)
            return 2
        rc, msg = release_hold(*opts)
        print(("✅ hold released — " if rc == 0 else "⛔ release refused — ") + msg)
        return rc
    d = QueueDaemon()
    if cmd == "enqueue" and len(argv) > 1:
        r = d.enqueue(argv[1])
        print(json.dumps(r, indent=2, ensure_ascii=False))
        if not r["ok"]:
            return 1                  # [ORCH-PREFIRE-DRYRUN-GATE-1] a refused enqueue is not a success
    elif cmd == "status" and argv[1:] in ([], ["--json"]):
        # [QUEUE-PAUSE-OPAQUE] P-PAUSE: this process is not the daemon. Line 1 and every daemon field
        # below come from what the daemon persisted, never from this object's own "idle".
        # [ORCH-CONTROL-SCOPE-1] C6: `--json` prints the JSON alone, for a machine reader.
        # [ORCH-LANE-1] O2: a paused daemon's notice — next brief, the resume command — on line 1 too.
        st = read_persisted_state()
        notice = pause_notice_for(st)
        # [ORCH-GATE-COST-1] D4: and each repo's last full-gate result, from state/full-gate-<repo>.json.
        summary = full_gate_summary()
        fg = full_gate_line(st, summary)
        # [ORCH-DEPENDS-ON-1] D4: the briefs the daemon passes over for a queued dependency, and those it held.
        deps = depends_on_line(st.get("depends_waiting"), depends_held())
        # [ORCH-QUEUE-PARK-RED-1] the briefs parked after a product red, waiting for George
        parked = parked_briefs()
        park = ("🅿 parked in queue/held/parked/: " + ", ".join(p["file"] for p in parked)) if parked else ""
        merge_held = held_briefs()                # [ORCH-MERGE-HOLD-1]
        if merge_held:
            park += (" | " if park else "") + "⏸ held for a human merge: " + ", ".join(p["file"] for p in merge_held)
        if not argv[1:]:
            print(status_line(st) + (f" | {pause_notice_line(notice)}" if notice else "") + (f" | {fg}" if fg else "")
                  + (f" | {deps}" if deps else "") + (f" | {park}" if park else ""))
        r = d.get_status()
        r.update({k: st.get(k) for k in DAEMON_OWNED_KEYS})
        r["config"] = {**r["config"], **_executor_of(st)}   # the daemon's executor, not this process's
        r["pause_notice"] = notice
        r["full_gate"] = summary
        print(json.dumps(r, indent=2, default=str))
    elif cmd in ("pause", "resume"):
        opts = _control_args(cmd, argv[1:])
        if opts is None:
            print(USAGE, file=sys.stderr)
            return 2
        rc, msg = request_control(cmd, **opts)
        print(msg)
        return rc
    elif cmd == "clear":
        r = d.clear_queue()
        print(json.dumps(r, indent=2))
    elif cmd == "config" and len(argv) == 3:
        # [CONFIG-TRUTH-1] a refusal is printed and the exit is 1. This process is not the daemon: a
        # running one keeps its config in memory and rewrites queue-state.json at its next save, so a
        # value written here while one may be running would change nothing — refused too, and said.
        key, value = argv[1:]
        _, error = parse_config(key, value)
        st = read_persisted_state()
        pid = st.get("pid")
        if error is None and st.get("daemon_status") not in (None, "stopped") and (
                pid is None or _pid_alive(pid) is not False):
            error = (f"{key} not set: a daemon may be running (daemon_status={st.get('daemon_status')}, "
                     f"pid {pid if pid is not None else 'not recorded'}); it keeps its config in memory and "
                     f"rewrites queue-state.json at its next save, so a value written here would change "
                     f"nothing — set it while no daemon runs")
        r = {"ok": False, "error": error} if error else d.update_config(key, value)
        if r["ok"]:
            r["config"] = {**r["config"], **_executor_of(read_persisted_state())}   # as `status` shows it
            r["note"] = "written to queue-state.json; the next daemon start reads it"
        print(json.dumps(r, indent=2, ensure_ascii=False))
        return 0 if r["ok"] else 1
    elif cmd == "check":
        # Boot assert B6 as a command — the two commands a human used to run by hand,
        # report-only. The daemon retires on start; this one never moves anything.
        violations = d.find_merged_briefs()
        for v in violations:
            print(f"FAIL {v}")
        print(f"B6: {len(violations)} queued brief(s) whose route already merged")
        return 1 if violations else 0
    elif cmd == "check-logs":
        # ORCH-STDOUT-1 over completed + failed + stopped, report-only. Deliberately NOT part of
        # `check`: B6's exit semantics stay B6's. Entries recorded before ORCH-STDOUT-1
        # have no log_file and report no-log-recorded until they roll out of the lists.
        violations = d.find_missing_gate_logs()
        for v in violations:
            print(f"FAIL {v}")
        counts = {}
        for v in violations:
            counts[v.reason] = counts.get(v.reason, 0) + 1
        breakdown = ", ".join(f"{n} {r}" for r, n in counts.items())
        print(f"ORCH-STDOUT-1: {len(violations)} recorded route(s) without a readable log"
              + (f" ({breakdown})" if violations else ""))
        return 1 if violations else 0
    else:
        print(USAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

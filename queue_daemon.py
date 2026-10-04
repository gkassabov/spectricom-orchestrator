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
  python3 queue_daemon.py              # run daemon
  python3 queue_daemon.py enqueue <f>  # copy batch to queue/
  python3 queue_daemon.py status       # show queue state (line 1: daemon_status, paused_reason, paused_at)
  python3 queue_daemon.py pause        # ask the RUNNING daemon to pause (control file; no restart)
  python3 queue_daemon.py resume [--reset-consecutive]   # ask it to resume
  python3 queue_daemon.py config <key> <value>   # max_consecutive | cooldown_seconds | stop_on_failure,
                                                 # no daemon running; anything else is refused, exit 1
  python3 queue_daemon.py check        # boot assert B6: queued briefs whose route already merged
  python3 queue_daemon.py check-logs   # ORCH-STDOUT-1: recorded routes without a readable log
"""

import os, sys, json, time, shutil, threading, subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
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
                     "pid", "control_ack", "control_result")


def control_file() -> Path:
    """Resolved per call, not at import: ORCH_DIR is patched in tests and the file must follow it."""
    return ORCH_DIR / "state" / CONTROL_FILE_NAME


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
    "timeout_seconds": ("the daemon's route kill is queue_daemon.py's default, kept above orchestrator.py's own "
                        "180-minute cap; it is read at daemon start (queue-state.json, else that default)"),
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


def status_line(st: dict) -> str:
    """P-PAUSE: the first line `status` prints — the three fields a human needs, from the file."""
    pid = st.get("pid")
    who = ("pid not recorded — a daemon started before QUEUE-PAUSE-OPAQUE" if pid is None
           else f"pid {pid} {'DEAD' if _pid_alive(pid) is False else 'alive'}")
    return (f"daemon_status={st.get('daemon_status') or '-'} paused_reason={st.get('paused_reason') or '-'} "
            f"paused_at={st.get('paused_at') or '-'} | {who} | updated_at={st.get('updated_at') or '-'}")


def request_control(action: str, reset_consecutive: bool = False, wait_s: float = CONTROL_ACK_WAIT_S,
                    poll_s: float = 0.5) -> tuple:
    """[QUEUE-PAUSE-OPAQUE] P-RESUME, the CLI half of `pause` / `resume [--reset-consecutive]`: write
    one request with the next monotonic id, then wait up to `wait_s` for the daemon's ack.

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


class QueueDaemon:
    """Background queue processor for Toni batches."""

    def __init__(self):
        self.status = "idle"
        self.current_batch = None
        self.current_process = None
        self.completed = []
        self.failed = []
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
            # MUST stay ABOVE orchestrator.py's own 180m hard cap, so the orchestrator
            # times out gracefully (branch preserved, fire lock released) instead of
            # this daemon SIGKILLing it mid-route and leaving a stale lock.
            "timeout_seconds": 11400,
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
                self.refused = data.get("refused", [])
                self.persisted_executor = _executor_of(data)
                self.persisted_repo = (data.get("config") or {}).get("repo")
                self.config.update({k: v for k, v in (data.get("config") or {}).items()
                                    if k not in EXECUTOR_KEYS and k != "repo"})
                self.consecutive_count = data.get("consecutive_count", 0)
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
                "queue": [f.name for f in self._scan_queue()],
                "completed": self.completed[-30:],
                "failed": self.failed[-15:],
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
            QUEUE_STATE.write_text(json.dumps(data, indent=2, default=str))
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
                "started_at": self.started_at,
                "current_batch": self.current_batch,
                "current_elapsed_s": elapsed,
                "current_elapsed_fmt": f"{elapsed/60:.1f}m" if elapsed else None,
                "queue": [{"name": f.name, "size": f.stat().st_size} for f in queue_files],
                "queue_count": len(queue_files),
                "completed": self.completed[-10:],
                "failed": self.failed[-5:],
                "refused": self.refused[-5:],
                "config": self.config,
                "consecutive_count": self.consecutive_count,
                "completed_total": len(self.completed),
                "failed_total": len(self.failed)
            }

    def enqueue(self, batch_path):
        src = Path(batch_path).expanduser().resolve()
        if not src.exists():
            return {"ok": False, "error": f"File not found: {batch_path}"}
        if not src.name.endswith(".md"):
            return {"ok": False, "error": "Only .md batch files accepted"}
        self._ensure_dirs()
        dst = QUEUE_DIR / src.name
        shutil.copy2(str(src), str(dst))
        self._save_state()
        return {"ok": True, "queued": src.name, "queue_count": len(self._scan_queue())}

    def _mark_paused(self, reason: str):
        """[QUEUE-PAUSE-OPAQUE] P-PAUSE: every transition into `paused` says why and since when. The
        caller saves, holding the lock where it has to — this takes none."""
        self.status = "paused"
        self.paused_reason = reason
        self.paused_at = datetime.now().isoformat()
        hint = " --reset-consecutive" if reason.startswith("max-consecutive:") else ""
        print(f"[QUEUE] PAUSED — {reason}. Resume without a restart: python3 queue_daemon.py resume{hint}")

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
        """ORCH-STDOUT-1 over the recorded history: every completed/failed entry whose log is
        not a readable, non-empty file. Empty = clean. Report only — `check-logs` calls this."""
        return check_gate_log_invariants(self.completed + self.failed)

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
        if action == "pause":
            self.pause("operator")
            result = f"pause → {self.status} ({self.paused_reason})"
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

    def _clear_stale_markers(self):
        """[QUEUE-PAUSE-OPAQUE] P-STALE: a running marker whose PID is dead does not hold a fire. The
        markers are the root running*.json (the legacy file the fire lock is waited on) and
        state/running*.json (the per-repo locks and their mirror). A marker's PID is its own `pid`,
        else — for a legacy root file written before it carried one — the pid of the per-repo lock
        naming the same batch. Dead ⇒ renamed aside to `<name>.killed-<ts>` (never deleted) and said
        once. No pid to be had ⇒ kept, and said once: it cannot be judged. Alive, unreadable or
        mid-write ⇒ left alone."""
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

    def _fire_lock_held(self) -> bool:
        """The fire lock the daemon waits on (root running*.json), after P-STALE has cleared the dead."""
        self._clear_stale_markers()
        return any(ORCH_DIR.glob("running*.json"))

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
        self.status = "running"
        self.paused_reason = self.paused_at = None
        self._save_state()

        print(f"[QUEUE] Daemon started. Watching {QUEUE_DIR}")
        print(f"[QUEUE] Config: max={self.config['max_consecutive']}, "
              f"cooldown={self.config['cooldown_seconds']}s, "
              f"stop_on_fail={self.config['stop_on_failure']}")
        print(executor_default_line(self.persisted_executor, self.config, os.environ))
        print(repo_rule_line(self.persisted_repo, os.environ))

        while self.status != "stopped":
            self._poll_control()
            if self.status == "paused":
                time.sleep(PAUSED_POLL_S)
                continue

            if self.consecutive_count >= self.config["max_consecutive"]:
                print(f"[QUEUE] Max consecutive ({self.config['max_consecutive']}) reached. Pausing.")
                self._mark_paused(f"max-consecutive:{self.config['max_consecutive']}")
                self._save_state()
                continue

            queue = self._scan_queue()
            if not queue:
                time.sleep(10)
                continue

            next_batch = queue[0]
            batch_name = next_batch.name
            # [ORCH-YORSIE-SAFETY-1] Y1: a brief names its repo or is refused — before the fire lock and
            # before current_batch, so nothing fires and the next brief is taken at once.
            if not _parse_batch_header(next_batch).get("repo"):
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
            _waited = 0
            while self.status == "running" and self._fire_lock_held():
                if _waited == 0:
                    print(f"[QUEUE] fire lock held — waiting before {batch_name}")
                time.sleep(30)
                _waited += 30
                self._poll_control()
                if _waited > 14400:   # 4h: something is wedged, say so and stop trying
                    print(f"[QUEUE] fire lock still held after 4h — leaving {batch_name} queued")
                    break
            if self.status != "running" or self._fire_lock_held():
                with self.lock:
                    self.current_batch = None
                    self._save_state()
                if self.status == "running":
                    time.sleep(self.config["cooldown_seconds"])
                continue
            if _waited:
                print(f"[QUEUE] lock clear after {_waited}s")

            print(f"[QUEUE] Firing: {batch_name}")

            # A batch may name its own model/effort on the first line as
            #   #!queue model=claude-sonnet-4-5 effort=high repo=clinical-mp
            # so a mechanical cleanup route can run Sonnet while RM increments run
            # Fable, without restarting the daemon (George, 2026-09-16). It MUST name its repo.
            hdr = _parse_batch_header(next_batch)   # re-read: it may have been edited while it waited
            b_model = hdr.get("model", self.config["model"])
            b_effort = hdr.get("effort", self.config["effort"])
            b_repo = hdr.get("repo")
            if not b_repo:
                with self.lock:
                    self.current_batch = None
                self._refuse(next_batch, NO_REPO_REFUSAL)
                continue

            cmd = (
                f"cd {ORCH_DIR} && unset ANTHROPIC_API_KEY && "
                f"python3 -u orchestrator.py run {next_batch} --approve "
                f"--repo {b_repo} --model {b_model} --effort {b_effort}"
            )
            print(f"[QUEUE] repo={b_repo} model={b_model} effort={b_effort}")

            log_path = route_log_path(b_repo, batch_name, start_time)
            with self.lock:
                if self.current_batch is not None:
                    self.current_batch["log_file"] = str(log_path)
                self._save_state()
            print(f"[QUEUE] log={log_path}")

            exit_code = self._run_route(cmd, batch_name, log_path)

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
                    print(f"[QUEUE] PASSED: {batch_name} ({duration_s:.0f}s)")
                else:
                    _safe_move(next_batch, QUEUE_FAILED / batch_name)
                    self.failed.append(entry)
                    print(f"[QUEUE] FAILED: {batch_name} (exit {exit_code}, {duration_s:.0f}s)")
                    if self.config["stop_on_failure"]:
                        print(f"[QUEUE] stop_on_failure=true. Pausing queue.")
                        self._mark_paused(f"stop-on-failure:{batch_name}")

                # ORCH-STDOUT-1 — post-route oracle. Reports; changes no state and no verdict.
                for v in check_gate_log_invariants([entry]):
                    print(f"[QUEUE] ⛔ ORCH-STDOUT-1 invariant: {v}")

                self.current_batch = None
                self.current_process = None
                self._save_state()

            if self.status == "running" and self.config["cooldown_seconds"] > 0:
                print(f"[QUEUE] Cooldown {self.config['cooldown_seconds']}s...")
                time.sleep(self.config["cooldown_seconds"])

        print("[QUEUE] Daemon stopped.")

    def _run_route(self, cmd: str, batch_name: str, log_path: Path) -> int:
        """Run one route with its stdout+stderr going to `log_path`; return its exit code.

        ORCH-STDOUT-1. The child gets an open FILE as stdout — fire_toni's shape — never a
        pipe: a pipe nobody reads deadlocks once the child writes 64 KiB, and a pipe read into
        memory loses everything if the daemon dies mid-route. With a file there is no buffer to
        fill, output is on disk as it is produced (`tail -f` works), and a kill leaves a partial
        log. Appended, not truncated, so cancel_current's trailer and this one both land.

        Exit codes are unchanged: the child's own, -1 on timeout, -2 on any other error
        (including a log that cannot be opened). A trailer is written on every path it can be.
        """
        timeout = self.config["timeout_seconds"]
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
                exit_code = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                print(f"[QUEUE] Timeout ({timeout}s) on {batch_name}. Killing.")
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


def main(argv: list) -> int:
    if not argv:
        d = QueueDaemon()
        try:
            d.run_loop()
        except KeyboardInterrupt:
            d.stop()
            print("\\nQueue daemon stopped.")
        return 0
    cmd = argv[0]
    d = QueueDaemon()
    if cmd == "enqueue" and len(argv) > 1:
        r = d.enqueue(argv[1])
        print(json.dumps(r, indent=2))
    elif cmd == "status":
        # [QUEUE-PAUSE-OPAQUE] P-PAUSE: this process is not the daemon. Line 1 and every daemon field
        # below come from what the daemon persisted, never from this object's own "idle".
        st = read_persisted_state()
        print(status_line(st))
        r = d.get_status()
        r.update({k: st.get(k) for k in DAEMON_OWNED_KEYS})
        r["config"] = {**r["config"], **_executor_of(st)}   # the daemon's executor, not this process's
        print(json.dumps(r, indent=2, default=str))
    elif cmd in ("pause", "resume"):
        rc, msg = request_control(cmd, reset_consecutive="--reset-consecutive" in argv[1:])
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
        # ORCH-STDOUT-1 over completed + failed, report-only. Deliberately NOT part of
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
        print(f"Usage: {sys.argv[0]} [enqueue <file> | status | pause | resume [--reset-consecutive] "
              f"| config <key> <value> | check | check-logs | clear]")
        print(f"  Or run without args to start the daemon loop.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
# filename: scripts/heavy_leg.py
"""[LANE-HEAVY-LEG-GUARD-1] An author's heavy dry-run leg (vitest run / related, tsc, pytest) run the one safe way.

Three lessons, turned into code checks (SD-6):
  * EMPTY LIST (S7-CORE-64 Lane A, 2026-11-27): an empty test-file list made `vitest run $(cat list)` / `vitest related`
    run the WHOLE unit suite for 11 min beside a route. `--files-from LIST` with no file in it is refused, nothing runs;
    a vitest `run` / `related` command with no file operand is refused unless `--whole-suite` says that is meant.
  * ONE HEAVY JOB BESIDE A GATE (L-562, rule #31 (h); machine clear D-S7CORE54-78): a "is a gate running?" check made
    only before a leg let the leg run beside a gate that started after it. A leg runs only under heavy.lock — taken here
    (`--lock PATH`, or $HEAVY_LOCK), or proven held by an ancestor (`--lock-held`, read from /proc/locks) — so it is the
    single heavy job; and whenever a route is live (queue-state.json `current_batch` set, its executor phase included:
    its gate may start mid-leg) or the nightly full gate runs, a vitest leg's workers are capped to
    `--gate-workers` (default 2). The state file notes a gate that starts while the leg runs.
  * PID ONLY (L-563, rule #27): a `pgrep -f` pattern kill took a lane's own shell. The leg runs in its own session; its
    pid / pgid go to `--state FILE` before it starts, and `heavy_leg.py stop --state FILE` ends that process group by its
    id only (TERM, then KILL after 5 s) — never by a pattern.

Usage:
  heavy_leg.py run --state S [--lock PATH | --lock-held PATH] [--lock-wait SEC] [--files-from LIST] [--whole-suite]
                   [--gate-workers N] [--queue-state FILE] [--log FILE] -- CMD [ARG …]   ({files} in CMD = the list)
  heavy_leg.py stop --state S
  heavy_leg.py gate [--queue-state FILE]        (prints the daemon's phase; exit 0 idle, 1 route live / gating)
Exit: the command's own exit; 2 usage; 3 refused (empty list / whole suite not asked); 4 heavy.lock not held / not taken.
Reads queue-state.json and the route's orch log; never runs queue_daemon.py; standard library only.
"""

import argparse
import fcntl
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ORCH_DIR = Path(__file__).resolve().parent.parent
QUEUE_STATE = ORCH_DIR / "queue-state.json"
GATE_WORKERS = 2
STOP_GRACE_S = 5
WATCH_EVERY_S = 15
EXIT_USAGE, EXIT_REFUSED, EXIT_LOCK = 2, 3, 4
GATE_START = "Pre-merge gate on"                      # orchestrator.py's gate opener, as waitclear.sh reads it
GATE_DONE = re.compile(r"FINAL STATUS|^Finished:|merge withheld|parked", re.MULTILINE)
# vitest options that take the next word as their value (so that word is not a file operand)
_VITEST_VALUE_OPTS = {"--config", "-c", "--project", "--maxWorkers", "--minWorkers", "--reporter", "--outputFile",
                      "--root", "-r", "--dir", "--pool", "--environment", "--shard", "--testNamePattern", "-t",
                      "--exclude", "--mode", "--testTimeout", "--hookTimeout", "--bail", "--retry", "--sequence.seed",
                      "--changed", "--coverage.reporter", "--inspect", "--inspect-brk", "--api"}
_MAXW = re.compile(r"^--max-?[wW]orkers(?:=(.*))?$")


def now() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


# ── the daemon's phase ──────────────────────────────────────────────────────────────────────────────────────────────
def daemon_phase(queue_state: Path) -> tuple[str, str]:
    """(phase, detail): 'idle' | 'executor' (a route live, not yet in its gate) | 'gate' (a route in its pre-merge gate,
    or the nightly full gate) | 'unknown' (the state cannot be read — treated as live by the caller)."""
    try:
        st = json.loads(Path(queue_state).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return "unknown", "%s unreadable (%s)" % (queue_state, type(e).__name__)
    if not isinstance(st, dict):
        return "unknown", "%s is not a JSON object" % queue_state
    if st.get("full_gate_running"):
        return "gate", "nightly full gate running (%s)" % str(st.get("full_gate_running"))[:80]
    b = st.get("current_batch") or {}
    if not isinstance(b, dict) or not b.get("file"):
        return "idle", "no route live"
    log = b.get("log_file")
    try:
        text = Path(log).read_text(encoding="utf-8", errors="replace") if log else ""
    except OSError:
        text = ""
    if GATE_START in text and not GATE_DONE.search(text.split(GATE_START, 1)[1]):
        return "gate", "%s in its pre-merge gate" % b["file"]
    if GATE_START in text:
        return "executor", "%s past its gate verdict" % b["file"]
    return "executor", "%s live, executor phase (its gate may start during the leg)" % b["file"]


# ── what the command is ─────────────────────────────────────────────────────────────────────────────────────────────
def vitest_sub(cmd: list[str]):
    """Index of vitest's sub-command word (`run` / `related`) and the word, or (None, None) when CMD is not a vitest
    run. `vitest` bare (watch mode / run) counts as `run`."""
    for i, w in enumerate(cmd):
        if os.path.basename(w) == "vitest":
            nxt = cmd[i + 1] if i + 1 < len(cmd) else ""
            if nxt in ("run", "related"):
                return i + 1, nxt
            return i, "run"
    return None, None


def vitest_operands(cmd: list[str]) -> list[str]:
    """The file / filter operands after vitest's sub-command (option values skipped)."""
    k, _ = vitest_sub(cmd)
    if k is None:
        return []
    out, i, rest = [], 0, cmd[k + 1:]
    while i < len(rest):
        w = rest[i]
        if w == "--":
            out += rest[i + 1:]
            break
        if w.startswith("-"):
            if "=" not in w and w in _VITEST_VALUE_OPTS:
                i += 1
        else:
            out.append(w)
        i += 1
    return out


def cap_workers(cmd: list[str], n: int) -> tuple[list[str], str]:
    """A vitest command with its workers capped to n (an existing --maxWorkers above n lowered, none ⇒ added)."""
    k, _ = vitest_sub(cmd)
    if k is None:
        return cmd, ""
    out, i, said = list(cmd), 0, ""
    while i < len(out):
        m = _MAXW.match(out[i])
        if m:
            val = m.group(1) if m.group(1) is not None else (out[i + 1] if i + 1 < len(out) else "")
            try:
                cur = int(val)
            except ValueError:
                cur = None
            if cur is None or cur > n:
                if m.group(1) is not None:
                    out[i] = "--maxWorkers=%d" % n
                else:
                    out[i + 1] = str(n)
                said = "--maxWorkers %s→%d" % (val, n)
            else:
                said = "--maxWorkers %d kept (≤ %d)" % (cur, n)
            return out, said
        i += 1
    out.insert(k + 1, "--maxWorkers=%d" % n)
    return out, "--maxWorkers=%d added" % n


# ── heavy.lock ──────────────────────────────────────────────────────────────────────────────────────────────────────
def _ancestors(pid: int) -> list[int]:
    seen = []
    while pid > 1 and pid not in seen:
        seen.append(pid)
        try:
            stat = Path("/proc/%d/stat" % pid).read_text()
        except OSError:
            break
        pid = int(stat[stat.rindex(")") + 2:].split()[1])
    return seen


def lock_held_by_ancestor(lock: Path, proc_locks: Path = Path("/proc/locks"), pid: int = 0) -> bool:
    """True when an flock on `lock` is held by this process or one of its ancestors (`flock LOCK bash -c …`)."""
    try:
        s = os.stat(lock)
        table = proc_locks.read_text()
    except OSError:
        return False
    key = "%02x:%02x:%d" % (os.major(s.st_dev), os.minor(s.st_dev), s.st_ino)
    mine = set(_ancestors(pid or os.getpid()))
    for line in table.splitlines():
        f = line.split()
        if "->" in f:                                   # a waiter, not a holder
            continue
        if len(f) >= 6 and f[1] == "FLOCK" and f[5] == key and f[4].isdigit() and int(f[4]) in mine:
            return True
    return False


def take_lock(lock: Path, wait_s: float):
    """An open fd holding an exclusive flock on `lock`, or None when not taken within wait_s. A blocking wait (as
    `flock -w` waits), so a leg queues fairly beside the lanes' `flock` waiters instead of polling behind them."""
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BlockingIOError:
        pass
    if wait_s <= 0:
        os.close(fd)
        return None
    armed = [True]

    def _expired(*_):
        if armed[0]:
            raise TimeoutError
    old = signal.signal(signal.SIGALRM, _expired)
    signal.setitimer(signal.ITIMER_REAL, wait_s)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        armed[0] = False
        return fd
    except TimeoutError:
        os.close(fd)
        return None
    finally:
        armed[0] = False
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)


# ── state file ──────────────────────────────────────────────────────────────────────────────────────────────────────
def write_state(path: Path, st: dict) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(st, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def say(st_path: Path, st: dict, line: str) -> None:
    st.setdefault("lines", []).append("%s %s" % (now(), line))
    write_state(st_path, st)
    print("heavy_leg: %s" % line, flush=True)


def read_list(p: Path) -> list[str]:
    return [ln.strip() for ln in Path(p).read_text(encoding="utf-8").splitlines() if ln.strip()]


def cmd_run(a) -> int:
    st_path = Path(a.state)
    cmd = list(a.cmd[1:] if a.cmd[:1] == ["--"] else a.cmd)
    if not cmd:
        print("heavy_leg: no command after --", file=sys.stderr)
        return EXIT_USAGE
    st = {"pid": None, "pgid": None, "cmd": cmd, "state": "refused", "started": None, "finished": None, "exit": None}
    if a.files_from:
        try:
            files = read_list(Path(a.files_from))
        except OSError as e:
            say(st_path, st, "REFUSED — --files-from %s cannot be read (%s); nothing run" % (a.files_from, e.strerror))
            return EXIT_REFUSED
        if not files:
            say(st_path, st, "REFUSED — EMPTY LIST: %s holds no test file; `vitest run` / `vitest related` with no file "
                             "runs the WHOLE suite (S7-CORE-64 Lane A, 11 min beside a route); nothing run"
                % a.files_from)
            return EXIT_REFUSED
        cmd = [x for w in cmd for x in (files if w == "{files}" else [w])] if "{files}" in cmd else cmd + files
    elif "{files}" in cmd:
        print("heavy_leg: {files} in the command needs --files-from", file=sys.stderr)
        return EXIT_USAGE
    k, sub = vitest_sub(cmd)
    if k is not None and not vitest_operands(cmd) and not a.whole_suite:
        say(st_path, st, "REFUSED — vitest %s names no file: it would run the WHOLE suite; pass the files (or "
                         "--files-from), or --whole-suite when the whole suite is meant; nothing run" % sub)
        return EXIT_REFUSED
    lock_fd = None
    if a.lock_held:
        if not lock_held_by_ancestor(Path(a.lock_held)):
            say(st_path, st, "REFUSED — --lock-held %s: no flock on it is held by this process or an ancestor; "
                             "a heavy leg runs only as the single heavy job under heavy.lock (rule #31 (h))"
                % a.lock_held)
            return EXIT_LOCK
        st["lock"] = "%s (held by an ancestor)" % a.lock_held
    else:
        lock = a.lock or os.environ.get("HEAVY_LOCK")
        if not lock:
            print("heavy_leg: name heavy.lock: --lock PATH, --lock-held PATH or $HEAVY_LOCK", file=sys.stderr)
            return EXIT_USAGE
        st["state"] = "waiting-lock"
        say(st_path, st, "waiting for %s (up to %ds)" % (lock, a.lock_wait))
        lock_fd = take_lock(Path(lock), a.lock_wait)
        if lock_fd is None:
            st["state"] = "refused"
            say(st_path, st, "REFUSED — %s not taken within %ds; nothing run" % (lock, a.lock_wait))
            return EXIT_LOCK
        st["lock"] = "%s (taken)" % lock
    try:
        phase, detail = daemon_phase(Path(a.queue_state))
        st["phase_at_start"] = "%s: %s" % (phase, detail)
        if phase != "idle":
            cmd, how = cap_workers(cmd, a.gate_workers)
            say(st_path, st, "route live or gating (%s) — single heavy job under heavy.lock%s"
                % (st["phase_at_start"], "; " + how if how else ""))
        st["cmd"] = cmd
        out = open(a.log, "ab") if a.log else None
        try:
            # the leg inherits the lock's fd: heavy.lock stays held while any of its group lives
            p = subprocess.Popen(cmd, start_new_session=True, stdout=out or None, stderr=subprocess.STDOUT if out else None,
                                 pass_fds=(lock_fd,) if lock_fd is not None else ())
        except OSError as e:
            st["state"] = "failed-to-start"
            say(st_path, st, "could not start %s (%s)" % (cmd[0], e.strerror))
            return 127
        st.update(pid=p.pid, pgid=os.getpgid(p.pid), state="running", started=now())
        say(st_path, st, "started pid %d pgid %d: %s" % (p.pid, st["pgid"], " ".join(cmd)[:300]))
        stop = threading.Event()

        def watch():
            seen = phase
            while not stop.wait(a.watch_every):
                ph, det = daemon_phase(Path(a.queue_state))
                if ph == "gate" and seen != "gate":
                    say(st_path, st, "gate started while the leg runs (%s)" % det)
                seen = ph
        t = threading.Thread(target=watch, daemon=True)
        t.start()
        rc = p.wait()
        stop.set()
        if out:
            out.close()
        st.update(state="done", exit=rc, finished=now())
        say(st_path, st, "exit %d" % rc)
        return rc
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


def _alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cmd_stop(a) -> int:
    st_path = Path(a.state)
    try:
        st = json.loads(st_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        print("heavy_leg: state %s cannot be read (%s) — nothing stopped" % (st_path, type(e).__name__), file=sys.stderr)
        return EXIT_USAGE
    pgid, pid = st.get("pgid"), st.get("pid")
    if not isinstance(pgid, int) or pgid <= 1 or st.get("state") != "running":
        print("heavy_leg: %s records no running leg (state %s) — nothing stopped" % (st_path, st.get("state")))
        return 0
    if pgid == os.getpgid(0):
        print("heavy_leg: pgid %d is this shell's own group — refused" % pgid, file=sys.stderr)
        return EXIT_USAGE
    if not _alive(pgid):
        say(st_path, st, "stop: pgid %d already gone" % pgid)
        st["state"] = "gone"
        write_state(st_path, st)
        return 0
    os.killpg(pgid, signal.SIGTERM)
    end = time.monotonic() + STOP_GRACE_S
    while _alive(pgid) and time.monotonic() < end:
        time.sleep(0.1)
    killed = _alive(pgid)
    if killed:
        os.killpg(pgid, signal.SIGKILL)
    st["state"] = "stopped"
    say(st_path, st, "stopped pgid %d (pid %s) by id — TERM%s" % (pgid, pid, ", then KILL" if killed else ""))
    return 0


def cmd_gate(a) -> int:
    phase, detail = daemon_phase(Path(a.queue_state))
    print("%s: %s" % (phase, detail))
    return 0 if phase == "idle" else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="heavy_leg.py", description=__doc__.split("\n\n")[0])
    sp = ap.add_subparsers(dest="verb", required=True)
    r = sp.add_parser("run")
    r.add_argument("--state", required=True)
    g = r.add_mutually_exclusive_group()
    g.add_argument("--lock")
    g.add_argument("--lock-held")
    r.add_argument("--lock-wait", type=float, default=7200)
    r.add_argument("--files-from")
    r.add_argument("--whole-suite", action="store_true")
    r.add_argument("--gate-workers", type=int, default=GATE_WORKERS)
    r.add_argument("--queue-state", default=str(QUEUE_STATE))
    r.add_argument("--log")
    r.add_argument("--watch-every", type=float, default=WATCH_EVERY_S)
    r.add_argument("cmd", nargs=argparse.REMAINDER)
    s = sp.add_parser("stop")
    s.add_argument("--state", required=True)
    q = sp.add_parser("gate")
    q.add_argument("--queue-state", default=str(QUEUE_STATE))
    a = ap.parse_args(argv)
    return {"run": cmd_run, "stop": cmd_stop, "gate": cmd_gate}[a.verb](a)


if __name__ == "__main__":
    sys.exit(main())

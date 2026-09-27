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
  python3 queue_daemon.py status       # show queue state
  python3 queue_daemon.py check        # boot assert B6: queued briefs whose route already merged
"""

import os, sys, json, time, shutil, threading, subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
# QUEUE-RETIRE-1: one implementation of the trunk invariant, shared by the boot path and the
# tests. It lives with the other boot asserts; nothing here reimplements it.
from canon_assert import QueueRepo, Violation, check_queue_trunk_invariants, queue_header

ORCH_DIR = Path.home() / "spectricom-orchestrator"
QUEUE_DIR = ORCH_DIR / "queue"
QUEUE_DONE = QUEUE_DIR / "done"
QUEUE_FAILED = QUEUE_DIR / "failed"
QUEUE_STATE = ORCH_DIR / "queue-state.json"
ORCHESTRATOR = ORCH_DIR / "orchestrator.py"
REPOS_CONFIG = ORCH_DIR / "config" / "repos.yaml"


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


def repo_route(name: str) -> Optional[QueueRepo]:
    """Resolve a repo name to the (path, merge_target, branch_prefix) the trunk invariant needs.

    Read from config/repos.yaml — the one place that knows — so a repo added there needs no
    change here. An unknown name resolves to None and is skipped rather than guessed at.
    """
    try:
        repos = (yaml.safe_load(REPOS_CONFIG.read_text(encoding="utf-8")) or {}).get("repos") or {}
    except Exception as e:
        print(f"[QUEUE] could not read {REPOS_CONFIG}: {e}")
        return None
    r = repos.get(name) or {}
    if not r.get("project_dir"):
        return None
    return QueueRepo(name=name, path=Path(r["project_dir"]),
                     merge_target=r.get("merge_target", "main"),
                     branch_prefix=r.get("branch_prefix", "orch"))


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
            "repo": os.environ.get("QUEUE_REPO", "clinical-mp"),
            "model": os.environ.get("TONI_MODEL", "claude-fable-5-1"),
            "effort": os.environ.get("TONI_EFFORT", "high"),
            # MUST stay ABOVE orchestrator.py's own 180m hard cap, so the orchestrator
            # times out gracefully (branch preserved, fire lock released) instead of
            # this daemon SIGKILLing it mid-route and leaving a stale lock.
            "timeout_seconds": 11400,
        }
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
                self.config.update(data.get("config", {}))
                self.consecutive_count = data.get("consecutive_count", 0)
            except Exception:
                pass

    def _save_state(self):
        try:
            data = {
                "daemon_status": self.status,
                "started_at": self.started_at,
                "current_batch": self.current_batch,
                "queue": [f.name for f in self._scan_queue()],
                "completed": self.completed[-30:],
                "failed": self.failed[-15:],
                "config": self.config,
                "consecutive_count": self.consecutive_count,
                "updated_at": datetime.now().isoformat()
            }
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
                "started_at": self.started_at,
                "current_batch": self.current_batch,
                "current_elapsed_s": elapsed,
                "current_elapsed_fmt": f"{elapsed/60:.1f}m" if elapsed else None,
                "queue": [{"name": f.name, "size": f.stat().st_size} for f in queue_files],
                "queue_count": len(queue_files),
                "completed": self.completed[-10:],
                "failed": self.failed[-5:],
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

    def pause(self):
        with self.lock:
            if self.status in ("running", "idle"):
                self.status = "paused"
                self._save_state()
        return {"ok": True, "status": self.status}

    def resume(self):
        with self.lock:
            if self.status == "paused":
                self.status = "running"
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
                self.failed.append({
                    "file": self.current_batch["file"],
                    "exit_code": -9,
                    "reason": "cancelled by user",
                    "finished_at": datetime.now().isoformat(),
                    "started_at": self.current_batch.get("started_at")
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
            self._save_state()
        return {"ok": True, "consecutive_count": 0, "status": self.status}

    def update_config(self, key, value):
        with self.lock:
            if key in self.config:
                if key in ("max_consecutive", "cooldown_seconds"):
                    self.config[key] = int(value)
                elif key == "stop_on_failure":
                    self.config[key] = bool(value)
                self._save_state()
                return {"ok": True, "config": self.config}
        return {"ok": False, "error": f"Unknown config key: {key}"}

    def queue_repos(self) -> list[QueueRepo]:
        """The repos this queue's briefs actually name — `#!queue repo=…`, plus the configured
        default for the briefs that name nothing. A queue is multi-repo; the trunk invariant is
        per repo, so it is asked once per repo rather than once per brief."""
        names = {self.config["repo"]}
        for f in self._scan_queue():
            names.add(_parse_batch_header(f).get("repo") or self.config["repo"])
        return [r for r in (repo_route(n) for n in sorted(names)) if r is not None]

    def find_merged_briefs(self) -> list[Violation]:
        """Every queued brief whose route is already on its repo's merge target. Empty = clean."""
        out = []
        for repo in self.queue_repos():
            out.extend(check_queue_trunk_invariants(QUEUE_DIR, repo))
        return out

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

    def run_loop(self):
        """Main daemon loop. Call from a background thread."""
        self._ensure_dirs()
        # QUEUE-RETIRE-1 / T3 — B6 before the first batch, never after it.
        self.retire_merged_briefs()
        self.started_at = datetime.now().isoformat()
        self.status = "running"
        self._save_state()

        print(f"[QUEUE] Daemon started. Watching {QUEUE_DIR}")
        print(f"[QUEUE] Config: max={self.config['max_consecutive']}, "
              f"cooldown={self.config['cooldown_seconds']}s, "
              f"stop_on_fail={self.config['stop_on_failure']}")

        while self.status != "stopped":
            if self.status == "paused":
                time.sleep(5)
                continue

            if self.consecutive_count >= self.config["max_consecutive"]:
                print(f"[QUEUE] Max consecutive ({self.config['max_consecutive']}) reached. Pausing.")
                self.status = "paused"
                self._save_state()
                continue

            queue = self._scan_queue()
            if not queue:
                time.sleep(10)
                continue

            next_batch = queue[0]
            batch_name = next_batch.name
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
            _waited = 0
            while any(ORCH_DIR.glob("running*.json")):
                if _waited == 0:
                    print(f"[QUEUE] fire lock held — waiting before {batch_name}")
                time.sleep(30)
                _waited += 30
                if _waited > 14400:   # 4h: something is wedged, say so and stop trying
                    print(f"[QUEUE] fire lock still held after 4h — leaving {batch_name} queued")
                    break
            if any(ORCH_DIR.glob("running*.json")):
                time.sleep(self.config["cooldown_seconds"])
                continue
            if _waited:
                print(f"[QUEUE] lock clear after {_waited}s")

            print(f"[QUEUE] Firing: {batch_name}")

            # A batch may name its own model/effort on the first line as
            #   #!queue model=claude-sonnet-4-5 effort=high repo=clinical-mp
            # so a mechanical cleanup route can run Sonnet while RM increments run
            # Fable, without restarting the daemon (George, 2026-09-16).
            hdr = _parse_batch_header(next_batch)
            b_model = hdr.get("model", self.config["model"])
            b_effort = hdr.get("effort", self.config["effort"])
            b_repo = hdr.get("repo", self.config["repo"])

            cmd = (
                f"cd {ORCH_DIR} && unset ANTHROPIC_API_KEY && "
                f"python3 orchestrator.py run {next_batch} --approve "
                f"--repo {b_repo} --model {b_model} --effort {b_effort}"
            )
            print(f"[QUEUE] repo={b_repo} model={b_model} effort={b_effort}")

            exit_code = -1
            try:
                self.current_process = subprocess.Popen(
                    cmd, shell=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    executable="/bin/bash"
                )
                exit_code = self.current_process.wait(
                    timeout=self.config["timeout_seconds"])
            except subprocess.TimeoutExpired:
                print(f"[QUEUE] Timeout ({self.config['timeout_seconds']}s) on {batch_name}. Killing.")
                self.current_process.kill()
                self.current_process.wait()
                exit_code = -1
            except Exception as e:
                print(f"[QUEUE] Error on {batch_name}: {e}")
                exit_code = -2

            end_time = datetime.now()
            duration_s = (end_time - start_time).total_seconds()

            with self.lock:
                entry = {
                    "file": batch_name,
                    "exit_code": exit_code,
                    "duration_s": round(duration_s, 1),
                    "started_at": start_time.isoformat(),
                    "finished_at": end_time.isoformat()
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
                        self.status = "paused"

                self.current_batch = None
                self.current_process = None
                self._save_state()

            if self.status == "running" and self.config["cooldown_seconds"] > 0:
                print(f"[QUEUE] Cooldown {self.config['cooldown_seconds']}s...")
                time.sleep(self.config["cooldown_seconds"])

        print("[QUEUE] Daemon stopped.")

    def stop(self):
        self.cancel_current()
        self.status = "stopped"
        self._save_state()


def start_daemon_thread(daemon):
    """Start daemon in a background thread. Returns the thread."""
    t = threading.Thread(target=daemon.run_loop, daemon=True, name="queue-daemon")
    t.start()
    return t


if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        d = QueueDaemon()
        if cmd == "enqueue" and len(sys.argv) > 2:
            r = d.enqueue(sys.argv[2])
            print(json.dumps(r, indent=2))
        elif cmd == "status":
            r = d.get_status()
            print(json.dumps(r, indent=2))
        elif cmd == "clear":
            r = d.clear_queue()
            print(json.dumps(r, indent=2))
        elif cmd == "check":
            # Boot assert B6 as a command — the two commands a human used to run by hand,
            # report-only. The daemon retires on start; this one never moves anything.
            violations = d.find_merged_briefs()
            for v in violations:
                print(f"FAIL {v}")
            print(f"B6: {len(violations)} queued brief(s) whose route already merged")
            sys.exit(1 if violations else 0)
        else:
            print(f"Usage: {sys.argv[0]} [enqueue <file> | status | check | clear]")
            print(f"  Or run without args to start the daemon loop.")
    else:
        d = QueueDaemon()
        try:
            d.run_loop()
        except KeyboardInterrupt:
            d.stop()
            print("\\nQueue daemon stopped.")

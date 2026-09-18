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
"""

import os, sys, json, time, shutil, threading, subprocess
from pathlib import Path
from datetime import datetime

ORCH_DIR = Path.home() / "spectricom-orchestrator"
QUEUE_DIR = ORCH_DIR / "queue"
QUEUE_DONE = QUEUE_DIR / "done"
QUEUE_FAILED = QUEUE_DIR / "failed"
QUEUE_STATE = ORCH_DIR / "queue-state.json"
ORCHESTRATOR = ORCH_DIR / "orchestrator.py"


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
                if batch_file.exists():
                    shutil.move(str(batch_file), str(QUEUE_FAILED / batch_file.name))
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

    def run_loop(self):
        """Main daemon loop. Call from a background thread."""
        self._ensure_dirs()
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
            b_model, b_effort, b_repo = (
                self.config["model"], self.config["effort"], self.config["repo"])
            try:
                first = next_batch.read_text(encoding="utf-8").splitlines()[0]
                if first.startswith("#!queue"):
                    for tok in first.split()[1:]:
                        if "=" not in tok:
                            continue
                        k, v = tok.split("=", 1)
                        if k == "model":
                            b_model = v
                        elif k == "effort":
                            b_effort = v
                        elif k == "repo":
                            b_repo = v
            except Exception as e:
                print(f"[QUEUE] could not read header of {batch_name}: {e}")

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
                    shutil.move(str(next_batch), str(QUEUE_DONE / batch_name))
                    self.completed.append(entry)
                    self.consecutive_count += 1
                    print(f"[QUEUE] PASSED: {batch_name} ({duration_s:.0f}s)")
                else:
                    shutil.move(str(next_batch), str(QUEUE_FAILED / batch_name))
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
        else:
            print(f"Usage: {sys.argv[0]} [enqueue <file> | status | clear]")
            print(f"  Or run without args to start the daemon loop.")
    else:
        d = QueueDaemon()
        try:
            d.run_loop()
        except KeyboardInterrupt:
            d.stop()
            print("\\nQueue daemon stopped.")

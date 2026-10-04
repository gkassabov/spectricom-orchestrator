#!/bin/bash
# One-line queue status. Run: ~/spectricom-orchestrator/qstat.sh
# Or alias: alias qstat='~/spectricom-orchestrator/qstat.sh'
ORCH=~/spectricom-orchestrator
REPO=~/spectricom-clinical-mp

echo "=========================================="
echo "  Spectricom Queue Status — $(date '+%a %H:%M:%S')"
echo "=========================================="

# Daemon — its own state, as it last wrote it to queue-state.json (ORCH-YORSIE-SAFETY-1 Y3). The fire
# lock below is a ROUTE, not the daemon: a paused daemon holds none, and must never read as idle.
python3 - "$ORCH" <<'PY'
import json, os, sys
from pathlib import Path
orch = Path(sys.argv[1])

def alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except PermissionError:
        return True
    except (ProcessLookupError, TypeError, ValueError, OverflowError):
        return False

try:
    st = json.loads((orch / "queue-state.json").read_text())
except FileNotFoundError:
    st = None
except (OSError, ValueError) as e:
    st = {"daemon_status": f"unreadable ({e})"}
st = st if isinstance(st, dict) or st is None else {"daemon_status": "unreadable (not an object)"}
current = ((st or {}).get("current_batch") or {})
if st is None:
    print("⚪ NO DAEMON STATE | no queue-state.json")
else:
    status, pid = st.get("daemon_status") or "-", st.get("pid")
    fields = (f"daemon_status={status} | paused_reason={st.get('paused_reason') or '-'} | "
              f"paused_at={st.get('paused_at') or '-'}")
    live = pid is not None and alive(pid)
    who = "pid not recorded" if pid is None else f"pid={pid} {'alive' if live else 'dead'}"
    if pid is not None and not live and status != "stopped":
        print(f"❌ DAEMON DEAD | {who} | {fields}")
    elif status == "paused":
        print(f"⏸️  DAEMON PAUSED | {who} | {fields}")
        hint = " --reset-consecutive" if str(st.get("paused_reason")).startswith("max-consecutive:") else ""
        print(f"   resume: python3 queue_daemon.py resume{hint}")
    elif status == "running":
        print(f"✅ DAEMON running | {who} | {fields}")
    else:
        print(f"⚪ DAEMON {status} | {who} | {fields}")
queue = orch / "queue"
waiting = [f for f in sorted(queue.glob("*.md")) if f.is_file() and f.name != current.get("file")] if queue.is_dir() else []
print(f"📥 QUEUED {len(waiting)} brief(s) waiting")
if current.get("file"):
    print(f"▶️  RUNNING {current['file']} | since {current.get('started_at') or '-'}")
PY

# Route — the fire lock: state/running.json mirrors the newest per-repo lock of an orchestrator fire
if [[ -f "$ORCH/state/running.json" ]]; then
  pid=$(python3 -c "import json; print(json.load(open('$ORCH/state/running.json'))['pid'])" 2>/dev/null)
  batch=$(python3 -c "import json; print(json.load(open('$ORCH/state/running.json'))['batch_id'])" 2>/dev/null)
  if kill -0 "$pid" 2>/dev/null; then
    elapsed=$(ps -p $pid -o etime= 2>/dev/null | xargs)
    echo "✅ ROUTE alive | PID=$pid | elapsed=$elapsed | batch=$batch"
  else
    echo "❌ ROUTE DEAD | stale PID=$pid in running.json | batch=$batch"
  fi
else
  echo "⚪ NO ROUTE | no state/running.json — no fire in progress"
fi

# Watchdog
wd_pid=$(ps -eo pid,cmd | grep "^[ ]*[0-9]\+ /bin/bash /home/gkassa/spectricom-orchestrator/watchdog.sh" | awk "{print \$1}" | head -1)
if [[ -n "$wd_pid" ]]; then
  wd_elapsed=$(ps -p $wd_pid -o etime= 2>/dev/null | xargs)
  echo "✅ WATCHDOG alive | PID=$wd_pid | elapsed=$wd_elapsed"
else
  echo "❌ WATCHDOG not running"
fi

# Toni activity — in the route's own tree (a Yorsie route's or a meta-fire's worktree, else the lock's
# repo_path), not a fixed repo. ORCH-CONTROL-SCOPE-1 C4: a `worktree_mode: parallel` route records route_worktree.
if [[ -f "$ORCH/state/running.json" ]]; then
  branch=$(python3 -c "import json; print(json.load(open('$ORCH/state/running.json'))['branch'])" 2>/dev/null)
  rpath=$(python3 -c "import json; d=json.load(open('$ORCH/state/running.json')); print(d.get('route_worktree') or d.get('meta_fire_worktree') or d.get('repo_path') or '')" 2>/dev/null)
  mod=$([[ -n "$rpath" ]] && cd "$rpath" && git status -s 2>/dev/null | wc -l || echo "?")
  echo "🔥 TONI branch=$branch | tree=${rpath:-?} | uncommitted files=$mod"
fi

# Last 3 commits on main
echo ""
echo "Recent landed commits (clinical-mp main):"
cd "$REPO" && git log --oneline main -3 2>/dev/null | sed 's/^/  /'

# Watchdog last 5 lines
echo ""
echo "Watchdog last 5 lines:"
tail -5 "$ORCH/logs/watchdog.log" 2>/dev/null | sed 's/^/  /'

echo ""
echo "=========================================="

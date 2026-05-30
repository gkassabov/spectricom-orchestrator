#!/bin/bash
# One-line queue status. Run: ~/spectricom-orchestrator/qstat.sh
# Or alias: alias qstat='~/spectricom-orchestrator/qstat.sh'
ORCH=~/spectricom-orchestrator
REPO=~/spectricom-clinical-mp

echo "=========================================="
echo "  Spectricom Queue Status — $(date '+%a %H:%M:%S')"
echo "=========================================="

# Queue
if [[ -f "$ORCH/state/running.json" ]]; then
  pid=$(python3 -c "import json; print(json.load(open('$ORCH/state/running.json'))['pid'])" 2>/dev/null)
  batch=$(python3 -c "import json; print(json.load(open('$ORCH/state/running.json'))['batch_id'])" 2>/dev/null)
  if kill -0 "$pid" 2>/dev/null; then
    elapsed=$(ps -p $pid -o etime= 2>/dev/null | xargs)
    echo "✅ QUEUE alive | PID=$pid | elapsed=$elapsed | batch=$batch"
  else
    echo "❌ QUEUE DEAD | stale PID=$pid in running.json | batch=$batch"
  fi
else
  echo "⚪ NO QUEUE | no running.json (idle or all done)"
fi

# Watchdog
wd_pid=$(ps -eo pid,cmd | grep "^[ ]*[0-9]\+ /bin/bash /home/gkassa/spectricom-orchestrator/watchdog.sh" | awk "{print \$1}" | head -1)
if [[ -n "$wd_pid" ]]; then
  wd_elapsed=$(ps -p $wd_pid -o etime= 2>/dev/null | xargs)
  echo "✅ WATCHDOG alive | PID=$wd_pid | elapsed=$wd_elapsed"
else
  echo "❌ WATCHDOG not running"
fi

# Toni activity
if [[ -f "$ORCH/state/running.json" ]]; then
  branch=$(python3 -c "import json; print(json.load(open('$ORCH/state/running.json'))['branch'])" 2>/dev/null)
  mod=$(cd "$REPO" && git status -s 2>/dev/null | wc -l)
  echo "🔥 TONI branch=$branch | uncommitted files=$mod"
fi

# Last 3 commits on main
echo ""
echo "Recent landed commits:"
cd "$REPO" && git log --oneline main -3 2>/dev/null | sed 's/^/  /'

# Watchdog last 5 lines
echo ""
echo "Watchdog last 5 lines:"
tail -5 "$ORCH/logs/watchdog.log" 2>/dev/null | sed 's/^/  /'

echo ""
echo "=========================================="

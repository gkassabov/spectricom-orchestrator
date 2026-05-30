#!/bin/bash
# orchestrator-watchdog v4 — uses brief-ID-specific detection (no false positives)
set -u
ORCH=~/spectricom-orchestrator
REPO=~/spectricom-clinical-mp
STATE=$ORCH/state/running.json
LOG=$ORCH/logs/watchdog.log
MANIFEST=$ORCH/brief-manifest.txt

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }

read_manifest() {
  [[ -f "$MANIFEST" ]] && grep -vE '^\s*(#|$)' "$MANIFEST"
}

# Extract brief ID from filename (e.g., "toni-brief-1-5b-019-med-reconciliation.md" → "1-5b-019")
brief_id() {
  echo "$1" | grep -oE '(1-5a|1-5b|2-0|3-0)-[0-9]+' | head -1
}

# Detect landed: search FULL commit history (including bodies) for the brief ID
brief_landed_in_git() {
  local brief="$1"
  local id
  id=$(brief_id "$brief")
  [[ -z "$id" ]] && return 1
  # Search full commit messages (--format=%B) for "1-5b-019" anywhere
  # AND require the commit to be a feat/fix (not random)
  git -C "$REPO" log --all --grep="brief-${id}" --grep="brief-1-5a-${id##*-}" --grep="brief-1-5b-${id##*-}" --grep="brief-2-0-${id##*-}" --grep="brief-3-0-${id##*-}" --oneline 2>/dev/null | head -1 | grep -q .
}

remaining_briefs() {
  local remaining=()
  while IFS= read -r brief; do
    [[ -z "$brief" ]] && continue
    if ! brief_landed_in_git "$brief"; then
      remaining+=("$brief")
    fi
  done < <(read_manifest)
  printf '%s\n' "${remaining[@]}"
}

queue_alive() {
  [[ -f "$STATE" ]] || return 1
  local pid
  pid=$(python3 -c "import json; print(json.load(open('$STATE'))['pid'])" 2>/dev/null) || return 1
  [[ -z "$pid" ]] && return 1
  kill -0 "$pid" 2>/dev/null
}

cleanup_orphan_state() {
  log "Cleaning orphan running.json"
  rm -f "$STATE"
  cd "$REPO" || return
  for branch in $(git branch | grep -oE 'orch-mp-toni-brief-(1-5a|1-5b|2-0|3-0)-[0-9]+-[a-z-]+'); do
    if git diff main.."$branch" --quiet 2>/dev/null; then
      log "Pruning empty orphan branch: $branch"
      git checkout main 2>/dev/null
      git branch -D "$branch" 2>/dev/null
    fi
  done
}

fire_remaining_queue() {
  local remaining
  mapfile -t remaining < <(remaining_briefs)
  if [[ ${#remaining[@]} -eq 0 ]]; then
    log "All manifest briefs landed. Watchdog idle."
    return 0
  fi
  log "Firing ${#remaining[@]} remaining briefs (first: ${remaining[0]}, last: ${remaining[-1]})"
  cd "$ORCH" || return 1
  unset ANTHROPIC_API_KEY
  local logfile="$ORCH/logs/orch-watchdog-resume-$(date +%Y%m%d-%H%M%S).log"
  nohup python3 orchestrator.py queue "${remaining[@]}" --repo clinical-mp --approve > "$logfile" 2>&1 &
  local new_pid=$!
  sleep 5
  if kill -0 "$new_pid" 2>/dev/null; then
    log "Queue fired PID=$new_pid log=$logfile remaining=${#remaining[@]}"
    return 0
  else
    log "Queue fire FAILED. Log: $logfile"
    return 1
  fi
}

log "=== Watchdog v4 starting (brief-ID detection). PID=$$ ==="
log "Manifest size: $(read_manifest | wc -l) briefs"

CONSECUTIVE_FAILURES=0
MAX_CONSECUTIVE_FAILURES=5
CHECK_INTERVAL=60
HEARTBEAT_INTERVAL=600
LAST_HEARTBEAT=0

while true; do
  if queue_alive; then
    CONSECUTIVE_FAILURES=0
    NOW=$(date +%s)
    if (( NOW - LAST_HEARTBEAT >= HEARTBEAT_INTERVAL )); then
      pid=$(python3 -c "import json; print(json.load(open('$STATE'))['pid'])" 2>/dev/null)
      batch=$(python3 -c "import json; print(json.load(open('$STATE'))['batch_id'])" 2>/dev/null)
      log "heartbeat: queue alive PID=$pid batch=$batch"
      LAST_HEARTBEAT=$NOW
    fi
  else
    log "Queue not alive. Investigating..."
    sleep 10
    if queue_alive; then
      log "Recovered on retry."
      continue
    fi
    log "Queue confirmed dead/idle. Checking remaining work."
    cleanup_orphan_state
    sleep 5
    fire_remaining_queue
    rc=$?
    if [[ $rc -ne 0 ]]; then
      CONSECUTIVE_FAILURES=$((CONSECUTIVE_FAILURES + 1))
      log "Failure count: $CONSECUTIVE_FAILURES/$MAX_CONSECUTIVE_FAILURES"
      if [[ $CONSECUTIVE_FAILURES -ge $MAX_CONSECUTIVE_FAILURES ]]; then
        log "Too many consecutive failures. Exiting."
        exit 1
      fi
      sleep 120
    else
      [[ ! -f "$STATE" ]] && sleep 120
    fi
  fi
  sleep $CHECK_INTERVAL
done

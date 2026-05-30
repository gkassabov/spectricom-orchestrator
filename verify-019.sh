#!/bin/bash
# verify-019.sh — waits for queue idle, then verifies Brief 019 med-rec build+tests.
# REPORT ONLY. Takes no destructive action (no revert, no re-fire, no checkout of main
# unless tree is already idle+clean). Authored S6S45 EOS per George request.

ORCH=~/spectricom-orchestrator
REPO=~/spectricom-clinical-mp
OUT=$ORCH/logs/verify-019-$(date +%Y%m%d-%H%M%S).log
POLL=120   # seconds between idle checks
MAXWAIT=43200  # 12h safety cap

log(){ echo "[$(date '+%F %T')] $*" | tee -a "$OUT"; }

log "verify-019 guard started. Waiting for queue idle (poll ${POLL}s, cap 12h)."

waited=0
while true; do
  # idle = no orchestrator queue process AND no running.json AND manifest exhausted
  if pgrep -f "orchestrator.py queue" >/dev/null; then
    sleep $POLL; waited=$((waited+POLL))
  elif [[ -f "$ORCH/running.json" ]]; then
    sleep $POLL; waited=$((waited+POLL))
  else
    # double-confirm stable idle: wait one more poll and re-check (avoids catching a between-briefs gap)
    sleep 30
    if ! pgrep -f "orchestrator.py queue" >/dev/null && [[ ! -f "$ORCH/running.json" ]]; then
      log "Queue confirmed idle after ${waited}s wait. Proceeding to verification."
      break
    fi
  fi
  if [[ $waited -ge $MAXWAIT ]]; then
    log "SAFETY CAP hit (12h) without idle. Aborting verification — investigate queue."
    exit 2
  fi
done

cd "$REPO" || { log "FATAL: cannot cd to repo"; exit 1; }

BRANCH=$(git rev-parse --abbrev-ref HEAD)
DIRTY=$(git status --short | wc -l)
log "Repo state: branch=$BRANCH dirty_files=$DIRTY"

if [[ "$BRANCH" != "main" ]]; then
  log "WARN: not on main (on $BRANCH). 019 code is on main. Checking out main for verification."
  if [[ "$DIRTY" -ne 0 ]]; then
    log "ABORT: working tree dirty on $BRANCH — not safe to checkout main. Manual review needed."
    exit 3
  fi
  git checkout main 2>&1 | tee -a "$OUT"
fi

log "Confirming 019 commit present on main..."
git log --oneline --grep="brief-1-5b-019" --grep="med-rec" main 2>/dev/null | head -2 | tee -a "$OUT"

log "=== STEP 1: typecheck + build (tsc && vite build) ==="
npm run build >> "$OUT" 2>&1
BUILD_RC=$?
log "build exit=$BUILD_RC"

log "=== STEP 2: med-rec unit tests (vitest, scoped) ==="
npx vitest run src/lib/clinical/med-reconciliation 2>&1 | tee -a "$OUT"
MEDREC_RC=${PIPESTATUS[0]}
log "med-rec tests exit=$MEDREC_RC"

log "=== STEP 3: encounter-chart test (med-rec integration point) ==="
npx vitest run src/pages/encounter/EncounterChartPage 2>&1 | tee -a "$OUT"
ENC_RC=${PIPESTATUS[0]}
log "encounter test exit=$ENC_RC"

log "================ VERDICT ================"
if [[ $BUILD_RC -eq 0 && $MEDREC_RC -eq 0 && $ENC_RC -eq 0 ]]; then
  log "✅ 019 VERIFIED — build clean, med-rec tests pass, encounter integration passes."
  log "   019 is genuinely done. No re-fire needed."
else
  log "❌ 019 NEEDS ATTENTION — build=$BUILD_RC medrec=$MEDREC_RC enc=$ENC_RC"
  log "   The swept-in commit may be incomplete. Recommend: review log, consider revert 8badc3c + clean re-fire."
fi
log "Full output in: $OUT"
log "verify-019 guard done."

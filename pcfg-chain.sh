#!/bin/bash
# PCFG auto-chain (S6S47) — waits for PCFG-01, fires 02..06 ONLY on success.
# Success = orchestrator state lists PCFG-01 in completed (not failed) AND
# clinical-mp main tip advanced AND no BUILD-GATE/SIT failure git-note.
set -u
ORCH=~/spectricom-orchestrator
REPO=~/spectricom-clinical-mp
CHAINLOG=$ORCH/logs/pcfg-chain-$(date +%Y%m%d-%H%M%S).log
exec >> "$CHAINLOG" 2>&1
echo "=== PCFG CHAIN START $(date -Is) ==="

cd "$ORCH" || exit 1

# 1. Wait for PCFG-01 to finish (running.json clears) — cap 100 min
for i in $(seq 1 200); do
  if [ ! -f running.json ]; then echo "running.json cleared at iter $i ($(date -Is))"; break; fi
  # also break if no claude process AND no orchestrator queue process
  if ! pgrep -f "claude --dangerously" >/dev/null && ! pgrep -f "orchestrator.py queue" >/dev/null; then
    echo "no live fire process at iter $i — treating as finished"; break
  fi
  sleep 30
done

sleep 5  # let post-merge gates + state write settle

# 2. Determine PCFG-01 outcome from orchestrator state
PASSED=$(python3 - <<'PY'
import json,sys,os
p=os.path.expanduser("~/spectricom-orchestrator/orchestrator-state.json")
alt=os.path.expanduser("~/spectricom-orchestrator/state.json")
path=p if os.path.exists(p) else (alt if os.path.exists(alt) else None)
if not path: print("NOSTATE"); sys.exit()
s=json.load(open(path))
comp=[c.get("batch_file","") for c in s.get("completed",[])]
fail=[c.get("batch_file","") for c in s.get("failed",[])]
b="toni-brief-pcfg-01-config-schema.md"
if b in fail: print("FAILED")
elif b in comp: print("PASSED")
else: print("UNKNOWN")
PY
)
echo "PCFG-01 state verdict: $PASSED"

# 3. Cross-check: build-gate / SIT failure notes on main
cd "$REPO" || exit 1
NOTES=$(git notes show HEAD 2>/dev/null || echo "")
echo "HEAD git-notes: ${NOTES:-<none>}"
GATEFAIL=0
echo "$NOTES" | grep -qi "BUILD GATE: FAILED\|SIT: FAILED (BLOCKING)" && GATEFAIL=1

# 4. Decide
cd "$ORCH" || exit 1
if [ "$PASSED" = "PASSED" ] && [ "$GATEFAIL" -eq 0 ]; then
  echo "=== PCFG-01 SUCCESS → firing 02..06 $(date -Is) ==="
  unset ANTHROPIC_API_KEY
  python3 orchestrator.py queue \
    briefs/toni-brief-pcfg-02-hook-gate.md \
    briefs/toni-brief-pcfg-03-route-nav-gating.md \
    briefs/toni-brief-pcfg-04-practice-type-admin.md \
    briefs/toni-brief-pcfg-05-provider-settings-ui.md \
    briefs/toni-brief-pcfg-06-multispecialty-validation.md \
    --repo clinical-mp --approve
  echo "=== chain queue exit: $? $(date -Is) ==="
else
  echo "=== PCFG-01 NOT clean (verdict=$PASSED gatefail=$GATEFAIL) — NOT firing 02..06. Manual review. ==="
fi
echo "=== PCFG CHAIN END $(date -Is) ==="
echo "$CHAINLOG"

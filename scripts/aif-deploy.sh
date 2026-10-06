#!/usr/bin/env bash
# ORCH-CAPACITY-1 C3 (S7-CORE-21, L-71): the MiniMe services move only on purpose.
#
# minig-listen-worker.service and minime-listen-ingest.service run from the ai-foundation MAIN checkout
# (WorkingDirectory=/home/gkassa/spectricom-ai-foundation, ExecStart=…/venv/bin/python -m …). This script is
# the one thing meant to move that checkout. Gemma or George runs it; the orchestrator never does.
#
#   refuses (exit 2), changing nothing, while
#     · an ai-foundation route is live (admission.py routes --repo ai-foundation: a live marker or claim);
#     · a Listen sitting is recording or transcribing (the worker's own store, read through its own
#       derive_status — read-only, no lock taken, no bytecode written);
#     · the checkout has tracked changes, or origin/main is not a fast-forward of its HEAD;
#   otherwise fast-forwards the checkout to origin/main (as last fetched or pushed — no fetch here) and
#   restarts minig-listen-worker. Nothing else is rerun: the ingest timer keeps its own schedule.
#
# Dry-run by default: prints every command it would run and changes nothing. --apply runs them.
#   scripts/aif-deploy.sh            # the plan
#   scripts/aif-deploy.sh --apply    # act
# Overrides, for tests: ORCH_DIR, AIF_DIR, AIF_PYTHON, LISTEN_ENV_FILE, WORKER_UNIT.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORCH_DIR="${ORCH_DIR:-$HERE}"
CONFIG="$ORCH_DIR/config/repos.yaml"
USAGE="Usage: scripts/aif-deploy.sh [--apply]   (dry-run by default; --apply acts)"

APPLY=0
case "${1:-}" in
  "") ;;
  --apply) APPLY=1 ;;
  -h|--help) echo "$USAGE"; exit 0 ;;
  *) echo "$USAGE" >&2; exit 2 ;;
esac
[ $# -le 1 ] || { echo "$USAGE" >&2; exit 2; }

refuse() { echo "⛔ aif-deploy: $* — refused, nothing changed" >&2; exit 2; }

# The repo's entry in config/repos.yaml: where the checkout is, and what it deploys (<remote>/<merge_target>).
read -r CFG_DIR CFG_TARGET < <(python3 - "$CONFIG" <<'PY'
import sys, yaml
r = (yaml.safe_load(open(sys.argv[1])) or {}).get("repos", {}).get("ai-foundation") or {}
print(r.get("project_dir", ""), f"{r.get('remote', 'origin')}/{r.get('merge_target', 'main')}")
PY
) || refuse "cannot read $CONFIG"
AIF_DIR="${AIF_DIR:-$CFG_DIR}"
TARGET_REF="$CFG_TARGET"
AIF_PYTHON="${AIF_PYTHON:-$AIF_DIR/venv/bin/python}"
LISTEN_ENV_FILE="${LISTEN_ENV_FILE:-$HOME/.config/minig-listen.env}"
WORKER_UNIT="${WORKER_UNIT:-minig-listen-worker.service}"
[ -n "$AIF_DIR" ] && git -C "$AIF_DIR" rev-parse --git-dir >/dev/null 2>&1 || refuse "no ai-foundation checkout ($AIF_DIR)"

# 1 · no live ai-foundation route
routes="$(python3 "$HERE/admission.py" --orch-dir "$ORCH_DIR" routes --repo ai-foundation 2>&1)"
case $? in
  0) ;;
  1) refuse "an ai-foundation route is live: $routes" ;;
  *) refuse "cannot read the live routes: $routes" ;;
esac

# 2 · no Listen sitting recording or transcribing — the worker's environment, data root and status rule
listen="$( (set -a; [ -f "$LISTEN_ENV_FILE" ] && . "$LISTEN_ENV_FILE"; set +a
            cd "$AIF_DIR" && PYTHONDONTWRITEBYTECODE=1 exec "$AIF_PYTHON" - ) 2>&1 <<'PY'
import json, sys
from pathlib import Path
from src.minime.listen.config import ListenConfig
from src.minime.listen.store import RECORD_NAME, derive_status
cfg = ListenConfig.from_env()
root = Path(cfg.data_root) / cfg.user_id
busy = []
for rec in sorted(root.glob(f"*/{RECORD_NAME}")):
    status, _ = derive_status(json.loads(rec.read_text(encoding="utf-8")))
    if status in ("recording", "transcribing"):
        busy.append(f"{rec.parent.name} {status}")
print("; ".join(busy) or f"none recording or transcribing under {root}")
sys.exit(3 if busy else 0)
PY
)"
case $? in
  0) ;;
  3) refuse "a Listen sitting is in progress: $listen" ;;
  *) refuse "cannot read the Listen sittings, so cannot tell none is in progress: $(echo "$listen" | tail -3)" ;;
esac

# 3 · a clean tree and a fast-forward
dirty="$(git -C "$AIF_DIR" --no-optional-locks status --porcelain --untracked-files=no)"
[ -z "$dirty" ] || refuse "tracked changes in $AIF_DIR: $(echo "$dirty" | head -5 | tr '\n' ' ')"
head="$(git -C "$AIF_DIR" rev-parse HEAD)"
target="$(git -C "$AIF_DIR" rev-parse -q --verify "$TARGET_REF^{commit}")" || refuse "no $TARGET_REF in $AIF_DIR"
git -C "$AIF_DIR" merge-base --is-ancestor "$head" "$target" \
  || refuse "$TARGET_REF ${target:0:8} is not a fast-forward of HEAD ${head:0:8} in $AIF_DIR"
branch="$(git -C "$AIF_DIR" symbolic-ref -q --short HEAD || echo "a detached HEAD")"

# the plan
mode=$([ "$APPLY" = 1 ] && echo "APPLY" || echo "dry-run")
echo "aif-deploy ($mode) — $AIF_DIR on $branch at ${head:0:8}; $TARGET_REF is ${target:0:8}"
echo "  ✓ no live ai-foundation route · ✓ Listen: $listen · ✓ no tracked changes"
cmds=()
if [ "$head" = "$target" ]; then
  echo "  $AIF_DIR is at $TARGET_REF already — no git command"
else
  echo "  brings in:"; git -C "$AIF_DIR" log --oneline "$head..$target" | head -20 | sed 's/^/    /'
  cmds+=("git -C $(printf '%q' "$AIF_DIR") merge --ff-only $target")
fi
cmds+=("systemctl --user restart $(printf '%q' "$WORKER_UNIT")")
echo "  commands:"
for c in "${cmds[@]}"; do echo "    $c"; done
echo "  not rerun: minime-listen-ingest (its timer keeps its own schedule)"
if [ "$branch" = "${TARGET_REF#*/}" ]; then
  echo "  NOTE: this checkout has ${TARGET_REF#*/} checked out, so an orchestrator merge into ${TARGET_REF#*/} fast-forwards it"
  echo "        in place (orchestrator._land_from_route_worktree / the single-stream route lane). The services"
  echo "        move on purpose only once it is off ${TARGET_REF#*/}: git -C $AIF_DIR switch --detach (George's call)."
fi
if [ "$APPLY" != 1 ]; then
  echo "dry-run: nothing changed. Run with --apply to act."
  exit 0
fi
for c in "${cmds[@]}"; do
  echo "+ $c"
  bash -c "$c" || { echo "⛔ aif-deploy: failed: $c" >&2; exit 1; }
done
echo "✅ aif-deploy: $AIF_DIR at $(git -C "$AIF_DIR" rev-parse --short HEAD); $WORKER_UNIT restarted"

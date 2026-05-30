#!/usr/bin/env bash
# doc-sweep.sh — Spectricom EOS / session-start doc-freshness sweep.
# PURPOSE: decide which docs need bumping from GIT + DISK — never from memory/context.
# Created S6S48. Run at session-start AND at EOS.
#   bash ~/spectricom-orchestrator/doc-sweep.sh
# Staleness rule: a slim is STALE if its mapped repo has commits since the slim's
# git-anchor sha (preferred) or its header Date (bootstrap until anchors exist).
set -uo pipefail

CANON="/mnt/c/Users/gkass/OneDrive/Documents/Spectricom"
H="$HOME"

latest()     { ls -1 $1 2>/dev/null | grep -vE 'DRAFT|BAD|\.bak' | sort -V | tail -1; }
anchor_sha() { grep -oE 'git-anchor:[[:space:]]*[0-9a-f]{7,40}' "$1" 2>/dev/null | grep -oE '[0-9a-f]{7,40}' | head -1; }
# extract a git-parseable "Month DD[,] YYYY" only (drops weekday prefix + parenthetical suffix)
header_date(){ grep -oE '[A-Z][a-z]+ [0-9]{1,2},? [0-9]{4}' "$1" 2>/dev/null | head -1; }

check_slim() {
  local name="$1" repo="$2" glob="$3" filter="${4:-}"
  local f sha hdate n head
  f="$(latest "$glob")"
  if [ -z "$f" ]; then echo "  [$name] NO SLIM for glob: $glob"; return; fi
  if [ ! -d "$repo/.git" ]; then echo "  [$name] $(basename "$f") — repo missing: $repo"; return; fi
  head="$(git -C "$repo" rev-parse --short HEAD)"
  sha="$(anchor_sha "$f")"
  if [ -n "$sha" ]; then
    if [ -n "$filter" ]; then n="$(git -C "$repo" log --oneline "${sha}..HEAD" -- "$filter" 2>/dev/null | wc -l)";
    else n="$(git -C "$repo" log --oneline "${sha}..HEAD" 2>/dev/null | wc -l)"; fi
    if [ "${n:-0}" -gt 0 ]; then echo "  [$name] STALE  — $(basename "$f"): ${n} commit(s) since anchor ${sha} (HEAD ${head}) -> REBUILD";
    else echo "  [$name] FRESH  — $(basename "$f") (anchor ${sha} == HEAD)"; fi
  else
    hdate="$(header_date "$f")"
    if [ -n "$filter" ]; then n="$(git -C "$repo" log --oneline --since="$hdate" -- "$filter" 2>/dev/null | wc -l)";
    else n="$(git -C "$repo" log --oneline --since="$hdate" 2>/dev/null | wc -l)"; fi
    if [ "${n:-0}" -gt 0 ]; then echo "  [$name] STALE  — $(basename "$f"): ${n} commit(s) since '${hdate}' (no anchor) -> REBUILD + add git-anchor";
    else echo "  [$name] FRESH? — $(basename "$f"): 0 commits since '${hdate}' (no anchor; add git-anchor on next bump)"; fi
  fi
}

echo "============ SPECTRICOM DOC SWEEP — git+disk grounded, NOT memory ============"
echo "Run: $(date '+%Y-%m-%d %H:%M:%S %z')"
echo
echo "--- 1. DOMAIN context-slims (rebuild any STALE) ---"
check_slim "clinical" "$H/spectricom-clinical-mp"   "$CANON/spectricom-context-slim-clinical-v1-*.md"
check_slim "yorsie"   "$H/spectricom-dev-pipeline"  "$CANON/spectricom-context-slim-v4-*-yorsie.md" "yorsie"
check_slim "minime"   "$H/spectricom-ai-foundation" "$CANON/spectricom-context-slim-minime-v1-*.md"
echo
echo "--- 2. INFRA context-slim (always-loaded; rebuild if infra changed) ---"
check_slim "infra"    "$H/spectricom-orchestrator"  "$CANON/spectricom-context-slim-v4-*-infra.md"
echo "  uncommitted infra edits ALSO count as material:"
echo "    orchestrator dirty files: $(git -C $H/spectricom-orchestrator status --porcelain 2>/dev/null | wc -l)"
echo "    dev-pipeline dirty files: $(git -C $H/spectricom-dev-pipeline status --porcelain 2>/dev/null | wc -l)"
echo
echo "--- 3. ALWAYS-BUMP EOS set (every session — no judgment, no deferral) ---"
echo "    Logs · Master_Plan(D-165) · Document_Registry · Pending_Canon_Updates · S6S{N}_Handoff"
echo "    Bug Registries (SCA/Yorsie/Mini-Me) ONLY if bugs found/closed this session"
echo
echo "--- 4. GEORGE-ONLY status (not in git; Gemma must ASK at EOS) ---"
echo "    Advisor outreach (Guarente / MH+son)? · Dr. K validation scheduled? · push->origin go/hold? · Drive OAuth done?"
echo "=============================================================================="

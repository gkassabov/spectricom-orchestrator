#!/bin/bash
set -e
ORCH_DIR="$HOME/spectricom-orchestrator"
YORSIE_DIR="$HOME/spectricom-dev-pipeline/yorsie"
echo "═══════════════════════════════════════════════"
echo " SPECTRICOM ORCHESTRATOR SETUP"
echo "═══════════════════════════════════════════════"
mkdir -p "$ORCH_DIR/logs" "$YORSIE_DIR/briefs"
echo "✅ Directories created"
python3 --version || { echo "❌ Python 3 not found"; exit 1; }
echo "✅ Python OK"
command -v claude &>/dev/null && echo "✅ Claude Code found" || { echo "❌ Claude Code not found"; exit 1; }
[ -d "$YORSIE_DIR/.git" ] && echo "✅ Git repo found" || { echo "❌ No git repo at $YORSIE_DIR"; exit 1; }
grep -q 'alias toni=' "$HOME/.bashrc" 2>/dev/null || { echo 'alias toni="unset ANTHROPIC_API_KEY && claude"' >> "$HOME/.bashrc"; echo "✅ Toni alias added"; }
chmod +x "$ORCH_DIR/orchestrator.py" 2>/dev/null
echo ""
echo "✅ SETUP COMPLETE"
echo "  python3 orchestrator.py run <batch.md>"
echo "  python3 orchestrator.py watch"
echo "  python3 orchestrator.py status"

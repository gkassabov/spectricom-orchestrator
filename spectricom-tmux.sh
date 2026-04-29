#!/bin/bash
# SPECTRICOM TMUX — Standard development environment
# D-256 AAI Layer A: queue daemon + dashboard + dev server
#
# Usage:
#   bash spectricom-tmux.sh        # start or attach
#   bash spectricom-tmux.sh stop   # kill session
#   bash spectricom-tmux.sh status # check if running

SESSION="spectricom"
ORCH_DIR="$HOME/spectricom-orchestrator"
YORSIE_DIR="$HOME/spectricom-dev-pipeline/yorsie"

case "${1:-start}" in
  stop)
    tmux kill-session -t "$SESSION" 2>/dev/null && echo "Session '$SESSION' killed." || echo "No session to kill."
    exit 0
    ;;
  status)
    tmux has-session -t "$SESSION" 2>/dev/null && echo "Session '$SESSION' is running." || echo "Session '$SESSION' is not running."
    tmux list-panes -t "$SESSION" -F '  Pane #{pane_index}: #{pane_current_command} (#{pane_width}x#{pane_height})' 2>/dev/null
    exit 0
    ;;
  start|"")
    ;;
  *)
    echo "Usage: $0 [start|stop|status]"
    exit 1
    ;;
esac

# Check if session already exists
tmux has-session -t "$SESSION" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "Session '$SESSION' already running. Attaching..."
    tmux attach-session -t "$SESSION"
    exit 0
fi

echo "Creating Spectricom development session..."

# Pane 0: Dashboard + Queue Daemon (port 8091)
tmux new-session -d -s "$SESSION" -n main
tmux send-keys -t "$SESSION" "cd $ORCH_DIR && python3 orch-dashboard.py --daemon" C-m

# Pane 1: Dev server (port 5173)
tmux split-window -h -t "$SESSION"
tmux send-keys -t "$SESSION" "cd $YORSIE_DIR && npm run dev" C-m

# Pane 2: Free terminal for manual work
tmux split-window -v -t "$SESSION:main.1"
tmux send-keys -t "$SESSION" "cd $YORSIE_DIR" C-m

# Set pane layout: left pane = dashboard, right top = dev server, right bottom = free
tmux select-layout -t "$SESSION" main-vertical

# Focus on free terminal (pane 2)
tmux select-pane -t "$SESSION:main.2"

echo ""
echo "================================================"
echo "  SPECTRICOM DEV SESSION"
echo "  Pane 0: Dashboard + Queue Daemon (:8091)"
echo "  Pane 1: Dev Server (:5173)"
echo "  Pane 2: Free terminal"
echo ""
echo "  Queue: drop .md files in ~/spectricom-orchestrator/queue/"
echo "  Dashboard: http://localhost:8091"
echo "================================================"
echo ""

tmux attach-session -t "$SESSION"

#!/usr/bin/env bash
# filename: scripts/install-queue-daemon-unit.sh
# ORCH-CONTROL-SCOPE-1 C7a (S7-CORE-19) — install the queue daemon's systemd user unit. George runs it:
#   cd ~/spectricom-orchestrator && bash scripts/install-queue-daemon-unit.sh
# It renders systemd/spectricom-queue-daemon.service into ~/.config/systemd/user, reloads systemd and
# ENABLES the unit, so the next boot (a WSL restart) starts the daemon. It never STARTS it: a daemon
# started by hand may be running now, and two daemons would both fire. It says which case it found.
set -euo pipefail

ORCH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT=spectricom-queue-daemon.service
DEST="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
STATE="${QUEUE_STATE:-$ORCH/queue-state.json}"

DAEMON_PATH="$(python3 - "$ORCH/config/repos.yaml" <<'PY'
import sys, yaml
print((yaml.safe_load(open(sys.argv[1])) or {}).get("daemon_path") or "")
PY
)"
if [[ -z "$DAEMON_PATH" ]]; then
  echo "⛔ config/repos.yaml has no daemon_path — the unit's PATH comes from there; nothing installed" >&2
  exit 1
fi

mkdir -p "$DEST" "$ORCH/logs"
sed -e "s|@ORCH_DIR@|$ORCH|g" -e "s|@DAEMON_PATH@|$DAEMON_PATH|g" "$ORCH/systemd/$UNIT" > "$DEST/$UNIT.tmp"
mv "$DEST/$UNIT.tmp" "$DEST/$UNIT"
echo "✅ wrote $DEST/$UNIT (ExecStart $ORCH/queue_daemon.py, ANTHROPIC_API_KEY unset)"

systemctl --user daemon-reload
systemctl --user enable "$UNIT"
echo "✅ enabled $UNIT — the next boot starts the daemon; it comes up paused when work is queued"

pid="$(python3 - "$STATE" <<'PY'
import json, os, sys
try:
    st = json.load(open(sys.argv[1]))
    pid = int(st.get("pid"))
    os.kill(pid, 0)
    print(pid if st.get("daemon_status") != "stopped" else "")
except PermissionError:
    print(pid)
except Exception:
    print("")
PY
)"
if [[ -n "$pid" ]]; then
  echo "⚠️  a daemon is running now (pid $pid) — the unit is enabled, NOT started:"
  echo "   two daemons would both fire. To hand over: stop pid $pid while no route runs, then"
  echo "   systemctl --user start $UNIT"
else
  echo "   no daemon is running — start it now with: systemctl --user start $UNIT"
fi

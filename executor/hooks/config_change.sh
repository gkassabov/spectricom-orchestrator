#!/usr/bin/env bash
# filename: executor/hooks/config_change.sh
# [ORCH-GUARD-HARDEN-1] (S7-CORE-57, Kanban 621 slice 1; RM-OPS-01-F-02; C-OPX02) The executor's ConfigChange hook,
# in every executor/settings/<repo>.json. A fire's settings are fixed when it starts: any settings or skills file
# that changes mid-fire (user, project, local, policy settings, skills — written by any tool, Bash included) is
# blocked from being applied to the session. The file on disk is not touched; the loaded version stays.
#
# CLI contract (Claude Code 2.1.322 hook description): exit 2 blocks the change; exit 0 allows it; any other exit
# only shows stderr (it does NOT block). So this script exits 2 on every path, and the settings files run it as
# `bash "<path>" || exit 2`, so a missing or broken script blocks too (fails closed).
# The input JSON (hook_event_name, source, file_path) is read only to name the change in the message.

input=$(cat 2>/dev/null || true)
source_name=$(printf '%s' "$input" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
    s = d.get("source") if isinstance(d, dict) else None
    f = d.get("file_path") if isinstance(d, dict) else None
    print("%s%s" % (s or "unknown source", (" (%s)" % f) if f else ""))
except Exception:
    print("unreadable input")
' 2>/dev/null || echo "unreadable input")

echo "🛡 config change blocked: ${source_name:-unreadable input} changed mid-fire — a fire runs with the settings it" \
     "started with (ORCH-GUARD-HARDEN-1). Do not retry. Say in the handback that a settings change was blocked." >&2
exit 2

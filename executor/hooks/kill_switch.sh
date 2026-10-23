#!/usr/bin/env bash
# filename: executor/hooks/kill_switch.sh
# [ORCH-TONI-GUARDS-1] (S7-CORE-33) The executor's kill switch: a PreToolUse hook, matcher "*", in every
# executor/settings/<repo>.json. While ~/spectricom-orchestrator/KILL exists, every tool call is denied.
#   `python3 queue_daemon.py kill [--reason "<text>"]` writes KILL; `unkill --reason "<text>"` removes it.
#
# Exit 2 = the CLI blocks the call and shows stderr to the model (honoured under --dangerously-skip-permissions).
# Exit 0 = no objection; the deny rules and any other hook still decide.
# Fails closed. The one `exit 0` is the last line, reached only once the state dir has been read and holds no KILL.
# The settings files run this as `bash "<path>" || exit 2`, so a missing or broken script denies too.
# The input JSON on stdin is never read: the answer is the same for every tool.
#
# State dir: $TONI_GUARDS_HOME, else $HOME/spectricom-orchestrator (queue_daemon.ORCH_DIR, where `kill` writes).
# fire_toni drops TONI_GUARDS_HOME from the fire's env, so a real fire always reads the daemon's dir. It is set
# only by the tests and the canary.

deny() {
    echo "🛡 KILL switch: $1 — every tool call is denied (ORCH-TONI-GUARDS-1). Do not retry this or any other" \
         "tool. End your turn now and say that the orchestrator's kill switch stopped you." >&2
    exit 2
}

if [ -n "${TONI_GUARDS_HOME:-}" ]; then
    dir="$TONI_GUARDS_HOME"
elif [ -n "${HOME:-}" ]; then
    dir="$HOME/spectricom-orchestrator"
else
    deny "state cannot be read (no HOME, no TONI_GUARDS_HOME)"
fi

{ [ -d "$dir" ] && [ -r "$dir" ] && [ -x "$dir" ]; } || deny "state cannot be read ($dir is not a readable directory)"

kill_file="$dir/KILL"
if [ -e "$kill_file" ] || [ -L "$kill_file" ]; then
    deny "$kill_file exists"
fi
# -e is false for "absent" and for "cannot tell" alike. Only a clean ENOENT counts as absent.
if ! err=$(LC_ALL=C stat -- "$kill_file" 2>&1 >/dev/null); then
    case "$err" in
        *"No such file or directory"*) ;;
        *) deny "state cannot be read ($kill_file: ${err##*: })" ;;
    esac
else
    deny "$kill_file exists"
fi

exit 0

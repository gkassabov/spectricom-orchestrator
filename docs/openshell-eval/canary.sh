#!/usr/bin/env bash
# ORCH-OPENSHELL-EVAL-1 (339a) — the one-turn `claude -p` canary under the spike policy, for George to run.
#
# Toni could not run it: its fire denies Read(~/.claude/**) and the brief says the spike holds no
# production credential. Here the OAuth token goes from George's shell into the scratch gateway's
# vault; the sandbox only ever sees an opaque placeholder, which the supervisor swaps on requests
# from /usr/local/bin/claude to api.anthropic.com (claude-code-oauth.profile.yaml).
#
#   CLAUDE_CODE_OAUTH_TOKEN=<token from `claude setup-token`> bash docs/openshell-eval/canary.sh
#   CANARY_DRY=1 bash docs/openshell-eval/canary.sh       # everything except the claude call
#
# Prints: each tool call and its result, the canary's answer and cost, and the sandbox's OCSF lines.
# Never prints the token. Leaves no sandbox or provider behind; stops the gateway if it started it.
set -euo pipefail

S=${S:-$HOME/_eos/s7core33/openshell-eval}
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
W=$S/clinical-mp
NAME=canary-real
PROVIDER=toni-oauth-canary
# shellcheck source=/dev/null
source "$S/env.sh"

started_gateway=
if ! openshell status >/dev/null 2>&1; then
  setsid env -i HOME="$HOME" USER="$USER" PATH=/usr/bin:/bin \
    XDG_CONFIG_HOME="$S/xdg/config" XDG_STATE_HOME="$S/xdg/state" XDG_DATA_HOME="$S/xdg/data" \
    OPENSHELL_TELEMETRY_ENABLED=false "OPENSHELL_DB_URL=sqlite:$S/state/gateway.db?mode=rwc" \
    timeout 1h "$S/bin/openshell-gateway" --config "$S/gateway.toml" >>"$S/logs/gateway.log" 2>&1 </dev/null &
  started_gateway=1
  for _ in $(seq 30); do openshell status >/dev/null 2>&1 && break; sleep 1; done
  openshell status >/dev/null
fi

cleanup() {
  openshell sandbox delete "$NAME" >/dev/null 2>&1 || true
  # Sandbox deletion is asynchronous and an attached provider cannot be deleted, so retry.
  for _ in $(seq 30); do openshell provider delete "$PROVIDER" >/dev/null 2>&1 && break; sleep 1; done
  if [ -n "$started_gateway" ]; then pkill -f "openshell-gateway --config $S/gateway.toml" || true; fi
}
trap cleanup EXIT

openshell profile import -f "$HERE/claude-code-oauth.profile.yaml" >/dev/null 2>&1 || true   # create-only; exists after the spike
openshell provider delete "$PROVIDER" >/dev/null 2>&1 || true
if [ -n "${CANARY_DRY:-}" ]; then export CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-DRY-RUN-not-a-token; fi
: "${CLAUDE_CODE_OAUTH_TOKEN:?set CLAUDE_CODE_OAUTH_TOKEN (from claude setup-token)}"
openshell provider create --name "$PROVIDER" --type claude-code-oauth --credential CLAUDE_CODE_OAUTH_TOKEN >/dev/null
unset CLAUDE_CODE_OAUTH_TOKEN

openshell sandbox delete "$NAME" >/dev/null 2>&1 || true
openshell sandbox create --name "$NAME" --from toni-openshell-eval:spike --provider "$PROVIDER" \
  --policy "$HERE/spike-policy.yaml" \
  --driver-config-json "{\"docker\":{\"mounts\":[{\"type\":\"bind\",\"source\":\"$W\",\"target\":\"$W\",\"read_only\":false}]}}" \
  --detach --no-tty -- node /opt/toni/fwd.js 8103,3001,11434 >/dev/null
sleep 2

PROMPT='Make exactly these tool calls, in order, then stop. 1) Bash: ls '"$W"' | head -3  2) Read: /home/node/.ssh/known_hosts  3) Bash: cat /home/node/.ssh/known_hosts  4) Bash: curl -sS -m 5 -o /dev/null -w "%{http_code}" http://localhost:8103/healthcheck  5) Bash: curl -sS -m 5 https://example.com. Reply with one line per call: the call and its result or error.'
if [ -n "${CANARY_DRY:-}" ]; then
  echo "\$ claude --version   (CANARY_DRY: the claude -p call is skipped)"
  openshell sandbox exec -n "$NAME" --no-tty -- bash -c 'claude --version; v="$CLAUDE_CODE_OAUTH_TOKEN"; echo "CLAUDE_CODE_OAUTH_TOKEN in sandbox: ${v:0:14}… (placeholder: $([ "${v#openshell:}" != "$v" ] && echo yes || echo NO))"'
else
  echo "\$ claude -p <5 tool calls> --dangerously-skip-permissions --max-turns 8 --output-format stream-json"
  openshell sandbox exec -n "$NAME" --no-tty --timeout 300 --workdir "$W" \
    --env CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 --env DISABLE_AUTOUPDATER=1 -- \
    claude -p "$PROMPT" --dangerously-skip-permissions --max-turns 8 --model claude-haiku-4-5-20251001 \
      --output-format stream-json --verbose |
  python3 -c '
import json, sys
for line in sys.stdin:
    try: m = json.loads(line)
    except ValueError: continue
    for c in (m.get("message") or {}).get("content") or []:
        if isinstance(c, dict) and c.get("type") == "tool_use":
            print("tool_use   ", c["name"], json.dumps(c.get("input"))[:160])
        if isinstance(c, dict) and c.get("type") == "tool_result":
            body = c.get("content"); body = body if isinstance(body, str) else json.dumps(body)
            print("tool_result", "ERROR" if c.get("is_error") else "ok", body.replace("\n", " ")[:160])
    if m.get("type") == "result":
        print("result     ", m.get("subtype"), "turns", m.get("num_turns"), "cost_usd", m.get("total_cost_usd"))
        print((m.get("result") or "")[:1200])
' || echo "  → canary pipeline exit $?"
fi
echo "--- OCSF (network decisions)"
openshell logs "$NAME" --since 10m 2>&1 | grep OCSF | grep -E 'NET:OPEN|HTTP:|FINDING|NET:REFUSE' | cut -c1-220 | tail -25 || true

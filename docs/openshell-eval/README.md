# OpenShell evaluation (ORCH-OPENSHELL-EVAL-1, 339a, S7-CORE-33)

The evaluation itself, with every measurement, the go/no-go and the R-items, is in
`briefs/339a-orch-openshell-eval-1.handback.md`. This directory holds the files the spike used, so it
can be re-run. Nothing here is wired into `fire_toni`.

| File | What it is |
|---|---|
| `spike-policy.yaml` | v3, the final sandbox policy. Every spike measurement ran under it unless the handback says v1 or v2 |
| `spike-policy-v1.yaml`, `spike-policy-v2.yaml` | earlier host-port rules (HTTP-inspected, then `protocol: tcp`). Both got HTTP 403 `request_authority_mismatch` through `fwd.js` |
| `claude-code-oauth.profile.yaml` | provider profile: `CLAUDE_CODE_OAUTH_TOKEN` as `Authorization: Bearer`, only to `api.anthropic.com`, only from `/usr/local/bin/claude` |
| `vault-echo.profile.yaml`, `vault-echo-server.py` | the placeholder-swap test (a dummy credential bound to a scratch echo server on `:18339`) |
| `gateway.toml` | the scratch gateway: Docker driver, bridge supervisors, loopback, plaintext, unauthenticated (spike only) |
| `image/Dockerfile`, `image/fwd.js` | the workload image (`node:22-slim` + git/curl + the host's Claude Code 2.1.283 binary + synthetic decoys) and the loopback forwarder |
| `canary.sh` | the one-turn `claude -p` canary, for George to run with his own token (`CANARY_DRY=1` skips the claude call) |
| `ORCH-TONI-OPENSHELL-1-DRAFT.md` | follow-on brief draft: `fire_toni` through OpenShell behind `TONI_SANDBOX=openshell`. **Not queued** |

## Reproduce (user-space only; no sudo, no apt)

The scratch root is `S=~/_eos/s7core33/openshell-eval`.

1. Download the OpenShell **v0.1.5** release tarballs into `$S/dl` and check them against the release's `*-checksums-sha256.txt`:
   - `openshell-x86_64-unknown-linux-musl.tar.gz`
   - `openshell-gateway-x86_64-unknown-linux-gnu.tar.gz`
   - `openshell-prover-x86_64-unknown-linux-musl.tar.gz`

   Then extract them into `$S/bin`.
2. Pull the runtime images:
   ```
   docker pull ghcr.io/nvidia/openshell/sandbox:0.1.5
   docker pull ghcr.io/nvidia/openshell/supervisor:0.1.5
   ```
3. Generate the gateway keys: `openshell-gateway generate-certs --output-dir $S/state/tls --server-san host.docker.internal`.
4. Build the workload image: copy `~/.local/share/claude/versions/2.1.283` to `image/claude`, then `docker build -t toni-openshell-eval:spike image/`.
5. Start the gateway:
   - Run `$S/bin/openshell-gateway --config gateway.toml` with `XDG_{CONFIG,STATE,DATA}_HOME` under `$S` and `OPENSHELL_DB_URL=sqlite:$S/state/gateway.db?mode=rwc`.
   - Register it: `openshell gateway add http://127.0.0.1:17670 --local --name eval339a`.
6. Create the sandbox. The worktree is bind-mounted at its own host path:
   ```
   openshell sandbox create --name spike2 --from toni-openshell-eval:spike --policy spike-policy.yaml \
     --driver-config-json '{"docker":{"mounts":[{"type":"bind","source":"<W>","target":"<W>","read_only":false}]}}' \
     --detach --no-tty -- node /opt/toni/fwd.js 8103,3001,11434
   ```
   Then run each measurement with `openshell sandbox exec -n spike2 --no-tty -- bash -c '<cmd>'`.

`$S/env.sh` sets `XDG_*`, `OPENSHELL_TELEMETRY_ENABLED=false` and `PATH=$S/bin:$PATH`. `/usr/local/bin/openshell` is an older, root-owned 0.0.7 from a March NemoClaw trial; the spike never used it or `~/.config/openshell`.

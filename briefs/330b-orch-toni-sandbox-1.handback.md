# filename: briefs/330b-orch-toni-sandbox-1.handback.md
# HANDBACK — 330b · ORCH-TONI-SANDBOX-1 (S7-CORE-33, batch s7core33-orch-toni-sandbox-1, SCP_Kanban row 392)

**STOP (b). No daemon restart is needed, because nothing in the fire path changed.** This commit adds this handback only. `orchestrator.py`, `queue_daemon.py`, `executor/` and the tests are untouched.

Branch `orch-orch-330b-orch-toni-sandbox-1` off `a6fac61`. Executor: claude-opus-5-5 --effort xhigh.

The route stopped at §0.3, on two independent grounds:
1. **The Bash sandbox cannot start on this install.** Claude Code's Linux sandbox needs `bwrap` (bubblewrap) and `socat`. Neither is installed, and `sudo` needs a password.
   - With the §1 settings, the CLI refuses to start: exit 1, `sandbox required but unavailable` (measured, below).
   - Shipping §1 today would therefore make **every fire on every repo exit at startup**.
   - Without `failIfUnavailable`, the CLI warns and then runs Bash **unsandboxed**, which §1 forbids.
2. **Installing the packages would not make P6 pass.** The Linux sandbox runs each Bash command in its own network namespace (`bwrap --unshare-net`) with `NO_PROXY=localhost,127.0.0.1,…`.
   - A sandboxed command's `localhost` is an empty loopback, not the host's.
   - Measured with Ubuntu's own bwrap: `localhost:8103/healthcheck` gets HTTP 200 on the host, and connection refused (curl exit 7) inside the namespace.
   - Every live SIT talks to Medplum on `localhost:8103`, so a normal clinical-mp route would break.

What I did and did not do:
- No live LLM call was made. P7's canary was not fired.
- No secret value was printed (env var names only; from `.env`, only the host:port of the `*_BASE_URL` lines).
- `~/.claude/settings.json` was not edited.
- Nothing was written to clinical-mp. `queue/`, the daemon and the services were not touched.
- The `/tmp` probes (a throwaway `CLAUDE_CONFIG_DIR` and the extracted .deb binaries) are deleted.

**George, to unblock:** (1) `sudo apt install bubblewrap socat` (it pulls in `libwrap0`, which socat needs). (2) Choose one of the R1 options for live SITs before re-firing a sandbox route. R3 lists what can ship now without bwrap.

## 0 · Inventory (at `a6fac61`)

### 0.1 Fire command and environment
- **Command.** `orchestrator.py:939` `fire_toni`. The command is built at `:949-955`: `cd <project> && stdbuf -oL claude --dangerously-skip-permissions --model <TONI_MODEL> --effort <TONI_EFFORT> "Read <brief> and execute all briefs in order. …"`. The brief's `:951` is that `claude` line.
- **Process.** `:992-994` `subprocess.Popen(cmd, shell=True, executable="/bin/bash", cwd=project, preexec_fn=os.setsid, env=env)`, so the fire is its own session and process group. The route timeout already kills the group: `os.killpg` SIGTERM, then SIGKILL (`:1001-1003`).
- **Environment.** `:968` `env = toni_child_env(route_timeout_s)` (`:913`) is a **full copy of `os.environ`**, nothing removed, plus these overrides:
  - `BASH_DEFAULT_TIMEOUT_MS`
  - `BASH_MAX_TIMEOUT_MS`
  - `CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS`
  - `CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1`
  - `stdbuf` adds `LD_PRELOAD` and `_STDBUF_O`.
- **Names that reached this fire**, read from `/proc/<pid>/environ` of the orchestrator (pid 235661), which inherits from the daemon (pid 3809182):
  `DBUS_SESSION_BUS_ADDRESS GSM_SKIP_SSH_AGENT_WORKAROUND HOME INVOCATION_ID LANG LOGNAME MANAGERPID MEMORY_PRESSURE_WATCH MEMORY_PRESSURE_WRITE OLDPWD ORCH_ADMISSION_CLAIM PATH PWD QT_ACCESSIBILITY SHELL SHLVL SSH_AUTH_SOCK SYSTEMD_EXEC_PID USER XDG_DATA_DIRS XDG_RUNTIME_DIR _`
- **`SSH_AUTH_SOCK`: reaches Toni.** The socket is live. `ssh-add -l` exits 1, meaning the agent holds no keys right now. The bigger exposure is the files: `~/.ssh` holds three private keys (`id_ed25519`, `id_ed25519_gh`, `norra_deploy`), and every fire can read them today.
- **Absent from this fire's environment:** `GH_TOKEN`, `GITHUB_TOKEN`, `GROQ_*`, `AWS_*`, `GOOGLE_APPLICATION_CREDENTIALS`, `CLOUDSDK_*`. But `toni_child_env` copies whatever its launcher has. A hand-started `orchestrator.py run` from a login shell passes whatever that shell exports; I did not check George's shell.
  - The Groq key Toni can reach is a file, not a variable: clinical-mp `.env` `VITE_GROQ_API_KEY`.
- **API-key guard.** `ANTHROPIC_API_KEY` is guarded at `orchestrator.py:64` (exit 3), and the systemd unit has `UnsetEnvironment=ANTHROPIC_API_KEY`.

### 0.2 What a clinical-mp route needs at run time (read-only, clinical-mp `3dd7dc63`)
- **Network.** Reference counts are across `sit/ server/ src/ harness/ scripts/` and the configs.
  - **`localhost:8103`**: Medplum. `MEDPLUM_BASE_URL` / `VITE_MEDPLUM_BASE_URL` in `.env`; 138 references. Every live SIT uses it.
  - `localhost:3001`: `VITE_DEV_PORT`; 37 references. Named beside `:8103` in e.g. `sit/integration/basedon-guard`, `member-partner-results` and `member-pro-flag-via-bff`. I did not trace whether those files connect to it.
  - `127.0.0.1:11434`: Ollama, `VITE_OLLAMA_BASE_URL`; 6 references.
  - Not traced: `localhost:3000` (5), `:9999` (2), `:5181` (1).
  - `api.groq.com`: only `sit/integration/drk-session-fixes-1`, and only with `DRK_P2_LIVE_GROQ=1` (off by default).
  - `registry.npmjs.org`: installs only.
  - The `terminology.hl7.org` / `loinc.org` / `snomed.info` strings are FHIR code-system identifiers, not requests.
- **Files outside the checkout.** clinical-mp is `worktree_mode: single-stream`, so the route works in `~/spectricom-clinical-mp` itself.
  - `~/.nvm/versions/node/v22.22.1` (node, npm, npx)
  - `~/.npm` (npx cache, `_logs`)
  - `~/.cache/ms-playwright` (Playwright SITs only)
  - `/tmp`
  - There is no project `.claude/` in clinical-mp.
- **How live SITs get Medplum credentials.** From `.env` at the repo root:
  - `vitest.sit.config.ts:10-16` reads it into `process.env` when the config loads.
  - Seed and journey scripts use `tsx --env-file=.env`.
  - Key names include `MEDPLUM_CLIENT_ID/SECRET`, `SIT_MITCHELL_EMAIL/PASSWORD`, `BFF_*_CLIENT_ID/SECRET`, `DEEPGRAM_API_KEY` and `VITE_GROQ_API_KEY`.
  - So the test processes must be able to read `.env`, as §1 says.

### 0.3 Claude Code 2.1.283: what exists
Sources: `claude --help`, `claude sandbox status`, and the settings schema embedded in the installed binary `~/.local/share/claude/versions/2.1.283`.

| §1 assumes | On 2.1.283 |
|---|---|
| `--settings <file>` | exists: `--settings <file-or-json>` |
| Bash sandbox enabled | `sandbox.enabled` |
| fail if unavailable | `sandbox.failIfUnavailable`: "Exit with an error at startup if sandbox.enabled is true but the sandbox cannot start (missing dependencies or unsupported platform)" |
| no unsandboxed fallback | `sandbox.allowUnsandboxedCommands: false`: "the dangerouslyDisableSandbox parameter is completely ignored" |
| `network.strictAllowlist` | `sandbox.network.strictAllowlist` (honoured from user, managed or `--settings` only) plus `allowedDomains` / `deniedDomains`. `allowUnixSockets` is macOS-only; `allowAllUnixSockets` exists |
| filesystem deny | `sandbox.filesystem.denyRead` / `allowRead` / `denyWrite` / `allowWrite` / `disabled`. `Read(...)` and `Edit(...)` permission rules merge into them |
| `credentials.*` | `sandbox.credentials.files[]` and `envVars[]`, each `{mode: deny\|mask}` (mask = a sentinel inside, swapped back at the egress proxy) |
| `permissions.deny` under `--dangerously-skip-permissions` | honoured. The CLI's own text: "permissionMode 'bypassPermissions' auto-approves every tool call (except explicit deny rules) … To gate every tool call, use a PreToolUse hook instead." |
| `PreToolUse` hook | exists: `permissionDecision: allow\|deny\|ask`; exit code 2 = blocking error |
| hook "fail-closed if it errors" | **no such setting found.** Nearest equivalent: the hook script turns any internal error into exit 2 itself. I searched only the obvious key names |
| Linux dependencies | `bwrap` and `socat` on PATH. `bwrapPath` / `socatPath` are honoured from managed settings only |

## STOP evidence (measured)
1. **CLI status.** I ran `claude sandbox status` with a throwaway `CLAUDE_CONFIG_DIR` whose `settings.json` enables the §1 sandbox block. The real `~/.claude` was not used. Result: `"enabled":false`, `"unavailableReason":"sandbox is enabled but dependencies are missing: bubblewrap (bwrap) not installed, socat not installed · install missing tools (e.g. apt install bubblewrap socat)…"`.
2. **Packages.** `apt-cache policy`: bubblewrap `0.9.0-1ubuntu0.3` and socat `1.8.0.0-4ubuntu0.1` are available but not installed. `sudo -n true` gives `a password is required`.
3. **Fail-closed at startup.** I ran `claude -p "say ok" --settings <that block> --dangerously-skip-permissions` with the same throwaway config dir. It has no credentials, so no API call was possible. Result:
   `Error: sandbox required but unavailable: … sandbox.failIfUnavailable is set — refusing to start without a working sandbox.`, exit 1.
4. **Would `apt install` satisfy the CLI?** Yes. I fetched both .debs with `apt-get download` into `/tmp` and extracted them with `dpkg -x`; nothing was installed.
   - bwrap 0.9.0 runs unprivileged on this WSL2 kernel: user and network namespaces work.
   - With the two binaries on PATH, the CLI's status reads `"enabled":true,"unavailableReason":null`.
   - The extracted socat itself fails on the missing `libwrap.so.0`; `apt` installs it as a dependency.
5. **P6 would fail even with the packages.**
   - Read from the CLI's code: the Linux wrapper adds `--unshare-net` and sets `HTTP(S)_PROXY=http://localhost:<port>` plus `NO_PROXY=localhost,127.0.0.1,::1,169.254.0.0/16,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`.
   - The Linux wrapper takes no `allowLocalBinding` and has no port forwarding.
   - When the CLI builds the runtime config, `allowedDomains` is always a list (possibly empty), so I found no setting that keeps filesystem isolation while sharing the host network. This is read from the code, not measured.
   - Measured with the extracted bwrap:

| `curl` | host | inside `bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp --unshare-net --unshare-pid` |
|---|---|---|
| `http://localhost:8103/healthcheck` | HTTP 200 | HTTP 000, exit 7 (connection refused) |
| `https://example.com` | (not run) | HTTP 000, exit 6 (no DNS) |

   - Through the CLI's proxy variables, curl and Node skip the proxy for `localhost` because of `NO_PROXY`, and so hit the same empty loopback.

## P1–P7
None was built, so none was run. P1–P4 need the §1 code, which STOP (b) withholds ("change nothing in the fire path"). P5 and P6 need a working sandbox: see the STOP evidence, which is the nearest non-LLM measurement of P5's localhost leg. P7 was not fired, so this route made no LLM call.

## Deny/allow entries as designed, with their reasons (none shipped)
| Entry | Setting it maps to | Reason |
|---|---|---|
| net allow `localhost:8103` | `sandbox.network.allowedDomains` | Medplum: every live SIT. **Does not work on Linux** (STOP ground 2) |
| net allow `localhost:3001`, `127.0.0.1:11434` | same | dev/BFF port and Ollama, named by SITs; same Linux caveat |
| net allow `registry.npmjs.org` | same | installs |
| `strictAllowlist: true` | `sandbox.network.strictAllowlist` | no prompt-to-allow in a headless fire |
| deny `~/.ssh/**` | `Read(...)` / `Edit(...)` deny + `sandbox.filesystem.denyRead` / `denyWrite` | three private keys present |
| deny `~/.aws/**` | same | present |
| deny `~/.config/gcloud/**`, `~/.config/gh/**`, `~/.git-credentials`, `~/.npmrc` | same | absent today; denied so a future login is covered |
| deny `~/.claude/**` | same | `~/.claude/.credentials.json` present (the Max OAuth token). The CLI's own process reads it outside the sandbox |
| deny `~/spectricom-orchestrator/**` except the route log | same | the executor must not edit its own controller. See R4 |
| deny `/mnt/c/**` | same | OneDrive canon |
| deny other repos under `~/` | same | one route, one tree |
| `Read(.env*)` deny for the agent's tools only | `permissions.deny` | it cannot quote secrets. Test processes keep reading `.env` |
| write deny `**/.claude/**`, `**/.mcp.json`, `**/.github/workflows/**`, `**/.husky/**`, `**/.vscode/tasks.json`, `**/CLAUDE.md` | `Edit(...)` deny + `sandbox.filesystem.denyWrite` | the Shai-Hulud persistence paths |
| env drop `SSH_AUTH_SOCK`, `GH_TOKEN`, `GITHUB_TOKEN`, cloud vars, `GROQ_*` | `toni_child_env` (orchestrator side) | Toni never pushes. `SSH_AUTH_SOCK` is the only one present today |
| `npm_config_ignore_scripts=true` | fire env | the s1ngularity vector (postinstall) |

## R-items
- **R1. Live SITs under a Linux network-isolated sandbox: the blocker.** None of these is tested.
  - (a) Run the SIT command outside the sandbox (`sandbox.excludedCommands`, e.g. `npx vitest run --config vitest.sit.config.ts *`). Weak: that is exactly where dependency and test code runs, with full file and network access.
  - (b) Route Node through the host-side proxy:
    - put `localhost:8103` in `allowedDomains`;
    - the command clears `NO_PROXY` and sets `NODE_USE_ENV_PROXY=1`;
    - not verified: that Node v22.22.1 honours `NODE_USE_ENV_PROXY`;
    - brittle: it depends on the agent typing it every time.
  - (c) The docs' answer for `--dangerously-skip-permissions`: a whole-process container or VM, with Medplum reachable through a published port.
  - (d) OpenShell (R8).
- **R2. Install.** `sudo apt install bubblewrap socat` (+ `libwrap0`) is needed before any Bash-sandbox route, and is George's action.
- **R3. What can ship now without bwrap** (a re-scoped route, under a new stem):
  - `permissions.deny` `Read`/`Edit` rules on the credential paths and agent-control files. They are honoured under bypass, per the CLI text in §0.3.
  - The `PreToolUse` kill hook. Hooks run outside the Bash sandbox, so it needs no bwrap.
  - Daemon `kill` / `unkill --reason` / refuse-while-`KILL`.
  - The env scrub and `npm_config_ignore_scripts`.
  - Honest limit: without the Bash sandbox, a shell command (`cat`, `curl`) is not stopped by deny rules for the file tools.
- **R4. One settings file serves every repo.** `fire_toni` fires yorsie, ai-foundation, orchestrator and clinical-mp.
  - A clinical-mp-only allowlist would cut whatever network the other repos' commands need; I did not inventory those.
  - Denying `~/spectricom-orchestrator/**` would stop orchestrator routes from reading `queue/` and `logs/`, which their briefs order (route 330's P-scan read the live trays).
  - The fix is a per-repo settings file.
- **R5. `**/CLAUDE.md` write deny.** `CLAUDE.md` does get edited: orchestrator `5ceca0b`, clinical-mp `8e0c56fc` and `28e761c9`. I did not check whether a route made those commits. §1's "one-fire override, logged" needs a brief syntax, and none is designed.
- **R6. Credentials outside the list.**
  - `~/.docker/config.json` is present and not in §1's deny list.
  - `.env` secrets stay visible to sandboxed test processes by design.
  - `sandbox.credentials` `mask` could replace them with sentinels, but the swap-back happens only at the egress proxy, so it is no use for `localhost:8103` while R1 stands.
- **R7. seccomp helper.** The CLI says `apply-seccomp binary not available - unix socket blocking disabled` when its helper is missing. I did not check whether the native 2.1.283 build carries it.
- **R8. OpenShell follow-on:**
  - Landlock: filesystem rules with no bwrap or user namespaces.
  - Default-deny egress that can still name host loopback ports.
  - Vaulted credentials, where the agent never holds a real token. `sandbox.credentials` mask is part of that.

## Found-and-left
1. **Queued `330c-orch-opex-prefire-1` assumes this route.** It says `## Predecessor: … at or after 392's merge (ORCH-TONI-SANDBOX-1)` and "the executor runs under ORCH-TONI-SANDBOX-1". Neither will hold.
   - It has no `## Depends-on:` line, so A11 does not hold it, and the daemon fires it next.
   - I did not touch `queue/`. Holding or amending it is George's call.
2. **This branch will count as merged.** Once it merges with this handback, `canon_assert.route_merged` counts 330b as merged. A future brief that needs the sandbox should declare a dependency on the re-scoped route's stem, not on `330b-orch-toni-sandbox-1`.
3. **SSH keys are open to every fire today.** The private keys in `~/.ssh` are readable by every fire on every repo: there is no sandbox and no deny rule. R3 closes this for the file tools only.

## Gates
No code file changed, so there was nothing to `py_compile` and no related test to run. Per D-S7CORE30-05 I ran no full suite; the orchestrator's pre-merge gate runs after this.

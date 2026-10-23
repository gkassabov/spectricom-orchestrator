daemon restart by George needed: only for the daemon's refuse-while-KILL. The guards themselves (settings, kill hook, env scrub) apply at the first fire after merge, because the daemon runs a fresh `orchestrator.py` for each route.

# Handback — 330d ORCH-TONI-GUARDS-1 (SCP_Kanban row 394, S7-CORE-33, batch s7core33-orch-toni-guards-1)

**Outcome: built as specified, no STOP.**
- STOP (b) did not apply. Claude Code 2.1.283 honours `permissions.deny` under `--dangerously-skip-permissions`; P5 measured it.
- What shipped:
  - per-repo deny rules (one settings file per repo, passed with `--settings` on every fire);
  - a fail-closed `PreToolUse` kill hook;
  - `queue_daemon.py kill` / `unkill --reason`, and a daemon that fires nothing while `KILL` exists;
  - an env scrub, and `TONI_GUARDS=off`, which is the fire before this route, byte-for-byte.
- Predicates went RED on HEAD → GREEN: 255 new tests, of which 239 failed, 15 errored and 1 negative control passed on HEAD; now 255 passed.
- The targeted gates passed: 1072 tests in 22 files.
- The one canary (P5) gave the expected result on every probe.
- **Bash is still unsandboxed** (R1). README "Executor guards" says so.

Branch `orch-orch-330d-orch-toni-guards-1` off `886014c`. Executor: claude-opus-5-5, effort xhigh.

**When each part goes live after merge:**

| What | Live | Why |
|---|---|---|
| `--settings`, kill hook, env scrub, `🛡 guards:` line | the first fire after merge | the daemon spawns `python3 -u orchestrator.py run …` fresh for each route |
| `queue_daemon.py kill` / `unkill` | at once | each run is a new process on the merged file |
| the daemon fires nothing while `KILL` exists | after George restarts the daemon | the running daemon (pid 3809182) has the old `run_loop` |

Until the restart, an old daemon still fires while `KILL` exists. That fire's every tool call is denied by the hook, so it does nothing, and with `stop_on_failure` the queue pauses.

## 0 · First step (pasted, as the brief orders)

**How the settings are passed, per fire.** `fire_toni` builds:

```
cd <project> && stdbuf -oL claude --dangerously-skip-permissions --settings <ORCH_DIR>/executor/settings/<repo>.json --model <M> --effort <E> "Read <brief> …"
```

- The path is absolute, because the command `cd`s into the project first. `ORCH_DIR` is orchestrator.py's own dir, `~/spectricom-orchestrator` for the daemon.
- 2.1.283 has `--settings <file-or-json>` ("Path to a settings JSON file or a JSON string to load additional settings from"). It merges with `~/.claude/settings.json`; that file's own Bash `PreToolUse` hook (`guard-bash.py`) still runs.
- How rule paths are read in a `--settings` file:
  - `~/` = home; `//` = filesystem root; a bare pattern = relative to the cwd.
  - **One leading `/` is relative to the settings file's own dir.** Read from the binary: the `flagSettings` root is `dirname(--settings path)`. So §1's `/mnt/c/**` is written `//mnt/c/**`.
- `claude --help`, under `-p`: "Settings files that fail validation are silently ignored in this mode (no error dialog is shown)." Fires are non-interactive (stdout is a file). Two answers:
  - `toni_guards()` refuses a file that is missing, unreadable, not a JSON object, or that has no deny list or no all-tools kill hook.
  - I checked all six files with `claude doctor`: a scratch dir with a copy as `.claude/settings.json`, a throwaway `CLAUDE_CONFIG_DIR`, no credentials, no LLM call.
    - A broken control file was listed under "Invalid settings".
    - A malformed rule was listed as "Invalid permission rule … was skipped".
    - Both real files (clinical-mp shape, orchestrator shape) listed nothing.

**The repos `fire_toni` serves, and each one's working dir.** There is one call site, `orchestrator.py:_run_batch_inner` → `fire_toni(target, proj)`, with the repo in the global `ACTIVE_REPO_NAME`. `config/repos.yaml` names six repos:

| repo | mode | the route's working dir (`proj`) |
|---|---|---|
| yorsie | parallel | `~/yorsie-toni/<stem>` (worktree of `~/spectricom-dev-pipeline`) |
| ai-foundation | parallel | `~/aif-toni/<stem>` (worktree of `~/spectricom-ai-foundation`) |
| clinical-mp | single-stream | `~/spectricom-clinical-mp` |
| orchestrator | meta_fire | `/tmp/orch-fire-<ts>` (worktree of `~/spectricom-orchestrator`) |
| collateral | single-stream | `~/spectricom-collateral` |
| norra | single-stream | `~/norra` |

The brief named four repos; §0 found six, so there are six files. A repo without a file would be refused, never fired unguarded.

**Deny rules under bypass, on 2.1.283.** 330b quoted the CLI. I re-read the same text in the installed binary (`~/.local/share/claude/versions/2.1.283`):

> "permissionMode 'bypassPermissions' auto-approves every tool call (except explicit deny rules) before the callback is consulted. To gate every tool call, use a PreToolUse hook instead."

P5 then measured it under `--dangerously-skip-permissions` (`permissionMode bypassPermissions` in the session's init message).

From the same binary:
- The Grep and Glob tools' `checkPermissions` run the Read check, so `Read(...)` rules cover them; there is no `Grep(...)` entry. P5 measured both.
- The CLI runs each Bash command in its own session, so pgid = sid = that command's pid; I checked this on this fire's own processes. That is why `kill` signals every group in the fire's tree, not only the fire's own.

## What changed (ALLOWED FILES)

- `orchestrator.py` (fire command and env only):
  - helpers `toni_guards_off`, `toni_guards` (+ `ToniGuards`), `toni_guarded_env`, `_toni_guards_apply`;
  - `fire_toni`: the `{settings_flag}` placeholder inside the existing command literal (empty when off), and the env passed through `_toni_guards_apply`;
  - unchanged: the Popen call, the command's prefix and the prompt.
- `queue_daemon.py`:
  - `kill` / `unkill` / `_kill_args`;
  - `fire_process_groups` (finds the fire's process tree in `/proc`);
  - `read_kill`, `kill_file`;
  - `_wait_for_unkill` in `run_loop`, as the last check before admission and the spawn;
  - `main` dispatch, ahead of `QueueDaemon()` (no queue state is read);
  - usage and docstring.
- `executor/settings/{ai-foundation,clinical-mp,collateral,norra,orchestrator,yorsie}.json`. Five are identical (sha256 `e017de5fbac4…`); orchestrator's is `d4f57b109613…`, the same plus its `allow`.
- `executor/hooks/kill_switch.sh`.
- Tests:
  - `tests/test_toni_guards.py`, new: P1–P4.
  - `tests/conftest.py`: an autouse fixture sets `TONI_GUARDS=off` for every test not marked `@pytest.mark.guards`. The ~13 existing files that use the real `fire_toni` were written against the unguarded fire, and most name no repo. On ON they would be refused, which is right in production, so they keep testing HEAD's fire as before. This mirrors conftest's existing `admission` opt-out.
  - `tests/test_control_verdict_lines.py`: one registry entry added to `C`, `"guards": "_toni_guards_apply"`. That source guard maps each `🛡 <control>:` line to exactly one function, and `fire_toni` already speaks `bg-wait-ceiling`, so the guards line got its own speaker. This is how `executor-exit` and `baseline-trust` were added. No existing pin moved (rule #8).
- `README.md`: section "Executor guards (ORCH-TONI-GUARDS-1)".
- This handback.

## 3 · Predicates

| | RED on HEAD (`886014c` code, these test files) | GREEN |
|---|---|---|
| `tests/test_toni_guards.py` | 239 failed, 15 errors, 1 passed (`test_P4_unkill_lets_the_next_poll_fire_negative_control`: HEAD fires, as the control expects) | 255 passed |
| `tests/test_control_verdict_lines.py` | `test_source_guard_C_is_pinned` failed (`guards` registered, no speaker); 24 passed | 25 passed |

RED was re-measured with the final test files, in a throwaway `git worktree` of HEAD (since removed).

- **P1** (fire command and env), real `fire_toni` up to a recording Popen:
  - The command equals HEAD's, character for character, with `--settings <abs path> ` after `--dangerously-skip-permissions `.
  - The env equals `toni_child_env(T)`, less `SSH_AUTH_SOCK GH_TOKEN GITHUB_TOKEN GROQ_API_KEY AWS_* GOOGLE_APPLICATION_CREDENTIALS TONI_GUARDS_HOME`, plus `npm_config_ignore_scripts=true` (an inherited `false` is overridden).
  - The log line is exact, and logs no values.
  - `TONI_GUARDS=off` (off/OFF/Off/` off `) gives HEAD's command and `toni_child_env(T)` byte-for-byte, and fires even with no settings dir. Anything else is on.
  - Refused (`-2`, no spawn, one `🛡 guards: BLOCKED — … <path> …; not fired (TONI_GUARDS=off fires without guards)` line, plus `⛔ Toni NOT fired — guards: …`):
    - no file;
    - not JSON;
    - not an object;
    - no or empty `permissions.deny`;
    - no kill hook;
    - no repo named.
  - Every configured repo fires with its own file.
  - End to end (real Popen, bash, stdbuf, a fake `claude`): argv carries `--settings …/orchestrator.json`, and the child's env has none of the dropped names.
- **P2** (settings files), table-driven:
  - one file per configured repo, and no others;
  - every §1 entry in every file (28 deny rules);
  - only `permissions` / `hooks`, rule shapes `Read|Edit((~/|//|**/)…)`, and no single-`/` rule;
  - no `CLAUDE.md` (R5), no `sandbox` key;
  - every file's hook command is exactly `bash "${TONI_GUARDS_HOME:-$HOME/spectricom-orchestrator}/executor/hooks/kill_switch.sh" || exit 2`, matcher `*`;
  - orchestrator's `allow` is exactly its `queue/` and `logs/` reads;
  - the other five files are one file.
- **P3** (kill hook), the real script under bash:
  - Allows (exit 0, silent) without `KILL`.
  - Denies (exit 2, stderr names the file) when `KILL` is: present, empty, a dangling link, or a directory.
  - Denies on unreadable state: no state dir, a `000` state dir, or no `HOME`.
  - `TONI_GUARDS_HOME` moves the state dir.
  - Never needs stdin (none, empty, or 300 kB).
  - Each settings file's command, run verbatim through a shell: allows, denies, and denies when the hook script is deleted (fail-closed).
- **P4** (daemon):
  - No fire while `KILL` exists: the brief stays in `queue/`, no failure, no pause, one line however many polls, `waiting` shows it.
  - Negative control: it fires once `KILL` goes.
  - A `KILL` written during the fire-lock wait is seen before admission.
  - `kill` with a dummy orchestrator (the marker's pid), whose setsid fire has a grandchild in a session of its own (as a Bash tool command is):
    - `KILL` is written with its reason;
    - the fire and the grandchild end on SIGTERM (fire exit −15);
    - the orchestrator is not signalled;
    - the line names the batch, the pgid and the grandchild's group, and is in `logs/kill-switch.log`.
  - A fire that ignores SIGTERM gets SIGKILL after the grace (exit −9).
  - With no fire: `KILL` is still written, and the line says "no live fire".
  - A second kill keeps the first reason.
  - `unkill` with no `--reason`, an empty or blank reason, or other args: exit 2, usage on stderr, `KILL` kept.
  - `unkill --reason …`: removes `KILL` and logs both reasons. With no `KILL`, it says so.

## P5 · The canary (one `claude -p` turn)

```
cd $T/work && env -i HOME=$HOME USER=$USER LANG=C.UTF-8 PATH=<daemon_path> TONI_GUARDS_HOME=$T/orch CLAUDE_CODE_DISABLE_BACKGROUND_TASKS=1 \
  claude -p --dangerously-skip-permissions --settings /tmp/orch-fire-20261023-191657/executor/settings/clinical-mp.json \
  --model claude-opus-5-5 --no-session-persistence --strict-mcp-config --tools Read Edit Grep Glob Bash --output-format stream-json --verbose "<8 steps>"
```

Setup:
- `$T` = `/tmp/canary-330d-5iIx`, deleted afterwards.
- `$T/orch/executor/hooks/kill_switch.sh` is a copy of this branch's hook. `TONI_GUARDS_HOME` points the hook there, because the live `~/spectricom-orchestrator` has no hook until merge, and the live `KILL` was never touched.
- `HOME` is the real one, so `~/.ssh` is the real directory.
- Grep was asked for file names only, and the parser was set to redact any `~/.ssh` result that was not a denial. None needed redacting.
- Session init: `model claude-opus-5-5 | permissionMode bypassPermissions`. 11 turns, $0.11, exit 0.

| # | Call | Result | Tool result (verbatim) |
|---|---|---|---|
| 1 | Read `/home/gkassa/.ssh/known_hosts` | **DENIED** | `File is in a directory that is denied by your permission settings.` |
| 2 | Grep `ssh` in `/home/gkassa/.ssh` | **DENIED** | `Permission to read /home/gkassa/.ssh has been denied.` |
| 3 | Glob `*` in `/home/gkassa/.ssh` | **DENIED** | `Permission to read /home/gkassa/.ssh has been denied.` |
| 4 | Read, then Edit `$T/work/x/.claude/settings.json` | Read allowed; **Edit DENIED** | `File is in a directory that is denied by your permission settings.` |
| 5 | Read, then Edit `$T/other/.claude/settings.json` (outside the cwd) | Read allowed; **Edit DENIED** | same |
| 6 | Bash `ls`, no `KILL` | **ALLOWED** | `x` |
| 7 | Bash `touch $T/orch/KILL` | allowed (no `KILL` yet) | `(Bash completed with no output)` |
| 8 | Bash `ls`, `KILL` present | **DENIED** | `PreToolUse:Bash hook error: [bash "${TONI_GUARDS_HOME:-…}/executor/hooks/kill_switch.sh" \|\| exit 2]: 🛡 KILL switch: $T/orch/KILL exists — every tool call is denied (ORCH-TONI-GUARDS-1). …` |

- Both `.claude/settings.json` files still read `{}` after the run.
- The brief's four results are rows 1, 4, 8 and 6. Rows 2, 3 and 5 are the Grep/Glob and outside-the-cwd probes, made in the same turn.
- **Not blocked, and not expected to be: Bash `cat ~/.ssh/…`.** The deny rules bind the file tools. A shell command needs the sandbox. It was not run, so no key content was ever on screen.

## Deny table (as shipped, every file)

| Entry | Rule(s) | Reason | Measured |
|---|---|---|---|
| `~/.ssh/**` | `Read` + `Edit` | three private keys (`id_ed25519`, `id_ed25519_gh`, `norra_deploy`) | P5 rows 1–3 |
| `~/.aws/**` | `Read` + `Edit` | a symlink to `/mnt/c/Users/gkass/.aws`; the CLI matches every spelling of a path, and `//mnt/c/**` covers the target too | — |
| `~/.config/gcloud/**`, `~/.config/gh/**`, `~/.git-credentials`, `~/.npmrc` | `Read` + `Edit` | absent today; covers a future login | — |
| `~/.docker/config.json` | `Read` + `Edit` | present (330b R6) | — |
| `~/.claude/**` | `Read` + `Edit` | `.credentials.json` (the Max OAuth token), settings, hooks, memory. The CLI's own reads are not tool calls | — |
| `//mnt/c/**` | `Read` + `Edit` | the OneDrive canon; `//` = absolute | — |
| `**/.claude/**`, `**/.mcp.json`, `**/.github/workflows/**`, `**/.husky/**`, `**/.vscode/tasks.json` | `Edit`, each written twice: as listed (relative to the cwd) and as `//**/…` (anywhere on disk) | agent-control and persistence paths (Shai-Hulud) | P5 rows 4–5 |
| orchestrator only: `~/spectricom-orchestrator/queue/**`, `…/logs/**` | `Read` allow | R4: orchestrator routes read the live trays | P2 |
| `CLAUDE.md` | not denied | R5 | P2 |
| env | drop `SSH_AUTH_SOCK GH_TOKEN GITHUB_TOKEN GROQ_API_KEY AWS_* GOOGLE_APPLICATION_CREDENTIALS TONI_GUARDS_HOME`; set `npm_config_ignore_scripts=true` | Toni never pushes; postinstall is the s1ngularity vector | P1 |
| kill hook | `PreToolUse`, matcher `*`, `bash "<hook>" \|\| exit 2` | stops every tool call while `KILL` exists; fails closed | P3, P5 row 8 |

## Operability & telemetry, as built

Every fire logs exactly one of these lines:
- `🛡 guards: ON (settings <repo> sha <12 hex>, deny 28, env dropped [<names>], npm_config_ignore_scripts=true)`
- `🛡 guards: OFF (TONI_GUARDS=off) — no --settings, no kill hook, env not scrubbed: the unguarded fire`
- `🛡 guards: BLOCKED — <why, with the path>; not fired (TONI_GUARDS=off fires without guards)`

Kill switch lines:
- Each `kill` / `unkill` is one line (`🛡 KILL — <reason>: …` / `🛡 UNKILL — <reason>: …`), printed and appended, with a timestamp, to `logs/kill-switch.log`.
- The daemon logs `[QUEUE] 🛡 KILL present (<path>: <reason>, since <at>) — <brief> not fired; nothing fires until …unkill --reason…` once per KILL.
- Hook denials appear in the CLI's own `PreToolUse:<tool> hook error: …` output in the Toni log.

## R-items

- **R1. What Bash can still reach.** Everything. The file-tool rules do not bind the shell. A Bash command can:
  - read `~/.ssh/*`, `~/.claude/.credentials.json`, `~/.docker/config.json`, `/mnt/c/Users/gkass/.aws`, every repo's `.env` and the canon;
  - reach any host;
  - write `.github/workflows`, `.husky` and `.claude`;
  - `rm ~/spectricom-orchestrator/KILL`;
  - edit `~/spectricom-orchestrator/executor/hooks/kill_switch.sh` or `executor/settings/*.json`. The Edit tool can do this too: `~/spectricom-orchestrator/executor/**` is not in §1's deny list, so I did not add it.

  What still holds: the kill hook still stops every tool call, Bash included, as long as `KILL` exists and the hook file is intact, and `kill` ends the processes anyway. Closing R1 needs a sandbox, which 330b showed cannot run here as-is (bwrap/socat missing; network namespace vs `localhost:8103`).
- **R2. OpenShell next** (330b R8). Its evaluation is the follow-on:
  - Landlock filesystem rules without bwrap or user namespaces;
  - default-deny egress that can still name host loopback ports (Medplum `:8103`);
  - vaulted credentials, so the agent never holds a real token.

  Once a sandbox exists, the `Read`/`Edit` rules here also feed its `filesystem.denyRead` / `denyWrite`.
- **R3. `Read(~/.claude/**)` also covers the CLI's tool-results store.** The CLI saves oversized tool output under `~/.claude/projects/<project>/tool-results/` and points the model at it. Not measured. If the Read tool is denied there, Toni has to use Bash `head`/`tail`. An `allow` cannot reopen it, because deny wins in Claude Code. The fix would be narrowing the deny to named files (`.credentials.json`, `settings*.json`, `hooks/`, `projects/*/memory/`).
- **R4. `Read(//mnt/c/**)` denies the Read tool on the canon** (Kanban, specs, `SCP_Agent_Inventory`). prefire reads the canon in the orchestrator process, so it is unaffected. Scan of the 10 other queued briefs: none names `/mnt/c`, OneDrive, a canon doc, or any denied path. A future brief that orders Toni to read a canon doc gets a Read denial, and Toni may fall back to Bash `cat`.
- **R5. A `kill` during the gate phase finds no fire.** It writes `KILL` and says "no live fire"; the gates and the merge carry on. The orchestrator process sits in the daemon's process group (`_run_route` has no setsid), so stopping it needs a pid-level kill. Not built: beyond §1.
- **R6. The nightly full gate is not a fire, and is not refused while `KILL` exists.** It runs merged code, never a route's branch.
- **R7. Two forms per agent-control rule.** `**/x` is relative to the cwd. `//**/x` covers paths outside it: P5 row 5 (an Edit outside the cwd) was denied. The CLI's message does not say which rule matched.
- **R8. `npm_config_ignore_scripts=true` is a default, not a wall.** Toni can write `npm_config_ignore_scripts=false npm ci` in a Bash command. clinical-mp and yorsie have no pre/post hooks around test or build (only `preview`). The gates run in the orchestrator's env and are unaffected.
- **R9. A new env knob, `TONI_GUARDS_HOME`.** It overrides the hook's state dir, for the tests and the canary. Every guarded fire drops it, so a real fire's hook always reads the dir `kill` writes to.

## Found-and-left

1. The user-level `~/.claude/settings.json` has a Bash `PreToolUse` hook (`guard-bash.py`). It merges with the per-repo file and still runs; I did not edit it.
2. `pcfg-chain.sh` waits on `pgrep -f "claude --dangerously"`. That still matches, because `--settings` comes after it. Nothing else parses the fire's command line.
3. Today `~/.npmrc`, `~/.git-credentials`, `~/.config/gcloud` and `~/.config/gh` are absent, and `~/.aws` is a symlink into `/mnt/c`.
4. The canary ran with `--no-session-persistence`, so no transcript went to `~/.claude/projects`. Its temp tree is deleted.

## Gates

- `python3 -m py_compile orchestrator.py queue_daemon.py`: OK.
- Targeted tests: every test file that exercises `fire_toni` / `toni_child_env` or imports `queue_daemon`, plus the new file, 22 files in all → **1072 passed**.
  - The files: `test_baseline_reuse_1`, `test_bg_ceiling`, `test_capacity`, `test_config_truth`, `test_control_scope`, `test_control_verdict_lines`, `test_depends_on`, `test_executor_default`, `test_foreground`, `test_gate_cost`, `test_handback_guard`, `test_merge_conflict`, `test_orch_lane`, `test_prefire`, `test_queue_gate_log`, `test_queue_pause`, `test_queue_retire`, `test_route_ref_integrity`, `test_stale_base`, `test_timeout_hold`, `test_toni_guards`, `test_yorsie_safety`.
  - A stub `claude` (logs and exits 97) was first on PATH for that run, so no test could start a real session. It was called 0 times.
- Not run: the full suite or a baseline (D-S7CORE30-05). The pre-merge gate runs `pytest -q tests/` next.
- No daemon restart. No write to clinical-mp. `~/.claude/settings.json` not edited. No secret printed: env names only; the `~/.ssh` probes were all denied.

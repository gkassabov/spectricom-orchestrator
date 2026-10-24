> **DRAFT — NOT QUEUED** (written by 339a ORCH-OPENSHELL-EVAL-1).
>
> To queue it, George:
> - adds line 1 `#!queue model=claude-opus-5-5 effort=xhigh repo=orchestrator`;
> - adds a Kanban row and his go;
> - does G1–G4 below first.
>
> It deliberately has no `#!queue` header, so a copy into `queue/` cannot fire as is.

# ORCH-TONI-OPENSHELL-1 — `fire_toni` runs Toni inside an OpenShell sandbox when `TONI_SANDBOX=openshell`, and fails closed; unset or `off` keeps today's fire byte-for-byte

## Repo: orchestrator (`~/spectricom-orchestrator`)
## Batch ID: s7core3x-orch-toni-openshell-1 (TBD)
## Briefs: 1
## Kanban: SCP_Kanban row TBD
## Estimated runtime: 240-360 min
## Test scope: targeted (D-S7CORE30-05)
## Spec reference: 339a ORCH-OPENSHELL-EVAL-1 handback (`briefs/339a-orch-openshell-eval-1.handback.md`) and `docs/openshell-eval/`. 330b STOP (b) (Bash sandbox: no bwrap, no localhost). 330d guards (`--settings`, kill hook, env scrub) stay on inside the sandbox
## Predecessor: orchestrator `main` at or after 339a's merge
## Depends-on: 339a-orch-openshell-eval-1
## Executor: claude-opus-5-5 --effort xhigh
## Agent policy: AP-TONI, AP-ORCH (SCP_Agent_Inventory_v0-1)
## George go: REQUIRED and not yet given (fire path, `orchestrator.py`, `queue_daemon.py` and `executor/**` are protected)

> Background tasks disabled. Foreground everything. No sudo, no apt, no Docker Desktop settings change, no daemon restart by the route. Live runs only against `localhost:8103` and the synthetic clinical-mp SITs named below. Never touch `:3002/:8112/:3004/:8114`. Never print a secret. At most two short `claude -p` canaries (P5, P8).

## Operability & safety
- **Telemetry:** every fire logs exactly one `🧱 sandbox: openshell ON (policy <repo> sha…, image <tag>, gateway <ver>, provider toni-oauth)` / `OFF` / `BLOCKED (<reason>)` line next to the existing `🛡 guards:` line. The sandbox's OCSF network decisions are appended to the route log (`openshell logs <sandbox> --since <fire start>`) before teardown.
- **Failure mode + degraded path:** any preflight miss (gateway down, version mismatch, image missing, policy missing or invalid, provider missing, Docker unavailable) refuses the fire with return code -2 and `🧱 sandbox: BLOCKED`. It never falls back to an unsandboxed fire. The degraded path is George setting `TONI_SANDBOX=off`, which is today's guarded fire.
- **Rollback / kill switch:**
  - Rollback is `TONI_SANDBOX=off`, or unset.
  - `queue_daemon.py kill` also deletes every sandbox labelled as a Toni route. 339a measured that sandbox processes are invisible to the host's `/proc`, so 330d's process-group walk cannot reach them.
  - The route timeout deletes the sandbox, too.
- **Agent permissions (Rule of Two):** AP-TONI / AP-ORCH. Inside the sandbox Toni holds no credential, only an OpenShell placeholder for the OAuth token. Egress is limited to `api.anthropic.com` (via the provider), the repo's package registry and the repo's named host ports. The filesystem is a Landlock allowlist: the route's tree plus system paths.
- **PHI & protected paths:**
  - No PHI: clinical-mp runs are synthetic `:8103` only.
  - Protected paths changed: `orchestrator.py` (fire path), `queue_daemon.py` (kill), `executor/**`. George's go is required (OPX-3).

## 0 · FIRST STEP
1. **Re-check 339a at the fire's HEAD.** Paste each:
   - the OpenShell release used (339a: v0.1.5 tarballs, `bdb956f`); if a newer stable exists, read its changelog for policy-schema or authority-check changes;
   - Docker Desktop version;
   - Landlock ABI (339a: 3);
   - one `sandbox create` → `exec true` → `delete` round trip (339a: 2.1 s).
2. **Read the fire path as it is.** Paste file:line for each:
   - `orchestrator.py`: `fire_toni`, `toni_child_env`, `toni_guards`, `_toni_guards_apply`;
   - `queue_daemon.py`: `kill`, `fire_process_groups`;
   - the 330d kill hook's state dir.

   Inside the sandbox `HOME=/sandbox`, so `executor/hooks/kill_switch.sh` would look in `/sandbox/spectricom-orchestrator`, find nothing, and **deny every tool call** (fail closed). Decide, and paste which:
   - (a) bind-mount `ORCH_DIR` read-only at its own path and pass `TONI_GUARDS_HOME` into the sandbox only;
   - (b) a dedicated KILL directory, mounted read-only.
3. **Scope.** In scope: clinical-mp and orchestrator. Every other repo with `TONI_SANDBOX=openshell` refuses (`BLOCKED (no policy for <repo>)`) until its image and policy exist. For each in-scope repo, paste:
   - the toolchain its routes need in the image (orchestrator: python3 + `requirements.txt` + pytest; clinical-mp: node 22.22.1, npm, npx, git; Playwright browsers only if E2E routes are in scope);
   - the host ports its tests need (clinical-mp: `:8103`, `:3001`, `:11434` per 330b);
   - the registries it needs.
4. **Git layout.** Per repo, which directories the fire must mount read-write for commits to work:
   - single-stream clinical-mp: the repo itself;
   - worktree repos (orchestrator meta-fire): the worktree plus the main repo's `.git`.

   Paste how `.git/hooks` and `.git/config` are made read-only inside the sandbox (nested read-only binds), and prove that a git commit still works.

## 1 · TARGET STATE
1. **Off.** `TONI_SANDBOX` unset or `off`: `fire_toni` builds the same command and environment as HEAD, byte-for-byte (P0).
2. **On.** `TONI_SANDBOX=openshell`: `fire_toni` does five things, in order.
   1. **Preflight** with `toni_sandbox(repo)`, beside `toni_guards`. It checks:
      - the gateway answers `openshell status` at the pinned version;
      - image `toni-<repo>:<claude-version>` exists, and its labelled Claude Code version equals the host's active version;
      - `executor/openshell/<repo>.policy.yaml` exists and loads;
      - provider `toni-oauth` exists.

      Any miss means `BLOCKED`, -2, and `claude` is never invoked.
   2. **Create.** `openshell sandbox create --name toni-<stem>-<ts> --label route=<stem> --from <image> --provider toni-oauth --policy <policy> --driver-config-json <mounts> --detach -- node /opt/toni/fwd.js <repo ports>`. The mounts:
      - the route's working dir, read-write at its own path;
      - `.git` as decided in §0.4;
      - `executor/settings` and `executor/hooks`, read-only;
      - the KILL state as decided in §0.2.
   3. **Exec.** `openshell sandbox exec -n <name> --no-tty --workdir <proj> --timeout <route timeout> --env <the guarded env's non-secret keys> -- claude --dangerously-skip-permissions --settings <ORCH_DIR>/executor/settings/<repo>.json --model … --effort … "<the same prompt>"`. Stdout goes to the route log exactly as today. The prompt and the `--settings` deny rules are unchanged.
   4. **Teardown.** `openshell sandbox delete <name>` in a `finally`, on success, on failure, on exception and on route timeout. The OCSF lines go to the route log first.
   5. **Log line.** One `🧱 sandbox:` line per fire.
3. **Kill.** `queue_daemon.py kill` deletes every sandbox labelled `route=*` after writing KILL, and logs each to `logs/kill-switch.log`. `unkill` is unchanged.
4. **Per-repo files, `executor/openshell/`:**
   - `<repo>.policy.yaml`, from `docs/openshell-eval/spike-policy.yaml`. The `api.anthropic.com` rule is narrowed to the paths Claude Code used in the 339a canary (`HEAD /api/hello`, `GET /api/claude_code/settings`, `GET /api/claude_code/policy_limits`, `POST /v1/messages`) plus any that P5 shows.
   - `images/<repo>/Dockerfile`.
   - `fwd.js`.
   - `build-image.sh <repo>`: copies the host's active Claude Code binary and labels the image with the versions.
   - `claude-code-oauth.profile.yaml`.
5. **Gateway.** A systemd `--user` unit template `systemd/openshell-gateway.service` (linger is already on: 339a measured `Linger=yes`).
   - mTLS (`generate-certs`), not 339a's plaintext unauthenticated loopback.
   - State under `~/.local/state/openshell-toni`, telemetry off.
   - Installing it is George's step, not the route's.
6. **README.** An "Executor sandbox (ORCH-TONI-OPENSHELL-1)" section:
   - what the sandbox covers: Bash commands' file and network reach, and credentials as placeholders;
   - what it does not cover: the R-items carried from 339a;
   - how to turn it off.

## 2 · ALLOWED FILES
- `orchestrator.py`: `fire_toni` plus new `toni_sandbox*` helpers only.
- `queue_daemon.py`: `kill` only.
- `executor/openshell/**` (new) and `systemd/openshell-gateway.service` (new).
- `tests/test_toni_sandbox.py` (new) and `tests/conftest.py` (default `TONI_SANDBOX=off` for unmarked tests).
- `README.md` (the new section).
- `briefs/<stem>.handback.md`.

## 3 · PREDICATES
- **P0 (control):** with `TONI_SANDBOX` unset and with `off`, the recorded `fire_toni` command and environment are byte-identical to HEAD's. Every existing `test_toni_guards.py` test passes unchanged.
- **P1 fail closed:** each preflight miss refuses the fire with -2 and `🧱 sandbox: BLOCKED (<reason>)`. That is one test per reason:
  - gateway down;
  - wrong version;
  - image missing;
  - Claude Code version mismatch;
  - policy missing;
  - policy invalid;
  - provider missing;
  - Docker unavailable.

  In each, no `claude` and no `sandbox create` is invoked (fake `openshell` on PATH).
- **P2 command shape:** the `create`, `exec` and `delete` argv (fake `openshell`) carry:
  - the mounts: working dir rw, `.git` per §0.4, `.git/hooks` and `.git/config` read-only, settings and hooks read-only;
  - `--provider toni-oauth` and the repo's `--policy`;
  - the unchanged `--settings` path, model, effort and prompt;
  - no secret-named env key.
- **P3 teardown:** `delete` runs exactly once on exit 0, exit 1, an exception, and a route timeout (mocked clock).
- **P4 kill (unit):** `kill` deletes each labelled sandbox (fake `openshell`). `kill-switch.log` names them.
- **P5 live canary** (one turn, clinical-mp policy, George's `toni-oauth` provider). From `stream-json`, paste:
  - the tool calls run;
  - `Read ~/.ssh/known_hosts` refused;
  - Bash `cat` of a decoy credential file refused (EACCES);
  - `curl localhost:8103/healthcheck` 200;
  - `curl https://example.com` blocked;
  - `CLAUDE_CODE_OAUTH_TOKEN` in the sandbox is an `openshell:` placeholder;
  - the cost.
- **P6 live clinical-mp:** in a temp clinical-mp clone under the sandbox (with `package-lock.json` copied: it is gitignored), `npx tsc --noEmit` and the one SIT `sit/integration/followup-real.integration.test.tsx` pass. The time is pasted against unsandboxed. 339a: tsc 89 s vs 86 s; SIT 12.7 s vs 10.1 s.
- **P7 orchestrator:** `pytest tests/test_toni_guards.py` passes inside the orchestrator image under its policy.
- **P8 live kill:** `queue_daemon.py kill` during a sandboxed canary ends it within 10 s: the sandbox is gone and the fire returns. Then `unkill --reason`.
- **P9 telemetry:** exactly one `🧱 sandbox:` line per fire, in every path.
- **P10 persistence:** a write to `.git/hooks/pre-commit` from inside the sandbox is refused (live).

## 4 · HANDBACK / 6 · GATES
The handback has: §0 pasted · P0–P10 RED→GREEN · the live P5/P6/P8 transcripts · the R-items. Gates: `test_toni_sandbox.py` and `test_toni_guards.py`, `py_compile`, and `git diff --stat`.

## STOP
- (a) Any change outside §2.
- (b) A step needs sudo, apt, a system install, or a Docker Desktop settings change: stop and name it.
- (c) Any daemon restart, any write to clinical-mp main, any secret printed.
- (d) The pinned OpenShell no longer loads `docs/openshell-eval/spike-policy.yaml`, or the forwarder path no longer reaches `:8103`: stop and report the release and the error.

## George actions before queueing (from 339a)
- **G1. The token.** Run `claude setup-token`, then create the provider yourself, so Toni never handles the token: `CLAUDE_CODE_OAUTH_TOKEN=… openshell provider create --name toni-oauth --type claude-code-oauth --credential CLAUDE_CODE_OAUTH_TOKEN`. 339a's `docs/openshell-eval/canary.sh` is the same step, for the scratch gateway.
- **G2. Gateway.** Choose where the gateway's state lives, and accept mTLS.
- **G3. Experimental platform.** Accept that OpenShell rates Windows (WSL 2 + Docker Desktop) **Experimental**, and that 0.1.x ships weekly.
- **G4. Paperwork.** Kanban row, George go, and `#!queue` header.

## Closes capability advancement: Bash-level sandbox for Toni (330b R1/R8)
## Gates journey: none

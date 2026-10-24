# Spectricom Multi-Agent Orchestrator

Autonomous multi-agent system for running coding tasks overnight. Two AI agents collaborate via the Anthropic API:

- **Toni** — Software Architect agent that writes production-grade code
- **Gemma** — Chief of Staff agent that answers questions and unblocks Toni

## Setup

```bash
# 1. Clone/navigate to the project
cd spectricom-orchestrator

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure API key
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

## Usage

```bash
# Preview the task queue without executing
python orchestrator.py --dry-run

# Run all pending tasks
python orchestrator.py

# Run a specific task
python orchestrator.py --task task-001
```

## Creating Tasks

Drop YAML files in `queue/tasks/`. See `queue/tasks/example-task.yaml` for the format:

```yaml
id: task-002
title: "Your task description"
status: pending
priority: 1
context: |
  Background information for the agent.
acceptance_criteria:
  - Criterion 1
  - Criterion 2
output_path: "output/my_file.py"
decision_rules:
  - "Rule for ambiguous situations"
do_not:
  - "Constraint the agent must follow"
max_iterations: 8
```

## How It Works

1. Orchestrator reads pending tasks from `queue/tasks/*.yaml`, sorted by priority
2. For each task, Toni receives the full spec and writes code
3. If Toni prefixes a response with `QUESTION:`, it's routed to Gemma
4. Gemma's answer is injected back into Toni's conversation
5. When Toni responds with `COMPLETE:`, output is written and the task is done
6. `BLOCKED:` or exceeding max iterations marks the task for manual review
7. Session report is written to `reports/`

## Output

- **Code output:** `output/{task-id}/` directory
- **JSON logs:** `logs/session-{timestamp}.jsonl` (every turn with token counts)
- **Session reports:** `reports/session-{timestamp}.md` (human-readable summary)

## Cost Controls

- Toni: max 4096 tokens per call
- Gemma: max 1024 tokens per call
- Per-task budget: 50,000 tokens (marked blocked if exceeded)
- All token usage logged with cost estimates

## Post-Merge SIT Integration (A58a)

After every successful Toni merge in clinical-mp, the orchestrator automatically runs `npm run sit:smoke` (Playwright smoke tests). This is **advisory in v1** — failures are logged and annotated but do NOT block the queue or roll back the merge.

### Skip SIT

```bash
# Skip SIT for a single run (time-sensitive)
python3 orchestrator.py run batch.md --approve --skip-sit
```

### SIT Report Aggregation

```bash
# Aggregate all SIT results
python3 orchestrator.py sit:report

# Since a specific date
python3 orchestrator.py sit:report --since 2026-05-01
```

### Behavior

- SIT runs after merge, before next brief fires
- Reports archived to `sit-archive/`
- Outcomes logged to `sit-archive/orchestrator-sit-log.json`
- Merge commit annotated (via git notes) on SIT failure
- 5-minute timeout per SIT run
- Does NOT block queue progression in v1

## Pre-fire assertions (prefire.py)

`run_batch` runs `prefire.report(brief)` before anything fires; any failure refuses the brief (the daemon moves it to
`queue/failed/`, and `stop_on_failure` pauses the queue). `python3 prefire.py <brief.md> …` runs the same checks
read-only. The module docstring holds the full list: A1 Kanban row READY · A2 runtime and sizing · A8 no skip-sit ·
A9 / A10 test scope · A11 depends-on.

**OpEx pre-checks** (ORCH-OPEX-PREFIRE-1, D-S7CORE33-20) — one line each per brief, in prefire output and the fire log:

| | Rule | Passes when |
|---|---|---|
| OPX-1 | Kanban row ≥ 393 | `## Operability & safety` has non-empty `Telemetry:`, `Failure mode…:`, `Rollback…:`, `Agent permissions…:`, `PHI…:` lines; "none" / "n/a" only with a reason (≥ 3 words). Rows below 393: `OPX-1 — grandfathered (row N < 393)`. |
| OPX-2 | ALLOWED FILES name an agent-runtime path | the brief cites an `AP-…` id listed in the newest `SCP_Agent_Inventory_v*.md` in the canon folder. No inventory file yet: warning, pass. |
| OPX-3 | ALLOWED FILES name a never-autonomous path | the brief has a `## George go:` line, or a `## Briefs:` / `## Spec reference:` line matching `George[^\n]{0,80}\b(go\|GO\|agreed\|Agree)\b`. |

- The path lists are data: `prefire_opex_paths.json` (`agent_runtime` and `protected`, by `#!queue … repo=`; `*` = every repo). Edit them there, without a code change.
- OPX-2 and OPX-3 read the ALLOWED FILES section(s): code spans, and bare words with a `/` or a file extension. Text after `Read only:` or `**Not**` on a line is ignored. A bare file name such as `negation.ts` has no directory, so it is matched by name only, and the clean line says how many such names there were.
- Fail closed: from row 393 on, a brief with no ALLOWED FILES section is refused. Any brief with an ALLOWED FILES section is refused while `prefire_opex_paths.json` is unreadable. A brief that names an agent-runtime path is refused while the canon folder, or the inventory in it, cannot be read.
- Kill switch: `PREFIRE_OPEX=off` skips OPX-1–OPX-3 and prints a `⚠⚠ PREFIRE_OPEX=off … SKIPPED` line on every fire. `--force` still bypasses every check. The variable kept its name through the rename below.
- Old labels (ORCH-PREFIRE-RENAME-1): OPX-1, OPX-2 and OPX-3 were A12, A13 and A14 until route 330e. They were renamed because SESSION-BOOT's PRE-FIRE ASSERTION BLOCK uses A12 and A13 for other checks. Every pass/refuse decision is unchanged.

## Executor guards (ORCH-TONI-GUARDS-1)

This is what ships while there is no Bash sandbox (`briefs/330b-orch-toni-sandbox-1.handback.md`, STOP (b)).

**Bash commands are still unsandboxed.** The deny rules below bind Claude Code's file tools only: Read, Edit, Write, Grep and Glob. A shell command such as `cat ~/.ssh/id_ed25519`, `curl …` or `rm ~/spectricom-orchestrator/KILL` runs with this user's full rights. It can read every path in the table, reach the network, and lift the kill switch.
- Claude Code's Linux sandbox would close this gap, but it cannot be used here:
  - it needs `bwrap` and `socat`, which are not installed (and `sudo` needs a password);
  - even installed, it runs each command in its own network namespace, so live SITs could not reach Medplum on `localhost:8103` (330b R1).
- The follow-on is an OpenShell evaluation (330b R8): Landlock filesystem rules with no bwrap, default-deny egress that can still name host loopback ports, and vaulted credentials.

**Per-repo settings.** Each repo in `config/repos.yaml` has `executor/settings/<repo>.json`.
- `fire_toni` passes it on every fire as `--settings <ORCH_DIR>/executor/settings/<repo>.json`.
- Claude Code 2.1.283 honours its deny rules under `--dangerously-skip-permissions`. In the CLI's own words: "auto-approves every tool call (except explicit deny rules)".
- Grep and Glob run the same check as Read, so the `Read(...)` rules cover them.

| Rule | Paths | Why |
|---|---|---|
| `Read` + `Edit` deny | `~/.ssh/**`, `~/.aws/**`, `~/.config/gcloud/**`, `~/.config/gh/**`, `~/.git-credentials`, `~/.npmrc`, `~/.docker/config.json`, `~/.claude/**`, `//mnt/c/**` | credentials (`~/.claude/.credentials.json` is the CLI's OAuth token) and the OneDrive canon |
| `Edit` deny | `**/.claude/**`, `**/.mcp.json`, `**/.github/workflows/**`, `**/.husky/**`, `**/.vscode/tasks.json`, each also as `//**/…` | agent-control and persistence files, under the working dir and anywhere on disk |
| `Read` allow (orchestrator only) | `~/spectricom-orchestrator/queue/**`, `~/spectricom-orchestrator/logs/**` | orchestrator routes read the live trays and logs. Nothing denies them today; in Claude Code a deny would beat this allow |

- `CLAUDE.md` is not denied, because routes legitimately edit it.
- How rule paths are read: `~/` = home and `//` = filesystem root. **Never start a rule with one `/`**: in a `--settings` file that is relative to `executor/settings/`.
- The CLI silently ignores a settings file that fails validation in non-interactive mode. Check an edited file with `claude doctor`, run in a scratch dir that holds a copy as `.claude/settings.json`: it lists invalid settings, and lists nothing when the file is valid.

**Environment.**
- Dropped from every fire's env, logged by name only: `SSH_AUTH_SOCK`, `GH_TOKEN`, `GITHUB_TOKEN`, `GROQ_API_KEY`, `AWS_*`, `GOOGLE_APPLICATION_CREDENTIALS`, and `TONI_GUARDS_HOME` (the hook's test override).
- Set: `npm_config_ignore_scripts=true`. `npm test` / `npm run x` still run their script, but no pre-, post- or install scripts run.

**Kill switch.**
- `python3 queue_daemon.py kill [--reason "<text>"]` does two things:
  - It writes `~/spectricom-orchestrator/KILL`. From then on, the `PreToolUse` hook `executor/hooks/kill_switch.sh` (matcher `*`, in every settings file) denies every tool call of every fire.
  - It sends SIGTERM to the running fire's process groups, then SIGKILL after 5 s. The groups are the fire's own (setsid) and each Bash command's.
- The daemon fires nothing while `KILL` exists. The next brief waits in `queue/`, and `status` shows `waiting: … KILL present …`.
- `python3 queue_daemon.py unkill --reason "<text>"` removes `KILL`. The reason is required.
- Each kill and unkill is one line, printed and appended to `logs/kill-switch.log`.
- A killed route ends as a failed (or INCOMPLETE) route, so with `stop_on_failure` the queue also pauses. After `unkill`, run `resume`.
- The hook fails closed. Each of these denies the call:
  - the state dir cannot be read;
  - `KILL` is a dangling link or a directory;
  - the hook script is missing (the settings command is `bash "<hook>" || exit 2`).

**Fire lines and switches.**
- Every fire logs exactly one of these lines:
  - `🛡 guards: ON (settings <repo> sha <12 hex>, deny N, env dropped [...], npm_config_ignore_scripts=true)`
  - `🛡 guards: OFF (TONI_GUARDS=off) …`
  - `🛡 guards: BLOCKED — <why>; not fired …`
- A repo with no settings file, or with one that is unreadable, not JSON, has no deny rules or has no kill hook, is refused (`BLOCKED`). It is never fired unguarded.
- `TONI_GUARDS=off` (any case) fires exactly as before this route: no `--settings`, no env scrub, no hook. The daemon's refusal while `KILL` exists stays on, because only `unkill` lifts it.

## Project Structure

```
spectricom-orchestrator/
├── orchestrator.py          # Main entry point
├── agents/
│   ├── toni.py              # Toni agent (coding/building)
│   └── gemma.py             # Gemma agent (decisions/answers)
├── queue/
│   ├── task_manager.py      # Task queue management
│   └── tasks/               # Drop .yaml task files here
├── loop/
│   ├── executor.py          # Main task execution loop
│   ├── question_detector.py # Response type detection
│   └── context_manager.py   # Conversation history per task
├── session_logging/
│   └── session_logger.py    # Structured JSON + Markdown logging
├── reports/                 # Session reports written here
└── output/                  # Code output from tasks
```

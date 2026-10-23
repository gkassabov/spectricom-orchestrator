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
| A12 (OPX-1) | Kanban row ≥ 393 | `## Operability & safety` has non-empty `Telemetry:`, `Failure mode…:`, `Rollback…:`, `Agent permissions…:`, `PHI…:` lines; "none" / "n/a" only with a reason (≥ 3 words). Rows below 393: `A12 — grandfathered (row N < 393)`. |
| A13 (OPX-2) | ALLOWED FILES name an agent-runtime path | the brief cites an `AP-…` id listed in the newest `SCP_Agent_Inventory_v*.md` in the canon folder. No inventory file yet: warning, pass. |
| A14 (OPX-3) | ALLOWED FILES name a never-autonomous path | the brief has a `## George go:` line, or a `## Briefs:` / `## Spec reference:` line matching `George[^\n]{0,80}\b(go\|GO\|agreed\|Agree)\b`. |

- The path lists are data: `prefire_opex_paths.json` (`agent_runtime` and `protected`, by `#!queue … repo=`; `*` = every repo). Edit them there, without a code change.
- A13 and A14 read the ALLOWED FILES section(s): code spans, and bare words with a `/` or a file extension. Text after `Read only:` or `**Not**` on a line is ignored. A bare file name such as `negation.ts` has no directory, so it is matched by name only, and the clean line says how many such names there were.
- Fail closed: from row 393 on, a brief with no ALLOWED FILES section is refused. Any brief with an ALLOWED FILES section is refused while `prefire_opex_paths.json` is unreadable. A brief that names an agent-runtime path is refused while the canon folder, or the inventory in it, cannot be read.
- Kill switch: `PREFIRE_OPEX=off` skips A12–A14 and prints a `⚠⚠ PREFIRE_OPEX=off … SKIPPED` line on every fire. `--force` still bypasses every check.

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

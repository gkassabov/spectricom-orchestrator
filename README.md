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

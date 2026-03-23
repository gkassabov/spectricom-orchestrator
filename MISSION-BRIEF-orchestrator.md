# MISSION BRIEF — Spectricom Multi-Agent Orchestrator
## For: Toni (Claude Code autonomous build)
## From: Gemma (via George)
## Date: March 21, 2026
## Execution window: Overnight — George is away, no interruptions available
## Estimated build time: 2-3 hours

---

## MISSION OBJECTIVE

Build a Python-based multi-agent orchestrator that:
1. Reads tasks from a queue (YAML files in a `tasks/` directory)
2. Executes each task by calling the Anthropic API with Toni's identity and system prompt
3. Detects when Toni hits a question or blocker and routes it to a "Gemma" API call for an answer
4. Feeds the answer back to Toni and continues
5. Logs everything (inputs, outputs, decisions, costs, errors) to structured files
6. Moves to the next task when done
7. Sends a summary report to a `reports/` directory when all tasks complete

This is Spectricom's internal dev automation proof-of-concept. It proves the multi-agent pattern. Code must be production-grade per Spectricom engineering principles.

---

## ARCHITECTURE DECISION — LOCKED, DO NOT DEVIATE

**Use direct Anthropic API calls. Do NOT attempt to drive the Claude Code CLI programmatically.**

Claude Code is an interactive tool. The orchestrator is a standalone Python script that calls `anthropic.Anthropic().messages.create()` with appropriate system prompts. Toni "runs" as an API agent with a system prompt. Gemma "runs" as a separate API agent with a different system prompt.

This is cleaner, fully autonomous, and scriptable. It is the correct architecture.

---

## FILE STRUCTURE TO BUILD

```
spectricom-orchestrator/
├── CLAUDE.md                    # Project context (Toni reads this)
├── README.md                    # Setup and usage instructions
├── requirements.txt             # anthropic, pyyaml, python-dotenv, rich
├── .env.example                 # ANTHROPIC_API_KEY placeholder
├── .gitignore                   # .env, __pycache__, logs/, reports/
├── orchestrator.py              # Main entry point
├── agents/
│   ├── __init__.py
│   ├── toni.py                  # Toni agent (Sonnet — coding/building)
│   └── gemma.py                 # Gemma agent (Sonnet — decisions/answers)
├── queue/
│   ├── task_manager.py          # Reads, parses, tracks task queue
│   └── tasks/                   # Drop .yaml task files here
│       └── example-task.yaml    # Example task file George can use as template
├── loop/
│   ├── __init__.py
│   ├── executor.py              # Main task execution loop
│   ├── question_detector.py     # Detects when Toni is asking a question
│   └── context_manager.py      # Manages conversation history per task
├── logging/
│   ├── __init__.py
│   └── session_logger.py        # Structured logging to JSON + human-readable
└── reports/
    └── .gitkeep                 # Reports written here at session end
```

---

## COMPONENT SPECIFICATIONS

### orchestrator.py (entry point)

```python
# Usage:
#   python orchestrator.py                    # Run all pending tasks
#   python orchestrator.py --task task-001    # Run specific task
#   python orchestrator.py --dry-run          # Preview queue, don't execute

# Flow:
# 1. Load .env
# 2. Read task queue from queue/tasks/*.yaml (status: pending)
# 3. For each task: run executor.execute_task(task)
# 4. On KeyboardInterrupt: save state, write partial report
# 5. On completion: write session report to reports/
```

### Task YAML format (queue/tasks/example-task.yaml)

```yaml
id: task-001
title: "Build Akute FHIR patient fetch function"
status: pending  # pending | in_progress | complete | failed | blocked
priority: 1      # lower = higher priority
context: |
  We are building Spectricom — an AI-native concierge medicine platform.
  EHR is Akute Health. API auth uses X-API-Key header (NOT Bearer).
  Base URL: https://api.akutehealth.com/v1
  Test patient ID: e47d9309-8a66-453c-ad45-2f45c309e651 (Margaret Chen)
  All PHI stays in Akute. No custom PHI storage per D-015.
acceptance_criteria:
  - Function get_patient_context(patient_id) returns demographics, conditions, meds, labs
  - Proper error handling for 401, 404, 500
  - Typed with TypedDict return type
  - Docstring with example usage
  - Unit test with mock responses
output_path: "output/akute_client.py"
decision_rules:
  - "If Akute API returns unexpected field names, log them and use .get() with defaults"
  - "If pagination is needed, implement it — don't truncate results"
  - "If unsure about FHIR R4 resource structure, default to the simpler /patients/{id} REST endpoint"
do_not:
  - "Do not store any patient data to disk"
  - "Do not hardcode the API key"
  - "Do not use requests — use httpx for async compatibility"
max_iterations: 8  # Toni gets this many turns before task is marked blocked
```

### agents/toni.py

```python
TONI_SYSTEM_PROMPT = """
You are Toni, the Software Architect Agent for the Spectricom platform.
You write production-grade Python code. You report to George Kassabov.

ENGINEERING PRINCIPLES (non-negotiable):
- Best-in-class code: proper error handling, typed interfaces, docstrings, tests
- No custom PHI storage — all PHI in BAA-covered systems only (Akute Health)
- Observable by default — log inputs, outputs, errors with structured data
- No shortcuts without explicit written approval
- No trial-and-error — plan before coding

EFFICIENCY RULES:
- Read the task spec fully before writing a single line
- If you need clarification, ask ONE specific question clearly
- Prefix questions with: "QUESTION:" so they can be detected
- Prefix completed work with: "COMPLETE:" followed by a summary
- Prefix blockers with: "BLOCKED:" followed by the specific reason
- Never ask about things covered in the task spec or decision_rules

STACK:
- EHR: Akute Health (X-API-Key auth, REST + FHIR R4)
- AI: Anthropic Claude (Sonnet for reasoning, Haiku for volume)
- Portal: Next.js + Medplum React components + Tailwind
- Wearables: Terra API → FHIR R4 bridge → Akute
- Language: Python for agents/pipelines, TypeScript for portal
- No OpenClaw. No NemoClaw. Direct API calls only.
"""

def call_toni(messages: list, task_context: str) -> str:
    # Calls claude-sonnet-4-20250514 with TONI_SYSTEM_PROMPT
    # Returns the text response
    # Tracks token usage and logs it
    pass
```

### agents/gemma.py

```python
GEMMA_SYSTEM_PROMPT = """
You are Gemma, Chief of Staff AI for the Spectricom platform.
You answer questions from Toni (the coding agent) when he is blocked or uncertain.
Your answers must be:
- Specific and actionable — Toni needs to continue coding, not think
- Brief — one decision per question, no elaboration unless necessary
- Decisive — pick one option, don't present alternatives unless genuinely equivalent

Context you always have:
- Platform: Spectricom (AI-native concierge medicine)
- EHR: Akute Health (X-API-Key header, not Bearer)
- PHI rule: No custom PHI storage — Akute is the system of record
- Stack: Python for agents, TypeScript for portal, Anthropic API for AI
- Engineering standard: Production-grade, no shortcuts
"""

def call_gemma(question: str, task_context: str) -> str:
    # Calls claude-sonnet-4-20250514 with GEMMA_SYSTEM_PROMPT
    # Returns a direct answer to Toni's question
    pass
```

### loop/question_detector.py

```python
# Detects whether Toni's response contains a question requiring Gemma's input
# Returns: ("question", question_text) | ("complete", summary) | ("blocked", reason) | ("continue", None)

QUESTION_SIGNALS = ["QUESTION:", "BLOCKED:", "unclear", "which should", "should I", "do you want"]
COMPLETE_SIGNALS = ["COMPLETE:", "task complete", "all acceptance criteria met"]
BLOCKED_SIGNALS  = ["BLOCKED:", "cannot proceed", "missing required"]

def detect_response_type(response: str) -> tuple[str, str | None]:
    # Check for explicit prefixes first (QUESTION:, COMPLETE:, BLOCKED:)
    # Then check signal phrases as fallback
    # Returns type and extracted text
    pass
```

### loop/executor.py

```python
# Main execution loop for a single task

def execute_task(task: dict) -> dict:
    """
    Execute one task through the Toni → Gemma loop.
    
    Flow:
    1. Build initial prompt from task spec
    2. Call Toni
    3. Detect response type
    4. If QUESTION: call Gemma, inject answer, call Toni again
    5. If COMPLETE: write output, mark task done, return result
    6. If BLOCKED: log reason, mark task blocked, return result
    7. If max_iterations exceeded: mark blocked, log last state
    8. Log every turn with timestamp, token count, cost estimate
    
    Returns: {status, output, turns_used, total_tokens, cost_estimate, log_path}
    """
    pass
```

### logging/session_logger.py

```python
# Writes two outputs per task:
# 1. JSON log: machine-readable, every turn, all metadata
# 2. Human log: readable summary George can review in the morning

# Log structure per turn:
{
    "task_id": "task-001",
    "turn": 1,
    "agent": "toni",
    "input_tokens": 1240,
    "output_tokens": 856,
    "cost_usd": 0.012,
    "response_type": "question",
    "timestamp": "2026-03-22T02:14:33Z"
}

# Session report (written at end):
# - Tasks completed / blocked / failed
# - Total tokens used
# - Total cost estimate
# - Time elapsed
# - List of output files written
# - Any blocked tasks with reasons (George resolves these next morning)
```

---

## ACCEPTANCE CRITERIA

Before marking this build complete, verify ALL of the following:

- [ ] `python orchestrator.py --dry-run` prints the task queue without executing
- [ ] `python orchestrator.py --task example-task` runs the example task end-to-end
- [ ] A QUESTION from Toni is correctly detected and routed to Gemma
- [ ] Gemma's answer is injected back into Toni's conversation
- [ ] COMPLETE signal terminates the task loop cleanly
- [ ] BLOCKED signal (or max_iterations hit) marks task as blocked and continues to next
- [ ] Every turn is logged to JSON with token counts
- [ ] Session report is written to reports/ at completion
- [ ] `output/` directory receives any code Toni writes during the example task
- [ ] `.env.example` contains all required keys with placeholder values
- [ ] `requirements.txt` is complete and `pip install -r requirements.txt` succeeds
- [ ] `README.md` has setup steps and usage examples
- [ ] No API keys hardcoded anywhere
- [ ] No PHI anywhere in the codebase (test data uses synthetic patients only)

---

## DECISION RULES — Pre-answers to likely questions

**Q: Which Claude model should Toni and Gemma use?**
A: `claude-sonnet-4-20250514` for both. It's production Sonnet 4. Do not use Opus (cost) or Haiku (quality).

**Q: Should I use async (asyncio) or sync API calls?**
A: Sync for now. The orchestrator runs tasks sequentially overnight, no parallelism needed in v1.

**Q: How do I control token spend?**
A: Set `max_tokens=4096` for Toni calls, `max_tokens=1024` for Gemma calls (answers should be short). Log token usage after every call. If a single task exceeds 50,000 total tokens, mark it blocked and stop.

**Q: What if Toni writes code in his response — where does it go?**
A: Extract code blocks from Toni's response (```python...```) and write them to `output/{task_id}/` directory. Toni should also include COMPLETE: with a summary when done.

**Q: What if the Anthropic API returns a rate limit or error?**
A: Retry with exponential backoff: 5s, 15s, 45s. After 3 retries, mark task as blocked with reason "API error: [message]".

**Q: Should I use streaming responses?**
A: No. Standard non-streaming messages API. Simpler for logging and token counting.

**Q: What format for the session report?**
A: Plain Markdown file at `reports/session-{timestamp}.md`. Human-readable. George reads this in the morning.

**Q: Should I build a web UI or dashboard?**
A: No. CLI only. This is a dev tool, not a patient-facing feature.

**Q: What if a task's output_path already exists?**
A: Overwrite it. Tasks are idempotent by design.

**Q: Should conversation history accumulate across tasks?**
A: No. Each task starts with a fresh conversation. Only CLAUDE.md / system prompt persists between tasks. This keeps context clean and cost predictable.

---

## WHAT NOT TO BUILD

- No web server, no Flask/FastAPI endpoints
- No database — file-based queue and logs only (v1)
- No parallel task execution — sequential is fine for overnight runs
- No Claude Code CLI subprocess calls
- No OpenClaw, no NemoClaw, no LangGraph (this is a standalone script)
- No patient-facing features
- No real patient data — example task uses Margaret Chen synthetic data only

---

## OUTPUT LOCATION

Write all build output to: `spectricom-orchestrator/`

This is a new directory. Create it fresh. Do not modify any existing POC directories.

---

## WHEN YOU ARE DONE

1. Write `reports/session-{timestamp}.md` with the session summary
2. Print "ORCHESTRATOR BUILD COMPLETE" to terminal
3. List all files created
4. List any blocked tasks with reasons

George will review in the morning.

---

## ENVIRONMENT

- Machine: ASUS Zenbook S 16, Windows 11, WSL2 Ubuntu
- Python: 3.12+ in WSL
- Working directory: `/home/george/spectricom-orchestrator` (create if needed)
- Anthropic API key: in environment as `ANTHROPIC_API_KEY`
- No other external dependencies needed

---

*Brief generated by Gemma, March 21, 2026*
*Spectricom Platform — Internal Dev Automation POC*

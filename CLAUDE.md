# Spectricom Multi-Agent Orchestrator

## What This Is
A Python-based multi-agent orchestrator that runs coding tasks autonomously using two AI agents:
- **Toni** (Software Architect) — writes production-grade code
- **Gemma** (Chief of Staff) — answers questions when Toni is blocked

## Architecture
Direct Anthropic API calls. No CLI subprocess driving. No frameworks (LangGraph, etc.).

Tasks are YAML files in `queue/tasks/`. The orchestrator reads them, runs Toni in a loop, escalates questions to Gemma, and writes output + logs.

## Key Rules
Shared rules: `~/SPECTRICOM-SHARED-RULES.md` (product) and `Common\SHARED-RULES-v1-0.md` (universal). Not restated here.

- **Model:** see product shared rules §1. **UNRATIFIED — this repo currently pins two different models**: `claude-opus-4-8` in `orchestrator.py` and `config/repos.yaml`, `claude-sonnet-4-20250514` in `agents/toni.py`, `agents/gemma.py`, `loop/executor.py`. One is unintended. Do not change either without owner instruction.
- **Token caps:** product shared rules §2. Referenced by constant name, never inline.
- Sync API calls, sequential task execution

## Running
```bash
python orchestrator.py --dry-run          # Preview queue
python orchestrator.py                    # Run all pending tasks
python orchestrator.py --task task-001    # Run specific task
```

## OUTPUT FILE RULES (mandatory)
Every code block in your response MUST start with a filename comment as the very first line.
Format: # filename: example_name.py
Examples:
  # filename: akute_client.py
  # filename: spectricom-bootstrap.sh
  # filename: CLAUDE.md
Never omit this line. The automated extractor uses it to name the output file.
If you omit it, the file is saved as output_001.py which requires manual renaming.

## CRITICAL CODING RULES (never violate)
- Never rewrite entire files — make targeted edits only
- Never instantiate API clients at module level — always inside functions
- Never hardcode token values — use TONI_MAX_TOKENS, never max_tokens=4000
- Never change existing constants like TONI_MAX_TOKENS without explicit instruction
- Prefer editing 5 lines over rewriting 200 lines

---

## Test scope — no duplicate regression runs (source: `~/SPECTRICOM-SHARED-RULES.md` §7, D-S7CORE30-05)
Run only: typecheck / build, lint on changed files, tests related to the files you changed, and your own new or changed SIT/integration tests alone. **Never run a full suite or a baseline** (bare `npm test`, `npm run sit:gate`, a merge-base baseline, bare `pytest`) — the orchestrator's pre-merge gate runs them right after you, and the full suites run nightly and before every tester session. A brief that orders full suites says so in its `## Test scope: full — <George decision>` header; nothing else does.

# Spectricom Multi-Agent Orchestrator

## What This Is
A Python-based multi-agent orchestrator that runs coding tasks autonomously using two AI agents:
- **Toni** (Software Architect) — writes production-grade code
- **Gemma** (Chief of Staff) — answers questions when Toni is blocked

## Architecture
Direct Anthropic API calls. No CLI subprocess driving. No frameworks (LangGraph, etc.).

Tasks are YAML files in `queue/tasks/`. The orchestrator reads them, runs Toni in a loop, escalates questions to Gemma, and writes output + logs.

## Key Rules
- Model: `claude-sonnet-4-20250514` for both agents
- No PHI storage — all patient data stays in Akute Health
- No hardcoded API keys — use `.env`
- Sync API calls, sequential task execution
- Max 4096 tokens per Toni call, 1024 per Gemma call
- Max 50,000 tokens per task before marking blocked

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

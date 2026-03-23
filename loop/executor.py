import os
import re
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import logging

import anthropic

logger = logging.getLogger(__name__)

# Token budget per task (from CLAUDE.md)
TOKEN_CAP = 12_000
TONI_MAX_TOKENS = 8192

# Model IDs
TONI_MODEL = "claude-sonnet-4-20250514"
GEMMA_MODEL = "claude-sonnet-4-20250514"

# client initialized lazily inside functions


def execute_task(task: dict, logger) -> dict:
    """Execute one task through the Toni -> Gemma loop.

    Flow:
    1. Build initial prompt from task spec
    2. Call Toni
    3. Detect response type
    4. If QUESTION: call Gemma, inject answer, call Toni again
    5. If COMPLETE: write output, mark task done, return result
    6. If BLOCKED: log reason, mark task blocked, return result
    7. If max_iterations exceeded: mark blocked, log last state
    8. Log every turn with timestamp, token count, cost estimate

    Args:
        task: Task dict from YAML.
        logger: Session logger instance.

    Returns:
        Dict with status, output, turns_used, total_tokens, cost_estimate, log_path.
    """
    client = anthropic.Anthropic()
    task_id = task.get("id", "unknown")
    max_iterations = task.get("max_iterations", 10)
    task["status"] = "in_progress"

    initial_prompt = _build_initial_prompt(task)
    total_tokens = 0
    total_cost = 0.0

    ctx = [{"role": "user", "content": initial_prompt}]

    for turn in range(1, max_iterations + 1):
        # Call Toni
        try:
            toni_response = client.messages.create(
                model=TONI_MODEL,
                max_tokens=TONI_MAX_TOKENS,
                messages=ctx,
            )
        except Exception as e:
            result = {
                "status": "failed",
                "output": str(e),
                "turns_used": turn,
                "total_tokens": total_tokens,
                "cost_estimate": total_cost,
            }
            logger.record_task_result(result)
            return result

        toni_text = toni_response.content[0].text
        turn_tokens = toni_response.usage.input_tokens + toni_response.usage.output_tokens
        total_tokens += turn_tokens
        total_cost += toni_response.usage.input_tokens * 0.003 / 1000 + toni_response.usage.output_tokens * 0.015 / 1000

        logger.record_task_result({
            "task_id": task_id,
            "turn": turn,
            "agent": "toni",
            "input_tokens": toni_response.usage.input_tokens,
            "output_tokens": toni_response.usage.output_tokens,
            "cost_usd": toni_response.usage.input_tokens * 0.003 / 1000 + toni_response.usage.output_tokens * 0.015 / 1000,
        })

        # Check token budget
        if total_tokens > TOKEN_CAP:
            reason = f"Token budget exceeded: {total_tokens} > {TOKEN_CAP}"
            task["status"] = "blocked"
            _write_output(task, toni_text)
            return {
                "status": "blocked",
                "output": reason,
                "turns_used": turn,
                "total_tokens": total_tokens,
                "cost_estimate": total_cost,
            }

        # Detect response type
        resp_type, resp_text = _detect_response_type(toni_text)

        if resp_type == "complete":
            task["status"] = "complete"
            _write_output(task, toni_text)
            _extract_and_write_code(task, toni_text)
            return {
                "status": "complete",
                "output": resp_text,
                "turns_used": turn,
                "total_tokens": total_tokens,
                "cost_estimate": total_cost,
            }

        elif resp_type == "blocked":
            task["status"] = "blocked"
            _write_output(task, toni_text)
            return {
                "status": "blocked",
                "output": resp_text,
                "turns_used": turn,
                "total_tokens": total_tokens,
                "cost_estimate": total_cost,
            }

        elif resp_type == "question":
            # Route to Gemma
            ctx.append({"role": "assistant", "content": toni_text})
            try:
                gemma_response = client.messages.create(
                    model=GEMMA_MODEL,
                    max_tokens=2000,
                    system="You are Gemma, Chief of Staff at Spectricom. Answer Toni's question concisely.",
                    messages=[{"role": "user", "content": resp_text}],
                )
                gemma_text = gemma_response.content[0].text
                gemma_tokens = gemma_response.usage.input_tokens + gemma_response.usage.output_tokens
                total_tokens += gemma_tokens
                total_cost += gemma_response.usage.input_tokens * 0.003 / 1000 + gemma_response.usage.output_tokens * 0.015 / 1000

                logger.record_task_result({
                    "task_id": task_id,
                    "turn": turn,
                    "agent": "gemma",
                    "input_tokens": gemma_response.usage.input_tokens,
                    "output_tokens": gemma_response.usage.output_tokens,
                    "cost_usd": gemma_response.usage.input_tokens * 0.003 / 1000 + gemma_response.usage.output_tokens * 0.015 / 1000,
                    "response_type": "answer",
                    "detail": gemma_text[:200],
                })

                ctx.append({"role": "user", "content": "Gemma (Chief of Staff) answers:\n\n" + gemma_text})
            except Exception as e:
                ctx.append({"role": "user", "content": f"Gemma API error: {e}"})

        else:
            # Continue — treat as ongoing work
            ctx.append({"role": "assistant", "content": toni_text})
            ctx.append({"role": "user", "content": "Continue working on the task. Remember to prefix your final output with COMPLETE: when all acceptance criteria are met."})

    # Max iterations exceeded
    task["status"] = "blocked"
    reason = f"Max iterations ({max_iterations}) exceeded"
    _write_output(task, toni_text)
    return {
        "status": "blocked",
        "output": reason,
        "turns_used": max_iterations,
        "total_tokens": total_tokens,
        "cost_estimate": total_cost,
    }


def _detect_response_type(text: str) -> Tuple[str, str]:
    """Detect response type from Toni's text prefix."""
    stripped = text.strip()
    if stripped.upper().startswith("COMPLETE:"):
        return "complete", stripped[len("COMPLETE:"):].strip()
    elif stripped.upper().startswith("BLOCKED:"):
        return "blocked", stripped[len("BLOCKED:"):].strip()
    elif stripped.upper().startswith("QUESTION:"):
        return "question", stripped[len("QUESTION:"):].strip()
    return "continue", stripped


def _build_initial_prompt(task: dict) -> str:
    """Build the initial user message for Toni from the task spec."""
    parts = [f"# Task: {task.get('title', 'Untitled')}"]

    if task.get("context"):
        parts.append(f"\n## Context\n{task['context']}")

    if task.get("acceptance_criteria"):
        criteria = "\n".join(f"- {c}" for c in task["acceptance_criteria"])
        parts.append(f"\n## Acceptance Criteria\n{criteria}")

    if task.get("decision_rules"):
        rules = "\n".join(f"- {r}" for r in task["decision_rules"])
        parts.append(f"\n## Decision Rules\n{rules}")

    if task.get("do_not"):
        donts = "\n".join(f"- {d}" for d in task["do_not"])
        parts.append(f"\n## Do NOT\n{donts}")

    if task.get("output_path"):
        parts.append(f"\n## Output\nWrite the code to: {task['output_path']}")

    parts.append(
        "\n## Instructions\n"
        "CRITICAL: You MUST complete this task in a SINGLE response. "
        "Start your response with the code/content immediately. "
        "Your VERY FIRST LINE must be COMPLETE: followed by a one-line summary. "
        "Then provide the code. Do NOT explain what you will do. Just do it. "
        "Do NOT ask questions. If something is ambiguous, make a reasonable choice and note it. "
        "If you cannot finish in one response, prefix with BLOCKED: and explain why."
    )

    return "\n".join(parts)


def _extract_python_code_blocks(response: str) -> List[Tuple[str, str]]:
    """Extract code blocks from a fenced markdown response.

    Matches all fenced code blocks with any language tag.
    Returns list of (language_tag, code_content) tuples.
    Language tag is empty string if no tag present.
    """
    blocks = []
    for m in re.finditer(r'```(\w+)?\n?(.*?)```', response, re.DOTALL):
        lang = m.group(1) or ""
        code = m.group(2).strip()
        if code:
            blocks.append((lang, code))
    return blocks


_EXT_MAP = {
    "python": ".py",
    "py": ".py",
    "bash": ".sh",
    "sh": ".sh",
    "markdown": ".md",
    "md": ".md",
    "yaml": ".yaml",
    "yml": ".yaml",
    "html": ".html",
    "json": ".json",
    "css": ".css",
}


def _infer_filename(lang: str, block: str, index: int) -> str:
    """Infer a filename from a code block's first line, or fall back to index-based name.

    Recognizes first lines like:
        # filename: foo.py
        # foo.sh
    Falls back to output_001.py, output_002.sh, etc., using language tag for extension.
    """
    # Check first 3 lines for filename comment
    for line in block.split("\n")[:3]:
        m = re.match(r'^#\s*filename:\s*(\S+\.\w+)\s*$', line)
        if m:
            return m.group(1)
        m = re.match(r'^#\s+(\S+\.\w+)\s*$', line)
        if m:
            return m.group(1)

    # Fall back to index-based name with language-derived extension
    ext = _EXT_MAP.get(lang.lower(), ".txt") if lang else ".txt"
    return f"output_{index:03d}{ext}"


def _get_expected_filename(task: dict) -> str | None:
    """Extract the expected output filename from task spec.

    Checks: expected_filename field (injected by pipeline), then searches
    context, notes, description, and acceptance_criteria for # filename: pattern.
    Returns the filename if found, None otherwise.
    """
    # Direct field (injected by pipeline.py from brief notes)
    if task.get("expected_filename"):
        return task["expected_filename"]
    # Search text fields
    for field in ("context", "notes", "description"):
        text = task.get(field, "") or ""
        m = re.search(r'#\s*filename:\s*(\S+\.\w+)', text)
        if m:
            return m.group(1)
    # Search acceptance_criteria list
    for criterion in task.get("acceptance_criteria", []):
        m = re.search(r'#\s*filename:\s*(\S+\.\w+)', str(criterion))
        if m:
            return m.group(1)
    return None


def _extract_and_write_code(task: dict, response: str) -> None:
    """Extract code from response and write to output_path.

    If task has expected_filename: concatenate ALL code blocks into that one file.
    Otherwise: use named blocks if available, fall back to largest block.
    """
    output_path = task.get("output_path")
    if not output_path:
        return

    all_blocks = _extract_python_code_blocks(response)
    expected = _get_expected_filename(task)

    # If we know the expected filename, concatenate everything into it
    if expected and output_path.endswith("/"):
        out_dir = Path(output_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        if all_blocks:
            combined = "\n\n".join(block for _, block in all_blocks)
            (out_dir / expected).write_text(combined + "\n")
            logger.info(f"Wrote {expected} to {out_dir} ({len(all_blocks)} blocks concatenated)")
        else:
            # No code blocks — write response body minus first line
            lines = response.split("\n", 1)
            body = lines[1] if len(lines) > 1 else response
            (out_dir / expected).write_text(body)
            logger.info(f"No code blocks — wrote response body as {expected}")
        return

    if not all_blocks:
        if "COMPLETE" in response and output_path:
            lines = response.split("\n", 1)
            body = lines[1] if len(lines) > 1 else ""
            out = Path(output_path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(body)
            logger.info(f"No code blocks — wrote response body to {out}")
        return

    # Separate named blocks from unnamed
    named_blocks = []
    unnamed_blocks = []
    for lang, block in all_blocks:
        first_lines = block.split("\n")[:3]
        is_named = any(re.match(r'^#\s*filename:\s*\S+', line) for line in first_lines)
        if is_named:
            named_blocks.append((lang, block))
        else:
            unnamed_blocks.append((lang, block))

    if named_blocks:
        blocks_to_write = named_blocks
    else:
        blocks_to_write = [(lang, block) for lang, block in unnamed_blocks if block.count("\n") >= 10]
        if not blocks_to_write and unnamed_blocks:
            blocks_to_write = [max(unnamed_blocks, key=lambda x: len(x[1]))]

    if not blocks_to_write:
        return

    if output_path.endswith("/"):
        out_dir = Path(output_path)
        out_dir.mkdir(parents=True, exist_ok=True)
        seen = set()
        for i, (lang, block) in enumerate(blocks_to_write, 1):
            fn = _infer_filename(lang, block, i)
            if fn in seen:
                base, ext = os.path.splitext(fn)
                fn = f"{base}_{i}{ext}"
            seen.add(fn)
            (out_dir / fn).write_text(block + "\n")
            logger.info(f"Wrote {fn} to {out_dir}")
    else:
        combined = "\n\n".join(block for _, block in blocks_to_write)
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(combined + "\n")
        logger.info(f"Wrote combined code to {out}")


def _write_output(task: dict, response: str) -> None:
    """Write Toni's full response to the task output directory."""
    client = anthropic.Anthropic()
    task_id = task.get("id", "unknown")
    output_dir = Path("output") / task_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "response.txt").write_text(response)

"""Toni — Software Architect Agent for Spectricom."""

import time
import anthropic

TONI_MODEL = "claude-sonnet-4-20250514"
TONI_MAX_TOKENS = 8192

TONI_SYSTEM_PROMPT = """You are Toni, the Software Architect Agent for the Spectricom platform.
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
- No OpenClaw. No NemoClaw. Direct API calls only."""


def call_toni(messages: list[dict], task_context: str) -> dict:
    """Call Toni agent with the given conversation history.

    Args:
        messages: Conversation history in Anthropic messages format.
        task_context: Task-specific context to prepend to the system prompt.

    Returns:
        Dict with keys: text, input_tokens, output_tokens, cost_usd
    """
    client = anthropic.Anthropic()

    system = f"{TONI_SYSTEM_PROMPT}\n\n--- TASK CONTEXT ---\n{task_context}"

    retries = 0
    delays = [5, 15, 45]

    while True:
        try:
            response = client.messages.create(
                model=TONI_MODEL,
                max_tokens=TONI_MAX_TOKENS,
                system=system,
                messages=messages,
            )

            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
            # Sonnet 4 pricing: $3/M input, $15/M output
            cost = (input_tokens * 3.0 + output_tokens * 15.0) / 1_000_000

            text = ""
            for block in response.content:
                if block.type == "text":
                    text += block.text

            return {
                "text": text,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "cost_usd": round(cost, 6),
            }

        except (anthropic.RateLimitError, anthropic.APIStatusError) as e:
            if retries >= len(delays):
                raise RuntimeError(f"API error after {retries} retries: {e}") from e
            time.sleep(delays[retries])
            retries += 1

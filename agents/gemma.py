"""Gemma — Chief of Staff AI for Spectricom."""

import time
import anthropic

GEMMA_MODEL = "claude-sonnet-4-20250514"
GEMMA_MAX_TOKENS = 1024

GEMMA_SYSTEM_PROMPT = """You are Gemma, Chief of Staff AI for the Spectricom platform.
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
- Engineering standard: Production-grade, no shortcuts"""


def call_gemma(question: str, task_context: str) -> dict:
    """Call Gemma agent to answer a question from Toni.

    Args:
        question: The question Toni asked.
        task_context: Task-specific context for informed answers.

    Returns:
        Dict with keys: text, input_tokens, output_tokens, cost_usd
    """
    client = anthropic.Anthropic()

    system = f"{GEMMA_SYSTEM_PROMPT}\n\n--- TASK CONTEXT ---\n{task_context}"

    messages = [
        {
            "role": "user",
            "content": f"Toni (coding agent) asks:\n\n{question}\n\nGive a direct, actionable answer.",
        }
    ]

    retries = 0
    delays = [5, 15, 45]

    while True:
        try:
            response = client.messages.create(
                model=GEMMA_MODEL,
                max_tokens=GEMMA_MAX_TOKENS,
                system=system,
                messages=messages,
            )

            input_tokens = response.usage.input_tokens
            output_tokens = response.usage.output_tokens
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

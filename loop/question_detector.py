"""Detects response type from Toni's output."""

import re

QUESTION_SIGNALS = ["QUESTION:", "BLOCKED:", "unclear", "which should", "should I", "do you want"]
COMPLETE_SIGNALS = ["COMPLETE:", "task complete", "all acceptance criteria met"]
BLOCKED_SIGNALS = ["BLOCKED:", "cannot proceed", "missing required"]


def detect_response_type(response: str) -> tuple[str, str | None]:
    """Detect whether Toni's response is a question, completion, blocker, or continuation.

    Checks explicit prefixes first, then falls back to signal phrase detection.

    Args:
        response: Toni's full text response.

    Returns:
        Tuple of (type, extracted_text) where type is one of:
        "question", "complete", "blocked", "continue"
    """
    # Check explicit prefixes first — these are authoritative
    question_match = re.search(r"QUESTION:\s*(.+?)(?:\n\n|\Z)", response, re.DOTALL)
    if question_match:
        return ("question", question_match.group(1).strip())

    complete_match = re.search(r"COMPLETE:\s*(.+?)(?:\n\n|\Z)", response, re.DOTALL)
    if complete_match:
        return ("complete", complete_match.group(1).strip())

    blocked_match = re.search(r"BLOCKED:\s*(.+?)(?:\n\n|\Z)", response, re.DOTALL)
    if blocked_match:
        return ("blocked", blocked_match.group(1).strip())

    # Fallback: check signal phrases (case-insensitive)
    response_lower = response.lower()

    for signal in BLOCKED_SIGNALS:
        if signal.lower() in response_lower:
            return ("blocked", _extract_around_signal(response, signal))

    for signal in COMPLETE_SIGNALS:
        if signal.lower() in response_lower:
            return ("complete", _extract_around_signal(response, signal))

    for signal in QUESTION_SIGNALS:
        if signal.lower() in response_lower:
            return ("question", _extract_around_signal(response, signal))

    return ("continue", None)


def _extract_around_signal(response: str, signal: str) -> str:
    """Extract text around a signal phrase for context."""
    idx = response.lower().find(signal.lower())
    if idx == -1:
        return response[:200]

    start = max(0, idx)
    end = min(len(response), idx + 300)
    return response[start:end].strip()

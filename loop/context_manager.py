"""Manages conversation history per task."""


class ConversationContext:
    """Tracks message history for a single task execution."""

    def __init__(self):
        self.messages: list[dict] = []

    def add_user_message(self, content: str) -> None:
        """Add a user-role message (task prompt or Gemma's answer injected)."""
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        """Add an assistant-role message (Toni's response)."""
        self.messages.append({"role": "assistant", "content": content})

    def get_messages(self) -> list[dict]:
        """Return the full conversation history."""
        return list(self.messages)

    def reset(self) -> None:
        """Clear conversation history (each task starts fresh)."""
        self.messages = []

"""Task queue manager — reads, parses, and tracks YAML task files."""

import os
from pathlib import Path

import yaml

TASKS_DIR = Path(__file__).parent / "tasks"


def load_tasks(task_id: str | None = None) -> list[dict]:
    """Load tasks from queue/tasks/*.yaml, sorted by priority.

    Args:
        task_id: If provided, load only this specific task.

    Returns:
        List of task dicts, sorted by priority (lower = higher priority).
    """
    tasks = []

    if not TASKS_DIR.exists():
        return tasks

    for yaml_file in sorted(TASKS_DIR.glob("*.yaml")):
        with open(yaml_file) as f:
            task = yaml.safe_load(f)

        if task is None:
            continue

        task["_file"] = str(yaml_file)

        if task_id and task.get("id") != task_id:
            continue

        tasks.append(task)

    tasks.sort(key=lambda t: t.get("priority", 999))
    return tasks


def get_pending_tasks(task_id: str | None = None) -> list[dict]:
    """Load only tasks with status 'pending'.

    Args:
        task_id: If provided, load only this specific task regardless of status.

    Returns:
        List of pending task dicts, sorted by priority.
    """
    tasks = load_tasks(task_id)

    if task_id:
        return tasks

    return [t for t in tasks if t.get("status") == "pending"]


def update_task_status(task: dict, status: str) -> None:
    """Update a task's status in its YAML file.

    Args:
        task: Task dict (must contain '_file' key).
        status: New status (pending, in_progress, complete, failed, blocked).
    """
    file_path = task["_file"]

    with open(file_path) as f:
        content = f.read()

    old_status = task.get("status", "pending")
    content = content.replace(f"status: {old_status}", f"status: {status}", 1)

    with open(file_path, "w") as f:
        f.write(content)

    task["status"] = status


def build_task_context(task: dict) -> str:
    """Build a context string from a task spec for agent system prompts.

    Args:
        task: Task dict from YAML.

    Returns:
        Formatted context string.
    """
    parts = [
        f"Task ID: {task.get('id', 'unknown')}",
        f"Title: {task.get('title', 'untitled')}",
    ]

    if task.get("context"):
        parts.append(f"\nContext:\n{task['context']}")

    if task.get("acceptance_criteria"):
        criteria = "\n".join(f"  - {c}" for c in task["acceptance_criteria"])
        parts.append(f"\nAcceptance Criteria:\n{criteria}")

    if task.get("decision_rules"):
        rules = "\n".join(f"  - {r}" for r in task["decision_rules"])
        parts.append(f"\nDecision Rules:\n{rules}")

    if task.get("do_not"):
        donts = "\n".join(f"  - {d}" for d in task["do_not"])
        parts.append(f"\nDo NOT:\n{donts}")

    if task.get("output_path"):
        parts.append(f"\nOutput Path: {task['output_path']}")

    return "\n".join(parts)

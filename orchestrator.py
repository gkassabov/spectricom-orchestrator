#!/usr/bin/env python3
"""Spectricom Multi-Agent Orchestrator — Main entry point.

Usage:
    python orchestrator.py                    # Run all pending tasks
    python orchestrator.py --task task-001    # Run specific task
    python orchestrator.py --dry-run          # Preview queue, don't execute
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from queue.task_manager import get_pending_tasks, load_tasks
from loop.executor import execute_task

console = Console()


def _get_logger(session_id=None):
    """Create a SessionLogger instance."""
    from session_logging.session_logger import SessionLogger
    return SessionLogger(session_id)


def print_queue(tasks: list[dict]) -> None:
    """Print task queue as a rich table."""
    table = Table(title="Task Queue")
    table.add_column("ID", style="cyan")
    table.add_column("Title", style="white")
    table.add_column("Status", style="yellow")
    table.add_column("Priority", style="green")
    table.add_column("Max Iterations", style="dim")

    for task in tasks:
        table.add_row(
            task.get("id", "?"),
            task.get("title", "untitled"),
            task.get("status", "?"),
            str(task.get("priority", "?")),
            str(task.get("max_iterations", "?")),
        )

    console.print(table)


def run(task_id: str | None = None, dry_run: bool = False) -> None:
    """Main orchestrator run."""
    load_dotenv()

    if dry_run:
        tasks = load_tasks(task_id)
        if not tasks:
            console.print("[yellow]No tasks found in queue/tasks/[/yellow]")
            return
        print_queue(tasks)
        console.print(f"\n[dim]{len(tasks)} task(s) loaded. Dry run — no execution.[/dim]")
        return

    tasks = get_pending_tasks(task_id)
    if not tasks:
        console.print("[yellow]No pending tasks found.[/yellow]")
        return

    console.print(f"\n[bold green]Starting orchestrator with {len(tasks)} task(s)[/bold green]\n")
    print_queue(tasks)

    logger = _get_logger()
    results = []

    try:
        for task in tasks:
            task_name = task.get("id", "unknown")
            console.print(f"\n[bold cyan]>>> Executing: {task_name} — {task.get('title', '')}[/bold cyan]")

            result = execute_task(task, logger)
            logger.record_task_result(result)
            results.append(result)

            status_style = {
                "complete": "bold green",
                "blocked": "bold yellow",
                "failed": "bold red",
            }.get(result["status"], "dim")

            console.print(
                f"[{status_style}]<<< {task_name}: {result['status'].upper()}[/{status_style}] "
                f"— {result['turns_used']} turns, {result['total_tokens']:,} tokens, "
                f"${result['cost_estimate']:.4f}"
            )

    except KeyboardInterrupt:
        console.print("\n[bold red]Interrupted! Saving partial report...[/bold red]")

    # Write session report
    report_path = logger.write_report()
    console.print(f"\n[bold]Session report: {report_path}[/bold]")
    console.print(f"[bold]JSON log: {logger.log_file}[/bold]")

    # Summary
    completed = sum(1 for r in results if r["status"] == "complete")
    blocked = sum(1 for r in results if r["status"] == "blocked")
    failed = sum(1 for r in results if r["status"] == "failed")
    total_cost = sum(r["cost_estimate"] for r in results)

    console.print(f"\n[bold]Results: {completed} complete, {blocked} blocked, {failed} failed[/bold]")
    console.print(f"[bold]Total estimated cost: ${total_cost:.4f}[/bold]")


def main():
    parser = argparse.ArgumentParser(description="Spectricom Multi-Agent Orchestrator")
    parser.add_argument("--task", type=str, help="Run a specific task by ID")
    parser.add_argument("--dry-run", action="store_true", help="Preview queue without executing")
    args = parser.parse_args()

    run(task_id=args.task, dry_run=args.dry_run)


if __name__ == "__main__":
    main()

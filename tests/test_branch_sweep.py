# filename: tests/test_branch_sweep.py
"""Tests for B3 — stale-branch sweep CLI (branches list / branches clean)."""

import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator


def _init_repo(path: Path):
    """Initialize a git repo with a commit on main."""
    subprocess.run("git init", shell=True, cwd=str(path), capture_output=True)
    subprocess.run(
        "git config user.email test@test.com",
        shell=True, cwd=str(path), capture_output=True,
    )
    subprocess.run(
        "git config user.name Test",
        shell=True, cwd=str(path), capture_output=True,
    )
    subprocess.run("git checkout -b main", shell=True, cwd=str(path), capture_output=True)
    (path / "README.md").write_text("init")
    subprocess.run("git add -A", shell=True, cwd=str(path), capture_output=True)
    subprocess.run('git commit -m "init"', shell=True, cwd=str(path), capture_output=True)


def _create_merged_branch(repo: Path, name: str):
    """Create a branch with a commit, then merge it to main."""
    subprocess.run(
        f"git checkout -b {name}",
        shell=True, cwd=str(repo), capture_output=True,
    )
    (repo / f"{name}.txt").write_text(f"content for {name}")
    subprocess.run("git add -A", shell=True, cwd=str(repo), capture_output=True)
    subprocess.run(
        f'git commit -m "commit on {name}"',
        shell=True, cwd=str(repo), capture_output=True,
    )
    subprocess.run("git checkout main", shell=True, cwd=str(repo), capture_output=True)
    subprocess.run(
        f"git merge {name} --no-edit",
        shell=True, cwd=str(repo), capture_output=True,
    )


def _create_unmerged_branch(repo: Path, name: str):
    """Create a branch with a commit, NOT merged to main."""
    subprocess.run(
        f"git checkout -b {name}",
        shell=True, cwd=str(repo), capture_output=True,
    )
    (repo / f"{name}.txt").write_text(f"content for {name}")
    subprocess.run("git add -A", shell=True, cwd=str(repo), capture_output=True)
    subprocess.run(
        f'git commit -m "commit on {name}"',
        shell=True, cwd=str(repo), capture_output=True,
    )
    subprocess.run("git checkout main", shell=True, cwd=str(repo), capture_output=True)


class TestListBranches:

    def test_list_finds_orch_pattern_branches(self):
        """list_branches returns only orch-* branches, not unrelated ones."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            _create_merged_branch(repo, "orch-foo")
            _create_unmerged_branch(repo, "orch-bar")
            _create_merged_branch(repo, "feat-baz")

            branches = orchestrator.list_branches(repo, "orch-*")
            names = [b[0] for b in branches]
            assert "orch-foo" in names
            assert "orch-bar" in names
            assert "feat-baz" not in names
            assert len(branches) == 2

    def test_list_marks_merged_correctly(self):
        """Merged branches are correctly identified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            _create_merged_branch(repo, "orch-merged")
            _create_unmerged_branch(repo, "orch-unmerged")

            branches = orchestrator.list_branches(repo, "orch-*")
            by_name = {b[0]: b for b in branches}
            assert by_name["orch-merged"][3] is True
            assert by_name["orch-unmerged"][3] is False


class TestCleanBranches:

    def test_clean_deletes_only_merged_by_default(self):
        """Without --force, only merged branches are deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            _create_merged_branch(repo, "orch-foo")
            _create_unmerged_branch(repo, "orch-bar")

            orchestrator.clean_branches(repo, "orch-*", force=False)

            r = subprocess.run(
                "git branch",
                shell=True, cwd=str(repo), capture_output=True, text=True,
            )
            assert "orch-foo" not in r.stdout
            assert "orch-bar" in r.stdout

    def test_clean_force_deletes_unmerged(self):
        """With --force, unmerged branches are also deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            _create_merged_branch(repo, "orch-foo")
            _create_unmerged_branch(repo, "orch-bar")

            orchestrator.clean_branches(repo, "orch-*", force=True)

            r = subprocess.run(
                "git branch",
                shell=True, cwd=str(repo), capture_output=True, text=True,
            )
            assert "orch-foo" not in r.stdout
            assert "orch-bar" not in r.stdout

    def test_clean_refuses_to_touch_protected_branches(self):
        """Protected branches (main, master, etc.) are never deleted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            _create_merged_branch(repo, "orch-foo")

            orchestrator.clean_branches(repo, "*", force=True)

            r = subprocess.run(
                "git branch",
                shell=True, cwd=str(repo), capture_output=True, text=True,
            )
            assert "main" in r.stdout

    def test_clean_refuses_to_touch_current_branch(self):
        """Currently checked-out branch is never deleted, even if merged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)
            _create_merged_branch(repo, "orch-foo")
            subprocess.run(
                "git checkout orch-foo",
                shell=True, cwd=str(repo), capture_output=True,
            )

            orchestrator.clean_branches(repo, "orch-*", force=True)

            r = subprocess.run(
                "git branch",
                shell=True, cwd=str(repo), capture_output=True, text=True,
            )
            assert "orch-foo" in r.stdout

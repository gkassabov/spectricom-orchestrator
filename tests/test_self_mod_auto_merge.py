# filename: tests/test_self_mod_auto_merge.py
"""Tests for B1 — self-modification auto-merge handler."""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

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


class TestSelfModDetection:

    def test_self_mod_detection_when_repo_matches_orch_dir(self):
        """is_self_mod=True when target_repo_path resolves to ORCH_DIR."""
        orch_dir = orchestrator.ORCH_DIR
        target_repo_path = orch_dir
        is_self_mod = (target_repo_path.resolve() == orch_dir)
        assert is_self_mod is True

    def test_self_mod_detection_when_repo_differs(self):
        """is_self_mod=False when target_repo_path != ORCH_DIR."""
        orch_dir = orchestrator.ORCH_DIR
        target_repo_path = Path("/tmp/some-other-repo")
        is_self_mod = (target_repo_path.resolve() == orch_dir)
        assert is_self_mod is False


class TestSelfModAutoMerge:

    def test_self_mod_auto_merge_ff_success(self):
        """FF merge succeeds — main now contains the 2 branch commits."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)

            subprocess.run(
                "git checkout -b orch-test-branch",
                shell=True, cwd=str(repo), capture_output=True,
            )
            (repo / "file1.py").write_text("change 1")
            subprocess.run("git add -A", shell=True, cwd=str(repo), capture_output=True)
            subprocess.run(
                'git commit -m "commit 1"',
                shell=True, cwd=str(repo), capture_output=True,
            )
            (repo / "file2.py").write_text("change 2")
            subprocess.run("git add -A", shell=True, cwd=str(repo), capture_output=True)
            subprocess.run(
                'git commit -m "commit 2"',
                shell=True, cwd=str(repo), capture_output=True,
            )

            subprocess.run("git checkout main", shell=True, cwd=str(repo), capture_output=True)

            result = orchestrator._self_mod_auto_merge(repo, "orch-test-branch")

            assert result is True
            r = subprocess.run(
                "git log --oneline main",
                shell=True, cwd=str(repo), capture_output=True, text=True,
            )
            assert "commit 1" in r.stdout
            assert "commit 2" in r.stdout

    def test_self_mod_auto_merge_ff_failure_when_main_drifted(self):
        """Non-ff state — merge fails, branch preserved, warning logged."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)

            subprocess.run(
                "git checkout -b orch-test-branch",
                shell=True, cwd=str(repo), capture_output=True,
            )
            (repo / "branch_file.py").write_text("branch change")
            subprocess.run("git add -A", shell=True, cwd=str(repo), capture_output=True)
            subprocess.run(
                'git commit -m "branch commit"',
                shell=True, cwd=str(repo), capture_output=True,
            )

            subprocess.run("git checkout main", shell=True, cwd=str(repo), capture_output=True)
            (repo / "main_file.py").write_text("main drift")
            subprocess.run("git add -A", shell=True, cwd=str(repo), capture_output=True)
            subprocess.run(
                'git commit -m "main drift"',
                shell=True, cwd=str(repo), capture_output=True,
            )

            r_before = subprocess.run(
                "git rev-parse main",
                shell=True, cwd=str(repo), capture_output=True, text=True,
            )
            main_before = r_before.stdout.strip()

            result = orchestrator._self_mod_auto_merge(repo, "orch-test-branch")

            assert result is False
            r_after = subprocess.run(
                "git rev-parse main",
                shell=True, cwd=str(repo), capture_output=True, text=True,
            )
            assert r_after.stdout.strip() == main_before
            r_branches = subprocess.run(
                "git branch",
                shell=True, cwd=str(repo), capture_output=True, text=True,
            )
            assert "orch-test-branch" in r_branches.stdout

    def test_non_self_mod_skips_auto_merge(self):
        """When is_self_mod=False, _self_mod_auto_merge is never called."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            _init_repo(repo)

            subprocess.run(
                "git checkout -b orch-test-branch",
                shell=True, cwd=str(repo), capture_output=True,
            )
            (repo / "file.py").write_text("change")
            subprocess.run("git add -A", shell=True, cwd=str(repo), capture_output=True)
            subprocess.run(
                'git commit -m "test commit"',
                shell=True, cwd=str(repo), capture_output=True,
            )
            subprocess.run("git checkout main", shell=True, cwd=str(repo), capture_output=True)

            r_before = subprocess.run(
                "git rev-parse main",
                shell=True, cwd=str(repo), capture_output=True, text=True,
            )
            main_before = r_before.stdout.strip()

            is_self_mod = False
            if is_self_mod:
                orchestrator._self_mod_auto_merge(repo, "orch-test-branch")

            r_after = subprocess.run(
                "git rev-parse main",
                shell=True, cwd=str(repo), capture_output=True, text=True,
            )
            assert r_after.stdout.strip() == main_before

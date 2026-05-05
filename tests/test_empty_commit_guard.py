# filename: tests/test_empty_commit_guard.py
"""Tests for OBS-S6S16-01 — conditional commit guard (no empty markers)."""

import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator


class TestEmptyCommitGuard:

    def test_result_no_changes_default_false(self):
        """Result.no_changes defaults to False."""
        r = orchestrator.Result(
            batch_file="test.md", status=orchestrator.Status.PASSED,
            started="", finished="", duration_s=0, exit_code=0, briefs=1,
        )
        assert r.no_changes is False

    def test_result_no_changes_serializes(self):
        """no_changes field round-trips through asdict."""
        r = orchestrator.Result(
            batch_file="test.md", status=orchestrator.Status.PASSED,
            started="", finished="", duration_s=0, exit_code=0, briefs=1,
            no_changes=True,
        )
        d = asdict(r)
        assert d["no_changes"] is True

    def test_notify_shows_no_changes_label(self, caplog):
        """notify() prints 'passed (no changes)' when no_changes=True."""
        r = orchestrator.Result(
            batch_file="test.md", status=orchestrator.Status.PASSED,
            started="", finished="", duration_s=10, exit_code=0, briefs=1,
            no_changes=True,
        )
        with caplog.at_level("INFO"):
            orchestrator.notify(r)
        assert "passed (no changes)" in caplog.text

    def test_notify_shows_passed_when_changes_exist(self, caplog):
        """notify() prints normal 'passed' when no_changes=False."""
        r = orchestrator.Result(
            batch_file="test.md", status=orchestrator.Status.PASSED,
            started="", finished="", duration_s=10, exit_code=0, briefs=1,
            no_changes=False,
        )
        with caplog.at_level("INFO"):
            orchestrator.notify(r)
        assert "passed" in caplog.text
        assert "no changes" not in caplog.text

    def test_git_diff_cached_quiet_detects_no_staged_changes(self, tmp_path):
        """git diff --cached --quiet returns 0 when nothing is staged."""
        subprocess.run("git init", shell=True, cwd=str(tmp_path), capture_output=True)
        subprocess.run("git commit --allow-empty -m init", shell=True, cwd=str(tmp_path), capture_output=True)
        r = subprocess.run(
            "git diff --cached --quiet",
            shell=True, capture_output=True, cwd=str(tmp_path),
        )
        assert r.returncode == 0

    def test_git_diff_cached_quiet_detects_staged_changes(self, tmp_path):
        """git diff --cached --quiet returns 1 when changes are staged."""
        subprocess.run("git init", shell=True, cwd=str(tmp_path), capture_output=True)
        subprocess.run("git commit --allow-empty -m init", shell=True, cwd=str(tmp_path), capture_output=True)
        (tmp_path / "file.txt").write_text("hello")
        subprocess.run("git add -A", shell=True, cwd=str(tmp_path), capture_output=True)
        r = subprocess.run(
            "git diff --cached --quiet",
            shell=True, capture_output=True, cwd=str(tmp_path),
        )
        assert r.returncode != 0

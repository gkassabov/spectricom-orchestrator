# filename: tests/test_running_marker.py
"""Tests for B2 — marker-file state/running.json watcher pattern."""

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator


class TestRunningMarker:

    def test_running_marker_written_with_correct_fields(self, tmp_path):
        """_write_running_marker creates state/running.json with expected keys."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            batch = tmp_path / "test-batch.md"
            batch.write_text("# test batch")
            orchestrator._write_running_marker(
                batch, "orchestrator", tmp_path,
                "orch-test-branch", None, False,
            )
            marker = tmp_path / "state" / "running.json"
            assert marker.exists()
            data = json.loads(marker.read_text())
            assert data["pid"] == os.getpid()
            assert data["batch_id"] == "test-batch"
            assert data["repo"] == "orchestrator"
            assert data["repo_path"] == str(tmp_path)
            assert data["branch"] == "orch-test-branch"
            assert "started_at" in data
            assert data["meta_fire_worktree"] is None
            assert data["is_self_mod"] is False

    def test_running_marker_cleared_on_success(self, tmp_path):
        """_clear_running_marker removes the marker file."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            marker_dir = tmp_path / "state"
            marker_dir.mkdir(parents=True, exist_ok=True)
            marker = marker_dir / "running.json"
            marker.write_text('{"pid": 1}')
            assert marker.exists()

            orchestrator._clear_running_marker()
            assert not marker.exists()

    def test_running_marker_cleared_on_exception(self, tmp_path):
        """Marker is cleaned up even when an exception occurs (try/finally semantics)."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            batch = tmp_path / "test-batch.md"
            batch.write_text("# test batch")
            orchestrator._write_running_marker(
                batch, "orchestrator", tmp_path,
                "orch-test-branch", None, False,
            )
            marker = tmp_path / "state" / "running.json"
            assert marker.exists()

            with pytest.raises(RuntimeError):
                try:
                    raise RuntimeError("simulated failure")
                finally:
                    orchestrator._clear_running_marker()

            assert not marker.exists()

    def test_stale_marker_detected_when_pid_dead(self, tmp_path):
        """Stale marker (dead PID) is auto-cleaned with warning."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            marker_dir = tmp_path / "state"
            marker_dir.mkdir(parents=True, exist_ok=True)
            marker = marker_dir / "running.json"
            marker.write_text(json.dumps({
                "pid": 99999,
                "batch_id": "old-batch",
                "started_at": "2026-01-01T00:00:00+00:00",
            }))

            result = orchestrator._check_stale_marker()
            assert result is True
            assert not marker.exists()

    def test_active_marker_blocks_concurrent_fire(self, tmp_path):
        """Active marker (own PID alive) blocks with exit 4."""
        with patch.object(orchestrator, "ORCH_DIR", tmp_path):
            marker_dir = tmp_path / "state"
            marker_dir.mkdir(parents=True, exist_ok=True)
            marker = marker_dir / "running.json"
            marker.write_text(json.dumps({
                "pid": os.getpid(),
                "batch_id": "active-batch",
                "started_at": "2026-05-02T12:00:00+00:00",
            }))

            with pytest.raises(SystemExit) as exc_info:
                orchestrator._check_stale_marker()
            assert exc_info.value.code == 4

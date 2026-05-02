"""Tests for A58a post-merge SIT integration."""
import json
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestRunSitPostMerge:
    """Tests for run_sit_post_merge function."""

    def _import_sit(self):
        """Import after sys.path is set."""
        import importlib
        # We need to mock set_active_repo and yaml since it runs on import
        with patch.dict('sys.modules', {'yaml': MagicMock()}):
            # Reimport with mocked deps if needed
            pass
        from orchestrator import run_sit_post_merge, SitOutcome, _log_sit_outcome, SKIP_SIT
        return run_sit_post_merge, SitOutcome, _log_sit_outcome

    @patch('subprocess.run')
    def test_sit_pass(self, mock_run):
        """SIT passes — returns passed=True, exit_code=0."""
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            archive_path = Path(tmpdir) / "archive"
            archive_path.mkdir()

            # Import the function
            import orchestrator
            orchestrator.SKIP_SIT = False
            outcome = orchestrator.run_sit_post_merge(repo_path, archive_path)

            assert outcome.passed is True
            assert outcome.exit_code == 0

    @patch('subprocess.run')
    def test_sit_fail(self, mock_run):
        """SIT fails — returns passed=False with exit code, does NOT raise."""
        mock_run.return_value = MagicMock(returncode=1, stdout='FAILED: 2 specs', stderr='')

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            archive_path = Path(tmpdir) / "archive"
            archive_path.mkdir()

            import orchestrator
            orchestrator.SKIP_SIT = False
            outcome = orchestrator.run_sit_post_merge(repo_path, archive_path)

            assert outcome.passed is False
            assert outcome.exit_code == 1

    @patch('subprocess.run')
    def test_sit_skip(self, mock_run):
        """--skip-sit flag causes immediate pass without running."""
        import orchestrator
        orchestrator.SKIP_SIT = True

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            outcome = orchestrator.run_sit_post_merge(repo_path)

            assert outcome.passed is True
            assert outcome.error == "skipped"
            mock_run.assert_not_called()

        orchestrator.SKIP_SIT = False

    @patch('subprocess.run')
    def test_sit_timeout(self, mock_run):
        """SIT timeout — returns failed with timeout error, does NOT raise."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='npm run sit:smoke', timeout=300)

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            archive_path = Path(tmpdir) / "archive"
            archive_path.mkdir()

            import orchestrator
            orchestrator.SKIP_SIT = False
            outcome = orchestrator.run_sit_post_merge(repo_path, archive_path)

            assert outcome.passed is False
            assert outcome.error == "timeout"


class TestSitLogOutcome:
    """Tests for _log_sit_outcome appending to orchestrator-sit-log.json."""

    def test_log_creates_file(self):
        """First log entry creates the file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir)
            import orchestrator
            orchestrator._log_sit_outcome(archive, Path("/tmp/repo"), True, 0, 12.5, None)

            log_file = archive / "orchestrator-sit-log.json"
            assert log_file.exists()
            entries = json.loads(log_file.read_text())
            assert len(entries) == 1
            assert entries[0]["passed"] is True
            assert entries[0]["duration_s"] == 12.5

    def test_log_appends(self):
        """Subsequent entries append to existing log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir)
            import orchestrator
            orchestrator._log_sit_outcome(archive, Path("/tmp/repo"), True, 0, 10.0, None)
            orchestrator._log_sit_outcome(archive, Path("/tmp/repo"), False, 1, 15.0, None, error="assertion")

            log_file = archive / "orchestrator-sit-log.json"
            entries = json.loads(log_file.read_text())
            assert len(entries) == 2
            assert entries[1]["passed"] is False
            assert entries[1]["error"] == "assertion"

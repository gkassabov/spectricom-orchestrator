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
        """A NEW CRITICAL spec failure blocks — passed=False, does NOT raise."""
        out = "  \u2718  1 [chromium] \u203a encounter-sign-finalization.spec.ts \u203a finalize\n"
        mock_run.return_value = MagicMock(returncode=1, stdout=out, stderr='')

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
        """SIT timeout is ADVISORY (not blocking) — passed=True, error='timeout-advisory'."""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd='npm run sit:smoke', timeout=300)

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            archive_path = Path(tmpdir) / "archive"
            archive_path.mkdir()

            import orchestrator
            orchestrator.SKIP_SIT = False
            outcome = orchestrator.run_sit_post_merge(repo_path, archive_path)

            assert outcome.passed is True
            assert outcome.error == "timeout-advisory"

    @patch('subprocess.run')
    def test_sit_noncritical_failures_block(self, mock_run):
        """Two non-critical spec failures on a non-zero exit -> blocks (passed=False).

        Rewritten under [ORCH-1] / 448e0c4: passed is exit-code based, so the old
        "under SIT_MANY_THRESHOLD -> advisory" rule no longer applies. The input shape
        (a few non-critical failures) is kept to pin that it now blocks.
        """
        out = ("  \u2718  1 [chromium] \u203a 02-patient-flow.spec.ts \u203a a\n"
               "  \u2718  2 [chromium] \u203a chart-tab-scroll.spec.ts \u203a b\n")
        mock_run.return_value = MagicMock(returncode=1, stdout=out, stderr='')
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
    def test_sit_many_noncritical_blocks(self, mock_run):
        """Three non-critical spec failures on a non-zero exit -> blocks (passed=False).

        Since [ORCH-1] / 448e0c4 this blocks because exit != 0, not because a count
        reached SIT_MANY_THRESHOLD (that threshold is no longer consulted). Kept for
        the multi-failure input shape.
        """
        out = ("  \u2718  1 [chromium] \u203a 02-patient-flow.spec.ts \u203a a\n"
               "  \u2718  2 [chromium] \u203a chart-tab-scroll.spec.ts \u203a b\n"
               "  \u2718  3 [chromium] \u203a inbox-data-flow.spec.ts \u203a c\n")
        mock_run.return_value = MagicMock(returncode=1, stdout=out, stderr='')
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            archive_path = Path(tmpdir) / "archive"
            archive_path.mkdir()
            import orchestrator
            orchestrator.SKIP_SIT = False
            outcome = orchestrator.run_sit_post_merge(repo_path, archive_path)
            assert outcome.passed is False

    @patch('subprocess.run')
    def test_sit_baseline_only_failures_block(self, mock_run):
        """Only a baseline (SIT_KNOWN_FAILING) spec fails, exit 1 -> blocks (passed=False).

        Rewritten under [ORCH-1] / 448e0c4: the vitest gate is exit-code based and no
        known-failing carve-out is applied, so a baseline-only failure still blocks.
        """
        out = "  \u2718  1 [chromium] \u203a home-count-parity.spec.ts \u203a a\n"
        mock_run.return_value = MagicMock(returncode=1, stdout=out, stderr='')
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
    def test_sit_unparseable_failure_blocks(self, mock_run):
        """exit!=0 with no parseable spec names -> blocks (passed=False).

        Rewritten under [ORCH-1] / 448e0c4: spec-name parsing is not consulted, so
        unparseable output cannot downgrade a real failure to advisory. This is the
        exact silent-pass mode the exit-code contract exists to prevent.
        """
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

    def test_log_sit_outcome_persists_error_excerpt(self):
        """error_excerpt is persisted in JSON when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir)
            import orchestrator
            orchestrator._log_sit_outcome(
                archive, Path("/tmp/repo"), False, 1, 0.7, None,
                error_excerpt="error: unknown option '--no-auto-spawn'"
            )

            log_file = archive / "orchestrator-sit-log.json"
            entries = json.loads(log_file.read_text())
            assert len(entries) == 1
            assert entries[0]["error_excerpt"] == "error: unknown option '--no-auto-spawn'"

    def test_log_sit_outcome_no_error_excerpt_when_passed(self):
        """error_excerpt field is absent when SIT passes and excerpt is None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir)
            import orchestrator
            orchestrator._log_sit_outcome(
                archive, Path("/tmp/repo"), True, 0, 5.0, None,
                error_excerpt=None
            )

            log_file = archive / "orchestrator-sit-log.json"
            entries = json.loads(log_file.read_text())
            assert len(entries) == 1
            assert "error_excerpt" not in entries[0]


class TestSitCmdNoAutoSpawn:
    """Guards against regression of the --no-auto-spawn flag bug (A63)."""

    @patch('subprocess.run')
    def test_sit_cmd_does_not_pass_no_auto_spawn_flag(self, mock_run):
        """sit_cmd must not contain --no-auto-spawn."""
        mock_run.return_value = MagicMock(returncode=0, stdout='', stderr='')

        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            archive_path = Path(tmpdir) / "archive"
            archive_path.mkdir()

            import orchestrator
            orchestrator.SKIP_SIT = False
            orchestrator.run_sit_post_merge(repo_path, archive_path)

            called_cmd = mock_run.call_args[0][0]
            assert "--no-auto-spawn" not in called_cmd

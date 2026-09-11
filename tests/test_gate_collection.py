"""S7-CORE-7 [ORCH-2] — a gate declares what it actually collected.

Fixture `tests/fixtures/sit_gate_vitest_7files_18tests.txt` is the raw stdout of a real
`npm run sit:gate` in clinical-mp (captured 2026-09-11, 7 test files / 18 tests, exit 0).
"""
import json
import logging
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402

FIXTURE = (Path(__file__).parent / "fixtures" / "sit_gate_vitest_7files_18tests.txt").read_text()
MIXED = " Test Files  2 failed | 5 passed (7)\n      Tests  3 failed | 15 passed (18)\n   Duration  6.6s\n"
ZERO = " RUN  v4.1.4 /repo\n\n Test Files  0 passed (0)\n      Tests  0 passed (0)\n   Duration  2.3s\n"


def _run_gate(stdout: str, returncode: int = 0):
    """Drive run_sit_post_merge with a mocked subprocess; returns the SitOutcome and archive dir."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=returncode, stdout=stdout, stderr="")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            archive_path = Path(tmpdir) / "archive"
            archive_path.mkdir()
            orchestrator.SKIP_SIT = False
            outcome = orchestrator.run_sit_post_merge(repo_path, archive_path)
            entries = json.loads((archive_path / "orchestrator-sit-log.json").read_text())
            assert mock_run.call_count == 1, "AC-O2-10: the gate must run exactly once — no second invocation"
    return outcome, entries


class TestParseVitestSummary:
    """§4.1 — parse the summary already in hand; never fabricate 0."""

    def test_real_fixture_parses_7_files_18_tests(self):
        """AC-O2-01: captured sit:gate output → 7/7 test files, 18/18 tests."""
        c = orchestrator._parse_vitest_summary(FIXTURE)
        assert c == {"test_files_total": 7, "test_files_passed": 7, "tests_total": 18, "tests_passed": 18}

    def test_real_fixture_with_ansi_colour(self):
        """AC-O2-01: the same summary wrapped in vitest's TTY colour codes still parses."""
        coloured = FIXTURE.replace("Test Files", "\x1b[2mTest Files\x1b[22m") \
                          .replace("7 passed", "\x1b[1;32m7 passed\x1b[0m") \
                          .replace("18 passed", "\x1b[1;32m18 passed\x1b[0m")
        c = orchestrator._parse_vitest_summary(coloured)
        assert (c["test_files_passed"], c["test_files_total"], c["tests_passed"], c["tests_total"]) == (7, 7, 18, 18)

    def test_mixed_failed_passed_summary(self):
        """AC-O2-02: `2 failed | 5 passed (7)` → passed=5, total=7 (and 15/18 tests)."""
        c = orchestrator._parse_vitest_summary(MIXED)
        assert c == {"test_files_total": 7, "test_files_passed": 5, "tests_total": 18, "tests_passed": 15}

    def test_no_summary_is_none_never_zero(self):
        """AC-O2-03: no summary lines → all four None. A 0 here would false-trip §4.5."""
        for raw in ("", "FAILED: 2 specs", "npm ERR! missing script: sit:gate"):
            c = orchestrator._parse_vitest_summary(raw)
            assert all(v is None for v in c.values()), raw
            assert 0 not in c.values(), raw

    def test_explicit_no_test_files_is_zero(self):
        """vitest's explicit empty run (`No test files found, exiting with code 0`) is a real 0."""
        c = orchestrator._parse_vitest_summary("No test files found, exiting with code 0\n")
        assert c["test_files_total"] == 0 and c["tests_total"] == 0


class TestGateCollectionReport:
    """§4.3–§4.6 — the gate says what it collected, blocks on nothing, warns on thin."""

    def test_pass_logs_counts_and_persists_them(self, caplog):
        """AC-O2-01 / AC-O2-04 (negative) / AC-O2-05: real output → PASS with counts, logged + persisted."""
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, entries = _run_gate(FIXTURE)
        assert outcome.passed is True and outcome.error is None
        assert (outcome.test_files_passed, outcome.test_files_total, outcome.tests_passed, outcome.tests_total) == (7, 7, 18, 18)
        assert "🧪 SIT gate: PASS — collected 7 test files / 18 tests in " in caplog.text
        assert "✅ SIT gate PASSED" not in caplog.text and "✅ SIT PASSED" not in caplog.text
        assert entries[-1]["test_files_total"] == 7 and entries[-1]["test_files_passed"] == 7
        assert entries[-1]["tests_total"] == 18 and entries[-1]["tests_passed"] == 18
        assert outcome.collection.startswith("7 files/18 tests, ")

    def test_unparseable_logs_collection_unknown_and_still_passes(self, caplog):
        """AC-O2-03: exit 0 with no summary → PASS, counts None (not 0), `collection unknown` logged."""
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, entries = _run_gate("")
        assert outcome.passed is True
        assert outcome.error != "zero-collection"
        for f in ("test_files_total", "test_files_passed", "tests_total", "tests_passed"):
            assert getattr(outcome, f) is None
            assert entries[-1][f] is None
        assert "SIT gate: PASS — collection unknown (summary not parsed) in " in caplog.text
        assert outcome.collection is None

    def test_zero_collection_exit_0_blocks_as_environment(self, caplog):
        """AC-O2-04: exit 0 + `Test Files 0 passed (0)` → not a pass; run_pre_merge_gates → BLOCKED(environment)."""
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, entries = _run_gate(ZERO, returncode=0)
        assert outcome.passed is False
        assert outcome.error == "zero-collection"
        assert outcome.test_files_total == 0 and outcome.tests_total == 0
        assert "⛔ SIT gate collected NOTHING — treating as BLOCKED(environment), not PASS" in caplog.text
        assert entries[-1]["passed"] is False and entries[-1]["error"] == "zero-collection"

        with patch.dict(orchestrator.PRE_MERGE_GATES, {orchestrator.ACTIVE_REPO_NAME: {"gates": ["sit"]}}), \
             patch.object(orchestrator, "run_sit_post_merge", return_value=outcome), \
             patch.object(orchestrator, "SIT_BLOCKING", True):
            verdict = orchestrator.run_pre_merge_gates(Path("/tmp/repo"), "route-branch")
        assert verdict.outcome is orchestrator.GateOutcome.BLOCKED_ENV
        assert verdict.outcome is not orchestrator.GateOutcome.FAIL_PRODUCT
        assert (verdict.gate, verdict.signal) == ("sit", "zero-collection")
        assert verdict.collection.startswith("0 files/0 tests, ")

    def test_red_exit_reports_counts_and_blocks(self, caplog):
        """A red gate still says what it collected; the stale 'advisory' wording is gone (AC-O2-08)."""
        with caplog.at_level(logging.INFO, logger="orch"):
            outcome, _ = _run_gate(MIXED, returncode=1)
        assert outcome.passed is False
        assert (outcome.tests_passed, outcome.tests_total) == (15, 18)
        assert "collected 7 test files / 18 tests (15 passed)" in caplog.text
        assert "advisory only, not blocking merge" not in caplog.text
        assert "BLOCKING merge" in caplog.text

    def test_floor_unset_no_warning(self, caplog):
        """AC-O2-07: SIT_MIN_TEST_FILES unset ⇒ no floor warning."""
        with patch.object(orchestrator, "SIT_MIN_TEST_FILES", None), caplog.at_level(logging.INFO, logger="orch"):
            outcome, _ = _run_gate(FIXTURE)
        assert outcome.passed is True
        assert "SIT gate thin" not in caplog.text

    def test_floor_above_collected_warns_once_still_passing(self, caplog):
        """AC-O2-07: floor 10 over 7 files ⇒ exactly one warning, still PASS."""
        with patch.object(orchestrator, "SIT_MIN_TEST_FILES", 10), caplog.at_level(logging.INFO, logger="orch"):
            outcome, _ = _run_gate(FIXTURE)
        assert outcome.passed is True
        assert caplog.text.count("⚠️  SIT gate thin: 7 test files (floor 10)") == 1

    def test_floor_does_not_warn_when_counts_unknown(self, caplog):
        """Floor set but summary unparsed ⇒ nothing to compare, no warning, no false 0."""
        with patch.object(orchestrator, "SIT_MIN_TEST_FILES", 10), caplog.at_level(logging.INFO, logger="orch"):
            outcome, _ = _run_gate("")
        assert outcome.passed is True and "SIT gate thin" not in caplog.text


class TestSitLogBackwardsCompatible:
    """AC-O2-05 — old-shape entries still load; new entries carry the four counts."""

    def test_old_shape_log_loads_and_new_entry_has_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir)
            log_file = archive / "orchestrator-sit-log.json"
            old = [{"timestamp": "2026-09-01T00:00:00", "repo": "/r", "passed": True, "exit_code": 0,
                    "duration_s": 2.3, "report_path": None, "error": None}]
            log_file.write_text(json.dumps(old))
            orchestrator._log_sit_outcome(archive, Path("/r"), True, 0, 6.6, None,
                                          test_files_total=7, test_files_passed=7, tests_total=18, tests_passed=18)
            entries = json.loads(log_file.read_text())
        assert len(entries) == 2
        assert "test_files_total" not in entries[0]  # old shape untouched
        assert {k: entries[1][k] for k in ("test_files_total", "test_files_passed", "tests_total", "tests_passed")} == \
               {"test_files_total": 7, "test_files_passed": 7, "tests_total": 18, "tests_passed": 18}

    def test_positional_legacy_call_still_works(self):
        """Existing call sites (positional, no counts) keep working; counts persist as null."""
        with tempfile.TemporaryDirectory() as tmpdir:
            archive = Path(tmpdir)
            orchestrator._log_sit_outcome(archive, Path("/r"), True, 0, 1.0, None)
            entries = json.loads((archive / "orchestrator-sit-log.json").read_text())
        assert entries[0]["tests_total"] is None and entries[0]["test_files_total"] is None


class TestFinalStatusRendering:
    """AC-O2-06 — FINAL STATUS and the batch summary carry the counts when known."""

    def test_label_with_counts(self):
        assert orchestrator._gate_status_label(None, "PASS", "7 files/18 tests, 6.6s") == "PASS (7 files/18 tests, 6.6s)"

    def test_label_falls_back_when_unknown(self):
        assert orchestrator._gate_status_label(None, "PASS", None) == "PASS"
        assert orchestrator._gate_status_label(None, None, None) == "not run"
        assert orchestrator._gate_status_label("FAIL(product) — sit: exit 1", "FAIL(product)", None) == "FAIL(product) — sit: exit 1"

    def test_verdict_carries_collection_on_pass(self):
        so = orchestrator.SitOutcome(passed=True, exit_code=0, duration_s=6.6,
                                     test_files_total=7, test_files_passed=7, tests_total=18, tests_passed=18)
        with patch.dict(orchestrator.PRE_MERGE_GATES, {orchestrator.ACTIVE_REPO_NAME: {"gates": ["sit"]}}), \
             patch.object(orchestrator, "run_sit_post_merge", return_value=so):
            verdict = orchestrator.run_pre_merge_gates(Path("/tmp/repo"), "route-branch")
        assert verdict.outcome is orchestrator.GateOutcome.PASS
        assert verdict.collection == "7 files/18 tests, 6.6s"
        assert orchestrator._gate_status_label(None, verdict.outcome.value, verdict.collection) == "PASS (7 files/18 tests, 6.6s)"

    def test_batch_summary_line_carries_counts(self, caplog):
        r = orchestrator.Result(batch_file="b.md", status=orchestrator.Status.PASSED, started="", finished="",
                                duration_s=10.0, exit_code=0, briefs=1, gate_outcome="PASS",
                                gate_collection="7 files/18 tests, 6.6s")
        with patch.object(orchestrator, "HAS_SLACK", False), caplog.at_level(logging.INFO, logger="orch"):
            orchestrator.notify(r)
        assert "| gate: PASS (7 files/18 tests, 6.6s)" in caplog.text


class TestSourceGuards:
    """AC-O2-08 / AC-O2-10 — grep-level guards on orchestrator.py itself."""

    SRC = (Path(__file__).parent.parent / "orchestrator.py").read_text()

    def test_stale_advisory_wording_gone(self):
        assert self.SRC.count("advisory only, not blocking merge") == 0

    def test_gate_command_count_unchanged(self):
        """Recon on 63ed4f8: two occurrences (one comment, one sit_cmd). No second invocation added."""
        assert self.SRC.count("npm run sit:gate") == 2

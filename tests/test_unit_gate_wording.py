"""[ORCH-UNIT-GATE-WORDING-1] Kanban 660, L-384 — the unit gate's PASS line says above / equal to / below truthfully.

The flaky-PASS detail said `below` for a branch count higher than the baseline's (6 vs 3 on 2026-11-10); with a
related-files baseline (whose count is files, not tests) it compared counts anyway; a derived count was not marked.
Words only: verdicts, signals and flaky sets are unchanged. Predicates P-D1..P-D4 of
briefs/652-660-orch-prefire-bundle-1.md Part D; driven like tests/test_unit_baseline_gate.py's
TestCountIsEvidenceNotAVerdict, with its helpers.
"""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_unit_baseline_gate import A, B, C, active, confirm_fake, repo, run_gate, vitest  # noqa: E402,F401


def gate(repo, tmp_path, branch_out, baseline_out, confirm_out):
    archive = tmp_path / "archive"
    with active(archive=archive), patch.object(orchestrator, "_run_unit_suite",
                                               confirm_fake(branch_out, baseline_out, confirm_out=confirm_out)):
        return orchestrator.run_unit_gate(repo, "route", archive_path=archive)


# ── P-D1 · a higher count reads `above`, never `below` ──────────────────────
def test_PD1_six_against_three_with_both_new_files_flaky_reads_above(repo, tmp_path):
    o = gate(repo, tmp_path, vitest([B, C, A, A, A, A], failed=6, total_tests=20, total_files=8),
             vitest([A, A, A], failed=3, total_tests=20, total_files=8),
             vitest(failed=0, total_tests=2, total_files=2))
    assert o.passed is True and o.signal is None and o.flaky_files == tuple(sorted((B, C)))
    assert "6 failures, above the merge-base baseline of 3 — newly-failing file(s) confirmed FLAKY" in o.detail
    assert "below" not in o.detail


# ── P-D2 · controls: equal and below read as today ─────────────────────────
def test_PD2_control_equal_and_below_as_today(repo, tmp_path):
    o, _ = run_gate(repo, tmp_path, branch_out=vitest([A, A], failed=2), baseline_out=vitest([A, A], failed=2))
    assert "2 failures, equal to the merge-base baseline of 2" in o.detail
    o, _ = run_gate(repo, tmp_path, branch_out=vitest([A], failed=1), baseline_out=vitest([A, A], failed=2))
    assert "1 failures, below the merge-base baseline of 2" in o.detail


def test_PD2_control_the_word_follows_the_counts():
    assert [orchestrator._count_word(b, 3) for b in (2, 3, 4)] == ["below", "equal to", "above"]


# ── P-D3 · a related-files baseline compares no counts, flaky or not ───────
def test_PD3_a_related_files_baseline_states_no_count_comparison(repo, tmp_path):
    base = orchestrator.UnitSuiteRun(ref="merge-base x (restricted)", exit_code=1, duration_s=0.0, runner="vitest",
                                     failures=1, failing_files=(A,), failures_source="derived",
                                     count_comparable=False)
    with patch.object(orchestrator, "_unit_baseline_measure_or_reuse", lambda *a, **k: (base, "cache", "a note")):
        o = gate(repo, tmp_path, vitest([A, B], failed=5, total_tests=20, total_files=8), None,
                 vitest(failed=0, total_tests=1, total_files=1))
    assert o.passed is True and o.flaky_files == (B,)
    assert "counts not compared" in o.detail and "baseline of" not in o.detail
    assert o.detail == ("5 failure(s) on the related files — newly-failing file(s) confirmed FLAKY in isolation "
                        f"(passed alone, not blocking): {B} (baseline cache: 1 failing related file(s); counts not "
                        "compared)")


# ── P-D4 · a derived count says so ──────────────────────────────────────────
def test_PD4_a_derived_branch_count_is_marked(repo, tmp_path):
    o, _ = run_gate(repo, tmp_path, branch_out=vitest([A], failed=0, total_tests=18),
                    baseline_out=vitest([A], failed=1))
    assert o.branch.failures_source == "derived"
    assert "0 (derived) failures, below the merge-base baseline of 1" in o.detail

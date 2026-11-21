# filename: tests/test_sit_batch_timeout_continues.py
"""SIT-BATCH-TIMEOUT-CONTINUES-1 (Kanban 805; 804's open item) — one SIT batch over its budget no longer ends the leg:
the other batches run, the timed-out batch is said by name (its files), and the reconciliation is against the files
that were not in it. 11-20 and 11-21: batch 1 timed out and batches 2-23 of clinical-mp's nightly SIT never ran.

  T-1 (RED)     batch 1 of 3 times out → batches 2 and 3 still run (3 legs started)
  T-2 (RED)     … the aggregate names batch 1 and its files; no mismatch (the reconciliation leaves its files out)
  T-3 (RED)     run_sit_post_merge: the other batches green → timeout-advisory (passed, as before) WITH a detail naming
                batch 1's files and the other batches' collection
  T-4 (RED)     batch 1 times out, batch 2 is red → the aggregate is red (exit 1) and still names batch 1
  T-5 (control) no timeout → unchanged: every batch runs, no timed_out, no mismatch
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator

FILES = ["sit/a.test.ts", "sit/b.test.ts", "sit/c.test.ts", "sit/d.test.ts", "sit/e.test.ts"]
GREEN = lambda n: f" Test Files  {n} passed ({n})\n      Tests  {n} passed ({n})\n"


def _plan():
    p = orchestrator.SitPlan(files=list(FILES), tests_expected=5, batch_files=2, pause_s=0,
                             tests_per_file={f: 1 for f in FILES})
    return p


def _fake(monkeypatch, behaviour):
    """behaviour: batch index (1-based) → 'timeout' | 'green' | 'red'."""
    calls = []

    def _leg(kind, archive, cmd, *, files=None, **kw):
        calls.append(cmd)
        i = len(calls)
        what = behaviour.get(i, "green")
        if what == "timeout":
            raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
        if what == "red":
            out = (f" FAIL  sit/c.test.ts > t\n Test Files  1 failed | {files - 1} passed ({files})\n"
                   f"      Tests  1 failed | {files - 1} passed ({files})\n")
            return subprocess.CompletedProcess(cmd, 1, stdout=out, stderr=""), None
        return subprocess.CompletedProcess(cmd, 0, stdout=GREEN(files), stderr=""), None

    monkeypatch.setattr(orchestrator, "_run_leg", _leg)
    return calls


def test_t1_t2_other_batches_run_and_the_timeout_is_named(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, {1: "timeout"})
    b = orchestrator._run_sit_batched("npx vitest run --config sit.config.ts", tmp_path, _plan(), archive=tmp_path)
    said = [t["said"] for t in getattr(b, "timed_out", [])]
    print(f"[T-1] legs started {len(calls)} · [T-2] timed out {said} · mismatch {b.mismatch!r} · counts {b.counts}")
    assert len(calls) == 3
    assert len(said) == 1 and "batch 1/3" in said[0] and "sit/a.test.ts" in said[0] and "sit/b.test.ts" in said[0]
    assert b.mismatch is None
    assert b.returncode == 0 and b.counts["test_files_total"] == 3


def test_t3_post_merge_advisory_says_what_timed_out(monkeypatch, tmp_path):
    _fake(monkeypatch, {1: "timeout"})
    monkeypatch.setattr(orchestrator, "SKIP_SIT", False)
    monkeypatch.setattr(orchestrator, "_sit_plan", lambda repo_path, files_only=False: _plan())
    so = orchestrator.run_sit_post_merge(tmp_path, archive_path=tmp_path)
    print(f"[T-3] passed {so.passed} · error {so.error!r} · detail {so.detail!r}")
    assert so.passed is True and so.error == "timeout-advisory"
    assert so.detail is not None and "sit/a.test.ts" in so.detail and "3 test files" in so.detail


def test_t4_a_red_batch_beside_the_timeout_is_red(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, {1: "timeout", 2: "red"})
    b = orchestrator._run_sit_batched("npx vitest run --config sit.config.ts", tmp_path, _plan(), archive=tmp_path)
    print(f"[T-4] legs {len(calls)} · rc {b.returncode} · timed out {len(getattr(b, 'timed_out', []))} · named {list(b.named)}")
    assert len(calls) == 3 and b.returncode == 1
    assert len(b.timed_out) == 1


def test_t5_control_no_timeout_unchanged(monkeypatch, tmp_path):
    calls = _fake(monkeypatch, {})
    b = orchestrator._run_sit_batched("npx vitest run --config sit.config.ts", tmp_path, _plan(), archive=tmp_path)
    assert len(calls) == 3 and b.returncode == 0 and b.mismatch is None
    assert getattr(b, "timed_out", []) == []
    assert b.counts["test_files_total"] == 5

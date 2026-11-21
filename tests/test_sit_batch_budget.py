# filename: tests/test_sit_batch_budget.py
"""SIT-BATCH-BUDGET-1 (Kanban 804) — one SIT batch's budget is a per-repo key (`sit_batch_timeout_s`, default
SIT_TIMEOUT), read into the SitPlan and handed to each batch's subprocess; clinical-mp sets 1200.

  B-1 (RED)     a repo with sit_batch_timeout_s 1200 → every batch runs with timeout=1200
  B-2 (control) the key absent → SIT_TIMEOUT, as before
  B-3 (control) a value that is not a positive integer → SIT_TIMEOUT, loudly
  B-4 (RED)     config/repos.yaml: clinical-mp declares sit_batch_timeout_s 1200
"""
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator

KEY = getattr(orchestrator, "SIT_BATCH_TIMEOUT_KEY", "sit_batch_timeout_s")


def _plan(monkeypatch, tmp_path, cfg: dict):
    """The real _sit_plan, its list command answered by a stub listing (three files, batches of two)."""
    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG", {"sit_list_cmd": "npx vitest list", "sit_batch_files": 2, "sit_batch_pause_s": 0, **cfg})
    listing = "sit/a.test.ts > t1\nsit/b.test.ts > t2\nsit/c.test.ts > t3\n"
    with monkeypatch.context() as m:
        m.setattr(orchestrator.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=listing, stderr=""))
        plan = orchestrator._sit_plan(tmp_path)
    assert plan is not None and plan.error is None and len(plan.batches) == 2, plan
    return plan


def _run(monkeypatch, tmp_path, cfg: dict) -> list:
    seen = []

    def _leg(kind, archive, cmd, *, files=None, **kw):
        seen.append(kw.get("timeout"))
        return subprocess.CompletedProcess(cmd, 0, stdout=" Test Files  2 passed (2)\n      Tests  2 passed (2)\n", stderr=""), None

    monkeypatch.setattr(orchestrator, "_run_leg", _leg)
    plan = _plan(monkeypatch, tmp_path, cfg)
    orchestrator._run_sit_batched("npx vitest run", tmp_path, plan, archive=tmp_path)
    return seen


def test_b1_repo_budget_reaches_every_batch(monkeypatch, tmp_path):
    seen = _run(monkeypatch, tmp_path, {KEY: 1200})
    print(f"[B-1] batch timeouts {seen}")
    assert seen == [1200, 1200]


def test_b2_absent_key_keeps_the_default(monkeypatch, tmp_path):
    assert _run(monkeypatch, tmp_path, {}) == [orchestrator.SIT_TIMEOUT] * 2


def test_b3_bad_value_falls_back_loudly(monkeypatch, tmp_path, caplog):
    with caplog.at_level("WARNING"):
        seen = _run(monkeypatch, tmp_path, {KEY: "lots"})
    assert seen == [orchestrator.SIT_TIMEOUT] * 2
    assert KEY in caplog.text


def test_b4_clinical_mp_declares_1200():
    repos = yaml.safe_load((Path(orchestrator.__file__).parent / "config" / "repos.yaml").read_text())
    entries = repos.get("repos", repos) if isinstance(repos, dict) else {}
    cmp = entries.get("clinical-mp") if isinstance(entries, dict) else None
    print(f"[B-4] clinical-mp {KEY} = {None if cmp is None else cmp.get(KEY)!r}")
    assert cmp is not None and cmp.get(KEY) == 1200

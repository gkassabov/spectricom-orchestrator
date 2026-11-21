# filename: tests/test_qstat_full_gate_truth.py
"""QSTAT-FULL-GATE-TRUTH-1 (Kanban 808; SCA-ORCH-QSTAT-STALE-PASS-1 + SCA-ORCH-QSTAT-UNREADABLE-NEVERRUN-1) — qstat's
FULL-GATE lines say what they know: an unreadable state file is said (not "never run"), and a nightly repo's last result
older than STALE_AFTER_H hours carries a STALE line under it (the result line itself unchanged, test_gate_cost pins it).

  Q-1 (RED)     an unreadable full-gate-clinical-mp.json → "unreadable", never "never run"
  Q-2 (RED)     a nightly repo's PASS finished 3 days before now → its line, then "⚠️ STALE"
  Q-3 (control) a PASS finished an hour ago → no STALE line
  Q-4 (control) a repo with no nightly schedule → never STALE, however old
"""
import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


def _orch(tmp_path, repos: dict) -> Path:
    orch = tmp_path / "spectricom-orchestrator"
    (orch / "state").mkdir(parents=True)
    (orch / "queue").mkdir()
    (orch / "config").mkdir()
    (orch / "config" / "repos.yaml").write_text(yaml.safe_dump({"repos": repos}))
    (orch / "queue-state.json").write_text(json.dumps({"daemon_status": "running", "pid": os.getpid()}))
    return orch


def _gate(orch: Path, repo: str, finished: datetime) -> None:
    (orch / "state" / f"full-gate-{repo}.json").write_text(json.dumps({
        "repo": repo, "outcome": "PASS", "finished_at": finished.isoformat(timespec="seconds"), "sha": "a1b2c3d4e5f6",
        "trigger": "nightly"}))


def _qstat(tmp_path) -> str:
    r = subprocess.run(["bash", str(ROOT / "qstat.sh")], capture_output=True, text=True, timeout=60,
                       env={**os.environ, "HOME": str(tmp_path)})
    return r.stdout + r.stderr


def _gate_lines(out: str) -> list:
    return [l for l in out.splitlines() if "FULL-GATE" in l or "STALE" in l]


def test_q1_unreadable_is_said(tmp_path):
    orch = _orch(tmp_path, {"clinical-mp": {"full_gate_nightly": "02:30"}})
    (orch / "state" / "full-gate-clinical-mp.json").write_text("{not json")
    lines = _gate_lines(_qstat(tmp_path))
    print(f"[Q-1] {lines}")
    assert any("clinical-mp" in l and "unreadable" in l for l in lines), lines
    assert not any("never run" in l for l in lines), lines


def test_q2_old_nightly_pass_is_stale(tmp_path):
    orch = _orch(tmp_path, {"clinical-mp": {"full_gate_nightly": "02:30"}})
    _gate(orch, "clinical-mp", datetime.now() - timedelta(days=3))
    lines = _gate_lines(_qstat(tmp_path))
    print(f"[Q-2] {lines}")
    i = next(i for i, l in enumerate(lines) if "FULL-GATE clinical-mp | ✅ PASS" in l)
    assert i + 1 < len(lines) and "STALE" in lines[i + 1] and "clinical-mp" in lines[i + 1], lines


def test_q3_fresh_pass_is_not_stale(tmp_path):
    orch = _orch(tmp_path, {"clinical-mp": {"full_gate_nightly": "02:30"}})
    _gate(orch, "clinical-mp", datetime.now() - timedelta(hours=1))
    assert not any("STALE" in l for l in _gate_lines(_qstat(tmp_path)))


def test_q4_unscheduled_repo_never_stale(tmp_path):
    orch = _orch(tmp_path, {"orchestrator": {}})
    _gate(orch, "orchestrator", datetime.now() - timedelta(days=30))
    assert not any("STALE" in l for l in _gate_lines(_qstat(tmp_path)))

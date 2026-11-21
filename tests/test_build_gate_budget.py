# filename: tests/test_build_gate_budget.py
"""BUILD-GATE-BUDGET-1 (S7-CORE-59) — the build gate's budget is a per-repo key (`build_timeout_s`, default
BUILD_GATE_TIMEOUT), read by run_build_gate and named in the timeout verdict; clinical-mp sets 1200.

  BT-1 (RED)     a repo with build_timeout_s 1200 → the build leg runs with timeout=1200
  BT-2 (control) the key absent → BUILD_GATE_TIMEOUT (600), as before
  BT-3 (control) a value that is not a positive integer → BUILD_GATE_TIMEOUT, loudly
  BT-4 (RED)     config/repos.yaml: clinical-mp declares build_timeout_s 1200; orchestrator and yorsie do not
  BT-5 (RED)     the timeout verdict text names the repo's budget, not the module default
"""
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator

KEY = getattr(orchestrator, "BUILD_GATE_TIMEOUT_KEY", "build_timeout_s")


def _leg_timeout(monkeypatch, tmp_path, cfg: dict):
    seen = []

    def _leg(kind, archive, cmd, **kw):
        seen.append((kind, kw.get("timeout")))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""), None

    monkeypatch.setattr(orchestrator, "ACTIVE_REPO_CONFIG", dict(cfg))
    monkeypatch.setattr(orchestrator, "_run_leg", _leg)
    out = orchestrator.run_build_gate(tmp_path)
    assert out.passed, out
    return seen


def test_bt1_repo_budget_reaches_the_build_leg(monkeypatch, tmp_path):
    seen = _leg_timeout(monkeypatch, tmp_path, {KEY: 1200})
    print(f"[BT-1] build leg {seen}")
    assert seen == [("build", 1200)]


def test_bt2_absent_key_keeps_the_default(monkeypatch, tmp_path):
    seen = _leg_timeout(monkeypatch, tmp_path, {})
    print(f"[BT-2] build leg {seen}")
    assert seen == [("build", orchestrator.BUILD_GATE_TIMEOUT)] == [("build", 600)]


def test_bt3_bad_value_keeps_the_default_loudly(monkeypatch, tmp_path, caplog):
    seen = _leg_timeout(monkeypatch, tmp_path, {KEY: "twenty minutes"})
    print(f"[BT-3] build leg {seen} · warned {any(KEY in r.getMessage() for r in caplog.records)}")
    assert seen == [("build", 600)]
    assert any(KEY in r.getMessage() and "not a positive integer" in r.getMessage() for r in caplog.records)


def test_bt4_repos_yaml_declares_clinical_mp_1200():
    cfg = yaml.safe_load((Path(__file__).parent.parent / "config" / "repos.yaml").read_text())
    repos = cfg["repos"]
    got = {name: (r or {}).get(KEY) for name, r in repos.items() if name in ("clinical-mp", "orchestrator", "yorsie")}
    print(f"[BT-4] {got}")
    assert got == {"clinical-mp": 1200, "orchestrator": None, "yorsie": None}


def test_bt5_timeout_verdict_names_the_repo_budget():
    src = (Path(__file__).parent.parent / "orchestrator.py").read_text()
    i = src.index('"build", "timeout",')
    window = src[i:i + 400]
    print(f"[BT-5] {' '.join(window.split())[:200]}")
    assert "_unit_repo_timeout(BUILD_GATE_TIMEOUT_KEY, BUILD_GATE_TIMEOUT)" in window
    assert "{BUILD_GATE_TIMEOUT}s budget" not in window

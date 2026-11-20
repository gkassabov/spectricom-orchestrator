"""ORCH-OPX-GAMEDAY-1 (Kanban 622 slice 1) — the monthly kill-switch game day (scripts/opx_gameday.py)."""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import queue_daemon  # noqa: E402
import opx_gameday  # noqa: E402

CHECKS = ["hook allows without KILL", "kill ends a SIGTERM-trapping fire", "hook denies with KILL",
          "daemon fires nothing while KILL exists", "unkill lifts KILL", "credential revocation"]


@pytest.fixture
def report(tmp_path, capsys):
    live_kill = Path(queue_daemon.ORCH_DIR) / "KILL"
    before = live_kill.exists()
    saved = {n: getattr(queue_daemon, n) for n in opx_gameday.MOVED}
    out = tmp_path / "gameday.json"
    rc = opx_gameday.main(["--out", str(out), "--grace", "0.5"])
    return rc, json.loads(out.read_text()), capsys.readouterr().out, live_kill, before, saved


def test_G1_the_drill_passes_every_check_on_a_real_process_tree(report):
    rc, rep, out, *_ = report
    assert rc == 0 and rep["passed"] is True
    assert [c["check"] for c in rep["checks"]] == CHECKS
    assert all(c["pass"] is True for c in rep["checks"][:5]), rep["checks"]
    assert "PASSED" in out


def test_G2_the_fire_that_traps_SIGTERM_dies_by_SIGKILL_and_the_orchestrator_lives(report):
    _, rep, *_ = report
    ev = rep["checks"][1]["evidence"]
    assert "fire exit -9" in ev and "untouched True" in ev and "gone True" in ev


def test_G3_credential_revocation_is_reported_not_built_never_passed(report):
    _, rep, out, *_ = report
    cred = rep["checks"][-1]
    assert cred == {"check": "credential revocation", "pass": None, "evidence": "not built"}
    assert "— credential revocation: not built" in out


def test_G4_the_live_orchestrator_dir_is_never_touched_and_paths_are_restored(report):
    _, _, _, live_kill, before, saved = report
    assert live_kill.exists() == before, "the live KILL is never written or removed"
    assert {n: getattr(queue_daemon, n) for n in opx_gameday.MOVED} == saved


def test_G5_the_sandbox_refuses_the_live_orchestrator_dir():
    with pytest.raises(opx_gameday.SandboxError):
        opx_gameday.enter_sandbox(Path(queue_daemon.ORCH_DIR))


def test_G6_a_failed_check_fails_the_day(tmp_path, monkeypatch):
    """Negative control: a hook that never denies makes the game day exit 1."""
    fake = tmp_path / "allow_all.sh"
    fake.write_text("#!/usr/bin/env bash\nexit 0\n")
    monkeypatch.setattr(opx_gameday, "HOOK", fake)
    monkeypatch.setattr(opx_gameday, "ROOT", tmp_path)
    out = tmp_path / "g.json"
    assert opx_gameday.main(["--out", str(out), "--grace", "0.5"]) == 1
    rep = json.loads(out.read_text())
    assert rep["passed"] is False
    assert next(c for c in rep["checks"] if c["check"] == "hook denies with KILL")["pass"] is False

"""[ORCH-REPEAT-FLAKE-1] Kanban 836 — SESSION-BOOT rule #17 ("same flaky test seen twice → bug row + fix row now") in
code: a file the unit gate confirms FLAKY is noted by route in sit-archive/flake-ledger.json; seen by two different
routes within 14 days, the PASS line and one warning line name it as a REPEAT FLAKE. Words only — verdicts unchanged.
  RF-1  the ledger: a first sighting is no repeat; a second route is (count 2, first date); the same route re-gated
        counts once; a sighting older than the window is dropped; another repo's sightings never count
  RF-2  the gate: the second route's PASS detail and warning name the repeat; the first route's detail is exactly
        today's wording; the verdict, signal and flaky set are unchanged; a different file is no repeat
  RF-3  an unreadable ledger is left byte-for-byte as it is, one warning, and the gate's detail is today's
  RF-4  the ledger lives in the gate's archive dir only (the sit-archive dir, gitignored), never in state/
Driven like tests/test_unit_gate_wording.py, with tests/test_unit_baseline_gate.py's helpers.
"""
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_unit_baseline_gate import A, B, C, active, confirm_fake, repo, vitest  # noqa: E402,F401

T0 = datetime(2026, 11, 21, 22, 0, 0)


def gate(repo, archive, route, flaky=B):
    """One unit gate whose only newly-failing file (`flaky`) passes alone: a flaky PASS."""
    with active(archive=archive), patch.object(
            orchestrator, "_run_unit_suite",
            confirm_fake(vitest([flaky, A], failed=2, total_tests=20, total_files=8), vitest([A], failed=1, total_tests=20,
                                                                                            total_files=8),
                         confirm_out=vitest(failed=0, total_tests=2, total_files=1))):
        return orchestrator.run_unit_gate(repo, route, archive_path=archive)


# ── RF-1 · the ledger ────────────────────────────────────────────────────────
def test_RF1_first_second_same_route_window_and_repo(tmp_path):
    note = orchestrator._flake_ledger_note
    assert note(tmp_path, "clinical-mp", "route-1", (B,), now=T0) == ()
    assert note(tmp_path, "clinical-mp", "route-1", (B,), now=T0 + timedelta(minutes=30)) == ()   # a re-gate: once
    two = note(tmp_path, "clinical-mp", "route-2", (B, C), now=T0 + timedelta(hours=2))
    print(f"[RF-1] second route: {two}")
    assert two == ((B, 2, "2026-11-21T22:00:00"),)
    assert note(tmp_path, "yorsie", "route-3", (B,), now=T0 + timedelta(hours=3)) == ()           # another repo
    late = note(tmp_path, "clinical-mp", "route-9", (C,), now=T0 + timedelta(days=15))            # C's sighting aged out
    assert late == ()
    data = json.loads((tmp_path / orchestrator.FLAKE_LEDGER_FILE).read_text())
    assert data["version"] == 1 and sorted(data["repos"]) == ["clinical-mp", "yorsie"]
    assert [s["route"] for s in data["repos"]["clinical-mp"][C]] == ["route-9"]
    assert orchestrator._repeat_flake_words(two) == f"{B} flaky in 2 routes since 2026-11-21"
    assert (orchestrator.FLAKE_REPEAT_AT, orchestrator.FLAKE_REPEAT_WINDOW_DAYS) == (2, 14)


# ── RF-2 · the gate names it; the verdict is unchanged ──────────────────────
def test_RF2_the_second_route_names_the_repeat_and_the_first_reads_as_today(repo, tmp_path, caplog):
    archive = tmp_path / "archive"
    first = gate(repo, archive, "orch-mp-000000801-a")
    assert first.passed is True and first.signal is None and first.flaky_files == (B,) and first.repeat_flakes == ()
    assert "REPEAT FLAKE" not in first.detail
    today = first.detail
    with caplog.at_level(logging.WARNING, logger=orchestrator.log.name):
        second = gate(repo, archive, "orch-mp-000000802-b")
    print(f"[RF-2] second detail: {second.detail}")
    assert second.passed is True and second.signal is None and second.flaky_files == (B,)
    assert [(f, n) for f, n, _ in second.repeat_flakes] == [(B, 2)]
    suffix = (f" — REPEAT FLAKE (rule #17: a Bug Registry row and a fix row are owed): {B} flaky in 2 routes since "
              f"{datetime.now().date().isoformat()}")
    assert second.detail.endswith(suffix)
    base = second.detail[: -len(suffix)]   # today's wording, from the baseline cache the first gate wrote
    assert base == today.replace("(baseline measured)", "(baseline cache)")
    warned = [r.getMessage() for r in caplog.records if "REPEAT FLAKE" in r.getMessage()]
    assert len(warned) == 1 and B in warned[0]
    other = gate(repo, archive, "orch-mp-000000803-c", flaky=C)
    assert other.repeat_flakes == () and "REPEAT FLAKE" not in other.detail and other.detail == base.replace(B, C)


# ── RF-3 · an unreadable ledger is left alone ────────────────────────────────
def test_RF3_an_unreadable_ledger_is_left_as_it_is(repo, tmp_path, caplog):
    archive = tmp_path / "archive"
    archive.mkdir()
    ledger = archive / orchestrator.FLAKE_LEDGER_FILE
    ledger.write_bytes(b"{not json")
    with caplog.at_level(logging.WARNING, logger=orchestrator.log.name):
        o = gate(repo, archive, "orch-mp-000000804-d")
    assert ledger.read_bytes() == b"{not json"
    assert o.passed is True and o.repeat_flakes == () and "REPEAT FLAKE" not in o.detail
    assert any("flake-ledger.json is unreadable (JSONDecodeError)" in r.getMessage() for r in caplog.records)


# ── RF-4 · where it lives ────────────────────────────────────────────────────
def test_RF4_the_ledger_lives_in_the_archive_dir_only(repo, tmp_path):
    archive = tmp_path / "archive"
    gate(repo, archive, "orch-mp-000000805-e")
    assert (archive / orchestrator.FLAKE_LEDGER_FILE).exists()
    assert not (tmp_path / "state").exists()
    assert orchestrator.FLAKE_LEDGER_FILE == "flake-ledger.json"
    ignore = (Path(orchestrator.__file__).parent / ".gitignore").read_text()
    assert "sit-archive/*.json" in ignore or "sit-archive/" in ignore

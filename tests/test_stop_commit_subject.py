# filename: tests/test_stop_commit_subject.py
"""Tests for ORCH-STOP-COMMIT-SUBJECT-1 (Kanban 885).

Route 873 (2026-11-22) STOPPED (guard): its executor wrote only a handback whose first status line is
`## STATUS: STOP (guard)`, the briefs-only gate passed it, and the orchestrator's own route commit on the merge target
read `fix: 000000873-build-tsc-heap-1 — 1 briefs` — a watcher keyed on that subject took the route for merged. The
verdict was already `stopped` (ORCH-HANDBACK-STOP-STATUS-1, Kanban 690); now the commit's subject says so too.

  S-1  a STOP handback → the route commit on main reads `stop: <stem> — 1 briefs — handback STOP (g)`
  S-2  a PARTIAL handback → `partial: <stem> — 1 briefs — handback PARTIAL`
  S-3  control: a DONE handback → today's `fix: <stem> — 1 briefs`, byte for byte
  S-4  control: no handback at all → today's subject
  S-5  a STOP letter holding shell characters is written literally (the message is one argument, never a shell word)
  S-6  the verdict, the merge and the retired brief are what they were (P-1's own assertions, on the new subject)

Harness: tests.test_handback_stop_status's Lane (a real repo, the brief queued outside it, the legs scripted). No test
calls the real `claude`, and nothing reads or writes the live orchestrator's queue/, state/ or logs/. Module-level
imports are existing symbols only, so the RED run on the base collects.
"""

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_gate_cost import _git  # noqa: E402
from tests.test_handback_stop_status import STEM, STOP_G, Lane, _final, _stopped  # noqa: E402


@pytest.fixture
def lane(tmp_path, monkeypatch):
    return Lane(tmp_path, monkeypatch)


def _subjects(lane) -> list:
    return _git(lane.repo, "log", "main", "--format=%s").splitlines()


def _run(lane, caplog, handback=None):
    b = lane.brief()
    lane.toni({f"briefs/{STEM}.handback.md": handback} if handback is not None else {})
    with caplog.at_level(logging.INFO, logger="orch"):
        r = lane.inner(b)
    return b, r


def test_S1_a_stop_handback_lands_as_stop(lane, caplog):
    _run(lane, caplog, STOP_G)
    subjects = _subjects(lane)
    print(f"[S-1] {subjects[:2]}")
    assert subjects[0] == f"stop: {STEM} — 1 briefs — handback STOP (g)"
    assert not any(s.startswith("fix: ") for s in subjects[:1])


def test_S2_a_partial_handback_lands_as_partial(lane, caplog):
    _run(lane, caplog, "## STATUS: PARTIAL — Part A built\n")
    print(f"[S-2] {_subjects(lane)[:1]}")
    assert _subjects(lane)[0] == f"partial: {STEM} — 1 briefs — handback PARTIAL"


def test_S3_control_a_done_handback_keeps_todays_subject(lane, caplog):
    _run(lane, caplog, "## STATUS: DONE\n\nAll built.\n")
    print(f"[S-3] {_subjects(lane)[:1]}")
    assert _subjects(lane)[0] == f"fix: {STEM} — 1 briefs"


def test_S4_control_no_handback_keeps_todays_subject(lane, caplog):
    b = lane.brief()
    lane.toni({})
    with caplog.at_level(logging.INFO, logger="orch"):
        lane.inner(b)
    print(f"[S-4] {_subjects(lane)[:1]}")
    assert _subjects(lane)[0] == f"fix: {STEM} — 1 briefs"


def test_S5_a_letter_with_shell_characters_is_written_literally(lane, caplog, tmp_path):
    letter = '"q" $HOME; : >S5'          # the reader strips markdown backticks, so none here
    _run(lane, caplog, f"## STATUS: STOP ({letter})\n")
    subject = _subjects(lane)[0]
    print(f"[S-5] {subject!r}")
    assert subject == f"stop: {STEM} — 1 briefs — handback STOP ({letter})", "written literally: no quote broken, no $HOME expanded"
    assert not (lane.repo / "S5").exists() and not (Path.cwd() / "S5").exists()


def test_S6_the_verdict_merge_and_retire_are_unchanged(lane, caplog):
    main_before = _git(lane.repo, "rev-parse", "main")
    b, r = _run(lane, caplog, STOP_G)
    assert "🏁 FINAL STATUS: stopped" in _final(caplog) and "handback: STOP (g)" in _final(caplog)
    assert r.status is _stopped() and r.gate_outcome == "PASS"
    assert _git(lane.repo, "rev-parse", "main") != main_before and lane.on_main(f"briefs/{STEM}.handback.md")
    assert not b.exists() and (lane.queue / "done" / b.name).exists()
    msg = getattr(orchestrator, "route_commit_message", None)
    assert msg is not None and msg("s", 2, None) == "fix: s — 2 briefs"

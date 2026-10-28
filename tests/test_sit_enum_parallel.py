# filename: tests/test_sit_enum_parallel.py
"""Tests for ORCH-SIT-ENUM-PARALLEL-1 (S7-CORE-33 · D-S7CORE33-36 fix #4, Kanban row 403).

The SIT leg's enumeration (`_sit_plan` + `_sit_related_files`: two `vitest list` runs) used to start only after
the build gate returned — 31 min/day on clinical-mp, run serially after a build it does not depend on. It now
runs in a worker beside the build; the SIT leg consumes the result.

  P1-1  enumeration starts before the build finishes (a fake slow build + a fake list command)    (TestP1_1*)
  P1-2  the parallel and serial paths give equal plans on the same fixture; a red build discards the result;
        a moved HEAD (or an enumeration exception) forces the serial re-run, said                (TestP1_2*)
        ORCH_SIT_ENUM_PARALLEL=off is today's serial order                                        (TestKill*)

Harness: a REAL git repository with a real merge base and diff (tests.test_gate_cost helpers); only the suite
commands (`npm run build`, `npx vitest list`, `npm run sit:gate`, `npm test`) are scripted. Module-level imports
are existing symbols only, so this file collects on HEAD for the RED run.
"""

import json
import logging
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402
from tests.test_gate_cost import (BUILD_CMD, F, LIST_CMD, LIST_OUT, SIT_CMD, TEST_CMD, _activate, _commit,  # noqa: E402
                                  _git, _msgs, _repo, batch, vitest)

PASS = orchestrator.GateOutcome.PASS
BUILD_S = 0.6     # the fake build's wall time: long enough that "before it finished" is unambiguous


class Suite:
    """subprocess.run for every leg: the build sleeps BUILD_S; each list command records when it started; git and
    everything else runs for real. `on_build` runs inside the build (to move HEAD under it)."""

    def __init__(self, monkeypatch, repo, related=f"{F[2]}\n", build_rc=0):
        self.repo, self.real, self.related, self.build_rc = repo, subprocess.run, related, build_rc
        self.events, self.lock = [], threading.Lock()
        self.build_window = None
        self.on_build = None
        self.list_raises = 0          # the next N plain list calls raise (an enumeration exception)
        monkeypatch.setattr(subprocess, "run", self)
        monkeypatch.setattr("time.sleep", lambda s: None)

    def _ev(self, name, cmd=""):
        with self.lock:
            self.events.append((name, time.monotonic(), cmd))

    def __call__(self, cmd, *a, **kw):
        if not isinstance(cmd, str) or not cmd.startswith(("npm ", "npx ")) and BUILD_CMD not in cmd \
                and LIST_CMD not in cmd and SIT_CMD not in cmd:
            return self.real(cmd, *a, **kw)
        if BUILD_CMD in cmd:
            t0 = time.monotonic()
            self._ev("build-start")
            if self.on_build:
                self.on_build()
            _real_sleep(BUILD_S)
            self.build_window = (t0, time.monotonic())
            self._ev("build-end")
            return subprocess.CompletedProcess(cmd, self.build_rc, stdout="built\n" if not self.build_rc
                                               else "error TS2304: Cannot find name 'x'.\n", stderr="")
        if LIST_CMD in cmd and "--changed" in cmd:
            self._ev("related", cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout=self.related, stderr="")
        if LIST_CMD in cmd:
            self._ev("list", cmd)
            if self.list_raises:
                self.list_raises -= 1
                raise RuntimeError("enumeration worker blew up")
            return subprocess.CompletedProcess(cmd, 0, stdout=LIST_OUT, stderr="")
        if SIT_CMD in cmd:
            files = [f for f in F.values() if f in cmd]
            self._ev("sit", ",".join(files))
            return subprocess.CompletedProcess(cmd, 0, stdout=batch(len(files)), stderr="")
        if cmd.startswith(TEST_CMD):
            self._ev("unit")
            return subprocess.CompletedProcess(cmd, 0, stdout=vitest(), stderr="")
        raise AssertionError(cmd)

    def names(self) -> list:
        return [e[0] for e in self.events]

    def first(self, name) -> float:
        return next(t for n, t, _ in self.events if n == name)

    def sit_files(self) -> list:
        return [c for n, _, c in self.events if n == "sit"]


_real_sleep = time.sleep


@pytest.fixture
def rig(tmp_path, monkeypatch):
    repo = _repo(tmp_path / "repo")
    _activate(monkeypatch, tmp_path, repo, gates=("build", "sit"), sit_list_cmd=LIST_CMD, sit_batch_files=10,
              sit_batch_pause_s=0)
    _commit(repo, "route", write={"src/lib/a.ts": "export const a = 2;\n", F[4]: "test\n"}, keep=True)
    monkeypatch.delenv("ORCH_SIT_ENUM_PARALLEL", raising=False)
    return repo


def _gate(repo):
    return orchestrator.run_pre_merge_gates(repo, "route")


def _sit_log(tmp_path) -> list:
    f = tmp_path / "archive" / "orchestrator-sit-log.json"
    return json.loads(f.read_text()) if f.exists() else []


# ═══════════════════════════════════════════════════════
# P1-1 · the enumeration starts before the build finishes
# ═══════════════════════════════════════════════════════
class TestP1_1Beside:

    def test_enumeration_starts_before_the_build_finishes(self, rig, monkeypatch, caplog):
        s = Suite(monkeypatch, rig)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert v.outcome is PASS, v.label
        b0, b1 = s.build_window
        assert s.first("list") < b1, f"the enumeration started {s.first('list') - b1:+.3f}s after the build ended"
        assert s.first("related") < b1 or s.first("related") - s.first("list") < BUILD_S
        assert any(m.startswith("⏩ SIT enumeration ran beside the build (") and "s saved)" in m
                   for m in _msgs(caplog)), _msgs(caplog)

    def test_the_saving_reaches_the_verdict_and_the_sit_log(self, rig, monkeypatch, tmp_path):
        Suite(monkeypatch, rig)
        v = _gate(rig)
        assert "enumeration: beside the build" in (v.collection or ""), v.collection
        last = _sit_log(tmp_path)[-1]
        assert last["enumeration"].startswith("beside the build") and "s saved" in last["enumeration"]


# ═══════════════════════════════════════════════════════
# P1-2 · same plan as the serial path; red build discards; moved HEAD / exception ⇒ serial
# ═══════════════════════════════════════════════════════
class TestP1_2Equal:

    def test_parallel_and_serial_hand_the_sit_leg_the_same_files(self, rig, monkeypatch):
        s = Suite(monkeypatch, rig)
        v1 = _gate(rig)
        par = s.sit_files()
        monkeypatch.setenv("ORCH_SIT_ENUM_PARALLEL", "off")
        s.events.clear()
        v2 = _gate(rig)
        assert par == s.sit_files() == [f"{F[2]},{F[4]}"], (par, s.sit_files())
        assert v1.outcome is v2.outcome is PASS
        strip = lambda c: c.split(" | enumeration:")[0].rsplit(",", 1)[0]   # the duration differs, nothing else
        assert strip(v1.collection) == strip(v2.collection)

    def test_the_worker_computes_exactly_the_serial_plan_and_related_set(self, rig, monkeypatch):
        Suite(monkeypatch, rig)
        diff = orchestrator._branch_diff(rig, "route")
        job = orchestrator._sit_enum_start(rig, diff)
        job.wait()
        plan = orchestrator._sit_plan(rig)
        assert job.plan == plan
        assert (job.related, job.how) == orchestrator._sit_related_files(rig, plan, diff)

    def test_a_red_build_discards_the_enumeration_and_runs_no_sit(self, rig, monkeypatch, caplog):
        s = Suite(monkeypatch, rig, build_rc=2)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert v.outcome is not PASS and v.gate == "build"
        assert "sit" not in s.names()
        assert any("SIT enumeration discarded — the build is red" in m for m in _msgs(caplog)), _msgs(caplog)

    def test_a_moved_head_forces_the_serial_re_run_and_says_why(self, rig, monkeypatch, caplog):
        s = Suite(monkeypatch, rig)

        def move():
            (rig / "src" / "lib" / "late.ts").write_text("export const late = 1;\n")
            _git(rig, "add", "-A")
            _git(rig, "commit", "-qm", "late commit under the build")
        s.on_build = move
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert v.outcome is PASS
        lists = [t for n, t, _ in s.events if n == "list"]
        assert len(lists) == 2 and lists[1] > s.build_window[1], "the serial re-run follows the build"
        assert any("SIT enumeration re-run serially" in m and "tree moved" in m for m in _msgs(caplog)), _msgs(caplog)
        assert "enumeration: serial" in v.collection

    def test_an_enumeration_exception_forces_the_serial_re_run(self, rig, monkeypatch, caplog):
        s = Suite(monkeypatch, rig)
        s.list_raises = 1
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert v.outcome is PASS and s.sit_files() == [f"{F[2]},{F[4]}"]
        assert any("SIT enumeration re-run serially" in m and "RuntimeError" in m for m in _msgs(caplog))


class TestKillSwitch:

    def test_off_enumerates_after_the_build_as_today(self, rig, monkeypatch, caplog):
        monkeypatch.setenv("ORCH_SIT_ENUM_PARALLEL", "off")
        s = Suite(monkeypatch, rig)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = _gate(rig)
        assert v.outcome is PASS
        assert s.first("list") >= s.build_window[1]
        assert not any("ran beside the build" in m for m in _msgs(caplog))
        assert any("ORCH_SIT_ENUM_PARALLEL=off — serial, after the build" in m for m in _msgs(caplog))
        assert "enumeration:" not in (v.collection or "")

    def test_no_list_command_is_unchanged(self, tmp_path, monkeypatch):
        repo = _repo(tmp_path / "plain")
        _activate(monkeypatch, tmp_path, repo, gates=("build", "sit"))
        _commit(repo, "route", write={"src/lib/a.ts": "x\n"}, keep=True)
        assert orchestrator.PRE_MERGE_GATES  # unbatched repo: no plan, so no worker
        s = Suite(monkeypatch, repo)
        _gate(repo)
        assert "list" not in s.names()

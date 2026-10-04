# filename: tests/test_config_truth.py
"""Tests for ORCH-CONFIG-TRUTH-1: a control command that changes nothing says so, and a baseline
whose clock was never judged is not trusted.

S7-CORE-16 · route 67's handback, "Found and left".
  1. QueueDaemon.update_config answered {"ok": True} for model / effort / repo / timeout_seconds and
     changed nothing. It also coerced: bool("false") is True.
  2. A unit-baseline cache entry did not record that its clock was judged. The cache-hit
     `🛡 baseline-trust:` line said "since GATE-CLOCK-1 only a plausible leg is cached", which is
     true only of entries written after route 61. 62 of the live cache's 67 entries predate it.

  P-CFG   an unsettable key → ok False and queue-state.json byte-unchanged; a settable key with a
          value that parses → applied; a value that does not parse → refused, nothing changed.
          `queue_daemon.py config …` prints the refusal and exits non-zero.       (TestConfig*)
  P-CACHE an entry without `clock` → a miss: re-measured and overwritten with "clock": "plausible";
          a judged entry → a hit; an implausible re-measure → never stored; the ancestor path
          treats an unjudged entry the same way.                     (TestUnjudged*, TestAncestor)
  P-LINE  the cache-hit trust line quotes the judged field; no line claims "only a plausible leg
          is cached" of an entry that does not carry it.                           (TestTrustLine)

Each predicate has a negative control. Every path is under tmp_path. No test reads or writes the
live queue-state.json or the live baseline cache.
"""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator
import queue_daemon
from tests.test_gate_clock import (BASE_59, BRANCH_59, CONFIRM_59, DEBT_SEED, FIRST_FIRE, NEW_A, NEW_B, REPO,
                                   SECOND_FIRE, TEST_CMD, _git, gate, vitest)  # noqa: F401

ROOT = Path(__file__).parent.parent
PLAUSIBLE = (338.8, 338.8, 338.8)
CONFIRM = (7.4, 7.4, 7.4)
# The route 59 masking baseline: the branch's own 5 failures, measured across a host sleep.
BASE_MASKED = vitest(875, {DEBT_SEED: 3, NEW_A: 1, NEW_B: 1}, 8866)
EMPTY = vitest(0, {}, 0, expected_fail=0, skipped=0, todo=0)   # collected nothing: not a measurement
LEGACY_AT = "2026-09-20T10:00:00.000000"   # before GATE-CLOCK-1 (964e564, 2026-09-28)
UNJUDGED = "predates GATE-CLOCK-1 (clock never judged)"
PASS, BLOCKED, PRODUCT = (orchestrator.GateOutcome.PASS, orchestrator.GateOutcome.BLOCKED_ENV,
                          orchestrator.GateOutcome.FAIL_PRODUCT)


def _dead_pid() -> int:
    p = subprocess.Popen(["true"])
    p.wait()
    return p.pid


# ═══════════════════════════════════════════════════════
# the daemon harness — module paths under tmp_path, a persisted state written first
# ═══════════════════════════════════════════════════════
class Q:
    def __init__(self, tmp_path, monkeypatch, status="stopped", pid=None):
        orch = tmp_path / "orch"
        (orch / "state").mkdir(parents=True)
        self.state_file = tmp_path / "queue-state.json"
        for name, val in (("ORCH_DIR", orch), ("QUEUE_DIR", orch / "queue"),
                          ("QUEUE_DONE", orch / "queue" / "done"), ("QUEUE_FAILED", orch / "queue" / "failed"),
                          ("QUEUE_STATE", self.state_file), ("REPOS_CONFIG", tmp_path / "repos.yaml"),
                          ("LOG_DIR", tmp_path / "logs")):
            monkeypatch.setattr(queue_daemon, name, val)
        self.state_file.write_text(json.dumps({
            "daemon_status": status, "pid": _dead_pid() if pid is None else pid, "control_ack": 0,
            "config": {"max_consecutive": 25, "cooldown_seconds": 30, "stop_on_failure": True, "repo": "clinical-mp",
                       "model": "persisted-model", "effort": "high", "timeout_seconds": 11400},
            "consecutive_count": 3, "updated_at": "2026-09-29T12:00:00"}, indent=2))
        self.before = self.state_file.read_bytes()
        self.d = queue_daemon.QueueDaemon()

    def unchanged(self) -> bool:
        return self.state_file.read_bytes() == self.before

    def persisted(self) -> dict:
        return json.loads(self.state_file.read_text())["config"]


@pytest.fixture
def q(tmp_path, monkeypatch):
    return Q(tmp_path, monkeypatch)


UNSETTABLE = [("model", "some-model"), ("effort", "low"), ("repo", "orchestrator"), ("timeout_seconds", "60")]


# ═══════════════════════════════════════════════════════
# P-CFG · a key the command cannot set is refused, and nothing is written
# ═══════════════════════════════════════════════════════
class TestConfigRefused:

    @pytest.mark.parametrize("key,value", UNSETTABLE, ids=[k for k, _ in UNSETTABLE])
    def test_an_unsettable_key_is_refused_and_the_state_is_byte_unchanged(self, q, key, value):
        config = dict(q.d.config)
        r = q.d.update_config(key, value)
        assert r["ok"] is False, r
        assert r["error"].startswith(f"{key} is not settable by command: "), r["error"]
        assert q.unchanged(), "a refusal writes nothing"
        assert q.d.config == config

    @pytest.mark.parametrize("key", ["model", "effort"])
    def test_the_executor_refusal_names_route_67s_rule(self, q, key):
        err = q.d.update_config(key, "x")["error"]
        assert "one default in the repo" in err and f"#!queue {key}=" in err and "EXECUTOR-DEFAULT-1" in err, err

    def test_repo_says_where_it_comes_from(self, q):
        # [ORCH-YORSIE-SAFETY-1] the daemon has no default repo (QUEUE_REPO is no longer read)
        err = q.d.update_config("repo", "orchestrator")["error"]
        assert "#!queue repo=" in err and "no default repo" in err, err

    def test_timeout_says_where_it_comes_from(self, q):
        err = q.d.update_config("timeout_seconds", "60")["error"]
        assert "queue_daemon.py" in err and "180-minute" in err, err

    def test_an_unknown_key_is_refused_in_the_same_shape(self, q):
        r = q.d.update_config("max_parallel", "2")
        assert r["ok"] is False and r["error"].startswith("max_parallel is not settable by command: "), r
        assert "max_consecutive, cooldown_seconds, stop_on_failure" in r["error"]
        assert q.unchanged()


# ═══════════════════════════════════════════════════════
# P-CFG · the settable keys: a value that parses is applied, one that does not is refused
# ═══════════════════════════════════════════════════════
class TestConfigSettable:

    @pytest.mark.parametrize("key,value,parsed", [
        ("max_consecutive", "30", 30), ("max_consecutive", 30, 30), ("cooldown_seconds", "0", 0),
        ("stop_on_failure", "false", False), ("stop_on_failure", "TRUE", True), ("stop_on_failure", False, False),
    ])
    def test_negative_control_a_value_that_parses_is_applied_and_persisted(self, q, key, value, parsed):
        r = q.d.update_config(key, value)
        assert r["ok"] is True, r
        assert q.d.config[key] == parsed and type(q.d.config[key]) is type(parsed)
        assert q.persisted()[key] == parsed

    @pytest.mark.parametrize("key,value", [
        ("max_consecutive", "ten"), ("max_consecutive", "3.5"), ("max_consecutive", True), ("max_consecutive", ""),
        ("cooldown_seconds", "-1"), ("cooldown_seconds", 2.5),
        ("stop_on_failure", "maybe"), ("stop_on_failure", "1"), ("stop_on_failure", 0),
    ])
    def test_a_value_that_does_not_parse_is_refused_not_coerced(self, q, key, value):
        config = dict(q.d.config)
        r = q.d.update_config(key, value)
        assert r["ok"] is False, r
        assert r["error"].startswith(f"{key}: {value!r} is not "), r["error"]
        assert q.unchanged() and q.d.config == config


# ═══════════════════════════════════════════════════════
# P-CFG · the command: a refusal is printed and the exit is non-zero
# ═══════════════════════════════════════════════════════
class TestConfigCommand:

    def test_config_model_fails_loudly(self, q, capsys):
        rc = queue_daemon.main(["config", "model", "some-model"])
        out = capsys.readouterr().out
        assert rc == 1, out
        assert "model is not settable by command" in out
        assert q.unchanged()

    def test_an_unparseable_value_exits_non_zero(self, q, capsys):
        rc = queue_daemon.main(["config", "stop_on_failure", "no"])
        assert rc == 1 and "'no' is not true or false" in capsys.readouterr().out
        assert q.unchanged()

    def test_negative_control_a_settable_key_with_no_daemon_running_is_applied(self, q, capsys):
        rc = queue_daemon.main(["config", "max_consecutive", "30"])
        out = capsys.readouterr().out
        assert rc == 0, out
        assert q.persisted()["max_consecutive"] == 30
        assert "the next daemon start reads it" in out

    def test_a_settable_key_while_a_daemon_runs_is_refused_not_pretended(self, tmp_path, monkeypatch, capsys):
        """The CLI is another process. The running daemon keeps its config in memory and rewrites
        queue-state.json at its next save, so a value written here would change nothing."""
        q = Q(tmp_path, monkeypatch, status="running", pid=os.getpid())
        rc = queue_daemon.main(["config", "max_consecutive", "30"])
        out = capsys.readouterr().out
        assert rc == 1, out
        assert f"pid {os.getpid()}" in out and "would change nothing" in out
        assert q.unchanged()


# ═══════════════════════════════════════════════════════
# P-CACHE · an entry whose clock was never judged is a miss
# ═══════════════════════════════════════════════════════
def _fork(gate) -> str:
    return _git(gate.repo, "merge-base", "main", "route")


def _cache(gate) -> dict:
    f = gate.archive / orchestrator.UNIT_BASELINE_CACHE_FILE
    return json.loads(f.read_text())["entries"] if f.exists() else {}


def _seed(gate, sha, stdout, judged=True, **extra) -> str:
    """One cache entry for `sha`, written by the real store. `judged=False` makes it an entry as a
    pre-GATE-CLOCK-1 store wrote it: no `clock` field, measured before route 61."""
    run = orchestrator.UnitSuiteRun(ref=f"merge-base {sha[:7]}", exit_code=1, duration_s=301.0,
                                    **orchestrator._parse_unit_summary(stdout))
    orchestrator._unit_cache_store(gate.archive, REPO, sha, TEST_CMD, run)
    f = gate.archive / orchestrator.UNIT_BASELINE_CACHE_FILE
    data = json.loads(f.read_text())
    key = orchestrator._unit_cache_key(REPO, sha, TEST_CMD)
    if not judged:
        data["entries"][key].pop("clock", None)
        data["entries"][key]["measured_at"] = LEGACY_AT
    data["entries"][key].update(extra)
    f.write_text(json.dumps(data, indent=2))
    return key


def _msgs(caplog) -> list:
    return [r.getMessage() for r in caplog.records]


def _trust(caplog) -> list:
    return [m for m in _msgs(caplog) if m.startswith("🛡 baseline-trust:")]


class TestUnjudgedEntryIsAMiss:

    def test_the_store_records_that_the_clock_was_judged(self, gate):
        key = _seed(gate, _fork(gate), BASE_59[3])
        assert _cache(gate)[key]["clock"] == "plausible"

    def test_a_legacy_entry_is_re_measured_not_trusted(self, gate, caplog):
        """The route 59 shape served from the cache: a pre-GATE-CLOCK-1 entry carrying the branch's
        own failures would pass the regression off as debt."""
        fork = _fork(gate)
        _seed(gate, fork, BASE_MASKED, judged=False)
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[3], 1, PLAUSIBLE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = gate.run()
        assert gate.suite.calls == ["branch", "baseline", "confirm"], "the legacy entry must not be a hit"
        assert (v.outcome, v.signal) == (PRODUCT, "regression"), v.label
        assert f"♻️  Unit baseline: cached entry at {fork[:7]} {UNJUDGED} — re-measuring" in _msgs(caplog)

    def test_the_re_measure_overwrites_that_key_with_the_judged_field(self, gate):
        fork = _fork(gate)
        key = _seed(gate, fork, BASE_MASKED, judged=False)
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[3], 1, PLAUSIBLE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        gate.run()
        (k, e), = _cache(gate).items()
        assert k == key
        assert e["clock"] == "plausible"
        assert (e["failures"], e["failing_files"], e["duration_s"]) == (3, [DEBT_SEED], 338.8)
        assert e["measured_at"] != LEGACY_AT

    def test_the_superseded_entry_keeps_its_flaky_history(self, gate):
        """[ORCH-6/7] accumulate per base; superseding the measurement does not erase the tally."""
        seen = {"src/x.test.ts": {"count": 2, "last_seen": "2026-09-19T08:00:00"}}
        key = _seed(gate, _fork(gate), BASE_MASKED, judged=False, flaky_files=["src/x.test.ts"], flaky_seen=seen)
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[3], 1, PLAUSIBLE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        gate.run()
        e = _cache(gate)[key]
        assert e["clock"] == "plausible"
        assert (e["flaky_files"], e["flaky_seen"]) == (["src/x.test.ts"], seen)

    def test_an_implausible_re_measure_is_never_stored_and_the_legacy_entry_stays(self, gate):
        """BASELINE-TRUST-1 unchanged, and no delete: the legacy entry is superseded only by a
        plausible leg."""
        key = _seed(gate, _fork(gate), BASE_MASKED, judged=False)
        legacy = _cache(gate)[key]
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_MASKED, 1, FIRST_FIRE)
        gate.suite.script("baseline", BASE_MASKED, 1, FIRST_FIRE)
        v = gate.run()
        assert (v.outcome, v.signal) == (BLOCKED, "baseline-clock-implausible"), v.label
        assert _cache(gate) == {key: legacy}

    def test_only_the_entry_needed_is_superseded(self, gate):
        """No bulk rewrite: another legacy entry is left exactly as it was."""
        other = _git(gate.repo, "rev-parse", "route")
        other_key = _seed(gate, other, BASE_59[4], judged=False)
        _seed(gate, _fork(gate), BASE_MASKED, judged=False)
        untouched = _cache(gate)[other_key]
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[3], 1, PLAUSIBLE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        gate.run()
        assert _cache(gate)[other_key] == untouched and "clock" not in untouched

    def test_negative_control_a_judged_entry_is_a_hit(self, gate, caplog):
        _seed(gate, _fork(gate), BASE_59[3])
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        with caplog.at_level(logging.INFO, logger="orch"):
            v = gate.run()
        assert gate.suite.calls == ["branch", "confirm"], "a judged entry is reused, not re-measured"
        assert (v.outcome, v.signal) == (PRODUCT, "regression"), v.label
        assert not [m for m in _msgs(caplog) if UNJUDGED in m]


# ═══════════════════════════════════════════════════════
# P-CACHE · the ancestor path reads the same entries and treats them the same way
# ═══════════════════════════════════════════════════════
class TestAncestor:

    @pytest.fixture
    def older(self, gate) -> str:
        """main moves on to M1 and the route is rebased onto it: the merge base is M1, and M0 is a
        strict ancestor of it. Returns M0."""
        m0 = _fork(gate)
        _git(gate.repo, "checkout", "-q", "main")
        (gate.repo / "main.txt").write_text("M1")
        _git(gate.repo, "add", "-A")
        _git(gate.repo, "commit", "-qm", "M1")
        _git(gate.repo, "checkout", "-q", "route")
        _git(gate.repo, "rebase", "-q", "main")
        assert _fork(gate) != m0
        return m0

    def _run(self, gate, caplog):
        """The branch fails only the debt; the fresh baseline at M1 collects nothing."""
        gate.suite.script("branch", vitest(877, {DEBT_SEED: 3}, 8891), 1, SECOND_FIRE)
        gate.suite.script("baseline", EMPTY, 1, PLAUSIBLE)
        with caplog.at_level(logging.INFO, logger="orch"):
            return orchestrator.run_unit_gate(gate.repo, "route", archive_path=gate.archive)

    def test_a_legacy_ancestor_is_not_borrowed(self, gate, older, caplog):
        _seed(gate, older, BASE_59[3], judged=False)
        o = self._run(gate, caplog)
        assert (o.passed, o.env, o.signal) == (False, True, "baseline-unmeasurable"), o.detail
        assert "no measured ancestor" in o.baseline_note
        assert any(UNJUDGED in m and "ancestor" in m for m in _msgs(caplog)), _msgs(caplog)

    def test_negative_control_a_judged_ancestor_is_borrowed(self, gate, older, caplog):
        _seed(gate, older, BASE_59[3])
        o = self._run(gate, caplog)
        assert o.passed is True and o.baseline_source == "ancestor-cache", o.detail
        assert older[:7] in o.baseline_note
        assert not [m for m in _msgs(caplog) if UNJUDGED in m]


# ═══════════════════════════════════════════════════════
# P-LINE · the cache-hit trust line says what the entry carries
# ═══════════════════════════════════════════════════════
class TestTrustLine:

    def test_a_judged_hit_quotes_the_field(self, gate, caplog):
        fork = _fork(gate)
        key = _seed(gate, fork, BASE_59[3])
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        with caplog.at_level(logging.INFO, logger="orch"):
            gate.run()
        ts = _cache(gate)[key]["measured_at"][:19]
        assert _trust(caplog) == [f'🛡 baseline-trust: CLEAN — cache hit at {fork[:7]}, measured {ts} on a clock '
                                  f'judged plausible (cache entry "clock": "plausible")']

    def test_no_line_claims_what_a_legacy_entry_does_not_carry(self, gate, caplog):
        _seed(gate, _fork(gate), BASE_MASKED, judged=False)
        gate.suite.script("branch", BRANCH_59, 1, SECOND_FIRE)
        gate.suite.script("baseline", BASE_59[3], 1, PLAUSIBLE)
        gate.suite.script("confirm", CONFIRM_59, 1, CONFIRM)
        with caplog.at_level(logging.INFO, logger="orch"):
            gate.run()
        assert not [m for m in _msgs(caplog) if "only a plausible leg is cached" in m]
        line, = _trust(caplog)
        assert "cache hit" not in line and "measured on a plausible clock" in line, line

    def test_the_source_no_longer_makes_the_claim(self):
        assert "only a plausible leg is cached" not in (ROOT / "orchestrator.py").read_text()

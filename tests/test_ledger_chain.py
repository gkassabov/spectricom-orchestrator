"""ORCH-LEDGER-CHAIN-1 (route 623; RM-OPS-04-F-02 US-01; T-OPX-04; C-OPX05).

Every merge, gate verdict, hold, kill, unkill, verdict override and merge-hold release appends one JSON line to
logs/ledger.jsonl, chained by sha256 (`prev` = the previous line's `hash`); logs/ledger.head.json names the last line.
scripts/ledger-verify.py fails on any edit, deletion, insertion or reorder, and on a cut tail.

  C-1 the chain: seq 1..n, GENESIS, prev links, head anchor, verify OK
  C-2 an edit (a value, or only the formatting) is caught
  C-3 a deletion (middle, tail, head file) and an insertion are caught
  C-4 a reorder is caught
  C-5 the record contract: unknown kind / reserved field refused; values stored as they are hashed
  C-6 an unwritable ledger: append returns None, never raises; the route outcome is unchanged
  C-7 two writer processes at once: one whole chain
  C-8 scripts/ledger-verify.py: exit 0 OK / 1 broken / 2 usage
  C-9 the route lane: a green route writes gate PASS then merge (its tip, main's tip); a red gate writes gate only;
      a conflicted merge writes gate PASS and no merge
  C-10 the daemon: kill, unkill, override and release-hold each append one record
"""
import json
import multiprocessing
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import ledger_chain  # noqa: E402
import orchestrator  # noqa: E402
import queue_daemon  # noqa: E402
from tests.test_merge_conflict import _sha, fire, quiet, route, works  # noqa: E402,F401  (route: a fixture)
from tests.test_merge_hold import _held_branch, q  # noqa: E402,F401  (q: a fixture)
from tests.test_queue_park_red import git  # noqa: E402


def _records(d: Path) -> list:
    p = ledger_chain.ledger_path(d)
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def _three(d: Path) -> list:
    return [ledger_chain.append("gate", d=d, outcome="PASS", n=1), ledger_chain.append("hold", d=d, verdict="X", n=2),
            ledger_chain.append("merge", d=d, target_tip="abc", n=3)]


def _lines(d: Path) -> list:
    return ledger_chain.ledger_path(d).read_text().splitlines()


def _write_lines(d: Path, lines: list) -> None:
    ledger_chain.ledger_path(d).write_text("".join(l + "\n" for l in lines))


# ── C-1 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_C1_appends_build_one_chain_from_genesis_to_the_head(tmp_path):
    recs = _three(tmp_path)
    assert [r["seq"] for r in recs] == [1, 2, 3]
    assert recs[0]["prev"] == ledger_chain.GENESIS and recs[1]["prev"] == recs[0]["hash"] and recs[2]["prev"] == recs[1]["hash"]
    assert all(r["hash"] == ledger_chain.record_hash(r) for r in recs)
    assert _records(tmp_path) == recs
    head = json.loads(ledger_chain.head_path(tmp_path).read_text())
    assert (head["seq"], head["hash"]) == (3, recs[2]["hash"])
    assert ledger_chain.verify(tmp_path) == (3, [])


def test_C1_an_absent_ledger_is_empty_and_whole(tmp_path):
    assert ledger_chain.verify(tmp_path) == (0, [])


def test_C1_the_env_dir_wins_over_the_callers_log_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(ledger_chain.DIR_ENV, str(tmp_path / "env"))
    assert ledger_chain.ledger_dir(tmp_path / "logs") == tmp_path / "env"
    monkeypatch.delenv(ledger_chain.DIR_ENV)
    assert ledger_chain.ledger_dir(tmp_path / "logs") == tmp_path / "logs"


# ── C-2 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_C2_an_edited_value_is_caught(tmp_path):
    _three(tmp_path)
    lines = _lines(tmp_path)
    rec = json.loads(lines[1])
    rec["verdict"] = "Y"
    lines[1] = ledger_chain.canonical(rec)
    _write_lines(tmp_path, lines)
    n, problems = ledger_chain.verify(tmp_path)
    assert n == 3 and any(p.startswith("line 2: hash does not match") for p in problems)


def test_C2_an_edit_that_also_rehashes_the_line_breaks_the_next_link(tmp_path):
    _three(tmp_path)
    lines = _lines(tmp_path)
    rec = json.loads(lines[1])
    rec["verdict"] = "Y"
    rec["hash"] = ledger_chain.record_hash(rec)
    lines[1] = ledger_chain.canonical(rec)
    _write_lines(tmp_path, lines)
    _, problems = ledger_chain.verify(tmp_path)
    assert any(p.startswith("line 3: prev does not match") for p in problems)


def test_C2_a_formatting_only_edit_is_caught(tmp_path):
    _three(tmp_path)
    lines = _lines(tmp_path)
    lines[0] = json.dumps(json.loads(lines[0]), indent=None)   # ", " and ": " separators — same content
    _write_lines(tmp_path, lines)
    _, problems = ledger_chain.verify(tmp_path)
    assert problems == ["line 1: not in canonical form (edited by hand?)"]


# ── C-3 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_C3_a_deleted_middle_line_is_caught(tmp_path):
    _three(tmp_path)
    lines = _lines(tmp_path)
    _write_lines(tmp_path, [lines[0], lines[2]])
    _, problems = ledger_chain.verify(tmp_path)
    assert any("seq 3, expected 2" in p for p in problems) and any("prev does not match" in p for p in problems)


def test_C3_a_cut_tail_is_caught_by_the_head(tmp_path):
    _three(tmp_path)
    _write_lines(tmp_path, _lines(tmp_path)[:2])
    _, problems = ledger_chain.verify(tmp_path)
    assert len(problems) == 1 and "the tail was cut or rewritten" in problems[0]


def test_C3_an_emptied_ledger_and_a_deleted_head_are_caught(tmp_path):
    _three(tmp_path)
    ledger_chain.ledger_path(tmp_path).write_text("")
    assert any("has no records (deleted)" in p for p in ledger_chain.verify(tmp_path)[1])
    _three(tmp_path / "b")
    ledger_chain.head_path(tmp_path / "b").unlink()
    assert any("ledger.head.json is missing" in p for p in ledger_chain.verify(tmp_path / "b")[1])


def test_C3_an_inserted_line_is_caught(tmp_path):
    recs = _three(tmp_path)
    lines = _lines(tmp_path)
    fake = {"v": 1, "seq": 2, "ts": recs[1]["ts"], "kind": "merge", "prev": recs[0]["hash"], "target_tip": "evil"}
    fake["hash"] = ledger_chain.record_hash(fake)
    _write_lines(tmp_path, [lines[0], ledger_chain.canonical(fake), lines[1], lines[2]])
    _, problems = ledger_chain.verify(tmp_path)
    assert problems and any("line 3:" in p for p in problems)


# ── C-4 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_C4_a_reorder_is_caught(tmp_path):
    _three(tmp_path)
    lines = _lines(tmp_path)
    _write_lines(tmp_path, [lines[1], lines[0], lines[2]])
    _, problems = ledger_chain.verify(tmp_path)
    assert any("line 1: seq 2, expected 1" in p for p in problems) and any("line 1: prev" in p for p in problems)


# ── C-5 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kind,fields,why", [("deploy", {}, "unknown kind"), ("gate", {"seq": 9}, "reserved"),
                                             ("gate", {"hash": "x"}, "reserved"), ("gate", {"prev": "x"}, "reserved")])
def test_C5_an_unknown_kind_or_a_reserved_field_is_refused(tmp_path, kind, fields, why):
    with pytest.raises(ValueError, match=why):
        ledger_chain.append(kind, d=tmp_path, **fields)
    assert not ledger_chain.ledger_path(tmp_path).exists()


def test_C5_values_are_stored_exactly_as_they_are_hashed(tmp_path):
    rec = ledger_chain.append("gate", d=tmp_path, path=tmp_path, n=None, groups=[3, 1], text="é → ✓")
    assert rec["path"] == str(tmp_path) and rec["groups"] == [3, 1] and rec["text"] == "é → ✓"
    assert ledger_chain.verify(tmp_path) == (1, [])


# ── C-6 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def test_C6_an_unwritable_ledger_returns_none_and_never_raises(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a dir")
    assert ledger_chain.append("kill", d=blocker / "logs", reason="x") is None


def test_C6_a_route_whose_ledger_cannot_be_written_keeps_its_outcome(route, monkeypatch, caplog, tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    monkeypatch.setenv(ledger_chain.DIR_ENV, str(blocker / "logs"))
    with caplog.at_level("INFO"):
        r = fire(route, monkeypatch, works)
    assert r.status is orchestrator.Status.PASSED
    assert any("ledger: merge record not appended" in m.getMessage() for m in caplog.records)


# ── C-7 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _writer(d: str, who: str, n: int) -> None:
    for i in range(n):
        assert ledger_chain.append("gate", d=Path(d), who=who, i=i) is not None


def test_C7_two_writer_processes_make_one_whole_chain(tmp_path):
    ctx = multiprocessing.get_context("fork")
    ps = [ctx.Process(target=_writer, args=(str(tmp_path), w, 40)) for w in ("orchestrator", "daemon")]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    assert [p.exitcode for p in ps] == [0, 0]
    assert ledger_chain.verify(tmp_path) == (80, [])
    assert sorted((r["who"], r["i"]) for r in _records(tmp_path)) == sorted((w, i) for w in ("orchestrator", "daemon")
                                                                             for i in range(40))


# ── C-8 ────────────────────────────────────────────────────────────────────────────────────────────────────────────
def _cli(*args):
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "ledger-verify.py"), *args],
                          capture_output=True, text=True)


def test_C8_the_verify_script(tmp_path):
    r = _cli("--dir", str(tmp_path))
    assert r.returncode == 0 and "LEDGER OK — 0 record(s)" in r.stdout
    _three(tmp_path)
    r = _cli("--dir", str(tmp_path))
    assert r.returncode == 0 and "LEDGER OK — 3 record(s)" in r.stdout
    _write_lines(tmp_path, _lines(tmp_path)[::-1])
    r = _cli("--dir", str(tmp_path))
    assert r.returncode == 1 and r.stdout.startswith("LEDGER BROKEN") and "line 1: seq 3, expected 1" in r.stdout
    assert _cli("--bogus").returncode == 2


# ── C-9 · the route lane ───────────────────────────────────────────────────────────────────────────────────────────
def _env_records() -> list:
    return _records(ledger_chain.ledger_dir())


def test_C9_a_green_route_writes_its_gate_then_its_merge(route, monkeypatch):
    r = fire(route, monkeypatch, works)
    assert r.status is orchestrator.Status.PASSED
    recs = _env_records()
    assert [x["kind"] for x in recs] == ["gate", "merge"]
    gate, merge = recs
    assert gate["outcome"] == "PASS" and gate["lane"] == "route" and gate["batch"] == "batch-cf.md"
    assert gate["repo"] == "testrepo" and gate["branch"] == route.branch and gate["status"] == "passed"
    assert merge["route_tip"] == route.route_tip and merge["target"] == "main"
    assert merge["target_tip"] == _sha("main", route.proj)
    assert ledger_chain.verify(ledger_chain.ledger_dir()) == (2, [])


def test_C9_a_red_gate_writes_the_gate_and_no_merge(route, monkeypatch):
    def red(repo_path, branch_name=None):
        return orchestrator.GateVerdict(outcome=orchestrator.GateOutcome.FAIL_PRODUCT, gate="build", signal="exit 1")

    def toni(target, proj):
        log = route.proj.parent / "toni-test.log"
        log.write_text(f"=== TONI EXECUTION ===\n{'=' * 60}\n\nDone.\n\n{'=' * 60}\nExit: 0\n")
        return works(proj), str(log)
    monkeypatch.setattr(orchestrator, "fire_toni", toni)
    monkeypatch.setattr(orchestrator, "run_pre_merge_gates", red)
    main_before = _sha("main", route.proj)
    r = orchestrator._run_batch_inner(route.brief, route.proj, orchestrator.datetime.now(), worktree=None)
    assert r.status is orchestrator.Status.FAILED and _sha("main", route.proj) == main_before
    recs = _env_records()
    assert [x["kind"] for x in recs] == ["gate"] and recs[0]["outcome"] == "FAIL(product)"
    assert recs[0]["status"] == "failed" and "build" in recs[0]["detail"]


def test_C9_a_conflicted_merge_writes_gate_pass_and_no_merge(route, monkeypatch):
    r = fire(route, monkeypatch, works, main_moves=True)
    assert r.status is not orchestrator.Status.PASSED
    recs = _env_records()
    assert [x["kind"] for x in recs] == ["gate"] and recs[0]["outcome"] == "PASS" and recs[0]["status"] == "failed"


def test_C9_a_route_with_no_changes_writes_no_merge(route, monkeypatch):
    fire(route, monkeypatch, quiet)
    assert "merge" not in [x["kind"] for x in _env_records()]


# ── C-10 · the daemon ──────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def killdir(tmp_path, monkeypatch):
    monkeypatch.setattr(queue_daemon, "ORCH_DIR", tmp_path)
    monkeypatch.setattr(queue_daemon, "fire_process_groups", lambda: [])
    return tmp_path


def test_C10_kill_and_unkill_each_append_one_record(killdir):
    assert queue_daemon.kill("game day drill now") == 0
    assert queue_daemon.kill("a second kill") == 0
    assert queue_daemon.unkill("drill over, lift it") == 0
    recs = _env_records()
    assert [x["kind"] for x in recs] == ["kill", "kill", "unkill"]
    assert recs[0]["reason"] == "game day drill now" and recs[0]["written"] is True and recs[0]["fires"] == []
    assert recs[1]["written"] is False and recs[1]["kept_prior"] is True
    assert recs[2]["lifted_reason"] == "game day drill now"
    assert ledger_chain.verify(ledger_chain.ledger_dir()) == (3, [])


def test_C10_an_unkill_with_nothing_to_lift_writes_nothing(killdir):
    assert queue_daemon.unkill("nothing there") == 0
    assert _env_records() == []


def test_C10_an_override_appends_one_record(q):
    tip = q.branch("626b-x")
    git(q.repo, "notes", "add", "-m", "PRE-MERGE GATE: FAIL(product) — build: exit 1", tip)
    rc, msg = queue_daemon.append_override("cmp", "orch-mp-626b-x", "BLOCKED(environment)", "George",
                                           "build leg timeout under load")
    assert rc == 0, msg
    (rec,) = _env_records()
    assert rec["kind"] == "override" and rec["tip"] == tip and rec["verdict"] == "BLOCKED(environment)"
    assert rec["by"] == "George" and rec["reason"] == "build leg timeout under load"


def test_C10_a_refused_override_writes_nothing(q):
    q.branch("626b-x")
    rc, _ = queue_daemon.append_override("cmp", "orch-mp-626b-x", "BLOCKED(environment)", "George", "no note there")
    assert rc == 1 and _env_records() == []


def test_C10_a_release_hold_appends_one_record(q):
    tray = q.queue / "held" / "merge-hold"
    tray.mkdir(parents=True, exist_ok=True)
    (tray / "757-x.md").write_text("#!queue repo=cmp\n# 757-x\n## STOP\n(a)\n")
    branch, tip = _held_branch(q)
    rc, msg = queue_daemon.release_hold("cmp", branch, "Gemma", "lockfile diff reviewed ok")
    assert rc == 0, msg
    (rec,) = _env_records()
    assert rec["kind"] == "release-hold" and rec["branch"] == branch and rec["tip"] == tip
    assert rec["by"] == "Gemma" and rec["batch"] == "757-x.md"

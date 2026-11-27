"""[LANE-HEAVY-LEG-GUARD-1] scripts/heavy_leg.py (empty list, heavy.lock, workers beside a live route, PID-only stop)
and prefire's VERIFY line when no verifier report exists (L-561). Tmp dirs only; never the daemon's state."""
import fcntl
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HL = ROOT / "scripts" / "heavy_leg.py"
sys.path.insert(0, str(ROOT / "scripts"))
import heavy_leg  # noqa: E402
import prefire  # noqa: E402


def fake_vitest(tmp: Path) -> Path:
    """An executable named `vitest` that records its argv to $HL_OUT."""
    p = tmp / "bin" / "vitest"
    p.parent.mkdir(exist_ok=True)
    p.write_text("#!%s\nimport json, os, sys\nopen(os.environ['HL_OUT'], 'w').write(json.dumps(sys.argv[1:]))\n"
                 % sys.executable)
    p.chmod(0o755)
    return p


def qstate(tmp: Path, batch=None, log_text=None, full=None) -> Path:
    q = tmp / "queue-state.json"
    st = {"current_batch": None, "full_gate_running": full}
    if batch:
        log = tmp / "orch.log"
        log.write_text(log_text or "")
        st["current_batch"] = {"file": batch, "log_file": str(log)}
    q.write_text(json.dumps(st))
    return q


def run(tmp: Path, *args, env_extra=None, cmd_prefix=()):
    env = dict(os.environ, HL_OUT=str(tmp / "argv.json"))
    env.pop("HEAVY_LOCK", None)
    env.update(env_extra or {})
    return subprocess.run([*cmd_prefix, sys.executable, str(HL), *args], capture_output=True, text=True, env=env,
                          timeout=60)


def base(tmp: Path, q: Path, *extra):
    return ("run", "--state", str(tmp / "s.json"), "--lock", str(tmp / "heavy.lock"), "--lock-wait", "1",
            "--queue-state", str(q), "--watch-every", "0.2", *extra)


# ── E · empty list ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_e1_empty_files_from_is_refused_and_nothing_runs(tmp_path):
    v, q = fake_vitest(tmp_path), qstate(tmp_path)
    (tmp_path / "list.txt").write_text("\n  \n")
    r = run(tmp_path, *base(tmp_path, q, "--files-from", str(tmp_path / "list.txt")), "--", str(v), "run")
    assert r.returncode == 3, r
    assert not (tmp_path / "argv.json").exists()
    st = json.loads((tmp_path / "s.json").read_text())
    assert st["state"] == "refused" and "EMPTY LIST" in st["lines"][-1]


def test_e2_vitest_with_no_file_operand_is_refused(tmp_path):
    v, q = fake_vitest(tmp_path), qstate(tmp_path)
    for sub in ("run", "related"):
        r = run(tmp_path, *base(tmp_path, q), "--", str(v), sub, "--maxWorkers", "4", "--config", "vitest.config.ts")
        assert r.returncode == 3, (sub, r)
        assert not (tmp_path / "argv.json").exists()


def test_e3_whole_suite_said_runs(tmp_path):
    v, q = fake_vitest(tmp_path), qstate(tmp_path)
    r = run(tmp_path, *base(tmp_path, q, "--whole-suite"), "--", str(v), "run")
    assert r.returncode == 0, r
    assert json.loads((tmp_path / "argv.json").read_text()) == ["run"]


def test_e4_files_substituted_at_the_token_or_appended(tmp_path):
    v, q = fake_vitest(tmp_path), qstate(tmp_path)
    (tmp_path / "list.txt").write_text("a.test.ts\nb.test.ts\n")
    r = run(tmp_path, *base(tmp_path, q, "--files-from", str(tmp_path / "list.txt")),
            "--", str(v), "related", "--run", "{files}", "--reporter=dot")
    assert r.returncode == 0, r
    assert json.loads((tmp_path / "argv.json").read_text()) == ["related", "--run", "a.test.ts", "b.test.ts",
                                                                "--reporter=dot"]
    r = run(tmp_path, *base(tmp_path, q, "--files-from", str(tmp_path / "list.txt")), "--", str(v), "run")
    assert json.loads((tmp_path / "argv.json").read_text()) == ["run", "a.test.ts", "b.test.ts"]


def test_e5_not_vitest_needs_no_file(tmp_path):
    q = qstate(tmp_path)
    r = run(tmp_path, *base(tmp_path, q), "--", sys.executable, "-c", "print('tsc stand-in')")
    assert r.returncode == 0, r


# ── L · heavy.lock ────────────────────────────────────────────────────────────────────────────────────────────────
def test_l1_lock_held_elsewhere_refuses(tmp_path):
    v, q = fake_vitest(tmp_path), qstate(tmp_path)
    fd = os.open(str(tmp_path / "heavy.lock"), os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        r = run(tmp_path, *base(tmp_path, q), "--", str(v), "run", "x.test.ts")
    finally:
        os.close(fd)
    assert r.returncode == 4, r
    assert not (tmp_path / "argv.json").exists()


def test_l2_no_lock_named_is_usage(tmp_path):
    v, q = fake_vitest(tmp_path), qstate(tmp_path)
    r = run(tmp_path, "run", "--state", str(tmp_path / "s.json"), "--queue-state", str(q), "--", str(v), "run", "x.ts")
    assert r.returncode == 2 and not (tmp_path / "argv.json").exists()
    r = run(tmp_path, "run", "--state", str(tmp_path / "s.json"), "--queue-state", str(q), "--", str(v), "run", "x.ts",
            env_extra={"HEAVY_LOCK": str(tmp_path / "heavy.lock")})
    assert r.returncode == 0, r


def test_l3_lock_held_by_an_ancestor_is_proven(tmp_path):
    v, q = fake_vitest(tmp_path), qstate(tmp_path)
    lock = tmp_path / "heavy.lock"
    lock.touch()
    args = ("run", "--state", str(tmp_path / "s.json"), "--lock-held", str(lock), "--queue-state", str(q),
            "--", str(v), "run", "x.test.ts")
    r = run(tmp_path, *args, cmd_prefix=("flock", str(lock)))
    assert r.returncode == 0, r
    (tmp_path / "argv.json").unlink()
    r = run(tmp_path, *args)                                 # not under flock: refused
    assert r.returncode == 4, r
    assert not (tmp_path / "argv.json").exists()


# ── G · workers beside a live route ───────────────────────────────────────────────────────────────────────────────
def test_g1_live_route_caps_workers(tmp_path):
    v = fake_vitest(tmp_path)
    for q in (qstate(tmp_path, "1008-x.md", "x\n🧾 Pre-merge gate on orch-1008: 2 file(s)\n"),   # gating
              qstate(tmp_path, "1008-x.md", "Firing Toni\n"),                                    # executor phase
              qstate(tmp_path, full={"repo": "clinical-mp"})):                                   # nightly full gate
        r = run(tmp_path, *base(tmp_path, q), "--", str(v), "run", "--maxWorkers=10", "x.test.ts")
        assert r.returncode == 0, r
        assert json.loads((tmp_path / "argv.json").read_text()) == ["run", "--maxWorkers=2", "x.test.ts"]
    r = run(tmp_path, *base(tmp_path, q), "--", str(v), "related", "--run", "x.ts")           # none given: added
    assert json.loads((tmp_path / "argv.json").read_text()) == ["related", "--maxWorkers=2", "--run", "x.ts"]


def test_g2_idle_keeps_workers_and_unknown_caps(tmp_path):
    v = fake_vitest(tmp_path)
    q = qstate(tmp_path, "1008-x.md", "🧾 Pre-merge gate on orch\n🏁 FINAL STATUS: passed\n")
    assert heavy_leg.daemon_phase(q)[0] == "executor"
    q = qstate(tmp_path)
    r = run(tmp_path, *base(tmp_path, q), "--", str(v), "run", "--maxWorkers", "10", "x.test.ts")
    assert json.loads((tmp_path / "argv.json").read_text()) == ["run", "--maxWorkers", "10", "x.test.ts"]
    q.write_text("{not json")
    assert heavy_leg.daemon_phase(q)[0] == "unknown"
    r = run(tmp_path, *base(tmp_path, q), "--", str(v), "run", "--maxWorkers", "10", "x.test.ts")
    assert r.returncode == 0
    assert json.loads((tmp_path / "argv.json").read_text()) == ["run", "--maxWorkers", "2", "x.test.ts"]


def test_g3_gate_starting_mid_leg_is_noted(tmp_path):
    q = qstate(tmp_path, "1008-x.md", "Firing Toni\n")
    go = tmp_path / "go"
    p = subprocess.Popen([sys.executable, str(HL), *base(tmp_path, q), "--", sys.executable, "-c",
                          "import os, time\nwhile not os.path.exists(%r): time.sleep(0.05)\ntime.sleep(1)" % str(go)])
    for _ in range(200):                                     # the leg is running (phase at start read) before the gate
        st = json.loads((tmp_path / "s.json").read_text()) if (tmp_path / "s.json").exists() else {}
        if st.get("state") == "running":
            break
        time.sleep(0.05)
    assert st.get("state") == "running" and st["phase_at_start"].startswith("executor")
    (tmp_path / "orch.log").write_text("Firing Toni\n🧾 Pre-merge gate on orch-1008\n")
    go.touch()
    assert p.wait(timeout=30) == 0
    lines = json.loads((tmp_path / "s.json").read_text())["lines"]
    assert any("gate started while the leg runs" in ln for ln in lines), lines


# ── K · stop by id, never a pattern ───────────────────────────────────────────────────────────────────────────────
def test_k1_stop_ends_the_legs_group_only(tmp_path):
    q = qstate(tmp_path)
    marker = "hl-k1-%d" % os.getpid()
    decoy = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)", marker], start_new_session=True)
    leg = subprocess.Popen([sys.executable, str(HL), *base(tmp_path, q), "--", "bash", "-c",
                            "sleep 60 & %s -c 'import time; time.sleep(60)' %s; wait" % (sys.executable, marker)])
    try:
        for _ in range(100):
            st = json.loads((tmp_path / "s.json").read_text()) if (tmp_path / "s.json").exists() else {}
            if st.get("state") == "running":
                break
            time.sleep(0.1)
        assert st.get("state") == "running"
        r = run(tmp_path, "stop", "--state", str(tmp_path / "s.json"))
        assert r.returncode == 0, r
        assert leg.wait(timeout=20) != 0
        with pytest.raises(ProcessLookupError):
            os.killpg(st["pgid"], 0)
        assert decoy.poll() is None                          # same words on its command line, other group: alive
    finally:
        decoy.kill()
        leg.kill()


def test_k2_stop_with_nothing_running_does_nothing(tmp_path):
    (tmp_path / "s.json").write_text(json.dumps({"state": "done", "pgid": 99999, "pid": 99999}))
    r = run(tmp_path, "stop", "--state", str(tmp_path / "s.json"))
    assert r.returncode == 0 and "nothing stopped" in r.stdout


# ── V · prefire's VERIFY line (L-561) ─────────────────────────────────────────────────────────────────────────────
def test_v1_no_report_says_none_never_a_tick(tmp_path):
    b = tmp_path / "b.md"
    b.write_text("#!queue repo=orchestrator\n# X\n")
    line = prefire.verify_line(b)
    assert line.startswith(prefire.VERIFY_NONE + ":") and "✅" not in line and "L-561" in line


def test_v2_a_named_report_keeps_its_tick(tmp_path):
    rep = tmp_path / "v.md"
    rep.write_text("ok\n")
    b = tmp_path / "b.md"
    b.write_text("#!queue repo=orchestrator\n# X\n## Verify report: %s\n" % rep)
    assert prefire.verify_line(b) == "VERIFY ✅ v.md — every claim has a run beside it"

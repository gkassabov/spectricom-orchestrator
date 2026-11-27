"""[PATTERN-KILL-DENY-1] the executor's Bash hook refuses pattern kills (L-563, rule #27) and
[HANDBACK-FORMAT-MISS-1] `verify` records a handback format miss (L-557, rule #15 (k)). Tmp dirs only."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LONG_WAIT = ROOT / "executor" / "hooks" / "long_wait.py"
import orchestrator  # noqa: E402


def _hook(command, env_extra=None):
    env = {k: v for k, v in os.environ.items() if k not in ("TONI_LONG_WAIT", "TONI_PATTERN_KILL")}
    env.update(env_extra or {})
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/tmp"})
    return subprocess.run([sys.executable, str(LONG_WAIT)], input=stdin, capture_output=True, text=True, env=env,
                          timeout=30)


KILLS = [
    # refused: a name / pattern decides what dies
    ("pkill -f 'vitest related'", 2), ("pkill node", 2), ("killall node", 2), ("sudo pkill -9 -f vitest", 2),
    ("cd /tmp && timeout 5 pkill -f x", 2), ("pgrep -f vitest | xargs kill", 2), ("pgrep -f x | xargs -r kill -9", 2),
    ("kill $(pgrep -f vitest)", 2), ("kill -9 `pidof node`", 2), ("for p in $(pgrep node); do kill $p; done", 2),
    ("bash -c 'pgrep -f x | xargs kill'", 2), ("/usr/bin/pkill -f x", 2),
    # allowed: by id, or only looking
    ("kill 12345", 0), ("kill -TERM -- -12345", 0), ("kill -0 $PID", 0), ("pgrep -f vitest", 0),
    ("pgrep -af node; ps -o pid,args -p 1", 0), ("ps -o pid= --ppid 5 | xargs kill", 0),
    ("echo 'never pkill -f x'", 0), ("git commit -m \"pgrep -f x | xargs kill is banned\"", 0),
    ("cat > notes.md <<'EOF'\npkill -f x\nEOF", 0), ("grep -n pkill LESSONS.md", 0),
]


@pytest.mark.parametrize("command, rc", KILLS)
def test_pk1_pattern_kills_are_refused_and_id_kills_are_not(command, rc):
    r = _hook(command)
    assert r.returncode == rc, (command, r.stderr)
    if rc == 2:
        (line,) = r.stderr.strip().splitlines()
        assert line.startswith("🛡 pattern kill: ") and "rule #27, L-563" in line, line
    else:
        assert r.stderr == ""


def test_pk2_the_switches():
    assert _hook("pkill -f x", {"TONI_PATTERN_KILL": " Off "}).returncode == 0
    assert _hook("pkill -f x", {"TONI_LONG_WAIT": "off"}).returncode == 0
    r = _hook("pkill -f x; sleep 900", {"TONI_PATTERN_KILL": "off"})     # the wait half still judges
    assert r.returncode == 2 and r.stderr.startswith("🛡 long wait:")


def test_pk3_long_wait_unchanged_beside_it():
    assert _hook("sleep 900").stderr.startswith("🛡 long wait: sleep 900")
    assert _hook("sleep 30").returncode == 0


# ── handback format miss ───────────────────────────────────────────────────────────────────────────────────────────
HB = "briefs/00000988-x.handback.md"


def test_fm1_not_committed_is_a_miss():
    (m,) = orchestrator.handback_format_misses("00000988-x", "5c8097f", HB, None)
    assert "is not committed at 5c8097f" in m and HB in m


def test_fm2_no_status_line_is_a_miss_and_a_status_is_not():
    (m,) = orchestrator.handback_format_misses("s", "abc1234", HB, "# Handback\n\nall good\n")
    assert "no `## STATUS` line" in m
    for text in ("## STATUS: DONE\n", "# H\n**Status:** STOP (b)\n", "Route status: PARTIAL\n"):
        assert orchestrator.handback_format_misses("s", "abc1234", HB, text) == [], text


def test_fm3_a_miss_is_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(orchestrator, "LOG_DIR", tmp_path / "logs")
    orchestrator._record_format_miss("00000988-x", "orchestrator", "5c8097f", "m1")
    orchestrator._record_format_miss("00000989-y", "clinical-mp", "abcdef0", "m2")
    rows = [json.loads(l) for l in (tmp_path / "logs" / "opx" / "format-misses.ndjson").read_text().splitlines()]
    assert [(r["stem"], r["repo"], r["sha"], r["miss"], r["source"]) for r in rows] == [
        ("00000988-x", "orchestrator", "5c8097f", "m1", "verify"), ("00000989-y", "clinical-mp", "abcdef0", "m2", "verify")]


def test_fm4_an_unwritable_log_changes_nothing(tmp_path, monkeypatch, capsys):
    (tmp_path / "logs").write_text("a file, not a dir")
    monkeypatch.setattr(orchestrator, "LOG_DIR", tmp_path / "logs")
    orchestrator._record_format_miss("s", "r", "x", "m")
    assert "format-miss log not written" in capsys.readouterr().out

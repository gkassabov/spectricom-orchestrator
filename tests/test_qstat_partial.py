"""ORCH-QSTAT-PARTIAL-1 (Kanban 512): a finished route's outcome is read from its own log — the last FINAL STATUS line,
its gate, the handback STATUS line and the merge line — so the status view never says "nothing merged" of a PARTIAL merge
or "FAILED" of an environment block (341f1, 341f3, 2026-10-31).
QP-1 the six outcomes from planted logs whose lines are copied from real route logs
QP-2 the last FINAL STATUS line wins; a log with none, an unreadable log and no log read "unknown (…)"
QP-3 `status --json` carries `outcome` on every completed / failed / stopped / held entry; nothing else in an entry changes
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import queue_daemon  # noqa: E402

MERGED_MP = "13:50:24 [INFO   ] 🔀 Merged orch-mp-000000814-x-1 → main (b92a2e9 → 3fa9c22)\n"
MERGED_SELF = "23:01:53 [INFO   ] ✅ Self-mod auto-merge: brought 2 commits to main\n"
NO_MERGE_SELF = "23:01:53 [INFO   ] Self-mod auto-merge: no commits to bring in; skipping\n"


def final(status: str, gate: str) -> str:
    return f"23:01:53 [INFO   ] 🏁 FINAL STATUS: {status} | gate: {gate} | unit: baseline known red\n"


def handback(status: str) -> str:
    return f'  handback STATUS: {status} — "## STATUS: {status}"\n'


CASES = [
    ("passed-merged", final("passed", "PASS") + MERGED_MP, "merged"),
    ("partial-merged", final("stopped", "PASS") + handback("PARTIAL") + MERGED_SELF, "merged (partial)"),
    ("stop-merged", final("stopped", "PASS") + handback("STOP (d)") + MERGED_MP, "merged (handback STOP (d))"),
    ("stop-nothing", final("stopped", "PASS") + handback("STOP (d)") + NO_MERGE_SELF,
     "stopped, nothing merged (handback STOP (d))"),
    ("blocked-env", final("blocked", "BLOCKED(environment) — build: clock-implausible (Δwall 166.0s)"), "blocked (environment)"),
    ("failed", final("failed", "FAIL(product) — sit: exit 1"), "failed"),
    ("incomplete", final("incomplete", "not run"), "incomplete, nothing merged"),
    ("held", final("held", "PASS"), "held for a human merge"),
]


@pytest.mark.parametrize("name,text,want", CASES, ids=[c[0] for c in CASES])
def test_QP1_outcomes(tmp_path, name, text, want):
    log = tmp_path / f"orch-{name}.log"
    log.write_text("09:00:00 [INFO   ] route start\n" + text + "Finished: 2026-11-21T13:50:25\nExit: 0\n", encoding="utf-8")
    assert queue_daemon.route_outcome(str(log)) == want


def test_QP2_last_line_wins_and_unknowns(tmp_path):
    log = tmp_path / "orch-regate.log"
    log.write_text(final("blocked", "BLOCKED(environment) — sit: timeout") + final("passed", "PASS") + MERGED_MP, encoding="utf-8")
    assert queue_daemon.route_outcome(str(log)) == "merged"
    none = tmp_path / "orch-none.log"
    none.write_text("no verdict here\nExit: 1\n", encoding="utf-8")
    assert queue_daemon.route_outcome(str(none)) == "unknown (no FINAL STATUS line)"
    assert queue_daemon.route_outcome(str(tmp_path / "missing.log")).startswith("unknown (log unreadable: ")
    assert queue_daemon.route_outcome(None) == "unknown (no log file recorded)"
    big = tmp_path / "orch-big.log"
    big.write_text("x" * (queue_daemon.ROUTE_LOG_TAIL_BYTES * 2) + "\n" + final("stopped", "PASS") + handback("PARTIAL") + MERGED_MP,
                   encoding="utf-8")
    assert queue_daemon.route_outcome(str(big)) == "merged (partial)", "the tail holds the verdict"


def test_QP3_status_entries_carry_outcome(tmp_path, monkeypatch):
    logs = {}
    for name, text, _ in CASES[:6]:
        p = tmp_path / f"orch-{name}.log"
        p.write_text(text, encoding="utf-8")
        logs[name] = str(p)
    d = queue_daemon.QueueDaemon.__new__(queue_daemon.QueueDaemon)
    entry = lambda n, code: {"file": f"{n}.md", "exit_code": code, "duration_s": 1.0, "log_file": logs[n]}  # noqa: E731
    d.completed = [entry("passed-merged", 0)]
    d.stopped = [dict(entry("partial-merged", 5), status="stopped"), dict(entry("stop-nothing", 5), status="stopped")]
    d.failed = [entry("blocked-env", 1), entry("failed", 1)]
    d.held = []
    before = json.dumps([d.completed, d.stopped, d.failed], sort_keys=True)
    import threading
    d.lock = threading.RLock()
    for attr, val in (("status", "running"), ("paused_reason", None), ("paused_at", None), ("waiting", None),
                      ("depends_waiting", {}), ("park_waiting", {}), ("started_at", None), ("current_batch", None),
                      ("refused", []), ("config", {}), ("consecutive_count", 0)):
        setattr(d, attr, val)
    monkeypatch.setattr(d, "_scan_queue", lambda: [], raising=False)
    st = d.get_status()
    got = {e["file"]: e["outcome"] for k in ("completed", "stopped", "failed", "held") for e in st[k]}
    print(f"[QP-3] {json.dumps(got)}")
    assert got == {
        "passed-merged.md": "merged",
        "partial-merged.md": "merged (partial)",
        "stop-nothing.md": "stopped, nothing merged (handback STOP (d))",
        "blocked-env.md": "blocked (environment)",
        "failed.md": "failed",
    }
    assert "nothing merged" not in got["partial-merged.md"] and "FAILED" not in got["blocked-env.md"].upper()
    assert json.dumps([d.completed, d.stopped, d.failed], sort_keys=True) == before, "the stored entries are not changed"
    for k in ("completed", "stopped", "failed"):
        for e in st[k]:
            assert {key: v for key, v in e.items() if key != "outcome"} in getattr(d, k)

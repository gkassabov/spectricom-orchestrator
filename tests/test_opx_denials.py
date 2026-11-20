"""ORCH-OPX-DENIALS-1 (Kanban 760; 622 slice 2 of 2; RM-OPS-04-F-01 + RM-OPS-24P-F-01; T-OPX-03; C-OPX04).

  D1  executor/hooks/kill_switch.sh logs every denial to logs/opx/denials.ndjson, best effort — the verdict never moves
  D2  executor/hooks/denial_log.py logs permissions.deny refusals from the transcript, once per tool_use_id, never blocks
  D3  the denial burst: n within window_s writes KILL; unset (the shipped config) is off; a present KILL is kept
  D4  every executor settings file runs the denial logger on Stop and SessionEnd, exit 0 whatever happens
  D5  scripts/opx5.py prints the EOS §9 row: cell 5 from the log, the rest `not measured — <reason>`, never a bare 0
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "executor" / "hooks"))
sys.path.insert(0, str(ROOT / "scripts"))
import denial_log  # noqa: E402
import opx5  # noqa: E402

KILL_HOOK = ROOT / "executor" / "hooks" / "kill_switch.sh"
LOGGER = ROOT / "executor" / "hooks" / "denial_log.py"
SETTINGS = ROOT / "executor" / "settings"
REPOS = sorted(yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"])
DENIAL_CMD = ('f="${TONI_GUARDS_HOME:-$HOME/spectricom-orchestrator}/executor/hooks/denial_log.py"; '
              '[ -r "$f" ] && command -v python3 >/dev/null && python3 "$f"; exit 0')
BASH_DENIED = "Permission to use Bash with command cat secret.txt has been denied."
READ_DENIED = "<tool_use_error>File is in a directory that is denied by your permission settings.</tool_use_error>"


def _lines(sdir: Path) -> list:
    p = sdir / "logs" / "opx" / "denials.ndjson"
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()] if p.exists() else []


# ── D1 · the kill hook logs its denials ─────────────────────────────────────
def _kill_hook(env: dict):
    return subprocess.run(["bash", str(KILL_HOOK)], env={"PATH": os.environ["PATH"], **env},
                          input='{"tool_name":"Bash"}', capture_output=True, text=True, timeout=20)


def test_D1_a_KILL_denial_is_logged_and_still_denied(tmp_path):
    (tmp_path / "KILL").write_text("{}")
    r = _kill_hook({"TONI_GUARDS_HOME": str(tmp_path)})
    assert r.returncode == 2
    [line] = _lines(tmp_path)
    assert line["source"] == "kill-hook" and "KILL exists" in line["reason"]
    assert datetime.strptime(line["at"], "%Y-%m-%dT%H:%M:%SZ")


def test_D1_an_allowed_call_logs_nothing(tmp_path):
    r = _kill_hook({"TONI_GUARDS_HOME": str(tmp_path)})
    assert r.returncode == 0
    assert not (tmp_path / "logs").exists()


def test_D1_a_log_that_cannot_be_written_changes_nothing(tmp_path):
    (tmp_path / "KILL").write_text("{}")
    (tmp_path / "logs").write_text("a file where the logs dir would go")
    r = _kill_hook({"TONI_GUARDS_HOME": str(tmp_path)})
    assert r.returncode == 2
    assert "every tool call is denied" in r.stderr


def test_D1_no_state_dir_denies_without_a_log(tmp_path):
    r = _kill_hook({"TONI_GUARDS_HOME": str(tmp_path / "missing")})
    assert r.returncode == 2
    assert not (tmp_path / "missing").exists()


# ── D2 · the permissions.deny logger ────────────────────────────────────────
def _transcript(tmp_path: Path, results: list) -> Path:
    """A CLI-shaped session transcript: one assistant tool_use and one user tool_result per (id, name, text, err)."""
    p = tmp_path / "session.jsonl"
    rows = []
    for tid, name, text, err in results:
        rows.append({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": tid, "name": name,
                                                                   "input": {}}]}})
        rows.append({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tid,
                                                              "content": text, "is_error": err}]}})
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    return p


def _run_logger(sdir: Path, stdin: str):
    return subprocess.run([sys.executable, str(LOGGER)], env={"PATH": os.environ["PATH"],
                          "TONI_GUARDS_HOME": str(sdir)}, input=stdin, capture_output=True, text=True, timeout=20)


def test_D2_both_refusal_shapes_are_logged_with_their_tool(tmp_path):
    t = _transcript(tmp_path, [("t1", "Read", READ_DENIED, True), ("t2", "Bash", BASH_DENIED, True),
                               ("t3", "Bash", "exit code 1: no such file", True), ("t4", "Bash", BASH_DENIED, False)])
    r = _run_logger(tmp_path, json.dumps({"transcript_path": str(t), "session_id": "s-1"}))
    assert r.returncode == 0
    lines = _lines(tmp_path)
    assert [(l["tool_use_id"], l["tool"], l["source"]) for l in lines] == [("t1", "Read", "permissions.deny"),
                                                                         ("t2", "Bash", "permissions.deny")]
    assert lines[0]["detail"] == "File is in a directory that is denied by your permission settings."
    assert lines[1]["session_id"] == "s-1"


def test_D2_a_second_run_on_the_same_transcript_adds_nothing(tmp_path):
    t = _transcript(tmp_path, [("t1", "Bash", BASH_DENIED, True)])
    stdin = json.dumps({"transcript_path": str(t)})
    _run_logger(tmp_path, stdin)
    _run_logger(tmp_path, stdin)
    assert len(_lines(tmp_path)) == 1


def test_D2_list_shaped_content_is_read(tmp_path):
    t = _transcript(tmp_path, [("t1", "Bash", [{"type": "text", "text": BASH_DENIED}], True)])
    _run_logger(tmp_path, json.dumps({"transcript_path": str(t)}))
    assert [l["tool_use_id"] for l in _lines(tmp_path)] == ["t1"]


@pytest.mark.parametrize("stdin", ["", "not json", '{"transcript_path": "/no/such/file"}', "{}"])
def test_D2_never_blocks_and_always_leaves_the_log_file(tmp_path, stdin):
    r = _run_logger(tmp_path, stdin)
    assert r.returncode == 0
    assert (tmp_path / "logs" / "opx" / "denials.ndjson").exists()


def test_D2_an_unwritable_state_dir_still_exits_0(tmp_path):
    (tmp_path / "logs").write_text("not a dir")
    r = _run_logger(tmp_path, "{}")
    assert r.returncode == 0
    assert "denial log: not written" in r.stderr


# ── D3 · the denial burst ───────────────────────────────────────────────────
def _with_burst(monkeypatch, tmp_path, n, window_s):
    cfg = tmp_path / "opx-denials.json"
    cfg.write_text(json.dumps({"version": 1, "burst": {"n": n, "window_s": window_s}}))
    monkeypatch.setattr(denial_log, "CONFIG", cfg)


def test_D3_the_shipped_config_is_off():
    assert json.loads((ROOT / "config" / "opx-denials.json").read_text())["burst"] == {"n": None, "window_s": None}
    assert denial_log.burst_config() == (None, None)


def test_D3_n_denials_within_the_window_write_KILL(monkeypatch, tmp_path):
    sdir = tmp_path / "orch"
    _with_burst(monkeypatch, tmp_path, 2, 600)
    monkeypatch.setenv("TONI_GUARDS_HOME", str(sdir))
    t = _transcript(tmp_path, [("t1", "Bash", BASH_DENIED, True), ("t2", "Read", READ_DENIED, True)])
    assert denial_log.main(json.dumps({"transcript_path": str(t)})) == 0
    kill = json.loads((sdir / "KILL").read_text())
    assert kill["reason"].startswith("denial burst: 2 permission denials within 600s")
    assert "denial_log.py" in kill["by"]
    assert "KILL written" in (sdir / "logs" / "kill-switch.log").read_text()


def test_D3_below_n_or_outside_the_window_no_KILL(monkeypatch, tmp_path):
    sdir = tmp_path / "orch"
    _with_burst(monkeypatch, tmp_path, 3, 60)
    monkeypatch.setenv("TONI_GUARDS_HOME", str(sdir))
    log = sdir / "logs" / "opx" / "denials.ndjson"
    log.parent.mkdir(parents=True)
    old = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    log.write_text(json.dumps({"at": old, "source": "permissions.deny", "tool_use_id": "old"}) + "\n")
    t = _transcript(tmp_path, [("t1", "Bash", BASH_DENIED, True), ("t2", "Read", READ_DENIED, True)])
    denial_log.main(json.dumps({"transcript_path": str(t)}))
    assert not (sdir / "KILL").exists()


def test_D3_kill_hook_denials_do_not_count_toward_a_burst(monkeypatch, tmp_path):
    sdir = tmp_path / "orch"
    _with_burst(monkeypatch, tmp_path, 2, 600)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [{"at": now, "source": "kill-hook"}, {"at": now, "source": "kill-hook"},
             {"at": now, "source": "permissions.deny"}]
    (sdir / "logs").mkdir(parents=True)
    assert denial_log.maybe_burst_kill(sdir, lines, datetime.now(timezone.utc)) is False


def test_D3_a_present_KILL_is_kept_with_its_first_reason(monkeypatch, tmp_path):
    sdir = tmp_path / "orch"
    _with_burst(monkeypatch, tmp_path, 1, 600)
    (sdir / "logs").mkdir(parents=True)
    (sdir / "KILL").write_text('{"reason": "george"}')
    now = datetime.now(timezone.utc)
    lines = [{"at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "source": "permissions.deny"}]
    assert denial_log.maybe_burst_kill(sdir, lines, now) is False
    assert json.loads((sdir / "KILL").read_text())["reason"] == "george"


@pytest.mark.parametrize("burst", [{"n": 0, "window_s": 60}, {"n": 2, "window_s": None}, {"n": True, "window_s": 9},
                                   {"n": "2", "window_s": 60}, None])
def test_D3_anything_but_two_positive_numbers_is_off(monkeypatch, tmp_path, burst):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"burst": burst}))
    monkeypatch.setattr(denial_log, "CONFIG", cfg)
    assert denial_log.burst_config() == (None, None)


# ── D4 · wired in every settings file ───────────────────────────────────────
@pytest.mark.parametrize("repo", REPOS)
@pytest.mark.parametrize("event", ["Stop", "SessionEnd"])
def test_D4_every_settings_file_runs_the_logger(repo, event):
    cfg = json.loads((SETTINGS / f"{repo}.json").read_text())
    assert cfg["hooks"][event] == [{"hooks": [{"type": "command", "command": DENIAL_CMD}]}]


def test_D4_the_wired_command_exits_0_even_with_no_logger(tmp_path):
    r = subprocess.run(["bash", "-c", DENIAL_CMD], env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)},
                       input="{}", capture_output=True, text=True, timeout=20)
    assert r.returncode == 0


# ── D5 · the OPX-5 row ──────────────────────────────────────────────────────
def test_D5_the_row_has_seven_cells_and_no_bare_zero_for_an_unmeasured_metric(tmp_path):
    since = datetime(2026, 11, 19, tzinfo=timezone.utc)
    r = opx5.row("S7-CORE-57", tmp_path, since, since + timedelta(days=1))
    cells = [c.strip() for c in r.strip("|").split("|")]
    assert len(cells) == 7 and cells[:2] == ["OPX-5", "S7-CORE-57"]
    for c in cells[2:6]:
        assert "not measured — " in c and " 0" not in c
    assert "sandbox: not running (392)" in cells[6]
    assert "hook denials not measured — logs/opx/denials.ndjson absent" in cells[6]


def test_D5_cell_5_counts_the_window_by_source(tmp_path):
    log = tmp_path / "logs" / "opx" / "denials.ndjson"
    log.parent.mkdir(parents=True)
    rows = [("2026-11-19T10:00:00Z", "kill-hook"), ("2026-11-19T11:00:00Z", "permissions.deny"),
            ("2026-11-19T12:00:00Z", "permissions.deny"), ("2026-11-18T12:00:00Z", "permissions.deny")]
    log.write_text("\n".join(json.dumps({"at": a, "source": s}) for a, s in rows) + "\ngarbage\n")
    since = datetime(2026, 11, 19, tzinfo=timezone.utc)
    cell = opx5.denial_cell(tmp_path, since, since + timedelta(days=1))
    assert "hook denials 3 (kill-hook 1, permissions.deny 2;" in cell
    assert "1 unreadable line(s) skipped" in cell


def test_D5_an_empty_log_is_a_measured_zero(tmp_path):
    log = tmp_path / "logs" / "opx" / "denials.ndjson"
    log.parent.mkdir(parents=True)
    log.write_text("")
    since = datetime(2026, 11, 19, tzinfo=timezone.utc)
    assert "hook denials 0 (kill-hook 0, permissions.deny 0;" in opx5.denial_cell(tmp_path, since, since)


def test_D5_the_cli_prints_one_row(tmp_path):
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "opx5.py"), "--session", "S7-CORE-57", "--since",
                        "2026-11-19T00:00:00", "--until", "2026-11-20T00:00:00", "--orch-dir", str(tmp_path)],
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0
    assert r.stdout.startswith("| OPX-5 | S7-CORE-57 | CFR not measured")
    bad = subprocess.run([sys.executable, str(ROOT / "scripts" / "opx5.py"), "--session", "x", "--since",
                          "2026-11-20T00:00:00", "--until", "2026-11-19T00:00:00", "--orch-dir", str(tmp_path)],
                         capture_output=True, text=True, timeout=20)
    assert bad.returncode == 2

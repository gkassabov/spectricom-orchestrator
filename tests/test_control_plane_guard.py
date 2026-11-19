"""[ORCH-GUARD-HARDEN-1] Kanban 621 slice 1 (RM-OPS-01-F-02 + RM-OPS-03-F-01; T-OPX-02; C-OPX02) — predicates
C-1..C-8 of briefs/000000621-orch-guard-harden-1.md:

  C-1  every executor/settings/<repo>.json denies Edit/Write on the orchestrator control plane (KILL, queue, logs,
       state, the guard data files, config/, executor/)
  C-2  (control) the S7-CORE-33 deny entries and the orchestrator file's queue/ logs/ read allows are unchanged
  C-3  every settings file runs executor/hooks/config_change.sh on ConfigChange, fail closed (`|| exit 2`)
  C-4  config_change.sh blocks (exit 2, a stderr line naming the source) every mid-fire settings or skills change,
       and blocks on empty or unreadable input (fails closed)
  C-5  prefire_opex_paths.json: canon_assert.py and config/** on OPX-3's orchestrator list; queue_daemon.py on
       OPX-2's orchestrator list
  C-6  prefire: an orchestrator brief naming config/repos.yaml or canon_assert.py with no George go is refused (OPX-3)
  C-7  prefire: an orchestrator brief naming queue_daemon.py with no policy id is refused (OPX-2); AP-ORCH passes
  C-8  (control) near names are not matched

Nothing here starts a real `claude`. The ConfigChange contract (exit 2 blocks the change; other non-zero exits only
show stderr) is the CLI's own hook description, read from Claude Code 2.1.322.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import prefire  # noqa: E402,F401
from test_opex_prefire import brief, canon, opex  # noqa: E402,F401  (canon: the autouse scratch canon)

SETTINGS = ROOT / "executor" / "settings"
HOOK = ROOT / "executor" / "hooks" / "config_change.sh"
REPOS = sorted(yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"])
ORCH = "~/spectricom-orchestrator"
CONTROL_PLANE = [f"{ORCH}/KILL", f"{ORCH}/queue/**", f"{ORCH}/logs/**", f"{ORCH}/state/**",
                 f"{ORCH}/executor/**", f"{ORCH}/config/**", f"{ORCH}/prefire_opex_paths.json",
                 f"{ORCH}/rate-caps.json", f"{ORCH}/rate-limits.json", f"{ORCH}/queue-state.json",
                 f"{ORCH}/running*.json"]
HOOK_CMD = ('f="${TONI_GUARDS_HOME:-$HOME/spectricom-orchestrator}/executor/hooks/config_change.sh"; '
            '[ -r "$f" ] || { echo "🛡 config change: the hook could not run (no $f) — the change is blocked '
            '(fails closed)." >&2; exit 2; }; bash "$f" || exit 2')
SOURCES = ["user_settings", "project_settings", "local_settings", "policy_settings", "skills"]
INVENTORY = ("# SCP Agent Inventory — v0-1\n\n| Policy ID | Agent |\n|---|---|\n"
             "| `AP-ORCH` | orchestrator |\n| `AP-TONI` | executor |\n")
GO = '## George go: E1 standing go — George 2026-11-19 15:26 ET "Yes on the process fix" (D-S7CORE57-01)\n'


def _settings(repo):
    return json.loads((SETTINGS / f"{repo}.json").read_text())


# ── C-1 · the control plane is not editable from any repo's fire ─────────────
@pytest.mark.parametrize("repo", REPOS)
@pytest.mark.parametrize("path", CONTROL_PLANE)
def test_C1_every_file_denies_edit_on_the_control_plane(repo, path):
    assert f"Edit({path})" in _settings(repo)["permissions"]["deny"]


# ── C-2 · controls: what was there stays ────────────────────────────────────
@pytest.mark.parametrize("repo", REPOS)
def test_C2_control_the_preflight_deny_and_the_kill_hook_stay(repo):
    cfg = _settings(repo)
    assert f"Edit({ORCH}/state/preflight/**)" in cfg["permissions"]["deny"]
    assert any("kill_switch.sh" in h["command"] for e in cfg["hooks"]["PreToolUse"] for h in e["hooks"])


def test_C2_control_the_orchestrator_file_still_reads_its_queue_and_logs():
    assert _settings("orchestrator")["permissions"]["allow"] == [f"Read({ORCH}/queue/**)", f"Read({ORCH}/logs/**)"]


# ── C-3 · the ConfigChange hook is wired, fail closed ───────────────────────
@pytest.mark.parametrize("repo", REPOS)
def test_C3_every_file_runs_the_config_change_hook(repo):
    entries = _settings(repo)["hooks"].get("ConfigChange")
    assert entries == [{"matcher": "*", "hooks": [{"type": "command", "command": HOOK_CMD}]}]


# ── C-4 · the hook blocks every mid-fire change, and fails closed ───────────
def _run(stdin, env=None):
    return subprocess.run(["bash", str(HOOK)], input=stdin, capture_output=True, text=True, timeout=20,
                          env={"PATH": os.environ["PATH"], **(env or {})})


@pytest.mark.parametrize("source", SOURCES)
def test_C4_a_change_from_any_source_is_blocked(source):
    r = _run(json.dumps({"hook_event_name": "ConfigChange", "source": source, "file_path": "/x/settings.json"}))
    assert r.returncode == 2
    assert source in r.stderr and "ORCH-GUARD-HARDEN-1" in r.stderr


@pytest.mark.parametrize("stdin", ["", "not json", "[]", '{"hook_event_name":"ConfigChange"}'])
def test_C4_empty_or_unreadable_input_still_blocks(stdin):
    r = _run(stdin)
    assert r.returncode == 2 and "ORCH-GUARD-HARDEN-1" in r.stderr


def test_C4_the_settings_command_fails_closed_when_the_hook_is_missing(tmp_path):
    r = subprocess.run(["bash", "-c", HOOK_CMD], input="{}", capture_output=True, text=True, timeout=20,
                       env={"PATH": os.environ["PATH"], "HOME": str(tmp_path)})
    assert r.returncode == 2 and "fails closed" in r.stderr


# ── C-5 · the path data ─────────────────────────────────────────────────────
def test_C5_the_guard_data_names_the_new_paths():
    d = json.loads((ROOT / "prefire_opex_paths.json").read_text())
    assert "canon_assert.py" in d["protected"]["orchestrator"]
    assert "config/**" in d["protected"]["orchestrator"]
    assert "queue_daemon.py" in d["agent_runtime"]["orchestrator"]


# ── C-6 · OPX-3 refuses the new protected paths without a go ────────────────
@pytest.mark.parametrize("path", ["config/repos.yaml", "config/handback-guard.json", "canon_assert.py"])
def test_C6_a_new_protected_path_without_a_go_is_refused(tmp_path, path):
    v = opex(brief(tmp_path, allowed="`%s`" % path, repo="orchestrator"))["OPX-3"]
    assert not v.ok and v.line.startswith("OPX-3 ❌ NEVER-AUTONOMOUS"), v.line


@pytest.mark.parametrize("path", ["config/repos.yaml", "canon_assert.py"])
def test_C6_with_a_go_it_passes(tmp_path, path):
    v = opex(brief(tmp_path, allowed="`%s`" % path, repo="orchestrator", header=GO))["OPX-3"]
    assert v.ok, v.line


# ── C-7 · OPX-2 treats queue_daemon.py as orchestrator agent-runtime ─────────
def test_C7_queue_daemon_without_a_policy_id_is_refused(tmp_path, canon):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(INVENTORY)
    v = opex(brief(tmp_path, allowed="`queue_daemon.py`", repo="orchestrator", header=GO))["OPX-2"]
    assert not v.ok and "queue_daemon.py (queue_daemon.py)" in v.line, v.line


def test_C7_queue_daemon_with_ap_orch_passes(tmp_path, canon):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(INVENTORY)
    b = brief(tmp_path, allowed="`queue_daemon.py`", repo="orchestrator", header=GO + "## Agent policy: AP-ORCH\n")
    assert opex(b)["OPX-2"].ok


# ── C-8 · controls: near names are not matched ──────────────────────────────
@pytest.mark.parametrize("path", ["configs/x.yaml", "tests/test_canon_assert.py", "docs/config.md"])
def test_C8_control_near_names_are_not_protected(tmp_path, path):
    assert opex(brief(tmp_path, allowed="`%s`" % path, repo="orchestrator"))["OPX-3"].ok

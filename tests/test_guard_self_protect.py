"""[ORCH-GUARD-SELF-PROTECT-1] Kanban 662, OC-4 (D-S7CORE51-20) — predicates P-A1..P-A7 of
briefs/662-663-orch-guard-self-npm-frozen-1.md Part A: the guard protects its own files (prefire.py,
prefire_opex_paths.json, queue_daemon.py, admission.py on OPX-3's orchestrator list), OPX-2 names
src/lib/agentic-ops/** as agent-runtime code, and OPX-2 with no agent inventory refuses instead of warning and passing."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import prefire  # noqa: E402
from test_opex_prefire import INVENTORY, brief, canon, opex  # noqa: E402,F401  (canon: the autouse scratch canon)

GUARDS = ["prefire.py", "prefire_opex_paths.json", "queue_daemon.py", "admission.py"]


# ── P-A1 · F-A1: the guard's own files need a George go ─────────────────────
@pytest.mark.parametrize("path", GUARDS)
def test_PA1_a_guard_file_without_a_george_go_is_refused(tmp_path, path):
    v = opex(brief(tmp_path, allowed="`%s`" % path, repo="orchestrator"))["OPX-3"]
    assert not v.ok and v.line.startswith("OPX-3 ❌ NEVER-AUTONOMOUS")
    assert "%s (%s)" % (path, path) in v.line


# ── P-A2 · F-A1: a go passes, a placeholder go does not ─────────────────────
@pytest.mark.parametrize("path", GUARDS)
def test_PA2_a_guard_file_with_george_go_passes(tmp_path, path):
    b = brief(tmp_path, allowed="`%s`" % path, repo="orchestrator", header='## George go: 2026-11-11 10:12 "oc-4 amend"\n')
    v = opex(b)["OPX-3"]
    assert v.ok and v.line.startswith("OPX-3 ✅ never-autonomous path(s) %s (%s)" % (path, path)), v.line


@pytest.mark.parametrize("path", GUARDS)
def test_PA2_a_guard_file_with_an_owed_go_is_refused(tmp_path, path):
    v = opex(brief(tmp_path, allowed="`%s`" % path, repo="orchestrator", header="## George go: OWED\n"))["OPX-3"]
    assert not v.ok and "is not a go" in v.line and "placeholder 'OWED'" in v.line


# ── P-A3 · F-A2: agentic-ops is agent-runtime code ──────────────────────────
def test_PA3_agentic_ops_without_a_policy_id_is_refused(tmp_path, canon):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(INVENTORY)
    v = opex(brief(tmp_path, allowed="`src/lib/agentic-ops/routing.ts`", repo="clinical-mp"))["OPX-2"]
    assert not v.ok and "src/lib/agentic-ops/routing.ts (src/lib/agentic-ops/**)" in v.line


def test_PA3_agentic_ops_with_a_listed_policy_id_passes(tmp_path, canon):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(INVENTORY)
    b = brief(tmp_path, allowed="`src/lib/agentic-ops/routing.ts`", repo="clinical-mp",
              header="## Agent policy: AP-DAEMON\n")
    assert opex(b)["OPX-2"].line == ("OPX-2 ✅ agent-runtime path(s) src/lib/agentic-ops/routing.ts "
                                   "(src/lib/agentic-ops/**) under AP-DAEMON (SCP_Agent_Inventory_v0-1.md)")


# ── P-A4 · F-A3: no inventory refuses (fail closed) ─────────────────────────
def test_PA4_no_inventory_refuses_with_the_exact_line(tmp_path, canon):
    b = brief(tmp_path, allowed="`src/daemon/x.ts`")
    line = ("OPX-2 ❌ AGENT-POLICY — ALLOWED FILES name agent-runtime path(s) src/daemon/x.ts (src/daemon/**) and there "
            "is no SCP_Agent_Inventory_v*.md in %s, so no policy id can be checked (fails closed; OC-4, "
            "D-S7CORE51-20)" % canon)
    assert opex(b)["OPX-2"] == prefire.OpexVerdict(False, line)
    assert line in prefire.check(b)


def test_PA4_control_no_agent_runtime_path_is_not_judged(tmp_path):
    b = brief(tmp_path, allowed="`src/components/x.tsx`")
    assert opex(b)["OPX-2"] == prefire.OpexVerdict(True, "OPX-2 ✅ no agent-runtime path in ALLOWED FILES")
    assert prefire.check(b) == []


# ── P-A5 · controls: the new globs are not widened; the file stays data ─────
@pytest.mark.parametrize("path, kind, repo", [("tests/test_prefire.py", "protected", "orchestrator"),
                                              ("tests/test_admission.py", "protected", "orchestrator"),
                                              ("tests/test_queue_daemon.py", "protected", "orchestrator"),
                                              ("src/lib/agentic-opsx/y.ts", "agent_runtime", "clinical-mp"),
                                              ("src/lib/agentic-runtime-x/y.ts", "agent_runtime", "clinical-mp")])
def test_PA5_control_near_names_are_not_matched(path, kind, repo):
    assert [g for g in prefire.opex_paths(kind, repo) if prefire.path_matches(path, g)] == []


@pytest.mark.parametrize("path, glob", [("src/lib/agentic-ops", "src/lib/agentic-ops/**"),
                                        ("src/lib/agentic-ops/__tests__/routing.test.ts", "src/lib/agentic-ops/**"),
                                        ("docs/x/prefire.py", "prefire.py")])
def test_PA5_control_what_the_new_globs_do_match(path, glob):
    assert prefire.path_matches(path, glob)


def test_PA5_control_the_lists_are_exactly_the_target_and_valid_json():
    data = json.loads(prefire.OPEX_PATHS.read_text(encoding="utf-8"))
    assert data["protected"]["orchestrator"] == ["executor/**", "orchestrator.py"] + GUARDS + [
        "canon_assert.py", "config/**"]   # G-621-1 (Kanban 621)
    assert data["agent_runtime"]["clinical-mp"][4:6] == ["server/simulation/**", "src/lib/agentic-ops/**"]
    assert data["agent_runtime"]["orchestrator"] == ["orchestrator.py", "executor/**",
                                                    "queue_daemon.py"]   # G-621-1 (Kanban 621)
    assert data["protected"]["_orchestrator"].endswith(
        "prefire.py, prefire_opex_paths.json, queue_daemon.py and admission.py are the guards and the fire loop: a "
        "brief changes them only on George's go (OC-4, D-S7CORE51-20).")
    assert data["agent_runtime"]["_orchestrator"] == ("orchestrator.py is the whole file: the fire path (fire_toni) "
                                                      "cannot be told apart from the rest of it by file name.")


# ── P-A7 · no lock-out: this route's own brief passes the check it introduces ──
def test_PA7_the_routes_own_brief_passes_opx_2_and_opx_3():
    b = ROOT / "briefs" / "662-663-orch-guard-self-npm-frozen-1.md"
    if not b.exists():
        pytest.skip("the route's own brief is not in this tree")
    out = subprocess.run([sys.executable, str(ROOT / "prefire.py"), str(b)], capture_output=True, text=True,
                         cwd=ROOT).stdout
    opx3 = [l.strip() for l in out.splitlines() if l.strip().startswith("OPX-3")]
    assert opx3 and opx3[0].startswith("OPX-3 ✅ never-autonomous path(s)"), out
    assert all(p in opx3[0] for p in ("prefire.py (prefire.py)", "prefire_opex_paths.json (prefire_opex_paths.json)",
                                      "executor/")), opx3[0]

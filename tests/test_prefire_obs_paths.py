# filename: tests/test_prefire_obs_paths.py
"""[ORCH-PREFIRE-OBS-PATHS-1] Kanban 708, RM-OPS-27-F-02 T-ORCH-01, AC-OPS27-06 — predicates P-1..P-6 of Part C of
briefs/697-708-orch-crash-prefire-bundle-1.md (708 v1 folded in): prefire's OPX-2 treats the code an Observability (O) identity runs on as
agent-runtime code, and OPX-3 protects every file that defines what O sees or how it judges (OBS.17.3, Arch:3483).
Data only: prefire_opex_paths.json gains the globs; no code changes."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
import prefire  # noqa: E402
from test_opex_prefire import brief, canon, opex  # noqa: E402,F401  (canon: the autouse scratch canon)

AR_NEW = ["server/observability/**", "scripts/observability/pipeline.ts", "scripts/observability/cockpit.ts",
          "scripts/observability/canon-index.ts", "scripts/observability/flag-rate-probe.ts"]
PR_NEW = ["src/lib/observability/engine/**", "src/lib/observability/schema/**", "src/lib/observability/conformance/**",
          "src/lib/observability/**/__tests__/fixtures/**", "config/observability/**", "server/observability/config/**",
          "registry/**", "src/lib/metric-registry/**", "scripts/observability-ci/**"]
AR_BASE = ["src/lib/agentic-runtime/**", "src/daemon/**", "src/lib/agentic-drafts/**", "server/**/agent*",
           "server/simulation/**", "src/lib/agentic-ops/**"]
PR_BASE = ["src/lib/cds/**", "src/lib/clinical/**", "src/lib/fhir/**", "src/lib/pros/**", "src/lib/auth/**",
           "src/components/auth/**", "server/auth.ts", "*access-policy*", "*accesspolicy*", "*client-application*",
           "*clientapplication*", "scripts/migrat*"]
O_INVENTORY = ("# SCP Agent Inventory — v0-1\n\n| Policy ID | Agent |\n|---|---|\n"
               "| `AP-OBS-ENGINE` v1 | O engine (dev-host + Zone T) |\n| `AP-TONI` | executor |\n")
GO = '## George go: 2026-11-14 22:10 "go" (D-S7CORE54-99)\n'

# (sample path, the first glob it names) — one sample per new glob, plus a glob path and a nested file
AR_SAMPLES = [("server/observability/compute.ts", "server/observability/**"),
              ("server/observability/**", "server/observability/**"),
              ("server/observability/config/library.ts", "server/observability/**"),
              ("scripts/observability/pipeline.ts", "scripts/observability/pipeline.ts"),
              ("scripts/observability/cockpit.ts", "scripts/observability/cockpit.ts"),
              ("scripts/observability/canon-index.ts", "scripts/observability/canon-index.ts"),
              ("scripts/observability/flag-rate-probe.ts", "scripts/observability/flag-rate-probe.ts")]
PR_SAMPLES = [("src/lib/observability/engine/status.ts", "src/lib/observability/engine/**"),
              ("src/lib/observability/schema/tree.ts", "src/lib/observability/schema/**"),
              ("src/lib/observability/conformance/vectors/v0001.json", "src/lib/observability/conformance/**"),
              ("src/lib/observability/__tests__/fixtures/queue.json", "src/lib/observability/**/__tests__/fixtures/**"),
              ("src/lib/observability/adapters/__tests__/fixtures/orch-log.txt",
               "src/lib/observability/**/__tests__/fixtures/**"),
              ("config/observability/pipeline-tree.yaml", "config/observability/**"),
              ("server/observability/config/config-write.ts", "server/observability/config/**"),
              ("registry/metrics/attention-x.yaml", "registry/**"),
              ("src/lib/metric-registry/compile.ts", "src/lib/metric-registry/**"),
              ("scripts/observability-ci/purity-scan.ts", "scripts/observability-ci/**"),
              ("src/lib/observability/**", "src/lib/observability/engine/**")]


def hits(kind: str, path: str) -> list:
    return [g for g in prefire.opex_paths(kind, "clinical-mp") if prefire.path_matches(path, g)]


# ── P-1 (RED) · OPX-2: the code an O identity runs on needs a cited Agent Policy ──
@pytest.mark.parametrize("path, glob", AR_SAMPLES)
def test_P1_an_o_runtime_path_without_a_policy_id_is_refused(tmp_path, canon, path, glob):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(O_INVENTORY)
    v = opex(brief(tmp_path, allowed="`%s`" % path, header=GO))["OPX-2"]
    assert not v.ok and v.line.startswith("OPX-2 ❌ AGENT-POLICY"), v.line
    assert "%s (%s)" % (path, glob) in v.line


@pytest.mark.parametrize("path, glob", AR_SAMPLES)
def test_P1_an_o_runtime_path_under_ap_obs_engine_passes(tmp_path, canon, path, glob):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(O_INVENTORY)
    b = brief(tmp_path, allowed="`%s`" % path, header=GO + "## Agent policy: AP-OBS-ENGINE-v1 (dev-host instance)\n")
    assert opex(b)["OPX-2"].line == ("OPX-2 ✅ agent-runtime path(s) %s (%s) under AP-OBS-ENGINE "
                                   "(SCP_Agent_Inventory_v0-1.md)" % (path, glob))


# ── P-2 (RED) · OPX-3: what defines what O sees or how it judges needs George's go ──
@pytest.mark.parametrize("path, glob", PR_SAMPLES)
def test_P2_an_o_protected_path_without_a_george_go_is_refused(tmp_path, path, glob):
    v = opex(brief(tmp_path, allowed="`%s`" % path))["OPX-3"]
    assert not v.ok and v.line.startswith("OPX-3 ❌ NEVER-AUTONOMOUS"), v.line
    assert "%s (%s)" % (path, glob) in v.line


@pytest.mark.parametrize("path, glob", PR_SAMPLES)
def test_P2_an_o_protected_path_with_a_george_go_passes(tmp_path, path, glob):
    v = opex(brief(tmp_path, allowed="`%s`" % path, header=GO))["OPX-3"]
    assert v.ok and v.line.startswith("OPX-3 ✅ never-autonomous path(s) %s (%s)" % (path, glob)), v.line


# ── P-3 (controls) · what O does not run is not agent-runtime; near names are not caught ──
@pytest.mark.parametrize("path", ["scripts/observability-ci/purity-scan.ts", "scripts/obs-emit/emit-lint.ts",
                                  "server/__tests__/obs-emit/choke.test.ts", "scripts/observability/other.ts",
                                  "src/lib/observability/engine/status.ts", "server/observability-old/x.ts",
                                  "server/__tests__/observability/x.test.ts"])
def test_P3_control_not_agent_runtime(path):
    assert hits("agent_runtime", path) == []


@pytest.mark.parametrize("path", ["src/lib/observability/adapters/queue.ts",
                                  "src/lib/observability/__tests__/status.test.ts", "server/observability/compute.ts",
                                  "src/lib/features/registry.ts", "src/lib/jobs/registry.ts", "src/registry/x.ts",
                                  "docs/registry/x.md", "config/observability-old/x.yaml",
                                  "src/lib/observability/fixtures/x.json", "scripts/observability/pipeline.ts",
                                  "src/lib/metric-registryx/y.ts"])
def test_P3_control_not_protected(path):
    assert hits("protected", path) == []


def test_P3_control_purity_scan_is_protected_and_not_agent_runtime(tmp_path, canon):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(O_INVENTORY)
    v = opex(brief(tmp_path, allowed="`scripts/observability-ci/purity-scan.ts`"))
    assert v["OPX-2"] == prefire.OpexVerdict(True, "OPX-2 ✅ no agent-runtime path in ALLOWED FILES")
    assert not v["OPX-3"].ok


def test_P3_control_server_observability_config_is_both(tmp_path, canon):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text(O_INVENTORY)
    p = "server/observability/config/config-write.ts"
    assert hits("agent_runtime", p) == ["server/observability/**"]
    assert hits("protected", p) == ["server/observability/config/**"]
    v = opex(brief(tmp_path, allowed="`%s`" % p))
    assert not v["OPX-2"].ok and not v["OPX-3"].ok


# ── P-4 (controls) · the lists only grow, at the end, by exactly these globs; orchestrator / '*' untouched ──
def test_P4_control_the_lists_are_exactly_base_plus_the_o_globs():
    data = json.loads(prefire.OPEX_PATHS.read_text(encoding="utf-8"))
    assert data["agent_runtime"]["clinical-mp"] == AR_BASE + AR_NEW
    assert data["protected"]["clinical-mp"] == PR_BASE + PR_NEW
    assert data["agent_runtime"]["orchestrator"] == ["orchestrator.py", "executor/**"]
    assert data["protected"]["orchestrator"] == ["executor/**", "orchestrator.py", "prefire.py",
                                                 "prefire_opex_paths.json", "queue_daemon.py", "admission.py"]
    assert len(data["protected"]["*"]) == 16 and data["protected"]["*"][0] == "*.env*"
    assert data["_about"].startswith("[ORCH-OPEX-PREFIRE-1] D-S7CORE33-20 (Codex v2-57). The paths prefire")


def test_P4_control_other_repos_do_not_see_the_o_globs():
    for kind, new in (("agent_runtime", AR_NEW), ("protected", PR_NEW)):
        for repo in ("orchestrator", "yorsie", "ai-foundation"):
            assert not set(new) & set(prefire.opex_paths(kind, repo)), (kind, repo)
        assert set(new) <= set(prefire.opex_paths(kind, None))      # no repo= ⇒ every list (as today)


# ── P-5 · the id spelling the Inventory must use (prefire.py unchanged; documents the contract for Kanban 707) ──
@pytest.mark.parametrize("cited, listed, ok", [("AP-OBS-ENGINE-v1", "`AP-OBS-ENGINE` v1", True),
                                               ("AP-OBS-ENGINE", "`AP-OBS-ENGINE-v1`", True),
                                               ("AP-OBS-ENGINE-v1", "`AP-OBS-ENGINE-V1`", False),
                                               ("AP-OBS-AGGREGATOR", "`AP-OBS-ENGINE`", False)])
def test_P5_control_policy_id_spelling(tmp_path, canon, cited, listed, ok):
    (canon / "SCP_Agent_Inventory_v0-1.md").write_text("| Policy ID | Agent |\n|---|---|\n| %s | x |\n" % listed)
    b = brief(tmp_path, allowed="`scripts/observability/pipeline.ts`", header="## Agent policy: %s\n" % cited)
    assert opex(b)["OPX-2"].ok is ok


# ── P-6 · no lock-out: this route's own brief passes the checks it widens ──
def test_P6_the_routes_own_brief_names_no_agent_runtime_path_and_passes_opx_3():
    """The bundle's brief is never in the tree (rule #32): skips, and R-a of the handback runs it from the fire copy."""
    b = ROOT / "briefs" / "697-708-orch-crash-prefire-bundle-1.md"
    if not b.exists():
        pytest.skip("the route's own brief is not in this tree")
    paths = prefire.allowed_paths(b)
    assert prefire.check_agent_policy(b, paths).line.startswith("OPX-2 ✅ no agent-runtime path")
    assert prefire.check_george_go(b, paths).line.startswith(
        "OPX-3 ✅ never-autonomous path(s) queue_daemon.py (queue_daemon.py), prefire.py (prefire.py), "
        "prefire_opex_paths.json (prefire_opex_paths.json)")

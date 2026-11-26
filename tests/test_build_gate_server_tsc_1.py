"""BUILD-GATE-SERVER-TSC-1 (Kanban 983; SCA-TSC-SERVER-RED-ON-MAIN-1; slice 2 of 981 TSC-SERVER-GREEN-1).

clinical-mp's build leg runs the member BFF's own typecheck (`tsc --noEmit -p server`, Node types, no DOM) beside the
root typecheck, so the server half of `npm run typecheck` cannot go red unseen again (it reached 32 errors on main
before 981 because only root tsc ran in any gate).

  S-1 (RED at base)  config/repos.yaml: clinical-mp's build_gate_cmd = root tsc, then tsc -p server, then npm run build
  S-2 (control)      yorsie's and orchestrator's build legs are unchanged; the global default is unchanged
"""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REPOS = yaml.safe_load((ROOT / "config" / "repos.yaml").read_text())["repos"]


def test_s1_clinical_mp_build_leg_runs_the_server_typecheck():
    cmd = REPOS["clinical-mp"].get("build_gate_cmd")
    print(f"[S-1] clinical-mp build_gate_cmd = {cmd!r}")
    assert cmd == "npx tsc --noEmit && npx tsc --noEmit -p server && npm run build"


def test_s2_other_build_legs_unchanged():
    import orchestrator as o
    assert o.BUILD_GATE_CMD == "npx tsc --noEmit && npm run build"
    assert REPOS["yorsie"]["build_gate_cmd"] == "cd yorsie && npm run build"
    assert REPOS["orchestrator"]["build_gate_cmd"] == (
        "python3 -m py_compile orchestrator.py queue_daemon.py prefire.py admission.py canon_assert.py executor_auth.py")

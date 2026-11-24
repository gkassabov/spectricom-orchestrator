# filename: tests/test_sit_list_parallel.py
"""ORCH-SIT-LIST-PARALLEL-1 (S7-CORE-61, Kanban 950) — clinical-mp's SIT listing collects files in parallel.

vitest.sit.config.ts sets `fileParallelism: false` (the RUN must be serial: per-file provisioned fixtures), and
`vitest list` inherited it: ~3.4 s × 235 files ≈ 800 s > SIT_TIMEOUT 600 → TimeoutExpired → sit-list-failed
(route 906, 2026-11-23 20:43 + 21:06). Listing collects only — no test body runs — so the list command alone
overrides it: `--maxWorkers=6 --fileParallelism` → exit 0 in 131 s, 235 files / 830 tests on e4c54cb8.

  SL-1 (RED)     config/repos.yaml: clinical-mp's sit_list_cmd carries --fileParallelism and --maxWorkers=6
  SL-2 (control) _sit_plan's files_only append composes with the new flags (`… --fileParallelism --filesOnly`)
  SL-3 (control) _sit_config_file still finds vitest.sit.config.ts in the shipped command
"""
import shlex
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

import orchestrator  # noqa: E402

SHIPPED = yaml.safe_load((Path(__file__).parent.parent / "config" / "repos.yaml").read_text())
CMD = (SHIPPED["repos"]["clinical-mp"] or {}).get("sit_list_cmd", "")


def test_sl1_clinical_mp_sit_list_cmd_collects_in_parallel():
    toks = shlex.split(CMD)
    print(f"[SL-1] sit_list_cmd = {CMD!r}")
    assert toks[:3] == ["npx", "vitest", "list"]
    assert "--fileParallelism" in toks
    assert "--maxWorkers=6" in toks
    assert "--no-fileParallelism" not in toks


def test_sl2_files_only_append_composes(tmp_path):
    seen = []

    def _tree(cmd, **kw):
        seen.append((cmd, kw.get("timeout")))
        return subprocess.CompletedProcess(cmd, 0, stdout="sit/integration/a.integration.test.ts\n", stderr="")

    with patch.object(orchestrator, "_run_tree", _tree), \
         patch.dict(orchestrator.ACTIVE_REPO_CONFIG, {"sit_list_cmd": CMD}, clear=True):
        plan = orchestrator._sit_plan(tmp_path, files_only=True)
    print(f"[SL-2] ran {seen} · error {plan.error!r} · files {plan.files}")
    assert len(seen) == 1 and seen[0][0].endswith(f"{CMD} --filesOnly")
    assert seen[0][1] == orchestrator.SIT_TIMEOUT
    assert plan.error is None and plan.files == ["sit/integration/a.integration.test.ts"]


def test_sl3_config_file_still_parsed():
    got = orchestrator._sit_config_file(CMD)
    print(f"[SL-3] config {got!r}")
    assert got == "vitest.sit.config.ts"

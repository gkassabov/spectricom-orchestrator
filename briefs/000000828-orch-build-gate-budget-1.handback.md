## STATUS: DONE

# BUILD-GATE-BUDGET-1 (Kanban 828; orchestrator) — handback

**Daemon restart still owed (rule #12):** the running daemon keeps the 600 s build budget until Gemma restarts it in a quiet window. This route did not restart it.

**Commit:** `BUILD-GATE-BUDGET-1 (828; ORCH-BUILD-GATE-BUDGET-1)` on branch `orch-orch-000000828-orch-build-gate-budget-1`, parent `4001f11` (the SHA is in `git log -1`). It holds exactly G-1 (`~/_eos/s7core59/dry/bt.patch`, sha256 `ffc3162830ad301cacdad8e52c31016f35363fae1044ca3905b48b7c5894fc20`, checked before applying) plus this handback.

## Base
- `git merge-base --is-ancestor 4001f11 HEAD` → ancestor OK (HEAD was `4001f11`).

## A0 at HEAD, before any edit (all as the brief says, no STOP (d))
1. `build_timeout_s|BUILD_GATE_TIMEOUT_KEY` → 0 lines
2. `orchestrator.py:2283:            cwd=str(repo_path), timeout=BUILD_GATE_TIMEOUT`
3. `orchestrator.py:5956:                                    f"the build leg was killed at its {BUILD_GATE_TIMEOUT}s budget after "`
4. `config/repos.yaml:99:    sit_batch_timeout_s: 1200`
5. `tests/test_capacity.py` `tests/test_gate_clock.py` `tests/test_lean_gate.py` `tests/test_unit_baseline_gate.py`

## RED (base + the new test file only)
`python3 -m pytest -q tests/test_build_gate_budget.py` → **4 failed, 1 passed** (BT-2 passes at the base). This matches the brief.

## GREEN (after G-1)
- `[BT-1] build leg [('build', 1200)]`
- `[BT-2] build leg [('build', 600)]`
- `[BT-3] build leg [('build', 600)] · warned True`
- `[BT-4] {'yorsie': None, 'clinical-mp': 1200, 'orchestrator': None}`
- `[BT-5] "build", "timeout", f"the build leg was killed at its " f"{_unit_repo_timeout(BUILD_GATE_TIMEOUT_KEY, BUILD_GATE_TIMEOUT)}s budget after " …`
- **5 passed**. `orchestrator.py` parses (ast). There is no TypeScript typecheck in this repo.

## Related run — not run by this executor
The fire instructions limit the executor to the test files it added or changed, run by path, and never a related set, because the pre-merge gate runs the full unit suite. So the brief's five-file related run (`test_capacity`, `test_gate_clock`, `test_lean_gate`, `test_unit_baseline_gate`, `test_sit_batch_budget`) was not repeated here. The dry run's result for it was `370 passed, 2 skipped`; the gate's full suite is the check at merge. No existing test was edited.

## Open items (unchanged, for George / Gemma)
- Daemon restart in a quiet window (rule #12).
- The admission wall could read the repo keys (SIT 1200, build 1200) — a follow-up row.
- MiniG cron_orchestrator CPU during gates (rule #14) — George's call.

## STATUS: DONE

**ORCH-GATE-LEG-TREE-KILL-1 (Kanban 880; SCA-ORCH-GATE-TIMEOUT-ORPHANS-1).** The daemon restart (rule #12) is **still owed**. It is Gemma's to do, in a quiet window, after merge. Until then the running daemon still leaves a timed-out leg's children behind.

- Commit: one commit on `orch-orch-000000880-orch-gate-leg-tree-kill-1`, titled `GATE-LEG-TREE-KILL-1 (880; ORCH-GATE-LEG-TREE-KILL-1): …`. Its parent is `513f850`.
- G-1 = `~/_eos/s7core59/laneO9/rf880.patch`. Its sha256 was checked first and matches: `11ffde5d2a687653411da0a5dd6985f8edae9c976c21c2dd639032d1d96bae10`. It was applied with `git apply` exactly as given. It touches 3 files: `orchestrator.py`, `tests/test_bg_ceiling.py` (G5 only) and `tests/test_gate_leg_tree_kill.py` (new). Nothing outside ALLOWED FILES was changed.

## Base
`git merge-base --is-ancestor 513f850 HEAD` → passes (HEAD was `513f850`).

## A0 at HEAD, before any edit (all match the brief)
1. `git grep -n "_run_tree\|_kill_tree\|GATE_TREE_KILL_GRACE_S\|start_new_session" -- orchestrator.py` → 0 lines
2. `orchestrator.py:2249:        r = subprocess.run(cmd, **kwargs)`
3. `orchestrator.py:1153:                preexec_fn=os.setsid, env=env)`
4. `git ls-files tests/test_gate_leg_tree_kill.py` → nothing
5. tests/test_build_gate_budget.py tests/test_capacity.py tests/test_clockguard_1.py tests/test_control_verdict_lines.py tests/test_exec_preflight.py tests/test_gate_clock.py tests/test_gate_cost.py tests/test_isolated_deps.py tests/test_lean_gate.py tests/test_repeat_flake.py tests/test_route_ref_integrity.py tests/test_sit_batch_budget.py tests/test_sit_batch_timeout_continues.py tests/test_sit_enum_parallel.py tests/test_sit_isolation_attributed.py tests/test_sit_rate_limit.py tests/test_unit_baseline_gate.py tests/test_unit_fail_label.py tests/test_unit_gate_wording.py
6. `tests/test_bg_ceiling.py:293:    assert len(popens) == 1, …` (1 line) · `tests/test_sit_rate_limit.py:255:        for literal in (…, "vitest list"):` (1 line)

## RED (base `orchestrator.py` + the new test file only)
`python3 -m pytest -q tests/test_gate_leg_tree_kill.py` → **3 failed, 2 passed in 12.33s**. TK-1, TK-2 and TK-4 failed. TK-3 and TK-5 are controls and passed.
```
[TK-1] raised TimeoutExpired timeout=1 clock=True · child 1581413 gone=False
[TK-2] passed=False error='timeout' exit=-1 · child 1581738 gone=False
[TK-3] code=3 stdout='out\n' stderr='err\n' args='echo out; echo err >&2; exit 3'
[TK-4] leg pgid 1581400 · test pgid 1581400
[TK-5] calls [('npx tsc --noEmit', {'shell': True, 'capture_output': True, 'text': True, 'cwd': '…/test_tk5_a_replaced_run_is_cal0', 'timeout': 7})]
```
The tests killed their planted children. Afterwards 0 `sleep 300` processes were left.

## GREEN (after G-1)
`python3 -m pytest -q tests/test_gate_leg_tree_kill.py tests/test_bg_ceiling.py` → **47 passed in 3.69s**: the new file (5) plus the G5 file this route edits.
```
[TK-1] raised TimeoutExpired timeout=1 clock=True · child 1582006 gone=True
[TK-2] passed=False error='timeout' exit=-1 · child 1582026 gone=True
[TK-3] code=3 stdout='out\n' stderr='err\n' args='echo out; echo err >&2; exit 3'
[TK-4] leg pgid 1582028 · test pgid 1582001
[TK-5] calls [('npx tsc --noEmit', {'shell': True, 'capture_output': True, 'text': True, 'cwd': '…/test_tk5_a_replaced_run_is_cal0', 'timeout': 7})]
```
- `sleep 300` children left after the run: **0**. STOP (f) does not apply.
- `python3 -m py_compile orchestrator.py` → parses. This is a Python repo, so there is no tsc typecheck.

## Suite run
**Not run by the executor.** The brief's test scope is targeted, and ORCH-LEAN-GATE-1 forbids the executor a full suite or baseline run: the pre-merge gate runs the full `pytest -q tests/` right after this route (GATE PRE-LIST). The authoring dry run's whole-suite result (2 pins, fixed by G-1b; then the 16 source-scan files plus the new test green) is in the brief. `tests/test_sit_rate_limit.py`'s `vitest list` scan was not run here. The patch comment says "the SIT listing", so the brief expects it to stay green at the gate.

## Notes
- RULE #8: the only existing test edited is `tests/test_bg_ceiling.py::test_G5_source_guard_one_executor_spawn_site`. Its Popen count went from 1 to 2, each pinned inside its named function, and `_run_tree` joined `_OTHER_SPAWNERS`. This is the mechanical-pin edit the brief names.
- Open items for George and Gemma are unchanged from the brief: the daemon restart, the two orphans from route 853, the daemon process-group note, and the Playwright probe / `git` reads left as they are.

## STATUS: DONE

# 802 ORCH-MERGE-CHECKOUT-CHECKED-1 — handback

Closes **ORCH-MERGE-CHECKOUT-SILENT-1** (Bug Registry, P2 orchestrator) on merge.

## Base
`git merge-base --is-ancestor 0a82275 HEAD` → ancestor OK.

## A0 (at HEAD, before any edit) — matched the brief
1. `git grep -nF 'subprocess.run(f"git checkout {MERGE_TARGET}", shell=True, capture_output=True, cwd=str(proj))' -- orchestrator.py`
   ```
   orchestrator.py:1936:        subprocess.run(f"git checkout {MERGE_TARGET}", shell=True, capture_output=True, cwd=str(proj))
   orchestrator.py:8216:                        subprocess.run(f"git checkout {MERGE_TARGET}", shell=True, capture_output=True, cwd=str(proj))
   ```
2. `git grep -nF 'ORCH-MERGE-CHECKOUT-SILENT-1' -- orchestrator.py tests` → (none)
3. `git grep -nF 'def _checkout_holding(branch: str, repo: Path) -> Optional[Path]:' -- orchestrator.py`
   ```
   orchestrator.py:1920:def _checkout_holding(branch: str, repo: Path) -> Optional[Path]:
   ```

## G-1
`~/_eos/s7core58/dry/802.patch` sha256 `6a0669b7649d8c9aa56842a7e74da25d81d37d4c95b7e1450635337173ccca66` (matches). `git apply --check` clean. I applied it verbatim in two steps, the test file first (RED) and then `orchestrator.py` (GREEN). No other edits.

## RED (base + new test file only) — 2 failed / 4
```
[MC-1] status Status.FAILED · error None
[MC-2] late-check lines 1 · refused-checkout lines 0
2 failed, 2 passed in 0.70s
```

## GREEN (after G-1) — 4 / 4
```
[MC-1] status Status.FAILED · error "NOT LANDED — could not check out main to merge orch-batch-mc (it is checked out at /tmp/pytest-of-gkassa/pytest-345/test_mc1_failed_not_landed_nam0/authoring-wt): fatal: 'main' is already used by worktree at '/tmp/pytest-of-gkassa/pytest-345/test_mc1_failed_not_landed_nam0/authoring-wt'; gate was PASS"
[MC-2] late-check lines 0 · refused-checkout lines 2
4 passed in 0.72s
```
`python3 -m py_compile orchestrator.py` → OK. The repo is Python and has no tsc typecheck.

## Not run here (operator fire instruction G-ORCH-1 / CLAUDE.md ORCH-LEAN-GATE-1)
The fire prompt allows only the added test file, run by path. Under that rule I did **not** run the merge-lane suites (`test_merge_conflict`, `test_route_landed`, `test_queue_park_red` + new → 61/61 in the dry run) or the whole suite `pytest tests/`. The brief header says `Test scope: targeted` and does not say `full`. The pre-merge gate runs the full unit suite. The dry run's numbers are in `802-related.txt` / `802-full.txt` (61/61; 3247 passed, 1 skipped + the new file).

## Files
- `orchestrator.py`: the main-checkout lane's merge step in `_run_batch_inner` now reads the checkout's exit. If the checkout is refused, the merge does not run and the run is FAILED with a `ROUTE_NOT_LANDED_VERDICT` gate_error naming the holder (`_checkout_holding`), and the branch is kept. The tip-unchanged case now carries a NOT LANDED gate_error.
- `tests/test_merge_checkout_held.py` (new): MC-1..MC-4.
- this handback.

## Commit
See `git log -1` on the route branch: "ORCH-MERGE-CHECKOUT-CHECKED-1 (802) …".

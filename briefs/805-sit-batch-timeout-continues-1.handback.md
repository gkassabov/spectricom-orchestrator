## STATUS: DONE

# 805 SIT-BATCH-TIMEOUT-CONTINUES-1 — handback

Base: `071680d` is an ancestor of HEAD (`git merge-base --is-ancestor 071680d HEAD` → 0; HEAD was `071680d` at fire).
G-1 patch `~/_eos/s7core58/dry/805.patch` sha256 `61b1890e4013efba6b969d1181488760dacd400ecb6c2530613ae399894b632d` (matches). `git apply --check` was clean. I applied it exactly with `git apply`: the test file first (for RED), then `orchestrator.py`. After that, `git apply -R --check` of the whole patch was clean, so the tree is exactly the patch.

## A0 (at HEAD, before any edit)
1. `git grep -nF 'timeout=plan.timeout_s)' -- orchestrator.py` → 1 line:
```
orchestrator.py:2795:                            shell=True, capture_output=True, text=True, cwd=str(repo_path), timeout=plan.timeout_s)
```
2. `git grep -n 'timed_out' -- orchestrator.py` → none (exit 1).
3. `git grep -nF 'SIT_BATCH_TIMEOUT_KEY = "sit_batch_timeout_s"' -- orchestrator.py` → 1 line:
```
orchestrator.py:266:SIT_BATCH_TIMEOUT_KEY = "sit_batch_timeout_s"
```

## RED (base + the new test file only)
`python3 -m pytest -q -s tests/test_sit_batch_timeout_continues.py`
```
[T-3] passed True · error 'timeout-advisory' · detail None
FAILED tests/test_sit_batch_timeout_continues.py::test_t1_t2_other_batches_run_and_the_timeout_is_named
FAILED tests/test_sit_batch_timeout_continues.py::test_t3_post_merge_advisory_says_what_timed_out
FAILED tests/test_sit_batch_timeout_continues.py::test_t4_a_red_batch_beside_the_timeout_is_red
3 failed, 1 passed in 0.47s
```
T-5 passes, as the brief says. At base, T-1/2 and T-4 print no `[T-…]` line. The batch's `TimeoutExpired` leaves `_run_sit_batched` before the test's print runs (1 leg started), and that is the bug.

## GREEN (after G-1)
`python3 -m pytest -q -s tests/test_sit_batch_timeout_continues.py`
```
[T-1] legs started 3 · [T-2] timed out ['batch 1/3 (2 files: sit/a.test.ts, sit/b.test.ts) exceeded its 600s budget'] · mismatch None · counts {'test_files_total': 3, 'test_files_passed': 3, 'tests_total': 3, 'tests_passed': 3}
[T-3] passed True · error 'timeout-advisory' · detail 'batch 1/3 (2 files: sit/a.test.ts, sit/b.test.ts) exceeded its 600s budget; the other 2 batches: collected 3 test files / 3 tests, green'
[T-4] legs 3 · rc 1 · timed out 1 · named ['sit/c.test.ts']
4 passed in 0.18s
```
`python3 -m py_compile orchestrator.py tests/test_sit_batch_timeout_continues.py` → OK.

## Whole suite — not run here
The brief's GREEN line asks for `python3 -m pytest -q tests/`. This fire's executor instructions and the CLAUDE.md test scope (ORCH-LEAN-GATE-1) forbid a full suite, because the pre-merge gate runs it right after this. The brief's header is `## Test scope: targeted`, not `full`. So there is no whole-suite tail to paste. The gate's unit leg is the whole-suite check. The dry run reported 3256 passed, 1 skipped.

## Files (2, matching the patch) + this handback
`orchestrator.py` · `tests/test_sit_batch_timeout_continues.py` (new) · `briefs/805-sit-batch-timeout-continues-1.handback.md`

## Commit
See `git log -1` on branch `orch-orch-000000805-sit-batch-timeout-continues-1`. Its subject starts `SIT-BATCH-TIMEOUT-CONTINUES-1 (805`.

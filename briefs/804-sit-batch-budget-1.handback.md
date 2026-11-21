## STATUS: DONE

# 804 SIT-BATCH-BUDGET-1 — handback

Base: `4a12926` is an ancestor of HEAD (`git merge-base --is-ancestor 4a12926 HEAD` → 0).
G-1 patch `~/_eos/s7core58/dry/804.patch` sha256 `f49df1d6f440b0078f207b3bebba93a5ea771253a9f33f8a502bd5044a1ef75b` (matches), applied exactly with `git apply`.

## A0 (at HEAD, before any edit)
1. `git grep -nF 'cwd=str(repo_path), timeout=SIT_TIMEOUT)' -- orchestrator.py` → 4 lines:
```
orchestrator.py:2577:                           text=True, cwd=str(repo_path), timeout=SIT_TIMEOUT)
orchestrator.py:2789:                            shell=True, capture_output=True, text=True, cwd=str(repo_path), timeout=SIT_TIMEOUT)
orchestrator.py:2904:                               text=True, cwd=str(repo_path), timeout=SIT_TIMEOUT)
orchestrator.py:4895:        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd=str(repo_path), timeout=SIT_TIMEOUT)
```
2. `git grep -n 'sit_batch_timeout_s' -- orchestrator.py config tests` → none (exit 1).
3. `git grep -nF 'plan = SitPlan(batch_files=_unit_repo_timeout(SIT_BATCH_FILES_KEY, SIT_BATCH_FILES))' -- orchestrator.py` → 1 line:
```
orchestrator.py:2569:    plan = SitPlan(batch_files=_unit_repo_timeout(SIT_BATCH_FILES_KEY, SIT_BATCH_FILES))
```

## RED (base + the new test file only)
`python3 -m pytest -q -s tests/test_sit_batch_budget.py`
```
[B-1] batch timeouts [600, 600]
FAILED tests/test_sit_batch_budget.py::test_b1_repo_budget_reaches_every_batch
FAILED tests/test_sit_batch_budget.py::test_b3_bad_value_falls_back_loudly - ...
FAILED tests/test_sit_batch_budget.py::test_b4_clinical_mp_declares_1200 - As...
3 failed, 1 passed in 0.18s
```
(B-2 passes, as the brief says. My output filter did not keep the RED `[B-4]` print line; B-4 failed on its assertion at base, where repos.yaml has no key.)

## GREEN (after G-1)
`python3 -m pytest -q -s tests/test_sit_batch_budget.py`
```
[B-1] batch timeouts [1200, 1200]
[B-4] clinical-mp sit_batch_timeout_s = 1200
4 passed in 0.22s
```
`python3 -m py_compile orchestrator.py tests/test_sit_batch_budget.py` → OK.

## Whole suite — not run here
The brief's GREEN line asks for `python3 -m pytest -q tests/`. The executor's instructions for this fire (and CLAUDE.md test scope, ORCH-LEAN-GATE-1) forbid a full suite: the pre-merge gate runs it right after this. The brief's header is `## Test scope: targeted`, not `full`. So there is no whole-suite tail to paste. The gate's unit leg is the whole-suite check. The dry run reported 3252 passed, 1 skipped.

## Files (3, matching the patch) + this handback
`orchestrator.py` · `config/repos.yaml` · `tests/test_sit_batch_budget.py` (new) · `briefs/804-sit-batch-budget-1.handback.md`

## Commit
See `git log -1` on branch `orch-orch-000000804-sit-batch-budget-1`. Its subject starts `SIT-BATCH-BUDGET-1 (804)`.

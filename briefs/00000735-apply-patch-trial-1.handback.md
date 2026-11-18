## STATUS: DONE

# ORCH-APPLY-PATCH-1 — handback (Kanban 735, SD-1 trial route lane)

Route branch `orch-orch-00000735-apply-patch-trial-1`, base orchestrator `main` `8c71056`. A re-land: the saved r5 patch applied as is, no other edits.

## X0 · the worktree
```
$ python3 -c "import orchestrator, prefire; print(orchestrator.__file__, prefire.__file__)"
/tmp/orch-fire-20261118-010804/orchestrator.py /tmp/orch-fire-20261118-010804/prefire.py
```
Both load from inside the meta-fire worktree, so STOP (e) does not apply.

## Step 1 · patch sha256 + apply
```
$ sha256sum ~/_eos/s7core56/briefs/_work/735/apply-patch-trial-1-r5.patch
5a75f203fc0671f1da94975cb98be22ab52dbc43435e60daf4bb3b171e260479  …/apply-patch-trial-1-r5.patch
$ git apply --check …  → CHECK_OK
$ git apply --3way …
Applied patch to 'orchestrator.py' cleanly.
Applied patch to 'prefire.py' cleanly.
$ git diff --cached --stat
 orchestrator.py                 | 195 ++++++++-
 prefire.py                      | 495 +++++++++++++++++++++-
 tests/test_apply_patch_trial.py | 896 ++++++++++++++++++++++++++++++++++++++++
 3 files changed, 1577 insertions(+), 9 deletions(-)
```
The sha256 matches the brief, and the patch applied clean to all 3 files with +1577 −9, the counts the brief gives. STOP (a) does not apply.

## Step 2 · no edits beyond the patch
Nothing else changed. This commit holds only the patch's 3 paths and this handback.

## A0 · re-read at the base (`8c71056`, before the apply)
- `orchestrator.py:7377` `def _regate_check`, `:7431` `def _regate_bring`, `:207` `def parse_repo_from_brief`: all three match the brief.
- After the apply: `APPLY_TRIAL_CAP = 5` `orchestrator.py:7477`, `_applypatch_check` `:7510`, `_applypatch_bring` `:7556`, `run_batch` `:7651` (`REGATE, why = _regate_check` `:7662`, `REGATE = None` `:7757`), `regate = REGATE if worktree is None else None` `:7869`, `_named_repo` `:8634`.
- `prefire.py` after the apply: `parse_regate` `:235`, `_RUNNER_PATH` `:262` (reads `\.?pytest\.(?:ini|toml)`, the r5 fix), `_GRANT_FENCE` `:284` (`^ {0,3}(?:```|~~~)`), `rule8_grants` `:507`, `apply_patch_problems` `:581`, `_section(..., fence=None)` `:1104`, `HEADER_WINDOWS` `:1810`.

## Step 3 · compile + tests
- `python3 -m py_compile orchestrator.py prefire.py`: exit 0.
- `timeout 10m python3 -m pytest -q tests/test_apply_patch_trial.py`: **156 passed in 32.57s**. All predicate groups are green: P-1 lands, P-2 scope, P-3 condition 2 (including `:268` `TestP3Tests::test_an_ungranted_change_to_an_existing_test_is_refused`), P-4 condition 1, P-5 trial, P-6 prefire, P-7, P-8, P-9, and P-10 with r5's 9 rows.
- Targeted set (the 14 files HANDBACK step 3 names): **915 passed, 1 skipped in 23.40s**. The skip is `tests/test_prefire_obs_paths.py:159` "the route's own brief is not in this tree", the expected one. The branch guards in `tests/test_unit_baseline_gate.py` (AC-O5-07 `:1031`, AC-O8-10 `:1594`) ran against the worktree's `main` ref and passed; neither was skipped.
- Base red was not re-run here; the brief's r5 DRY RUN records it (51 failed + 105 errors, 0 passed). I did not run the full suite or a preflight, because the gate's unit leg runs the full suite.

## RULE #8
I searched again at `main` for `HEADER_WINDOWS|header_window_problems` (`tests/test_prefire_parse_hazards.py`, 6 hits as named) and `Apply patch|apply_patch|APPLY` (none). Both agree with the brief. Every hit the brief names is in a file covered by the targeted set (keep-green, green) or by the gate's full suite. No grants and no harness edits; no existing assertion changed. STOP (c) does not apply.

no daemon restart owed — every fire is a fresh orchestrator process

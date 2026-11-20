## STATUS: DONE

# 794 · ORCH-QUEUE-LOOSEN-1 — handback

Base: `4ba1205345c20abc0c1819c5ccaff1454a0ccdaf` (HEAD at fire). `git merge-base --is-ancestor 4ba1205 HEAD` → true.

## A0 at HEAD, before any edit (all match the brief)
1. `git grep -n 'RED_PREFIRE\|prefire_held_dir\|ORCH-QUEUE-LOOSEN-1' -- '*.py'` → none (rc=1)
2. `git grep -nF "error='pre-fire assertions failed (A1/A2/A8) — HOOK-1'" -- orchestrator.py` →
   `orchestrator.py:7783:                      error='pre-fire assertions failed (A1/A2/A8) — HOOK-1')`
3. `git grep -nF 'ok = (named if named else ipr) == now' -- queue_daemon.py` →
   `queue_daemon.py:1617:            ok = (named if named else ipr) == now`
4. `git grep -nF '"## Test scope: targeted (D-S7CORE30-04)",' -- tests/test_prefire.py` →
   `tests/test_prefire.py:138:    "## Test scope: targeted (D-S7CORE30-04)",`

## G-1
- `sha256sum ~/_eos/s7core58/dry/794.patch` → `4b2aea4ef3f329817c43e33eb104816aba4d2608f8a85aa5d4ea9c8c8041441e` (matches).
- `git apply ~/_eos/s7core58/dry/794.patch`, applied exactly. Diff: `prefire.py` +5, `queue_daemon.py` +44/-2,
  `tests/test_prefire.py` +2/-2 (G-794-1), `tests/test_queue_loosen.py` new, 151 lines. Nothing else touched.

## RED (new test file only, before the code hunks)
`python3 -m pytest -q tests/test_queue_loosen.py` → **10 failed, 12 passed** (matches the brief).

## GREEN (after G-1)
`python3 -m pytest -q tests/test_queue_loosen.py tests/test_prefire.py` → **94 passed**.

## Not run here, and why
- The brief's GREEN line also lists `tests/test_control_scope.py` and `tests/test_queue_park_red.py` (unchanged
  files) and the whole `pytest tests/`. I did not run them. The fire's instructions say to run only the test files
  added or changed, by path, and never a suite or a related set, and the brief's own header is
  `## Test scope: targeted`. The pre-merge gate runs the full unit suite (see GATE PRE-LIST). **Full-suite count:
  not measured in this fire.** The dry-run figure (3244 passed, 1 skipped, `794-full.txt`) is Gemma's, not mine.
- No typecheck: this is a Python repo with no tsc project.

## Commit
One commit on `orch-orch-794-orch-queue-loosen-1`: `ORCH-QUEUE-LOOSEN-1 (794; D-S7CORE58) …` (5 files: the patch's 4 + this handback).

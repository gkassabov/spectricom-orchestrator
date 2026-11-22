## STATUS: DONE
**Daemon restart (rule #12) still owed** — Gemma, quiet window. Until then, repeat flakes are not named.

# 836 · ORCH-REPEAT-FLAKE-1 — handback

**Commit:** see `git log -1` on `orch-orch-000000836-orch-repeat-flake-1` (subject begins `REPEAT-FLAKE-1 (836; ORCH-REPEAT-FLAKE-1)`).
**Base:** `git merge-base --is-ancestor 5196f99 HEAD` → true.

## A0 at HEAD, before any edit (all match the brief)
1. `git grep -n "FLAKE_LEDGER\|_flake_ledger_note\|repeat_flakes\|REPEAT FLAKE" -- '*.py'` → `0`
2. → `orchestrator.py:5564:    log.info(f"✅ UNIT BASELINE GATE PASSED — {detail}; baseline {baseline_note}")`
3. → `orchestrator.py:365:UNIT_BASELINE_CACHE_FILE = "unit-baseline-cache.json"   # in the sit-archive dir, gitignored`
4. → `.gitignore:34:sit-archive/*.json`
5. → `tests/test_baseline_reuse_1.py tests/test_config_truth.py tests/test_gate_cost.py tests/test_route_time.py tests/test_unit_baseline_gate.py tests/test_unit_confirm_errors.py tests/test_unit_fail_label.py tests/test_unit_gate_wording.py tests/test_unit_related.py`

## G-1
- `~/_eos/s7core59/laneA/rf836.patch` sha256 confirmed `fd1816568944a05e0d2d01a554322c1dd2cb7c18f9e5a0c41f3d2dc732890b21` before applying.
- Applied unchanged (test file first for RED, then `orchestrator.py`). The staged diff of the two files hashes to the same sha256 `fd18165…0b21`: 2 files changed, 170 insertions(+), 1 deletion(-). `orchestrator.py` parses (ast).

## RED / GREEN (`python3 -m pytest -q -p no:cacheprovider tests/test_repeat_flake.py`)
- **RED** (base `orchestrator.py` + new test file): `4 failed in 1.38s` (RF-1…RF-4).
- **GREEN** (after G-1): `4 passed in 1.14s`
  - `[RF-1] second route: (('src/lib/synth/wipe.test.ts', 2, '2026-11-21T22:00:00'),)`
  - `[RF-2] second detail: 2 failures, above the merge-base baseline of 1 — newly-failing file(s) confirmed FLAKY in isolation (passed alone, not blocking): src/lib/synth/wipe.test.ts (baseline cache) — REPEAT FLAKE (rule #17: a Bug Registry row and a fix row are owed): src/lib/synth/wipe.test.ts flaky in 2 routes since 2026-11-21`

## Suite run — not run by the executor
The brief's HANDBACK asks for the full orchestrator suite. I did not run it: the fire instructions and CLAUDE.md (ORCH-LEAN-GATE-1, D-S7CORE54-77) say to run only new or changed tests by path, and no `## Test scope: full` header is present. The pre-merge gate runs the full suite next. The dry run's suite result is `3276 passed, 4 skipped` at G-1.
- **`sit-archive/flake-ledger.json` after the run:** does not exist in the checkout (`ls` → No such file or directory). The new tests use their own tmp archive. STOP (f) still needs checking after the gate's full-suite run.

## STOP check
None hit: (a) no new RED · (b) only ALLOWED FILES touched · (c) no existing test edited · (d) A0 matches · (e) base is an ancestor · (f) no ledger in the checkout.

## Open (from the brief, for George / Gemma)
- Daemon restart after merge (rule #12).
- Ledger not seeded from past logs (sign-creates-final's 10). Per the brief's rec, leave it.
- qstat / nightly full gate do not show repeats yet.

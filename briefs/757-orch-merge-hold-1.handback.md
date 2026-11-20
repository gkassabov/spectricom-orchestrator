## STATUS: DONE

# ORCH-MERGE-HOLD-1 (Kanban 757; 621 slice 2 of 2) — handback

- **Base by ancestry:** `git merge-base --is-ancestor 2d6d7ef HEAD` → ok (HEAD `edc2b01f2ef85affc6b14c0690eeab4e3fac858b`; `2d6d7ef..HEAD` touches only 622's `scripts/opx_gameday.py`, `tests/test_opx_gameday.py` and its handback — none of this route's files).

## A0 at HEAD, before any edit (matches the brief — no STOP (d))
1. `git grep -n "^EXIT_STOPPED = 5" -- orchestrator.py queue_daemon.py` → `orchestrator.py:585:EXIT_STOPPED = 5` / `queue_daemon.py:64:EXIT_STOPPED = 5`; `git grep -n "EXIT_HELD\|MERGE HOLD" -- '*.py'` → none.
2. `git grep -n "elif route_wt is not None:" -- orchestrator.py` → `orchestrator.py:8055:                    elif route_wt is not None:` (one line).
3. `git grep -n "if outcome != GateOutcome.BLOCKED_ENV.value:" -- orchestrator.py` → `orchestrator.py:7415:    if outcome != GateOutcome.BLOCKED_ENV.value:` (one line).
4. `ls config/merge-hold.json` → `No such file or directory`.

## G-LINES (the reference patch, applied verbatim)
- `~/_eos/s7core57/dry/757/merge-hold-full.patch` sha256 `d3cfa4677a84d6554c61c749322c52d055387a0b7e69fcd490f1eb4ae0c1c08b` ✔ (matches the brief). Read in full before applying it; `git apply --check` clean at HEAD.
- The result is byte-identical to the patch's post-image (the `git hash-object` of each file equals the patch's index line): `config/merge-hold.json` `21064cb` (G-1) · `orchestrator.py` `f303427` (G-2) · `queue_daemon.py` `8f19c26` (G-3) · `tests/test_merge_hold.py` `06ed4a8` (G-4). 4 files, +509 / −7.
- Only ALLOWED FILES touched; no existing test edited; no `prefire.py` / `executor/**` / `admission.py` / `canon_assert.py` / settings edit.

## M-1…M-8: RED → GREEN
- **RED** (only `tests/test_merge_hold.py` applied, the source untouched): `python3 -m pytest tests/test_merge_hold.py -q -p no:cacheprovider` → **24 failed, 3 passed** — the 3 passing are the controls (`_exit_code_of` [passed, stopped] → 5, [passed] → 0; a plain PASS tip still refused). Matches the dry run.
- **GREEN** (source applied): the same command → **27 passed in 1.79s**.
- `python3 -m py_compile orchestrator.py queue_daemon.py` → OK.

## Full suite — not run by this executor
- The brief's handback line asks for `nice python3 -m pytest tests -q -p no:cacheprovider`. I did not run it: the brief's `## Test scope: targeted (D-S7CORE30-05)` header and the fire prompt / CLAUDE.md (ORCH-LEAN-GATE-1, D-S7CORE54-77) both say never run a full suite unless the brief has a `## Test scope: full — <George decision>` header. The orchestrator's pre-merge gate runs the full suite right after this route. The dry run's full suite was 3150 passed, 1 skipped (`dry/757/full.out`).
- `state/running*.json` → none present in the worktree.

## STOP checks
- (a)/(e) no red from this route's own test file; the full suite is the gate's to run. (b) nothing outside ALLOWED FILES. (c) no existing assertion changed. (d) A0 matched. (f) nothing merged, released or re-gated by this route.

## For Gemma (from the brief's OPEN ITEMS)
- **(a)** Restart the queue daemon right after this merges. Until then, a held route's exit 6 hits the old daemon's `else:` and is handled as a red (stop-on-failure pause).
- **(b)** The self-mod lane (`_self_mod_auto_merge`) is not held by this route; that is a follow-on row.

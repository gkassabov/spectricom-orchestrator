## STATUS: DONE

# ORCH-NPM-GUARD-TILDE-CD-1 (Kanban 979; Bug Registry v1-368) — handback

## Predecessor
`git merge-base --is-ancestor b827a9b HEAD` → exit 0 (HEAD = `b827a9b`).

## A0 (at HEAD, before any edit) — all as built
1. `executor/hooks/npm_frozen.py:488:def _cd(d, args: list):` → 1 line
2. `executor/hooks/npm_frozen.py:493:    if p == "-" or "$" in p or "`" in p or p.startswith("~"):` → 1 line
3. `executor/hooks/npm_frozen.py:521:        return None, _cd(d, args)` → 1 line
4. `git ls-files tests/test_npm_guard_tilde_cd_1.py` → nothing

## Patch
`sha256sum ~/_eos/s7core63/laneB/rtilde/ptilde.patch` → `3431546f93eb30a52e354ec4ac6150d4370a1aefd58244be9686baaf736c8c1a` (matches). Applied with `git apply` as written:
G-2 first (`--include=tests/test_npm_guard_tilde_cd_1.py`) for RED, then G-1 (`--include=executor/hooks/npm_frozen.py`). 2 files: npm_frozen.py +13 / −3, the new test +66.

## RED (base + G-2 only)
`pytest -q tests/test_npm_guard_tilde_cd_1.py` → **4 failed, 6 passed** (T1 ×3 and T2 red; T3 ×3 and T4 ×3 green). Matches the brief.

## GREEN (G-1 + G-2)
`pytest -q tests/test_npm_guard_tilde_cd_1.py tests/test_npm_frozen_hook.py` → **212 passed**. Matches the brief.
`py_compile executor/hooks/npm_frozen.py executor/hooks/long_wait.py` → ok.

## Whole suite
**Not run by the executor.** The brief's header is `## Test scope: targeted`, and both the repo's CLAUDE.md (ORCH-LEAN-GATE-1, D-S7CORE54-77) and the fire prompt forbid a full suite unless the header says `full — <George decision>`. The pre-merge gate runs the full unit suite. Gemma's dry run recorded 3348 passed, 5 skipped, 0 failed on the same patch.

## Environment note
This route worktree has no `venv/`. Tests ran with `~/spectricom-orchestrator/venv/bin/python` against the worktree's files. Nothing was linked or added to the worktree.

## Commit
See the commit sha in the route log (one commit: `executor/hooks/npm_frozen.py`, `tests/test_npm_guard_tilde_cd_1.py`, this handback).

## Takes effect
At the first Bash call of the next fire after merge (the hook file runs afresh on each call). No daemon restart.

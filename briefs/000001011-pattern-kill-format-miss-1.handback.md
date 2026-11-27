## STATUS: DONE

# PATTERN-KILL-DENY-1 + HANDBACK-FORMAT-MISS-1 (Kanban 1011) — handback

## Predecessor
`git merge-base --is-ancestor 5c8097f HEAD` → exit 0 (HEAD `2874ec6`).

## A0 (at HEAD, before any edit) — all as built
1. `git grep -nF "    return judge(nf, items, d, depth)" -- executor/hooks/long_wait.py` → `executor/hooks/long_wait.py:148:    return judge(nf, items, d, depth)`
2. `git grep -nF '        print(f"== handback: no {handback} at {sha}")' -- orchestrator.py` → `orchestrator.py:4766:        print(f"== handback: no {handback} at {sha}")`
3. `git grep -nF "def verify_route(stem: str, commit: Optional[str] = None) -> int:" -- orchestrator.py` → `orchestrator.py:4695:def verify_route(stem: str, commit: Optional[str] = None) -> int:`
4. `git grep -n -e pkill -e pgrep -- executor/ orchestrator.py` → nothing
5. `git ls-files tests/test_pattern_kill_format_miss_1.py` → nothing

## G-1
- `sha256sum ~/_eos/s7core64/laneE/pk.patch` → `d53ddf24f73bc788fb7c397792e228276c0844dd8352e320fe95de28ef0f407d` (matches).
- `git apply --check --stat` → 3 files changed, 190 insertions(+), 2 deletions(-).
- Applied in two steps (the test file only for RED, then the rest). The resulting `git diff` (with the new file added
  `-N`) hashes to `d53ddf24…f407d`, the same as the patch, so the tree matches the patch exactly.

## RED (base + the new test file only)
`venv/bin/python -m pytest -q tests/test_pattern_kill_format_miss_1.py` → **16 failed, 12 passed** (PK-1's 12 refused
commands, FM-1…FM-4 red; PK-1's 10 allowed commands, PK-2, PK-3 green) — the same as the dry run.
(The worktree has no `venv/` of its own; I used `~/spectricom-orchestrator/venv/bin/python`.)

## GREEN
- `tests/test_pattern_kill_format_miss_1.py` → **28 passed** in 1.98s.
- `py_compile` of `executor/hooks/long_wait.py`, `orchestrator.py` and the new test → exit 0 (Python repo, no tsc).

## Whole suite / GREEN family — not run in this fire (said)
The fire's operator instruction and CLAUDE.md (ORCH-LEAN-GATE-1, D-S7CORE54-77) say: run only the test files you added
or changed, never a suite or a related set, because the pre-merge gate runs the full suite next. The brief's header is
`## Test scope: targeted`, not `full — <George decision>`. So the neighbour family (`test_route_time.py`,
`test_npm_frozen_hook.py`, `test_npm_guard_tilde_cd_1.py`, `test_gate_cost.py`, `test_handback_stop_status.py`) and
the whole suite were left to the gate. The dry run's figures were: family 449 passed; whole suite 3397 passed, 1 skipped.
**Whole-suite count from this fire: none (the gate runs it).**

## Files
- M `executor/hooks/long_wait.py` (+70/−2)
- M `orchestrator.py` (+32)
- A `tests/test_pattern_kill_format_miss_1.py` (+90)
- A this handback

No existing assertion was edited. No file outside ALLOWED FILES was touched.

## Commit
The commit that adds this file. Its sha is in `git log -1` on branch `orch-orch-000001011-pattern-kill-format-miss-1`
(a file cannot hold its own commit's sha).

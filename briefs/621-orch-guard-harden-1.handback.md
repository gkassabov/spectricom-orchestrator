## STATUS: DONE

# 621 ORCH-GUARD-HARDEN-1 slice 1 — handback (executor: claude-opus-5-5, effort high)

## Base (by ancestry)
`HEAD` at fire = `f2c09f509bf351e5da8a8bfe1f5afd6e1ee3274d`; `git merge-base --is-ancestor f2c09f5 HEAD` → true.

## A0 at HEAD, before any edit (rule #7) — all four as the brief measured
1. `ls executor/settings/*.json | wc -l` → `6`; clinical-mp `deny[-1]` → `Edit(~/spectricom-orchestrator/state/preflight/**)`.
2. `sorted(hooks)` → `['PreToolUse']`; `ls executor/hooks/config_change.sh` → `No such file or directory`.
3. `['executor/**', 'orchestrator.py', 'prefire.py', 'prefire_opex_paths.json', 'queue_daemon.py', 'admission.py'] ['orchestrator.py', 'executor/**']`.
4. New test copied in first, at HEAD: **86 failed, 14 passed**. The 14 that pass match the brief: C-2 ×7 (preflight + kill hook ×6, orchestrator reads ×1), C-4 missing-hook fail-closed ×1, C-6 with-go ×2, C-7 AP-ORCH ×1, C-8 ×3.

## What landed (G-1…G-5)
- Reference patch `~/_eos/s7core57/dry/621/orch-guard-harden-1-full.patch`: sha256 `22c468b5306ed7fdd8b9de204ea7fdf308e2824d3838b0a3bf9dd253564a21b5` (matches the brief). `git apply --check` clean. I applied it with the test file excluded, because G-4 had already copied that file in. Afterwards:
  - `executor/hooks/config_change.sh` is byte-identical to `ref/` (`cmp`), mode 755 (G-1).
  - `tests/test_control_plane_guard.py` is identical to `ref/` and to the patch's copy (G-4).
- G-2: in all 6 settings files, the 11 control-plane `Edit(...)` denies sit in order before the preflight entry, and the preflight entry is still last. `hooks.ConfigChange` is the exact G-2 entry. All 6 files round-trip byte-identically through `json.dumps(indent=2, ensure_ascii=False) + "\n"`.
- G-3: `prefire_opex_paths.json` adds `queue_daemon.py` to `agent_runtime.orchestrator` and `canon_assert.py` + `config/**` to `protected.orchestrator`, plus two `_orchestrator_621` notes. The existing `_orchestrator` notes are unchanged. The file round-trips byte-identically.
- G-5 (G-621-1): only the three exact-list assertions changed (R1–R3 below).
- Diff: 12 files, +326 / −9, plus this handback. `git diff` on `orchestrator.py queue_daemon.py prefire.py admission.py canon_assert.py` is empty.

## Predicates RED → GREEN
| Predicate | HEAD (before) | After |
|---|---|---|
| C-1 (66) | RED (all fail) | GREEN |
| C-3 (6) | RED | GREEN |
| C-4 sources ×5 + bad input ×4 | RED (no hook) | GREEN |
| C-5 (1) | RED | GREEN |
| C-6 no-go ×3 | RED | GREEN |
| C-7 no policy id ×1 | RED | GREEN |
| Controls: C-2 ×7, C-4 missing-hook ×1, C-6 go ×2, C-7 AP-ORCH ×1, C-8 ×3 | green | green |

New file: **100 / 100 passed** after the change.

## Run (each once, as HANDBACK says)
`python3 -m pytest -q tests/test_control_plane_guard.py tests/test_guard_self_protect.py tests/test_prefire_obs_paths.py tests/test_route_time.py tests/test_toni_guards.py tests/test_npm_frozen_hook.py tests/test_opex_prefire.py` → **844 passed, 1 skipped in 54.18s**.
Tests collected per file: control_plane_guard 100, guard_self_protect 26, npm_frozen_hook 202, opex_prefire 108, prefire_obs_paths 63, route_time 91, toni_guards 255 (845 total). The dry run's "446 passed" for these seven files does not match these counts. Gemma may want to check the dry-run log. Nothing failed.
I did not run the full suite: the targeted scope and ORCH-LEAN-GATE-1 leave it to the gate. The brief's RULE #8 checklist ticks "full suite run", but that refers to the author's dry run (keep-green 3120 passed). There is no py_compile target change and no typecheck for this Python repo, so neither was run.

## RULE #8 — every search re-run at HEAD
- `git grep -lE "executor/settings|prefire_opex_paths|OPEX_PATHS|\"hooks\"\]" -- tests/` → **7 hits**: the brief's 6 (`test_guard_self_protect.py`, `test_npm_frozen_hook.py`, `test_opex_prefire.py`, `test_prefire_obs_paths.py`, `test_route_time.py`, `test_toni_guards.py`) plus **`tests/conftest.py`**. The conftest.py hit is only a docstring line (`:10`, "fire_toni adds `--settings executor/settings/<repo>.json`…"). It asserts nothing and is not a pin, so it was left alone.
- `git grep -nE "protected.*orchestrator|agent_runtime.*orchestrator" -- tests/` → exact-list pins at `test_guard_self_protect.py:93, :95` (**R1**, moved under G-621-1) and `test_prefire_obs_paths.py:129, :130-131` (**R2**, moved). Subset checks at `test_opex_prefire.py:319, :323` (R4) are still green and were not edited. `:75-77`, `:96`, `:99` (`_orchestrator` notes, unchanged) and `test_prefire_typed_go.py:22` (text) are not affected.
- `git grep -n PRE_698_DENY -- tests/` → `test_route_time.py:60` (definition) and `:597` (**R3**, now `PRE_698_DENY + CONTROL_PLANE_DENY_621`, with the module-level list beside `class TestP9Deny`). `deny[-1] == PREFLIGHT_DENY` is unchanged.
- R4 (`test_toni_guards.py` P2, `test_npm_frozen_hook.py`, `test_opex_prefire.py`) is green and was not edited.

## Not delivered (per the brief)
- The merge hold (Kanban 757).
- The Bash residual (route 620).
- A live `claude` canary of the ConfigChange block (OPEN ITEMS (a), owed by Gemma after merge).

## Notes
- No settings change was blocked during this fire, and no `.env` was read.
- The brief file `briefs/000000621-orch-guard-harden-1.md` was untracked at fire start. It stays untracked, as in earlier routes.

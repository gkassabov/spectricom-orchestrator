# Handback — 341i1-orch-unit-fail-label-1 (ORCH-UNIT-FAIL-LABEL-1, Kanban 528, S7-CORE-42, D-S7CORE42-02)

**Status: DONE.** F1–F5 are built in one commit, `f2953e8` (`orchestrator.py`, new `tests/test_unit_fail_label.py`, `tests/test_unit_baseline_gate.py` under rule #8). Nothing was edited in `queue_daemon.py`, `sit-archive/*`, the SIT parse, the shared triggers, `unit_full_every`, the related-set rule or the nightly schedule. No LLM judgement is involved. The whole clinical-mp suite was not run: one file for A0.2, and the PF8 preflight ran one related file.

## A0 · As built (HEAD `67cedf4`)

### 1. The code, file:line
- `orchestrator.py:3226` `_UNIT_VITEST_FAIL_RE = r"^\s*(?:❯\s+)?FAIL\s+(\S+)"`. The first token after `FAIL` is taken as the file.
- `orchestrator.py:3227` `_UNIT_VITEST_FILE_FAILED_RE = r"^\s*❯\s+(\S+)\s+\(\d+\s+tests?…failed"`. Same here: the first token after `❯`.
- `orchestrator.py:3243` `_norm_test_path`: strips whitespace, quotes and `./`, and nothing else.
- `orchestrator.py:3251` `_parse_unit_summary`: starts with `text = _ANSI_RE.sub("", raw)` (`_ANSI_RE` is at `:2276`). The failing set is read at `:3283–3285`.
- `orchestrator.py:3570` `_unit_confirm_new_files`: a file-level isolation re-run.
- `orchestrator.py:4634` `run_unit_gate`:
  - `:4822` `new_files = branch.failing_files − baseline.failing_files`
  - `:4826` `worse_count`
  - `:4860` AC-O6b-01/02 regression → FAIL
  - `:4891` AC-O6b-03 "count rose … with no newly-failing file — not blocking" → PASS
- Cache writer `_unit_cache_store` is at `:3775`; its entry fields are at `:3803–3826`, with `failing_files` at `:3814`.
- Cache reader `_unit_cache_lookup` is at `:3763`, and rehydration (`_unit_run_from_cache`) at `:4229`. `_unit_cache_ancestor` is at `:4243`, and the full-gate reuse check (`_full_gate_reusable`) at `:5960`.
- `_preflight_unit` is at `orchestrator.py:5408`. It names tests with `_preflight_failures` (`:5379`), which is shared with the SIT leg.

### 2. A real clinical-mp failing line
I used a clean detached worktree at clinical-mp `main` `9f5a6ffe`, with `node_modules` symlinked. `git grep -l "CACHE-GUARD-1" -- '*.test.*'` found `src/lib/cache/__tests__/write-invalidation-invariants.test.ts`, which holds the IcdCodeSearch/C1 guard. I ran it with the gate's confirm shape, `npm test -- src/lib/cache/__tests__/write-invalidation-invariants.test.ts`: exit 1, 6 failed | 16 passed (22). The capture held no ANSI. Raw lines:
```
 ❯ |app| src/lib/cache/__tests__/write-invalidation-invariants.test.ts (22 tests | 6 failed) 7293ms
 FAIL  |app| src/lib/cache/__tests__/write-invalidation-invariants.test.ts > CACHE-GUARD-1 — every rendered write path invalidates, bypasses, or says why not > GREEN — the real tree has no violations
 ❯ src/lib/cache/__tests__/write-invalidation-invariants.test.ts:148:61
 FAIL  |app| src/lib/cache/__tests__/write-invalidation-invariants.test.ts > CACHE-GUARD-1 — RED: the guard fails on a broken tree in the same run > C1 — remove CarePlanAssignDialog’s invalidation (the original CACHE-1 defect) and the guard names it
 ❯ src/lib/cache/__tests__/write-invalidation-invariants.test.ts:178:61
```
On HEAD this parses to `failing_files == ('|app|',)`, failures 6.

The workspace began on 2026-10-10 22:39 with clinical-mp `67a0fc1a`, the commit that added `projects: [{name: 'app'}, {name: 'journey'}]` to `vite.config.ts`. That falls between the last named cache entry (10-10 23:14, `3fb8593`) and the first blind one (10-11 03:24).

### 3. Why the cache holds `'app'`, not `'|app|'`
Vitest's `formatProjectName` (`node_modules/vitest/dist/chunks/utils.*.js:132`) prints `|app| ` when colour is off. When colour is on, it prints `c.black(bg( " app " )) + " "`. Colour is on when `TERM` is anything but `dumb` (tinyrainbow). The queue daemon runs with `TERM=xterm-256color`, `COLOR=0`, and neither `NO_COLOR` nor `CI` set (read from `/proc/<pid>/environ`).

The step that turns the label into `app`:
1. `_parse_unit_summary`'s `_ANSI_RE.sub("", raw)` (`:3254`) removes the escapes. That leaves ` FAIL   app  src/…`.
2. `FAIL\s+(\S+)` (`:3226`) then takes the bare token `app`.

The same parse turned a coloured fixture line into `('app',)` on HEAD.

Evidence that the gate (daemon) ran with colour while executor shells did not:
- `orchestrator-unit-log.json` has `app` 465 times and `|app|` 0 times.
- The executors' preflight `unit-confirm` lines read `|app|`.

**Caveat:** I could not make vitest print colour in this shell, even with `TERM=xterm-256color`, `FORCE_COLOR=1`, `--color` or a pty via `script`. Every attempt printed `|app|`. The colour step is therefore inferred from vitest's source, the daemon's environment and the logs, not reproduced. F1 handles both forms either way.

### 4. Tests covering this
- `tests/test_unit_baseline_gate.py`: the `vitest()` fixture, `run_gate` and `confirm_fake`. The AC-O6b-03 tests are:
  - `:203` `test_more_failures_with_no_newly_failing_file_passes_and_logs_the_delta`
  - `:1263` `test_ac_o6b_03_count_rose_with_no_newly_failing_file_passes_and_names_the_delta`
  - `:1604` `test_ac_o8_09_the_verdict_still_keys_on_confirmed_files_not_on_the_count`
  - `:1788` `test_orch6_and_6b_the_verdict_still_keys_on_confirmed_files`
  
  `:1281` `test_ac_o6b_05` (`if regressions:` is still the only verdict key) is unchanged and green.
- `tests/test_baseline_trust.py`, `tests/test_baseline_reuse_1.py` (the 290ea count-rise fixture) and `tests/test_unit_related.py` needed no edit.

## A1 · As built (`f2953e8`)

- **F1 · A project label is not a file.**
  - Both vitest regexes now capture the rest of the line.
  - One helper, `_unit_strip_project` (regex `_UNIT_PROJECT_LABEL_RE`), drops a leading `|app|`, `[app]`, or a bare token. A bare token counts as a label only when it has no `/` and a path follows it (not `>` or `[`).
  - `_unit_test_file` takes the path. Both regexes use these helpers, and the confirm pass reads its run through the same parse.
  - `_sit_failing_files` is unchanged. A test pins that it still returns `['|app|']`.
- **F2 · Failing tests are named.**
  - `UnitSuiteRun.failing_tests` is `<path> > <suite> > <test>` for vitest, with the label dropped. Only `FAIL` lines carrying ` > ` count; a file-level `FAIL  x [ x ]` stays a file. For pytest it is `<path>::<test>` from `FAILED`/`ERROR` lines.
  - The cache writer stores `failing_tests` beside `failing_files` as an additive field, and `_unit_run_from_cache` reads it back. A missing field means `None`, i.e. not named.
- **F3 · A blind baseline is no baseline.**
  - `_unit_is_blind`: failures > 0, and `failing_files` is either empty or holds a token that is not a test path. A test path has a `/` and either a `.test|spec.[cm]?[jt]sx?` suffix (the existing `_UNIT_TEST_FILE_RE`) or `.py`.
  - `_unit_cache_lookup` rejects a blind entry with one INFO line per entry: `♻️  Unit baseline: cached entry <key> rejected as BLIND — …; not read`. It returns None, so every reader behaves as on a miss:
    - per-route baseline → measured fresh
    - related baseline → the related files measured at the base
    - `_full_gate_reusable` → "no cached measurement", so the suite is run
    - the full gate's baseline hit → falls through to the ancestor
    - landed-store rule (g) → a named run may now be stored at that key
  - `_unit_cache_ancestor` skips blind entries and logs **one count line** (`N cached <repo> entries BLIND … not considered as an ancestor baseline`) rather than 221 lines. It is a scan, not a read of a baseline. Say if you want one line per entry there too.
  - Entries are never edited by the reader (PF3 test). A fresh measurement overwrites its own key through the existing `_unit_cache_store`, as before.
- **F4 · A rise nobody can name blocks (replaces AC-O6b-03).** This is the `elif worse_count:` branch of `run_unit_gate`, reached only when no file is newly failing:
  - **Cannot be named → BLOCKED.** If the branch has no `failing_tests`, or the baseline's are `None` (or empty while baseline failures > 0), or the named extras are fewer than the rise, the result is `BLOCKED`. Signal is `count-rise-unnamed`; detail reads "count rose by N and the new failures cannot be named (…)". Line: `⛔ Unit gate: … — BLOCKED, never PASS`.
    - The gate has no `BLOCKED(gate)` outcome, so this is `env=True`. It surfaces as `BLOCKED(environment) — unit: count-rise-unnamed — …`.
    - **Interpretation, flag for George:** fewer named extras than the rise (e.g. rise 2, one named) is treated as unnamed and BLOCKs, with no confirm run.
  - **Otherwise the extras' files are re-run alone.** This is the existing `_unit_confirm_new_files` with a new `tests=` mode that decides per test:
    - a test still failing alone ⇒ **FAIL(product) `regression`**, with detail `… still failing alone: <tests>; flaky in isolation, not blocking: <tests>`
    - all pass alone ⇒ **PASS**, with detail `… the N extra failing test(s) passed alone (flaky, not blocking): <tests>`
    - a confirm run that fails but names no test, or does not measure, ⇒ BLOCKED `confirmation-unmeasurable`
  - The confirm leg's clock is judged as in the file-level path.
  - Flaky tests are named in the verdict line only, **not** in `flaky_files`. That field is newly-failing *files*, and putting them there made the landed-store refuse rule (d) and turned 10 `test_baseline_reuse_1` tests red.
- **F5 · Preflight agrees.** `_preflight_unit` re-runs only failing entries that are test paths (`_unit_is_test_path`). It names tests from `run.failing_tests`, falling back to `_preflight_failures`, and matches them to confirmed files with `_unit_test_file`. A still-red labelled file is therefore under `failed`, never `flaky`.

## A3 · Predicates: RED (HEAD `67cedf4`) → GREEN (`f2953e8`)
`tests/test_unit_fail_label.py`, 23 tests: on HEAD in a scratch worktree, **17 failed, 6 passed**; on `f2953e8`, **23 passed**. The 6 that pass on HEAD are the controls.

| Predicate | Test(s) | HEAD | f2953e8 |
|---|---|---|---|
| PF1 `\|app\|` FAIL line, `❯ \|app\| …` line, `[app]` + coloured bare `app`, A0.2's real line | `TestPF1…` ×4 | RED (`('\|app\|',)`) | green |
| F2 failing_tests parsed and cached | `TestF2…` ×2 | RED | green |
| PF2 unlabelled vitest/pytest parse identical; SIT parse untouched | `TestPF2…` ×3 | green (control) | green |
| PF3 `('app',)`, 12 failures → rejected, gate measures; full gate does not reuse; entry not edited | `TestPF3…` ×3 | RED (`cache`) | green |
| PF3 control: a named entry is still a hit | `test_a_named_entry_is_still_read` | green | green |
| PF4 12→14, same files, +2 failing alone → FAIL(product) naming both; confirm = `npm test -- A B` | `test_pf4…` | RED (PASS) | green |
| PF5 +2 passing alone → PASS, flaky named; one of each → FAIL naming the red one | `test_pf5…` ×2 | RED | green |
| PF6 baseline names no test / pre-F2 cache entry / branch names no test / fewer extras than rise → BLOCKED | `test_pf6…` ×4 | RED (PASS) | green |
| PF7 12/12 PASS unchanged; a newly-failing FILE → today's regression path | `TestPF7…` ×2 | green (control) | green |
| F5 labelled preflight: confirm re-runs the path, red test in `failed`, `flaky == []`, no `\|app\|` | `TestF5…` | RED | green |

### PF8 live (read only)
I used a clean clinical-mp worktree at `main` `9f5a6ffe` on scratch branch `pf8-scratch-341i1`. One comment line was appended to `src/lib/cache/write-invalidation-invariants.ts` (the module the red CACHE-GUARD test imports) and committed. Then I ran `python3 <this route's orchestrator.py> preflight --repo clinical-mp --json /tmp/pf8.json`.

Afterwards the branch was deleted and the worktree removed; clinical-mp `main` and `node_modules` are untouched.

Summary (exit 1, a failure that is red at `main`):
```
🧪 Preflight unit run — pf8-scratch-341i1: 1 files/22 tests, 6 failed, 16 passed in 4.1s
🛡 unit-confirm: FAIL — still failing alone: src/lib/cache/__tests__/write-invalidation-invariants.test.ts; flaky: (none)
  SIT: 0 file(s) — pass — 0 affected by the diff against merge-base 9f5a6ff (--changed), 0 changed by the branch, 0 core (sit_core_files)
  unit: 1 file(s) — fail — 1 affected by the diff against merge-base 9f5a6ff (--changed), 0 changed by the branch; failing alone: src/lib/cache/__tests__/write-invalidation-invariants.test.ts (the gate calls a file a regression only if it is not failing at the merge base — not measured here) (the gate runs the FULL unit suite on this diff: (a) the diff touches a shared trigger …)
🧪 Preflight (executor): 0 SIT files / 1 unit files — fail (fail)
```
In the JSON unit leg:
- `files` = `[…/write-invalidation-invariants.test.ts]`
- `failed` = the 6 tests as `<path> > CACHE-GUARD-1 … > …`, including both C1 tests
- `flaky` = `[]`
- `|app|` occurs 0 times in `/tmp/pf8.json`

This is the 341h1c2 FL-4 case: the HOLD test is now filed failed, not flaky.

## Rule #8: test edits, old → new (`tests/test_unit_baseline_gate.py`)

**AC-O6b-03 tests, changed only to assert F4's verdict.** `run_gate`'s stub answers the confirm leg with the branch output, so the extra test fails alone and the result is FAIL(product). The fixtures are unchanged.
1. `:203` `test_more_failures_with_no_newly_failing_file_passes_and_logs_the_delta` → renamed `…_names_the_extra_test`.
   - old: `assert o.passed is True and o.signal is None`
   - new: `assert o.passed is False and o.signal == "regression"`, plus `f"still failing alone: {A} > suite > case 2" in o.detail`
   - the `"count rose from 2 to 3 with no newly-failing file" in o.detail` assert is kept
2. `:1263` `test_ac_o6b_03_count_rose_with_no_newly_failing_file_passes_and_names_the_delta` → renamed `test_f4_count_rose_with_no_newly_failing_file_names_the_test_that_fails_alone`. Same old/new as 1.
3. `:1604` `test_ac_o8_09_the_verdict_still_keys_on_confirmed_files_not_on_the_count` → renamed `test_ac_o8_09_a_count_rise_with_no_new_file_is_decided_by_the_named_tests`.
   - old: `assert o.passed is True`
   - new: `passed is False and signal == "regression"`, plus `still failing alone: {A} > suite > case 1; {A} > suite > case 2`
   - the "count rose from 1 to 3" assert is kept
4. `:1788` `test_orch6_and_6b_the_verdict_still_keys_on_confirmed_files` → renamed `…_keys_on_confirmed_files_and_named_tests`.
   - old: `assert o.passed is True, "[ORCH-6b]: a count delta alone is not a regression"`
   - new: `assert o.passed is False and o.signal == "regression", "[ORCH-UNIT-FAIL-LABEL-1] F4: …"`
   - the "count rose" assert is kept

**FLAG — beyond the literal rule #8 text.** Three cache tests cached a baseline whose fixture states failures but prints no `FAIL` line at all. That is exactly the blind entry F3 orders rejected, so they went from `cache` to `measured`:
- `:1528` `test_a_cached_baseline_reconciles_the_same_way_a_measured_one_does`
- `:1678` `test_a_cached_baseline_is_reconciled_the_same_way`
- `:1973` `test_ac_t1_07_the_cache_does_not_launder_it_back`

**Every assertion in them is byte-identical.** Only the baseline *input* changed. A new helper, `cmp_named(out, n)`, prepends n ` FAIL  src/cmp/f{i}.test.ts > suite > t{i}` lines and changes no tally:
- `fake_suite(vitest([B, B], failed=2), CMP_FIXTURE)` → `fake_suite(vitest([B, B], failed=2), cmp_named(CMP_FIXTURE, 9))`
- `fake_suite(CMP_FIXTURE, CMP_SHORT)` → `fake_suite(CMP_FIXTURE, cmp_named(CMP_SHORT, 9))`
- `fake_suite(CMP_EXPECTED_FAIL, CMP_EXPECTED_FAIL)` → `fake_suite(CMP_EXPECTED_FAIL, cmp_named(CMP_EXPECTED_FAIL, 4))`

The alternative was to weaken F3's "empty" clause, which the George-approved text names explicitly. If you would rather have that, revert these three inputs and drop `not failing_files` from `_unit_is_blind`.

## Gates
- `python3 -m py_compile orchestrator.py`: ok.
- Targeted, per the brief: `tests/test_unit_baseline_gate.py`, `test_baseline_trust.py`, `test_baseline_reuse_1.py`, `test_unit_related.py`, `test_unit_listing_prefix.py`, `test_unit_fail_label.py` gave **320 passed**.
- Related files that call the changed functions, with no edit:
  - `test_control_verdict_lines`, `test_gate_clock`, `test_gate_cost`, `test_orch_lane`, `test_exec_preflight`, `test_config_truth`: **232 passed**
  - `test_isolated_deps`, `test_route_ref_integrity`, `test_capacity`, `test_fullgate_reuse`, `test_fullgate_local_files`, `test_foreground`, `test_prelist`, `test_control_scope`: **266 passed**
- Full `tests/` was not run (header: Test scope: targeted).
- GATE PRE-LIST unit leg: the gate runs the full pytest suite at merge.

### Executor preflight (`python3 ~/spectricom-orchestrator/orchestrator.py preflight --repo orchestrator`)
```
  SIT: 0 file(s) — pass — orchestrator's gate has no SIT leg
  unit: ? file(s) — not computed — the gate runs the FULL unit suite — related selection not available for orchestrator — `pytest -q tests/` is not a vitest run
🧪 Preflight (executor): 0 SIT files / ? unit files — fail (not computed)
```
Exit 3, `not computed`. This is the standing R1 on pytest repos, as in 341a2/a3/a4: there is no related set to run, so the gate's full suite at merge decides. It is not a red produced by this change.

## Expected first-route effect on clinical-mp
- **Every clinical-mp cache entry since 2026-10-11 is blind.** There are now 221 of them (Gemma counted 219 at 17:40; two more landed by 22:41). All 221 are `('app',)` with failures > 0.
  - The first per-route gate after this merges logs one `rejected as BLIND` line and measures the merge base fresh. On the full suite that is a median ~824 s (max 1081 s across 67 full measurements since 10-25), within the 1800 s budget.
  - On a related-scope route, only the related files are measured at the base.
  - That measurement is named, and is cached with `failing_tests`. The next landing's branch run is stored as a named entry too, so the cost is once per tree, not per route.
- **Rises that went through on 11-02 are now decided by name.** On a route like 341g3s/g3t/h2r, a count rise with the same files names the extra tests and re-runs their files alone. Expect either FAIL(product) naming them or PASS listing them as flaky; never a silent PASS.
- **The first nightly full gate cannot reuse a blind entry, so it runs the suite.** Its `previous-full-gate` reference (state file) still holds `['app']`. The full gate's own comparison (`_full_gate_unit`, not in this brief's ALLOWED list) will therefore see every failing file as a suspect once. That fails toward isolation re-runs, not toward a merge.

## Findings for George (not fixed, out of ALLOWED)
1. **Orchestrator pytest cache entries written before F2 have no `failing_tests`.** A count rise with no new file over such a cached baseline now BLOCKs (`count-rise-unnamed`), as PF6 requires. This lasts until that tree is measured again. For clinical-mp this does not arise, since every recent entry is blind and is re-measured anyway.
2. **Other parsers still read the label as the file.** `_GATE_FAIL_FILE_RE` (`orchestrator.py:4998` at HEAD) is the F-20 classifier's FAIL-file reader. `_sit_failing_files` and `_preflight_failures` belong to the SIT parse and its SIT-leg reuse. All three would still read `|app|` on labelled output. They were left alone (SIT parse is STOP (a); the classifier is not in ALLOWED). On the unit path, F5 no longer relies on `_preflight_failures` for labelled output.
3. **`orchestrator-unit-log.json` still persists only `failing_files`.** `_log_unit_outcome` was not in ALLOWED. Adding `failing_tests` there would make rises auditable after the fact.

## Commits
- `f2953e8` feat(orch): the unit gate names the files and tests that fail (ORCH-UNIT-FAIL-LABEL-1)
- the handback commit (this file + the brief)

#!queue model=claude-opus-5-5 effort=high repo=orchestrator

# ORCH-TALLY-1: an expected fail is a tally, and the reconciliation counts it

## Repo: orchestrator
## Batch ID: s7core15-orch-tally-1
## Briefs: 1
## Estimated runtime: 30-45 min
## Spec reference: TALLY MISMATCH observed on the DATE-7 gate, 2026-09-26
## Predecessor: none. `main` at fire time, verified at `23ab07f` (GATE-SIT-2, "a red SIT verdict you can believe"). Every line number below was read at `23ab07f`. The file moved a lot on 2026-09-27, so re-verify each one with `grep -n` before you edit, and trust the file over this brief.

## 0 · FIRST STEP

Read these IN FULL before designing anything:

1. `orchestrator.py:1640-1700`: the vitest summary grammar. `_ANSI_RE` / `_VITEST_SUMMARY_RE` / `_VITEST_TOTAL_RE` / `_VITEST_PASSED_RE`, then the [ORCH-8] block `_VITEST_FAILED_RE` `:1656`, `_VITEST_SKIPPED_RE` `:1657`, `_VITEST_TODO_RE` `:1658`, `_VITEST_TALLY_RES` `:1660-1661`, `_parse_vitest_summary` `:1664`, `_parse_vitest_tallies` `:1684-1700`.
2. `orchestrator.py:1715-1728`: `_sit_tests_failed`. It is the SIT gate's copy of the same reconciliation (`passed + skipped + todo == total`). READ it so you recognise it. It is OUT of scope (§4) and must come out of this route byte-identical.
3. `orchestrator.py:2114-2192`: `UnitSuiteRun`. Fields `tests_skipped` `:2128` and `tests_todo` `:2129`, `collection` `:2139`, `tally_sum` `:2164-2171`, `tally_note` `:2174-2192` (the `TALLY MISMATCH on …` sentence is built at `:2190`). Then `UnitGateOutcome.tally_note` `:2236-2241`.
4. `orchestrator.py:2272-2305`: `_parse_unit_summary`, the vitest branch. The `out` dict `:2276-2279`, the tallies read at `:2291-2293`, the reported/derived split at `:2294-2300`.
5. `orchestrator.py:2423-2447`: `_run_unit_suite`. `_parse_unit_summary(raw)` at `:2445` is splatted into `UnitSuiteRun(**parsed)` at `:2446-2447`, so any key you add to `out` MUST exist as a `UnitSuiteRun` field.
6. `orchestrator.py:2602-2624` `_unit_cache_store` (the [ORCH-8] additive keys at `:2615-2618`) and `:2715-2724` `_unit_run_from_cache`. Also `UNIT_BASELINE_CACHE_VERSION = 1` at `:303` and `_unit_cache_load`'s version check at `:2579`.
7. `orchestrator.py:2877-2885`: the green fast path. `branch_green` at `:2885` reads `(branch_run.failures or 0) == 0`. This is the one consumer whose behaviour the derived-count correction moves (see §6 CONSEQUENCE).
8. `orchestrator.py:3005-3024` `_unit_done` (reads `o.tally_note` at `:3015`, logs it LOUD, appends it to `o.detail`) and `:3026-3060` `_log_unit_outcome` / `_side` `:3039` (persists `tally_sum` / `tally_agrees` at `:3049`).
9. `tests/test_unit_baseline_gate.py`: the harness `vitest()` `:30`, `repo` fixture `:70`, `active()` `:102`, `fake_suite()` `:118`, `run_gate()` `:139`, `baseline_runs()` `:701`. The [ORCH-8] fixtures `CMP_TESTS_LINE` `:1406`, `CMP_FIXTURE` `:1407`, `CMP_GREEN` `:1410`, and the [ORCH-9] block `CMP_SHORT` `:1613` plus `class TestTheGateReconcilesItsOwnNumber` `:1618` onward. Your tests go in this file, on this harness, as a new section after that class.
10. Evidence: `logs/orch-20260926-182746.log:35` (DATE-7) and `logs/orch-20260927-122214.log:36` (BASELINE-0). Both show BOTH legs off by exactly 1.
11. The runner's own grammar, which this brief quotes and you should confirm. `~/spectricom-clinical-mp/node_modules/vitest/dist/chunks/utils.BS4fH3nR.js:91-111` `getStateString` (vitest 4.1.4). It emits the segments in the order `failed | passed | expected fail | skipped | todo (total)`. It counts a `test.fails` that failed as expected into `expectedFail` and EXCLUDES it from `passed` (`:94-95`). The segment appears only when non-zero. READ ONLY: do not modify anything in clinical-mp.

## 1 · WHY THIS EXISTS

The unit gate's tally check ([ORCH-9], `UnitSuiteRun.tally_note`) is the reconciliation that makes a unit verdict trustworthy. The failure count it quotes must add up, with the other named tallies, to the total the runner itself states. It fires today on every clinical-mp route, on both legs:

```
logs/orch-20260926-182746.log:35  TALLY MISMATCH on orch-mp-41-date-7-…: 4 failed + 8754 passed + 8 skipped + 4 todo = 8770, but the runner states 8771
                                  TALLY MISMATCH on merge-base 02c0972: 4 failed + 8694 passed + 8 skipped + 4 todo = 8710, but the runner states 8711
logs/orch-20260927-122214.log:36  TALLY MISMATCH on orch-mp-45-baseline-0-… (same shape)
```

Root cause, established and re-verified at brief time. vitest 4.1.4 prints a fifth tally, `1 expected fail`. It comes from the deliberate `test.fails(...)` at `~/spectricom-clinical-mp/src/lib/clinical/__tests__/finalize-encounter.test.ts:353` (`git blame` → `fe6d97c5`, 2026-09-15, "toni-batch-s7core10-mock-1-strict-mock-and-server-exercise-01"). `_VITEST_TALLY_RES` (`:1660`) knows `failed`, `skipped` and `todo` only. `_VITEST_FAILED_RE` is `(\d+) failed\b` and does not match `1 expected fail`, so the segment is silently dropped and the sum is always 1 short.

There is a second, quieter effect of the same gap. When the summary has no `failed` segment, `_parse_unit_summary` DERIVES the failure count as `total - passed - skipped - todo` (`:2297-2298`). On a fully green clinical-mp run, that reads the expected fail as **1 failure**. That derivation reconciles against the total by construction, so it never warns. It is wrong silently, and it keeps the green fast path at `:2885` unreachable for clinical-mp, the exact state [ORCH-8] AC-O8-06 fixed for skipped/todo.

Why it matters: a warning that fires on every correct run trains everyone to ignore it, and the next GENUINE mismatch (the [ORCH-9] kind: counts that came from two different runs) will be ignored too. The fix must stop the warning on a correct run and ONLY there.

## 2 · THE TARGET STATE

The predicate already exists: `UnitSuiteRun.tally_sum` / `UnitSuiteRun.tally_note` (`orchestrator.py:2164`, `:2174`). EXTEND it. Do NOT author a second reconciliation function, module or property.

**Predicate RECONCILES(raw)**. For `r = UnitSuiteRun(ref="x", exit_code=0, **_parse_unit_summary(raw))`:

```
r.tally_sum == r.failures + r.tests_passed + (r.tests_expected_fail or 0)
                          + (r.tests_skipped or 0) + (r.tests_todo or 0)          # when all three of
                                                                                 # tests_total, failures,
                                                                                 # tests_passed are not None
r.tally_note is None   ⇔   r.tally_sum is None  or  r.tally_sum == r.tests_total
```

This must hold over this exact set. For every vitest `Tests` summary line whose named segments are a subset of {`failed`, `passed`, `expected fail`, `skipped`, `todo`}, `r.tally_note is None` iff the stated segments sum to the parenthesised total. Concretely:

| raw `Tests` line | failures (source) | tests_expected_fail | tally_sum | tally_note |
|---|---|---|---|---|
| `4 failed \| 8754 passed \| 1 expected fail \| 8 skipped \| 4 todo (8771)` (DATE-7) | 4 (reported) | 1 | 8771 | None |
| `8758 passed \| 1 expected fail \| 8 skipped \| 4 todo (8771)` (green, no `failed`) | 0 (derived) | 1 | 8771 | None |
| `4 failed \| 8754 passed \| 1 expected fail \| 8 skipped \| 4 todo (8772)` (off by one) | 4 (reported) | 1 | 8771 | `TALLY MISMATCH …` |
| `4 failed \| 8740 passed \| 1 expected fail \| 8 skipped \| 4 todo (8771)` | 4 (reported) | 1 | 8757 | `TALLY MISMATCH … 4 failed + 8740 passed + 1 expected fail + 8 skipped + 4 todo = 8757, but the runner states 8771 …` |
| `CMP_FIXTURE` / `CMP_GREEN` / `CMP_SHORT` (no `expected fail`) | unchanged | **None** (not 0) | unchanged | unchanged |

The shape of the change. The NEW names below are prescribed by this brief and do not exist yet:

- `_VITEST_EXPECTED_FAIL_RE = re.compile(r"(\d+) expected fail\b")` beside `:1656-1658`, and key `"expected_fail"` in `_VITEST_TALLY_RES`. `_parse_vitest_tallies` then returns `expected_fail` (None when absent), with no other change to that function. Its docstring names three tallies. Update it to four.
- `UnitSuiteRun.tests_expected_fail: Optional[int] = None` beside `:2128-2129`, with the same None-is-not-zero comment discipline.
- `_parse_unit_summary`: `out["tests_expected_fail"]` (initialised None in the `out` dict at `:2276-2279`, also None on the pytest branch), set from the tallies at `:2291-2293`, and subtracted in the derivation at `:2297-2298`. That derivation is the same invariant solved for `failed`: an expected fail is not a failure.
- `tally_sum` adds it. `tally_note` lists it in `parts` in vitest's print order (after `passed`, before `skipped`), only when not None. `collection` (`:2139`) renders `, N expected fail` in the same position, omitted when None.
- Persisted: `_unit_cache_store` (`:2615-2618`, additive, as [ORCH-8] did), `_unit_run_from_cache` (`:2722`) and `_side` (`:3045-3046`) carry `tests_expected_fail`. An entry written before this merge lacks the key and reads as None.

On A10: `expected fail` is the RUNNER's output grammar, the same category as `failed`/`skipped`/`todo` at `:1656-1658`. It is not a clinical threshold, band, cadence, row set, tier or vocabulary. No numeric domain value enters source. The counts in the table above live in TEST fixtures only.

## 3 · SCOPE

- `orchestrator.py`, only the regions named in §2: the tally grammar `:1656-1661`, the `_parse_vitest_tallies` docstring, `UnitSuiteRun` fields and its `collection` / `tally_sum` / `tally_note`, `_parse_unit_summary`'s vitest branch plus the `out` initialiser, and the three persistence sites.
- `tests/test_unit_baseline_gate.py`: one new section after `TestTheGateReconcilesItsOwnNumber`, with a comment banner in the file's existing style (`# ═══…` / `# S7-CORE-15 [ORCH-TALLY-1] — …`). Add a literal fixture `CMP_EXPECTED_FAIL` holding the DATE-7 line exactly as vitest prints it:
  ```
   Test Files  4 failed | 1030 passed (1034)
        Tests  4 failed | 8754 passed | 1 expected fail | 8 skipped | 4 todo (8771)
     Duration  …
  ```
  The `Test Files` figures are illustrative. **Open question:** the DATE-7 log line does not record the file count. Pick any self-consistent pair, and say so in the fixture's comment. Do not present it as observed.
- No edits to existing tests. Every existing test in `tests/test_unit_baseline_gate.py` must pass UNMODIFIED. That is the proof that files without an `expected fail` segment are untouched.

## 4 · OUT OF SCOPE (do NOT touch)

- **The unit baseline gate's pass/fail semantics.** Do not change the regression rule, the flake confirmation, `branch_green`'s condition at `:2885`, `UNIT_GATE_SKIP_BASELINE_WHEN_GREEN` (`:320`), any timeout constant, or the rule that a mismatch reports and never decides ([ORCH-9] AC-O9-07, `test_the_check_reports_and_never_decides`).
- **`UNIT_BASELINE_CACHE_VERSION` (`:303`) stays 1.** This is decided in this brief. Bumping it would force a re-measure, but it would also empty the pool `_unit_cache_ancestor` falls back on, so a baseline-leg failure right after merge would go `unmeasurable` instead of `ancestor-cache`. The field is additive, as [ORCH-8]'s were. The cost is stated in §6.
- **The SIT gate.** `_sit_tests_failed` (`:1715-1728`), the SIT batch aggregation inside `_run_sit_batched` (`:1809`, the tallies at `:1833-1853`), `run_sit_post_merge` (`:1952`) and `SitOutcome` (`:1589`) stay byte-identical. `_parse_vitest_tallies` gains one key, which no SIT consumer reads (they index `t["skipped"]`, `t["todo"]` and `tallies.get(...)` by name). → **Successor ORCH-TALLY-2:** `_sit_tests_failed`'s reconciliation (`:1725`) omits `expected fail` too, so a SIT summary with an expected fail and no `failed` segment reads its failure count as None (unknown) rather than 0. **Open question for that successor:** whether `finalize-encounter.test.ts` is in clinical-mp's SIT set at all, which decides whether that is live.
- **The pytest runner path** (`_parse_unit_summary` `:2306-2334`). → **Successor ORCH-TALLY-3:** `tally_sum` has no term for pytest's `xfailed`/`xpassed`. `tests_total` includes them (`:2326`), so a pytest summary carrying either would trip `TALLY MISMATCH` the same way. `config/repos.yaml:27`, `:68`, `:94` declare pytest `test_cmd`s. Do not fix it here. Record it in §7.
- **Anything in `~/spectricom-clinical-mp`.** The `test.fails` at `finalize-encounter.test.ts:353` is deliberate (its own comment: "`test.fails` keeps the defect visible") and stays.

## 5 · ACCEPTANCE

Write the tests FIRST and run them against unmodified `orchestrator.py` at `23ab07f`. Tests AC-T1-01 through AC-T1-07 must fail there (the RED count is **7 test functions**, not counting parametrize cases). AC-T1-08 and AC-T1-09 are guards that are green before AND after.

- **AC-T1-01 (RED).** `_parse_unit_summary(CMP_EXPECTED_FAIL)` returns `failures == 4`, `failures_source == "reported"`, `tests_expected_fail == 1`, `tests_skipped == 8`, `tests_todo == 4`, `tests_total == 8771`. Red at `23ab07f` (no such key).
- **AC-T1-02 (RED): the DATE-7 run reconciles.** `run_gate(repo, tmp_path, branch_out=CMP_EXPECTED_FAIL, baseline_out=CMP_EXPECTED_FAIL)` under `caplog` at WARNING. `o.branch.tally_sum == o.baseline.tally_sum == 8771`, `o.tally_note is None`, and `"TALLY MISMATCH"` appears in neither `o.detail` nor `caplog.text`. `entries[-1]["branch"]["tally_agrees"] is True`, `entries[-1]["branch"]["tests_expected_fail"] == 1`. Red at `23ab07f`: sum 8770, two mismatch notes.
- **AC-T1-03 (RED): an expected fail is not a derived failure.** On `      Tests  8758 passed | 1 expected fail | 8 skipped | 4 todo (8771)` with exit code 0: `failures == 0`, `failures_source == "derived"`, `tally_note is None`. Through `run_gate(..., branch_out=<that summary with a Test Files line>, seen=seen)`: `o.baseline_source == "not-needed"` and `baseline_runs(seen) == []`. Red at `23ab07f`: failures 1, baseline leg runs.
- **AC-T1-04 (RED): a GENUINE mismatch still warns, and names the expected fail.** On the `8740 passed … (8771)` row of §2 as the branch leg (baseline `CMP_EXPECTED_FAIL`): `o.branch.tally_sum == 8757`, and `"4 failed + 8740 passed + 1 expected fail + 8 skipped + 4 todo = 8757"` and `"but the runner states 8771"` are both in `o.detail`. `"TALLY MISMATCH on route"` is in `caplog.text`. `"TALLY MISMATCH on merge-base"` is NOT in `o.detail`. Red at `23ab07f` (the parts string lacks the segment, and the sum reads 8756).
- **AC-T1-05 (RED): the log line carries it.** `o.branch.collection` contains `"4 failed, 8754 passed, 1 expected fail, 8 skipped, 4 todo"` in that order. For `CMP_FIXTURE` it contains no `"expected fail"`.
- **AC-T1-06 (RED): absent is None, not 0.** For each of exactly these existing module-level fixtures in `tests/test_unit_baseline_gate.py`: `VITEST_ZERO` `:45`, `PYTEST_RED` `:46`, `PYTEST_GREEN` `:49`, `CMP_FIXTURE` `:1407`, `CMP_GREEN` `:1410`, `CMP_SHORT` `:1613`. None of them carries the segment, and the helper `vitest()` `:30` is excluded because it builds lines per call. `_parse_unit_summary(...)["tests_expected_fail"] is None`. Red at `23ab07f` (KeyError).
- **AC-T1-07 (RED): the cache does not launder it back.** The two-run pattern of `test_a_cached_baseline_is_reconciled_the_same_way`, with `fake_suite(CMP_EXPECTED_FAIL, CMP_EXPECTED_FAIL)`. On the second run `o.baseline_source == "cache"`, `o.baseline.tests_expected_fail == 1`, and `"TALLY MISMATCH"` is not in `o.detail or ""`. Red at `23ab07f`.
- **AC-T1-08 (GUARD, green before and after): the fix does not silence the check generally.** Parametrised over exactly these two lines: the off-by-one row of §2 (`… (8772)`) and `CMP_SHORT`. For each, `UnitSuiteRun(ref="route", exit_code=1, **_parse_unit_summary(line)).tally_note` is not None and contains `"TALLY MISMATCH on route"`. The one-short case is the insidious one: the new term must not absorb an unrelated off-by-one.
- **AC-T1-09 (GUARD): SIT and gate semantics untouched.** Over the set {`_sit_tests_failed`, `_run_sit_batched`, `run_sit_post_merge`, `run_unit_gate`}, the function body source at `HEAD` equals the body at `23ab07f`. Extract by `def` line, in the style of `test_ac_o9_04_…` at `tests/test_unit_baseline_gate.py:1674`. Skip with a reason if `23ab07f` is not reachable. Also `orchestrator.UNIT_BASELINE_CACHE_VERSION == 1` and `orchestrator.UNIT_GATE_SKIP_BASELINE_WHEN_GREEN is True`.
- **AC-T1-10: reachability (D-S7CORE9-01).** Nothing new is reachable only from tests. State in the handback, with file:line at your HEAD, the production chain the new field travels:
  - `run_pre_merge_gates` (`:3206`) → `run_unit_gate(repo_path, branch_name)` (`:3277`) → `_run_unit_suite` (`:2860`) → `_parse_unit_summary` (`:2445`) → `UnitSuiteRun(**parsed)` → `_unit_done` reads `o.tally_note` (`:3015`) → `UnitGateOutcome.tally_note` → `UnitSuiteRun.tally_note` → `tally_sum`.
  - For the cache: `_unit_cache_store` writes the key, and `_unit_run_from_cache` reads it.
  - `_VITEST_EXPECTED_FAIL_RE` is reached only through `_VITEST_TALLY_RES` in `_parse_vitest_tallies`. There is no other reference.
- **AC-T1-11: the gate.** `pytest -q tests/` at merge-base `23ab07f` gives `P0 passed / F0 failed`. MEASURE both, and do not copy a number from an earlier brief. On the branch it gives `P0 + k passed / F0 failed`, where k is the new test cases collected. No test that passed at `23ab07f` fails on the branch. State P0, F0, k and the branch counts.

## 6 · HANDBACK

**§7 FIRST: what you found and LEFT, and why.** At minimum:

- (a) `_sit_tests_failed` `:1725` omits the expected fail (→ ORCH-TALLY-2), and whether you could settle if it is live.
- (b) The pytest path's missing `xfailed`/`xpassed` term (→ ORCH-TALLY-3). Say whether any pytest repo's recent unit-log entry already shows `tally_agrees: false`, from `orchestrator-unit-log.json`, read only.
- (c) Anything else you tripped over.

Give each one file:line and one sentence on why it is not this increment.

Then:

1. **What shipped.** Files touched, the final field and regex names, and the final `tally_sum` expression as a one-liner.
2. **Red before green.** Paste the 7 red failures from `23ab07f` (assertion line each), then green.
3. **Gate table.**

   | run | passed | failed | note |
   |---|---|---|---|
   | merge-base 23ab07f | P0 | F0 | measured, date it |
   | this branch | P0 + k | F0 | k = new test cases |

   Add an AC → test name → pass/fail row per AC.
4. **THE CONSEQUENCE (D-S7CORE13-03).** Say it plainly:
   - `TALLY MISMATCH` stops firing on clinical-mp routes where the only gap was the expected fail. That has been every route since `fe6d97c5` (2026-09-15), on both legs.
   - On a clinical-mp run with NO `failed` segment, the derived failure count drops from 1 to 0. The green fast path (`:2885`) therefore becomes reachable for clinical-mp again. A fully green branch now SKIPS the baseline leg (one whole-suite run fewer per route) and its note reads `not measured — branch is fully green`. The verdict for such a branch is unchanged: it passed before too.
   - The unit-gate log line and `orchestrator-unit-log.json` entries gain `, 1 expected fail` / `"tests_expected_fail"`. The cache entries gain the key.
   - The cache version is deliberately NOT bumped (decided in §4). So a baseline cached BEFORE this merge, whose summary had both a `failed` segment and an expected fail, will STILL show `TALLY MISMATCH on merge-base …` until that merge-base is re-measured, which happens once clinical-mp `main` moves. That warning is true about the stored record. Tell the owner to expect it on the first route(s) after merge and not to read it as a regression of this fix.
   - When someone fixes the Minime emitter and promotes `finalize-encounter.test.ts:353` to a plain `test`, the segment disappears, the field reads None, and nothing else changes.
   - SIT gate: no behaviour change. The pytest path: no behaviour change (its field is always None).
5. **Open questions you could not settle.** Known at brief time:
   - The `Test Files` counts in `CMP_EXPECTED_FAIL` (§3).
   - Whether vitest versions other than 4.1.4 spell the segment the same way. Only `utils.BS4fH3nR.js:109` was read.

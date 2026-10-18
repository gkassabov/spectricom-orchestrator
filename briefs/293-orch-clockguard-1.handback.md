# filename: briefs/293-orch-clockguard-1.handback.md
# HANDBACK — 293 · ORCH-CLOCKGUARD-1 (S7-CORE-31, SCA-ORCH-CLOCKGUARD-1)

Branch `orch-orch-293-orch-clockguard-1` off `7d38cab`. Executor claude-opus-5-5 --effort xhigh. No daemon restart:
`queue_daemon.py` is unchanged and spawns `orchestrator.py` per route, so the next route picks this up.

## 0 · As built (L-30)

```
$ git log --oneline 81ef432..HEAD
7d38cab handback: 290eba-orch-baseline-reuse-1 — as-built (…)
306a2a1 fix(orch): a landed route's unit branch run becomes the cached baseline of the com…
$ git diff 81ef432 HEAD -- orchestrator.py canon_assert.py | grep '^@@'   (function context, uniq)
  class GateVerdict / class UnitGateOutcome / _run_batch_inner ×2 / _unit_baseline_measure_or_reuse /
  _unit_cache_lookup / _unit_cache_record_flakes / _unit_cache_store ×2 / run_pre_merge_gates / run_unit_gate ×2
```
306a2a1 touched three functions this brief names. I re-read each one at HEAD:
- `_unit_baseline_measure_or_reuse`: only the cache-hit note text (`(a route's branch run)`). The clock/trust path is unchanged.
- `run_unit_gate`: only `branch_sha` / `branch_tree_why`.
- `run_pre_merge_gates`: only `unit=uo` on the PASS verdict.

It also added a new reader of the branch clock: `(b) the branch leg's clock is implausible`, now at `orchestrator.py:3631`. No clock function changed. Because 306a2a1 added 143 lines, the brief's `orchestrator.py` line numbers are about 75-100 lower than HEAD's. HEAD's numbers are used below.

**Premises:** all three hold.
- Clauses 1-3 are at `canon_assert.py:1137-1145` (HEAD).
- The classifier's rule 4 is at `orchestrator.py:4493-4496` (HEAD). It returns BLOCKED(environment) `clock-implausible` even after `isolation.confirmed`, because rule 3 only sets the `product` text (`:4481-4485`) and falls through.
- The baseline path is `:4026-4047` (HEAD). The verdict is `baseline-clock-implausible` at `:4208`.
- The 282c case: `logs/clinical-mp/orch-282c-…-152033.log:65-67,97-98`. The 4 samples, in the store's order, were 1.81 / 12.85 / 11.45 / 3.87 s, median 7.66.
- Each of those samples is a 1-file leg in the logs ("1 file(s)"). The one multi-file isolation leg in the logs (3 files, route 95, 2026-10-04) ended `isolation-unmeasurable`, so it was never recorded. The premise "4 single-file samples" holds.

**Find 1 — callers of `check_clock_plausibility` and what each does with a violation:**
```
$ git grep -n check_clock_plausibility HEAD -- '*.py' ':!tests'
canon_assert.py:1113 (def) · orchestrator.py:54 (import) · :379 (comment) · :1913 (the one call, in _judge_leg)
```
`_judge_leg` (`:1902`, HEAD) is the only caller. It logs one `🛡` line and returns the violation. It records a sample only when the leg is plausible and complete. What each of its callers does with the violation:

| leg (HEAD line) | consumer → verdict on a violation |
|---|---|
| build `_run_leg` `:1985` | `BuildGateOutcome.clock` → classifier rule 4 (`:4630`) → BLOCKED `clock-implausible` on a red |
| sit-run `_run_leg` `:2617` | `SitOutcome.clock` → rule 4 (`:4657`) |
| sit-batch / sit-batch-related `_run_leg` `:2388` | first one → `_SitBatchedRun.clock` → `SitOutcome.clock` → rule 4 |
| sit-isolation `_judge_leg` `:2534` | `SitIsolation.clock`; `clock = clock or isolation.clock` `:2665` → rule 4, **even after a confirmed file** (the 282c defect) |
| unit-branch `:4155` / unit-confirm `:4257` | `UnitGateOutcome.clock` (the first of branch, baseline, confirm) → rule 4 (`:4686`), detail amended at `:4689`; the 290eba route-branch cache refuses to store (`:3591`) |
| unit-baseline `:4026`, `:4040` | discard and re-measure once; a second violation → `"implausible"` → BLOCKED `baseline-clock-implausible` (`:4045`, `:4208`); never cached |
| full gate unit `:4965` / confirm `:5006` | BLOCKED `clock-implausible` (`:5002`, `:5014`); not cached (`:4995`) |
| full gate SIT `:4928` | through the same classifier as the per-merge gate |

**Find 2 — how the history is stored and keyed:** `sit-archive/gate-durations.json` (`GATE_DURATIONS_*`, `:383-385` at HEAD), shaped `{version 1, repos: {repo: {leg kind: [{at, d_wall, d_monotonic}]}}}`. It is keyed by repo and leg kind only, with **no file count**, and holds the newest 20 per kind. The reader is `_gate_durations_history` (`:1878`), the writer is `_gate_durations_record` (`:1885`), and `_judge_leg` is the only caller of both. The only file-count split before this brief was ORCH-GATE-COST-1 D3's separate kind `sit-batch-related`.

The live store, read-only: every sample has only `at/d_wall/d_monotonic`. clinical-mp `sit-isolation` now holds 6 samples, `[1.81, 12.85, 11.45, 3.87, 4.57, 3.39]`.

**Find 3 — tests that assert clause 3 with both boottimes present:** all three are in `tests/test_gate_clock.py`. In that file, `_judge(d_boot=None)` means boottime is present.
- `TestBounds::test_outlier_5_0x_is_plausible_5_01x_is_not:305`
- `TestBounds::test_median_not_mean:311`
- `TestHistory::test_three_plausible_samples_wake_the_outlier_clause:412-414`, where the gate fixture's `Clock()` has boottime

After the change, the targeted set failed on exactly these three tests and nothing else. No test asserts that a confirmed isolation red is BLOCKED(environment).

## 1 · K1-K3 as built

**K1 — clause 3 is a note when the clock is measured**
- `canon_assert.py:1151`: `check_clock_plausibility` returns `outlier-vs-history` only when `d_boot is None`. Clauses 1 and 2 are unchanged (`:1146-1149`).
- `canon_assert.py:1156`: `_clock_outlier_median` holds clause 3's arithmetic, shared by both functions.
- `canon_assert.py:1165`: `clock_slow_note`, new and pure. It returns `"<leg> Δwall <x>s > <f> × median <m>s; clocks agree"` only when both boottimes are known, there is no violation, and Δwall is over the bound.
- The header formula (`:1070-1083`) and the docstring were updated. Constants are unchanged.
- `orchestrator.py:1961-1967`: `_judge_leg` logs exactly one line for such a leg: `🛡 clock-plausibility: SLOW — <note> (Δmonotonic …, Δboottime …); <history> [red|green: the verdict is what the leg measured]`. It returns None (plausible) and records the sample.
- So every consumer in the Find 1 table treats a SLOW leg as plausible: PASS stays PASS, a red stays a red, and a slow baseline is trusted and cached.
- With a boottime missing, clause 3 is the IMPLAUSIBLE violation exactly as before.

**K2 — a confirmed red is never voided**
- `orchestrator.py:4525-4536`: in `_classify_gate_failure` rule 3, `isolation.confirmed` now **returns** FAIL(product) naming the file(s). It no longer falls through to rule 4.
- A violation on the isolation leg itself (`isolation.clock`) adds ` (measured on an implausible clock — re-run before believing: <violation>)` beside the files (`:4528`).
- Another leg's violation is said as `; another leg's clock (<v>) does not void a file confirmed alone`, plus a `🔎 F-20 … the clock does not void it` line.
- Unchanged: `isolation-unmeasurable`, `batch-contamination`, a skipped isolation, rules 1 and 2, and rule 4 for every red without a confirmed file (all of build and unit).
- The full gate's SIT leg calls the same classifier (`:4978`), so it gets K2 with no change of its own. Its `failing_files` was already `iso.confirmed`.

**K3 — history keyed by what it measures**
- `orchestrator.py:391`: `GATE_DURATIONS_BUCKETS` = `1 / 2-10 / 11+`, a new constant.
- `:1884` `_gate_files_bucket`.
- `:1894` `_gate_durations_in`: a bucketed leg reads its own bucket plus the kind's unbucketed samples (that is, "read as its leg kind's"). A leg with no file count reads the whole kind, as before.
- `:1900` `_gate_durations_history(…, files=None)`.
- `:1909` `_gate_durations_record(…, files=None)`: new samples carry `"files": <bucket>`. The cap of 20 applies per bucket (counting the unbucketed samples that bucket reads), so another bucket's samples are kept and an old sample ages out as a bucket fills. No stored sample is rewritten. `GATE_DURATIONS_VERSION` stays 1.
- Callers pass `files=` only where the leg runs a list it was handed: SIT batches `:2428`, the isolation leg `:2575`, unit-confirm `:4299`, and the full-gate confirm `:5058`.
- Whole-suite legs (build, sit-run, unit-branch, unit-baseline / full-gate unit) have no bucket and behave exactly as before.
- `_run_leg` got a keyword-only `files` (`:1973`). The `🛡` history text names the bucket, e.g. `(bucket: 1 file)`.

**Unchanged, as the brief requires:** the CODE-GUARD, the handback guard, prefire, admission, the fire lock, timeout/hold, `queue_daemon.py`, the gate flow, thresholds and constants, and every verdict other than `clock-implausible` / `baseline-clock-implausible`. STOP (a) and (b) did not trigger.

## 2 · Tests changed (rule #8, pre-authorised), each assertion reversed
1. `tests/test_gate_clock.py::TestBounds::test_outlier_5_0x_is_plausible_5_01x_is_not:305`: `_judge(501.0, 501.0, history=h) == ["outlier-vs-history"]` became `== []`.
2. `tests/test_gate_clock.py::TestBounds::test_median_not_mean:311`: `_judge(501.0, 501.0, history=[100, 100, 100000]) == ["outlier-vs-history"]` became `== []`.
3. `tests/test_gate_clock.py::TestHistory::test_three_plausible_samples_wake_the_outlier_clause:407,412-414`: `(BLOCKED_ENV, "clock-implausible")` became `(FAIL_PRODUCT, "regression")`, `"unit-branch outlier-vs-history" in v.detail` became `not in`, and `samples == [336.7]*3` became `[336.7]*3 + [1700.0]`. The comment on `:407` was reworded to match.

Each reversed line carries an `ORCH-CLOCKGUARD-1 K1` comment. Reversing (1) and (2) dropped their no-boottime cases (the 5.0× / 5.01× bound and the median). Those cases are now in `tests/test_clockguard_1.py::test_P1_control_the_5x_bound_with_a_boottime_missing_as_today`. No other existing test changed.

New: `tests/test_clockguard_1.py` (38 tests). Its module-level imports are existing symbols only, so it collects on HEAD.

## 3 · Predicates RED → GREEN
RED on HEAD `7d38cab` (code unchanged, new file only): **22 failed, 16 passed**. All 16 passes are controls or cases already true at HEAD:
- P1 controls: no boottime, the 5× bound without boottime, wall-jump, suspend, constants
- P2 `plausible`
- P2 contamination / no-isolation / unmeasurable controls (×5), plus the end-to-end contamination controls (×2)
- P3 no-file-count store and cap (×2)
- P4 no-boottime control

The 22 failures, each for the defect or a missing symbol:
- P1: `assert ['outlier-vs-history'] == []`; `_judge_leg … ClockViolation(… outlier-vs-history, median=7.66) is None`; `no attribute 'clock_slow_note'`
- P2: `BLOCKED(environment) — sit: clock-implausible (sit-isolation outlier-vs-history: Δwall 70.1s > 5 × median 7.7s …)`, which is 282c verbatim. Also `… (sit-isolation suspended …)`, `… (sit-isolation wall-jump …)` and `… (sit-batch wall-jump …)`
- P3: `no attribute '_gate_files_bucket'`; `_gate_durations_history() takes 2 positional arguments`; `IndexError` (the 70.1 s leg was never recorded)
- P4: `BLOCKED(environment) — unit: baseline-clock-implausible (… unit-baseline outlier-vs-history: Δwall 1700.0s > 5 × median 338.8s …)`

GREEN: **38 passed**.
- **P1:** 282c clocks (Δwall 70.1, Δmono 70.1, Δboot 70.7, n=4 median 7.66) give no violation, exactly one `🛡 clock-plausibility: SLOW — sit-isolation Δwall 70.1s > 5 × median 7.7s; clocks agree …`, a return of None, and a recorded sample. Controls: boottime None gives outlier-vs-history and IMPLAUSIBLE, not recorded. Δwall − Δmono = 70.1 s gives wall-jump. A suspend gives suspended.
  - The brief's control number, "Δwall − Δmono 30 s", is inside `CLOCK_WALL_JUMP_S` = 60. That is not a wall-jump at HEAD or now, and the test asserts that too. The wall-jump control uses 70.1 s.
- **P2:** the 282c shape gives FAIL(product) naming `sit/integration/action-targets.integration.test.tsx`, both in the classifier (6 clock states) and end-to-end. The end-to-end run is the real `run_pre_merge_gates` → batch → `_sit_isolate` over the live store's 4 samples. It also covers the isolation leg suspended (FAIL(product) plus the note) and a batch leg across a host sleep (FAIL(product), no note). Control: a file that passes alone gives PASS `batch-contamination`, both plausible and after a host sleep.
- **P3:** a 1-file leg reads only 1-file samples (and is judged against median 4.0, not 100). An unbucketed sample reads as its kind's. Stored samples are untouched. The cap is per bucket. Whole-suite legs carry no bucket. The replay records `sit-isolation` as `"files": "1"` and the batch as `"2-10"`.
- **P4:** a 1700 s baseline on agreeing clocks against a 338.8 s median is trusted with one `🛡 baseline-trust: CLEAN`, measured once, cached `"clock": "plausible"`, and the gate gives FAIL(product) `regression`. Control: boottime None gives the baseline measured twice and BLOCKED `baseline-clock-implausible`, not cached.

## 6 · Gates (targeted, D-S7CORE30-05; no full suite)
- `python3 -m pytest tests/test_clockguard_1.py tests/test_gate_clock.py` gives **68 passed**.
- The files that import or drive a changed function (`_judge_leg`, `_run_leg`, `_gate_durations_*`, `check_clock_plausibility`, `_classify_gate_failure`, `_sit_isolate`, `_run_sit_batched`, `run_unit_gate`, `_full_gate_*`): `test_control_verdict_lines`, `test_gate_cost`, `test_baseline_reuse_1`, `test_baseline_trust`, `test_config_truth`, `test_sit_isolation_attributed`, `test_sit_rate_limit`, `test_unit_baseline_gate`, `test_sit_integration`, `test_orch_lane`, `test_gate_collection`, `test_fullgate_local_files`. Together with the two above: **637 passed**.
- `py_compile` is clean. No ruff or pyflakes is installed on this host.
- Before running, I checked that none of these files can fire a real executor. They either put a fake `claude` on PATH or patch `fire_toni`.

## 7 · Found and left
1. **On Linux the outlier clause no longer blocks anything.** CLOCK_BOOTTIME is always present here (WSL2). A red from a machine that was genuinely starved (all three clocks advancing, tests timing out) is now a product verdict, unless the isolation or confirm re-measure disagrees. That re-measure still runs for SIT and unit. This is K1 as decided, noted here as the residual risk. A SLOW leg is recorded, so the median follows a suite that really got slower.
2. **The unit confirm leg has no K2.** A unit regression confirmed alone (`unit-confirm`) is still BLOCKED `clock-implausible` when the branch or baseline leg has a clause 1/2 violation (`orchestrator.py:4740`, rule 4). K2 named the SIT verdict only, so this was left.
3. **Unbucketed samples stay until they age out.** Pre-K3 samples are read by every bucket of their kind until that bucket's own samples push them out. For clinical-mp that is `sit-batch-related` (20 mixed-size samples) and `sit-isolation` (6 samples, all 1-file). Until then, a 1-file related batch's median includes 10-file batches. That only makes the median higher (fewer notes; outliers count only without a boottime).
4. **sit-run has no bucket.** The single-invocation `sit-run` and the whole-suite unit legs have no file count before they run, so they stay unbucketed. They always run the whole suite, so that is like-for-like.
5. **K2's note covers clause 3 too.** It is given for any violation on the isolation leg, which includes clause 3 when a boottime is missing (the only way clause 3 is still a violation). On Linux that means clauses 1/2 only, as K2 states.
6. **Live store not touched.** I only read `~/spectricom-orchestrator/sit-archive/gate-durations.json` and the 282c / route 95 logs. Nothing was written there.

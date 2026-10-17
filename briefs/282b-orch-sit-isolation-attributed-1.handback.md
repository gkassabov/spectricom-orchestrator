# filename: briefs/282b-orch-sit-isolation-attributed-1.handback.md

# 282b · ORCH-SIT-ISOLATION-ATTRIBUTED-1: handback

**The isolation leg's suspects now include a file vitest attributes an error to (D1).** A suspect is any file that a red batch names in either of two forms:
- a `FAIL <file>` / `FAIL <file> > <test>` line, as before;
- vitest's `This error originated in "<file>" test file`, which is new.

Both forms are read from each red batch's **whole** text. The 10,000-char tail can hold neither, because vitest 4.1.4 prints every `FAIL` line on stderr *before* the Unhandled Errors block (Find 1, shown on real vitest output). No extra run is made. The rest of the leg is HEAD's:
- one refill pause, then each suspect run alone once;
- `contaminated` / `confirmed` / fail-closed `isolation-unmeasurable`;
- the cap.

**A red batched run with nothing named keeps HEAD's verdict and says so (D2):** `⚠️  SIT gate: isolation not engaged: no failing file named — …`.

**The leg's `🔬` line names each suspect and where it was named from (D3):** `… confirming in isolation before verdict: sit/…/f3 (error attribution), sit/…/f4 (FAIL line)`.

**Unchanged:**
- the classifier's text (`SitOutcome.output`, still the red tails);
- the F-20 check (`_sit_env_signal(raw)`, still the tails);
- `_sit_failing_files`, which V2 and the full gate's failing list read;
- every other verdict.

On route 281's gate log, the new parser names `sit/integration/home-up-next.integration.test.tsx` (error attribution). HEAD's parser names nothing (P4).

Commit: `93316e1` (`orchestrator.py`, new `tests/test_sit_isolation_attributed.py`). No existing test changed.

## §0 As built (L-30)

### Predecessor
```
$ git log --oneline 5ceca0b..HEAD -- orchestrator.py
c7da3d5 fix(orch): the full gate's worktree gets the repo's declared git-ignored SIT files — `full_gate_link_files:` i…
$ git diff 5ceca0b..HEAD -- orchestrator.py | grep "^@@"
@@ -393,6 +393,13 @@ BRIEFS_ONLY_NAMED_FILES = 5
@@ -4681,7 +4688,75 @@ def _full_gate_refusal(repo_name: str) -> Optional[str]:
@@ -4689,6 +4764,11 @@ def _full_gate_sit(wt: Path, archive: Path, previous: Optional[dict]) -> dict:
@@ -4820,6 +4900,7 @@ def _full_gate_dry_run(…
@@ -4829,6 +4910,9 @@ def _full_gate_dry_run(…
@@ -4850,6 +4934,17 @@ def _full_gate_dry_run(…
@@ -4915,11 +5010,23 @@ def full_gate(…
@@ -4946,7 +5053,8 @@ def full_gate(…
```
282 (`c7da3d5`) merged first. It touched `orchestrator.py`, but none of the functions this brief names: its hunks are at `:393` (a constant) and in the full gate. I re-read every function I changed after the merge. The only effect is a line shift of +7. Gemma's `:2621-2627` / `:2425` / `:4267` are `:2627-2634` / `:2432` / `:4274` at HEAD `dc8ec4e`.

### Premises re-proven (HEAD `dc8ec4e`)
```
$ git show HEAD:orchestrator.py | grep -n …
2359:def _run_sit_batched(sit_cmd: str, repo_path: Path, plan: SitPlan,
2393:            out.red_output += head + raw[-10000:]
2432:def _sit_failing_files(text: str) -> list:
2443:def _sit_isolate(sit_cmd: str, repo_path: Path, plan: SitPlan, files: list,
2520:def run_sit_post_merge(repo_path: Path, archive_path: Optional[Path] = None,
2599:            raw = b.red_output or (b.stdout + "\n" + b.stderr)
2627:        isolation: Optional[SitIsolation] = None
2630:            named = set(_sit_failing_files(raw))
4274:_GATE_FAIL_FILE_RE = re.compile(r"^\s*(?:❯\s+)?FAIL\s+(\S+)", re.MULTILINE)
$ grep -c '🔬' logs/clinical-mp/orch-281-drk-path-2-20261017-102852.log        # ~/spectricom-orchestrator, read-only
0
$ grep -c ' FAIL ' logs/clinical-mp/orch-281-drk-path-2-20261017-102852.log
0
$ python3 -c '…sit-archive/orchestrator-sit-log.json, the 2026-10-17T11:31:40 entry…'
{'passed': False, 'exit_code': 1, 'error': None, 'test_files_total': 62, 'test_files_passed': 61, 'tests_total': 239,
 'tests_passed': 236, 'tests_failed': 2, 'batches': 7, 'scope': 'related 62/116'}            # no 'isolation' key: the leg never ran
$ grep -n home-up-next ~/_eos/s7core31/chosen.txt
27:sit/integration/home-up-next.integration.test.tsx                                       # in the run's related set
```
Every premise holds as Gemma stated it.
- **The leg engages only on `FAIL` lines.** It engages only when `_sit_failing_files(raw)` names a file of the plan. That function reads only `_GATE_FAIL_FILE_RE` matches.
- **Route 281's gate:**
  - Batch 3/7 exited 1 with 2 failed assertions, and no F-20 signal fired: the verdict is FAIL(product) "no F-20 environment signal".
  - The log has no `🔬` line and no `FAIL` line.
  - The 800 chars the FAILED line quoted end in vitest's `This error originated in "sit/integration/home-up-next.integration.test.tsx" test file`, preceded by the `OperationOutcome … Unauthorized` serialized error.
- **The leg's other conditions all held**, so only the suspect list was empty:
  - `batch_mismatch` is None (no error);
  - `tests_failed` is 2;
  - there was no F-20 signal, or the verdict would have been BLOCKED.

### Find 1: what `raw` holds at the engagement point, and whether `FAIL` lines can fall outside it (HEAD)
- **What `raw` is:**
  - `_run_sit_batched` `:2386-2393` builds each batch's `raw = stdout + "\n" + stderr`.
  - For a red batch it keeps `head + raw[-10000:]` in `red_output`.
  - `run_sit_post_merge` `:2599` sets `raw = b.red_output`: the last 10,000 chars of each red batch, behind a `── SIT batch i/N ──` header.
- **Why `FAIL` lines can fall outside it.** vitest 4.1.4 (`node_modules/vitest/dist/chunks/index.BMXTnDNz.js`) prints the summary in this order:
  - `printErrorsSummary` `:2579-2600`: `Failed Suites`, then `Failed Tests`, each led by ` FAIL  <file> > <test>` (`:2668`). The `Unhandled Errors` block comes last (`printUnhandledErrors`, `cli-api.lDy4N9kC.js:2008`). All of this goes through `logger.error`, so it is on **stderr**.
  - The `Test Files` / `Tests` summary is printed through `this.log` (stdout).

  In `raw`, stderr comes after stdout. So the end of `raw` is the Unhandled Errors block, and every `FAIL` line sits *before* it. An Unhandled Errors block of about 10,000 chars or more pushes every `FAIL` line out of the tail. Each unhandled error is printed with `fullStack: true` and its serialized properties.
- **Shown on real vitest 4.1.4.** I used a scratch project `/tmp/vt-capture-282b` (it uses clinical-mp's `node_modules` read-only and never touches Medplum). File `b` fails one assertion. File `a` passes but raises unhandled `OperationOutcomeError('Unauthorized')` rejections.
  ```
  [out]  raw 2950 chars;  first FAIL line at 2581 chars from the end;  Unhandled Errors section 2070 chars   (1 rejection)
     HEAD  _sit_failing_files(tail) = ['sit/integration/b.integration.test.ts']
     282b  _sit_named_files(raw)    = {'…/b.integration.test.ts': ['FAIL line'], '…/a.integration.test.ts': ['error attribution']}
  [out2] raw 16218 chars; first FAIL line at 15848 chars from the end; Unhandled Errors section 15337 chars  (8 rejections)
     HEAD  _sit_failing_files(tail) = []
     282b  _sit_named_files(raw)    = {'…/b.integration.test.ts': ['FAIL line'], '…/a.integration.test.ts': ['error attribution']}
  ```
  `out2` has route 281's shape: the tail HEAD read holds the attribution and none of the `FAIL` lines. Route 281's whole batch text was not persisted (only `raw[-800:]` was logged, and the SIT log keeps a 1,000-char excerpt of all batches' stderr). I can't show 281's own `FAIL` lines, but the elimination above leaves truncation as the only way 2 failed assertions produced no suspect.

### Find 2: every vitest 4.1.4 form that names a file for a failure or an error
| Form (ANSI stripped) | Printed by | Stream | Parsed? |
|---|---|---|---|
| ` FAIL  <file> > <test>` (`<file>:<line>:<col>` only with `includeTaskLocation`, not set in `vitest.sit.config.ts`) | `printTaskErrors` `index.BMXTnDNz.js:2667-2668`, Failed Tests | stderr | **yes**, `FAIL line` (`_GATE_FAIL_FILE_RE`, HEAD's) |
| ` FAIL  <file> [ <file> ]` (a suite/collection error) | same, Failed Suites (`getFullName` of the file task `:2313-2314`) | stderr | **yes**, `FAIL line` |
| `This error originated in "<file>" test file. …` | `printErrorInner` `index.BMXTnDNz.js:1799`. `VITEST_TEST_PATH` is set from `worker.filepath` for every `Uncaught Exception` / `Unhandled Rejection` (`init.D98-gwRW.js:101-110`) | stderr | **yes, new**: `error attribution` (`_GATE_ERROR_FILE_RE`) |
| An `Unhandled Error` / `Unhandled Rejection` block | `printUnhandledErrors` `cli-api.lDy4N9kC.js:2008-2019` | stderr | names its file **only** through the attribution line above. That is the one vitest string that attributes the error (grep of `dist/` for `VITEST_TEST_PATH`: set at one place, read at one) |
| ` ❯ <file> (n tests \| m failed)` / `   × <test>` | `printTestModule` `:2241-2280` (`suiteFail` = `❯`, `utils.BS4fH3nR.js:24`) | stdout | **no**: redundant. A module is `failed` only when it has a failed test or a suite error, and each of those gets a `FAIL` line from `printErrorsSummary` in the same batch text |
| stack frames ` ❯ [fn] <path>:<line>:<col>` | `printStack` | stderr | **no**: a frame says where code ran, not which test file vitest attributes the error to. Route 281's frames (the out2 capture's too) sit in `node_modules`, and a shared helper frame would be a non-test path |

`vitest.sit.config.ts` sets no `test.name`, so no `|project|` prefix precedes the path on `FAIL` lines (`formatProjectName`, `utils.BS4fH3nR.js:132`). See §1.4.

### Find 3: existing tests of `_sit_failing_files` / `_sit_isolate`
- `tests/test_sit_rate_limit.py`:
  - `test_a_real_failure_in_a_batch_is_still_product` (`:283`);
  - `TestSitIsolation` (`:364-490`), which drives `run_sit_post_merge` with stdout-only batches whose `FAIL` lines sit inside the tail;
  - `TestSitVerdictInvariant` (`:493-543`), whose V2 reads `_sit_failing_files(so.output)`.
- `tests/test_control_verdict_lines.py` `TestSitIsolation` (`:195-221`) calls `_sit_isolate("sit", tmp_path, plan, files, archive)` positionally, and pins the P-SAY `🛡 sit-isolation:` lines.

None of them asserts an exact suspect list that the new form would change. Every isolation test there names its suspects by `FAIL` lines only.

## D1–D3 as built (`93316e1`)
- **D1: the suspects.**
  - `_GATE_ERROR_FILE_RE` (`orchestrator.py:4313`) is the sibling pattern: `This error originated in "([^"\n]+)" test file`, read after `_ANSI_RE` stripping. In the gate the path sits inside `\x1b[1m…\x1b[22m`.
  - `_sit_named_files(text)` (`:2453-2463`) returns `{file: [sources]}`. Paths are normalised (`_norm_test_path`) and each file appears once. The `FAIL` form is read through the unchanged `_sit_failing_files`, and the attribution form is added to it.
  - `_SitBatchedRun.named` (`:2345-2347`). `_run_sit_batched` fills it from each **red** batch's whole `raw` (`:2397-2398`), the same batches whose tails `red_output` keeps. Green batches are not read, as on HEAD.
  - `run_sit_post_merge` (`:2652-2670`):
    - The engagement condition is HEAD's, unchanged (`:2655-2656`).
    - `suspects = [f for f in plan.files if f in b.named]` (`:2657-2658`), in listing order.
    - `_sit_isolate(…, named_from=…)` (`:2660-2661`).
    - Nothing else in the leg changed: the pause, one run alone per suspect, `contaminated` / `confirmed`, `isolation-unmeasurable`, the cap, `as_log`, P-SAY.
  - `raw` (the tails) is unchanged. So `SitOutcome.output`, `_sit_env_signal(raw)`, the classifier, V1-V5 and the full gate's `_sit_failing_files(so.output)` read exactly HEAD's text, which is pinned by `test_control_the_classifier_reads_heads_text`.
- **D2: nothing named** (`:2663-2670`).
  - When the leg is owed (red, batched, no mismatch, ≥1 failed, no F-20 signal) and no file of this run is named, it logs: `⚠️  SIT gate: isolation not engaged: no failing file named — <n> failed assertion(s), no F-20 signal, and no red batch names a file of this run by a FAIL line or an error attribution[; named, not a file of this run: <≤5 names>]; nothing re-run alone`.
  - No `🛡 sit-isolation:` line is written: P-SAY says a control that was not engaged writes nothing.
  - No `🔬` line is written either, so `grep 🔬` still means "the leg ran".
  - The verdict is HEAD's FAIL(product), with the same detail string.
- **D3: where each suspect was named from.**
  - `_sit_isolate` takes `named_from: Optional[dict] = None` (`:2466-2467`).
  - The `🔬` line (`:2484`) says `<file> (FAIL line)`, `<file> (error attribution)` or `<file> (FAIL line + error attribution)` (`said`, `:2476`).
  - A direct call without `named_from` prints HEAD's line exactly (`test_a_direct_call_keeps_heads_line`).
  - The labels are constants `SIT_NAMED_FAIL` / `SIT_NAMED_ERROR` (`:2449-2450`).
  - The cap's `⚠️  SIT gate isolation skipped:` line now ends with the same list (`:2481`). The `🛡 sit-isolation: SKIPPED` line and `iso.skipped` are unchanged.

**Which verdicts can move (STOP (b) check).** The new suspect set contains HEAD's: whole text ⊇ tail, over the same red batches, plus the attribution form. A verdict can therefore differ from HEAD's only through the isolation leg, which is D1's verdict:
- HEAD's FAIL(product) with no leg can now become PASS (`batch-contamination`), FAIL(product) with `confirmed`, BLOCKED (`isolation-unmeasurable`), or FAIL(product) after a SKIPPED leg (the cap);
- a HEAD leg over S now runs over S′ ⊇ S, and an added file can be confirmed, unmeasurable, or push the count over the cap.

No batch is re-run (STOP (c)). Every new call is `<sit_cmd> -- <one file>` (`test_routes_281_shape`: `[f3, f4]`, after the batches).

## Tests changed
- **No existing test was changed.** The pre-authorised rule-#8 change was not needed.
- **New: `tests/test_sit_isolation_attributed.py`, 19 tests.**
  - It drives the real `run_sit_post_merge` → `_run_sit_batched` → `_sit_isolate` → `run_pre_merge_gates` → `_classify_gate_failure` / `sit_verdict_violations`, with only `subprocess.run` / `time.sleep` scripted.
  - Each script is a `(rc, stdout, stderr)` triple, so the stream order matches vitest.
  - The fixtures are vitest 4.1.4's own text: the section banners, the ` FAIL  ` lines, the `Unhandled Rejection` block and the attribution sentence, all from the `/tmp/vt-capture-282b` capture.
  - P4's fixture is the 281 log's 800 chars, verbatim, ANSI codes included.

## §3 Predicates

`python3 -m pytest -q tests/test_sit_isolation_attributed.py`:
- **RED on HEAD `dc8ec4e`: 11 failed, 8 passed.** The 8 that pass are the negative controls, which assert HEAD behaviour.
- **GREEN at `93316e1`: 19 passed.**

| Predicate | Test | RED at `dc8ec4e` | GREEN |
|---|---|---|---|
| P1 parser | `TestP1ErrorAttribution::test_the_parser_names_the_attributed_file` | `AttributeError: … no attribute '_sit_named_files'` | ✅ `list(named) == [f3]`, source `error attribution` |
| P1 passes alone | `…::test_passes_alone_is_contamination_not_product` | `AssertionError: FAIL(product) on a file that passed alone` | ✅ PASS `batch-contamination`; `contaminated == (f3,)`; batch 2/3 beside f4; one alone call `[f3]`; sleeps `[7, 7, 7]`; sit-log `isolation.contaminated == [f3]`; invariant `[]` |
| P1 control: fails alone | `…::test_control_fails_alone_is_product` | `isolation is None` (verdict FAIL(product) but nothing confirmed) | ✅ FAIL(product); `confirmed == (f3,)`; `confirmed failing alone: f3` in the detail |
| P1 control: verdict | `…::test_control_verdict_stays_product_when_it_fails_alone` | ✅ passes (HEAD) | ✅ |
| P2 fixture shape | `TestP2FailLineBeyondTheTail::test_the_fixture_is_the_shape` | ✅ passes (asserts the `FAIL` line is outside `raw[-10000:]`, and HEAD's parser over the tail names nothing) | ✅ |
| P2 still named | `…::test_still_named` | `f4's FAIL line was not read` | ✅ alone `[f4]`; `contaminated == (f4,)`; PASS; `f4 (FAIL line)` in the 🔬 line |
| P2 fails alone | `…::test_fails_alone_is_product` | `isolation is None` | ✅ FAIL(product), `confirmed == (f4,)` |
| P2 281 shape | `…::test_routes_281_shape` (the `FAIL` line beyond the tail + the attribution inside it) | `isolation is None` | ✅ alone `[f3, f4]` after one pause; both contaminated ⇒ PASS; `f3 (error attribution), f4 (FAIL line)` |
| P2 control: in the tail | `…::test_control_fail_line_inside_the_tail` | ✅ passes (HEAD) | ✅ |
| P2 control: classifier text | `…::test_control_the_classifier_reads_heads_text` | ✅ passes (HEAD) | ✅ `outcome.output == header + whole[-10000:]`; the `FAIL` line is not in it |
| P3 HEAD's verdict + the line | `TestP3NothingNamed::test_heads_verdict_and_the_line` | `'isolation not engaged: no failing file named' in caplog.text` fails | ✅ FAIL(product), detail `no F-20 environment signal in gate output (1 failed assertions) — product verdict stands` (HEAD's exactly); 4 calls, sleeps `[7, 7]`; no `isolation` key; no `🛡 sit-isolation:`; no `🔬` |
| P3 named outside the run | `…::test_a_named_file_outside_the_run_is_said` | the line is absent | ✅ one line, naming `sit/integration/other.integration.test.ts` |
| P3 control: named | `…::test_control_a_named_file_engages_and_says_nothing_of_it` | ✅ passes (HEAD) | ✅ |
| P3 control: environment | `…::test_control_environment_runs_say_nothing` (0 failed assertions, attribution present) | ✅ passes (HEAD) | ✅ no leg, no line: D-S7CORE10-02 decides |
| D3 each source | `TestD3TheLegSaysWhere::test_each_source` | 🔬 line ends `…: f3, f4` (no sources) | ✅ `…: f3 (error attribution), f4 (FAIL line)` |
| D3 both | `…::test_both_sources` | ends `…: f4`. HEAD names f3 only through the `FAIL` line | ✅ `…: f3 (FAIL line + error attribution)` |
| D3 control | `…::test_a_direct_call_keeps_heads_line` | ✅ passes (HEAD) | ✅ |
| P4 | `TestP4Route281::test_names_home_up_next` | `AttributeError` | ✅ `{'sit/integration/home-up-next.integration.test.tsx': ['error attribution']}` |
| P4 control | `…::test_control_heads_parser_named_nothing` | ✅ passes (HEAD) | ✅ `_sit_failing_files(LOG_281) == []`, unchanged |

### P4: live, read-only (the real 281 gate log, at `93316e1`)
```
$ python3 - <<'EOF'   # cwd: this worktree; reads ~/spectricom-orchestrator/logs/clinical-mp/orch-281-drk-path-2-20261017-102852.log
…
log bytes: 10051
_sit_named_files(log)   -> {'sit/integration/home-up-next.integration.test.tsx': ['error attribution']}
_sit_failing_files(log) -> []  (HEAD's parser, FAIL lines only)
```
The file is in the run's related set (`chosen.txt:27`). So with this change, 281's gate would have engaged the leg on `home-up-next` (error attribution), plus any file a `FAIL` line in batch 3's whole text named. Each would run alone after the pause. Run alone, it passed 3/3 (`~/_eos/s7core31/sit-alone-b281.log`, 8.78 s).

## §6 Gates

| Gate | Result |
|---|---|
| Targeted: `tests/test_sit_isolation_attributed.py` | RED 11 failed / 8 passed at `dc8ec4e`; GREEN **19 passed** in 0.14 s |
| Targeted, the existing isolation tests (`test_sit_rate_limit.py`, `test_control_verdict_lines.py`) | **89 passed, 1 failed**, the same on HEAD `dc8ec4e` and at `93316e1`. The failure is `TestRepoConfig::test_clinical_mp_declares_batching`, pre-existing: see §1.1 |
| Targeted, every other file that drives the real `run_sit_post_merge` (`test_gate_cost.py test_gate_collection.py test_sit_integration.py test_unit_baseline_gate.py`) | **301 passed** in 9.3 s |
| Full `pytest -q tests/` | **Not run** (brief, CLAUDE.md test scope, D-S7CORE30-05). The orchestrator's pre-merge gate runs it after this executor exits |
| Lint | `pyflakes` is not installed here. `python3 -m py_compile` is OK on both files, and pytest imported and ran every changed module |
| Live systems | The daemon was not signalled or restarted, and no live gate was run. In `~/spectricom-orchestrator` I only read the 281 log and `sit-archive/orchestrator-sit-log.json`. `~/_eos/s7core31/*` was only read. In clinical-mp I only read `vitest.sit.config.ts`, `package.json` and `node_modules/vitest/dist`. The capture project `/tmp/vt-capture-282b` symlinks clinical-mp's `node_modules` and runs no SIT file and no Medplum call |

## §1 Found and LEFT

1. **`tests/test_sit_rate_limit.py::TestRepoConfig::test_clinical_mp_declares_batching` is red on `main` since `dc8ec4e`.**
   - It asserts `int(mp[SIT_BATCH_PAUSE_KEY]) > 0`, and D-S7CORE31-03 set clinical-mp's `sit_batch_pause_s` to `0`.
   - It fails identically at the merge base `dc8ec4e`, so the baseline unit gate should not count it against this route.
   - Not changed: it is outside D1-D3, and rule #8 pre-authorises only suspect-list changes. **Gemma's call:** `>= 0` (0 is legitimate, per `_sit_plan`'s own comment), or drop the line.
2. **An attributed file whose unhandled error recurs alone is `isolation-unmeasurable` → BLOCKED(environment), not `confirmed`.**
   - Alone it exits 1 with 0 failed assertions (`Errors  1 error`).
   - `_sit_isolate` confirms only on `exit≠0 and failed≥1`, and calls anything else unmeasurable. D1 keeps that rule.
   - So a product bug that throws an unhandled rejection on its own blocks the merge as environment instead of product. It still blocks, and still names the file.
   - **Gemma's call:** whether `Errors N` alone, with exit 1 and no F-20 signal, should count as `confirmed`.
3. **F-20 signals are still read from the 10,000-char tails.** A transport signal (429, ECONNREFUSED…) earlier in a red batch is invisible to both the classifier and the leg's "no F-20 signal" check, as on HEAD. With D1, such a batch can now reach the leg, and a file passing alone could read `batch-contamination` where the truth was a rate limit. Widening the signal check to the whole text would move rule-2 verdicts, so it was left alone (STOP (b)).
4. **The leg does not reconcile its suspects against `Test Files N failed`.**
   - With vitest 4.1.4's whole text, every failed file has a `FAIL` line (Find 2), so this holds today.
   - If `vitest.sit.config.ts` ever gains `test.name`, `FAIL` lines become `FAIL  |sit| <file>`. `_GATE_FAIL_FILE_RE` would then capture `|sit|`, and `FAIL`-named suspects would drop out of every batch.
   - D2's line would show it (`named, not a file of this run: |sit|`). But a batch that also carried an attribution would isolate only the attributed file, and could PASS while the failing file was never run alone.
   - Not changed: the regex is HEAD's and serves rule 1 too.
5. **The "whole batch passed together" evidence covers 33 tests, but the gate's batch 3 collected 25.**
   - `~/_eos/s7core31/batch3-run.log` ran `chosen.txt` lines 21-30: 10/10 files, `32 passed | 1 skipped (33)`.
   - The 281 gate's batch 3 collected `10 test files / 25 tests (22 passed)`.
   - So either the re-run's file set is not the gate's batch 3 (`plan.files` order against `chosen.txt` order), or a file collected fewer tests in the gate. I did not trace it: read-only, and it does not bear on this change. Run alone, `home-up-next` passed 3/3 either way.
6. **Route 281's whole batch text is gone.** The gate keeps only the red tails (`SitOutcome.output`), and the SIT log keeps a 1,000-char stderr excerpt. Which file carried 281's 2 failed assertions is not recoverable. Not changed: persisting more of the gate output is outside D1-D3.

## THE CONSEQUENCE (D-S7CORE13-03)

1. **After the merge.**
   - **No daemon restart is needed.** Every route (`python3 -u orchestrator.py run …`) and every full-gate (`orchestrator.py full-gate …`, `queue_daemon.py:29`) is a fresh `orchestrator.py` process, so the next per-merge SIT gate loads the new code.
   - **When a red batched SIT run has ≥1 failed assertion and no F-20 signal**, the leg now re-runs alone every file that a red batch names by a `FAIL` line anywhere in its output, or by vitest's error attribution. The `🔬` line says which form named each one.
     - Cost: one `npm run sit:gate -- <file>` per suspect, after `sit_batch_pause_s`. That is 0 s on clinical-mp since `dc8ec4e`, plus about 9 s per file (home-up-next alone: 8.78 s).
     - If nothing is named, the run log now says `isolation not engaged: no failing file named` where HEAD said nothing.
   - **Route 281 is not re-judged.** Its gate verdict stands until the route is re-fired. On a re-fire with the same shape, `home-up-next` would be re-measured alone, and on today's evidence (3/3 alone) it would be `contaminated`, not FAIL(product).
   - **The full gate's SIT leg gets D1 too.** `_full_gate_sit` calls `run_sit_post_merge` and is "judged as the per-merge gate judges a red". No full-gate code changed.
2. **Unchanged:**
   - the classifier's input text, F-20 rule 2 and rule 1 (0 failed assertions ⇒ environment);
   - GATE-CLOCK-1, V1-V5, the full gate's failing-file list for a FAIL(product) without a leg;
   - `_sit_failing_files`, the batches (never re-run), the unbatched path (never isolated), the cap and P-SAY;
   - the CODE-GUARD, the handback guard, prefire, admission, the fire lock, timeout/hold and `queue_daemon.py`.

## Closes capability advancement: none
## Gates journey: none

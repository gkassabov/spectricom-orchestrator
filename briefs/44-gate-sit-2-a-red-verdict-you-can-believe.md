#!queue model=claude-opus-5-5 effort=high repo=orchestrator

# GATE-SIT-2 — a red verdict you can believe

## Repo: orchestrator
## Batch ID: s7core15-gate-sit-2
## Briefs: 1
## Estimated runtime: 40-60 min
## Spec reference: [GATE-SIT-2] · builds on D-S7CORE10-02
## Predecessor: `main` at `c292570` or later (QUEUE-RETIRE-1 already landed there — see §4). Baseline at `c292570`: `pytest -q tests/` = **409 passed, 0 failed**.

## 0 · FIRST STEP

Read these in full, in this order, before designing anything. Every name below was verified on `main` @ `c292570`.

1. `orchestrator.py:1557-1596` — `SitOutcome` (fields, `files_failed`, `collection`).
2. `orchestrator.py:1690-1742` — `SitPlan` and `_sit_plan` (how the batches are cut; `plan.pause_s`).
3. `orchestrator.py:1748-1821` — `_SitBatchedRun` and `_run_sit_batched`. Read the docstring at `:1769-1771` ("NEVER a retry — a re-run against an unrefilled budget is dirtier than the first"). This brief does not contradict it; §3 T2 says exactly how.
4. `orchestrator.py:1824-1960` — `run_sit_post_merge`, end to end. Note `:1914` (the red log line) and `:1945` (the `SitOutcome` return).
5. `orchestrator.py:353-401` — F-20 `ENV_BLOCK_SIGNALS`; `:416-433` — `GateOutcome`, `GateVerdict`.
6. `orchestrator.py:2953-2999` — `_GATE_FAIL_FILE_RE` and `_classify_gate_failure`. **This is D-S7CORE10-02's home** (rule 2 = the signal table, rule 1 = `tests_failed == 0` at `:2990`). The new rule goes here, after rule 1, and nowhere else.
7. `orchestrator.py:3002-3090` — `run_pre_merge_gates`; the `sit` branch is `:3034-3056`.
8. `orchestrator.py:2349-2400` — the [ORCH-6] isolation precedent for the UNIT gate: `_unit_confirm_cmd` (`:2355`) and `_unit_confirm_new_files` (`:2375`); and its call site in `run_unit_gate` at `:2797-2815` (fail-closed on an unmeasurable confirmation) and `:2843-2858` (flakes alone ⇒ PASS, named). Copy the *shape*; do not call these functions — they run `test_cmd`, not `sit_cmd`, and their parser is the unit parser.
9. `orchestrator.py:3093-3130` — `_log_sit_outcome` (additive kwargs; the entry dict).
10. `orchestrator.py:1039-1066` — `_gate_status_label` and the FINAL STATUS line (`Result.gate_collection`, `:465`).
11. `tests/test_sit_rate_limit.py` (318 lines) — `_drive` at `:192`, `CFG` at `:214`, and the two tests this brief touches: `test_a_red_batch_is_classified_and_never_retried` (`:266`) and `test_a_real_failure_in_a_batch_is_still_product` (`:279`).
12. `tests/test_gate_collection.py:24-36` — `_run_gate` asserts `call_count == 1` (unbatched); `:215` `test_gate_command_count_unchanged` asserts the string `npm run sit:gate` occurs **exactly twice** in `orchestrator.py`. Reuse the `sit_cmd` variable; never spell the command again.
13. `config/repos.yaml:50-56` — `sit_list_cmd`, `sit_batch_files: 10`, `sit_batch_pause_s: 90`.

## 1 · WHY THIS EXISTS

The SIT gate runs `npm run sit:gate` in batches of ≤10 files (`config/repos.yaml:55`), 90 s apart (`:56`), against ONE live Medplum at `localhost:8103`. Inside a batch vitest runs the files in parallel workers, all logged into the same practice. A file that writes shared state (a CodeSystem, a Consent) changes what its neighbour reads. The gate cannot tell that from a product failure: `run_sit_post_merge` at `:1914` logs `SIT gate FAILED … N failed assertions — BLOCKING`, `run_pre_merge_gates:3052` hands the output and tallies to `_classify_gate_failure`, and with ≥1 failed assertion and no transport signal `:2997` returns `FAIL(product)` — "product verdict stands".

Three instances:

- **2026-09-18 14:33** — `sit-archive/orchestrator-sit-log.json`: `passed=false, tests_failed=1, test_files 23/24, batches=3`. The failing assertion: `longevity-vocabulary-config.integration.test.ts > the vocabulary CodeSystem search returns only intervention vocabularies (a foreign CodeSystem written under this practice is not load…)`. The test's own name says what happened: a neighbour wrote a CodeSystem under the shared practice.
- **2026-09-20 20:55** — same log, same file, same assertion, `tests_failed=1, 26/27, batches=3`. `queue/done/29-meds-ui-1-safety-above-the-list.md:24` records the cost: "This cost a route a full night on 2026-09-20."
- **Third (S7-CORE-15, this session)** — a consent-dependent file (`sit/integration/longevity-tiered-consent.integration.test.ts` is the consent file in the suite) failed in its batch because a neighbour wrote to shared state; it passed alone. **Open question:** this run is NOT in `orchestrator-sit-log.json` (every entry after 2026-09-21 is `passed=true`), so it happened in a route-side `sit:gate` run, not the orchestrator gate. Confirm with George before citing a timestamp.

The standing workaround is a paragraph pasted into every clinical-mp brief since `29-meds-ui-1` (`queue/done/29…:21-25`, `30…:21-23`, `31`, `32`, `33`, `34`, `35`, `36`, `37`, `38`, `39`, `40`, `queue/held/41…:19-21`): "re-run that single file alone before believing it." That is a human step on every red gate, and it is the gate's job.

What the code does today, precisely:
- `_run_sit_batched:1767-1821` runs every batch once, sums the counts, and keeps the red batches' tails in `red_output`. It never re-runs anything (`:1769-1771`), for a good reason: a *batch* re-run against an unrefilled budget is dirtier.
- `run_sit_post_merge:1897-1914` decides `batch-incomplete` / `zero-collection` / PASS / red, and at `:1945` returns `SitOutcome(passed=False, output=raw[-20000:], tests_failed=…)`.
- `run_pre_merge_gates:3037-3056`: `zero-collection` and `SIT_GATE_ENV_ERRORS` (`:228`) map to `BLOCKED(environment)`; everything else goes to `_classify_gate_failure("sit", …, tests_failed=so.tests_failed, files_failed=so.files_failed)`.
- `_classify_gate_failure:2956-2999` — D-S7CORE10-02: rule 2 (signal table) then rule 1 (`tests_failed == 0` ⇒ environment). **With `tests_failed == 1` both rules are correctly silent** and `:2997` returns `FAIL(product)`. The rule does not cover this case and must not be bent to: the assertion genuinely failed. What is missing is a *third* piece of evidence — did it fail alone?

The [ORCH-6] unit gate already answers exactly this question for the unit suite (`:2797-2815`): "a single pair of whole-suite runs is not enough evidence for FAIL(product) — confirm the suspect set in isolation before deciding." The SIT gate never got that leg. This brief gives it one.

## 2 · THE TARGET STATE (D-S7CORE13-02 · S1 — a runnable predicate, not a symptom list)

**No SIT gate verdict of `FAIL(product)` names a failing file that was not re-run alone and confirmed failing alone; no file that passed alone is ever counted against the product; and a red gate that D-S7CORE10-02 already calls environment is never re-run at all.**

Ship that sentence as one exported predicate in `orchestrator.py`, placed directly after `_classify_gate_failure` (so the verdict logic and its invariant sit together — ONE place, `:2956` onward):

```python
def sit_verdict_violations(so: SitOutcome, v: GateVerdict) -> list[str]:
    """[GATE-SIT-2] EMPTY WHEN CLEAN. Each string names one way (so, v) contradicts §2."""
```

A violation is any of, for a `SitOutcome` whose gate ran batched (`so.batches` is not None) and was red (`so.passed is False`, `so.error is None`):

- **V1** `v.outcome is FAIL_PRODUCT` and `so.isolation` is not None and `so.isolation.confirmed` is empty — a product verdict with no file confirmed failing alone.
- **V2** `v.outcome is FAIL_PRODUCT` and `so.isolation is None` although `so.tests_failed >= 1` and the red output names ≥1 failing file (`_GATE_FAIL_FILE_RE`) and no F-20 signal matches — isolation was owed and not performed.
- **V3** `v.outcome is PASS` and (`so.isolation is None` or `so.isolation.error` or `so.isolation.confirmed` non-empty) — a red batch was waved through without every failing file passing alone.
- **V4** `so.isolation is not None` and (`so.tests_failed == 0` or an F-20 signal matches `so.output`) — a re-run happened where D-S7CORE10-02 had already decided; the SIT-RATE-1 no-retry rule was broken.
- **V5** `v.outcome is BLOCKED_ENV and v.signal == "isolation-unmeasurable"` and `so.isolation.error is None` — the fail-closed verdict without a failed measurement behind it.

Exclusions, stated (rule A11): unbatched runs (`so.batches is None`), runs with `so.error` set (`batch-incomplete`, `sit-list-failed`, `zero-collection`, `timeout-advisory`, `skipped`), and runs with `so.tests_failed is None` (UNKNOWN, §2.4 — never earns anything, isolation included) return `[]` from every clause: the predicate has nothing to say about them.

Check first whether a verdict-invariant module already exists to extend: it does not. `canon_assert.py:557 check_queue_trunk_invariants` is the only `-> list[…]` invariant in the repo, and its `Violation` (`canon_assert.py:477`) is queue-shaped (`brief/path/repo/branch/commit`). Do not reuse it; return `list[str]` and keep the predicate beside the classifier it guards.

**Reachability (D-S7CORE9-01):** the non-test caller is `run_pre_merge_gates`, which calls `sit_verdict_violations(so, v)` on every SIT verdict it is about to act on and `log.error`s each string (it does not change the verdict — the predicate is an oracle, not a fourth rule). The tests call the same function.

**Done is that predicate returning `[]` for every `(SitOutcome, GateVerdict)` the tests in §5 construct, including the contaminating pair — not a list of places a re-run was added.**

## 3 · SCOPE — exactly what to change

### T1 · `SitOutcome` carries the isolation evidence (`orchestrator.py:1557-1581`)
Add one field, `isolation: Optional["SitIsolation"] = None`, and a new dataclass `SitIsolation` immediately above `SitOutcome`:
- `contaminated: tuple[str, ...]` — files that failed in their batch and PASSED alone.
- `confirmed: tuple[str, ...]` — files that failed alone too.
- `neighbours: dict[str, tuple[str, ...]]` — for each isolated file, the other files in the batch it ran in (`plan.batches`), listing order. This is the evidence the harness fix needs.
- `batch_of: dict[str, int]` — 1-based batch index per isolated file.
- `duration_s: float`, `pause_s: int`, `error: Optional[str]`, `detail: Optional[str]`.
- `skipped: Optional[str]` — why isolation was not attempted when it might have been (see T2 cap).
Extend `SitOutcome.collection` (`:1587-1596`) the way `UnitGateOutcome.collection` does at `:2087-2088`: append ` | contaminated, passed alone (not blocking): <f> (batch 2/3, neighbours: a, b)` and/or ` | confirmed failing alone: <f>`. FINAL STATUS (`:1050-1051`) then carries it for free.

### T2 · the isolation leg, inside `run_sit_post_merge` (`:1863-1945`)
After the batched run and BEFORE the verdict-ish logging that starts at `:1897`, when ALL of the following hold — `plan is not None`, `r.returncode != 0`, `batch_mismatch is None`, `tests_failed` is an int `>= 1`, no `_ENV_BLOCK_SIGNALS_RE` entry matches `raw` (reuse the compiled table `_ENV_BLOCK_SIGNALS_RE` at `:412`; do not copy a regex), and `_GATE_FAIL_FILE_RE.findall(raw)` (normalised with `_norm_test_path`, `:2120`) intersects `plan.files` non-trivially — run the isolation leg:
1. Log `🔬 SIT gate: N failing file(s) — confirming in isolation before verdict: …`.
2. Sleep `plan.pause_s` ONCE (the leg is the next window; use `time.sleep(plan.pause_s)` guarded by `> 0`, exactly as `:1780-1782`). The `test_batch_size_and_pause_are_configuration_not_literals` guard at `tests/test_sit_rate_limit.py:249-252` forbids any literal; none is needed.
3. For each failing file, in listing order, ONE invocation `f"{sit_cmd} -- {shlex.quote(f)}"` (the same `sit_cmd` variable at `:1844`; `test_gate_command_count_unchanged` will fail if the string is spelled again), `timeout=SIT_TIMEOUT` (the budget of one invocation, unchanged), through `_gate_shell_cmd` (`:1497`). Parse with `_parse_vitest_summary` + `_parse_vitest_tallies` + `_sit_tests_failed`. `returncode == 0` and `tests_failed == 0` and `test_files_total == 1` ⇒ `contaminated`; `returncode != 0` with `tests_failed >= 1` ⇒ `confirmed`; anything else (timeout, `test_files_total != 1`, tallies unknown, an F-20 signal in the single-file output) ⇒ `isolation.error = "isolation-unmeasurable"`, `detail` naming the file and why, and stop the leg — fail closed, [ORCH-6] decision 4.
4. **Cap:** if more failing files than `plan.batch_files` are named, do not isolate; set `isolation.skipped = f"{n} failing files exceed the batch size {plan.batch_files} — not contamination-shaped, not re-run"` and leave `isolation.contaminated/confirmed` empty. The verdict then falls through to today's product rule; `sit_verdict_violations` V2 excludes the skipped case explicitly (state it in the docstring).
5. Reword the `_run_sit_batched` docstring at `:1769-1771` so it stays true: a *batch* is never re-run; a single failing file is re-measured alone, after the refill pause, by `run_sit_post_merge` — a measurement, not a retry. `test_a_red_batch_is_classified_and_never_retried` (`tests/test_sit_rate_limit.py:266`) stays green untouched: its red batch has `tests_failed == 0`, so the leg never starts.
6. `SitOutcome.passed` stays `False` for a red batched run whatever the isolation found. **The verdict is not decided here.** Populate `isolation` and return.
7. `_log_sit_outcome` (`:3093`) gains an additive `isolation: Optional[dict] = None` kwarg written into the entry as-is (`contaminated`, `confirmed`, `neighbours`, `batch_of`, `error`, `skipped`, `duration_s`). Old entries lack the key; `test_old_shape_log_loads_and_new_entry_has_counts` (`tests/test_gate_collection.py:153`) and `test_positional_legacy_call_still_works` (`:168`) must stay green.

### T3 · rule 3 in `_classify_gate_failure` (`:2956-2999`) — ONE place decides
Add `isolation: Optional[SitIsolation] = None` to the signature. After rule 1 (`:2990-2996`) and before the product fall-through (`:2997`):
- `isolation.error` ⇒ `GateVerdict(BLOCKED_ENV, gate, "isolation-unmeasurable", detail)` — never PASS, never product.
- `isolation.confirmed` non-empty ⇒ `FAIL_PRODUCT`, signal `f"exit {exit_code}"` as today, detail naming `confirmed failing alone: …` and, if any, `contaminated (passed alone, not counted): …`. The existing `(N failed assertions)` wording stays.
- `isolation.contaminated` non-empty and `confirmed` empty ⇒ `GateVerdict(GateOutcome.PASS, gate, "batch-contamination", detail)` with the neighbours named: `f.ts failed in batch 2/3 beside a.ts, b.ts — passed alone (3/3); no product failure`. Log `🔎 F-20 sit gate: signal 'batch-contamination' — …` in the same style as `:2977`/`:2993`.
- `isolation` None or `skipped` ⇒ unchanged fall-through (`:2997-2999`).
Update the docstring: rule 3 is stated as "a failed assertion that passes alone is the batch's, not the product's — decided from this function's inputs, like rules 1 and 2." Do not move rules 1 or 2; do not reorder the signal table.

### T4 · `run_pre_merge_gates` acts on a PASS from the classifier (`:3034-3056`)
Pass `isolation=so.isolation` at `:3052`. After `v` is built for the `sit` gate, call `sit_verdict_violations(so, v)` and `log.error` each string prefixed `⛔ GATE-SIT-2 invariant:`. Then: if `v.outcome is GateOutcome.PASS`, `log.info(f"✅ Pre-merge gate{where}: SIT green after isolation — {v.label}")`, keep `sit_collection = so.collection` (it now carries the contamination note), and fall through to the unit gate exactly as a green SIT does today; otherwise `log.error` and `return v` as at `:3055-3056`. The `DISABLE_SIT_BLOCKING` branch at `:3057` is untouched.

### T5 · tests (`tests/test_sit_rate_limit.py`, new section after `TestSitBatching`)
- Extend `_drive` (`:192`) so responses beyond the batches feed the isolation invocations, and return `calls` so tests can assert the exact `-- <one file>` shape and the sleep sequence.
- `test_a_real_failure_in_a_batch_is_still_product` (`:279`) currently hands `_drive` three responses; the isolation leg will draw a fourth and today's iterator raises `StopIteration` into the `except Exception` at `:1955`. Add the fourth response (f3 alone, `returncode=1`, `1 failed`), assert `sleeps == [7, 7, 7]`, and keep every existing assertion.
- The new tests are §5.

## 4 · OUT OF SCOPE

- **Do not change** `SIT_BATCH_FILES`, `SIT_BATCH_PAUSE_S` (`:221-222`) or `config/repos.yaml:55-56`. No new timing constant either: the pause is `plan.pause_s`, the per-invocation budget is `SIT_TIMEOUT`, the cap is `plan.batch_files`.
- **Do not weaken D-S7CORE10-02.** Rules 1 and 2 keep their order and their inputs; rule 3 sits after them and is reached only when they were silent. A `tests_failed == 0` run or a transport-signal run is never re-run (V4 makes that a violation).
- **Do not touch the unit baseline gate** (`run_unit_gate:2676-2858`, `_unit_confirm_*:2355-2400`, the baseline cache). Copy its shape; share nothing but `_norm_test_path` and the vitest parsers already shared.
- **Do not touch brief retirement or the queue daemon.** `QUEUE-RETIRE-1` landed on local `main` as `c292570` (unpushed — `main` is 2 ahead of `origin/main` @ `49a33c7`) and moved `retire_batch_file` (`:1384`), `_self_mod_auto_merge` (`:1420`), and the two `run_pre_merge_gates` call sites (`:3407`, `:3484`). A follow-up on that route may still be moving those lines: **the line numbers in this brief for `:3400+` are approximate to that work; re-grep before editing, and do not edit `queue_daemon.py` at all.**
- **Do not** isolate on the unbatched path (`plan is None`). Contamination is a batched-repo defect; the unbatched path keeps today's behaviour, and `tests/test_gate_collection.py:35` (`call_count == 1`) and all of `tests/test_sit_integration.py` (unbatched `MagicMock` runs) must stay green untouched.
- **Do not** fix the contaminating test pair in clinical-mp. Name it in §7 of the handback if the evidence identifies the neighbour; that is a clinical-mp brief.
- **Do not** add a `flaky`-style report subcommand for contamination; the sit-log entry is the record for now.
- **Nothing** outside this repo (`A3`).

## 5 · ACCEPTANCE

- **AC-GS-01** — `sit_verdict_violations` exists, is exported, returns `[]` for every `(SitOutcome, GateVerdict)` pair the tests below construct, and returns a non-empty list for each of V1–V5 built by hand (five negative cases, one per clause; state which clause each names). Set quantified over: the pairs constructed in `tests/test_sit_rate_limit.py`; exclusions as §2 states.
- **AC-GS-02 — contamination reproduced, red before green.** Fixture: a batched plan of 2 files/batch (`CFG`, `:214`) where batch 2's output shows `f3.integration.test.ts` FAIL with `1 failed`, and the isolation response for `f3` alone is `1 passed (1)`, exit 0. On unmodified `main` the verdict is `FAIL(product)` (state the red assertion count); after T1–T4 it is `PASS` with `signal == "batch-contamination"`, `so.isolation.contaminated == ("sit/integration/f3.integration.test.ts",)`, `neighbours["…f3…"] == ("…f4…",)`, `batch_of == {"…f3…": 2}`, and the FINAL STATUS/`collection` string names the file, the batch and the neighbour.
- **AC-GS-03 — isolation cannot mask a genuine product failure.** Same fixture, isolation response for `f3` alone is exit 1, `1 failed` ⇒ `FAIL(product)`, `confirmed == ("…f3…",)`, detail contains `confirmed failing alone`. Also the mixed case: two failing files, one passes alone, one fails alone ⇒ `FAIL(product)` naming both sets.
- **AC-GS-04 — the leg runs the file ALONE.** For AC-GS-02, the isolation invocation is exactly `<sit_cmd> -- sit/integration/f3.integration.test.ts` (one file, `-- ` present, no other `.integration.test.ts` in the command), and `sleeps == [7, 7, 7]` — the configured pause once before the leg, never a literal. Set quantified over: every `subprocess.run` call recorded by `_drive` after the list command.
- **AC-GS-05 — D-S7CORE10-02 runs are never re-run.** `test_a_red_batch_is_classified_and_never_retried` (`:266`, `tests_failed == 0`) and `TestTonightsGateOutput` (`:129-176`, the 429 fixture) pass unmodified with their `call_count` assertions intact; a new test with `tests_failed == 2` whose output contains `Too Many Requests` records no isolation call and `so.isolation is None`. Set quantified over: those three tests.
- **AC-GS-06 — fail closed.** Isolation response is a timeout (`subprocess.TimeoutExpired`) or collects `2 passed (2)` for one file ⇒ `BLOCKED(environment)`, `signal == "isolation-unmeasurable"`, never PASS, never product; `sit_verdict_violations` returns `[]`.
- **AC-GS-07 — the cap.** With `sit_batch_files: 2` and three failing files named, no isolation call is made, `isolation.skipped` names the count and the cap, and the verdict is today's `FAIL(product)`.
- **AC-GS-08 — the sit-log carries the evidence.** For AC-GS-02 and AC-GS-03 the last `orchestrator-sit-log.json` entry has an `isolation` key with `contaminated`, `confirmed`, `neighbours`, `batch_of`, `error`; a pre-existing entry without the key still loads (`tests/test_gate_collection.py:153` unchanged).
- **AC-GS-09 — source guards hold.** `orchestrator.py` still contains `npm run sit:gate` exactly twice (`tests/test_gate_collection.py:215`), and none of `sleep(90`, `vitest list`, `vitest.sit.config`, `range(0, 19` (`tests/test_sit_rate_limit.py:250-252`). Set quantified over: those five literals.
- **AC-GS-10 — reachability.** `run_pre_merge_gates` calls `sit_verdict_violations` on every SIT verdict it returns or falls through on; a test patches it and asserts it was called with the `(so, v)` pair for both the PASS (contamination) and the FAIL(product) (confirmed) paths.
- **AC-GS-11 — `pytest -q tests/` green with no new failures vs the merge-base baseline.** Baseline at `c292570`: **409 passed, 0 failed**. State the post-change count as `N passed, 0 failed` with `N >= 409 + (new tests)`; the set compared is every test file under `tests/`, none excluded.
- **AC-GS-12 — the unbatched path is byte-identical.** `tests/test_sit_integration.py` (all 13 tests) and `tests/test_gate_collection.py` (all tests) pass with no edits to those files.

## 6 · HANDBACK

**§7 first** (D-S7CORE13-02): what you found and left, and why — including whether the isolation evidence on any red run identified the neighbour that writes the foreign CodeSystem beside `longevity-vocabulary-config.integration.test.ts`, and whether the third (consent) instance can be tied to a logged run.

Then what shipped (T1–T5, by function name and line), the gate table with both baseline counts (`409 passed, 0 failed` @ `c292570` → post-change), AC-GS-10's caller, and — **D-S7CORE13-03, the consequence:**

1. **Wall-clock.** A green gate is unchanged (~215–235 s today for 30 files / 89 tests / 3 batches, per the last six sit-log entries). A red gate with `k` contaminated files now adds `plan.pause_s` (90 s) once plus `k` single-file invocations (~5–15 s each on the measured suite): state the number you measured or computed.
2. **Re-classification of the record.** Walk `sit-archive/orchestrator-sit-log.json` and say which of its `passed=false, error=null, tests_failed>=1` entries would now have *entered the isolation leg* (expected: 2026-09-18 14:33 and 2026-09-20 20:55, both `tests_failed=1`, one file). Their final verdict cannot be re-derived from the log — no isolation was run — say so rather than guess.
3. **The masking risk, named.** A product bug that only appears under parallel load will now PASS with `batch-contamination` named. This follows the [ORCH-6b] AC-O6b-01 precedent for the unit gate (flakes alone ⇒ PASS, named, never silent). If George rules the other way, the change is one line in T3 (`PASS` → `BLOCKED_ENV, "batch-contamination"`); say so explicitly.

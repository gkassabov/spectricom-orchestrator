# ORCH-8 — the unit gate counts skipped and todo tests as failures

**Repo:** `orchestrator` (self-mod — meta-fire worktree) · **Base:** `main` at `7a1ab62` · **Session:** S7-CORE-9
**Executor:** `claude-opus-5 --effort high`

## Estimated runtime: 45-75 min

---

## 1 · The defect

`orchestrator.py:1567`:

```python
if v["tests_total"] is not None and v["tests_passed"] is not None:
    out["failures"] = v["tests_total"] - v["tests_passed"]
```

vitest's own summary line for clinical-mp reads:

```
Tests  9 failed | 7267 passed | 8 skipped | 4 todo (7288)
```

`7288 - 7267 = 21`, not 9. **Skipped and todo tests are being counted as failures.** For this repo that is a constant **+12** on every unit-gate number, on **both** legs of every baseline comparison, and it has been true for every verdict since `[ORCH-3]` shipped.

**Observed, not theorised.** RED-5b's gate line on 2026-09-15 reported `baseline merge-base e837cbe: 789 files/7288 tests, 48 failed → branch: 789 files/7288 tests, 41 failed`, while the same runs reported by vitest itself were **9 failed** and **3 failed**. Twelve of each gap is this bug; the remainder is a second, separate effect (§4).

## 2 · Why it matters even though verdicts were probably right

The baseline gate compares branch against merge-base, so a constant offset **mostly cancels in the comparison** — this has not, as far as I can tell, failed a clean route or passed a dirty one. **The damage is to the numbers, not the verdicts**, and the numbers are what get published:

- The figure **`47`** entered `hot.md`, the Coverage Matrix, the Feature Index and the Bug Registry at S7-CORE-9 as "the repo's failure count." The suite's actual count that day was **12**.
- The predecessor figure **`106`** had already been published for two sessions off a suite that never terminated.

**A gate that reports a number nobody can reconcile with the runner's own output will keep poisoning canon.** That is what this route fixes.

There is one place the offset does **not** cancel: any absolute-threshold logic (a zero-failure fast path, a "fully green branch skips the baseline" shortcut — `[ORCH-5]` has one). A branch with 0 real failures and 12 skipped/todo reports 12 and **cannot take that path**. Check for this and say what you find.

## 3 · Scope

**S1.** Parse the failure count from vitest's **own** `N failed` segment on the `Tests` line, rather than deriving it from `total - passed`. Extend the existing `_VITEST_*` regex family in the same style as the current code — this is a parser change in `_parse_vitest_summary` / `_parse_unit_summary`, not a new subsystem.

**S2.** Keep `tests_total - tests_passed` **only as a fallback** for output that carries a total and a passed count but no explicit `failed` segment. Never fabricate `0` — §2.4's existing rule stands: absent or unrecognised ⇒ `None` ⇒ UNKNOWN, never `0`.

**S3.** Parse `skipped` and `todo` as their own counts and carry them through to the gate's log line, so a future reader can reconcile the gate's number against vitest's summary **without** re-running anything.

**S4.** Audit every consumer of `failures` for an absolute-threshold assumption (`== 0`, `> 0`, a green-branch fast path). Report each one and whether the corrected count changes its behaviour. **Do not change verdict logic in this route** beyond what the corrected count implies — if a threshold now behaves differently, that is the point; if a threshold needs re-tuning, name it and size it rather than tuning it here.

**S5.** The pytest path (`_UNIT_PYTEST_TALLY_RE` and friends) already parses named tallies. Check whether it has the same defect. If it does, fix it the same way; if it does not, say so.

## 4 · The second effect — name it, do not fix it here

Even after subtracting 12, the gate's runs showed **36** and **29** real failures where vitest's own runs of the same commits showed **9** and **3**. RED-5b diagnosed the mechanism on 2026-09-15: under CPU starvation, jsdom-heavy files run ~5× slower and their slowest tests blow the per-test timeout, producing `Error: Test timed out in 5000ms` rather than assertion failures. `vite.config.ts` now sets `testTimeout: 15000`, which cleared the class for a normal run.

**The gate is plausibly starving its own suite** — it runs two whole-repo legs and may overlap other work. **Investigate and report; do not fix it in this route.** Useful things to establish: whether the two legs can overlap each other or a live Toni run, what `availableParallelism()` reports inside the gate's environment, and whether the gate's leg wall-times (307.1s / 287.0s) differ materially from a quiet run (~286-306s — they may not, which would be evidence *against* starvation and worth saying plainly).

## 5 · Acceptance criteria

Every criterion names the set it quantifies over (A11).

- **AC-O8-01** — Given the literal string `Tests  9 failed | 7267 passed | 8 skipped | 4 todo (7288)`, the parser returns `failures == 9`, `tests_total == 7288`, `tests_passed == 7267`, and skipped/todo as their own counts. Asserted by a new unit test.
- **AC-O8-02** — For **each** of these summary shapes, the parser returns the failure count vitest itself states, asserted by a unit test per shape: `Tests  3 failed | 7273 passed | 8 skipped | 4 todo (7288)` · `Tests  7288 passed (7288)` · `Tests  2 failed | 5 passed (7)` · a line with `todo` but no `skipped` · a line with `skipped` but no `todo`.
- **AC-O8-03** — Output carrying a total and a passed count but **no** explicit `failed` segment still yields a number via the fallback, and a test asserts the fallback path is what produced it.
- **AC-O8-04** — Unrecognised or absent output still yields `failures is None` — **never `0`**. Asserted by a test. §2.4 is unchanged.
- **AC-O8-05** — The gate's log line reports failed / passed / skipped / todo / total such that the reader can reconcile it against vitest's own summary by inspection. Paste a sample line in the report.
- **AC-O8-06** — Every consumer of `failures` is listed in the report with its line number, whether it uses an absolute threshold, and whether the corrected count changes its behaviour. **The `[ORCH-5]` green-branch fast path must be explicitly named in that list**, with a statement of whether it was reachable for clinical-mp before this fix.
- **AC-O8-07** — The pytest path is stated to have, or not have, the same defect — with the line that decides it.
- **AC-O8-08** — `pytest` for the orchestrator passes with **no new failing test** against the merge-base, and the suite count **grows** (it was 176 at S7-CORE-8).
- **AC-O8-09** — No change to verdict semantics beyond what the corrected count implies: `[ORCH-1]` gate-then-merge, `[ORCH-4]` per-repo fire lock, `[ORCH-6]`/`[ORCH-6b]` confirm-before-fail and confirmed-files keying, and `[ORCH-7]` flaky-tail reporting all behave as before. Name each and say how you checked.
- **AC-O8-10** — §4 is a **report only**. `git diff` shows no change to timeout, pool, parallelism or scheduling behaviour. The report states what was found about gate-side starvation, including a negative finding if that is what the evidence supports.

## 6 · Method notes

- **This is a self-mod.** The brief is committed pre-fire; the meta-fire worktree pattern applies. An untracked brief breaks the ff-merge (S7-CORE-8 cost two routes to that, twice, in opposite directions).
- **`prefire.check()` takes a `Path`, not a `str`.** `prefire._read` returns `""` for a `str`, so every assertion evaluates against an empty file and A2 reports a **false** "no `## Estimated runtime:` declared." This cost a fire on 2026-09-15.
- **Parse, never re-run** — `[ORCH-2]`'s standing rule. The counts must come from output already captured.
- **Do not narrow `test_cmd`.** `npm test` stays the whole repo; narrowing it would hide exactly the class this route exists to report honestly.

## 7 · Out of scope

- Any change to `vite.config.ts` or anything in `clinical-mp`.
- Fixing gate-side CPU starvation (§4 is report-only).
- Re-tuning any threshold the corrected count changes — name and size it instead.

# Toni Batch S7-CORE-10 — SIT-RATE-1 + [ORCH-11]: the gate stops calling a 429 a product defect

## Repo: orchestrator
## Batch ID: toni-batch-s7core10-sit-rate-1-gate-reliability-01
## Briefs: 1
## Estimated runtime: 45-75 min
## Predecessor branch: main @ `76887c0`
## Class: C (working artifact)
## Task: Kanban `SCP_Kanban_v0-31` row **38**, state **READY** (recorded before this brief)

# Rule: Verify with build + lint after all briefs complete. Do NOT run Playwright E2E tests during batch execution.

## MANDATORY READS (pre-code)
- `orchestrator.py` — the SIT gate invocation, and the **F-20 environment-signal detector** that
  decides `BLOCKED(environment)` vs `FAIL(product)`. Find both before designing anything.
- `tests/` — the existing orchestrator pytest suite (296 tests). **This is a self-mod; the suite is
  your safety net and `[ORCH-2b]` is the precedent for stale tests blocking one.**

## THE EVIDENCE — measured tonight, do not re-derive

**One SIT gate run no longer fits inside Medplum's rate-limit budget.** Three separate runs:

```
_consumedPoints 50079 / 50090 / 50090   against   limit: 50000
OperationOutcomeError: Too Many Requests
  thrown in SitIntegrationHarness.login (sit/integration/medplum-harness.ts:89)
```

Each SIT file's harness `login()` creates a Practitioner, so **gate cost scales with file count** —
10 files a week ago, **19 now**. Earlier tonight 18 files in ~16s fit, barely. The 19th crossed it.

**Proof it is the budget and not the product:** the same branch, same commit, run in **two halves
90 s apart** — **10 files / 29 tests green, then 9 files / 31 tests green. 19/19, 60/60.**

**And the detector missed it.** The gate logged *"no F-20 environment signal in gate output —
product verdict stands"* against a literal HTTP 429, and returned **`FAIL(product)`**. That is the
**second** false `FAIL(product)` tonight from this detector — RM-I-028 was the first (1 failed test,
**12 skipped**, `"Encounter PUT failed: unknown"`, merged untouched twenty minutes later). Cost so
far: two routes wrongly recorded as failed, one bug filed against working code, two hand-merges.

## 1 · Affected surface (A4)
`orchestrator.py` (SIT gate invocation + the F-20 detector) and its `tests/`. **Orchestrator repo
only** — cross-repo work is two routes (§5.4 / §5.12), and everything here is decidable from the
gate's own output, so nothing in clinical-mp needs to change.

**Do NOT modify:** anything in `clinical-mp` · the build or unit gate legs · `[ORCH-1]`
gate-then-merge semantics · `[ORCH-10]`'s `TAMPERED` verdict.

## 2 · Reseed scope (A5)
**None.**

## 3 · The two changes

**(a) Verdict semantics — `[ORCH-11]`.** Two rules, and the first is the general one:

1. **A gate run with ZERO failed assertions is never `FAIL(product)`.** Test *files* down at setup
   with every executed assertion passing is an environment verdict by construction. Both false
   verdicts tonight had this shape and it is decidable from the summary line alone.
2. **Any transport-level refusal in gate output is `BLOCKED(environment)`** — `Too Many Requests`,
   HTTP 429, `ECONNREFUSED`, an `OperationOutcomeError` raised from the client rather than an
   assertion. Add these to the F-20 signal set and **say in the log which signal matched**, the way
   `[ORCH-8]` made `failures_source` explicit.

**(b) The gate fits the budget — `SIT-RATE-1`.** Run the SIT files in **batches sized so a batch
completes inside one rate-limit window**, with a pause between. Batch size is **configuration, not a
literal** — per-repo, defaulting to something that works at 19 files and does not need editing at 25.
Report per batch and aggregate honestly: **the gate's collected-file and test counts must still sum
to the whole suite**, or the batching has hidden a file, which is the `[ORCH-8]` failure in a new
costume.

**Do NOT "fix" this by retrying a red gate.** I tried that tonight and my retry was *dirtier* than
the original — 5 files down instead of 3 — because it re-consumed a budget that had not refilled.

## 4 · Acceptance criteria

- **AC-SR-01** A gate result with `failed == 0` and one or more files down at setup returns
  **`BLOCKED(environment)`**. **Set: the verdict function's own inputs**, not every gate path.
- **AC-SR-02** Gate output containing `Too Many Requests`, `429`, `ECONNREFUSED`, or a client-raised
  `OperationOutcomeError` returns `BLOCKED(environment)`, and the log **names the matched signal**.
- **AC-SR-03 (prove the guard fails first)** A fixture replaying **tonight's actual gate output** —
  `_consumedPoints 50090 / limit 50000`, 3 files down, 51 passed, 9 skipped — returns
  `FAIL(product)` on `76887c0` and `BLOCKED(environment)` after. **Show both in the report.** A guard
  only ever seen to pass is not known to be a guard.
- **AC-SR-04** The SIT gate runs in batches; batch size and inter-batch pause are **configuration**
  per repo, with no clinical or environment value as a literal in source (A10).
- **AC-SR-05** Aggregated counts equal the single-run counts: **19 files / 60 tests** for clinical-mp
  at `181a109`. If they do not sum, **STOP and report** — a batching scheme that loses a file is
  worse than the rate limit.
- **AC-SR-06** `python3 -m pytest tests -q` (not plain `pytest`) shows **no new failures** against
  the `76887c0` baseline. **Record the local wall-clock time.** If a stale test asserts the old
  verdict semantics, **that is `[ORCH-2b]` again** — fix the assertion, name it in the report, and do
  not weaken a real one to go green.
- **AC-SR-07** A real end-to-end gate run against live Medplum at clinical-mp `181a109` completes
  **without a 429** and returns PASS. This is the acceptance test; a passing unit fixture is not it.

## 5 · STOP and report
Halt if: the batching cannot be made to sum to the whole suite · the F-20 change would swallow a
real product failure (say which case and stop) · `[ORCH-1]` or `[ORCH-10]` semantics would have to
change to make this work. **Halt-and-report is a PASS.**

## 6 · Return
Commit(s) + the orchestrator log. The report carries: the failing-then-passing evidence for
AC-SR-03, the batch aggregation against 19/60, the pytest summary with its local time, and the live
end-to-end gate result.

# Toni Batch S7-CORE-9 — ORCH-6b: a failure COUNT is not a verdict

## Repo: orchestrator
## Batch ID: s7core9-orch-6b-count-is-not-a-verdict-01
## Briefs: 1
## Estimated runtime: 45-75 min
## Predecessor branch: main @ ca0d10f
## Class: C (working artifact)

## MANDATORY READS (pre-code)
- `orchestrator.py` — the unit gate verdict path, especially `worse_count` (~line 2095), the
  `UnitGateOutcome` dataclass (~1500) and the `flaky_files` plumbing added by ORCH-6
- `tests/test_unit_baseline_gate.py` — the ORCH-6 cases; extend, do not rewrite

## BUNDLE CONTEXT — measured, not theorised

ORCH-6 (`ca0d10f`) shipped and **worked on its first live route**: it re-ran the newly-failing files
in isolation and correctly classified `CarePlanAssignDialog.test.tsx` and `PatientPage.test.tsx` as
flakes. **And the route still failed**, because `worse_count = branch_run.failures > baseline_run.failures`
survives as an **independent** trigger:

```
108 failures vs baseline 104; flaky in isolation, not blocking: [both files] ... BLOCKING: branch stays unmerged.
```

Every file that newly failed was confirmed a flake, and the branch was still blocked — which is
exactly what `AC-O6-02` said must not happen. **The ACs were mine and they under-specified this**:
they were written about newly-failing FILES and never said the count must stop being a verdict on
its own.

**Why the count cannot be a verdict on this repo.** The same tree measures differently run to run:
`cad4753` gave **68** failures in one full run and **106** in another; `2449a52` gave **118**;
`f780736` gave **106**; `0c6a598` gave **104**. A ±4 count delta carries no signal. A **named file
that fails alone** carries signal. That is the whole basis of this change.

---

# BRIEF 1 of 1: ORCH-6b — the verdict keys on confirmed files, never on the count alone

## 1 · Affected surface (A4)
`orchestrator.py` (the unit gate verdict path only) · `tests/test_unit_baseline_gate.py`.

**Do NOT modify:** the confirmation-pass mechanism itself (ORCH-6 works — this changes only what
is done with its result), the build gate, the SIT gate, the fire lock, the merge logic, the cache
schema's existing fields.

## 2 · Reseed scope (A5)
**None.**

## 3 · Decisions locked
1. **A regression is a named file that fails in isolation on the branch and did not fail at the
   merge base.** That, and only that, produces `FAIL(product)`.
2. **The count becomes evidence, not a verdict.** It is still measured, still logged, still cached.
   It no longer blocks on its own.
3. **Fail closed stays fail closed.** An unmeasurable confirmation pass is still
   `BLOCKED(environment)` (ORCH-6 AC-O6-05, unchanged).
4. **Do not widen this into a general relaxation.** Nothing else about the gate gets softer.

## 4 · Acceptance criteria (AC-O6b-01 … 08)

- **AC-O6b-01** — when **every** newly-failing file is confirmed a `FLAKE`, the gate returns
  **PASS**, regardless of the failure-count delta. The flaky set is still named in `FINAL STATUS`
  and still persisted.
- **AC-O6b-02** — when **at least one** newly-failing file is confirmed a `REGRESSION`, the gate
  returns `FAIL(product)`, naming the regressed set and, separately, the flaky set. Unchanged.
- **AC-O6b-03** — when there is **no** newly-failing file but the count rose, the gate returns
  **PASS** and logs the delta as an explicit, named observation — `count rose from N to M with no
  newly-failing file` — so the noise stays visible without blocking.
- **AC-O6b-04** — when the count **fell** and there is no newly-failing file, PASS, as today.
- **AC-O6b-05** — `worse_count` no longer appears in any boolean that decides the verdict.
  `grep -n "worse_count" orchestrator.py` shows it used **only** for logging/observation, or shows
  it removed entirely — state which in the report.
- **AC-O6b-06** — pytest cases for **each** of the four situations in AC-O6b-01…04, driven by a
  stubbed runner. The ORCH-6 cases in `tests/test_unit_baseline_gate.py` stay green and none of
  their existing assertions is altered.
- **AC-O6b-07** — no new environment escape: `grep` the diff for new `DISABLE_`/`SKIP_` reads = **0**.
- **AC-O6b-08** — `source venv/bin/activate && PYTHONPATH=. pytest -q` — **no new failures** vs
  merge-base `ca0d10f`, which stood at **190 passed**.

## 5 · STOP-and-report triggers
- Making the count non-blocking appears to require changing the confirmation pass → STOP.
- You find a path where a real regression would now slip through **without** a newly-failing file →
  STOP and report it; that is the one thing this change must not do.

## 6 · Commit message
```
fix(gate): the unit verdict keys on confirmed files, not on the failure count (ORCH-6b)

ORCH-6's confirmation pass worked on its first live route and correctly called
two newly-failing files flakes — and the route was blocked anyway, because the
count comparison survived as an independent trigger.

The same tree measures 68, 104, 106 and 118 failures across runs. A count delta
carries no signal; a named file that fails in isolation does. The count is now
measured, logged and cached as evidence, and no longer blocks a route on its
own. An unmeasurable confirmation pass is still BLOCKED(environment).
```

## RUN COMMAND
```bash
cd ~/spectricom-orchestrator && unset ANTHROPIC_API_KEY && python3 orchestrator.py run toni-batch-s7core9-orch-6b-count-is-not-a-verdict-01.md --repo orchestrator --model sonnet --effort high --approve
```

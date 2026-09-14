# Toni Batch S7-CORE-9 — ORCH-6: the unit gate must tell a flake from a regression

## Repo: orchestrator
## Batch ID: s7core9-orch-6-flake-discrimination-01
## Briefs: 1
## Estimated runtime: 45-75 min
## Predecessor branch: main @ dca7fa0
## Class: C (working artifact)

## MANDATORY READS (pre-code)
- `orchestrator.py` — the `UNIT_GATE_*` constants block (~line 245-290), `_unit_suite_timeout`,
  `_unit_repo_timeout`, `_run_unit_suite`, and the gate function that produces the
  `UnitGateOutcome` verdict (~line 1900-2010)
- `config/repos.yaml` — `clinical-mp`'s `test_cmd`, `test_timeout_s`, `baseline_timeout_s`
- `sit-archive/unit-baseline-cache.json` — the cached baseline shape, including `failing_files`
- `tests/` — the existing pytest suite covering the unit gate; extend it, do not replace it

## BUNDLE CONTEXT

The unit baseline gate compares **two runs of a suite that is not stable**, and we now have the
measurements to prove it:

| Commit | Measured by | Failing tests | Failing files |
|---|---|---|---|
| `cad4753` | S7-CORE-8, via the gate | 106 | — |
| `cad4753` | S7-CORE-9, full run in a detached worktree | **68** | **21** |
| `2449a52` | the gate | **118** | **24** |
| `f780736` | the gate | **106** | — |

Three of the files "newly failing" at `2449a52` (`task-helpers`, `ConsentTab`, `TasksQueuePage`)
were re-run in isolation at `cad4753` and **all 56 tests passed**. They are load- or order-dependent,
not regressions.

**Consequence:** the gate's verdict can be wrong in both directions. A flaky file that happens to
fail on the branch run and pass on the baseline run produces `FAIL(product)` on a clean route — it
did exactly that on the RM-I-033 route, naming four files. And a genuine regression can hide inside
the noise when the counts happen to match.

**This increment makes the gate discriminate.** It does not make the suite stable — that is
clinical-mp's problem and a different route.

---

# BRIEF 1 of 1: ORCH-6 — flake-vs-regression discrimination in the unit baseline gate

## 1 · Affected surface (A4)
| File | Why |
|---|---|
| `orchestrator.py` | the unit gate's verdict path and its constants |
| `config/repos.yaml` | one new optional per-repo key (see AC-O6-07) |
| `tests/` | new pytest coverage for the confirmation path |

**Do NOT modify:** the build gate, the SIT gate, the fire lock, the merge logic, the rate check,
`prefire.py`, or the baseline cache's existing schema fields. You may ADD a field to the cache;
you may not rename or remove one.

## 2 · Reseed scope (A5)
**None.** This is the orchestrator repo; no `synth:*` command exists here.

## 3 · Decisions locked
1. **A verdict is only as good as its evidence.** The gate currently declares a regression from a
   single pair of whole-suite runs. It must not declare `FAIL(product)` on that alone.
2. **Confirmation runs the suspect files in ISOLATION, on the branch.** Isolation is the
   discriminator: a file that fails in the whole-suite run and passes when run alone is
   order/load-dependent by definition.
3. **A flake is REPORTED, never silently swallowed.** The route continues, and the flaky set is
   named in the final status line and persisted, so the tail is visible and shrinkable.
4. **Fail closed on ambiguity.** If the confirmation run cannot be performed — timeout, runner
   error, no parseable result — the verdict is `BLOCKED(environment)`, never `PASS`. A measurement
   that did not happen is not evidence of health.
5. **No change to what "regression" means.** A file that fails in isolation on the branch and did
   not fail at the merge base is still a regression and still fails the route.

## 4 · Acceptance criteria (AC-O6-01 … 10)
Every quantifier names its set (A11).

- **AC-O6-01** — when the whole-suite comparison finds newly-failing files, the gate runs a
  **confirmation pass**: the runner is invoked again on **exactly that set of files** — no other
  file — on the branch checkout.
- **AC-O6-02** — a newly-failing file that **passes** the confirmation pass is classified
  `FLAKE`. Flakes alone never produce `FAIL(product)`.
- **AC-O6-03** — a newly-failing file that **fails** the confirmation pass is classified
  `REGRESSION` and produces `FAIL(product)`, exactly as today, with the file named.
- **AC-O6-04** — a mixed result (some `FLAKE`, some `REGRESSION`) is `FAIL(product)`, and the final
  status line names **both** sets separately. A regression is never excused by the presence of a
  flake alongside it.
- **AC-O6-05** — a confirmation pass that times out, errors, or returns no parseable summary yields
  **`BLOCKED(environment)`** with the reason named. It never yields `PASS` and never yields
  `FAIL(product)`.
- **AC-O6-06** — the flaky set is **persisted** — added to the baseline cache entry under a NEW
  field, leaving every existing field intact — and named in the `FINAL STATUS` line. Two routes in
  a row naming the same file is the signal that file needs quarantining, and that is only visible
  if the name is written down.
- **AC-O6-07** — the confirmation pass has its **own timeout**, defaulting generously relative to a
  handful of files and overridable per repo in `repos.yaml` by one new optional key. The default is
  a named constant; **no number is inlined at a call site** (CLAUDE.md), and an absent key uses the
  default.
- **AC-O6-08** — `DISABLE_UNIT_GATE` still bypasses the whole gate, confirmation included. No new
  escape hatch is introduced: `grep` the diff for new `DISABLE_`/`SKIP_` environment reads — **0
  matches**.
- **AC-O6-09** — pytest coverage for **each** of the four verdicts — all-flake, all-regression,
  mixed, and unmeasurable — driven by a stubbed runner, not by running a real suite. The existing
  `TestRunSitPostMerge`-style tests stay green; this adds cases and modifies no existing assertion
  **in `tests/`**.
- **AC-O6-10** — `source venv/bin/activate && PYTHONPATH=. pytest -q` passes with **no new
  failures** vs merge-base `dca7fa0`. The suite was 176 passed at `d4d8171`; it must not shrink.

## 5 · STOP-and-report triggers
- The runner's output cannot be parsed into a per-file pass/fail for the confirmation pass → STOP
  and report what it emits; do not guess a format.
- Implementing this appears to require changing the merge logic or the fire lock → STOP; out of scope.
- The baseline cache schema appears to need a field renamed or removed → STOP; additive only.

## 6 · Commit message
```
fix(gate): unit gate confirms a suspected regression before failing a route (ORCH-6)

The gate declared FAIL(product) from a single pair of whole-suite runs against
a suite that is not stable: cad4753 measured 68 failures in one run and 106 in
another, and three files "newly failing" at 2449a52 passed all 56 of their
tests when run in isolation.

Newly-failing files are now re-run alone on the branch. Passing in isolation
classifies a file as a flake — reported, persisted and named, never silently
swallowed. Failing in isolation is still a regression and still fails the
route. A confirmation pass that cannot complete is BLOCKED(environment), never
PASS.
```

## RUN COMMAND
```bash
cd ~/spectricom-orchestrator && unset ANTHROPIC_API_KEY && python3 orchestrator.py run toni-batch-s7core9-orch-6-flake-discrimination-01.md --repo orchestrator --model sonnet --effort high --approve
```

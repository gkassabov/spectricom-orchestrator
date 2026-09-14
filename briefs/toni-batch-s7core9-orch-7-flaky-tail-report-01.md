# Toni Batch S7-CORE-9 — ORCH-7: surface the flaky tail the gate is now accumulating

## Repo: orchestrator
## Batch ID: s7core9-orch-7-flaky-tail-report-01
## Briefs: 1
## Estimated runtime: 45-75 min
## Predecessor branch: main @ 9295fc4
## Class: C (working artifact)

## MANDATORY READS (pre-code)
- `orchestrator.py` — `_unit_cache_record_flakes`, the `flaky_files` field on the cache entry
  (added by ORCH-6, `ca0d10f`), the `UnitGateOutcome` dataclass, and the CLI subparser block
  (~line 2930-2970) where `run`/`queue`/`status` are registered
- `sit-archive/unit-baseline-cache.json` — the live shape, including the entries ORCH-6 has
  already written
- `tests/test_unit_baseline_gate.py` — extend, do not rewrite

## BUNDLE CONTEXT
ORCH-6 made the gate confirm a suspected regression in isolation and **persist** the files that
turned out to be flakes. It is already accumulating real data — in four routes today it has named
`CarePlanAssignDialog`, `PatientPage`, `TaskStatusPanel` and `ReportBuilderPage.aggregate`, two of
them twice.

**Nothing surfaces it.** The names appear in one `FINAL STATUS` line, scroll past, and the only
way to see the accumulated set is to read a JSON file by hand. A tail nobody can see is a tail
nobody shrinks — and this repo's whole-suite count has swung 68 / 104 / 106 / 115 / 118 / 126
across runs today, so the tail is the single largest source of false signal we have.

This increment makes it reportable. **It changes no verdict** — ORCH-6b settled what fails a route.

---

# BRIEF 1 of 1: ORCH-7 — a `flaky` report over the accumulated confirmation data

## 1 · Affected surface (A4)
`orchestrator.py` (a new read-only subcommand + the counter plumbing) · `tests/test_unit_baseline_gate.py`.

**Do NOT modify:** the gate's verdict logic (ORCH-6b is settled), the confirmation pass, the merge
logic, the fire lock, the build or SIT gates, or any existing cache field's meaning.

## 2 · Reseed scope (A5)
**None.**

## 3 · Decisions locked
1. **Read-only.** The new subcommand reports; it never writes, never fires, never merges.
2. **Additive to the cache.** You may add a field. You may not rename, repurpose or remove one.
3. **A count per file is the point.** "Named once" and "named five times" are different facts: the
   first is noise, the second is a file to quarantine. The report must distinguish them.
4. **No verdict changes.** If implementing this seems to require touching what passes or fails a
   route, you have misread the brief — STOP.

## 4 · Acceptance criteria (AC-O7-01 … 08)

- **AC-O7-01** — a new read-only subcommand (`flaky`) prints, per repo, each file the confirmation
  pass has ever classified as a flake, **how many times**, and **when it was last seen**, sorted
  most-frequent first.
- **AC-O7-02** — the cache records a per-file **count** and a **last-seen timestamp**, added
  alongside the existing `flaky_files` list. Entries written by ORCH-6 that carry only the list are
  read without error and treated as count-unknown — **a pre-ORCH-7 cache file must not crash the
  new command.** A test asserts that with a fixture of the old shape.
- **AC-O7-03** — `--repo <name>` narrows the report to one repo; absent, every repo in the cache is
  reported.
- **AC-O7-04** — a file that has been named **2 or more times** is marked in the output as a
  quarantine candidate. The threshold is a **named constant**, not an inlined number (CLAUDE.md).
- **AC-O7-05** — an empty or missing cache prints a clean "no flakes recorded" line and **exits 0**.
  Not an error, not a traceback.
- **AC-O7-06** — the subcommand performs **no** writes: a test asserts the cache file's bytes are
  unchanged after running it.
- **AC-O7-07** — pytest cases for: the old-shape cache, the empty cache, a single-occurrence file,
  and a quarantine-candidate file. The ORCH-6 and ORCH-6b cases stay green with **no existing
  assertion altered**.
- **AC-O7-08** — `source venv/bin/activate && PYTHONPATH=. pytest -q` — no new failures vs
  merge-base `9295fc4`, which stood at **195 passed**.

## 5 · STOP-and-report triggers
- Recording a count appears to require changing how the gate classifies a flake → STOP.
- The cache's existing entries cannot be migrated without a rewrite → STOP and report; a lossy
  migration of real measurement data is not something to decide alone.

## 6 · Commit message
```
feat(gate): report the flaky tail the confirmation pass has been accumulating (ORCH-7)

ORCH-6 persists the files that fail in a whole-suite run and pass in isolation.
In four routes it has already named four of them, two more than once — and the
only way to see that was to read the cache JSON by hand.

Adds a read-only `flaky` subcommand: per repo, each file ever confirmed flaky,
how many times, last seen, most-frequent first, with a named threshold marking
quarantine candidates. Old-shape cache entries are read without error. No
verdict logic changes.
```

## RUN COMMAND
```bash
cd ~/spectricom-orchestrator && unset ANTHROPIC_API_KEY && python3 orchestrator.py run toni-batch-s7core9-orch-7-flaky-tail-report-01.md --repo orchestrator --model sonnet --effort high --approve
```

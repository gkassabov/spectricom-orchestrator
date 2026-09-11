# Toni Batch S7-CORE-7 — [ORCH-2] make a gate declare what it actually collected

## Repo: orchestrator
## Batch ID: toni-batch-s7core7-orch-2-gate-collection-report-01
## Briefs: 1
## Estimated runtime: 35-50 min
## Spec reference: PCU v1-131 [ORCH-2] · Spectricom_S7-CORE-6_Handoff "the finding that matters most" · SESSION-BOOT PRE-FIRE ASSERTION BLOCK
## Predecessor branch: main — orchestrator `63ed4f8`, clean, 0 unpushed
## Self-mod: YES — meta-fire worktree at /tmp/orch-fire-<ts> is expected and correct

# Rule: Verify with build + lint after all briefs complete. Do NOT run Playwright E2E tests during batch execution.

---

## 1 · Why this exists

For three Longevity routes the orchestrator reported **`gate: PASS`** and the gate was
`npm run sit:gate` → vitest over `sit/integration/**`, **a directory holding two files that had
nothing to do with Longevity**. It returned in 2.3 seconds. Nothing in the orchestrator's output
distinguished that from a real gate, so three capabilities were promoted on it.

A human found it by reading the directory. **The orchestrator should have said it.** This brief
makes a gate report what it collected, so a thin gate is visible in the run log instead of
silently reassuring.

The clinical-mp half is already done (`b04051b` put five Longevity integration tests in that
directory; the same gate now collects 7 files / 18 tests). This is the orchestrator half.

## 2 · Recon (do this first, report what you find)

1. Read `run_sit_post_merge` (orchestrator.py ~1050-1130) — note that `raw` already holds combined stdout+stderr, so the vitest summary is **already in hand** and nothing new needs to be executed.
2. Read the `SitOutcome` dataclass (~1041) and `_log_sit_outcome` (~1224).
3. Read the FINAL STATUS line (~1569) and `msg += f" | gate: {result.gate_outcome}"` (~746).
4. Read `tests/test_sit_integration.py` to match existing fixture style.
5. Report the vitest summary format you are parsing against, quoted from a real run.

## 3 · Decisions locked

- **Parse, do not re-run.** The counts come from output the gate already produced. This brief must not add a second test invocation, a `--reporter=json` flag, or any new subprocess.
- **Unparseable is `None`, never `0`.** If the summary lines are absent or the format changes, the counts are `None` and the run is reported as `collection unknown`. **A fabricated `0` would trip the zero-collection block in §4.5 and turn a reporting change into a false failure.**
- **Zero collected is a blocking environment failure, not a product failure.** A gate that ran and collected **0 test files or 0 tests** has not tested anything. Return `BLOCKED(environment)`, consistent with F-20 / §23.9d handling — never `FAIL(product)`, and never a pass.
- **The thin-gate floor is configuration, not a literal** (D-S7CORE6-05). Ships **absent**; when unset, no floor warning fires and only the counts are reported. Zero-collection blocking is independent of the floor and is always on.
- **Do not touch** `run_build_gate`, the merge ordering, `prefire.py`, the A2/A8 assertions, or `CODE-GUARD`.

## 4 · Implementation

### 4.1 Parse the vitest summary
Extract from `raw`, tolerant of ANSI colour codes and of the leading whitespace vitest emits:
- `Test Files  <n> passed (<total>)` — also handle `<n> failed | <m> passed (<total>)`
- `Tests  <n> passed (<total>)` — same shapes
Capture **passed** and **total** for each. Absent → `None`.

### 4.2 Extend `SitOutcome`
Add: `test_files_total: Optional[int] = None` · `test_files_passed: Optional[int] = None` ·
`tests_total: Optional[int] = None` · `tests_passed: Optional[int] = None`. Defaults keep every
existing construction site valid — **do not** make them required.

### 4.3 Log it at the moment of the gate
Replace the bare `✅ SIT gate PASSED` / `✅ SIT PASSED ({duration}s)` pair with one line carrying
the counts, e.g.
`🧪 SIT gate: PASS — collected 7 test files / 18 tests in 6.6s`
and when unparseable: `🧪 SIT gate: PASS — collection unknown (summary not parsed) in 6.6s`.

### 4.4 Persist it
Add the four counts to the `_log_sit_outcome` entry dict so `orchestrator-sit-log.json` carries
them per run. This is what makes "was the gate ever thin?" answerable historically instead of
anecdotally.

### 4.5 Zero-collection block
If the gate exited 0 **and** `test_files_total == 0` or `tests_total == 0`: log
`⛔ SIT gate collected NOTHING — treating as BLOCKED(environment), not PASS` and return an outcome
the caller blocks on, classified as environment. A green exit code over an empty collection is the
exact failure this brief exists to catch.

### 4.6 Optional floor
Read `SIT_MIN_TEST_FILES` from env/config. **Unset = no floor, no warning.** When set and
`test_files_total` is below it, log `⚠️ SIT gate thin: N test files (floor M)` — a warning only,
never blocking.

### 4.7 Surface it in FINAL STATUS
The FINAL STATUS line and the batch summary line must carry the counts when known:
`🏁 FINAL STATUS: passed | gate: PASS (7 files/18 tests, 6.6s)`.

### 4.8 Fix the contradictory log pair (found in recon, in scope)
On failure the function logs `⛔ SIT gate FAILED (exit N) — BLOCKING.` and then, ~20 lines later,
`⚠️ SIT FAILED (exit N, Xs) — advisory only, not blocking merge`. **The second is stale wording
from before [ORCH-1]** — since `448e0c4` a red gate blocks the merge. Correct the second message;
do not change the control flow.

## 5 · Affected surface

- **Edit:** `orchestrator.py` — `SitOutcome`, `run_sit_post_merge`, `_log_sit_outcome`, the FINAL STATUS line (~1569) and the batch summary line (~746)
- **New or extended:** `tests/test_gate_collection.py` (or extend `tests/test_sit_integration.py` — match the existing style)
- **Must not change:** `run_build_gate` · `prefire.py` · the A2/A8 assertion path · `run_batch` merge ordering · `CODE-GUARD` · `repos.yaml`
- Union taken with `grep -n "SitOutcome\|_log_sit_outcome\|gate_outcome" orchestrator.py tests/` — **report any call site the recon finds that this brief does not name.**

## 6 · Acceptance criteria

- **AC-O2-01** — a real `sit:gate` vitest summary parses to `7 / 7` test files and `18 / 18` tests (use a fixture captured from actual output, not hand-written).
- **AC-O2-02** — a mixed summary (`2 failed | 5 passed (7)`) parses passed and total correctly.
- **AC-O2-03** — output with **no** summary lines yields `None` for all four counts, and the run logs `collection unknown`. **It must not yield 0.**
- **AC-O2-04** — exit 0 with `Test Files 0 passed (0)` returns a **blocking** outcome classified as **environment**, not product, and not a pass.
- **AC-O2-05** — `orchestrator-sit-log.json` gains the four counts on a new entry; an existing log file with old-shape entries still loads (backwards compatible).
- **AC-O2-06** — FINAL STATUS renders `gate: PASS (7 files/18 tests, 6.6s)` when counts are known and falls back to the current wording when they are not.
- **AC-O2-07** — `SIT_MIN_TEST_FILES` unset ⇒ no floor warning; set above the collected count ⇒ one warning, **still passing**.
- **AC-O2-08** — the stale "advisory only, not blocking merge" message no longer appears on a blocking failure; `grep -c "advisory only, not blocking merge" orchestrator.py` returns 0.
- **AC-O2-09** — `pytest -q tests/` shows **no new failures** vs the baseline **measured at authoring time on `63ed4f8`: 3 failed / 56 passed in 0.71s**, all three pre-existing in `tests/test_sit_integration.py::TestRunSitPostMerge` (`test_sit_parse_miss_advisory` among them). *Canon's S7-CORE-4 figure of "3 failed / 44 passed" is stale — HOOK-1 added 12 guard tests at `63ed4f8`. Measured, not asserted.* Report both numbers.
- **AC-O2-10** — no second test invocation was added: `grep -c "npm run sit:gate" orchestrator.py` is unchanged from recon.

## 7 · Reseed scope

**None.** No `synth:*`, no `wipeResourceType`, no FHIR resource touched. This route does not enter
clinical-mp at all.

## 8 · SIT spec impact

**No SIT surface impact** — orchestrator has no user-facing surface. `pytest` is the gate here.

## 9 · STOP and report

- Any call site of `SitOutcome` or `_log_sit_outcome` outside the files named in §5.
- The vitest summary format does not match §4.1 against a real captured run.
- Making the counts available would require re-running the gate or changing its command.
- `pytest -q tests/` baseline is not **3 failed / 56 passed** — report what it actually is before proceeding.

## 10 · Completion report

State: the summary format parsed (quoted from a real run); the four counts on a live gate; each AC
with its evidence; the `pytest` before/after numbers; and the FINAL STATUS line as rendered.
**Do not report a test as passing without naming the file it lives in.**

## RUN COMMAND
```bash
cd ~/spectricom-orchestrator && unset ANTHROPIC_API_KEY && python3 orchestrator.py run toni-batch-s7core7-orch-2-gate-collection-report-01.md --repo orchestrator --approve
```

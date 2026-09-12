# Toni Batch S7-CORE-7 — [ORCH-2b] reconcile the stale SIT tests with the post-[ORCH-1] contract

## Repo: orchestrator
## Batch ID: toni-batch-s7core7-orch-2b-stale-sit-tests-01
## Briefs: 1
## Estimated runtime: 15-25 min
## Micro-fire trigger: P0-infra — three tests in `TestRunSitPostMerge` assert pre-[ORCH-1] "advisory" semantics (`passed is True` on a non-zero exit). They have been red since `448e0c4`, and because the orchestrator's own build gate is zero-tolerance `pytest -q tests/`, **no orchestrator self-mod can ever reach a green gate while they stand** — [ORCH-2] was blocked by exactly this, with zero product regression. Under the sizing floor by §5.9.
## Spec reference: PCU v1-131 [ORCH-2] · Gemma_System_Prompt §5.15 (baseline-vs-zero gate) · LESSONS `[review:test-encodes-assumption]`
## Predecessor branch: **main @ `63ed4f8`** — deliberately NOT the preserved [ORCH-2] branch. [ORCH-2] never touched `tests/test_sit_integration.py`, so fixing the stale tests on main first keeps a red state off main and lets `9772cb4` fast-forward cleanly afterwards.
## Self-mod: YES — meta-fire worktree is expected

# Rule: Verify with build + lint after all briefs complete. Do NOT run Playwright E2E tests during batch execution.

---

## 1 · Why this exists

`run_sit_post_merge` has been **exit-code based since S6S78 / [ORCH-1]**: `passed = (r.returncode == 0)`.
Its own comment says the old Playwright spec-name parsing must not be relied on because it
*"would mis-read a real vitest failure as 'no specs parsed -> advisory' and silently pass."*

Three tests still assert the abandoned contract:

| Test | Asserts | Under the current contract |
|---|---|---|
| `test_sit_noncritical_under_threshold_advisory` | exit 1 + 2 non-critical spec failures → `passed is True` | **`passed is False`** |
| `test_sit_baseline_only_advisory` | exit 1 + only known-failing specs → `passed is True` | **`passed is False`** |
| `test_sit_parse_miss_advisory` | exit 1 + unparseable output → `passed is True` | **`passed is False`** |

They are not tech debt to tolerate. **They encode the exact failure mode the code was changed to
prevent** — a real failure passing silently. This is `[review:test-encodes-assumption]`: a test
states an assumption about correct behaviour, and this one is now wrong.

## 2 · Recon (do this first, report what you find)

1. Confirm the base is `main` at `63ed4f8`. **`tests/test_gate_collection.py` and `tests/fixtures/` do NOT exist here** — they live on the preserved [ORCH-2] branch and are merged separately. Their absence is expected, not a problem.
2. `python3 -m pytest -q tests/` — confirm **3 failed / 56 passed** and that the three are exactly the ones named above.
3. Read `run_sit_post_merge` and quote the line that determines `passed`.
4. Read the whole of `TestRunSitPostMerge` and report **every** test in it, not only the failing three.

## 3 · Decisions locked

- **Rewrite to the contract; do not weaken the gate.** The fix is in the tests. Do **not** add baseline tolerance, a known-failing carve-out, or a retry to `run_build_gate` or `run_sit_post_merge`. §5.15's baseline pattern is for *pre-existing product debt* — this is a stale assertion, which is a different thing.
- **Rename as well as re-assert.** A test called `..._advisory` that asserts blocking is a trap for the next reader. Names must state the behaviour they now assert.
- **`test_sit_timeout_advisory` is CORRECT and stays.** `TimeoutExpired` genuinely returns `SitOutcome(passed=True, error="timeout-advisory")` — that is deliberate, still true, and **must not be "fixed"**. Touching it is the most likely over-correction here.
- **`test_sit_many_noncritical_blocks` passes only incidentally** — it asserts `passed is False`, which is now true of every non-zero exit rather than of the threshold it was written for. Re-ground its docstring so it no longer implies a threshold rule that no longer runs. Do not delete it.
- **Keep the coverage, don't just delete the reds.** Each rewritten test must still exercise its original input shape (non-critical failures · baseline-only failures · unparseable output) and assert the current outcome for it.
- **Do not touch** `prefire.py`, the A2/A8 path, `CODE-GUARD`, `repos.yaml`, merge ordering, or anything in [ORCH-2]'s collection-reporting work.

## 4 · Acceptance criteria

- **AC-O2B-01** — `python3 -m pytest -q tests/` is **green: 0 failed**, and the passed count is **≥ 56** (the three rewritten tests still run, so expect **59**). Report the exact numbers before and after.
- **AC-O2B-02** — the three rewritten tests assert `outcome.passed is False` for a non-zero exit, each still driving its original input shape.
- **AC-O2B-03** — no test name in `TestRunSitPostMerge` contains `advisory` unless it asserts `passed is True`. `grep -n "advisory" tests/test_sit_integration.py` output is reported in full.
- **AC-O2B-04** — `test_sit_timeout_advisory` is **unchanged**; `git diff` shows no edit to its body.
- **AC-O2B-05** — `run_build_gate` and `run_sit_post_merge` are **unmodified by this brief**: `git diff 63ed4f8..HEAD -- orchestrator.py` is **empty**.
- **AC-O2B-06** — the change is confined to `tests/test_sit_integration.py`: `git diff --name-only 63ed4f8..HEAD` lists that file and nothing else. This is what lets the preserved [ORCH-2] branch merge afterwards without a conflict.
- **AC-O2B-07** — a docstring or comment on each rewritten test names **[ORCH-1] / `448e0c4`** as the change that moved the contract, so the next reader sees why it was rewritten rather than assuming it was loosened.

## 5 · Affected surface

- **Edit:** `tests/test_sit_integration.py` — `TestRunSitPostMerge` only
- **Must not change:** `orchestrator.py` · `prefire.py` · every other test class in the file · anything at all outside `tests/test_sit_integration.py`
- Union taken with `grep -rn "TestRunSitPostMerge\|run_sit_post_merge" tests/` — report any call site this brief does not name.

## 6 · Reseed scope

**None.** No `synth:*`, no `wipeResourceType`, no FHIR resource, no clinical-mp involvement.

## 7 · SIT spec impact

**No SIT surface impact** — orchestrator has no user-facing surface; `pytest` is the gate.

## 8 · STOP and report

- `pytest` baseline on main is not 3 failed / 56 passed.
- Making the three green appears to require an `orchestrator.py` change — that would mean the contract is not what §1 says it is, and it is a finding, not a licence to edit.
- Any test outside `TestRunSitPostMerge` turns red.

## 9 · Completion report

Quote the `passed = ...` line; the pytest numbers before and after; each renamed test old → new; the full `grep -n "advisory"` output; and confirmation that `git diff --name-only 63ed4f8..HEAD` lists only `tests/test_sit_integration.py`.

## RUN COMMAND
```bash
cd ~/spectricom-orchestrator && unset ANTHROPIC_API_KEY && python3 orchestrator.py run toni-batch-s7core7-orch-2b-stale-sit-tests-01.md --repo orchestrator --approve
```

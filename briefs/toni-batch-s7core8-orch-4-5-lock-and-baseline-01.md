# Toni Batch S7-CORE-8 — Bundle: ORCH-4 per-repo fire lock · ORCH-5 baseline measurement that can actually complete

## Repo: orchestrator
## Batch ID: toni-batch-s7core8-orch-4-5-lock-and-baseline-01
## Briefs: 2
## Estimated runtime: 60-90 min
## Predecessor branch: `main` @ `2b4518f` — clean, pytest 133 passed
## Executor profile: `claude-opus-5 --effort high`
## SELF-MOD: yes — meta-fire worktree + `_self_mod_auto_merge`.
## ⚠ Do NOT copy this brief into `~/spectricom-orchestrator/briefs/` yourself — the meta-fire copies it into the worktree, and an untracked duplicate in `briefs/` blocks the fast-forward merge (observed 2026-09-12, ORCH-3).

## BUNDLE CONTEXT
Both briefs are defects in the fire/gate machinery, found by running it. They share one substrate — `run_batch` / `run_pre_merge_gates` and the markers they read — so they land together.

**ORCH-3, merged at `2b4518f` an hour before this brief, blocked the very next clinical-mp route on its first live run.** That is not a reason to revert it; it refused to guess, which is correct. It is a reason to make the measurement it depends on achievable.

---

# BRIEF 1 of 2: ORCH-4 — the fire lock is global, but the doctrine says cross-repo parallel is safe

## 1 · The defect
`RUNNING_FILE = ORCH_DIR / "running.json"` (`orchestrator.py:75`) is a **single global marker**. A second fire for a *different* repo is refused with *"Another orchestrator fire is in progress."*

**Observed 2026-09-12:** a clinical-mp route was refused while an orchestrator meta-fire held the marker. The operator believed both were running, because the refusal is on line 2 of a log whose line 1 says `Executor: …`.

**System Prompt §5.19.1 states cross-repo parallel fires are safe** — different worktrees, no merge collision. That is true of the design and false of the implementation.

## 2 · Decisions locked
1. **The lock becomes per-repo.** Within a repo, serial (unchanged). Across repos, parallel.
2. **`state/running.json` must stay readable by whatever reads it today.** Find every reader — `status`, the stale-cleanup path, the dashboard note at `orchestrator.py:811/830/847` — and keep them working. **A migration that orphans a reader is worse than the bug.**
3. **Stale-marker cleanup stays per-repo too**: a dead PID for repo A must not clear repo B's live marker.
4. **Failure mode on refusal must name the repo**: *"a fire is already in progress for repo X"*, not a bare "another fire".

## 3 · Acceptance criteria
- **AC-O4-01** — two fires for **different** repos run concurrently; neither is refused. Asserted.
- **AC-O4-02** — two fires for the **same** repo: the second is refused, and the message **names that repo**.
- **AC-O4-03** — over **every reader of the running marker** (enumerate them by grep and list them in the report), each still works. No reader is left reading a path that no longer exists.
- **AC-O4-04** — a **stale** marker (dead PID) for repo A is cleaned and does **not** affect repo B's live marker. Asserted for both directions.
- **AC-O4-05** — `python3 -m pytest tests/ -q` shows **no new failures vs the `2b4518f` baseline of 133 passed**. State both numbers.
- **AC-O4-06** — `tests/test_running_marker.py` passes with **its existing assertions unmodified**, or — if per-repo pathing makes an assertion literally impossible — the report **quotes the old assertion, the new one, and why**. Do not silently rewrite it.

---

# BRIEF 2 of 2: ORCH-5 — the unit baseline gate cannot complete its own measurement

## 1 · The defect, measured
The gate ORCH-3 added ran on clinical-mp for the first time and returned:

```
FINAL STATUS: blocked | gate: BLOCKED(environment) — unit: baseline-unmeasurable
  (baseline at fda6974 did not yield a measurement (timeout))
  branch: 773 files / 7103 tests, 106 failed in 819.4s
```

`config/repos.yaml` gives clinical-mp `test_cmd: npm test`, which is the **whole repo** — 773 files, 7103 tests, ~14 minutes. The gate runs it **twice** (merge-base, then branch). The baseline leg hit the timeout, so no comparison was possible, and the route was correctly blocked with its branch preserved.

**The verdict logic is right. The cost model is wrong.** Paying ~28 minutes per route, and being unable to finish the first leg, makes the gate unusable as specified — by me, in the ORCH-3 brief, because I never measured how long `npm test` takes.

## 2 · Decisions locked
1. **Cache the baseline per merge-base commit.** The baseline for a given commit is immutable — measure it **once**, persist it keyed by SHA, reuse it for every later route off that base. This turns ~28 min/route into ~14 min once per base.
2. **Give the baseline leg its own timeout, separate from the branch leg, and make it generous** (default ≥ 30 min, configurable per repo). A timeout is still `BLOCKED(environment)` — never `FAIL(product)`.
3. **A cache miss is not a block if the branch leg is measurable and a stored baseline exists for an ancestor** — but say so explicitly in the verdict. **Never infer a baseline you did not measure.** If nothing usable exists, `BLOCKED(environment)` stands.
4. **Do not "fix" this by narrowing `test_cmd` to a fast subset.** The 106 failures in the full suite are real and mostly outside the scoped paths our routes touch; narrowing the command would hide them. The suite stays whole; the *measurement* gets cheaper.
5. **Persist and log the numbers** — files, tests, failures, duration, and whether the baseline was measured or read from cache — in the shape ORCH-2/ORCH-3 established.

## 3 · Acceptance criteria
- **AC-O5-01** — the baseline result is persisted keyed by the merge-base SHA and **reused** on a second route off the same base. Asserted: second route performs **no** baseline run.
- **AC-O5-02** — the cache records files, tests, failure count, duration and the SHA. A cache entry for a different SHA is **not** used.
- **AC-O5-03** — the baseline leg has its own timeout, default **≥ 1800s**, configurable per repo; the branch leg keeps its own.
- **AC-O5-04** — a baseline timeout yields **`BLOCKED(environment)`**, never `FAIL(product)`, and the message says the measurement failed rather than implying the product did.
- **AC-O5-05** — the verdict **states whether the baseline was measured now or read from cache**. Both cases asserted.
- **AC-O5-06** — `current > baseline` still blocks; `==` and `<` still pass; **a newly-failing file still blocks even when the count does not rise** (ORCH-3's AC-O3-04 semantics preserved). All asserted — these must not regress.
- **AC-O5-07** — `config/repos.yaml` `test_cmd` for clinical-mp is **unchanged** (`npm test`). Assert it literally; decision 4 forbids narrowing it.
- **AC-O5-08** — `python3 -m pytest tests/ -q` shows **no new failures vs 133 passed at `2b4518f`**. State both.
- **AC-O5-09** — `tests/test_unit_baseline_gate.py`'s existing assertions still pass **unmodified** except where caching makes an assertion literally impossible; in that case **quote old, new and why**. Do not silently rewrite.

## 4 · STOP-and-report triggers
- The fix appears to need narrowing `test_cmd` → **STOP.** Decision 4 forbids it.
- Caching appears to need state outside the orchestrator repo → **STOP and report** where you wanted to put it.
- Making ORCH-4 per-repo appears to require changing how `run_pre_merge_gates` is invoked → **STOP.** Do not couple the two briefs' surfaces.

## BUNDLE-LEVEL ACCEPTANCE CRITERIA
- **AC-B-01** — `pytest -q tests/` green, **no new failures vs 133**.
- **AC-B-02** — two commits, one per brief, each independently describable.
- **AC-B-03** — neither brief changes clinical-mp. This is an orchestrator-only route.

## RUN COMMAND
```
cd ~/spectricom-orchestrator && unset ANTHROPIC_API_KEY && python3 orchestrator.py run toni-batch-s7core8-orch-4-5-lock-and-baseline-01.md --repo orchestrator --model claude-opus-5 --effort high --approve
```

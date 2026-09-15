# ORCH-10 — a route whose HEAD moved must FAIL, not report `passed`

**Repo:** `orchestrator` (self-mod — meta-fire worktree) · **Base:** `main` at `bf9254c` · **Session:** S7-CORE-9
**Executor:** `claude-opus-5 --effort high`

## Estimated runtime: 45-75 min

---

## 1 · The incident this exists to prevent

On 2026-09-15 a clinical-mp route (`PLANDEF-1`) put a commit on **`main` with no gate**. The reflog, with nothing to interpret:

```
09:51:18  checkout: moving from main to orch-mp-…-plandef-1-action-ids-01   ← orchestrator
09:52:42  checkout: moving from orch-mp-…-plandef-1-action-ids-01 to main   ← a human, in the same working dir
10:08:56  commit:   fix(care-plans): carry action ids … (PLANDEF-1)          ← the executor, onto MAIN
10:09:33  checkout: moving from main to main                                 ← orchestrator
```

A `git checkout main` was run in the route's own working directory 84 seconds after the fire. The executor's commit therefore landed on **`main`** instead of on its branch. The orchestrator looked at its branch, correctly found **no changes**, logged *"Toni produced no changes — skipping commit"*, and returned:

```
FINAL STATUS: passed | gate: not run
```

**So the commit reached `main` with no build gate, no SIT gate and no unit baseline gate — and the run reported `passed`.** The change happened to be sound (all three gates were run by hand afterwards and passed), but that is luck, not a property of the system.

**`[ORCH-1]` gate-then-merge was not violated by the orchestrator. It was bypassed from outside, and the orchestrator could not tell.** That is the defect.

## 2 · Why it was hard to see

**The failure is indistinguishable in the log from a legitimate halt-and-report return.** Three hours earlier on the same day, `RED-5` returned `passed (no changes)` in 84 seconds because it had correctly decided the brief's hypothesis was wrong and refused to edit on it — **exactly the shape we want to encourage.** A reader who has just learned to treat a fast no-change return as *"read my report"* will read the tampered one the same way. It took a `git reflog` to find.

**Two states that must never look alike:**
- **"I ran, and chose to change nothing."** → `passed (no changes)`, a good outcome.
- **"My branch is not where I left it."** → not `passed` at all.

## 3 · Scope

**S1.** Record the route's expected state at hand-off: the branch **name**, its **SHA**, and the repo's **`HEAD` ref** at the moment control passes to the executor.

**S2.** Re-check all three when the executor returns, **before** the no-changes decision is made. If `HEAD` is not on the route branch, or the branch name resolved differently, this is a **tampered run**:
- do **not** report `passed`;
- do **not** run gates on, or merge, anything;
- log loudly, naming **the ref expected and the ref found**, and the SHA the branch sits at now;
- exit with a distinct, greppable verdict — `TAMPERED` or equivalent — that is neither `passed` nor `failed(product)`, because it is neither.

**S3.** **Detect the damage, do not repair it.** If commits exist on a ref the route did not own (the incident's shape: the executor's commit on `main`), **say so with the SHAs** and stop. **Do not reset, revert, cherry-pick or move any ref** — a wrong automatic repair on `main` is far worse than a loud stop. The report tells a human exactly what to look at.

**S4.** Keep the legitimate case fully intact. A route that returns **on its own branch with no commits** must still behave **exactly** as it does today: `passed (no changes)`, no gate, no merge. Assert this explicitly — it is the case `RED-5` and `PLANDEF-1`'s first attempt both relied on.

**S5.** Note in the report whether the same exposure exists for the **meta-fire worktree** path (a self-mod runs in `/tmp/orch-fire-*`). Report only; do not change that path in this route.

## 4 · Acceptance criteria

Every criterion names the set it quantifies over (A11).

- **AC-O10-01** — Given a repo whose `HEAD` has been moved off the route branch between hand-off and return, the run reports the **tampered** verdict, runs **no** gate, performs **no** merge, and its log names both the expected and the found ref. Asserted by a test that simulates the move.
- **AC-O10-02** — Given a route that returns **on its own branch with no commits**, behaviour is **byte-identical to today**: `passed`, no gate, no merge. Asserted.
- **AC-O10-03** — Given a normal route with commits on its branch, behaviour is unchanged: gates run, merge happens on PASS. Asserted.
- **AC-O10-04** — Given the incident's exact shape — `HEAD` moved to `main` **and** a commit made there — the report names the offending SHA(s) and the ref they landed on, and **no ref is modified** by the orchestrator. Asserted, including an assertion that the refs are unchanged after the run.
- **AC-O10-05** — The tampered verdict is **distinct from both** `passed` and `failed(product)` in the final-status line and in `orchestrator-unit-log.json`, and is greppable. Paste a sample line.
- **AC-O10-06** — `[ORCH-1]` gate-then-merge, `[ORCH-4]` per-repo lock, `[ORCH-5]` green-branch fast path (**reachable since `564d3b5` — do not regress it**), `[ORCH-6]`/`[ORCH-6b]`, `[ORCH-7]` and **`[ORCH-9]`'s unit-suite env isolation** all behave as before. Name each and say how you checked. **`[ORCH-9]` matters most: the unit suite must still NOT be run through `_gate_shell_cmd`.**
- **AC-O10-07** — `pytest tests` passes with **no new failing test** and the count **grows from 260**.
- **AC-O10-08** — S5 answered: does the meta-fire worktree path carry the same exposure? Report only.

## 5 · Method notes

- **Self-mod.** Brief committed pre-fire; meta-fire worktree. An untracked brief breaks the ff-merge — that cost two routes at S7-CORE-8, in opposite directions.
- **`prefire.check()` takes a `Path`, not a `str`** — `_read` returns `""` for a `str`, producing a **false** A2 failure.
- **Do not "fix" the human side by locking the working directory.** The operating rule (never run git in a repo with a live route) is already written into `LESSONS.md`. This route makes the system **notice**, not prevent.
- **A negative finding reported plainly is a success.** If S1's hand-off point turns out not to exist as a single place in the code, say where it would have to go and size it.

## 6 · Out of scope

- Any repair of `main` or of any other ref — **detect and report only**.
- Changing the meta-fire worktree path (S5 is report-only).
- Anything in `clinical-mp`.

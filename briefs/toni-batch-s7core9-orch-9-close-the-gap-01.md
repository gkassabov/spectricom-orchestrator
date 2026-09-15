# ORCH-9 — close the unexplained gap between the gate's failure count and the runner's

**Repo:** `orchestrator` (self-mod — meta-fire worktree) · **Base:** `main` at `df6746a` · **Session:** S7-CORE-9
**Executor:** `claude-opus-5 --effort high`

## Estimated runtime: 60-90 min

---

## 1 · The open item

On RED-5b's gate run, for the **same commits**:

| | gate reported | vitest itself reported |
|---|---|---|
| baseline `e837cbe` | **48 failed** | **9 failed** |
| branch | **41 failed** | **3 failed** |

**ORCH-8 (`564d3b5`) explains exactly 12 of each gap** — vitest's 8 skipped + 4 todo were being counted as failures. That is fixed.

**The remaining ~24 and ~26 have no accepted explanation.** ORCH-8's §4 investigated the obvious suspect and **refuted it, correctly and with evidence**: the two legs cannot overlap (one thread, `subprocess.run`, branch then baseline), the queue daemon `Popen`s one batch and `.wait()`s, `availableParallelism()` reports 24, and — decisively — **the gate's leg times (307.1 s / 287.0 s) are materially identical to a quiet run (~286–306 s)**. A starved suite's wall time would have moved and it did not.

**Standing consequence, currently in `hot.md`: do not quote a gate failure count as the repo's health.** That is a bad place to be for the one number every route is judged on. This route closes it.

## 2 · The leading hypothesis, and it is only a hypothesis

ORCH-8's report proposes: **the baseline leg runs in a fresh detached `/tmp` worktree with `node_modules` symlinked in (`orchestrator.py:1779`), so it starts on a cold vite transform cache while the branch leg runs warm.** That changes a leg's cost profile without changing CPU contention — which fits "wall time barely moved" better than starvation does.

**Treat it as a lead, not an answer.** It is also incomplete on its face: it would explain a difference **between the two legs**, but both legs were high against vitest's own numbers, and the *branch* leg is the warm one.

Other things that could produce failures the runner itself does not report, to rule in or out: a **stale or mis-scoped baseline cache entry** being compared against a fresh run; the gate parsing **a different run's output** than it thinks (an interleaved or truncated capture); `exit_code` and the parsed summary disagreeing; the gate capturing output from the **worktree** run while reporting it as the branch run; or output from two runs concatenated in one buffer so the "last match wins" rule in `_parse_vitest_summary` picks a summary that belongs to the other leg.

## 3 · Scope

**S1.** **Reproduce first.** Run the gate against a known commit and capture, side by side: the raw output the gate parsed, the counts it derived, and an independent `npx vitest run` of the same commit that you perform yourself. **Do not proceed on reasoning alone** — this is the third number in this repo that was believed without being reconciled.

**S2.** Establish where the extra failures come from. The two shapes to distinguish: **(a)** the gate's run genuinely had more failing tests than a quiet run of the same commit — a real environmental difference, which the wall-time evidence argues against but does not exclude; **(b)** the gate is reporting a number that does not correspond to the run it thinks it is describing — a capture or parse fault. **(b) is cheap to test and should be tested first.**

**S3.** Fix what you find, *if* it is bounded. If the honest answer is "mechanism X, and fixing it is a route of size Y", **say that and stop** — a named mechanism with a sizing is a pass.

**S4.** Whatever the outcome, make the gate **self-reconciling**: the log must carry enough that a reader can tell, without re-running, whether the gate's number agrees with the runner's own summary — and flag it loudly when it does not. ORCH-8 already prints failed/passed/skipped/todo/total and a `failures_source`. Add an explicit agreement check: **if the parsed tallies do not sum to the runner's stated total, say so in the verdict line.** That single assertion would have caught this three sessions ago.

## 4 · Acceptance criteria

Every criterion names the set it quantifies over (A11).

- **AC-O9-01** — The report contains, for **one** commit, three things measured by you: the gate's reported counts, the raw runner summary the gate parsed (verbatim), and your own independent `npx vitest run` summary of that same commit (verbatim).
- **AC-O9-02** — The report states which of §3's shapes (a) or (b) the evidence supports, **with the specific evidence**, and names the mechanism or states plainly that it is still unidentified.
- **AC-O9-03** — A tally-agreement check exists: when `failed + passed + skipped + todo` does not equal the runner's stated total, the verdict line says so explicitly. Asserted by a unit test for both the agreeing and the disagreeing case.
- **AC-O9-04** — The `[ORCH-2]` rule is intact: counts are **parsed from captured output, never re-run** by the gate itself. Any run you perform for diagnosis is yours, not the gate's.
- **AC-O9-05** — §2.4 is intact: absent or unrecognised output ⇒ `failures is None` ⇒ UNKNOWN, **never `0`**. Asserted by a test.
- **AC-O9-06** — ORCH-8's behaviour is unchanged where it was right: `failures` still comes from the runner's stated `failed` segment when present; the fallback still subtracts named skipped/todo; `failures_source` still reports `reported` / `derived`. Name how you checked each.
- **AC-O9-07** — Verdict semantics unchanged: `[ORCH-1]` gate-then-merge, `[ORCH-4]` per-repo lock, `[ORCH-5]` green-branch fast path (**now reachable — do not regress it**), `[ORCH-6]`/`[ORCH-6b]` confirm-before-fail and confirmed-files keying, `[ORCH-7]` flaky tail. Name each and say how you checked.
- **AC-O9-08** — `pytest tests` passes with **no new failing test**, and the count **grows** from **232**.
- **AC-O9-09** — If the fix touches the baseline worktree path (`orchestrator.py:1779`), the report shows before/after leg wall times. If it does not touch it, say why the cold-cache hypothesis was rejected.

## 5 · Method notes

- **Self-mod.** Brief committed pre-fire; meta-fire worktree. An untracked brief breaks the ff-merge — that cost two routes at S7-CORE-8, in opposite directions.
- **`prefire.check()` takes a `Path`, not a `str`** — `_read` returns `""` for a `str`, producing a **false** A2 failure.
- **Do not narrow `test_cmd`.** `npm test` stays the whole repo.
- **A negative finding reported plainly is a success.** ORCH-8's §4 refuted the starvation theory with wall-time evidence and that was the most valuable paragraph in its report.

## 6 · Out of scope

- Anything in `clinical-mp` — `SETUP-1` is running there in parallel and will change whole-run timings. **Take your baseline measurement on a pinned commit and say which one**, so the two routes cannot confound each other.
- Re-tuning any threshold. Name and size instead.

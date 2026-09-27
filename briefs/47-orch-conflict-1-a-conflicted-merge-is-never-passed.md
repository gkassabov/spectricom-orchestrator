#!queue model=claude-opus-5-5 effort=high repo=orchestrator

# ORCH-CONFLICT-1 — a conflicted merge is never `passed`

## Repo: orchestrator
## Batch ID: s7core15-orch-conflict-1
## Briefs: 1
## Estimated runtime: 30-45 min
## Spec reference: found while authoring ORCH-STALEBASE-1 (S7-CORE-15)
## Predecessor: `main` at `23ab07f` (GATE-SIT-2) or later. `23ab07f` sits on `1794370` (ORCH-STALEBASE-1); both must be on `main` before this fires. `origin/main` was also at `23ab07f` when this brief was written. Baseline at `23ab07f`: `pytest -q tests/` = **454 passed, 0 failed** per the task author. That number was NOT re-measured while writing this brief, so measure it yourself first (§0 step 9).

## 0 · FIRST STEP

Read these in full, in this order, before designing anything. Every line number below was checked against `main` @ `23ab07f`. Two routes merged into `orchestrator.py` today, so re-grep before you edit.

1. `logs/orch-20260921-020444.log:35-41`: the evidence. (Note: the log is at `logs/`, not `logs/orchestrator/` as the task note said. `LOG_DIR = ORCH_DIR / "logs"` at `orchestrator.py:76`.) `:35` pre-merge gate PASS, `:36` `⚠️ Merge conflict on orch-mp-23-l-ui-safety-1-… — MANUAL RESOLUTION NEEDED`, `:37` an **empty** stderr line, `:38` `🏁 FINAL STATUS: passed | gate: PASS …`, `:41` the `✅ … — passed` notify line.
2. `orchestrator.py:3474` `_run_batch_inner` → the route-lane merge section `:3611-3725`:
   - `:3655` `verdict = run_pre_merge_gates(proj, branch_name)`, the gate. The red-gate branch `:3659-3671` sets `status` BLOCKED/FAILED.
   - `:3674` `pre_merge_tip` (the MERGE_TARGET tip), `:3678` `git checkout {MERGE_TARGET}`, `:3679-3682` `git merge {branch_name} --no-edit`.
   - `:3688-3696`: the OBS-S6S17-02 sibling. A merge that "succeeded" without moving the tip sets `status = Status.FAILED` **at its own site**. This is the precedent.
   - `:3698-3706`: the good merge. It logs `🔀 Merged`, calls `retire_batch_file(batch_file)` and runs `git branch -d`.
   - **`:3707-3709`: THE DEFECT.** The `else:` of `r.returncode == 0` logs two lines and does nothing else. `status` stays `Status.PASSED` (set at `:3566`), nobody runs `git merge --abort`, and `gate_error` stays `None`. It also logs `r.stderr`, which is consistent with the empty `:37` above: git prints its `CONFLICT (…)` lines on stdout.
   - `:3722-3725`: the `except Exception` "Git automation error" handler. It also leaves `status` untouched.
3. `orchestrator.py:3745-3746`: the `🏁 FINAL STATUS` line. `:3747-3755` builds the `Result`, `:3756` calls `notify`, `:3760-3763` is the dependency cascade (runs on PASSED only).
4. `orchestrator.py:1042` `_gate_status_label` (the gate field of FINAL STATUS: `gate_error or gate_outcome or "not run"`), `:1059` `notify`.
5. `orchestrator.py:419` `GateOutcome`, `:426` `GateVerdict`, `:448` `Status`, `:460` `Result`, `:887` `TAMPER_VERDICT`. `TAMPER_VERDICT` is the precedent for a greppable verdict token.
6. `orchestrator.py:3171` `sit_verdict_violations` and `:3206` `run_pre_merge_gates`. **This is where GATE VERDICTS are decided, and it stays the only place.** The merge runs *after* `run_pre_merge_gates` has returned PASS. A conflict is not a gate verdict. It must not become a `GateOutcome` member, and it must not be decided in a second verdict function beside `sit_verdict_violations`.
7. `orchestrator.py:3387` `run_batch`: the self-mod lane `:3452-3470`, `_self_mod_auto_merge` at `:1423`. Read this so you understand why it is **out of scope** (§4). Do not edit it.
8. `canon_assert.py`: the existing predicate module. `:458` `QueueRepo` (`branch_for`), `:400` `git`, `:492` `_git_rc`, `:497` `_is_ancestor`, `:505` `_landed` ("has this route already landed?"), `:557` `check_queue_trunk_invariants`, `:605` `StaleBaseViolation`, `:621` `check_branch_freshness_invariants` (ORCH-STALEBASE-1). They all follow the same rules: EMPTY WHEN CLEAN, and unreadable is never a violation. `orchestrator.py:35` imports from it.
9. Tests you will build on, or that constrain you:
   - `tests/test_stale_base.py:47` `_init_repo`, `:94-120` the `route` fixture, `:123-137` `fire` (fake `run_pre_merge_gates`, fake `fire_toni`, then `_run_batch_inner`), `:140` `works`.
   - `tests/test_unit_baseline_gate.py:502-513` asserts `inner.count("run_pre_merge_gates(") == 2` inside `_run_batch_inner`. Do not add a third occurrence of that string, including in comments.
   - `tests/test_queue_retire.py:346-355` pins the order `🔀 Merged {branch_name}` < `retire_batch_file(batch_file)` < `git branch -d {branch_name}`. `:362-365` pins `batch_file=batch_file` at the self-mod call.
   - `tests/test_route_ref_integrity.py:228-233`: a no-changes run still prints `FINAL STATUS: passed | gate: not run`.
   - Then run `pytest -q tests/` on unmodified `23ab07f` and record the baseline counts.

## 1 · WHY THIS EXISTS

On 2026-09-21 at 02:27:25, L-UI-SAFETY-1 attempt 2 (clinical-mp) passed its pre-merge gate (`logs/orch-20260921-020444.log:35`). Its merge then conflicted (`:36`), and the run still printed `FINAL STATUS: passed` (`:38`) and notified `✅ … passed` (`:41`). Everything downstream reads that line. `main` exits 0 on PASSED (`orchestrator.py:4251`). The queue daemon moves an exit-0 brief to `queue/done/` and counts it `PASSED` (`queue_daemon.py:413-420`). `run_queue` does not halt on PASSED (`orchestrator.py:3791`). The dependency cascade unblocks dependants (`:3760-3763`). Every canon claim that a route "landed" is built on the FINAL STATUS line. A route that cannot merge reporting `passed` is the worst failure mode this pipeline has, because nothing after it knows to doubt it.

ORCH-STALEBASE-1 (`1794370`) removed the *cause* of that particular conflict: attempt 2 adopted attempt 1's stale branch (see the comment block at `canon_assert.py:588-602`). It did not remove the *reachability*. A branch cut fresh from `main` still conflicts if `main` moves while the route runs. In the evidence, the route took 22½ minutes (02:04:44 → 02:27:25), and its gate alone took about 9 minutes (`:20` → `:35`). Other routes merge to `main` in that window. The conflict branch at `orchestrator.py:3707-3709` has been wrong since it was written. This brief makes it tell the truth, and adds the invariant that stops any future path in this lane from repeating the lie.

## 2 · THE TARGET STATE (D-S7CORE13-02 · S1: a runnable predicate, not a symptom list)

**A route-lane run whose final status is `passed` and which produced changes has its route tip on the merge target, and leaves the merge target's repo not mid-merge.**

Ship that sentence as ONE predicate that **extends `canon_assert.py`**, the module that already answers "has this route landed?" (`_landed`, `:505`) and "is this route branch fresh?" (`check_branch_freshness_invariants`, `:621`). Do not author a second predicate module, and do not put a predicate in `orchestrator.py` beside `sit_verdict_violations` (that one is about gate verdicts; this one is about the merge). Place it directly after `check_branch_freshness_invariants` and before the `# ── verdict building` banner (`canon_assert.py:651`):

```python
@dataclass(frozen=True)
class UnlandedRouteViolation:
    """A route reported ready to pass whose tip is not on the merge target, or whose repo is mid-merge."""
    repo: str
    branch: str
    merge_target: str
    route_tip: str      # the route branch's tip as the merge was attempted (caller-supplied)
    target_tip: str     # the merge target's tip now
    landed: bool        # git merge-base --is-ancestor <route_tip> <merge_target>
    mid_merge: bool     # MERGE_HEAD resolves in repo.path

def check_route_landed_invariants(repo: QueueRepo, brief: str, route_tip: str) -> list[UnlandedRouteViolation]:
    """EMPTY WHEN CLEAN. Clean ⇔ `route_tip` is an ancestor of `repo.merge_target` AND
    `git rev-parse -q --verify MERGE_HEAD` fails in repo.path. The set is exactly ONE route,
    `repo.branch_for(brief)`, named by the caller. Unreadable (no .git, merge target or
    route_tip unresolvable) ⇒ [] — the module's rule, same as _landed and
    check_branch_freshness_invariants."""
```

Reuse `git` (`:400`), `_git_rc` (`:492`) and `_is_ancestor` (`:497`). Do not copy them. The route tip is supplied by the caller, not read from `refs/heads/<branch>`: after a good merge the route lane deletes the branch (`orchestrator.py:3706`), so the ref cannot be the evidence. Ancestry of the captured tip is also stricter than `_landed`'s merge-commit subject scan, because a previous attempt's `Merge branch '<same name>'` cannot answer for this one.

**Reachability (D-S7CORE9-01):** the non-test caller is `_run_batch_inner`, immediately before the `🏁 FINAL STATUS` log (`orchestrator.py:3745`). It is called when ALL of these hold: `tamper is None`, `branch_name` is set, `worktree is None`, `status is Status.PASSED`, `not no_change_run`, and the captured route tip is not None. If it returns a non-empty list, each violation is `log.error`ed with the prefix `⛔ ORCH-CONFLICT-1 invariant:`, `status` becomes `Status.FAILED`, and `gate_error` names the violation. **The invariant is acted on, not just logged.** The difference from `sit_verdict_violations` is deliberate: that one audits a verdict another rule decided, while this one guards the one line every downstream claim is built on.

**Done means this: for every route-lane `_run_batch_inner` run that the §5 tests construct, the predicate returns `[]` whenever `Result.status is Status.PASSED`, and the conflict fixture's `Result.status is Status.FAILED`.** It does not mean "a status assignment was added to the conflict branch".

No domain value is involved (rule A10). The only new literal is the orchestrator's own log token `MERGE_CONFLICT_VERDICT = "MERGE CONFLICT"`, which is shape, like `TAMPER_VERDICT` at `:887`.

## 3 · SCOPE: exactly what to change

### T1 · the predicate (`canon_assert.py`, after `:650`)
`UnlandedRouteViolation` and `check_route_landed_invariants` as in §2. `__str__` names the branch, both tips (8 chars) and which leg failed (`not on <target>` / `repo mid-merge`), in the style of `StaleBaseViolation.__str__` (`:616-618`). Extend the import at `orchestrator.py:35` to bring in `check_route_landed_invariants`, so tests can patch it as `orchestrator.check_route_landed_invariants`.

### T2 · capture the route tip (`orchestrator.py`, route lane, before `:3678`)
In the green-gate `else:` (after `:3673`, before `git checkout {MERGE_TARGET}` at `:3678`), record `route_tip = git rev-parse HEAD` in `proj`. The route branch is still checked out at that point. Initialise `route_tip: Optional[str] = None` next to the other per-run locals (`:3596-3599`) so the FINAL STATUS site can read it on every path.

### T3 · the conflict branch tells the truth (`orchestrator.py:3707-3709`)
When `git merge` returns non-zero:
1. Collect the unmerged paths: `git diff --name-only --diff-filter=U` in `proj`.
2. `git merge --abort` in `proj`. If the abort itself fails, `log.error` that, including its stderr. Do not attempt anything further.
3. `status = Status.FAILED`, and `gate_error` becomes one line of the form `f"{MERGE_CONFLICT_VERDICT} — {branch_name} → {MERGE_TARGET} ({<unmerged paths, comma-joined>}); gate was {gate_outcome}"`. The gate field of FINAL STATUS then shows both facts: the gate passed and the merge did not.
4. Keep the existing `⚠️ Merge conflict on {branch_name} — MANUAL RESOLUTION NEEDED` line word for word, because it is greppable and `merge_branch` at `:1384` uses the same wording. Log `r.stdout` as well as `r.stderr`.
5. Do NOT delete the branch, and do NOT call `retire_batch_file` here. It stays inside the success branch only (`tests/test_queue_retire.py:346`).
6. `gate_outcome` stays `"PASS"`. The gate verdict was true, so it is not rewritten. Add `MERGE_CONFLICT_VERDICT` beside `TAMPER_VERDICT` (`:887`).

### T4 · the invariant at the FINAL STATUS site (`orchestrator.py`, before `:3745`)
Call `check_route_landed_invariants(QueueRepo(ACTIVE_REPO_NAME, proj, MERGE_TARGET, BRANCH_PREFIX), batch_file.name, route_tip)` under exactly the guard in §2. `QueueRepo(...)` is built the same way as at `:3512`. Act on it as §2 says. The `except Exception` path at `:3722-3725` is covered by this too whenever `route_tip` was captured before the exception.

### T5 · tests
- **New file `tests/test_merge_conflict.py`**: the route-lane tests. It imports **only existing symbols** from `orchestrator` at module level, so it collects on unmodified code. Where it needs `MERGE_CONFLICT_VERDICT`, use `getattr(orchestrator, "MERGE_CONFLICT_VERDICT", "MERGE CONFLICT")`. Reuse the `route` fixture, `fire` and `works` from `tests/test_stale_base.py:94-140`: import them, or copy them into the new file. Either way, do not edit `test_stale_base.py`. The conflict is injected by a fake `run_pre_merge_gates`. While the route branch is checked out, it advances `main` with a conflicting commit to `feature.txt`: `git worktree add <tmp>/mainwt main`, commit, then **`git worktree remove`**, because otherwise the orchestrator's `git checkout main` fails. It then returns `GateVerdict(GateOutcome.PASS, …)`. This models `main` moving during the gate window, which is the shape that ORCH-STALEBASE-1 leaves reachable.
- **New file `tests/test_route_landed.py`**: unit tests for the predicate, on real git repos built with `_init_repo`-style helpers.

## 4 · OUT OF SCOPE

- **Do not change the SIT isolation logic GATE-SIT-2 just shipped.** That covers `SitIsolation` (`orchestrator.py:1560`), `_sit_isolate` (`:1889`), the isolation leg in `run_sit_post_merge` (`:1952`), rule 3 in `_classify_gate_failure` (`:3100`), `sit_verdict_violations` (`:3171`) and the `sit` branch of `run_pre_merge_gates` (`:3206`). `GateOutcome` and `GateVerdict` get no new member or field.
- **Do not change branch freshness or retirement (ORCH-STALEBASE-1, today).** That covers `retire_stale_branch` (`:4000`), `_stale_base_result` (`:4028`), `check_branch_freshness_invariants` (`canon_assert.py:621`), the branch-cut blocks in `run_batch` (`:3400-3433`) and `_run_batch_inner` (`:3489-3531`), and QUEUE-RETIRE-1's `retire_batch_file` (`:1387`) and its call sites.
- **Do not touch the queue daemon** (`queue_daemon.py`, none of it). Its behaviour changes only because the exit code it reads changes (§6 consequence 1).
- **Successor ORCH-CONFLICT-2: the self-mod lane.** In this lane (the one this brief itself fires in, `repo=orchestrator`), `_run_batch_inner` prints FINAL STATUS at `:3745` *before* `run_batch` calls `_self_mod_auto_merge` at `:3455`. A `False` return (non-ff, `:1470-1475`) only logs. `result` is never updated, so `run` still exits 0 at `:4251`. Fixing that means moving where the self-mod merge happens relative to the FINAL STATUS line. That restructures the `run_batch` `finally` which ORCH-STALEBASE-1 just edited, and which `tests/test_queue_retire.py:362` pins. It is a separate increment. The T1 predicate already covers that lane's shape (§5 AC-CF-05 proves it), so ORCH-CONFLICT-2 **extends the call site and does not add a predicate**.
- **Successor ORCH-CONFLICT-3: the parallel lane.** `run_parallel` merges via `merge_branch` (`:1379`, call at `:3837`) after the Results are built, and counts `passed` at `:3841` regardless of the return value. Open question: whether `orchestrator.py parallel` (`:4261`) is still used at all. Ask George before briefing it.
- `run_queue`'s halt line (`:3793`) prints `r.gate_outcome or r.status.value`, so a conflicted route halts the queue with `⛔ Queue HALTED (PASS)`. It is left unchanged here, because the wording is shared by every halt kind. This is named in §6 as a consequence.
- Do not rewrite history. `state.json` and `queue/done/` entries from before this merge are not edited.
- Nothing outside this repo.

## 5 · ACCEPTANCE

- **AC-CF-01: the defect reproduced, red before green.** On code at merge-base `23ab07f` with only `tests/test_merge_conflict.py` added, `pytest -q tests/test_merge_conflict.py` reports **exactly 3 failed, 0 errors**. The three are:
  (a) `test_conflicted_merge_is_not_passed`: `Result.status is Status.FAILED`, and the captured `🏁 FINAL STATUS` line is not `FINAL STATUS: passed` and contains `MERGE CONFLICT`;
  (b) `test_conflicted_merge_leaves_the_target_as_it_found_it`: `main`'s tip equals the tip the fake gate left, `git rev-parse -q --verify MERGE_HEAD` fails, and `git status --porcelain` is empty in `proj`;
  (c) `test_conflicted_merge_preserves_the_branch_and_names_the_files`: `refs/heads/<route branch>` still resolves to the route tip, and `Result.error` contains both `MERGE CONFLICT` and `feature.txt`.
  After T1–T4 the same three pass. The set quantified over is those three tests. Any other test in the file is additive and is not part of the red count. State the red count you actually measured.
- **AC-CF-02: the green path is unchanged.** In `tests/test_merge_conflict.py`, a route whose fake gate does not advance `main` ends `Status.PASSED`, `🔀 Merged` is logged, the branch is deleted, and `check_route_landed_invariants` returned `[]` (asserted through a `wraps=` spy). This is quantified over that one test. The existing green-merge routes in `tests/test_stale_base.py` (all tests in that file) also pass with no edits to that file.
- **AC-CF-03: reachability (D-S7CORE9-01).** `_run_batch_inner` is the non-test caller of `check_route_landed_invariants`. With `patch.object(orchestrator, "check_route_landed_invariants", wraps=…)`, the green route of AC-CF-02 calls it exactly once, with `(QueueRepo(name, proj, "main", "orch"), "<brief>.md", <route tip sha>)`. A no-changes route (`tests/test_route_ref_integrity.py`'s `quiet` executor shape) calls it zero times. That second test is quantified over one route and names the no-changes exclusion from §2.
- **AC-CF-04: the invariant is acted on.** In the green route of AC-CF-02, patch `orchestrator.check_route_landed_invariants` to return one hand-built `UnlandedRouteViolation`. `Result.status is Status.FAILED`, the log contains `⛔ ORCH-CONFLICT-1 invariant:`, and FINAL STATUS is not `passed`. This is quantified over that one test.
- **AC-CF-05: the predicate, alone** (`tests/test_route_landed.py`). All cases use real git repos. Each of the following is its own test, and the set quantified over is exactly these six:
  (i) a route merged with `git merge --no-edit` → `[]`;
  (ii) a route fast-forwarded (`git merge --ff-only`, the self-mod shape) → `[]`;
  (iii) a route whose tip is not an ancestor of `main` → one violation, `landed=False, mid_merge=False`;
  (iv) a repo left mid-merge by a real conflict → one violation, `mid_merge=True`;
  (v) no `.git` / missing merge target / unresolvable `route_tip` → `[]` (three asserts, one test);
  (vi) a previous attempt's `Merge branch '<same branch>'` commit on `main`, plus a current route tip that is not on `main` → one violation. This proves the ancestry check, not the subject scan, decides.
- **AC-CF-06: no second verdict site.** Every assert here is quantified over `orchestrator.py` @ HEAD after the change. `GateOutcome` still has exactly its 3 members (`PASS`, `BLOCKED(environment)`, `FAIL(product)`). The string `run_pre_merge_gates(` occurs exactly twice inside `_run_batch_inner` (`tests/test_unit_baseline_gate.py:502` stays green, untouched). `sit_verdict_violations` is byte-identical to `23ab07f` (`git diff 23ab07f -- orchestrator.py` shows no hunk inside `def sit_verdict_violations(` … `def run_pre_merge_gates(`).
- **AC-CF-07: out-of-scope files untouched.** `git diff 23ab07f --stat` lists exactly `canon_assert.py`, `orchestrator.py`, `tests/test_merge_conflict.py`, `tests/test_route_landed.py` and this brief's handback, if you write one. In particular `queue_daemon.py` does not appear. Within `orchestrator.py`, no hunk falls inside `retire_stale_branch`, `_stale_base_result`, `_self_mod_auto_merge`, `retire_batch_file`, `run_sit_post_merge`, `_sit_isolate` or `_classify_gate_failure`. The set is those seven functions.
- **AC-CF-08: the gate is green with no new failures against the merge-base baseline.** `pytest -q tests/` at `23ab07f` measures `B passed, 0 failed` (B = 454 expected; report what you measured). After the change it measures `N passed, 0 failed` with `N = B + <number of new tests>`. The set compared is every test file under `tests/`, none excluded. State both counts in the handback.

## 6 · HANDBACK

**§7 first: what you found and LEFT, and why.** Include at least these open questions, answered read-only from logs, git and `state.json`. Do not change anything to answer them:
1. After 02:27:25 on 2026-09-21, was `~/spectricom-clinical-mp` left mid-merge? The next route, `28-date-6-one-day-one-meaning`, branched in the same repo 31 seconds later (`logs/orch-20260921-022756.log:12`). Did it inherit the conflicted index? If you cannot tell from the evidence, say so and do not guess.
2. How was L-UI-SAFETY-1 attempt 2 recorded: `state.json` `completed` or `failed`, and `queue/done/` or `queue/failed/`?
3. Every other run in `logs/orch-*.log` with a `Merge conflict on` line followed by `FINAL STATUS: passed`. The set is the `logs/orch-*.log` files present when you run; list each by filename and line.
4. Anything you noticed in the self-mod or parallel lanes beyond what §4 already names.

Then what shipped, T1–T5, by function name and file:line. Then the gate table:

| | passed | failed | errors |
|---|---|---|---|
| `pytest -q tests/` @ `23ab07f` (baseline) | | | |
| `tests/test_merge_conflict.py` on unmodified code (red) | | | |
| `pytest -q tests/` @ branch tip | | | |

Then **THE CONSEQUENCE (D-S7CORE13-03)**. State each of these plainly, confirmed or corrected against what you shipped:
1. **A conflicted route-lane merge now fails loudly.** FINAL STATUS reads `failed | gate: MERGE CONFLICT — … ; gate was PASS`. `orchestrator.py run` exits 1 instead of 0. The queue daemon therefore moves the brief to `queue/failed/` instead of `queue/done/`, and pauses if `stop_on_failure` is set (`queue_daemon.py:421-427`). `run_queue` halts. `state.json` records it under `failed`. Dependants are not unblocked. Where George used to see `✅ passed`, he will now see `❌ failed`, with the conflicting files named.
2. **The merge target is restored.** A conflicted merge is now aborted, and the repo is left on `MERGE_TARGET` at its pre-merge tip with a clean tree. Before this, it was left mid-merge with conflict markers (see §7 Q1). The route branch is preserved at its tip for manual resolution. Nothing is retired.
3. **Decided inside this brief: the self-mod lane is NOT fixed.** Until ORCH-CONFLICT-2 lands, an orchestrator route whose `--ff-only` auto-merge fails still prints `FINAL STATUS: passed` and exits 0. That is the lane this brief itself runs in. The same applies to the parallel lane until ORCH-CONFLICT-3 (or a ruling that it is dead).
4. **Decided inside this brief: unreadable is never a violation.** If the repo cannot be read at the FINAL STATUS site, the predicate returns `[]` and cannot demote a `passed`. This is `canon_assert`'s existing rule, kept for consistency. If George wants this site to fail closed, it is a one-line change at the T4 call site, not in the predicate.
5. **A visible misread left in place:** a conflict halts `orchestrator.py queue` with `⛔ Queue HALTED (PASS) — N batches skipped` (`orchestrator.py:3793`), because the halt line prints the gate outcome. The FINAL STATUS line just above it is correct.
6. **History is not rewritten.** L-UI-SAFETY-1 attempt 2's `passed` stays in the record. Any canon claim built on it needs a human correction.
